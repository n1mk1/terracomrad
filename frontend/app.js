/* ── State ────────────────────────────────────────────────── */
const state = {
    fileId: null,
    ww: 400, wl: 40, defaultWw: 400, defaultWl: 40,
    meta: {},

    maskFileId: null,
    maskWw: 400, maskWl: 40, maskDefaultWw: 400, maskDefaultWl: 40,
    maskVisible: true,

    target: 'base',  // 'base' | 'mask'

    demoId: null,
};

// Independent transform state per image
const viewBase = { x: 0, y: 0, zoom: 1, angle: 0, flipH: 1, flipV: 1, invert: false };
const viewMask = { x: 0, y: 0, zoom: 1, angle: 0, flipH: 1, flipV: 1, invert: false };

function getActiveView() {
    return state.target === 'mask' && state.maskFileId ? viewMask : viewBase;
}

let activeTool       = 'pan';
let selectedBaseFile = null;
let selectedMaskFile = null;

/* ── DOM ──────────────────────────────────────────────────── */
const uploadArea    = document.getElementById('uploadArea');
const workspace     = document.getElementById('workspace');
const baseBox       = document.getElementById('baseBox');
const maskBox       = document.getElementById('maskBox');
const baseFname     = document.getElementById('baseFname');
const maskFname     = document.getElementById('maskFname');
const fileInput     = document.getElementById('fileInput');
const maskFileInput = document.getElementById('maskFileInput');
const maskToggle    = document.getElementById('maskToggle');
const proceedBtn    = document.getElementById('proceedBtn');
const openNewBtn    = document.getElementById('openNewBtn');
const fileLabel     = document.getElementById('fileLabel');
const saveStatus    = document.getElementById('saveStatus');

const btnPan        = document.getElementById('btnPan');
const btnWL         = document.getElementById('btnWL');
const targetGroup   = document.getElementById('targetGroup');
const btnTargetBase = document.getElementById('btnTargetBase');
const btnTargetMask = document.getElementById('btnTargetMask');
const btnInvert     = document.getElementById('btnInvert');
const btnRotCCW     = document.getElementById('btnRotCCW');
const btnRotCW      = document.getElementById('btnRotCW');
const btnFlipH      = document.getElementById('btnFlipH');
const btnFlipV      = document.getElementById('btnFlipV');
const btnFit        = document.getElementById('btnFit');
const btnReset      = document.getElementById('btnReset');

const canvasContainer = document.getElementById('canvasContainer');
const dicomImg        = document.getElementById('dicomImg');
const maskImg         = document.getElementById('maskImg');
const targetRing      = document.getElementById('targetRing');
const spinnerWrap     = document.getElementById('spinnerWrap');
const imgError        = document.getElementById('imgError');

const ovTL = document.getElementById('ovTL');
const ovTR = document.getElementById('ovTR');
const ovBL = document.getElementById('ovBL');
const ovBR = document.getElementById('ovBR');

const wwSlider      = document.getElementById('wwSlider');
const wlSlider      = document.getElementById('wlSlider');
const wwVal         = document.getElementById('wwVal');
const wlVal         = document.getElementById('wlVal');
const btnAutoWwwl   = document.getElementById('btnAutoWwwl');
const maskControls  = document.getElementById('maskControls');
const maskOpacity   = document.getElementById('maskOpacity');
const maskOpVal     = document.getElementById('maskOpVal');
const maskColorSel  = document.getElementById('maskColor');
const btnToggleMask = document.getElementById('btnToggleMask');
const metaToggle    = document.getElementById('metaToggle');
const metaArrow     = document.getElementById('metaArrow');
const metaGrid      = document.getElementById('metaGrid');

const btnStartAnalysis  = document.getElementById('btnStartAnalysis');
const analysisScreen    = document.getElementById('analysisScreen');
const analysisLoading   = document.getElementById('analysisLoading');
const analysisError     = document.getElementById('analysisError');
const analysisScanLabel = document.getElementById('analysisScanLabel');
const analysisGrid      = document.getElementById('analysisGrid');
const legendItems       = document.getElementById('legendItems');
const lesionCards       = document.getElementById('lesionCards');
const resultsRow        = document.getElementById('resultsRow');
const scanCanvas        = document.getElementById('scanCanvas');
const overlayCanvas     = document.getElementById('overlayCanvas');
const togMask           = document.getElementById('togMask');
const togBboxes         = document.getElementById('togBboxes');
const togHalo           = document.getElementById('togHalo');
const togRelevance      = document.getElementById('togRelevance');
const togAnnotations    = document.getElementById('togAnnotations');
const btnBackToViewer   = document.getElementById('btnBackToViewer');
const btnReanalyze      = document.getElementById('btnReanalyze');

/* ── Annotation (ROI) DOM ─────────────────────────────────── */
const annotLayer    = document.getElementById('annotLayer');
const annotType     = document.getElementById('annotType');
const btnAnnotRect  = document.getElementById('btnAnnotRect');
const btnAnnotEll   = document.getElementById('btnAnnotEllipse');
const btnAnnotFree  = document.getElementById('btnAnnotFree');
const btnAnnotUndo  = document.getElementById('btnAnnotUndo');
const btnAnnotClear = document.getElementById('btnAnnotClear');
const annotBar      = document.getElementById('annotBar');
const annotChips    = document.getElementById('annotChips');
const annotHint     = document.getElementById('annotHint');

/* ── Mask colour filters ──────────────────────────────────── */
const MASK_FILTER = {
    green:  'sepia(1) saturate(20) hue-rotate(85deg)',
    red:    'sepia(1) saturate(20) hue-rotate(315deg)',
    blue:   'sepia(1) saturate(20) hue-rotate(175deg)',
    yellow: 'sepia(1) saturate(20) hue-rotate(15deg)',
    cyan:   'sepia(1) saturate(20) hue-rotate(130deg)',
};

/* ── Upload screen: mask toggle ───────────────────────────── */
maskToggle.addEventListener('change', () => {
    const on = maskToggle.checked;
    maskBox.classList.toggle('disabled', !on);
    if (!on) {
        selectedMaskFile = null;
        maskFname.textContent = '';
        maskBox.classList.remove('has-file');
    }
});

/* ── Upload screen: base box ──────────────────────────────── */
baseBox.addEventListener('click', () => fileInput.click());
baseBox.addEventListener('dragover',  e => { e.preventDefault(); baseBox.classList.add('drag-over'); });
baseBox.addEventListener('dragleave', ()  => baseBox.classList.remove('drag-over'));
baseBox.addEventListener('drop', e => {
    e.preventDefault(); baseBox.classList.remove('drag-over');
    if (e.dataTransfer.files[0]) setBaseFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) setBaseFile(fileInput.files[0]);
    fileInput.value = '';
});

/* ── Upload screen: mask box ──────────────────────────────── */
maskBox.addEventListener('click', () => maskFileInput.click());
maskBox.addEventListener('dragover',  e => { e.preventDefault(); maskBox.classList.add('drag-over'); });
maskBox.addEventListener('dragleave', ()  => maskBox.classList.remove('drag-over'));
maskBox.addEventListener('drop', e => {
    e.preventDefault(); maskBox.classList.remove('drag-over');
    if (e.dataTransfer.files[0]) setMaskFile(e.dataTransfer.files[0]);
});
maskFileInput.addEventListener('change', () => {
    if (maskFileInput.files[0]) setMaskFile(maskFileInput.files[0]);
    maskFileInput.value = '';
});

function setBaseFile(file) {
    selectedBaseFile = file;
    baseFname.textContent = file.name;
    baseBox.classList.add('has-file');
    proceedBtn.disabled = false;
}

