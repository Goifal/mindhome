/* ============================================================
   Jarvis Dashboard v2 — JavaScript
   11 Settings Tabs: Allgemein, Personen, Persoenlichkeit, Gedaechtnis,
   Stimmung, Raeume, Stimme, Routinen, Sicherheit, KI-Autonomie, Easter Eggs
   ============================================================ */

let TOKEN = '';
let S = {};  // Settings cache
let ALL_ENTITIES = [];
const API = '';

// ---- Mobile Sidebar Toggle mit Backdrop ----
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const bd = document.getElementById('sidebarBackdrop');
  const isOpen = sb.classList.toggle('open');
  if (bd) bd.classList.toggle('show', isOpen);
}
function closeSidebar() {
  const sb = document.getElementById('sidebar');
  const bd = document.getElementById('sidebarBackdrop');
  sb.classList.remove('open');
  if (bd) bd.classList.remove('show');
}

// ---- Session-Timeout: Auto-Logout bei Inaktivitaet (30 Min) ----
const SESSION_TIMEOUT_MS = 30 * 60 * 1000;  // 30 Minuten
let _sessionTimer = null;
function resetSessionTimer() {
  if (_sessionTimer) clearTimeout(_sessionTimer);
  if (!TOKEN) return;
  _sessionTimer = setTimeout(() => {
    doLogout();
    alert('Sitzung abgelaufen (30 Min Inaktivitaet). Bitte erneut anmelden.');
  }, SESSION_TIMEOUT_MS);
}
['click','keydown','scroll','mousemove','touchstart'].forEach(evt =>
  document.addEventListener(evt, resetSessionTimer, {passive: true})
);

// ---- Screens ausblenden ----
function hideAllScreens() {
  ['setupScreen','recoveryScreen','loginScreen','resetScreen','newRecoveryScreen','bootScreen'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  document.getElementById('app').classList.remove('active');
}

// ---- Jarvis Boot Sequence ----
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function typeText(el, text, speed) {
  el.textContent = '';
  for (const ch of text) { el.textContent += ch; await sleep(speed); }
}

function playBootSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    // Ton 1: Tiefer Sweep (0-1.5s)
    const o1 = ctx.createOscillator(), g1 = ctx.createGain();
    o1.type = 'sine';
    o1.frequency.setValueAtTime(80, ctx.currentTime);
    o1.frequency.exponentialRampToValueAtTime(300, ctx.currentTime + 1.5);
    g1.gain.setValueAtTime(0, ctx.currentTime);
    g1.gain.linearRampToValueAtTime(0.15, ctx.currentTime + 0.3);
    g1.gain.linearRampToValueAtTime(0, ctx.currentTime + 1.5);
    o1.connect(g1).connect(ctx.destination);
    o1.start(); o1.stop(ctx.currentTime + 1.5);
    // Ton 2: Hoher Ping (1.5s)
    const o2 = ctx.createOscillator(), g2 = ctx.createGain();
    o2.type = 'sine';
    o2.frequency.setValueAtTime(880, ctx.currentTime + 1.5);
    g2.gain.setValueAtTime(0, ctx.currentTime + 1.5);
    g2.gain.linearRampToValueAtTime(0.1, ctx.currentTime + 1.55);
    g2.gain.linearRampToValueAtTime(0, ctx.currentTime + 2.5);
    o2.connect(g2).connect(ctx.destination);
    o2.start(ctx.currentTime + 1.5); o2.stop(ctx.currentTime + 2.5);
    // Ton 3: Confirmation-Chime (3s)
    const o3 = ctx.createOscillator(), g3 = ctx.createGain();
    o3.type = 'triangle';
    o3.frequency.setValueAtTime(660, ctx.currentTime + 3);
    o3.frequency.setValueAtTime(880, ctx.currentTime + 3.15);
    g3.gain.setValueAtTime(0, ctx.currentTime + 3);
    g3.gain.linearRampToValueAtTime(0.12, ctx.currentTime + 3.05);
    g3.gain.linearRampToValueAtTime(0, ctx.currentTime + 3.8);
    o3.connect(g3).connect(ctx.destination);
    o3.start(ctx.currentTime + 3); o3.stop(ctx.currentTime + 3.8);
  } catch(e) { /* Audio nicht verfuegbar */ }
}

async function playBootSequence() {
  const screen = document.getElementById('bootScreen');
  const textEl = document.getElementById('bootText');
  const sysEl = document.getElementById('bootSystems');
  screen.style.display = 'flex';
  playBootSound();

  const systems = ['LLM', 'HA', 'Redis', 'Memory', 'TTS'];
  sysEl.innerHTML = systems.map((s, i) =>
    `<div class="boot-sys" style="animation-delay:${0.8 + i * 0.3}s" id="bootSys${i}"><span class="sys-dot"></span>${s}</div>`
  ).join('');

  await typeText(textEl, 'INITIALIZING...', 60);
  await sleep(600);
  for (let i = 0; i < systems.length; i++) {
    await sleep(300);
    const el = document.getElementById('bootSys' + i);
    if (el) el.classList.add('online');
  }
  await sleep(300);
  textEl.textContent = '';
  await typeText(textEl, 'ALL SYSTEMS ONLINE', 40);
  await sleep(800);

  screen.classList.add('fade-out');
  await sleep(500);
  screen.style.display = 'none';
  screen.classList.remove('fade-out');
}

// ---- Setup-Status pruefen und richtigen Screen zeigen ----
async function checkSetupAndShow() {
  try {
    const r = await fetch(`${API}/api/ui/setup-status`);
    const d = await r.json();
    hideAllScreens();
    if (!d.setup_complete) {
      // Erster Aufruf: Setup-Screen
      document.getElementById('setupScreen').style.display = 'flex';
      document.getElementById('setupPin').focus();
    } else {
      // Setup fertig: Token pruefen oder Login zeigen
      const t = sessionStorage.getItem('jt');
      if (t) {
        // Pruefen ob Token aelter als 4h (Backend-Timeout)
        const ts = parseInt(sessionStorage.getItem('jt_ts') || '0');
        if (Date.now() - ts > 4 * 60 * 60 * 1000) {
          sessionStorage.removeItem('jt');
          sessionStorage.removeItem('jt_ts');
        } else {
          TOKEN = t;
          try {
            const sr = await fetch(`${API}/api/ui/stats`, {headers: {'Authorization': `Bearer ${TOKEN}`}});
            if (sr.ok) { resetSessionTimer(); await showApp(); return; }
          } catch(e) {}
        }
      }
      showLoginScreen();
    }
  } catch(e) {
    // Fallback: Login zeigen
    showLoginScreen();
  }
}

// ---- Setup: PIN setzen ----
async function doSetup() {
  const pin = document.getElementById('setupPin').value;
  const confirm = document.getElementById('setupPinConfirm').value;
  const err = document.getElementById('setupError');
  err.textContent = '';

  if (pin.length < 4) { err.textContent = 'PIN muss mindestens 4 Zeichen haben'; return; }
  if (pin !== confirm) { err.textContent = 'PINs stimmen nicht ueberein'; return; }

  try {
    const r = await fetch(`${API}/api/ui/setup`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pin, pin_confirm: confirm})
    });
    const d = await r.json();
    if (!r.ok) { err.textContent = d.detail || 'Fehler'; return; }

    // Recovery-Key anzeigen
    hideAllScreens();
    document.getElementById('recoveryKeyDisplay').textContent = d.recovery_key;
    document.getElementById('recoveryScreen').style.display = 'flex';
  } catch(e) { err.textContent = 'Verbindung fehlgeschlagen'; }
}

function recoveryAcknowledged() {
  hideAllScreens();
  showLoginScreen();
}

// ---- Login ----
function showLoginScreen() {
  hideAllScreens();
  document.getElementById('loginScreen').style.display = 'flex';
  document.getElementById('pinInput').value = '';
  document.getElementById('loginError').textContent = '';
  document.getElementById('pinInput').focus();
}

async function doLogin() {
  const pin = document.getElementById('pinInput').value;
  const err = document.getElementById('loginError');
  err.textContent = '';

  if (!pin) { err.textContent = 'PIN eingeben'; return; }

  try {
    const r = await fetch(`${API}/api/ui/auth`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pin})
    });
    if (!r.ok) { err.textContent = 'Falscher PIN'; return; }
    const d = await r.json();
    TOKEN = d.token;
    sessionStorage.setItem('jt', TOKEN);
    sessionStorage.setItem('jt_ts', Date.now().toString());
    resetSessionTimer();
    await showApp();
  } catch(e) { err.textContent = 'Verbindung fehlgeschlagen'; }
}

function doLogout() {
  TOKEN = '';
  sessionStorage.removeItem('jt');
  sessionStorage.removeItem('jt_ts');
  sessionStorage.removeItem('jb');
  if (_sessionTimer) { clearTimeout(_sessionTimer); _sessionTimer = null; }
  stopLiveRefresh();
  hideAllScreens();
  showLoginScreen();
}

async function showApp() {
  hideAllScreens();
  // Boot-Animation nur beim ersten Aufruf pro Session
  if (!sessionStorage.getItem('jb')) {
    sessionStorage.setItem('jb', '1');
    await playBootSequence();
  }
  document.getElementById('app').classList.add('active');
  loadDashboard();
  startLiveRefresh();
  loadHealthTrends(_trendHours);
  refreshErrBadge();
}

// ---- PIN Reset ----
function showResetScreen() {
  hideAllScreens();
  document.getElementById('resetScreen').style.display = 'flex';
  document.getElementById('resetRecoveryKey').value = '';
  document.getElementById('resetNewPin').value = '';
  document.getElementById('resetNewPinConfirm').value = '';
  document.getElementById('resetError').textContent = '';
  document.getElementById('resetRecoveryKey').focus();
}

async function doResetPin() {
  const recovery_key = document.getElementById('resetRecoveryKey').value.trim().toUpperCase();
  const new_pin = document.getElementById('resetNewPin').value;
  const new_pin_confirm = document.getElementById('resetNewPinConfirm').value;
  const err = document.getElementById('resetError');
  err.textContent = '';

  if (!recovery_key) { err.textContent = 'Recovery-Key eingeben'; return; }
  if (new_pin.length < 4) { err.textContent = 'PIN muss mindestens 4 Zeichen haben'; return; }
  if (new_pin !== new_pin_confirm) { err.textContent = 'PINs stimmen nicht ueberein'; return; }

  try {
    const r = await fetch(`${API}/api/ui/reset-pin`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({recovery_key, new_pin, new_pin_confirm})
    });
    const d = await r.json();
    if (!r.ok) { err.textContent = d.detail || 'Falscher Recovery-Key'; return; }

    // Neuen Recovery-Key anzeigen
    hideAllScreens();
    document.getElementById('newRecoveryKeyDisplay').textContent = d.recovery_key;
    document.getElementById('newRecoveryScreen').style.display = 'flex';
  } catch(e) { err.textContent = 'Verbindung fehlgeschlagen'; }
}

function newRecoveryAcknowledged() {
  hideAllScreens();
  showLoginScreen();
}

// ---- Init: Setup-Status pruefen ----
checkSetupAndShow();

// ---- API ----
async function api(path, method='GET', body=null) {
  const url = `${API}${path}`;
  const opts = {method, headers:{'Content-Type':'application/json', 'Authorization': `Bearer ${TOKEN}`}};
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  if (r.status === 401) { doLogout(); throw new Error('Auth'); }
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const d = await r.json(); detail = d.detail || detail; } catch(e) {}
    throw new Error(detail);
  }
  try { return await r.json(); }
  catch(e) { throw new Error('Ungueltige Server-Antwort'); }
}

// ---- Navigation (Sidebar Groups + Sub-Items) ----
function toggleNavGroup(hdr) {
  const items = hdr.nextElementSibling;
  const isOpen = hdr.classList.toggle('open');
  items.classList.toggle('open', isOpen);
}

// Sidebar nav-item click handler (delegiert)
document.getElementById('sidebarNav').addEventListener('click', e => {
  const item = e.target.closest('.nav-item');
  if (!item) return;
  const pg = item.dataset.page;
  const tab = item.dataset.tab;
  // Aktive Markierung setzen
  document.querySelectorAll('#sidebarNav .nav-item').forEach(n => n.classList.remove('active'));
  item.classList.add('active');
  // Seite wechseln
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(`page-${pg}`).classList.add('active');
  const titles = {dashboard:'Dashboard',settings:'Einstellungen',presence:'Anwesenheit',entities:'Entities',knowledge:'Wissen',logs:'Logs',errors:'Fehler'};
  document.getElementById('pageTitle').textContent = titles[pg] || pg;
  stopLiveRefresh();
  stopPresenceRefresh();
  if (pg === 'dashboard') { loadDashboard(); startLiveRefresh(); loadHealthTrends(_trendHours); }
  else if (pg === 'presence') { loadPresence(); startPresenceRefresh(); }
  else if (pg === 'settings') {
    // Tab wechseln und Settings laden
    if (tab && tab !== currentTab) {
      mergeCurrentTabIntoS();
      currentTab = tab;
    }
    loadSettings();
    // Settings-Titel aktualisieren
    const tabTitles = {
      'tab-general':'Allgemein','tab-persons':'Personen','tab-personality':'Persoenlichkeit',
      'tab-memory':'Gedaechtnis','tab-mood':'Stimmung','tab-rooms':'Raeume & Speaker',
      'tab-devices':'Geraete','tab-covers':'Rolllaeden','tab-routines':'Routinen',
      'tab-proactive':'Proaktiv & Vorausdenken','tab-cooking':'Koch-Assistent',
      'tab-autonomie':'Autonomie & Selbstoptimierung','tab-followme':'Follow-Me',
      'tab-voice':'Stimme & TTS',
      'tab-eastereggs':'Easter Eggs','tab-security':'Sicherheit & Notfall',
      'tab-house-status':'Haus-Status & Health','tab-system':'System & Updates'
    };
    const el = document.getElementById('settingsTitle');
    if (el) el.textContent = tabTitles[currentTab] || 'Einstellungen';
    const sub = document.getElementById('settingsSub');
    if (sub) sub.textContent = 'Einstellungen — ' + (tabTitles[currentTab] || '');
  }
  else if (pg === 'entities') loadEntities();
  else if (pg === 'knowledge') { loadKnowledge(); setTimeout(initKbDropzone, 50); }
  else if (pg === 'logs') { if(currentLogTab==='audit') loadAudit(); else loadLogs(); }
  else if (pg === 'errors') loadErrors();
  closeSidebar();
});

// ---- Toast ----
let _toastTimer = null;
function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast toast-${type} show`;
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
}

// ---- Helpers ----
function esc(s) { if (s == null) return ''; const d=document.createElement('div'); d.textContent=String(s); return d.innerHTML.replace(/'/g,'&#39;'); }
function fmtBytes(b) { if(b==null||isNaN(b)) return '0 B'; if(b<1024) return b+' B'; if(b<1048576) return (b/1024).toFixed(1)+' KB'; return (b/1048576).toFixed(1)+' MB'; }
function getPath(obj,path) { return path.split('.').reduce((o,k)=>o?.[k], obj); }
function setPath(obj,path,val) {
  const parts=path.split('.'); let cur=obj;
  for(let i=0;i<parts.length-1;i++) { if(cur[parts[i]]==null||typeof cur[parts[i]]!=='object') cur[parts[i]]={}; cur=cur[parts[i]]; }
  cur[parts[parts.length-1]]=val;
}
function deepMerge(target, source) {
  for (const key of Object.keys(source)) {
    if (source[key]&&typeof source[key]==='object'&&!Array.isArray(source[key])
        &&target[key]&&typeof target[key]==='object'&&!Array.isArray(target[key])) {
      deepMerge(target[key], source[key]);
    } else {
      target[key] = source[key];
    }
  }
  return target;
}

// ---- Dashboard ----
async function loadDashboard() {
  try {
    const d = await api('/api/ui/stats');
    const mem=d.memory||{}, sem=mem.semantic||{}, kb=d.knowledge_base||{}, auto=d.autonomy||{};
    document.getElementById('dashStats').innerHTML = `
      <div class="stat-card"><div class="stat-label">Fakten</div><div class="stat-value">${sem.total_facts||0}</div>
        <div class="stat-sub">${(sem.persons||[]).length} Personen</div></div>
      <div class="stat-card"><div class="stat-label">Wissensbasis</div><div class="stat-value">${kb.total_chunks||0}</div>
        <div class="stat-sub">${(kb.sources||[]).length} Quellen</div></div>
      <div class="stat-card"><div class="stat-label">Episoden</div><div class="stat-value">${mem.episodic_count||0}</div>
        <div class="stat-sub">Langzeitgedaechtnis</div></div>
      <div class="stat-card"><div class="stat-label">Autonomie</div><div class="stat-value" style="color:var(--accent);">${auto.level||'?'}/5</div>
        <div class="stat-sub">${esc(auto.name||'')}</div></div>`;
    const comps=d.components||{};
    let ch='';
    for(const [n,s] of Object.entries(comps)) {
      const ok=s==='connected'||String(s).includes('active');
      ch+=`<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">
        <span style="font-size:12px;">${esc(n)}</span>
        <span style="font-size:11px;color:${ok?'var(--success)':'var(--danger)'};font-family:var(--mono);">${esc(s)}</span></div>`;
    }
    document.getElementById('compList').innerHTML=ch;
    const mood=d.mood||{};
    document.getElementById('moodInfo').innerHTML=`
      <div style="padding:8px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;">
        <span style="font-size:12px;">Stimmung</span><span style="font-size:12px;color:var(--accent);font-weight:600;">${esc(mood.mood||'neutral')}</span></div>
      <div style="padding:8px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;">
        <span style="font-size:12px;">Stress</span><span style="font-size:12px;font-family:var(--mono);">${esc((mood.stress_level||0).toFixed(2))}</span></div>
      <div style="padding:8px 0;display:flex;justify-content:space-between;">
        <span style="font-size:12px;">Redis</span><span style="font-size:11px;color:${mem.redis_connected?'var(--success)':'var(--danger)'};">${mem.redis_connected?'Verbunden':'Getrennt'}</span></div>`;
  } catch(e) { console.error('Dashboard fail:', e); }
}

// ---- Live-Status Auto-Refresh ----
let _liveInterval = null;

function startLiveRefresh() {
  stopLiveRefresh();
  refreshLiveStatus();
  _liveInterval = setInterval(refreshLiveStatus, 30000);
}

function stopLiveRefresh() {
  if (_liveInterval) { clearInterval(_liveInterval); _liveInterval = null; }
}

async function refreshLiveStatus() {
  try {
    const d = await api('/api/ui/live-status');
    const dot = document.getElementById('liveIndicator');
    const ts = document.getElementById('liveTimestamp');
    const wb = document.getElementById('whisperBadge');
    if (dot) dot.classList.toggle('offline', !d.components_ok);
    if (ts) ts.textContent = 'Aktualisiert: ' + new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    if (wb) wb.style.display = d.whisper_mode ? '' : 'none';
    const sb = document.getElementById('statusBadge');
    if (sb) { sb.textContent = d.components_ok ? 'Online' : 'Offline'; sb.className = 'badge ' + (d.components_ok ? 'badge-ok' : 'badge-err'); }
    // Mood und Stress im Status-Bereich aktualisieren
    const mi = document.getElementById('moodInfo');
    if (mi && d.mood) {
      const mood = d.mood;
      mi.innerHTML = `
        <div style="padding:8px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;">
          <span style="font-size:12px;">Stimmung</span><span style="font-size:12px;color:var(--accent);font-weight:600;">${esc(mood.mood||'neutral')}</span></div>
        <div style="padding:8px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;">
          <span style="font-size:12px;">Stress</span><span style="font-size:12px;font-family:var(--mono);">${esc((mood.stress_level||0).toFixed(2))}</span></div>
        <div style="padding:8px 0;display:flex;justify-content:space-between;">
          <span style="font-size:12px;">Autonomie</span><span style="font-size:12px;color:var(--accent);font-weight:600;">${esc(d.autonomy?.level||'?')}/5</span></div>`;
    }
  } catch(e) {
    const dot = document.getElementById('liveIndicator');
    if (dot) dot.classList.add('offline');
    const sb = document.getElementById('statusBadge');
    if (sb) { sb.textContent = 'Offline'; sb.className = 'badge badge-err'; }
  }
}

// ---- Health Trends ----
let _trendHours = 24;

async function loadHealthTrends(hours) {
  _trendHours = hours || 24;
  // Button aktiv markieren
  document.querySelectorAll('#trendPeriodBar button').forEach(b => {
    b.classList.toggle('active', parseInt(b.textContent)=== hours || (b.textContent==='7 Tage' && hours===168) || (b.textContent==='24h' && hours===24) || (b.textContent==='48h' && hours===48));
  });
  const c = document.getElementById('healthTrendsContainer');
  try {
    const d = await api(`/api/ui/health-trends?hours=${hours}`);
    const current = d.current || {};
    const trends = d.trends || {};
    const sensors = [
      {key:'co2', label:'CO2', unit:'ppm', icon:'&#127811;', goodMax:800, warnMax:1200},
      {key:'temperature', label:'Temperatur', unit:'°C', icon:'&#127777;'},
      {key:'humidity', label:'Luftfeuchtigkeit', unit:'%', icon:'&#128167;', goodMin:40, goodMax:60},
    ];
    let html = '';
    let hasData = false;
    for (const s of sensors) {
      const val = current[s.key];
      const trendData = trends[s.key] || [];
      if (val === undefined && trendData.length === 0) continue;
      hasData = true;
      // Trend-Pfeil berechnen
      let arrow = 'stable', arrowIcon = '&#8594;';
      if (trendData.length >= 2) {
        const recent = trendData[trendData.length-1].value;
        const older = trendData[Math.max(0, trendData.length-3)].value;
        if (recent > older + 1) { arrow='up'; arrowIcon='&#8593;'; }
        else if (recent < older - 1) { arrow='down'; arrowIcon='&#8595;'; }
      }
      // Mini-Sparkline SVG
      let sparkline = '';
      if (trendData.length >= 2) {
        const vals = trendData.map(t => t.value);
        const min = Math.min(...vals), max = Math.max(...vals);
        const range = max - min || 1;
        const w = 120, h = 24;
        const points = vals.map((v, i) => `${(i/(vals.length-1))*w},${h-(((v-min)/range)*h)}`).join(' ');
        sparkline = `<svg class="trend-sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="1.5" /></svg>`;
      }
      html += `<div class="trend-row">
        <span class="trend-label">${s.icon} ${s.label}</span>
        <span class="trend-value">${val!==undefined ? (typeof val==='number'?val.toFixed(1):val) : '—'}</span>
        <span class="trend-unit">${s.unit}</span>
        <span class="trend-arrow ${arrow}">${arrowIcon}</span>
        ${sparkline}
        <span style="font-size:10px;color:var(--text-muted);">${trendData.length} Messpunkte</span>
      </div>`;
    }
    if (!hasData) {
      html = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">Keine Sensordaten verfuegbar</div>';
    }
    c.innerHTML = html;
  } catch(e) {
    c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">Keine Sensordaten verfuegbar</div>';
  }
}

// ============================================================
//  SETTINGS - 11 Tabs
// ============================================================

let currentTab = 'tab-general';

function mergeCurrentTabIntoS() {
  try {
    const current = collectSettings();
    deepMerge(S, current);
  } catch(e) { /* Tab noch nicht gerendert */ }
}

async function loadSettings() {
  try {
    S = await api('/api/ui/settings');
    renderCurrentTab();
  } catch(e) { console.error('Settings fail:', e); }
}

function renderCurrentTab() {
  const c = document.getElementById('settingsContent');
  // Offene Sections merken (Index-basiert)
  const openIdxs = new Set();
  c.querySelectorAll('.s-section-hdr.open').forEach(hdr => {
    const sec = hdr.closest('.s-section');
    if (sec) {
      const all = c.querySelectorAll('.s-section');
      for (let i = 0; i < all.length; i++) { if (all[i] === sec) { openIdxs.add(i); break; } }
    }
  });
  try {
    switch(currentTab) {
      case 'tab-general': c.innerHTML = renderGeneral(); break;
      case 'tab-persons': c.innerHTML = renderPersons(); loadMindHomeEntities(); break;
      case 'tab-personality': c.innerHTML = renderPersonality(); break;
      case 'tab-memory': c.innerHTML = renderMemory(); break;
      case 'tab-mood': c.innerHTML = renderMood(); break;
      case 'tab-rooms': c.innerHTML = renderRooms(); loadMindHomeEntities(); loadRoomTempAverage(); break;
      case 'tab-voice': c.innerHTML = renderVoice(); break;
      case 'tab-routines': c.innerHTML = renderRoutines(); break;
      case 'tab-proactive': c.innerHTML = renderProactive(); break;
      case 'tab-cooking': c.innerHTML = renderCooking(); break;
      case 'tab-house-status': c.innerHTML = renderHouseStatus(); break;
      case 'tab-devices': c.innerHTML = renderDevices(); loadMindHomeEntities(); break;
      case 'tab-covers': c.innerHTML = renderCovers(); loadCoverEntities(); break;
      case 'tab-security': c.innerHTML = renderSecurity(); loadApiKey(); loadNotifyChannels(); loadEmergencyProtocols(); break;
      case 'tab-autonomie': c.innerHTML = renderAutonomie(); loadSnapshots(); loadOptStatus(); break;
      case 'tab-followme': c.innerHTML = renderFollowMe(); break;
      case 'tab-eastereggs': c.innerHTML = renderEasterEggs(); loadEasterEggs(); break;
      case 'tab-system': c.innerHTML = renderSystem(); loadSystemStatus(); break;
    }
  } catch(err) {
    c.innerHTML = '<div style="padding:24px;color:var(--danger);"><h3>Rendering-Fehler</h3><pre style="margin-top:12px;font-size:12px;white-space:pre-wrap;">' + esc(err.message) + '\n' + esc(err.stack) + '</pre></div>';
    console.error('Tab render error:', err);
  }
  // Offene Sections wiederherstellen
  if (openIdxs.size > 0) {
    const secs = c.querySelectorAll('.s-section');
    openIdxs.forEach(i => {
      if (secs[i]) {
        const hdr = secs[i].querySelector('.s-section-hdr');
        const body = secs[i].querySelector('.s-section-body');
        if (hdr) hdr.classList.add('open');
        if (body) body.classList.add('open');
      }
    });
  }
  bindFormEvents();
}

// ---- Help Tooltip System ----
function showHelp(path) {
  const h = HELP_TEXTS[path];
  if (!h) return;
  const bd = document.getElementById('helpModalBackdrop');
  document.getElementById('helpModalTitle').textContent = h.title || path;
  document.getElementById('helpModalText').innerHTML = h.text || '';
  const det = document.getElementById('helpModalDetail');
  if (h.detail) { det.innerHTML = h.detail; det.style.display = ''; }
  else { det.style.display = 'none'; }
  bd.classList.add('show');
}
function closeHelpModal() {
  document.getElementById('helpModalBackdrop').classList.remove('show');
}
// ESC schliesst Modal
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHelpModal(); });

