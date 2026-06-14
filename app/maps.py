"""Spatial maps and lesion-detection feature maps.

Each map is a 512x512 float32 array in [0, 1]. A base64 PNG render is also
returned for the legend panel — analysis itself runs on the float arrays.

Two families of maps live here:

* **Display maps** (intensity, roughness, edges, density) — shown in the legend.
  These describe global appearance and are kept for the UI contract.
* **Detection feature maps** (breast_mask, local_contrast, blob, gradient) —
  *background-suppressed* signals that respond to focal masses rather than to
  the whole breast. The relevance map is built from these, which is what makes
  the detector localize a lesion instead of segmenting the breast.

The detection maps are deliberately insensitive to global brightness: a real
mammographic mass may be no brighter than the breast mean (only brighter than
its *local* surround), so every detection feature measures local distinctness.
"""

import base64
import io

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage


_CMAPS: dict[str, np.ndarray] = {
    "viridis": np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], dtype=np.uint8),
    "plasma":  np.array([[13, 8, 135], [126, 3, 168], [204, 71, 120], [248, 149, 64], [240, 249, 33]], dtype=np.uint8),
    "inferno": np.array([[0, 0, 4], [66, 10, 104], [172, 44, 58], [252, 165, 60], [252, 255, 164]], dtype=np.uint8),
    "magma":   np.array([[0, 0, 4], [80, 18, 123], [183, 55, 121], [251, 136, 97], [252, 253, 191]], dtype=np.uint8),
    "gray":    np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8),
}


def _norm01(arr: np.ndarray) -> np.ndarray:
    mn, mx = float(arr.min()), float(arr.max())
    return (arr - mn) / (mx - mn) if mx > mn else np.zeros_like(arr, dtype=float)


def _robust_norm01(arr: np.ndarray, mask: np.ndarray | None = None, pct: float = 99.0) -> np.ndarray:
    """Normalize to [0,1] using a high percentile as the ceiling.

    Using a percentile instead of the raw max stops a single extreme pixel
    (e.g. the skin/air edge) from compressing the rest of the map into nothing.
    When ``mask`` is given the percentile is taken over masked pixels only.
    """
    vals = arr[mask] if mask is not None and mask.any() else arr
    hi = float(np.percentile(vals, pct)) if vals.size else 0.0
    lo = float(vals.min()) if vals.size else 0.0
    if hi <= lo:
        return np.zeros_like(arr, dtype=float)
    return np.clip((arr - lo) / (hi - lo), 0.0, 1.0)


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


def _pil_box_blur(img: np.ndarray, radius: int) -> np.ndarray:
    pil = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "L")
    blurred = pil.filter(ImageFilter.BoxBlur(radius))
    return np.array(blurred).astype(float) / 255.0


def _local_std(img: np.ndarray, window: int = 16) -> np.ndarray:
    """Local std-dev via the Var(X) = E[X²] − E[X]² identity.

    Uses scipy ``uniform_filter`` (float, separable) rather than a uint8 PIL
    blur so the squared term keeps full precision.
    """
    img = img.astype(float)
    mean = ndimage.uniform_filter(img, size=window)
    mean_sq = ndimage.uniform_filter(img * img, size=window)
    return np.sqrt(np.maximum(mean_sq - mean ** 2, 0.0))


def _sobel_edges(img: np.ndarray, percentile: float = 80.0) -> np.ndarray:
    """Sobel magnitude with a percentile floor (bottom values zeroed out)."""
    sx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=float)
    sy = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=float)
    h, w = img.shape
    padded = np.pad(img, ((1, 1), (1, 1)), mode="reflect")
    ex = np.zeros_like(img)
    ey = np.zeros_like(img)
    for i in range(3):
        for j in range(3):
            ex += sx[i, j] * padded[i:i + h, j:j + w]
            ey += sy[i, j] * padded[i:i + h, j:j + w]
    mag = np.sqrt(ex ** 2 + ey ** 2)
    threshold = np.percentile(mag, percentile)
    return np.where(mag >= threshold, mag, 0.0)


# --------------------------------------------------------------------------- #
# Detection feature maps (background-suppressed)
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