function setMaskFile(file) {
    selectedMaskFile = file;
    maskFname.textContent = file.name;
    maskBox.classList.add('has-file');
}

/* ── Upload screen: proceed button ───────────────────────── */
proceedBtn.addEventListener('click', async () => {
    if (!selectedBaseFile) return;
    setSaveStatus('Uploading…', 'loading');
    proceedBtn.disabled = true;

    try {
        const form = new FormData();
        form.append('file', selectedBaseFile);
        const res = await fetch('/api/upload', { method: 'POST', body: form });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Error ${res.status}`);
        const data = await res.json();

        if (selectedMaskFile) {
            const mform = new FormData();
            mform.append('file', selectedMaskFile);
            const mres = await fetch('/api/upload', { method: 'POST', body: mform });
            if (mres.ok) {
                const md = await mres.json();
                data.mask_file_id = md.file_id;
                data.mask_ww = md.ww;
                data.mask_wl = md.wl;
            }
        }
        applyFileData(data);
    } catch (err) {
        setSaveStatus(`Error: ${err.message}`, 'err');
        proceedBtn.disabled = false;
    }
});

/* ── Demo cards ───────────────────────────────────────────── */
document.querySelectorAll('.demo-card').forEach(card => {
    card.addEventListener('click', () => loadDemo(card.dataset.demo, card));
});

async function loadDemo(name, cardEl) {
    cardEl.disabled = true; cardEl.style.opacity = '.6';
    setSaveStatus('Loading…', 'loading');
    try {
        const res = await fetch(`/api/demo/${name}`);
        if (!res.ok) throw new Error(`Server error ${res.status}`);
        applyFileData(await res.json());
    } catch (err) {
        setSaveStatus(`Error: ${err.message}`, 'err');
    } finally {
        cardEl.disabled = false; cardEl.style.opacity = '';
    }
}

/* ── Viewer: back to upload screen ───────────────────────── */
openNewBtn.addEventListener('click', () => {
    workspace.classList.add('hidden');
    uploadArea.style.display = '';
    selectedBaseFile = null;
    selectedMaskFile = null;
    baseFname.textContent = '';
    maskFname.textContent = '';
    baseBox.classList.remove('has-file');
    maskBox.classList.remove('has-file');
    proceedBtn.disabled = true;
    maskToggle.checked = false;
    maskBox.classList.add('disabled');
    btnStartAnalysis.disabled = true;
    analysisScreen.classList.add('hidden');
    annotBar.classList.add('hidden');
    resetAnalysisUi();
    resetAnnotations();
});

/* ── Analysis screen: data + overlay state ───────────────── */
let analysisRunning = false;
let analysisAbortController = null;
let currentAnalysis = null;
let scanImageEl = null;
let relevanceImageEl = null;
let maskImageEl = null;
let selectedLesionId = null;

const CSS_COLORS = {
    respects_boundary: '#2dd4bf',   // teal
    ambiguous:         '#f5a524',   // amber
    invasive:          '#fb7185',   // coral
};
const NEUTRAL_COLOR = '#7a7a90';

btnStartAnalysis.addEventListener('click', () => runAnalysis());
btnReanalyze.addEventListener('click',     () => runAnalysis());
btnBackToViewer.addEventListener('click',  showViewer);

[togMask, togBboxes, togHalo, togRelevance, togAnnotations].forEach(el =>
    el.addEventListener('change', drawOverlays)
);

function showViewer() {
    analysisScreen.classList.add('hidden');
    workspace.classList.remove('hidden');
}

function showAnalysisScreen() {
    workspace.classList.add('hidden');
    analysisScreen.classList.remove('hidden');
    analysisScanLabel.textContent = state.fileId || '';
}

async function runAnalysis() {
    if (!state.fileId || analysisRunning) return;
    analysisRunning = true;
    analysisAbortController = new AbortController();

    btnStartAnalysis.textContent = 'Analyzing…';
    btnStartAnalysis.classList.add('running');
    btnStartAnalysis.disabled = true;
    btnReanalyze.disabled = true;

    analysisError.classList.add('hidden');
    analysisError.textContent = '';
    legendItems.innerHTML = '';
    lesionCards.innerHTML = '';
    resultsRow.innerHTML = '<td colspan="6" class="results-empty">Computing…</td>';
    clearOverlays();
    analysisLoading.classList.remove('hidden');
    showAnalysisScreen();

    try {
        const params = new URLSearchParams({ ww: state.ww, wl: state.wl });
        if (state.maskFileId) params.set('mask_file_id', state.maskFileId);
        if (state.demoId)     params.set('demo_id', state.demoId);
        // Forward the doctor's ROI annotations so the backend can focus
        // detection where the clinician marked the finding (in base-image px).
        const roiBody = {
            rois: annotations.map(a => {
                const shape = a.kind === 'freehand'
                    ? { kind: 'freehand', points: a.points }
                    : { kind: a.kind, x1: a.x1, y1: a.y1, x2: a.x2, y2: a.y2 };
                // Carry the doctor's id / finding type / label / note so the backend
                // can log them alongside the measured AOI.
                return { ...shape, id: a.id, type: a.type, label: a.label || '', note: a.note || '' };
            }),
            image_width:  dicomImg.naturalWidth,
            image_height: dicomImg.naturalHeight,
        };
        const res = await fetch(
            `/api/process/${enc(state.fileId)}?${params.toString()}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(roiBody),
                signal: analysisAbortController.signal,
            }
        );
        if (!res.ok) {
            const detail = (await res.json().catch(() => ({}))).detail || `Error ${res.status}`;
            throw new Error(detail);
        }
        renderAnalysis(await res.json());
    } catch (err) {
        if (err.name === 'AbortError') return;
        analysisLoading.classList.add('hidden');
        analysisError.classList.remove('hidden');
        analysisError.textContent = `Analysis failed: ${err.message}`;
        resultsRow.innerHTML = '<td colspan="6" class="results-empty">Analysis failed.</td>';
    } finally {
        analysisRunning = false;
        analysisAbortController = null;
        btnStartAnalysis.textContent = 'Start Analysis';
        btnStartAnalysis.classList.remove('running');
        btnStartAnalysis.disabled = !state.fileId;
        btnReanalyze.disabled = false;
    }
}

function renderAnalysis(data) {
    analysisLoading.classList.add('hidden');
    currentAnalysis = data;
    const aois = (data.lesion_profile && (data.lesion_profile.aois || data.lesion_profile.lesions)) || [];
    selectedLesionId = aois[0] ? (aois[0].aoi_id || aois[0].lesion_id) : null;
    renderLegend(data);
    renderResultsTable(data);
    renderLesionCards(data);
    preloadOverlayImages(data);
    drawScan();
}

function renderLegend(data) {
    const items = [
        ['intensity', 'Intensity'],
        ['roughness', 'Roughness'],
        ['edges', 'Edges'],
        ['density', 'Density'],
    ];
    const maps = data.maps || {};
    let html = items
        .filter(([k]) => maps[k])
        .map(([k, label]) => `
            <div class="legend-item">
                <img src="data:image/png;base64,${maps[k]}" alt="${label}">
                <span>${label}</span>
            </div>
        `).join('');
    if (data.relevance && data.relevance.png) {
        const thr = Number(data.relevance.threshold || 0).toFixed(2);
        const method = data.relevance.threshold_method || 'otsu';
        html += `
            <div class="legend-item">
                <img src="data:image/png;base64,${data.relevance.png}" alt="Mass likelihood">
                <span>Mass likelihood · ${method} thr ${thr}</span>
            </div>
        `;
    }
    if (data.generated_mask && data.generated_mask.png) {
        const pct = Number(data.generated_mask.area_pct || 0).toFixed(2);
        html += `
            <div class="legend-item">
                <img src="data:image/png;base64,${data.generated_mask.png}" alt="Generated mass mask">
                <span>Generated mass mask · ${pct}% area</span>
            </div>
        `;
    }
    legendItems.innerHTML = html || '<div class="legend-empty">No maps returned.</div>';
}

