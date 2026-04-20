/**
 * AeroDynaSim v2 — Frontend with Tab Navigation
 * Real car customization with 23 geometric parameters
 */

// ============================================================================
// STATE
// ============================================================================

const state = {
    currentTab: 'body-type',
    selectedBodyType: null,
    selectedTrack: null,
    currentParams: {},
    stockParams: {},
    underbody: 'S',
    wheels: 'WWC',
    presets: [],
    paramDefs: [],
    results: null,
    vizAnimationId: null,
    vizPlaying: false,
    vizPresetIdx: 0,
    vizPresetIdx2: -1,
    simTime: 0,
    timelines: {},
    lastLapTime: null,   // seconds — set after simulation, improves sensitivity accuracy
};

// Three.js State
let scene = null;
let camera = null;
let renderer = null;
let carGroup = null;
let carMesh = null; // Will hold the future STL model

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    await loadParamDefs();
    await loadBodyTypes();
    await loadTracks();
});

async function loadParamDefs() {
    try {
        const res = await fetch('/api/param_defs');
        state.paramDefs = await res.json();
    } catch (e) {
        console.error('Failed to load parameter definitions:', e);
    }
}

async function loadBodyTypes() {
    try {
        const res = await fetch('/api/templates');
        const bodyTypes = await res.json();
        state.bodyTypes = bodyTypes;   // cache it
        renderBodyTypeGrid(bodyTypes);
    } catch (e) {
        console.error('Failed to load body types:', e);
    }
}

async function loadTracks() {
    try {
        const res = await fetch('/api/tracks');
        state.tracks = await res.json();
        renderTrackGrid();
    } catch (e) {
        console.error('Failed to load tracks:', e);
    }
}

// ============================================================================
// TAB NAVIGATION
// ============================================================================

function switchTab(tabName) {
    state.currentTab = tabName;

    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // Update content panels
    document.querySelectorAll('.tab-content').forEach(panel => {
        panel.classList.toggle('active', panel.id === `tab-${tabName}`);
    });

    // Re-size 3D renderer after tab becomes visible (layout may have changed)
    if (tabName === 'customize' && renderer) {
        requestAnimationFrame(() => {
            const container = document.getElementById('car3dCanvas');
            if (container && container.clientWidth > 0) {
                renderer.setSize(container.clientWidth, container.clientHeight);
                camera.aspect = container.clientWidth / container.clientHeight;
                camera.updateProjectionMatrix();
            }
        });
    }
}

// ============================================================================
// BODY TYPE SELECTION
// ============================================================================

function renderBodyTypeGrid(bodyTypes) {
    const grid = document.getElementById('bodyTypeGrid');
    grid.innerHTML = bodyTypes.map(bt => `
        <div class="body-card" onclick="selectBodyType('${bt.body_code}')" id="body-${bt.body_code}">
            <div class="body-icon">${bt.icon}</div>
            <div class="body-name">${bt.name}</div>
            <div class="body-stats">
                <div class="stat">Cd: <span class="val">${bt.cd}</span></div>
                <div class="stat">Cl_f: <span class="val">${bt.cl_f}</span></div>
                <div class="stat">Cl_r: <span class="val">${bt.cl_r}</span></div>
            </div>
        </div>
    `).join('');
}

function selectBodyType(bodyCode) {
    // Use cached body types — no fetch needed
    const bodyTypes = state.bodyTypes || [];
    const bt = bodyTypes.find(b => b.body_code === bodyCode);
    if (!bt) {
        // Fallback: fetch if cache is empty
        fetch('/api/templates').then(r => r.json()).then(bts => {
            state.bodyTypes = bts;
            selectBodyType(bodyCode);
        });
        return;
    }

    state.selectedBodyType = bt;
    state.currentParams = { ...bt.params };
    state.stockParams = { ...bt.params };
    state.underbody = 'S';
    state.wheels = 'WWC';

    // Reset categorical dropdowns
    const ubSel = document.getElementById('underbodySelect');
    const wSel = document.getElementById('wheelsSelect');
    if (ubSel) ubSel.value = 'S';
    if (wSel) wSel.value = 'WWC';

    // Update UI
    document.querySelectorAll('.body-card').forEach(c => c.classList.remove('selected'));
    const card = document.getElementById(`body-${bodyCode}`);
    if (card) card.classList.add('selected');

    // Initialize presets with stock
    state.presets = [{
        name: 'Stock',
        params: { ...bt.params },
        underbody: 'S',
        wheels: 'WWC',
        isStock: true,
    }];

    renderParameterGroups();
    renderPresetList();
    updateSimulateButton();

    // Switch to customize tab
    switchTab('customize');

    // Wait for layout then init 3D
    setTimeout(() => {
        if (!scene) init3DCar();
        update3DCar();
        updateLocalSensitivity();
    }, 150);
}

// ============================================================================
// 3D CAR VISUALIZER
// ============================================================================

