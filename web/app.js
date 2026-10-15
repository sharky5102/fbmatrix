const state = {
  effects: [],
  led_effects: [],
  effect: null,
  led_effect: 'default',
  color1: [0, 0, 1],
  color2: [1, 1, 0],
  color3: [1, 0, 0],
  speed: 1,
  brightness: 1,
  supersample: 3,
  fit_mode: 'fill',
  autoplay: false,
  autoplay_interval: 30,
  autoplay_effects: [],
  error: null,
  input_mode: 'effect',
  ndi_source: null,
  ndi_sources: [],
  ndi_status: {},
  matrix_size: 16,
  matrix_channels_per_universe: 510,
  matrix_start_address: 1,
  matrix_artnet: { port_address: 0 },
  matrix_sacn: { universe: 1 },
  matrix_protocol: 'artnet',
  matrix_status: {},
  network_control_enabled: false,
  network_control_protocol: 'artnet',
  network_control_artnet: { port_address: 0 },
  network_control_sacn: { universe: 1 },
  network_control_start_address: 1,
  network_control_hold: 30,
  network_control_status: {},
};

const preview = {
  gl: null,
  program: null,
  buffer: null,
  effect: null,
  error: null,
  effect_time: 0,
  last_frame: performance.now(),
};

const SLIDER_UPDATE_DELAY = 100;

const effectsEl = document.getElementById('effects');
const ledEffectsEl = document.getElementById('led-effects');
const colorKeys = ['color1', 'color2', 'color3'];
const colorEls = colorKeys.map((key) => document.getElementById(key));
const speedEl = document.getElementById('speed');
const brightnessEl = document.getElementById('brightness');
const supersampleEl = document.getElementById('supersample');
const fitModeEl = document.getElementById('fit-mode');
const autoplayEl = document.getElementById('autoplay');
const autoplayIntervalEl = document.getElementById('autoplay-interval');
const statusEl = document.getElementById('status');
const signalEl = document.getElementById('signal');
const canvas = document.getElementById('swatch');
const workspaceEl = document.getElementById('workspace');
const modeEffectEl = document.getElementById('mode-effect');
const modeNetworkEl = document.getElementById('mode-network');
const modeSetupEl = document.getElementById('mode-setup');
const matrixChannelsEl = document.getElementById('matrix-channels');
const matrixSizeEl = document.getElementById('matrix-size');
const matrixAddressEl = document.getElementById('matrix-address');
const matrixProtocolEl = document.getElementById('matrix-protocol');
const matrixStartEl = document.getElementById('matrix-artnet-universe');
const matrixSacnStartEl = document.getElementById('matrix-sacn-universe');
const matrixStatusEl = document.getElementById('matrix-status');
const matrixErrorEl = document.getElementById('matrix-error');
const modeNdiEl = document.getElementById('mode-ndi');
const ndiSourceEl = document.getElementById('ndi-source');
const ndiPanelEl = document.getElementById('ndi-panel');
const ndiStatusEl = document.getElementById('ndi-status');
const ndiErrorEl = document.getElementById('ndi-error');
const networkControlEnabledEl = document.getElementById('network-control-enabled');
const networkControlProtocolEl = document.getElementById('network-control-protocol');
const networkControlArtNetEl = document.getElementById('network-control-artnet-universe');
const networkControlSacnEl = document.getElementById('network-control-sacn-universe');
const networkControlAddressEl = document.getElementById('network-control-address');
const networkControlHoldEl = document.getElementById('network-control-hold');
const networkControlStatusEl = document.getElementById('network-control-status');
const networkControlErrorEl = document.getElementById('network-control-error');
const layoutPreviewEl = document.getElementById('layout-preview');
const layoutStatsEl = document.getElementById('layout-stats');
const captureModalEl = document.getElementById('capture-modal');
const generateLayoutModalEl = document.getElementById('generate-layout-modal');
const generateLayoutTypeEl = document.getElementById('generate-layout-type');
const generateRectangleFieldsEl = document.getElementById('generate-rectangle-fields');
const generateRadialFieldsEl = document.getElementById('generate-radial-fields');
const generateCenterSpacingFieldEl = document.getElementById('generate-center-spacing-field');
const generateLayoutSubmitEl = document.getElementById('generate-layout-submit');
const generateLayoutErrorEl = document.getElementById('generate-layout-error');
const captureOpenEl = document.getElementById('capture-open');
const captureCloseEl = document.getElementById('capture-close');
const captureCountStepEl = document.getElementById('capture-count-step');
const captureQrStepEl = document.getElementById('capture-qr-step');
const capturePixelCountEl = document.getElementById('capture-pixel-count');
const captureNextEl = document.getElementById('capture-next');
const captureQrImageEl = document.getElementById('capture-qr-image');
const captureStatusEl = document.getElementById('capture-status');
const captureLayoutFileEl = document.getElementById('capture-layout-file');
let layoutPoints = [];
let layoutStats = null;
let captureSession = null;
let capturePollTimer = null;