// ---- Help Texts fuer alle Settings ----
const HELP_TEXTS = {
  // === ALLGEMEIN ===
  'assistant.name': {title:'Assistenten-Name', text:'Der Name, mit dem sich der Assistent vorstellt und auf den er reagiert.'},
  'assistant.version': {title:'Version', text:'Aktuelle Software-Version. Nur zur Anzeige.'},
  'assistant.language': {title:'Sprache', text:'In welcher Sprache der Assistent antwortet.'},
  'autonomy.level': {title:'Autonomie-Level', text:'Wie selbststaendig darf der Assistent handeln?', detail:'<b>1 Assistent:</b> Nur auf Befehl<br><b>2 Butler:</b> Schlaegt vor, wartet auf OK<br><b>3 Mitbewohner:</b> Handelt bei Routine-Aufgaben<br><b>4 Vertrauter:</b> Proaktiv<br><b>5 Autopilot:</b> Volle Autonomie'},
  'models.enabled.fast': {title:'Fast-Modell', text:'Schnelles Modell fuer einfache Befehle (Licht an, Timer, Danke).'},
  'models.enabled.smart': {title:'Smart-Modell', text:'Standard-Modell fuer normale Gespraeche und Anfragen.'},
  'models.enabled.deep': {title:'Deep-Modell', text:'Grosses Modell fuer komplexe Analysen und ausfuehrliche Antworten.'},
  'models.fast': {title:'Fast-Modell Auswahl', text:'Welches KI-Modell fuer schnelle Befehle.', detail:'Kleinere Modelle (3-4B) sind schneller, groessere praeziser.'},
  'models.smart': {title:'Smart-Modell Auswahl', text:'Welches KI-Modell fuer normale Gespraeche.'},
  'models.deep': {title:'Deep-Modell Auswahl', text:'Welches KI-Modell fuer komplexe Aufgaben.', detail:'14B+ empfohlen fuer beste Ergebnisse.'},
  'models.deep_min_words': {title:'Deep ab Woertern', text:'Ab wie vielen Woertern automatisch das Deep-Modell genutzt wird.'},
  'models.options.temperature': {title:'Kreativitaet', text:'Wie kreativ die Antworten sein sollen.', detail:'0 = deterministisch, 0.7 = Standard, 2.0 = sehr kreativ'},
  'models.options.max_tokens': {title:'Max. Antwortlaenge', text:'Maximale Laenge einer Antwort in Tokens (~0.75 Woerter pro Token).'},
  'models.fast_keywords': {title:'Fast-Keywords', text:'Woerter die das schnelle Modell aktivieren.'},
  'models.deep_keywords': {title:'Deep-Keywords', text:'Woerter die das ausfuehrliche Modell aktivieren.'},
  'models.cooking_keywords': {title:'Koch-Keywords', text:'Woerter die den Koch-Modus aktivieren.'},
  'web_search.enabled': {title:'Web-Suche', text:'Optionale Web-Recherche. Privacy-First: SearXNG oder DuckDuckGo.'},
  'web_search.engine': {title:'Suchmaschine', text:'SearXNG (self-hosted) oder DuckDuckGo.'},
  'web_search.searxng_url': {title:'SearXNG URL', text:'URL deiner SearXNG-Instanz. Nur bei SearXNG relevant.'},
  'web_search.max_results': {title:'Max. Ergebnisse', text:'Wie viele Suchergebnisse maximal abgerufen werden.'},
  'web_search.timeout_seconds': {title:'Such-Timeout', text:'Nach wie vielen Sekunden die Suche abgebrochen wird.'},
  // === PERSOENLICHKEIT ===
  'personality.style': {title:'Grundstil', text:'Grundlegender Kommunikationsstil des Assistenten.'},
  'personality.sarcasm_level': {title:'Sarkasmus-Level', text:'Wie sarkastisch der Assistent sein darf (1-5).'},
  'personality.opinion_intensity': {title:'Meinungs-Intensitaet', text:'Wie stark der Assistent seine Meinung aeussert (0-3).'},
  'personality.self_irony_enabled': {title:'Selbstironie', text:'Ob der Assistent ueber sich selbst witzeln darf.'},
  'personality.self_irony_max_per_day': {title:'Max. Selbstironie/Tag', text:'Wie oft pro Tag Selbstironie erlaubt ist.'},
  'personality.character_evolution': {title:'Charakter-Entwicklung', text:'Assistent wird mit der Zeit vertrauter und informeller.'},
  'personality.formality_start': {title:'Anfangs-Formalitaet', text:'Wie formell am Anfang (100%=Sie, 0%=sehr locker).'},
  'personality.formality_min': {title:'Minimale Formalitaet', text:'Wie locker der Assistent maximal werden darf.'},
  'personality.formality_decay_per_day': {title:'Formalitaets-Abbau', text:'Wie schnell der Assistent lockerer wird (Punkte/Tag).'},
  'response_filter.enabled': {title:'Antwort-Filter', text:'Filtert unerwuenschte Phrasen und begrenzt Antwortlaenge.'},
  'response_filter.max_response_sentences': {title:'Max. Saetze', text:'Max. Saetze pro Antwort. 0 = unbegrenzt.'},
  'response_filter.banned_phrases': {title:'Verbotene Phrasen', text:'Phrasen die der Assistent nie verwenden soll.'},
  'response_filter.banned_starters': {title:'Verbotene Satzanfaenge', text:'Satzanfaenge die vermieden werden sollen.'},
  // === GEDAECHTNIS ===
  'memory.extraction_enabled': {title:'Fakten-Extraktion', text:'Automatisch Fakten aus Gespraechen lernen und merken.'},
  'memory.extraction_min_words': {title:'Min. Nachrichtenlaenge', text:'Mindestlaenge damit Fakten extrahiert werden.'},
  'memory.extraction_model': {title:'Extraktions-Modell', text:'KI-Modell fuer Fakten-Erkennung.'},
  'memory.extraction_temperature': {title:'Extraktions-Genauigkeit', text:'Niedrig = nur offensichtliche Fakten, hoch = auch Vermutungen.'},
  'memory.extraction_max_tokens': {title:'Max. Extraktions-Laenge', text:'Maximale Laenge der Extraktions-Antwort.'},
  'memory.max_person_facts_in_context': {title:'Personen-Fakten', text:'Wie viele Fakten ueber die Person ins Gespraech einfliessen.'},
  'memory.max_relevant_facts_in_context': {title:'Relevante Fakten', text:'Wie viele thematisch passende Fakten pro Gespraech.'},
  'memory.min_confidence_for_context': {title:'Min. Sicherheit', text:'Wie sicher ein Fakt sein muss um genutzt zu werden.'},
  'memory.duplicate_threshold': {title:'Duplikat-Erkennung', text:'Wie aehnlich zwei Fakten fuer Duplikat-Erkennung sein muessen.'},
  'memory.episode_min_words': {title:'Min. Woerter Episode', text:'Mindestlaenge fuer episodisches Gedaechtnis.'},
  'memory.default_confidence': {title:'Standard-Sicherheit', text:'Sicherheit mit der neue Fakten gespeichert werden.'},
  'knowledge_base.enabled': {title:'Wissensdatenbank', text:'RAG-System fuer eigene Dokumente (.txt, .md, .pdf).'},
  'knowledge_base.auto_ingest': {title:'Auto-Einlesen', text:'Beim Start neue Dateien automatisch aufnehmen.'},
  'knowledge_base.chunk_size': {title:'Textblock-Groesse', text:'In welche Stuecke Dokumente zerteilt werden.'},
  'knowledge_base.chunk_overlap': {title:'Ueberlappung', text:'Ueberlappung zwischen aufeinanderfolgenden Bloecken.'},
  'knowledge_base.max_distance': {title:'Suchgenauigkeit', text:'Max. Distanz fuer Treffer (niedriger = strenger).'},
  'knowledge_base.search_limit': {title:'Max. Treffer', text:'Max. Wissens-Treffer pro Suche.'},
  'knowledge_base.embedding_model': {title:'Embedding-Modell', text:'Modell fuer Vektorisierung. Nach Wechsel Rebuild noetig.'},
  'knowledge_base.supported_extensions': {title:'Dateitypen', text:'Welche Formate in die Wissensdatenbank koennen.'},
  'correction.confidence': {title:'Korrektur-Sicherheit', text:'Sicherheit bei durch Nutzer korrigierten Fakten.'},
  'correction.model': {title:'Korrektur-Modell', text:'KI-Modell fuer Korrektur-Analyse.'},
  'correction.temperature': {title:'Korrektur-Kreativitaet', text:'Kreativitaet der Korrektur-Analyse.'},
  'summarizer.run_hour': {title:'Zusammenfassung Stunde', text:'Uhrzeit (Stunde) der taeglichen Zusammenfassung.'},
  'summarizer.run_minute': {title:'Zusammenfassung Minute', text:'Uhrzeit (Minute) der Zusammenfassung.'},
  'summarizer.model': {title:'Zusammenfassungs-Modell', text:'KI-Modell fuer Tages-Zusammenfassung.'},
  'summarizer.max_tokens_daily': {title:'Laenge taeglich', text:'Max. Laenge der taeglichen Zusammenfassung.'},
  'summarizer.max_tokens_weekly': {title:'Laenge woechentlich', text:'Max. Laenge der woechentlichen Zusammenfassung.'},
  'summarizer.max_tokens_monthly': {title:'Laenge monatlich', text:'Max. Laenge der monatlichen Zusammenfassung.'},
  'context.recent_conversations': {title:'Gespraeche merken', text:'Wie viele vergangene Gespraeche im Kontext bleiben.'},
  'context.api_timeout': {title:'HA-API Timeout', text:'Timeout fuer Home-Assistant-Anfragen (Sek).'},
  'context.llm_timeout': {title:'LLM Timeout', text:'Timeout fuer KI-Anfragen (Sek). Groessere Modelle brauchen laenger.'},
  // === STIMMUNG ===
  'mood.rapid_command_seconds': {title:'Schnelle Befehle', text:'Zeitfenster fuer "schnelle Befehle hintereinander" (Sek).'},
  'mood.stress_decay_seconds': {title:'Stress-Abbau', text:'Nach wie vielen Sek Ruhe der Stress sinkt.'},
  'mood.frustration_threshold': {title:'Frustrations-Schwelle', text:'Ab wie vielen Stress-Punkten Frustration erkannt wird.'},
  'mood.tired_hour_start': {title:'Muede ab', text:'Ab welcher Uhrzeit Muedigkeit angenommen wird.'},
  'mood.tired_hour_end': {title:'Muede bis', text:'Bis zu welcher Uhrzeit Muedigkeit gilt.'},
  'mood.rapid_command_stress_boost': {title:'Stress: Schnelle Befehle', text:'Stressanstieg durch schnelle Befehle hintereinander.'},
  'mood.positive_stress_reduction': {title:'Stress: Positive Worte', text:'Stressabbau durch positive Worte.'},
  'mood.negative_stress_boost': {title:'Stress: Negative Worte', text:'Stressanstieg durch negative Worte.'},
  'mood.impatient_stress_boost': {title:'Stress: Ungeduld', text:'Stressanstieg durch ungedulige Worte.'},
  'mood.tired_boost': {title:'Stress: Muedigkeit', text:'Stresseinfluss durch Muedigkeit.'},
  'mood.repetition_stress_boost': {title:'Stress: Wiederholungen', text:'Stressanstieg durch wiederholte Befehle.'},
  'mood.positive_keywords': {title:'Positive Woerter', text:'Woerter die gute Stimmung signalisieren.'},
  'mood.negative_keywords': {title:'Negative Woerter', text:'Woerter die schlechte Stimmung signalisieren.'},
  'mood.impatient_keywords': {title:'Ungeduld-Woerter', text:'Woerter die Ungeduld signalisieren.'},
  'mood.tired_keywords': {title:'Muedigkeits-Woerter', text:'Woerter die Muedigkeit signalisieren.'},
  // === SPRACH-ENGINE ===
  'speech.stt_model': {title:'Whisper-Modell', text:'Groessere Modelle sind genauer aber langsamer. "small" ist fuer CPU empfohlen, "large-v3-turbo" fuer GPU.'},
  'speech.stt_language': {title:'Sprache', text:'Sprache fuer die Spracherkennung. Beeinflusst Genauigkeit der Transkription.'},
  'speech.stt_beam_size': {title:'Beam Size', text:'Hoehere Werte = genauere Erkennung, aber langsamer. Standard: 5.'},
  'speech.stt_compute': {title:'Berechnung', text:'int8 fuer CPU (schnell, wenig RAM), float16 fuer GPU, float32 fuer maximale Praezision.'},
  'speech.stt_device': {title:'Hardware', text:'CPU fuer Standard-Betrieb, CUDA fuer NVIDIA GPU (NVIDIA Container Toolkit erforderlich).'},
  'speech.tts_voice': {title:'Piper-Stimme', text:'Stimme fuer die Sprachsynthese. "thorsten-high" hat die beste Qualitaet auf Deutsch.'},
  'speech.auto_night_whisper': {title:'Nacht-Fluestern', text:'Jarvis spricht nachts automatisch leiser (basierend auf den Lautstaerke-Einstellungen).'},
  'voice_analysis.enabled': {title:'Stimm-Analyse', text:'Analysiert Sprechtempo zur Stimmungserkennung.'},
  'voice_analysis.wpm_fast': {title:'Schnelles Sprechen (WPM)', text:'Ab wie vielen Woertern/Min schnelles Sprechen erkannt wird.'},
  'voice_analysis.wpm_slow': {title:'Langsames Sprechen (WPM)', text:'Unter wie vielen Woertern/Min langsames Sprechen gilt.'},
  'voice_analysis.wpm_normal': {title:'Normales Tempo (WPM)', text:'Referenzwert fuer normales Sprechtempo.'},
  'voice_analysis.use_whisper_metadata': {title:'Whisper-Metadaten', text:'Zusaetzliche Daten von Whisper fuer Analyse nutzen.'},
  'voice_analysis.voice_weight': {title:'Stimm-Gewichtung', text:'Wie stark Stimm-Analyse die Gesamtstimmung beeinflusst (0-1).'},
  // === RAEUME ===
  'room_temperature.sensors': {title:'Temperatursensoren', text:'HA-Sensoren fuer Raumtemperatur.'},
  'multi_room.enabled': {title:'Multi-Room', text:'Erkennt in welchem Raum du bist.'},
  'multi_room.presence_timeout_minutes': {title:'Praesenz-Timeout', text:'Nach wie vielen Min ohne Bewegung der Raum leer ist.'},
  'multi_room.auto_follow': {title:'Musik folgen', text:'Musik folgt automatisch von Raum zu Raum.'},
  'follow_me.enabled': {title:'Follow-Me', text:'JARVIS folgt dir von Raum zu Raum. Musik, Licht und Temperatur wechseln automatisch.'},
  'follow_me.cooldown_seconds': {title:'Cooldown', text:'Mindestabstand zwischen Follow-Me Transfers. Verhindert Ping-Pong bei schnellen Raumwechseln.'},
  'follow_me.transfer_music': {title:'Musik folgt', text:'Musik wird automatisch in den neuen Raum transferiert.'},
  'follow_me.transfer_lights': {title:'Licht folgt', text:'Licht wird im alten Raum aus- und im neuen Raum eingeschaltet.'},
  'follow_me.transfer_climate': {title:'Klima folgt', text:'Heizung/Kuehlung wird im neuen Raum auf Komfort-Temperatur gesetzt.'},
  'multi_room.room_speakers': {title:'Speaker-Zuordnung', text:'Welcher Speaker in welchem Raum steht.'},
  'multi_room.room_motion_sensors': {title:'Bewegungsmelder', text:'Welcher Melder in welchem Raum haengt.'},
  'activity.entities.media_players': {title:'Media Player', text:'Media Player fuer Aktivitaetserkennung.'},
  'activity.entities.mic_sensors': {title:'Mikrofon-Sensoren', text:'Mikrofon-Sensoren fuer Spracheingabe.'},
  'activity.entities.bed_sensors': {title:'Bett-Sensoren', text:'Sensoren fuer Schlaf-Erkennung.'},
  'activity.entities.pc_sensors': {title:'PC-Sensoren', text:'Sensoren fuer Arbeits-Erkennung.'},
  'activity.thresholds.night_start': {title:'Nacht beginnt', text:'Ab wann Nachtruhe gilt.'},
  'activity.thresholds.night_end': {title:'Nacht endet', text:'Bis wann Nachtruhe gilt.'},
  'activity.thresholds.guest_person_count': {title:'Besuch ab Personen', text:'Ab wie vielen Personen Gaeste-Modus aktiviert wird.'},
  'activity.thresholds.focus_min_minutes': {title:'Fokus-Modus', text:'Ab wie vielen Min ununterbrochener Arbeit Fokus erkannt wird.'},
  // === STIMME & TTS ===
  'sounds.default_speaker': {title:'Standard-Speaker', text:'Standard-Geraet fuer Sprachausgabe und Sounds.'},
  'sounds.tts_entity': {title:'TTS-Engine', text:'Welche Text-to-Speech Engine genutzt wird.'},
  'sounds.alexa_speakers': {title:'Alexa Speaker', text:'Echo/Alexa Geraete fuer Benachrichtigungen.'},
  'tts.ssml_enabled': {title:'SSML', text:'Erweiterte Sprachsteuerung (Betonung, Pausen). Nicht alle Engines unterstuetzt.'},
  'tts.prosody_variation': {title:'Prosody', text:'Tonhoehe und Tempo variieren je nach Kontext.'},
  'tts.speed.confirmation': {title:'Tempo: Bestaetigung', text:'Sprechgeschwindigkeit bei Bestaetigungen (100=normal).'},
  'tts.speed.warning': {title:'Tempo: Warnung', text:'Sprechgeschwindigkeit bei Warnungen.'},
  'tts.speed.briefing': {title:'Tempo: Briefing', text:'Sprechgeschwindigkeit bei Briefings.'},
  'tts.speed.greeting': {title:'Tempo: Begruessung', text:'Sprechgeschwindigkeit bei Begruessungen.'},
  'tts.speed.question': {title:'Tempo: Frage', text:'Sprechgeschwindigkeit bei Fragen.'},
  'tts.speed.casual': {title:'Tempo: Normal', text:'Sprechgeschwindigkeit bei normalen Antworten.'},
  'tts.pauses.before_important': {title:'Pause: Wichtig', text:'ms Pause vor wichtigen Infos.'},
  'tts.pauses.between_sentences': {title:'Pause: Saetze', text:'ms Pause zwischen Saetzen.'},
  'tts.pauses.after_greeting': {title:'Pause: Begruessung', text:'ms Pause nach der Begruessung.'},
  'tts.whisper_triggers': {title:'Fluestern bei', text:'Bei welchen Situationen gefluestert wird.'},
  'tts.whisper_cancel_triggers': {title:'Fluestern beenden', text:'Was den Fluestermodus beendet.'},
  'volume.day': {title:'Lautstaerke: Tag', text:'Lautstaerke tagsueber (0-1).'},
  'volume.evening': {title:'Lautstaerke: Abend', text:'Lautstaerke am Abend.'},
  'volume.night': {title:'Lautstaerke: Nacht', text:'Lautstaerke nachts.'},
  'volume.sleeping': {title:'Lautstaerke: Schlaf', text:'Lautstaerke im Schlafmodus.'},
  'volume.emergency': {title:'Lautstaerke: Notfall', text:'Lautstaerke bei Notfaellen. Sollte hoch sein.'},
  'volume.whisper': {title:'Lautstaerke: Fluestern', text:'Lautstaerke im Fluestermodus.'},
  'volume.morning_start': {title:'Morgen ab', text:'Ab welcher Stunde Tages-Lautstaerke gilt.'},
  'volume.evening_start': {title:'Abend ab', text:'Ab welcher Stunde Abend-Lautstaerke gilt.'},
  'volume.night_start': {title:'Nacht ab', text:'Ab welcher Stunde Nacht-Lautstaerke gilt.'},
  'sounds.enabled': {title:'Sound-Effekte', text:'Kurze Toene bei Events (Zuhoeren, Bestaetigung, Warnung).'},
  'sounds.events.listening': {title:'Sound: Zuhoeren', text:'Sound beim Start des Zuhoerens.'},
  'sounds.events.confirmed': {title:'Sound: Bestaetigung', text:'Sound nach Bestaetigung.'},
  'sounds.events.warning': {title:'Sound: Warnung', text:'Sound bei Warnungen.'},
  'sounds.events.alarm': {title:'Sound: Alarm', text:'Sound bei Alarmen.'},
  'sounds.events.doorbell': {title:'Sound: Tuerklingel', text:'Sound bei Tuerklingel-Events.'},
  'sounds.events.greeting': {title:'Sound: Begruessung', text:'Sound bei Begruessungen.'},
  'sounds.events.error': {title:'Sound: Fehler', text:'Sound bei Fehlern.'},
  'sounds.events.goodnight': {title:'Sound: Gute Nacht', text:'Sound bei Gute-Nacht-Routine.'},
  'sounds.night_volume_factor': {title:'Nacht-Sound-Faktor', text:'Sound-Lautstaerke nachts als Faktor (0.3 = 30%).'},
  'narration.enabled': {title:'Szenen-Narration', text:'Assistent erzaehlt bei Szenen-Wechseln was passiert.'},
  'narration.default_transition': {title:'Standard-Uebergang', text:'Standard-Dauer fuer Szenen-Uebergaenge (Sek).'},
  'narration.scene_transitions.filmabend': {title:'Filmabend-Uebergang', text:'Uebergangs-Dauer Filmabend-Szene.'},
  'narration.scene_transitions.gute_nacht': {title:'Gute-Nacht-Uebergang', text:'Uebergangs-Dauer Gute-Nacht-Szene.'},
  'narration.scene_transitions.aufwachen': {title:'Aufwach-Uebergang', text:'Uebergangs-Dauer Aufwach-Szene.'},
  'narration.scene_transitions.gemuetlich': {title:'Gemuetlich-Uebergang', text:'Uebergangs-Dauer Gemuetlich-Szene.'},
  'narration.step_delay': {title:'Schritt-Verzoegerung', text:'Pause zwischen Aktionen innerhalb einer Szene.'},
  'narration.narrate_actions': {title:'Aktionen ansagen', text:'Bei Szenen-Wechseln ansagen was passiert.'},
  'speaker_recognition.enabled': {title:'Sprecher-Erkennung', text:'Erkennt wer spricht und passt Antworten an.'},
  'speaker_recognition.min_confidence': {title:'Erkennungs-Sicherheit', text:'Wie sicher die Erkennung sein muss (0.6 empfohlen). Unter diesem Wert wird nachgefragt.'},
  'speaker_recognition.enrollment_duration': {title:'Einlern-Dauer', text:'Wie lange eine Person sprechen muss zum Einlernen.'},
  'speaker_recognition.fallback_ask': {title:'Nachfragen', text:'Bei unsicherer Erkennung nachfragen "Wer spricht?" — die Antwort wird fuer den Stimmabdruck gelernt.'},
  'speaker_recognition.max_profiles': {title:'Max. Profile', text:'Max. Anzahl gespeicherter Sprecher-Profile.'},
  'speaker_recognition.device_mapping': {title:'Geraete-Zuordnung', text:'Welches ESPHome-Geraet gehoert welcher Person? Format: Device-ID → Person. Die Device-ID findest du in HA unter Einstellungen → Geraete → ESPHome.'},
  'speaker_recognition.doa_mapping': {title:'Richtungs-Zuordnung (DoA)', text:'Direction of Arrival: Welcher Winkel gehoert welcher Person pro Geraet? Erfordert ReSpeaker XVF3800. Format: Winkelbereich (z.B. "0-90") → Person.'},
  'speaker_recognition.doa_tolerance': {title:'DoA-Toleranz', text:'Toleranz fuer die Richtungserkennung in Grad. Groessere Werte sind toleranter, kleinere praeziser.'},
  // === ROUTINEN ===
  'routines.morning_briefing.enabled': {title:'Morgen-Briefing', text:'Automatisches Update am Morgen mit Wetter, Terminen, Neuigkeiten.'},
  'routines.morning_briefing.trigger': {title:'Briefing-Ausloeser', text:'Was das Morgen-Briefing ausloest (Bewegung, Sprache, Wecker).'},
  'routines.morning_briefing.modules': {title:'Briefing-Module', text:'Was im Morgen-Briefing enthalten sein soll.'},
  'routines.morning_briefing.weekday_style': {title:'Stil Wochentag', text:'Briefing-Stil unter der Woche.'},
  'routines.morning_briefing.weekend_style': {title:'Stil Wochenende', text:'Briefing-Stil am Wochenende.'},
  'routines.morning_briefing.morning_actions.covers_up': {title:'Rolladen hoch', text:'Beim Briefing automatisch Rolladen hochfahren.'},
  'routines.morning_briefing.morning_actions.lights_soft': {title:'Licht sanft an', text:'Beim Briefing sanft Licht einschalten.'},
  'routines.evening_briefing.enabled': {title:'Abend-Briefing', text:'Automatischer Abend-Status: offene Fenster, Sicherheit, Wetter morgen.'},
  'routines.evening_briefing.window_start_hour': {title:'Abend-Start', text:'Ab wann das Abend-Briefing ausgeloest werden kann.'},
  'routines.evening_briefing.window_end_hour': {title:'Abend-Ende', text:'Bis wann das Abend-Briefing ausgeloest wird.'},
  'calendar.entities': {title:'Kalender-Entities', text:'HA-Kalender die abgefragt werden. Leer = alle.'},
  'routines.good_night.enabled': {title:'Gute-Nacht-Routine', text:'Automatische Aktionen bei "Gute Nacht": Lichter, Heizung, Checks.'},
  'routines.good_night.triggers': {title:'Gute-Nacht Phrasen', text:'Saetze die die Routine ausloesen.'},
  'routines.good_night.checks': {title:'Sicherheits-Checks', text:'Was vor dem Schlafen geprueft wird (Tueren, Fenster, Herd).'},
  'routines.good_night.actions.lights_off': {title:'Lichter aus', text:'Alle Lichter bei Gute-Nacht ausschalten.'},
  'routines.good_night.actions.heating_night': {title:'Heizung Nacht', text:'Heizung auf Nacht-Modus setzen.'},
  'routines.good_night.actions.covers_down': {title:'Rolladen runter', text:'Alle Rolladen bei Gute-Nacht runterfahren.'},
  'routines.good_night.actions.alarm_arm_home': {title:'Alarmanlage', text:'Alarmanlage im Home-Modus scharf schalten.'},
  'routines.guest_mode.triggers': {title:'Gaeste-Modus Trigger', text:'Saetze die den Gaeste-Modus aktivieren.'},
  'routines.guest_mode.restrictions.hide_personal_info': {title:'Infos verstecken', text:'Persoenliche Infos im Gaeste-Modus verbergen.'},
  'routines.guest_mode.restrictions.formal_tone': {title:'Formeller Ton', text:'Im Gaeste-Modus formeller sprechen.'},
  'routines.guest_mode.restrictions.restrict_security': {title:'Sicherheit einschraenken', text:'Sicherheitsfunktionen im Gaeste-Modus limitieren.'},
  'routines.guest_mode.restrictions.suggest_guest_wifi': {title:'Gaeste-WLAN', text:'Gaeste-WLAN im Gaeste-Modus vorschlagen.'},
  // === PROAKTIV ===
  'proactive.enabled': {title:'Proaktive Meldungen', text:'Assistent meldet sich von allein bei wichtigen Ereignissen.'},
  'proactive.cooldown_seconds': {title:'Meldungs-Abstand', text:'Mindestzeit zwischen proaktiven Meldungen.'},
  'proactive.music_follow_cooldown_minutes': {title:'Musik-Pause', text:'Wartezeit bevor Musik dem Raumwechsel folgt.'},
  'proactive.min_autonomy_level': {title:'Min. Autonomie', text:'Ab welchem Level proaktive Meldungen erlaubt sind.'},
  'proactive.silence_scenes': {title:'Nicht stoeren', text:'Szenen in denen nicht gestoert wird (Film, Schlaf, Meditation).'},
  'time_awareness.enabled': {title:'Zeitgefuehl', text:'Erinnert wenn Geraete zu lange laufen (Ofen, Buegeleisen).'},
  'time_awareness.check_interval_minutes': {title:'Pruef-Intervall', text:'Wie oft nach vergessenen Geraeten geschaut wird.'},
  'time_awareness.thresholds.oven': {title:'Ofen-Warnung', text:'Nach wie vielen Min der Ofen gemeldet wird.'},
  'time_awareness.thresholds.iron': {title:'Buegeleisen-Warnung', text:'Nach wie vielen Min das Buegeleisen gemeldet wird.'},
  'time_awareness.thresholds.light_empty_room': {title:'Licht leer', text:'Nach wie vielen Min Licht im leeren Raum gemeldet wird.'},
  'time_awareness.thresholds.window_open_cold': {title:'Fenster kalt', text:'Nach wie vielen Min offenes Fenster bei Kaelte gemeldet wird.'},
  'time_awareness.thresholds.pc_no_break': {title:'PC-Pause', text:'Nach wie vielen Min am PC eine Pause vorgeschlagen wird.'},
  'time_awareness.counters.coffee_machine': {title:'Kaffee-Zaehler', text:'Zaehlt Kaffees und erinnert bei zu vielen.'},
  'anticipation.enabled': {title:'Vorausdenken', text:'Lernt Gewohnheiten und schlaegt Aktionen vor.'},
  'anticipation.history_days': {title:'Lern-Zeitraum', text:'Wie viele Tage zurueck fuer Muster-Erkennung.'},
  'anticipation.min_confidence': {title:'Mindest-Sicherheit', text:'Wie sicher eine Vorhersage sein muss.'},
  'anticipation.check_interval_minutes': {title:'Pruef-Intervall', text:'Wie oft nach vorhersagbaren Aktionen geschaut wird.'},
  'anticipation.thresholds.ask': {title:'Schwelle: Nachfragen', text:'Ab welcher Sicherheit nachgefragt wird.'},
  'anticipation.thresholds.suggest': {title:'Schwelle: Vorschlagen', text:'Ab welcher Sicherheit vorgeschlagen wird.'},
  'anticipation.thresholds.auto': {title:'Schwelle: Automatisch', text:'Ab welcher Sicherheit automatisch ausgefuehrt wird.'},
  'insights.enabled': {title:'Jarvis denkt voraus', text:'Kreuz-referenziert Wetter, Kalender, Energie und Geraete — und meldet sich proaktiv.'},
  'insights.check_interval_minutes': {title:'Pruef-Intervall', text:'Wie oft alle Datenquellen abgeglichen werden.'},
  'insights.cooldown_hours': {title:'Cooldown', text:'Wie lange nach einem Hinweis der gleiche Typ nicht nochmal kommt.'},
  'insights.checks.weather_windows': {title:'Wetter + Fenster', text:'Warnt wenn Regen/Sturm kommt und Fenster offen sind.'},
  'insights.checks.frost_heating': {title:'Frost + Heizung', text:'Warnt wenn Frost erwartet wird und Heizung aus/abwesend ist.'},
  'insights.checks.calendar_travel': {title:'Reise + Haus', text:'Erkennt Reise-Termine und prueft Alarm, Fenster, Heizung.'},
  'insights.checks.energy_anomaly': {title:'Energie-Anomalie', text:'Meldet wenn der Verbrauch deutlich ueber dem Durchschnitt liegt.'},
  'insights.checks.away_devices': {title:'Abwesend + Geraete', text:'Meldet wenn niemand da ist aber Licht/Fenster offen sind.'},
  'insights.checks.temp_drop': {title:'Temperatur-Abfall', text:'Erkennt wenn die Temperatur ungewoehnlich schnell faellt.'},
  'insights.checks.window_temp_drop': {title:'Fenster + Kaelte', text:'Warnt bei offenem Fenster und grosser Temperatur-Differenz innen/aussen.'},
  'insights.thresholds.frost_temp_c': {title:'Frost-Schwelle', text:'Ab welcher Temperatur Frostwarnung ausgeloest wird.'},
  'insights.thresholds.energy_anomaly_percent': {title:'Energie-Schwelle', text:'Ab wie viel Prozent Abweichung gewarnt wird.'},
  'insights.thresholds.away_device_minutes': {title:'Abwesenheits-Dauer', text:'Wie lange jemand weg sein muss bevor der Hinweis kommt.'},
  'insights.thresholds.temp_drop_degrees_per_2h': {title:'Temp-Abfall', text:'Wie viel Grad Abfall in 2 Stunden als ungewoehnlich gilt.'},
  'intent_tracking.enabled': {title:'Absicht-Erkennung', text:'Erkennt offene Absichten und erinnert spaeter.'},
  'intent_tracking.check_interval_minutes': {title:'Pruef-Intervall', text:'Wie oft nach offenen Absichten geschaut wird.'},
  'intent_tracking.remind_hours_before': {title:'Erinnerung vorher', text:'Wie viele Stunden vorher erinnert wird.'},
  'conversation_continuity.enabled': {title:'Gespraech fortsetzen', text:'Fragt nach ob unterbrochenes Gespraech fortgesetzt werden soll.'},
  'conversation_continuity.resume_after_minutes': {title:'Nachfragen nach', text:'Nach wie vielen Min zum Thema zurueckgekehrt wird.'},
  'conversation_continuity.expire_hours': {title:'Thema vergessen', text:'Nach wie vielen Stunden ein Thema vergessen wird.'},
  // === KOCH-ASSISTENT ===
  'cooking.enabled': {title:'Koch-Assistent', text:'Koch-Modus mit Rezepten, Schritt-fuer-Schritt und Timern.'},
  'cooking.language': {title:'Rezept-Sprache', text:'Sprache der generierten Rezepte.'},
  'cooking.default_portions': {title:'Standard-Portionen', text:'Fuer wie viele Personen Rezepte berechnet werden.'},
  'cooking.max_steps': {title:'Max. Schritte', text:'Max. Schritte pro Rezept.'},
  'cooking.max_tokens': {title:'Rezept-Detailgrad', text:'Wie ausfuehrlich Rezepte beschrieben werden.'},
  'cooking.timer_notify_tts': {title:'Timer per Sprache', text:'Timer-Erinnerungen per Sprachausgabe.'},
  // === SICHERHEIT ===
  'security.require_confirmation': {title:'Bestaetigung noetig', text:'Fuer welche Aktionen der Assistent vorher fragen muss.'},
  'security.climate_limits.min': {title:'Temperatur Min', text:'Unter diese Temperatur wird nie geheizt (Frostschutz).'},
  'security.climate_limits.max': {title:'Temperatur Max', text:'Ueber diese Temperatur wird nie geheizt.'},
  'trust_levels.default': {title:'Standard-Vertrauen', text:'Vertrauensstufe fuer neue/unbekannte Personen.'},
  'trust_levels.guest_allowed_actions': {title:'Gaeste-Aktionen', text:'Was Gaeste ohne Bestaetigung duerfen.'},
  'trust_levels.security_actions': {title:'Besitzer-Aktionen', text:'Aktionen die nur der Besitzer darf.'},
  'interrupt_queue.enabled': {title:'Interrupt-Queue', text:'CRITICAL-Meldungen unterbrechen sofort.'},
  'interrupt_queue.pause_ms': {title:'Interrupt-Pause', text:'ms Pause vor Notfall-Meldung.'},
  'situation_model.enabled': {title:'Situations-Modell', text:'Merkt sich Haus-Zustand und meldet Aenderungen.'},
  'situation_model.min_pause_minutes': {title:'Delta-Pause', text:'Min. Abstand zwischen Aenderungs-Meldungen.'},
  'situation_model.max_changes': {title:'Max. Aenderungen', text:'Wie viele Aenderungen auf einmal gemeldet werden.'},
  'situation_model.temp_threshold': {title:'Temp-Schwelle', text:'Ab wie viel Grad Aenderung gemeldet wird.'},
  // === HAUS-STATUS ===
  'house_status.detail_level': {title:'Detail-Level', text:'Wie ausfuehrlich der Haus-Status berichtet wird. Kompakt = Zahlen, Normal = mit Namen, Ausfuehrlich = alle Details.'},
  'house_status.sections': {title:'Angezeigte Bereiche', text:'Welche Infos im Haus-Status angezeigt werden.'},
  'house_status.temperature_rooms': {title:'Temperatur-Raeume', text:'Nur diese Raeume fuer Temperatur. Leer = alle.'},
  'health_monitor.enabled': {title:'Health Monitor', text:'Ueberwacht Raumklima und warnt bei Problemen.'},
  'health_monitor.check_interval_minutes': {title:'Pruef-Intervall', text:'Wie oft Sensoren geprueft werden (Min).'},
  'health_monitor.alert_cooldown_minutes': {title:'Warn-Cooldown', text:'Min. Abstand zwischen Warnungen.'},
  'health_monitor.temp_low': {title:'Temp niedrig', text:'Unter dieser Temperatur wird gewarnt.'},
  'health_monitor.temp_high': {title:'Temp hoch', text:'Ueber dieser Temperatur wird gewarnt.'},
  'health_monitor.humidity_low': {title:'Feuchte niedrig', text:'Unter dieser Luftfeuchte wird gewarnt.'},
  'health_monitor.humidity_high': {title:'Feuchte hoch', text:'Ueber dieser Luftfeuchte wird gewarnt.'},
  'health_monitor.co2_warn': {title:'CO2 Warnung', text:'Ab diesem ppm-Wert wird gewarnt.'},
  'health_monitor.co2_critical': {title:'CO2 Kritisch', text:'Ab diesem ppm-Wert dringend lueften.'},
  'health_monitor.exclude_patterns': {title:'Ausschluss-Patterns', text:'Entity-IDs die ignoriert werden.'},
  // === GERAETE ===
  'device_health.enabled': {title:'Geraete-Health', text:'Ueberwacht Zustand von Smart-Home-Geraeten.'},
  'device_health.check_interval_minutes': {title:'Pruef-Intervall', text:'Wie oft Geraete geprueft werden.'},
  'device_health.alert_cooldown_minutes': {title:'Alert-Cooldown', text:'Min. Abstand zwischen Warnungen pro Geraet.'},
  'diagnostics.enabled': {title:'Diagnostik', text:'Automatische Pruefung: Batterie, Offline, veraltete Sensoren.'},
  'diagnostics.check_interval_minutes': {title:'Diagnostik-Intervall', text:'Wie oft die Diagnostik laeuft.'},
  'diagnostics.battery_warning_threshold': {title:'Batterie-Warnung', text:'Ab welchem Prozent eine Warnung kommt.'},
  'diagnostics.stale_sensor_minutes': {title:'Sensor veraltet', text:'Nach wie vielen Min ohne Update veraltet.'},
  'diagnostics.offline_threshold_minutes': {title:'Geraet offline', text:'Nach wie vielen Min ein Geraet offline gilt.'},
  'diagnostics.alert_cooldown_minutes': {title:'Diagnostik-Cooldown', text:'Min. Abstand zwischen Diagnostik-Warnungen.'},
  'diagnostics.monitor_domains': {title:'Ueberwachte Domains', text:'Welche HA-Domains ueberwacht werden.'},
  'diagnostics.exclude_patterns': {title:'Ignorierte Patterns', text:'Entity-IDs die ausgeschlossen werden.'},
  'maintenance.enabled': {title:'Wartungs-Erinnerungen', text:'Automatische Erinnerungen fuer Geraete-Wartung.'},
  // === AUTONOMIE ===
  'self_optimization.enabled': {title:'Selbstoptimierung', text:'Assistent analysiert sich selbst und schlaegt Verbesserungen vor.'},
  'self_optimization.approval_mode': {title:'Genehmigungsmodus', text:'ask = vorher fragen, auto = anwenden, log_only = nur loggen.'},
  'self_optimization.analysis_interval': {title:'Analyse-Intervall', text:'Wie oft Selbst-Analyse laeuft.'},
  'self_optimization.max_proposals_per_cycle': {title:'Max. Vorschlaege', text:'Max. Optimierungen pro Analyse-Zyklus.'},
  'self_optimization.model': {title:'Analyse-Modell', text:'KI-Modell fuer Selbst-Analyse.'},
  'self_optimization.rollback.enabled': {title:'Rollback', text:'Aenderungen koennen rueckgaengig gemacht werden.'},
  'self_optimization.rollback.max_snapshots': {title:'Max. Snapshots', text:'Wie viele Config-Snapshots gespeichert werden.'},
  'self_optimization.rollback.snapshot_on_every_edit': {title:'Snapshot bei Aenderung', text:'Vor jeder Aenderung automatisch Snapshot erstellen.'},
  'self_optimization.immutable_keys': {title:'Geschuetzte Bereiche', text:'Config-Bereiche die NIE automatisch geaendert werden.'},
  'self_automation.enabled': {title:'Self-Automation', text:'Assistent erstellt eigenstaendig Automationen.'},
  'self_automation.max_per_day': {title:'Max. Automationen/Tag', text:'Max. Automationen die pro Tag erstellt werden.'},
  'self_automation.model': {title:'Automations-Modell', text:'KI-Modell fuer Automations-Erstellung.'},
  'feedback.auto_timeout_seconds': {title:'Feedback-Timeout', text:'Timeout fuer Feedback-Anfragen (Sek).'},
  'feedback.base_cooldown_seconds': {title:'Feedback-Abstand', text:'Min. Abstand zwischen Feedback-Anfragen.'},
  'feedback.score_suppress': {title:'Unterdruecken unter', text:'Unter diesem Score wird Feature unterdrueckt.'},
  'feedback.score_reduce': {title:'Reduzieren unter', text:'Unter diesem Score wird Feature reduziert.'},
  'feedback.score_normal': {title:'Normal ab', text:'Ab diesem Score normales Verhalten.'},
  'feedback.score_boost': {title:'Boost ab', text:'Ab diesem Score wird Feature verstaerkt.'},
};