function init3DCar() {
    try {
        const container = document.getElementById('car3dCanvas');
        if (!container || typeof THREE === "undefined") return;

        const W = container.clientWidth  || 600;
        const H = container.clientHeight || 400;

        scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0a0a12);

        // Lighting
        scene.add(new THREE.AmbientLight(0x334466, 1.2));
        const key = new THREE.DirectionalLight(0xffffff, 2.5);
        key.position.set(4, 7, 3);
        key.castShadow = true;
        scene.add(key);
        const fill = new THREE.DirectionalLight(0x4466bb, 0.8);
        fill.position.set(-5, 3, 2);
        scene.add(fill);
        const rim = new THREE.DirectionalLight(0xff3300, 1.0);
        rim.position.set(0, 3, -6);
        scene.add(rim);

        // ── Camera ──────────────────────────────────────────────────
        camera = new THREE.PerspectiveCamera(42, W / H, 0.1, 100);
        camera.position.set(3.5, 2.0, -3.5);
        camera.lookAt(0, 0.5, 0);

        // ── Renderer ────────────────────────────────────────────────
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
        renderer.setSize(W, H);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.shadowMap.enabled = true;
        container.innerHTML = '';
        container.appendChild(renderer.domElement);

        // ── Floor ───────────────────────────────────────────────────
        const floorMat = new THREE.MeshStandardMaterial({
            color: 0x0d0d14,
            metalness: 0.7,
            roughness: 0.45,
        });
        const floor = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), floorMat);
        floor.rotation.x = -Math.PI / 2;
        floor.receiveShadow = true;
        scene.add(floor);

        const grid = new THREE.GridHelper(12, 16, 0x1a1a2a, 0x111118);
        grid.position.y = 0.002;
        scene.add(grid);

        // ── Controls ────────────────────────────────────────────────
        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping  = true;
        controls.dampingFactor  = 0.06;
        controls.target.set(0, 0.5, 0);
        controls.minDistance    = 2;
        controls.maxDistance    = 12;
        controls.maxPolarAngle  = Math.PI / 2.1;

        carGroup = new THREE.Group();
        scene.add(carGroup);

        const animate = () => {
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        };
        animate();

        window.addEventListener('resize', () => {
            if (!container || !renderer) return;
            camera.aspect = container.clientWidth / container.clientHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(container.clientWidth, container.clientHeight);
        });
    } catch (e) {
        console.error("ThreeJS initialization failed:", e);
    }
}

let lastStlUrl = null;
let stlLoadTimeout = null;
let deformTimeout = null;

// Stock (baseline) parameter values — populated when first STL loads
let stockParams3D = null;

function update3DCar() {
    // Debounced: fetch local sensitivity + closest real STL mesh together
    if (stlLoadTimeout) clearTimeout(stlLoadTimeout);
    stlLoadTimeout = setTimeout(async () => {
        await Promise.all([
            loadClosestSTL(),
            updateLocalSensitivity(),
        ]);
    }, 300);
}

async function updateLocalSensitivity() {
    if (!state.selectedBodyType) return;
    try {
        const res = await fetch('/api/local_sensitivity', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                params:    state.currentParams,
                body_code: state.selectedBodyType.body_code,
                underbody: state.underbody,
                wheels:    state.wheels,
                lap_time:  state.lastLapTime,  // null before sim → backend uses 90s default
            }),
        });
        const data = await res.json();
        if (data.local_sensitivity) {
            applyImpactBars(data.local_sensitivity, data.sensitivity_seconds || {});
        }
        if (data.confidence_level) {
            applyConfidence(data);
        }
    } catch (e) {
        // Non-critical — bars stay at last known values
    }
}

function applyConfidence(data) {
    const widget  = document.getElementById('confidenceWidget');
    const dot     = document.getElementById('confDot');
    const label   = document.getElementById('confLabel');
    const score   = document.getElementById('confScore');
    const fill    = document.getElementById('confBarFill');
    const detail  = document.getElementById('confDetail');
    if (!widget) return;

    widget.style.display = 'block';

    const lvl = data.confidence_level;
    const pct = data.confidence_score;
    const color = lvl === 'high' ? '#00c853' : lvl === 'medium' ? '#f59e0b' : '#e60000';
    const text  = lvl === 'high' ? 'HIGH CONFIDENCE' : lvl === 'medium' ? 'MEDIUM CONFIDENCE' : 'LOW CONFIDENCE';

    dot.style.background  = color;
    dot.style.boxShadow   = `0 0 6px ${color}`;
    label.textContent     = text;
    label.style.color     = color;
    score.textContent     = `${pct}%`;
    fill.style.width      = `${pct}%`;
    fill.style.background = color;

    const nearest = data.dist_nearest;
    const mean64  = data.dist_mean64;
    if (lvl === 'high') {
        detail.textContent = `Nearest CFD design is ${nearest.toFixed(2)}σ away — prediction is reliable`;
    } else if (lvl === 'medium') {
        detail.textContent = `Nearest CFD design is ${nearest.toFixed(2)}σ away — some interpolation`;
    } else {
        detail.textContent = `Nearest CFD design is ${nearest.toFixed(2)}σ away — extrapolating, treat with caution`;
    }
}

function applyImpactBars(sensitivity, sensitivitySeconds = {}) {
    const absValues = Object.values(sensitivity).map(Math.abs);
    const maxAbs = Math.max(...absValues, 1e-6);

    state.paramDefs.forEach(pd => {
        const sliderEl = document.querySelector(`#slider-${pd.key}`);
        if (!sliderEl) return;
        const container = sliderEl.closest('.param-slider');
        if (!container) return;

        const leftEl    = container.querySelector('.impact-left');
        const rightEl   = container.querySelector('.impact-right');
        const barEl     = container.querySelector('.impact-bar-split');
        const secondsEl = container.querySelector('.impact-seconds');
        if (!leftEl || !rightEl) return;

        const val  = sensitivity[pd.key] || 0;
        const pct  = Math.min(100, Math.round((Math.abs(val) / maxAbs) * 100));
        const negligible = pct < 5;

        // right = what increasing the slider does, left = decreasing
        let rightColour, leftColour, tip;

        if (negligible) {
            rightColour = '#333';
            leftColour  = '#333';
            tip = 'Negligible aero effect from here';
        } else if (val < 0) {
            // increase → lower Cd → faster
            rightColour = pct >= 50 ? '#00c853' : '#66bb6a';
            leftColour  = pct >= 50 ? '#e60000' : '#ef9a9a';
            tip = `▶ Increase → faster (ΔCd ${val.toFixed(4)})  |  ◀ Decrease → slower`;
        } else {
            // increase → higher Cd → slower
            rightColour = pct >= 50 ? '#e60000' : '#ef9a9a';
            leftColour  = pct >= 50 ? '#00c853' : '#66bb6a';
            tip = `◀ Decrease → faster (ΔCd ${val.toFixed(4)})  |  ▶ Increase → slower`;
        }

        const w = Math.max(4, pct) + '%';
        leftEl.style.width  = w;
        rightEl.style.width = w;
        leftEl.style.background  = leftColour;
        rightEl.style.background = rightColour;
        if (barEl) barEl.title = tip;

        // ── Seconds label ─────────────────────────────────────────────
        if (secondsEl) {
            const sec = sensitivitySeconds[pd.key];
            if (sec !== undefined && !negligible) {
                // Show the faster direction's magnitude
                const fasterSec = Math.abs(sec);
                const isGain    = sec < 0;  // delta_cd<0 → delta_sec<0 → faster = gain
                const sign      = isGain ? '−' : '+';
                const colour    = isGain ? '#00c853' : '#e60000';
                secondsEl.textContent   = `${sign}${fasterSec.toFixed(1)}s`;
                secondsEl.style.color   = colour;
                secondsEl.style.display = 'inline-block';
            } else {
                secondsEl.textContent   = '';
                secondsEl.style.display = 'none';
            }
        }
    });
}

