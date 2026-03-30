const PHASES = ['problem','debate','converge','solution'];
const PHASE_LABELS = {problem:'DEFINE', debate:'DEBATE', converge:'CONVERGE', solution:'SOLVE'};
const PHASE_ICONS  = {problem:'◇', debate:'◆', converge:'◈', solution:'▣'};
const PHASE_COLORS = {problem:'#fbbf24', debate:'#ff6b3d', converge:'#c084fc', solution:'#34d399'};

const AGENT_RAW_COLORS = {orange:'#ff6b3d', blue:'#3d8bff', green:'#34d399', magenta:'#c084fc', cyan:'#22d3ee'};
const AGENT_CSS_COLORS = {orange:'var(--orange)', blue:'var(--blue)', green:'var(--green)', magenta:'var(--magenta)', cyan:'var(--cyan)'};

const PROBLEM_CHIPS = [
  'how to reduce meeting fatigue in remote teams',
  'design an AI-powered education system for underserved areas',
  'solve urban food waste at scale',
  'make open source financially sustainable',
  'prevent social media from harming teen mental health',
  'decarbonize shipping and logistics',
];

let state = {
  screen:'setup', ws:null, config:{}, messages:[], proposals:[],
  proposalRecords:[], chairmanVerdict:null,
  phase:'problem', turn:0, totalTurns:20, consensus:0,
  thinking:null, lastProtocol:null, showJson:false,
  audioData:{}, stopped:false, topic:'', agentRoster:null,
  speakingAgent:null, // which agent is currently speaking (for waveform)
  // P2: ETA tracking
  turnStartTime:null,     // timestamp when current turn started
  turnDurations:[],       // array of past turn durations in ms
  sessionStartTime:null,  // when the session began
  // P2: Error toast
  errorToast:null,        // {msg, timer} or null
  // Fix 8: Mobile panel
  mobilePanelOpen:false,
  // Fix 9: Connection lost
  connectionLost:false,
  // Fix 10: Audio failures per turn
  audioFailed:{},         // {turn: true} for turns where audio decode failed
  // Fix 11: Pause
  paused:false,
};

const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
let currentSource = null;
let analyserNode = null;
let errorToastTimer = null;

// ── Error toast ──────────────────────────────────────────────
function showErrorToast(msg) {
  // Clear any existing toast timer
  if (errorToastTimer) clearTimeout(errorToastTimer);
  state.errorToast = msg;
  renderErrorToast();
  // Auto-dismiss after 12 seconds
  errorToastTimer = setTimeout(() => dismissErrorToast(), 12000);
}

function dismissErrorToast(animate) {
  if (errorToastTimer) { clearTimeout(errorToastTimer); errorToastTimer = null; }
  const el = document.getElementById('error-toast');
  if (el && animate !== false) {
    el.style.animation = 'toastSlideOut 0.25s ease forwards';
    setTimeout(() => { state.errorToast = null; renderErrorToast(); }, 250);
  } else {
    state.errorToast = null;
    renderErrorToast();
  }
}

function renderErrorToast() {
  let container = document.getElementById('error-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'error-toast-container';
    document.body.appendChild(container);
  }
  if (!state.errorToast) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = `
    <div class="error-toast" id="error-toast">
      <span class="error-toast-icon">⚠</span>
      <div class="error-toast-body">
        <div class="error-toast-msg">${esc(state.errorToast)}</div>
      </div>
      <button class="error-toast-dismiss" onclick="dismissErrorToast()">dismiss</button>
    </div>`;
}

// ── ETA calculation ─────────────────────────────────────────
function formatEta(ms) {
  if (!ms || ms < 0) return '';
  const secs = Math.ceil(ms / 1000);
  if (secs < 60) return `~${secs}s left`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `~${mins}m${remSecs > 0 ? ` ${remSecs}s` : ''} left`;
}

function getEtaString() {
  if (state.turnDurations.length < 1) return '';
  // Use a moving average of the last 4 turns for stability
  const recent = state.turnDurations.slice(-4);
  const avgMs = recent.reduce((a, b) => a + b, 0) / recent.length;
  const turnsLeft = state.totalTurns - state.turn;
  if (turnsLeft <= 0) return '';
  // Add ~15s for chairman synthesis at the end
  const etaMs = (turnsLeft * avgMs) + 15000;
  return formatEta(etaMs);
}

// ── Message display buffer ──────────────────────────────────
// Messages from the server are buffered here. They are displayed
// one at a time: the next message only appears after the previous
// one's TTS audio finishes playing. Acks are sent to the server
// immediately on receipt so LLM generation keeps running in the
// background — this is what keeps the experience smooth.
let displayQueue = [];
let isProcessingQueue = false;

function enqueueForDisplay(data) {
  displayQueue.push(data);
  if (!isProcessingQueue) processDisplayQueue();
}

