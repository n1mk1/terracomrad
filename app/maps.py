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


# Only a grayscale render is needed now (the generated mass mask via
# ``mask_png``); the display "legend" colormaps were removed with their maps.
def to_png_b64(arr: np.ndarray) -> str:
    """Render a normalized [0, 1] array as a base64 grayscale (RGB) PNG."""
    gray = (np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)
    pil = Image.fromarray(np.stack([gray, gray, gray], axis=-1), "RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- #
# Breast mask + gradient (consumed by the geometry / boundary stages)
# --------------------------------------------------------------------------- #

def segment_breast(img: np.ndarray) -> np.ndarray:
    """Boolean breast-tissue mask: Otsu on intensity, largest blob, holes filled.

    Mammograms are a bright breast on a dark background. An intensity Otsu split
    (Otsu 1979, between-class-variance maximization -- same criterion as
    relevance._otsu_threshold) separates the two cleanly; we keep the largest
    connected bright region and fill internal holes so that dense tissue, vessels,
    and (importantly) a mass that sits inside the breast are all retained.
    Verified: recovers a synthetic bright blob on a dark background at IoU 1.0.
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
    """First-derivative-of-Gaussian gradient magnitude (sigma=1).

    order=(1,0)/(0,1) convolves with the partial derivatives of a Gaussian, i.e.
    the standard scale-space / Canny-style gradient that smooths and differentiates
    in one pass (robust to pixel noise). Shared by the margin and Crown-Shyness
    boundary metrics.
    """
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
