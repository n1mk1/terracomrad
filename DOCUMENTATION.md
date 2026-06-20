# TerraComrad — System Documentation

_Current build reference. Describes what is actually implemented in the codebase today._

TerraComrad is an explainable DICOM mammogram viewer and Area-of-Interest (AOI)
analysis prototype. It is a **FastAPI** backend serving a **vanilla-JavaScript**
single-page frontend. A clinician can open a DICOM mammogram, annotate it with
region-of-interest tools, and run a deterministic computer-vision pipeline that
measures the dominant AOI.

The analysis input is a **hyper-zoomed ROI crop centred on a single mass**
(CBIS-DDSM style), not a whole-breast mammogram. The pipeline's job is to
reproduce the radiologist's **mass mask** for that crop without any machine
learning — by segmenting the dominant, locally-brighter central object (§7).

> **Research / demonstration prototype only — not a clinical diagnostic tool.**

The core viewer and analysis pipeline are **fully local and deterministic** — no
network calls and no API key required. The single exception is an **optional "AI
Insights" layer** (§14): when a free **Google Gemini Flash** key is configured, the
analysis screen can send the rendered AOI image plus the measured profile to Gemini
in one multimodal call and display a narrative report. It is **OFF by default**; with
no key set, nothing ever leaves the machine.

---

## 1. What it does

1. Web-based DICOM viewer (upload or bundled demo cases).
2. Optional second "mask" DICOM overlay, independently windowed and transformed.
3. Window width / window level (WW/WL) rendering with live sliders + auto reset.
4. Viewer transforms: pan, zoom, rotate, flip, invert, fit, reset, metadata panel.
5. **Doctor ROI annotation** in the viewer — three region tools (Box, Ellipse, Trace).
6. A deterministic backend analysis pipeline (input: a hyper-zoomed mass crop)
   that produces:
   - an internal **mass-likelihood** map and an Otsu-thresholded, centre-selected
     **generated mass mask**,
   - connected-component AOI candidates with geometry features,
   - **Crown Shyness** boundary metrics per AOI,
   - rule-based shape, margin, and pathology/risk labels,
   - a saved JSON log per analysis.
7. An **AOI Panel** that shows the doctor's annotations alongside the
   system-collected measurements for the **largest AOI only**.

---

## 2. The three-window workflow

```
┌──────────────┐    ┌─────────────────────────────┐    ┌──────────────────────┐
│ 1. Upload    │ →  │ 2. Viewer  (the doctor       │ →  │ 3. Analysis screen   │
│   screen     │    │    annotates here, BEFORE    │    │   (maps, overlays,   │
│              │    │    analysis)                 │    │    AOI Panel, table) │
└──────────────┘    └─────────────────────────────┘    └──────────────────────┘
```

1. **Upload screen** — drag/drop a DICOM image (and optionally a mask DICOM), or
   click a bundled demo case. "Proceed" uploads and opens the viewer.
2. **Viewer (second window)** — adjust WW/WL and transforms, then draw ROI
   annotations with the Box / Ellipse / Trace tools. "Start Analysis" runs the
   pipeline.
3. **Analysis screen (third window)** — shows the optional AI Insights panel, the
   scan with toggleable overlays, the AOI Panel, and an image-level results table.

---

## 3. Project layout

```text
app/                    FastAPI backend (analysis owns the server side)
  main.py               App factory + entrypoint  (app.main:app)
  paths.py              Absolute project paths
  routes.py             API endpoints + AOI JSON log writer
  dicom_io.py           Metadata, default WW/WL, PNG rendering for the viewer
  storage.py            Upload dir, demo registry, filename safety
  preprocess.py         DICOM → normalized 512×512 float32 analysis image
  maps.py               Breast mask + gradient map for the geometry/boundary stages
  relevance.py          Mass-likelihood map + Otsu/centre mass-mask segmentation
  lesions.py            Connected-component AOI extraction + geometry features
  crown_shyness.py      Per-AOI boundary metrics ("Crown Shyness")
  classify.py           Rule-based shape / margin / pathology classifiers
  pipeline.py           Orchestrates the analysis and builds the response payload

frontend/
  index.html            Single-page UI (upload, viewer, analysis screen)
  app.js                Viewer, ROI annotation engine, analysis rendering
  styles.css            Layout and visual styling

backend/
  demos/                Bundled demo DICOM cases (image + mask)
  uploads/              Runtime scratch for uploaded/demo-copied DICOMs (gitignored)
  aoi_logs/             One JSON log written per analysis run (gitignored)
```

Deployment uses `app.main:app` (the same command the `Procfile` runs).

---

## 4. Run locally