function helpBtn(path) {
  if (!HELP_TEXTS[path]) return '';
  return ` <span class="help-btn" onclick="event.stopPropagation();showHelp('${path}')" title="Hilfe">?</span>`;
}

// ---- Form field generators ----
function fText(path, label, hint='', ro=false) {
  const v = getPath(S,path) ?? '';
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <input type="text" data-path="${path}" value="${esc(String(v))}" ${ro?'readonly':''}>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}
function fNum(path, label, min='', max='', step='1', hint='') {
  const v = getPath(S,path) ?? '';
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <input type="number" data-path="${path}" value="${v}" min="${min}" max="${max}" step="${step}">${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}
function fRange(path, label, min, max, step, labels=null) {
  const v = getPath(S,path) ?? min;
  const lbl = labels ? (labels[v]||v) : v;
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="range-group"><input type="range" data-path="${path}" min="${min}" max="${max}" step="${step}" value="${v}"
      oninput="updRange(this)"><span class="range-value" id="rv_${path.replace(/\./g,'_')}">${lbl}</span></div></div>`;
}
function fToggle(path, label) {
  const v = getPath(S,path);
  return `<div class="form-group"><div class="toggle-group"><label>${label}${helpBtn(path)}</label>
    <label class="toggle"><input type="checkbox" data-path="${path}" ${v?'checked':''}><span class="toggle-track"></span><span class="toggle-thumb"></span></label></div></div>`;
}
function fSelect(path, label, opts) {
  const v = getPath(S,path) ?? '';
  let h = `<div class="form-group"><label>${label}${helpBtn(path)}</label><select data-path="${path}">`;
  for(const o of opts) h += `<option value="${o.v}" ${v==o.v?'selected':''}>${o.l}</option>`;
  return h + `</select></div>`;
}
function fKeywords(path, label) {
  const arr = getPath(S,path) || [];
  let tags = arr.map(k => `<span class="kw-tag">${esc(k)}<span class="kw-rm" onclick="rmKw(this,'${path}')">&#10005;</span></span>`).join('');
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="kw-editor" data-path="${path}" onclick="this.querySelector('input').focus()">
      ${tags}<input class="kw-input" placeholder="+ hinzufuegen..." onkeydown="addKw(event,this,'${path}')">
    </div></div>`;
}
function fTextarea(path, label, hint='') {
  const v = getPath(S,path);
  const isArr = Array.isArray(v);
  const isObj = v && typeof v === 'object' && !isArr;
  const txt = isArr ? v.join('\n') : (isObj ? JSON.stringify(v,null,2) : String(v??''));
  const dtype = isArr ? 'array' : (isObj ? 'json' : 'text');
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <textarea data-path="${path}" data-type="${dtype}">${esc(txt)}</textarea>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

// Klickbare Chip-Auswahl (vordefinierte Optionen zum An/Abklicken)
function fChipSelect(path, label, options, hint='') {
  const arr = getPath(S, path) || [];
  let chips = options.map(opt => {
    const val = typeof opt === 'string' ? opt : opt.v;
    const lbl = typeof opt === 'string' ? opt : opt.l;
    const sel = arr.includes(val) ? 'selected' : '';
    return `<span class="chip-opt ${sel}" data-chip-path="${path}" data-chip-val="${esc(val)}" onclick="toggleChip('${path}','${esc(val)}')">${esc(lbl)}</span>`;
  }).join('');
  // Auch custom Werte anzeigen die nicht in options sind
  const optValues = options.map(o => typeof o === 'string' ? o : o.v);
  arr.filter(v => !optValues.includes(v)).forEach(v => {
    chips += `<span class="chip-opt selected" data-chip-path="${path}" data-chip-val="${esc(v)}" onclick="toggleChip('${path}','${esc(v)}')">${esc(v)}</span>`;
  });
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="chip-grid" data-path="${path}">${chips}</div>
    ${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

function toggleChip(path, value) {
  mergeCurrentTabIntoS();
  const arr = getPath(S, path) || [];
  const idx = arr.indexOf(value);
  if (idx >= 0) arr.splice(idx, 1); else arr.push(value);
  setPath(S, path, arr);
  renderCurrentTab();
}

// Modell-Auswahl als Dropdown
function fModelSelect(path, label, hint='') {
  const v = getPath(S, path) ?? '';
  const models = [
    {v:'qwen3:4b', l:'Qwen3 4B (Schnell)'},
    {v:'qwen3:8b', l:'Qwen3 8B (Ausgewogen)'},
    {v:'qwen3:14b', l:'Qwen3 14B (Smart)'},
    {v:'qwen3:32b', l:'Qwen3 32B (Deep)'},
    {v:'llama3.2:3b', l:'Llama 3.2 3B'},
    {v:'llama3.1:8b', l:'Llama 3.1 8B'},
    {v:'gemma3:4b', l:'Gemma3 4B'},
    {v:'gemma3:12b', l:'Gemma3 12B'},
    {v:'gemma3:27b', l:'Gemma3 27B'},
    {v:'phi4:14b', l:'Phi4 14B'},
    {v:'mistral:7b', l:'Mistral 7B'},
    {v:'deepseek-r1:14b', l:'DeepSeek-R1 14B'},
    {v:'deepseek-r1:32b', l:'DeepSeek-R1 32B'},
  ];
  // Aktuellen Wert in Liste sicherstellen
  const hasVal = models.some(m => m.v === v);
  let h = `<div class="form-group"><label>${label}${helpBtn(path)}</label><select data-path="${path}">`;
  if (!hasVal && v) h += `<option value="${esc(v)}" selected>${esc(v)}</option>`;
  for (const m of models) h += `<option value="${m.v}" ${v===m.v?'selected':''}>${m.l}</option>`;
  return h + `</select>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

// Key-Value Mapping Editor (fuer Device-Mapping, DoA-Mapping etc.)
function fKeyValue(path, label, keyLabel='Schluessel', valLabel='Wert', hint='') {
  const obj = getPath(S, path) || {};
  const entries = Object.entries(obj);
  let rows = entries.map(([k,v], i) =>
    `<div class="kv-row" data-idx="${i}">
       <input type="text" class="kv-key" value="${esc(String(k))}" placeholder="${keyLabel}">
       <span class="kv-arrow">&#8594;</span>
       <input type="text" class="kv-val" value="${esc(String(v))}" placeholder="${valLabel}">
       <button class="kv-rm" onclick="kvRemove(this,'${path}')" title="Entfernen">&#10005;</button>
     </div>`
  ).join('');
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="kv-editor" data-path="${path}">
      ${rows}
      <button class="kv-add" onclick="kvAdd(this,'${path}','${keyLabel}','${valLabel}')">+ Zuordnung</button>
    </div>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}
function kvAdd(btn, path, keyLabel, valLabel) {
  const editor = btn.closest('.kv-editor');
  const row = document.createElement('div');
  row.className = 'kv-row';
  row.innerHTML = `<input type="text" class="kv-key" placeholder="${keyLabel}">
    <span class="kv-arrow">&#8594;</span>
    <input type="text" class="kv-val" placeholder="${valLabel}">
    <button class="kv-rm" onclick="kvRemove(this,'${path}')" title="Entfernen">&#10005;</button>`;
  editor.insertBefore(row, btn);
  kvSync(editor, path);
}
function kvRemove(btn, path) {
  const editor = btn.closest('.kv-editor');
  btn.closest('.kv-row').remove();
  kvSync(editor, path);
}
function kvSync(editor, path) {
  const obj = {};
  editor.querySelectorAll('.kv-row').forEach(row => {
    const k = row.querySelector('.kv-key').value.trim();
    const v = row.querySelector('.kv-val').value.trim();
    if (k) obj[k] = v;
  });
  setPath(S, path, obj);
}

// Info-Box
function fInfo(text) {
  return `<div class="info-box"><span class="info-icon">&#128161;</span>${text}</div>`;
}

function sectionWrap(icon, title, content) {
  return `<div class="s-section"><div class="s-section-hdr" onclick="toggleSec(this)">
    <h3>${icon} ${title}</h3><span class="arrow">&#9660;</span></div>
    <div class="s-section-body">${content}</div></div>`;
}

// ---- Entity-Picker Komponenten ----
// Cached entities (lazy loaded)
let _pickerEntities = null;
async function ensurePickerEntities() {
  if (_pickerEntities) return _pickerEntities;
  if (ALL_ENTITIES.length > 0) { _pickerEntities = ALL_ENTITIES; return _pickerEntities; }
  try {
    const d = await api('/api/ui/entities');
    _pickerEntities = d.entities || [];
    ALL_ENTITIES = _pickerEntities;
  } catch(e) { _pickerEntities = []; }
  return _pickerEntities;
}

// Entity-Picker: Auswahl von Entities als Tags (wie fKeywords, aber mit Dropdown)
function fEntityPicker(path, label, domains, hint='') {
  const arr = getPath(S, path) || [];
  const domStr = (domains||[]).join(',');
  let tags = arr.map(k => `<span class="kw-tag">${esc(k)}<span class="kw-rm" onclick="rmEntityPick(this,'${path}')">&#10005;</span></span>`).join('');
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="entity-pick-wrap">
      <div class="kw-editor" data-path="${path}" data-entity-picker="list" data-domains="${domStr}" onclick="this.querySelector('input')?.focus()">
        ${tags}<input class="kw-input entity-pick-input" placeholder="&#128269; Entity suchen..." oninput="entityPickFilter(this,'${domStr}')" onfocus="entityPickFilter(this,'${domStr}')" data-path="${path}">
      </div>
      <div class="entity-pick-dropdown" style="display:none;"></div>
    </div>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

// Entity-Picker Single: Auswahl einer einzelnen Entity mit Dropdown-Autocomplete
function fEntityPickerSingle(path, label, domains, hint='') {
  const v = getPath(S, path) || '';
  const domStr = (domains||[]).join(',');
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="entity-pick-wrap">
      <input class="form-input entity-pick-input" value="${esc(String(v))}"
        data-path="${path}" data-room-map="${path}" data-domains="${domStr}"
        placeholder="&#128269; Entity suchen..."
        oninput="entityPickFilter(this,'${domStr}')" onfocus="entityPickFilter(this,'${domStr}')"
        style="font-family:var(--mono);font-size:13px;">
      <div class="entity-pick-dropdown" style="display:none;"></div>
    </div>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

// Room-Entity-Map: Pro Raum eine Entity zuordnen (fuer Speaker, Motion Sensors)
function fRoomEntityMap(path, label, domains, hint='') {
  const map = getPath(S, path) || {};
  const domStr = (domains||[]).join(',');
  const rooms = _getKnownRooms();
  let rows = '';
  for (const room of rooms) {
    const val = map[room] || '';
    rows += `<div class="room-entity-row" style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
      <span style="min-width:120px;font-size:12px;font-weight:600;color:var(--text-secondary);">&#127968; ${esc(room)}</span>
      <div class="entity-pick-wrap" style="flex:1;">
        <input class="form-input entity-pick-input" value="${esc(val)}" placeholder="&#128269; Entity waehlen..."
          data-room-map="${path}" data-room-name="${esc(room)}" data-domains="${domStr}"
          oninput="entityPickFilter(this,'${domStr}')" onfocus="entityPickFilter(this,'${domStr}')"
          style="font-size:12px;font-family:var(--mono);padding:6px 10px;">
        <div class="entity-pick-dropdown" style="display:none;"></div>
      </div>
      ${val ? `<button class="btn btn-sm" style="padding:2px 6px;min-width:auto;font-size:11px;color:var(--danger);" onclick="this.parentElement.querySelector('input').value='';this.remove()">&#10005;</button>` : ''}
    </div>`;
  }
  // Manuelle Eintraege die nicht in rooms sind
  for (const [room, val] of Object.entries(map)) {
    if (!rooms.includes(room)) {
      rows += `<div class="room-entity-row" style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
        <span style="min-width:120px;font-size:12px;font-weight:600;color:var(--text-muted);">&#127968; ${esc(room)}</span>
        <input class="form-input" value="${esc(val)}" data-room-map="${path}" data-room-name="${esc(room)}"
          style="flex:1;font-size:12px;font-family:var(--mono);padding:6px 10px;">
      </div>`;
    }
  }
  if (rooms.length === 0 && Object.keys(map).length === 0) {
    rows = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Raeume bekannt. Raeume werden automatisch aus den MindHome-Geraeten erkannt.</div>';
  }
  return `<div class="form-group"><label>${label}</label>
    <div class="room-entity-map" data-path="${path}">${rows}</div>
    ${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

function _getKnownRooms() {
  // Raeume aus MindHome entities (wenn geladen)
  const rooms = new Set();
  if (_mhEntities && _mhEntities.rooms) {
    for (const r of Object.keys(_mhEntities.rooms)) rooms.add(r.toLowerCase());
  }
  // Raeume aus bestehenden room_speakers / room_motion_sensors
  const speakers = getPath(S, 'multi_room.room_speakers') || {};
  const motion = getPath(S, 'multi_room.room_motion_sensors') || {};
  if (typeof speakers === 'object') for (const r of Object.keys(speakers)) rooms.add(r.toLowerCase());
  if (typeof motion === 'object') for (const r of Object.keys(motion)) rooms.add(r.toLowerCase());
  return [...rooms].sort();
}

async function entityPickFilter(input, domStr) {
  const entities = await ensurePickerEntities();
  const domains = domStr ? domStr.split(',') : [];
  const search = input.value.toLowerCase();
  const wrap = input.closest('.entity-pick-wrap');
  const dropdown = wrap?.querySelector('.entity-pick-dropdown');
  if (!dropdown) return;

  let filtered = entities;
  if (domains.length > 0) filtered = filtered.filter(e => domains.includes(e.domain));
  if (search && !search.startsWith('media_player.') && !search.startsWith('binary_sensor.')) {
    filtered = filtered.filter(e => e.entity_id.toLowerCase().includes(search) || e.name.toLowerCase().includes(search));
  }
  const show = filtered.slice(0, 30);

  if (show.length === 0) {
    dropdown.style.display = 'none';
    return;
  }

  dropdown.innerHTML = show.map(e =>
    `<div class="entity-pick-item" onmousedown="entityPickSelect(this,'${esc(e.entity_id)}')">
      <span class="ename">${esc(e.name)}</span>
      <span class="eid">${esc(e.entity_id)}</span>
    </div>`
  ).join('');
  dropdown.style.display = 'block';

  // Schliessen bei Blur
  input.onblur = () => setTimeout(() => { dropdown.style.display = 'none'; }, 200);
}

function entityPickSelect(item, entityId) {
  const wrap = item.closest('.entity-pick-wrap');
  const input = wrap.querySelector('.entity-pick-input, input[data-room-map]');
  const dropdown = wrap.querySelector('.entity-pick-dropdown');
  if (dropdown) dropdown.style.display = 'none';

  // Room-Map Modus: Input-Wert setzen
  if (input?.dataset?.roomMap) {
    input.value = entityId;
    return;
  }

  // List Modus: Entity zu Array hinzufuegen
  const path = input?.dataset?.path;
  if (!path) return;
  mergeCurrentTabIntoS();
  const arr = getPath(S, path) || [];
  if (!arr.includes(entityId)) {
    arr.push(entityId);
    setPath(S, path, arr);
    renderCurrentTab();
  }
}

function rmEntityPick(el, path) {
  mergeCurrentTabIntoS();
  const tag = el.parentElement;
  const word = tag.textContent.replace('✕','').trim();
  const arr = (getPath(S, path) || []).filter(k => k !== word);
  setPath(S, path, arr);
  renderCurrentTab();
}

// Personen-Profile: Pro Haushaltsmitglied notify_service und preferred_room
function fPersonProfiles() {
  const profiles = getPath(S, 'person_profiles.profiles') || {};
  const members = getPath(S, 'household.members') || [];
  const primaryUser = getPath(S, 'household.primary_user') || '';
  // Alle bekannten Personen sammeln
  const persons = new Set();
  if (primaryUser) persons.add(primaryUser.toLowerCase());
  for (const m of members) { if (m.name) persons.add(m.name.toLowerCase()); }
  for (const p of Object.keys(profiles)) persons.add(p.toLowerCase());
  const rooms = _getKnownRooms();

  let rows = '';
  for (const person of [...persons].sort()) {
    const prof = profiles[person] || {};
    const notifySvc = prof.notify_service || '';
    const prefRoom = prof.preferred_room || '';
    const roomOpts = rooms.map(r => `<option value="${esc(r)}" ${prefRoom.toLowerCase()===r?'selected':''}>${esc(r)}</option>`).join('');
    rows += `<div style="padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);margin-bottom:8px;">
      <div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#128100; ${esc(person)}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <div>
          <label style="font-size:11px;color:var(--text-muted);">Benachrichtigung</label>
          <div class="entity-pick-wrap">
            <input class="form-input entity-pick-input" value="${esc(notifySvc)}" placeholder="&#128269; notify.mobile..."
              data-person-profile="${esc(person)}" data-profile-field="notify_service" data-domains="notify"
              oninput="entityPickFilter(this,'notify')" onfocus="entityPickFilter(this,'notify')"
              style="font-size:11px;font-family:var(--mono);padding:5px 8px;width:100%;box-sizing:border-box;">
            <div class="entity-pick-dropdown" style="display:none;"></div>
          </div>
        </div>
        <div>
          <label style="font-size:11px;color:var(--text-muted);">Bevorzugter Raum</label>
          <select data-person-profile="${esc(person)}" data-profile-field="preferred_room"
            style="font-size:11px;padding:5px 8px;width:100%;box-sizing:border-box;">
            <option value="">-- Kein Raum --</option>${roomOpts}
          </select>
        </div>
      </div>
    </div>`;
  }
  if (persons.size === 0) {
    rows = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Personen konfiguriert. Zuerst unter "Personen" Haushaltsmitglieder anlegen.</div>';
  }
  return `<div class="person-profiles-container">${rows}</div>`;
}

// Personen-Anrede: Pro Person eine Anrede zuordnen
function fPersonTitles() {
  const titles = getPath(S, 'persons.titles') || {};
  const members = getPath(S, 'household.members') || [];
  const primaryUser = getPath(S, 'household.primary_user') || '';
  const persons = new Set();
  if (primaryUser) persons.add(primaryUser.toLowerCase());
  for (const m of members) { if (m.name) persons.add(m.name.toLowerCase()); }
  for (const p of Object.keys(titles)) persons.add(p.toLowerCase());

  let rows = '';
  for (const person of [...persons].sort()) {
    const title = (typeof titles === 'object' ? titles[person] : '') || '';
    rows += `<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
      <span style="min-width:120px;font-size:12px;font-weight:600;color:var(--text-secondary);">&#128100; ${esc(person)}</span>
      <input class="form-input" value="${esc(title)}" placeholder="z.B. Sir, Frau Mueller..."
        data-person-title="${esc(person)}"
        style="flex:1;font-size:12px;padding:6px 10px;">
    </div>`;
  }
  if (persons.size === 0) {
    rows = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Personen konfiguriert. Zuerst unter "Personen" Haushaltsmitglieder anlegen.</div>';
  }
  return `<div class="person-titles-container">${rows}</div>`;
}

function updRange(el) {
  const path = el.dataset.path;
  document.getElementById('rv_'+path.replace(/\./g,'_')).textContent = el.value;
}
function toggleSec(hdr) { hdr.classList.toggle('open'); hdr.nextElementSibling.classList.toggle('open'); }

function addKw(e, input, path) {
  if (e.key !== 'Enter' || !input.value.trim()) return;
  e.preventDefault();
  mergeCurrentTabIntoS();
  const arr = getPath(S, path) || [];
  const val = input.value.trim();
  if (!arr.includes(val)) {
    arr.push(val);
    setPath(S, path, arr);
    renderCurrentTab();
  }
}
function rmKw(el, path) {
  mergeCurrentTabIntoS();
  const tag = el.parentElement;
  const word = tag.textContent.replace('✕','').trim();
  const arr = (getPath(S, path) || []).filter(k => k !== word);
  setPath(S, path, arr);
  renderCurrentTab();
}

function bindFormEvents() {
  // no-op: we collect on save
}

async function loadRoomTempAverage() {
  const el = document.getElementById('roomTempAverage');
  if (!el) return;
  try {
    const d = await api('/api/ui/room-temperature');
    if (!d || !d.sensors || d.sensors.length === 0) {
      el.innerHTML = '<div style="padding:8px 12px;background:var(--bg-tertiary);border-radius:8px;font-size:12px;color:var(--text-muted);">' +
        '&#128161; Noch keine Sensoren konfiguriert. Jarvis nutzt aktuell die Temperatur der Heizung/Klimaanlage.</div>';
      return;
    }
    let rows = d.sensors.map(s =>
      '<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;">' +
        '<span style="font-size:12px;">' + esc(s.name) + ' <span style="color:var(--text-muted);font-size:11px;">(' + esc(s.entity_id) + ')</span></span>' +
        '<span style="font-weight:600;color:' + (s.available ? 'var(--accent)' : 'var(--danger)') + ';">' +
          (s.value != null ? s.value + '\u00b0C' : 'n/v') +
        '</span>' +
      '</div>'
    ).join('');
    const avgHtml = d.average != null
      ? '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid var(--border);margin-top:4px;font-weight:700;">' +
          '<span>&#127777; Mittelwert (wird Jarvis gemeldet)</span>' +
          '<span style="font-size:18px;color:var(--accent);">' + d.average + '\u00b0C</span>' +
        '</div>'
      : '';
    el.innerHTML = '<div style="padding:10px 14px;background:var(--bg-tertiary);border-radius:8px;margin-top:4px;">' +
      '<div style="font-size:12px;font-weight:600;margin-bottom:6px;">Aktuelle Sensorwerte</div>' +
      rows + avgHtml + '</div>';
  } catch(e) {
    el.innerHTML = '';
  }
}

// ---- Tab 1: Allgemein ----
function renderGeneral() {
  return sectionWrap('&#9881;', 'Assistent',
    fInfo('Grundeinstellungen fuer deinen Assistenten — Name, Sprache und Version.') +
    fText('assistant.name', 'Name', 'So stellt sich der Assistent vor') +
    fText('assistant.version', 'Version', '', true) +
    fSelect('assistant.language', 'Sprache', [{v:'de',l:'Deutsch'},{v:'en',l:'English'}])
  ) +
  sectionWrap('&#9889;', 'Autonomie',
    fInfo('Wie selbststaendig darf der Assistent handeln? Je hoeher, desto mehr macht er eigenstaendig.') +
    fRange('autonomy.level', 'Autonomie-Level', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'})
  ) +
  sectionWrap('&#129302;', 'Modell-Routing',
    fInfo('Welche KI-Modelle sollen fuer welche Aufgaben genutzt werden? Deaktivierte Modelle werden uebersprungen — Fallback auf das naechstkleinere.') +
    fToggle('models.enabled.fast', 'Fast — Einfache Befehle (Licht an, Timer, etc.)') +
    fToggle('models.enabled.smart', 'Smart — Konversation & Standardanfragen') +
    fToggle('models.enabled.deep', 'Deep — Komplexe Analyse & Planung') +
    fModelSelect('models.fast', 'Fast-Modell', 'Fuer schnelle, einfache Befehle') +
    fModelSelect('models.smart', 'Smart-Modell', 'Fuer normale Gespraeche') +
    fModelSelect('models.deep', 'Deep-Modell', 'Fuer komplexe Aufgaben') +
    fRange('models.deep_min_words', 'Deep ab Woertern', 5, 50, 1, {5:'5',10:'10',15:'15',20:'20',25:'25',30:'30',35:'35',40:'40',45:'45',50:'50'}) +
    fRange('models.options.temperature', 'Kreativitaet (Temperatur)', 0, 2, 0.1, {0:'Exakt',0.5:'Konservativ',0.7:'Standard',1:'Kreativ',1.5:'Sehr kreativ',2:'Maximum'}) +
    fRange('models.options.max_tokens', 'Antwortlaenge (Max Tokens)', 64, 4096, 64)
  ) +
  sectionWrap('&#127991;', 'Schnell-Erkennung',
    fInfo('Klicke auf Woerter, die das jeweilige Modell ausloesen sollen. Ausgewaehlte Woerter sind hervorgehoben.') +
    fChipSelect('models.fast_keywords', 'Fast-Keywords — Woerter fuer schnelle Antworten', [
      'licht','lampe','an','aus','timer','stopp','danke','ja','nein','ok','stop',
      'wecker','alarm','pause','weiter','leiser','lauter','heller','dunkler',
      'rolladen','hoch','runter','temperatur','heizung','musik'
    ]) +
    fChipSelect('models.deep_keywords', 'Deep-Keywords — Woerter fuer ausfuehrliche Analyse', [
      'warum','erklaere','vergleiche','analysiere','plane','zusammenfassung',
      'recherchiere','berechne','strategie','vor- und nachteile','unterschied',
      'optimiere','hilf mir bei','was meinst du','ueberblick'
    ]) +
    fChipSelect('models.cooking_keywords', 'Koch-Keywords — Woerter die den Koch-Modus aktivieren', [
      'rezept','kochen','backen','zubereiten','gericht','essen','zutaten',
      'portion','mahlzeit','fruehstueck','mittagessen','abendessen','snack',
      'dessert','kuchen','suppe','salat','pizza','pasta','sauce'
    ])
  ) +
  sectionWrap('&#128269;', 'Web-Suche',
    fInfo('Optionale Web-Recherche fuer Wissensfragen. Privacy-First: SearXNG (self-hosted) oder DuckDuckGo. Standardmaessig deaktiviert.') +
    fToggle('web_search.enabled', 'Web-Suche aktivieren') +
    fSelect('web_search.engine', 'Suchmaschine', [{v:'searxng',l:'SearXNG (self-hosted)'},{v:'duckduckgo',l:'DuckDuckGo'}]) +
    fText('web_search.searxng_url', 'SearXNG URL', 'Nur relevant wenn SearXNG als Engine gewaehlt') +
    fNum('web_search.max_results', 'Max. Ergebnisse', 1, 20, 1) +
    fNum('web_search.timeout_seconds', 'Timeout (Sekunden)', 3, 30, 1)
  ) +
  sectionWrap('&#128274;', 'Dashboard & PIN',
    fInfo('Der Zugang zum Dashboard ist mit einer PIN geschuetzt. Der Recovery-Key wird benoetigt wenn du die PIN vergisst.') +
    '<div class="form-group"><label>PIN-Schutz</label>' +
    '<p style="font-size:12px;color:var(--success);margin-bottom:8px;">PIN ist gesetzt und aktiv</p>' +
    '<p style="font-size:11px;color:var(--text-muted);margin-bottom:12px;">PIN aendern: "PIN vergessen?" auf dem Login-Screen nutzen.</p></div>' +
    '<div class="form-group"><label>Recovery-Key</label>' +
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">Falls du deine PIN vergisst, brauchst du diesen Key zum Zuruecksetzen. Sicher aufbewahren!</p>' +
    '<div style="display:flex;gap:8px;align-items:center;">' +
    '<input type="text" id="recoveryKeyDisplay" readonly style="flex:1;font-family:var(--mono);font-size:14px;letter-spacing:2px;text-align:center;" value="Versteckt — Klicke Generieren" />' +
    '<button class="btn btn-primary" onclick="regenerateRecoveryKey()" style="white-space:nowrap;">Neu generieren</button>' +
    '</div>' +
    '<p style="font-size:11px;color:var(--danger);margin-top:6px;">Nach dem Generieren wird der Key nur EINMAL angezeigt. Notiere ihn sofort!</p>' +
    '</div>'
  );
}

// ---- Tab: Personen & Haushalt ----
function renderPersons() {
  const members = getPath(S, 'household.members') || [];
  const primaryUser = getPath(S, 'household.primary_user') || '';

  const roleInfo = {
    owner: {icon:'&#128081;', color:'var(--accent)', desc:'Voller Zugriff inkl. Sicherheit'},
    member: {icon:'&#128100;', color:'var(--blue)', desc:'Alles ausser Sicherheit'},
    guest: {icon:'&#128587;', color:'var(--text-muted)', desc:'Nur Licht, Klima, Medien'}
  };

  let memberRows = '';
  members.forEach((m, i) => {
    const ri = roleInfo[m.role] || roleInfo.member;
    memberRows += `<div class="person-row" style="display:flex;gap:10px;align-items:center;margin-bottom:10px;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-sm);border-left:3px solid ${ri.color};">
      <span style="font-size:20px;">${ri.icon}</span>
      <input type="text" value="${esc(m.name || '')}" data-member-idx="${i}" data-member-field="name"
        placeholder="Name eingeben..." style="flex:1;font-size:14px;">
      <select data-member-idx="${i}" data-member-field="role" style="width:160px;" onchange="updateMemberRoleVisual(this)">
        <option value="owner" ${m.role==='owner'?'selected':''}>&#128081; Hausherr/in</option>
        <option value="member" ${m.role==='member'?'selected':''}>&#128100; Mitbewohner/in</option>
        <option value="guest" ${m.role==='guest'?'selected':''}>&#128587; Gast</option>
      </select>
      <button class="btn btn-danger btn-sm" onclick="removeHouseholdMember(${i})"
        style="padding:6px 10px;min-width:auto;" title="Entfernen">&#128465;</button>
    </div>`;
  });

  return sectionWrap('&#128100;', 'Hauptbenutzer',
    fInfo('Dein Name — so kennt und begruesst dich der Assistent.') +
    '<div class="form-group"><label>Dein Name</label>' +
    '<input type="text" data-path="household.primary_user" value="' + esc(primaryUser) + '" placeholder="z.B. Alex" style="font-size:15px;">' +
    '</div>'
  ) +
  sectionWrap('&#128106;', 'Haushaltsmitglieder',
    fInfo('Alle Personen im Haushalt. Die Rolle bestimmt was jeder steuern darf.') +
    '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px;">' +
    '<div style="padding:8px 12px;background:var(--accent-dim);border-radius:6px;font-size:11px;text-align:center;"><b>&#128081; Hausherr/in</b><br>Voller Zugriff</div>' +
    '<div style="padding:8px 12px;background:var(--blue-dim);border-radius:6px;font-size:11px;text-align:center;"><b>&#128100; Mitbewohner/in</b><br>Alles ausser Sicherheit</div>' +
    '<div style="padding:8px 12px;background:rgba(255,255,255,0.05);border-radius:6px;font-size:11px;text-align:center;"><b>&#128587; Gast</b><br>Nur Licht, Klima, Medien</div>' +
    '</div>' +
    '<div id="householdMembers">' + memberRows + '</div>' +
    '<button class="btn btn-secondary" onclick="addHouseholdMember()" style="margin-top:8px;width:100%;justify-content:center;">+ Person hinzufuegen</button>'
  ) +
  sectionWrap('&#128101;', 'Personen-Anrede',
    fInfo('Wie soll der Assistent einzelne Personen ansprechen? Der Hauptbenutzer wird standardmaessig als "Sir" angesprochen.') +
    fPersonTitles()
  );
}

function addHouseholdMember() {
  mergeCurrentTabIntoS();
  const members = getPath(S, 'household.members') || [];
  members.push({name: '', role: 'member'});
  setPath(S, 'household.members', members);
  renderCurrentTab();
}

function removeHouseholdMember(idx) {
  mergeCurrentTabIntoS();
  const members = getPath(S, 'household.members') || [];
  members.splice(idx, 1);
  setPath(S, 'household.members', members);
  renderCurrentTab();
}

function updateMemberRoleVisual(selectEl) {
  // Nur Icon + Farbe updaten, KEIN Re-Render (verhindert Select-Reset)
  const roleColors = {owner:'var(--accent)', member:'var(--blue)', guest:'var(--text-muted)'};
  const roleIcons = {owner:'\u{1F451}', member:'\u{1F464}', guest:'\u{1F64B}'};
  const role = selectEl.value;
  const row = selectEl.closest('.person-row');
  if (row) {
    row.style.borderLeftColor = roleColors[role] || roleColors.member;
    const icon = row.querySelector('span');
    if (icon) icon.textContent = roleIcons[role] || roleIcons.member;
  }
  // State aktualisieren ohne Re-Render
  const idx = parseInt(selectEl.dataset.memberIdx, 10);
  const members = getPath(S, 'household.members') || [];
  if (members[idx]) members[idx].role = role;
}

function collectHouseholdMembers() {
  const members = [];
  document.querySelectorAll('#householdMembers .person-row').forEach(row => {
    const nameEl = row.querySelector('[data-member-field="name"]');
    const roleEl = row.querySelector('[data-member-field="role"]');
    if (nameEl && roleEl && nameEl.value.trim()) {
      members.push({name: nameEl.value.trim(), role: roleEl.value});
    }
  });
  return members;
}

// ---- Tab 2: Persoenlichkeit ----
function renderPersonality() {
  const styleOpts = [
    {v:'minimal',l:'Minimal — Kurz und praezise'},
    {v:'verschlafen',l:'Verschlafen — Ruhig, wenig Worte'},
    {v:'knapp',l:'Knapp — Auf den Punkt'},
    {v:'freundlich',l:'Freundlich — Warm und einladend'},
    {v:'butler',l:'Butler — Formell und elegant'},
    {v:'entspannt',l:'Entspannt — Locker und gemuetlich'},
    {v:'sachlich',l:'Sachlich — Neutral und informativ'},
    {v:'warm',l:'Warm — Herzlich und persoenlich'},
    {v:'muede',l:'Muede — Kurz, leise, sanft'}
  ];
  return sectionWrap('&#127917;', 'Stil & Charakter',
    fInfo('Wie soll sich der Assistent verhalten? Stil, Humor und Meinungsfreude einstellen.') +
    fSelect('personality.style', 'Grundstil', styleOpts) +
    fRange('personality.sarcasm_level', 'Sarkasmus-Level', 1, 5, 1, {1:'Sachlich',2:'Gelegentl. trocken',3:'Standard Butler',4:'Haeufig',5:'Vollgas Ironie'}) +
    fRange('personality.opinion_intensity', 'Meinungs-Intensitaet', 0, 3, 1, {0:'Still',1:'Selten',2:'Gelegentlich',3:'Redselig'}) +
    fToggle('personality.self_irony_enabled', 'Selbstironie aktiviert') +
    fRange('personality.self_irony_max_per_day', 'Max. Selbstironie pro Tag', 0, 20, 1)
  ) +
  sectionWrap('&#128200;', 'Charakter-Entwicklung',
    fInfo('Der Assistent wird mit der Zeit weniger formell — wie ein echter Butler, der seinen Herrn kennenlernt.') +
    fToggle('personality.character_evolution', 'Charakter entwickelt sich ueber Zeit') +
    fRange('personality.formality_start', 'Formalitaet am Anfang', 0, 100, 5, {0:'Sehr locker',25:'Locker',50:'Normal',75:'Formell',100:'Sehr formell'}) +
    fRange('personality.formality_min', 'Minimale Formalitaet', 0, 100, 5, {0:'Sehr locker',25:'Locker',50:'Normal',75:'Formell',100:'Sehr formell'}) +
    fRange('personality.formality_decay_per_day', 'Abbau pro Tag', 0, 5, 0.1)
  ) +
  sectionWrap('&#128336;', 'Tageszeit-Stile',
    fInfo('Der Assistent passt seinen Stil je nach Tageszeit an. Waehle fuer jede Zeit einen passenden Stil und maximale Satzlaenge.') +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127749; Fruehmorgens (05:00 - 08:00)</div>' +
    fSelect('personality.time_layers.early_morning.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.early_morning.max_sentences', 'Max. Saetze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#9728; Morgens (08:00 - 12:00)</div>' +
    fSelect('personality.time_layers.morning.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.morning.max_sentences', 'Max. Saetze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127774; Nachmittags (12:00 - 18:00)</div>' +
    fSelect('personality.time_layers.afternoon.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.afternoon.max_sentences', 'Max. Saetze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127751; Abends (18:00 - 22:00)</div>' +
    fSelect('personality.time_layers.evening.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.evening.max_sentences', 'Max. Saetze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127769; Nachts (22:00 - 05:00)</div>' +
    fSelect('personality.time_layers.night.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.night.max_sentences', 'Max. Saetze', 1, 10, 1) +
    '</div>'
  ) +
  sectionWrap('&#128683;', 'Antwort-Filter',
    fInfo('Unerwuenschte Phrasen aus den Antworten filtern und maximale Antwortlaenge begrenzen.') +
    fToggle('response_filter.enabled', 'Antwort-Filter aktiv') +
    fRange('response_filter.max_response_sentences', 'Max. Saetze pro Antwort', 0, 20, 1, {0:'Kein Limit',1:'1',2:'2',3:'3',5:'5',10:'10',20:'20'}) +
    fChipSelect('response_filter.banned_phrases', 'Verbotene Phrasen', [
      'als KI','als Sprachmodell','ich bin ein KI','ich habe keine Gefuehle',
      'ich bin nur eine Maschine','als AI','language model','ich kann nicht fuehlen',
      'ich bin kein Mensch','mein Training','meine Trainingsdaten'
    ]) +
    fChipSelect('response_filter.banned_starters', 'Verbotene Satzanfaenge', [
      'Natuerlich!','Selbstverstaendlich!','Klar!','Gerne!',
      'Absolut!','Definitiv!','Auf jeden Fall!','Sicher!',
      'Das ist eine gute Frage','Ich verstehe'
    ])
  );
}

// ---- Tab 3: Gedaechtnis ----
function renderMemory() {
  return sectionWrap('&#128065;', 'Semantisches Gedaechtnis',
    fInfo('Der Assistent merkt sich Fakten aus Gespraechen — z.B. "Du trinkst gern Kaffee". Hier steuerst du, wie das funktioniert.') +
    fToggle('memory.extraction_enabled', 'Fakten automatisch aus Gespraechen lernen') +
    fRange('memory.extraction_min_words', 'Min. Nachrichtenlaenge fuer Extraktion', 1, 20, 1) +
    fModelSelect('memory.extraction_model', 'Modell fuer Fakten-Extraktion') +
    fRange('memory.extraction_temperature', 'Extraktions-Genauigkeit', 0, 1, 0.1, {0:'Sehr exakt',0.1:'Exakt',0.3:'Normal',0.5:'Flexibel',0.7:'Kreativ',1:'Sehr kreativ'}) +
    fRange('memory.extraction_max_tokens', 'Max. Antwortlaenge Extraktion', 64, 2048, 64) +
    fRange('memory.max_person_facts_in_context', 'Personen-Fakten im Gespraech', 1, 20, 1) +
    fRange('memory.max_relevant_facts_in_context', 'Relevante Fakten im Gespraech', 1, 10, 1) +
    fRange('memory.min_confidence_for_context', 'Min. Sicherheit fuer Nutzung', 0, 1, 0.05, {0:'Alles nutzen',0.3:'Niedrig',0.5:'Mittel',0.6:'Standard',0.8:'Hoch',1:'Nur sichere'}) +
    fRange('memory.duplicate_threshold', 'Duplikat-Erkennung', 0, 1, 0.05, {0:'Streng',0.5:'Mittel',0.8:'Locker',1:'Aus'}) +
    fRange('memory.episode_min_words', 'Min. Woerter fuer Episode', 1, 20, 1) +
    fRange('memory.default_confidence', 'Standard-Sicherheit neuer Fakten', 0, 1, 0.05)
  ) +
  sectionWrap('&#128218;', 'Wissensdatenbank (RAG)',
    fInfo('Eigene Dokumente als Wissensquelle. Dateien in config/knowledge/ werden automatisch eingelesen.') +
    fToggle('knowledge_base.enabled', 'Wissensdatenbank aktiv') +
    fToggle('knowledge_base.auto_ingest', 'Automatisch beim Start einlesen') +
    fRange('knowledge_base.chunk_size', 'Textblock-Groesse', 100, 2000, 50, {100:'Klein (100)',300:'Mittel (300)',500:'Standard (500)',1000:'Gross (1000)',2000:'Sehr gross (2000)'}) +
    fRange('knowledge_base.chunk_overlap', 'Ueberlappung zwischen Bloecken', 0, 500, 25) +
    fRange('knowledge_base.max_distance', 'Suchgenauigkeit', 0.5, 2, 0.1, {0.5:'Sehr genau',1:'Standard',1.5:'Breit',2:'Sehr breit'}) +
    fRange('knowledge_base.search_limit', 'Max. Treffer pro Suche', 1, 10, 1) +
    fSelect('knowledge_base.embedding_model', 'Embedding-Modell', [
      {v:'paraphrase-multilingual-MiniLM-L12-v2', l:'Multilingual MiniLM (empfohlen fuer Deutsch)'},
      {v:'all-MiniLM-L6-v2', l:'English MiniLM (ChromaDB Default)'},
      {v:'distiluse-base-multilingual-cased-v2', l:'Multilingual DistilUSE'},
      {v:'paraphrase-multilingual-mpnet-base-v2', l:'Multilingual MPNet (groesser, genauer)'},
    ]) +
    fInfo('Nach Modellwechsel: Wissen-Seite → "Rebuild" klicken, damit alle Vektoren neu berechnet werden.') +
    fChipSelect('knowledge_base.supported_extensions', 'Unterstuetzte Dateitypen', [
      '.txt','.md','.pdf','.csv','.json','.yaml','.yml','.xml','.html','.log','.doc','.docx'
    ], 'Welche Dateitypen sollen eingelesen werden?')
  ) +
  sectionWrap('&#128221;', 'Korrektur-Lernen',
    fInfo('Wenn du den Assistenten korrigierst, merkt er sich das. Wie sicher soll er sich bei Korrekturen sein?') +
    fRange('correction.confidence', 'Sicherheit bei Korrekturen', 0, 1, 0.05, {0:'Unsicher',0.5:'Mittel',0.8:'Sicher',0.95:'Sehr sicher',1:'Absolut sicher'}) +
    fModelSelect('correction.model', 'Modell fuer Korrektur-Analyse') +
    fRange('correction.temperature', 'Analyse-Kreativitaet', 0, 1, 0.1, {0:'Exakt',0.3:'Normal',0.5:'Flexibel',1:'Kreativ'})
  ) +
  sectionWrap('&#128197;', 'Tages-Zusammenfassung',
    fInfo('Automatische Zusammenfassungen des Tages, der Woche und des Monats.') +
    fRange('summarizer.run_hour', 'Uhrzeit (Stunde)', 0, 23, 1) +
    fRange('summarizer.run_minute', 'Uhrzeit (Minute)', 0, 59, 1) +
    fModelSelect('summarizer.model', 'Zusammenfassungs-Modell') +
    fRange('summarizer.max_tokens_daily', 'Laenge taeglich', 128, 2048, 64) +
    fRange('summarizer.max_tokens_weekly', 'Laenge woechentlich', 128, 2048, 64) +
    fRange('summarizer.max_tokens_monthly', 'Laenge monatlich', 128, 2048, 64)
  ) +
  sectionWrap('&#128172;', 'Kontext',
    fInfo('Wie viel Gespraechsverlauf soll der Assistent bei jeder Antwort beruecksichtigen?') +
    fRange('context.recent_conversations', 'Letzte Gespraeche merken', 1, 20, 1) +
    fRange('context.api_timeout', 'HA-API Timeout (Sek.)', 1, 30, 1) +
    fRange('context.llm_timeout', 'LLM Timeout (Sek.)', 15, 120, 5, {15:'15s',30:'30s',45:'45s',60:'60s',90:'90s',120:'2 Min'})
  );
}

// ---- Tab 4: Stimmung ----
function renderMood() {
  return sectionWrap('&#128578;', 'Stimmungserkennung',
    fInfo('Der Assistent erkennt deine Stimmung anhand von Worten und Sprechgeschwindigkeit und passt seine Antworten an.') +
    fRange('mood.rapid_command_seconds', 'Schnelle Befehle erkennen (Sek.)', 1, 30, 1, {1:'1s',5:'5s',10:'10s',15:'15s',30:'30s'}) +
    fRange('mood.stress_decay_seconds', 'Stress-Abbau nach (Sek.)', 60, 600, 30, {60:'1 Min',120:'2 Min',180:'3 Min',300:'5 Min',600:'10 Min'}) +
    fRange('mood.frustration_threshold', 'Frustrations-Schwelle', 1, 10, 1, {1:'Empfindlich',3:'Normal',5:'Geduldig',7:'Sehr geduldig',10:'Ignorieren'}) +
    fRange('mood.tired_hour_start', 'Muede ab Uhrzeit', 0, 23, 1) +
    fRange('mood.tired_hour_end', 'Muede bis Uhrzeit', 0, 23, 1)
  ) +
  sectionWrap('&#9889;', 'Stress-Einfluss',
    fInfo('Wie stark beeinflussen verschiedene Signale den erkannten Stresslevel?') +
    fRange('mood.rapid_command_stress_boost', 'Schnelle Befehle hintereinander', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.positive_stress_reduction', 'Positive Worte reduzieren Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.negative_stress_boost', 'Negative Worte erhoehen Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.impatient_stress_boost', 'Ungeduld erhoeht Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.tired_boost', 'Muedigkeit erhoeht Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.repetition_stress_boost', 'Wiederholungen erhoehen Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'})
  ) +
  sectionWrap('&#128172;', 'Stimmungs-Erkennung — Woerter',
    fInfo('Klicke auf Woerter, die der Assistent als Stimmungssignal erkennen soll.') +
    fChipSelect('mood.positive_keywords', 'Positive Stimmung', [
      'danke','super','toll','perfekt','genau','klasse','wunderbar','prima',
      'cool','nice','geil','mega','hammer','top','gut gemacht','bravo',
      'lieb','freut mich','ausgezeichnet','fantastisch','herrlich'
    ]) +
    fChipSelect('mood.negative_keywords', 'Negative Stimmung', [
      'mist','scheisse','nein','falsch','schlecht','nervig','bloed',
      'egal','vergiss es','lass','stopp','aufhoeren','genug',
      'katastrophe','furchtbar','schrecklich','idiot','dumm'
    ]) +
    fChipSelect('mood.impatient_keywords', 'Ungeduld', [
      'schnell','sofort','jetzt','beeil dich','mach schon','hurry',
      'los','tempo','endlich','wird das noch','wie lange noch',
      'komm schon','beeilung','dalli','zack zack'
    ]) +
    fChipSelect('mood.tired_keywords', 'Muedigkeit', [
      'muede','schlafen','gute nacht','schlaf','bett','gaehnen',
      'erschoepft','fertig','kaputt','ausgelaugt','matt',
      'pennen','heia','einschlafen','nachts'
    ])
  ) +
  sectionWrap('&#127908;', 'Stimm-Analyse',
    fInfo('Der Assistent erkennt anhand deiner Sprechgeschwindigkeit ob du gestresst, muede oder entspannt bist.') +
    fToggle('voice_analysis.enabled', 'Stimm-Analyse aktiv') +
    fRange('voice_analysis.wpm_fast', 'Schnelles Sprechen ab (WPM)', 100, 300, 10, {100:'100',150:'150',180:'180',200:'200',250:'250',300:'300'}) +
    fRange('voice_analysis.wpm_slow', 'Langsames Sprechen unter (WPM)', 30, 150, 10, {30:'30',60:'60',80:'80',100:'100',120:'120',150:'150'}) +
    fRange('voice_analysis.wpm_normal', 'Normales Sprechtempo (WPM)', 50, 200, 10, {50:'50',80:'80',100:'100',120:'120',150:'150',200:'200'}) +
    fToggle('voice_analysis.use_whisper_metadata', 'Whisper-Metadaten nutzen') +
    fRange('voice_analysis.voice_weight', 'Stimm-Gewichtung', 0, 1, 0.05, {0:'Ignorieren',0.25:'Schwach',0.5:'Mittel',0.75:'Stark',1:'Voll'})
  );
}

// ---- Tab 5: Raeume ----
function renderRooms() {
  const hMode = getPath(S, 'heating.mode') || 'room_thermostat';
  const isCurve = hMode === 'heating_curve';

  return sectionWrap('&#128293;', 'Heizung',
    fInfo('Wie wird geheizt? Einzelraumregelung = jeder Raum hat eigenen Thermostat. Heizkurve = zentrale Waermepumpe mit Offset-Steuerung.') +
    '<div class="form-group"><label>Heizungsmodus</label>' +
    '<select data-path="heating.mode" onchange="mergeCurrentTabIntoS();setPath(S,\'heating.mode\',this.value);renderCurrentTab();">' +
    '<option value="room_thermostat" ' + (hMode==='room_thermostat'?'selected':'') + '>Raumthermostate (Einzelraumregelung)</option>' +
    '<option value="heating_curve" ' + (hMode==='heating_curve'?'selected':'') + '>Heizkurve (Waermepumpe, Vorlauf-Offset)</option>' +
    '</select></div>' +
    (isCurve ?
      fText('heating.curve_entity', 'Heizungs-Entity', 'z.B. climate.panasonic_heat_pump_main_z1_temp') +
      fRange('heating.curve_offset_min', 'Min. Offset (°C)', -10, 0, 0.5) +
      fRange('heating.curve_offset_max', 'Max. Offset (°C)', 0, 10, 0.5) +
      fRange('heating.night_offset', 'Nacht-Offset (°C)', -10, 0, 0.5) +
      fRange('heating.away_offset', 'Abwesenheits-Offset (°C)', -10, 0, 0.5)
    :
      '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">Jeder Raum hat seinen eigenen Thermostat. Temperatur-Grenzen findest du unter Sicherheit.</p>'
    )
  ) +
  sectionWrap('&#127777;', 'Raumtemperatur-Sensoren',
    fInfo('Welche Temperatursensoren sollen fuer die Raumtemperatur verwendet werden? Jarvis berechnet den Mittelwert aller Sensoren. Ohne Sensoren wird die Temperatur der Klimaanlage/Heizung genutzt.') +
    fEntityPicker('room_temperature.sensors', 'Temperatursensoren', ['sensor'], 'Nur sensor.*-Entities mit Temperaturwerten. z.B. sensor.temperatur_wohnzimmer') +
    '<div id="roomTempAverage" style="margin-top:8px;"></div>'
  ) +
  sectionWrap('&#127968;', 'Multi-Room',
    fInfo('Der Assistent erkennt in welchem Raum du bist und antwortet dort. Praesenz-Timeout = wie lange er dich in einem Raum "merkt".') +
    fToggle('multi_room.enabled', 'Multi-Room Erkennung aktiv') +
    fRange('multi_room.presence_timeout_minutes', 'Praesenz-Timeout', 1, 60, 1, {1:'1 Min',5:'5 Min',10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fToggle('multi_room.auto_follow', 'Musik folgt automatisch in neuen Raum')
  ) +
  sectionWrap('&#128266;', 'Raum-Speaker',
    fInfo('Welcher Lautsprecher gehoert zu welchem Raum? Raeume werden automatisch aus MindHome erkannt.') +
    fRoomEntityMap('multi_room.room_speakers', 'Speaker-Zuordnung', ['media_player'])
  ) +
  sectionWrap('&#128694;', 'Raum-Bewegungsmelder',
    fInfo('Welcher Bewegungsmelder gehoert zu welchem Raum? Damit weiss der Assistent wo du bist.') +
    fRoomEntityMap('multi_room.room_motion_sensors', 'Bewegungsmelder-Zuordnung', ['binary_sensor'])
  ) +
  sectionWrap('&#127916;', 'Aktivitaets-Sensoren',
    fInfo('Welche Home Assistant Entities sollen fuer die Aktivitaetserkennung genutzt werden? Tippe um zu suchen.') +
    fEntityPicker('activity.entities.media_players', 'Media Player', ['media_player']) +
    fEntityPicker('activity.entities.mic_sensors', 'Mikrofon-Sensoren', ['binary_sensor','sensor']) +
    fEntityPicker('activity.entities.bed_sensors', 'Bett-Sensoren (Schlaf-Erkennung)', ['binary_sensor','sensor']) +
    fEntityPicker('activity.entities.pc_sensors', 'PC-Sensoren (Arbeit-Erkennung)', ['binary_sensor','sensor'])
  ) +
  sectionWrap('&#9200;', 'Aktivitaets-Zeiten',
    fInfo('Wann ist Nacht? Ab wann zaehlt Besuch? Wie lange muss Fokus dauern?') +
    fRange('activity.thresholds.night_start', 'Nacht beginnt um', 0, 23, 1) +
    fRange('activity.thresholds.night_end', 'Nacht endet um', 0, 23, 1) +
    fRange('activity.thresholds.guest_person_count', 'Besuch ab Personen', 1, 10, 1) +
    fRange('activity.thresholds.focus_min_minutes', 'Fokus-Modus ab Minuten', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'})
  ) +
  sectionWrap('&#128101;', 'Personen-Profile',
    fInfo('Erweiterte Einstellungen pro Person — Benachrichtigungs-Service und bevorzugter Raum.') +
    fPersonProfiles()
  );
}

// ---- Tab 6: Stimme ----
function renderVoice() {
  const soundOpts = [
    {v:'',l:'Kein Sound'},
    {v:'listening',l:'Zuhoeren-Ton'},
    {v:'confirmed',l:'Bestaetigung'},
    {v:'warning',l:'Warnung'},
    {v:'alarm',l:'Alarm'},
    {v:'doorbell',l:'Tuerklingel'},
    {v:'greeting',l:'Begruessung'},
    {v:'error',l:'Fehler'},
    {v:'goodnight',l:'Gute Nacht'},
    {v:'chime',l:'Glockenspiel'},
    {v:'notification',l:'Benachrichtigung'}
  ];
  return sectionWrap('&#127897;', 'Sprach-Engine (STT / TTS)',
    fInfo('Whisper-Modell und Piper-Stimme. Aenderungen hier erfordern einen Container-Neustart (System → Neustart).') +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Spracherkennung (Whisper STT)</div>' +
    fSelect('speech.stt_model', 'Whisper-Modell', [
      {v:'tiny',l:'Tiny — Schnellstes (schlechteste Qualitaet)'},
      {v:'base',l:'Base — Schnell'},
      {v:'small',l:'Small — Empfohlen fuer CPU'},
      {v:'medium',l:'Medium — Besser (langsamer)'},
      {v:'large-v3-turbo',l:'Large V3 Turbo — Beste Qualitaet (GPU empfohlen)'}
    ]) +
    fSelect('speech.stt_language', 'Sprache', [
      {v:'de',l:'Deutsch'},{v:'en',l:'Englisch'},{v:'fr',l:'Franzoesisch'},
      {v:'es',l:'Spanisch'},{v:'it',l:'Italienisch'},{v:'nl',l:'Niederlaendisch'},
      {v:'pl',l:'Polnisch'},{v:'pt',l:'Portugiesisch'},{v:'ru',l:'Russisch'},
      {v:'tr',l:'Tuerkisch'},{v:'ja',l:'Japanisch'},{v:'zh',l:'Chinesisch'}
    ]) +
    fRange('speech.stt_beam_size', 'Beam Size (Genauigkeit)', 1, 10, 1, {1:'1 (schnell)',3:'3',5:'5 (Standard)',7:'7',10:'10 (genauest)'}) +
    fSelect('speech.stt_compute', 'Berechnung', [
      {v:'int8',l:'int8 — Empfohlen fuer CPU'},
      {v:'float16',l:'float16 — Empfohlen fuer GPU'},
      {v:'float32',l:'float32 — Hoechste Praezision (langsam)'}
    ]) +
    fSelect('speech.stt_device', 'Hardware', [
      {v:'cpu',l:'CPU'},
      {v:'cuda',l:'GPU (CUDA)'}
    ]) +
    '<div style="margin:16px 0 8px;font-weight:600;font-size:13px;">Sprachsynthese (Piper TTS)</div>' +
    fSelect('speech.tts_voice', 'Piper-Stimme', [
      {v:'de_DE-thorsten-high',l:'Thorsten High — Beste Qualitaet (empfohlen)'},
      {v:'de_DE-thorsten-medium',l:'Thorsten Medium — Gute Qualitaet'},
      {v:'de_DE-thorsten-low',l:'Thorsten Low — Schnell, weniger natuerlich'},
      {v:'de_DE-kerstin-low',l:'Kerstin — Weibliche Stimme'},
      {v:'en_US-lessac-high',l:'Lessac High — English (US)'},
      {v:'en_US-amy-medium',l:'Amy Medium — English (US)'},
      {v:'en_GB-alba-medium',l:'Alba Medium — English (UK)'}
    ]) +
    fToggle('speech.auto_night_whisper', 'Nachts automatisch fluestern')
  ) +
  sectionWrap('&#128266;', 'Sprachausgabe (TTS)',
    fInfo('Standard-Lautsprecher und TTS-Engine fuer Jarvis. Wenn leer, wird der erste Raum-Speaker verwendet.') +
    fEntityPickerSingle('sounds.default_speaker', 'Standard-Lautsprecher', ['media_player'], 'Welcher Lautsprecher soll Jarvis standardmaessig nutzen?') +
    fEntityPickerSingle('sounds.tts_entity', 'TTS-Engine', ['tts'], 'TTS-Service (z.B. tts.piper)') +
    '<div style="margin:14px 0 6px;font-weight:600;font-size:13px;">Alexa / Echo Speaker</div>' +
    fInfo('Alexa/Echo Geraete koennen keine Audio-Dateien von Piper TTS empfangen. Fuer diese Speaker wird stattdessen der Alexa-eigene TTS (notify.alexa_media) genutzt. Nur Geraete eintragen die ueber die Alexa Media Player Integration eingebunden sind.') +
    fEntityPicker('sounds.alexa_speakers', 'Alexa/Echo Speaker', ['media_player'], 'Diese Speaker erhalten TTS ueber den Alexa Notify-Service statt Audiodateien.') +
    fToggle('tts.ssml_enabled', 'Fortgeschrittene Betonung (SSML)') +
    fToggle('tts.prosody_variation', 'Tonhoehe/Tempo variieren (Prosody)') +
    fInfo('Wenn aktiv, aendert Jarvis Tonhoehe und Geschwindigkeit je nach Nachrichtentyp (Warnung=tiefer, Frage=hoeher). Bei Deaktivierung bleibt der Ton konstant.') +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Sprechgeschwindigkeit pro Situation</div>' +
    fRange('tts.speed.confirmation', 'Bestaetigung', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.warning', 'Warnung', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.briefing', 'Briefing', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.greeting', 'Begruessung', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.question', 'Frage', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.casual', 'Normal', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Sprechpausen</div>' +
    fRange('tts.pauses.before_important', 'Vor wichtigen Infos (ms)', 0, 1000, 50) +
    fRange('tts.pauses.between_sentences', 'Zwischen Saetzen (ms)', 0, 1000, 50) +
    fRange('tts.pauses.after_greeting', 'Nach Begruessung (ms)', 0, 1000, 50) +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Fluestern</div>' +
    fChipSelect('tts.whisper_triggers', 'Fluestern aktivieren bei', [
      'psst','leise','fluestern','schlafen','baby',
      'ruhe','still','shh','nachts','nacht'
    ]) +
    fChipSelect('tts.whisper_cancel_triggers', 'Fluestern beenden bei', [
      'normal','laut','aufwachen','morgen','wach','genug gefluestert'
    ])
  ) +
  sectionWrap('&#128264;', 'Lautstaerke',
    fInfo('Lautstaerke je nach Tageszeit. 0 = stumm, 1 = volle Lautstaerke.') +
    fRange('volume.day', '&#9728; Tag', 0, 1, 0.05) +
    fRange('volume.evening', '&#127751; Abend', 0, 1, 0.05) +
    fRange('volume.night', '&#127769; Nacht', 0, 1, 0.05) +
    fRange('volume.sleeping', '&#128164; Schlafen', 0, 1, 0.05) +
    fRange('volume.emergency', '&#128680; Notfall', 0, 1, 0.05) +
    fRange('volume.whisper', '&#129296; Fluestern', 0, 1, 0.05) +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Tageszeit-Wechsel</div>' +
    fRange('volume.morning_start', 'Morgen ab', 0, 23, 1) +
    fRange('volume.evening_start', 'Abend ab', 0, 23, 1) +
    fRange('volume.night_start', 'Nacht ab', 0, 23, 1)
  ) +
  sectionWrap('&#127925;', 'Sound-Effekte',
    fInfo('Kurze Toene bei bestimmten Ereignissen. Deaktiviere Sounds komplett oder waehle pro Ereignis.') +
    fToggle('sounds.enabled', 'Sound-Effekte aktiv') +
    fSelect('sounds.events.listening', 'Zuhoeren-Sound', soundOpts) +
    fSelect('sounds.events.confirmed', 'Bestaetigung-Sound', soundOpts) +
    fSelect('sounds.events.warning', 'Warnung-Sound', soundOpts) +
    fSelect('sounds.events.alarm', 'Alarm-Sound', soundOpts) +
    fSelect('sounds.events.doorbell', 'Tuerklingel-Sound', soundOpts) +
    fSelect('sounds.events.greeting', 'Begruessung-Sound', soundOpts) +
    fSelect('sounds.events.error', 'Fehler-Sound', soundOpts) +
    fSelect('sounds.events.goodnight', 'Gute-Nacht-Sound', soundOpts) +
    fRange('sounds.night_volume_factor', 'Nacht-Lautstaerke-Faktor', 0, 1, 0.1, {0:'Stumm',0.3:'Leise',0.5:'Halb',0.7:'Etwas leiser',1:'Normal'})
  ) +
  sectionWrap('&#127916;', 'Szenen-Uebergaenge',
    fInfo('Wie lange dauert der Uebergang bei Szenen-Wechsel? (z.B. Licht dimmen fuer Filmabend)') +
    fToggle('narration.enabled', 'Szenen-Narration aktiv') +
    fRange('narration.default_transition', 'Standard (Sek.)', 1, 20, 1) +
    fRange('narration.scene_transitions.filmabend', 'Filmabend (Sek.)', 1, 30, 1) +
    fRange('narration.scene_transitions.gute_nacht', 'Gute Nacht (Sek.)', 1, 30, 1) +
    fRange('narration.scene_transitions.aufwachen', 'Aufwachen (Sek.)', 1, 30, 1) +
    fRange('narration.scene_transitions.gemuetlich', 'Gemuetlich (Sek.)', 1, 30, 1) +
    fRange('narration.step_delay', 'Verzoegerung zwischen Schritten (Sek.)', 0, 10, 0.5) +
    fToggle('narration.narrate_actions', 'Aktionen ansagen ("Licht wird gedimmt...")')
  ) +
  sectionWrap('&#128100;', 'Sprecher-Erkennung',
    fInfo('Erkennt wer spricht ueber 7 Methoden: Geraete-Zuordnung, Richtung (DoA), Raum, Anwesenheit, Stimmabdruck, Voice-Features und Cache. Lernt automatisch dazu.') +
    fToggle('speaker_recognition.enabled', 'Sprecher-Erkennung aktiv') +
    fRange('speaker_recognition.min_confidence', 'Erkennungs-Sicherheit', 0, 1, 0.05, {0:'Jeder',0.3:'Niedrig',0.5:'Mittel',0.6:'Empfohlen',0.7:'Hoch',0.9:'Sehr hoch',1:'Perfekt'}) +
    fToggle('speaker_recognition.fallback_ask', 'Bei Unsicherheit nachfragen: "Wer spricht?"') +
    fRange('speaker_recognition.max_profiles', 'Max. Sprecher-Profile', 1, 50, 1) +
    fRange('speaker_recognition.enrollment_duration', 'Einlern-Dauer (Sek.)', 5, 120, 5, {5:'5s (kurz)',15:'15s',30:'30s (empfohlen)',60:'1 Min',120:'2 Min'}) +
    fKeyValue('speaker_recognition.device_mapping', 'Geraete → Person Zuordnung',
      'ESPHome Device-ID', 'Person (z.B. max)',
      'Welches Mikrofon-Geraet gehoert wem? Device-ID findest du in HA → Einstellungen → Geraete → ESPHome.') +
    fTextarea('speaker_recognition.doa_mapping', 'Richtungs-Erkennung (DoA)',
      'JSON-Format. Beispiel: {"respeaker_kueche":{"0-90":"max","270-360":"lisa"}}. Erfordert ReSpeaker XVF3800.') +
    fRange('speaker_recognition.doa_tolerance', 'DoA-Toleranz (Grad)', 5, 90, 5, {5:'5°',10:'10°',15:'15°',20:'20°',30:'30° (Standard)',45:'45°',60:'60°',90:'90°'})
  );
}

// ---- Tab 7: Routinen ----
function renderHouseStatus() {
  // Defaults setzen wenn noch nicht konfiguriert
  if (!getPath(S, 'house_status.sections')) {
    setPath(S, 'house_status.sections', ['presence','temperatures','weather','lights','security','media','open_items','offline']);
  }
  if (!getPath(S, 'house_status.detail_level')) {
    setPath(S, 'house_status.detail_level', 'normal');
  }
  return sectionWrap('&#127968;', 'Haus-Status Bereiche',
    fInfo('Welche Informationen sollen im Haus-Status angezeigt werden? Wird verwendet wenn du nach dem Status fragst oder "Haus-Status" sagst.') +
    fSelect('house_status.detail_level', 'Detail-Level', [
      {v:'kompakt',l:'Kompakt — Nur Zusammenfassung (z.B. "2 Lichter an, 22\u00b0C")'},
      {v:'normal',l:'Normal — Bereiche mit Namen (z.B. "Lichter an: Wohnzimmer, Flur")'},
      {v:'ausfuehrlich',l:'Ausfuehrlich — Alle Details (Helligkeit, Soll-Temp, Medientitel)'}
    ]) +
    fChipSelect('house_status.sections', 'Angezeigte Bereiche', [
      {v:'presence',l:'Anwesenheit'},
      {v:'temperatures',l:'Temperaturen'},
      {v:'weather',l:'Wetter'},
      {v:'lights',l:'Lichter'},
      {v:'security',l:'Sicherheit'},
      {v:'media',l:'Medien'},
      {v:'open_items',l:'Offene Fenster/Tueren'},
      {v:'offline',l:'Offline-Geraete'}
    ])
  ) +
  sectionWrap('&#127777;', 'Temperatur-Raeume',
    fInfo('Optional: Nur bestimmte Raeume im Status anzeigen. Leer = alle Raeume. Raumnamen wie in Home Assistant (z.B. Wohnzimmer, Schlafzimmer).') +
    fTextarea('house_status.temperature_rooms', 'Raeume (einer pro Zeile)', 'z.B.\nWohnzimmer\nSchlafzimmer\nGaestezimmer')
  ) +
  sectionWrap('&#128296;', 'Health Monitor',
    fInfo('Welche Sensoren sollen ueberwacht werden? Nicht-Raum-Sensoren (Waermepumpe, Prozessor etc.) werden automatisch gefiltert.') +
    fToggle('health_monitor.enabled', 'Health Monitor aktiv') +
    fNum('health_monitor.check_interval_minutes', 'Pruef-Intervall (Minuten)', 5, 60, 5) +
    fNum('health_monitor.alert_cooldown_minutes', 'Benachrichtigungs-Cooldown (Minuten)', 15, 240, 15) +
    '<div style="margin:16px 0 8px;font-weight:600;font-size:13px;">Schwellwerte</div>' +
    fNum('health_monitor.temp_low', 'Temperatur zu niedrig (°C)', 10, 20, 1) +
    fNum('health_monitor.temp_high', 'Temperatur zu hoch (°C)', 24, 35, 1) +
    fNum('health_monitor.humidity_low', 'Luftfeuchte zu niedrig (%)', 20, 40, 5) +
    fNum('health_monitor.humidity_high', 'Luftfeuchte zu hoch (%)', 60, 80, 5) +
    fNum('health_monitor.co2_warn', 'CO2 Warnung (ppm)', 800, 1500, 100) +
    fNum('health_monitor.co2_critical', 'CO2 Kritisch (ppm)', 1000, 2500, 100) +
    fTextarea('health_monitor.exclude_patterns', 'Zusaetzliche Ausschluss-Patterns (einer pro Zeile)', 'z.B.\naquarea\ntablet_\nsteckdose_')
  );
}

function renderRoutines() {
  const morningStyleOpts = [
    {v:'kompakt',l:'Kompakt — Kurzes Briefing'},
    {v:'ausfuehrlich',l:'Ausfuehrlich — Detailliertes Update'},
    {v:'freundlich',l:'Freundlich — Lockerer Start'},
    {v:'butler',l:'Butler — Formeller Morgengruss'},
    {v:'minimal',l:'Minimal — Nur das Wichtigste'},
    {v:'entspannt',l:'Entspannt — Gemuetlicher Start'}
  ];
  return sectionWrap('&#127748;', 'Morgen-Briefing',
    fInfo('Automatisches Update am Morgen — Wetter, Termine, Neuigkeiten. Wird ausgeloest wenn du morgens das erste Mal erkannt wirst.') +
    fToggle('routines.morning_briefing.enabled', 'Morgen-Briefing aktiv') +
    fSelect('routines.morning_briefing.trigger', 'Ausloeser', [
      {v:'first_motion_after_night',l:'Erste Bewegung nach der Nacht'},
      {v:'first_voice_after_night',l:'Erstes Sprachkommando nach der Nacht'},
      {v:'alarm_dismissed',l:'Wecker ausgeschaltet'},
      {v:'manual',l:'Nur auf Anfrage'}
    ]) +
    fChipSelect('routines.morning_briefing.modules', 'Was soll im Briefing enthalten sein?', [
      {v:'greeting',l:'Begruessung'},
      {v:'weather',l:'Wetter'},
      {v:'calendar',l:'Termine'},
      {v:'news',l:'Nachrichten'},
      {v:'reminders',l:'Erinnerungen'},
      {v:'traffic',l:'Verkehr'},
      {v:'smart_home',l:'Smart Home Status'},
      {v:'energy',l:'Energieverbrauch'},
      {v:'birthday',l:'Geburtstage'},
      {v:'quote',l:'Tages-Zitat'}
    ]) +
    fSelect('routines.morning_briefing.weekday_style', 'Stil unter der Woche', morningStyleOpts) +
    fSelect('routines.morning_briefing.weekend_style', 'Stil am Wochenende', morningStyleOpts) +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Morgen-Aktionen</div>' +
    fToggle('routines.morning_briefing.morning_actions.covers_up', 'Rolladen automatisch hochfahren') +
    fToggle('routines.morning_briefing.morning_actions.lights_soft', 'Licht sanft einschalten')
  ) +
  sectionWrap('&#127769;', 'Abend-Briefing',
    fInfo('Automatischer Abend-Status — Sicherheit, offene Fenster, Wetter morgen. Wird bei erster Bewegung am Abend ausgeloest. Jarvis schlaegt proaktiv vor, Rolllaeden und Fenster zu schliessen.') +
    fToggle('routines.evening_briefing.enabled', 'Abend-Briefing aktiv') +
    fRange('routines.evening_briefing.window_start_hour', 'Startzeit', 18, 23, 1, {18:'18 Uhr',19:'19 Uhr',20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr'}) +
    fRange('routines.evening_briefing.window_end_hour', 'Endzeit', 19, 24, 1, {19:'19 Uhr',20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr',24:'24 Uhr'})
  ) +
  sectionWrap('&#128197;', 'Kalender',
    fInfo('Welche Home Assistant Kalender sollen abgefragt werden? Wenn keiner gewaehlt ist, werden automatisch alle Kalender aus HA genutzt.') +
    fEntityPicker('calendar.entities', 'Kalender-Entities', ['calendar'], 'Nur ausgewaehlte Kalender abfragen — leer = alle')
  ) +
  sectionWrap('&#127769;', 'Gute-Nacht-Routine',
    fInfo('Automatische Aktionen wenn du "Gute Nacht" sagst — Lichter aus, Heizung runter, alles pruefen.') +
    fToggle('routines.good_night.enabled', 'Gute-Nacht-Routine aktiv') +
    fChipSelect('routines.good_night.triggers', 'Ausloese-Phrasen', [
      'gute nacht','schlaf gut','nacht','geh schlafen','ab ins bett',
      'ich geh pennen','bis morgen','nacht jarvis','schlafenszeit'
    ]) +
    fChipSelect('routines.good_night.checks', 'Sicherheits-Checks vor dem Schlafen', [
      {v:'doors',l:'Tueren geschlossen?'},
      {v:'windows',l:'Fenster geschlossen?'},
      {v:'lights',l:'Alle Lichter aus?'},
      {v:'stove',l:'Herd aus?'},
      {v:'oven',l:'Ofen aus?'},
      {v:'iron',l:'Buegeleisen aus?'},
      {v:'garage',l:'Garage zu?'},
      {v:'alarm',l:'Alarmanlage scharf?'}
    ]) +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Automatische Aktionen</div>' +
    fToggle('routines.good_night.actions.lights_off', 'Alle Lichter ausschalten') +
    fToggle('routines.good_night.actions.heating_night', 'Heizung auf Nacht-Modus') +
    fToggle('routines.good_night.actions.covers_down', 'Rolladen runterfahren') +
    fToggle('routines.good_night.actions.alarm_arm_home', 'Alarmanlage scharf schalten')
  ) +
  sectionWrap('&#128101;', 'Gaeste-Modus',
    fInfo('Wenn Besuch da ist — der Assistent wird formeller und zeigt keine privaten Infos.') +
    fChipSelect('routines.guest_mode.triggers', 'Aktivierung durch', [
      'besuch','gaeste','gast','besucher','gast modus','wir haben besuch',
      'gaeste da','jemand zu besuch'
    ]) +
    fToggle('routines.guest_mode.restrictions.hide_personal_info', 'Persoenliche Infos verstecken') +
    fToggle('routines.guest_mode.restrictions.formal_tone', 'Formeller Ton aktivieren') +
    fToggle('routines.guest_mode.restrictions.restrict_security', 'Sicherheitsfunktionen einschraenken') +
    fToggle('routines.guest_mode.restrictions.suggest_guest_wifi', 'Gaeste-WLAN vorschlagen')
  );
}

// ---- Proaktiv & Vorausdenken (aus Routinen ausgelagert) ----
function renderProactive() {
  return sectionWrap('&#128276;', 'Proaktive Meldungen',
    fInfo('Der Assistent meldet sich von allein — z.B. bei offenen Fenstern oder Vergesslichkeit. Je hoeher der Autonomie-Level, desto mehr meldet er sich.') +
    fToggle('proactive.enabled', 'Proaktive Meldungen aktiv') +
    fRange('proactive.cooldown_seconds', 'Mindestabstand zwischen Meldungen', 60, 3600, 60, {60:'1 Min',120:'2 Min',300:'5 Min',600:'10 Min',1800:'30 Min',3600:'1 Std'}) +
    fRange('proactive.music_follow_cooldown_minutes', 'Musik-Nachfolge Pause', 1, 30, 1) +
    fRange('proactive.min_autonomy_level', 'Ab Autonomie-Level', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fChipSelect('proactive.silence_scenes', 'Nicht stoeren bei', [
      'filmabend','schlafen','meditation','telefonat','meeting',
      'konzentration','gaeste','nicht_stoeren','musik','arbeit'
    ])
  ) +
  sectionWrap('&#9200;', 'Zeitgefuehl',
    fInfo('Der Assistent erinnert dich wenn Geraete zu lange laufen — z.B. Ofen vergessen, PC-Pause noetig.') +
    fToggle('time_awareness.enabled', 'Zeitgefuehl aktiv') +
    fRange('time_awareness.check_interval_minutes', 'Pruef-Intervall', 1, 30, 1, {1:'Jede Min.',5:'5 Min.',10:'10 Min.',15:'15 Min.',30:'30 Min.'}) +
    fRange('time_awareness.thresholds.oven', 'Ofen-Warnung nach', 10, 180, 5, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std'}) +
    fRange('time_awareness.thresholds.iron', 'Buegeleisen-Warnung nach', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('time_awareness.thresholds.light_empty_room', 'Licht im leeren Raum nach', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fRange('time_awareness.thresholds.window_open_cold', 'Fenster offen bei Kaelte nach', 30, 600, 30, {30:'30 Min',60:'1 Std',120:'2 Std',300:'5 Std',600:'10 Std'}) +
    fRange('time_awareness.thresholds.pc_no_break', 'PC-Pause erinnern nach', 60, 720, 30, {60:'1 Std',120:'2 Std',180:'3 Std',360:'6 Std',720:'12 Std'}) +
    fToggle('time_awareness.counters.coffee_machine', 'Kaffee-Zaehler (zaehlt deine Kaffees)')
  ) +
  sectionWrap('&#128300;', 'Vorausdenken',
    fInfo('Der Assistent lernt deine Gewohnheiten und schlaegt Aktionen vor — z.B. "Du machst normalerweise jetzt das Licht an".') +
    fToggle('anticipation.enabled', 'Vorausdenken aktiv') +
    fRange('anticipation.history_days', 'Lern-Zeitraum (Tage)', 7, 90, 7, {7:'1 Woche',14:'2 Wochen',30:'1 Monat',60:'2 Monate',90:'3 Monate'}) +
    fRange('anticipation.min_confidence', 'Mindest-Sicherheit', 0, 1, 0.05, {0:'Alles vorschlagen',0.3:'Niedrig',0.5:'Mittel',0.7:'Hoch',0.9:'Sehr hoch'}) +
    fRange('anticipation.check_interval_minutes', 'Pruef-Intervall', 5, 60, 5, {5:'5 Min',10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Ab welcher Sicherheit...</div>' +
    fRange('anticipation.thresholds.ask', '...nachfragen?', 0, 1, 0.05, {0.3:'30%',0.5:'50%',0.6:'60%',0.7:'70%',0.8:'80%'}) +
    fRange('anticipation.thresholds.suggest', '...vorschlagen?', 0, 1, 0.05, {0.5:'50%',0.6:'60%',0.7:'70%',0.8:'80%',0.9:'90%'}) +
    fRange('anticipation.thresholds.auto', '...automatisch ausfuehren?', 0, 1, 0.05, {0.7:'70%',0.8:'80%',0.9:'90%',0.95:'95%',1:'100%'})
  ) +
  sectionWrap('&#129504;', 'Jarvis denkt voraus',
    fInfo('Kreuz-referenziert Wetter, Kalender, Energie und Geraete-Status — und meldet sich proaktiv. Z.B. "Es wird gleich regnen, Fenster sind noch offen."') +
    fToggle('insights.enabled', 'Insights aktiv') +
    fRange('insights.check_interval_minutes', 'Pruef-Intervall', 10, 120, 5, {10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('insights.cooldown_hours', 'Cooldown pro Insight', 1, 24, 1, {1:'1 Std',2:'2 Std',4:'4 Std',8:'8 Std',12:'12 Std',24:'1 Tag'}) +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Aktive Checks</div>' +
    fToggle('insights.checks.weather_windows', 'Regen/Sturm + offene Fenster') +
    fToggle('insights.checks.frost_heating', 'Frost + Heizung aus/Away') +
    fToggle('insights.checks.calendar_travel', 'Reise im Kalender + Alarm/Fenster/Heizung') +
    fToggle('insights.checks.energy_anomaly', 'Energie-Verbrauch ueber Baseline') +
    fToggle('insights.checks.away_devices', 'Abwesend + Licht/Fenster offen') +
    fToggle('insights.checks.temp_drop', 'Ungewoehnlicher Temperatur-Abfall') +
    fToggle('insights.checks.window_temp_drop', 'Fenster offen + grosse Temp-Differenz') +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Schwellwerte</div>' +
    fRange('insights.thresholds.frost_temp_c', 'Frost-Warnung ab', -10, 10, 1, {'-5':'-5\u00B0C',0:'0\u00B0C',2:'2\u00B0C',5:'5\u00B0C'}) +
    fRange('insights.thresholds.energy_anomaly_percent', 'Energie-Abweichung', 10, 100, 5, {10:'10%',20:'20%',30:'30%',50:'50%',100:'100%'}) +
    fRange('insights.thresholds.away_device_minutes', 'Abwesend-Hinweis nach', 30, 480, 30, {30:'30 Min',60:'1 Std',120:'2 Std',240:'4 Std',480:'8 Std'}) +
    fRange('insights.thresholds.temp_drop_degrees_per_2h', 'Temp-Abfall Schwelle', 1, 10, 1, {1:'1\u00B0C',2:'2\u00B0C',3:'3\u00B0C',5:'5\u00B0C',10:'10\u00B0C'})
  ) +
  sectionWrap('&#128203;', 'Absicht-Erkennung',
    fInfo('Erkennt offene Absichten — z.B. "Ich muss noch einkaufen" wird als Aufgabe gemerkt und spaeter erinnert.') +
    fToggle('intent_tracking.enabled', 'Absicht-Erkennung aktiv') +
    fRange('intent_tracking.check_interval_minutes', 'Pruef-Intervall', 10, 240, 10, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std',240:'4 Std'}) +
    fRange('intent_tracking.remind_hours_before', 'Erinnerung vorher', 1, 48, 1, {1:'1 Std',2:'2 Std',4:'4 Std',12:'12 Std',24:'1 Tag',48:'2 Tage'})
  ) +
  sectionWrap('&#128172;', 'Gespraechs-Fortfuehrung',
    fInfo('Wenn ein Gespraech unterbrochen wird — soll der Assistent spaeter nachfragen? "Wolltest du vorhin noch was wegen...?"') +
    fToggle('conversation_continuity.enabled', 'Gespraech fortsetzen') +
    fRange('conversation_continuity.resume_after_minutes', 'Nachfragen nach', 1, 60, 1, {1:'1 Min',5:'5 Min',10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fRange('conversation_continuity.expire_hours', 'Thema vergessen nach', 1, 72, 1, {1:'1 Std',6:'6 Std',12:'12 Std',24:'1 Tag',48:'2 Tage',72:'3 Tage'})
  );
}

// ---- Koch-Assistent (aus Routinen ausgelagert) ----
function renderCooking() {
  return sectionWrap('&#127859;', 'Koch-Assistent',
    fInfo('Der Assistent kann dir Rezepte vorschlagen und beim Kochen helfen — Schritt fuer Schritt mit Timer.') +
    fToggle('cooking.enabled', 'Koch-Assistent aktiv') +
    fSelect('cooking.language', 'Rezept-Sprache', [{v:'de',l:'Deutsch'},{v:'en',l:'English'}]) +
    fRange('cooking.default_portions', 'Standard-Portionen', 1, 12, 1) +
    fRange('cooking.max_steps', 'Max. Schritte pro Rezept', 3, 30, 1) +
    fRange('cooking.max_tokens', 'Rezept-Detailgrad', 256, 4096, 256, {256:'Kurz',512:'Normal',1024:'Ausfuehrlich',2048:'Sehr ausfuehrlich',4096:'Maximum'}) +
    fToggle('cooking.timer_notify_tts', 'Timer-Erinnerungen per Sprache')
  );
}

/// ---- Tab 8: Sicherheit & Erweitert ----
function renderSecurity() {
  const hMode = getPath(S, 'heating.mode') || 'room_thermostat';
  const isCurve = hMode === 'heating_curve';

  return sectionWrap('&#128274;', 'Sicherheit',
    fInfo('Welche Aktionen brauchen eine Bestaetigung? Und welche Temperatur-Grenzen gelten?') +
    fChipSelect('security.require_confirmation', 'Bestaetigung erforderlich fuer', [
      {v:'alarm_disarm',l:'Alarm deaktivieren'},
      {v:'alarm_arm',l:'Alarm aktivieren'},
      {v:'lock_unlock',l:'Tuerschloss oeffnen'},
      {v:'garage_open',l:'Garage oeffnen'},
      {v:'heating_off',l:'Heizung ausschalten'},
      {v:'all_lights_off',l:'Alle Lichter aus'},
      {v:'cover_open',l:'Rolladen oeffnen'},
      {v:'camera_disable',l:'Kamera deaktivieren'},
      {v:'automation_delete',l:'Automation loeschen'}
    ]) +
    (!isCurve ?
      fRange('security.climate_limits.min', 'Temperatur Min (°C)', 5, 25, 0.5) +
      fRange('security.climate_limits.max', 'Temperatur Max (°C)', 20, 35, 0.5)
    : '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">Im Heizkurven-Modus gelten die Offset-Grenzen (Raeume &rarr; Heizung).</p>'
    )
  ) +
  sectionWrap('&#128273;', 'API Key (Netzwerk-Schutz)',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Schuetzt die Assistant-API gegen unbefugte Netzwerkzugriffe. Diesen Key im HA-Addon und in der HA-Integration eintragen, DANN Pruefung aktivieren.</p>' +
    '<div class="form-group" style="margin-bottom:12px;">' +
    '<label style="display:flex;align-items:center;gap:8px;cursor:pointer;">' +
    '<input type="checkbox" id="apiKeyEnforcement" onchange="toggleApiKeyEnforcement(this.checked)" style="width:18px;height:18px;" />' +
    '<span>API Key Pruefung aktiv</span>' +
    '</label>' +
    '<p id="apiKeyEnforcementHint" style="font-size:11px;color:var(--text-secondary);margin-top:4px;"></p>' +
    '</div>' +
    '<div class="form-group"><label>Aktueller API Key</label>' +
    '<div style="display:flex;gap:8px;align-items:center;">' +
    '<input type="text" id="apiKeyDisplay" readonly style="flex:1;font-family:monospace;font-size:12px;" value="Wird geladen..." />' +
    '<button onclick="copyApiKey()" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg-card);cursor:pointer;font-size:12px;">Kopieren</button>' +
    '</div></div>' +
    '<div style="margin-top:8px;"><button onclick="regenerateApiKey()" style="padding:6px 12px;border:1px solid var(--danger);border-radius:6px;background:transparent;color:var(--danger);cursor:pointer;font-size:12px;">Key neu generieren</button>' +
    '<span style="font-size:11px;color:var(--text-secondary);margin-left:8px;">Achtung: Addon + HA-Integration muessen danach aktualisiert werden!</span></div>'
  ) +
  sectionWrap('&#128272;', 'Vertrauensstufen',
    fInfo('Standard-Vertrauensstufe fuer neue Personen und was Gaeste/Besitzer duerfen.') +
    fSelect('trust_levels.default', 'Standard fuer neue Personen', [
      {v:0,l:'Gast (eingeschraenkt)'},
      {v:1,l:'Mitbewohner (normal)'},
      {v:2,l:'Besitzer (voll)'}
    ]) +
    fChipSelect('trust_levels.guest_allowed_actions', 'Gaeste duerfen', [
      {v:'light_control',l:'Licht steuern'},
      {v:'climate_control',l:'Temperatur aendern'},
      {v:'media_control',l:'Musik/TV steuern'},
      {v:'cover_control',l:'Rolladen steuern'},
      {v:'scene_activate',l:'Szenen aktivieren'},
      {v:'timer_set',l:'Timer stellen'},
      {v:'weather_query',l:'Wetter fragen'},
      {v:'smalltalk',l:'Smalltalk'}
    ]) +
    fChipSelect('trust_levels.security_actions', 'Nur Besitzer duerfen', [
      {v:'alarm_control',l:'Alarmanlage'},
      {v:'lock_control',l:'Tuerschloesser'},
      {v:'camera_control',l:'Kameras'},
      {v:'garage_control',l:'Garage'},
      {v:'automation_edit',l:'Automationen bearbeiten'},
      {v:'settings_change',l:'Einstellungen aendern'},
      {v:'person_manage',l:'Personen verwalten'},
      {v:'system_restart',l:'System neustarten'}
    ])
  ) +
  sectionWrap('&#128276;', 'Benachrichtigungskanaele',
    fInfo('Welche Kanaele soll der Assistent fuer Benachrichtigungen nutzen? Kanaele koennen einzeln konfiguriert werden.') +
    '<div id="notifyChannelsContainer" style="color:var(--text-muted);font-size:12px;">Wird geladen...</div>' +
    '<div style="margin-top:10px;"><button class="btn btn-primary" style="font-size:12px;" onclick="saveNotifyChannels()">Kanaele speichern</button></div>'
  ) +
  // --- Phase 17: Notfall-Protokolle ---
  sectionWrap('&#127752;', 'Notfall-Protokolle',
    fInfo('Bei CRITICAL Events (Rauch, Einbruch, Wasser) werden automatisch Aktionen ausgefuehrt. Jedes Protokoll kann einzeln aktiviert werden. Geraete werden ueber die Rollenzuweisung zugeordnet.') +
    '<div id="emergencyProtocolsContainer" style="color:var(--text-muted);font-size:12px;padding:8px;">Lade Notfall-Protokolle...</div>'
  ) +
  // --- Phase 17: Interrupt-Queue ---
  sectionWrap('&#9889;', 'Interrupt-Queue',
    fInfo('CRITICAL-Meldungen unterbrechen sofort alle laufenden Aktionen (TTS, Streaming). Ohne Interrupt geht die Meldung den normalen Weg ueber das LLM.') +
    fToggle('interrupt_queue.enabled', 'Interrupt-Queue aktiviert') +
    fRange('interrupt_queue.pause_ms', 'Pause vor Notfall-Meldung (ms)', 100, 1000, 100,
      {100:'0.1s',200:'0.2s',300:'0.3s',500:'0.5s',1000:'1s'})
  ) +
  // --- Phase 17: Situations-Modell ---
  sectionWrap('&#128269;', 'Situations-Modell',
    fInfo('JARVIS merkt sich den Hausstatus bei jedem Gespraech und erwaehnt beim naechsten Gespraech beilaeufig was sich veraendert hat.') +
    fToggle('situation_model.enabled', 'Situations-Modell aktiviert') +
    fRange('situation_model.min_pause_minutes', 'Mindest-Pause zwischen Deltas (Min)', 5, 120, 5) +
    fRange('situation_model.max_changes', 'Max. gemeldete Aenderungen', 1, 10, 1) +
    fRange('situation_model.temp_threshold', 'Temperatur-Schwelle (°C)', 1, 5, 0.5)
  );
}

// ---- Notfall-Protokolle (Emergency Protocols with Entity Assignment) ----
const EP_PROTOCOLS = [
  { key: 'fire', title: 'Feuer / Rauch', desc: 'Rauchmelder loest aus — Lichter an, Rolllaeden offen, Durchsage', icon: '&#128293;', feature: 'fire_co',
    roles: {light:'Lichter einschalten', cover:'Rolllaeden oeffnen', tts_speaker:'Durchsage-Speaker', emergency_lock:'Schloesser entriegeln', hvac:'Heizung/Klima aus'} },
  { key: 'intrusion', title: 'Einbruch / Alarm', desc: 'Alarmsystem wird ausgeloest — Lichter an, Sirene, Durchsage', icon: '&#128680;', feature: 'emergency',
    roles: {light:'Lichter einschalten', siren:'Sirene aktivieren', tts_speaker:'Durchsage-Speaker', lock:'Schloesser verriegeln', cover:'Rolllaeden schliessen'} },
  { key: 'water_leak', title: 'Wasserleck', desc: 'Wassersensor schlaegt an — Ventile zu, Heizung aus, Durchsage', icon: '&#128167;', feature: 'water_leak',
    roles: {valve:'Ventile schliessen', heating:'Heizung aus', tts_speaker:'Durchsage-Speaker', light:'Lichter einschalten'} },
];
let _epData = {}; // { fire: {entities: [...], config: {...}}, ... }
let _epExpanded = {};

async function loadEmergencyProtocols() {
  const c = document.getElementById('emergencyProtocolsContainer');
  if (!c) return;
  try {
    // Load config + entities for each protocol
    for (const proto of EP_PROTOCOLS) {
      const [entities, config] = await Promise.all([
        api('/api/ui/security/entities/' + proto.feature).catch(() => []),
        api('/api/ui/security/emergency/config').catch(() => ({})),
      ]);
      _epData[proto.key] = { entities: Array.isArray(entities) ? entities : [], config: config || {} };
    }
    renderEmergencyProtocols();
  } catch(e) {
    c.innerHTML = '<div style="color:var(--danger);padding:8px;">Fehler: ' + esc(e.message) + '</div>';
  }
}

function renderEmergencyProtocols() {
  const c = document.getElementById('emergencyProtocolsContainer');
  if (!c) return;
  c.innerHTML = EP_PROTOCOLS.map(proto => {
    const data = _epData[proto.key] || { entities: [], config: {} };
    const yamlProto = getPath(S, 'emergency_protocols.' + proto.key) || {};
    const enabled = yamlProto.enabled !== false && (yamlProto.actions || []).length > 0;
    const expanded = _epExpanded[proto.key] || false;
    const entityCount = data.entities.filter(e => e.is_active).length;

    let html = '<div style="margin-bottom:12px;background:var(--bg-secondary);border-radius:10px;border-left:3px solid ' + (enabled ? 'var(--success)' : 'var(--text-muted)') + ';overflow:hidden;">';

    // Header
    html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;cursor:pointer;" onclick="toggleEpExpand(\'' + proto.key + '\')">';
    html += '<div style="display:flex;align-items:center;gap:10px;">';
    html += '<span style="font-size:22px;">' + proto.icon + '</span>';
    html += '<div>';
    html += '<div style="font-weight:600;font-size:14px;">' + proto.title + '</div>';
    html += '<div style="font-size:11px;color:var(--text-muted);margin-top:1px;">' + proto.desc + '</div>';
    html += '</div></div>';
    html += '<div style="display:flex;align-items:center;gap:10px;">';
    if (entityCount > 0) html += '<span style="font-size:11px;color:var(--text-muted);">' + entityCount + ' Geraete</span>';
    html += '<label class="toggle" style="margin:0;" onclick="event.stopPropagation()">';
    html += '<input type="checkbox" data-path="emergency_protocols.' + proto.key + '.enabled" ' + (enabled ? 'checked' : '') + '>';
    html += '<span class="toggle-track"></span><span class="toggle-thumb"></span></label>';
    html += '<span class="mdi ' + (expanded ? 'mdi-chevron-up' : 'mdi-chevron-down') + '" style="font-size:20px;color:var(--text-muted);"></span>';
    html += '</div></div>';

    // Expanded content
    if (expanded) {
      html += '<div style="padding:0 16px 16px;border-top:1px solid var(--border);">';

      // Entity assignments grouped by role
      for (const [role, roleLabel] of Object.entries(proto.roles)) {
        const roleEntities = data.entities.filter(e => e.role === role);
        const roleIcon = {light:'&#128161;', cover:'&#129695;', lock:'&#128274;', siren:'&#128680;', tts_speaker:'&#128266;', valve:'&#128295;', heating:'&#127777;', hvac:'&#127777;', emergency_lock:'&#128274;', emergency_light:'&#128161;', emergency_cover:'&#129695;'}[role] || '&#9881;';

        html += '<div style="margin-top:12px;">';
        html += '<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:6px;display:flex;align-items:center;gap:6px;">';
        html += '<span>' + roleIcon + '</span> ' + esc(roleLabel);
        html += '</div>';

        if (roleEntities.length > 0) {
          for (const ent of roleEntities) {
            const active = ent.is_active !== false;
            html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 10px;margin:3px 0;background:var(--bg-primary);border-radius:6px;border:1px solid var(--border);opacity:' + (active ? '1' : '0.5') + ';">';
            html += '<span style="flex:1;font-size:12px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(ent.name || ent.entity_id) + '</span>';
            html += '<span style="font-size:10px;color:var(--text-muted);font-family:var(--mono,monospace);">' + esc(ent.entity_id) + '</span>';
            html += '<button class="btn btn-ghost" style="padding:2px 6px;min-width:auto;color:var(--danger);font-size:14px;" onclick="removeEpEntity(\'' + proto.feature + '\',' + ent.id + ')" title="Entfernen">&#10005;</button>';
            html += '</div>';
          }
        } else {
          html += '<div style="font-size:11px;color:var(--text-muted);padding:4px 0;font-style:italic;">Keine Geraete zugewiesen</div>';
        }

        // Add entity input
        html += '<div style="margin-top:4px;display:flex;gap:6px;align-items:center;">';
        html += '<div class="entity-pick-wrap" style="flex:1;position:relative;">';
        html += '<input class="form-input entity-pick-input" placeholder="&#128269; Entity suchen..." ';
        html += 'id="ep_add_' + proto.key + '_' + role + '" ';
        html += 'data-feature="' + proto.feature + '" data-role="' + role + '" ';
        html += 'oninput="epEntityFilter(this)" onfocus="epEntityFilter(this)" ';
        html += 'style="font-size:12px;padding:6px 10px;background:var(--bg-input);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);width:100%;">';
        html += '<div class="ep-entity-dropdown" style="display:none;position:absolute;z-index:100;top:100%;left:0;right:0;max-height:200px;overflow-y:auto;background:var(--bg-card);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.3);"></div>';
        html += '</div>';
        html += '</div>';

        html += '</div>';
      }

      // Auto-detect button
      html += '<div style="margin-top:14px;display:flex;gap:8px;justify-content:flex-end;">';
      html += '<button class="btn btn-secondary" style="font-size:12px;padding:6px 12px;" onclick="autoDetectEpEntities(\'' + proto.feature + '\',\'' + proto.key + '\')">';
      html += '&#128269; Auto-Erkennung</button>';
      html += '</div>';

      html += '</div>';
    }

    html += '</div>';
    return html;
  }).join('');
}

function toggleEpExpand(key) {
  _epExpanded[key] = !_epExpanded[key];
  renderEmergencyProtocols();
}

// Entity search dropdown for emergency protocols
let _epAllEntities = null;
async function epEntityFilter(input) {
  const dropdown = input.parentElement.querySelector('.ep-entity-dropdown');
  const query = input.value.trim().toLowerCase();
  if (query.length < 1) { dropdown.style.display = 'none'; return; }

  // Load all HA entities once
  if (!_epAllEntities) {
    try {
      const d = await api('/api/ui/entities');
      _epAllEntities = d.entities || d || [];
    } catch(e) { _epAllEntities = []; }
  }

  const feature = input.dataset.feature;
  const role = input.dataset.role;
  const matches = _epAllEntities.filter(e => {
    const eid = (e.entity_id || '').toLowerCase();
    const name = (e.name || e.friendly_name || '').toLowerCase();
    return eid.includes(query) || name.includes(query);
  }).slice(0, 15);

  if (matches.length === 0) {
    dropdown.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:12px;">Keine Treffer</div>';
  } else {
    dropdown.innerHTML = matches.map(e => {
      const eid = e.entity_id || '';
      const name = e.name || e.friendly_name || eid;
      return '<div style="padding:6px 10px;cursor:pointer;font-size:12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;" ' +
        'onmousedown="addEpEntity(\'' + feature + '\',\'' + role + '\',\'' + esc(eid) + '\')" ' +
        'onmouseover="this.style.background=\'var(--bg-tertiary)\'" onmouseout="this.style.background=\'\'">' +
        '<span style="font-weight:500;">' + esc(name) + '</span>' +
        '<span style="color:var(--text-muted);font-family:var(--mono,monospace);font-size:10px;">' + esc(eid) + '</span>' +
      '</div>';
    }).join('');
  }
  dropdown.style.display = '';

  // Close on blur (slight delay for click)
  input.onblur = () => setTimeout(() => { dropdown.style.display = 'none'; }, 200);
}

async function addEpEntity(feature, role, entityId) {
  try {
    await api('/api/ui/security/entities/' + feature, 'POST', { entity_id: entityId, role: role });
    toast('Geraet zugewiesen: ' + entityId);
    await loadEmergencyProtocols();
  } catch(e) { toast('Fehler: ' + e.message, 'error'); }
}

async function removeEpEntity(feature, assignmentId) {
  try {
    await api('/api/ui/security/entities/' + feature + '/' + assignmentId, 'DELETE');
    toast('Geraet entfernt');
    await loadEmergencyProtocols();
  } catch(e) { toast('Fehler: ' + e.message, 'error'); }
}

async function autoDetectEpEntities(feature, protoKey) {
  try {
    const suggestions = await api('/api/ui/security/entities/' + feature + '/auto-detect', 'POST');
    if (!suggestions || suggestions.length === 0) {
      toast('Keine passenden Geraete gefunden', 'warning');
      return;
    }
    let added = 0;
    const existing = (_epData[protoKey] || {}).entities || [];
    const existingIds = new Set(existing.map(e => e.entity_id + ':' + e.role));
    for (const s of suggestions) {
      if (!existingIds.has(s.entity_id + ':' + s.role)) {
        await api('/api/ui/security/entities/' + feature, 'POST', { entity_id: s.entity_id, role: s.role });
        added++;
      }
    }
    toast(added + ' Geraete erkannt und zugewiesen', 'success');
    await loadEmergencyProtocols();
  } catch(e) { toast('Fehler bei Auto-Erkennung: ' + e.message, 'error'); }
}

// ---- Notification Channels ----
let _notifyChannels = {};

async function loadNotifyChannels() {
  try {
    const d = await api('/api/ui/notification-channels');
    _notifyChannels = d.channels || {};
    renderNotifyChannels();
  } catch(e) { console.error('Notify channels fail:', e); }
}

function renderNotifyChannels() {
  const c = document.getElementById('notifyChannelsContainer');
  if (!c) return;
  const icons = {websocket:'&#127760;', tts:'&#128266;', ha_notify:'&#128241;'};
  const labels = {websocket:'WebSocket (Dashboard)', tts:'Sprachausgabe (TTS)', ha_notify:'HA Benachrichtigung (App)'};
  let html = '';
  for (const [name, ch] of Object.entries(_notifyChannels)) {
    const icon = icons[name] || '&#128276;';
    const label = labels[name] || name;
    const pref = ch.preferred || false;
    const urgency = ch.urgency_min || 'low';
    const info = name==='websocket' && ch.connected_clients !== undefined ? ` (${ch.connected_clients} verbunden)` : '';
    html += `<div style="padding:10px;margin-bottom:8px;background:var(--bg-secondary);border-radius:6px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
        <span style="font-size:13px;font-weight:600;">${icon} ${label}${info}</span>
        <label class="toggle" style="margin:0;">
          <input type="checkbox" data-notify="${name}" data-field="preferred" ${pref?'checked':''} onchange="updateNotifyChannel('${name}','preferred',this.checked)">
          <span class="toggle-track"></span><span class="toggle-thumb"></span>
        </label>
      </div>
      <div style="font-size:11px;color:var(--text-secondary);margin-bottom:6px;">${esc(ch.description||'')}</div>
      <div style="display:flex;gap:12px;align-items:center;">
        <label style="font-size:11px;color:var(--text-muted);">Min. Dringlichkeit:</label>
        <select data-notify="${name}" data-field="urgency_min" style="font-size:11px;padding:3px 8px;background:var(--bg-input);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);"
          onchange="updateNotifyChannel('${name}','urgency_min',this.value)">
          <option value="low" ${urgency==='low'?'selected':''}>Niedrig</option>
          <option value="medium" ${urgency==='medium'?'selected':''}>Mittel</option>
          <option value="high" ${urgency==='high'?'selected':''}>Hoch</option>
        </select>
      </div>
    </div>`;
  }
  if (!html) html = '<div style="font-size:12px;color:var(--text-muted);">Keine Kanaele verfuegbar</div>';
  c.innerHTML = html;
}

function updateNotifyChannel(name, field, value) {
  if (_notifyChannels[name]) _notifyChannels[name][field] = value;
}

async function saveNotifyChannels() {
  try {
    const payload = {};
    for (const [name, ch] of Object.entries(_notifyChannels)) {
      payload[name] = { preferred: !!ch.preferred, urgency_min: ch.urgency_min || 'low' };
      if (ch.quiet_hours) payload[name].quiet_hours = ch.quiet_hours;
    }
    await api('/api/ui/notification-channels', 'PUT', {channels: payload});
    toast('Benachrichtigungskanaele gespeichert');
  } catch(e) { toast('Fehler beim Speichern', 'error'); }
}

// ---- API Key Management ----
async function loadApiKey() {
  try {
    const data = await api('/api/ui/api-key');
    const el = document.getElementById('apiKeyDisplay');
    if (el && data.api_key) el.value = data.api_key;
    const cb = document.getElementById('apiKeyEnforcement');
    if (cb) {
      cb.checked = !!data.enforcement;
      if (data.env_locked) { cb.disabled = true; }
    }
    updateEnforcementHint(!!data.enforcement, !!data.env_locked);
  } catch (e) { /* ignore */ }
}
function updateEnforcementHint(active, envLocked) {
  const hint = document.getElementById('apiKeyEnforcementHint');
  if (!hint) return;
  if (envLocked) {
    hint.textContent = 'Durch Umgebungsvariable ASSISTANT_API_KEY erzwungen (kann hier nicht deaktiviert werden).';
    hint.style.color = '#f59e0b';
  } else if (active) {
    hint.textContent = 'Aktiv: Alle /api/assistant/* Anfragen benoetigen einen gueltigen API Key.';
    hint.style.color = '#10b981';
  } else {
    hint.textContent = 'Inaktiv: API ist ohne Key zugaenglich. Erst Key in Addon/HA-Integration eintragen, dann hier aktivieren.';
    hint.style.color = 'var(--text-secondary)';
  }
}
function copyApiKey() {
  const el = document.getElementById('apiKeyDisplay');
  if (el) { navigator.clipboard.writeText(el.value); toast('API Key kopiert!'); }
}
async function regenerateApiKey() {
  if (!confirm('API Key wirklich neu generieren? Addon und HA-Integration muessen danach aktualisiert werden!')) return;
  try {
    const data = await api('/api/ui/api-key/regenerate', 'POST');
    const el = document.getElementById('apiKeyDisplay');
    if (el && data.api_key) el.value = data.api_key;
    toast('Neuer API Key generiert!');
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}
async function toggleApiKeyEnforcement(enabled) {
  const action = enabled ? 'aktivieren' : 'deaktivieren';
  if (enabled && !confirm('API Key Pruefung aktivieren? Stelle sicher, dass der Key bereits im HA-Addon und in der HA-Integration eingetragen ist, sonst funktioniert die Kommunikation nicht mehr!')) {
    const cb = document.getElementById('apiKeyEnforcement');
    if (cb) cb.checked = false;
    return;
  }
  try {
    const data = await api('/api/ui/api-key/enforcement', 'POST', { enabled });
    updateEnforcementHint(data.enforcement);
    toast('API Key Pruefung ' + (data.enforcement ? 'aktiviert' : 'deaktiviert'));
  } catch (e) {
    toast('Fehler: ' + e.message, 'error');
    const cb = document.getElementById('apiKeyEnforcement');
    if (cb) cb.checked = !enabled;
  }
}

// ---- Recovery-Key ----
async function regenerateRecoveryKey() {
  if (!confirm('Neuen Recovery-Key generieren? Der alte Key wird ungueltig! Notiere dir den neuen Key sofort.')) return;
  try {
    const data = await api('/api/ui/recovery-key/regenerate', 'POST');
    const el = document.getElementById('recoveryKeyDisplay');
    if (el && data.recovery_key) {
      el.value = data.recovery_key;
      el.style.color = 'var(--accent)';
      el.style.fontSize = '18px';
      el.style.fontWeight = '700';
    }
    toast('Neuer Recovery-Key generiert — JETZT notieren!');
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

// ---- Tab: KI-Autonomie (Phase 13.1 / 13.2 / 13.4) ----
let SNAPSHOTS = [];

function renderAutonomie() {
  return sectionWrap('&#129302;', 'Selbstoptimierung',
    fInfo('Der Assistent lernt aus euren Gespraechen und schlaegt Verbesserungen vor. Du entscheidest ob Vorschlaege angenommen werden. Die Kern-Identitaet ist geschuetzt.') +
    fToggle('self_optimization.enabled', 'Selbstoptimierung aktiv') +
    fSelect('self_optimization.approval_mode', 'Genehmigungsmodus', [
      {v:'manual', l:'Manuell (nur mit Bestaetigung)'},
      {v:'off', l:'Aus (keine Vorschlaege)'}
    ]) +
    fSelect('self_optimization.analysis_interval', 'Analyse-Intervall', [
      {v:'weekly', l:'Woechentlich'},
      {v:'daily', l:'Taeglich'}
    ]) +
    fNum('self_optimization.max_proposals_per_cycle', 'Max. Vorschlaege pro Zyklus', 1, 10) +
    fModelSelect('self_optimization.model', 'Analyse-Modell')
  ) +
  sectionWrap('&#128203;', 'Vorschlaege (Approval-Workflow)',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Jarvis macht nur Vorschlaege — DU entscheidest ob sie angewendet werden. Jede Aenderung wird vorher gesnapshot.</p>' +
    '<div id="proposalsList" style="margin-bottom:12px;"></div>' +
    '<button class="btn btn-secondary" style="font-size:12px;" onclick="runAnalysis()">Analyse jetzt starten</button>'
  ) +
  sectionWrap('&#128190;', 'Rollback & Snapshots',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Jede Config-Aenderung wird gesichert. Rollback jederzeit moeglich.</p>' +
    fToggle('self_optimization.rollback.enabled', 'Rollback aktiv') +
    fNum('self_optimization.rollback.max_snapshots', 'Max. gespeicherte Snapshots', 5, 100) +
    fToggle('self_optimization.rollback.snapshot_on_every_edit', 'Snapshot bei jeder Aenderung') +
    '<div id="snapshotsList" style="margin-top:12px;"></div>'
  ) +
  sectionWrap('&#128295;', 'Parameter-Grenzen',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Jarvis kann NUR innerhalb dieser Grenzen vorschlagen.</p>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">' +
    fNum('self_optimization.parameter_bounds.sarcasm_level.min', 'Sarkasmus Min', 1, 5) +
    fNum('self_optimization.parameter_bounds.sarcasm_level.max', 'Sarkasmus Max', 1, 5) +
    fNum('self_optimization.parameter_bounds.opinion_intensity.min', 'Meinungen Min', 0, 3) +
    fNum('self_optimization.parameter_bounds.opinion_intensity.max', 'Meinungen Max', 0, 3) +
    fNum('self_optimization.parameter_bounds.max_response_sentences.min', 'Saetze Min', 1, 10) +
    fNum('self_optimization.parameter_bounds.max_response_sentences.max', 'Saetze Max', 1, 10) +
    fNum('self_optimization.parameter_bounds.formality_min.min', 'Formalitaet-Min Min', 0, 100) +
    fNum('self_optimization.parameter_bounds.formality_min.max', 'Formalitaet-Min Max', 0, 100) +
    '</div>'
  ) +
  sectionWrap('&#128683;', 'Geschuetzte Bereiche (Immutable)',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Diese Bereiche kann Jarvis NIEMALS selbst aendern.</p>' +
    fChipSelect('self_optimization.immutable_keys', 'Geschuetzte Bereiche (nicht aenderbar durch KI)', [
      'security','trust_levels','response_filter.banned_phrases',
      'response_filter.banned_starters','household','assistant.name',
      'self_optimization.immutable_keys','self_optimization.approval_mode',
      'models.fast','models.smart','models.deep','autonomy.level'
    ], 'Klicke auf Bereiche die die KI NIEMALS selbst aendern darf.')
  ) +
  sectionWrap('&#9889;', 'Self-Automation (Phase 13.2)',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Jarvis erstellt HA-Automationen aus natuerlicher Sprache. Approval-Workflow: Du musst jede Automation bestaetigen.</p>' +
    fToggle('self_automation.enabled', 'Self-Automation aktiv') +
    fNum('self_automation.max_per_day', 'Max. Automationen pro Tag', 1, 20) +
    fModelSelect('self_automation.model', 'Modell fuer Automations-Erstellung')
  ) +
  sectionWrap('&#128200;', 'Feedback-System',
    fInfo('Wie reagiert der Assistent auf positives/negatives Feedback? Scores bestimmen wie haeufig er sich meldet.') +
    fRange('feedback.auto_timeout_seconds', 'Feedback-Timeout', 30, 600, 30, {30:'30s',60:'1 Min',120:'2 Min',300:'5 Min',600:'10 Min'}) +
    fRange('feedback.base_cooldown_seconds', 'Basis-Abstand', 60, 1800, 60, {60:'1 Min',120:'2 Min',300:'5 Min',600:'10 Min',1800:'30 Min'}) +
    fRange('feedback.score_suppress', 'Unterdruecken unter', 0, 1, 0.05) +
    fRange('feedback.score_reduce', 'Reduzieren unter', 0, 1, 0.05) +
    fRange('feedback.score_normal', 'Normal ab', 0, 1, 0.05) +
    fRange('feedback.score_boost', 'Boost ab', 0, 1, 0.05)
  ) +
  sectionWrap('&#128221;', 'Config-Selbstmodifikation (Phase 13.1)',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Jarvis kann nur diese 3 Dateien editieren (Whitelist). settings.yaml ist NICHT editierbar durch Jarvis.</p>' +
    '<div style="display:flex;flex-direction:column;gap:8px;">' +
    '<div style="display:flex;align-items:center;gap:8px;padding:8px;background:var(--bg-secondary);border-radius:6px;">' +
      '<span style="color:var(--success);">&#9989;</span><span style="font-size:13px;">easter_eggs.yaml</span>' +
      '<span style="font-size:11px;color:var(--text-muted);margin-left:auto;">Easter Eggs &amp; Gag-Antworten</span></div>' +
    '<div style="display:flex;align-items:center;gap:8px;padding:8px;background:var(--bg-secondary);border-radius:6px;">' +
      '<span style="color:var(--success);">&#9989;</span><span style="font-size:13px;">opinion_rules.yaml</span>' +
      '<span style="font-size:11px;color:var(--text-muted);margin-left:auto;">Meinungs-Kommentare</span></div>' +
    '<div style="display:flex;align-items:center;gap:8px;padding:8px;background:var(--bg-secondary);border-radius:6px;">' +
      '<span style="color:var(--success);">&#9989;</span><span style="font-size:13px;">room_profiles.yaml</span>' +
      '<span style="font-size:11px;color:var(--text-muted);margin-left:auto;">Raum-Metadaten</span></div>' +
    '<div style="display:flex;align-items:center;gap:8px;padding:8px;background:var(--bg-secondary);border-radius:6px;opacity:0.5;">' +
      '<span style="color:var(--danger);">&#10060;</span><span style="font-size:13px;">settings.yaml</span>' +
      '<span style="font-size:11px;color:var(--text-muted);margin-left:auto;">NUR durch User aenderbar</span></div>' +
    '</div>'
  );
}

async function loadOptStatus() {
  try {
    const data = await api('/api/ui/self-optimization/status');
    renderProposalList(data.proposals || []);
  } catch(e) { console.error('OptStatus fail:', e); }
}

function renderProposalList(proposals) {
  const c = document.getElementById('proposalsList');
  if (!c) return;
  if (proposals.length === 0) {
    c.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-muted);font-size:12px;">Keine offenen Vorschlaege</div>';
    return;
  }
  c.innerHTML = '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">Offene Vorschlaege:</div>' +
    proposals.map((p, i) => {
      const conf = Math.round((p.confidence || 0) * 100);
      return `<div style="padding:8px;margin-bottom:6px;background:var(--bg-secondary);border-radius:6px;border-left:3px solid var(--accent);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="font-weight:600;font-size:13px;">${esc(p.parameter)}: ${esc(String(p.current))} &#8594; ${esc(String(p.proposed))}</span>
          <span style="font-size:11px;color:var(--text-muted);background:var(--bg-primary);padding:2px 6px;border-radius:4px;">${conf}%</span>
        </div>
        <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">${esc(p.reason)}</div>
        <div style="display:flex;gap:6px;justify-content:flex-end;">
          <button class="btn btn-secondary" style="padding:3px 10px;font-size:11px;background:var(--danger);border-color:var(--danger);color:white;" onclick="rejectProposal(${i})">Ablehnen</button>
          <button class="btn btn-primary" style="padding:3px 10px;font-size:11px;" onclick="approveProposal(${i})">Annehmen</button>
        </div>
      </div>`;
    }).join('') +
    (proposals.length > 1 ? '<div style="text-align:right;margin-top:6px;"><button class="btn btn-secondary" style="padding:3px 12px;font-size:11px;" onclick="rejectAllProposals()">Alle ablehnen</button></div>' : '');
}

async function approveProposal(index) {
  if (!confirm('Diesen Vorschlag wirklich anwenden? (Snapshot wird vorher erstellt)')) return;
  try {
    const result = await api('/api/ui/self-optimization/approve', 'POST', {index});
    if (result.success) {
      toast('Angewendet: ' + result.message);
      S = await api('/api/ui/settings');
      renderCurrentTab();
      loadOptStatus();
      loadSnapshots();
    } else {
      toast(result.message, 'error');
    }
  } catch(e) { toast('Fehler', 'error'); }
}

async function rejectProposal(index) {
  try {
    const result = await api('/api/ui/self-optimization/reject', 'POST', {index});
    if (result.success) {
      toast('Abgelehnt');
      loadOptStatus();
    }
  } catch(e) { toast('Fehler', 'error'); }
}

async function rejectAllProposals() {
  try {
    const result = await api('/api/ui/self-optimization/reject-all', 'POST', {});
    if (result.success) {
      toast(result.message);
      loadOptStatus();
    }
  } catch(e) { toast('Fehler', 'error'); }
}

async function runAnalysis() {
  toast('Analyse wird gestartet...', 'info');
  try {
    const result = await api('/api/ui/self-optimization/run-analysis', 'POST', {});
    toast(result.message);
    loadOptStatus();
  } catch(e) { toast('Analyse-Fehler', 'error'); }
}

async function loadSnapshots() {
  try {
    const data = await api('/api/ui/snapshots');
    SNAPSHOTS = data.snapshots || [];
    renderSnapshotList();
  } catch(e) { console.error('Snapshots fail:', e); }
}

function renderSnapshotList() {
  const c = document.getElementById('snapshotsList');
  if (!c) return;
  if (SNAPSHOTS.length === 0) {
    c.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-muted);font-size:12px;">Keine Snapshots vorhanden</div>';
    return;
  }
  c.innerHTML = '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">Letzte Snapshots:</div>' +
    SNAPSHOTS.slice(0, 10).map(s => {
      const dt = new Date(s.timestamp).toLocaleString('de-DE', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;margin-bottom:4px;background:var(--bg-secondary);border-radius:6px;font-size:12px;">
        <span style="font-weight:600;min-width:100px;">${esc(s.config_file)}</span>
        <span style="color:var(--text-secondary);flex:1;">${esc(s.reason)}</span>
        <span style="color:var(--text-muted);min-width:80px;">${dt}</span>
        <button class="btn btn-secondary" style="padding:2px 8px;font-size:11px;" onclick="rollbackSnapshot('${esc(s.id)}')">Rollback</button>
      </div>`;
    }).join('');
}

async function rollbackSnapshot(snapshotId) {
  if (!confirm('Config auf diesen Snapshot zuruecksetzen?')) return;
  try {
    const result = await api('/api/ui/rollback', 'POST', {snapshot_id: snapshotId});
    if (result.success) {
      toast('Rollback erfolgreich: ' + result.message);
      // Settings neu laden
      S = await api('/api/ui/settings');
      renderCurrentTab();
      loadSnapshots();
    } else {
      toast('Rollback fehlgeschlagen: ' + result.message, 'error');
    }
  } catch(e) { toast('Rollback-Fehler', 'error'); }
}

// ---- Tab: Follow-Me ----

function renderFollowMe() {
  // Defaults setzen
  if (getPath(S, 'follow_me.enabled') === undefined) setPath(S, 'follow_me.enabled', false);
  if (!getPath(S, 'follow_me.cooldown_seconds')) setPath(S, 'follow_me.cooldown_seconds', 60);
  if (getPath(S, 'follow_me.transfer_music') === undefined) setPath(S, 'follow_me.transfer_music', true);
  if (getPath(S, 'follow_me.transfer_lights') === undefined) setPath(S, 'follow_me.transfer_lights', true);
  if (getPath(S, 'follow_me.transfer_climate') === undefined) setPath(S, 'follow_me.transfer_climate', false);

  return sectionWrap('&#128694;', 'Follow-Me',
    fInfo('JARVIS folgt dir von Raum zu Raum. Musik, Licht und Temperatur wechseln automatisch mit dir — wie im echten MCU.') +
    fToggle('follow_me.enabled', 'Follow-Me aktiv') +
    fRange('follow_me.cooldown_seconds', 'Mindestabstand zwischen Transfers', 30, 300, 10, {
      30:'30s', 60:'1 Min', 120:'2 Min', 180:'3 Min', 300:'5 Min'
    })
  ) +
  sectionWrap('&#127925;', 'Was soll folgen?',
    fInfo('Waehle aus welche Systeme dir von Raum zu Raum folgen sollen.') +
    fToggle('follow_me.transfer_music', 'Musik folgt') +
    fToggle('follow_me.transfer_lights', 'Licht folgt') +
    fToggle('follow_me.transfer_climate', 'Temperatur folgt')
  ) +
  sectionWrap('&#128100;', 'Personen-Profile',
    fInfo('Individuelle Einstellungen pro Person. Helligkeit, Farbtemperatur und Wunschtemperatur.') +
    renderFollowMeProfiles()
  );
}

function renderFollowMeProfiles() {
  const profiles = getPath(S, 'follow_me.profiles') || {};
  let html = '';

  for (const [name, p] of Object.entries(profiles)) {
    html += '<div class="s-card" style="margin-bottom:12px;padding:12px;">' +
      '<h4 style="margin:0 0 8px 0;">' + esc(name) + '</h4>' +
      fRange('follow_me.profiles.' + name + '.light_brightness', 'Helligkeit', 10, 100, 5, {
        10:'10%', 25:'25%', 50:'50%', 75:'75%', 100:'100%'
      }) +
      fNum('follow_me.profiles.' + name + '.light_color_temp', 'Farbtemperatur (Kelvin)', 2700, 6500) +
      fNum('follow_me.profiles.' + name + '.comfort_temp', 'Komfort-Temperatur', 16, 28) +
      '</div>';
  }

  // Button zum Hinzufuegen
  html += '<button class="btn btn-sm" onclick="addFollowMeProfile()" style="margin-top:8px;">' +
    '+ Profil hinzufuegen</button>';

  return html;
}

function addFollowMeProfile() {
  const name = prompt('Name der Person:');
  if (!name || !name.trim()) return;
  const key = name.trim();
  const profiles = getPath(S, 'follow_me.profiles') || {};
  if (profiles[key]) { alert('Profil existiert bereits.'); return; }
  profiles[key] = { light_brightness: 80, light_color_temp: 3500, comfort_temp: 22 };
  setPath(S, 'follow_me.profiles', profiles);
  renderCurrentTab();
}

// ---- Tab 9: Easter Eggs ----
let EGGS = [];

function renderEasterEggs() {
  let html = '<div id="easterEggsList"></div>';
  html += '<div style="margin-top:16px;text-align:center;">';
  html += '<button class="btn btn-primary" onclick="addEasterEgg()">+ Neues Easter Egg</button>';
  html += '</div>';
  return html;
}

async function loadEasterEggs() {
  try {
    const data = await api('/api/ui/easter-eggs');
    EGGS = data.easter_eggs || [];
    renderEggList();
  } catch(e) { console.error('Easter Eggs fail:', e); }
}

function renderEggList() {
  const c = document.getElementById('easterEggsList');
  if (!c) return;
  if (EGGS.length === 0) {
    c.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);">Keine Easter Eggs vorhanden</div>';
    return;
  }
  c.innerHTML = EGGS.map((egg, i) => `
    <div class="s-section">
      <div class="s-section-hdr" onclick="toggleSec(this)" style="cursor:pointer;">
        <h3>${egg.enabled !== false ? '&#127866;' : '&#128683;'} ${esc(egg.id)}</h3>
        <span class="arrow">&#9660;</span>
      </div>
      <div class="s-section-body">
        <div class="form-group"><label>ID</label>
          <input type="text" value="${esc(egg.id)}" onchange="EGGS[${i}].id=this.value"></div>
        <div class="form-group"><label>Aktiviert</label>
          <label class="toggle"><input type="checkbox" ${egg.enabled!==false?'checked':''} onchange="EGGS[${i}].enabled=this.checked">
          <span class="toggle-track"></span><span class="toggle-thumb"></span></label></div>
        <div class="form-group"><label>Trigger (einer pro Zeile)</label>
          <textarea rows="3" onchange="EGGS[${i}].triggers=this.value.split('\\n').map(s=>s.trim()).filter(Boolean)">${esc((egg.triggers||[]).join('\n'))}</textarea>
          <div class="hint">Substring-Matching, case-insensitive</div></div>
        <div class="form-group"><label>Antworten (eine pro Zeile)</label>
          <textarea rows="4" onchange="EGGS[${i}].responses=this.value.split('\\n').map(s=>s.trim()).filter(Boolean)">${esc((egg.responses||[]).join('\n'))}</textarea>
          <div class="hint">Zufaellige Auswahl</div></div>
        <div style="text-align:right;margin-top:8px;">
          <button class="btn btn-secondary" style="background:var(--danger);border-color:var(--danger);" onclick="removeEgg(${i})">Entfernen</button>
        </div>
      </div>
    </div>`).join('');
  c.innerHTML += '<div style="margin-top:16px;text-align:center;">' +
    '<button class="btn btn-primary" onclick="saveEasterEggs()">Easter Eggs speichern</button></div>';
}

function addEasterEgg() {
  EGGS.push({id: 'neues_egg_' + Date.now(), triggers: [], responses: [], enabled: true});
  renderEggList();
}

function removeEgg(idx) {
  EGGS.splice(idx, 1);
  renderEggList();
}

async function saveEasterEggs() {
  try {
    await api('/api/ui/easter-eggs', 'PUT', {easter_eggs: EGGS});
    toast('Easter Eggs gespeichert');
  } catch(e) { toast('Fehler beim Speichern', 'error'); }
}

// ---- Collect + Save ----
function collectSettings() {
  const updates = {};
  // Text, number, select
  document.querySelectorAll('#settingsContent [data-path]').forEach(el => {
    const path = el.dataset.path;
    const tag = el.tagName.toLowerCase();
    if (tag === 'div') return; // kw-editor handled separately
    let val;
    if (el.type === 'checkbox') {
      val = el.checked;
    } else if (el.type === 'number' || el.type === 'range') {
      val = parseFloat(el.value);
      if (Number.isInteger(val) && el.step && !String(el.step).includes('.')) val = parseInt(el.value);
    } else if (tag === 'textarea') {
      const raw = el.value.trim();
      if (el.dataset.type === 'array') {
        val = raw.split('\n').map(l=>l.trim()).filter(Boolean);
      } else if (el.dataset.type === 'json') {
        // Round-trip JSON objects
        try { val = JSON.parse(raw); } catch(e) { val = raw; }
      } else {
        // Try YAML-like map parsing (only for simple key: value lines)
        try {
          const lines = raw.split('\n').filter(l=>l.trim());
          const isMap = lines.length > 0 && lines.every(l => /^[a-zA-Z0-9_.-]+\s*:/.test(l));
          if (isMap) {
            val = {};
            for (const line of lines) {
              const [k,...rest] = line.split(':');
              val[k.trim()] = rest.join(':').trim().replace(/^["']|["']$/g,'');
            }
          } else {
            val = raw;
          }
        } catch(e) { val = raw; }
      }
    } else {
      val = el.value;
    }
    setPath(updates, path, val);
  });
  // Keywords (kw-editor divs) - already maintained in S
  document.querySelectorAll('#settingsContent .kw-editor[data-path]').forEach(el => {
    const path = el.dataset.path;
    const arr = getPath(S, path) || [];
    setPath(updates, path, arr);
  });
  // Key-Value editors (kv-editor divs) - collect from DOM
  document.querySelectorAll('#settingsContent .kv-editor[data-path]').forEach(el => {
    const path = el.dataset.path;
    const obj = {};
    el.querySelectorAll('.kv-row').forEach(row => {
      const k = row.querySelector('.kv-key').value.trim();
      const v = row.querySelector('.kv-val').value.trim();
      if (k) obj[k] = v;
    });
    setPath(updates, path, obj);
  });
  // Chip-Selects - already maintained in S via toggleChip()
  document.querySelectorAll('#settingsContent .chip-grid[data-path]').forEach(el => {
    const path = el.dataset.path;
    const arr = getPath(S, path) || [];
    setPath(updates, path, arr);
  });
  // Household members (dynamic list)
  if (document.getElementById('householdMembers')) {
    setPath(updates, 'household.members', collectHouseholdMembers());
  }
  // Monitored entities (device health entity picker)
  if (document.getElementById('entityPickerContainer')) {
    setPath(updates, 'device_health.monitored_entities', collectMonitoredEntities());
  }
  // Diagnostik monitored entities
  if (document.getElementById('diagEntityPickerContainer')) {
    const diagEnts = collectDiagEntities();
    if (diagEnts.length > 0) setPath(updates, 'diagnostics.monitored_entities', diagEnts);
  }
  // Room-Entity-Maps (room_speakers, room_motion_sensors)
  document.querySelectorAll('#settingsContent .room-entity-map[data-path]').forEach(container => {
    const path = container.dataset.path;
    const map = {};
    container.querySelectorAll('input[data-room-map]').forEach(input => {
      const room = input.dataset.roomName;
      const val = input.value.trim();
      if (room && val) map[room] = val;
    });
    setPath(updates, path, map);
  });
  // Entity-Picker lists (activity.entities.*)  - maintained in S via entityPickSelect/rmEntityPick
  document.querySelectorAll('#settingsContent [data-entity-picker="list"]').forEach(el => {
    const path = el.dataset.path;
    const arr = getPath(S, path) || [];
    setPath(updates, path, arr);
  });
  // Person-Profiles
  const profileContainer = document.querySelector('#settingsContent .person-profiles-container');
  if (profileContainer) {
    const profiles = {};
    profileContainer.querySelectorAll('[data-person-profile]').forEach(el => {
      const person = el.dataset.personProfile;
      const field = el.dataset.profileField;
      if (!profiles[person]) profiles[person] = {};
      profiles[person][field] = el.tagName === 'SELECT' ? el.value : el.value.trim();
    });
    // Leere Felder entfernen
    for (const [p, fields] of Object.entries(profiles)) {
      for (const [k, v] of Object.entries(fields)) { if (!v) delete fields[k]; }
      if (Object.keys(fields).length === 0) delete profiles[p];
    }
    setPath(updates, 'person_profiles.profiles', profiles);
  }
  // Person-Titles (data-person-title inputs)
  const titlesContainer = document.querySelector('#settingsContent .person-titles-container');
  if (titlesContainer) {
    const titles = {};
    titlesContainer.querySelectorAll('[data-person-title]').forEach(el => {
      const person = el.dataset.personTitle;
      const val = el.value.trim();
      if (person && val) titles[person] = val;
    });
    setPath(updates, 'persons.titles', titles);
  }
  // Emergency Protocols — actions are maintained directly in S by add/remove functions
  if (S.emergency_protocols) {
    setPath(updates, 'emergency_protocols', JSON.parse(JSON.stringify(S.emergency_protocols)));
  }
  return updates;
}

let _saving = false;
async function saveAllSettings() {
  if (_saving) return;
  _saving = true;
  try {
    // Erst aktuelle Tab-Werte in S uebernehmen, dann S als Basis nutzen
    const tabUpdates = collectSettings();
    deepMerge(S, tabUpdates);
    // Vollstaendiges Settings-Objekt senden (nicht nur aktiven Tab)
    const updates = JSON.parse(JSON.stringify(S));
    const result = await api('/api/ui/settings', 'PUT', {settings: updates});
    if (result && result.restart_needed) {
      toast('Gespeichert — Container-Neustart noetig fuer Sprach-Engine!', 'warning');
    } else {
      toast('Einstellungen gespeichert');
    }
  } catch(e) {
    toast('Fehler beim Speichern', 'error');
  } finally {
    _saving = false;
  }
}

// ---- Presence ----
let _presenceInterval = null;
let _presenceSettings = {};

function startPresenceRefresh() {
  stopPresenceRefresh();
  _presenceInterval = setInterval(() => { loadPresencePersons(); }, 15000);
}
function stopPresenceRefresh() {
  if (_presenceInterval) { clearInterval(_presenceInterval); _presenceInterval = null; }
}

async function loadPresence() {
  await Promise.all([loadPresencePersons(), loadPresenceSettings()]);
}

async function loadPresencePersons() {
  try {
    const d = await api('/api/ui/presence');
    const persons = d.persons || [];
    const home = d.home_count || 0;
    const away = d.away_count || 0;
    const unknown = d.unknown_count || 0;

    // Summary cards
    document.getElementById('presenceSummary').innerHTML = `
      <div class="card" style="text-align:center;padding:20px;">
        <div style="font-size:32px;font-weight:700;color:var(--success);">${home}</div>
        <div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;">Zuhause</div>
      </div>
      <div class="card" style="text-align:center;padding:20px;">
        <div style="font-size:32px;font-weight:700;color:#f59e0b;">${away}</div>
        <div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;">Unterwegs</div>
      </div>
      <div class="card" style="text-align:center;padding:20px;">
        <div style="font-size:32px;font-weight:700;color:var(--text-muted);">${unknown}</div>
        <div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;">Unbekannt</div>
      </div>`;

    // Person cards
    if (persons.length === 0) {
      document.getElementById('presencePersons').innerHTML = `
        <div class="card" style="grid-column:1/-1;text-align:center;padding:32px;color:var(--text-muted);">
          <div style="font-size:36px;margin-bottom:12px;">&#128100;</div>
          <div style="font-weight:600;">Keine Personen in Home Assistant gefunden</div>
          <div style="font-size:13px;margin-top:8px;">Erstelle Person-Entities in HA unter Einstellungen &rarr; Personen und verknuepfe sie mit Device-Trackern.</div>
        </div>`;
      return;
    }

    let html = '';
    for (const p of persons) {
      const isHome = p.state === 'home';
      const isAway = p.state === 'not_home';
      const color = isHome ? 'var(--success)' : isAway ? '#f59e0b' : 'var(--text-muted)';
      const icon = isHome ? '&#127968;' : isAway ? '&#128694;' : '&#10067;';
      const label = isHome ? 'Zuhause' : isAway ? 'Unterwegs' : 'Unbekannt';
      const glow = isHome ? 'box-shadow:0 0 12px rgba(0,230,118,0.2);' : '';
      html += `
        <div class="card" style="padding:16px;border-left:3px solid ${color};${glow}">
          <div style="display:flex;align-items:center;gap:12px;">
            <div style="width:44px;height:44px;border-radius:50%;background:${color}15;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;">${icon}</div>
            <div style="flex:1;min-width:0;">
              <div style="font-weight:700;font-size:15px;">${esc(p.name)}</div>
              <div style="display:flex;align-items:center;gap:6px;margin-top:3px;">
                <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;${isHome ? 'box-shadow:0 0 6px ' + color + ';' : ''}"></span>
                <span style="font-size:13px;color:${color};font-weight:500;">${label}</span>
              </div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:4px;font-family:var(--mono);">${esc(p.entity_id)}</div>
              ${p.source ? `<div style="font-size:11px;color:var(--text-muted);">Tracker: ${esc(p.source)}</div>` : ''}
            </div>
          </div>
        </div>`;
    }
    document.getElementById('presencePersons').innerHTML = html;
  } catch (e) {
    document.getElementById('presencePersons').innerHTML = `<div class="card" style="grid-column:1/-1;padding:16px;color:var(--danger);">Fehler beim Laden: ${esc(e.message)}</div>`;
  }
}

async function loadPresenceSettings() {
  try {
    const d = await api('/api/ui/presence/settings');
    _presenceSettings = d || {};
    renderPresenceSettings();
  } catch (e) {
    document.getElementById('presenceSettings').innerHTML = `<div style="color:var(--danger);">Einstellungen konnten nicht geladen werden: ${esc(e.message)}</div>`;
  }
}

function renderPresenceSettings() {
  const s = _presenceSettings;
  const autoEnabled = s.presence_auto_detect_enabled === 'true';
  const manualOverride = s.presence_manual_override === 'true';
  const treatUnavailable = s.presence_treat_unavailable_as_away === 'true';
  const guestThreshold = parseInt(s.presence_guest_threshold) || 2;
  const awayMinutes = parseInt(s.presence_away_device_minutes) || 120;
  const bufferMinutes = parseInt(s.presence_buffer_minutes) || 5;

  document.getElementById('presenceSettings').innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-weight:600;font-size:14px;">Auto-Erkennung</div>
          <div style="font-size:12px;color:var(--text-muted);">Automatische Anwesenheitserkennung anhand von HA Person-Entities</div>
        </div>
        <button class="btn btn-sm ${autoEnabled ? 'btn-primary' : 'btn-secondary'}" onclick="togglePresenceSetting('presence_auto_detect_enabled', ${!autoEnabled})">${autoEnabled ? 'ON' : 'OFF'}</button>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-weight:600;font-size:14px;">Manuelle Uebersteuerung</div>
          <div style="font-size:12px;color:var(--text-muted);">Auto-Erkennung pausieren</div>
        </div>
        <button class="btn btn-sm ${manualOverride ? 'btn-primary' : 'btn-secondary'}" onclick="togglePresenceSetting('presence_manual_override', ${!manualOverride})">${manualOverride ? 'ON' : 'OFF'}</button>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <div style="font-weight:600;font-size:14px;">Besuch-Schwelle</div>
          <span style="font-weight:700;color:var(--accent);font-size:16px;">${guestThreshold}</span>
        </div>
        <input type="range" min="2" max="10" step="1" value="${guestThreshold}" style="width:100%;accent-color:var(--accent);"
          onchange="updatePresenceSetting('presence_guest_threshold', this.value)">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);"><span>2 Personen</span><span>10 Personen</span></div>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <div style="font-weight:600;font-size:14px;">Abwesenheits-Timer</div>
          <span style="font-weight:700;color:var(--accent);font-size:16px;">${awayMinutes} min</span>
        </div>
        <input type="range" min="15" max="480" step="15" value="${awayMinutes}" style="width:100%;accent-color:var(--accent);"
          onchange="updatePresenceSetting('presence_away_device_minutes', this.value)">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);"><span>15 min</span><span>8 Std</span></div>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <div style="font-weight:600;font-size:14px;">Puffer-Zeit</div>
          <span style="font-weight:700;color:var(--accent);font-size:16px;">${bufferMinutes} min</span>
        </div>
        <input type="range" min="0" max="30" step="1" value="${bufferMinutes}" style="width:100%;accent-color:var(--accent);"
          onchange="updatePresenceSetting('presence_buffer_minutes', this.value)">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);"><span>0 min</span><span>30 min</span></div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-weight:600;font-size:14px;">"Nicht erreichbar" = Abwesend</div>
          <div style="font-size:12px;color:var(--text-muted);">Wenn Person-Entity nicht erreichbar (z.B. Handy-Akku leer)</div>
        </div>
        <button class="btn btn-sm ${treatUnavailable ? 'btn-primary' : 'btn-secondary'}" onclick="togglePresenceSetting('presence_treat_unavailable_as_away', ${!treatUnavailable})">${treatUnavailable ? 'ON' : 'OFF'}</button>
      </div>
    </div>
    <div style="margin-top:16px;padding:12px;background:var(--bg-secondary);border-radius:var(--radius-md);border:1px solid var(--border);font-size:12px;color:var(--text-muted);">
      &#9432; Die Erkennung basiert auf person.* Entities aus Home Assistant. Verknuepfe Personen mit Device-Trackern (Companion App, Router, Bluetooth).
    </div>`;
}

async function togglePresenceSetting(key, value) {
  try {
    await api('/api/ui/presence/settings', 'PUT', { [key]: String(value) });
    _presenceSettings[key] = String(value);
    renderPresenceSettings();
    toast('Einstellung gespeichert');
  } catch (e) {
    toast('Fehler: ' + e.message, 'error');
  }
}

async function updatePresenceSetting(key, value) {
  try {
    await api('/api/ui/presence/settings', 'PUT', { [key]: String(value) });
    _presenceSettings[key] = String(value);
    renderPresenceSettings();
    toast('Einstellung gespeichert');
  } catch (e) {
    toast('Fehler: ' + e.message, 'error');
  }
}


// ---- Entities ----
async function loadEntities() {
  try {
    const data = await api('/api/ui/entities');
    ALL_ENTITIES = data.entities || [];
    const domains = [...new Set(ALL_ENTITIES.map(e => e.domain))].sort();
    const sel = document.getElementById('entityDomainFilter');
    sel.innerHTML = `<option value="">Alle Domains (${ALL_ENTITIES.length})</option>`;
    for (const d of domains) {
      const c = ALL_ENTITIES.filter(e => e.domain === d).length;
      sel.innerHTML += `<option value="${esc(d)}">${esc(d)} (${c})</option>`;
    }
    filterEntities();
  } catch(e) { console.error('Entities fail:', e); }
}

function filterEntities() {
  const domain = document.getElementById('entityDomainFilter').value;
  const search = document.getElementById('entitySearchInput').value.toLowerCase();
  let filtered = ALL_ENTITIES;
  if (domain) filtered = filtered.filter(e => e.domain === domain);
  if (search) filtered = filtered.filter(e => e.entity_id.toLowerCase().includes(search) || e.name.toLowerCase().includes(search));
  const show = filtered.slice(0, 100);
  const c = document.getElementById('entityBrowser');
  c.innerHTML = show.map(e => `
    <div class="entity-item" onclick="navigator.clipboard?.writeText('${esc(e.entity_id)}');toast('${esc(e.entity_id)} kopiert')">
      <span class="ename">${esc(e.name)}</span>
      <span class="eid">${esc(e.entity_id)}</span>
      <span style="color:var(--text-muted);font-size:11px;">${esc(e.state)}</span>
    </div>`).join('');
  if (filtered.length > 100) c.innerHTML += `<div style="padding:10px;text-align:center;color:var(--text-muted);font-size:11px;">...und ${filtered.length-100} weitere</div>`;
}

// ---- Knowledge ----
async function loadKnowledge() {
  try {
    const d = await api('/api/ui/knowledge');
    const st = d.stats || {}, fi = d.files || [];
    document.getElementById('kbStats').innerHTML = `
      <div class="stat-card"><div class="stat-label">Status</div>
        <div class="stat-value" style="font-size:18px;color:${st.enabled?'var(--success)':'var(--danger)'};">${st.enabled?'Aktiv':'Aus'}</div></div>
      <div class="stat-card"><div class="stat-label">Chunks</div><div class="stat-value">${st.total_chunks||0}</div></div>
      <div class="stat-card"><div class="stat-label">Quellen</div><div class="stat-value">${(st.sources||[]).length}</div>
        <div class="stat-sub">${(st.sources||[]).map(s=>esc(s)).join(', ')||'keine'}</div></div>`;
    document.getElementById('kbFiles').innerHTML = fi.length === 0
      ? '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Dateien</div>'
      : fi.map(f => `<div class="file-item" style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border);">
          <span style="font-size:16px;">&#128196;</span>
          <span class="file-name" style="flex:1;min-width:0;">${esc(f.name)}</span>
          <span class="file-size" style="color:var(--text-muted);font-size:12px;white-space:nowrap;">${fmtBytes(f.size)}</span>
          <button class="btn" onclick="reingestFile('${esc(f.name)}')" style="font-size:11px;padding:3px 10px;white-space:nowrap;" title="Chunks loeschen und Datei neu einlesen">Neu einlesen</button>
          <button class="btn btn-danger" onclick="deleteFileChunks('${esc(f.name)}')" style="font-size:11px;padding:3px 10px;white-space:nowrap;" title="Alle Chunks dieser Datei loeschen">Entfernen</button>
        </div>`).join('');
    // Quellen-Filter befuellen
    const sel = document.getElementById('kbSourceFilter');
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = '<option value="">Alle Quellen</option>' +
        (st.sources||[]).map(s => `<option value="${esc(s)}" ${s===cur?'selected':''}>${esc(s)}</option>`).join('');
    }
    loadKbChunks();
  } catch(e) { console.error('KB fail:', e); }
}
// ---- Knowledge Rebuild ----
async function rebuildKnowledge() {
  if (!confirm('Wissensdatenbank komplett neu aufbauen?\n\nAlle Vektoren werden geloescht und mit dem aktuellen Embedding-Modell neu berechnet. Das kann einige Minuten dauern.')) return;
  try {
    toast('Rebuild gestartet...', 'info');
    const d = await api('/api/ui/knowledge/rebuild', 'POST');
    if (d.success) {
      toast(`Rebuild fertig: ${d.new_chunks} Chunks mit ${d.embedding_model}`, 'success');
    } else {
      toast(d.error || 'Rebuild fehlgeschlagen', 'error');
    }
    loadKnowledge();
  } catch(e) { toast('Rebuild fehlgeschlagen', 'error'); }
}

// ---- Knowledge Upload ----
async function uploadKbFile(file) {
  if (!file) return;
  const allowed = ['.txt','.md','.pdf','.csv'];
  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (!allowed.includes(ext)) { toast('Dateityp nicht erlaubt. Nur: ' + allowed.join(', '), 'error'); return; }
  if (file.size > 10 * 1024 * 1024) { toast('Datei zu gross (max 10 MB)', 'error'); return; }

  const dz = document.getElementById('kbDropzone');
  if (dz) { dz.style.borderColor = 'var(--primary)'; dz.querySelector('div').textContent = 'Wird hochgeladen...'; }

  const fd = new FormData();
  fd.append('file', file);
  fd.append('token', sessionStorage.getItem('token') || '');

  try {
    const resp = await fetch('/api/ui/knowledge/upload', { method: 'POST', body: fd });
    if (!resp.ok) { const e = await resp.json().catch(() => ({})); throw new Error(e.detail || 'Upload fehlgeschlagen'); }
    const d = await resp.json();
    toast(`"${d.filename}" hochgeladen — ${d.new_chunks} Chunks eingelesen`, 'success');
    loadKnowledge();
  } catch(e) { toast(e.message || 'Upload fehlgeschlagen', 'error'); }
  finally {
    if (dz) { dz.style.borderColor = ''; dz.querySelector('div').textContent = '\u{1F4E4}'; }
    const inp = document.getElementById('kbFileInput');
    if (inp) inp.value = '';
  }
}

function initKbDropzone() {
  const dz = document.getElementById('kbDropzone');
  if (!dz || dz.dataset.init) return;
  dz.dataset.init = '1';
  ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.style.borderColor = 'var(--primary)'; dz.style.background = 'var(--bg-secondary)'; }));
  ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.style.borderColor = ''; dz.style.background = ''; }));
  dz.addEventListener('drop', e => { if (e.dataTransfer.files.length) uploadKbFile(e.dataTransfer.files[0]); });
}

async function ingestKnowledge() {
  try {
    const d = await api('/api/ui/knowledge/ingest', 'POST');
    toast(`${d.new_chunks} neue Chunks eingelesen`);
    loadKnowledge();
  } catch(e) { toast('Fehler beim Einlesen', 'error'); }
}

// ---- Knowledge File Actions ----
async function deleteFileChunks(filename) {
  if (!confirm(`Alle Wissensinhalte von "${filename}" aus der Datenbank entfernen?`)) return;
  try {
    const d = await api('/api/ui/knowledge/file/delete', 'POST', { filename });
    toast(`${d.deleted} Chunks von "${filename}" entfernt`, 'success');
    loadKnowledge();
  } catch(e) { toast('Fehler beim Entfernen', 'error'); }
}

async function reingestFile(filename) {
  try {
    toast(`"${filename}" wird neu eingelesen...`);
    const d = await api('/api/ui/knowledge/file/reingest', 'POST', { filename });
    toast(`"${filename}": ${d.new_chunks} Chunks eingelesen`, 'success');
    loadKnowledge();
  } catch(e) { toast('Fehler beim Einlesen', 'error'); }
}

// ---- Knowledge Chunks ----
let kbChunksData = [];

async function loadKbChunks() {
  try {
    const src = document.getElementById('kbSourceFilter')?.value || '';
    const params = src ? `&source=${encodeURIComponent(src)}` : '';
    const d = await api(`/api/ui/knowledge/chunks?limit=200${params}`);
    kbChunksData = d.chunks || [];
    const c = document.getElementById('kbChunks');
    if (!c) return;
    if (kbChunksData.length === 0) {
      c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Eintraege</div>';
      return;
    }
    c.innerHTML = kbChunksData.map((ch, i) => `
      <div class="chunk-item" style="display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-bottom:1px solid var(--border);${i%2?'background:var(--bg-secondary);':''}">
        <input type="checkbox" class="kb-chunk-cb" data-id="${esc(ch.id)}" onchange="updateKbDeleteBtn()" style="margin-top:3px;min-width:16px;" />
        <div style="flex:1;min-width:0;">
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:2px;">${esc(ch.source)} #${ch.chunk_index}</div>
          <div style="font-size:13px;line-height:1.4;word-break:break-word;">${esc(ch.content)}</div>
        </div>
      </div>
    `).join('');
  } catch(e) { console.error('KB chunks fail:', e); }
}

function updateKbDeleteBtn() {
  const checked = document.querySelectorAll('.kb-chunk-cb:checked');
  const btn = document.getElementById('kbDeleteBtn');
  if (btn) btn.style.display = checked.length > 0 ? '' : 'none';
  if (btn && checked.length > 0) btn.textContent = `${checked.length} loeschen`;
}

async function deleteSelectedChunks() {
  const checked = document.querySelectorAll('.kb-chunk-cb:checked');
  if (checked.length === 0) return;
  if (!confirm(`${checked.length} Wissenseintraege unwiderruflich loeschen?`)) return;
  const ids = Array.from(checked).map(cb => cb.dataset.id);
  try {
    const d = await api('/api/ui/knowledge/chunks/delete', 'POST', { ids });
    toast(`${d.deleted} Eintraege geloescht`, 'success');
    loadKnowledge();
  } catch(e) { toast('Fehler beim Loeschen', 'error'); }
}

// ---- Logs & Audit ----
let currentLogTab = 'conversations';

function switchLogTab(tab) {
  currentLogTab = tab;
  document.querySelectorAll('#logsTabBar .tab-item').forEach(t => t.classList.toggle('active', t.dataset.logtab===tab));
  document.getElementById('logsContainer').style.display = tab==='conversations' ? '' : 'none';
  document.getElementById('protocolContainer').style.display = tab==='protocol' ? '' : 'none';
  document.getElementById('protocolFilters').style.display = tab==='protocol' ? '' : 'none';
  document.getElementById('auditContainer').style.display = tab==='audit' ? '' : 'none';
  if (tab==='conversations') loadLogs();
  else if (tab==='protocol') loadProtocol();
  else loadAudit();
}

// ---- Protokoll (Jarvis Action Protocol with Filters) ----
let _protocolData = [];
let _protocolLiveIv = null;

async function loadProtocol() {
  const type = document.getElementById('protocolType').value;
  const period = document.getElementById('protocolPeriod').value;
  const c = document.getElementById('protocolContainer');
  if (!c) return;
  try {
    // tts and notification are pseudo-types — filter client-side from jarvis_action
    const isClientFilter = (type === 'tts' || type === 'notification');
    const apiType = isClientFilter ? '' : type;
    const params = `limit=200&period=${period}` + (apiType ? `&type=${apiType}` : '');
    const d = await api('/api/ui/action-log?' + params);
    let items = d.items || [];
    // Client-side filter for TTS/notification pseudo-types
    if (type === 'tts') {
      items = items.filter(log => {
        const func = (log.action_data || {}).function || '';
        return func === 'announce_tts' || func === 'tts' || func === 'play_tts' || func === 'speak';
      });
    } else if (type === 'notification') {
      items = items.filter(log => {
        const func = (log.action_data || {}).function || '';
        return func === 'send_notification' || func === 'notify';
      });
    }
    _protocolData = items;
    filterProtocol();
  } catch(e) {
    c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--danger);">Fehler: ' + esc(e.message) + '</div>';
  }
}

function filterProtocol() {
  const search = (document.getElementById('protocolSearch').value || '').toLowerCase();
  const c = document.getElementById('protocolContainer');
  if (!c) return;

  const filtered = _protocolData.filter(log => {
    if (!search) return true;
    const ad = log.action_data || {};
    const haystack = [
      log.reason || '',
      log.action_type || '',
      ad.function || '',
      JSON.stringify(ad.arguments || {}),
      ad.result || ''
    ].join(' ').toLowerCase();
    return haystack.includes(search);
  });

  document.getElementById('protocolCount').textContent = filtered.length +
    (_protocolData.length !== filtered.length ? ' / ' + _protocolData.length : '') + ' Eintraege';

  if (filtered.length === 0) {
    c.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);">' +
      (search ? 'Keine Treffer fuer "' + esc(search) + '"' : 'Keine Jarvis-Aktionen im Zeitraum.') + '</div>';
    return;
  }

  const typeIcons = {
    jarvis_action: '&#9889;', automation: '&#129302;', observation: '&#128065;',
    quick_action: '&#9889;', suggestion: '&#128161;', anomaly: '&#9888;',
    system: '&#9881;', first_time: '&#11088;'
  };
  const typeLabels = {
    jarvis_action: 'Jarvis', automation: 'Automation', observation: 'Beobachtung',
    quick_action: 'Schnellaktion', suggestion: 'Vorschlag', anomaly: 'Anomalie',
    system: 'System', first_time: 'Erstmalig'
  };
  const typeColors = {
    jarvis_action: 'var(--accent)', automation: 'var(--warning, #f59e0b)',
    observation: 'var(--text-muted)', quick_action: 'var(--info, #3b82f6)',
    suggestion: 'var(--accent)', anomaly: 'var(--danger, #ef4444)',
    system: 'var(--text-secondary)', first_time: 'var(--success, #22c55e)'
  };
  const funcIcons = {
    set_light: '&#128161;', set_cover: '&#129695;', set_climate: '&#127777;',
    activate_scene: '&#127912;', play_media: '&#127925;', send_notification: '&#128276;',
    announce_tts: '&#128266;', tts: '&#128266;', play_tts: '&#128266;', speak: '&#128266;',
    notify: '&#128276;', call_service: '&#9881;'
  };
  const funcLabels = {
    send_notification: 'Benachrichtigung', announce_tts: 'Durchsage',
    tts: 'Durchsage', play_tts: 'Durchsage', speak: 'Durchsage', notify: 'Benachrichtigung'
  };

  c.innerHTML = filtered.map(log => {
    const ad = log.action_data || {};
    const func = ad.function || '';
    const args = ad.arguments || {};
    const result = ad.result || '';
    const reason = log.reason || '';
    const aType = log.action_type || 'system';
    const icon = func ? (funcIcons[func] || typeIcons[aType] || '&#9889;') : (typeIcons[aType] || '&#9889;');
    const label = funcLabels[func] || typeLabels[aType] || aType;
    const color = typeColors[aType] || 'var(--text-muted)';

    // Beschreibung zusammenbauen
    const parts = [];
    if (func) parts.push('<strong>' + esc(func.replace(/_/g, ' ')) + '</strong>');
    if (args.entity_id) parts.push(esc(args.entity_id));
    if (args.room) parts.push(esc(args.room));
    if (args.message) parts.push('"' + esc(args.message.length > 80 ? args.message.substring(0,80) + '...' : args.message) + '"');
    if (args.brightness !== undefined) parts.push(args.brightness + '%');
    if (args.position !== undefined) parts.push(args.position + '%');
    if (args.state) parts.push(esc(args.state));
    if (args.temperature !== undefined) parts.push(args.temperature + '\u00b0C');
    if (args.target) parts.push(esc(args.target));
    const desc = parts.length > 0 ? parts.join(' \u2014 ') : esc(reason.substring(0, 120));
    // LLM response text (if available)
    const llmResponse = ad.response || '';

    const ts = log.created_at
      ? new Date(log.created_at).toLocaleString('de-DE', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'})
      : '';

    return '<div class="log-entry" style="align-items:flex-start;">' +
      '<span class="log-time">' + ts + '</span>' +
      '<span style="font-size:18px;min-width:28px;text-align:center;">' + icon + '</span>' +
      '<div style="flex:1;min-width:0;">' +
        '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">' +
          '<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:color-mix(in srgb, ' + color + ' 15%, transparent);color:' + color + ';font-weight:600;">' + esc(label) + '</span>' +
          '<span style="font-size:13px;">' + desc + '</span>' +
        '</div>' +
        (result ? '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">\u2192 ' + esc(result.length > 100 ? result.substring(0,100) + '...' : result) + '</div>' : '') +
        (llmResponse ? '<div style="font-size:11px;color:var(--info);margin-top:2px;">&#129302; ' + esc(llmResponse.length > 120 ? llmResponse.substring(0,120) + '...' : llmResponse) + '</div>' : '') +
        (reason && parts.length > 0 ? '<div style="font-size:11px;color:var(--text-muted);font-style:italic;margin-top:1px;">' + esc(reason.length > 100 ? reason.substring(0,100) + '...' : reason) + '</div>' : '') +
      '</div>' +
      (log.was_undone ? '<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:var(--warning);color:#000;font-weight:600;">Rueckgaengig</span>' : '') +
    '</div>';
  }).join('');
}

function toggleProtocolLive() {
  const live = document.getElementById('protocolLive').checked;
  if (live) {
    loadProtocol();
    _protocolLiveIv = setInterval(loadProtocol, 10000);
  } else {
    if (_protocolLiveIv) { clearInterval(_protocolLiveIv); _protocolLiveIv = null; }
  }
}

async function loadAudit() {
  try {
    const d = await api('/api/ui/audit?limit=100');
    const entries = d.entries || [];
    const c = document.getElementById('auditContainer');
    if (entries.length === 0) {
      c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Audit-Eintraege</div>';
      return;
    }
    c.innerHTML = entries.map(e => {
      const t = e.timestamp ? new Date(e.timestamp).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
      const act = e.action || '';
      const cat = act.includes('login')||act.includes('pin')||act.includes('setup') ? 'auth'
        : act.includes('security')||act.includes('api_key')||act.includes('recovery') ? 'security'
        : act.includes('settings')||act.includes('autonomy')||act.includes('easter')||act.includes('notification') ? 'settings'
        : 'system';
      const details = e.details ? Object.entries(e.details).map(([k,v])=>`${k}: ${typeof v==='object'?JSON.stringify(v):v}`).join(', ') : '';
      return `<div class="audit-entry"><span class="audit-time">${t}</span><span class="audit-action ${cat}">${esc(act)}</span><span class="audit-details">${esc(details)}</span></div>`;
    }).join('');
  } catch(e) { console.error('Audit fail:', e); }
}

async function loadLogs() {
  try {
    const d = await api('/api/ui/logs?limit=200');
    const convs = d.conversations || [];
    const c = document.getElementById('logsContainer');
    if (convs.length === 0) { c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Gespraeche</div>'; return; }
    c.innerHTML = convs.map(cv => {
      const t = cv.timestamp ? new Date(cv.timestamp).toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'}) : '';
      const role = cv.role || 'system';
      return `<div class="log-entry"><span class="log-time">${t}</span><span class="log-role ${role}">${role}</span><span class="log-content">${esc(cv.content||'')}</span></div>`;
    }).join('');
  } catch(e) { console.error('Logs fail:', e); }
}

// ---- Fehlerspeicher ----
let _errFilter = '';

function filterErrors(level) {
  _errFilter = level;
  document.getElementById('errFilterAll').classList.toggle('active-filter', !level);
  document.getElementById('errFilterError').classList.toggle('active-filter', level==='ERROR');
  document.getElementById('errFilterWarn').classList.toggle('active-filter', level==='WARNING');
  loadErrors();
}

async function loadErrors() {
  try {
    const params = _errFilter ? `&level=${_errFilter}` : '';
    const d = await api(`/api/ui/errors?limit=200${params}`);
    const errs = d.errors || [];
    const c = document.getElementById('errorsContainer');
    if (errs.length === 0) {
      c.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);">Keine Fehler gespeichert</div>';
    } else {
      c.innerHTML = errs.map(e => {
        const t = e.timestamp ? new Date(e.timestamp).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
        return `<div class="err-entry level-${esc(e.level)}"><span class="err-time">${t}</span><span class="err-level ${esc(e.level)}">${esc(e.level)}</span><span class="err-logger" title="${esc(e.logger||'')}">${esc(e.logger||'')}</span><span class="err-msg">${esc(e.message||'')}</span></div>`;
      }).join('');
    }
    document.getElementById('errorsInfo').textContent = `${d.total} Eintraege gespeichert (max. 200)`;
    updateErrBadge(d.total);
  } catch(e) { console.error('Errors fail:', e); }
}

async function clearErrors() {
  if (!confirm('Fehlerspeicher wirklich leeren?')) return;
  try {
    await api('/api/ui/errors', 'DELETE');
    toast('Fehlerspeicher geleert');
    loadErrors();
  } catch(e) { toast('Fehler beim Leeren', 'error'); }
}

function updateErrBadge(count) {
  const b = document.getElementById('errBadge');
  if (count > 0) { b.textContent = count > 99 ? '99+' : count; b.style.display = 'inline-flex'; }
  else { b.style.display = 'none'; }
}

// Fehlerzahl beim Seitennavigation aktualisieren
async function refreshErrBadge() {
  try {
    const d = await api('/api/ui/errors?limit=1');
    updateErrBadge(d.total);
  } catch(e) {}
}

// ============================================================
// System-Tab (Update, Restart, Status)
// ============================================================

let _sysStatus = null;
// ---- Tab: Geräte-Überwachung ----
function renderCovers() {
  return sectionWrap('&#129695;', 'Rollläden & Garagentore',
    fInfo('Hier legst du fest, welche Geräte Rollläden sind und welche Garagentore. <strong>Garagentore werden NIEMALS automatisch von Jarvis gesteuert.</strong>') +
    '<div id="coverListContainer" style="color:var(--text-secondary);padding:12px;">Lade Cover-Geräte...</div>'
  );
}

async function loadCoverEntities() {
  try {
    const d = await api('/api/ui/covers');
    const covers = d.covers || [];
    const container = document.getElementById('coverListContainer');
    if (!container) return;

    if (covers.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Keine Cover-Geräte in Home Assistant gefunden.</div>';
      return;
    }

    let html = '';
    for (const c of covers) {
      const isGarage = c.cover_type === 'garage_door';
      const isDisabled = c.enabled === false;
      const borderColor = isGarage ? 'var(--danger)' : isDisabled ? 'var(--text-muted)' : 'var(--border)';
      const bgColor = isGarage ? 'rgba(239,68,68,0.08)' : isDisabled ? 'rgba(128,128,128,0.08)' : 'var(--bg-card)';
      const opacity = isDisabled ? '0.6' : '1';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;margin-bottom:6px;border-radius:8px;background:' + bgColor + ';border:1px solid ' + borderColor + ';opacity:' + opacity + ';">';
      html += '<div style="flex:1;min-width:0;margin-right:8px;">';
      html += '<div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + (isGarage ? '&#128274; ' : '') + esc(c.name) + '</div>';
      html += '<div style="font-size:10px;color:var(--text-muted);font-family:var(--mono);">' + esc(c.entity_id) + '</div>';
      html += '</div>';
      // Enable/Disable Toggle
      const toggleId = 'toggle_' + c.entity_id.replace(/\./g, '_');
      const checked = c.enabled !== false ? ' checked' : '';
      html += '<label style="display:flex;align-items:center;gap:4px;cursor:pointer;margin-right:8px;flex-shrink:0;" title="' + (isDisabled ? 'Deaktiviert — Jarvis steuert dieses Gerät NICHT' : 'Aktiv — Jarvis darf steuern') + '">';
      html += '<input type="checkbox" id="' + toggleId + '"' + checked + ' onchange="setCoverEnabled(\'' + esc(c.entity_id) + '\', this.checked)" style="width:16px;height:16px;accent-color:var(--accent);cursor:pointer;">';
      html += '<span style="font-size:11px;color:var(--text-secondary);">' + (isDisabled ? 'Aus' : 'An') + '</span>';
      html += '</label>';
      // Type Dropdown
      html += '<select onchange="setCoverType(\'' + esc(c.entity_id) + '\', this.value)" style="background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:12px;width:130px;flex-shrink:0;">';
      const types = [
        ['shutter', 'Rollladen'], ['blind', 'Jalousie'], ['awning', 'Markise'],
        ['roof_window', 'Dachfenster'], ['garage_door', '&#128274; Garagentor']
      ];
      for (const [val, label] of types) {
        html += '<option value="' + val + '"' + (c.cover_type === val ? ' selected' : '') + '>' + label + '</option>';
      }
      html += '</select></div>';
    }
    container.innerHTML = html;
  } catch (e) {
    const c = document.getElementById('coverListContainer');
    if (c) c.innerHTML = '<div style="color:var(--danger);padding:8px;">Fehler: ' + esc(e.message) + '</div>';
  }
}

async function setCoverType(entityId, coverType) {
  try {
    await api('/api/ui/covers/' + entityId + '/type', 'PUT', { cover_type: coverType });
    toast('Typ gespeichert');
    loadCoverEntities();
  } catch (e) {
    toast('Fehler beim Speichern: ' + e.message, 'error');
    console.error('Cover type save failed:', e);
  }
}

async function setCoverEnabled(entityId, enabled) {
  try {
    await api('/api/ui/covers/' + entityId + '/type', 'PUT', { enabled: enabled });
    toast(enabled ? 'Aktiviert — Jarvis darf steuern' : 'Deaktiviert — Jarvis ignoriert dieses Gerät');
    loadCoverEntities();
  } catch (e) {
    toast('Fehler beim Speichern: ' + e.message, 'error');
    console.error('Cover enabled save failed:', e);
  }
}

function renderDevices() {
  return sectionWrap('&#128268;', 'Geräteüberwachung',
    fInfo('Wähle welche Geräte der Health-Monitor überwacht. Wenn keine ausgewählt sind, werden alle Sensoren überwacht.') +
    fToggle('device_health.enabled', 'Health-Monitor aktiv') +
    fRange('device_health.check_interval_minutes', 'Prüfintervall', 15, 180, 15, {15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std'}) +
    fRange('device_health.alert_cooldown_minutes', 'Alert-Cooldown', 60, 2880, 60, {60:'1 Std',360:'6 Std',720:'12 Std',1440:'24 Std',2880:'48 Std'})
  ) +
  sectionWrap('&#127968;', 'Überwachte Entities',
    fInfo('Entities aus MindHome. Haken setzen = wird überwacht. Ohne Auswahl werden alle Entities der aktiven Domains geprüft.') +
    '<div id="entityPickerContainer" style="color:var(--text-secondary);padding:12px;">Lade Entities aus MindHome...</div>'
  ) +
  sectionWrap('&#128295;', 'Diagnostik',
    fInfo('Automatische Pruefung von Sensoren, Batterien und Geraetestatus.') +
    fToggle('diagnostics.enabled', 'Geraete-Diagnostik aktiv') +
    fRange('diagnostics.check_interval_minutes', 'Pruef-Intervall', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('diagnostics.battery_warning_threshold', 'Batterie-Warnung ab', 5, 50, 5, {5:'5%',10:'10%',15:'15%',20:'20%',30:'30%',50:'50%'}) +
    fRange('diagnostics.stale_sensor_minutes', 'Sensor veraltet nach', 30, 600, 30, {30:'30 Min',60:'1 Std',120:'2 Std',300:'5 Std',600:'10 Std'}) +
    fRange('diagnostics.offline_threshold_minutes', 'Geraet offline nach', 10, 120, 10, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('diagnostics.alert_cooldown_minutes', 'Wiederholung fruehestens nach', 10, 240, 10, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std',240:'4 Std'}) +
    fChipSelect('diagnostics.monitor_domains', 'Ueberwachte Domains', [
        {v:'sensor',l:'Sensoren'}, {v:'binary_sensor',l:'Binaer-Sensoren'},
        {v:'light',l:'Lichter'}, {v:'switch',l:'Schalter'},
        {v:'cover',l:'Rolladen'}, {v:'climate',l:'Klima'},
        {v:'lock',l:'Schloesser'}, {v:'fan',l:'Ventilatoren'},
        {v:'water_heater',l:'Warmwasser'}, {v:'media_player',l:'Media Player'},
        {v:'camera',l:'Kameras'}, {v:'alarm_control_panel',l:'Alarmanlagen'}
    ], 'Nur Entities aus diesen Domains werden ueberwacht') +
    fKeywords('diagnostics.exclude_patterns', 'Ignorierte Patterns (Entity-ID)') +
    '<div style="margin:12px 0;font-weight:600;font-size:13px;">Ueberwachte Geraete</div>' +
    fInfo('Waehle welche Geraete die Diagnostik ueberwachen soll. Klicke "Von MindHome importieren" um deine konfigurierten Geraete zu laden. Ohne Auswahl werden alle Entities der Standard-Domains geprueft.') +
    '<div id="diagEntityPickerContainer" style="color:var(--text-secondary);padding:12px;">' +
      '<button class="btn btn-primary btn-sm" onclick="loadDiagnosticsEntities()" style="font-size:12px;">&#127968; Von MindHome importieren</button>' +
      '<span style="color:var(--text-muted);font-size:11px;margin-left:10px;" id="diagEntityStatus"></span>' +
    '</div>'
  ) +
  sectionWrap('&#128295;', 'Wartung',
    fInfo('Automatische Wartungshinweise fuer Geraete im Haushalt.') +
    fToggle('maintenance.enabled', 'Wartungs-Erinnerungen aktiv')
  );
}

let _mhEntities = null;
async function loadMindHomeEntities() {
  try {
    const d = await api('/api/ui/entities/mindhome');
    _mhEntities = d;
    const monitored = d.monitored_entities || [];
    const container = document.getElementById('entityPickerContainer');
    if (!container) return;

    const rooms = d.rooms || {};
    const roomNames = Object.keys(rooms).sort();

    if (roomNames.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Keine Geräte in MindHome gefunden.</div>';
      return;
    }

    let html = '<div style="display:flex;gap:8px;margin-bottom:12px;">' +
      '<button class="btn btn-secondary btn-sm" onclick="toggleAllEntities(true)" style="font-size:11px;">Alle auswählen</button>' +
      '<button class="btn btn-secondary btn-sm" onclick="toggleAllEntities(false)" style="font-size:11px;">Keine</button>' +
      '<span style="color:var(--text-muted);font-size:11px;align-self:center;margin-left:auto;" id="entityCountLabel"></span>' +
      '</div>';

    for (const room of roomNames) {
      const entities = rooms[room] || [];
      html += '<div style="margin-bottom:16px;">';
      html += '<div style="font-size:13px;font-weight:600;color:var(--accent);margin-bottom:6px;border-bottom:1px solid var(--border);padding-bottom:4px;">&#127968; ' + esc(room) + ' <span style="color:var(--text-muted);font-weight:400;">(' + entities.length + ')</span></div>';

      for (const e of entities) {
        const checked = monitored.includes(e.entity_id) ? 'checked' : '';
        const domain = e.domain || '';
        const domainBadge = domain ? '<span style="font-size:10px;font-family:var(--mono);color:var(--text-muted);background:var(--bg-primary);padding:1px 5px;border-radius:3px;margin-left:6px;">' + esc(domain) + '</span>' : '';
        html += '<label style="display:flex;align-items:center;gap:8px;padding:5px 8px;cursor:pointer;border-radius:6px;transition:background 0.15s;" onmouseover="this.style.background=\'var(--bg-card-hover)\'" onmouseout="this.style.background=\'transparent\'">' +
          '<input type="checkbox" class="entity-check" data-entity="' + esc(e.entity_id) + '" ' + checked + ' onchange="updateEntityCount()" style="accent-color:var(--accent);width:16px;height:16px;">' +
          '<span style="font-size:13px;">' + esc(e.name || e.entity_id) + '</span>' +
          domainBadge +
          '</label>';
      }
      html += '</div>';
    }

    container.innerHTML = html;
    updateEntityCount();
  } catch (e) {
    const c = document.getElementById('entityPickerContainer');
    if (c) c.innerHTML = '<div style="color:var(--danger);padding:8px;">Fehler beim Laden: ' + esc(e.message) + '</div>';
  }
}

function updateEntityCount() {
  const all = document.querySelectorAll('.entity-check');
  const checked = document.querySelectorAll('.entity-check:checked');
  const label = document.getElementById('entityCountLabel');
  if (label) {
    label.textContent = checked.length === 0
      ? 'Keine Auswahl — alle Domains werden überwacht'
      : checked.length + ' von ' + all.length + ' ausgewählt';
  }
}

function toggleAllEntities(state) {
  document.querySelectorAll('.entity-check').forEach(cb => cb.checked = state);
  updateEntityCount();
}

function collectMonitoredEntities() {
  const entities = [];
  document.querySelectorAll('.entity-check:checked').forEach(cb => {
    entities.push(cb.dataset.entity);
  });
  return entities;
}

// --- Diagnostik Entity Picker (MindHome Import) ---
async function loadDiagnosticsEntities() {
  const container = document.getElementById('diagEntityPickerContainer');
  const status = document.getElementById('diagEntityStatus');
  if (!container) return;
  if (status) status.textContent = 'Lade...';
  try {
    const d = await api('/api/ui/entities/mindhome');
    const rooms = d.rooms || {};
    const roomNames = Object.keys(rooms).sort();
    const current = getPath(S, 'diagnostics.monitored_entities') || [];

    if (roomNames.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Keine Geraete in MindHome gefunden.</div>';
      return;
    }

    let html = '<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">' +
      '<button class="btn btn-secondary btn-sm" onclick="toggleDiagEntities(true)" style="font-size:11px;">Alle</button>' +
      '<button class="btn btn-secondary btn-sm" onclick="toggleDiagEntities(false)" style="font-size:11px;">Keine</button>' +
      '<button class="btn btn-primary btn-sm" onclick="loadDiagnosticsEntities()" style="font-size:11px;">&#128260; Neu laden</button>' +
      '<span style="color:var(--text-muted);font-size:11px;align-self:center;margin-left:auto;" id="diagCountLabel"></span>' +
      '</div>';

    for (const room of roomNames) {
      const entities = rooms[room] || [];
      html += '<div style="margin-bottom:14px;">';
      html += '<div style="font-size:13px;font-weight:600;color:var(--accent);margin-bottom:4px;border-bottom:1px solid var(--border);padding-bottom:3px;">&#127968; ' + esc(room) + ' <span style="color:var(--text-muted);font-weight:400;">(' + entities.length + ')</span></div>';
      for (const e of entities) {
        const checked = current.includes(e.entity_id) ? 'checked' : '';
        const domain = e.domain || '';
        const badge = domain ? '<span style="font-size:10px;font-family:var(--mono);color:var(--text-muted);background:var(--bg-primary);padding:1px 5px;border-radius:3px;margin-left:6px;">' + esc(domain) + '</span>' : '';
        html += '<label style="display:flex;align-items:center;gap:8px;padding:4px 8px;cursor:pointer;border-radius:6px;transition:background 0.15s;" onmouseover="this.style.background=\'var(--bg-card-hover)\'" onmouseout="this.style.background=\'transparent\'">' +
          '<input type="checkbox" class="diag-entity-check" data-entity="' + esc(e.entity_id) + '" ' + checked + ' onchange="updateDiagCount()" style="accent-color:var(--accent);width:16px;height:16px;">' +
          '<span style="font-size:13px;">' + esc(e.name || e.entity_id) + '</span>' + badge +
          '</label>';
      }
      html += '</div>';
    }
    container.innerHTML = html;
    updateDiagCount();
  } catch(e) {
    if (container) container.innerHTML = '<div style="color:var(--danger);padding:8px;">Fehler: ' + esc(e.message) + '</div>';
  }
}

function updateDiagCount() {
  const all = document.querySelectorAll('.diag-entity-check');
  const checked = document.querySelectorAll('.diag-entity-check:checked');
  const label = document.getElementById('diagCountLabel');
  if (label) {
    label.textContent = checked.length === 0
      ? 'Keine Auswahl — Standard-Domains'
      : checked.length + ' von ' + all.length + ' gewaehlt';
  }
}

function toggleDiagEntities(state) {
  document.querySelectorAll('.diag-entity-check').forEach(cb => cb.checked = state);
  updateDiagCount();
}

function collectDiagEntities() {
  const entities = [];
  document.querySelectorAll('.diag-entity-check:checked').forEach(cb => {
    entities.push(cb.dataset.entity);
  });
  return entities;
}

let _updating = false;

function renderSystem() {
  return sectionWrap('&#128300;', 'System-Status',
    '<div id="sysStatusBox" style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);">Lade...</div>' +
    '<button class="btn btn-secondary" style="margin-top:12px;font-size:12px;" onclick="loadSystemStatus()">Status aktualisieren</button>'
  ) +
  sectionWrap('&#128640;', 'System-Update',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Holt neuen Code von Git und baut die Container neu. Der Assistant startet dabei kurz neu.</p>' +
    '<div id="sysUpdateCheck" style="margin-bottom:12px;"></div>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
      '<button class="btn btn-primary" id="btnSysUpdate" onclick="doSystemUpdate()">&#128640; System-Update starten</button>' +
      '<button class="btn btn-secondary" id="btnSysCheckUpdate" onclick="checkForUpdates()">&#128269; Auf Updates pruefen</button>' +
    '</div>' +
    '<div id="sysUpdateLog" style="display:none;margin-top:16px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:12px;max-height:300px;overflow-y:auto;">' +
      '<div style="font-size:11px;font-family:var(--font-mono);white-space:pre-wrap;" id="sysUpdateLogContent"></div>' +
    '</div>'
  ) +
  sectionWrap('&#128260;', 'Container neustarten',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Startet alle Container neu ohne Rebuild. Schneller als ein volles Update.</p>' +
    '<button class="btn btn-secondary" id="btnSysRestart" onclick="doSystemRestart()">&#128260; Container neustarten</button>'
  ) +
  sectionWrap('&#129302;', 'Ollama-Modelle aktualisieren',
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">Aktualisiert alle installierten LLM-Modelle auf die neueste Version.</p>' +
    '<div id="sysModelsList" style="margin-bottom:12px;font-size:12px;color:var(--text-secondary);"></div>' +
    '<button class="btn btn-secondary" id="btnSysModels" onclick="doUpdateModels()">&#129302; Modelle aktualisieren</button>' +
    '<div id="sysModelsLog" style="display:none;margin-top:12px;font-size:12px;font-family:var(--font-mono);color:var(--text-secondary);"></div>'
  );
}

async function loadSystemStatus() {
  const box = document.getElementById('sysStatusBox');
  if (!box) return;
  try {
    _sysStatus = await api('/api/ui/system/status');
    const s = _sysStatus;
    const git = s.git || {};
    const containers = s.containers || {};
    const ollama = s.ollama || {};
    const disk = s.disk?.system || {};

    const cStatus = Object.entries(containers).map(([name, status]) => {
      const color = status === 'healthy' ? 'var(--success)' : status === 'unhealthy' ? 'var(--danger)' : 'var(--warning)';
      const short = name.replace('mindhome-', '').replace('mha-', '');
      return `<span style="color:${color};">&#9679;</span> ${short}: ${status}`;
    }).join('&nbsp;&nbsp;|&nbsp;&nbsp;');

    const models = document.getElementById('sysModelsList');
    if (models && ollama.models) {
      models.innerHTML = '<strong>Installiert:</strong> ' + esc(ollama.models).split('\n').slice(1).filter(l=>l.trim()).map(l => l.split(/\s+/)[0]).join(', ');
    }

    const ram = s.ram || {};
    const cpu = s.cpu || {};
    const gpu = s.gpu || {};

    function bar(pct, label, sub) {
      const color = pct > 90 ? 'var(--danger)' : pct > 70 ? 'var(--warning)' : 'var(--success)';
      return '<div style="margin-bottom:10px;">' +
        '<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">' +
          '<strong>' + label + '</strong><span style="color:var(--text-muted);">' + sub + '</span></div>' +
        '<div style="height:8px;background:var(--bg-secondary);border-radius:4px;overflow:hidden;">' +
          '<div style="height:100%;width:' + Math.min(100, pct) + '%;background:' + color + ';border-radius:4px;transition:width 0.3s;"></div>' +
        '</div></div>';
    }

    let hwHtml = '';
    if (ram.total_gb) {
      hwHtml += bar(ram.percent, 'RAM', ram.used_gb + ' / ' + ram.total_gb + ' GB (' + ram.percent + '%)');
    }
    if (cpu.cores) {
      hwHtml += bar(cpu.percent, 'CPU', 'Load ' + cpu.load_1m + ' / ' + cpu.cores + ' Kerne (' + cpu.percent + '%)');
    }
    if (gpu.name) {
      const gpuPct = gpu.memory_total_mb > 0 ? Math.round(gpu.memory_used_mb / gpu.memory_total_mb * 100) : 0;
      if (gpu.ollama_fallback) {
        hwHtml += bar(gpuPct, 'GPU (Ollama)', gpu.memory_used_mb + ' / ' + gpu.memory_total_mb + ' MB VRAM belegt');
      } else {
        hwHtml += bar(gpu.utilization_percent, 'GPU ' + esc(gpu.name), gpu.utilization_percent + '% Last, ' + gpu.temperature_c + '°C');
        hwHtml += bar(gpuPct, 'VRAM', gpu.memory_used_mb + ' / ' + gpu.memory_total_mb + ' MB (' + gpuPct + '%)');
      }
    }
    if (disk.total_gb) {
      const diskPct = Math.round((disk.total_gb - disk.free_gb) / disk.total_gb * 100);
      hwHtml += bar(diskPct, 'Gehirn', disk.free_gb + ' GB frei / ' + disk.total_gb + ' GB (' + diskPct + '%)');
    }
    // Weitere Partitionen (z.B. zweite SSD)
    const allDisks = s.disk || {};
    let extraDiskIdx = 0;
    for (const [mount, dinfo] of Object.entries(allDisks)) {
      if (mount === 'system' || !dinfo.total_gb) continue;
      const pct = Math.round((dinfo.total_gb - dinfo.free_gb) / dinfo.total_gb * 100);
      hwHtml += bar(pct, 'Ged\u00e4chtnis', dinfo.free_gb + ' GB frei / ' + dinfo.total_gb + ' GB (' + pct + '%)');
      extraDiskIdx++;
    }

    box.innerHTML = `
      ${hwHtml ? '<div style="margin-bottom:16px;">' + hwHtml + '</div>' : ''}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px 24px;">
        <div><strong>Version:</strong> ${esc(s.version || '?')}</div>
        <div><strong>Branch:</strong> ${esc(git.branch || '?')}</div>
        <div style="grid-column:1/-1;"><strong>Commit:</strong> ${esc(git.commit || '?')}</div>
        <div style="grid-column:1/-1;"><strong>Container:</strong> ${cStatus}</div>
        <div><strong>Ollama:</strong> ${ollama.available ? '<span style="color:var(--success);">Online</span>' : '<span style="color:var(--danger);">Offline</span>'}</div>
      </div>
      ${git.changes ? '<div style="margin-top:8px;padding:8px;background:var(--bg-hover);border-radius:4px;"><strong>Lokale Aenderungen:</strong><pre style="margin:4px 0 0;font-size:11px;">' + esc(git.changes) + '</pre></div>' : ''}
    `;
  } catch(e) {
    box.innerHTML = '<span style="color:var(--danger);">Fehler beim Laden: ' + esc(e.message) + '</span>';
  }
}

async function checkForUpdates() {
  const box = document.getElementById('sysUpdateCheck');
  const btn = document.getElementById('btnSysCheckUpdate');
  if (!box || !btn) return;
  btn.disabled = true;
  btn.textContent = 'Pruefe...';
  try {
    const data = await api('/api/ui/system/update-check');
    if (data.updates_available) {
      const commits = (data.new_commits || []).map(c => '<div style="padding:2px 0;">' + esc(c) + '</div>').join('');
      box.innerHTML = '<div style="padding:10px;background:var(--bg-hover);border-left:3px solid var(--accent);border-radius:4px;">' +
        '<strong style="color:var(--accent);">&#9889; Updates verfuegbar!</strong> (' + esc(data.local) + ' &rarr; ' + esc(data.remote) + ')' +
        '<div style="margin-top:8px;font-size:11px;font-family:var(--font-mono);">' + commits + '</div></div>';
    } else {
      box.innerHTML = '<div style="padding:8px;color:var(--success);"><strong>&#10003;</strong> System ist aktuell (' + esc(data.local || '') + ')</div>';
    }
  } catch(e) {
    box.innerHTML = '<span style="color:var(--danger);">Fehler: ' + esc(e.message) + '</span>';
  } finally {
    btn.disabled = false;
    btn.textContent = '\u{1F50D} Auf Updates pruefen';
  }
}

function _waitForRestart() {
  // Pollt alle 3s bis der Server wieder antwortet, dann Reload
  toast('Container startet neu... bitte kurz warten.');
  let attempts = 0;
  const poll = setInterval(async () => {
    attempts++;
    try {
      const r = await fetch('/api/assistant/health');
      if (r.ok) { clearInterval(poll); location.reload(); }
    } catch(e) { /* noch nicht bereit */ }
    if (attempts > 40) { clearInterval(poll); location.reload(); }
  }, 3000);
}

async function doSystemUpdate() {
  if (_updating) return;
  if (!confirm('System-Update starten?\n\nDer Assistant wird kurz neu gestartet.')) return;
  _updating = true;
  const btn = document.getElementById('btnSysUpdate');
  const logBox = document.getElementById('sysUpdateLog');
  const logContent = document.getElementById('sysUpdateLogContent');
  if (btn) { btn.disabled = true; btn.textContent = 'Update laeuft...'; }
  if (logBox) logBox.style.display = 'block';
  if (logContent) logContent.textContent = 'Update gestartet...\n';

  try {
    const data = await api('/api/ui/system/update', 'POST');
    if (logContent) logContent.textContent = (data.log || []).join('\n');
    if (data.success) {
      toast('Update erfolgreich! Container startet neu...');
      _waitForRestart();
    } else {
      toast('Update fehlgeschlagen — siehe Log', 'error');
      _updating = false;
      if (btn) { btn.disabled = false; btn.textContent = '\u{1F680} System-Update starten'; }
    }
  } catch(e) {
    if (logContent) logContent.textContent += '\nFehler: ' + e.message;
    if (e.message.includes('Failed to fetch') || e.message.includes('NetworkError')) {
      _waitForRestart();
    } else {
      toast('Update-Fehler: ' + e.message, 'error');
      _updating = false;
      if (btn) { btn.disabled = false; btn.textContent = '\u{1F680} System-Update starten'; }
    }
  }
}

async function doSystemRestart() {
  if (!confirm('Alle Container jetzt neustarten?')) return;
  const btn = document.getElementById('btnSysRestart');
  if (btn) { btn.disabled = true; btn.textContent = 'Neustart laeuft...'; }
  try {
    await api('/api/ui/system/restart', 'POST');
  } catch(e) { /* erwartbar: Verbindung bricht ab */ }
  _waitForRestart();
}

async function doUpdateModels() {
  if (!confirm('Alle Ollama-Modelle aktualisieren?\n\nDas kann je nach Modellgroesse einige Minuten dauern.')) return;
  const btn = document.getElementById('btnSysModels');
  const logBox = document.getElementById('sysModelsLog');
  if (btn) { btn.disabled = true; btn.textContent = 'Aktualisiere...'; }
  if (logBox) { logBox.style.display = 'block'; logBox.textContent = 'Modelle werden aktualisiert...\n'; }
  try {
    const data = await api('/api/ui/system/update-models', 'POST');
    if (logBox) {
      logBox.textContent = (data.models || []).map(m =>
        (m.success ? '\u2713' : '\u2717') + ' ' + m.model + ': ' + (m.output || '').split('\n').pop()
      ).join('\n');
    }
    if (data.success) {
      toast('Alle Modelle aktualisiert!');
    } else {
      toast('Einige Modelle konnten nicht aktualisiert werden', 'error');
    }
  } catch(e) {
    toast('Fehler: ' + e.message, 'error');
    if (logBox) logBox.textContent += '\nFehler: ' + e.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '\u{1F916} Modelle aktualisieren'; }
  }
}