function renderResultsTable(data) {
    const lp = data.lesion_profile || {};
    const pathologyLabel = lp.pathology_source === 'ground_truth'
        ? `Pathology: ${escapeHtml(lp.pathology || 'N/A')}`
        : `Risk: ${escapeHtml(lp.pathology || 'N/A')}`;
    resultsRow.innerHTML = `
        <td>${escapeHtml(lp.image_label || state.fileId || '—')}</td>
        <td>${escapeHtml(lp.is_there_an_aoi || lp.is_there_a_lesion || '—')}</td>
        <td>${lp.aoi_count ?? lp.lesion_count ?? '—'}</td>
        <td>${escapeHtml(lp.aoi_shape || lp.lesion_shape || 'N/A')}</td>
        <td>${escapeHtml(lp.aoi_margin || lp.lesion_margin || 'N/A')}</td>
        <td class="${pathologyClass(lp.pathology)}">${pathologyLabel}${lp.confidence != null ? ` (${(lp.confidence * 100).toFixed(0)}%)` : ''}</td>
    `;
}

function renderLesionCards(data) {
    const lesions = (data.lesion_profile && (data.lesion_profile.aois || data.lesion_profile.lesions)) || [];

    // ── Doctor's annotations (drawn in the viewer; browser-side only) ──
    const annHtml = annotations.length
        ? annotations.map(a => `
            <div class="doc-annot-row" style="--chip-color:${a.color}">
                <span class="annot-chip-dot"></span>
                <span class="doc-annot-id">${a.id}</span>
                <span class="doc-annot-type">${escapeHtml(a.label || a.type)}</span>
                <span class="doc-annot-kind">${ANNOT_GLYPH[a.kind]} ${a.kind}</span>
                <span class="doc-annot-size">${annotMeasure(a)}</span>
            </div>${a.note ? `<div class="doc-annot-note">📝 ${escapeHtml(a.note)}</div>` : ''}`).join('')
        : '<div class="aoi-none">No ROI annotations were drawn in the viewer.</div>';

    // ── System analysis — largest AOI only ──
    let sysHtml;
    if (!lesions.length) {
        sysHtml = '<div class="aoi-none">No AOI candidates detected by the system.</div>';
    } else {
        const largest = lesions.reduce((best, l) =>
            ((l.geometry && l.geometry.area_px) || 0) > ((best.geometry && best.geometry.area_px) || 0) ? l : best,
            lesions[0]);
        selectedLesionId = largest.aoi_id || largest.lesion_id;
        const compare = data.mask_comparison;
        const compareHtml = compare
            ? `<div class="mask-compare">Reference mask · Dice ${compare.dice_score?.toFixed?.(3) ?? '—'} · IoU ${compare.iou_score?.toFixed?.(3) ?? '—'}</div>`
            : '';
        sysHtml = compareHtml + systemAoiCard(largest, lesions.length);
    }

    lesionCards.innerHTML = `
        <div class="aoi-group">
            <div class="aoi-group-title">Doctor's annotations <span class="aoi-badge">${annotations.length}</span></div>
            <div class="doc-annot-list">${annHtml}</div>
        </div>
        <div class="aoi-group">
            <div class="aoi-group-title">System analysis · largest AOI</div>
            ${sysHtml}
        </div>`;

    const card = lesionCards.querySelector('.lesion-card');
    if (card) card.addEventListener('click', () => selectLesion(card.dataset.lesion, false));
}

function systemAoiCard(lesion, totalCount) {
    const css = lesion.crown_shyness || {};
    const geom = lesion.geometry || {};
    const aoiId = lesion.aoi_id || lesion.lesion_id;
    const interp = css.interpretation || 'ambiguous';
    const color = CSS_COLORS[interp] || NEUTRAL_COLOR;
    const conf = lesion.confidence != null ? `${(lesion.confidence * 100).toFixed(0)}%` : '—';
    const pillPrefix = lesion.pathology_source === 'ground_truth' ? 'Pathology' : 'Risk';
    const evidence = (lesion.margin_evidence || []).map(e => `<li>${escapeHtml(e)}</li>`).join('');
    const countNote = totalCount > 1
        ? `<div class="aoi-subnote">Largest of ${totalCount} detected AOIs.</div>`
        : '';
    return `
        <div class="lesion-card selected" data-lesion="${aoiId}" style="--lesion-color:${color}">
            <div class="lesion-card-head">
                <span class="lesion-id">${aoiId}</span>
                <span class="lesion-pill ${pathologyClass(lesion.pathology)}">${pillPrefix}: ${escapeHtml(lesion.pathology || 'N/A')} · ${conf}</span>
            </div>
            ${countNote}
            <dl class="lesion-kv">
                <dt>Shape</dt><dd>${escapeHtml(lesion.shape || 'N/A')}</dd>
                <dt>Margin</dt><dd>${escapeHtml(lesion.margin || 'N/A')}</dd>
                <dt>Area</dt><dd>${geom.area_px ?? '—'} px (${formatNum(geom.area_pct)}%)</dd>
                <dt>Bbox</dt><dd>${(geom.bbox || []).join(', ') || '—'}</dd>
                <dt>Centroid</dt><dd>${(geom.centroid || []).map(n => Math.round(n)).join(', ') || '—'}</dd>
                <dt>Circularity</dt><dd>${formatNum(geom.circularity)}</dd>
                <dt>Eccentricity</dt><dd>${formatNum(geom.eccentricity)}</dd>
                <dt>Solidity</dt><dd>${formatNum(geom.solidity)}</dd>
                <dt>Roughness</dt><dd>${formatNum(geom.contour_roughness)}</dd>
                <dt>Lobulation</dt><dd>${formatNum(geom.lobulation_index)}</dd>
                <dt>Spikes</dt><dd>${formatNum(geom.radial_spike_index)}</dd>
            </dl>
            <div class="lesion-kv-sep">Crown Shyness · boundary metrics</div>
            <dl class="lesion-kv">
                <dt>Score</dt><dd>${formatNum(css.raw_score)} <span class="lesion-interp">${escapeHtml(interp)}</span></dd>
                <dt>Sharpness</dt><dd>${formatNum(css.gradient_sharpness)}</dd>
                <dt>Halo σ</dt><dd>${formatNum(css.halo_width_std)}</dd>
                <dt>Entropy</dt><dd>${formatNum(css.transition_zone_entropy)}</dd>
                <dt>Visibility</dt><dd>${formatNum(css.boundary_visibility_ratio)}</dd>
                <dt>Dark ring</dt><dd>${css.radiolucent_halo_present ? 'yes' : 'no'}</dd>
            </dl>
            ${evidence ? `<div class="lesion-kv-sep">Margin evidence</div><ul class="lesion-evidence">${evidence}</ul>` : ''}
        </div>`;
}

function annotMeasure(a) {
    let w, h;
    if (a.kind === 'freehand') {
        const b = polygonBBox(a.points);
        w = b[2] - b[0]; h = b[3] - b[1];
    } else {
        w = Math.abs(a.x2 - a.x1); h = Math.abs(a.y2 - a.y1);
    }
    return `${Math.round(w)}×${Math.round(h)} px`;
}