async function processDisplayQueue() {
  if (isProcessingQueue) return;
  isProcessingQueue = true;

  while (displayQueue.length > 0) {
    if (state.stopped) { displayQueue = []; break; }

    // Fix 11: Wait while paused
    while (state.paused && !state.stopped) {
      await new Promise(r => setTimeout(r, 200));
    }
    if (state.stopped) { displayQueue = []; break; }

    const data = displayQueue.shift();

    if (data._type === 'message') {
      // Apply state updates (text)
      state.thinking = null;
      state.messages.push(data);
      if (data.proposals) state.proposals = data.proposals;
      if (data.proposal_records) state.proposalRecords = data.proposal_records;
      if (data.agent_roster && !state.agentRoster) state.agentRoster = data.agent_roster;
      state.lastProtocol = data.protocol_message;
      state.phase = data.phase;
      state.turn = data.turn + 1;
      state.consensus = data.consensus || state.consensus;
      render(); scrollChat();

      // Play audio and wait for it to finish before showing next message
      if (data.audio && !state.stopped) {
        try {
          state.speakingAgent = data.agent;
          updateWaveforms();
          await playAudioB64(data.audio, data.audio_format);
        } catch(e) {
          // Fix 10: Track audio failure for this turn
          console.warn('Audio error:', e);
          state.audioFailed[data.turn] = true;
          render();
        }
        state.speakingAgent = null;
        updateWaveforms();
      }

    } else if (data._type === 'chairman') {
      state.thinking = null;
      state.chairmanVerdict = data;
      if (data.proposal_records) state.proposalRecords = data.proposal_records;
      render(); scrollChat();

      if (data.audio && !state.stopped) {
        try {
          state.speakingAgent = 'chairman';
          updateWaveforms();
          await playAudioB64(data.audio, data.audio_format);
        } catch(e) {
          console.warn('Audio error:', e);
          state.audioFailed['chairman'] = true;
          render();
        }
        state.speakingAgent = null;
        updateWaveforms();
      }
    }
  }

  isProcessingQueue = false;
}

// ── Audio playback (returns promise that resolves when audio ENDS) ──
async function playAudioB64(b64, format) {
  try {
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    const raw = atob(b64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const buffer = await audioCtx.decodeAudioData(bytes.buffer.slice(0));
    return new Promise(resolve => {
      const source = audioCtx.createBufferSource();
      source.buffer = buffer;

      // Create analyser for waveform visualization
      analyserNode = audioCtx.createAnalyser();
      analyserNode.fftSize = 64;
      source.connect(analyserNode);
      analyserNode.connect(audioCtx.destination);

      currentSource = source;
      const timeout = setTimeout(() => { currentSource = null; analyserNode = null; resolve(); }, (buffer.duration * 1000) + 3000);
      source.onended = () => { clearTimeout(timeout); currentSource = null; analyserNode = null; resolve(); };
      source.start();
    });
  } catch(e) { console.warn('Audio playback failed:', e); }
}

// ── Waveform visualizer ─────────────────────────────────────
let waveformAnimId = null;

function updateWaveforms() {
  // Cancel any existing animation
  if (waveformAnimId) { cancelAnimationFrame(waveformAnimId); waveformAnimId = null; }

  // Update speaking dot classes
  document.querySelectorAll('.agent-dot').forEach(dot => dot.classList.remove('speaking'));

  if (!state.speakingAgent) {
    // Clear all canvases to flat line
    document.querySelectorAll('.agent-waveform canvas').forEach(c => {
      const ctx = c.getContext('2d');
      const w = c.width, h = c.height;
      ctx.clearRect(0, 0, w, h);
      ctx.beginPath();
      ctx.moveTo(0, h/2);
      ctx.lineTo(w, h/2);
      ctx.strokeStyle = 'rgba(58,69,85,0.3)';
      ctx.lineWidth = 1;
      ctx.stroke();
    });
    return;
  }

  // Find the speaking agent's canvas and dot
  const speakingCanvas = document.getElementById('waveform-' + state.speakingAgent);
  const speakingDot = document.getElementById('dot-' + state.speakingAgent);
  if (speakingDot) speakingDot.classList.add('speaking');

  // Clear non-speaking canvases
  document.querySelectorAll('.agent-waveform canvas').forEach(c => {
    if (c === speakingCanvas) return;
    const ctx = c.getContext('2d');
    const w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);
    ctx.beginPath();
    ctx.moveTo(0, h/2);
    ctx.lineTo(w, h/2);
    ctx.strokeStyle = 'rgba(58,69,85,0.3)';
    ctx.lineWidth = 1;
    ctx.stroke();
  });

  if (!speakingCanvas) return;

  const agentEl = speakingCanvas.closest('.agent-info');
  const colorStr = agentEl ? agentEl.dataset.color : '#ff6b3d';

  function drawWaveform() {
    if (!state.speakingAgent) return;
    const canvas = speakingCanvas;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const bars = 20;
    const gap = w / bars;
    let freqData = null;

    if (analyserNode) {
      freqData = new Uint8Array(analyserNode.frequencyBinCount);
      analyserNode.getByteFrequencyData(freqData);
    }

    for (let i = 0; i < bars; i++) {
      const x = i * gap + gap / 2;
      let amp;
      if (freqData && freqData.length > 0) {
        // Map bar index to frequency bin
        const binIdx = Math.floor((i / bars) * freqData.length);
        amp = (freqData[binIdx] / 255) * (h / 2 - 1);
      } else {
        // Fallback: animated sine wave
        const t = performance.now() / 1000;
        amp = (Math.sin(t * 6 + i * 0.5) * 0.5 + 0.5) *
              (Math.sin(t * 3.7 + i * 0.3) * 0.3 + 0.7) *
              (h / 2 - 1);
      }
      amp = Math.max(1, amp);

      ctx.fillStyle = colorStr;
      ctx.globalAlpha = 0.5 + (amp / (h/2)) * 0.5;
      ctx.fillRect(x - 1, h/2 - amp, 2, amp * 2);
      ctx.globalAlpha = 1;
    }

    waveformAnimId = requestAnimationFrame(drawWaveform);
  }

  drawWaveform();
}

