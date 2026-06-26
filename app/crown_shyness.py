"""Crown Shyness boundary metrics for each AOI candidate.

Answers: does the AOI respect the surrounding tissue boundary, or does it
pull into adjacent tissue? Feeds the margin classifier directly and contributes
secondary evidence to the pathology classifier.
"""

import numpy as np
from scipy import ndimage


BAND_RADIUS = 6                # pixels — half-width of the transition band around the contour
VISIBILITY_FLOOR = 0.18        # minimum normalized gradient counted as a "visible" edge


def _gradient_magnitude(img: np.ndarray) -> np.ndarray:
    """Plain gradient magnitude via np.gradient (central differences).

    A fallback for standalone use; the pipeline normally passes in the shared
    smoothed (DoG) gradient from app.maps instead.
    """
    gy, gx = np.gradient(img.astype(float))
    return np.sqrt(gx ** 2 + gy ** 2)


def normalize_gradient(grad: np.ndarray, breast_mask: np.ndarray | None) -> np.ndarray:
    """Scale gradient to [0,1] by a robust *breast-interior* ceiling.

    Min–max over the whole image is dominated by the skin/air edge, which is far
    stronger than any internal margin — that single edge would compress every
    real boundary toward zero and make every margin look ill-defined. Using the
    95th percentile of in-breast gradient as the ceiling keeps internal margin
    sharpness on a meaningful scale.

    Two consequences confirmed by rigor testing: (1) the scale is RELATIVE to the
    in-breast gradient distribution, so every gradient metric below measures margin
    *conspicuity vs surrounding tissue*, not absolute steepness -- on a perfectly
    flat synthetic breast even a faint edge normalizes to ~1. (2) Edge case: if the
    breast mask ~= the lesion itself (a crop that is essentially all mass, with no
    surrounding tissue), the 6-px interior erosion deletes the only edge, the 95th
    percentile is 0, and this returns ~all-zeros -- collapsing gradient_sharpness
    to 0. Not reached on real crops (which always have tissue around the mass), but
    worth knowing if the segmenter ever returns a frame-filling mask.
    """
    if breast_mask is not None and breast_mask.any():
        # ignore a rim so the breast-air edge itself is excluded from the scale
        interior = ndimage.binary_erosion(breast_mask.astype(bool),
                                          structure=np.ones((3, 3), int), iterations=6, border_value=0)
        vals = grad[interior] if interior.any() else grad[breast_mask.astype(bool)]
    else:
        vals = grad.ravel()
    ceil = float(np.percentile(vals, 95)) if vals.size else 0.0
    if ceil <= 0:
        # Sparse gradient (e.g. a single smooth boundary): the 95th percentile is
        # zero, so fall back to the peak so the one real edge still scales to ~1.
        ceil = float(vals.max()) if vals.size else 0.0
    if ceil <= 0:
        return np.zeros_like(grad, dtype=float)
    return np.clip(grad / ceil, 0.0, 1.0)


