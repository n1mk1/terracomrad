"""Breast mask + gradient map for the geometry / boundary stages, plus the
shared ``to_png_b64`` helper used to render the generated mass mask.

Both maps are 512x512 arrays derived from the preprocessed analysis image:

* **breast_mask** — boolean tissue mask (Otsu, largest component, holes filled),
  used to normalize the Crown-Shyness gradient *inside* the breast.
* **gradient** — Gaussian-smoothed gradient magnitude, shared by the margin and
  Crown-Shyness boundary metrics.

The mass segmenter does not consume these: it runs directly on the preprocessed
image (see ``relevance.compute_relevance``). Earlier builds also produced four
display "legend" maps (intensity/roughness/edges/density); those were
display-only and have been removed.
"""

import base64
import io

import numpy as np
from PIL import Image
from scipy import ndimage


_CMAPS: dict[str, np.ndarray] = {
    "viridis": np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], dtype=np.uint8),
    "plasma":  np.array([[13, 8, 135], [126, 3, 168], [204, 71, 120], [248, 149, 64], [240, 249, 33]], dtype=np.uint8),
    "inferno": np.array([[0, 0, 4], [66, 10, 104], [172, 44, 58], [252, 165, 60], [252, 255, 164]], dtype=np.uint8),
    "magma":   np.array([[0, 0, 4], [80, 18, 123], [183, 55, 121], [251, 136, 97], [252, 253, 191]], dtype=np.uint8),
    "gray":    np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8),
}


def _apply_cmap(arr: np.ndarray, name: str) -> np.ndarray:
    colors = _CMAPS.get(name, _CMAPS["gray"]).astype(float)
    n = len(colors)
    idx = np.clip(arr * (n - 1), 0, n - 1)
    lo = np.clip(idx.astype(int), 0, n - 2)
    hi = lo + 1
    t = (idx - lo)[..., np.newaxis]
    return ((1 - t) * colors[lo] + t * colors[hi]).clip(0, 255).astype(np.uint8)


def to_png_b64(arr: np.ndarray, cmap: str = "gray") -> str:
    """Render a normalized array as a base64 PNG."""
    rgb = _apply_cmap(arr, cmap)
    pil = Image.fromarray(rgb, "RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- #
# Breast mask + gradient (consumed by the geometry / boundary stages)
# --------------------------------------------------------------------------- #

def segment_breast(img: np.ndarray) -> np.ndarray:
    """Boolean breast-tissue mask: Otsu on intensity, largest blob, holes filled.

    Mammograms are a bright breast on a dark background. An intensity Otsu split
    separates the two cleanly; we keep the largest connected bright region and
    fill internal holes so that dense tissue, vessels, and (importantly) a mass
    that sits inside the breast are all retained.
    """
    flat = img.ravel()
    hist, edges = np.histogram(flat, bins=256, range=(0.0, 1.0))
    total = hist.sum()
    if total == 0:
        return np.ones_like(img, dtype=bool)
    centers = 0.5 * (edges[:-1] + edges[1:])
    w1 = np.cumsum(hist)
    w2 = total - w1
    cum_mean = np.cumsum(hist * centers)
    mean_total = cum_mean[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        m1 = np.where(w1 > 0, cum_mean / np.maximum(w1, 1), 0.0)
        m2 = np.where(w2 > 0, (mean_total - cum_mean) / np.maximum(w2, 1), 0.0)
    variance = w1 * w2 * (m1 - m2) ** 2
    thr = float(centers[int(np.argmax(variance))])

    breast = img > thr
    breast = ndimage.binary_fill_holes(breast)
    labeled, n = ndimage.label(breast)
    if n > 1:
        sizes = ndimage.sum(breast, labeled, index=np.arange(1, n + 1))
        breast = labeled == (1 + int(np.argmax(sizes)))
    elif n == 0:
        return np.ones_like(img, dtype=bool)
    return breast.astype(bool)


def gradient_magnitude(img: np.ndarray) -> np.ndarray:
    """Gaussian-smoothed gradient magnitude (shared by margin/boundary metrics)."""
    img = img.astype(float)
    gy = ndimage.gaussian_filter(img, 1.0, order=(1, 0))
    gx = ndimage.gaussian_filter(img, 1.0, order=(0, 1))
    return np.sqrt(gx ** 2 + gy ** 2)


def compute_maps(img: np.ndarray) -> dict:
    """Build the breast mask and gradient map consumed by the geometry /
    Crown-Shyness stages.

    Returns float32 [0,1] 512x512 arrays: the normalized analysis ``image`` (the
    segmenter works on this directly), the ``gradient`` map, and the boolean
    ``breast_mask``.
    """
    img = img.astype(float)
    return {
        # The normalized analysis image itself — the mass-crop segmenter works on
        # this directly (local brightness + elevation above a broad background).
        "image":       img.astype(np.float32),
        # Gradient magnitude — shared by the margin / Crown-Shyness boundary metrics.
        "gradient":    gradient_magnitude(img).astype(np.float32),
        "breast_mask": segment_breast(img),
    }
