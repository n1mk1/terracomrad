"""Deterministic geometry/classifier self-check.

Feeds synthetic shapes with known theoretical geometry through the real pipeline
functions and asserts the measured features and shape labels are correct. This is
a regression guard for the geometry layer (contour tracing, perimeter/circularity,
lobulation, spike) and the shape classifier. Run directly:

    python _validate_metrics.py        # exits non-zero if any check fails
"""
import sys

import numpy as np

from app.classify import classify_margin, classify_shape
from app.crown_shyness import compute_css
from app.lesions import compute_geometry, extract_lesions

S = 512
CX = CY = 256
_failures: list[str] = []


def disk(r):
    Y, X = np.ogrid[:S, :S]
    return ((X - CX) ** 2 + (Y - CY) ** 2 <= r * r).astype(np.uint8)


def ellipse(a, b):
    Y, X = np.ogrid[:S, :S]
    return (((X - CX) / a) ** 2 + ((Y - CY) / b) ** 2 <= 1).astype(np.uint8)


def rect(w, h):
    m = np.zeros((S, S), np.uint8)
    m[CY - h // 2:CY + h // 2, CX - w // 2:CX + w // 2] = 1
    return m


def _poly_fill(xs, ys):
    m = np.zeros((S, S), np.uint8)
    poly = np.column_stack([xs, ys])
    for y in range(S):
        xints = []
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xints.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        xints.sort()
        for i in range(0, len(xints) - 1, 2):
            m[y, int(np.ceil(xints[i])):int(np.floor(xints[i + 1])) + 1] = 1
    return m


def star(n=8, r_out=120, r_in=55):
    th = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    r = np.where((np.arange(720) // (360 // n)) % 2 == 0, r_out, r_in)
    return _poly_fill(CX + r * np.cos(th), CY + r * np.sin(th))


def soft_disk(r, edge=18.0):
    """Bright disk with a smooth intensity falloff — a realistic mass profile."""
    Y, X = np.ogrid[:S, :S]
    d = np.sqrt((X - CX) ** 2 + (Y - CY) ** 2)
    return np.clip((r - d) / edge + 0.5, 0.0, 1.0).astype(np.float32)


def check(name, cond, detail=""):
    tag = "OK  " if cond else "FAIL"
    if not cond:
        _failures.append(f"{name}: {detail}")
    print(f"   [{tag}] {name}  {detail}")


def approx(name, got, expect, tol):
    check(name, abs(got - expect) <= tol, f"got={got:.3f} expect~{expect}±{tol}")


print("== geometry (binary shapes) ==")
g_disk = compute_geometry(extract_lesions(disk(100))[0], disk(100).astype(np.float32))
approx("disk.circularity", g_disk["circularity"], 1.00, 0.06)
approx("disk.eccentricity", g_disk["eccentricity"], 0.00, 0.05)
approx("disk.solidity", g_disk["solidity"], 1.00, 0.05)
approx("disk.lobulation", g_disk["lobulation_index"], 0.00, 0.05)
approx("disk.spike", g_disk["radial_spike_index"], 0.00, 0.05)
check("disk -> Round", classify_shape(g_disk) == "Round", classify_shape(g_disk))

g_ell = compute_geometry(extract_lesions(ellipse(140, 70))[0], ellipse(140, 70).astype(np.float32))
approx("ellipse.eccentricity", g_ell["eccentricity"], 0.866, 0.06)
approx("ellipse.solidity", g_ell["solidity"], 1.00, 0.05)
check("ellipse -> Oval", classify_shape(g_ell) == "Oval", classify_shape(g_ell))

g_rect = compute_geometry(extract_lesions(rect(200, 100))[0], rect(200, 100).astype(np.float32))
approx("rect.circularity", g_rect["circularity"], 0.785, 0.10)

g_star = compute_geometry(extract_lesions(star())[0], star().astype(np.float32))
check("star.circularity low", g_star["circularity"] < 0.4, f"circ={g_star['circularity']}")
check("star -> Irregular", classify_shape(g_star) == "Irregular", classify_shape(g_star))

print("== Crown Shyness (soft-intensity disk: sharp, visible boundary) ==")
img = soft_disk(100)
mask = (img > 0.5).astype(np.uint8)
cand = extract_lesions(mask)[0]
g = compute_geometry(cand, img)
css = compute_css(cand, g, img)
check("css.visibility high", css["boundary_visibility_ratio"] > 0.6, f"vis={css['boundary_visibility_ratio']}")
check("css.sharpness present", css["gradient_sharpness"] > 0.3, f"sharp={css['gradient_sharpness']}")
margin, evidence = classify_margin(g, css)
check("soft disk margin not spiculated", "SPICULATED" not in margin, margin)
print(f"        margin={margin} evidence={evidence}")

print()
if _failures:
    print(f"FAILED {len(_failures)} check(s):")
    for f in _failures:
        print("  -", f)
    sys.exit(1)
print("All geometry/classifier checks passed.")
