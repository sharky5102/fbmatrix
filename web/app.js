const state = {
  effects: [],
  led_effects: [],
  effect: null,
  led_effect: 'default',
  hue: 0,
  brightness: 1,
  supersample: 3,
  autoplay: false,
  autoplay_interval: 30,
  autoplay_effects: [],
  error: null,
  input_mode: 'effect',
  ndi_source: null,
  ndi_sources: [],
  ndi_status: {},
};

const preview = {
  gl: null,
  program: null,
  buffer: null,
  effect: null,
  start: performance.now(),
  error: null,
};

const SLIDER_UPDATE_DELAY = 100;

const effectsEl = document.getElementById('effects');
const ledEffectsEl = document.getElementById('led-effects');
const hueEl = document.getElementById('hue');
const brightnessEl = document.getElementById('brightness');
const supersampleEl = document.getElementById('supersample');
const autoplayEl = document.getElementById('autoplay');
const autoplayIntervalEl = document.getElementById('autoplay-interval');
const statusEl = document.getElementById('status');
const signalEl = document.getElementById('signal');
const canvas = document.getElementById('swatch');
const workspaceEl = document.getElementById('workspace');
const modeEffectEl = document.getElementById('mode-effect');
const modeNdiEl = document.getElementById('mode-ndi');
const ndiSourceEl = document.getElementById('ndi-source');
const ndiPanelEl = document.getElementById('ndi-panel');
const ndiStatusEl = document.getElementById('ndi-status');
const ndiErrorEl = document.getElementById('ndi-error');

async function request(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(await response.text());
  }

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  return response.text();
}

async function init() {
  initWebGL();

  try {
    state.effects = await request('/api/effects');
    state.led_effects = await request('/api/led-effects');
    Object.assign(state, await request('/api/state'));
    await refreshNdiSources();
    renderControls();
    await loadPreviewEffect(state.effect);
    setOnline(true);
    requestAnimationFrame(drawPreview);
  } catch (error) {
    setOnline(false, error.message);
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
  hueEl.value = state.hue;
  brightnessEl.value = state.brightness;
  supersampleEl.value = state.supersample;
  autoplayEl.checked = state.autoplay;
  modeEffectEl.classList.toggle('active', effectMode);
  modeEffectEl.setAttribute('aria-pressed', String(effectMode));
  modeNdiEl.classList.toggle('active', !effectMode);
  modeNdiEl.setAttribute('aria-pressed', String(!effectMode));
  workspaceEl.hidden = !effectMode;
  ndiPanelEl.hidden = effectMode;
  const ndiStatus = currentNdiStatus();
  ndiStatusEl.hidden = effectMode || !ndiStatus;
  ndiStatusEl.textContent = ndiStatus;
  ndiErrorEl.hidden = effectMode || !state.error;
  ndiErrorEl.textContent = state.error || '';
  renderNdiSources();
  if (document.activeElement !== autoplayIntervalEl) {
    autoplayIntervalEl.value = Math.round(state.autoplay_interval);
  }
  renderEffects();
  renderLedEffects();
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
    uniform highp float iHue;
    uniform highp float iBrightness;

    ${stripVersion(source)}

    void main() {
      highp vec4 color;
      mainImage(color, v_texcoor * iResolution);
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

  const gl = preview.gl;
  if (!gl || !preview.program) {
    return;
  }

  resizeCanvas();

  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.useProgram(preview.program);

  setUniform1f('iTime', (performance.now() - preview.start) / 1000);
  setUniform2f('iResolution', canvas.width, canvas.height);
  setUniform1f('iHue', Number(state.hue));
  setUniform1f('iBrightness', Number(state.brightness));

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

const updateHue = debounce((hue) => updateState({ hue }), SLIDER_UPDATE_DELAY);
const updateBrightness = debounce(
  (brightness) => updateState({ brightness }),
  SLIDER_UPDATE_DELAY,
);
const updateSupersample = debounce(
  (supersample) => updateState({ supersample }),
  SLIDER_UPDATE_DELAY,
);

hueEl.addEventListener('input', () => {
  state.hue = Number(hueEl.value);
  updateHue(state.hue);
});
brightnessEl.addEventListener('input', () => {
  state.brightness = Number(brightnessEl.value);
  updateBrightness(state.brightness);
});
supersampleEl.addEventListener('input', () => {
  state.supersample = Number(supersampleEl.value);
  updateSupersample(state.supersample);
});
autoplayEl.addEventListener('change', () => updateState({ autoplay: autoplayEl.checked }));
autoplayIntervalEl.addEventListener('change', () => updateState({
  autoplay_interval: Number(autoplayIntervalEl.value),
}));
modeEffectEl.addEventListener('click', () => updateState({ input_mode: 'effect' }));
modeNdiEl.addEventListener('click', () => updateState({ input_mode: 'ndi' }));
ndiSourceEl.addEventListener('change', () => {
  if (ndiSourceEl.value) updateState({ ndi_source: ndiSourceEl.value, input_mode: 'ndi' });
});

setInterval(refreshState, 1500);
setInterval(refreshNdiSources, 3000);
init();
