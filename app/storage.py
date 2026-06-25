"""File storage: disk-only uploads, demo registry, filename sanitization, scratch cleanup."""

import os
import re
import time
import uuid
from pathlib import Path

from app.paths import AOI_LOG_DIR, DEMO_DIR, UPLOAD_DIR


UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Reject uploads larger than this (chunk-checked in routes) — guards memory/disk.
MAX_UPLOAD_MB = _env_float("MAX_UPLOAD_MB", 80.0)
# Auto-delete scratch files (uploads + analysis logs) older than this. 0 disables.
SCRATCH_TTL_HOURS = _env_float("SCRATCH_TTL_HOURS", 24.0)
_PRUNE_INTERVAL_S = 300.0   # at most one cleanup sweep per 5 minutes
_last_prune = 0.0


DEMOS: dict[str, dict] = {
    "case1": {
        "label": "P_00778 · Right MLO",
        "image": DEMO_DIR / "TEST_Mass-Training_P_00778_RIGHT_MLO_1" / "200abea1-01cf-4fa5-8270-bcf55d5ccca9.dcm",
        "mask":  DEMO_DIR / "TEST_Mass-Training_P_00778_RIGHT_MLO_1" / "74e56d2d-5f47-420a-b7f5-11f01d0745f9.dcm",
    },
    "case2": {
        "label": "P_00853 · Right CC",
        "image": DEMO_DIR / "TEST_Mass-Training_P_00853_RIGHT_CC_1" / "26d89c28-1bba-4c1c-afd9-308c86797187.dcm",
        "mask":  DEMO_DIR / "TEST_Mass-Training_P_00853_RIGHT_CC_1" / "8e8b6954-8798-4225-ae34-83f06cea126d.dcm",
    },
    "case3": {
        "label": "P_00900 · Left MLO",
        "image": DEMO_DIR / "TEST_Mass-Training_P_00900_LEFT_MLO_1" / "02cdbb12-ec20-4e2d-85f6-6f22c4aa233c.dcm",
        "mask":  DEMO_DIR / "TEST_Mass-Training_P_00900_LEFT_MLO_1" / "0b5ffe50-4a4c-42a4-a876-46555074a56a.dcm",
    },
}


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w\-_\.]", "_", name)
    return name or "unnamed.dcm"


def unique_upload_name(name: str) -> str:
    """A collision-proof upload filename: random prefix + sanitized original.

    Two users (or two files that happen to share a name) must never resolve to
    the same path on disk — otherwise one upload overwrites the other and the
    first user could read back the second's image.
    """
    return f"{uuid.uuid4().hex}_{safe_filename(name)}"


def _prune_dir(directory: Path, ttl_seconds: float, keep: tuple[str, ...] = (".gitkeep",)) -> None:
    cutoff = time.time() - ttl_seconds
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for path in entries:
        if path.name in keep or not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def maybe_prune() -> None:
    """Throttled cleanup of aged scratch files; cheap to call on hot paths.

    Keeps a long-lived instance from accumulating uploads/logs without bound.
    No-op when disabled (``SCRATCH_TTL_HOURS=0``) or when called again too soon.
    """
    global _last_prune
    if SCRATCH_TTL_HOURS <= 0:
        return
    now = time.time()
    if now - _last_prune < _PRUNE_INTERVAL_S:
        return
    _last_prune = now
    ttl = SCRATCH_TTL_HOURS * 3600.0
    _prune_dir(UPLOAD_DIR, ttl)
    _prune_dir(AOI_LOG_DIR, ttl)
