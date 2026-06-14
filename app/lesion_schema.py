"""Allowed-label enums and Pydantic models for the AOI profile contract.

These document the shape of the `/api/process` payload (see DOCUMENTATION.md §8).
They are kept in sync with what `pipeline.run_pipeline` actually emits — every
field below appears in the response, and the `aoi_*` keys mirror the `lesion_*`
keys for backward compatibility.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Shape(str, Enum):
    ROUND = "Round"
    OVAL = "Oval"
    LOBULATED = "Lobulated"
    IRREGULAR = "Irregular"
    ARCHITECTURAL_DISTORTION = "Architectural_Distortion"
    FOCAL_ASYMMETRIC_DENSITY = "Focal_Asymmetric_Density"
    LYMPH_NODE = "Lymph_Node"
    ASYMMETRIC_BREAST_TISSUE = "Asymmetric_Breast_Tissue"
    NA = "N/A"


class Margin(str, Enum):
    CIRCUMSCRIBED = "CIRCUMSCRIBED"
    CIRCUMSCRIBED_ILL_DEFINED = "CIRCUMSCRIBED-ILL_DEFINED"
    MICROLOBULATED = "MICROLOBULATED"
    MICROLOBULATED_ILL_DEFINED_SPICULATED = "MICROLOBULATED-ILL_DEFINED-SPICULATED"
    ILL_DEFINED = "ILL_DEFINED"
    ILL_DEFINED_SPICULATED = "ILL_DEFINED-SPICULATED"
    OBSCURED = "OBSCURED"
    OBSCURED_ILL_DEFINED = "OBSCURED-ILL_DEFINED"
    SPICULATED = "SPICULATED"
    NA = "N/A"


class Pathology(str, Enum):
    MALIGNANT = "malignant"
    BENIGN = "benign"
    NA = "N/A"


SHAPE_VALUES = {s.value for s in Shape}
MARGIN_VALUES = {m.value for m in Margin}
PATHOLOGY_VALUES = {p.value for p in Pathology}


class LesionGeometry(BaseModel):
    area_px: int
    area_pct: float
    bbox: List[int]
    centroid: List[float]
    circularity: float
    eccentricity: float
    solidity: float
    extent: float
    contour_roughness: float
    lobulation_index: float
    radial_spike_index: float
    spiculation_convergence: float
    # Physical size — populated only when the DICOM carries PixelSpacing.
    area_mm2: Optional[float] = None
    equiv_diameter_mm: Optional[float] = None


class CrownShyness(BaseModel):
    raw_score: float
    interpretation: str
    gradient_sharpness: float
    halo_width_mean: float
    halo_width_std: float
    transition_zone_entropy: float
    boundary_visibility_ratio: float
    radiolucent_halo_present: bool


class Lesion(BaseModel):
    lesion_id: str
    aoi_id: str
    shape: Shape
    margin: Margin
    pathology: Pathology
    confidence: float
    pathology_source: Optional[str] = None
    geometry: LesionGeometry
    crown_shyness: CrownShyness
    margin_evidence: List[str] = Field(default_factory=list)
    outline: List[List[int]] = Field(default_factory=list)


class LesionProfile(BaseModel):
    image_label: str
    is_there_a_lesion: str
    is_there_an_aoi: str
    lesion_count: int
    aoi_count: int
    lesion_shape: Shape
    aoi_shape: Shape
    lesion_margin: Margin
    aoi_margin: Margin
    pathology: Pathology
    confidence: float
    pathology_source: Optional[str] = None
    localization_quality: Optional[str] = None
    quality_flags: List[str] = Field(default_factory=list)
    lesions: List[Lesion] = Field(default_factory=list)
    aois: List[Lesion] = Field(default_factory=list)
