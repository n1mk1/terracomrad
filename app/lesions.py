"""Area-of-interest candidates: connected components, contours, geometry."""

import numpy as np
from scipy import ndimage


# Clockwise 8-neighbour offsets, index 0..7 (E, SE, S, SW, W, NW, N, NE).
_CW_OFFSETS = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]


def _trace_contour(mask: np.ndarray) -> list[list[int]]:
    """Ordered outer contour of a binary component via Moore-neighbour tracing.

    Traces the boundary of the *filled* component (not a pre-eroded ring) with
    Jacob's stopping criterion: stop when the start pixel is re-entered from the
    same direction. This yields each boundary pixel once, in order — unlike a
    naive ring walk, which revisits pixels on straight edges and massively
    inflates the perimeter. Returns a list of [x, y] pairs.
    """
    m = mask.astype(bool)
    h, w = m.shape
    ys, xs = np.where(m)
    if ys.size == 0:
        return []

    sy, sx = int(ys[0]), int(xs[0])  # raster-first pixel: top row, leftmost

    def is_fg(y: int, x: int) -> bool:
        return 0 <= y < h and 0 <= x < w and m[y, x]

    contour: list[list[int]] = [[sx, sy]]
    cy, cx = sy, sx
    backtrack = 4  # we reached the start coming from the West (background)
    first_step = None
    max_steps = 8 * int(m.sum()) + 16

    for _ in range(max_steps):
        found = False
        for j in range(8):
            d = (backtrack + 1 + j) % 8
            dy, dx = _CW_OFFSETS[d]
            ny, nx = cy + dy, cx + dx
            if is_fg(ny, nx):
                backtrack = (d + 4) % 8  # direction from the new pixel back to here
                cy, cx = ny, nx
                contour.append([cx, cy])
                found = True
                break
        if not found:
            break  # isolated pixel
        step = (cy, cx)
        if first_step is None:
            first_step = step
        elif (cy, cx) == (sy, sx) and step == first_step:
            contour.pop()  # drop the duplicated start
            break
        elif (cy, cx) == (sy, sx):
            break

    return contour


def _perimeter(contour: list[list[int]]) -> float:
    """Digital perimeter with the Vossepoel–Smeulders correction.

    Naively summing step lengths over-estimates the true boundary length of a
    smooth curve (staircase effect). Weighting orthogonal vs diagonal steps by
    0.948 and 1.340 recovers an accurate estimate, so circularity is meaningful
    (digital disk -> ~1.0, square -> ~0.785).
    """
    if len(contour) < 2:
        return 0.0
    pts = np.asarray(contour, dtype=float)
    diffs = np.diff(np.vstack([pts, pts[0]]), axis=0)  # close the loop
    steplen = np.abs(diffs).sum(axis=1)
    n_ortho = int(np.sum(np.isclose(steplen, 1.0)))
    n_diag = int(np.sum(np.isclose(steplen, 2.0)))
    other = float(np.sum(np.sqrt((diffs[~np.isclose(steplen, 1.0) & ~np.isclose(steplen, 2.0)] ** 2).sum(axis=1))))
    return 0.948 * n_ortho + 1.340 * n_diag + other


