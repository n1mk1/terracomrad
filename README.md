<img width="1038" height="593" alt="Screenshot 2026-07-01 191225" src="https://github.com/user-attachments/assets/2d06f5c1-b12b-4111-b8d4-18a2b98dc539" />

# TerraComrad
TerraComrad connects radiologist and physician judgment with AI-assisted mass analysis. The system scans each image at scale, segmenting masses, measuring shape and margin features, and scoring boundary characteristics. Here, algorithmic findings directed by clinicians act as a harness on agentic workflows. Doctors draw regions of interest based on their workflow: processing patient history, diagnostic context, and implicit expertise that no algorithm can fully replicate yet. This is a guardrail model: the physician prunes absurdity; AI narrows the search.

A DICOM mammogram viewer with doctor ROI annotation and a deterministic
Area-of-Interest (AOI) analysis pipeline. Given a hyper-zoomed mass crop,
the pipeline reproduces the radiologist's mass mask **without any ML** and
reports shape, margin, geometry, and Crown-Shyness (coined term for boundary optimization) metrics. 
The analysis then sent over to AI model(in this case gemini-2.5-flash) for explanations and insights.

> Research / demo prototype.

## Features

- **DICOM viewer** with window-width / window-level controls and standard transforms.
- **ROI annotation**: Box, Ellipse, and Trace tools with optional labels and short notes.
- **Deterministic analysis pipeline**: no ML, no randomness. Segments the dominant
  mass, then measures geometry, margin, and Crown-Shyness; produces a rule-based
  shape / margin / pathology label set.
- **AI Insights**: when a Google Gemini key is configured, the analysis
  screen can send the rendered AOI image plus the measured profile to Gemini in
  a single multimodal call and render a structured narrative report. **Off by
  default**; with no key set. The deployed web app has its own api key, refer to configuration for local machine setup.

## Project Layout

```text
app/                 FastAPI backend
  main.py            App factory + entrypoint (app.main:app)
  routes.py          HTTP endpoints
  paths.py           Project-relative paths
  storage.py         Demo manifest + upload lookup
  dicom_io.py        DICOM metadata, WW/WL, PNG rendering
  preprocess.py      Image normalization
  pipeline.py        Top-level analysis pipeline
  maps.py            Colormap helpers
  crown_shyness.py   Crown-Shyness metric
  lesions.py         Mass segmentation
  classify.py        Rule-based shape / margin / pathology labels
  relevance.py       Spatial relevance maps
  config.py          Env-driven settings for the AI Insights layer
  insights.py        Gemini multimodal call + response schema
  ratelimit.py       In-process per-IP limiter for the insights endpoint

frontend/            Single-page UI (no build step)
  index.html
  app.js             Viewer, ROI annotation, analysis interactions
  styles.css

backend/
  demos/             Bundled demo DICOM cases (kept in git)
  uploads/           Runtime scratch: DICOMs copied here on demo open / upload
  aoi_logs/          Per-analysis JSON logs

pyproject.toml       uv / pip dependency spec
requirements.txt     Flat pin list (used by the Docker build)
uv.lock              uv lockfile (local reproducibility)
.env.example         Template for the optional AI Insights key
Dockerfile           Container image for production hosts
.dockerignore        Files excluded from the Docker build context
render.yaml          Render Blueprint (one-click deploy spec)
```

## Run Locally

### With `uv` (recommended)