function selectLesion(lesionId, scrollCard = true) {
    selectedLesionId = lesionId;
    lesionCards.querySelectorAll('.lesion-card').forEach(card => {
        const active = card.dataset.lesion === lesionId;
        card.classList.toggle('selected', active);
        if (active && scrollCard) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
    drawOverlays();
}

function preloadOverlayImages(data) {
    relevanceImageEl = null;
    maskImageEl = null;
    if (data.relevance && data.relevance.png) {
        const img = new Image();
        img.onload = () => { relevanceImageEl = img; drawOverlays(); };
        img.src = `data:image/png;base64,${data.relevance.png}`;
    }
    if (data.generated_mask && data.generated_mask.png) {
        const img = new Image();
        img.onload = () => { maskImageEl = img; drawOverlays(); };
        img.src = `data:image/png;base64,${data.generated_mask.png}`;
    }
}

function drawScan() {
    if (!state.fileId) return;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
        scanImageEl = img;
        const ctx = scanCanvas.getContext('2d');
        ctx.clearRect(0, 0, scanCanvas.width, scanCanvas.height);
        ctx.drawImage(img, 0, 0, scanCanvas.width, scanCanvas.height);
        drawOverlays();
    };
    img.onerror = () => {
        scanImageEl = null;
        const ctx = scanCanvas.getContext('2d');
        ctx.fillStyle = '#101018';
        ctx.fillRect(0, 0, scanCanvas.width, scanCanvas.height);
        drawOverlays();
    };
    img.src = `/api/files/${enc(state.fileId)}/image?ww=${state.ww}&wl=${state.wl}&_=${Date.now()}`;
}

function clearOverlays() {
    currentAnalysis = null;
    relevanceImageEl = null;
    maskImageEl = null;
    scanImageEl = null;
    selectedLesionId = null;
    const sc = scanCanvas.getContext('2d');
    sc.clearRect(0, 0, scanCanvas.width, scanCanvas.height);
    const oc = overlayCanvas.getContext('2d');
    oc.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
}

function drawOverlays() {
    const ctx = overlayCanvas.getContext('2d');
    ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    if (!currentAnalysis) return;

    const W = overlayCanvas.width, H = overlayCanvas.height;
    const size = currentAnalysis.generated_mask?.size || 512;
    const sx = W / size, sy = H / size;

    if (togRelevance.checked && relevanceImageEl) {
        ctx.globalAlpha = 0.40;
        ctx.drawImage(relevanceImageEl, 0, 0, W, H);
        ctx.globalAlpha = 1.0;
    }
    if (togMask.checked && maskImageEl) {
        ctx.globalCompositeOperation = 'lighter';
        ctx.globalAlpha = 0.35;
        ctx.drawImage(maskImageEl, 0, 0, W, H);
        ctx.globalAlpha = 1.0;
        ctx.globalCompositeOperation = 'source-over';
    }

    const lesions = (currentAnalysis.lesion_profile && (currentAnalysis.lesion_profile.aois || currentAnalysis.lesion_profile.lesions)) || [];
    // Focus the per-AOI overlay on the largest AOI — the one shown in the panel.
    const largest = lesions.length
        ? lesions.reduce((best, l) => ((l.geometry && l.geometry.area_px) || 0) > ((best.geometry && best.geometry.area_px) || 0) ? l : best, lesions[0])
        : null;
    [largest].filter(Boolean).forEach(lesion => {
        const aoiId = lesion.aoi_id || lesion.lesion_id;
        const interp = lesion.crown_shyness?.interpretation || 'ambiguous';
        const color = CSS_COLORS[interp] || NEUTRAL_COLOR;
        const isSelected = aoiId === selectedLesionId;

        if (togHalo.checked && Array.isArray(lesion.outline) && lesion.outline.length > 1) {
            ctx.beginPath();
            lesion.outline.forEach(([x, y], i) => {
                const px = x * sx, py = y * sy;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            });
            ctx.closePath();
            ctx.strokeStyle = color;
            ctx.lineWidth = isSelected ? 4 : 2.5;
            ctx.shadowColor = color;
            ctx.shadowBlur = isSelected ? 14 : 8;
            ctx.stroke();
            ctx.shadowBlur = 0;
        }

        if (togBboxes.checked && Array.isArray(lesion.geometry?.bbox)) {
            const [x1, y1, x2, y2] = lesion.geometry.bbox;
            ctx.strokeStyle = color;
            ctx.lineWidth = isSelected ? 3 : 1.5;
            ctx.setLineDash(isSelected ? [] : [6, 4]);
            ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
            ctx.setLineDash([]);

            ctx.fillStyle = color;
            ctx.font = '12px Inter, system-ui, sans-serif';
            ctx.fillText(aoiId, x1 * sx + 4, Math.max(12, y1 * sy - 4));
        }
    });

    // Doctor's ROI annotations carried over from the viewer (image-pixel → canvas)
    if (togAnnotations && togAnnotations.checked && annotations.length && dicomImg.naturalWidth) {
        drawDoctorAnnotations(ctx, W / dicomImg.naturalWidth, H / dicomImg.naturalHeight);
    }
}

function resetAnalysisUi() {
    if (analysisAbortController) {
        analysisAbortController.abort();
        analysisAbortController = null;
    }
    analysisRunning = false;
    analysisScreen.classList.add('hidden');
    analysisLoading.classList.add('hidden');
    analysisError.classList.add('hidden');
    analysisError.textContent = '';
    legendItems.innerHTML = '';
    lesionCards.innerHTML = '';
    resultsRow.innerHTML = '<td colspan="6" class="results-empty">Run an analysis to populate the AOI profile.</td>';
    clearOverlays();
    btnStartAnalysis.textContent = 'Start Analysis';
    btnStartAnalysis.classList.remove('running');
    btnStartAnalysis.disabled = false;
    btnReanalyze.disabled = false;
}

function pathologyClass(p) {
    if (p === 'malignant') return 'pathology-malignant';
    if (p === 'benign')    return 'pathology-benign';
    return 'pathology-na';
}

function formatNum(v) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return Number(v).toFixed(3);
}