// Geometric deformation intentionally removed.
// The 3D viewer now shows the actual nearest CFD mesh from the DrivAerNet dataset
// (selected via KNN), updated automatically as sliders change.
function applyGeometricDeformation() { /* no-op — real mesh swapping handles this */ }

// Cross-fade animation state
let fadeAnim = null;

function makeMeshMaterial(opacity = 1) {
    return new THREE.MeshPhysicalMaterial({
        color: 0x8a9aaa,
        metalness: 0.75,
        roughness: 0.25,
        clearcoat: 1.0,
        clearcoatRoughness: 0.08,
        envMapIntensity: 1.5,
        reflectivity: 0.9,
        side: THREE.DoubleSide,
        transparent: opacity < 1,
        opacity,
    });
}

function centerAndOrientMesh(mesh, geometry) {
    geometry.computeBoundingBox();
    const center = new THREE.Vector3();
    geometry.boundingBox.getCenter(center);
    mesh.position.sub(center);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.5;
}

/**
 * Cross-fade from old car mesh to new mesh over `duration` ms.
 * The new mesh fades in while the old one fades out and is removed.
 */
function crossfadeToMesh(newMesh, duration = 450) {
    if (fadeAnim) { cancelAnimationFrame(fadeAnim); fadeAnim = null; }

    const oldMesh = carMesh;
    carMesh = newMesh;

    // Make old mesh transparent, new mesh starts invisible
    if (oldMesh) {
        oldMesh.material.transparent = true;
    }
    newMesh.material.transparent = true;
    newMesh.material.opacity = 0;
    carGroup.add(newMesh);

    const start = performance.now();
    function step() {
        const t = Math.min(1, (performance.now() - start) / duration);
        const ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; // ease in-out quad

        if (oldMesh) oldMesh.material.opacity = 1 - ease;
        newMesh.material.opacity = ease;

        if (t >= 1) {
            // Cleanup — remove old mesh, make new opaque
            if (oldMesh) carGroup.remove(oldMesh);
            newMesh.material.transparent = false;
            newMesh.material.opacity = 1;
            fadeAnim = null;
        } else {
            fadeAnim = requestAnimationFrame(step);
        }
    }
    fadeAnim = requestAnimationFrame(step);
}

async function loadClosestSTL() {
    if (!scene || !carGroup || !state.selectedBodyType) {
        document.getElementById('statusText').innerText = 'viewer not ready';
        return;
    }

    let data;
    try {
        const res = await fetch('/api/closest_mesh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                params:    state.currentParams,
                body_code: state.selectedBodyType.body_code,
                underbody: state.underbody || 'S',
                wheels:    state.wheels    || 'WWC',
            })
        });
        data = await res.json();
    } catch (e) {
        document.getElementById('statusText').innerText = 'API error: ' + e.message;
        return;
    }

    if (!data.has_stl || !data.stl_url) {
        document.getElementById('statusText').innerText = 'no STL for this design';
        return;
    }

    const designId = data.stl_url.split('/').pop();
    document.getElementById('statusText').innerText = `Design: ${designId}`;

    if (data.stl_url === lastStlUrl) return; // same design, skip
    lastStlUrl = data.stl_url;

    document.getElementById('statusText').innerText = `Loading ${designId}…`;

    const loader = new THREE.STLLoader();
    loader.load(
        data.stl_url,
        (geometry) => {
            geometry.computeVertexNormals();

            // Step 1: centre geometry in X and Z only (not Y — keep car above ground)
            geometry.computeBoundingBox();
            const bb = geometry.boundingBox;
            const cx = (bb.max.x + bb.min.x) / 2;
            const cz = (bb.max.z + bb.min.z) / 2;
            geometry.translate(-cx, 0, -cz);

            // Step 2: rotate so Z-up CAD model becomes Y-up Three.js
            geometry.rotateX(-Math.PI / 2);

            // Step 3: sit the car on the ground (minY → 0)
            geometry.computeBoundingBox();
            const minY = geometry.boundingBox.min.y;
            geometry.translate(0, -minY, 0);

            const mat = new THREE.MeshStandardMaterial({
                color: 0x9aabb8,
                metalness: 0.55,
                roughness: 0.4,
                side: THREE.DoubleSide,   // fixes hollow appearance
            });
            const newMesh = new THREE.Mesh(geometry, mat);
            newMesh.castShadow = true;

            // Clear old mesh and add new one immediately
            while (carGroup.children.length) carGroup.remove(carGroup.children[0]);
            carGroup.add(newMesh);
            carMesh = newMesh;

            document.getElementById('statusText').innerText = designId;
            document.querySelector('.status-dot').style.background = '#06d6a0';
        },
        (xhr) => {
            if (xhr.lengthComputable) {
                const pct = Math.round(xhr.loaded / xhr.total * 100);
                document.getElementById('statusText').innerText = `${designId} ${pct}%`;
            }
        },
        (err) => {
            document.getElementById('statusText').innerText = 'Preparing mesh…';
            document.querySelector('.status-dot').style.background = '#ffcc00';
            // Retry in 5s (server may still be decimating)
            lastStlUrl = null; // allow retry
            setTimeout(() => loadClosestSTL(), 5000);
        }
    );
}

