"""Analysis pipeline orchestrator.

Calls preprocess → maps → relevance → AOIs → crown_shyness → classify in order,
then assembles the response payload promised by /api/process/{file_id}. The
pipeline only collects deterministic measurements — there is no explanation
text, external API, or LLM call. The DICOM viewer is untouched; this module
owns the analysis side of the system only.
"""

import numpy as np
from PIL import Image, ImageDraw

from app.classify import classify_margin, classify_pathology, classify_shape
from app.crown_shyness import compute_css
from app.lesions import compute_geometry, extract_lesions
from app.maps import compute_maps
from app.preprocess import ANALYSIS_SIZE, preprocess
from app.relevance import (
    compute_relevance,
    mask_png,
    relevance_png,
    threshold_and_clean,
)


# The input is a zoomed crop centred on one mass, so the generated mask is
# expected to be a large central blob. The quality gate now flags a mask that is
# implausibly *small* (the central object was missed / under-segmented) or one
# that floods almost the whole crop (over-segmented), rather than penalizing a
# large mask as "diffuse". Fractions are of the 512² analysis frame.
MIN_MASS_FRAC = 0.04        # below this the central object is too small to be the cropped mass
MAX_MASS_FRAC = 0.85        # above this the threshold has flooded the crop
LOW_REFERENCE_DICE = 0.20


def _mm2_per_px(ds) -> float | None:
    """Area (mm²) covered by one analysis pixel, accounting for the 512² resize.

    Needs PixelSpacing and the original Rows/Columns; returns None when the DICOM
    does not carry physical spacing (so geometry stays in pixels).
    """
    spacing = getattr(ds, "PixelSpacing", None)
    rows = getattr(ds, "Rows", None)
    cols = getattr(ds, "Columns", None)
    if not spacing or rows is None or cols is None:
        return None
    try:
        row_mm, col_mm = float(spacing[0]), float(spacing[1])
        scale = (row_mm * int(rows) / ANALYSIS_SIZE) * (col_mm * int(cols) / ANALYSIS_SIZE)
        return scale if scale > 0 else None
    except Exception:
        return None


def _rasterize_rois(rois: list[dict] | None, image_w: float, image_h: float) -> np.ndarray | None:
    """Rasterize doctor ROIs (base-image pixel coords) into the 512² analysis grid.

    Returns a boolean mask of the union of all ROIs, or None when there are no
    usable ROIs. Box/ellipse use their drawn shape; freehand uses the traced
    polygon — i.e. the radiologist's own margin.
    """
    if not rois or not image_w or not image_h:
        return None
    sx = ANALYSIS_SIZE / float(image_w)
    sy = ANALYSIS_SIZE / float(image_h)
    canvas = Image.new("L", (ANALYSIS_SIZE, ANALYSIS_SIZE), 0)
    draw = ImageDraw.Draw(canvas)
    drew = False
    for roi in rois:
        kind = roi.get("kind")
        try:
            if kind == "freehand":
                pts = [(float(x) * sx, float(y) * sy) for x, y in roi.get("points", [])]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=255)
                    drew = True
            elif kind in ("rect", "ellipse"):
                x1, y1 = float(roi["x1"]) * sx, float(roi["y1"]) * sy
                x2, y2 = float(roi["x2"]) * sx, float(roi["y2"]) * sy
                box = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
                if box[2] - box[0] >= 1 and box[3] - box[1] >= 1:
                    (draw.ellipse if kind == "ellipse" else draw.rectangle)(box, fill=255)
                    drew = True
        except (KeyError, TypeError, ValueError):
            continue
    if not drew:
        return None
    return np.array(canvas) > 0


NOTE_MAX_LEN = 100  # doctor notes are short free-text, capped server-side too


def _summarize_annotations(rois: list[dict] | None) -> list[dict]:
    """Record the doctor's ROIs (id, kind, finding type, label, note) for the log.

    The note is free text the clinician attached to a mark; it is trimmed to
    ``NOTE_MAX_LEN`` here as a server-side guard even though the UI also limits it.
    Geometry is intentionally not duplicated — these are the human annotations,
    not the measured AOIs.
    """
    if not rois:
        return []
    summary: list[dict] = []
    for i, roi in enumerate(rois, start=1):
        if not isinstance(roi, dict):
            continue
        note = str(roi.get("note") or "").strip()[:NOTE_MAX_LEN]
        label = str(roi.get("label") or "").strip()[:NOTE_MAX_LEN]
        summary.append({
            "id": str(roi.get("id") or f"A{i}"),
            "kind": roi.get("kind"),
            "type": roi.get("type") or roi.get("label") or "Other",
            "label": label,
            "note": note,
        })
    return summary


