"""Preprocessing: DICOM pixel array -> normalized 512x512 float32 analysis image."""

import numpy as np
from fastapi import HTTPException
from PIL import Image

from app.dicom_io import window_to_uint8


ANALYSIS_SIZE = 512


def preprocess(ds, ww: float, wl: float) -> np.ndarray:
    """Produce the normalized analysis image used by every downstream module.

    Steps follow the System Outline: load pixel array, reduce to grayscale,
    apply rescale + WW/WL, invert MONOCHROME1, resize to 512x512, normalize.
    """
    try:
        pixels = ds.pixel_array
    except Exception as e:
        raise HTTPException(422, f"Cannot read pixel data: {e}")

    photometric = getattr(ds, "PhotometricInterpretation", "MONOCHROME2").strip()

    if photometric in ("RGB", "YBR_FULL", "YBR_FULL_422"):
        p = pixels.astype(float)
        if p.ndim == 3:
            pixels = 0.299 * p[:, :, 0] + 0.587 * p[:, :, 1] + 0.114 * p[:, :, 2]
        else:
            pixels = p.squeeze()
    else:
        if pixels.ndim == 3:
            pixels = pixels[0]
        pixels = pixels.astype(float)
        pixels = pixels * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))

    scaled = window_to_uint8(pixels, ww, wl)

    if photometric == "MONOCHROME1":
        scaled = 255 - scaled

    pil = Image.fromarray(scaled, "L").resize((ANALYSIS_SIZE, ANALYSIS_SIZE), Image.LANCZOS)
    return np.array(pil).astype(np.float32) / 255.0