// ============================================================================
// PARAMETER CUSTOMIZATION
// ============================================================================

function renderParameterGroups() {
    const container = document.getElementById('parameterGroups');
    if (!state.paramDefs.length) return;

    // Group by category
    const categories = {};
    state.paramDefs.forEach(p => {
        if (!categories[p.category]) categories[p.category] = [];
        categories[p.category].push(p);
    });

    container.innerHTML = Object.entries(categories).map(([category, params]) => `
        <div class="param-group">
            <div class="param-group-header" onclick="toggleParamGroup('${category}')">
                <span>${getCategoryIcon(category)} ${category}</span>
                <span class="collapse-icon">▼</span>
            </div>
            <div class="param-group-body" id="group-${category}">
                ${params.map(p => createParamSlider(p)).join('')}
            </div>
        </div>
    `).join('');

    updateAllSliders();
}

function getCategoryIcon(category) {
    const icons = {
        'Body': '📐',
        'Exterior': '🎨',
        'Windows': '🪟',
        'Mirrors': '🪞',
        'Details': '🔩',
    };
    return icons[category] || '⚙️';
}

function impactBar(cdImpact) {
    // Initial render — neutral grey both sides until first API call populates direction
    return `<span class="impact-bar-split" title="Select a body type to see direction">
        <span class="impact-left"  style="background:#333"></span>
        <span class="impact-divider"></span>
        <span class="impact-right" style="background:#333"></span>
    </span>`;
}

function createParamSlider(paramDef) {
    const key = paramDef.key;
    const value = state.currentParams[key] !== undefined ? state.currentParams[key] : 0;

    // Use actual dataset min/max so the full parameter space is reachable
    const min = paramDef.min !== undefined ? paramDef.min : -100;
    const max = paramDef.max !== undefined ? paramDef.max : 100;
    const step = parseFloat(((max - min) / 200).toFixed(4));
    const impact = paramDef.cd_impact || 0;

    return `
        <div class="param-slider">
            <label class="param-label">
                ${paramDef.name}
                <span class="param-label-right">
                    ${impactBar(impact)}
                    <span class="impact-seconds" id="sec-${key}" style="display:none;"></span>
                    <span class="param-value" id="val-${key}">${value.toFixed(2)}${paramDef.unit}</span>
                </span>
            </label>
            <input
                type="range"
                id="slider-${key}"
                min="${min}"
                max="${max}"
                step="${step}"
                value="${value}"
                oninput="updateParam('${key}')"
                class="slider"
            >
        </div>
    `;
}

function toggleParamGroup(category) {
    const body = document.getElementById(`group-${category}`);
    body.classList.toggle('collapsed');
}

function updateParam(key) {
    const slider = document.getElementById(`slider-${key}`);
    const value = parseFloat(slider.value);
    state.currentParams[key] = value;

    // Update display
    const paramDef = state.paramDefs.find(p => p.key === key);
    const display = document.getElementById(`val-${key}`);
    if (display && paramDef) {
        display.textContent = `${value.toFixed(2)}${paramDef.unit}`;
    }

    // Animate 3D car part morph
    update3DCar();
}

function updateAllSliders() {
    state.paramDefs.forEach(p => {
        const key = p.key;
        const slider = document.getElementById(`slider-${key}`);
        const display = document.getElementById(`val-${key}`);
        if (slider && state.currentParams[key] !== undefined) {
            slider.value = state.currentParams[key];
            if (display) {
                display.textContent = `${state.currentParams[key].toFixed(2)}${p.unit}`;
            }
        }
    });

    // Sync 3D car mesh to match
    update3DCar();
}

function resetToStock() {
    if (!state.stockParams) return;
    state.currentParams = { ...state.stockParams };
    state.underbody = 'S';
    state.wheels = 'WWC';
    const ubSel = document.getElementById('underbodySelect');
    const wSel = document.getElementById('wheelsSelect');
    if (ubSel) ubSel.value = 'S';
    if (wSel) wSel.value = 'WWC';
    updateAllSliders();
}

function updateUnderbody(val) {
    state.underbody = val;
    // affects Cd output only — no mesh reload needed
    updateLocalSensitivity();
}

function updateWheels(val) {
    state.wheels = val;
    // affects Cd output only — no mesh reload needed
    updateLocalSensitivity();
}

// ============================================================================
// PRESET MANAGEMENT
// ============================================================================

function savePreset() {
    document.getElementById('presetModal').classList.add('active');
    document.getElementById('presetNameInput').value = '';
    setTimeout(() => document.getElementById('presetNameInput').focus(), 100);
}

function closePresetModal() {
    document.getElementById('presetModal').classList.remove('active');
}

function confirmSavePreset() {
    const name = document.getElementById('presetNameInput').value.trim();
    if (!name) return;

    state.presets.push({
        name,
        params: { ...state.currentParams },
        underbody: state.underbody,
        wheels: state.wheels,
        isStock: false,
    });

    closePresetModal();
    renderPresetList();
    updateSimulateButton();
}

function deletePreset(idx) {
    if (state.presets[idx].isStock) return;
    state.presets.splice(idx, 1);
    renderPresetList();
    updateSimulateButton();
}

function quickAddToSim() {
    if (!state.selectedBodyType) {
        alert('Select a body type first.');
        return;
    }
    const n = state.presets.filter(p => !p.isStock).length + 1;
    state.presets.push({
        name: `Config ${n}`,
        params: { ...state.currentParams },
        underbody: state.underbody,
        wheels: state.wheels,
        isStock: false,
    });
    renderPresetList();
    updateSimulateButton();
}

