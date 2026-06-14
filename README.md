# TerraComrad

Explainable DICOM mammogram viewer with doctor ROI annotation and a deterministic
Area-of-Interest analysis pipeline. The analysis input is a hyper-zoomed mass crop
and the pipeline reproduces the radiologist's mass mask without any ML.
Research/demo prototype — not for clinical use.

📄 **Full system documentation:** [`DOCUMENTATION.md`](DOCUMENTATION.md)

## Project Layout

```text
app/
  main.py       FastAPI deployment entrypoint: app.main:app
  paths.py      Absolute project paths for deployment-safe static/data access
  routes.py     API endpoints
  dicom_io.py   DICOM metadata, WW/WL, and PNG rendering
  pipeline.py   Mass-crop segmentation, geometry/margin analysis, response payload
  storage.py    Demo manifest and runtime upload lookup

frontend/
  index.html    Single-page UI
  app.js        Viewer, ROI annotation, and analysis interactions
  styles.css    UI layout and visual styling

backend/
  demos/        Bundled demo DICOM cases
  uploads/      Runtime/demo-copy workspace, ignored by git except .gitkeep
```

Root `main.py` is a compatibility shim for older `uvicorn main:app` commands.
Use `app.main:app` for deployment.

## Workflow

1. **Open** a DICOM image (or a bundled test case).
2. **Annotate** in the viewer — the doctor marks Areas of Interest with three ROI
   tools before any analysis runs: **Box** (rectangle), **Ellipse** (circle/oval),
   and **Trace** (freehand margin), each with an optional label and a short note
   (≤ 100 chars). Annotations are pinned to image pixels, guide the segmentation,
   and carry over onto the analysis overlay.
3. **Start Analysis** — a deterministic pipeline measures the Areas of Interest. The
   **AOI Panel** then shows the doctor's annotations plus the system-collected
   measurements for the **largest AOI** (shape, margin, geometry, boundary metrics).

No external API/LLM is involved and no environment configuration is required —
everything runs locally and the pipeline only produces measurements, no generated text.

## Run Locally

```powershell
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Deployment Notes

- Deploy from the repository root so `app/`, `frontend/`, and `backend/` stay together.
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `Procfile` includes the same web command for platforms that read it.
- `backend/demos/` must be included if bundled demo cases should work.
- `backend/uploads/` is runtime scratch space; it should not be treated as permanent storage.