def _downsample_outline(contour: list, max_points: int = 96) -> list[list[int]]:
    """Downsample a dense contour to at most `max_points` evenly-spaced vertices."""
    if not contour:
        return []
    if len(contour) <= max_points:
        return [[int(x), int(y)] for x, y in contour]
    step = len(contour) / max_points
    return [[int(contour[int(i * step)][0]), int(contour[int(i * step)][1])] for i in range(max_points)]


def _no_lesion_profile(image_label: str, analysis_quality: dict | None = None) -> dict:
    analysis_quality = analysis_quality or {"localization_quality": "acceptable_heuristic", "quality_flags": []}
    return {
        "image_label": image_label,
        "is_there_a_lesion": "No",
        "is_there_an_aoi": "No",
        "lesion_count": 0,
        "aoi_count": 0,
        "lesion_shape": "N/A",
        "aoi_shape": "N/A",
        "lesion_margin": "N/A",
        "aoi_margin": "N/A",
        "pathology": "N/A",
        "confidence": 1.0,
        "pathology_source": "not_available",
        "localization_quality": analysis_quality["localization_quality"],
        "quality_flags": analysis_quality["quality_flags"],
        "lesions": [],
        "aois": [],
    }


def _rank_lesion(lesion: dict) -> tuple:
    """Risk ranking used to pick the image-level fields among multiple AOIs."""
    margin = lesion["margin"]
    shape = lesion["shape"]
    pathology = lesion["pathology"]
    css_score = lesion["crown_shyness"]["raw_score"]

    pathology_score = 1 if pathology == "malignant" else 0
    spiculated_margins = {"SPICULATED", "ILL_DEFINED-SPICULATED", "MICROLOBULATED-ILL_DEFINED-SPICULATED"}
    margin_score = 1 if margin in spiculated_margins else 0
    shape_score = 2 if shape == "Architectural_Distortion" else (1 if shape == "Irregular" else 0)

    # Sort descending: larger tuple wins. CSS is inverted (lower = riskier).
    return (pathology_score, margin_score, shape_score, -css_score)


# A reference mask whose foreground covers less than this fraction of its own
# frame is a whole-mammogram mask (the lesion is a speck in a full breast); it
# must be cropped to the lesion to line up with the zoomed image crop.
WHOLE_MAMMOGRAM_FG_FRAC = 0.15


def _resize_mask_to_analysis(mask_pixels: np.ndarray,
                             image_shape: tuple[int, int] | None = None) -> np.ndarray:
    """Align a reference mask DICOM to the 512² analysis space of the zoomed crop.

    The analysis image is a ROI crop centred on the mass, stretched to 512²
    (``preprocess`` ignores aspect ratio). A reference mask comes in one of two
    forms:

    * **already cropped** (foreground fills much of its frame) — just resize it;
    * **whole-mammogram** (the lesion is a tiny off-centre blob, as the bundled
      demo masks are) — crop to the lesion's bounding box and re-centre it in a
      frame shaped like the *image crop* (``image_shape`` = original Rows×Columns),
      so it undergoes the same stretch and Dice/IoU compare the same mass the
      zoomed image shows rather than a speck in an empty field.
    """
    if mask_pixels.ndim == 3:
        mask_pixels = mask_pixels[0]
    fg = mask_pixels > 0
    if not fg.any():
        return np.zeros((ANALYSIS_SIZE, ANALYSIS_SIZE), dtype=np.uint8)

    if float(fg.mean()) < WHOLE_MAMMOGRAM_FG_FRAC:
        ys, xs = np.where(fg)
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        crop = (fg[y0:y1, x0:x1].astype(np.uint8)) * 255
        ch, cw = crop.shape
        # Frame matched to the image crop's geometry; the ROI crop is the lesion
        # bounding box plus padding, so embed the bbox centred in that frame. Fall
        # back to a square frame with ~30% padding when the image size is unknown.
        if image_shape and image_shape[0] and image_shape[1]:
            fh, fw = int(image_shape[0]), int(image_shape[1])
        else:
            fh = fw = int(round(max(ch, cw) * 1.30))
        scale = min(fh / ch, fw / cw, 1.0)
        nh, nw = max(1, int(ch * scale)), max(1, int(cw * scale))
        if (nh, nw) != (ch, cw):
            crop = np.array(Image.fromarray(crop).resize((nw, nh), Image.NEAREST))
        frame = np.zeros((fh, fw), dtype=np.uint8)
        oy, ox = (fh - nh) // 2, (fw - nw) // 2
        frame[oy:oy + nh, ox:ox + nw] = crop
        binary = frame
    else:
        binary = fg.astype(np.uint8) * 255

    pil = Image.fromarray(binary, "L").resize((ANALYSIS_SIZE, ANALYSIS_SIZE), Image.NEAREST)
    return (np.array(pil) > 0).astype(np.uint8)