```powershell
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### With `pip`

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000>.

## Configuration

The viewer and analysis pipeline need **no** configuration; they run fully
locally with no network calls.

To enable the optional **AI Insights** panel:

1. Get a free Gemini API key at <https://aistudio.google.com/apikey>.
2. Copy `.env.example` to `.env` and set `INSIGHTS_API_KEY`.
3. Restart the server.

Optional overrides (see `.env.example` for the full list):

| Variable | Default | Purpose |
| --- | --- | --- |
| `INSIGHTS_API_KEY` | _unset_ | Gemini key, server-side only |
| `INSIGHTS_MODEL` | `gemini-2.5-flash` | Model id |
| `INSIGHTS_ENABLED` | auto | Force the feature on/off |
| `INSIGHTS_MAX_IMAGE_MB` | `4` | Reject larger composites |
| `INSIGHTS_RATE_LIMIT_PER_MIN` | `15` | Per-IP cap on AI-insight calls (`0` = unlimited) |
| `MAX_UPLOAD_MB` | `80` | Reject larger DICOM uploads |
| `SCRATCH_TTL_HOURS` | `24` | Auto-delete uploads/logs older than this (`0` = keep forever) |
| `ENABLE_DOCS` | `false` | Expose `/docs`, `/redoc`, `/openapi.json` when true |

With no key set, `/api/insights/status` reports disabled and the panel shows a
"not configured" message.

## API Reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | Liveness probe (`{"ok": true}`) |
| `POST` | `/api/upload` | Upload a DICOM file |
| `GET` | `/api/demo/{name}` | Copy a bundled demo into uploads |
| `GET` | `/api/files/{file_id}/image?ww&wl` | Render a stored DICOM to PNG |
| `POST` | `/api/process/{file_id}?ww&wl` | Run the analysis pipeline (optional JSON body for ROI-guided detection) |
| `GET` | `/api/insights/status` | Whether the AI Insights layer is configured |
| `POST` | `/api/insights/{file_id}` | Generate the AI narrative for an analyzed AOI |

## Workflow

1. **Open** a DICOM image (uploaded or bundled demo).
2. **Annotate** in the viewer: mark Areas of Interest with the Box, Ellipse,
   or Trace tool, each with an optional label and a short note (≤ 100 chars).
3. **Start Analysis**: the pipeline measures every AOI; the panel shows the
   largest AOI's shape, margin, geometry, and Crown-Shyness metrics alongside
   the doctor's annotations.
4. **Generate AI insights**: sends the flattened composite plus
   the compact profile to Gemini and renders a structured narrative report.

### Build and run locally

```powershell
docker build -t terracomrad .
docker run --rm -p 8000:8000 terracomrad
# add -e INSIGHTS_API_KEY=... to enable AI Insights
```
Then open <http://127.0.0.1:8000>.

---
# REPORT
## Data flow

```
DICOM crop
  → preprocess (512² float)
  → breast mask + gradient
  → mass-likelihood map → segment (binary mask)
  → connected components + contour
  → geometry (shape) + Crown-Shyness (boundary)
  → rule-based classification → lesion profile
  → Gemini narrative
