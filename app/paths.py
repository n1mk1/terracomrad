"""Project paths used by the FastAPI app.

Keep filesystem paths absolute so the server can be launched from the project
root, an IDE, or a deployment runner without losing static/demo file access.
"""

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"
FRONTEND_DIR = ROOT_DIR / "frontend"
BACKEND_DIR = ROOT_DIR / "backend"
DEMO_DIR = BACKEND_DIR / "demos"
UPLOAD_DIR = BACKEND_DIR / "uploads"
AOI_LOG_DIR = BACKEND_DIR / "aoi_logs"