// ── TTS health poll ──
function pollTtsReady() {
  if (!state.config.tts_enabled || state.config.tts_provider === 'elevenlabs' || state.config.tts_provider === 'none') return;
  const check = () => {
    fetch('/api/tts-health').then(r => r.ok ? r.json() : null).then(d => {
      const badge = document.getElementById('tts-badge');
      if (!badge) return;
      if (d && d.status === 'ok') {
        badge.textContent = `tts:${state.config.tts_provider} ✓`;
        badge.className = 'tts-badge ready';
      } else {
        badge.textContent = `tts:${state.config.tts_provider} loading...`;
        setTimeout(check, 2000);
      }
    }).catch(() => setTimeout(check, 2000));
  };
  check();
}

// ── WebSocket ──
let _reconnectAttempts = 0;
const MAX_RECONNECT = 3;

function connect(topic, turns) {
  state.stopped = false;
  state.connectionLost = false;
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    _reconnectAttempts = 0;
    state.connectionLost = false;
    ws.send(JSON.stringify({topic, turns}));
    state.screen = 'running';
    render();
    pollTtsReady();
  };

  ws.onmessage = async (e) => {
    if (state.stopped) return;
    const data = JSON.parse(e.data);

    if (data.type === 'thinking') {
      // Track turn timing for ETA calculation
      if (state.turnStartTime && state.turn > 0) {
        // Previous turn just ended — record its duration
        const duration = Date.now() - state.turnStartTime;
        if (duration > 500) state.turnDurations.push(duration); // ignore sub-500ms noise
      }
      state.turnStartTime = Date.now();

      // Only update thinking if the display queue is empty (i.e. not mid-playback).
      // If we're still playing a previous message, the thinking indicator will
      // show after the queue drains naturally.
      if (!isProcessingQueue && displayQueue.length === 0) {
        state.thinking = data.agent;
        state.phase = data.phase;
        state.turn = data.turn;
        render(); scrollChat();
      }
    }

    if (data.type === 'message') {
      // Store audio data for replay
      if (data.audio) state.audioData[data.turn] = {b64: data.audio, format: data.audio_format || 'mp3'};

      // Ack IMMEDIATELY so the server starts generating the next turn
      // while the client is still playing the current one's audio.
      if (!state.stopped && ws.readyState === 1) {
        ws.send(JSON.stringify({type:'ack'}));
      }

      // Buffer the message — it will be displayed + played sequentially
      data._type = 'message';
      enqueueForDisplay(data);
    }

    if (data.type === 'chairman') {
      if (data.audio) state.audioData['chairman'] = {b64: data.audio, format: data.audio_format || 'mp3'};

      // Ack immediately
      if (!state.stopped && ws.readyState === 1) {
        ws.send(JSON.stringify({type:'ack'}));
      }

      data._type = 'chairman';
      enqueueForDisplay(data);
    }

    if (data.type === 'complete') {
      state.thinking = null;
      state.screen = 'complete';
      state.consensus = data.consensus || 100;
      if (data.proposal_records) state.proposalRecords = data.proposal_records;
      render();
      scrollChat();
    }

    if (data.type === 'error') {
      state.thinking = null;
      // Show as a dismissable toast instead of an inline message
      showErrorToast(data.message);
      render(); scrollChat();
    }
  };

  ws.onclose = (ev) => {
    // Fix 9: Detect unexpected disconnection vs normal completion
    if (state.screen === 'running' && !state.stopped) {
      // Unexpected disconnect — show connection lost banner
      state.connectionLost = true;
      state.thinking = null;
      renderConnectionBanner();
    } else if (state.screen === 'running') {
      state.screen = 'complete';
      render();
    }
  };

  ws.onerror = () => {
    // onerror always fires before onclose — let onclose handle the UI
  };

  state.ws = ws;
}

function renderConnectionBanner() {
  let container = document.getElementById('connection-banner-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'connection-banner-container';
    document.body.appendChild(container);
  }
  if (!state.connectionLost) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = `
    <div class="connection-banner">
      <span class="connection-banner-msg">⚠ Connection lost — the session cannot continue.</span>
      <button class="connection-banner-btn" onclick="dismissConnectionAndReset()">[ new session ]</button>
    </div>`;
}