```

## Stages

1. **DICOM I/O (`dicom_io.py`).** Decodes pixels, applies the Modality LUT
   (`value = slope·SV + intercept`), then the linear VOI/window LUT, and inverts
   MONOCHROME1. *(DICOM PS3.3 §C.11.1–.2.)*

2. **Preprocess (`preprocess.py`).** Pins the image's own default window rather than the
   live viewer, maps RGB→luma when needed, and Lanczos-resizes to a 512² float image
   in [0,1]. *(ITU-R BT.601; Duchon 1979.)*

3. **Breast mask (`maps.py`).** Otsu threshold maximising between-class variance
   `ω₀·ω₁·(μ₀−μ₁)²`, then the largest bright component with holes filled. *(Otsu 1979.)*

4. **Gradient map (`maps.py`).** First-derivative-of-Gaussian magnitude (σ=1), shared
   by the margin and boundary metrics. *(Canny 1986.)*

5. **Mass-likelihood (`relevance.py`).** Per-pixel score
   `(0.5·intensity + 0.5·elevation)·(0.85·prior + 0.15)`. Elevation is the smoothed
   image minus a broad Gaussian background (a linear top-hat or unsharp mask), and a
   Gaussian centre prior favours the central object. *(Top-hat: Soille 2003.)*

6. **Segment mass (`relevance.py`).** Otsu over the central or ROI-dilated search
   region, keep the central component, then fill, close, and dilate. A ROI-collapse
   fallback applies, and `<256 px ⇒ "no mass"`. *(Otsu 1979.)*

7. **Components + contour (`lesions.py`).** 8-connected labelling, then Moore-neighbour
   boundary tracing with Jacob's stopping criterion so each boundary pixel is visited
   once. *(Gonzalez & Woods.)*

8. **Perimeter + circularity (`lesions.py`).** Kulpa chain-code correction
   `P = 0.948·n_ortho + 1.340·n_diag`, which removes the roughly 5.5% staircase bias,
   then circularity `4πA / P²`. *(Kulpa 1977.)*

9. **Solidity (`lesions.py`).** `A / A_hull`, using the convex hull from Andrew's
   monotone chain and a shoelace area. *(Andrew 1979.)*

10. **Eccentricity (`lesions.py`).** `√(1 − λ_min/λ_max)` from the eigenvalues of the
    pixel second-moment covariance, running from 0 for a circle to 1 for an elongated
    shape. *(Hu 1962.)*

11. **Lobulation / spicules / convergence (`lesions.py`).** From the 180-point
    centroid-to-contour radial signature: broad peaks give lobulation and narrow
    outward excursions give spicules, while the angular entropy of ring gradients
    gives spiculation convergence. *(Rangayyan 1997; Karssemeijer & te Brake 1996.)*

12. **Crown-Shyness boundary (`crown_shyness.py`).** Over a ±6 px band it measures
    gradient sharpness as a soft conspicuity cue, halo-width standard deviation,
    transition-zone Shannon entropy `−Σ pₖ·log₂ pₖ`, and visibility ratio, with
    composite weights `0.40 / 0.25 / 0.20 / 0.15`. The entropy term is the most
    reliable discriminator. *(Shannon 1948.)* ("Crown Shyness" is the project's own
    coinage.)

13. **Classification (`classify.py`).** Conservative rule thresholds map the geometry
    and boundary features to BI-RADS shape labels and compound CBIS-DDSM margin labels.
    An additive malignancy score (`≥0.50 ⇒ malignant`) gives the risk. The thresholds
    are hand-set rather than fitted. *(ACR BI-RADS; Liberman et al. 1998.)*

14. **Orchestration + quality gate (`pipeline.py`).** Runs the chain and gates trust
    through three states: `failed_no_mass`, `clinician_guided`, and `needs_roi`.
    Unguided localisation is never trusted and withholds morphology. ROIs are
    rasterised to the 512² grid by the affine scale `512/W, 512/H`.

15. **AI insights (`insights.py`).** One multimodal Gemini call (overlay PNG plus
    profile JSON) returns a fixed 9-field narrative. It retries on 429/500/503/504, is
    inert without a key, and is explicitly non-diagnostic.

**Supporting modules.** `main.py` (app factory), `routes.py` (endpoints), `config.py`
(insights settings), `storage.py` (uploads, demos, pruning), `ratelimit.py` (per-IP
limiter), `paths.py` (path constants).

## References

1. DICOM PS3.3 §C.11.1 (Modality LUT), §C.11.2 (VOI LUT).
2. Otsu N. "A threshold selection method from gray-level histograms." *IEEE Trans. Syst. Man Cybern.* 9:62–66, 1979. doi:10.1109/TSMC.1979.4310076.
3. ITU-R BT.601. Luma coefficients (0.299, 0.587, 0.114).
4. Kulpa Z. "Area and perimeter measurement of blobs in discrete binary pictures." *Comput. Graph. Image Process.* 6:434–451, 1977.
5. Andrew A.M. "Another efficient algorithm for convex hulls in two dimensions." *Inf. Process. Lett.* 9:216–219, 1979.
6. Hu M.-K. "Visual pattern recognition by moment invariants." *IRE Trans. Inf. Theory* 8(2):179–187, 1962.
7. Rangayyan R.M. et al. Centroid-to-contour radial-signature shape descriptor (generic in-code attribution).
8. Karssemeijer N., te Brake G.M. "Detection of stellate distortions in mammograms." *IEEE Trans. Med. Imaging* 15:611–619, 1996.
9. Shannon C.E. "A mathematical theory of communication." *Bell Syst. Tech. J.* 27:379–423, 1948.
10. ACR BI-RADS mammography lexicon (shape/margin vocabulary and risk direction).
11. Liberman L. et al. "The Breast Imaging Reporting and Data System: positive predictive value of mammographic features and final assessment categories." *AJR Am. J. Roentgenol.* 171(1):35–40, 1998. PMID 9648759.

**Auxiliary**

12. Canny J. "A computational approach to edge detection." *IEEE Trans. Pattern Anal. Mach. Intell.* 8(6):679–698, 1986. The code's gradient is first-derivative-of-Gaussian ("Canny-style"); Marr–Hildreth instead detects Laplacian zero-crossings.
13. Gonzalez R.C., Woods R.E. *Digital Image Processing*. Moore-neighbour boundary tracing.
14. Soille P. *Morphological Image Analysis*, 2nd ed., Springer, 2003. White top-hat and morphology.
15. Duchon C.E. "Lanczos filtering in one and two dimensions." *J. Appl. Meteorol.* 18:1016–1022, 1979. Lanczos resampling.
16. Rangayyan R.M. et al. "Measures of acutance and shape for classification of breast tumors." *IEEE Trans. Med. Imaging* 16(6):799–810, 1997.
17. ACR BI-RADS Atlas, 5th ed., American College of Radiology, 2013.
18. FDA *AI/ML-Based SaMD Action Plan*, 2021.

---