function loadPreset(idx) {
    const preset = state.presets[idx];
    state.currentParams = { ...preset.params };
    state.underbody = preset.underbody || 'S';
    state.wheels = preset.wheels || 'WWC';
    const ubSel = document.getElementById('underbodySelect');
    const wSel = document.getElementById('wheelsSelect');
    if (ubSel) ubSel.value = state.underbody;
    if (wSel) wSel.value = state.wheels;
    updateAllSliders();
}

function renderPresetList() {
    const list = document.getElementById('presetList');
    const WHEELS_LABEL = { WWC: 'Closed', WW: 'Open Det.', WWS: 'Open Smooth' };
    const UNDERBODY_LABEL = { S: 'Smooth', D: 'Detailed' };
    list.innerHTML = state.presets.map((p, i) => `
        <li class="preset-item ${p.isStock ? 'stock' : ''}">
            <div>
                <div class="preset-name">${p.isStock ? '📌 ' : ''}${p.name}</div>
                <div class="preset-meta">${UNDERBODY_LABEL[p.underbody||'S']} underbody · ${WHEELS_LABEL[p.wheels||'WWC']} wheels</div>
            </div>
            <div class="preset-actions">
                <button class="btn btn-sm btn-secondary btn-icon" onclick="loadPreset(${i})" title="Load">📥</button>
                ${!p.isStock ? `<button class="btn btn-sm btn-danger btn-icon" onclick="deletePreset(${i})" title="Delete">✕</button>` : ''}
            </div>
        </li>
    `).join('');
}

// ============================================================================
// TRACK SELECTION
// ============================================================================

function renderTrackGrid() {
    const grid = document.getElementById('trackGrid');
    grid.innerHTML = state.tracks.map(t => `
        <div class="track-card" onclick="selectTrack('${t.name}')" id="track-${t.name}">
            <canvas class="track-preview" id="preview-${t.name}" width="200" height="120"></canvas>
            <div class="track-name">${t.name}</div>
        </div>
    `).join('');

    state.tracks.forEach(t => drawTrackPreview(t));
}