```powershell
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`. No environment configuration or API key is
required for the viewer and analysis pipeline — everything runs locally.

To enable the optional **AI Insights** panel (§14), copy `.env.example` to `.env`
and set `INSIGHTS_API_KEY` to a free Google Gemini key
(<https://aistudio.google.com/apikey>). Leave it blank to keep the app fully local.

**Dependencies** (`pyproject.toml`): `fastapi`, `uvicorn`, `python-multipart`,
`pydicom`, `numpy`, `Pillow`, `scipy`, and `google-genai` (used only by the optional
AI Insights layer).

---

## 5. API surface

| Method | Path | Purpose | Returns |
|---|---|---|---|
| GET  | `/` | Serve the SPA | `index.html` |
| GET  | `/static/*` | Frontend assets | css/js |
| POST | `/api/upload` | Upload one DICOM (multipart `file`) | `{file_id, metadata, ww, wl}` |
| GET  | `/api/demos` | List bundled demos | `[{id, label, description}]` |
| GET  | `/api/demo/{name}` | Copy a demo (image+mask) into uploads | `{file_id, mask_file_id, metadata, ww, wl, mask_ww, mask_wl, label}` |
| GET  | `/api/files/{file_id}/image?ww&wl` | Render a stored DICOM to PNG | `image/png` (no-store) |
| POST | `/api/process/{file_id}?ww&wl` | Run the analysis pipeline (optional JSON body `{rois, image_width, image_height}` for ROI-guided detection) | analysis payload (§8) |
| GET  | `/api/insights/status` | Whether the optional AI Insights layer is configured | `{enabled, provider, model, max_image_mb}` |
| POST | `/api/insights/{file_id}` | Generate an AI narrative for an analyzed AOI — one multimodal Gemini call (body `{image_png_b64, profile}`) | `{report, model, provider, usage, cached}` or `503` |

Uploaded files are written to `backend/uploads/` under a sanitized filename;
`file_id` is that filename. Demo loading copies the demo image/mask into
`backend/uploads/` so the same render/analyze endpoints work uniformly.

---

## 6. DICOM handling (`dicom_io.py`, `preprocess.py`)

- **Metadata** (`extract_meta`) — pulls a fixed set of patient/study/series tags
  for the viewer's metadata panel and image corners.
- **Default WW/WL** (`default_wwwl`) — uses `WindowWidth`/`WindowCenter` if
  present, otherwise derives them from the rescaled pixel min/max, falling back to
  `400/40`.
- **Viewer rendering** (`dicom_to_png`) — applies `RescaleSlope/Intercept`, the
  requested WW/WL window, `MONOCHROME1` inversion, and RGB/YBR handling, then
  emits a PNG. The frontend re-requests this endpoint whenever WW/WL changes.
- **Analysis preprocessing** (`preprocess`) — grayscale reduction → rescale →
  WW/WL window → `MONOCHROME1` inversion → **resize to 512×512 (LANCZOS)** →
  normalize to `float32 [0,1]`. `ANALYSIS_SIZE = 512` is the canonical analysis
  resolution used by every downstream module.

---

## 7. Analysis pipeline (`pipeline.py` → `run_pipeline`)

Order: **preprocess → maps → relevance → threshold/clean → extract AOIs →
geometry → crown_shyness → classify → aggregate**. Pure measurement, no generated
text.

### 7.1 Breast mask & gradient (`maps.py`)
`maps.py` produces two 512×512 arrays consumed by the downstream geometry /
boundary stages. They do **not** drive segmentation and are not rendered for the
UI:
- **breast_mask** — Otsu split of tissue vs. air, largest component, holes filled;
  bounds the in-breast gradient normalization for Crown Shyness (§7.6).
- **gradient** — Gaussian-smoothed gradient magnitude, shared by the margin and
  Crown-Shyness boundary metrics (§7.5–7.6).

> **The input is always a hyper-zoomed ROI crop centred on one mass**, not a
> whole-breast mammogram (see the bundled demo cases). So the mass is *not* a tiny
> focal outlier to hunt inside a breast — it is the **dominant, roughly centred
> object** that fills a large fraction (~30–60%) of the frame and is *locally
> brighter* than the tissue around it. The segmenter (§7.2–7.3) is built for that
> geometry and runs **directly on the preprocessed image**.

### 7.2 Mass-likelihood map (`relevance.py → compute_relevance`)
A per-pixel **mass likelihood** in `[0,1]`, built directly from the crop from
three signals that match a centred mass:
```
likelihood = (0.5·local_brightness + 0.5·elevation) · centre_prior
```
- **local_brightness** — the smoothed crop intensity (Gaussian σ≈3); a mass core
  is bright.
- **elevation** — how far each pixel rises above a *broad* local background
  (smoothed minus Gaussian σ≈60, clipped at 0): a fast white-top-hat. Bright
  tissue that is merely part of a wide bright field (e.g. a dense region at the
  crop edge) has low elevation and is rejected; a mass that rises above its
  surround scores high. **This is the signal that separates a mass from
  bright-but-flat tissue** — it is what recovers the low-contrast cases.
- **centre_prior** — a smooth radial Gaussian weight (`CENTER_WIDTH = 0.55` of the
  frame, blended at `CENTER_STRENGTH = 0.85`); the crop is padded around the
  finding, so the central object is favoured and corner structures suppressed.
  When the clinician drew an ROI, the prior is centred on the **ROI centroid**.

The outer `BORDER_FRAC = 4%` of the frame is forced to zero (a padded crop never
has the true mass running off the edge). The likelihood map is internal — it
drives segmentation and is no longer returned as an image.

### 7.3 Threshold + mask cleanup (`relevance.py → threshold_and_clean`)
The likelihood is split with **Otsu** and reduced to one clean blob:
- **Unguided** (no ROI): Otsu over the central region, then keep the **connected
  component at the frame centre** (a zoomed crop holds a single mass), fill holes,
  3×3 closing, a small dilation (`GROW_ITERS = 2`) to recover the consistently
  under-segmented rim, and re-select the central component.
- **ROI-guided** (clinician drew an annotation, §10): the search is restricted to
  a dilated neighbourhood of the ROI and Otsu is taken over that region, so a
  subtle finding is still captured where the clinician pointed. If that refinement
  collapses (`< 20%` of the ROI area), it falls back to the **ROI shape itself** —
  the mass is always reported where the clinician marked it.

A result below `MIN_AREA_PX = 256` is reported as **no mass localized**. The
output is the **generated mass mask** (binary 512×512), reported with its pixel
area and percentage of the frame. The threshold method (`mass_otsu`, `roi_otsu`,
or `roi_shape`) is computed internally.

> **Why this works deterministically.** Reliably localizing a subtle mass *inside
> a whole breast* bottom-up is not solvable without learning (it is why
> mammography CAD uses deep nets) — but the input here is already a crop centred on
> the finding, which collapses the task to "segment the dominant central object".
> Local brightness + elevation + a centre prior recovers the radiologist's mask at
> **~0.82 Dice** across the three demo cases; an ROI makes it more reliable still
> by re-centring the search on the clinician's mark.

### 7.4 AOI candidate extraction (`lesions.py → extract_lesions`)
8-connected (`3×3`) connected components. Each component stores area, bbox,
centroid, traced contour, and sub-mask. **Components are sorted by area
descending and labeled `aoi_1`, `aoi_2`, … — so `aoi_1` is always the largest.**

### 7.5 Geometry features (`lesions.py → compute_geometry`)
The outline is traced with **Moore-neighbour boundary tracing + Jacob's stopping
criterion** (each boundary pixel once), and the perimeter uses the
**Vossepoel–Smeulders** digital-length correction — so `circularity` is finally
meaningful (digital disk → ~1.0, square → ~0.785; earlier builds collapsed every
non-circular shape to ~0.01).

Per AOI: `area_px`, `area_pct`, `bbox`, `centroid`, `circularity` (`4πA/P²`,
capped at 1), `eccentricity` (fitted-ellipse), `solidity`
(`area / convex-hull area`), `contour_roughness`,
`lobulation_index` (prominence-based count of broad rounded lobes on a resampled
radial signature — disk → 0), `radial_spike_index` (narrow sharp outward
protrusions — disk → 0), and `spiculation_convergence` (angular **entropy** of
strong gradients in a ring around the mass: spread evenly → 0, radiating spicules
→ 1; sees spicules the segmentation outline may have missed).

### 7.6 Crown Shyness boundary metrics (`crown_shyness.py → compute_css`)
"Does the AOI respect the surrounding tissue boundary, or pull into it?" Computed
over a transition band (`BAND_RADIUS = 6` px) around the contour:
- `gradient_sharpness` — mean normalized gradient in the band.
- `halo_width_std` — variation of the transition-band width sampled along 64
  radial rays.
- `transition_zone_entropy` — Shannon entropy (16 bins) of band intensities,
  normalized to `[0,1]`.
- `boundary_visibility_ratio` — fraction of contour points whose gradient clears
  `VISIBILITY_FLOOR = 0.18`.

The gradient is normalized by a robust **in-breast 95th percentile**, not the
global max — otherwise the single huge skin/air edge would compress every
internal margin toward zero and make everything look ill-defined (an earlier bug:
`sharpness ≈ 0.10` everywhere). Composite score:
```
raw_score = 0.40·sharpness + 0.25·(1 − halo_width_std)
          + 0.20·(1 − entropy) + 0.15·visibility
```
Interpretation: `> 0.65` → **respects_boundary**, `0.40–0.65` → **ambiguous**,
`< 0.40` → **invasive** (a disrupted-boundary pattern; not biological invasion).

### 7.7 Classifiers (`classify.py`)
- **Shape** — thresholds over circularity/eccentricity/solidity/roughness/
  lobulation/spike → `Round`, `Oval`, `Lobulated`, or `Irregular`
  (`Architectural_Distortion` / `Focal_Asymmetric_Density` are reachable when
  optional asymmetry/compactness signals are supplied; they default off today).
- **Margin** — boolean conditions (spiculated, ill-defined, circumscribed,
  microlobulated, obscured) combine into a BI-RADS-style margin label **plus an
  evidence list** of the conditions that fired.
- **Pathology/risk** — weighted rule score from margin/shape/CSS/spikes; `≥ 0.50`
  → `malignant` else `benign`, with a confidence. This is a demo heuristic
  (`pathology_source = "rule_based_demo"`).

### 7.8 Image-level aggregation
The image-level shape/margin come from a **risk-ranked** top candidate
(`_rank_lesion`: pathology → spiculated margin → irregular/AD shape → lower CSS).
Image pathology is malignant if any AOI is malignant.

### 7.9 Quality gates
- **Localization quality** (`analysis_quality`): the honest "how much to trust
  this" signal. The cropped mass should be a large central blob, so it gates on
  the generated mask as a **fraction of the frame**. Statuses: `clinician_guided`
  (an ROI bounded the finding — trusted), `acceptable_heuristic`,
  `low_confidence_small` (mask `< MIN_MASS_FRAC = 4%` → the central object was
  missed / under-segmented), `failed_broad_mask` (mask `> MAX_MASS_FRAC = 85%` →
  the threshold flooded the crop), or `failed_no_mass` (nothing localized). Also
  reports `roi_guided`.

### 7.10 AOI log (`routes.py → _write_aoi_log`)
Every analysis writes a timestamped JSON to `backend/aoi_logs/` containing the
AOI profile and per-AOI records (without the heavy base64 image fields).

---

## 8. `/api/process` response contract

```jsonc
{
  "generated_mask": { "size": 512, "area_px": 87800, "area_pct": 33.49, "png": "<b64>" },
  "analysis_quality": { "localization_quality": "acceptable_heuristic",
                        "quality_flags": [], "roi_guided": false },
  "doctor_annotations": [ { "id": "A1", "kind": "rect", "type": "Mass",
                            "label": "central mass", "note": "follow up in 6 months" } ],
  "lesion_profile": {
    "image_label": "demo_case1_img.dcm",
    "is_there_an_aoi": "Yes", "aoi_count": 1,
    "aoi_shape": "Irregular", "aoi_margin": "ILL_DEFINED-SPICULATED",
    "pathology": "malignant", "confidence": 0.82, "pathology_source": "rule_based_demo",
    "localization_quality": "acceptable_heuristic", "quality_flags": [],
    "aois": [ {
      "aoi_id": "aoi_1",
      "shape": "Irregular", "margin": "ILL_DEFINED-SPICULATED",
      "pathology": "malignant", "confidence": 0.82, "pathology_source": "rule_based_demo",
      "geometry": { "area_px": ..., "area_pct": ..., "bbox": [...], "centroid": [...],
                    "circularity": ..., "eccentricity": ..., "solidity": ...,
                    "contour_roughness": ..., "lobulation_index": ...,
                    "radial_spike_index": ..., "spiculation_convergence": ... },
      "crown_shyness": { "raw_score": ..., "interpretation": "ambiguous",
                         "gradient_sharpness": ..., "halo_width_std": ...,
                         "transition_zone_entropy": ..., "boundary_visibility_ratio": ... },
      "margin_evidence": [ "low gradient sharpness", ... ],
      "outline": [ [x,y], ... ]
    } ]
  },
  "aoi_log": { "file": "...aoi_log.json", "path": "...", "aoi_count": 1 }
}
```

The profile uses `aoi_*` keys (`is_there_an_aoi`, `aoi_count`, `aoi_shape`,
`aoi_margin`, `aois`). **There is no `explanation` field** — that AI layer was
removed.

### Label schema (allowed values emitted by `classify.py`)
- **Shape**: `Round, Oval, Lobulated, Irregular, Architectural_Distortion, Focal_Asymmetric_Density, Lymph_Node, Asymmetric_Breast_Tissue, N/A`.
- **Margin**: `CIRCUMSCRIBED, CIRCUMSCRIBED-ILL_DEFINED, MICROLOBULATED, MICROLOBULATED-ILL_DEFINED-SPICULATED, ILL_DEFINED, ILL_DEFINED-SPICULATED, OBSCURED, OBSCURED-ILL_DEFINED, SPICULATED, N/A`.
- **Pathology**: `malignant, benign, N/A`.

---

## 9. Frontend

### 9.1 Upload screen
Two drop targets (image + optional mask, gated by a toggle), three bundled demo
cards (P_00778 R-MLO, P_00853 R-CC, P_00900 L-MLO — each image + mask), and a
Proceed button.

### 9.2 Viewer / workspace (the second window)
- **Navigation**: Pan and W/L drag modes; wheel zoom; double-click to fit.
- **Transforms**: invert, rotate 90° CW/CCW, flip H/V, fit, reset (independent
  transform state for the base image and the mask overlay).
- **WW/WL**: sliders with live values, an Auto reset, and corner HUD readouts.
- **Mask overlay**: opacity, colour tint, hide/show, and a Base/Mask "editing
  target" selector with a coloured target ring.
- **Metadata** panel (collapsible).
- **ROI annotation** (see §10).

### 9.3 Analysis screen (the third window)
- **AI Insights panel** (left): the optional Gemini-backed narrative report (§14). A
  "Generate AI insights" button flattens the scan + overlay into one PNG, posts it
  with the compact AOI profile, and renders the returned sections (headline, shape,
  margin, risk, BI-RADS suggestion, follow-up, limitations + disclaimer). Shows a
  clear "not configured" note when no key is set.
- **Scan stage** (centre): the rendered scan with a vector overlay canvas.
  Toggles: Generated AOI mask, Bounding boxes, Crown Shyness halo, and **Doctor
  annotations**. The per-AOI vector overlay (halo + bbox) is focused on the
  **largest AOI**.
- **AOI Panel** (right): see §11.
- **Results table** (bottom): image-level summary — label, AOI present, AOI count,
  shape, margin, pathology/risk + confidence.

---

## 10. Doctor ROI annotation (viewer)

The headline interaction: the clinician marks Areas of Interest **before** running
analysis. The annotation engine lives in `frontend/` (`app.js`, `styles.css`),
and the drawn ROIs are now **sent to the backend with the analysis request** (a
JSON body on `POST /api/process`) and used as a **detection prior** (§7.3,
ROI-guided mode) — focusing the pipeline on the region the radiologist marked.
ROIs are sent in base-image pixel coordinates with the image's natural size; the
backend rasterizes them into the 512² analysis grid.

**Three region tools** (research-aligned with how radiologists mark findings):
| Tool | Shape | Typical use |
|---|---|---|
| **Box** | rectangle ROI | fast localisation of a finding |
| **Ellipse** | circle/oval ROI | rounded masses & density |
| **Trace** | freehand polygon | tracing irregular/spiculated margins |

New annotations take a **finding type** from a selector (Mass, Calcification,
Asymmetry, Arch. distortion, Other), each colour-coded. Each annotation also
carries an optional free-text **label** and a short **note** (≤ 100 characters)
the clinician can attach — both are sent with the analysis request and recorded
in the AOI log (`doctor_annotations`).

**Mechanics**
- Annotations are stored in **base-image pixel coordinates** on an SVG overlay
  sized to the image's natural pixels. The overlay shares the base image's CSS
  transform, so ROIs stay pinned to anatomy through pan / zoom / rotate / flip /
  W-L. Screen→image mapping uses `getScreenCTM().inverse()`; strokes use
  `vector-effect="non-scaling-stroke"` to stay crisp at any zoom.
- **Edit**: click a shape or its chip to select; `Del`/`Backspace` removes;
  double-click a chip to add a free-text label; the **📝** button on a chip adds or
  edits the note (capped at 100 chars in the UI and again server-side); `Esc`
  cancels a draw or exits the tool. **Undo** removes the last ROI; **Clear**
  removes all.
- A chips strip under the canvas lists every ROI (colour dot, id, type/label,
  shape glyph, and the note when present). A note is also flagged with a 📝 on the
  on-image label.
- Annotations reset when a new file is opened; they persist across the
  viewer↔analysis switch and are redrawn (dashed, to distinguish from the
  system's solid outlines) on the analysis overlay when the **Doctor annotations**
  toggle is on.

---

## 11. AOI Panel content

The AOI Panel (analysis screen, right rail) shows exactly two sections:

1. **Doctor's annotations** — every ROI the clinician drew, with its id,
   type/label, shape kind, measured bounding size in pixels, and its note (when
   one was attached).
2. **System analysis · largest AOI** — the `aoi_1` card (largest by
   `geometry.area_px`) with:
   - a Risk pill (label + confidence from the demo heuristic),
   - shape and margin,
   - geometry: area (px + %), bbox, centroid, circularity, eccentricity, solidity,
     roughness, lobulation, spikes,
   - Crown Shyness boundary metrics: score + interpretation, sharpness, halo σ,
     entropy, visibility,
   - the margin-evidence list.

Only the largest AOI is detailed here (and highlighted on the scan); the bottom
results table still reports the total AOI count and the image-level summary.

---

## 12. Data, logs, and storage

- `backend/uploads/` — every uploaded or demo-copied DICOM (the `file_id` is the
  sanitized filename). Runtime scratch; gitignored except `.gitkeep`.
- `backend/aoi_logs/` — one timestamped JSON per analysis run. Gitignored.
- `backend/demos/` — the three bundled CBIS-DDSM-style mass cases (image + mask).

---

## 13. Notable design decisions

- **No AI/LLM, by design.** The pipeline only measures; the AOI panel only
  reports measurements and the doctor's own annotations. No prompt, payload, key,
  or network call exists in the app.
- **Largest-AOI focus.** The AOI panel and the per-AOI scan overlay concentrate on
  the single largest AOI (`aoi_1`); multi-AOI "show all" UI was removed.
- **Built for the crop, not the breast.** The input is a hyper-zoomed mass crop,
  so segmentation targets the *dominant central object* (local brightness +
  elevation above a broad background + a centre prior), not a tiny focal outlier
  inside a breast. This is what makes a no-ML mask track the radiologist's at
  ~0.82 Dice across the demo cases.
- **Annotations refine detection.** ROIs drawn in the viewer are sent to the
  backend and re-centre the search on the clinician's mark (ROI-guided mode);
  notes the clinician attaches travel with them into the AOI log.
- **Honest confidence.** When the result is implausible for a cropped mass — too
  small (`low_confidence_small`), flooding the crop (`failed_broad_mask`), nothing
  found (`failed_no_mass`), or low overlap with a reference (`low_reference_overlap`)
  — the quality gate says so rather than asserting a label over a bad mask.
- **Everything is deterministic and local**, suitable for offline research use.

---

## 14. AI Insights Report (implemented — Google Gemini Flash)

> **Status: implemented.** An *optional, environment-gated* layer that is **OFF by
> default**: with no key set there is no network call and the "runs fully local, no
> API key required" guarantee (§4) holds. Setting `INSIGHTS_API_KEY` (or
> `GEMINI_API_KEY`) auto-enables it. Built across `app/config.py`, `app/insights.py`,
> and `app/routes.py` (`GET /api/insights/status`, `POST /api/insights/{file_id}`),
> plus the analysis screen's left **AI Insights** panel. The provider is **Google
> Gemini Flash** (`gemini-2.5-flash` by default) via the `google-genai` SDK.

### 14.1 Goal & constraints
Package what the analysis screen already has — the curated AOI Panel metrics (§11)
**plus** a flattened *DICOM-render + generated-mask + outlines/bboxes + doctor-ROI*
image — send it to a **free multimodal model in a single request**, and render the
returned narrative report.

Two constraints drive every decision below:
- **One multimodal call** — the image and the structured JSON travel in the *same*
  message; no multi-turn, no separate vision/text calls (token economy).
- **The provider key stays server-side.** A key in `frontend/app.js` would be
  world-readable, so the request is proxied through a new FastAPI route; the
  browser never talks to the provider directly.

### 14.2 Data flow
```text
ANALYSIS SCREEN (browser)
 ├─ scanCanvas      (DICOM render, 512²)
 ├─ overlayCanvas   (mask + outlines + bboxes + doctor ROIs, 512²)
 │     └─ composite both → one flattened PNG → base64
 └─ currentAnalysis.lesion_profile → compact JSON ("the package")
            │  POST /api/insights/{file_id}   { image_png_b64, profile }
            ▼
BACKEND  app/insights.py
   build_prompt(profile) + image
        └─ ONE multimodal request ─────────────► free model (e.g. Gemini Flash)
                                                 ◄─ JSON report
   validate / parse → { report, model, usage, cached }
            │  (optional) persist backend/aoi_logs/..._insights.json
            ▼
   FRONTEND renders report panel + disclaimer; caches by analysis hash
```

**Why composite client-side:** the analysis screen already draws the complete
annotated view across `scanCanvas` + `overlayCanvas` (including
`drawDoctorAnnotations`). Flattening those two same-origin canvases with
`toDataURL()` is a few lines and is exactly WYSIWYG. Re-compositing on the backend
with PIL would mean re-implementing every overlay and re-scaling ROI coordinates —
avoid it.

### 14.3 The package sent to the model
A compact, de-duplicated subset of `lesion_profile` (rounded floats, no base64
inside the JSON, no redundant keys), built in the frontend from data it already
holds — **no pipeline re-run**:
```jsonc
{
  "image_label": "P_00778 R MLO",
  "detection": "Yes · compact mass",
  "aoi_count": 3,
  "displayed_aoi": {
    "id": "aoi_1",
    "shape": "Irregular",
    "margin": "ILL_DEFINED-SPICULATED",
    "margin_evidence": ["sharp radial protrusions (spicules)", "low gradient sharpness"],
    "risk": { "label": "malignant", "confidence": 0.72 },
    "geometry": { "area_pct": 3.2, "circularity": 0.42, "eccentricity": 0.61,
                  "solidity": 0.63, "roughness": 0.55, "lobulation": 0.20,
                  "spikes": 0.70, "convergence": 0.66 },
    "crown_shyness": { "score": 0.31, "sharpness": 0.29, "halo_std": 0.40,
                       "entropy": 0.70, "visibility": 0.55 }
  },
  "method_note": "Rule-based explainable demo classifier, not a trained model."
}
```

### 14.4 The single call
**Provider: Google Gemini Flash** via AI Studio — free tier, native multimodal
endpoint (image + text in one request), generous free quotas, and a structured-output
mode. The call uses the official **`google-genai`** SDK with `response_schema` set to
the fixed `InsightReport` model below, so the response is valid JSON without manual
parsing. The model id is config-only (`INSIGHTS_MODEL`, default `gemini-2.5-flash`),
keeping the door open to other Gemini tiers if a paid upgrade is ever needed.

The request carries one message with two parts: (1) the base64 image, (2) a system
framing + the §14.3 package + the requested output schema. Output is requested as
**fixed-schema JSON** so the frontend renders clean sections and `max_output_tokens`
can be capped:
```jsonc
{
  "headline": "…one-line gestalt…",
  "detection_summary": "…",
  "shape_assessment": "…ties the shape label to circularity / solidity / spikes…",
  "margin_assessment": "…interprets the margin label + evidence…",
  "risk_discussion": "…what raises / lowers suspicion here…",
  "birads_suggestion": "e.g. 'BI-RADS 4 — suspicious', with one-line rationale, or N/A",
  "recommended_followup": "…",
  "limitations": "…",
  "disclaimer": "Educational decision-support only; not a diagnosis."
}
```
The prompt must hard-frame: role = *assist a radiologist*; inputs come from a
*rule-based demo*; *never assert a definitive diagnosis*; *return only valid JSON*.

### 14.5 Backend changes

| File | Change |
|---|---|
| `app/config.py` *(new)* | A `Settings` object reading `INSIGHTS_ENABLED`, `INSIGHTS_PROVIDER`, `INSIGHTS_API_KEY` (falls back to `GEMINI_API_KEY`), `INSIGHTS_MODEL`, `INSIGHTS_MAX_IMAGE_MB`, seeded from a project-root `.env` by a tiny built-in parser (no `python-dotenv` dependency). Auto-enables when a key is present. |
| `app/insights.py` *(new)* | `build_prompt(profile)`, the `InsightReport` Pydantic schema, and async `generate_insights(image_bytes, profile)` — one `google-genai` multimodal call (run in a worker thread) returning `{report, model, provider, usage}`. Raises `InsightsUnavailable` / `InsightsError` for the route to map to 503 / 502. |
| `app/routes.py` | `GET /api/insights/status` and `POST /api/insights/{file_id}`: validate `{image_png_b64, profile}` (accepts a data-URL), enforce the size cap (413), return **503** when not configured, call `generate_insights`, and persist `..._insights.json` beside the AOI log. |
| `pyproject.toml` / `uv.lock` | `google-genai` added via `uv add google-genai` (`httpx` ships with it). |

**Caching:** the frontend caches the report on `currentAnalysis._insights` and only
re-calls on an explicit **Regenerate**, so reopening the panel never silently repeats
a call. Each generated report is also persisted to
`backend/aoi_logs/..._insights.json`.

### 14.6 Frontend changes (`index.html`, `app.js`, `styles.css`)
- **Left "AI Insights" panel** added to the analysis grid (now a 3-column layout:
  insights · scan · AOI cards), with a header, an always-visible disclaimer, a
  **Generate AI insights** button, and a body that swaps between empty / loading /
  error / report states.
- `compositeAnalysisImage()` → temp 512² canvas, `drawImage(scanCanvas)` then
  `drawImage(overlayCanvas)`, `toDataURL('image/png')` (PNG keeps spicules legible).
- `buildInsightProfile(currentAnalysis)` → the §14.3 compact JSON (rounded floats).
- **Call + states**: `fetchInsightsStatus()` on load disables the button with a
  "not configured" note when no key is set; `generateInsights()` POSTs, shows a
  spinner, renders the returned sections, and surfaces 503 / errors inline. Bad JSON
  falls back to a headline + raw text from the backend.
- **Disclaimer** is always shown above the report, alongside the model's own
  disclaimer line and a token-usage footer.
- **Client cache** on `currentAnalysis._insights`; the button becomes **Regenerate**,
  and a fresh analysis is required to invalidate it.

### 14.7 Token / cost minimization
- One multimodal message (image + JSON together).
- Downscale / compress the composite (512² already small; JPEG q≈0.85 cuts image
  tokens — verify spicule legibility first).
- Compact JSON (rounded floats, no redundant fields, no embedded base64).
- Cap `max_output_tokens`; bounded fixed schema.
- Cache by hash + explicit Regenerate (no silent repeats).
- Surface the provider `usage` in the UI to watch consumption.

### 14.8 Privacy, safety & compliance — read before shipping
The largest non-code risk:
- **Free AI tiers typically train on submitted data and offer no BAA.** Sending
  real mammograms / DICOM metadata to a free endpoint is a PHI / HIPAA / GDPR
  problem.
- **Mitigation here:** restrict the feature to the **bundled demo / de-identified
  public-dataset images**. Helpfully, the composite is built from `scanCanvas` +
  `overlayCanvas` only — the corner overlays showing Patient Name/ID are HTML
  `<div>`s, *not* on the canvas, so they are **not** transmitted (the raw breast
  image still is).
- **Gate** behind `INSIGHTS_ENABLED` (default off) with a one-time "this sends the
  image to a third-party AI" consent notice; document that production / PHI use
  requires a paid provider with a BAA or an on-prem model.
- **Always-on disclaimer** in both prompt and UI: non-diagnostic, educational
  decision-support only.

### 14.9 Edge cases
- No AOI detected → emit a "no suspicious mass found" report, or disable the button.
- Missing key / `INSIGHTS_ENABLED=false` → 503 with a clear UI message.
- Provider 429 / 5xx / timeout → friendly retry messaging; never hang the UI.
- Non-JSON model output → fall back to a headline + raw text.
- Oversized image → reject above `INSIGHTS_MAX_IMAGE_MB`.

### 14.10 Configuration & API surface

| Env var | Purpose | Default |
| --- | --- | --- |
| `INSIGHTS_API_KEY` | Provider key, server-side only (falls back to `GEMINI_API_KEY`) | _unset_ |
| `INSIGHTS_ENABLED` | Force the feature on/off | auto: on when a key is present |
| `INSIGHTS_PROVIDER` | Provider label | `gemini` |
| `INSIGHTS_MODEL` | Model id | `gemini-2.5-flash` |
| `INSIGHTS_MAX_IMAGE_MB` | Reject larger composites | `4` |

Two endpoints: `GET /api/insights/status` → `{enabled, provider, model, max_image_mb}`;
`POST /api/insights/{file_id}` takes `{image_png_b64, profile}` and returns
`{report, model, provider, usage, cached}` (or `503` when not configured).

### 14.11 Resolved decisions
1. **Provider** — **Gemini Flash** (`gemini-2.5-flash`) via the `google-genai` SDK.
2. **Output format** — **structured JSON sections** via the SDK `response_schema`.
3. **Privacy gate** — **off by default**, auto-enabled only when a key is set, with an
   always-visible disclaimer. Production / PHI use still needs a paid provider with a
   BAA (see §14.8).
4. **Report persistence** — both: persisted to `aoi_logs/..._insights.json` and cached
   in-browser on `currentAnalysis._insights`.

**Possible follow-ups:** unit tests mocking the SDK (prompt builder, JSON parser,
503-without-key path); a backend hash-based cache to dedupe identical requests; a JPEG
quality knob to further cut image tokens.

---

## 15. Disclaimer

TerraComrad is a research and demonstration prototype. Its labels, scores, and
"risk" outputs are heuristic and **must not be used for clinical diagnosis.**