def _ring_masks(component: np.ndarray, radius: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Three thin bands around the AOI contour: inner, outer, full transition band."""
    structure = np.ones((3, 3), dtype=int)
    inner = component & ~ndimage.binary_erosion(component, structure=structure, iterations=radius, border_value=0)
    dilated = ndimage.binary_dilation(component, structure=structure, iterations=radius, border_value=0)
    outer = dilated & ~component
    band = inner | outer
    return inner.astype(bool), outer.astype(bool), band.astype(bool)


def _halo_widths(component: np.ndarray, img: np.ndarray, ray_count: int = 64, max_distance: int = 24) -> np.ndarray:
    """Estimate the transition-band width along radial rays from the centroid."""
    ys, xs = np.where(component)
    if ys.size == 0:
        return np.zeros(ray_count, dtype=float)
    cy, cx = float(ys.mean()), float(xs.mean())
    h, w = img.shape

    widths: list[float] = []
    angles = np.linspace(0.0, 2 * np.pi, ray_count, endpoint=False)
    for theta in angles:
        dx, dy = np.cos(theta), np.sin(theta)
        last_inside = 0
        for r in range(1, max_distance + max_distance):
            x = int(round(cx + dx * r))
            y = int(round(cy + dy * r))
            if not (0 <= x < w and 0 <= y < h):
                break
            if component[y, x]:
                last_inside = r
            else:
                if last_inside == 0:
                    continue
                # Walk outward until the local intensity stabilizes (reaches the background).
                start_val = float(img[y, x])
                width = 1
                for k in range(1, max_distance):
                    x2 = int(round(cx + dx * (r + k)))
                    y2 = int(round(cy + dy * (r + k)))
                    if not (0 <= x2 < w and 0 <= y2 < h):
                        break
                    if abs(float(img[y2, x2]) - start_val) < 0.02:
                        width = k + 1
                        break
                    width = k + 1
                widths.append(float(width))
                break
        else:
            widths.append(0.0)
    return np.asarray(widths, dtype=float)


def compute_css(lesion: dict, img: np.ndarray,
                breast_mask: np.ndarray | None = None,
                gradient: np.ndarray | None = None,
                grad_norm: np.ndarray | None = None) -> dict:
    """Crown Shyness metrics for one AOI candidate.

    ``grad_norm`` is the normalized gradient; it depends only on the per-image
    ``gradient`` and ``breast_mask``, so the caller can compute it once and pass
    it in to avoid repeating the work for every AOI. When omitted it is derived
    here, preserving the standalone behavior.
    """
    component = lesion["mask"].astype(bool)
    inner, outer, band = _ring_masks(component, BAND_RADIUS)

    if grad_norm is None:
        grad = gradient if gradient is not None else _gradient_magnitude(img)
        grad_norm = normalize_gradient(grad, breast_mask)

    # gradient_sharpness = MEAN normalized gradient over the +/-6px transition band.
    # Rigor-tested caveat (do not read this as "edge steepness"): it is a band-
    # occupancy / conspicuity proxy. Because (a) a razor-sharp 1-2px edge is
    # averaged down across the ~12px-wide band, and (b) normalize_gradient rescales
    # by the in-breast 95th-pct gradient -- which the sharp edge itself raises -- a
    # maximally sharp boundary can score EQUAL OR LOWER than a gentle one (confirmed
    # across three synthetic constructions). It is therefore only a soft cue in
    # classify_margin; transition_zone_entropy and the geometry features
    # (solidity / spike / lobulation) carry most of the actual margin discrimination.
    if band.any():
        gradient_sharpness = float(grad_norm[band].mean())
    else:
        gradient_sharpness = 0.0

    halo_widths = _halo_widths(component, img)
    halo_widths_norm = halo_widths / max(1.0, float(halo_widths.max()) or 1.0)
    halo_width_std = float(halo_widths_norm.std()) if halo_widths.size else 0.0

    if band.any():
        band_vals = img[band]
        hist, _ = np.histogram(band_vals, bins=16, range=(0.0, 1.0))
        total = hist.sum()
        if total > 0:
            probs = hist[hist > 0] / total
            # Shannon (1948) entropy of the transition-band intensity histogram:
            # a clean two-level margin is low-entropy, an infiltrative/heterogeneous
            # one is high. Rigor-tested as the MOST reliable margin discriminator
            # here (clean band 0.25 vs noisy band 0.99).
            entropy = float(-np.sum(probs * np.log2(probs)))
            # Normalize entropy to [0, 1] using log2(bins) as the max.
            entropy_norm = float(min(1.0, entropy / np.log2(16)))
        else:
            entropy_norm = 0.0
    else:
        entropy_norm = 0.0

    contour = lesion["contour"]
    if contour:
        cpts = np.asarray(contour, dtype=int)
        cx_idx = np.clip(cpts[:, 0], 0, img.shape[1] - 1)
        cy_idx = np.clip(cpts[:, 1], 0, img.shape[0] - 1)
        # Fraction of the outline whose normalized gradient clears VISIBILITY_FLOOR:
        # a proxy for the BI-RADS "obscured" margin (a boundary hidden by adjacent
        # tissue reads as low-visibility). Like gradient_sharpness it is relative to
        # the in-breast gradient scale, so it discriminates only weakly on its own.
        gradient_at_contour = grad_norm[cy_idx, cx_idx]
        visibility = float(np.mean(gradient_at_contour >= VISIBILITY_FLOOR))
    else:
        visibility = 0.0

    raw_score = (
        0.40 * gradient_sharpness
        + 0.25 * (1.0 - halo_width_std)
        + 0.20 * (1.0 - entropy_norm)
        + 0.15 * visibility
    )
    raw_score = float(max(0.0, min(1.0, raw_score)))

    if raw_score > 0.65:
        interpretation = "respects_boundary"
    elif raw_score >= 0.40:
        interpretation = "ambiguous"
    else:
        interpretation = "invasive"

    return {
        "raw_score": round(raw_score, 4),
        "interpretation": interpretation,
        "gradient_sharpness": round(gradient_sharpness, 4),
        "halo_width_std": round(halo_width_std, 4),
        "transition_zone_entropy": round(entropy_norm, 4),
        "boundary_visibility_ratio": round(visibility, 4),
    }