function drawTrackPreview(track) {
    const canvas = document.getElementById(`preview-${track.name}`);
    if (!canvas || !track.preview || track.preview.length < 2) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    const pts = track.preview;

    const xs = pts.map(p => p[0]);
    const ys = pts.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const pad = 12;
    const scale = Math.min((w - 2 * pad) / rangeX, (h - 2 * pad) / rangeY);
    const offX = (w - rangeX * scale) / 2;
    const offY = (h - rangeY * scale) / 2;

    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.6)';
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    pts.forEach((p, i) => {
        const x = offX + (p[0] - minX) * scale;
        const y = offY + (maxY - p[1]) * scale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
}

function selectTrack(name) {
    state.selectedTrack = name;
    document.querySelectorAll('.track-card').forEach(c => c.classList.remove('selected'));
    document.getElementById(`track-${name}`).classList.add('selected');
    updateSimulateButton();
}

// ============================================================================
// SIMULATION
// ============================================================================

function updateSimulateButton() {
    const btn = document.getElementById('btnSimulate');
    btn.disabled = !(state.selectedBodyType && state.selectedTrack && state.presets.length >= 1);
}

async function runSimulation() {
    if (!state.selectedBodyType || !state.selectedTrack || state.presets.length < 1) return;

    showLoading('Preparing simulation...');

    // Always include Stock as the baseline for comparison
    const hasStock = state.presets.some(p => p.isStock);
    const allPresets = hasStock ? state.presets : [
        { name: 'Stock', params: { ...state.stockParams }, underbody: 'S', wheels: 'WWC', isStock: true },
        ...state.presets,
    ];

    const payload = {
        body_code: state.selectedBodyType.body_code,
        track: state.selectedTrack,
        presets: allPresets.map(p => ({
            name: p.name,
            params: p.params,
            underbody: p.underbody || 'S',
            wheels: p.wheels || 'WWC',
        })),
    };

    updateLoading(`Simulating ${allPresets.length} presets on ${state.selectedTrack}...`, 20);

    try {
        const res = await fetch('/api/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        updateLoading('Processing results...', 80);

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Simulation failed');
        }

        state.results = await res.json();
        updateLoading('Done!', 100);

        // Store best lap time — used to convert sensitivity bars to seconds
        const bestResult = state.results.results?.find(r => r.name === state.results.best);
        if (bestResult?.lap_time) {
            state.lastLapTime = bestResult.lap_time;
        }

        setTimeout(() => {
            hideLoading();
            switchTab('results');
            renderResults();
        }, 500);

    } catch (e) {
        hideLoading();
        alert('Simulation error: ' + e.message);
    }
}

// ============================================================================
// RESULTS RENDERING
// ============================================================================

function renderResults() {
    if (!state.results) return;
    document.getElementById('btnExport').disabled = false;
    const { results, best, track } = state.results;

    document.getElementById('resultsSubtitle').textContent =
        `${results.length} presets tested on ${track}`;

    // Best banner
    const bestResult = results.find(r => r.name === best);
    if (bestResult) {
        document.getElementById('bestBanner').style.display = 'block';
        document.getElementById('bestName').textContent = bestResult.name;
        document.getElementById('bestTime').textContent = formatTime(bestResult.lap_time);

        if (bestResult.improvement_vs_stock !== undefined && bestResult.improvement_vs_stock !== 0) {
            const imp = bestResult.improvement_vs_stock;
            document.getElementById('bestImprovement').textContent =
                imp > 0 ? `⬆ ${imp.toFixed(3)}s faster than stock` : `⬇ ${Math.abs(imp).toFixed(3)}s slower than stock`;
        } else if (bestResult.name === 'Stock') {
            document.getElementById('bestImprovement').textContent = 'Stock configuration is the fastest';
        } else {
            document.getElementById('bestImprovement').textContent = '';
        }
    }

    // Table
    const tbody = document.getElementById('resultsBody');
    tbody.innerHTML = results.map((r, i) => {
        const rank = i + 1;
        const rankClass = rank === 1 ? 'rank-1' : rank === 2 ? 'rank-2' : rank === 3 ? 'rank-3' : 'rank-other';
        const deltaStr = r.delta !== undefined ? (r.delta === 0 ? '—' : `+${r.delta.toFixed(3)}s`) : '—';
        const deltaClass = r.delta === 0 ? 'zero' : 'positive';

        let impStr = '—';
        let impClass = '';
        if (r.improvement_vs_stock !== undefined) {
            if (r.improvement_vs_stock > 0) {
                impStr = `↑ ${r.improvement_vs_stock.toFixed(3)}s`;
                impClass = 'good';
            } else if (r.improvement_vs_stock < 0) {
                impStr = `↓ ${Math.abs(r.improvement_vs_stock).toFixed(3)}s`;
                impClass = 'bad';
            } else {
                impStr = 'Baseline';
            }
        }

        const WHEELS_LABEL = { WWC: 'Closed', WW: 'Open Det.', WWS: 'Open Smooth' };
        const UNDERBODY_LABEL = { S: 'Smooth', D: 'Detailed' };
        return `
            <tr>
                <td><span class="rank-badge ${rankClass}">${rank}</span></td>
                <td><strong>${r.name}</strong>${r.name === 'Stock' ? ' 📌' : ''}</td>
                <td>${UNDERBODY_LABEL[r.underbody || 'S']}</td>
                <td>${WHEELS_LABEL[r.wheels || 'WWC']}</td>
                <td class="aero-val">${r.cd != null ? r.cd.toFixed(3) : '—'}</td>
                <td class="aero-val">${r.cl_f != null ? r.cl_f.toFixed(3) : '—'}</td>
                <td class="aero-val">${r.cl_r != null ? r.cl_r.toFixed(3) : '—'}</td>
                <td class="lap-time">${r.status === 'ok' ? formatTime(r.lap_time) : 'Error'}</td>
                <td><span class="delta ${deltaClass}">${deltaStr}</span></td>
                <td>${impClass ? `<span class="improvement-badge ${impClass}">${impStr}</span>` : impStr}</td>
                <td>${r.max_speed ? r.max_speed.toFixed(1) + ' km/h' : '—'}</td>
            </tr>
        `;
    }).join('');

    // Viz preset selectors
    const okResults = results.filter(r => r.status === 'ok' && r.vel_profile);
    const optionsHtml = okResults.map((r, i) => `<option value="${i}">${r.name}</option>`).join('');
    document.getElementById('vizPresetSelect').innerHTML = optionsHtml;
    document.getElementById('vizPresetSelect2').innerHTML =
        `<option value="-1">— Compare —</option>` + optionsHtml;
    state.vizPresetIdx = 0;
    state.vizPresetIdx2 = -1;
    state.simTime = 0;
    state.timelines = {};

    drawTrackVisualization();

    // Fetch and render optimisation suggestions asynchronously (non-blocking)
    fetchSuggestions();
}

// ============================================================================
// ML SUGGESTIONS PANEL
// ============================================================================

async function fetchSuggestions() {
    if (!state.results || !state.selectedBodyType) return;

    const panel = document.getElementById('suggestionsPanel');
    if (panel) panel.style.display = 'none';   // hide while loading

    // Use the fastest preset's params for suggestions
    const bestName   = state.results.best;
    const bestResult = state.results.results?.find(r => r.name === bestName && r.status === 'ok');
    if (!bestResult) return;

    const bestPreset = state.presets.find(p => p.name === bestName)
                    || state.presets.find(p => p.isStock);
    if (!bestPreset) return;

    try {
        const res = await fetch('/api/suggestions', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                params:    bestPreset.params,
                body_code: state.selectedBodyType.body_code,
                underbody: bestPreset.underbody || 'S',
                wheels:    bestPreset.wheels    || 'WWC',
                lap_time:  bestResult.lap_time,
                cd:        bestResult.cd,
                track:     state.selectedTrack,
            }),
        });
        if (!res.ok) return;
        const data = await res.json();
        renderSuggestionsPanel(data.suggestions || [], bestResult.lap_time, data.sensitivity_source, bestName);
    } catch (e) {
        console.warn('[suggestions] fetch failed:', e);
    }
}

function renderSuggestionsPanel(suggestions, lapTime, source, presetName) {
    const panel = document.getElementById('suggestionsPanel');
    if (!panel) return;

    if (!suggestions || suggestions.length === 0) {
        panel.style.display = 'none';
        return;
    }

    const sourceLabel = source === 'gradient_boosting' ? 'Gradient Boosting ML' : 'KNN interpolation';
    const lapStr      = lapTime ? `${lapTime.toFixed(3)}s` : '';
    const maxGain     = Math.abs(suggestions[0].delta_seconds);

    panel.innerHTML = `
        <div class="suggestions-header">
            <div class="suggestions-title-row">
                <span class="suggestions-icon">🎯</span>
                <span class="suggestions-title">How to Go Faster</span>
                <span class="suggestions-preset">based on <strong>${presetName}</strong>${lapStr ? ' (' + lapStr + ')' : ''}</span>
            </div>
            <span class="suggestions-source">via ${sourceLabel}</span>
        </div>
        <div class="suggestions-list">
            ${suggestions.map((s, i) => {
                const isGain   = s.delta_seconds < 0;
                const secClass = isGain ? 'sug-gain' : 'sug-loss';
                const secSign  = isGain ? '−' : '+';
                const secAbs   = Math.abs(s.delta_seconds).toFixed(2);
                const arrow    = s.direction === 'increase' ? '▲' : '▼';
                const barPct   = maxGain > 0
                    ? Math.round((Math.abs(s.delta_seconds) / maxGain) * 100)
                    : 0;
                return `
                    <div class="suggestion-row">
                        <span class="sug-rank">${i + 1}</span>
                        <span class="sug-name">${s.param_name}</span>
                        <span class="sug-arrow ${isGain ? 'sug-arrow-gain' : 'sug-arrow-loss'}">${arrow}</span>
                        <span class="sug-delta ${secClass}">${secSign}${secAbs}s</span>
                        <div class="sug-bar-track">
                            <div class="sug-bar-fill ${secClass}" style="width:${barPct}%"></div>
                        </div>
                        <span class="sug-category">${s.category}</span>
                    </div>
                `;
            }).join('')}
        </div>
    `;
    panel.style.display = 'block';
}