async function request(path, options) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const body = await response.text();
  if (!response.ok) {
    let message = body;
    if (contentType.includes('application/json')) {
      try {
        const payload = JSON.parse(body);
        if (payload.error) message = payload.error;
      } catch (error) {
        // Keep the original response text when it is not valid JSON.
      }
    }
    throw new Error(message || `Request failed (${response.status})`);
  }

  if (contentType.includes('application/json')) {
    return JSON.parse(body);
  }
  return body;
}

function setCaptureStatus(message, isError = false) {
  captureStatusEl.textContent = message;
  captureStatusEl.classList.toggle('input-error', isError);
  captureStatusEl.classList.toggle('input-status', !isError);
  captureStatusEl.setAttribute('role', isError ? 'alert' : 'status');
  captureStatusEl.setAttribute('aria-live', isError ? 'assertive' : 'polite');
}

async function switchMode(mode) {
  if (mode !== 'setup' && captureModalEl.open) await closeCaptureWorkflow();
  if (mode !== 'setup' && generateLayoutModalEl.open) generateLayoutModalEl.close();
  await updateState(mode === 'setup'
    ? { input_mode: mode, led_effect: 'layout_colors' }
    : { input_mode: mode });
  state.led_effects = await request('/api/led-effects');
  if (!state.led_effects.some((effect) => effect.id === state.led_effect)) {
    const fallback = state.led_effects[0];
    if (fallback) await updateState({ led_effect: fallback.id });
  }
  renderLedEffects();
}

async function init() {
  initWebGL();

  try {
    state.effects = await request('/api/effects');
    state.led_effects = await request('/api/led-effects');
    const layout = await request('/api/layout');
    layoutPoints = layout.points;
    layoutStats = layout.stats;
    Object.assign(state, await request('/api/state'));
    await refreshNdiSources();
    renderControls();
    renderLayoutStats();
    drawLayoutPreview();
    new ResizeObserver(drawLayoutPreview).observe(layoutPreviewEl);
    await loadPreviewEffect(state.effect);
    setOnline(true);
    requestAnimationFrame(drawPreview);
  } catch (error) {
    setOnline(false, error.message);
  }
}