def _convex_hull_area(points: np.ndarray) -> float:
    """Monotone-chain convex hull area for an Nx2 array of (x, y) integer-ish points."""
    if points.shape[0] < 3:
        return float(points.shape[0])
    pts = points[np.lexsort((points[:, 1], points[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[np.ndarray] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[np.ndarray] = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = np.asarray(lower[:-1] + upper[:-1], dtype=float)
    if hull.shape[0] < 3:
        return float(points.shape[0])
    x, y = hull[:, 0], hull[:, 1]
    return float(0.5 * np.abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _ellipse_eccentricity(mask: np.ndarray) -> float:
    """Eccentricity of the fitted ellipse (0 = circle, 1 = degenerate line)."""
    ys, xs = np.where(mask)
    if ys.size < 6:
        return 0.0
    coords = np.vstack([xs - xs.mean(), ys - ys.mean()])
    cov = np.cov(coords)
    eig = np.linalg.eigvalsh(cov)
    eig = np.clip(eig, 0.0, None)
    if eig[1] <= 0:
        return 0.0
    a = float(np.sqrt(eig[1]))
    b = float(np.sqrt(eig[0]))
    if a == 0:
        return 0.0
    return float(np.sqrt(max(0.0, 1.0 - (b ** 2) / (a ** 2))))


def _radial_signature(contour: np.ndarray, centroid: tuple[float, float], n: int = 180) -> np.ndarray:
    """Resample centroid-to-contour distance onto `n` evenly-spaced angles.

    A fixed-length angular signature makes the lobulation/spike measures
    independent of how many boundary pixels the tracer produced, and lets us
    smooth circularly without index gymnastics.
    """
    dx = contour[:, 0] - centroid[0]
    dy = contour[:, 1] - centroid[1]
    r = np.sqrt(dx ** 2 + dy ** 2)
    theta = np.mod(np.arctan2(dy, dx), 2 * np.pi)
    order = np.argsort(theta)
    theta, r = theta[order], r[order]
    grid = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    # np.interp needs the period wrapped so angle 0 interpolates from the last point.
    tt = np.concatenate([theta - 2 * np.pi, theta, theta + 2 * np.pi])
    rr = np.concatenate([r, r, r])
    return np.interp(grid, tt, rr)


def _circular_smooth(sig: np.ndarray, frac: float = 0.12) -> np.ndarray:
    n = sig.size
    win = max(3, int(round(n * frac)) | 1)  # odd
    k = np.ones(win) / win
    pad = np.concatenate([sig[-win:], sig, sig[:win]])
    return np.convolve(pad, k, mode="same")[win:win + n]


def _lobulation_index(sig: np.ndarray) -> float:
    """Count broad, rounded outward lobes on the radial signature.

    A lobe is a prominent local maximum of the smoothed signature (prominence
    measured against the lower of its two flanking valleys). A smooth disk has a
    flat signature and therefore ~0 lobes; a 3–4 lobed mass scores moderate.
    """
    if sig.size < 16:
        return 0.0
    s = _circular_smooth(sig, 0.10)
    mean_r = float(s.mean())
    if mean_r <= 0:
        return 0.0
    n = s.size
    prom_floor = 0.04 * mean_r
    lobes = 0
    for i in range(n):
        if s[i] <= s[(i - 1) % n] or s[i] < s[(i + 1) % n]:
            continue  # not a strict local max
        # walk down to the valley on each side, capture the higher valley
        left = s[i]
        j = i
        for _ in range(n):
            j = (j - 1) % n
            if s[j] > s[i]:
                break
            left = min(left, s[j])
        right = s[i]
        j = i
        for _ in range(n):
            j = (j + 1) % n
            if s[j] > s[i]:
                break
            right = min(right, s[j])
        prominence = s[i] - max(left, right)
        if prominence >= prom_floor:
            lobes += 1
    return float(min(1.0, lobes / 8.0))


def _spike_index(sig: np.ndarray) -> float:
    """Fraction of the outline taken up by sharp, narrow outward protrusions.

    Spicules are narrow high-frequency excursions: the detail signal (signature
    minus a wide smoothing) spikes outward over a small angular span. Broad lobes
    (captured by lobulation) are smoothed away and do not count here. A disk's
    detail is ~0, so it scores ~0.
    """
    if sig.size < 16:
        return 0.0
    base = _circular_smooth(sig, 0.18)
    mean_r = float(sig.mean())
    if mean_r <= 0:
        return 0.0
    detail = (sig - base) / mean_r          # outward excursion as a fraction of radius
    spike_px = detail > 0.12
    if not spike_px.any():
        return 0.0
    # Keep only *narrow* runs (true spicules), reject wide bulges.
    n = sig.size
    max_run = max(2, n // 18)
    spikes = 0
    i = 0
    flags = np.concatenate([spike_px, spike_px[:1]])
    while i < n:
        if flags[i]:
            run = 1
            while run <= n and flags[(i + run) % n] and run <= max_run + 1:
                run += 1
            if run <= max_run:
                spikes += 1
            i += run
        else:
            i += 1
    return float(min(1.0, spikes / 10.0))


def _spiculation_convergence(component: np.ndarray, img: np.ndarray, gradient: np.ndarray | None = None) -> float:
    """Angular concentration of strong gradients in a ring around the AOI.

    Spiculated masses radiate linear structures, so strong gradients in the
    surrounding band cluster at a few angles, leaving gaps; a smooth round mass
    has boundary gradients spread evenly over all angles. We measure this with
    the angular entropy of the strong-gradient energy: high entropy (even) -> ~0,
    low entropy (concentrated into spikes) -> ~1. Uses image intensity, so it can
    see spicules the segmentation outline missed. Returns 0 when the ring is too
    small to estimate an angular distribution reliably.
    """
    ys, xs = np.where(component)
    if ys.size < 64:
        return 0.0
    cy, cx = float(ys.mean()), float(xs.mean())
    ring = ndimage.binary_dilation(component, np.ones((3, 3), int), iterations=8) & ~component
    ry, rx = np.where(ring)
    if gradient is None:
        gy, gx = np.gradient(img.astype(float))
        gmag = np.sqrt(gx ** 2 + gy ** 2)
    else:
        gmag = gradient
    g = gmag[ry, rx]
    strong = g >= np.percentile(g, 75)
    if strong.sum() < 24:        # too few strong pixels to judge concentration
        return 0.0
    angles = np.arctan2(ry[strong] - cy, rx[strong] - cx)
    nbins = 12
    hist, _ = np.histogram(angles, bins=nbins, range=(-np.pi, np.pi), weights=g[strong])
    total = hist.sum()
    if total <= 0:
        return 0.0
    p = hist[hist > 0] / total
    entropy = float(-np.sum(p * np.log(p)) / np.log(nbins))   # normalized [0,1]
    return float(min(1.0, max(0.0, 1.0 - entropy) * 2.2))


def extract_lesions(mask: np.ndarray) -> list[dict]:
    """8-connected components on a binary mask -> ordered AOI candidates.

    Each entry includes the per-component sub-mask in image coordinates, the
    pixel contour, area, bbox and centroid. Geometry features come later via
    compute_geometry().
    """
    if mask.sum() == 0:
        return []

    labeled, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    total_pixels = mask.size

    components: list[dict] = []
    for idx in range(1, n + 1):
        component = (labeled == idx)
        area_px = int(component.sum())
        if area_px == 0:
            continue
        ys, xs = np.where(component)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        centroid = [float(xs.mean()), float(ys.mean())]
        contour = _trace_contour(component)
        components.append({
            "area_px": area_px,
            "area_pct": round(100.0 * area_px / total_pixels, 4),
            "bbox": bbox,
            "centroid": centroid,
            "contour": contour,
            "mask": component,
        })

    # Sort by area, descending, so aoi_1 is the dominant candidate.
    components.sort(key=lambda c: c["area_px"], reverse=True)
    for i, comp in enumerate(components, start=1):
        comp["lesion_id"] = f"aoi_{i}"
    return components


def compute_geometry(lesion: dict, img: np.ndarray, mm2_per_px: float | None = None,
                     gradient: np.ndarray | None = None) -> dict:
    """Per-AOI geometry feature dict used by the shape/margin classifiers."""
    area_px = lesion["area_px"]
    contour = lesion["contour"]
    bbox = lesion["bbox"]
    centroid = lesion["centroid"]
    component = lesion["mask"]

    perimeter = _perimeter(contour)
    circularity = float(4 * np.pi * area_px / (perimeter ** 2)) if perimeter > 0 else 0.0
    circularity = min(circularity, 1.0)

    bbox_area = max(1, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    extent = float(area_px / bbox_area)

    ys, xs = np.where(component)
    hull_area = _convex_hull_area(np.column_stack([xs, ys])) if xs.size >= 3 else float(area_px)
    solidity = float(area_px / hull_area) if hull_area > 0 else 1.0

    eccentricity = _ellipse_eccentricity(component)

    if len(contour) >= 8:
        cpts = np.asarray(contour, dtype=float)
        sig = _radial_signature(cpts, (centroid[0], centroid[1]))
        mean_d = float(sig.mean())
        contour_roughness = min(float(sig.std() / (mean_d + 1e-6)) if mean_d > 0 else 0.0, 1.0)
        lobulation = _lobulation_index(sig)
        outline_spike = _spike_index(sig)
    else:
        contour_roughness, lobulation, outline_spike = 0.0, 0.0, 0.0

    convergence = _spiculation_convergence(component, img, gradient)
    # radial_spike_index stays the clean, outline-based measure (disk -> 0);
    # convergence is reported separately and used as softer margin evidence.
    spike = float(outline_spike)

    geom = {
        "area_px": int(area_px),
        "area_pct": float(lesion["area_pct"]),
        "bbox": [int(v) for v in bbox],
        "centroid": [round(float(centroid[0]), 2), round(float(centroid[1]), 2)],
        "circularity": round(circularity, 4),
        "eccentricity": round(eccentricity, 4),
        "solidity": round(min(max(solidity, 0.0), 1.0), 4),
        "extent": round(min(max(extent, 0.0), 1.0), 4),
        "contour_roughness": round(contour_roughness, 4),
        "lobulation_index": round(lobulation, 4),
        "radial_spike_index": round(spike, 4),
        "spiculation_convergence": round(convergence, 4),
    }
    if mm2_per_px and mm2_per_px > 0:
        area_mm2 = area_px * mm2_per_px
        geom["area_mm2"] = round(area_mm2, 2)
        geom["equiv_diameter_mm"] = round(2.0 * float(np.sqrt(area_mm2 / np.pi)), 2)
    else:
        geom["area_mm2"] = None
        geom["equiv_diameter_mm"] = None
    return geom