function escapeHtml(str) {
    return String(str ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

/* ── Apply server response to viewer state ────────────────── */
function applyFileData(data) {
    resetAnalysisUi();
    resetAnnotations();
    state.fileId    = data.file_id;
    state.meta      = data.metadata || {};
    state.ww        = data.ww;        state.defaultWw = data.ww;
    state.wl        = data.wl;        state.defaultWl = data.wl;
    state.demoId    = data.demo_id || null;

    if (data.mask_file_id) {
        enableMask(data.mask_file_id, data.mask_ww, data.mask_wl, data.mask_ww, data.mask_wl);
    } else {
        disableMask();
    }

    setSaveStatus('Saved ✓', 'ok');
    fileLabel.textContent = data.label || data.file_id;
    btnStartAnalysis.disabled = false;
    btnStartAnalysis.textContent = 'Start Analysis';
    setTarget('base');
    resetViewTransforms();
    syncSliders();
    renderMeta(state.meta);
    uploadArea.style.display = 'none';
    workspace.classList.remove('hidden');
    annotBar.classList.remove('hidden');
    loadImage();
}

function enableMask(fileId, ww, wl, defWw, defWl) {
    state.maskFileId    = fileId;
    state.maskWw        = ww;    state.maskDefaultWw = defWw;
    state.maskWl        = wl;    state.maskDefaultWl = defWl;
    state.maskVisible   = true;
    maskControls.classList.remove('hidden');
    targetGroup.classList.remove('hidden');
    loadMaskImage();
}

function disableMask() {
    state.maskFileId = null;
    maskImg.style.display = 'none';
    maskControls.classList.add('hidden');
    targetGroup.classList.add('hidden');
    targetRing.className = 'target-ring hidden';
}

/* ── Target selector ──────────────────────────────────────── */
function setTarget(t) {
    state.target = t;
    btnTargetBase.classList.toggle('active', t === 'base');
    btnTargetMask.classList.toggle('active', t === 'mask');
    const v = t === 'base' ? viewBase : viewMask;
    btnInvert.classList.toggle('active', v.invert);
    if (state.maskFileId) targetRing.className = `target-ring ${t}`;
    else targetRing.className = 'target-ring hidden';
    syncSliders();
}
btnTargetBase.addEventListener('click', () => setTarget('base'));
btnTargetMask.addEventListener('click', () => setTarget('mask'));

/* ── Load base image from backend ─────────────────────────── */
let baseTimer = null;
function loadImage(ms = 0) {
    clearTimeout(baseTimer);
    baseTimer = setTimeout(() => {
        if (!state.fileId) return;
        showSpinner(true); hideError();
        dicomImg.src = `/api/files/${enc(state.fileId)}/image?ww=${state.ww}&wl=${state.wl}&_=${Date.now()}`;
    }, ms);
}
dicomImg.addEventListener('load', () => {
    showSpinner(false);
    if (viewBase.zoom === 1 && viewBase.x === 0 && viewBase.y === 0) fitViewToWindow(viewBase, dicomImg);
    applyTransform();
    updateOverlays();
    syncAnnotLayer();
});
dicomImg.addEventListener('error', () => {
    showSpinner(false);
    showError('Failed to render image — unsupported transfer syntax or corrupt file.');
});

/* ── Load mask image from backend ─────────────────────────── */
let maskTimer = null;
function loadMaskImage(ms = 0) {
    clearTimeout(maskTimer);
    maskTimer = setTimeout(() => {
        if (!state.maskFileId) return;
        maskImg.src = `/api/files/${enc(state.maskFileId)}/image?ww=${state.maskWw}&wl=${state.maskWl}&_=${Date.now()}`;
    }, ms);
}
maskImg.addEventListener('load', () => {
    maskImg.style.display = 'block';
    applyMaskStyle();
    if (viewMask.zoom === 1 && viewMask.x === 0 && viewMask.y === 0) fitViewToWindow(viewMask, maskImg);
    applyTransform();
});

/* ── Mask overlay style ───────────────────────────────────── */
function applyMaskStyle() {
    const opacity = parseInt(maskOpacity.value, 10) / 100;
    maskImg.style.opacity = state.maskVisible ? opacity : 0;
    maskImg.style.filter  = (MASK_FILTER[maskColorSel.value] || MASK_FILTER.green)
        + (viewMask.invert ? ' invert(1)' : '');
}
maskOpacity.addEventListener('input', () => {
    maskOpVal.textContent = `${maskOpacity.value}%`; applyMaskStyle();
});
maskColorSel.addEventListener('change', applyMaskStyle);
btnToggleMask.addEventListener('click', () => {
    state.maskVisible = !state.maskVisible;
    btnToggleMask.textContent = state.maskVisible ? 'Hide mask' : 'Show mask';
    btnToggleMask.classList.toggle('active', !state.maskVisible);
    applyMaskStyle();
});

/* ── Independent transforms per image ────────────────────── */
function applyTransform() {
    const b = viewBase;
    const m = viewMask;
    const baseT = `translate(calc(-50% + ${b.x}px), calc(-50% + ${b.y}px)) rotate(${b.angle}deg) scale(${b.zoom * b.flipH}, ${b.zoom * b.flipV})`;
    dicomImg.style.transform = baseT;
    dicomImg.style.filter    = b.invert ? 'invert(1)' : '';
    if (annotLayer) annotLayer.style.transform = baseT;   // ROI layer tracks the base image
    maskImg.style.transform  = `translate(calc(-50% + ${m.x}px), calc(-50% + ${m.y}px)) rotate(${m.angle}deg) scale(${m.zoom * m.flipH}, ${m.zoom * m.flipV})`;
}

function fitViewToWindow(v, img) {
    if (!img.naturalWidth) return;
    const rotated = v.angle % 180 !== 0;
    const iw = rotated ? img.naturalHeight : img.naturalWidth;
    const ih = rotated ? img.naturalWidth  : img.naturalHeight;
    v.zoom = Math.min(
        (canvasContainer.clientWidth  * 0.96) / iw,
        (canvasContainer.clientHeight * 0.96) / ih
    );
    v.x = 0; v.y = 0;
}

function fitToWindow() {
    const v   = getActiveView();
    const img = state.target === 'mask' && state.maskFileId ? maskImg : dicomImg;
    fitViewToWindow(v, img);
    applyTransform(); updateOverlays();
}

function resetViewTransforms() {
    Object.assign(viewBase, { x:0, y:0, zoom:1, angle:0, flipH:1, flipV:1, invert:false });
    Object.assign(viewMask, { x:0, y:0, zoom:1, angle:0, flipH:1, flipV:1, invert:false });
    btnInvert.classList.remove('active');
    applyTransform();
}

/* ── Mouse: pan / W-L drag ────────────────────────────────── */
let isDragging = false;
let drag = {};

canvasContainer.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    e.preventDefault();

    // ROI annotation drawing takes priority over navigation
    if (annotTool) { annotStart(e); return; }
    // In pan mode, clicking an existing ROI selects it (instead of panning);
    // clicking empty space clears the current selection.
    if (activeTool === 'pan') {
        const p = clientToImage(e.clientX, e.clientY);
        const hit = p ? annotAt(p) : null;
        if (hit) { selectAnnot(hit.id); return; }
        if (selectedAnnotId) { selectedAnnotId = null; renderAnnots(); renderAnnotChips(); }
    }

    isDragging = true;
    const v = getActiveView();
    drag = {
        mx: e.clientX,    my: e.clientY,
        vx: v.x,          vy: v.y,
        ww: state.ww,     wl: state.wl,
        mww: state.maskWw, mwl: state.maskWl,
    };
    canvasContainer.classList.add('dragging');
});
window.addEventListener('mousemove', e => {
    if (isDrawingAnnot) { annotMove(e); return; }
    if (!isDragging) return;
    const dx = e.clientX - drag.mx;
    const dy = e.clientY - drag.my;
    if (activeTool === 'pan') {
        const v = getActiveView();
        v.x = drag.vx + dx; v.y = drag.vy + dy;
        applyTransform(); updateOverlays();
    } else {
        if (state.target === 'base') {
            state.wl = Math.round(drag.wl + dx * 2);
            state.ww = Math.max(1, Math.round(drag.ww - dy * 4));
            syncSliders(); updateOverlays(); loadImage(120);
        } else {
            state.maskWl = Math.round(drag.mwl + dx * 2);
            state.maskWw = Math.max(1, Math.round(drag.mww - dy * 4));
            syncSliders(); loadMaskImage(120);
        }
    }
});
window.addEventListener('mouseup', () => {
    if (isDrawingAnnot) annotEnd();
    isDragging = false; canvasContainer.classList.remove('dragging');
});

canvasContainer.addEventListener('wheel', e => {
    e.preventDefault();
    const v = getActiveView();
    v.zoom = Math.min(Math.max(v.zoom * (e.deltaY < 0 ? 1.1 : 0.9), 0.05), 20);
    applyTransform(); updateOverlays();
}, { passive: false });

canvasContainer.addEventListener('dblclick', fitToWindow);

/* ── Toolbar: mode + transforms ───────────────────────────── */
btnPan.addEventListener('click', () => {
    activeTool = 'pan';
    btnPan.classList.add('active'); btnWL.classList.remove('active');
    canvasContainer.classList.remove('wl-mode');
    clearAnnotTool();
});
btnWL.addEventListener('click', () => {
    activeTool = 'wl';
    btnWL.classList.add('active'); btnPan.classList.remove('active');
    canvasContainer.classList.add('wl-mode');
    clearAnnotTool();
});