function drawLayoutPreview() {
  if (!layoutPreviewEl || !layoutPoints.length) return;
  const rect = layoutPreviewEl.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const scale = window.devicePixelRatio || 1;
  layoutPreviewEl.width = Math.round(rect.width * scale);
  layoutPreviewEl.height = Math.round(rect.height * scale);
  const ctx = layoutPreviewEl.getContext('2d');
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const padding = 12;
  const bounds = layoutPoints.reduce((result, point) => ({
    minX: Math.min(result.minX, point.x), maxX: Math.max(result.maxX, point.x),
    minY: Math.min(result.minY, point.y), maxY: Math.max(result.maxY, point.y),
  }), { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity });
  const dataWidth = bounds.maxX - bounds.minX || 1;
  const dataHeight = bounds.maxY - bounds.minY || 1;
  const aspect = dataWidth / dataHeight;
  const availableWidth = Math.max(0, rect.width - padding * 2);
  const availableHeight = Math.max(0, rect.height - padding * 2);
  const mode = fitModeEl.value || state.fit_mode || 'fill';
  const baseWidth = Math.min(availableWidth, availableHeight * aspect);
  const baseHeight = Math.min(availableHeight, availableWidth / aspect);
  const imageExtent = mode === 'stretch'
    ? Math.max(baseWidth, baseHeight)
    : mode === 'fit' ? Math.min(baseWidth, baseHeight)
      : Math.max(baseWidth, baseHeight);
  const contentScale = Math.min(0.92, availableWidth / imageExtent, availableHeight / imageExtent);
  const drawWidth = baseWidth * contentScale;
  const drawHeight = baseHeight * contentScale;
  const left = (rect.width - drawWidth) / 2;
  const top = (rect.height - drawHeight) / 2;
  ctx.globalCompositeOperation = 'lighter';
  for (const point of layoutPoints) {
    const x = left + (point.x - bounds.minX) / dataWidth * drawWidth;
    const y = top + (point.y - bounds.minY) / dataHeight * drawHeight;
    ctx.beginPath();
    ctx.fillStyle = point.enabled ? '#ffffff' : 'rgba(115, 130, 140, 0.3)';
    ctx.shadowColor = point.enabled ? 'rgba(40, 255, 170, 1)' : 'transparent';
    ctx.shadowBlur = point.enabled ? 11 : 0;
    ctx.arc(x, y, point.enabled ? 2.0 : 1.0, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }
  let imageLeft = left;
  let imageTop = top;
  let imageWidth = drawWidth;
  let imageHeight = drawHeight;
  if (mode !== 'stretch') {
    const side = mode === 'fit'
      ? Math.min(drawWidth, drawHeight)
      : Math.max(drawWidth, drawHeight);
    imageLeft += (drawWidth - side) / 2;
    imageTop += (drawHeight - side) / 2;
    imageWidth = side;
    imageHeight = side;
  }
  ctx.globalCompositeOperation = 'source-over';
  ctx.strokeStyle = 'rgba(110, 205, 255, 0.95)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(imageLeft, imageTop, imageWidth, imageHeight);
  ctx.globalCompositeOperation = 'source-over';
}

function renderLayoutStats() {
  layoutStatsEl.replaceChildren();
  if (!layoutStats || layoutStats.total === 0) {
    const empty = document.createElement('dt');
    empty.className = 'layout-stats-empty';
    empty.textContent = 'No layout';
    layoutStatsEl.appendChild(empty);
    return;
  }
  const entries = [
    ['Total LEDs', layoutStats.total],
    ['Active', layoutStats.active],
    ['Connector LEDs', layoutStats.connectors],
    ['Inactive padding', layoutStats.padding],
    ['Output strings', layoutStats.strings],
  ];
  entries.forEach(([label, value]) => {
    const term = document.createElement('dt');
    term.textContent = label;
    const detail = document.createElement('dd');
    detail.textContent = value.toLocaleString();
    layoutStatsEl.append(term, detail);
  });
}

function openCaptureWorkflow() {
  captureCountStepEl.hidden = false;
  captureQrStepEl.hidden = true;
  const pixelOptions = new Set(['250', '500', '1000', '1500', '2000']);
  const currentCount = String(layoutPoints.length);
  capturePixelCountEl.value = pixelOptions.has(currentCount) ? currentCount : '250';
  setCaptureStatus('');
  captureLayoutFileEl.value = '';
  captureLayoutFileEl.disabled = false;
  captureSession = null;
  captureModalEl.showModal();
  capturePixelCountEl.focus();
}

function updateGenerateLayoutFields() {
  const type = generateLayoutTypeEl.value;
  const rectangle = type === 'rectangle';
  generateRectangleFieldsEl.hidden = !rectangle;
  generateRadialFieldsEl.hidden = rectangle;
  generateCenterSpacingFieldEl.hidden = type !== 'dual-radial';
  document.getElementById('generate-center-spacing').required = type === 'dual-radial';
  generateLayoutErrorEl.hidden = true;
  generateLayoutErrorEl.textContent = '';
}

function openGenerateLayoutDialog() {
  updateGenerateLayoutFields();
  generateLayoutModalEl.showModal();
  generateLayoutTypeEl.focus();
}

function generateLayoutOptions() {
  const number = (id) => Number(document.getElementById(id).value);
  const optionalNumber = (id) => {
    const value = document.getElementById(id).value;
    return value === '' ? null : Number(value);
  };
  const type = generateLayoutTypeEl.value;
  const stringLeds = optionalNumber(type === 'rectangle'
    ? 'generate-rectangle-string-leds' : 'generate-radial-string-leds');
  if (type === 'rectangle') {
    return {
      type,
      columns: number('generate-columns'),
      rows: number('generate-rows'),
      stringLeds,
    };
  }
  return {
    type,
    width: number('generate-width'),
    height: number('generate-height'),
    ledDistance: number('generate-led-distance'),
    hubRadius: number('generate-hub-radius'),
    spokes: number('generate-spokes'),
    centerSpacing: type === 'dual-radial' ? number('generate-center-spacing') : 0,
    sectionLeds: number('generate-section-leds'),
    stringLeds,
    maxSpokeLength: optionalNumber('generate-max-spoke-length'),
  };
}

async function uploadGeneratedLayout() {
  const fields = generateLayoutTypeEl.value === 'rectangle'
    ? generateRectangleFieldsEl : generateRadialFieldsEl;
  const invalid = [...fields.querySelectorAll('input')]
    .find((input) => !input.closest('label').hidden && !input.checkValidity());
  if (invalid) {
    invalid.reportValidity();
    return;
  }
  generateLayoutSubmitEl.disabled = true;
  generateLayoutErrorEl.hidden = true;
  try {
    const layout = window.LayoutGenerator.generateLayout(generateLayoutOptions());
    await request('/api/layout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(layout),
    });
    const result = await request('/api/layout');
    layoutPoints = result.points;
    layoutStats = result.stats;
    renderLayoutStats();
    drawLayoutPreview();
    await updateState({ led_effect: 'layout_colors' });
    generateLayoutModalEl.close();
  } catch (error) {
    generateLayoutErrorEl.textContent = error.message;
    generateLayoutErrorEl.hidden = false;
  } finally {
    generateLayoutSubmitEl.disabled = false;
  }
}

async function startCaptureWorkflow() {
  if (!capturePixelCountEl.reportValidity()) return;
  const pixels = Number(capturePixelCountEl.value);
  captureNextEl.disabled = true;
  try {
    const session = await request('/api/capture-sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pixels, origin: window.location.origin }),
    });
    if (!captureModalEl.open) {
      await request(`/api/capture-sessions/${encodeURIComponent(session.token)}`, {
        method: 'DELETE',
        keepalive: true,
      });
      return;
    }
    captureSession = session;
    await updateState({ led_effect: 'calibration' });
    captureCountStepEl.hidden = true;
    captureQrStepEl.hidden = false;
    captureQrImageEl.src = captureSession.qr_url;
    setCaptureStatus('Waiting for the phone to upload the captured layout.');
    capturePollTimer = setInterval(checkCaptureSession, 2500);
  } catch (error) {
    setCaptureStatus(error.message, true);
  } finally {
    captureNextEl.disabled = false;
  }
}

