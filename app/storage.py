"""File storage: disk-only uploads, demo registry, filename sanitization."""

import re
from pathlib import Path

from app.paths import DEMO_DIR, UPLOAD_DIR


UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


DEMOS: dict[str, dict] = {
    "case1": {
        "label":       "P_00778 · Right MLO",
        "description": "Mammogram - annotated AOI",
        "image": DEMO_DIR / "TEST_Mass-Training_P_00778_RIGHT_MLO_1" / "200abea1-01cf-4fa5-8270-bcf55d5ccca9.dcm",
        "mask":  DEMO_DIR / "TEST_Mass-Training_P_00778_RIGHT_MLO_1" / "74e56d2d-5f47-420a-b7f5-11f01d0745f9.dcm",
    },
    "case2": {
        "label":       "P_00853 · Right CC",
        "description": "Mammogram - annotated AOI",
        "image": DEMO_DIR / "TEST_Mass-Training_P_00853_RIGHT_CC_1" / "26d89c28-1bba-4c1c-afd9-308c86797187.dcm",
        "mask":  DEMO_DIR / "TEST_Mass-Training_P_00853_RIGHT_CC_1" / "8e8b6954-8798-4225-ae34-83f06cea126d.dcm",
    },
    "case3": {
        "label":       "P_00900 · Left MLO",
        "description": "Mammogram - annotated AOI",
        "image": DEMO_DIR / "TEST_Mass-Training_P_00900_LEFT_MLO_1" / "02cdbb12-ec20-4e2d-85f6-6f22c4aa233c.dcm",
        "mask":  DEMO_DIR / "TEST_Mass-Training_P_00900_LEFT_MLO_1" / "0b5ffe50-4a4c-42a4-a876-46555074a56a.dcm",
    },
}


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w\-_\.]", "_", name)
    return name or "unnamed.dcm"