function dismissConnectionAndReset() {
  state.connectionLost = false;
  state.screen = 'complete';
  renderConnectionBanner();
  render();
}

function scrollChat() {
  // Double requestAnimationFrame ensures layout is fully complete
  // before we measure scrollHeight (fixes chairman card scroll issue)
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const chat = document.getElementById('chat-scroll');
      if (chat) chat.scrollTop = chat.scrollHeight;
      const proposals = document.querySelector('.proposals-scroll');
      if (proposals) proposals.scrollTop = proposals.scrollHeight;
    });
  });
}

// ── Render ──
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function render() {
  const app = document.getElementById('app');
  if (state.screen === 'setup') return renderSetup(app);
  return renderMain(app);
}

function renderSetup(app) {
  app.className = '';
  app.innerHTML = `
    <div class="setup"><div class="setup-card">
      <div class="setup-logo">
        <div class="ascii-title"> ██████╗ ██╗██████╗ ██████╗ ███████╗██████╗
██╔════╝ ██║██╔══██╗██╔══██╗██╔════╝██╔══██╗
██║  ███╗██║██████╔╝██████╔╝█████╗  ██████╔╝
██║   ██║██║██╔══██╗██╔══██╗██╔══╝  ██╔══██╗
╚██████╔╝██║██████╔╝██████╔╝███████╗██║  ██║
 ╚═════╝ ╚═╝╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝</div>
        <div class="sub"><span>L I N K</span> &nbsp;REVISITED</div>
        <div class="council-badge">◈ discuss · debate · solve</div>
        <p>four ai minds discuss a problem, debate solutions, and reach consensus — live with voice</p>
      </div>
      <div class="field"><label>problem</label>
        <textarea id="topic" placeholder="what problem should they solve?">How to reduce meeting fatigue and restore deep work time in remote-first teams</textarea>
        <div class="topic-chips">
          ${PROBLEM_CHIPS.map(t => `<button class="topic-chip" onclick="document.getElementById('topic').value='${t}'">${t}</button>`).join('')}
        </div>
      </div>
      <div class="field"><label>rounds <span id="turns-display" style="color:var(--orange)">16</span></label>
        <input type="range" id="turns" min="8" max="32" value="16" step="4" oninput="document.getElementById('turns-display').textContent=this.value">
        <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text-dim);margin-top:4px;letter-spacing:0.5px"><span>8 quick</span><span>16 standard</span><span>32 deep</span></div>
      </div>
      <button class="launch-btn" onclick="startConversation()">[ launch agents ]</button>
      <p class="setup-note">backend must be running: python3 server.py</p>
    </div></div>`;
  fetch('/api/config').then(r => r.json()).then(cfg => { state.config = cfg; }).catch(() => {});
}

function startConversation() {
  const topic = document.getElementById('topic').value.trim();
  if (!topic) return;
  if (audioCtx.state === 'suspended') audioCtx.resume();
  const turns = parseInt(document.getElementById('turns').value) || 16;
  state.topic = topic;
  state.totalTurns = turns;
  state.messages = [];
  state.proposals = [];
  state.proposalRecords = [];
  state.chairmanVerdict = null;
  state.phase = 'problem';
  state.turn = 0;
  state.consensus = 0;
  state.audioData = {};
  state.lastProtocol = null;
  state.agentRoster = null;
  // P2: Reset ETA tracking
  state.turnStartTime = null;
  state.turnDurations = [];
  state.sessionStartTime = Date.now();
  state.errorToast = null;
  connect(topic, turns);
}

function stopConversation() {
  state.stopped = true;
  state.paused = false;
  state.speakingAgent = null;
  displayQueue = [];
  isProcessingQueue = false;
  if (waveformAnimId) { cancelAnimationFrame(waveformAnimId); waveformAnimId = null; }
  try { currentSource?.stop(); } catch(e) {}
  currentSource = null;
  analyserNode = null;
  // Send a stop signal so the server cancels pending LLM tasks
  if (state.ws && state.ws.readyState === 1) {
    try { state.ws.send(JSON.stringify({type: 'stop'})); } catch(e) {}
    // Give the server a moment to process, then close
    setTimeout(() => {
      try { state.ws?.close(); } catch(e) {}
      state.ws = null;
    }, 300);
  } else {
    state.ws = null;
  }
  state.thinking = null;
  state.screen = 'complete';
  render();
}

// Fix 11: Pause / resume
function togglePause() {
  state.paused = !state.paused;
  if (state.paused) {
    // Stop any currently playing audio
    try { currentSource?.stop(); } catch(e) {}
    state.speakingAgent = null;
    updateWaveforms();
  }
  render();
}

// Fix 8: Mobile panel toggle
function toggleMobilePanel() {
  state.mobilePanelOpen = !state.mobilePanelOpen;
  const side = document.querySelector('.side');
  const overlay = document.querySelector('.mobile-overlay');
  if (side) side.classList.toggle('open', state.mobilePanelOpen);
  if (overlay) overlay.classList.toggle('open', state.mobilePanelOpen);
}
function closeMobilePanel() {
  state.mobilePanelOpen = false;
  const side = document.querySelector('.side');
  const overlay = document.querySelector('.mobile-overlay');
  if (side) side.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
}