async function checkCaptureSession() {
  if (!captureSession) return;
  try {
    const status = await request(`/api/capture-sessions/${encodeURIComponent(captureSession.token)}`);
    if (status.uploaded) {
      await finishCaptureUpload();
    } else if (!status.active) {
      clearInterval(capturePollTimer);
      capturePollTimer = null;
      setCaptureStatus('This capture session has ended. Close this dialog and start again.', true);
    }
  } catch (error) {
    setCaptureStatus(error.message, true);
  }
}

async function finishCaptureUpload(message = 'Layout uploaded and saved. Restart fbmserve to apply it.') {
  clearInterval(capturePollTimer);
  capturePollTimer = null;
  setCaptureStatus(message);
  captureLayoutFileEl.disabled = true;
  const result = await request('/api/layout');
  layoutPoints = result.points;
  layoutStats = result.stats;
  renderLayoutStats();
  drawLayoutPreview();
  await updateState({ led_effect: 'layout_colors' });
  await closeCaptureWorkflow();
}

async function uploadCaptureFile() {
  const file = captureLayoutFileEl.files[0];
  if (!file || !captureSession) return;
  setCaptureStatus('Uploading layout...');
  captureLayoutFileEl.disabled = true;
  try {
    const result = await request(captureSession.upload_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: await file.text(),
    });
    await finishCaptureUpload(result.message);
  } catch (error) {
    setCaptureStatus(error.message, true);
    captureLayoutFileEl.disabled = false;
    captureLayoutFileEl.value = '';
  }
}

async function closeCaptureWorkflow() {
  clearInterval(capturePollTimer);
  capturePollTimer = null;
  const token = captureSession?.token;
  captureSession = null;
  if (token) {
    try {
      await request(`/api/capture-sessions/${encodeURIComponent(token)}`, {
        method: 'DELETE',
        keepalive: true,
      });
    } catch (error) {
      console.warn('Could not close capture session:', error.message);
    }
  }
  captureQrImageEl.removeAttribute('src');
  captureLayoutFileEl.disabled = false;
  captureCountStepEl.hidden = false;
  captureQrStepEl.hidden = true;
  if (captureModalEl.open) captureModalEl.close();
  if (state.input_mode === 'setup' && state.led_effect !== 'layout_colors') {
    await updateState({ led_effect: 'layout_colors' });
  }
}

function initWebGL() {
  preview.gl = canvas.getContext('webgl2', { alpha: false, antialias: false });
  if (!preview.gl) {
    preview.error = 'WebGL2 is not available';
    return;
  }

  preview.buffer = preview.gl.createBuffer();
  preview.gl.bindBuffer(preview.gl.ARRAY_BUFFER, preview.buffer);
  preview.gl.bufferData(preview.gl.ARRAY_BUFFER, new Float32Array([
    -1, -1,
     1, -1,
    -1,  1,
     1,  1,
  ]), preview.gl.STATIC_DRAW);
}

function renderEffects() {
  effectsEl.replaceChildren();

  for (const effect of state.effects) {
    const row = document.createElement('div');
    row.className = 'effect-row';
    row.classList.toggle('active', effect.id === state.effect);

    const checkbox = document.createElement('input');
    checkbox.className = 'effect-autoplay';
    checkbox.type = 'checkbox';
    checkbox.checked = state.autoplay_effects.includes(effect.id);
    checkbox.setAttribute('aria-label', `Use ${effect.name} in autoplay`);
    checkbox.addEventListener('change', () => updateAutoplayEffect(effect.id, checkbox.checked));

    const button = document.createElement('button');
    button.className = 'effect-button';
    button.type = 'button';
    button.textContent = effect.name;
    button.dataset.effect = effect.id;
    button.classList.toggle('active', effect.id === state.effect);
    button.addEventListener('click', () => updateState({ effect: effect.id }));

    row.append(checkbox, button);
    effectsEl.appendChild(row);
  }
}

function renderLedEffects() {
  ledEffectsEl.replaceChildren();
  for (const effect of state.led_effects) {
    const button = document.createElement('button');
    button.className = 'effect-button';
    button.type = 'button';
    button.textContent = effect.name;
    button.classList.toggle('active', effect.id === state.led_effect);
    button.addEventListener('click', () => updateState({ led_effect: effect.id }));
    ledEffectsEl.appendChild(button);
  }
}

