"""Shape, margin, and pathology classifiers (rule-based, explainable).

These operate on the corrected geometry/Crown-Shyness features. Each rule is a
documented threshold over a feature with a clear physical meaning, so a label can
always be traced back to the measurements that produced it (the margin classifier
returns that trace as an evidence list). Thresholds are deliberately conservative
— this is a demonstration heuristic, not a trained classifier.
"""


def classify_shape(geom: dict) -> str:
    circularity = geom["circularity"]
    eccentricity = geom["eccentricity"]
    solidity = geom["solidity"]
    roughness = geom["contour_roughness"]
    lobulation = geom["lobulation_index"]
    spike = geom["radial_spike_index"]
    asymmetry = geom.get("regional_asymmetry", 0.0)
    has_compact_mass = geom.get("has_compact_mass", True)

    if not has_compact_mass and spike > 0.65:
        return "Architectural_Distortion"
    if not has_compact_mass and asymmetry > 0.55:
        return "Focal_Asymmetric_Density"

    # Rounded undulations (not spikes) over an otherwise solid body.
    if lobulation > 0.45 and solidity > 0.78 and spike < 0.5:
        return "Lobulated"

    # A round mass: highly circular, near-isotropic, convex.
    if circularity > 0.80 and eccentricity < 0.50 and solidity > 0.90 and spike < 0.35:
        return "Round"

    # An oval mass: still smooth and convex, but elongated.
    if circularity > 0.60 and solidity > 0.85 and roughness < 0.45 and spike < 0.40:
        return "Oval"

    return "Irregular"


def classify_margin(geom: dict, css: dict) -> tuple[str, list[str]]:
    """Margin label plus the list of conditions that fired (used as evidence)."""
    sharpness = css["gradient_sharpness"]
    entropy = css["transition_zone_entropy"]
    score = css["raw_score"]
    visibility = css["boundary_visibility_ratio"]
    spike = geom["radial_spike_index"]
    convergence = geom.get("spiculation_convergence", 0.0)
    lobulation = geom["lobulation_index"]
    solidity = geom["solidity"]

    spiculated = spike > 0.55 or convergence > 0.60 or (solidity < 0.65 and score < 0.45)
    ill_defined = sharpness < 0.38 or entropy > 0.62
    circumscribed = score > 0.62 and sharpness > 0.52 and visibility > 0.68 and spike < 0.40
    microlobulated = lobulation > 0.50 and not spiculated
    obscured = visibility < 0.50

    evidence: list[str] = []
    if spiculated:
        if spike > 0.55:
            evidence.append("sharp radial protrusions (spicules)")
        elif convergence > 0.60:
            evidence.append("gradients converge radially on the mass")
        else:
            evidence.append("low, irregular Crown Shyness boundary")
    if ill_defined:
        evidence.append("low gradient sharpness" if sharpness < 0.38 else "high boundary entropy")
    if circumscribed:
        evidence.append("strong, even Crown Shyness boundary")
    if microlobulated:
        evidence.append("rounded outward lobulations")
    if obscured:
        evidence.append("low boundary visibility")

    if microlobulated and ill_defined and spiculated:
        return "MICROLOBULATED-ILL_DEFINED-SPICULATED", evidence
    if ill_defined and spiculated:
        return "ILL_DEFINED-SPICULATED", evidence
    if obscured and ill_defined:
        return "OBSCURED-ILL_DEFINED", evidence
    if circumscribed and ill_defined:
        return "CIRCUMSCRIBED-ILL_DEFINED", evidence
    if spiculated:
        return "SPICULATED", evidence
    if microlobulated:
        return "MICROLOBULATED", evidence
    if obscured:
        return "OBSCURED", evidence
    if ill_defined:
        return "ILL_DEFINED", evidence
    if circumscribed:
        return "CIRCUMSCRIBED", evidence
    return "ILL_DEFINED", evidence or ["fallback: insufficient boundary clarity"]


def classify_pathology(shape: str, margin: str, geom: dict, css: dict) -> tuple[str, float]:
    """Rule-based demo pathology score. Returns (label, confidence).

    Weights mirror the BI-RADS intuition that spiculated / ill-defined margins and
    irregular, low-solidity shapes raise suspicion, while a sharp even boundary
    lowers it. Confidence is the score for malignant, or its complement for benign.
    """
    convergence = geom.get("spiculation_convergence", 0.0)
    solidity = geom.get("solidity", 1.0)

    score = 0.0
    if "SPICULATED" in margin:
        score += 0.35
    if "ILL_DEFINED" in margin:
        score += 0.18
    if "OBSCURED" in margin:
        score += 0.10
    if shape in {"Irregular", "Architectural_Distortion"}:
        score += 0.18
    if convergence > 0.60:
        score += 0.12
    if solidity < 0.70:
        score += 0.12
    if css["raw_score"] < 0.40:
        score += 0.10
    if geom["radial_spike_index"] > 0.55:
        score += 0.05

    score = min(1.0, score)
    if score >= 0.50:
        return "malignant", round(score, 4)
    return "benign", round(1.0 - score, 4)
