"""DICOM IO: metadata extraction, default WW/WL, and PNG rendering for the viewer."""

import io

import numpy as np
from fastapi import HTTPException
from PIL import Image


def _safe_attr(ds, attr: str) -> str:
    try:
        v = getattr(ds, attr, "")
        return str(v).strip() if v else ""
    except Exception:
        return ""


def extract_meta(ds) -> dict:
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
    if val is None:
        return None
    try:
        return float(val[0]) if hasattr(val, "__iter__") and not isinstance(val, str) else float(val)
    except Exception:
        return None


def default_wwwl(ds) -> tuple[float, float]:
    ww = _scalar(getattr(ds, "WindowWidth",  None))
    wl = _scalar(getattr(ds, "WindowCenter", None))
    if ww is None or wl is None:
        try:
            px = ds.pixel_array.astype(float)
            px = px * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))
            if ww is None: ww = float(px.max() - px.min())
            if wl is None: wl = float((px.max() + px.min()) / 2)
        except Exception:
            ww = ww or 400.0
            wl = wl or 40.0
    return round(ww, 1), round(wl, 1)


def dicom_to_png(ds, ww: float | None, wl: float | None) -> io.BytesIO:
    """Render a DICOM dataset as a PNG byte stream with the given window/level."""
    try:
        pixels = ds.pixel_array
    except Exception as e:
        raise HTTPException(422, f"Cannot read pixel data: {e}")

    photometric = getattr(ds, "PhotometricInterpretation", "MONOCHROME2").strip()

    if photometric in ("RGB", "YBR_FULL", "YBR_FULL_422"):
        img = Image.fromarray(pixels.astype(np.uint8), "RGB")
    else:
        if pixels.ndim == 3:
            pixels = pixels[0]
        pixels = pixels.astype(float)
        pixels = pixels * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))
        if ww is None or wl is None:
            dw, dl = default_wwwl(ds)
            ww = ww if ww is not None else dw
            wl = wl if wl is not None else dl
        lo, hi = wl - ww / 2, wl + ww / 2
        pixels = np.clip(pixels, lo, hi)
        pixels = ((pixels - lo) / (hi - lo) * 255).astype(np.uint8) if hi > lo else np.zeros_like(pixels, dtype=np.uint8)
        if photometric == "MONOCHROME1":
            pixels = 255 - pixels
        img = Image.fromarray(pixels, "L")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
