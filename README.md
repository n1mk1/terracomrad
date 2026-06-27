# TerraComrad
TerraComrad connects radiologist and physician judgment with AI-assisted mass analysis.

The system scans each image at scale, segmenting masses, measuring shape and margin features, and scoring boundary characteristics.

Here, algorithmic findings directed by clinicians act as a harness on agentic workflows.

Doctors draw regions of interest based on their workflow: processing patient history, diagnostic context, and implicit expertise that no algorithm can fully replicate yet.

This is a guardrail model: the physician prunes absurdity; AI narrows the search.

This is a concept exploration for educational and informational purposes only and should not be considered medical advice.

Always consult with a qualified healthcare professional for diagnosis and treatment.


A DICOM mammogram viewer with doctor ROI annotation and a deterministic
Area-of-Interest (AOI) analysis pipeline. Given a hyper-zoomed mass crop,
the pipeline reproduces the radiologist's mass mask **without any ML** and
reports shape, margin, geometry, and Crown-Shyness (coined term for boundary optimization) metrics. 
The analysis then sent over to AI model(in this case gemini-2.5-flash) for explanations and insights.

> Research / demo prototype. **Not a clinical diagnostic tool.**

## Features

- **DICOM viewer** with window-width / window-level controls and standard transforms.
- **ROI annotation**: Box, Ellipse, and Trace tools with optional labels and short notes.
- **Deterministic analysis pipeline**: no ML, no randomness. Segments the dominant
  mass, then measures geometry, margin, and Crown-Shyness; produces a rule-based
  shape / margin / pathology label set.
- **AI Insights**: when a Google Gemini key is configured, the analysis
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
4. *(optional)* **Generate AI insights**: sends the flattened composite plus
   the compact profile to Gemini and renders a structured narrative report.

## Deployment

The app is a long-running uvicorn server that needs a **writable local disk**
(it stores opened DICOMs under `backend/uploads/` and analysis logs under
`backend/aoi_logs/`). That suits a container/VM host (Render, Railway, Fly.io,
Cloud Run, or a plain VPS), not a read-only serverless platform.

A `Dockerfile` is included; every host below builds from it. For Render, a
`render.yaml` Blueprint is also included for a one-click, pre-wired deploy.

### Build and run locally

```powershell
docker build -t terracomrad .
docker run --rm -p 8000:8000 terracomrad
# add -e INSIGHTS_API_KEY=... to enable AI Insights
```

Then open <http://127.0.0.1:8000>.

### Deploy to a host

| Host | Steps |
| --- | --- |
| **Render** | New → **Blueprint** → connect the repo → Apply (uses the bundled `render.yaml`, which wires the `/healthz` check and ephemeral 2h-TTL logs). Or New → Web Service → *Docker* runtime for a manual setup. Render injects `$PORT`. |
| **Railway** | New Project → Deploy from repo. The Dockerfile is auto-detected; `$PORT` is injected. |
| **Fly.io** | `fly launch` (detects the Dockerfile) → set the service `internal_port` to `8000`. |

Notes:

- `backend/demos/` ships in the image so the bundled demo cases work.
- `backend/uploads/` and `backend/aoi_logs/` are **ephemeral scratch**: fine
  for demos, but they reset on every redeploy and are not backed by a disk. The
  bundled `render.yaml` keeps them ephemeral on purpose and sets
  `SCRATCH_TTL_HOURS=2`, so files are pruned ~2h after upload and a long-lived
  instance can't fill its disk. To retain research logs across redeploys, mount
  a disk at `backend/aoi_logs/` and set `SCRATCH_TTL_HOURS=0`. Each upload gets a
  unique on-disk name (no cross-user collisions).
- The AI-insights endpoint is rate-limited per IP (`INSIGHTS_RATE_LIMIT_PER_MIN`)
  to protect a configured key's quota/billing. Behind a proxy the limiter reads
  `X-Forwarded-For`; with multiple workers the limit is per-worker.
- Interactive API docs (`/docs`) are **off by default**; set `ENABLE_DOCS=true`
  to expose them (handy for local development).
- The `render.yaml` Blueprint sets `autoDeploy: false` (a demo redeploys on
  demand, not on every push), so trigger a manual deploy from the Render
  dashboard after you push changes.
- Set `INSIGHTS_API_KEY` (and any overrides) as environment variables in the
  host's dashboard to enable the AI Insights layer; never bake the key into the
  image (`.env` is excluded from the build context).