function exportCSV() {
    if (!state.results) return;
    const { results, track } = state.results;
    const bodyName = state.selectedBodyType?.name || 'Unknown';
    const now = new Date().toISOString().slice(0, 19).replace('T', ' ');

    const WHEELS_LABEL = { WWC: 'Closed Cover', WW: 'Open Detailed', WWS: 'Open Smooth' };
    const UNDERBODY_LABEL = { S: 'Smooth', D: 'Detailed' };

    const headers = [
        'Rank', 'Preset Name', 'Body Type', 'Track', 'Underbody', 'Wheels',
        'Cd', 'Cl_F', 'Cl_R',
        'Lap Time (s)', 'Lap Time', 'Delta (s)', 'vs Stock (s)', 'Top Speed (km/h)',
        'Run Date',
    ];

    const rows = results.map((r, i) => [
        i + 1,
        r.name,
        bodyName,
        track,
        UNDERBODY_LABEL[r.underbody || 'S'],
        WHEELS_LABEL[r.wheels || 'WWC'],
        r.cd ?? '',
        r.cl_f ?? '',
        r.cl_r ?? '',
        r.status === 'ok' ? r.lap_time : '',
        r.status === 'ok' ? formatTime(r.lap_time) : 'Error',
        r.delta ?? '',
        r.improvement_vs_stock ?? '',
        r.max_speed ?? '',
        now,
    ]);

    const csv = [headers, ...rows]
        .map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(','))
        .join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `laptime_${track}_${now.slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

function formatTime(seconds) {
    const min = Math.floor(seconds / 60);
    const sec = (seconds % 60).toFixed(3);
    return `${min}:${sec.padStart(6, '0')}`;
}

// ============================================================================
// 2D TRACK VISUALIZATION
// ============================================================================

function drawTrackVisualization() {
    const canvas = document.getElementById('trackCanvas');
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.scale(dpr, dpr);

    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const coords = state.results.track_coords;

    if (!coords || coords.length < 2) return;

    const xs = coords.map(p => p[0]);
    const ys = coords.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const pad = 40;
    const scale = Math.min((w - 2 * pad) / rangeX, (h - 2 * pad) / rangeY);
    const offX = (w - rangeX * scale) / 2;
    const offY = (h - rangeY * scale) / 2;

    state.vizTransform = { minX, maxY, scale, offX, offY };
    state.vizCoords = coords;

    ctx.clearRect(0, 0, w, h);

    // Track outline
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    coords.forEach((p, i) => {
        const x = offX + (p[0] - minX) * scale;
        const y = offY + (maxY - p[1]) * scale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();

    // Start/finish
    const sfX = offX + (coords[0][0] - minX) * scale;
    const sfY = offY + (maxY - coords[0][1]) * scale;
    ctx.fillStyle = '#f59e0b';
    ctx.beginPath();
    ctx.arc(sfX, sfY, 6, 0, Math.PI * 2);
    ctx.fill();

    drawSpeedOverlay(ctx);
}

function drawSpeedOverlay(ctx) {
    const results = state.results.results.filter(r => r.status === 'ok' && r.vel_profile);
    if (results.length === 0) return;

    // Draw comparison preset first (thinner, underneath)
    if (state.vizPresetIdx2 >= 0 && state.vizPresetIdx2 < results.length) {
        drawSpeedLayer(ctx, results[state.vizPresetIdx2], speedColor2, 3);
    }
    // Draw primary preset on top
    drawSpeedLayer(ctx, results[state.vizPresetIdx], speedColor, 5);
}

function drawSpeedLayer(ctx, r, colorFn, lineWidth) {
    if (!r || !r.vel_profile) return;
    const coords = state.vizCoords;
    const { minX, maxY, scale, offX, offY } = state.vizTransform;
    const speeds = r.vel_profile.speeds;
    const maxSpeed = Math.max(...speeds);
    const minSpeed = Math.min(...speeds);
    const step = Math.max(1, Math.floor(coords.length / speeds.length));

    ctx.lineWidth = lineWidth;
    ctx.lineCap = 'round';

    for (let i = 1; i < coords.length; i++) {
        const speedIdx = Math.min(Math.floor(i / step), speeds.length - 1);
        const t = (speeds[speedIdx] - minSpeed) / (maxSpeed - minSpeed || 1);
        ctx.strokeStyle = colorFn(t);
        const x1 = offX + (coords[i - 1][0] - minX) * scale;
        const y1 = offY + (maxY - coords[i - 1][1]) * scale;
        const x2 = offX + (coords[i][0] - minX) * scale;
        const y2 = offY + (maxY - coords[i][1]) * scale;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
    }
}

function speedColor(t) {
    let r, g, b;
    if (t < 0.5) {
        const s = t * 2;
        r = 239;
        g = Math.round(68 + (245 - 68) * s);
        b = Math.round(68 + (11 - 68) * s);
    } else {
        const s = (t - 0.5) * 2;
        r = Math.round(245 - (245 - 6) * s);
        g = Math.round(158 + (214 - 158) * s);
        b = Math.round(11 + (160 - 11) * s);
    }
    return `rgb(${r},${g},${b})`;
}

function selectVizPreset() {
    state.vizPresetIdx = parseInt(document.getElementById('vizPresetSelect').value);
    drawTrackVisualization();
}

function selectVizPreset2() {
    state.vizPresetIdx2 = parseInt(document.getElementById('vizPresetSelect2').value);
    drawTrackVisualization();
}

// Blue→cyan color scheme for comparison preset
function speedColor2(t) {
    let r, g, b;
    if (t < 0.5) {
        const s = t * 2;
        r = Math.round(30 + (99 - 30) * s);
        g = Math.round(64 + (51 - 64) * s);
        b = Math.round(175 + (234 - 175) * s);
    } else {
        const s = (t - 0.5) * 2;
        r = Math.round(99 - (99 - 34) * s);
        g = Math.round(51 + (211 - 51) * s);
        b = Math.round(234 - (234 - 238) * s);
    }
    return `rgb(${r},${g},${b})`;
}

// Build a time→position lookup for a vel_profile.
// Returns { cumTime[], totalTime } where cumTime[i] = elapsed seconds at node i.
function buildTimeline(vp) {
    const dists = vp.distances;
    const speeds = vp.speeds; // km/h
    if (!dists || dists.length < 2) return null;
    const t = [0];
    for (let i = 1; i < dists.length; i++) {
        const ds = dists[i] - dists[i - 1];
        const v = Math.max(1, speeds[i]) / 3.6; // m/s, guard div-by-zero
        t.push(t[i - 1] + ds / v);
    }
    return { cumTime: t, totalTime: t[t.length - 1] };
}

// Return {x, y} on the track at elapsed time t (wraps every lap).
function posAtTime(vp, timeline, t) {
    const tMod = t % timeline.totalTime;
    const ct = timeline.cumTime;
    // Binary search for bracketing nodes
    let lo = 0, hi = ct.length - 1;
    while (lo < hi - 1) {
        const mid = (lo + hi) >> 1;
        if (ct[mid] <= tMod) lo = mid; else hi = mid;
    }
    const span = ct[hi] - ct[lo] || 1;
    const frac = (tMod - ct[lo]) / span;
    return {
        x: vp.x[lo] + (vp.x[hi] - vp.x[lo]) * frac,
        y: vp.y[lo] + (vp.y[hi] - vp.y[lo]) * frac,
    };
}

const SIM_SPEED = 10.0; // animation runs at 10× real time

function toggleVisualization() {
    const btn = document.getElementById('btnPlayViz');
    if (state.vizPlaying) {
        state.vizPlaying = false;
        cancelAnimationFrame(state.vizAnimationId);
        btn.innerHTML = '▶ Play';
        drawTrackVisualization();
    } else {
        state.vizPlaying = true;
        state.simTime = 0;
        btn.innerHTML = '⏹ Stop';
        animateLap();
    }
}

function animateLap() {
    if (!state.vizPlaying) return;

    const results = state.results.results.filter(r => r.status === 'ok' && r.vel_profile);
    const r1 = results[state.vizPresetIdx];
    if (!r1 || !r1.vel_profile.x) { state.vizPlaying = false; return; }

    // Advance shared sim-clock (seconds of race time per frame at 60 fps)
    state.simTime += SIM_SPEED / 60;

    // Build/cache timelines
    const key1 = r1.name;
    if (!state.timelines[key1]) state.timelines[key1] = buildTimeline(r1.vel_profile);
    const tl1 = state.timelines[key1];

    drawTrackVisualization();

    const canvas = document.getElementById('trackCanvas');
    const ctx = canvas.getContext('2d');
    const { minX, maxY, scale, offX, offY } = state.vizTransform;

    // Draw comparison dot first (underneath)
    if (state.vizPresetIdx2 >= 0 && state.vizPresetIdx2 < results.length) {
        const r2 = results[state.vizPresetIdx2];
        if (r2 && r2.vel_profile.x) {
            const key2 = r2.name;
            if (!state.timelines[key2]) state.timelines[key2] = buildTimeline(r2.vel_profile);
            const tl2 = state.timelines[key2];
            const p2 = posAtTime(r2.vel_profile, tl2, state.simTime);
            const sx2 = offX + (p2.x - minX) * scale;
            const sy2 = offY + (maxY - p2.y) * scale;
            ctx.shadowBlur = 10;
            ctx.shadowColor = '#22d3ee';
            ctx.fillStyle = '#22d3ee';
            ctx.beginPath();
            ctx.arc(sx2, sy2, 6, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
        }
    }

    // Draw primary dot on top
    const p1 = posAtTime(r1.vel_profile, tl1, state.simTime);
    const sx1 = offX + (p1.x - minX) * scale;
    const sy1 = offY + (maxY - p1.y) * scale;
    ctx.shadowBlur = 10;
    ctx.shadowColor = '#ffffff';
    ctx.fillStyle = '#e60000';
    ctx.beginPath();
    ctx.arc(sx1, sy1, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    state.vizAnimationId = requestAnimationFrame(animateLap);
}

// ============================================================================
// LOADING UI
// ============================================================================

function showLoading(text) {
    document.getElementById('loadingText').textContent = text;
    document.getElementById('loadingBar').style.width = '5%';
    document.getElementById('loadingOverlay').classList.add('active');
}

function updateLoading(text, progress) {
    document.getElementById('loadingText').textContent = text;
    document.getElementById('loadingBar').style.width = progress + '%';
}

function hideLoading() {
    document.getElementById('loadingOverlay').classList.remove('active');
}

// Handle Enter key in modal
document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && document.getElementById('presetModal').classList.contains('active')) {
        confirmSavePreset();
    }
    if (e.key === 'Escape') closePresetModal();
});