btnInvert.addEventListener('click', () => {
    const v = getActiveView();
    v.invert = !v.invert;
    btnInvert.classList.toggle('active', v.invert);
    if (state.target === 'base') applyTransform();
    else applyMaskStyle();
});

btnRotCCW.addEventListener('click', () => { getActiveView().angle = (getActiveView().angle - 90 + 360) % 360; applyTransform(); fitToWindow(); });
btnRotCW.addEventListener('click',  () => { getActiveView().angle = (getActiveView().angle + 90)        % 360; applyTransform(); fitToWindow(); });
btnFlipH.addEventListener('click',  () => { getActiveView().flipH *= -1; applyTransform(); });
btnFlipV.addEventListener('click',  () => { getActiveView().flipV *= -1; applyTransform(); });
btnFit.addEventListener('click', fitToWindow);
btnReset.addEventListener('click', () => {
    Object.assign(viewBase, { x:0, y:0, zoom:1, angle:0, flipH:1, flipV:1, invert:false });
    Object.assign(viewMask, { x:0, y:0, zoom:1, angle:0, flipH:1, flipV:1, invert:false });
    btnInvert.classList.remove('active');
    if (dicomImg.naturalWidth) fitViewToWindow(viewBase, dicomImg);
    if (state.maskFileId && maskImg.naturalWidth) fitViewToWindow(viewMask, maskImg);
    applyTransform(); updateOverlays();
    state.ww = state.defaultWw; state.wl = state.defaultWl;
    state.maskWw = state.maskDefaultWw; state.maskWl = state.maskDefaultWl;
    syncSliders();
    loadImage(); if (state.maskFileId) loadMaskImage();
});

/* ── WW/WL sliders — routed to current target ─────────────── */
wwSlider.addEventListener('input', () => {
    const v = parseInt(wwSlider.value, 10); wwVal.textContent = v;
    if (state.target === 'base') { state.ww = v; updateOverlays(); loadImage(200); }
    else                         { state.maskWw = v; loadMaskImage(200); }
});
wlSlider.addEventListener('input', () => {
    const v = parseInt(wlSlider.value, 10); wlVal.textContent = v;
    if (state.target === 'base') { state.wl = v; updateOverlays(); loadImage(200); }
    else                         { state.maskWl = v; loadMaskImage(200); }
});
btnAutoWwwl.addEventListener('click', () => {
    if (state.target === 'base') {
        state.ww = state.defaultWw; state.wl = state.defaultWl;
        syncSliders(); updateOverlays(); loadImage();
    } else {
        state.maskWw = state.maskDefaultWw; state.maskWl = state.maskDefaultWl;
        syncSliders(); loadMaskImage();
    }
});

function syncSliders() {
    const ww = state.target === 'base' ? state.ww : state.maskWw;
    const wl = state.target === 'base' ? state.wl : state.maskWl;
    wwSlider.value    = Math.min(Math.max(ww, 1), 4096);
    wlSlider.value    = Math.min(Math.max(wl, -1024), 3071);
    wwVal.textContent = Math.round(ww);
    wlVal.textContent = Math.round(wl);
}

