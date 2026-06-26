"""DICOM IO: metadata extraction, default WW/WL, and PNG rendering for the viewer."""

import io

import numpy as np
from fastapi import HTTPException
from PIL import Image


def _safe_attr(ds, attr: str) -> str:
    """Read a DICOM attribute as a trimmed string, or '' if absent/unreadable."""
    try:
        v = getattr(ds, attr, "")
        return str(v).strip() if v else ""
    except Exception:
        return ""


def extract_meta(ds) -> dict:
    """Curated, human-readable DICOM header fields for the viewer's metadata panel.

    Only tags that are present and non-empty are returned (see _safe_attr).
    """
    fields = [
        ("PatientName",           "Patient Name"),
        ("PatientID",             "Patient ID"),
        ("PatientBirthDate",      "Birth Date"),
        ("PatientSex",            "Sex"),
        ("Modality",              "Modality"),
        ("StudyDate",             "Study Date"),
        ("StudyDescription",      "Study Description"),
        ("SeriesDescription",     "Series Description"),
        ("InstanceNumber",        "Instance No."),
        ("Rows",                  "Rows"),
        ("Columns",               "Columns"),
        ("PixelSpacing",          "Pixel Spacing"),
        ("SliceThickness",        "Slice Thickness"),
        ("Manufacturer",          "Manufacturer"),
        ("ManufacturerModelName", "Model"),
        ("KVP",                   "kVp"),
    ]
    return {label: v for attr, label in fields if (v := _safe_attr(ds, attr))}


def _scalar(val) -> float | None:
    """Coerce a DICOM value to float, taking the first element of a multi-valued tag."""
    if val is None:
        return None
    try:
        return float(val[0]) if hasattr(val, "__iter__") and not isinstance(val, str) else float(val)
    except Exception:
        return None


def default_wwwl(ds) -> tuple[float, float]:
    """Deterministic display window for the image.

    Uses the stored WindowWidth/WindowCenter when present; otherwise falls back to
    the modality-rescaled pixel min/max (full-range width, midpoint center), and to
    400/40 only if the pixels can't be read. The analysis pipeline normalizes with
    this window, so it must not depend on the live viewer setting.
    """
    ww = _scalar(getattr(ds, "WindowWidth",  None))
    wl = _scalar(getattr(ds, "WindowCenter", None))
    if ww is None or wl is None:
        try:
            px = ds.pixel_array.astype(np.float32)
            px = px * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))
            if ww is None: ww = float(px.max() - px.min())
            if wl is None: wl = float((px.max() + px.min()) / 2)
        except Exception:
            ww = ww or 400.0
            wl = wl or 40.0
    return round(ww, 1), round(wl, 1)


def window_to_uint8(pixels: np.ndarray, ww: float, wl: float) -> np.ndarray:
    """Apply the DICOM VOI LUT (window width/center) and scale to uint8 [0,255].

    Implements the linear VOI LUT of the DICOM standard (PS3.3 C.11.2): clip to
    [wl - ww/2, wl + ww/2] then map linearly to 0..255. Runs AFTER the modality
    LUT (RescaleSlope/Intercept, applied in rescale_mono). Shared by the viewer
    render (``dicom_to_png``) and the analysis preprocessor so both apply identical
    windowing. A degenerate window (hi <= lo) maps to all zeros, matching the prior
    behavior in both call sites.
    """
    lo, hi = wl - ww / 2.0, wl + ww / 2.0
    if hi <= lo:
        return np.zeros(pixels.shape, dtype=np.uint8)
    clipped = np.clip(pixels, lo, hi)
    return ((clipped - lo) / (hi - lo) * 255).astype(np.uint8)


def read_pixels(ds) -> tuple[np.ndarray, str]:
    """Raw pixel array + photometric interpretation, with a clean 422 on failure.

    Shared by the viewer render and the analysis preprocessor so both read pixel
    data and detect photometric interpretation the same way.
    """
    try:
        pixels = ds.pixel_array
    except Exception as e:
        raise HTTPException(422, f"Cannot read pixel data: {e}")
    photometric = getattr(ds, "PhotometricInterpretation", "MONOCHROME2").strip()
    return pixels, photometric


def rescale_mono(ds, pixels: np.ndarray) -> np.ndarray:
    """Apply the DICOM modality LUT: stored pixels -> output units via
    RescaleSlope/Intercept (PS3.3 C.11.1). Monochrome plane as float (3-D -> first
    frame). Precedes the VOI/windowing step done in window_to_uint8.
    """
    if pixels.ndim == 3:
        pixels = pixels[0]
    # float32, not float64: halves the transient array for a full-res mammogram
    # (a 6000x4600 mask drops from ~220 MB to ~110 MB), which keeps a small host
    # from OOM-ing on render. The result is windowed down to uint8 next, so the
    # reduced precision never changes the rendered or analyzed output.
    pixels = pixels.astype(np.float32)
    return pixels * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))


def dicom_to_png(ds, ww: float | None, wl: float | None) -> io.BytesIO:
    """Render a DICOM dataset as a PNG byte stream with the given window/level."""
    pixels, photometric = read_pixels(ds)

    if photometric in ("RGB", "YBR_FULL", "YBR_FULL_422"):
        img = Image.fromarray(pixels.astype(np.uint8), "RGB")
    else:
        pixels = rescale_mono(ds, pixels)
        if ww is None or wl is None:
            dw, dl = default_wwwl(ds)
            ww = ww if ww is not None else dw
            wl = wl if wl is not None else dl
        scaled = window_to_uint8(pixels, ww, wl)
        if photometric == "MONOCHROME1":
            scaled = 255 - scaled
        img = Image.fromarray(scaled, "L")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