function renderControls() {
  const effectMode = state.input_mode === 'effect';
  colorEls.forEach((el, index) => {
    if (document.activeElement !== el) el.value = rgbToHex(state[colorKeys[index]]);
  });
  speedEl.value = state.speed;
  brightnessEl.value = state.brightness;
  supersampleEl.value = state.supersample;
  fitModeEl.value = state.fit_mode || 'fill';
  autoplayEl.checked = state.autoplay;
  modeEffectEl.classList.toggle('active', effectMode);
  modeEffectEl.setAttribute('aria-pressed', String(effectMode));
  const ndiMode = state.input_mode === 'ndi';
  const networkMode = state.input_mode === 'network_matrix';
  const setupMode = state.input_mode === 'setup';
  modeNetworkEl.classList.toggle('active', networkMode);
  modeNetworkEl.setAttribute('aria-pressed', String(networkMode));
  modeSetupEl.classList.toggle('active', setupMode);
  modeSetupEl.setAttribute('aria-pressed', String(setupMode));
  document.getElementById('network-panel').hidden = !networkMode;
  matrixSizeEl.value = state.matrix_size;
  matrixChannelsEl.value = state.matrix_channels_per_universe;
  matrixProtocolEl.value = state.matrix_protocol;
  const firstUniverseCapacity = state.matrix_channels_per_universe - state.matrix_start_address + 1;
  const remainingChannels = Math.max(0, state.matrix_size ** 2 * 3 - firstUniverseCapacity);
  const universeCount = 1 + Math.ceil(remainingChannels / state.matrix_channels_per_universe);
  matrixStartEl.max = 32768 - universeCount;
  matrixSacnStartEl.max = 63999 - universeCount + 1;
  if (document.activeElement !== matrixStartEl) matrixStartEl.value = state.matrix_artnet.port_address;
  if (document.activeElement !== matrixSacnStartEl) matrixSacnStartEl.value = state.matrix_sacn.universe;
  document.getElementById('matrix-artnet-universe-label').hidden = state.matrix_protocol !== 'artnet';
  document.getElementById('matrix-sacn-universe-label').hidden = state.matrix_protocol !== 'sacn';
  document.getElementById('matrix-protocol-help').textContent = state.matrix_protocol === 'sacn'
    ? 'RGB, left to right, top to bottom. Match channel packing to your sender. sACN uses UDP port 5568 and universe multicast.'
    : 'RGB, left to right, top to bottom. Match channel packing to your sender. Art-Net uses UDP port 6454.';
  if (document.activeElement !== matrixAddressEl) matrixAddressEl.value = state.matrix_start_address;
  matrixAddressEl.max = state.matrix_channels_per_universe;
  const stats = state.matrix_status || {};
  matrixStatusEl.textContent = stats.packets
    ? `${stats.packets} packets / ${stats.age < 2 ? 'Receiving' : 'Signal lost; holding pixels'}`
    : `Waiting for ${state.matrix_protocol === 'sacn' ? 'sACN' : 'Art-Net'}`;
  matrixErrorEl.hidden = !state.error;
  matrixErrorEl.textContent = state.error || '';
  modeNdiEl.classList.toggle('active', ndiMode);
  modeNdiEl.setAttribute('aria-pressed', String(ndiMode));
  workspaceEl.hidden = !effectMode;
  document.getElementById('output-controls').hidden =
    !(effectMode || ndiMode || networkMode || setupMode);
  document.getElementById('output-controls').classList.toggle('setup-mode', setupMode);
  document.getElementById('led-effects-settings').hidden = setupMode;
  document.getElementById('output-settings').hidden = !setupMode;
  document.getElementById('image-quality-settings').hidden = setupMode;
  document.getElementById('network-control-panel').hidden = !setupMode;
  ndiPanelEl.hidden = !ndiMode;
  const ndiStatus = currentNdiStatus();
  ndiStatusEl.hidden = !ndiMode || !ndiStatus;
  ndiStatusEl.textContent = ndiStatus;
  ndiErrorEl.hidden = !ndiMode || !state.error;
  ndiErrorEl.textContent = state.error || '';
  renderNdiSources();
  if (document.activeElement !== autoplayIntervalEl) {
    autoplayIntervalEl.value = Math.round(state.autoplay_interval);
  }
  renderEffects();
  renderLedEffects();
  networkControlEnabledEl.checked = state.network_control_enabled;
  networkControlProtocolEl.value = state.network_control_protocol;
  if (document.activeElement !== networkControlArtNetEl) networkControlArtNetEl.value = state.network_control_artnet.port_address;
  if (document.activeElement !== networkControlSacnEl) networkControlSacnEl.value = state.network_control_sacn.universe;
  if (document.activeElement !== networkControlAddressEl) networkControlAddressEl.value = state.network_control_start_address;
  if (document.activeElement !== networkControlHoldEl) networkControlHoldEl.value = state.network_control_hold;
  const controlSacn = state.network_control_protocol === 'sacn';
  document.getElementById('network-control-artnet-label').hidden = controlSacn;
  document.getElementById('network-control-sacn-label').hidden = !controlSacn;
  const controlStats = state.network_control_status || {};
  networkControlStatusEl.textContent = controlStats.error ? 'Unavailable'
    : !state.network_control_enabled ? 'Disabled'
      : controlStats.packets ? `${controlStats.packets} packets / ${controlStats.age <= state.network_control_hold ? 'Receiving' : 'Signal lost; using web controls'}`
        : `Waiting for ${controlSacn ? 'sACN' : 'Art-Net'}`;
  networkControlErrorEl.hidden = !controlStats.error;
  networkControlErrorEl.textContent = controlStats.error || '';
  if (controlStats.error) networkControlStatusEl.textContent += ` / ${controlStats.error}`;
}