def _mask_comparison(pred: np.ndarray, truth: np.ndarray) -> dict:
    pred_bool = pred.astype(bool)
    truth_bool = truth.astype(bool)
    intersection = float(np.logical_and(pred_bool, truth_bool).sum())
    union = float(np.logical_or(pred_bool, truth_bool).sum())
    pred_sum = float(pred_bool.sum())
    truth_sum = float(truth_bool.sum())
    dice = (2.0 * intersection) / (pred_sum + truth_sum) if (pred_sum + truth_sum) > 0 else 0.0
    iou = intersection / union if union > 0 else 0.0
    return {"dice_score": round(dice, 4), "iou_score": round(iou, 4)}


def _localization_quality(generated_mask: dict, mask_comparison: dict | None,
                          roi_guided: bool) -> dict:
    """Quality gates that say how much to trust the localization.

    The cropped mass should be a large central blob, so the honest denominator is
    the generated-mask area as a fraction of the **frame** (``frame_area_fraction
    = area_pct / 100``). A plausible result sits between ``MIN_MASS_FRAC`` and
    ``MAX_MASS_FRAC``; outside that range the central object was missed
    (under-segmented), or the threshold flooded the crop (over-segmented).
    ``roi_guided`` means a clinician bounded the finding, so it is trusted.
    """
    area_pct = float(generated_mask.get("area_pct", 0.0))
    frame_frac = area_pct / 100.0
    flags: list[str] = []

    if mask_comparison and float(mask_comparison.get("dice_score", 1.0)) < LOW_REFERENCE_DICE:
        flags.append("low_reference_mask_overlap")

    if area_pct <= 0.0 or int(generated_mask.get("area_px", 0)) == 0:
        flags.append("no_mass_localized")
        status = "failed_no_mass"
    elif roi_guided:
        status = "clinician_guided"
    elif frame_frac > MAX_MASS_FRAC:
        flags.append("over_segmented_mask")
        status = "failed_broad_mask"
    elif frame_frac < MIN_MASS_FRAC:
        flags.append("under_segmented_mask")
        status = "low_confidence_small"
    elif "low_reference_mask_overlap" in flags:
        status = "low_reference_overlap"
    else:
        status = "acceptable_heuristic"

    return {
        "localization_quality": status,
        "quality_flags": flags,
        "roi_guided": roi_guided,
        "frame_area_fraction": round(float(frame_frac), 4),
        "quality_gate_thresholds": {
            "min_mass_frac": MIN_MASS_FRAC,
            "max_mass_frac": MAX_MASS_FRAC,
            "low_reference_dice": LOW_REFERENCE_DICE,
        },
    }