/* ── Corner overlays ──────────────────────────────────────── */
function updateOverlays() {
    const { meta } = state;
    const ww = state.target === 'base' ? state.ww : state.maskWw;
    const wl = state.target === 'base' ? state.wl : state.maskWl;
    const v  = getActiveView();
    ovTL.innerHTML = [
        meta['Patient Name'] && `<div>${meta['Patient Name']}</div>`,
        meta['Patient ID']   && `<div>ID: ${meta['Patient ID']}</div>`,
        meta['Modality']     && `<div>${meta['Modality']}</div>`,
    ].filter(Boolean).join('');
    ovTR.innerHTML = [
        meta['Study Date']         && `<div>${fmtDate(meta['Study Date'])}</div>`,
        meta['Series Description'] && `<div>${meta['Series Description']}</div>`,
    ].filter(Boolean).join('');
    ovBL.innerHTML = dicomImg.naturalWidth
        ? `<div>${dicomImg.naturalWidth} × ${dicomImg.naturalHeight} px</div>` : '';
    ovBR.innerHTML = `<div>WW ${Math.round(ww)} / WL ${Math.round(wl)}</div>`
                   + `<div>Zoom ${Math.round(v.zoom * 100)}%</div>`;
}
function fmtDate(d) {
    return d && d.length >= 8 ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}` : d;
}

/* ── Metadata panel ───────────────────────────────────────── */
let metaOpen = false;
metaToggle.addEventListener('click', () => {
    metaOpen = !metaOpen;
    metaGrid.classList.toggle('hidden', !metaOpen);
    metaArrow.textContent = metaOpen ? '▴' : '▾';
});
function renderMeta(meta) {
    const entries = Object.entries(meta).filter(([, v]) => v);
    metaToggle.style.display = entries.length ? '' : 'none';
    metaGrid.innerHTML = entries
        .map(([k, v]) => `<div class="meta-key">${k}</div><div class="meta-val">${v}</div>`)
        .join('');
}

/* ── Helpers ──────────────────────────────────────────────── */
const enc = s => encodeURIComponent(s);
function showSpinner(on) { spinnerWrap.classList.toggle('hidden', !on); }
function hideError()     { imgError.classList.add('hidden'); imgError.textContent = ''; }
function showError(msg)  { imgError.textContent = msg; imgError.classList.remove('hidden'); }
function setSaveStatus(msg, cls) {
    saveStatus.textContent = msg;
    saveStatus.className   = `save-status ${cls}`;
}

/* ══════════════════════════════════════════════════════════════════
   Doctor annotations (ROI) — the viewer's "second window" markup layer

   Three region tools radiologists rely on, each defining an Area of
   Interest the system analysis can reason about:
     • Box      — rectangle ROI, fast localisation of a finding
     • Ellipse  — circle/oval ROI, natural for rounded masses & density
     • Trace    — freehand polygon, for tracing irregular margins

   Shapes are stored in base-image pixel coordinates, so they stay pinned
   to anatomy through pan / zoom / rotate / flip, and map 1:1 onto the
   analysis canvas. Everything lives in the browser; no API/info transfer.
   ══════════════════════════════════════════════════════════════════ */

const ANNOT_COLORS = {
    'Mass':             '#f5a524',
    'Calcification':    '#38bdf8',
    'Asymmetry':        '#a78bfa',
    'Arch. distortion': '#fb7185',
    'Other':            '#34d399',
};
const ANNOT_GLYPH = { rect: '▭', ellipse: '◯', freehand: '✎' };

let annotTool      = null;   // null | 'rect' | 'ellipse' | 'freehand'
let annotations    = [];     // committed ROIs, in base-image pixel coords
let annotDraft     = null;   // in-progress ROI
let isDrawingAnnot = false;
let selectedAnnotId = null;
let annotSeq       = 0;
let annotFont      = 24;     // SVG label size in image-pixel units

/* ── Tool selection ───────────────────────────────────────── */
function setAnnotTool(tool) {
    if (annotTool === tool) { clearAnnotTool(); return; }
    annotTool = tool;
    [['rect', btnAnnotRect], ['ellipse', btnAnnotEll], ['freehand', btnAnnotFree]]
        .forEach(([t, btn]) => btn.classList.toggle('annot-active', t === tool));
    canvasContainer.classList.add('annot-mode');
    updateAnnotHint();
}
function clearAnnotTool() {
    annotTool = null;
    [btnAnnotRect, btnAnnotEll, btnAnnotFree].forEach(b => b.classList.remove('annot-active'));
    canvasContainer.classList.remove('annot-mode');
    updateAnnotHint();
}

btnAnnotRect.addEventListener('click', () => setAnnotTool('rect'));
btnAnnotEll.addEventListener('click',  () => setAnnotTool('ellipse'));
btnAnnotFree.addEventListener('click', () => setAnnotTool('freehand'));
btnAnnotUndo.addEventListener('click', undoAnnot);
btnAnnotClear.addEventListener('click', clearAnnots);

/* ── Coordinate mapping: screen → base-image pixels ───────── */
function clientToImage(clientX, clientY) {
    const ctm = annotLayer.getScreenCTM();
    if (!ctm) return null;
    const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
}

/* ── Size the SVG layer to the base image's natural pixels ─── */
function syncAnnotLayer() {
    const nw = dicomImg.naturalWidth, nh = dicomImg.naturalHeight;
    if (!nw || !nh) return;
    annotLayer.setAttribute('viewBox', `0 0 ${nw} ${nh}`);
    annotLayer.setAttribute('width', nw);
    annotLayer.setAttribute('height', nh);
    annotLayer.style.width  = `${nw}px`;
    annotLayer.style.height = `${nh}px`;
    annotFont = Math.max(12, Math.round(Math.max(nw, nh) * 0.018));
    annotLayer.style.transform = dicomImg.style.transform;
    annotLayer.classList.remove('hidden');
    renderAnnots();
}

/* ── Drawing lifecycle ────────────────────────────────────── */
function annotStart(e) {
    const p = clientToImage(e.clientX, e.clientY);
    if (!p) return;
    isDrawingAnnot = true;
    const type  = annotType.value;
    const color = ANNOT_COLORS[type] || '#9aa';
    annotDraft = annotTool === 'freehand'
        ? { kind: 'freehand', type, color, label: '', note: '', points: [[p.x, p.y]] }
        : { kind: annotTool, type, color, label: '', note: '', x1: p.x, y1: p.y, x2: p.x, y2: p.y };
    renderAnnots();
}
function annotMove(e) {
    if (!annotDraft) return;
    const p = clientToImage(e.clientX, e.clientY);
    if (!p) return;
    if (annotDraft.kind === 'freehand') {
        const last = annotDraft.points[annotDraft.points.length - 1];
        if (!last || Math.hypot(p.x - last[0], p.y - last[1]) > 1.5) annotDraft.points.push([p.x, p.y]);
    } else {
        annotDraft.x2 = p.x; annotDraft.y2 = p.y;
    }
    renderAnnots();
}
function annotEnd() {
    isDrawingAnnot = false;
    const d = annotDraft;
    annotDraft = null;
    if (!d) return;

    let ok;
    if (d.kind === 'freehand') {
        ok = d.points.length >= 3 && polygonExtent(d.points) > 6;
    } else {
        const x1 = Math.min(d.x1, d.x2), x2 = Math.max(d.x1, d.x2);
        const y1 = Math.min(d.y1, d.y2), y2 = Math.max(d.y1, d.y2);
        d.x1 = x1; d.y1 = y1; d.x2 = x2; d.y2 = y2;
        ok = (x2 - x1) > 4 && (y2 - y1) > 4;
    }
    if (!ok) { renderAnnots(); return; }   // discard tiny accidental clicks

    d.id = `A${++annotSeq}`;
    annotations.push(d);
    selectedAnnotId = d.id;
    renderAnnots();
    renderAnnotChips();
    updateAnnotButtons();
}

/* ── SVG rendering ────────────────────────────────────────── */
function renderAnnots() {
    if (!annotLayer) return;
    const all = annotDraft ? annotations.concat([annotDraft]) : annotations;
    annotLayer.innerHTML = all.map(a => shapeSvg(a, a.id && a.id === selectedAnnotId)).join('');
}
function shapeSvg(a, sel) {
    const sw  = sel ? 3 : 2;
    const cls = sel ? ' class="annot-sel"' : '';
    let body = '', lx = 0, ly = 0;

    if (a.kind === 'rect') {
        const x = Math.min(a.x1, a.x2), y = Math.min(a.y1, a.y2);
        const w = Math.abs(a.x2 - a.x1), h = Math.abs(a.y2 - a.y1);
        body = `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${a.color}" fill-opacity="0.10" stroke="${a.color}" stroke-width="${sw}" vector-effect="non-scaling-stroke"${cls}/>`;
        lx = x; ly = y;
    } else if (a.kind === 'ellipse') {
        const cx = (a.x1 + a.x2) / 2, cy = (a.y1 + a.y2) / 2;
        const rx = Math.abs(a.x2 - a.x1) / 2, ry = Math.abs(a.y2 - a.y1) / 2;
        body = `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${a.color}" fill-opacity="0.10" stroke="${a.color}" stroke-width="${sw}" vector-effect="non-scaling-stroke"${cls}/>`;
        lx = cx - rx; ly = cy - ry;
    } else {
        const pts  = a.points.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
        const open = isDrawingAnnot && a === annotDraft;
        const tag  = open ? 'polyline' : 'polygon';
        const fill = open ? 'fill="none"' : `fill="${a.color}" fill-opacity="0.10"`;
        body = `<${tag} points="${pts}" ${fill} stroke="${a.color}" stroke-width="${sw}" stroke-linejoin="round" vector-effect="non-scaling-stroke"${cls}/>`;
        const bb = polygonBBox(a.points); lx = bb[0]; ly = bb[1];
    }

    if (!a.id) return body;   // draft has no label yet
    const base = a.label ? `${a.id} · ${a.label}` : `${a.id} · ${a.type}`;
    const text = a.note ? `${base} 📝` : base;
    const ty = ly - annotFont * 0.4;
    const label = `<text x="${lx}" y="${ty}" font-size="${annotFont}" fill="${a.color}" stroke="#000" stroke-width="${annotFont * 0.06}" paint-order="stroke" font-family="Inter, system-ui, sans-serif" font-weight="700">${escapeHtml(text)}</text>`;
    return body + label;
}

/* ── Geometry helpers ─────────────────────────────────────── */
function polygonBBox(points) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const [x, y] of points) {
        if (x < minX) minX = x; if (y < minY) minY = y;
        if (x > maxX) maxX = x; if (y > maxY) maxY = y;
    }
    return [minX, minY, maxX, maxY];
}
function polygonExtent(points) {
    const b = polygonBBox(points);
    return Math.hypot(b[2] - b[0], b[3] - b[1]);
}
function pointInPolygon(p, pts) {
    let inside = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
        const xi = pts[i][0], yi = pts[i][1], xj = pts[j][0], yj = pts[j][1];
        const hit = ((yi > p.y) !== (yj > p.y)) &&
                    (p.x < (xj - xi) * (p.y - yi) / ((yj - yi) || 1e-9) + xi);
        if (hit) inside = !inside;
    }
    return inside;
}
function annotAt(p) {
    for (let i = annotations.length - 1; i >= 0; i--) {
        if (pointInAnnot(annotations[i], p)) return annotations[i];
    }
    return null;
}
function pointInAnnot(a, p) {
    if (a.kind === 'rect') {
        return p.x >= Math.min(a.x1, a.x2) && p.x <= Math.max(a.x1, a.x2) &&
               p.y >= Math.min(a.y1, a.y2) && p.y <= Math.max(a.y1, a.y2);
    }
    if (a.kind === 'ellipse') {
        const cx = (a.x1 + a.x2) / 2, cy = (a.y1 + a.y2) / 2;
        const rx = Math.abs(a.x2 - a.x1) / 2 || 1, ry = Math.abs(a.y2 - a.y1) / 2 || 1;
        return ((p.x - cx) ** 2) / (rx * rx) + ((p.y - cy) ** 2) / (ry * ry) <= 1;
    }
    return pointInPolygon(p, a.points);
}

