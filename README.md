# TerraComrad

A DICOM mammogram viewer with doctor ROI annotation and a deterministic
Area-of-Interest (AOI) analysis pipeline. Given a hyper-zoomed mass crop,
the pipeline reproduces the radiologist's mass mask **without any ML** and
reports shape, margin, geometry, and Crown-Shyness metrics. An optional AI
Insights layer can narrate the result via Google Gemini Flash.

> Research / demo prototype — **not a clinical diagnostic tool.**

## Features

- **DICOM viewer** with window-width / window-level controls and standard transforms.
- **ROI annotation** — Box, Ellipse, and Trace tools with optional labels and short notes.
- **Deterministic analysis pipeline** — no ML, no randomness. Segments the dominant
  mass, then measures geometry, margin, and Crown-Shyness; produces a rule-based
  shape / margin / pathology label set.
- **Optional AI Insights** — when a Google Gemini key is configured, the analysis
  screen can send the rendered AOI image plus the measured profile to Gemini in
  a single multimodal call and render a structured narrative report. **Off by
  default**; with no key set, nothing leaves the machine.

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

frontend/            Single-page UI (no build step)
  index.html
  app.js             Viewer, ROI annotation, analysis interactions
  styles.css

backend/
  demos/             Bundled demo DICOM cases (kept in git)
  uploads/           Runtime scratch — DICOMs copied here on demo open / upload
  aoi_logs/          Per-analysis JSON logs

pyproject.toml       uv / pip dependency spec
requirements.txt     Flat pin list (used by Vercel)
uv.lock              uv lockfile (local reproducibility)
.env.example         Template for the optional AI Insights key
.vercelignore        Files excluded from the Vercel build
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

The viewer and analysis pipeline need **no** configuration — they run fully
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

With no key set, `/api/insights/status` reports disabled and the panel shows a
"not configured" message.

## API Reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/upload` | Upload a DICOM file |
| `GET` | `/api/demos` | List the bundled demo cases |
| `GET` | `/api/demo/{name}` | Copy a bundled demo into uploads |
| `GET` | `/api/files/{file_id}/image?ww&wl` | Render a stored DICOM to PNG |
| `POST` | `/api/process/{file_id}?ww&wl` | Run the analysis pipeline (optional JSON body for ROI-guided detection) |
| `GET` | `/api/insights/status` | Whether the AI Insights layer is configured |
| `POST` | `/api/insights/{file_id}` | Generate the AI narrative for an analyzed AOI |

## Workflow

1. **Open** a DICOM image (uploaded or bundled demo).
2. **Annotate** in the viewer — mark Areas of Interest with the Box, Ellipse,
   or Trace tool, each with an optional label and a short note (≤ 100 chars).
3. **Start Analysis** — the pipeline measures every AOI; the panel shows the
   largest AOI's shape, margin, geometry, and Crown-Shyness metrics alongside
   the doctor's annotations.
4. *(optional)* **Generate AI insights** — sends the flattened composite plus
   the compact profile to Gemini and renders a structured narrative report.

## Deployment Notes

- Designed to deploy from the repository root so `app/`, `frontend/`, and
  `backend/` ship together.
- Production start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `backend/demos/` must be included for the bundled demo cases to work.
- `backend/uploads/` and `backend/aoi_logs/` are runtime scratch — not
  persistent storage.
- Set `INSIGHTS_API_KEY` (and any overrides) in the deployment environment to
  enable the AI Insights layer in production.
