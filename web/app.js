const state = {
  effects: [],
  effect: null,
  hue: 0,
  brightness: 1,
  autoplay: false,
  autoplay_interval: 30,
  error: null,
};

const preview = {
  gl: null,
  program: null,
  buffer: null,
  effect: null,
  start: performance.now(),
  error: null,
};

const effectsEl = document.getElementById('effects');
const hueEl = document.getElementById('hue');
const brightnessEl = document.getElementById('brightness');
const autoplayEl = document.getElementById('autoplay');
const autoplayIntervalEl = document.getElementById('autoplay-interval');
const statusEl = document.getElementById('status');
const signalEl = document.getElementById('signal');
const canvas = document.getElementById('swatch');

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
    Object.assign(state, await request('/api/state'));
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
    const button = document.createElement('button');
    button.className = 'effect-button';
    button.type = 'button';
    button.textContent = effect.name;
    button.dataset.effect = effect.id;
    button.classList.toggle('active', effect.id === state.effect);
    button.addEventListener('click', () => updateState({ effect: effect.id }));
    effectsEl.appendChild(button);
  }
}

function renderControls() {
  hueEl.value = state.hue;
  brightnessEl.value = state.brightness;
  autoplayEl.checked = state.autoplay;
  if (document.activeElement !== autoplayIntervalEl) {
    autoplayIntervalEl.value = Math.round(state.autoplay_interval);
  }
  renderEffects();
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
  const effect = state.effects.find((item) => item.id === state.effect);
  return effect ? effect.name : 'Ready';
}

async function updateState(values) {
  Object.assign(state, values);
  renderControls();

  if (values.effect) {
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

async function refreshState() {
  try {
    const previousEffect = state.effect;
    Object.assign(state, await request('/api/state'));
    if (state.effect !== previousEffect) {
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

hueEl.addEventListener('input', () => updateState({ hue: Number(hueEl.value) }));
brightnessEl.addEventListener('input', () => updateState({ brightness: Number(brightnessEl.value) }));
autoplayEl.addEventListener('change', () => updateState({ autoplay: autoplayEl.checked }));
autoplayIntervalEl.addEventListener('change', () => updateState({
  autoplay_interval: Number(autoplayIntervalEl.value),
}));

setInterval(refreshState, 1500);
init();