function renderNdiSources() {
  const selected = state.ndi_source;
  ndiSourceEl.replaceChildren();
  if (!selected && state.ndi_sources.length === 0) {
    ndiSourceEl.add(new Option('No NDI sources found', '', true, true));
  }
  if (selected && !state.ndi_sources.includes(selected)) {
    ndiSourceEl.add(new Option(`${selected} (offline)`, selected, true, true));
  }
  for (const name of state.ndi_sources) {
    ndiSourceEl.add(new Option(name, name, name === selected, name === selected));
  }
  if (!selected && state.ndi_sources.length) {
    ndiSourceEl.selectedIndex = -1;
  }
}

async function refreshNdiSources() {
  try {
    const result = await request('/api/ndi/sources');
    state.ndi_sources = result.sources;
    renderNdiSources();
  } catch (error) {
    console.error(error.message);
  }
}

function setOnline(online, message) {
  signalEl.classList.toggle('online', online);
  statusEl.textContent = online ? currentStatus() : 'Offline';

  if (state.error) {
    statusEl.textContent = state.error;
  }
  if (preview.error) {
    statusEl.textContent = preview.error;
  }
  if (message && !online) {
    console.error(message);
  }
}

function currentStatus() {
  if (state.input_mode === 'setup') {
    const setupEffect = state.led_effects.find((item) => item.id === state.led_effect);
    return setupEffect ? `Setup / ${setupEffect.name}` : 'Setup';
  }
  if (state.input_mode === 'network_matrix') return `${state.matrix_protocol === 'sacn' ? 'sACN' : 'Art-Net'} / ${state.matrix_size} x ${state.matrix_size}`;
  if (state.input_mode === 'ndi') {
    if (!state.ndi_source) return 'Select an NDI source';
    return state.ndi_source;
  }
  const effect = state.effects.find((item) => item.id === state.effect);
  const ledEffect = state.led_effects.find((item) => item.id === state.led_effect);
  if (effect && ledEffect) return `${effect.name} + ${ledEffect.name}`;
  return effect ? effect.name : 'Ready';
}

function currentNdiStatus() {
  if (!state.ndi_source) return '';
  if (!state.ndi_sources.includes(state.ndi_source)) return 'Offline';

  const stats = state.ndi_status || {};
  if (!stats.width || !stats.height) return 'Waiting for video';

  const details = [`${stats.width}×${stats.height}`];
  if (stats.fps) details.push(`${stats.fps.toFixed(1)} fps`);
  if (Number.isFinite(stats.dropped)) details.push(`${stats.dropped} dropped`);
  return details.join(' · ');
}

async function updateState(values) {
  Object.assign(state, values);
  renderControls();

  if (values.effect && state.input_mode === 'effect') {
    await loadPreviewEffect(values.effect);
  }

  try {
    Object.assign(state, await request('/api/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    }));
    setOnline(true);
    renderControls();
  } catch (error) {
    setOnline(false, error.message);
  }
}

function debounce(callback, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => callback(...args), delay);
  };
}

function updateAutoplayEffect(effectId, checked) {
  const selected = new Set(state.autoplay_effects);
  if (checked) {
    selected.add(effectId);
  } else {
    selected.delete(effectId);
  }

  updateState({
    autoplay_effects: state.effects
      .map((effect) => effect.id)
      .filter((id) => selected.has(id)),
  });
}

async function refreshState() {
  try {
    const previousEffect = state.effect;
    Object.assign(state, await request('/api/state'));
    if (state.input_mode === 'effect' && state.effect !== previousEffect) {
      await loadPreviewEffect(state.effect);
    }
    setOnline(true);
    renderControls();
  } catch (error) {
    setOnline(false, error.message);
  }
}

async function loadPreviewEffect(effectId) {
  if (!preview.gl || !effectId || preview.effect === effectId) {
    setOnline(Boolean(preview.gl));
    return;
  }

  try {
    const source = await request(`/api/effects/${encodeURIComponent(effectId)}/source`);
    const program = createProgram(wrapVertexSource(), wrapFragmentSource(source));
    if (preview.program) {
      preview.gl.deleteProgram(preview.program);
    }
    preview.program = program;
    preview.effect = effectId;
    preview.error = null;
  } catch (error) {
    preview.error = error.message;
  }

  setOnline(true);
}

function wrapVertexSource() {
  return `#version 300 es
    in vec2 position;
    out highp vec2 v_texcoor;

    void main() {
      v_texcoor = position * 0.5 + 0.5;
      gl_Position = vec4(position, 0.0, 1.0);
    }`;
}