function resetApp() {
  dismissErrorToast(false);
  state.connectionLost = false;
  renderConnectionBanner();
  state = {
    screen:'setup', ws:null, config:state.config,
    messages:[], proposals:[], proposalRecords:[], chairmanVerdict:null,
    phase:'problem', turn:0, totalTurns:16,
    consensus:0, thinking:null, lastProtocol:null, showJson:false,
    audioData:{}, stopped:false, topic:'', agentRoster:null,
    speakingAgent:null,
    turnStartTime:null, turnDurations:[], sessionStartTime:null,
    errorToast:null,
    mobilePanelOpen:false, connectionLost:false, audioFailed:{}, paused:false,
  };
  displayQueue = [];
  isProcessingQueue = false;
  render();
}

// Fix 12: Export as JSON or Markdown
function exportTranscript() {
  const data = {
    topic: state.topic, turns: state.messages.length,
    proposals: state.proposalRecords,
    consensus: state.consensus,
    chairman_verdict: state.chairmanVerdict ? state.chairmanVerdict.text : null,
    messages: state.messages.filter(m => m.type !== 'error').map(m => ({
      agent: m.agent_name, role: m.agent_role, phase: m.phase,
      turn: m.turn, text: m.text, consensus: m.consensus,
    })),
    exported_at: new Date().toISOString(),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `gibberlink-revisited-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportMarkdown() {
  const msgs = state.messages.filter(m => m.type !== 'error');
  let md = `# GibberLink Revisited — Council Transcript\n\n`;
  md += `**Problem:** ${state.topic}\n\n`;
  md += `**Rounds:** ${msgs.length} · **Consensus:** ${state.consensus}%\n\n`;
  md += `---\n\n`;

  let lastPhase = '';
  for (const m of msgs) {
    if (m.phase !== lastPhase) {
      const label = {problem:'Problem Definition',debate:'Open Debate',converge:'Convergence',solution:'Solution'}[m.phase] || m.phase;
      md += `## ${label}\n\n`;
      lastPhase = m.phase;
    }
    md += `**${m.agent_name || 'Agent'}** _(${m.agent_role || ''})_: ${m.text}\n\n`;
  }

  if (state.proposalRecords.length > 0) {
    md += `---\n\n## Proposals\n\n`;
    for (const p of state.proposalRecords) {
      const vc = {};
      if (p.votes) {
        for (const v of Object.values(p.votes)) vc[v] = (vc[v]||0) + 1;
      }
      md += `- **${p.author}** (round ${(p.turn||0)+1}): ${p.text}`;
      const parts = [];
      if (vc.agree) parts.push(`${vc.agree} agree`);
      if (vc.amend) parts.push(`${vc.amend} amend`);
      if (vc.disagree) parts.push(`${vc.disagree} disagree`);
      if (parts.length) md += ` — _${parts.join(', ')}_`;
      md += `\n`;
    }
    md += `\n`;
  }

  if (state.chairmanVerdict) {
    md += `---\n\n## Chairman's Verdict\n\n${state.chairmanVerdict.text}\n`;
  }

  md += `\n---\n_Exported ${new Date().toISOString()}_\n`;

  const blob = new Blob([md], {type:'text/markdown'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `gibberlink-revisited-${Date.now()}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function toggleJson() { state.showJson = !state.showJson; render(); scrollChat(); }

async function replayAudio(turn) {
  const ad = state.audioData[turn];
  if (!ad) return;
  // Find which agent spoke on this turn
  const msg = state.messages.find(m => m.turn === turn);
  const agentId = msg ? msg.agent : null;
  try {
    if (agentId) { state.speakingAgent = agentId; updateWaveforms(); }
    await playAudioB64(ad.b64, ad.format);
  } catch(e) { console.warn(e); }
  state.speakingAgent = null;
  updateWaveforms();
}

function syntaxHighlight(json) {
  return esc(json)
    .replace(/"([^"]+)"(?=\s*:)/g, '<span class="jk">"$1"</span>')
    .replace(/: "([^"]+)"/g, ': <span class="js">"$1"</span>')
    .replace(/: (\d+\.?\d*)/g, ': <span class="jv">$1</span>');
}

function renderPhaseBar() {
  const ci = PHASES.indexOf(state.phase);
  return PHASES.map((p, i) => {
    const active = i === ci, done = i < ci, color = PHASE_COLORS[p];
    return `<div class="phase-step">
      <div class="phase-dot ${active?'active':''} ${done?'done':''}"
        style="${active||done ? `background:${color};${active?`box-shadow:0 0 8px ${color},0 0 16px ${color}`:''}` : ''}">
      </div>
      <span class="phase-label ${active?'active':''}" style="${active?`color:${color}`:''}">
        ${PHASE_ICONS[p]} ${PHASE_LABELS[p]}
      </span>
    </div>${i < PHASES.length-1 ? '<span class="phase-sep">│</span>' : ''}`;
  }).join('');
}

function renderMsg(m, idx) {
  if (m.type === 'error') {
    return `<div class="msg" style="align-self:center;border-color:rgba(248,113,113,0.3);border-left:2px solid var(--red)"><div style="color:var(--red);font-size:11px">ERR: ${esc(m.text)}</div></div>`;
  }
  const color = AGENT_RAW_COLORS[m.agent_color] || '#ff6b3d';
  const cssColor = AGENT_CSS_COLORS[m.agent_color] || 'var(--orange)';
  const agentIdx = state.agentRoster ? state.agentRoster.findIndex(a => a.id === m.agent) : 0;
  const isLeft = agentIdx % 2 === 0;
  const borderStyle = isLeft ? `border-left:2px solid ${color}` : `border-right:2px solid ${color}`;
  const ad = state.audioData[m.turn];
  const phase = m.phase || 'problem';
  const hasProposals = m.new_proposals && m.new_proposals.length > 0;

  return `<div class="msg" style="max-width:85%;padding:10px 14px;background:var(--bg2);border:1px solid var(--border);position:relative;animation:fadeIn 0.3s ease;font-size:12px;line-height:1.7;${isLeft?'align-self:flex-start':'align-self:flex-end'};${borderStyle}">
    <div class="msg-header">
      <span class="msg-agent" style="color:${color}">◉ ${m.agent_name || 'agent'}</span>
      ${m.agent_model ? `<span style="font-size:9px;color:var(--text-dim);opacity:0.6">${esc(m.agent_model)}</span>` : ''}
      <span class="msg-phase ${phase}">${PHASE_LABELS[phase]||phase}</span>
    </div>
    <div class="msg-text">${esc(m.text)}</div>
    ${hasProposals ? m.new_proposals.map(p => `<div class="proposal-inline">${esc(p)}</div>`).join('') : ''}
    ${ad ? `<button class="msg-audio-btn" onclick="replayAudio(${m.turn})">[ replay ]</button>` : ''}
    ${state.audioFailed[m.turn] ? '<div class="msg-audio-fail">⚠ audio unavailable</div>' : ''}
  </div>`;
}

function renderThinking() {
  if (!state.thinking) return '';
  if (state.thinking === 'chairman') {
    return `<div class="thinking"><span class="thinking-dots"><span>▪</span><span>▪</span><span>▪</span></span> nexus is preparing the final verdict</div>`;
  }
  const roster = state.agentRoster;
  const agent = roster ? roster.find(a => a.id === state.thinking) : null;
  const name = agent ? agent.name.toLowerCase() : 'agent';
  return `<div class="thinking"><span class="thinking-dots"><span>▪</span><span>▪</span><span>▪</span></span> ${name} is deliberating</div>`;
}

function renderChairmanVerdict() {
  const v = state.chairmanVerdict;
  if (!v) return '';
  const hasAudio = state.audioData['chairman'];
  const scoreboard = v.scoreboard || [];
  const rankColors = ['gold', 'silver', 'bronze'];

  const scoreboardHtml = scoreboard.length > 0 ? `
    <div class="scoreboard">
      <div class="scoreboard-title">proposal scoreboard</div>
      ${scoreboard.map((p, i) => {
        const rankClass = i < 3 ? rankColors[i] : '';
        const vc = p.vote_counts || {agree:0, disagree:0, amend:0};
        const vetoed = p.chairman_vetoed;
        const reasons = p.reasons || {};
        const reasonLines = Object.entries(reasons).filter(([,r]) => r).map(([aid, r]) => {
          const agent = (state.agentRoster || []).find(a => a.id === aid);
          const name = agent ? agent.name : aid;
          return `${name.toLowerCase()}: ${esc(r)}`;
        });
        return `<div class="scoreboard-item" ${vetoed ? 'style="opacity:0.6"' : ''}>
          <div class="scoreboard-rank ${rankClass}">#${i+1}</div>
          <div class="scoreboard-body">
            <div class="scoreboard-proposal-text">${esc(p.text)}</div>
            <div class="scoreboard-meta">
              <span class="scoreboard-author">by ${esc(p.author)} · t${(p.turn||0)+1}</span>
              <div class="scoreboard-votes">
                ${vc.agree ? `<span class="scoreboard-vote-pill agree">${vc.agree} agree</span>` : ''}
                ${vc.amend ? `<span class="scoreboard-vote-pill amend">${vc.amend} amend</span>` : ''}
                ${vc.disagree ? `<span class="scoreboard-vote-pill disagree">${vc.disagree} disagree</span>` : ''}
              </div>
              <span class="scoreboard-score">${p.score} pts</span>
            </div>
            ${vetoed ? '<div class="veto-indicator">◈ CHAIRMAN VETO — score halved</div>' : ''}
            ${reasonLines.length > 0 ? `<div class="vote-reason" style="margin-top:3px">${reasonLines.join(' · ')}</div>` : ''}
          </div>
        </div>`;
      }).join('')}
    </div>
  ` : '';

  return `<div class="chairman-card">
    <div class="chairman-header">
      <div class="chairman-dot"></div>
      <span class="chairman-name">◈ ${esc(v.agent_name || 'Nexus')}</span>
      ${v.agent_model ? `<span style="font-size:9px;color:var(--text-dim);opacity:0.6">${esc(v.agent_model)}</span>` : ''}
      <span class="chairman-label">FINAL VERDICT</span>
    </div>
    <div class="chairman-text">${esc(v.text)}</div>
    ${scoreboardHtml}
    ${hasAudio ? `<button class="chairman-audio-btn" onclick="replayChairmanAudio()">[ replay verdict ]</button>` : ''}
  </div>`;
}

async function replayChairmanAudio() {
  const ad = state.audioData['chairman'];
  if (!ad) return;
  try {
    state.speakingAgent = 'chairman'; updateWaveforms();
    await playAudioB64(ad.b64, ad.format);
  } catch(e) { console.warn(e); }
  state.speakingAgent = null; updateWaveforms();
}

function renderMain(app) {
  app.className = 'app';
  const cfg = state.config;
  const proposalCount = state.proposalRecords.length;
  const roster = state.agentRoster || cfg.default_agents || [];
  const ttsLabel = cfg.tts_provider && cfg.tts_provider !== 'none' ? `tts:${cfg.tts_provider}...` : '';

  app.innerHTML = `
    <div class="top-bar">
      <div class="logo">
        <span class="logo-bracket">[</span>
        <span class="logo-text">GIBBER<span>LINK</span></span>
        <span class="logo-bracket">]</span>
        <span style="font-size:9px;color:var(--green);letter-spacing:1px;margin-left:4px">REVISITED</span>
      </div>
      <div class="phase-bar">${renderPhaseBar()}</div>
      <div class="controls">
        ${ttsLabel ? `<span class="tts-badge" id="tts-badge">${ttsLabel}</span>` : ''}
        ${state.screen === 'running' ? `
          <div class="progress-info">
            <span class="turn-badge">${String(state.turn).padStart(2,'0')}/${String(state.totalTurns).padStart(2,'0')}</span>
            <div class="progress-track"><div class="progress-fill" style="width:${Math.round((state.turn / state.totalTurns) * 100)}%"></div></div>
            ${getEtaString() ? `<span class="progress-eta">${getEtaString()}</span>` : ''}
          </div>
        ` : `<span class="turn-badge">${String(state.turn).padStart(2,'0')}/${String(state.totalTurns).padStart(2,'0')}</span>`}
        ${state.screen === 'complete'
          ? `<button class="btn" onclick="exportTranscript()">[ json ]</button>
             <button class="btn" onclick="exportMarkdown()">[ markdown ]</button>
             <button class="btn" onclick="resetApp()">[ new ]</button>`
          : `${state.screen === 'running' ? `<button class="btn btn-pause" onclick="togglePause()">${state.paused ? '[ resume ]' : '[ pause ]'}</button>` : ''}
             <button class="btn btn-danger" onclick="stopConversation()">[ stop ]</button>`}
        <button class="mobile-panel-toggle" onclick="toggleMobilePanel()">☰</button>
      </div>
    </div>
    <div class="main">
      <div class="chat-col">
        <div class="chat-scroll" id="chat-scroll">
          ${state.messages.map((m,i) => renderMsg(m,i)).join('')}
          ${state.chairmanVerdict ? renderChairmanVerdict() : ''}
          ${state.thinking ? renderThinking() : ''}
          ${state.screen === 'complete' ? `
            <div class="final-solution">
              <div class="final-solution-header">session complete — consensus reached</div>
              <div class="final-solution-text">
                The agents deliberated over ${state.messages.filter(m=>m.type!=='error').length} rounds on: "${esc(state.topic)}".
                ${proposalCount > 0 ? `${proposalCount} proposal(s) were surfaced and refined.` : ''}
                Final consensus: ${state.consensus}%.
              </div>
            </div>
            <div style="text-align:center;padding:12px;color:var(--text-dim);font-size:11px;letter-spacing:1px">
              // session complete — ${state.messages.filter(m=>m.type!=='error').length} rounds — ${proposalCount} proposals — ${state.consensus}% consensus
            </div>
          ` : ''}
        </div>
        <div class="consensus-bar">
          <span class="consensus-label">// consensus</span>
          <div class="consensus-track">
            <div class="consensus-fill" style="width:${state.consensus}%"></div>
          </div>
          <span class="consensus-pct">${state.consensus}%</span>
        </div>
      </div>
      <div class="mobile-overlay${state.mobilePanelOpen ? ' open' : ''}" onclick="closeMobilePanel()"></div>
      <div class="side${state.mobilePanelOpen ? ' open' : ''}">
        <div class="side-section">
          <div class="side-title">agents</div>
          ${roster.map((a) => {
            const color = AGENT_RAW_COLORS[a.color] || '#ff6b3d';
            const isSpeaking = state.speakingAgent === a.id;
            return `<div class="agent-info" data-color="${color}">
              <div class="agent-dot${isSpeaking ? ' speaking' : ''}" id="dot-${a.id}" style="background:${color};box-shadow:0 0 ${isSpeaking ? '12' : '6'}px ${color}"></div>
              <div style="flex:1;min-width:0">
                <span class="agent-label">${esc((a.name||'').toLowerCase())}</span>
                <span class="agent-role">${a.role || a.mood || ''}</span>
                ${a.model ? `<div style="font-size:8px;color:var(--text-dim);opacity:0.5;margin-top:-1px">${esc(a.model)}</div>` : ''}
              </div>
              <div class="agent-waveform"><canvas id="waveform-${a.id}" width="128" height="36"></canvas></div>
            </div>`;
          }).join('')}
          <div class="stats-row">
            <div class="stat-item"><div class="stat-label">rounds</div><div class="stat-value">${state.messages.filter(m=>m.type!=='error').length}</div></div>
            <div class="stat-item"><div class="stat-label">proposals</div><div class="stat-value">${proposalCount}</div></div>
            <div class="stat-item"><div class="stat-label">consensus</div><div class="stat-value" style="font-size:12px;color:var(--green)">${state.consensus}%</div></div>
          </div>
        </div>
        <div class="side-section"><div class="side-title">problem</div><div class="topic-text">${esc(state.topic||'')}</div></div>
        <div class="side-section" style="flex-shrink:0">
          <div class="side-title">proposals [${proposalCount}]</div>
        </div>
        <div class="proposals-scroll">
          ${state.proposalRecords.length === 0
            ? '<div class="proposal-empty">awaiting convergence phase...</div>'
            : state.proposalRecords.map((p, i) => {
                const reasons = p.reasons || {};
                const authorId = p.author_id || '';
                const voteHtml = (() => {
                  const badges = [];
                  // Author badge
                  if (authorId) {
                    const authorAgent = (state.agentRoster || []).find(a => a.id === authorId);
                    const authorName = authorAgent ? authorAgent.name : '';
                    if (authorName) badges.push(`<span class="vote-badge author">${authorName.toLowerCase()}: author</span>`);
                  }
                  // Voter badges
                  if (p.votes) {
                    Object.entries(p.votes).forEach(([aid, vote]) => {
                      const agent = (state.agentRoster || []).find(a => a.id === aid);
                      const name = agent ? agent.name : aid;
                      const isChairman = aid === 'chairman';
                      const cls = isChairman && vote === 'disagree' ? 'veto' : vote;
                      const label = isChairman && vote === 'disagree' ? 'VETO' : vote;
                      badges.push(`<span class="vote-badge ${cls}">${name.toLowerCase()}: ${label}</span>`);
                    });
                  }
                  return badges.join('');
                })();
                // Collect non-empty reasons
                const reasonLines = Object.entries(reasons).filter(([,r]) => r).map(([aid, r]) => {
                  const agent = (state.agentRoster || []).find(a => a.id === aid);
                  const name = agent ? agent.name : aid;
                  return `${name.toLowerCase()}: ${esc(r)}`;
                });
                return `<div class="proposal-entry">
                  <div class="proposal-author">◉ ${esc(p.author || '')} — t${(p.turn||0) + 1}</div>
                  <div class="proposal-text">${esc(p.text)}</div>
                  ${voteHtml ? `<div class="vote-row">${voteHtml}</div>` : ''}
                  ${reasonLines.length > 0 ? `<div class="vote-reason">${reasonLines.join(' · ')}</div>` : ''}
                </div>`;
              }).join('')}
        </div>
        <div class="json-toggle">
          <button class="btn" style="width:100%;font-size:10px;letter-spacing:1px" onclick="toggleJson()">${state.showJson?'[ hide json ]':'[ show json ]'}</button>
          ${state.showJson && state.lastProtocol
            ? `<pre class="json-pre">${syntaxHighlight(JSON.stringify(state.lastProtocol,null,2))}</pre>`
            : ''}
        </div>
      </div>
    </div>`;

  if (cfg.tts_enabled && cfg.tts_provider !== 'elevenlabs' && cfg.tts_provider !== 'none') {
    pollTtsReady();
  } else if (cfg.tts_provider === 'elevenlabs') {
    const badge = document.getElementById('tts-badge');
    if (badge) { badge.textContent = 'tts:elevenlabs ✓'; badge.className = 'tts-badge ready'; }
  }

  // Re-init waveform canvases after innerHTML wipe
  if (state.speakingAgent) {
    requestAnimationFrame(() => updateWaveforms());
  } else {
    // Draw flat lines on all canvases
    requestAnimationFrame(() => {
      document.querySelectorAll('.agent-waveform canvas').forEach(c => {
        const ctx = c.getContext('2d');
        const w = c.width, h = c.height;
        ctx.clearRect(0, 0, w, h);
        ctx.beginPath();
        ctx.moveTo(0, h/2);
        ctx.lineTo(w, h/2);
        ctx.strokeStyle = 'rgba(58,69,85,0.3)';
        ctx.lineWidth = 1;
        ctx.stroke();
      });
    });
  }
}

render();