/* ── Selection / edit / remove ────────────────────────────── */
function selectAnnot(id) {
    selectedAnnotId = id;
    renderAnnots();
    renderAnnotChips();
}
function deleteAnnot(id) {
    annotations = annotations.filter(a => a.id !== id);
    if (selectedAnnotId === id) selectedAnnotId = null;
    renderAnnots(); renderAnnotChips(); updateAnnotButtons();
}
function undoAnnot() {
    const last = annotations.pop();
    if (last && selectedAnnotId === last.id) selectedAnnotId = null;
    renderAnnots(); renderAnnotChips(); updateAnnotButtons();
}
function clearAnnots() {
    if (!annotations.length) return;
    annotations = []; selectedAnnotId = null;
    renderAnnots(); renderAnnotChips(); updateAnnotButtons();
}
function renameAnnot(id) {
    const a = annotations.find(x => x.id === id);
    if (!a) return;
    const v = window.prompt(`Label for ${a.id} (${a.type}):`, a.label || '');
    if (v === null) return;
    a.label = v.trim();
    renderAnnots(); renderAnnotChips();
}

const ANNOT_NOTE_MAX = 100;   // doctor notes are short; capped here and server-side
function noteAnnot(id) {
    const a = annotations.find(x => x.id === id);
    if (!a) return;
    const v = window.prompt(
        `Note for ${a.id} (${a.label || a.type}) — up to ${ANNOT_NOTE_MAX} characters:`,
        a.note || ''
    );
    if (v === null) return;
    a.note = v.trim().slice(0, ANNOT_NOTE_MAX);
    renderAnnots(); renderAnnotChips();
}

/* ── Chips list under the viewer ──────────────────────────── */
function renderAnnotChips() {
    annotChips.innerHTML = annotations.length
        ? annotations.map(a => `
            <span class="annot-chip${a.id === selectedAnnotId ? ' selected' : ''}" data-id="${a.id}" style="--chip-color:${a.color}" title="${a.note ? escapeHtml(a.note) : 'Double-click to label · 📝 to add a note'}">
                <span class="annot-chip-dot"></span>
                <span class="annot-chip-label">${a.id}</span>
                <span class="annot-chip-kind">${escapeHtml(a.label || a.type)} · ${ANNOT_GLYPH[a.kind]}</span>
                ${a.note ? `<span class="annot-chip-note-text">📝 ${escapeHtml(a.note)}</span>` : ''}
                <button class="annot-chip-note" data-note="${a.id}" title="Add / edit note">📝</button>
                <button class="annot-chip-del" data-del="${a.id}" title="Delete">×</button>
            </span>`).join('')
        : '<span class="annot-empty">No annotations yet.</span>';

    annotChips.querySelectorAll('.annot-chip').forEach(chip => {
        chip.addEventListener('click', e => {
            if (e.target.closest('.annot-chip-del') || e.target.closest('.annot-chip-note')) return;
            selectAnnot(chip.dataset.id);
        });
        chip.addEventListener('dblclick', () => renameAnnot(chip.dataset.id));
    });
    annotChips.querySelectorAll('.annot-chip-note').forEach(btn => {
        btn.addEventListener('click', e => { e.stopPropagation(); noteAnnot(btn.dataset.note); });
    });
    annotChips.querySelectorAll('.annot-chip-del').forEach(btn => {
        btn.addEventListener('click', e => { e.stopPropagation(); deleteAnnot(btn.dataset.del); });
    });
    updateAnnotHint();
}
function updateAnnotButtons() {
    const has = annotations.length > 0;
    btnAnnotUndo.disabled  = !has;
    btnAnnotClear.disabled = !has;
}
function updateAnnotHint() {
    if (annotTool) {
        const names = { rect: 'Box', ellipse: 'Ellipse', freehand: 'Trace' };
        annotHint.textContent = `${names[annotTool]} tool active — drag on the image to draw. Esc cancels.`;
    } else if (annotations.length) {
        annotHint.textContent = 'Click a chip or shape to select · Del removes · double-click a chip to label · 📝 adds a note.';
    } else {
        annotHint.textContent = 'Choose Box, Ellipse, or Trace, then drag on the image.';
    }
}
function resetAnnotations() {
    annotations = [];
    annotDraft = null;
    isDrawingAnnot = false;
    selectedAnnotId = null;
    annotSeq = 0;
    clearAnnotTool();
    if (annotLayer) annotLayer.innerHTML = '';
    renderAnnotChips();
    updateAnnotButtons();
}

/* ── Keyboard: Del removes selection, Esc cancels draw/tool ─ */
window.addEventListener('keydown', e => {
    const tag = document.activeElement && document.activeElement.tagName;
    if (/INPUT|TEXTAREA|SELECT/.test(tag || '')) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedAnnotId && !workspace.classList.contains('hidden')) {
            e.preventDefault();
            deleteAnnot(selectedAnnotId);
        }
    } else if (e.key === 'Escape') {
        if (isDrawingAnnot) { isDrawingAnnot = false; annotDraft = null; renderAnnots(); }
        else clearAnnotTool();
    }
});

/* ── Carry ROIs onto the analysis overlay canvas ──────────── */
function drawDoctorAnnotations(ctx, sx, sy) {
    ctx.save();
    ctx.lineWidth = 2;
    ctx.font = '12px Inter, system-ui, sans-serif';
    for (const a of annotations) {
        ctx.strokeStyle = a.color;
        ctx.fillStyle   = a.color;
        ctx.setLineDash([5, 3]);   // dashed → visibly the doctor's mark vs. the system's solid outlines
        let lx, ly;
        if (a.kind === 'rect') {
            const x = Math.min(a.x1, a.x2) * sx, y = Math.min(a.y1, a.y2) * sy;
            ctx.strokeRect(x, y, Math.abs(a.x2 - a.x1) * sx, Math.abs(a.y2 - a.y1) * sy);
            lx = x; ly = y;
        } else if (a.kind === 'ellipse') {
            const cx = (a.x1 + a.x2) / 2 * sx, cy = (a.y1 + a.y2) / 2 * sy;
            const rx = Math.abs(a.x2 - a.x1) / 2 * sx, ry = Math.abs(a.y2 - a.y1) / 2 * sy;
            ctx.beginPath();
            ctx.ellipse(cx, cy, Math.max(rx, 0.5), Math.max(ry, 0.5), 0, 0, Math.PI * 2);
            ctx.stroke();
            lx = cx - rx; ly = cy - ry;
        } else {
            ctx.beginPath();
            a.points.forEach((p, i) => {
                const X = p[0] * sx, Y = p[1] * sy;
                if (i) ctx.lineTo(X, Y); else ctx.moveTo(X, Y);
            });
            ctx.closePath();
            ctx.stroke();
            const bb = polygonBBox(a.points); lx = bb[0] * sx; ly = bb[1] * sy;
        }
        ctx.setLineDash([]);
        const base = a.label ? `${a.id} · ${a.label}` : `${a.id} · ${a.type}`;
        const text = a.note ? `${base} 📝` : base;
        const tx = lx + 2, tyy = Math.max(11, ly - 3);
        ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(0,0,0,.75)';
        ctx.strokeText(text, tx, tyy);
        ctx.fillStyle = a.color;
        ctx.fillText(text, tx, tyy);
        ctx.lineWidth = 2;
    }
    ctx.restore();
}
