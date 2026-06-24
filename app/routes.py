"""HTTP routes — thin glue between requests and the backend services."""

import asyncio
import base64
import binascii
import io
import json
from datetime import datetime, timezone

import pydicom
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.config import settings as insights_settings
from app.dicom_io import default_wwwl, dicom_to_png, extract_meta
from app.insights import InsightsError, InsightsUnavailable, generate_insights
from app.paths import AOI_LOG_DIR
from app.pipeline import run_pipeline
from app.storage import DEMOS, UPLOAD_DIR, safe_filename

router = APIRouter()


def _read_dataset(file_id: str):
    """Locate and parse a DICOM dataset by file_id from disk."""
    safe_name = safe_filename(file_id)
    path = UPLOAD_DIR / safe_name
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return safe_name, pydicom.dcmread(str(path))


def _write_aoi_log(file_id: str, result: dict) -> dict:
    """Persist the full AOI card payload without heavy base64 image fields."""
    AOI_LOG_DIR.mkdir(parents=True, exist_ok=True)
    profile = result.get("lesion_profile") or {}
    aois = profile.get("aois") or []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = safe_filename(file_id).rsplit(".", 1)[0]
    log_name = safe_filename(f"{timestamp}_{stem}_aoi_log.json")
    log_path = AOI_LOG_DIR / log_name

    payload = {
        "created_at": timestamp,
        "image_label": profile.get("image_label") or file_id,
        "source_file_id": file_id,
        "displayed_aoi_id": aois[0].get("aoi_id") if aois else None,
        "aoi_count": profile.get("aoi_count", len(aois)),
        "analysis_quality": result.get("analysis_quality"),
        "doctor_annotations": result.get("doctor_annotations") or [],
        "generated_mask": {
            k: v for k, v in (result.get("generated_mask") or {}).items()
            if k != "png"
        },
        "aoi_profile": {
            "is_there_an_aoi": profile.get("is_there_an_aoi"),
            "aoi_count": profile.get("aoi_count"),
            "aoi_shape": profile.get("aoi_shape"),
            "aoi_margin": profile.get("aoi_margin"),
            "pathology": profile.get("pathology"),
            "pathology_source": profile.get("pathology_source"),
            "confidence": profile.get("confidence"),
            "localization_quality": profile.get("localization_quality"),
            "quality_flags": profile.get("quality_flags"),
        },
        "aois": aois,
    }
    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"file": log_name, "path": str(log_path), "aoi_count": len(aois)}


def _write_insights_log(file_id: str, profile: dict, result: dict) -> None:
    """Persist a generated AI-insights report beside the AOI logs (best-effort)."""
    AOI_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = safe_filename(file_id).rsplit(".", 1)[0]
    log_path = AOI_LOG_DIR / safe_filename(f"{timestamp}_{stem}_insights.json")
    payload = {
        "created_at": timestamp,
        "source_file_id": file_id,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "usage": result.get("usage"),
        "profile": profile,
        "report": result.get("report"),
    }
    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@router.post("/api/upload")
async def upload_dicom(file: UploadFile = File(...)):
    content = await file.read()
    try:
        ds = pydicom.dcmread(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Not a valid DICOM file: {e}")

    safe_name = safe_filename(file.filename or "unnamed.dcm")
    (UPLOAD_DIR / safe_name).write_bytes(content)

    ww, wl = default_wwwl(ds)
    return {"file_id": safe_name, "metadata": extract_meta(ds), "ww": ww, "wl": wl}


@router.get("/api/demos")
async def list_demos():
    return [
        {"id": k, "label": v["label"], "description": v["description"]}
        for k, v in DEMOS.items()
    ]


@router.get("/api/demo/{name}")
async def load_demo(name: str):
    if name not in DEMOS:
        raise HTTPException(404, "Demo not found")
    demo = DEMOS[name]

    for key in ("image", "mask"):
        if not demo[key].is_file():
            raise HTTPException(500, f"Demo file missing: {demo[key]}")

    img_bytes = demo["image"].read_bytes()
    img_name = f"demo_{name}_img.dcm"
    (UPLOAD_DIR / img_name).write_bytes(img_bytes)
    ds_img = pydicom.dcmread(str(demo["image"]))
    ww, wl = default_wwwl(ds_img)

    mask_bytes = demo["mask"].read_bytes()
    mask_name = f"demo_{name}_mask.dcm"
    (UPLOAD_DIR / mask_name).write_bytes(mask_bytes)
    ds_mask = pydicom.dcmread(str(demo["mask"]))
    mww, mwl = default_wwwl(ds_mask)

    return {
        "file_id":      img_name,
        "mask_file_id": mask_name,
        "metadata":     extract_meta(ds_img),
        "ww": ww,  "wl": wl,
        "mask_ww": mww, "mask_wl": mwl,
        "label": demo["label"],
    }


@router.get("/api/files/{file_id}/image")
async def render_image(file_id: str, ww: float | None = None, wl: float | None = None):
    _, ds = _read_dataset(file_id)
    buf = dicom_to_png(ds, ww, wl)
    return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "no-store"})


