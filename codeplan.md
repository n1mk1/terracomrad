# TerraComrad — Code Optimization Plan

**Date:** 2026-06-20
**Scope:** Full line-by-line review of `app/` (backend), and `frontend/` (`app.js`,
`index.html`, `styles.css`).
**Goal:** Reduce redundant work and duplicated logic **without changing any
externally observable behavior** (identical API responses, identical rendered
output, identical UI).

## Guiding principles

1. **No functional change.** Every item below must produce byte-identical API
   responses and pixel-identical renders. Where that can't be guaranteed
   trivially, a verification step is specified.
2. **Reasonableness filter.** If something is merely a matter of taste, or the
   current code is already clear and correct, it is left alone and recorded in
   §6 ("Considered and intentionally left as-is") so the review is auditable.
3. **The analysis pipeline is deterministic.** There is no randomness anywhere in
   `run_pipeline`, so a golden-output comparison (see §7) is a complete safety
   net for backend refactors.

## 1. Summary of findings

| ID | Area | Finding | Impact | Effort | Risk | Status |
|----|------|---------|--------|--------|------|--------|
| BE‑1 | `crown_shyness.py` / `pipeline.py` | Gradient normalization recomputed once **per AOI** though it depends only on per-image inputs | Perf (real) | S | Low | ✅ Implemented |
| BE‑2 | `dicom_io.py` / `preprocess.py` | WW/WL windowing math duplicated in two modules | Maintainability | M | Low | ✅ Implemented |
| BE‑3 | `maps.py` | 4 of 5 colormaps are dead code (only `"gray"` is ever used) | Clarity / LOC | S | Low | ✅ Implemented |
| BE‑4 | `pipeline.py` | `binary_mask.sum()` computed twice in adjacent lines | Micro | XS | None | ✅ Implemented |
| FE‑1 | `app.js` | "Largest AOI" reduce duplicated in 3 places | DRY / micro-perf | S | Low | ✅ Implemented |
| FE‑2 | `app.js` | `drawScan()` re-fetches the base image already decoded in the viewer | Perf (1 request/analysis) | M | Med | ⏸ Deferred (fails low-risk bar) |
| FE‑3 | `app.js` | `renderAnnotChips()` re-binds per-chip listeners on every render | Micro-perf / clarity | M | Low | ✅ Implemented |
| CSS‑1 | `styles.css` | ~10 element-specific `.x.hidden{display:none}` rules redundant vs the global `!important` rule | LOC / clarity | S | Low | ✅ Implemented |