def run_pipeline(
    ds,
    ww: float,
    wl: float,
    image_label: str,
    mask_ds=None,
    pathology_ground_truth: str | None = None,
    rois: list[dict] | None = None,
    image_size: tuple[float, float] | None = None,
) -> dict:
    """Execute the analysis pipeline and return the response payload."""
    img = preprocess(ds, ww, wl)
    map_bundle = compute_maps(img)
    arrays = map_bundle["arrays"]
    pngs = map_bundle["pngs"]
    breast_mask = arrays["breast_mask"]
    gradient = arrays["gradient"]
    mm2_per_px = _mm2_per_px(ds)

    roi_mask = None
    if rois and image_size:
        roi_mask = _rasterize_rois(rois, image_size[0], image_size[1])
    roi_guided = roi_mask is not None and bool(roi_mask.any())

    relevance = compute_relevance(arrays, roi_mask=roi_mask)
    binary_mask, threshold_value, threshold_method = threshold_and_clean(
        relevance, breast_mask, roi_mask=roi_mask
    )

    candidates = extract_lesions(binary_mask)

    response: dict = {
        "maps": pngs,
        "relevance": {
            "png": relevance_png(relevance),
            "threshold": round(float(threshold_value), 4),
            "threshold_method": threshold_method,
        },
        "generated_mask": {
            "size": ANALYSIS_SIZE,
            "area_px": int(binary_mask.sum()),
            "area_pct": round(100.0 * float(binary_mask.sum()) / binary_mask.size, 4),
            "png": mask_png(binary_mask),
        },
        "mask_comparison": None,
    }

    if mask_ds is not None:
        try:
            img_rows = getattr(ds, "Rows", None)
            img_cols = getattr(ds, "Columns", None)
            image_shape = (int(img_rows), int(img_cols)) if img_rows and img_cols else None
            truth = _resize_mask_to_analysis(mask_ds.pixel_array, image_shape)
            response["mask_comparison"] = _mask_comparison(binary_mask, truth)
        except Exception:
            response["mask_comparison"] = None

    analysis_quality = _localization_quality(
        response["generated_mask"], response["mask_comparison"], roi_guided
    )
    response["analysis_quality"] = analysis_quality
    response["doctor_annotations"] = _summarize_annotations(rois)

    if not candidates:
        response["lesion_profile"] = _no_lesion_profile(image_label, analysis_quality)
        return response

    lesions_payload: list[dict] = []
    for candidate in candidates:
        geometry = compute_geometry(candidate, img, mm2_per_px, gradient)
        css = compute_css(candidate, geometry, img, breast_mask, gradient)
        shape_label = classify_shape(geometry)
        margin_label, margin_evidence = classify_margin(geometry, css)
        pathology_label, confidence = classify_pathology(shape_label, margin_label, geometry, css)
        pathology_source = "rule_based_demo"

        lesions_payload.append({
            "lesion_id": candidate["lesion_id"],
            "aoi_id": candidate["lesion_id"],
            "shape": shape_label,
            "margin": margin_label,
            "pathology": pathology_label,
            "confidence": confidence,
            "geometry": geometry,
            "crown_shyness": {k: v for k, v in css.items() if k != "radial_spike_index"},
            "margin_evidence": margin_evidence,
            "pathology_source": pathology_source,
            "outline": _downsample_outline(candidate["contour"]),
        })

    image_level_source = "rule_based_demo"
    if pathology_ground_truth in {"malignant", "benign"}:
        for entry in lesions_payload:
            entry["pathology"] = pathology_ground_truth
            entry["confidence"] = 1.0
            entry["pathology_source"] = "ground_truth"
        image_level_source = "ground_truth"

    top = max(lesions_payload, key=_rank_lesion)
    image_pathology = "malignant" if any(l["pathology"] == "malignant" for l in lesions_payload) else "benign"
    if pathology_ground_truth in {"malignant", "benign"}:
        image_pathology = pathology_ground_truth

    response["lesion_profile"] = {
        "image_label": image_label,
        "is_there_a_lesion": "Yes",
        "is_there_an_aoi": "Yes",
        "lesion_count": len(lesions_payload),
        "aoi_count": len(lesions_payload),
        "lesion_shape": top["shape"],
        "aoi_shape": top["shape"],
        "lesion_margin": top["margin"],
        "aoi_margin": top["margin"],
        "pathology": image_pathology,
        "confidence": top["confidence"],
        "pathology_source": image_level_source,
        "localization_quality": analysis_quality["localization_quality"],
        "quality_flags": analysis_quality["quality_flags"],
        "lesions": lesions_payload,
        "aois": lesions_payload,
    }
    return response