function wrapFragmentSource(source) {
  return `#version 300 es
    precision highp float;

    out highp vec4 f_color;
    in highp vec2 v_texcoor;

    uniform highp float iTime;
    uniform highp vec2 iResolution;
    uniform highp vec3 iColor1;
    uniform highp vec3 iColor2;
    uniform highp vec3 iColor3;
    uniform highp float iBrightness;
    uniform highp float fitSourceAspect;
    uniform highp float fitTargetAspect;
    uniform highp int fitMode;

    highp vec2 fitSourceUV(highp vec2 outputUV, out highp float insideSource) {
      highp vec2 sourceUV = outputUV;
      insideSource = 1.0;
      if (fitMode == 0) {
        if (fitSourceAspect > fitTargetAspect)
          sourceUV.x = 0.5 + (outputUV.x - 0.5) * fitTargetAspect / fitSourceAspect;
        else
          sourceUV.y = 0.5 + (outputUV.y - 0.5) * fitSourceAspect / fitTargetAspect;
      } else if (fitMode == 1) {
        if (fitSourceAspect > fitTargetAspect) {
          highp float occupied = fitTargetAspect / fitSourceAspect;
          highp float bottom = (1.0 - occupied) * 0.5;
          if (outputUV.y < bottom || outputUV.y > 1.0 - bottom) insideSource = 0.0;
          sourceUV.y = (outputUV.y - bottom) / occupied;
        } else {
          highp float occupied = fitSourceAspect / fitTargetAspect;
          highp float left = (1.0 - occupied) * 0.5;
          if (outputUV.x < left || outputUV.x > 1.0 - left) insideSource = 0.0;
          sourceUV.x = (outputUV.x - left) / occupied;
        }
      }
      return sourceUV;
    }

    ${stripVersion(source)}

    void main() {
      highp vec4 color;
      highp float insideSource;
      highp vec2 sourceUV = fitSourceUV(v_texcoor, insideSource);
      if (insideSource < 0.5) color = vec4(0.0, 0.0, 0.0, 1.0);
      else mainImage(color, sourceUV * iResolution);
      f_color = vec4(color.rgb * iBrightness, color.a);
    }`;
}

function stripVersion(source) {
  return source.replace(/^\s*#version\s+.+$/m, '');
}

function createProgram(vertexSource, fragmentSource) {
  const gl = preview.gl;
  const vertex = compileShader(gl.VERTEX_SHADER, vertexSource);
  const fragment = compileShader(gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();

  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(log || 'Shader link failed');
  }

  return program;
}

function compileShader(type, source) {
  const gl = preview.gl;
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);

  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(log || 'Shader compile failed');
  }

  return shader;
}

function drawPreview() {
  requestAnimationFrame(drawPreview);

  const frameTime = performance.now();
  preview.effect_time += (frameTime - preview.last_frame) / 1000 * Number(state.speed);
  preview.last_frame = frameTime;

  const gl = preview.gl;
  if (!gl || !preview.program) {
    return;
  }

  resizeCanvas();

  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.useProgram(preview.program);

  setUniform1f('iTime', preview.effect_time);
  setUniform2f('iResolution', canvas.height, canvas.height);
  colorKeys.forEach((key, index) => {
    const loc = gl.getUniformLocation(preview.program, `iColor${index + 1}`);
    gl.uniform3fv(loc, state[key]);
  });
  setUniform1f('iBrightness', Number(state.brightness));
  setUniform1f('fitSourceAspect', 1);
  setUniform1f('fitTargetAspect', canvas.width / canvas.height);
  const fitMode = { fill: 0, fit: 1, stretch: 2 }[state.fit_mode || 'fill'];
  const fitModeLocation = gl.getUniformLocation(preview.program, 'fitMode');
  gl.uniform1i(fitModeLocation, fitMode);

  const position = gl.getAttribLocation(preview.program, 'position');
  gl.bindBuffer(gl.ARRAY_BUFFER, preview.buffer);
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.floor(rect.width * ratio));
  const height = Math.max(1, Math.floor(rect.height * ratio));

  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
}

function setUniform1f(name, value) {
  const loc = preview.gl.getUniformLocation(preview.program, name);
  preview.gl.uniform1f(loc, value);
}

function setUniform2f(name, x, y) {
  const loc = preview.gl.getUniformLocation(preview.program, name);
  preview.gl.uniform2f(loc, x, y);
}

function rgbToHex(rgb) {
  return '#' + rgb.map((value) => Math.round(value * 255).toString(16).padStart(2, '0')).join('');
}

function hexToRgb(hex) {
  return [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255);
}

colorEls.forEach((el, index) => {
  const key = colorKeys[index];
  const sendColor = debounce((color) => updateState({ [key]: color }), SLIDER_UPDATE_DELAY);
  el.addEventListener('input', () => {
    state[key] = hexToRgb(el.value);
    sendColor(state[key]);
  });
});
const updateBrightness = debounce(
  (brightness) => updateState({ brightness }),
  SLIDER_UPDATE_DELAY,
);
const updateSpeed = debounce(
  (speed) => updateState({ speed }),
  SLIDER_UPDATE_DELAY,
);
const updateSupersample = debounce(
  (supersample) => updateState({ supersample }),
  SLIDER_UPDATE_DELAY,
);