def _local_contrast(img: np.ndarray, bg_sigma: float = 24.0, tex_sigma: float = 12.0) -> np.ndarray:
    """How much brighter a pixel is than its local surround, in local-σ units.

    A separable-Gaussian surrogate for a white top-hat: subtract a smooth local
    background then standardize by the local texture scale. The result responds
    to focal bright structures (masses) and is ~0 across uniformly bright tissue,
    so a globally average-brightness mass still stands out.
    """
    img = img.astype(float)
    background = ndimage.gaussian_filter(img, bg_sigma)
    highpass = img - background
    local_var = ndimage.gaussian_filter(highpass * highpass, tex_sigma)
    local_sd = np.sqrt(np.maximum(local_var, 1e-6))
    z = np.maximum(highpass, 0.0) / (local_sd + 1e-6)
    return z


def _dog_blob(img: np.ndarray, scales: tuple[float, ...] = (4.0, 8.0, 16.0), k: float = 1.6) -> np.ndarray:
    """Multiscale Difference-of-Gaussians blob response (bright blobs only).

    Classic deterministic mass detector: a bright compact region produces a
    positive DoG peak at the scale matching its radius. We take the per-pixel
    max positive response across scales so masses of different sizes all score.
    """
    img = img.astype(float)
    response = np.zeros_like(img)
    for sigma in scales:
        dog = ndimage.gaussian_filter(img, sigma) - ndimage.gaussian_filter(img, sigma * k)
        response = np.maximum(response, np.maximum(dog, 0.0) * sigma)  # scale-normalized
    return response


def gradient_magnitude(img: np.ndarray) -> np.ndarray:
    """Gaussian-smoothed gradient magnitude (shared by margin/boundary metrics)."""
    img = img.astype(float)
    gy = ndimage.gaussian_filter(img, 1.0, order=(1, 0))
    gx = ndimage.gaussian_filter(img, 1.0, order=(0, 1))
    return np.sqrt(gx ** 2 + gy ** 2)


def _edge_density(grad: np.ndarray, sigma: float = 8.0) -> np.ndarray:
    """Smoothed gradient magnitude — 'how much boundary structure is nearby'.

    Masses (especially spiculated / ill-defined ones that are not bright blobs)
    are rich in internal and marginal gradients. Blurring the gradient turns
    sparse edge pixels into a coherent regional signal that fills the mass, which
    empirically tracks real annotated masses better than blob brightness alone.
    """
    return ndimage.gaussian_filter(grad, sigma)


def compute_maps(img: np.ndarray) -> dict:
    """Build display maps, detection feature maps, and legend PNG previews.

    Returns a dict with two keys:
      arrays — float32 [0,1] 512x512 arrays. Display: intensity, roughness,
               edges, density. Detection: local_contrast, blob, gradient, plus
               the boolean breast_mask.
      pngs   — base64 PNG strings for the four display maps (legend panel).
    """
    img = img.astype(float)
    breast = segment_breast(img)

    # Display maps (global appearance) — kept for the legend.
    intensity = _norm01(img)
    roughness = _norm01(_local_std(img, window=16))
    edges = _norm01(_sobel_edges(img, percentile=80.0))
    density = _norm01(_pil_box_blur(img, radius=20))

    # Detection feature maps (background-suppressed), normalized within the breast.
    gradient = gradient_magnitude(img)
    local_contrast = _robust_norm01(_local_contrast(img), mask=breast, pct=99.0)
    blob = _robust_norm01(_dog_blob(img), mask=breast, pct=99.0)
    edge_density = _robust_norm01(_edge_density(gradient), mask=breast, pct=99.0)

    arrays = {
        # The normalized analysis image itself — the mass-crop segmenter works on
        # this directly (local brightness + elevation above a broad background).
        "image":     img.astype(np.float32),
        "intensity": intensity.astype(np.float32),
        "roughness": roughness.astype(np.float32),
        "edges":     edges.astype(np.float32),
        "density":   density.astype(np.float32),
        "local_contrast": local_contrast.astype(np.float32),
        "blob":      blob.astype(np.float32),
        "edge_density": edge_density.astype(np.float32),
        "gradient":  gradient.astype(np.float32),
        "breast_mask": breast,
    }
    pngs = {
        "intensity": to_png_b64(intensity, "viridis"),
        "roughness": to_png_b64(roughness, "plasma"),
        "edges":     to_png_b64(edges, "gray"),
        "density":   to_png_b64(density, "inferno"),
    }
    return {"arrays": arrays, "pngs": pngs}