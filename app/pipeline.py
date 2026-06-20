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
from app.crown_shyness import compute_css, normalize_gradient
from app.lesions import compute_geometry, extract_lesions
from app.maps import compute_maps
from app.preprocess import ANALYSIS_SIZE, preprocess
from app.relevance import compute_relevance, mask_png, threshold_and_clean


# The input is a zoomed crop centred on one mass, so the generated mask is
# expected to be a large central blob. The quality gate flags a mask that is
# implausibly *small* (the central object was missed / under-segmented) or one
# that floods almost the whole crop (over-segmented). Fractions are of the 512²
# analysis frame.
MIN_MASS_FRAC = 0.04        # below this the central object is too small to be the cropped mass
MAX_MASS_FRAC = 0.85        # above this the threshold has flooded the crop


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
        "is_there_an_aoi": "No",
        "aoi_count": 0,
        "aoi_shape": "N/A",
        "aoi_margin": "N/A",
        "pathology": "N/A",
        "confidence": 1.0,
        "pathology_source": "not_available",
        "localization_quality": analysis_quality["localization_quality"],
        "quality_flags": analysis_quality["quality_flags"],
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


def _localization_quality(generated_mask: dict, roi_guided: bool) -> dict:
    """Quality gate that says how much to trust the localization.

    The cropped mass should be a large central blob, so the gate keys on the
    generated-mask area as a fraction of the **frame**. A plausible result sits
    between ``MIN_MASS_FRAC`` and ``MAX_MASS_FRAC``; outside that range the central
    object was missed (under-segmented), or the threshold flooded the crop
    (over-segmented). ``roi_guided`` means a clinician bounded the finding, so it
    is trusted.
    """
    area_pct = float(generated_mask.get("area_pct", 0.0))
    frame_frac = area_pct / 100.0
    flags: list[str] = []

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
    else:
        status = "acceptable_heuristic"

    return {
        "localization_quality": status,
        "quality_flags": flags,
        "roi_guided": roi_guided,
    }


def run_pipeline(
    ds,
    ww: float,
    wl: float,
    image_label: str,
    rois: list[dict] | None = None,
    image_size: tuple[float, float] | None = None,
) -> dict:
    """Execute the analysis pipeline and return the response payload."""
    img = preprocess(ds, ww, wl)
    arrays = compute_maps(img)
    breast_mask = arrays["breast_mask"]
    gradient = arrays["gradient"]

    roi_mask = None
    if rois and image_size:
        roi_mask = _rasterize_rois(rois, image_size[0], image_size[1])
    roi_guided = roi_mask is not None and bool(roi_mask.any())

    relevance = compute_relevance(arrays, roi_mask=roi_mask)
    binary_mask, _threshold, _method = threshold_and_clean(relevance, roi_mask=roi_mask)

    candidates = extract_lesions(binary_mask)

    mass_px = int(binary_mask.sum())
    response: dict = {
        "generated_mask": {
            "size": ANALYSIS_SIZE,
            "area_px": mass_px,
            "area_pct": round(100.0 * mass_px / binary_mask.size, 4),
            "png": mask_png(binary_mask),
        },
    }

    analysis_quality = _localization_quality(response["generated_mask"], roi_guided)
    response["analysis_quality"] = analysis_quality
    response["doctor_annotations"] = _summarize_annotations(rois)

    if not candidates:
        response["lesion_profile"] = _no_lesion_profile(image_label, analysis_quality)
        return response

    lesions_payload: list[dict] = []
    # The normalized gradient depends only on per-image inputs, so compute it
    # once here instead of repeating it inside compute_css for every AOI.
    grad_norm = normalize_gradient(gradient, breast_mask)
    for candidate in candidates:
        geometry = compute_geometry(candidate, img, gradient)
        css = compute_css(candidate, geometry, img, breast_mask, gradient, grad_norm=grad_norm)
        shape_label = classify_shape(geometry)
        margin_label, margin_evidence = classify_margin(geometry, css)
        pathology_label, confidence = classify_pathology(shape_label, margin_label, geometry, css)
        pathology_source = "rule_based_demo"

        lesions_payload.append({
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

    top = max(lesions_payload, key=_rank_lesion)
    image_pathology = "malignant" if any(e["pathology"] == "malignant" for e in lesions_payload) else "benign"

    response["lesion_profile"] = {
        "image_label": image_label,
        "is_there_an_aoi": "Yes",
        "aoi_count": len(lesions_payload),
        "aoi_shape": top["shape"],
        "aoi_margin": top["margin"],
        "pathology": image_pathology,
        "confidence": top["confidence"],
        "pathology_source": "rule_based_demo",
        "localization_quality": analysis_quality["localization_quality"],
        "quality_flags": analysis_quality["quality_flags"],
        "aois": lesions_payload,
    }
    return response