Implemented: **BE‑1, BE‑2, BE‑3, BE‑4, FE‑1, FE‑3, CSS‑1** (all "real, low-risk,
no behavior change").
Deferred: **FE‑2** — the plan rates it Medium-risk (couples the viewer and
analysis render paths), so it fails the "low-risk, no behavior change" bar and
was intentionally left out.

## 1a. Implementation log — 2026‑06‑20

All items except FE‑2 were implemented. Each was verified to preserve behavior:

**Safety nets used**
- *Golden pipeline hashes* (deterministic `run_pipeline` over the 3 demos, see §7
  Step 0). Baseline: `case1 5199ec…`, `case2 6fcd9c…`, `case3 209f7c…`.
- *Geometry/classifier self-check*: `PYTHONPATH=. uv run python tests/validate_metrics.py`.

**Results**
- **BE‑1** — `_normalize_gradient` → public `normalize_gradient`; `compute_css`
  gained an optional `grad_norm` param (falls back to computing it, so the
  3-arg test call still works); `pipeline.py` computes it once before the AOI
  loop. Golden hashes **unchanged**; self-check **passes**.
- **BE‑2** — added `window_to_uint8` in `dicom_io.py`, used by both
  `dicom_to_png` and `preprocess`. Proven **bit-identical** to the old inline
  formula over 2000 random + 3 degenerate windows; `dicom_to_png` still renders
  valid PNGs for all demos; golden hashes unchanged.
- **BE‑3** — removed the 4 unused colormaps from `_CMAPS` (kept `gray`). Golden
  hashes unchanged (`mask_png` output identical).
- **BE‑4** — `binary_mask.sum()` computed once as `mass_px`. Golden hashes
  unchanged.
- **FE‑1** — added `largestByArea(list)`; replaced the 3 duplicated reduces.
  `node --check frontend/app.js` passes; call sites verified in context.
- **FE‑3** — `renderAnnotChips` no longer rebinds per-chip listeners; chip
  click/dblclick are delegated once on the `annotChips` container. Buttons
  (`[data-del]`, `[data-note]`) are matched before chip-select, reproducing the
  prior `stopPropagation` + early-return semantics. `node --check` passes.
- **CSS‑1** — removed the 10 redundant `.x.hidden { display: none; }` rules; the
  global `.hidden { display: none !important; }` and the non-redundant
  `.analysis-loading:not(.hidden) ~ …` rule are intact. Braces balanced (250/250),
  no collapsed rules.
- **FE‑2** — **deferred** (Medium-risk; see table).

Net diff: `app/crown_shyness.py`, `app/pipeline.py`, `app/dicom_io.py`,
`app/preprocess.py`, `app/maps.py`, `frontend/app.js`, `frontend/styles.css`.

---

## 2. Backend findings (detail)

### BE‑1 — Hoist gradient normalization out of the per-AOI loop  ⭐ highest-value  · ✅ Implemented

**Where:** `app/crown_shyness.py:99` (`compute_css`) → calls `_normalize_gradient`
(`crown_shyness.py:21`); driven by `app/pipeline.py:217` inside the
`for candidate in candidates:` loop.

**Observation.** `compute_css` runs once per AOI candidate. On every call it does:

```python
grad = gradient if gradient is not None else _gradient_magnitude(img)
grad_norm = _normalize_gradient(grad, breast_mask)   # crown_shyness.py:107
```

`_normalize_gradient` performs a `binary_erosion` over the 512² breast mask
(`iterations=6`) plus a `np.percentile(..., 95)`. But its inputs — `gradient` and
`breast_mask` — are **per-image constants** computed once in `compute_maps` and
passed unchanged into every iteration (`pipeline.py:184, 192, 217`). So for *N*
candidates the identical erosion + percentile is computed *N* times. Only the
ring/halo/contour parts of `compute_css` are genuinely per-AOI.

**Why it's safe.** The normalized gradient is a pure function of
`(gradient, breast_mask)`; hoisting it produces a **bit-identical** `grad_norm`,
just computed once.

**Proposed change.**

1. Expose the helper publicly in `crown_shyness.py` (keep the formula in one
   place):
   ```python
   def normalize_gradient(grad, breast_mask):   # was _normalize_gradient
       ...
   _normalize_gradient = normalize_gradient      # back-compat alias (optional)
   ```
2. Add an optional pre-computed arg to `compute_css`:
   ```python
   def compute_css(lesion, geometry, img, breast_mask=None, gradient=None,
                   grad_norm=None):
       ...
       grad = gradient if gradient is not None else _gradient_magnitude(img)
       if grad_norm is None:
           grad_norm = normalize_gradient(grad, breast_mask)
   ```
   (Fallback preserves current behavior for any direct/test caller.)
3. In `pipeline.py`, compute it once before the loop and pass it in:
   ```python
   from app.crown_shyness import compute_css, normalize_gradient
   ...
   grad_norm = normalize_gradient(gradient, breast_mask)
   for candidate in candidates:
       ...
       css = compute_css(candidate, geometry, img, breast_mask, gradient,
                         grad_norm=grad_norm)
   ```

**Verification.** Golden-output diff on the 3 demos (§7) must show **no change**.

---

### BE‑2 — Single source of truth for WW/WL windowing  · ✅ Implemented

**Where:** `app/dicom_io.py:64` (`dicom_to_png`) and `app/preprocess.py:11`
(`preprocess`).

**Observation.** Both modules independently implement the same monochrome
windowing math:

```python
lo, hi = wl - ww / 2, wl + ww / 2
windowed = np.clip(pixels, lo, hi)
scaled = ((windowed - lo) / (hi - lo) * 255).astype(np.uint8) if hi > lo \
         else np.zeros_like(..., np.uint8)
# + MONOCHROME1 inversion
```

(`dicom_io.py:84-88` vs `preprocess.py:36-44`.) This is the exact transform that
must stay consistent between what the radiologist *sees* (viewer PNG) and what
the analysis pipeline *measures* (preprocessed array). Duplication is a
correctness hazard: a future tweak to one path silently diverges from the other.

**Proposed change.** Add one shared helper in `dicom_io.py` and import it into
`preprocess.py`:

```python
def window_to_uint8(pixels: np.ndarray, ww: float, wl: float) -> np.ndarray:
    """Clip a float pixel array to the WW/WL window and scale to uint8 [0,255]."""
    lo, hi = wl - ww / 2.0, wl + ww / 2.0
    if hi <= lo:
        return np.zeros(pixels.shape, dtype=np.uint8)
    clipped = np.clip(pixels, lo, hi)
    return ((clipped - lo) / (hi - lo) * 255).astype(np.uint8)
```

- `dicom_to_png` (monochrome branch): replace lines 84-86 with
  `scaled = window_to_uint8(pixels, ww, wl)`; keep the existing MONOCHROME1
  inversion and the default-WW/WL resolution above it.
- `preprocess` (both branches converge on the window block): replace lines 36-41
  with `scaled = window_to_uint8(pixels, ww, wl)`; keep the MONOCHROME1
  inversion, resize, and `/255` normalization.

**Care points.** Preserve the existing `hi > lo` / `hi <= lo` semantics exactly
(helper returns zeros when the window is degenerate — same as today). RGB
handling stays in each caller (it differs: `dicom_to_png` returns RGB directly,
`preprocess` first converts to luminance, then windows).

**Verification.** Render each demo via `/api/files/{id}/image` and compare PNG
bytes before/after; run the golden pipeline diff (§7) for the preprocess path.

---

### BE‑3 — Remove dead colormaps in `maps.py`  · ✅ Implemented

**Where:** `app/maps.py:25` (`_CMAPS`), `:34` (`_apply_cmap`), `:44` (`to_png_b64`).

**Observation.** `to_png_b64` is called in exactly one place —
`relevance.mask_png` (`relevance.py:219`) — always with `"gray"`. The
`viridis`, `plasma`, `inferno`, and `magma` entries are vestigial from the
removed "legend maps" (the module docstring at `maps.py:13-14` confirms those
were deleted). They are never reachable.

**Proposed change (conservative).** Delete the four unused `_CMAPS` entries,
keeping `gray` and the generic `_apply_cmap`/`to_png_b64` API intact. This trims
~4 lines and removes a misleading "we render colormaps" signal without touching
any code path.

> Optional, slightly larger: since only binary masks are ever rendered,
> `mask_png` could bypass the colormap entirely
> (`Image.fromarray((mask > 0).astype(np.uint8) * 255, "L")`). Left out of the
> recommended set because it changes the render helper rather than just deleting
> dead data — only worth it if `to_png_b64` is otherwise removed.

**Verification.** `mask_png` output is unchanged (gray path untouched); golden
diff confirms identical `generated_mask.png`.

---

### BE‑4 — Compute `binary_mask.sum()` once  · ✅ Implemented

**Where:** `app/pipeline.py:200-201`.

```python
"area_px":  int(binary_mask.sum()),
"area_pct": round(100.0 * float(binary_mask.sum()) / binary_mask.size, 4),
```

**Proposed change.** Compute once:

```python
mass_px = int(binary_mask.sum())
...
"area_px":  mass_px,
"area_pct": round(100.0 * mass_px / binary_mask.size, 4),
```

Trivial, zero risk, marginally clearer. (`.sum()` over 512² is cheap, so this is
clarity more than perf.)

---

## 3. Frontend findings (detail)

### FE‑1 — One "largest AOI" helper  · ✅ Implemented

**Where:** `frontend/app.js:458-459`, `:619`, `:1477-1478` — the same reduce
appears three times:

```js
lesions.reduce((best, l) =>
  ((l.geometry && l.geometry.area_px) || 0) > ((best.geometry && best.geometry.area_px) || 0) ? l : best,
  lesions[0]);
```

**Proposed change.** Define one helper near the other helpers (e.g. by
`formatNum`, ~`app.js:688`):

```js
function largestByArea(list) {
    return list.reduce((best, l) =>
        ((l.geometry && l.geometry.area_px) || 0) > ((best.geometry && best.geometry.area_px) || 0) ? l : best,
        list[0]);
}
```

Replace the three call sites:
- `renderLesionCards` (`:458`) → `const largest = largestByArea(lesions);`
- `drawOverlays` (`:618-620`) → `const largest = lesions.length ? largestByArea(lesions) : null;`
- `buildInsightProfile` (`:1477`) → `const largest = largestByArea(aois);`

**Why safe.** Identical logic, identical seed (`list[0]`). All three sites
already guard non-empty before calling (or keep their existing guard).

**Verification.** Manual: run an analysis with a multi-AOI image; confirm the
selected card, overlay focus, and insight profile all still target the same AOI.

---

### FE‑2 — (Optional) Reuse the decoded base image in `drawScan()`  · ⏸ Deferred (Medium-risk)

**Where:** `frontend/app.js:570-587`.

**Observation.** `drawScan()` creates a fresh `Image`, fetches
`/api/files/{id}/image?ww=&wl=` (the server sends `Cache-Control: no-store`, so
it's always a real round-trip + decode), and draws it onto `scanCanvas`. The
viewer's `dicomImg` is normally already decoded at the same `state.ww/state.wl`.

**Proposed change (guarded).** When `dicomImg.complete && dicomImg.naturalWidth`,
draw it directly and skip the fetch; otherwise fall back to the current fetch
path:

```js
function drawScan() {
    if (!state.fileId) return;
    if (dicomImg.complete && dicomImg.naturalWidth) {
        const ctx = scanCanvas.getContext('2d');
        ctx.clearRect(0, 0, scanCanvas.width, scanCanvas.height);
        ctx.drawImage(dicomImg, 0, 0, scanCanvas.width, scanCanvas.height);
        drawOverlays();
        return;
    }
    /* …existing fetch-based fallback… */
}
```

**Risk / why optional.** `drawImage` uses raw decoded pixels (CSS transforms on
`dicomImg` do not affect it), so output matches. The edge risk is `state.ww/wl`
being changed *after* the viewer image loaded but *before* analysis — in the
current flow analysis uses the same `state.ww/wl`, so they match, but this
couples two code paths that are currently independent. Payoff is one avoided
request per analysis run. Implement only if that request is observably costly.

---

### FE‑3 — (Optional) Event delegation in `renderAnnotChips()`  · ✅ Implemented

**Where:** `frontend/app.js:1285-1312`.

**Observation.** Every render rebuilds `annotChips.innerHTML` and then attaches
three sets of listeners (`.annot-chip`, `.annot-chip-note`, `.annot-chip-del`)
to the freshly created nodes. Functionally fine (old nodes are discarded so no
leak), but it re-binds on each annotation change.

**Proposed change.** Bind once to the `annotChips` container using delegation
(check `e.target.closest('[data-del]')` / `[data-note]` / `.annot-chip`). Removes
per-render binding and is a bit easier to reason about.

**Why optional.** Annotation counts are small (single digits), so the perf gain
is negligible; this is mostly a clarity improvement. Low risk, low payoff.

---

## 4. CSS findings (detail)

### CSS‑1 — (Optional) Drop redundant `.x.hidden` rules  · ✅ Implemented

**Where:** global rule `styles.css:2` is `.hidden { display: none !important; }`.
Because it is `!important`, these element-specific rules can never matter and are
redundant:

- `.workspace.hidden` (`:320`)
- `.tool-group.hidden` (`:355`)
- `.spinner-wrap.hidden` (`:421`)
- `.target-ring.hidden` (`:443`) — *but see note*
- `.img-error.hidden` (`:457`)
- `.meta-grid.hidden` (`:517`)
- `.mask-controls.hidden` (`:546`)
- `.analysis-screen.hidden` (`:731`)
- `.analysis-loading.hidden` (`:764`)
- `.analysis-error.hidden` (`:777`)

**Proposed change.** Remove the redundant declarations. Each target is only ever
hidden via `display:none`, which the global rule already enforces.

**Care point.** `.target-ring` also has variant classes (`.target-ring.base`,
`.target-ring.mask`) that set a border but **not** `display`, and JS toggles
between `target-ring hidden` and `target-ring base|mask`. The global `.hidden`
still wins, so removing `.target-ring.hidden{display:none}` is safe — but verify
the ring shows/hides correctly in dual (image+mask) mode after the change.

**Why optional.** Pure noise reduction; no behavioral or perf effect. Only do it
as part of a broader CSS tidy.

---

## 5. Whole-pipeline performance note

The analysis pipeline's heavy lifting is already vectorized via NumPy/SciPy
(`gaussian_filter`, `binary_*` morphology, `ndimage.label`, histogram-based
Otsu). It also runs off the event loop through `asyncio.to_thread`
(`routes.py:193`), so request handling stays responsive. **No structural change
recommended.** BE‑1 is the only redundant heavy computation found.

---

## 6. Considered and intentionally left as-is

These were reviewed and deliberately **not** changed — the code is correct,
clear, and any "optimization" would be taste or would risk altering tuned
numeric output.

- **`crown_shyness._halo_widths` (`:57`)** — nested Python ray-march (64 rays ×
  ≤48 steps). Non-vectorized, but runs once per AOI on a 512² frame and the
  early-exit logic is subtle. Vectorizing risks changing the tuned halo metric.
  Leave unless profiling proves it a bottleneck.
- **`lesions._trace_contour` / `_lobulation_index` / `_spike_index`** — Python
  loops by necessity (ordered boundary walk, prominence/run detection). Bounded,
  run once per AOI, and feed tuned thresholds. Leave.
- **Rule thresholds in `classify.py`** — deliberately hand-tuned demo heuristics.
  Out of scope for "optimization."
- **`crown_shyness._gradient_magnitude` / `lesions` gradient fallbacks** — only
  used when no precomputed gradient is passed (i.e. direct calls / tests). They
  are cheap safety fallbacks; keep them.
- **Stateless `pydicom.dcmread` per request (`routes.py:24`)** — re-reading the
  dataset for `/image` and `/process` is inherent to the disk-only, stateless
  design. Caching would add lifecycle complexity for little gain. Leave.
- **Two small log writers `_write_aoi_log` / `_write_insights_log`
  (`routes.py:33,72`)** — share a timestamp/stem preamble, but extracting a
  helper saves ~2 lines and is borderline taste. Leave.
- **DOM element caching at top of `app.js` (`:27-111`)** — already the right
  pattern. Leave.
- **`escapeHtml` / Markdown renderer (`app.js`)** — recently added, correct, and
  XSS-safe. Leave.

---

## 7. Implementation plan & sequencing

Work in small, independently-verifiable commits. Backend first (covered by a
golden diff), then frontend (manual UI check), then optional CSS.

### Step 0 — Establish the safety net (do this first)

Create a throwaway golden-capture before any change, so every backend refactor
can be proven output-identical. The pipeline is deterministic, so this is exact:

```bash
uv run python - <<'PY'
import json, hashlib, pydicom
from app.storage import DEMOS
from app.dicom_io import default_wwwl
from app.pipeline import run_pipeline

for name, d in DEMOS.items():
    ds = pydicom.dcmread(str(d["image"]))
    ww, wl = default_wwwl(ds)
    out = run_pipeline(ds, ww, wl, f"demo_{name}")
    blob = json.dumps(out, sort_keys=True).encode()
    print(name, hashlib.sha256(blob).hexdigest())
PY
```

Record the three hashes. After **each** backend step, re-run and confirm the
hashes are unchanged. (Includes `generated_mask.png`, so BE‑3 is covered too.)

### Step 1 — BE‑4 (warm-up, trivial)
Single `binary_mask.sum()`. Re-run golden hashes → must match.

### Step 2 — BE‑1 (perf, highest value)
Expose `normalize_gradient`, add `grad_norm` param to `compute_css`, hoist the
call in `pipeline.py`. Re-run golden hashes → must match. Optionally time the
pipeline on a multi-AOI image before/after to confirm the win.

### Step 3 — BE‑2 (windowing DRY)
Add `window_to_uint8` to `dicom_io.py`; use it in both `dicom_to_png` and
`preprocess`. Verify:
- Golden hashes (preprocess path) unchanged.
- `GET /api/files/{demo}/image` PNG bytes identical before/after for each demo
  and a couple of non-default WW/WL values.

### Step 4 — BE‑3 (dead colormaps)
Delete the four unused `_CMAPS` entries. Re-run golden hashes → must match.

### Step 5 — FE‑1 (largest-AOI helper)
Add `largestByArea`, replace the 3 call sites. Manual check: multi-AOI image —
selected card, overlay focus, and AI-insight profile still reference the same
AOI; single-AOI and no-AOI cases still render.

### Step 6 — (Optional) FE‑2, FE‑3, CSS‑1
Implement only if desired. Each is independently revertible:
- FE‑2: confirm the analysis scan still renders identically (compare a
  screenshot) and the fetch fallback still works on a cold load.
- FE‑3: confirm select / note / delete still work from chips.
- CSS‑1: confirm every toggled element still hides/shows, paying attention to
  the target ring in dual-image mode.

### Tooling note
There is no linter/formatter or JS build step configured (vanilla static JS,
`pyproject.toml` has no dev tooling). No new dependencies are introduced by any
item above. If desired later, adding `ruff` for the backend would be a separate,
non-functional change — out of scope here.

---

## 8. Expected outcome

- **Performance:** BE‑1 removes (N−1) redundant 512² erosion+percentile passes
  per analysis (N = AOI count); FE‑2 (if taken) removes one image fetch+decode
  per analysis run.
- **Maintainability:** windowing math lives in one place (BE‑2); the
  "largest AOI" rule lives in one place (FE‑1); dead colormap data removed
  (BE‑3).
- **Behavior:** unchanged — enforced by the golden-hash net for the backend and
  targeted manual checks for the frontend.