async def _read_roi_body(request: Request) -> tuple[list[dict] | None, tuple[float, float] | None]:
    """Parse the optional doctor-ROI JSON body sent with an analysis request.

    Body shape: {"rois": [...], "image_width": W, "image_height": H}. ROIs are in
    base-image pixel coordinates (the viewer's natural image space). Absent or
    malformed bodies simply disable ROI guidance.
    """
    try:
        body = await request.json()
    except Exception:
        return None, None
    if not isinstance(body, dict):
        return None, None
    rois = body.get("rois")
    rois = rois if isinstance(rois, list) and rois else None
    try:
        w = float(body.get("image_width")) if body.get("image_width") else None
        h = float(body.get("image_height")) if body.get("image_height") else None
    except (TypeError, ValueError):
        w = h = None
    size = (w, h) if w and h else None
    return rois, size


@router.post("/api/process/{file_id}")
async def process_dicom(request: Request, file_id: str):
    """Run the analysis pipeline. Returns the AOI profile + generated-mask preview.

    The analysis normalizes with the image's own default window, so it does not
    depend on the viewer's WW/WL — the display window is a viewing preference, not
    an analysis input. (Clients may still send ww/wl query params; they're ignored.)
    """
    safe_name, ds = _read_dataset(file_id)
    rois, image_size = await _read_roi_body(request)

    result = await asyncio.to_thread(run_pipeline, ds, safe_name, rois, image_size)
    result["aoi_log"] = _write_aoi_log(safe_name, result)
    return result


@router.get("/api/insights/status")
async def insights_status():
    """Report whether the optional AI-insights layer is usable (never leaks the key)."""
    return {
        "enabled": insights_settings.configured,
        "provider": insights_settings.provider,
        "model": insights_settings.model if insights_settings.configured else None,
        "max_image_mb": insights_settings.max_image_mb,
    }


@router.post("/api/insights/{file_id}")
async def insights(file_id: str, request: Request):
    """Generate an AI narrative for an analyzed AOI via one multimodal Gemini call.

    Body: ``{image_png_b64, profile}`` — the flattened scan+overlay PNG (base64,
    optionally a data URL) and the compact AOI profile built on the analysis screen.
    Returns ``{report, model, provider, usage, cached}``; 503 when the feature is
    not configured.
    """
    if not insights_settings.configured:
        raise HTTPException(
            503,
            "AI insights are not configured. Set INSIGHTS_API_KEY (or GEMINI_API_KEY) in .env.",
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid JSON body")

    image_b64 = str(body.get("image_png_b64") or "")
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    if not image_b64:
        raise HTTPException(400, "Missing image_png_b64")
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "image_png_b64 is not valid base64")

    max_bytes = int(insights_settings.max_image_mb * 1024 * 1024)
    if len(image_bytes) > max_bytes:
        raise HTTPException(413, f"Composite image exceeds {insights_settings.max_image_mb} MB limit")

    try:
        result = await generate_insights(image_bytes, profile)
    except InsightsUnavailable as exc:
        raise HTTPException(503, str(exc))
    except InsightsError as exc:
        raise HTTPException(502, str(exc))

    try:
        _write_insights_log(file_id, profile, result)
    except OSError:
        pass

    result["cached"] = False
    return result