brightnessEl.addEventListener('input', () => {
  state.brightness = Number(brightnessEl.value);
  updateBrightness(state.brightness);
});
speedEl.addEventListener('input', () => {
  state.speed = Number(speedEl.value);
  updateSpeed(state.speed);
});
supersampleEl.addEventListener('input', () => {
  state.supersample = Number(supersampleEl.value);
  updateSupersample(state.supersample);
});
fitModeEl.addEventListener('change', () => {
  updateState({ fit_mode: fitModeEl.value });
  drawLayoutPreview();
});
autoplayEl.addEventListener('change', () => updateState({ autoplay: autoplayEl.checked }));
autoplayIntervalEl.addEventListener('change', () => updateState({
  autoplay_interval: Number(autoplayIntervalEl.value),
}));
matrixAddressEl.addEventListener('change', () => {
  if (matrixAddressEl.reportValidity()) updateState({ matrix_start_address: Number(matrixAddressEl.value) });
});
modeNetworkEl.addEventListener('click', () => switchMode('network_matrix'));
modeSetupEl.addEventListener('click', () => switchMode('setup'));
matrixChannelsEl.addEventListener('change', () => {
  const channels = Number(matrixChannelsEl.value);
  const address = Math.min(state.matrix_start_address, channels);
  updateState({ matrix_channels_per_universe: channels, matrix_start_address: address });
});
matrixSizeEl.addEventListener('change', () => updateState({ matrix_size: Number(matrixSizeEl.value) }));
matrixStartEl.addEventListener('change', () => {
  if (matrixStartEl.reportValidity()) updateState({
    matrix_artnet: { ...state.matrix_artnet, port_address: Number(matrixStartEl.value) },
  });
});
matrixSacnStartEl.addEventListener('change', () => {
  if (matrixSacnStartEl.reportValidity()) updateState({
    matrix_sacn: { ...state.matrix_sacn, universe: Number(matrixSacnStartEl.value) },
  });
});
matrixProtocolEl.addEventListener('change', () => updateState({ matrix_protocol: matrixProtocolEl.value }));
modeEffectEl.addEventListener('click', () => switchMode('effect'));
modeNdiEl.addEventListener('click', () => switchMode('ndi'));
captureOpenEl.addEventListener('click', openCaptureWorkflow);
captureCloseEl.addEventListener('click', closeCaptureWorkflow);
captureNextEl.addEventListener('click', startCaptureWorkflow);
captureLayoutFileEl.addEventListener('change', uploadCaptureFile);
captureQrImageEl.addEventListener('error', () => {
  setCaptureStatus('Could not generate the QR code. You can still upload a saved layout JSON file.', true);
});
captureModalEl.addEventListener('cancel', (event) => {
  event.preventDefault();
  closeCaptureWorkflow();
});
captureModalEl.addEventListener('click', (event) => {
  if (event.target === captureModalEl) closeCaptureWorkflow();
});
document.getElementById('generate-layout-open').addEventListener('click', openGenerateLayoutDialog);
document.getElementById('generate-layout-close').addEventListener('click', () => generateLayoutModalEl.close());
document.getElementById('generate-layout-submit').addEventListener('click', uploadGeneratedLayout);
generateLayoutTypeEl.addEventListener('change', updateGenerateLayoutFields);
generateLayoutModalEl.addEventListener('click', (event) => {
  if (event.target === generateLayoutModalEl) generateLayoutModalEl.close();
});
ndiSourceEl.addEventListener('change', () => {
  if (ndiSourceEl.value) updateState({ ndi_source: ndiSourceEl.value, input_mode: 'ndi' });
});
networkControlEnabledEl.addEventListener('change', () => updateState({ network_control_enabled: networkControlEnabledEl.checked }));
networkControlProtocolEl.addEventListener('change', () => updateState({ network_control_protocol: networkControlProtocolEl.value }));
networkControlArtNetEl.addEventListener('change', () => {
  if (networkControlArtNetEl.reportValidity()) updateState({ network_control_artnet: { ...state.network_control_artnet, port_address: Number(networkControlArtNetEl.value) } });
});
networkControlSacnEl.addEventListener('change', () => {
  if (networkControlSacnEl.reportValidity()) updateState({ network_control_sacn: { ...state.network_control_sacn, universe: Number(networkControlSacnEl.value) } });
});
networkControlAddressEl.addEventListener('change', () => {
  if (networkControlAddressEl.reportValidity()) updateState({ network_control_start_address: Number(networkControlAddressEl.value) });
});
networkControlHoldEl.addEventListener('change', () => {
  if (networkControlHoldEl.reportValidity()) updateState({ network_control_hold: Number(networkControlHoldEl.value) });
});

setInterval(refreshState, 1500);
setInterval(refreshNdiSources, 3000);
init();
