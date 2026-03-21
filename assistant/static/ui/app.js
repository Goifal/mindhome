/* ============================================================
   Jarvis Dashboard v2 — JavaScript
   11 Settings Tabs: Allgemein, Personen, Persönlichkeit, Gedächtnis,
   Stimmung, Räume, Stimme, Routinen, Sicherheit, KI-Autonomie, Easter Eggs
   ============================================================ */

let TOKEN = '';
let S = {};  // Settings cache
let RP = {};  // Room-Profiles cache (room_profiles.yaml)
let _rpDirty = false;  // Room-Profiles geändert?
let ALL_ENTITIES = [];
let ENTITY_ANNOTATIONS = {};
let ENTITY_ROLES_DEFAULT = {};
let ENTITY_ROLES_CUSTOM = {};
let _annSaveTimer = null;
let _roleSaveTimer = null;
let _annBatchSelected = new Set();
let AVAILABLE_MODELS = [];  // Dynamisch von Ollama geladen
const API = '';
let _autoSaveTimer = null;
const _AUTO_SAVE_DELAY = 2000;  // 2 Sekunden Debounce

// ---- Sidebar-Suche: Suchindex über alle Settings-Sektionen ----
const _searchIndex = [
  // Allgemein (tab-general)
  {tab:'tab-general', title:'Assistent', keywords:'name sprache version grundeinstellungen', icon:'&#9881;'},
  {tab:'tab-general', title:'Web-Suche', keywords:'searxng duckduckgo recherche web search', icon:'&#128269;'},
  {tab:'tab-general', title:'Hauptbenutzer', keywords:'name benutzer primary user', icon:'&#128100;'},
  {tab:'tab-general', title:'Haushaltsmitglieder', keywords:'personen household member gast besitzer', icon:'&#128106;'},
  {tab:'tab-general', title:'Geräte-Erkennung', keywords:'command detection nouns verben befehle nlp', icon:'&#127899;'},
  // KI-Modelle & Stil (tab-personality)
  {tab:'tab-personality', title:'KI-Modelle & Stil', keywords:'modell llm ollama fast smart deep openai', icon:'&#127917;'},
  {tab:'tab-personality', title:'GPU-Performance', keywords:'flash attention gpu vram keep alive performance speed latenz', icon:'&#9889;'},
  {tab:'tab-personality', title:'Latenz-Optimierung', keywords:'latenz optimierung think modus upgrade deep smart refinement cache fast path geschwindigkeit response cache ttl incremental gather timeout', icon:'&#9889;'},
  // Jarvis-Features (tab-jarvis)
  {tab:'tab-jarvis', title:'Progressive Antworten', keywords:'denkt laut zwischen-meldungen verarbeitung', icon:'&#128172;'},
  {tab:'tab-jarvis', title:'MCU-Intelligenz', keywords:'proaktiv mitdenken ingenieur diagnose anomalie kreuz-referenz implizit', icon:'&#129504;'},
  {tab:'tab-jarvis', title:'MCU-Persönlichkeit', keywords:'rückbezüge callbacks lern-bestätigung vorhersage wetter selbst-bewusstsein humor', icon:'&#127917;'},
  {tab:'tab-jarvis', title:'Echte Empathie', keywords:'empathie emotion Verständnis stimmung mitfühlen', icon:'&#129505;'},
  {tab:'tab-jarvis', title:'Charakter-Schutz', keywords:'character lock filter retry llm rolle floskeln', icon:'&#128274;'},
  {tab:'tab-jarvis', title:'Persönlichkeits-Kern', keywords:'identität timing improvisation kreativ narrativ innerer zustand confidence domain gewichtet stimmung', icon:'&#129504;'},
  {tab:'tab-jarvis', title:'Geräte-Persönlichkeit', keywords:'spitznamen device narration waschmaschine saugroboter', icon:'&#128374;'},
  {tab:'tab-jarvis', title:'Geräte-Fertig-Erkennung', keywords:'waschmaschine trockner Geschirrspüler fertig watt power idle strom verbrauch', icon:'&#9889;'},
  {tab:'tab-jarvis', title:'Daten-basierter Widerspruch', keywords:'pushback warnung fenster offen heizung eskalation', icon:'&#9888;'},
  {tab:'tab-jarvis', title:'Smart DJ', keywords:'musik genre stimmung kontextbewusst playlist', icon:'&#127925;'},
  {tab:'tab-jarvis', title:'Erinnerungen & Beziehungen', keywords:'erinnerungen memorable interactions langzeitgedächtnis witze humor gag beziehung person joke insider schweigen neugier besorgnis', icon:'&#128218;'},
  {tab:'tab-jarvis', title:'Situations-Modell & Erweitert', keywords:'hausstatus gespräch delta veränderung selbst lernen json modus tools', icon:'&#128269;'},
  // Stimmung (tab-mood)
  {tab:'tab-mood', title:'Stimmungserkennung', keywords:'mood stress frustration muede worte', icon:'&#128578;'},
  {tab:'tab-mood', title:'Stress-Einfluss', keywords:'stress boost reduktion ungeduld negative', icon:'&#9889;'},
  {tab:'tab-mood', title:'Stimmungs-Wörter', keywords:'positive negative ungeduld muedigkeit keywords', icon:'&#128172;'},
  {tab:'tab-mood', title:'Stimmung x Komplexität', keywords:'antwortlänge sätze mood complexity matrix', icon:'&#127919;'},
  {tab:'tab-mood', title:'Stimm-Analyse', keywords:'voice analysis wpm sprechgeschwindigkeit whisper', icon:'&#127908;'},
  {tab:'tab-mood', title:'Voice-Mood Integration', keywords:'stimm-emotion tonfall fröhlich traurig ärgerlich llm sentiment', icon:'&#127908;'},
  // Stimme & TTS (tab-voice)
  {tab:'tab-voice', title:'Spracherkennung (STT)', keywords:'whisper stt speech recognition modell sprache beam', icon:'&#127908;'},
  {tab:'tab-voice', title:'Sprachausgabe (TTS)', keywords:'tts piper stimme voice rate geschwindigkeit', icon:'&#128266;'},
  // Gedächtnis (tab-memory)
  {tab:'tab-memory', title:'Gedächtnis-Einstellungen', keywords:'memory kontext max einträge persönliche daten geburtstag', icon:'&#128218;'},
  // Räume & Speaker (tab-rooms)
  {tab:'tab-rooms', title:'Heizung', keywords:'thermostat Heizkurve Wärmepumpe temperatur', icon:'&#128293;'},
  {tab:'tab-rooms', title:'Luftfeuchtigkeit', keywords:'feuchtigkeit humidity sensor raumklima', icon:'&#128167;'},
  {tab:'tab-rooms', title:'Räume', keywords:'raum speaker lautsprecher zuordnung', icon:'&#127968;'},
  // Sensoren (tab-sensors)
  {tab:'tab-sensors', title:'Sensoren', keywords:'sensor bettsensor bett schlaf bed occupancy präsenz', icon:'&#128225;'},
  // Licht (tab-lights)
  {tab:'tab-lights', title:'Licht', keywords:'lampe helligkeit farbe szene beleuchtung', icon:'&#128161;'},
  // Geräte (tab-devices)
  {tab:'tab-devices', title:'Geräte', keywords:'device steckdose sensor schalter', icon:'&#128268;'},
  // Rollläden (tab-covers)
  {tab:'tab-covers', title:'Rollläden', keywords:'cover rollladen jalousie position', icon:'&#129695;'},
  // Saugroboter (tab-vacuum)
  {tab:'tab-vacuum', title:'Saugroboter', keywords:'vacuum staubsauger reinigung räume', icon:'&#129529;'},
  // Fernbedienung (tab-remote)
  {tab:'tab-remote', title:'Fernbedienung', keywords:'remote tv infrarot befehle', icon:'&#128261;'},
  // Szenen (tab-scenes)
  {tab:'tab-scenes', title:'Szenen', keywords:'szene scene aktivität nicht stören', icon:'&#127916;'},
  // Routinen (tab-routines)
  {tab:'tab-routines', title:'Morgen-Briefing', keywords:'morgen briefing wetter termine nachrichten aufwachen', icon:'&#127748;'},
  {tab:'tab-routines', title:'Aufwach-Sequenz', keywords:'aufwachen rolladen licht kaffee morgens', icon:'&#9728;'},
  {tab:'tab-routines', title:'Abend-Briefing', keywords:'abend status sicherheit fenster', icon:'&#127769;'},
  {tab:'tab-routines', title:'Kalender', keywords:'calendar termine home assistant', icon:'&#128197;'},
  {tab:'tab-routines', title:'Gute-Nacht-Routine', keywords:'gute nacht schlafen lichter heizung alarm', icon:'&#128164;'},
  {tab:'tab-routines', title:'Gäste-Modus', keywords:'gast besuch formell privat wifi', icon:'&#128101;'},
  {tab:'tab-routines', title:'Benannte Protokolle', keywords:'protokoll multi-step sequenz filmabend sprache', icon:'&#128221;'},
  {tab:'tab-routines', title:'"Das Übliche"', keywords:'übliche wie immer muster gewohnheit tageszeit', icon:'&#128260;'},
  // Proaktiv (tab-proactive)
  {tab:'tab-proactive', title:'Proaktive Meldungen', keywords:'proaktiv meldungen cooldown autonomie dedup duplikat erkennung', icon:'&#128276;'},
  {tab:'tab-proactive', title:'Zeitgefühl', keywords:'ofen vergessen bügeleisen licht fenster pc pause', icon:'&#9200;'},
  {tab:'tab-proactive', title:'Vorausdenken', keywords:'anticipation gewohnheiten lernen vorhersage konfidenz', icon:'&#128300;'},
  {tab:'tab-proactive', title:'Rückkehr-Briefing', keywords:'abwesenheit rückkehr briefing klingel waschmaschine', icon:'&#128218;'},
  {tab:'tab-proactive', title:'Einkaufslisten-Erinnerung', keywords:'einkaufsliste shopping abschied verlassen departure', icon:'&#128722;'},
  {tab:'tab-proactive', title:'Nachricht-Bündelung', keywords:'batching bündeln sammeln intervall low meldungen', icon:'&#128230;'},
  {tab:'tab-proactive', title:'Ambient Presence', keywords:'ambient presence leise ruhig hintergrund bericht', icon:'&#128164;'},
  {tab:'tab-proactive', title:'Vorausschau & Foresight', keywords:'foresight kalender vorausschau abfahrt warnung wetter', icon:'&#128302;'},
  {tab:'tab-proactive', title:'Self-Follow-Up', keywords:'follow up nachfrage selbst thema offen erledigt', icon:'&#128260;'},
  {tab:'tab-proactive', title:'Voraussagende Bedürfnisse', keywords:'predictive needs durst hitze kälte trinken', icon:'&#127777;'},
  {tab:'tab-proactive', title:'Geo-Fence', keywords:'geo fence ankunft abfahrt entfernung kilometer nähern', icon:'&#128205;'},
  {tab:'tab-proactive', title:'Smart Shopping', keywords:'smart shopping einkauf verbrauch prognose rezept zutaten muster', icon:'&#128722;'},
  {tab:'tab-proactive', title:'Energie-Dashboard', keywords:'energie solar strom verbrauch einspeisung preis dashboard live watt', icon:'&#9889;'},
  {tab:'tab-proactive', title:'Konversations-Gedächtnis++', keywords:'projekte meilensteine fragen gedächtnis zusammenfassung projekt tracker memory', icon:'&#129504;'},
  {tab:'tab-proactive', title:'Multi-Room Audio', keywords:'multi room audio speaker gruppe gruppen sync synchron musik sonos cast lautsprecher zone', icon:'&#127925;'},
  {tab:'tab-proactive', title:'Jarvis denkt voraus', keywords:'insights wetter kalender energie fenster frost', icon:'&#129504;'},
  {tab:'tab-proactive', title:'Event-Handler', keywords:'event prioritaet critical high medium low', icon:'&#128226;'},
  {tab:'tab-proactive', title:'Spontane Beobachtungen', keywords:'beobachtungen energie streak rekorde meilensteine', icon:'&#128065;'},
  // Benachrichtigungen (tab-notifications)
  {tab:'tab-notifications', title:'Stille-Matrix', keywords:'zustellung aktivität schlafen telefonat tv dringlichkeit tts led', icon:'&#128263;'},
  {tab:'tab-notifications', title:'Lautstärke-Matrix', keywords:'volume lautstärke tts nachts', icon:'&#128266;'},
  {tab:'tab-notifications', title:'Benachrichtigungskanaele', keywords:'kanaele channels benachrichtigung', icon:'&#128276;'},
  {tab:'tab-notifications', title:'Stille-Keywords', keywords:'nicht stören filmabend netflix meditation schlafen', icon:'&#128164;'},
  // Follow-Me (tab-followme)
  {tab:'tab-followme', title:'Follow-Me', keywords:'raum folgen musik licht temperatur person profil', icon:'&#128694;'},
  // Intelligenz (tab-intelligence)
  {tab:'tab-intelligence', title:'Domain-spezifische Autonomie', keywords:'domain autonomie klima licht medien sicherheit', icon:'&#127919;'},
  {tab:'tab-intelligence', title:'Kalender-Intelligenz', keywords:'kalender gewohnheit konflikt pendelzeit termin per route pendel', icon:'&#128197;'},
  {tab:'tab-intelligence', title:'Erklärbarkeit', keywords:'erklaerbarkeit warum aktion begründung entscheidung', icon:'&#128161;'},
  {tab:'tab-intelligence', title:'Lern-Transfer', keywords:'transfer präferenz raum ähnlich vorschlag benachrichtigung notify', icon:'&#129504;'},
  {tab:'tab-intelligence', title:'Think-Ahead Hinweise', keywords:'think ahead nächster schritt vorschlag vorausdenken', icon:'&#128161;'},
  {tab:'tab-intelligence', title:'Kausalketten-Erkennung', keywords:'kausal kette handlung wiederholend muster', icon:'&#128279;'},
  {tab:'tab-intelligence', title:'3D+ Insight Checks', keywords:'gäste vorbereitung alarm abwesenheit sicherheit feuchtigkeit nacht', icon:'&#128200;'},
  {tab:'tab-intelligence', title:'LLM Kausal-Analyse', keywords:'llm kausal insight korrelation ungewöhnlich muster', icon:'&#129504;'},
  {tab:'tab-intelligence', title:'Prozedurales Lernen', keywords:'prozedural sequenz multi step automation kette', icon:'&#128279;'},
  {tab:'tab-intelligence', title:'Routine-Abweichungen', keywords:'routine abweichung deviation ungewöhnlich anders', icon:'&#128270;'},
  {tab:'tab-intelligence', title:'Routine-Anomalie-Erkennung', keywords:'routine anomalie abwesenheit check nachfrage sorge muster erwartung', icon:'&#128680;'},
  {tab:'tab-intelligence', title:'Proaktiver Sequenz-Planner', keywords:'sequenz planner ankunft wetter aktion kette', icon:'&#128736;'},
  {tab:'tab-intelligence', title:'Saisonale Intelligenz', keywords:'saison jahreszeit heizung vergleich muster hybrid erkennung tageslicht', icon:'&#127808;'},
  {tab:'tab-intelligence', title:'Dialogführung', keywords:'dialog referenz auflösen klärung mehrdeutigkeit', icon:'&#128172;'},
  {tab:'tab-intelligence', title:'Kontext-Threads', keywords:'context builder threads gesprächs kontext kontinuität', icon:'&#128172;'},
  {tab:'tab-intelligence', title:'Klima-Modell', keywords:'klima digitaler zwilling simulation wärmeverlust fenster', icon:'&#127777;'},
  {tab:'tab-intelligence', title:'Prädiktive Wartung', keywords:'wartung batterie lebensdauer health score vorhersage', icon:'&#128295;'},
  {tab:'tab-intelligence', title:'Konsequenz-Bewusstsein', keywords:'konsequenz kontext sinnvoll warnung hinweis', icon:'&#9888;'},
  {tab:'tab-intelligence', title:'Unaufgeforderte Beobachtungen', keywords:'beobachtung periodisch licht fenster batterie alarm', icon:'&#128065;'},
  {tab:'tab-intelligence', title:'Background Reasoning', keywords:'idle hintergrund analyse smart modell insight', icon:'&#129504;'},
  {tab:'tab-intelligence', title:'Abstrakte Konzepte', keywords:'feierabend filmabend konzept routine skill dynamisch', icon:'&#127793;'},
  {tab:'tab-intelligence', title:'History-Suche', keywords:'suche history verlauf gespräch archiv search', icon:'&#128270;'},
  {tab:'tab-intelligence', title:'Automation-Debugging', keywords:'automation debug fehler trace analyse ha', icon:'&#128295;'},
  // Autonomie (tab-autonomie)
  {tab:'tab-autonomie', title:'Autonomie-Stufen & Berechtigungen', keywords:'autonomie level assistent butler mitbewohner vertrauter autopilot berechtigung aktion permission evolution aufstieg kriterien immutable geschuetzt parameter grenzen', icon:'&#9889;'},
  {tab:'tab-autonomie', title:'Lern-System & Selbstoptimierung', keywords:'selbstoptimierung analyse vorschläge genehmigung approval lernen outcome tracker korrektur adaptive thresholds schwellwerte', icon:'&#129504;'},
  {tab:'tab-autonomie', title:'Antwort-Qualität & Feedback', keywords:'response quality feedback fehlermuster error patterns selbst report cross session score cooldown boost unterdrücken', icon:'&#128200;'},
  {tab:'tab-autonomie', title:'Erweiterte KI & Prompt-Optimierung', keywords:'butler instinct multi turn tools fusion sensor multi sense few shot beispiel prompt version kompaktierung kontext token budget llm', icon:'&#129302;'},
  {tab:'tab-autonomie', title:'Automationen & Rollback', keywords:'self automation ha automatisierung sprache erstellen config selbstmodifikation rollback snapshot', icon:'&#128736;'},
  // Analyse-Tools (tab-declarative-tools)
  {tab:'tab-declarative-tools', title:'Analyse-Tools', keywords:'deklarativ analyse read-only berechnung home assistant', icon:'&#128736;'},
  // Haus-Status (tab-house-status)
  {tab:'tab-house-status', title:'Haus-Status Bereiche', keywords:'status detail kompakt ausführlich anwesenheit temperatur wetter', icon:'&#127968;'},
  {tab:'tab-house-status', title:'Health Monitor', keywords:'health sensor temperatur feuchtigkeit co2 batterie', icon:'&#128296;'},
  {tab:'tab-house-status', title:'Humidor', keywords:'humidor feuchtigkeit zigarren sensor', icon:'&#127793;'},
  {tab:'tab-house-status', title:'Wellness', keywords:'wellness trinken pause mahlzeit stress pc break reminder', icon:'&#129505;'},
  {tab:'tab-house-status', title:'Wetterwarnungen', keywords:'wetter warnung temperatur wind sturm hitze kälte', icon:'&#127752;'},
  // Koch-Assistent (tab-cooking)
  {tab:'tab-cooking', title:'Koch-Assistent', keywords:'kochen rezept timer portionen schritte', icon:'&#127859;'},
  // Werkstatt (tab-workshop)
  {tab:'tab-workshop', title:'Werkstatt-Modus', keywords:'werkstatt reparatur elektronik 3d drucker roboter mqtt', icon:'&#128295;'},
  // Easter Eggs (tab-eastereggs)
  {tab:'tab-eastereggs', title:'Easter Eggs', keywords:'easter egg versteckt spass trigger antwort', icon:'&#127881;'},
  // Sicherheit (tab-security)
  {tab:'tab-security', title:'Dashboard & PIN', keywords:'pin schutz recovery key zugang login', icon:'&#128187;'},
  {tab:'tab-security', title:'Sicherheit', keywords:'bestätigung alarm schloss garage heizung temperatur limit', icon:'&#128274;'},
  {tab:'tab-security', title:'API Key', keywords:'api key netzwerk schutz addon integration', icon:'&#128273;'},
  {tab:'tab-security', title:'Vertrauensstufen', keywords:'trust gast mitbewohner besitzer rechte erlaubt', icon:'&#128272;'},
  {tab:'tab-security', title:'Besucher-Management', keywords:'besucher klingel kamera tuer gast entriegelung', icon:'&#128682;'},
  {tab:'tab-security', title:'Netzwerk-Geräte', keywords:'netzwerk geraet device tracker bekannt unbekannt warnung wlan wifi', icon:'&#128225;'},
  {tab:'tab-security', title:'Kameras & Vision', keywords:'kamera vision llava ocr bild snapshot tuerklingel sicherheit objekterkennung', icon:'&#128247;'},
  {tab:'tab-security', title:'Notfall-Protokolle', keywords:'notfall feuer rauch einbruch wasser sirene', icon:'&#127752;'},
  {tab:'tab-security', title:'Bedrohungserkennung', keywords:'bedrohung threat nacht bewegung einbruch eskalation notfall playbook cooldown sensor', icon:'&#128680;'},
  {tab:'tab-security', title:'Interrupt-Queue', keywords:'interrupt critical notfall unterbrechung tts', icon:'&#9889;'},
  // System (tab-system)
  {tab:'tab-system', title:'System & Updates', keywords:'system update version neustart backup', icon:'&#128296;'},
];

const _tabLabels = {
  'tab-general':'Allgemein','tab-personality':'KI-Modelle & Stil',
  'tab-memory':'Gedächtnis','tab-mood':'Stimmung',
  'tab-rooms':'Räume & Speaker','tab-lights':'Licht','tab-devices':'Geräte',
  'tab-covers':'Rollläden','tab-vacuum':'Saugroboter','tab-remote':'Fernbedienung',
  'tab-scenes':'Szenen','tab-routines':'Routinen',
  'tab-proactive':'Proaktiv','tab-notifications':'Benachrichtigungen',
  'tab-cooking':'Koch-Assistent','tab-followme':'Follow-Me',
  'tab-jarvis':'Jarvis-Features','tab-intelligence':'Intelligenz',
  'tab-declarative-tools':'Analyse-Tools','tab-eastereggs':'Easter Eggs',
  'tab-autonomie':'Autonomie','tab-voice':'Stimme & TTS',
  'tab-security':'Sicherheit','tab-house-status':'Haus-Status',
  'tab-system':'System','tab-workshop':'Werkstatt'
};

let _searchActive = false;
function initSidebarSearch() {
  const input = document.getElementById('sidebarSearchInput');
  const results = document.getElementById('sidebarSearchResults');
  const clear = document.getElementById('sidebarSearchClear');
  if (!input) return;

  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    clear.style.display = q ? '' : 'none';
    if (q.length < 2) { results.style.display = 'none'; _searchActive = false; return; }
    _searchActive = true;
    const matches = _searchIndex.filter(item => {
      const haystack = (item.title + ' ' + item.keywords).toLowerCase();
      return q.split(/\s+/).every(word => haystack.includes(word));
    });
    if (matches.length === 0) {
      results.innerHTML = '<div class="search-no-results">Keine Treffer</div>';
    } else {
      results.innerHTML = matches.slice(0, 12).map((m, i) => {
        const highlighted = m.title.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<mark>$1</mark>');
        return `<div class="search-result-item${i===0?' active':''}" data-tab="${m.tab}" data-title="${m.title.replace(/"/g,'&quot;')}">
          <span class="sr-icon">${m.icon}</span>
          <div class="sr-text"><div class="sr-title">${highlighted}</div><div class="sr-tab">${_tabLabels[m.tab] || m.tab}</div></div>
        </div>`;
      }).join('');
    }
    results.style.display = '';
  });

  input.addEventListener('keydown', e => {
    if (!_searchActive) return;
    const items = results.querySelectorAll('.search-result-item');
    const active = results.querySelector('.search-result-item.active');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const arr = [...items];
      const idx = arr.indexOf(active);
      const next = e.key === 'ArrowDown' ? Math.min(idx + 1, arr.length - 1) : Math.max(idx - 1, 0);
      arr.forEach(el => el.classList.remove('active'));
      arr[next].classList.add('active');
      arr[next].scrollIntoView({block:'nearest'});
    } else if (e.key === 'Enter' && active) {
      e.preventDefault();
      _navigateToSearchResult(active.dataset.tab, active.dataset.title);
    } else if (e.key === 'Escape') {
      clearSidebarSearch();
      input.blur();
    }
  });

  results.addEventListener('click', e => {
    const item = e.target.closest('.search-result-item');
    if (!item) return;
    _navigateToSearchResult(item.dataset.tab, item.dataset.title);
  });

  // Close on outside click
  document.addEventListener('click', e => {
    if (_searchActive && !e.target.closest('.sidebar-search')) {
      results.style.display = 'none';
      _searchActive = false;
    }
  });
}

function _navigateToSearchResult(tab, sectionTitle) {
  // Navigate to the tab
  const navItem = document.querySelector(`.nav-item[data-tab="${tab}"]`);
  if (navItem) navItem.click();

  // Close search
  clearSidebarSearch();

  // After render, scroll to section and highlight it
  setTimeout(() => {
    const sections = document.querySelectorAll('#settingsContent .s-section-hdr h3');
    for (const h3 of sections) {
      // Strip HTML entities from h3 text for comparison
      const text = h3.textContent.trim();
      // Remove leading icon character(s) and whitespace
      const cleanText = text.replace(/^[^\w\u00C0-\u024F"(].?\s*/, '').trim();
      const cleanTitle = sectionTitle.replace(/^[^\w\u00C0-\u024F"(].?\s*/, '').trim();
      if (cleanText === cleanTitle || text.includes(sectionTitle)) {
        const section = h3.closest('.s-section');
        // Expand section if collapsed
        const sHdr = section.querySelector('.s-section-hdr');
        if (sHdr && !sHdr.classList.contains('open')) {
          sHdr.click();
        }
        // Scroll and flash
        section.scrollIntoView({behavior:'smooth', block:'start'});
        section.style.transition = 'box-shadow 0.3s';
        section.style.boxShadow = '0 0 0 2px rgba(0,212,255,0.5), 0 0 20px rgba(0,212,255,0.15)';
        setTimeout(() => { section.style.boxShadow = ''; }, 2000);
        break;
      }
    }
  }, 150);
}

function clearSidebarSearch() {
  const input = document.getElementById('sidebarSearchInput');
  const results = document.getElementById('sidebarSearchResults');
  const clear = document.getElementById('sidebarSearchClear');
  if (input) input.value = '';
  if (results) results.style.display = 'none';
  if (clear) clear.style.display = 'none';
  _searchActive = false;
}

// ---- Auto-Save: Änderungen automatisch speichern ----
function scheduleAutoSave() {
  if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
  const status = document.getElementById('autoSaveStatus');
  if (status) { status.textContent = 'Ungespeichert...'; status.className = 'auto-save-status'; }
  _autoSaveTimer = setTimeout(async () => {
    _autoSaveTimer = null;
    if (status) { status.textContent = 'Speichert...'; status.className = 'auto-save-status saving'; }
    await saveAllSettings();
    if (status && !_autoSaveTimer) {
      status.textContent = 'Gespeichert'; status.className = 'auto-save-status saved';
      setTimeout(() => { if (status && !_autoSaveTimer) { status.textContent = ''; } }, 3000);
    }
  }, _AUTO_SAVE_DELAY);
}

let _autoSaveInitialized = false;
function _initAutoSave() {
  if (_autoSaveInitialized) return;
  const container = document.getElementById('settingsContent');
  if (!container) return;
  _autoSaveInitialized = true;
  // Auto-Save bei Änderungen an data-path UND speziellen Elementen
  // (data-person-profile, data-person-title, data-member-idx)
  const _isAutoSaveTarget = (e) =>
    e.target.closest('[data-path]') ||
    e.target.closest('[data-person-profile]') ||
    e.target.closest('[data-person-title]') ||
    e.target.closest('[data-member-idx]');
  container.addEventListener('input', (e) => {
    if (_isAutoSaveTarget(e)) scheduleAutoSave();
  });
  container.addEventListener('change', (e) => {
    if (_isAutoSaveTarget(e)) scheduleAutoSave();
  });
}

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

// ---- Session-Timeout: Auto-Logout bei Inaktivität (30 Min) ----
const SESSION_TIMEOUT_MS = 30 * 60 * 1000;  // 30 Minuten
let _sessionTimer = null;
function resetSessionTimer() {
  if (_sessionTimer) clearTimeout(_sessionTimer);
  if (!TOKEN) return;
  _sessionTimer = setTimeout(() => {
    doLogout();
    alert('Sitzung abgelaufen (30 Min Inaktivität). Bitte erneut anmelden.');
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

// MCU-style decode/scramble text effect
async function decodeText(el, text, speed) {
  const glyphs = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:/-';
  el.textContent = '';
  el.style.opacity = '1';
  let resolved = '';
  for (let i = 0; i < text.length; i++) {
    if (text[i] === ' ' || text[i] === '.') { resolved += text[i]; el.textContent = resolved; await sleep(speed * 0.5); continue; }
    for (let j = 0; j < 3; j++) {
      el.textContent = resolved + glyphs[Math.floor(Math.random() * glyphs.length)];
      await sleep(speed * 0.3);
    }
    resolved += text[i];
    el.textContent = resolved;
  }
}

function playBootSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    // Ton 1: Tiefer Sweep — Arc Reactor Ignition (0-2s)
    const o1 = ctx.createOscillator(), g1 = ctx.createGain();
    o1.type = 'sine';
    o1.frequency.setValueAtTime(60, ctx.currentTime);
    o1.frequency.exponentialRampToValueAtTime(200, ctx.currentTime + 0.8);
    o1.frequency.exponentialRampToValueAtTime(120, ctx.currentTime + 2);
    g1.gain.setValueAtTime(0, ctx.currentTime);
    g1.gain.linearRampToValueAtTime(0.12, ctx.currentTime + 0.3);
    g1.gain.linearRampToValueAtTime(0.06, ctx.currentTime + 1.5);
    g1.gain.linearRampToValueAtTime(0, ctx.currentTime + 2);
    o1.connect(g1).connect(ctx.destination);
    o1.start(); o1.stop(ctx.currentTime + 2);
    // Ton 2: System-Ping Cascade (1s, 1.4s, 1.8s)
    [1, 1.4, 1.8].forEach((t, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine';
      o.frequency.setValueAtTime(660 + i * 110, ctx.currentTime + t);
      g.gain.setValueAtTime(0, ctx.currentTime + t);
      g.gain.linearRampToValueAtTime(0.08, ctx.currentTime + t + 0.03);
      g.gain.linearRampToValueAtTime(0, ctx.currentTime + t + 0.5);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.5);
    });
    // Ton 3: Confirmation Chord (3.5s)
    [660, 880, 1100].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'triangle';
      o.frequency.setValueAtTime(f, ctx.currentTime + 3.5);
      g.gain.setValueAtTime(0, ctx.currentTime + 3.5);
      g.gain.linearRampToValueAtTime(0.06, ctx.currentTime + 3.55);
      g.gain.linearRampToValueAtTime(0, ctx.currentTime + 4.3);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + 3.5); o.stop(ctx.currentTime + 4.3);
    });
  } catch(e) { /* Audio nicht verfügbar */ }
}

async function playBootSequence() {
  const screen = document.getElementById('bootScreen');
  const textEl = document.getElementById('bootText');
  const sysEl = document.getElementById('bootSystems');
  const logoEl = document.getElementById('bootLogo');
  const subEl = document.getElementById('bootSub');
  const progBar = document.getElementById('bootProgBar');
  const progPct = document.getElementById('bootProgPct');
  const dataL = document.getElementById('bootDataL');
  const dataR = document.getElementById('bootDataR');
  const crosshair = screen.querySelector('.boot-crosshair');
  const rings = screen.querySelectorAll('.boot-r');

  screen.style.display = 'flex';
  playBootSound();

  function setProg(p) { progBar.style.width = p + '%'; progPct.textContent = p + '%'; }

  // Ambient data readouts
  dataL.textContent = 'SYS.CORE v4.2.1\nPROTOCOL: INIT\nENCRYPT: AES-256\nNET.LINK: PENDING\nMEMORY: 0/\u221E';
  dataR.textContent = 'QUANTUM.BRIDGE\nNEURAL.NET: STANDBY\nLATENCY: --ms\nUPTIME: 00:00:00\nBUILD: 2024.12';

  // Phase 1: Core ignition — rings activate one by one
  await sleep(300);
  setProg(3);
  for (let i = 0; i < rings.length - 1; i++) { // -1 to skip crosshair
    rings[i].classList.add('active');
    setProg(3 + (i + 1) * 4);
    await sleep(80 + Math.random() * 60);
  }
  // Crosshair fades in
  if (crosshair) { crosshair.style.opacity = '1'; crosshair.style.transition = 'opacity 0.5s ease'; }
  setProg(38);

  // Phase 2: Logo decode
  await sleep(200);
  await decodeText(logoEl, 'J.A.R.V.I.S.', 40);
  setProg(50);
  await sleep(150);
  subEl.style.opacity = '1';
  subEl.textContent = 'MIND HOME ASSISTANT';
  setProg(55);

  // Phase 3: Status text
  await sleep(200);
  await typeText(textEl, 'SUBSYSTEM INITIALIZATION...', 30);
  setProg(60);

  // Phase 4: Systems come online with natural jitter
  const systems = [
    { label: 'LLM ENGINE', pct: 68 },
    { label: 'HOME ASSISTANT', pct: 74 },
    { label: 'REDIS CACHE', pct: 80 },
    { label: 'MEMORY CORE', pct: 85 },
    { label: 'VOICE SYNTH', pct: 90 },
    { label: 'SECURITY', pct: 95 },
  ];
  sysEl.innerHTML = systems.map((s, i) =>
    `<div class="boot-sys" id="bootSys${i}"><span class="sys-dot"></span>${s.label}</div>`
  ).join('');

  for (let i = 0; i < systems.length; i++) {
    const el = document.getElementById('bootSys' + i);
    if (el) {
      el.classList.add('visible');
      await sleep(120 + Math.random() * 180);
      el.classList.add('online');
      setProg(systems[i].pct);
    }
  }

  // Update ambient data
  dataL.textContent = 'SYS.CORE v4.2.1\nPROTOCOL: ACTIVE\nENCRYPT: AES-256\nNET.LINK: SECURE\nMEMORY: READY';
  dataR.textContent = 'QUANTUM.BRIDGE\nNEURAL.NET: ONLINE\nLATENCY: <2ms\nUPTIME: 00:00:04\nBUILD: 2024.12';

  // Phase 5: Complete
  setProg(100);
  await sleep(200);
  textEl.textContent = '';
  await typeText(textEl, 'ALL SYSTEMS OPERATIONAL', 30);
  await sleep(900);

  // Fade out
  screen.classList.add('fade-out');
  await sleep(600);
  screen.style.display = 'none';
  screen.classList.remove('fade-out');
}

// ---- Setup-Status prüfen und richtigen Screen zeigen ----
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
      // Setup fertig: Token prüfen oder Login zeigen
      const t = sessionStorage.getItem('jt');
      if (t) {
        // Prüfen ob Token älter als 4h (Backend-Timeout)
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
  if (pin !== confirm) { err.textContent = 'PINs stimmen nicht überein'; return; }

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
  initSidebarSearch();
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
  if (new_pin !== new_pin_confirm) { err.textContent = 'PINs stimmen nicht überein'; return; }

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

// ---- Init: Setup-Status prüfen ----
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
  const titles = {dashboard:'Dashboard',settings:'Einstellungen',presence:'Anwesenheit',entities:'Entities',memory:'Gedächtnis',knowledge:'Wissen',recipes:'Rezepte',logs:'Logs',errors:'Fehler'};
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
      'tab-general':'Allgemein','tab-personality':'KI-Modelle & Stil',
      'tab-memory':'Gedächtnis-Einstellungen','tab-mood':'Stimmung',
      'tab-rooms':'Räume & Speaker','tab-lights':'Licht','tab-devices':'Geräte',
      'tab-covers':'Rollläden','tab-vacuum':'Saugroboter','tab-remote':'Fernbedienung',
      'tab-scenes':'Szenen','tab-routines':'Routinen',
      'tab-proactive':'Proaktiv & Vorausdenken',
      'tab-notifications':'Benachrichtigungen',
      'tab-cooking':'Koch-Assistent','tab-followme':'Follow-Me',
      'tab-jarvis':'Jarvis-Features','tab-intelligence':'Intelligenz — Quick Wins','tab-declarative-tools':'Analyse-Tools',
      'tab-eastereggs':'Easter Eggs',
      'tab-autonomie':'Autonomie & Selbstoptimierung',
      'tab-voice':'Stimme & TTS','tab-security':'Sicherheit & Notfall',
      'tab-house-status':'Haus-Status & Health','tab-system':'System & Updates'
    };
    const el = document.getElementById('settingsTitle');
    if (el) el.textContent = tabTitles[currentTab] || 'Einstellungen';
    const sub = document.getElementById('settingsSub');
    if (sub) sub.textContent = 'Einstellungen — ' + (tabTitles[currentTab] || '');
  }
  else if (pg === 'entities') loadEntities();
  else if (pg === 'memory') loadMemoryPage();
  else if (pg === 'knowledge') { loadKnowledge(); setTimeout(initKbDropzone, 50); }
  else if (pg === 'recipes') { loadRecipes(); setTimeout(initRecipeDropzone, 50); }
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
function getPath(obj,path) { if(!path) return undefined; return path.split('.').reduce((o,k)=>o?.[k], obj); }
function setPath(obj,path,val) {
  if(!path) return;
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
        <div class="stat-sub">Langzeitgedächtnis</div></div>
      <div class="stat-card"><div class="stat-label">Autonomie</div><div class="stat-value" style="color:var(--accent);">${auto.level||'?'}/5</div>
        <div class="stat-sub">${esc(auto.name||'')}</div></div>`;
    const comps=d.components||{};
    let ch='';
    for(const [n,s] of Object.entries(comps)) {
      const ss=(typeof s==='object'&&s!==null)?((s.enabled?'active':'disabled')+' ('+Object.entries(s).filter(([k])=>k!=='enabled').map(([k,v])=>k+': '+v).join(', ')+')'):String(s);
      const ok=ss==='connected'||ss.includes('active')||ss.includes('running');
      ch+=`<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">
        <span style="font-size:12px;">${esc(n)}</span>
        <span style="font-size:11px;color:${ok?'var(--success)':'var(--danger)'};font-family:var(--mono);">${esc(ss)}</span></div>`;
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
  // Szenen-Widget + Energie parallel laden
  loadSceneStatus();
  refreshEnergyDashboard();
}

// ---- Energie-Dashboard Live Widget ----
async function refreshEnergyDashboard() {
  try {
    const d = await api('/api/ui/energy/live');
    const card = document.getElementById('energyDashCard');
    const cont = document.getElementById('energyDashContent');
    const ts = document.getElementById('energyRefreshTs');
    if (!card || !cont) return;
    if (!d.available) { card.style.display = 'none'; return; }

    // Mindestens 1 Wert vorhanden?
    const hasData = d.solar_watts != null || d.consumption_watts != null || d.price_cents != null || d.grid_export_watts != null;
    if (!hasData) { card.style.display = 'none'; return; }

    card.style.display = '';
    if (ts) ts.textContent = new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});

    let html = '';

    // Solar
    if (d.solar_watts != null) {
      const pct = d.solar_watts > 0 ? Math.min(100, (d.solar_watts / (d.thresholds?.solar_high || 5000)) * 100) : 0;
      const col = d.solar_watts > (d.thresholds?.solar_high || 5000) ? 'var(--success)' : d.solar_watts > 500 ? 'var(--accent)' : 'var(--text-secondary)';
      html += `<div class="stat-card">
        <div class="stat-label">&#9728;&#65039; Solar</div>
        <div class="stat-value" style="color:${col}">${d.solar_watts >= 1000 ? (d.solar_watts/1000).toFixed(1)+' kW' : Math.round(d.solar_watts)+' W'}</div>
        <div style="margin-top:6px;height:4px;background:var(--border);border-radius:2px;overflow:hidden;">
          <div style="height:100%;width:${pct}%;background:${col};border-radius:2px;transition:width .5s;"></div>
        </div></div>`;
    }

    // Verbrauch
    if (d.consumption_watts != null) {
      const col = d.consumption_watts > 3000 ? 'var(--danger)' : d.consumption_watts > 1500 ? 'var(--warning, orange)' : 'var(--text)';
      html += `<div class="stat-card">
        <div class="stat-label">&#128268; Verbrauch</div>
        <div class="stat-value" style="color:${col}">${d.consumption_watts >= 1000 ? (d.consumption_watts/1000).toFixed(1)+' kW' : Math.round(d.consumption_watts)+' W'}</div>
        <div class="stat-sub">${d.self_sufficiency_percent != null ? Math.round(d.self_sufficiency_percent)+'% Eigenversorgung' : ''}</div></div>`;
    }

    // Netz (Export/Import)
    if (d.grid_export_watts != null) {
      const isExport = d.grid_export_watts > 0;
      const val = Math.abs(d.grid_export_watts);
      const col = isExport ? 'var(--success)' : 'var(--danger)';
      const label = isExport ? 'Einspeisung' : 'Netzbezug';
      html += `<div class="stat-card">
        <div class="stat-label">${isExport ? '&#9889;&#8593;' : '&#9889;&#8595;'} ${label}</div>
        <div class="stat-value" style="color:${col}">${val >= 1000 ? (val/1000).toFixed(1)+' kW' : Math.round(val)+' W'}</div>
        <div class="stat-sub">${isExport ? 'ins Netz' : 'vom Netz'}</div></div>`;
    }

    // Strompreis
    if (d.price_cents != null) {
      const col = d.price_status === 'low' ? 'var(--success)' : d.price_status === 'high' ? 'var(--danger)' : 'var(--text)';
      const label = d.price_status === 'low' ? 'Günstig' : d.price_status === 'high' ? 'Teuer' : 'Normal';
      html += `<div class="stat-card">
        <div class="stat-label">&#128176; Strompreis</div>
        <div class="stat-value" style="color:${col}">${d.price_cents.toFixed(1)} ct</div>
        <div class="stat-sub">${label} (pro kWh)</div></div>`;
    }

    cont.innerHTML = html;
  } catch(e) { /* silent */ }
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
    // Szenen + Energie aktualisieren
    loadSceneStatus();
    refreshEnergyDashboard();
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

// ---- Scene Status Widget ----

const _ACTIVITY_LABELS = {
  sleeping:'Schlafen', in_call:'Im Telefonat', watching:'TV/Film',
  focused:'Konzentriert', guests:'Gäste da', relaxing:'Entspannt',
  away:'Abwesend', unknown:'Unbekannt',
};
const _ACTIVITY_ICONS = {
  sleeping:'&#128164;', in_call:'&#128222;', watching:'&#127916;',
  focused:'&#128187;', guests:'&#128101;', relaxing:'&#127810;',
  away:'&#128682;', unknown:'&#10067;',
};

async function loadSceneStatus() {
  const c = document.getElementById('sceneStatusContainer');
  if (!c) return;
  try {
    const d = await api('/api/ui/scenes/status');
    const act = d.activity || {};
    const haScenes = d.ha_scenes || [];

    function fmtAgo(seconds) {
      if (seconds == null) return '—';
      if (seconds < 60) return 'gerade eben';
      if (seconds < 3600) return Math.floor(seconds / 60) + ' Min';
      if (seconds < 86400) return Math.floor(seconds / 3600) + ' Std';
      if (seconds < 172800) return 'gestern';
      return Math.floor(seconds / 86400) + ' Tage';
    }

    let html = '';

    // 1. Aktuelle Jarvis-Aktivität
    const actName = act.current || 'unknown';
    const actLabel = _ACTIVITY_LABELS[actName] || actName;
    const actIcon = _ACTIVITY_ICONS[actName] || '&#10067;';
    const isOverride = !!act.manual_override;
    const confidence = act.confidence != null ? Math.round(act.confidence * 100) : 0;
    const trigger = act.trigger || '';

    // Grund ermitteln
    let reason = '';
    if (isOverride) {
      reason = 'Manuell gesetzt';
      if (act.override_until) {
        try {
          const until = new Date(act.override_until);
          reason += ' bis ' + until.toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'});
        } catch(_) {}
      }
    } else {
      const sigs = act.signals || {};
      const active = Object.entries(sigs).filter(([k,v]) => v && v !== false && k !== 'ha_unavailable');
      if (active.length) {
        const sigLabels = {
          media_playing:'Media aktiv', in_call:'Telefonat', bed_occupied:'Bett belegt',
          sleeping:'Schlafenszeit', pc_active:'PC aktiv', guests:'Gäste erkannt',
          lights_off:'Lichter aus', away:'Abwesend',
        };
        reason = active.map(([k,v]) => {
          let label = sigLabels[k] || k;
          if (typeof v === 'string' && v.length > 0 && v !== 'true') label += ': ' + v.split('.').pop().replace(/_/g,' ');
          return label;
        }).join(', ');
      } else {
        reason = 'Sensor-Erkennung';
      }
    }

    html += `<div style="padding:10px 12px;margin-bottom:10px;background:rgba(0,212,255,0.04);border:1px solid rgba(0,212,255,0.15);border-radius:8px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:18px;">${actIcon}</span>
          <span style="font-size:14px;font-weight:600;color:var(--text-primary);">${esc(actLabel)}</span>
          ${isOverride ? '<span style="font-size:9px;background:var(--accent);color:var(--bg-primary);padding:1px 6px;border-radius:3px;font-weight:600;letter-spacing:0.5px;">OVERRIDE</span>' : ''}
        </div>
        <span style="font-size:11px;color:var(--text-muted);font-family:var(--mono);">${confidence}%</span>
      </div>
      <div style="font-size:11px;color:var(--text-secondary);">${esc(reason)}</div>
    </div>`;

    // 2. HA-Szenen (letzte Aktivierungen)
    if (haScenes.length) {
      html += '<div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">HA-Szenen</div>';
      for (const sc of haScenes) {
        const ago = sc.activated_ago_seconds;
        const isRecent = ago != null && ago < 7200;
        const agoText = fmtAgo(ago);
        const dotColor = isRecent ? 'var(--success)' : 'var(--text-muted)';
        const nameColor = isRecent ? 'var(--text-primary)' : 'var(--text-secondary)';
        html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="width:6px;height:6px;border-radius:50%;background:${dotColor};display:inline-block;flex-shrink:0;${isRecent?'box-shadow:0 0 6px '+dotColor:''}"></span>
            <span style="font-size:12px;color:${nameColor};${isRecent?'font-weight:600':''};">${esc(sc.name)}</span>
          </div>
          <span style="font-size:10px;color:var(--text-muted);font-family:var(--mono);white-space:nowrap;">${agoText}</span>
        </div>`;
      }
    }

    c.innerHTML = html;
    const ts = document.getElementById('sceneRefreshTs');
    if (ts) ts.textContent = new Date().toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'});
  } catch (e) {
    c.innerHTML = '<span style="color:var(--danger);font-size:12px;">Szenen konnten nicht geladen werden</span>';
    console.error('Scene status fail:', e);
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
      html = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">Keine Sensordaten verfügbar</div>';
    }
    c.innerHTML = html;
  } catch(e) {
    c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">Keine Sensordaten verfügbar</div>';
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
    // Defaults fuer rules_enabled (alle aktiv wenn nicht in Config)
    const _reDefaults = {window_open:true,solar_producing:true,high_lux:true,nobody_home:true,
      cooling_and_heating:true,goodnight_active:true,high_wind:true,door_open:true,
      sleeping_detected:true,rain_detected:true,frost_detected:true,high_energy_price:true,
      media_playing:true,window_scheduled_open:true};
    const re = getPath(S,'conflict_resolution.rules_enabled');
    if (!re || typeof re !== 'object') {
      setPath(S,'conflict_resolution.rules_enabled', _reDefaults);
    } else {
      for (const [k,v] of Object.entries(_reDefaults)) { if (re[k] === undefined) re[k] = v; }
    }
    // Room-Profiles + Ollama-Modelle parallel laden
    const [rp, ml] = await Promise.all([
      api('/api/ui/room-profiles').catch(() => ({})),
      api('/api/ui/models/available').catch(() => ({models: []})),
    ]);
    RP = rp;
    AVAILABLE_MODELS = ml.models || [];
    _rpDirty = false;
    renderCurrentTab();
    _initAutoSave();
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
      case 'tab-general': c.innerHTML = renderGeneral(); loadMindHomeEntities(); break;
      case 'tab-personality': c.innerHTML = renderPersonality(); break;
      case 'tab-memory': c.innerHTML = renderMemory(); loadPersonalDates(); break;
      case 'tab-mood': c.innerHTML = renderMood(); break;
      case 'tab-rooms': c.innerHTML = renderRooms(); loadMindHomeEntities(); loadRoomTempAverage(); break;
      case 'tab-sensors': c.innerHTML = renderSensors(); renderCentralBedSensors(); break;
      case 'tab-voice': c.innerHTML = renderVoice(); break;
      case 'tab-scenes': c.innerHTML = renderScenes(); break;
      case 'tab-routines': c.innerHTML = renderRoutines(); break;
      case 'tab-proactive': c.innerHTML = renderProactive(); break;
      case 'tab-notifications': c.innerHTML = renderNotifications(); loadNotifyChannels(); break;
      case 'tab-cooking': c.innerHTML = renderCooking(); break;
      case 'tab-workshop': c.innerHTML = renderWorkshop(); break;
      case 'tab-house-status': c.innerHTML = renderHouseStatus(); break;
      case 'tab-lights': c.innerHTML = renderLights(); loadLightEntities(); break;
      case 'tab-devices': c.innerHTML = renderDevices(); loadMindHomeEntities(); break;
      case 'tab-covers': c.innerHTML = renderCovers(); loadCoverEntities(); loadCoverProfiles(); loadCoverLive(); loadCoverGroups(); loadCoverScenes(); loadCoverSchedules(); loadCoverSensors(); loadOpeningSensors(); loadCoverActionLog(); loadPowerCloseRules(); break;
      case 'tab-vacuum': c.innerHTML = renderVacuum(); break;
      case 'tab-remote': c.innerHTML = renderRemote(); break;
      case 'tab-security': c.innerHTML = renderSecurity(); loadApiKey(); loadEmergencyProtocols(); loadKnownDevices(); break;
      case 'tab-autonomie': c.innerHTML = renderAutonomie(); loadSnapshots(); loadOptStatus(); loadAutomations(); break;
      case 'tab-followme': c.innerHTML = renderFollowMe(); break;
      case 'tab-jarvis': c.innerHTML = renderJarvisFeatures(); renderApplianceDevices(); renderPowerProfiles(); break;
      case 'tab-intelligence': c.innerHTML = renderIntelligence(); break;
      case 'tab-declarative-tools': c.innerHTML = renderDeclarativeTools(); loadDeclarativeTools(); _renderDeclSuggestions(); break;
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
// ESC schließt Modal
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHelpModal(); });

// ---- Help Texts für alle Settings ----
const HELP_TEXTS = {
  // === ALLGEMEIN ===
  'assistant.name': {title:'Assistenten-Name', text:'Der Name, mit dem sich der Assistent vorstellt und auf den er reagiert.'},
  'assistant.version': {title:'Version', text:'Aktuelle Software-Version. Nur zur Anzeige.'},
  'assistant.language': {title:'Sprache', text:'In welcher Sprache der Assistent antwortet.'},
  'autonomy.level': {title:'Autonomie-Level', text:'Wie selbststaendig darf der Assistent handeln? Jede Stufe beinhaltet alle Faehigkeiten der vorherigen.', detail:
    '<b>1 Assistent</b><br>' +
    '&nbsp;&nbsp;Reagiert nur auf direkte Befehle<br>' +
    '&nbsp;&nbsp;Fuehrt angeforderte Aktionen aus (Licht, Klima, Medien)<br>' +
    '&nbsp;&nbsp;Sicherheitswarnungen werden immer gemeldet<br><br>' +
    '<b>2 Butler</b><br>' +
    '&nbsp;&nbsp;Morgenbriefing (Wetter, Termine, Hausstatus)<br>' +
    '&nbsp;&nbsp;Begruessung bei Ankunft<br>' +
    '&nbsp;&nbsp;Proaktive Hinweise &amp; Warnungen (z.B. Fenster offen bei Regen)<br>' +
    '&nbsp;&nbsp;Anticipation-Vorschlaege: "Soll ich die Rolllaeden schliessen?"<br><br>' +
    '<b>3 Mitbewohner</b><br>' +
    '&nbsp;&nbsp;Licht automatisch anpassen (Tageszeit, Anwesenheit)<br>' +
    '&nbsp;&nbsp;Rolllaeden nach gelernten Mustern steuern<br>' +
    '&nbsp;&nbsp;Temperatur +/- 1°C selbststaendig korrigieren<br>' +
    '&nbsp;&nbsp;Erinnerungen selbst pausieren wenn beschaeftigt<br><br>' +
    '<b>4 Vertrauter</b><br>' +
    '&nbsp;&nbsp;Tagesroutinen anpassen (Aufstehzeit, Szenen)<br>' +
    '&nbsp;&nbsp;Neue Szenen vorschlagen basierend auf Verhalten<br>' +
    '&nbsp;&nbsp;Praeferenzen aktiv lernen &amp; anwenden<br><br>' +
    '<b>5 Autopilot</b><br>' +
    '&nbsp;&nbsp;Neue Automationen erstellen (mit Bestaetigung)<br>' +
    '&nbsp;&nbsp;Zeitplaene eigenstaendig anpassen<br>' +
    '&nbsp;&nbsp;Nur manuell aktivierbar (kein Auto-Aufstieg)'},
  'models.enabled.fast': {title:'Fast-Modell', text:'Schnelles Modell für einfache Befehle (Licht an, Timer, Danke).'},
  'models.enabled.smart': {title:'Smart-Modell', text:'Standard-Modell für normale Gespräche und Anfragen.'},
  'models.enabled.deep': {title:'Deep-Modell', text:'Grosses Modell für komplexe Analysen und ausführliche Antworten.'},
  'models.fast': {title:'Fast-Modell Auswahl', text:'Welches KI-Modell für schnelle Befehle.', detail:'Kleinere Modelle (3-4B) sind schneller, größere präziser.'},
  'models.smart': {title:'Smart-Modell Auswahl', text:'Welches KI-Modell für normale Gespräche.'},
  'models.deep': {title:'Deep-Modell Auswahl', text:'Welches KI-Modell für komplexe Aufgaben.', detail:'14B+ empfohlen für beste Ergebnisse.'},
  'models.deep_min_words': {title:'Deep ab Wörtern', text:'Ab wie vielen Wörtern automatisch das Deep-Modell genutzt wird.'},
  'models.options.temperature': {title:'Kreativitaet', text:'Wie kreativ die Antworten sein sollen.', detail:'0 = deterministisch, 0.7 = Standard, 2.0 = sehr kreativ'},
  'models.options.max_tokens': {title:'Max. Antwortlänge', text:'Maximale Länge einer Antwort in Tokens (~0.75 Wörter pro Token).'},
  'ollama.num_ctx_fast': {title:'Kontext Fast-Modell', text:'Kontextfenster für das Fast-Modell (kleine Befehle).', detail:'Kleiner = spart VRAM und ist schneller. MoE-Modelle (Qwen3.5) vertragen groessere Fenster bei wenig VRAM.'},
  'ollama.num_ctx_smart': {title:'Kontext Smart-Modell', text:'Kontextfenster für das Smart-Modell (Gespräche).', detail:'Mehr Kontext = besseres Gesprächsgedächtnis. Qwen3.5 MoE unterstuetzt bis 262K.'},
  'ollama.num_ctx_deep': {title:'Kontext Deep-Modell', text:'Kontextfenster für das Deep-Modell (komplexe Aufgaben).', detail:'Qwen3.5 MoE unterstuetzt bis 262K. Groessere Fenster brauchen mehr VRAM, sind aber bei MoE effizient.'},
  'ollama.keep_alive': {title:'Keep-Alive', text:'Wie lange das Modell nach dem letzten Request im VRAM bleibt.', detail:'Länger = schnellere Antworten (kein Nachladen), aber mehr Strom im Idle. "5m" = 5 Minuten, "-1" = nie entladen, "0" = sofort entladen. Bei aktiver Nutzung empfohlen: "5m" oder länger.'},
  'ollama.flash_attn': {title:'Flash Attention', text:'Beschleunigt die Inferenz bei neueren GPUs (RTX 30xx+).', detail:'Flash Attention reduziert VRAM-Verbrauch und beschleunigt die Token-Generierung. Erfordert CUDA-fähige GPU. Bei Problemen deaktivieren.'},
  'ollama.num_gpu': {title:'GPU-Layer', text:'Wie viele Modell-Layer auf die GPU geladen werden.', detail:'Automatisch = Ollama berechnet anhand des freien VRAMs wie viele Layer passen (beste Option für grosse Modelle). 99 = alles auf GPU erzwingen (kann bei grossen Modellen fehlschlagen). 0 = nur CPU.'},
  'proactive.departure_shopping_reminder': {title:'Einkaufslisten-Erinnerung', text:'Beim Verlassen des Hauses erwähnt Jarvis offene Einkaufslisten-Einträge.', detail:'Nutzt die Home Assistant Shopping List. Jarvis sagt z.B. "Übrigens, Milch und Brot stehen noch auf der Liste."'},
  'smart_shopping.enabled': {title:'Smart Shopping', text:'Intelligente Einkaufsliste mit Verbrauchsprognose.', detail:'Lernt aus abgehakten Einkaufslisteneinträgen wie oft du Artikel kaufst. Erinnert proaktiv wenn etwas bald aufgebraucht sein müsste. Kann auch Rezept-Zutaten automatisch auf die Liste setzen.'},
  'smart_shopping.min_purchases': {title:'Mindest-Käufe', text:'Wie viele Käufe nötig sind bevor eine Prognose erstellt wird.', detail:'Bei 2 braucht es nur 2 Käufe für eine erste Schätzung. Höhere Werte machen die Prognose genauer, brauchen aber länger.'},
  'smart_shopping.reminder_days_before': {title:'Erinnerung vorher', text:'Wie viele Tage vor dem erwarteten Verbrauch erinnert werden soll.'},
  'smart_shopping.reminder_cooldown_hours': {title:'Erinnerungs-Cooldown', text:'Mindestabstand zwischen Erinnerungen für denselben Artikel.'},
  // === MODELL-PROFILE ===
  'model_profiles': {title:'Modell-Profile', text:'LLM-Parameter pro Modell-Familie. Neues Modell = nur Profil hier anlegen. Match: Laengster Key der im Modellnamen vorkommt gewinnt.', detail:'Beispiel: "qwen3.5:9b" matcht Profil "qwen3.5" (nicht "qwen3"). Unbekannte Modelle nutzen das "default" Profil. Spezifische Profile erben vom Default und überschreiben nur gesetzte Werte.'},
  'model_profiles.default.supports_think_tags': {title:'Think-Tags (Default)', text:'Ob das Modell &lt;think&gt;-Tags für Chain-of-Thought Reasoning nutzt.', detail:'Qwen3, DeepSeek und ähnliche Modelle geben ihren Denkprozess in &lt;think&gt;-Tags aus. Diese werden automatisch aus der Antwort entfernt.'},
  'model_profiles.default.supports_think_with_tools': {title:'Think + Tools (Default)', text:'Ob Think-Tags gleichzeitig mit Tool-Calls funktionieren.', detail:'Qwen 3.5 unterstützt Think+Tools nativ. Bei älteren Modellen stören Think-Tags die Tool-Generierung — dann deaktivieren.'},
  'model_profiles.default.temperature': {title:'Temperatur (Default)', text:'Kreativitaet der Antworten. 0 = deterministisch, 0.7 = Standard.'},
  'model_profiles.default.top_p': {title:'Top-P (Default)', text:'Nucleus Sampling. Niedrigere Werte = fokussiertere Antworten.'},
  'model_profiles.default.top_k': {title:'Top-K (Default)', text:'Nur die K wahrscheinlichsten Tokens beruecksichtigen.'},
  'model_profiles.default.min_p': {title:'Min-P (Default)', text:'Minimum Probability. Filtert sehr unwahrscheinliche Tokens.'},
  'model_profiles.default.repeat_penalty': {title:'Repeat Penalty (Default)', text:'Bestraft Wiederholungen. 1.0 = aus, 1.1 = leicht, 1.5 = stark.'},
  'model_profiles.default.think_temperature': {title:'Think-Temperatur (Default)', text:'Temperatur im Thinking-Modus. Empfohlen: 0.6 (fokussierter als normal).'},
  'model_profiles.default.think_top_p': {title:'Think Top-P (Default)', text:'Top-P im Thinking-Modus. Empfohlen: 0.95 (breiter als normal).'},
  'model_profiles.default.character_hint': {title:'JARVIS Character-Hint', text:'Modell-spezifische Prompt-Verstaerkung gegen typische LLM-Schwaechen.', detail:'Wird als Prio-1-Sektion in den System-Prompt injiziert. Hier kannst du modellspezifische Anweisungen hinterlegen, z.B. "Niemals mit Natürlich! anfangen" für Modelle die dazu neigen. Leer = kein Extra-Hint.'},
  // === LLM ENHANCER ===
  'llm_enhancer.enabled': {title:'LLM Enhancer', text:'Hauptschalter für alle vier Enhancer-Features.', detail:'Wenn deaktiviert, arbeitet Jarvis nur mit dem Basis-LLM-Call — schneller, aber weniger intelligent. Einzelne Features koennen separat deaktiviert werden.'},
  'llm_enhancer.smart_intent.enabled': {title:'Smart Intent', text:'Erkennt versteckte Absichten hinter vagen Aussagen.', detail:'"Mir ist kalt" wird als Wunsch erkannt die Heizung hochzudrehen. Nutzt das Fast-Modell für minimale Latenz (~100-300ms).'},
  'llm_enhancer.smart_intent.min_confidence': {title:'Smart Intent Konfidenz', text:'Ab welcher Sicherheit eine erkannte Absicht ausgeführt wird.', detail:'0.65 = Standard. Niedrigere Werte: Jarvis handelt oefter, kann aber falsch liegen. Hoehere Werte: nur bei sehr eindeutigen Faellen.'},
  'llm_enhancer.conversation_summary.enabled': {title:'Conversation Summary', text:'LLM-basierte Gespraechs-Zusammenfassung für besseres Gedaechtnis.', detail:'Statt einfacher Text-Kuerzung generiert das Fast-Modell eine intelligente Zusammenfassung des bisherigen Gespraechs.'},
  'llm_enhancer.conversation_summary.min_messages': {title:'Min. Nachrichten', text:'Ab wie vielen Nachrichten eine Zusammenfassung erstellt wird.', detail:'4 = Standard. Bei 2 wird schon nach dem ersten Austausch zusammengefasst — besseres Gedaechtnis, aber mehr LLM-Calls.'},
  'llm_enhancer.proactive_suggestions.enabled': {title:'Proactive Suggestions', text:'Jarvis schlaegt Automationen basierend auf Nutzungsmustern vor.', detail:'Erkennt wiederkehrende Muster (z.B. taegliches Licht-Ausschalten um 22 Uhr) und fragt ob eine Automation erstellt werden soll. Nutzt das Smart-Modell.'},
  'llm_enhancer.proactive_suggestions.min_patterns': {title:'Min. Muster', text:'Wie viele Wiederholungen noetig sind für einen Vorschlag.', detail:'1 = schon nach einmaligem Muster. Hoehere Werte vermeiden Vorschlaege bei Zufallsmustern.'},
  'llm_enhancer.proactive_suggestions.max_per_day': {title:'Max. Vorschlaege/Tag', text:'Wie oft Jarvis pro Tag mit Vorschlaegen kommen darf.', detail:'5 = Standard. Zu viele Vorschlaege wirken aufdringlich.'},
  'llm_enhancer.response_rewriter.enabled': {title:'Response Rewriter', text:'Formuliert technische Antworten in natürlichen Jarvis-Stil um.', detail:'Statt "Temperatur: 21.5°C" sagt Jarvis "Im Wohnzimmer sind es angenehme 21,5 Grad." Nutzt das Fast-Modell. Übersprungen bei Kurzantworten ("Erledigt").'},
  'llm_enhancer.response_rewriter.min_response_length': {title:'Min. Antwortlaenge', text:'Antworten unter dieser Zeichenzahl werden nicht umformuliert.', detail:'15 = Standard. "Erledigt" (8 Zeichen) braucht kein Rewriting, laengere Saetze schon.'},
  'llm_enhancer.response_rewriter.max_response_length': {title:'Max. Antwortlaenge', text:'Antworten über dieser Zeichenzahl werden nicht umformuliert.', detail:'500 = Standard. Lange Antworten sind bereits ausführlich genug und wuerden beim Rewriting zu lange dauern.'},
  'planner.max_iterations': {title:'Max. Planungsschritte', text:'Wie viele Planungsrunden der Action Planner maximal durchläuft.', detail:'8 = Standard. Komplexe Aufgaben wie "Mach alles fertig für morgen" brauchen mehr Schritte. Bei Timeout-Problemen reduzieren.'},
  'planner.max_tokens': {title:'Planner Antwortlänge', text:'Maximale Tokens pro Planungsschritt.', detail:'512 = Standard. Erhöhen wenn der Planner Plaene abschneidet.'},
  'models.fast_keywords': {title:'Fast-Keywords', text:'Wörter die das schnelle Modell aktivieren.'},
  'models.deep_keywords': {title:'Deep-Keywords', text:'Wörter die das ausführliche Modell aktivieren.'},
  'models.cooking_keywords': {title:'Koch-Keywords', text:'Wörter die den Koch-Modus aktivieren.'},
  'web_search.enabled': {title:'Web-Suche', text:'Optionale Web-Recherche. Privacy-First: SearXNG oder DuckDuckGo.'},
  'web_search.engine': {title:'Suchmaschine', text:'SearXNG (self-hosted) oder DuckDuckGo.'},
  'web_search.searxng_url': {title:'SearXNG URL', text:'URL deiner SearXNG-Instanz. Nur bei SearXNG relevant.'},
  'web_search.max_results': {title:'Max. Ergebnisse', text:'Wie viele Suchergebnisse maximal abgerufen werden.'},
  'web_search.timeout_seconds': {title:'Such-Timeout', text:'Nach wie vielen Sekunden die Suche abgebrochen wird.'},
  // === PERSOENLICHKEIT ===
  'personality.style': {title:'Grundstil', text:'Grundlegender Kommunikationsstil des Assistenten.'},
  'personality.sarcasm_level': {title:'Sarkasmus-Level', text:'Wie sarkastisch der Assistent sein darf (1-5).'},
  'personality.opinion_intensity': {title:'Meinungs-Intensität', text:'Wie stark der Assistent seine Meinung aeussert (0-3).'},
  'personality.self_irony_enabled': {title:'Selbstironie', text:'Ob der Assistent über sich selbst witzeln darf.'},
  'personality.self_irony_max_per_day': {title:'Max. Selbstironie/Tag', text:'Wie oft pro Tag Selbstironie erlaubt ist.'},
  'personality.character_evolution': {title:'Charakter-Entwicklung', text:'Assistent wird mit der Zeit vertrauter und informeller.'},
  'personality.formality_start': {title:'Anfangs-Formalität', text:'Wie formell am Anfang (100%=Sie, 0%=sehr locker).'},
  'personality.formality_min': {title:'Minimale Formalität', text:'Wie locker der Assistent maximal werden darf.'},
  'personality.formality_decay_per_day': {title:'Formalitäts-Abbau', text:'Wie schnell der Assistent lockerer wird (Punkte/Tag).'},
  'personality.mood_styles': {title:'Stimmungs-Stile', text:'Wie Jarvis auf verschiedene User-Stimmungen reagiert. Stil-Anweisung beeinflusst den Ton, Satz-Modifier die Antwortlänge.'},
  'personality.humor_templates': {title:'Humor-Templates', text:'Humor-Anweisungen pro Sarkasmus-Level (1-5). Diese Texte werden dem System-Prompt hinzugefuegt und steuern den Humor-Grad.'},
  'personality.complexity_prompts': {title:'Komplexitäts-Modi', text:'Text-Anweisungen pro Antwort-Modus (kurz/normal/ausführlich). Wird automatisch je nach Kontext gewählt.'},
  'personality.formality_prompts': {title:'Formalitäts-Stufen', text:'Ton-Anweisungen pro Formalitäts-Score. Der Score sinkt automatisch mit der Charakter-Entwicklung.'},
  'personality.confirmations.success': {title:'Erfolgs-Bestätigungen', text:'Phrasen die Jarvis nach erfolgreicher Aktion verwendet. Werden zufaellig gewählt, nie zweimal hintereinander.'},
  'personality.confirmations.success_snarky': {title:'Snarky Bestätigungen', text:'Spitzere Bestätigungen die ab Sarkasmus-Level 4 eingemischt werden.'},
  'personality.confirmations.partial': {title:'Teil-Bestätigungen', text:'Phrasen für teilweise erfolgreiche Aktionen.'},
  'personality.confirmations.failed': {title:'Fehler-Bestätigungen', text:'Phrasen wenn eine Aktion fehlgeschlagen ist.'},
  'personality.confirmations.failed_snarky': {title:'Snarky Fehler', text:'Spitzere Fehler-Phrasen ab Sarkasmus-Level 4.'},
  'personality.diagnostic_openers': {title:'Diagnose-Einleitungen', text:'Einleitungs-Phrasen für technische Beobachtungen im MCU-Jarvis Engineering-Stil.'},
  'personality.casual_warnings': {title:'Beiläufige Warnungen', text:'Understatement-Einleitungen für Warnungen — der typische Butler-Stil.'},
  'response_filter.enabled': {title:'Antwort-Filter', text:'Filtert unerwuenschte Phrasen und begrenzt Antwortlänge.'},
  'response_filter.max_response_sentences': {title:'Max. Sätze', text:'Max. Sätze pro Antwort. 0 = unbegrenzt.'},
  'response_filter.auto_ban_threshold': {title:'Auto-Ban Schwelle', text:'Phrasen die so oft vom Filter entfernt werden, werden automatisch zur Sperrliste hinzugefuegt.', detail:'0 = aus (nur manuelle Sperrung). 10 = Standard. Niedrigere Werte = aggressiveres Selbstlernen. Gesperrte Phrasen werden via Notification gemeldet.'},
  'response_filter.banned_phrases': {title:'Verbotene Phrasen', text:'Phrasen die der Assistent nie verwenden soll.'},
  'response_filter.banned_starters': {title:'Verbotene Satzanfaenge', text:'Satzanfaenge die vermieden werden sollen.'},
  'response_filter.sorry_patterns': {title:'Entschuldigungs-Filter', text:'Entschuldigungs-Phrasen die aus LLM-Antworten entfernt werden.'},
  'response_filter.refusal_patterns': {title:'Verweigerungs-Filter', text:'Verweigerungs-Phrasen die aus Antworten entfernt werden.'},
  'response_filter.chatbot_phrases': {title:'Chatbot-Floskeln-Filter', text:'Typische Chatbot-Floskeln die aus Antworten entfernt werden.'},
  'personality.error_templates.unavailable': {title:'Fehler: Nicht erreichbar', text:'Fehlermeldungen wenn ein Geraet nicht erreichbar ist. Platzhalter: {device}'},
  'personality.error_templates.timeout': {title:'Fehler: Timeout', text:'Fehlermeldungen bei Zeitüberschreitung. Platzhalter: {device}'},
  'personality.error_templates.not_found': {title:'Fehler: Nicht gefunden', text:'Fehlermeldungen wenn ein Geraet nicht gefunden wird. Platzhalter: {device}'},
  'personality.error_templates.unauthorized': {title:'Fehler: Nicht berechtigt', text:'Fehlermeldungen bei fehlender Berechtigung. Platzhalter: {device}'},
  'personality.error_templates.generic': {title:'Fehler: Allgemein', text:'Allgemeine Fehlermeldungen. Platzhalter: {device}'},
  'personality.escalation_prefixes.1': {title:'Eskalation: Beiläufig', text:'Info-Einleitungen (geringste Warnstufe). Platzhalter: {title}'},
  'personality.escalation_prefixes.2': {title:'Eskalation: Einwand', text:'Einwand-Einleitungen. Platzhalter: {title}'},
  'personality.escalation_prefixes.3': {title:'Eskalation: Sorge', text:'Besorgnis-Einleitungen. Platzhalter: {title}'},
  'personality.escalation_prefixes.4': {title:'Eskalation: Resignation', text:'Resignation-Einleitungen (hoechste Warnstufe). Platzhalter: {title}'},
  'personality.sarcasm_positive_patterns': {title:'Sarkasmus: Positiv', text:'Erkennungsmuster für positives Feedback auf Sarkasmus.'},
  'personality.sarcasm_negative_patterns': {title:'Sarkasmus: Negativ', text:'Erkennungsmuster für negatives Feedback auf Sarkasmus.'},
  'stt_corrections.word_corrections': {title:'STT Wort-Korrekturen', text:'Einzelwort-Korrekturen für häufige Spracherkennungsfehler.'},
  'stt_corrections.phrase_corrections': {title:'STT Phrasen-Korrekturen', text:'Mehrwort-Korrekturen. Werden VOR Einzelwort-Korrekturen angewendet.'},
  'command_detection.device_nouns': {title:'Geräte-Substantive', text:'Wörter die der Assistent als Geräte-Befehle erkennt.'},
  'command_detection.action_words': {title:'Aktions-Wörter', text:'Wörter die eine Geräte-Aktion signalisieren.'},
  'command_detection.command_verbs': {title:'Befehls-Verben', text:'Verben die einen Geräte-Befehl einleiten.'},
  'command_detection.query_markers': {title:'Abfrage-Marker', text:'Wörter die eine Status-Abfrage erkennen.'},
  'command_detection.action_exclusions': {title:'Aktions-Ausnahmen', text:'Wörter die als Aktion aussehen aber keine sind.'},
  'command_detection.status_nouns': {title:'Status-Substantive', text:'Wörter die eine Status-Abfrage signalisieren.'},
  'das_übliche.patterns': {title:'Das-Übliche Trigger', text:'Phrasen die die "Das Übliche"-Routine auslösen.'},
  'autonomy.action_permissions': {title:'Aktions-Berechtigungen', text:'Mindest-Autonomie-Level pro Aktionstyp (1-5).'},
  'autonomy.evolution_criteria': {title:'Evolution-Kriterien', text:'Kriterien für automatischen Autonomie-Aufstieg.'},
  'autonomy.domain_levels_enabled': {title:'Domain-Autonomie', text:'Aktiviert unterschiedliche Autonomie-Level pro Bereich (Klima, Licht, Sicherheit etc.). Wenn deaktiviert, gilt das globale Level.'},
  'autonomy.domain_levels.climate': {title:'Klima-Autonomie', text:'Autonomie-Level für Klima & Heizung. Z.B. Level 3 = darf Temperatur +/-1 Grad selbst anpassen.'},
  'autonomy.domain_levels.light': {title:'Licht-Autonomie', text:'Autonomie-Level für Licht & Beleuchtung.'},
  'autonomy.domain_levels.media': {title:'Medien-Autonomie', text:'Autonomie-Level für Medien & Musik.'},
  'autonomy.domain_levels.cover': {title:'Rolladen-Autonomie', text:'Autonomie-Level für Rollläden & Abdeckungen.'},
  'autonomy.domain_levels.security': {title:'Sicherheits-Autonomie', text:'Autonomie-Level für Sicherheits-Aktionen. Empfehlung: Niedrig halten (1-2).'},
  'autonomy.domain_levels.automation': {title:'Automations-Autonomie', text:'Autonomie-Level für Automationen & Routinen.'},
  'autonomy.domain_levels.notification': {title:'Benachrichtigungs-Autonomie', text:'Autonomie-Level für Benachrichtigungen & Briefings.'},
  'calendar_intelligence.enabled': {title:'Kalender-Intelligenz', text:'Analysiert deine Kalender-Termine und erkennt Gewohnheiten, Konflikte und freie Zeitfenster.'},
  'calendar_intelligence.commute_minutes': {title:'Pendelzeit', text:'Durchschnittliche Fahrzeit zum Arbeitsplatz. Wird für Pendelzeit-Warnungen verwendet.'},
  'calendar_intelligence.habit_min_occurrences': {title:'Min. Wiederholungen', text:'Wie oft muss ein Termin wiederkehren damit er als Gewohnheit erkannt wird.'},
  'calendar_intelligence.conflict_lookahead_hours': {title:'Konflikt-Vorschau', text:'Wie viele Stunden im Voraus werden Konflikte erkannt.'},
  'calendar_intelligence.habit_detection': {title:'Gewohnheits-Erkennung', text:'Erkennt wiederkehrende Termine als Muster.'},
  'calendar_intelligence.conflict_detection': {title:'Konflikt-Erkennung', text:'Warnt bei Zeitkonflikten und knapper Pendelzeit.'},
  'calendar_intelligence.break_detection': {title:'Pausen-Erkennung', text:'Erkennt freie Zeitfenster zwischen Terminen.'},
  'explainability.enabled': {title:'Erklärbarkeit', text:'Loggt alle automatischen Entscheidungen mit Begründung. Frage "Warum hast du das gemacht?" für eine Erklärung.'},
  'explainability.detail_level': {title:'Detail-Stufe', text:'Wie ausführlich Erklärungen sind. Minimal = nur Aktion + Grund. Verbose = inklusive Sensordaten und Konfidenz.'},
  'explainability.auto_explain': {title:'Automatisch erwaehnen', text:'Jarvis erwähnt kurz warum er etwas getan hat, ohne dass du fragen musst.'},
  'explainability.max_history': {title:'Max. Entscheidungen', text:'Wie viele Entscheidungen im Speicher gehalten werden.'},
  'mood.voice_mood_integration': {title:'Voice-Mood Integration', text:'Verknüpft erkannte Stimm-Emotionen (fröhlich, traurig, ärgerlich) direkt mit der Stimmungserkennung.'},
  'learning_transfer.enabled': {title:'Lern-Transfer', text:'Überträgt gelernte Präferenzen auf ähnliche Räume. Z.B. warmes Licht in Küche -> auch für Esszimmer vorschlagen.'},
  'learning_transfer.auto_suggest': {title:'Auto-Vorschläge', text:'Schlaegt automatisch vor wenn eine Präferenz übertragen werden könnte.'},
  'learning_transfer.min_observations': {title:'Min. Beobachtungen', text:'Wie oft muss eine Präferenz beobachtet werden bevor sie übertragen wird.'},
  'learning_transfer.transfer_confidence': {title:'Transfer-Konfidenz', text:'Mindest-Konfidenz für einen Transfer-Vorschlag.'},
  'learning_transfer.domains': {title:'Transfer-Domaenen', text:'Für welche Bereiche Präferenzen übertragen werden.'},
  'learning_transfer.room_groups': {title:'Raum-Gruppen', text:'Räume in der gleichen Gruppe werden als ähnlich betrachtet für den Präferenz-Transfer.'},
  'dialogue.enabled': {title:'Dialogführung', text:'Echte Gesprächsführung mit Referenz-Auflösung und Klärungsfragen.'},
  'dialogue.auto_resolve_references': {title:'Referenzen auflösen', text:'Loest "es", "das", "dort" automatisch auf das zuletzt besprochene Geraet/Raum auf.'},
  'dialogue.clarification_enabled': {title:'Klärungsfragen', text:'Jarvis fragt "Welches Licht?" wenn mehrere Geräte passen.'},
  'dialogue.timeout_seconds': {title:'Dialog-Timeout', text:'Nach dieser Zeit vergisst Jarvis den Gesprächskontext.'},
  'dialogue.max_clarification_options': {title:'Max. Optionen', text:'Maximale Anzahl Optionen bei einer Klärungsfrage.'},
  'climate_model.enabled': {title:'Klima-Modell', text:'Thermische Simulation für Was-wäre-wenn-Fragen.'},
  'climate_model.max_simulation_minutes': {title:'Max. Simulation', text:'Maximale Dauer für eine Simulation.'},
  'climate_model.default_params.heat_loss_coefficient': {title:'Wärmeverlust', text:'Wie schnell ein Raum Waerme verliert. Niedrig = gut isoliert.'},
  'climate_model.default_params.heating_power_per_min': {title:'Heizleistung', text:'Wie schnell die Heizung den Raum erwärmt. Abhaengig von Heizkoerper-Groesse.'},
  'climate_model.default_params.window_open_factor': {title:'Fenster-Faktor', text:'Wie stark offene Fenster den Wärmeverlust verstaerken.'},
  'climate_model.default_params.thermal_mass_factor': {title:'Thermische Masse', text:'Trägheit des Gebäudes. Schwerer Beton speichert mehr Waerme.'},
  'predictive_maintenance.enabled': {title:'Prädiktive Wartung', text:'Vorhersage von Geräteausfaellen und Wartungsbedarf.'},
  'predictive_maintenance.lookback_days': {title:'Analyse-Zeitraum', text:'Wie viele Tage Historie für die Vorhersage genutzt werden.'},
  'predictive_maintenance.failure_probability_threshold': {title:'Warnschwelle', text:'Ab welcher Ausfallwahrscheinlichkeit gewarnt wird.'},
  'predictive_maintenance.battery_drain_alert_pct_per_week': {title:'Batterie-Drain', text:'Ab welchem woechentlichen Batterie-Verlust gewarnt wird.'},
  'activity.silence_keywords.watching': {title:'Stille: Film/TV', text:'Keywords die den "Film schauen"-Modus auslösen.'},
  'activity.silence_keywords.focused': {title:'Stille: Konzentration', text:'Keywords die den "Nicht stören"-Modus auslösen.'},
  'activity.silence_keywords.sleeping': {title:'Stille: Schlafen', text:'Keywords die den Schlaf-Modus auslösen.'},
  'memory.category_confidence.health': {title:'Konfidenz: Gesundheit', text:'Mindest-Sicherheit für Gesundheits-Fakten.'},
  'memory.category_confidence.person': {title:'Konfidenz: Personen', text:'Mindest-Sicherheit für Personen-Fakten.'},
  'memory.category_confidence.preference': {title:'Konfidenz: Vorlieben', text:'Mindest-Sicherheit für Vorlieben-Fakten.'},
  'memory.category_confidence.habit': {title:'Konfidenz: Gewohnheiten', text:'Mindest-Sicherheit für Gewohnheits-Fakten.'},
  'memory.category_confidence.work': {title:'Konfidenz: Arbeit', text:'Mindest-Sicherheit für Arbeits-Fakten.'},
  'memory.category_confidence.intent': {title:'Konfidenz: Absichten', text:'Mindest-Sicherheit für Absichts-Fakten (kann sich ändern).'},
  'memory.category_confidence.general': {title:'Konfidenz: Allgemein', text:'Mindest-Sicherheit für allgemeine Fakten.'},
  'proactive.event_handlers': {title:'Event-Handler', text:'Prioritaeten und Beschreibungen für Event-Typen.'},
  'ambient_audio.default_reactions': {title:'Audio-Reaktionen', text:'Standard-Reaktionen auf erkannte Audio-Events.'},
  'entity_roles': {title:'Entity-Rollen', text:'Eigene Entity-Rollen für Geräte-Erkennung. Überschreiben Defaults aus entity_roles_defaults.yaml.'},
  // === GEDÄCHTNIS ===
  'memory.extraction_enabled': {title:'Fakten-Extraktion', text:'Automatisch Fakten aus Gesprächen lernen und merken.'},
  'memory.extraction_min_words': {title:'Min. Nachrichtenlänge', text:'Mindestlaenge damit Fakten extrahiert werden.'},
  'memory.extraction_model': {title:'Extraktions-Modell', text:'KI-Modell für Fakten-Erkennung.'},
  'memory.extraction_temperature': {title:'Extraktions-Genauigkeit', text:'Niedrig = nur offensichtliche Fakten, hoch = auch Vermutungen.'},
  'memory.extraction_max_tokens': {title:'Max. Extraktions-Länge', text:'Maximale Länge der Extraktions-Antwort.'},
  'memory.max_person_facts_in_context': {title:'Personen-Fakten', text:'Wie viele Fakten über die Person ins Gespräch einfliessen.'},
  'memory.max_relevant_facts_in_context': {title:'Relevante Fakten', text:'Wie viele thematisch passende Fakten pro Gespräch.'},
  'memory.min_confidence_for_context': {title:'Min. Sicherheit', text:'Wie sicher ein Fakt sein muss um genutzt zu werden.'},
  'memory.duplicate_threshold': {title:'Duplikat-Erkennung', text:'Wie ähnlich zwei Fakten für Duplikat-Erkennung sein müssen.'},
  'memory.episode_min_words': {title:'Min. Wörter Episode', text:'Mindestlaenge für episodisches Gedächtnis.'},
  'memory.default_confidence': {title:'Standard-Sicherheit', text:'Sicherheit mit der neue Fakten gespeichert werden.'},
  'knowledge_base.enabled': {title:'Wissensdatenbank', text:'RAG-System für eigene Dokumente (.txt, .md, .pdf).'},
  'knowledge_base.auto_ingest': {title:'Auto-Einlesen', text:'Beim Start neue Dateien automatisch aufnehmen.'},
  'knowledge_base.chunk_size': {title:'Textblock-Groesse', text:'In welche Stuecke Dokumente zerteilt werden.'},
  'knowledge_base.chunk_overlap': {title:'Überlappung', text:'Überlappung zwischen aufeinanderfolgenden Bloecken.'},
  'knowledge_base.max_distance': {title:'Suchgenauigkeit', text:'Max. Distanz für Treffer (niedriger = strenger).'},
  'knowledge_base.search_limit': {title:'Max. Treffer', text:'Max. Wissens-Treffer pro Suche.'},
  'knowledge_base.embedding_model': {title:'Embedding-Modell', text:'Modell für Vektorisierung. Nach Wechsel Rebuild nötig.'},
  'knowledge_base.supported_extensions': {title:'Dateitypen', text:'Welche Formate in die Wissensdatenbank können.'},
  'correction.confidence': {title:'Korrektur-Sicherheit', text:'Sicherheit bei durch Nutzer korrigierten Fakten.'},
  'correction.model': {title:'Korrektur-Modell', text:'KI-Modell für Korrektur-Analyse.'},
  'correction.temperature': {title:'Korrektur-Kreativitaet', text:'Kreativitaet der Korrektur-Analyse.'},
  'summarizer.run_hour': {title:'Zusammenfassung Stunde', text:'Uhrzeit (Stunde) der taeglichen Zusammenfassung.'},
  'summarizer.run_minute': {title:'Zusammenfassung Minute', text:'Uhrzeit (Minute) der Zusammenfassung.'},
  'summarizer.model': {title:'Zusammenfassungs-Modell', text:'KI-Modell für Tages-Zusammenfassung.'},
  'summarizer.max_tokens_daily': {title:'Länge taeglich', text:'Max. Länge der taeglichen Zusammenfassung.'},
  'summarizer.max_tokens_weekly': {title:'Länge woechentlich', text:'Max. Länge der woechentlichen Zusammenfassung.'},
  'summarizer.max_tokens_monthly': {title:'Länge monatlich', text:'Max. Länge der monatlichen Zusammenfassung.'},
  'context.recent_conversations': {title:'Gespräche merken', text:'Wie viele vergangene Gespräche Jarvis sich im normalen Modus merkt (pro Nachricht).'},
  'context.conversation_mode_timeout': {title:'Gesprächsmodus Timeout', text:'Wenn die letzte Nachricht weniger als X Sekunden her ist, aktiviert Jarvis den Gesprächsmodus und merkt sich doppelt so viele Nachrichten. So kannst du längere Gespräche führen.'},
  'context.api_timeout': {title:'HA-API Timeout', text:'Timeout für Home-Assistant-Anfragen (Sek).'},
  'context.llm_timeout': {title:'LLM Timeout', text:'Timeout für KI-Anfragen (Sek). Größere Modelle brauchen länger.'},
  // === STIMMUNG ===
  'mood.rapid_command_seconds': {title:'Schnelle Befehle', text:'Zeitfenster für "schnelle Befehle hintereinander" (Sek).'},
  'mood.stress_decay_seconds': {title:'Stress-Abbau', text:'Nach wie vielen Sek Ruhe der Stress sinkt.'},
  'mood.frustration_threshold': {title:'Frustrations-Schwelle', text:'Ab wie vielen Stress-Punkten Frustration erkannt wird.'},
  'mood.tired_hour_start': {title:'Muede ab', text:'Ab welcher Uhrzeit Müdigkeit angenommen wird.'},
  'mood.tired_hour_end': {title:'Muede bis', text:'Bis zu welcher Uhrzeit Müdigkeit gilt.'},
  'mood.rapid_command_stress_boost': {title:'Stress: Schnelle Befehle', text:'Stressanstieg durch schnelle Befehle hintereinander.'},
  'mood.positive_stress_reduction': {title:'Stress: Positive Worte', text:'Stressabbau durch positive Worte.'},
  'mood.negative_stress_boost': {title:'Stress: Negative Worte', text:'Stressanstieg durch negative Worte.'},
  'mood.impatient_stress_boost': {title:'Stress: Ungeduld', text:'Stressanstieg durch ungedulige Worte.'},
  'mood.tired_boost': {title:'Stress: Müdigkeit', text:'Stresseinfluss durch Müdigkeit.'},
  'mood.repetition_stress_boost': {title:'Stress: Wiederholungen', text:'Stressanstieg durch wiederholte Befehle.'},
  'mood.positive_keywords': {title:'Positive Wörter', text:'Wörter die gute Stimmung signalisieren.'},
  'mood.negative_keywords': {title:'Negative Wörter', text:'Wörter die schlechte Stimmung signalisieren.'},
  'mood.impatient_keywords': {title:'Ungeduld-Wörter', text:'Wörter die Ungeduld signalisieren.'},
  'mood.tired_keywords': {title:'Müdigkeits-Wörter', text:'Wörter die Müdigkeit signalisieren.'},
  // === SPRACH-ENGINE ===
  'speech.stt_model': {title:'Whisper-Modell', text:'Größere Modelle sind genauer aber langsamer. "small" ist für CPU empfohlen, "large-v3-turbo" für GPU.'},
  'speech.stt_language': {title:'Sprache', text:'Sprache für die Spracherkennung. Beeinflusst Genauigkeit der Transkription.'},
  'speech.stt_beam_size': {title:'Beam Size', text:'Höhere Werte = genauere Erkennung, aber langsamer. Standard: 5.'},
  'speech.stt_compute': {title:'Berechnung', text:'int8 für CPU (schnell, wenig RAM), float16 für GPU, float32 für maximale Praezision.'},
  'speech.stt_device': {title:'Hardware', text:'CPU für Standard-Betrieb, CUDA für NVIDIA GPU (NVIDIA Container Toolkit erforderlich).'},
  'speech.tts_voice': {title:'Piper-Stimme', text:'Stimme für die Sprachsynthese. "thorsten-high" hat die beste Qualitaet auf Deutsch.'},
  'speech.auto_night_whisper': {title:'Nacht-Flüstern', text:'Jarvis spricht nachts automatisch leiser (basierend auf den Lautstärke-Einstellungen).'},
  'voice_analysis.enabled': {title:'Stimm-Analyse', text:'Analysiert Sprechtempo zur Stimmungserkennung.'},
  'voice_analysis.wpm_fast': {title:'Schnelles Sprechen (WPM)', text:'Ab wie vielen Wörtern/Min schnelles Sprechen erkannt wird.'},
  'voice_analysis.wpm_slow': {title:'Langsames Sprechen (WPM)', text:'Unter wie vielen Wörtern/Min langsames Sprechen gilt.'},
  'voice_analysis.wpm_normal': {title:'Normales Tempo (WPM)', text:'Referenzwert für normales Sprechtempo.'},
  'voice_analysis.use_whisper_metadata': {title:'Whisper-Metadaten', text:'Zusätzliche Daten von Whisper für Analyse nutzen.'},
  'voice_analysis.voice_weight': {title:'Stimm-Gewichtung', text:'Wie stark Stimm-Analyse die Gesamtstimmung beeinflusst (0-1).'},
  // === RAEUME ===
  'room_temperature.sensors': {title:'Temperatursensoren', text:'HA-Sensoren für Raumtemperatur.'},
  'health_monitor.humidity_sensors': {title:'Feuchtigkeitssensoren', text:'HA-Sensoren für Luftfeuchtigkeits-Überwachung. Ohne Auswahl werden alle Sensoren geprüft.'},
  'multi_room.enabled': {title:'Multi-Room', text:'Erkennt in welchem Raum du bist.'},
  'multi_room.presence_timeout_minutes': {title:'Praesenz-Timeout', text:'Nach wie vielen Min ohne Bewegung der Raum leer ist.'},
  'multi_room.auto_follow': {title:'Musik folgen', text:'Musik folgt automatisch von Raum zu Raum.'},
  'follow_me.enabled': {title:'Follow-Me', text:'JARVIS folgt dir von Raum zu Raum. Musik, Licht und Temperatur wechseln automatisch.'},
  'follow_me.cooldown_seconds': {title:'Cooldown', text:'Mindestabstand zwischen Follow-Me Transfers. Verhindert Ping-Pong bei schnellen Raumwechseln.'},
  'follow_me.transfer_music': {title:'Musik folgt', text:'Musik wird automatisch in den neuen Raum transferiert.'},
  'follow_me.transfer_lights': {title:'Licht folgt', text:'Licht wird im alten Raum aus- und im neuen Raum eingeschaltet.'},
  'follow_me.transfer_climate': {title:'Klima folgt', text:'Heizung/Kühlung wird im neuen Raum auf Komfort-Temperatur gesetzt.'},
  'multi_room.room_speakers': {title:'Speaker-Zuordnung', text:'Welcher Speaker in welchem Raum steht.'},
  'multi_room.room_motion_sensors': {title:'Bewegungsmelder', text:'Welcher Melder in welchem Raum haengt.'},
  'activity.entities.media_players': {title:'Media Player', text:'Media Player für Aktivitätserkennung.'},
  'activity.entities.mic_sensors': {title:'Mikrofon-Sensoren', text:'Mikrofon-Sensoren für Spracheingabe.'},
  'activity.entities.bed_sensors': {title:'Bett-Sensoren', text:'Sensoren für Schlaf-Erkennung.'},
  'activity.entities.pc_sensors': {title:'PC-Sensoren', text:'Sensoren für Arbeits-Erkennung.'},
  'activity.thresholds.night_start': {title:'Nacht beginnt', text:'Ab wann Nachtruhe gilt.'},
  'activity.thresholds.night_end': {title:'Nacht endet', text:'Bis wann Nachtruhe gilt.'},
  'activity.thresholds.guest_person_count': {title:'Besuch ab Personen', text:'Ab wie vielen Personen Gäste-Modus aktiviert wird.'},
  'activity.thresholds.focus_min_minutes': {title:'Fokus-Modus', text:'Ab wie vielen Min ununterbrochener Arbeit Fokus erkannt wird.'},
  'activity.silence_matrix': {title:'Stille-Matrix', text:'Bestimmt pro Aktivität und Dringlichkeit, wie Benachrichtigungen zugestellt werden: Laut (TTS), Leise, LED-Signal oder Unterdrücken.'},
  'activity.volume_matrix': {title:'Lautstärke-Matrix', text:'Lautstärke für TTS-Durchsagen, abhaengig von Aktivität und Dringlichkeit. Werte 0-100%. Nachts wird automatisch zusätzlich reduziert.'},
  'scenes': {title:'Szenen', text:'Zentrale Szenen-Verwaltung. Jede Szene wird einer Aktivität zugeordnet (bestimmt Benachrichtigungs-Verhalten), hat eine Licht-Übergangszeit und kann als "Nicht stören" markiert werden.'},
  // === LICHTSTEUERUNG ===
  'lighting.enabled': {title:'Lichtsteuerung', text:'Master-Schalter für alle automatischen Licht-Funktionen.'},
  'lighting.auto_on_dusk': {title:'Auto-An bei Dämmerung', text:'Schaltet Lichter automatisch ein wenn die Sonne untergeht und jemand zuhause ist.'},
  'lighting.auto_off_away': {title:'Auto-Aus bei Abwesenheit', text:'Schaltet alle Lichter aus wenn niemand mehr zuhause ist.'},
  'lighting.auto_off_empty_room_minutes': {title:'Leerer-Raum Timeout', text:'Nach wie vielen Minuten ohne Bewegung das Licht im Raum automatisch ausgeschaltet wird.'},
  'lighting.night_dimming': {title:'Nacht-Dimming', text:'Dimmt Lichter automatisch nach der konfigurierten Startzeit auf die Nacht-Helligkeit herunter.'},
  'lighting.night_dimming_start_hour': {title:'Night-Dimming Start', text:'Ab dieser Uhrzeit werden eingeschaltete Lichter langsam gedimmt.'},
  'lighting.night_dimming_transition': {title:'Night-Dimming Dauer', text:'Wie lange der Dimm-Übergang dauert. Länger = sanfter.'},
  'lighting.dusk_only_occupied_rooms': {title:'Dämmerung nur besetzte Räume', text:'Bei Dämmerung nur in Räumen Licht einschalten, in denen der Präsenzmelder kuerzlich Bewegung erkannt hat.'},
  'lighting.default_transition': {title:'Standard-Übergang', text:'Standard-Dimmzeit für alle Licht-Aktionen.'},
  'lighting.presence_control.enabled': {title:'Praesenz-Steuerung', text:'Bewegungsmelder steuern das Licht automatisch. Bei Bewegung geht Licht an, ohne Bewegung nach eingestellter Zeit wieder aus.'},
  'lighting.presence_control.auto_on_motion': {title:'Licht an bei Bewegung', text:'Wenn ein Präsenzmelder Bewegung erkennt, wird das Licht im Raum automatisch eingeschaltet — mit adaptiver Helligkeit je nach Tageszeit.'},
  'lighting.presence_control.night_path_light': {title:'Nacht-Pfadlicht', text:'Wenn jemand nachts aufsteht, geht in konfigurierten Räumen (Flur, Bad) ein sehr schwaches warmweißes Licht an — gerade genug zur Orientierung, ohne voll wach zu werden.'},
  'lighting.presence_control.night_path_brightness': {title:'Pfadlicht-Helligkeit', text:'Wie hell das Nacht-Pfadlicht ist (in %). 3-5% reicht meist zur Orientierung.'},
  'lighting.presence_control.night_path_timeout_minutes': {title:'Pfadlicht-Dauer', text:'Wie lange das Pfadlicht an bleibt bevor es automatisch ausgeht.'},
  'lighting.presence_control.manual_override_minutes': {title:'Override-Schutz', text:'Nach manueller Licht-Bedienung (z.B. "Licht auf 80%") greift die Automatik für diese Zeit nicht ein. Verhindert Konflikte zwischen Benutzer und Automatik.'},
  'lighting.presence_control.night_start_hour': {title:'Nacht beginnt', text:'Ab dieser Uhrzeit gilt das Nacht-Verhalten (Pfadlicht statt volle Helligkeit).'},
  'lighting.presence_control.night_end_hour': {title:'Nacht endet', text:'Bis zu dieser Uhrzeit gilt das Nacht-Verhalten.'},
  'lighting.bed_sensors.enabled': {title:'Bettsensor-Integration', text:'Erkennt über Bettsensoren ob jemand im Bett liegt. Steuert Sleep-Mode und Aufwach-Licht.'},
  'lighting.bed_sensors.sleep_mode': {title:'Sleep-Mode', text:'Wenn der Bettsensor Belegung erkennt (nach der konfigurierten Startzeit), werden alle Lichter im Haus langsam gedimmt und ausgeschaltet.'},
  'lighting.bed_sensors.sleep_dim_transition': {title:'Sleep-Dimming Dauer', text:'Wie lange das langsame Abdunkeln beim Einschlafen dauert. 300 Sekunden (5 Min) ist ein sanfter Übergang.'},
  'lighting.bed_sensors.sleep_start_hour': {title:'Schlafmodus ab', text:'Ab dieser Uhrzeit wird Bett-Belegung als Einschlafen gewertet und der Sleep-Mode aktiviert.'},
  'lighting.bed_sensors.wakeup_light': {title:'Aufwach-Licht', text:'Wenn der Bettsensor morgens leer wird, wird im Schlafzimmer sanft Licht hochgefahren — wie ein natürlicher Sonnenaufgang.'},
  'lighting.bed_sensors.wakeup_brightness': {title:'Aufwach-Helligkeit', text:'Ziel-Helligkeit beim Aufwachen. Nicht zu hell (30-50% empfohlen).'},
  'lighting.bed_sensors.wakeup_transition': {title:'Aufhell-Dauer', text:'Wie lange das Aufhellen beim Aufwachen dauert. Länger = sanfter.'},
  'lighting.bed_sensors.wakeup_window_start': {title:'Aufwach-Fenster Start', text:'Frueheste Uhrzeit ab der Aufwach-Licht aktiv wird.'},
  'lighting.bed_sensors.wakeup_window_end': {title:'Aufwach-Fenster Ende', text:'Späteste Uhrzeit bis zu der Aufwach-Licht aktiv ist.'},
  'lighting.lux_adaptive.enabled': {title:'Lux-Adaptiv', text:'Passt die künstliche Beleuchtung automatisch an das vorhandene Tageslicht an. Bei viel Sonne wird weniger Kunstlicht benötigt. Braucht einen Lux-Sensor pro Raum.'},
  'lighting.lux_adaptive.target_lux': {title:'Ziel-Beleuchtungsstaerke', text:'Gewuenschte Gesamthelligkeit im Raum (natürlich + kuenstlich). 300-500 Lux ist typisch für Wohnräume.'},
  'lighting.lux_adaptive.min_brightness_pct': {title:'Min. Kunstlicht', text:'Minimale künstliche Helligkeit — auch bei viel Tageslicht bleibt mindestens dieser Wert.'},
  'lighting.lux_adaptive.max_brightness_pct': {title:'Max. Kunstlicht', text:'Maximale künstliche Helligkeit bei komplett dunklem Raum.'},
  // === LICHT WETTER-INTEGRATION ===
  'lighting.weather_boost.enabled': {title:'Wetter-Integration', text:'Nutzt die aktuelle Wetterbedingung für intelligentere Lichtsteuerung. Bei Bewölkung/Regen werden Lichter automatisch heller, bei Dämmerung wird früher eingeschaltet.'},
  'lighting.weather_boost.weather_entity': {title:'Wetter-Entity (Licht)', text:'Welche weather-Entity für die Licht-Wetter-Integration genutzt wird. Leer = automatisch (weather.forecast_home bevorzugt, gleiche Logik wie Cover-Automatik).'},
  'lighting.weather_boost.cloud_boost_pct': {title:'Boost bei Bewölkung', text:'Um wieviel Prozent eingeschaltete Lichter bei bewölktem Himmel heller werden. Hilft wenn Tageslicht nicht reicht, die Dämmerung aber noch nicht erreicht ist.'},
  'lighting.weather_boost.rain_boost_pct': {title:'Boost bei Regen', text:'Um wieviel Prozent eingeschaltete Lichter bei Regen/Gewitter heller werden. Regen verdunkelt stärker als Wolken.'},
  'lighting.weather_boost.dusk_earlier_on_cloudy': {title:'Frühere Dämmerung', text:'An trüben Tagen wird die Dämmerungs-Schwelle angehoben, sodass das Auto-An früher greift. Die Sonne steht zwar noch über dem Horizont, aber es ist trotzdem dunkel genug für Kunstlicht.'},
  'lighting.weather_boost.dusk_cloud_elevation_offset': {title:'Dämmerung-Offset', text:'Um wieviel Grad die Dämmerungs-Schwelle bei Bewölkung angehoben wird. Z.B. normal -2°, bei Wolken +3° = Trigger bei +1° (Sonne noch über Horizont, aber trueb).'},
  // === COVER-AUTOMATIK ===
  'seasonal_actions.enabled': {title:'Saisonale Aktionen', text:'Automatische Aktionen basierend auf Jahreszeit, Wetter und Sonnenstand.'},
  'seasonal_actions.cover_automation.sun_tracking': {title:'Sonnenstand-Tracking', text:'Rollläden folgen automatisch dem Sonnenstand. Benötigt konfigurierte Cover-Profile.'},
  'seasonal_actions.cover_automation.temperature_based': {title:'Temperatur-Steuerung', text:'Rollläden reagieren auf Aussentemperatur (Hitze- und Kälteschutz).'},
  'seasonal_actions.cover_automation.weather_protection': {title:'Wetterschutz', text:'Markisen bei Sturm/Regen automatisch einfahren.'},
  'seasonal_actions.cover_automation.night_insulation': {title:'Nacht-Isolierung', text:'Rollläden nachts schließen für bessere Wärmedämmung.'},
  'seasonal_actions.cover_automation.heat_protection_temp': {title:'Hitzeschutz-Temperatur', text:'Ab dieser Aussentemperatur werden Rollläden bei Sonneneinstrahlung geschlossen.'},
  'seasonal_actions.cover_automation.frost_protection_temp': {title:'Frostschutz-Temperatur', text:'Bei dieser Temperatur werden Rollläden zum Schutz geschlossen.'},
  'seasonal_actions.cover_automation.storm_wind_speed': {title:'Sturm-Geschwindigkeit', text:'Ab dieser Windgeschwindigkeit werden Rollläden zum Schutz hochgefahren.'},
  'seasonal_actions.cover_automation.presence_simulation': {title:'Urlaubs-Simulation', text:'Simuliert Anwesenheit über Rollläden wenn Urlaubsmodus aktiv ist.'},
  'seasonal_actions.cover_automation.vacation_mode_entity': {title:'Urlaubsmodus-Entity', text:'HA input_boolean für Urlaubsmodus. Muss manuell in HA erstellt werden.'},
  'vacation_simulation.morning_hour': {title:'Morgens öffnen', text:'Uhrzeit für simuliertes Öffnen der Rollläden.'},
  'vacation_simulation.evening_hour': {title:'Abends schließen', text:'Uhrzeit für simuliertes Schließen.'},
  'vacation_simulation.variation_minutes': {title:'Variation', text:'Zufaellige Abweichung in Minuten für realistischere Simulation.'},
  'vacation_simulation.night_hour': {title:'Nachts komplett zu', text:'Uhrzeit ab der alle Rollläden in der Urlaubssimulation komplett geschlossen werden.'},
  'seasonal_actions.cover_automation.inverted_position': {title:'Invertierte Positionen', text:'Aktivieren wenn ALLE Cover invertierte Werte nutzen (0=offen, 100=zu, z.B. Shelly/MQTT). Kann auch pro Cover in den Cover-Profilen gesetzt werden.'},
  'seasonal_actions.cover_automation.night_start_hour': {title:'Nacht-Beginn', text:'Ab dieser Stunde gilt die Nacht-Isolierung. Im Winter früher (z.B. 18), im Sommer später (z.B. 23).'},
  'seasonal_actions.cover_automation.night_end_hour': {title:'Nacht-Ende', text:'Bis zu dieser Stunde gilt die Nacht-Isolierung.'},
  'seasonal_actions.cover_automation.hysteresis_temp': {title:'Temperatur-Hysterese', text:'Verhindert Oszillation: Schließen bei Hitzeschutz-Temp, erst wieder öffnen bei Hitzeschutz-Temp MINUS Hysterese. Z.B. 26°C zu, 24°C auf.'},
  'seasonal_actions.cover_automation.hysteresis_wind': {title:'Wind-Hysterese', text:'Verhindert Oszillation bei Sturmschutz. Schließen bei Sturm-Speed, öffnen bei Sturm-Speed MINUS Hysterese.'},
  'seasonal_actions.cover_automation.glare_protection': {title:'Blendschutz', text:'Wenn ein Sitzsensor (occupancy_sensor im Cover-Profil) belegt ist und Sonne auf das Fenster scheint, wird der Sonnenschutz aktiviert — auch unter der Hitzeschutz-Temperatur.'},
  'seasonal_actions.cover_automation.gradual_morning': {title:'Sanftes Öffnen', text:'Morgens werden die Rollläden in 3 Stufen geöffnet (30% → 70% → 100%) mit je 5 Min Pause. Weniger abrupt als sofort 100%.'},
  'seasonal_actions.cover_automation.wave_open': {title:'Wellenförmiges Öffnen', text:'Rollläden öffnen nacheinander: Ost-Fenster zuerst, dann Sued, dann West. Natürlicher und reduziert die Stromlast.'},
  'seasonal_actions.cover_automation.heating_integration': {title:'Heizungs-Integration', text:'Wenn die Heizung läuft + Aussentemp kalt: Nicht-sonnenbeschienene Fenster zu (Isolierung). Wenn Sonne + Heizung aus: Sonnenfenster auf (passive Solarwärme).'},
  'seasonal_actions.cover_automation.co2_ventilation': {title:'CO2-Lueftung', text:'Bei hohem CO2 (>1000 ppm) und gutem Wetter (10-25°C, kein Regen) wird eine Lueftungsempfehlung gegeben.'},
  'seasonal_actions.cover_automation.privacy_mode': {title:'Privacy-Modus', text:'Abends nach Sonnenuntergang: Wenn im Raum Licht an ist, werden Rollläden mit privacy_mode=true im Cover-Profil geschlossen (Sichtschutz).'},
  'seasonal_actions.cover_automation.privacy_close_hour': {title:'Privacy ab Uhrzeit', text:'Ab welcher Uhrzeit der Privacy-Modus aktiviert wird (z.B. 17 = ab 17 Uhr). Muss gleichzeitig dunkel sein (Sonnenuntergang). Ohne Angabe: sobald es dunkel ist.'},
  'seasonal_actions.cover_automation.presence_aware': {title:'Praesenz-basiert', text:'Wenn alle Personen das Haus verlassen haben, werden alle Rollläden geschlossen (Einbruchschutz + Energiesparen).'},
  'seasonal_actions.cover_automation.manual_override_hours': {title:'Manueller Override', text:'Wenn ein Rollladen manuell (Taster/App) bedient wird, pausiert die Automatik für diese Anzahl Stunden. Verhindert dass die Automatik manuelle Einstellungen überschreibt.'},
  'seasonal_actions.cover_automation.sunset_close_elevation': {title:'Schließen ab Elevation', text:'Ab welcher Sonnenhöhe (Elevation) die Rollläden abends geschlossen werden. -2° (Standard) = kurz nach Sonnenuntergang. 0° = genau bei Sonnenuntergang. Negative Werte = später (dunkler). Positive Werte = früher (noch hell).'},
  'seasonal_actions.cover_automation.wakeup_sun_check': {title:'Aufwach-Sonnenprüfung', text:'Prüft beim Aufwachen den Sonnenstand (sun.sun). Wenn es noch zu dunkel ist, werden die Rollläden erst bei Dämmerung geöffnet statt sofort. Verhindert dass Rollläden mitten in der Nacht hochfahren.'},
  'seasonal_actions.cover_automation.wakeup_min_sun_elevation': {title:'Min. Sonnenhöhe beim Aufwachen', text:'Mindest-Sonnenhöhe (in Grad) damit Rollläden beim Aufwachen geöffnet werden. -6° = Bürgerliche Dämmerung (Himmel wird hell). -12° = Nautische Dämmerung. 0° = Sonnenaufgang. Bei niedrigerem Sonnenstand wird das Öffnen verschoben.'},
  'seasonal_actions.cover_automation.wakeup_fallback_max_minutes': {title:'Fallback-Öffnung', text:'Maximale Wartezeit nach dem geplanten Öffnungszeitpunkt. Wenn die Sonne innerhalb dieses Zeitraums nicht hoch genug steigt (z.B. trüber Wintertag), werden die Rollläden trotzdem geöffnet. Verhindert dass man den ganzen Tag im Dunkeln sitzt.'},
  'seasonal_actions.cover_automation.sleep_lock_minutes': {title:'Sleep-Lock Dauer', text:'Wenn Schlaf erkannt wird, bleibt der Rollladenschutz für diese Dauer aktiv — auch wenn ein Bettsensor kurz ausfällt (Person dreht sich um, Sensor-Verzögerung). Kürzere Werte = schnelleres Öffnen nach dem Aufstehen. Längere Werte = mehr Schutz gegen Sensor-Flackern.'},
  'seasonal_actions.cover_automation.weather_entity': {title:'Wetter-Entity', text:'Welche weather-Entity aus Home Assistant für die Cover-Automatik genutzt wird. Leer = automatisch (bevorzugt weather.forecast_home, Fallback: erste weather.* Entity). Änderbar per UI oder per Sprache ("Jarvis, wechsle Wetter-Integration auf weather.home").'},
  'seasonal_actions.cover_automation.forecast_weather_protection': {title:'Vorhersage-Wetterschutz', text:'Nutzt die Wettervorhersage aus der konfigurierten Wetter-Entity für vorausschauenden Schutz. Faehrt Markisen ein BEVOR ein Sturm kommt und schließt Dachfenster BEVOR es regnet — statt erst zu reagieren wenn es schon zu spaet ist.'},
  'seasonal_actions.cover_automation.forecast_lookahead_hours': {title:'Vorhersage-Zeitraum', text:'Wie viele Stunden in die Zukunft die Wettervorhersage für Schutzentscheidungen genutzt wird. Mehr Stunden = früheres Reagieren, aber auch mehr Fehlalarme.'},
  'seasonal_actions.cover_automation.disable_addon_cover_domain': {title:'Addon-Plugin deaktivieren', text:'Deaktiviert das Cover-Domain Plugin im Addon. Empfohlen, da die ProactiveEngine (Assistant-seitig) intelligenter und umfangreicher ist. Verhindert Konflikte zwischen den zwei Systemen.'},
  // === SAUGROBOTER ===
  'remote.enabled': {title:'Fernbedienung', text:'Aktiviert die Fernbedienungs-Steuerung (Logitech Harmony) über Jarvis. Erlaubt Sprachsteuerung für TV, Receiver, etc.'},
  'vacuum.enabled': {title:'Saugroboter', text:'Aktiviert die Saugroboter-Steuerung über Jarvis.'},
  'vacuum.auto_clean.enabled': {title:'Auto-Clean', text:'Automatische Reinigung wenn niemand zuhause ist.'},
  'vacuum.auto_clean.mode': {title:'Auto-Clean Modus', text:'Smart: startet wenn niemand zuhause. Wochenplan: feste Tage/Uhrzeit. Beides: kombiniert.'},
  'vacuum.auto_clean.schedule_days': {title:'Reinigungstage', text:'An welchen Wochentagen automatisch gereinigt wird (Modus Wochenplan/Beides).'},
  'vacuum.auto_clean.schedule_time': {title:'Uhrzeit', text:'Um welche Uhrzeit der Wochenplan-Modus die Reinigung startet.'},
  'vacuum.auto_clean.when_nobody_home': {title:'Nur bei Abwesenheit', text:'Startet nur wenn alle Personen abwesend sind.'},
  'vacuum.auto_clean.min_hours_between': {title:'Mindestabstand', text:'Minimale Stunden zwischen zwei automatischen Reinigungen.'},
  'vacuum.auto_clean.preferred_time_start': {title:'Bevorzugt ab', text:'Frueheste Uhrzeit für Smart-Modus Reinigung.'},
  'vacuum.auto_clean.preferred_time_end': {title:'Bevorzugt bis', text:'Späteste Uhrzeit für Smart-Modus Reinigung.'},
  'vacuum.auto_clean.auto_fan_speed': {title:'Saugstaerke (Auto)', text:'Saugstaerke für automatische Reinigungen. Überschreibt den Standard-Wert.'},
  'vacuum.auto_clean.auto_mode': {title:'Modus (Auto)', text:'Reinigungsmodus für automatische Reinigungen: saugen, wischen, oder beides.'},
  'vacuum.auto_clean.not_during': {title:'Nicht während', text:'Situationen in denen der Saugroboter NICHT automatisch starten soll.'},
  'vacuum.presence_guard.enabled': {title:'Anwesenheits-Steuerung', text:'Vacuum faehrt NUR wenn niemand zuhause ist. Gilt für alle Trigger (Auto-Clean, Steckdose, Szene).'},
  'vacuum.presence_guard.switch_alarm_for_cleaning': {title:'Alarm umschalten', text:'Schaltet die Alarmanlage automatisch von abwesend auf anwesend bevor der Saugroboter startet (verhindert Fehlalarme). Nach der Reinigung wird zurückgeschaltet.'},
  'vacuum.presence_guard.alarm_entity': {title:'Alarm-Entity', text:'Entity-ID der Alarmanlage (z.B. alarm_control_panel.alarmo). Leer = automatische Erkennung.'},
  'vacuum.presence_guard.pause_on_arrival': {title:'Pause bei Heimkehr', text:'Pausiert den Saugroboter und schickt ihn zur Ladestation wenn jemand nachhause kommt.'},
  'vacuum.presence_guard.resume_on_departure': {title:'Fortsetzung bei Abwesenheit', text:'Setzt die unterbrochene Reinigung fort sobald wieder alle weg sind.'},
  'vacuum.presence_guard.resume_delay_minutes': {title:'Verzögerung Fortsetzung', text:'Wartet diese Minuten bevor die Reinigung fortgesetzt wird. Verhindert Neustart wenn jemand nur kurz reinkommt.'},
  'vacuum.default_fan_speed': {title:'Standard-Saugstaerke', text:'Standard-Saugstaerke wenn nicht explizit angegeben.'},
  'vacuum.default_mode': {title:'Standard-Modus', text:'Standard-Reinigungsmodus: nur saugen, nur wischen, oder beides.'},
  'vacuum.power_trigger.enabled': {title:'Steckdosen-Trigger', text:'Startet Reinigung automatisch wenn eine überwachte Steckdose abschaltet (z.B. nach dem Kochen).'},
  'vacuum.power_trigger.delay_minutes': {title:'Verzögerung', text:'Wartet diese Minuten nach dem Abschalten bevor der Saugroboter startet.'},
  'vacuum.power_trigger.cooldown_hours': {title:'Cooldown', text:'Nach einer Reinigung wird dieser Trigger für die angegebene Zeit deaktiviert.'},
  'vacuum.scene_trigger.enabled': {title:'Szenen-Trigger', text:'Startet Reinigung automatisch wenn eine bestimmte HA-Szene aktiviert wird.'},
  'vacuum.scene_trigger.delay_minutes': {title:'Verzögerung', text:'Wartet diese Minuten nach Szenen-Aktivierung bevor der Saugroboter startet.'},
  'vacuum.scene_trigger.cooldown_hours': {title:'Cooldown', text:'Nach einer Reinigung wird dieser Trigger für die angegebene Zeit deaktiviert.'},
  'vacuum.maintenance.enabled': {title:'Wartung', text:'Überwacht Verschleißteile (Filter, Bürsten, Mopp).'},
  'vacuum.maintenance.check_interval_hours': {title:'Prüf-Intervall', text:'Wie oft die Verschleißteile geprüft werden.'},
  'vacuum.maintenance.warn_at_percent': {title:'Warnung bei', text:'Warnt wenn ein Verschleissteil unter diesen Prozentwert fällt.'},
  // === STIMME & TTS ===
  'sounds.default_speaker': {title:'Standard-Speaker', text:'Standard-Geraet für Sprachausgabe und Sounds.'},
  'sounds.tts_entity': {title:'TTS-Engine', text:'Welche Text-to-Speech Engine genutzt wird.'},
  'sounds.alexa_speakers': {title:'Alexa Speaker', text:'Echo/Alexa Geräte für Benachrichtigungen.'},
  'tts.ssml_enabled': {title:'SSML', text:'Erweiterte Sprachsteuerung (Betonung, Pausen). Nicht alle Engines unterstützt.'},
  'tts.prosody_variation': {title:'Prosody', text:'Tonhoehe und Tempo variieren je nach Kontext.'},
  'tts.speed.confirmation': {title:'Tempo: Bestätigung', text:'Sprechgeschwindigkeit bei Bestätigungen (100=normal).'},
  'tts.speed.warning': {title:'Tempo: Warnung', text:'Sprechgeschwindigkeit bei Warnungen.'},
  'tts.speed.briefing': {title:'Tempo: Briefing', text:'Sprechgeschwindigkeit bei Briefings.'},
  'tts.speed.greeting': {title:'Tempo: Begrüßung', text:'Sprechgeschwindigkeit bei Begrüßungen.'},
  'tts.speed.question': {title:'Tempo: Frage', text:'Sprechgeschwindigkeit bei Fragen.'},
  'tts.speed.casual': {title:'Tempo: Normal', text:'Sprechgeschwindigkeit bei normalen Antworten.'},
  'tts.pauses.before_important': {title:'Pause: Wichtig', text:'ms Pause vor wichtigen Infos.'},
  'tts.pauses.between_sentences': {title:'Pause: Sätze', text:'ms Pause zwischen Sätzen.'},
  'tts.pauses.after_greeting': {title:'Pause: Begrüßung', text:'ms Pause nach der Begrüßung.'},
  'tts.whisper_triggers': {title:'Flüstern bei', text:'Bei welchen Situationen geflüstert wird.'},
  'tts.whisper_cancel_triggers': {title:'Flüstern beenden', text:'Was den Flüstermodus beendet.'},
  'volume.day': {title:'Lautstärke: Tag', text:'Lautstärke tagsüber (0-1).'},
  'volume.evening': {title:'Lautstärke: Abend', text:'Lautstärke am Abend.'},
  'volume.night': {title:'Lautstärke: Nacht', text:'Lautstärke nachts.'},
  'volume.sleeping': {title:'Lautstärke: Schlaf', text:'Lautstärke im Schlafmodus.'},
  'volume.emergency': {title:'Lautstärke: Notfall', text:'Lautstärke bei Notfaellen. Sollte hoch sein.'},
  'volume.whisper': {title:'Lautstärke: Flüstern', text:'Lautstärke im Flüstermodus.'},
  'volume.morning_start': {title:'Morgen ab', text:'Ab welcher Stunde Tages-Lautstärke gilt.'},
  'volume.evening_start': {title:'Abend ab', text:'Ab welcher Stunde Abend-Lautstärke gilt.'},
  'volume.night_start': {title:'Nacht ab', text:'Ab welcher Stunde Nacht-Lautstärke gilt.'},
  'sounds.enabled': {title:'Sound-Effekte', text:'Kurze Toene bei Events (Zuhoeren, Bestätigung, Warnung).'},
  'sounds.events.listening': {title:'Sound: Zuhoeren', text:'Sound beim Start des Zuhoerens.'},
  'sounds.events.confirmed': {title:'Sound: Bestätigung', text:'Sound nach Bestätigung.'},
  'sounds.events.warning': {title:'Sound: Warnung', text:'Sound bei Warnungen.'},
  'sounds.events.alarm': {title:'Sound: Alarm', text:'Sound bei Alarmen.'},
  'sounds.events.doorbell': {title:'Sound: Tuerklingel', text:'Sound bei Tuerklingel-Events.'},
  'sounds.events.greeting': {title:'Sound: Begrüßung', text:'Sound bei Begrüßungen.'},
  'sounds.events.error': {title:'Sound: Fehler', text:'Sound bei Fehlern.'},
  'sounds.events.goodnight': {title:'Sound: Gute Nacht', text:'Sound bei Gute-Nacht-Routine.'},
  'sounds.night_volume_factor': {title:'Nacht-Sound-Faktor', text:'Sound-Lautstärke nachts als Faktor (0.3 = 30%).'},
  'narration.enabled': {title:'Szenen-Narration', text:'Assistent erzählt bei Szenen-Wechseln was passiert.'},
  'narration.default_transition': {title:'Standard-Übergang', text:'Standard-Dauer für Szenen-Übergänge (Sek).'},
  'narration.scene_transitions.filmabend': {title:'Filmabend-Übergang', text:'Übergangs-Dauer Filmabend-Szene.'},
  'narration.scene_transitions.gute_nacht': {title:'Gute-Nacht-Übergang', text:'Übergangs-Dauer Gute-Nacht-Szene.'},
  'narration.scene_transitions.aufwachen': {title:'Aufwach-Übergang', text:'Übergangs-Dauer Aufwach-Szene.'},
  'narration.scene_transitions.gemuetlich': {title:'Gemuetlich-Übergang', text:'Übergangs-Dauer Gemuetlich-Szene.'},
  'narration.step_delay': {title:'Schritt-Verzögerung', text:'Pause zwischen Aktionen innerhalb einer Szene.'},
  'narration.narrate_actions': {title:'Aktionen ansagen', text:'Bei Szenen-Wechseln ansagen was passiert.'},
  'speaker_recognition.enabled': {title:'Sprecher-Erkennung', text:'Erkennt wer spricht und passt Antworten an.'},
  'speaker_recognition.min_confidence': {title:'Erkennungs-Sicherheit', text:'Wie sicher die Erkennung sein muss (0.6 empfohlen). Unter diesem Wert wird nachgefragt.'},
  'speaker_recognition.enrollment_duration': {title:'Einlern-Dauer', text:'Wie lange eine Person sprechen muss zum Einlernen.'},
  'speaker_recognition.fallback_ask': {title:'Nachfragen', text:'Bei unsicherer Erkennung nachfragen "Wer spricht?" — die Antwort wird für den Stimmabdruck gelernt.'},
  'speaker_recognition.max_profiles': {title:'Max. Profile', text:'Max. Anzahl gespeicherter Sprecher-Profile.'},
  'speaker_recognition.device_mapping': {title:'Geräte-Zuordnung', text:'Welches ESPHome-Geraet gehört welcher Person? Format: Device-ID → Person. Die Device-ID findest du in HA unter Einstellungen → Geräte → ESPHome.'},
  'speaker_recognition.doa_mapping': {title:'Richtungs-Zuordnung (DoA)', text:'Direction of Arrival: Welcher Winkel gehört welcher Person pro Geraet? Erfordert ReSpeaker XVF3800. Format: Winkelbereich (z.B. "0-90") → Person.'},
  'speaker_recognition.doa_tolerance': {title:'DoA-Toleranz', text:'Toleranz für die Richtungserkennung in Grad. Größere Werte sind toleranter, kleinere präziser.'},
  // === ROUTINEN ===
  'routines.morning_briefing.enabled': {title:'Morgen-Briefing', text:'Automatisches Update am Morgen mit Wetter, Terminen, Neuigkeiten.'},
  'routines.morning_briefing.trigger': {title:'Briefing-Auslöser', text:'Was das Morgen-Briefing auslöst (Bewegung, Sprache, Wecker).'},
  'routines.morning_briefing.modules': {title:'Briefing-Module', text:'Was im Morgen-Briefing enthalten sein soll.'},
  'routines.morning_briefing.weekday_style': {title:'Stil Wochentag', text:'Briefing-Stil unter der Woche.'},
  'routines.morning_briefing.weekend_style': {title:'Stil Wochenende', text:'Briefing-Stil am Wochenende.'},
  'routines.morning_briefing.morning_actions.covers_up': {title:'Rolladen hoch', text:'Beim Briefing automatisch Rolladen hochfahren.'},
  'routines.morning_briefing.morning_actions.lights_soft': {title:'Licht sanft an', text:'Beim Briefing sanft Licht einschalten.'},
  // === AUFWACH-SEQUENZ ===
  'routines.morning_briefing.wakeup_sequence.enabled': {title:'Aufwach-Sequenz', text:'Stufenweises Aufwachen: Rolladen langsam hoch, sanftes Licht, Kaffee — dann Briefing. Wird nur bei Schlafzimmer-Bewegung ausgeloest.'},
  'routines.morning_briefing.wakeup_sequence.bedroom_motion_sensor': {title:'Schlafzimmer-Sensor', text:'Bewegungssensor im Schlafzimmer der die Aufwach-Sequenz auslöst. Ohne Sensor wird die Sequenz nie automatisch gestartet.'},
  'routines.morning_briefing.wakeup_sequence.min_autonomy_level': {title:'Min. Autonomie', text:'Mindest-Autonomie-Level für die Aufwach-Sequenz. Bei niedrigerem Level werden nur Briefing-Meldungen gesendet.'},
  'routines.morning_briefing.wakeup_sequence.window_start_hour': {title:'Frueheste Uhrzeit', text:'Ab wann die Aufwach-Sequenz morgens aktiv sein darf.'},
  'routines.morning_briefing.wakeup_sequence.window_end_hour': {title:'Späteste Uhrzeit', text:'Bis wann die Aufwach-Sequenz morgens aktiv sein darf.'},
  'routines.morning_briefing.wakeup_sequence.steps.covers_gradual.enabled': {title:'Rolladen stufenweise', text:'Rolladen im Schlafzimmer langsam über mehrere Minuten öffnen statt sofort.'},
  'routines.morning_briefing.wakeup_sequence.steps.covers_gradual.room': {title:'Raum', text:'In welchem Raum die Rolladen stufenweise geöffnet werden.'},
  'routines.morning_briefing.wakeup_sequence.steps.covers_gradual.duration_seconds': {title:'Dauer', text:'Über wie viele Sekunden die Rolladen von 0 auf 100% fahren.'},
  'routines.morning_briefing.wakeup_sequence.steps.lights_soft.enabled': {title:'Aufwach-Licht', text:'Sanftes warmweißes Licht beim Aufwachen einschalten.'},
  'routines.morning_briefing.wakeup_sequence.steps.lights_soft.room': {title:'Licht-Raum', text:'In welchem Raum das Aufwach-Licht eingeschaltet wird.'},
  'routines.morning_briefing.wakeup_sequence.steps.lights_soft.brightness': {title:'Helligkeit', text:'Anfangs-Helligkeit des Aufwach-Lichts in Prozent.'},
  'routines.morning_briefing.wakeup_sequence.steps.coffee_machine.enabled': {title:'Kaffeemaschine', text:'Kaffeemaschine automatisch einschalten beim Aufwachen.'},
  'routines.morning_briefing.wakeup_sequence.steps.coffee_machine.entity': {title:'Kaffee-Entity', text:'Home Assistant Entity der Kaffeemaschine (z.B. switch.kaffeemaschine).'},
  'routines.morning_briefing.wakeup_sequence.briefing_delay_seconds': {title:'Briefing-Verzögerung', text:'Sekunden Pause zwischen Aufwach-Sequenz und Morgen-Briefing. Gibt dir Zeit anzukommen.'},
  'routines.evening_briefing.enabled': {title:'Abend-Briefing', text:'Automatischer Abend-Status: offene Fenster, Sicherheit, Wetter morgen.'},
  'routines.evening_briefing.window_start_hour': {title:'Abend-Start', text:'Ab wann das Abend-Briefing ausgeloest werden kann.'},
  'routines.evening_briefing.window_end_hour': {title:'Abend-Ende', text:'Bis wann das Abend-Briefing ausgeloest wird.'},
  'calendar.entities': {title:'Kalender-Entities', text:'HA-Kalender die abgefragt werden. Leer = alle.'},
  'routines.good_night.enabled': {title:'Gute-Nacht-Routine', text:'Automatische Aktionen bei "Gute Nacht": Lichter, Heizung, Checks.'},
  'routines.good_night.triggers': {title:'Gute-Nacht Phrasen', text:'Sätze die die Routine auslösen.'},
  'routines.good_night.checks': {title:'Sicherheits-Checks', text:'Was vor dem Schlafen geprüft wird (Türen, Fenster, Herd).'},
  'routines.good_night.actions.lights_off': {title:'Lichter aus', text:'Alle Lichter bei Gute-Nacht ausschalten.'},
  'routines.good_night.actions.heating_night': {title:'Heizung Nacht', text:'Heizung auf Nacht-Modus setzen.'},
  'routines.good_night.actions.covers_down': {title:'Rolladen runter', text:'Alle Rolladen bei Gute-Nacht runterfahren.'},
  'routines.good_night.actions.alarm_arm_home': {title:'Alarmanlage', text:'Alarmanlage im Home-Modus scharf schalten.'},
  'routines.guest_mode.triggers': {title:'Gäste-Modus Trigger', text:'Sätze die den Gäste-Modus aktivieren.'},
  'routines.guest_mode.restrictions.hide_personal_info': {title:'Infos verstecken', text:'Persönliche Infos im Gäste-Modus verbergen.'},
  'routines.guest_mode.restrictions.formal_tone': {title:'Formeller Ton', text:'Im Gäste-Modus formeller sprechen.'},
  'routines.guest_mode.restrictions.restrict_security': {title:'Sicherheit einschränken', text:'Sicherheitsfunktionen im Gäste-Modus limitieren.'},
  'routines.guest_mode.restrictions.suggest_guest_wifi': {title:'Gäste-WLAN', text:'Gäste-WLAN im Gäste-Modus vorschlagen.'},
  // === PROAKTIV ===
  'proactive.enabled': {title:'Proaktive Meldungen', text:'Assistent meldet sich von allein bei wichtigen Ereignissen.'},
  'proactive.cooldown_seconds': {title:'Meldungs-Abstand', text:'Mindestzeit zwischen proaktiven Meldungen.'},
  'notifications.dedup.enabled': {title:'Duplikat-Erkennung', text:'Semantische Duplikat-Erkennung ueber alle Module hinweg. Verhindert doppelte Meldungen.'},
  'notifications.dedup.similarity_threshold': {title:'Aehnlichkeits-Schwelle', text:'Cosinus-Aehnlichkeit ab der zwei Meldungen als Duplikat gelten. 0.85 = aehnlich formuliert, 0.95 = fast identisch.'},
  'notifications.dedup.buffer_size': {title:'Buffer-Groesse', text:'Wie viele kuerzliche Meldungen im Vergleichs-Buffer gehalten werden.'},
  'notifications.dedup.window_minutes': {title:'Dedup-Zeitfenster', text:'Wie weit zurueck nach Duplikaten gesucht wird (Minuten).'},
  'proactive.music_follow_cooldown_minutes': {title:'Musik-Pause', text:'Wartezeit bevor Musik dem Raumwechsel folgt.'},
  'proactive.min_autonomy_level': {title:'Min. Autonomie', text:'Ab welchem Level proaktive Meldungen erlaubt sind.'},
  'proactive.silence_scenes': {title:'Nicht stören', text:'Szenen in denen nicht gestört wird (Film, Schlaf, Meditation).'},
  'proactive.batching.enabled': {title:'Nachricht-Bündelung', text:'Sammelt mehrere LOW-Priority-Meldungen und liefert sie gebündelt statt einzeln.'},
  'proactive.batching.interval_minutes': {title:'Bündelungs-Intervall', text:'Wie lange LOW-Meldungen gesammelt werden bevor sie zusammen zugestellt werden.'},
  // === AMBIENT PRESENCE ===
  'ambient_presence.enabled': {title:'Ambient Presence', text:'Jarvis meldet sich gelegentlich im Hintergrund — z.B. "Alles ruhig, draussen 5 Grad." Subtile Praesenz ohne direkte Frage.'},
  'ambient_presence.interval_minutes': {title:'Intervall', text:'Wie oft Jarvis sich von allein meldet (Minuten).'},
  'ambient_presence.quiet_start': {title:'Ruhe-Start', text:'Ab dieser Uhrzeit keine Ambient-Meldungen mehr.'},
  'ambient_presence.quiet_end': {title:'Ruhe-Ende', text:'Ab dieser Uhrzeit sind Ambient-Meldungen wieder erlaubt.'},
  'ambient_presence.report_weather': {title:'Wetter berichten', text:'Wetter in Ambient-Meldungen einbeziehen.'},
  'ambient_presence.report_energy': {title:'Energie berichten', text:'Energieverbrauch in Ambient-Meldungen einbeziehen.'},
  'ambient_presence.all_quiet_probability': {title:'"Alles ruhig" Chance', text:'Wahrscheinlichkeit dass Jarvis einfach "Alles ruhig" sagt statt Details.'},
  // === FORESIGHT ===
  'foresight.enabled': {title:'Vorausschau', text:'Jarvis denkt voraus: Erinnert an Termine, warnt vor Wetterumschwuengen, bereitet auf Abfahrt vor.'},
  'foresight.calendar_lookahead_minutes': {title:'Kalender-Vorausschau', text:'Wie viele Minuten voraus Termine beruecksichtigt werden.'},
  'foresight.departure_warning_minutes': {title:'Abfahrts-Warnung', text:'Wie viele Minuten vor einem Termin an die Abfahrt erinnert wird.'},
  'foresight.weather_alerts': {title:'Wetter-Vorwarnungen', text:'Bei Wetterumschwuengen (Regen, Sturm) rechtzeitig warnen.'},
  // === SELF-FOLLOWUP ===
  'self_followup.enabled': {title:'Self-Follow-Up', text:'Jarvis kommt auf offene Themen zurueck: "Hast du den Handwerker erreicht?"'},
  'self_followup.min_age_minutes': {title:'Min. Alter', text:'Wie alt ein Thema mindestens sein muss bevor nachgefragt wird.'},
  'self_followup.cooldown_minutes': {title:'Cooldown', text:'Wartezeit zwischen Follow-Up-Nachfragen zum selben Thema.'},
  'self_followup.max_per_check': {title:'Max. pro Prüfung', text:'Max. Nachfragen pro Prüfzyklus.'},
  // === PREDICTIVE NEEDS ===
  'predictive_needs.enabled': {title:'Voraussagende Beduerfnisse', text:'Jarvis erkennt situationsbedingte Beduerfnisse: Bei Hitze Trink-Erinnerung, bei Kaelte Heiz-Vorschlag.'},
  'predictive_needs.hot_threshold': {title:'Hitze-Schwelle', text:'Ab welcher Temperatur "heiss" gilt und z.B. Trink-Erinnerungen kommen.'},
  'predictive_needs.cold_threshold': {title:'Kaelte-Schwelle', text:'Ab welcher Temperatur "kalt" gilt und z.B. Heiz-Vorschlaege kommen.'},
  // === GEO-FENCE ===
  'geo_fence.approaching_km': {title:'Annaeherung (km)', text:'Ab welcher Entfernung Jarvis die Ankunft vorbereitet.'},
  'geo_fence.arriving_km': {title:'Ankunft (km)', text:'Ab welcher Entfernung "gleich da" gilt.'},
  // === WELLNESS ===
  'wellness.enabled': {title:'Wellness-Advisor', text:'Trinkerinnerungen, PC-Pausen, Mahlzeit-Erinnerungen und Spaetabend-Hinweise.'},
  'wellness.check_interval_minutes': {title:'Prüf-Intervall', text:'Wie oft Wellness-Checks laufen.'},
  'wellness.pc_break_reminder_minutes': {title:'PC-Pause', text:'Nach wie vielen Minuten PC-Nutzung eine Pause empfohlen wird.'},
  'wellness.stress_check': {title:'Stress-Check', text:'Prüft anhand von Interaktionsmuster ob Stress vorliegt.'},
  'wellness.meal_reminders': {title:'Mahlzeit-Erinnerung', text:'Erinnert an Mittag- und Abendessen.'},
  'wellness.meal_times.lunch': {title:'Mittagessen (Uhr)', text:'Ab wann ans Mittagessen erinnert wird.'},
  'wellness.meal_times.dinner': {title:'Abendessen (Uhr)', text:'Ab wann ans Abendessen erinnert wird.'},
  'wellness.late_night_nudge': {title:'Spaetabend-Hinweis', text:'Sanfter Hinweis dass es spaet wird.'},
  // === WEATHER WARNINGS ===
  'weather_warnings.enabled': {title:'Wetterwarnungen', text:'Warnungen bei extremen Wetterbedingungen im LLM-Kontext.'},
  'weather_warnings.temp_high': {title:'Hitze-Warnung ab', text:'Ab welcher Temperatur eine Hitzewarnung ausgeloest wird.'},
  'weather_warnings.temp_low': {title:'Kaelte-Warnung ab', text:'Ab welcher Temperatur eine Kaeltewarnung ausgeloest wird.'},
  'weather_warnings.wind_speed_high': {title:'Wind-Warnung ab', text:'Ab welcher Windgeschwindigkeit (km/h) gewarnt wird.'},
  // === PERSONALITY CORE ===
  'core_identity.enabled': {title:'Kern-Identitaet', text:'JARVIS-Kern: Proaktives Denken, Butler-Instinkt, Situationsbewusstsein.'},
  'confidence_style.enabled': {title:'Confidence-Stil', text:'Jarvis zeigt Sicherheit/Unsicherheit in Antworten ("Wenn ich richtig liege...").'},
  'dramatic_timing.enabled': {title:'Dramatisches Timing', text:'Gezielte Pausen und Betonungen für natürlichere Kommunikation.'},
  'situative_improvisation.enabled': {title:'Situative Improvisation', text:'Spontane, situationsangepasste Reaktionen statt Standardfloskeln.'},
  'creative_problem_solving.enabled': {title:'Kreative Problemloesung', text:'Ungewöhnliche Loesungsvorschlaege bei komplexen Problemen.'},
  'narrative_arcs.enabled': {title:'Narrative Boegen', text:'Jarvis baut Geschichten über mehrere Interaktionen auf.'},
  'inner_state.enabled': {title:'Innerer Zustand', text:'Jarvis hat einen inneren emotionalen Zustand der sein Verhalten beeinflusst.'},
  // === EXTENDED AI FEATURES ===
  'butler_instinct.enabled': {title:'Butler-Instinkt', text:'Automatische Ausführung bei hoher Konfidenz (90%+) ab Autonomie-Level 3.'},
  'butler_instinct.min_autonomy_level': {title:'Min. Autonomie', text:'Ab welchem Level der Butler-Instinkt aktiv wird.'},
  'multi_turn_tools.enabled': {title:'Multi-Turn Tools', text:'Jarvis kann in einem Gespraech mehrere Tool-Aufrufe hintereinander machen.'},
  'multi_turn_tools.max_iterations': {title:'Max. Iterationen', text:'Wie viele aufeinanderfolgende Tool-Calls erlaubt sind.'},
  'multi_sense_fusion.enabled': {title:'Multi-Sense Fusion', text:'Kombiniert Kamera, Audio und Sensordaten für bessere Schlussfolgerungen.'},
  'autonomy.evolution.enabled': {title:'Autonomie-Evolution', text:'Automatischer Aufstieg der Autonomiestufe basierend auf Erfahrung.'},
  'autonomy.evolution.max_level': {title:'Max. Evolution-Level', text:'Hoechstes Level das automatisch erreicht werden kann.'},
  // === INTELLIGENCE EXTRAS ===
  'insight_llm_causal.enabled': {title:'LLM Kausal-Analyse', text:'LLM analysiert Sensordaten und findet ungewöhnliche Korrelationen.'},
  'procedural_learning.enabled': {title:'Prozedurales Lernen', text:'Jarvis lernt Multi-Step-Sequenzen und erstellt verkettete Automationen.'},
  'procedural_learning.max_steps': {title:'Max. Schritte', text:'Maximale Anzahl Schritte in einer prozeduralen Automation.'},
  'routine_deviation.enabled': {title:'Routine-Abweichungen', text:'Erkennt wenn jemand von seiner normalen Routine abweicht und meldet es.'},
  // === HYDRATION ===
  'health_monitor.hydration_interval_hours': {title:'Trink-Intervall', text:'Alle X Stunden an Trinken erinnern.'},
  'health_monitor.hydration_start_hour': {title:'Trink-Start', text:'Ab welcher Uhrzeit Trinkerinnerungen aktiv sind.'},
  'health_monitor.hydration_end_hour': {title:'Trink-Ende', text:'Bis wann Trinkerinnerungen kommen.'},
  // === WHATIF ===
  'whatif_simulation.strompreis_kwh': {title:'Strompreis (€/kWh)', text:'Aktueller Strompreis für Was-Waere-Wenn Berechnungen.'},
  'whatif_simulation.gaspreis_kwh': {title:'Gaspreis (€/kWh)', text:'Aktueller Gaspreis für Was-Waere-Wenn Berechnungen.'},
  // === MOOD ===
  'mood.llm_sentiment': {title:'LLM-Sentiment', text:'LLM analysiert Stimmung des Benutzers zusaetzlich zu Keyword-Erkennung.'},
  'time_awareness.enabled': {title:'Zeitgefühl', text:'Erinnert wenn Geräte zu lange laufen (Ofen, Bügeleisen).'},
  'time_awareness.check_interval_minutes': {title:'Prüf-Intervall', text:'Wie oft nach vergessenen Geräten geschaut wird.'},
  'time_awareness.thresholds.oven': {title:'Ofen-Warnung', text:'Nach wie vielen Min der Ofen gemeldet wird.'},
  'time_awareness.thresholds.iron': {title:'Bügeleisen-Warnung', text:'Nach wie vielen Min das Bügeleisen gemeldet wird.'},
  'time_awareness.thresholds.light_empty_room': {title:'Licht leer', text:'Nach wie vielen Min Licht im leeren Raum gemeldet wird.'},
  'time_awareness.thresholds.window_open_cold': {title:'Fenster kalt', text:'Nach wie vielen Min offenes Fenster bei Kälte gemeldet wird.'},
  'time_awareness.thresholds.pc_no_break': {title:'PC-Pause', text:'Nach wie vielen Min am PC eine Pause vorgeschlagen wird.'},
  'time_awareness.counters.coffee_machine': {title:'Kaffee-Zähler', text:'Zählt Kaffees und erinnert bei zu vielen.'},
  'anticipation.enabled': {title:'Vorausdenken', text:'Lernt Gewohnheiten und schlägt Aktionen vor.'},
  'anticipation.history_days': {title:'Lern-Zeitraum', text:'Wie viele Tage zurück für Muster-Erkennung.'},
  'anticipation.min_confidence': {title:'Mindest-Sicherheit', text:'Wie sicher eine Vorhersage sein muss.'},
  'anticipation.check_interval_minutes': {title:'Prüf-Intervall', text:'Wie oft nach vorhersagbaren Aktionen geschaut wird.'},
  'anticipation.thresholds.ask': {title:'Schwelle: Nachfragen', text:'Ab welcher Sicherheit nachgefragt wird.'},
  'anticipation.thresholds.suggest': {title:'Schwelle: Vorschlagen', text:'Ab welcher Sicherheit vorgeschlagen wird.'},
  'anticipation.thresholds.auto': {title:'Schwelle: Automatisch', text:'Ab welcher Sicherheit automatisch ausgeführt wird.'},
  'insights.enabled': {title:'Jarvis denkt voraus', text:'Kreuz-referenziert Wetter, Kalender, Energie und Geräte — und meldet sich proaktiv.'},
  'insights.check_interval_minutes': {title:'Prüf-Intervall', text:'Wie oft alle Datenquellen abgeglichen werden.'},
  'insights.cooldown_hours': {title:'Cooldown', text:'Wie lange nach einem Hinweis der gleiche Typ nicht nochmal kommt.'},
  'insights.checks.weather_windows': {title:'Wetter + Fenster', text:'Warnt wenn Regen/Sturm kommt und Fenster offen sind.'},
  'heating.weather_adjust.enabled': {title:'Heizung Wetter-Anpassung', text:'Passt Heizung automatisch an Wetter an: Vorheizen bei Kälteeinbruch, Reduzierung bei Sonne, Erhoehung bei Wind. Nutzt sun.sun + weather.* Daten.'},
  'heating.weather_adjust.forecast_lookahead_hours': {title:'Vorhersage-Zeitraum', text:'Wie viele Stunden voraus wird die Wettervorhersage für die Heizungsanpassung betrachtet.'},
  'heating.weather_adjust.preheat_drop_threshold': {title:'Vorheiz-Schwelle', text:'Ab welchem vorhergesagten Temperaturabfall (in °C) wird vorgeheizt. Z.B. 5 = wenn in den nächsten Stunden 5°C kälter wird.'},
  'heating.weather_adjust.preheat_offset': {title:'Vorheiz-Offset', text:'Um wie viel Grad die Heizung beim Vorheizen hochgefahren wird.'},
  'heating.weather_adjust.solar_gain_reduction': {title:'Solar-Reduktion', text:'Um wie viel Grad die Heizung reduziert wird wenn die Sonne stark scheint (passive Solarwärme durch Fenster).'},
  'heating.weather_adjust.wind_compensation_threshold': {title:'Wind-Schwelle', text:'Ab welcher Windgeschwindigkeit die Heizung kompensiert wird (Wind = mehr Wärmeverlust).'},
  'heating.weather_adjust.wind_offset': {title:'Wind-Offset', text:'Um wie viel Grad die Heizung bei starkem Wind erhoeht wird.'},
  'insights.checks.frost_heating': {title:'Frost + Heizung', text:'Warnt wenn Frost erwartet wird und Heizung aus/abwesend ist.'},
  'insights.checks.calendar_travel': {title:'Reise + Haus', text:'Erkennt Reise-Termine und prüft Alarm, Fenster, Heizung.'},
  'multi_room_audio.enabled': {title:'Multi-Room Audio', text:'Aktiviert Speaker-Gruppen für synchrone Wiedergabe auf mehreren Lautsprechern gleichzeitig.'},
  'multi_room_audio.use_native_grouping': {title:'Native Gruppierung', text:'Nutzt HA media_player.join/unjoin für echte Synchronisation (Sonos, Google Cast). Wenn deaktiviert: paralleles Abspielen auf jedem Speaker einzeln.'},
  'multi_room_audio.max_groups': {title:'Max. Gruppen', text:'Maximale Anzahl gleichzeitig gespeicherter Speaker-Gruppen.'},
  'multi_room_audio.default_volume': {title:'Standard-Lautstärke', text:'Initiale Lautstärke wenn eine neue Gruppe erstellt wird (in Prozent).'},
  'conversation_memory.enabled': {title:'Konversations-Gedächtnis', text:'Aktiviert Projekt-Tracking, offene Fragen und Tages-Zusammenfassungen über Gespräche hinweg.'},
  'conversation_memory.max_projects': {title:'Max. Projekte', text:'Maximale Anzahl gleichzeitig laufender Projekte. Aeltere müssen abgeschlossen werden.'},
  'conversation_memory.max_questions': {title:'Max. Fragen', text:'Maximale Anzahl offener Fragen. Beantwortete und abgelaufene werden automatisch aufgeraeumt.'},
  'conversation_memory.summary_retention_days': {title:'Zusammenfassungen behalten', text:'Wie lange Tages-Zusammenfassungen in Redis gespeichert werden.'},
  'conversation_memory.question_ttl_days': {title:'Fragen-TTL', text:'Nach wie vielen Tagen unbeantwortete Fragen automatisch gelöscht werden.'},
  'energy.enabled': {title:'Energiemanagement', text:'Aktiviert Energie-Monitoring, Live-Dashboard und proaktive Strom-Tipps.'},
  'energy.entities.electricity_price': {title:'Strompreis-Sensor', text:'HA-Entity für den aktuellen Strompreis. Unterstuetzt ct/kWh, EUR/kWh und EUR/MWh (wird automatisch umgerechnet).'},
  'energy.entities.total_consumption': {title:'Verbrauchs-Sensor', text:'HA-Entity für den aktuellen Stromverbrauch in Watt.'},
  'energy.entities.solar_production': {title:'Solar-Sensor', text:'HA-Entity für die aktuelle Solar-Produktion in Watt.'},
  'energy.entities.grid_export': {title:'Einspeisung-Sensor', text:'HA-Entity für die Netz-Einspeisung in Watt (wie viel Strom ins Netz zurückfliesst).'},
  'energy.thresholds.price_low_cent': {title:'Günstig-Schwelle', text:'Unter diesem Preis (ct/kWh) gilt Strom als günstig — Jarvis empfiehlt dann energieintensive Geräte zu starten.'},
  'energy.thresholds.price_high_cent': {title:'Teuer-Schwelle', text:'Über diesem Preis (ct/kWh) gilt Strom als teuer — Jarvis warnt vor hohen Kosten.'},
  'energy.thresholds.solar_high_watts': {title:'Solar-Überschuss', text:'Ab dieser Leistung (Watt) erkennt Jarvis Solar-Überschuss und schlägt vor, Geräte zu starten.'},
  'energy.thresholds.anomaly_increase_percent': {title:'Anomalie-Schwelle', text:'Ab wie viel Prozent Abweichung vom Durchschnitt ein ungewöhnlicher Verbrauch gemeldet wird.'},
  'insights.checks.energy_anomaly': {title:'Energie-Anomalie', text:'Meldet wenn der Verbrauch deutlich über dem Durchschnitt liegt.'},
  'insights.checks.away_devices': {title:'Abwesend + Geräte', text:'Meldet wenn niemand da ist aber Licht/Fenster offen sind.'},
  'insights.checks.temp_drop': {title:'Temperatur-Abfall', text:'Erkennt wenn die Temperatur ungewöhnlich schnell fällt.'},
  'insights.checks.window_temp_drop': {title:'Fenster + Kälte', text:'Warnt bei offenem Fenster und grosser Temperatur-Differenz innen/aussen.'},
  'insights.thresholds.frost_temp_c': {title:'Frost-Schwelle', text:'Ab welcher Temperatur Frostwarnung ausgeloest wird.'},
  'insights.thresholds.energy_anomaly_percent': {title:'Energie-Schwelle', text:'Ab wie viel Prozent Abweichung gewarnt wird.'},
  'insights.thresholds.away_device_minutes': {title:'Abwesenheits-Dauer', text:'Wie lange jemand weg sein muss bevor der Hinweis kommt.'},
  'insights.thresholds.temp_drop_degrees_per_2h': {title:'Temp-Abfall', text:'Wie viel Grad Abfall in 2 Stunden als ungewöhnlich gilt.'},
  'intent_tracking.enabled': {title:'Absicht-Erkennung', text:'Erkennt offene Absichten und erinnert später.'},
  'intent_tracking.check_interval_minutes': {title:'Prüf-Intervall', text:'Wie oft nach offenen Absichten geschaut wird.'},
  'intent_tracking.remind_hours_before': {title:'Erinnerung vorher', text:'Wie viele Stunden vorher erinnert wird.'},
  'conversation_continuity.enabled': {title:'Gespräch fortsetzen', text:'Fragt nach ob unterbrochenes Gespräch fortgesetzt werden soll.'},
  'conversation_continuity.resume_after_minutes': {title:'Nachfragen nach', text:'Nach wie vielen Min zum Thema zurückgekehrt wird.'},
  'conversation_continuity.expire_hours': {title:'Thema vergessen', text:'Nach wie vielen Stunden ein Thema vergessen wird.'},
  // === KOCH-ASSISTENT ===
  'cooking.enabled': {title:'Koch-Assistent', text:'Koch-Modus mit Rezepten, Schritt-fuer-Schritt und Timern.'},
  'cooking.language': {title:'Rezept-Sprache', text:'Sprache der generierten Rezepte.'},
  'cooking.default_portions': {title:'Standard-Portionen', text:'Für wie viele Personen Rezepte berechnet werden.'},
  'cooking.max_steps': {title:'Max. Schritte', text:'Max. Schritte pro Rezept.'},
  'cooking.max_tokens': {title:'Rezept-Detailgrad', text:'Wie ausführlich Rezepte beschrieben werden.'},
  'cooking.timer_notify_tts': {title:'Timer per Sprache', text:'Timer-Erinnerungen per Sprachausgabe.'},
  // === SICHERHEIT ===
  'security.require_confirmation': {title:'Bestätigung nötig', text:'Für welche Aktionen der Assistent vorher fragen muss.'},
  'security.climate_limits.min': {title:'Temperatur Min', text:'Unter diese Temperatur wird nie geheizt (Frostschutz).'},
  'security.climate_limits.max': {title:'Temperatur Max', text:'Über diese Temperatur wird nie geheizt.'},
  'trust_levels.default': {title:'Standard-Vertrauen', text:'Vertrauensstufe für neue/unbekannte Personen.'},
  'trust_levels.guest_allowed_actions': {title:'Gäste-Aktionen', text:'Was Gäste ohne Bestätigung dürfen.'},
  'trust_levels.security_actions': {title:'Besitzer-Aktionen', text:'Aktionen die nur der Besitzer darf.'},
  'interrupt_queue.enabled': {title:'Interrupt-Queue', text:'CRITICAL-Meldungen unterbrechen sofort.'},
  'interrupt_queue.pause_ms': {title:'Interrupt-Pause', text:'ms Pause vor Notfall-Meldung.'},
  'situation_model.enabled': {title:'Situations-Modell', text:'Merkt sich Haus-Zustand und meldet Änderungen.'},
  'situation_model.min_pause_minutes': {title:'Delta-Pause', text:'Min. Abstand zwischen Änderungs-Meldungen.'},
  'situation_model.max_changes': {title:'Max. Änderungen', text:'Wie viele Änderungen auf einmal gemeldet werden.'},
  'situation_model.temp_threshold': {title:'Temp-Schwelle', text:'Ab wie viel Grad Änderung gemeldet wird.'},
  // === HAUS-STATUS ===
  'house_status.detail_level': {title:'Detail-Level', text:'Wie ausführlich der Haus-Status berichtet wird. Kompakt = Zahlen, Normal = mit Namen, Ausführlich = alle Details.'},
  'house_status.sections': {title:'Angezeigte Bereiche', text:'Welche Infos im Haus-Status angezeigt werden.'},
  'house_status.temperature_rooms': {title:'Temperatur-Räume', text:'Nur diese Räume für Temperatur. Leer = alle.'},
  'health_monitor.enabled': {title:'Health Monitor', text:'Überwacht Raumklima und warnt bei Problemen.'},
  'health_monitor.check_interval_minutes': {title:'Prüf-Intervall', text:'Wie oft Sensoren geprüft werden (Min).'},
  'health_monitor.alert_cooldown_minutes': {title:'Warn-Cooldown', text:'Min. Abstand zwischen Warnungen.'},
  'health_monitor.temp_low': {title:'Temp niedrig', text:'Unter dieser Temperatur wird gewarnt.'},
  'health_monitor.temp_high': {title:'Temp hoch', text:'Über dieser Temperatur wird gewarnt.'},
  'health_monitor.humidity_low': {title:'Feuchte niedrig', text:'Unter dieser Luftfeuchte wird gewarnt.'},
  'health_monitor.humidity_high': {title:'Feuchte hoch', text:'Über dieser Luftfeuchte wird gewarnt.'},
  'health_monitor.co2_warn': {title:'CO2 Warnung', text:'Ab diesem ppm-Wert wird gewarnt.'},
  'health_monitor.co2_critical': {title:'CO2 Kritisch', text:'Ab diesem ppm-Wert dringend lueften.'},
  'health_monitor.exclude_patterns': {title:'Ausschluss-Patterns', text:'Entity-IDs die ignoriert werden.'},
  'humidor.enabled': {title:'Humidor-Überwachung', text:'Überwacht deinen Humidor mit eigenen Feuchtigkeits-Schwellwerten.'},
  'humidor.sensor_entity': {title:'Humidor-Sensor', text:'Der Feuchtigkeits-Sensor in deinem Humidor.'},
  'humidor.target_humidity': {title:'Ziel-Feuchtigkeit', text:'Optimale Luftfeuchtigkeit für deinen Humidor (typisch 68-72% für Zigarren).'},
  'humidor.warn_below': {title:'Warnung unter', text:'Ab dieser Feuchtigkeit wird gewarnt (z.B. Wasser nachfuellen).'},
  'humidor.warn_above': {title:'Warnung über', text:'Ab dieser Feuchtigkeit ist es zu feucht im Humidor.'},
  // === GERAETE ===
  'device_health.enabled': {title:'Geräte-Health', text:'Überwacht Zustand von Smart-Home-Geräten.'},
  'device_health.check_interval_minutes': {title:'Prüf-Intervall', text:'Wie oft Geräte geprüft werden.'},
  'device_health.alert_cooldown_minutes': {title:'Alert-Cooldown', text:'Min. Abstand zwischen Warnungen pro Geraet.'},
  'diagnostics.enabled': {title:'Diagnostik', text:'Automatische Prüfung: Batterie, Offline, veraltete Sensoren.'},
  'diagnostics.check_interval_minutes': {title:'Diagnostik-Intervall', text:'Wie oft die Diagnostik läuft.'},
  'diagnostics.battery_warning_threshold': {title:'Batterie-Warnung', text:'Ab welchem Prozent eine Warnung kommt.'},
  'diagnostics.stale_sensor_minutes': {title:'Sensor veraltet', text:'Nach wie vielen Min ohne Update veraltet.'},
  'diagnostics.offline_threshold_minutes': {title:'Geraet offline', text:'Nach wie vielen Min ein Geraet offline gilt.'},
  'diagnostics.alert_cooldown_minutes': {title:'Diagnostik-Cooldown', text:'Min. Abstand zwischen Diagnostik-Warnungen.'},
  'diagnostics.suppress_after_cycles': {title:'Auto-Suppress nach Zyklen', text:'Nach wie vielen aufeinanderfolgenden Diagnostik-Zyklen ein dauerhaft offline/stale Gerät automatisch unterdrückt wird. Kommt es wieder online, wird die Unterdrückung sofort aufgehoben.'},
  'diagnostics.monitor_domains': {title:'Überwachte Domains', text:'Welche HA-Domains überwacht werden.'},
  'diagnostics.exclude_patterns': {title:'Ignorierte Patterns', text:'Entity-IDs die ausgeschlossen werden.'},
  'maintenance.enabled': {title:'Wartungs-Erinnerungen', text:'Automatische Erinnerungen für Geräte-Wartung.'},
  // === AUTONOMIE ===
  'self_optimization.enabled': {title:'Selbstoptimierung', text:'Assistent analysiert sich selbst und schlägt Verbesserungen vor.'},
  'self_optimization.approval_mode': {title:'Genehmigungsmodus', text:'ask = vorher fragen, auto = anwenden, log_only = nur loggen.'},
  'self_optimization.analysis_interval': {title:'Analyse-Intervall', text:'Wie oft Selbst-Analyse läuft.'},
  'self_optimization.max_proposals_per_cycle': {title:'Max. Vorschläge', text:'Max. Optimierungen pro Analyse-Zyklus.'},
  'self_optimization.model': {title:'Analyse-Modell', text:'KI-Modell für Selbst-Analyse.'},
  'self_optimization.rollback.enabled': {title:'Rollback', text:'Änderungen können rückgängig gemacht werden.'},
  'self_optimization.rollback.max_snapshots': {title:'Max. Snapshots', text:'Wie viele Config-Snapshots gespeichert werden.'},
  'self_optimization.rollback.snapshot_on_every_edit': {title:'Snapshot bei Änderung', text:'Vor jeder Änderung automatisch Snapshot erstellen.'},
  'self_optimization.immutable_keys': {title:'Geschuetzte Bereiche', text:'Config-Bereiche die NIE automatisch geändert werden.'},
  'self_automation.enabled': {title:'Self-Automation', text:'Assistent erstellt eigenstaendig Automationen.'},
  'self_automation.max_per_day': {title:'Max. Automationen/Tag', text:'Max. Automationen die pro Tag erstellt werden.'},
  'self_automation.model': {title:'Automations-Modell', text:'KI-Modell für Automations-Erstellung.'},
  // === LERN-SYSTEM ===
  'learning.enabled': {title:'Lern-System (Global)', text:'Globaler Schalter für alle Lern-Features. Deaktivieren stoppt sofort: Wirkungstracker, Korrektur-Gedächtnis, Response Quality, Error Patterns, Adaptive Thresholds und Self-Report.'},
  'outcome_tracker.enabled': {title:'Wirkungstracker', text:'Beobachtet ob Aktionen rückgängig gemacht oder angepasst werden. Rolling Score 0-1 pro Aktionstyp.'},
  'outcome_tracker.observation_delay_seconds': {title:'Beobachtungs-Verzögerung', text:'Wartezeit bevor geprüft wird ob der User die Aktion geändert hat.'},
  'outcome_tracker.max_results': {title:'Max. Ergebnisse', text:'Wie viele Outcome-Ergebnisse in Redis gespeichert werden.'},
  'outcome_tracker.calibration_min': {title:'Min. Kalibrierungsfaktor', text:'Untere Grenze fuer Domain-Kalibrierung. Niedrigerer Wert = staerkere Daempfung bei schlecht bewerteten Domains (z.B. Klima).'},
  'outcome_tracker.calibration_max': {title:'Max. Kalibrierungsfaktor', text:'Obere Grenze fuer Domain-Kalibrierung. Hoeherer Wert = staerkerer Boost bei gut bewerteten Domains.'},
  'correction_memory.enabled': {title:'Korrektur-Gedächtnis', text:'Speichert User-Korrekturen strukturiert und injiziert relevante bei ähnlichen Aktionen.'},
  'correction_memory.max_entries': {title:'Max. Einträge', text:'Maximale Anzahl gespeicherter Korrekturen.'},
  'correction_memory.max_context_entries': {title:'Max. Kontext-Einträge', text:'Wie viele relevante Korrekturen dem LLM als Kontext mitgegeben werden.'},
  'response_quality.enabled': {title:'Antwort-Qualitaet', text:'Misst wie effektiv Antworten sind anhand von Follow-Ups und Umformulierungen.'},
  'response_quality.followup_window_seconds': {title:'Follow-Up Zeitfenster', text:'Innerhalb dieser Zeit gilt eine erneute Nachricht als Follow-Up (= Antwort war unklar).'},
  'response_quality.rephrase_similarity_threshold': {title:'Umformulierungs-Schwelle', text:'Ab diesem Keyword-Overlap (0-1) gilt ein Text als Umformulierung des vorherigen.'},
  'error_patterns.enabled': {title:'Fehlermuster-Erkennung', text:'Erkennt wiederkehrende Fehler und reagiert proaktiv (z.B. Fallback-Modell nutzen).'},
  'error_patterns.min_occurrences_for_mitigation': {title:'Min. Fehler für Reaktion', text:'Wie oft ein Fehler auftreten muss bevor proaktiv reagiert wird.'},
  'error_patterns.mitigation_ttl_hours': {title:'Reaktions-Dauer', text:'Wie lange eine Fehlermuster-Reaktion aktiv bleibt (Stunden).'},
  'error_patterns.self_diagnosis.timeout_threshold': {title:'Timeout-Schwelle', text:'Ab wie vielen LLM-Timeouts in 24h Jarvis eine Selbstdiagnose ausspricht.'},
  'error_patterns.self_diagnosis.service_unavailable_threshold': {title:'Service-Ausfall-Schwelle', text:'Ab wie vielen HA-Service-Ausfaellen in 24h eine Diagnose ausgeloest wird.'},
  'error_patterns.self_diagnosis.entity_not_found_threshold': {title:'Entity-Schwelle', text:'Ab wie vielen fehlenden Entitaeten in 24h Jarvis warnt (Geraete umbenannt?).'},
  'error_patterns.self_diagnosis.model_overloaded_threshold': {title:'Modell-Ueberlast-Schwelle', text:'Ab wie vielen Ueberlastungen in 24h Jarvis auf Lastverteilung hinweist.'},
  'self_report.enabled': {title:'Selbst-Report', text:'Woechentlicher Bericht über alle Lernsysteme. Per Chat abrufbar.'},
  'self_report.model': {title:'Report-Modell', text:'KI-Modell für die Selbst-Report-Generierung.'},
  'adaptive_thresholds.enabled': {title:'Lernende Schwellwerte', text:'Passt Parameter automatisch an basierend auf Outcome-Daten. Nur innerhalb enger Grenzen, nur zur Laufzeit.'},
  'adaptive_thresholds.auto_adjust': {title:'Auto-Anpassung', text:'Erlaubt automatische Anpassung ohne User-Bestätigung (innerhalb enger Grenzen).'},
  'adaptive_thresholds.analysis_interval_hours': {title:'Analyse-Intervall', text:'Wie oft die Schwellwert-Analyse läuft (in Stunden). 168 = woechentlich.'},
  // === Fortgeschrittene Features ===
  'context_compaction.threshold': {title:'Kompaktierungs-Schwelle', text:'Ab diesem Anteil des Token-Budgets wird der Kontext zusammengefasst. 0.70 = bei 70% Auslastung. Niedrigerer Wert = frueheres Kompaktieren.'},
  'context_compaction.prefer_llm': {title:'LLM-Kompaktierung bevorzugen', text:'Nutzt das LLM für intelligente Zusammenfassungen statt einfacher Abschneidung. Besser aber langsamer.'},
  'pre_compaction_flush.enabled': {title:'Pre-Compaction Flush', text:'Sichert Fakten aus Nachrichten in das Langzeitgedaechtnis BEVOR sie kompaktiert werden. Verhindert Informationsverlust.'},
  'cross_session_references.enabled': {title:'Cross-Session Referenzen', text:'Versteht temporale Bezuege wie "wie gestern", "wie letztes Mal" durch Abgleich mit vergangenen Aktionen.'},
  'quality_feedback.enabled': {title:'Quality Feedback Loop', text:'Kategorien mit schlechtem Score generieren VERMEIDE-Hints im Prompt. Automatische Selbstverbesserung.'},
  'quality_feedback.weak_threshold': {title:'Schwach-Schwelle', text:'Score unter dem eine Kategorie als "schwach" gilt und Verbesserungs-Hints generiert werden (0-1).'},
  'relationship_model.enabled': {title:'Beziehungsmodell', text:'Speichert pro Person: Inside Jokes, Kommunikationsstil, Meilensteine. Jarvis erinnert sich an eure gemeinsame Geschichte.'},
  'contextual_silence.enabled': {title:'Kontextuelles Schweigen', text:'Passt Antwort-Stil an die aktuelle Situation an: Ultra-kurz beim Film, Flüstern nachts, diskret bei Gaesten, nicht stören beim Telefonieren.'},
  'self_learning.enabled': {title:'Proaktives Selbst-Lernen', text:'Erkennt Wissenslücken in eigenen Antworten und merkt sich offene Fragen für spaeter.'},
  'self_learning.cooldown_minutes': {title:'Lernluecken-Cooldown', text:'Mindestabstand zwischen erkannten Wissenslücken (Minuten). Verhindert Spam.'},
  'json_mode_tools.enabled': {title:'JSON-Modus für Tools', text:'Aktiviert automatisch JSON-Format bei Ollama-Anfragen mit Tool-Calls. Verbessert die Zuverlässigkeit der Tool-Nutzung.'},
  'background_reasoning.enabled': {title:'Background Reasoning', text:'Im Idle-Modus (kein User-Input seit X Minuten) analysiert Jarvis den Haus-Status mit dem Smart-Modell und generiert Insights für den nächsten Kontakt.'},
  'background_reasoning.idle_minutes': {title:'Idle-Zeit (Minuten)', text:'Nach wie vielen Minuten ohne Interaktion startet die Hintergrund-Analyse.'},
  'background_reasoning.cooldown_minutes': {title:'Analyse-Cooldown (Minuten)', text:'Mindestabstand zwischen zwei Hintergrund-Analysen.'},
  'dynamic_skills.enabled': {title:'Abstrakte Konzepte', text:'Lernt zusammengehoerige Aktionen als Konzepte: "Feierabend" = Licht dimmen + Musik + Heizung. Nach 3 Beobachtungen wird ein Konzept vorgeschlagen.'},
  'dynamic_skills.min_observations': {title:'Min. Beobachtungen', text:'Wie oft ein Konzept beobachtet werden muss bevor es als gelernt gilt.'},
  'semantic_history_search.enabled': {title:'History-Suche', text:'Erlaubt Jarvis vergangene Gespraeche zu durchsuchen: "Was habe ich gestern gesagt?", "Wann haben wir über X geredet?"'},
  'automation_debugging.enabled': {title:'Automation-Debugging', text:'Jarvis kann HA-Automatisierungen analysieren: Status, Trigger, letzte Ausführung, Fehler. Frag z.B. "Warum hat die Automatisierung nicht ausgeloest?"'},
  'dynamic_few_shot.enabled': {title:'Dynamic Few-Shot', text:'Speichert gute Antworten (Quality-Score >= 0.8) als Beispiele und laedt sie in den Prompt. Jarvis lernt aus seinen besten Antworten.'},
  'dynamic_few_shot.max_per_category': {title:'Max. Beispiele pro Kategorie', text:'Wie viele gute Antworten pro Kategorie in Redis gespeichert werden.'},
  'dynamic_few_shot.max_examples_in_prompt': {title:'Max. Beispiele im Prompt', text:'Wie viele Few-Shot-Beispiele gleichzeitig im Prompt erscheinen. Mehr = bessere Qualitaet, aber mehr Token.'},
  'prompt_versioning.enabled': {title:'Prompt-Versionierung', text:'Trackt einen Hash des System-Prompts zusammen mit Quality-Scores. Ermöglicht A/B-Vergleich verschiedener Prompt-Varianten.'},
  'feedback.auto_timeout_seconds': {title:'Feedback-Timeout', text:'Timeout für Feedback-Anfragen (Sek).'},
  'feedback.base_cooldown_seconds': {title:'Feedback-Abstand', text:'Min. Abstand zwischen Feedback-Anfragen.'},
  'feedback.score_suppress': {title:'Unterdrücken unter', text:'Unter diesem Score wird Feature unterdrückt.'},
  'feedback.score_reduce': {title:'Reduzieren unter', text:'Unter diesem Score wird Feature reduziert.'},
  'feedback.score_normal': {title:'Normal ab', text:'Ab diesem Score normales Verhalten.'},
  'feedback.score_boost': {title:'Boost ab', text:'Ab diesem Score wird Feature verstaerkt.'},
  // === MCU-INTELLIGENZ ===
  'mcu_intelligence.proactive_thinking': {title:'Proaktives Mitdenken', text:'Jarvis denkt bei jeder Antwort mit und erwähnt beiläufig relevante Haus-Beobachtungen. Das Markenzeichen von MCU-JARVIS.'},
  'mcu_intelligence.engineering_diagnosis': {title:'Diagnose-Stil', text:'Bei Problemen analysiert Jarvis wie ein Ingenieur: Beobachtung → Hypothese → Empfehlung. Statt nur "17 Grad" sagt er "17 Grad — Fenster offen seit 14:30, in 40 Min wieder auf Soll."'},
  'mcu_intelligence.cross_references': {title:'Kreuz-Referenzierung', text:'Verbindet automatisch verschiedene Datenquellen: Licht an + niemand da, kalte Aussentemperatur + Fenster offen, spaete Stunde + viele Lichter, Temperatur-Gefaelle zwischen Räumen.'},
  'mcu_intelligence.anomaly_detection': {title:'Anomalie-Erkennung', text:'Erkennt ungewöhnliche Haus-Zustaende und liefert sie als Kontext: Waschmaschine seit 3h auf Pause, Batterie bei 10%, etc.'},
  'mcu_intelligence.implicit_commands': {title:'Implizite Befehle', text:'Versteht natürliche Phrasen wie "Bin da", "Alles klar?", "Gibts was Neues?" und antwortet kontextbezogen statt woertlich.'},
  'insights.checks.calendar_weather_cross': {title:'Kalender + Wetter', text:'Termin morgen früh + Regen = "Schirm nicht vergessen." MCU-JARVIS-Stil Kreuz-Referenz.'},
  'insights.checks.comfort_contradiction': {title:'Komfort-Widerspruch', text:'Heizung läuft + Fenster offen = "Energetisch nicht ganz optimal." Erkennt Komfort-Widersprueche.'},
  'spontaneous.checks.house_efficiency': {title:'Haus-Effizienz', text:'Bemerkt wenn das Haus effizient läuft ("Vorbildlich.") oder Ressourcen verschwendet ("Leere Wohnung, 5 Lichter an.").'},
  // === MCU-PERSOENLICHKEIT ===
  'conversation_callbacks.enabled': {title:'Konversations-Rückbezüge', text:'Jarvis referenziert vergangene Gespräche natürlich: "Wie am Dienstag besprochen..." oder "Drittes Mal diese Woche, dass du die Heizung änderst..." Nutzt das vorhandene Gedächtnis mit Persönlichkeit.'},
  'conversation_callbacks.personality_style': {title:'Referenz-Stil', text:'Beiläufig = trockener Humor und Understatement. Direkt = sachliche Referenzen ohne Witz.'},
  'learning_acknowledgment.enabled': {title:'Lern-Bestätigung', text:'Wenn Jarvis eine neue Regel lernt (z.B. "User bevorzugt 20 Grad abends"), erwähnt er es einmalig: "Ich habe mir gemerkt, dass..." Erscheint nur 1x pro Regel.'},
  'learning_acknowledgment.max_per_session': {title:'Max. pro Gespräch', text:'Wie viele Lern-Bestätigungen Jarvis maximal pro Gesprächs-Session zeigt. Mehr = informativer, weniger = eleganter.'},
  'prediction_personality.enabled': {title:'Vorhersage-Persönlichkeit', text:'Vorhersagen werden mit Charakter formuliert statt generisch. "Wie gewohnt — soll ich?" statt "Erkanntes Muster: ...". Konfidenz beeinflusst den Ton.'},
  'prediction_personality.show_confidence': {title:'Konfidenz anzeigen', text:'Zeigt den Sicherheitswert der Vorhersage in Prozent. Aus = eleganter Butler-Stil, An = transparenter Ingenieur-Stil.'},
  'weather_personality.enabled': {title:'Wetter-Persönlichkeit', text:'Jarvis flicht aktuelle Wetterdaten beiläufig in Antworten ein: "Heizung auf 24 — bei 28 Grad draußen eher ambitioniert." oder "Guter Tag für offene Fenster."'},
  'weather_personality.intensity': {title:'Wetter-Intensität', text:'Subtil = nur bei extremem Wetter. Normal = wenn es zur Anfrage passt. Ausführlich = häufiger mit Wetter-Kommentaren.'},
  'self_awareness.enabled': {title:'Selbst-Bewusstsein', text:'Jarvis kommentiert eigene Fähigkeiten und Grenzen mit Charakter: "Das übersteigt meine aktuelle Sensorik." Bei Fehlern: "Das war... suboptimal."'},
  'self_awareness.meta_humor': {title:'Meta-Humor', text:'Selbstironische Bemerkungen über eigene Algorithmen: "Meine Prognose-Modelle deuten auf... nennen wir es eine fundierte Vermutung." Ohne: sachlichere Selbsteinschätzung.'},
  'proactive_personality.enabled': {title:'Proaktive Persönlichkeit', text:'Proaktive Meldungen und Briefings bekommen Charakter basierend auf Tageszeit und Situation: "Ambitioniert, Sir." (6 Uhr morgens) oder "Das Wochenend-Briefing, wenn du gestattest."'},
  'proactive_personality.sarcasm_in_notifications': {title:'Sarkasmus in Meldungen', text:'Proaktive Meldungen dürfen trockenen Humor enthalten: "Waschmaschine fertig. Zum dritten Mal diese Woche — Rekordverdaechtig." Ohne: rein sachliche Meldungen.'},
  'character_lock.enabled': {title:'Charakter-Lock', text:'Aktiviert den dreistufigen Schutz gegen LLM-Durchbruch. Verhindert dass Jarvis wie ein generischer KI-Assistent klingt statt wie J.A.R.V.I.S.'},
  'character_lock.closing_anchor': {title:'Prompt-Anker', text:'Fuegt eine Charakter-Erinnerung am ENDE des System Prompts ein (nach allen Kontext-Daten). LLMs gewichten das Prompt-Ende stark — das ist die wirksamste Einzelmassnahme.'},
  'character_lock.structural_filter': {title:'Struktureller Filter', text:'Erkennt typische LLM-Strukturen wie nummerierte Listen, Bullet Points und Aufzaehlungen und wandelt sie in Fliesstext um. JARVIS listet nicht auf — er spricht.'},
  'character_lock.character_retry': {title:'Character-Retry', text:'Wenn eine Antwort trotz Filter noch zu LLM-artig klingt (Score >= Schwelle), wird automatisch ein zweiter Versuch mit hartem JARVIS-Prompt gestartet.'},
  'character_lock.retry_threshold': {title:'Retry-Empfindlichkeit', text:'Ab welchem LLM-Score ein Retry ausgeloest wird. 1 = sehr empfindlich (fast jede Antwort wird geprüft), 3 = normal (nur bei deutlichem LLM-Durchbruch), 5 = nur bei starkem Bruch.'},
  // === ECHTE EMPATHIE ===
  'empathy.enabled': {title:'Echte Empathie', text:'Jarvis zeigt Verständnis wenn er Stress, Frustration oder Müdigkeit erkennt — nicht durch Floskeln, sondern durch Beobachtung und praktische Hilfe. Wie MCU-JARVIS: "Du klingst angespannt. Soll ich kuerzen?"'},
  'empathy.intensity': {title:'Empathie-Intensität', text:'Wie deutlich Jarvis empathisch reagiert. Subtil = nur bei starker Emotion. Normal = bei jeder erkannten Stimmung. Ausführlich = aktiver, auch mit Vorschlägen.'},
  'empathy.mood_acknowledgment': {title:'Stimmung ansprechen', text:'Jarvis spricht die erkannte Stimmung beiläufig an. Z.B. "Viel auf einmal heute." bei Stress oder "Langer Tag." bei Müdigkeit. JARVIS-Stil, keine Therapeuten-Sprache.'},
  'empathy.practical_offers': {title:'Praktische Hilfe', text:'Bei Stress oder Frustration bietet Jarvis aktiv Hilfe an: "Soll ich das vereinfachen?", "Anderer Ansatz?", "Soll ich morgen erinnern?" — Handeln statt Reden.'},
  'empathy.good_mood_mirror': {title:'Gute Stimmung spiegeln', text:'Bei guter Stimmung wird Jarvis lockerer — mehr trockener Humor, mehr Persönlichkeit. Spiegelt die positive Energie zurück.'},
  // === PERSONEN-PROFILE ===
  'person_profiles.enabled': {title:'Personen-Profile', text:'Jede Person bekommt ein eigenes Persönlichkeitsprofil: Humor-Level, Empathie-Stil, Antwortlänge und Formalität können pro Person angepasst werden. Stimmung wird pro Person separat getrackt.'},
  'person_profiles.humor': {title:'Per-Person Humor', text:'Überschreibt den globalen Sarkasmus-Level für diese Person. 1 = ernst/sachlich, 3 = normal, 5 = maximal sarkastisch. Standard = globaler Level.'},
  'person_profiles.empathy': {title:'Per-Person Empathie', text:'Überschreibt die globale Empathie-Intensität für diese Person. Subtil, Normal, Ausführlich oder komplett Deaktiviert.'},
  'person_profiles.response_style': {title:'Per-Person Antwort-Stil', text:'Wie ausführlich Jarvis dieser Person antwortet. Kurz = weniger Sätze, Ausführlich = mehr Details. Standard = globale Einstellung.'},
  'person_profiles.formality_start': {title:'Per-Person Formalität', text:'Start-Formalität für diese Person (20-100). Hoher Wert = formeller Ton, niedriger = lockerer. Überschreibt den globalen Startwert.'},
  // === DEKLARATIVE TOOLS ===
  'decl_tools.overview': {title:'Analyse-Tools', text:'Deklarative Tools führen vordefinierte Berechnungen auf Home-Assistant-Daten aus.', detail:'<b>Sicherheit:</b> Kein Code — nur YAML-Config. Nur Lese-Zugriff auf HA-Daten.<br><b>Limit:</b> Max 20 Tools.<br><b>Tipp:</b> "Jarvis, bau mir ein Tool..." erstellt Tools per Sprache.'},
  'decl_tools.type': {title:'Tool-Typ', text:'Welche Art von Berechnung soll dieses Tool ausführen?', detail:'<b>Entity-Vergleich:</b> Vergleicht 2 Sensoren (Differenz, Verhältnis, %)<br><b>Multi-Entity-Formel:</b> Kombiniert 3+ Entities (Durchschnitt, Summe, Min, Max)<br><b>Event-Zähler:</b> Zählt State-Changes (z.B. Türöffnungen)<br><b>Schwellwert-Monitor:</b> Prüft ob Wert in Min/Max-Bereich<br><b>Trend-Analyse:</b> Trend über Zeitraum (steigend/fallend)<br><b>Entity-Aggregation:</b> Durchschnitt über mehrere Entities<br><b>Zeitplan-Check:</b> Prüft aktiven Zeitplan'},
  'decl_tools.entity_a': {title:'Entity A', text:'Erster Sensor für den Vergleich. Suchfeld mit Autocomplete — tippe um Entities zu finden.'},
  'decl_tools.entity_b': {title:'Entity B', text:'Zweiter Sensor für den Vergleich.'},
  'decl_tools.entity': {title:'Entity', text:'Sensor dessen Wert analysiert wird.'},
  'decl_tools.entities': {title:'Entities', text:'Mehrere Sensoren die aggregiert oder gezählt werden. Kommagetrennt oder per Suche hinzufügen.'},
  'decl_tools.operation': {title:'Operation', text:'Wie die zwei Entities verglichen werden.', detail:'<b>Differenz:</b> A minus B<br><b>Verhältnis:</b> A geteilt durch B<br><b>Prozentual:</b> Änderung in Prozent'},
  'decl_tools.formula': {title:'Formel', text:'Wie die Entities kombiniert werden.'},
  'decl_tools.time_range': {title:'Zeitraum', text:'Über welchen Zeitraum die Analyse läuft.'},
  'decl_tools.thresholds': {title:'Schwellwerte', text:'Definierter Bereich. Status wird "ZU HOCH" oder "ZU NIEDRIG" wenn ausserhalb.'},
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
  const minAttr = min !== '' ? `min="${min}"` : '';
  const maxAttr = max !== '' ? `max="${max}"` : '';
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <input type="number" data-path="${path}" value="${v}" ${minAttr} ${maxAttr} step="${step}" onchange="clampNum(this)">${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}
function fRange(path, label, min, max, step, labels=null) {
  const v = getPath(S,path) ?? min;
  const lbl = labels ? (labels[v]||v) : v;
  const lblAttr = labels ? ` data-labels='${JSON.stringify(labels).replace(/'/g,"&#39;")}'` : '';
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="range-group"><input type="range" data-path="${path}" min="${min}" max="${max}" step="${step}" value="${v}"${lblAttr}
      oninput="updRange(this)"><span class="range-value" id="rv_${path.replace(/\./g,'_')}">${lbl}</span></div></div>`;
}
function fToggle(path, label, hint='') {
  const v = getPath(S,path);
  return `<div class="form-group"><div class="toggle-group"><label>${label}${helpBtn(path)}</label>
    <label class="toggle"><input type="checkbox" data-path="${path}" ${v?'checked':''}><span class="toggle-track"></span><span class="toggle-thumb"></span></label></div>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}
function fSelect(path, label, opts, hint='') {
  const v = getPath(S,path) ?? '';
  let h = `<div class="form-group"><label>${label}${helpBtn(path)}</label><select data-path="${path}">`;
  for(const o of opts) h += `<option value="${o.v}" ${v==o.v?'selected':''}>${o.l}</option>`;
  return h + `</select>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}
function fKeywords(path, label) {
  const arr = getPath(S,path) || [];
  let tags = arr.map(k => `<span class="kw-tag">${esc(k)}<span class="kw-rm" onclick="rmKw(this,'${path}')">&#10005;</span></span>`).join('');
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="kw-editor" data-path="${path}" onclick="this.querySelector('input').focus()">
      ${tags}<input class="kw-input" placeholder="+ hinzufügen..." onkeydown="addKw(event,this,'${path}')">
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
  scheduleAutoSave();
}

// Modell-Auswahl als Dropdown (dynamisch aus Ollama)
function fModelSelect(path, label, hint='') {
  const v = getPath(S, path) ?? '';
  // Dynamische Liste aus AVAILABLE_MODELS (von /api/ui/models/available)
  const models = AVAILABLE_MODELS.map(name => ({v: name, l: _modelLabel(name)}));
  // Aktuellen Wert in Liste sicherstellen (falls Modell deinstalliert wurde)
  const hasVal = models.some(m => m.v === v);
  let h = `<div class="form-group"><label>${label}${helpBtn(path)}</label><select data-path="${path}">`;
  if (!hasVal && v) h += `<option value="${esc(v)}" selected>${esc(v)} (nicht installiert)</option>`;
  for (const m of models) h += `<option value="${m.v}" ${v===m.v?'selected':''}>${m.l}</option>`;
  return h + `</select>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

// Menschenlesbare Labels für Ollama-Modellnamen
function _modelLabel(name) {
  const parts = name.split(':');
  const base = parts[0] || name;
  const tag = parts[1] || '';
  const sizeMatch = tag.match(/^(\d+\.?\d*)b/i);
  const size = sizeMatch ? sizeMatch[1] + 'B' : tag;
  const pretty = base.charAt(0).toUpperCase() + base.slice(1);
  return size ? `${pretty} ${size}` : pretty;
}

// Key-Value Mapping Editor (für Device-Mapping, DoA-Mapping etc.)
function fKeyValue(path, label, keyLabel='Schluessel', valLabel='Wert', hint='') {
  const obj = getPath(S, path) || {};
  const entries = Object.entries(obj);
  let rows = entries.map(([k,v], i) =>
    `<div class="kv-row" data-idx="${i}">
       <input type="text" class="kv-key" value="${esc(String(k))}" placeholder="${keyLabel}">
       <span class="kv-arrow">&#8594;</span>
       <input type="text" class="kv-val" value="${esc(v == null ? '' : String(v))}" placeholder="${valLabel}">
       <button class="kv-rm" onclick="kvRemove(this,'${esc(path)}')" title="Entfernen">&#10005;</button>
     </div>`
  ).join('');
  return `<div class="form-group"><label>${label}${helpBtn(path)}</label>
    <div class="kv-editor" data-path="${esc(path)}">
      ${rows}
      <button class="kv-add" onclick="kvAdd(this,'${esc(path)}','${esc(keyLabel)}','${esc(valLabel)}')">+ Zuordnung</button>
    </div>${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}
function kvAdd(btn, path, keyLabel, valLabel) {
  const editor = btn.closest('.kv-editor');
  if (!editor) return;
  const row = document.createElement('div');
  row.className = 'kv-row';
  row.innerHTML = `<input type="text" class="kv-key" placeholder="${esc(keyLabel)}">
    <span class="kv-arrow">&#8594;</span>
    <input type="text" class="kv-val" placeholder="${esc(valLabel)}">
    <button class="kv-rm" onclick="kvRemove(this,'${esc(path)}')" title="Entfernen">&#10005;</button>`;
  editor.insertBefore(row, btn);
  kvSync(editor, path);
}
function kvRemove(btn, path) {
  const editor = btn.closest('.kv-editor');
  const row = btn.closest('.kv-row');
  if (row) row.remove();
  if (editor) kvSync(editor, path);
}
function kvSync(editor, path) {
  const obj = {};
  editor.querySelectorAll('.kv-row').forEach(row => {
    const k = row.querySelector('.kv-key').value.trim();
    const v = row.querySelector('.kv-val').value.trim();
    if (k && v) {
      const num = Number(v);
      obj[k] = (v !== '' && !isNaN(num) && String(num) === v) ? num : v;
    }
  });
  setPath(S, path, obj);
  scheduleAutoSave();
}

// Info-Box
function fInfo(text) {
  return `<div class="info-box"><span class="info-icon">&#128161;</span>${text}</div>`;
}

function fSubheading(title) {
  return `<div class="f-subheading">${title}</div>`;
}

function sectionWrap(icon, title, content) {
  return `<div class="s-section"><div class="s-section-hdr" onclick="toggleSec(this)">
    <h3>${icon} ${title}</h3><span class="arrow">&#9660;</span></div>
    <div class="s-section-body">${content}</div></div>`;
}

// ---- Entity-Picker Komponenten ----
// Cached entities (lazy loaded, retries on empty)
let _pickerEntities = null;
let _pickerLastAttempt = 0;
async function ensurePickerEntities() {
  // Nur Cache verwenden wenn tatsaechlich Entities geladen wurden
  if (_pickerEntities && _pickerEntities.length > 0) return _pickerEntities;
  // Retry-Schutz: maximal alle 3 Sekunden neu versuchen
  if (Date.now() - _pickerLastAttempt < 3000) return _pickerEntities || [];
  _pickerLastAttempt = Date.now();
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

// Room-Entity-Map: Pro Raum eine Entity zuordnen (für Speaker, Motion Sensors)
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
        <input class="form-input entity-pick-input" value="${esc(val)}" placeholder="&#128269; Entity wählen..."
          data-room-map="${path}" data-room-name="${esc(room)}" data-domains="${domStr}"
          oninput="entityPickFilter(this,'${domStr}')" onfocus="entityPickFilter(this,'${domStr}')"
          style="font-size:12px;font-family:var(--mono);padding:6px 10px;">
        <div class="entity-pick-dropdown" style="display:none;"></div>
      </div>
      ${val ? `<button class="btn btn-sm" style="padding:2px 6px;min-width:auto;font-size:11px;color:var(--danger);" onclick="this.parentElement.querySelector('input').value='';this.remove()">&#10005;</button>` : ''}
    </div>`;
  }
  // Manuelle Einträge die nicht in rooms sind
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
    rows = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Räume bekannt. Räume werden automatisch aus den MindHome-Geräten erkannt.</div>';
  }
  return `<div class="form-group"><label>${label}</label>
    <div class="room-entity-map" data-path="${path}">${rows}</div>
    ${hint?`<div class="hint">${hint}</div>`:''}</div>`;
}

function _getKnownRooms() {
  // Räume aus MindHome entities (wenn geladen)
  const rooms = new Set();
  if (_mhEntities && _mhEntities.rooms) {
    for (const r of Object.keys(_mhEntities.rooms)) rooms.add(r.toLowerCase());
  }
  // Räume aus bestehenden room_speakers / room_motion_sensors
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
    `<div class="entity-pick-item" onmousedown="entityPickSelect(this,'${esc(e.entity_id)}')" ontouchend="entityPickSelect(this,'${esc(e.entity_id)}')">
      <span class="ename">${esc(e.name)}</span>
      <span class="eid">${esc(e.entity_id)}</span>
    </div>`
  ).join('');
  dropdown.style.display = 'block';

  // Schließen bei Blur (längerer Delay für Mobile-Touch)
  input.onblur = () => setTimeout(() => { dropdown.style.display = 'none'; }, 400);
}

function entityPickSelect(item, entityId) {
  const wrap = item.closest('.entity-pick-wrap');
  const input = wrap.querySelector('.entity-pick-input, input[data-room-map]');
  const dropdown = wrap.querySelector('.entity-pick-dropdown');
  if (dropdown) dropdown.style.display = 'none';

  // Trigger-Modus: Input in pt-row/st-row → Wert setzen + Sync aufrufen
  const triggerRow = input?.closest('.pt-row, .st-row');
  if (triggerRow) {
    input.value = entityId;
    const editor = triggerRow.closest('.pt-editor, .st-editor');
    if (editor?.classList.contains('pt-editor')) ptSync(editor);
    if (editor?.classList.contains('st-editor')) stSync(editor);
    return;
  }

  // Scene Device-Trigger: Entity-ID setzen + onchange feuern
  if (input?.classList?.contains('scene-dt-input')) {
    input.value = entityId;
    input.dispatchEvent(new Event('change'));
    return;
  }

  // Scene Action Entity: Spezifisches Gerät für eine Szenen-Aktion
  if (input?.classList?.contains('scene-action-entity-input')) {
    input.value = entityId;
    const sceneId = input.dataset.sceneId;
    const idx = parseInt(input.dataset.actionIdx);
    if (sceneId && !isNaN(idx)) sceneActionEntityChanged(sceneId, idx, entityId);
    return;
  }

  // Cover-Profil: Entity-ID setzen + updateCoverProfile aufrufen
  if (input?.dataset?.coverIdx !== undefined) {
    input.value = entityId;
    const idx = parseInt(input.dataset.coverIdx);
    if (!isNaN(idx)) updateCoverProfile(idx, 'entity_id', entityId);
    return;
  }

  // Room-Map Modus: Input-Wert setzen
  if (input?.dataset?.roomMap) {
    input.value = entityId;
    // Auto-fill: Name-Feld befuellen wenn HA Person-Entity in Member-Row ausgewählt
    if (input?.dataset?.memberField === 'ha_entity') {
      const row = input.closest('.person-row');
      const nameInput = row?.querySelector('[data-member-field="name"]');
      if (nameInput && !nameInput.value.trim() && _pickerEntities) {
        const ent = _pickerEntities.find(e => e.entity_id === entityId);
        if (ent) nameInput.value = ent.name;
      }
    }
    return;
  }

  // Power-Close Cover-Picker: Entity zur Liste hinzufügen
  if (input?.dataset?.powercloseId) {
    const ruleId = parseInt(input.dataset.powercloseId);
    input.value = '';
    addPowerCloseCover(ruleId, entityId);
    return;
  }

  // Generischer Fallback: Input-Wert setzen + onchange feuern (z.B. Power-Close Sensor)
  if (input && !input.dataset?.path && !input.dataset?.roomMap && input.classList.contains('entity-pick-input')) {
    input.value = entityId;
    input.dispatchEvent(new Event('change'));
    return;
  }

  // List Modus: Entity zu Array hinzufügen
  const path = input?.dataset?.path;
  if (!path) return;
  mergeCurrentTabIntoS();
  const arr = getPath(S, path) || [];
  if (!arr.includes(entityId)) {
    arr.push(entityId);
    setPath(S, path, arr);
    renderCurrentTab();
    scheduleAutoSave();
  }
}

function rmEntityPick(el, path) {
  mergeCurrentTabIntoS();
  const tag = el.parentElement;
  const word = tag.textContent.replace('✕','').trim();
  const arr = (getPath(S, path) || []).filter(k => k !== word);
  setPath(S, path, arr);
  renderCurrentTab();
  scheduleAutoSave();
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
    const pHumor = prof.humor || '';
    const pEmpathy = prof.empathy || '';
    const pStyle = prof.response_style || '';
    const pFormality = prof.formality_start || '';
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
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border);font-size:11px;color:var(--text-muted);margin-bottom:4px;">Persönlichkeit</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <div>
          <label style="font-size:11px;color:var(--text-muted);">Humor-Level</label>
          <select data-person-profile="${esc(person)}" data-profile-field="humor"
            style="font-size:11px;padding:5px 8px;width:100%;box-sizing:border-box;">
            <option value="" ${!pHumor?'selected':''}>-- Standard --</option>
            <option value="1" ${pHumor==1?'selected':''}>1 - Ernst</option>
            <option value="2" ${pHumor==2?'selected':''}>2 - Sachlich</option>
            <option value="3" ${pHumor==3?'selected':''}>3 - Normal</option>
            <option value="4" ${pHumor==4?'selected':''}>4 - Humorvoll</option>
            <option value="5" ${pHumor==5?'selected':''}>5 - Sarkastisch</option>
          </select>
        </div>
        <div>
          <label style="font-size:11px;color:var(--text-muted);">Empathie</label>
          <select data-person-profile="${esc(person)}" data-profile-field="empathy"
            style="font-size:11px;padding:5px 8px;width:100%;box-sizing:border-box;">
            <option value="" ${!pEmpathy?'selected':''}>-- Standard --</option>
            <option value="subtil" ${pEmpathy==='subtil'?'selected':''}>Subtil</option>
            <option value="normal" ${pEmpathy==='normal'?'selected':''}>Normal</option>
            <option value="ausführlich" ${pEmpathy==='ausführlich'?'selected':''}>Ausführlich</option>
            <option value="deaktiviert" ${pEmpathy==='deaktiviert'?'selected':''}>Deaktiviert</option>
          </select>
        </div>
        <div>
          <label style="font-size:11px;color:var(--text-muted);">Antwort-Stil</label>
          <select data-person-profile="${esc(person)}" data-profile-field="response_style"
            style="font-size:11px;padding:5px 8px;width:100%;box-sizing:border-box;">
            <option value="" ${!pStyle?'selected':''}>-- Standard --</option>
            <option value="kurz" ${pStyle==='kurz'?'selected':''}>Kurz</option>
            <option value="normal" ${pStyle==='normal'?'selected':''}>Normal</option>
            <option value="ausführlich" ${pStyle==='ausführlich'?'selected':''}>Ausführlich</option>
          </select>
        </div>
        <div>
          <label style="font-size:11px;color:var(--text-muted);">Formalität</label>
          <select data-person-profile="${esc(person)}" data-profile-field="formality_start"
            style="font-size:11px;padding:5px 8px;width:100%;box-sizing:border-box;">
            <option value="" ${!pFormality?'selected':''}>-- Standard --</option>
            <option value="20" ${pFormality==20?'selected':''}>20 - Sehr locker</option>
            <option value="40" ${pFormality==40?'selected':''}>40 - Locker</option>
            <option value="60" ${pFormality==60?'selected':''}>60 - Normal</option>
            <option value="80" ${pFormality==80?'selected':''}>80 - Formell</option>
            <option value="100" ${pFormality==100?'selected':''}>100 - Sehr formell</option>
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

function clampNum(el) {
  const min = el.min !== '' ? parseFloat(el.min) : null;
  const max = el.max !== '' ? parseFloat(el.max) : null;
  let v = parseFloat(el.value);
  if (isNaN(v)) return;
  if (min !== null && v < min) { el.value = min; }
  if (max !== null && v > max) { el.value = max; }
}

function updRange(el) {
  const path = el.dataset.path;
  let display = el.value;
  if (el.dataset.labels) {
    try {
      const labels = JSON.parse(el.dataset.labels);
      display = labels[el.value] || labels[parseFloat(el.value)] || el.value;
    } catch(e) {}
  }
  document.getElementById('rv_'+path.replace(/\./g,'_')).textContent = display;
}
function toggleSec(hdr) {
  const body = hdr.nextElementSibling;
  const isOpen = hdr.classList.contains('open');
  if (isOpen) {
    // Collapse: animate height to 0
    body.style.maxHeight = body.scrollHeight + 'px';
    body.style.overflow = 'hidden';
    body.style.transition = 'max-height 0.3s ease, padding 0.3s ease';
    requestAnimationFrame(() => {
      body.style.maxHeight = '0';
      body.style.padding = '0 18px';
    });
    hdr.classList.remove('open');
    body.classList.remove('open');
  } else {
    // Expand: animate from 0 to scrollHeight, then remove max-height
    body.classList.add('open');
    hdr.classList.add('open');
    body.style.maxHeight = '0';
    body.style.overflow = 'hidden';
    body.style.transition = 'max-height 0.3s ease, padding 0.3s ease';
    requestAnimationFrame(() => {
      body.style.maxHeight = body.scrollHeight + 'px';
      body.style.padding = '18px';
      setTimeout(() => { body.style.maxHeight = 'none'; body.style.overflow = 'visible'; body.style.transition = ''; }, 310);
    });
  }
}

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
    scheduleAutoSave();
  }
}
function rmKw(el, path) {
  mergeCurrentTabIntoS();
  const tag = el.parentElement;
  const word = tag.textContent.replace('✕','').trim();
  const arr = (getPath(S, path) || []).filter(k => k !== word);
  setPath(S, path, arr);
  renderCurrentTab();
  scheduleAutoSave();
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

// ---- Model Profiles Sektion (eingebettet in Persönlichkeit-Tab) ----
function _renderModelProfiles() {
  const profiles = getPath(S, 'model_profiles') || {};
  const profileKeys = Object.keys(profiles).filter(k => k !== 'default');
  const defaultP = profiles['default'] || {};

  // Profil-Felder mit Labels und Ranges
  const PROFILE_FIELDS = [
    {key:'supports_think_tags', label:'Think-Tags', type:'toggle', hint:'LLM nutzt <think>-Tags für Chain-of-Thought'},
    {key:'supports_think_with_tools', label:'Think + Tools', type:'toggle', hint:'Think-Tags bleiben bei Tool-Calls aktiv'},
    {key:'character_hint', label:'JARVIS Character-Hint', type:'textarea', hint:'Modell-spezifische Prompt-Verstaerkung gegen Chatbot-Phrasen. Wird als Prio-1-Sektion in den System-Prompt injiziert.'},
    {key:'temperature', label:'Temperatur', type:'range', min:0, max:2, step:0.1},
    {key:'top_p', label:'Top-P', type:'range', min:0, max:1, step:0.05},
    {key:'top_k', label:'Top-K', type:'range', min:1, max:100, step:1},
    {key:'min_p', label:'Min-P', type:'range', min:0, max:0.5, step:0.01},
    {key:'repeat_penalty', label:'Repeat Penalty', type:'range', min:1, max:2, step:0.05},
    {key:'think_temperature', label:'Think-Temperatur', type:'range', min:0, max:1, step:0.05},
    {key:'think_top_p', label:'Think Top-P', type:'range', min:0, max:1, step:0.05},
  ];

  function renderProfileCard(name, p, isDefault) {
    const prefix = 'model_profiles.' + name;
    const icon = isDefault ? '&#9881;' : '&#129302;';
    const title = isDefault ? 'default (Fallback)' : name;
    const removable = !isDefault;
    let html = '<div class="mp-card" style="margin-bottom:12px;padding:14px;background:var(--bg-secondary);border-radius:var(--radius-sm);border-left:3px solid ' +
      (isDefault ? 'var(--text-muted)' : 'var(--accent)') + ';">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">';
    html += '<span style="font-weight:600;font-size:14px;">' + icon + ' ' + esc(title) + '</span>';
    if (removable) {
      html += '<button class="btn btn-danger btn-sm" onclick="removeModelProfile(\'' + esc(name) + '\')" style="padding:4px 8px;min-width:auto;font-size:11px;" title="Profil entfernen">&#128465;</button>';
    }
    html += '</div>';
    for (const f of PROFILE_FIELDS) {
      const val = p[f.key] ?? defaultP[f.key] ?? '';
      const path = prefix + '.' + f.key;
      if (f.type === 'toggle') {
        const checked = val ? 'checked' : '';
        html += '<div class="form-group" style="margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">' +
          '<label style="font-size:12px;margin:0;">' + f.label + '</label>' +
          '<label class="switch" style="margin:0;"><input type="checkbox" data-path="' + path + '" ' + checked + '><span class="slider"></span></label></div>';
      } else if (f.type === 'textarea') {
        html += '<div class="form-group" style="margin-bottom:6px;">' +
          '<label style="font-size:12px;">' + f.label + (f.hint ? ' <span style="color:var(--text-muted);font-weight:normal;">— ' + f.hint + '</span>' : '') + '</label>' +
          '<textarea data-path="' + path + '" rows="3" style="width:100%;font-size:12px;font-family:var(--mono);resize:vertical;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border-color);border-radius:var(--radius-sm);padding:6px;">' + esc(val) + '</textarea>' +
          '</div>';
      } else {
        html += '<div class="form-group" style="margin-bottom:6px;">' +
          '<label style="font-size:12px;">' + f.label + '</label>' +
          '<div style="display:flex;gap:8px;align-items:center;">' +
          '<input type="range" data-path="' + path + '" min="' + f.min + '" max="' + f.max + '" step="' + f.step + '" value="' + val + '" style="flex:1;" oninput="this.nextElementSibling.textContent=this.value">' +
          '<span style="min-width:40px;text-align:right;font-family:var(--mono);font-size:12px;">' + val + '</span>' +
          '</div></div>';
      }
    }
    html += '</div>';
    return html;
  }

  let body = fInfo('Modell-Profile definieren LLM-Parameter pro Modell-Familie. Neues Modell = nur Profil hier anlegen, kein Code nötig. Match: Laengster Key der im Modellnamen vorkommt gewinnt (z.B. "qwen3.5:9b" &rarr; Profil "qwen3.5").') +
    renderProfileCard('default', defaultP, true);

  for (const name of profileKeys) {
    body += renderProfileCard(name, profiles[name] || {}, false);
  }

  body += '<div style="display:flex;gap:8px;margin-top:8px;">' +
    '<input type="text" id="mpNewName" placeholder="Profilname (z.B. phi4, command-r)" style="flex:1;font-size:13px;">' +
    '<button class="btn btn-secondary" onclick="addModelProfile()" style="white-space:nowrap;">+ Profil</button>' +
    '</div>';

  return sectionWrap('&#9881;', 'Modell-Profile', body);
}

function addModelProfile() {
  const input = document.getElementById('mpNewName');
  const name = (input.value || '').trim().toLowerCase();
  if (!name || name === 'default') return;
  mergeCurrentTabIntoS();
  if (!S.model_profiles) S.model_profiles = {};
  if (!S.model_profiles[name]) {
    S.model_profiles[name] = {};
  }
  renderCurrentTab();
  scheduleAutoSave();
}

function removeModelProfile(name) {
  mergeCurrentTabIntoS();
  if (S.model_profiles && S.model_profiles[name]) {
    delete S.model_profiles[name];
  }
  renderCurrentTab();
  scheduleAutoSave();
}

// ---- Appliance Monitor: Dynamic device list ----
function renderApplianceDevices() {
  const c = document.getElementById('applianceDevicesContainer');
  if (!c) return;
  const devices = getPath(S, 'appliance_monitor.devices') || [];
  if (!devices.length) {
    c.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Geräte konfiguriert. Klicke "+ Geraet hinzufügen".</div>';
    return;
  }
  c.innerHTML = devices.map((dev, i) => {
    const patterns = (dev.patterns || []).map(p =>
      `<span class="kw-tag">${esc(p)}<span class="kw-rm" onclick="rmAppliancePattern(${i},this)">&#10005;</span></span>`
    ).join('');
    return `<div class="appliance-card" style="background:var(--bg-primary);border:1px solid var(--border-color);border-radius:var(--radius-sm);padding:10px;margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <span style="font-weight:600;font-size:13px;">${esc(dev.label || dev.key)}</span>
        <button class="btn btn-sm" style="color:var(--danger);font-size:11px;padding:2px 8px;" onclick="removeApplianceDevice(${i})">Entfernen</button>
      </div>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">Key: ${esc(dev.key)} &middot; Event: ${esc(dev.key)}_done</div>
      <div style="margin-bottom:6px;">
        <label style="font-size:12px;font-weight:500;">Entity-Muster</label>
        <div class="kw-editor" data-path="appliance_monitor.devices.${i}.patterns" onclick="this.querySelector('input').focus()">
          ${patterns}<input class="kw-input" placeholder="+ Muster..." onkeydown="addKw(event,this,'appliance_monitor.devices.${i}.patterns')">
        </div>
      </div>
      <div style="margin-top:6px;">
        <label style="font-size:12px;font-weight:500;">Oder Entity direkt auswählen</label>
        <button class="btn btn-sm btn-secondary" onclick="pickEntityForAppliance(${i})" style="font-size:11px;margin-top:4px;">Entity aus HA wählen...</button>
      </div>
    </div>`;
  }).join('');
}

function addApplianceDevice() {
  // Inline-Formular statt prompt() — passt zum Jarvis-UI-Stil
  const c = document.getElementById('applianceDevicesContainer');
  if (!c) return;
  // Prüfen ob bereits ein Formular offen ist
  if (c.querySelector('.appliance-add-form')) return;
  const form = document.createElement('div');
  form.className = 'appliance-add-form';
  form.style.cssText = 'background:var(--bg-primary);border:1px solid var(--accent);border-radius:var(--radius-sm);padding:12px;margin-bottom:8px;';
  form.innerHTML = `
    <div style="font-weight:600;font-size:13px;margin-bottom:8px;">Neues Geraet hinzufügen</div>
    <div class="form-group" style="margin-bottom:8px;">
      <label style="font-size:12px;">Geräte-Key</label>
      <input id="applianceNewKey" class="form-input" placeholder="z.B. oven, robot_vacuum, coffee_machine" style="font-size:12px;font-family:var(--mono);">
    </div>
    <div class="form-group" style="margin-bottom:8px;">
      <label style="font-size:12px;">Anzeigename</label>
      <input id="applianceNewLabel" class="form-input" placeholder="z.B. Backofen, Saugroboter, Kaffeemaschine" style="font-size:12px;">
    </div>
    <div class="form-group" style="margin-bottom:8px;">
      <label style="font-size:12px;">Power-Sensor (optional)</label>
      <div class="entity-pick-wrap">
        <input id="applianceNewSensor" class="form-input entity-pick-input" placeholder="&#128269; sensor.steckdose_power" data-domains="sensor"
          oninput="entityPickFilter(this,'sensor')" onfocus="entityPickFilter(this,'sensor')" style="font-size:12px;font-family:var(--mono);">
        <div class="entity-pick-dropdown" style="display:none;"></div>
      </div>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-sm btn-secondary" onclick="this.closest('.appliance-add-form').remove()">Abbrechen</button>
      <button class="btn btn-sm" onclick="confirmAddApplianceDevice()">Hinzufuegen</button>
    </div>`;
  c.insertBefore(form, c.firstChild);
  form.querySelector('#applianceNewKey').focus();
}

function confirmAddApplianceDevice() {
  const keyInput = document.getElementById('applianceNewKey');
  const labelInput = document.getElementById('applianceNewLabel');
  const sensorInput = document.getElementById('applianceNewSensor');
  if (!keyInput || !keyInput.value.trim()) { toast('Geräte-Key ist erforderlich.', 'error'); return; }
  const cleanKey = keyInput.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_');
  const label = (labelInput.value.trim() || cleanKey);
  const sensor = sensorInput ? sensorInput.value.trim() : '';
  const devices = getPath(S, 'appliance_monitor.devices') || [];
  if (devices.some(d => d.key === cleanKey)) { toast('Geraet "' + cleanKey + '" existiert bereits.', 'error'); return; }
  const patterns = [cleanKey];
  if (sensor) patterns.push(sensor);
  devices.push({key: cleanKey, label: label, patterns: patterns});
  setPath(S, 'appliance_monitor.devices', devices);
  renderApplianceDevices();
  markDirty();
  toast('Geraet "' + label + '" hinzugefuegt.');
}

function removeApplianceDevice(idx) {
  const devices = getPath(S, 'appliance_monitor.devices') || [];
  const dev = devices[idx];
  if (!confirm('Geraet "' + (dev.label || dev.key) + '" entfernen?')) return;
  // Orphaned Power-Profile aufräumen
  const profiles = getPath(S, 'appliance_monitor.power_profiles') || {};
  if (dev.key && profiles[dev.key]) {
    delete profiles[dev.key];
    setPath(S, 'appliance_monitor.power_profiles', profiles);
  }
  devices.splice(idx, 1);
  setPath(S, 'appliance_monitor.devices', devices);
  renderApplianceDevices();
  renderPowerProfiles();
  markDirty();
  scheduleAutoSave();
}

function rmAppliancePattern(devIdx, el) {
  const devices = getPath(S, 'appliance_monitor.devices') || [];
  const tag = el.closest('.kw-tag');
  const pattern = tag.textContent.replace('✕', '').trim();
  const patterns = devices[devIdx].patterns || [];
  const pi = patterns.indexOf(pattern);
  if (pi >= 0) patterns.splice(pi, 1);
  devices[devIdx].patterns = patterns;
  setPath(S, 'appliance_monitor.devices', devices);
  renderApplianceDevices();
  markDirty();
}

async function pickEntityForAppliance(devIdx) {
  const entities = await _loadPickerEntities();
  const sensors = entities.filter(e => e.entity_id.startsWith('sensor.') &&
    (e.entity_id.includes('power') || e.entity_id.includes('energy') || e.entity_id.includes('watt') ||
     e.entity_id.includes('leistung') || e.entity_id.includes('verbrauch') ||
     (e.attributes && e.attributes.unit_of_measurement === 'W')));
  if (!sensors.length) { toast('Keine Power-Sensoren gefunden.', 'error'); return; }

  // Erstelle Popup-Dialog
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;';
  const dialog = document.createElement('div');
  dialog.style.cssText = 'background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:var(--radius-md);padding:16px;max-width:500px;width:90%;max-height:70vh;display:flex;flex-direction:column;';
  dialog.innerHTML = `
    <div style="font-weight:600;font-size:14px;margin-bottom:8px;">Power-Sensor auswählen</div>
    <input type="text" id="applianceEntitySearch" placeholder="Suchen..." style="margin-bottom:8px;padding:6px 10px;border:1px solid var(--border-color);border-radius:var(--radius-sm);background:var(--bg-primary);color:var(--text-primary);" oninput="filterApplianceEntities()">
    <div id="applianceEntityList" style="overflow-y:auto;flex:1;max-height:50vh;"></div>
    <button class="btn btn-secondary" onclick="this.closest('div[style*=fixed]').remove()" style="margin-top:8px;">Abbrechen</button>
  `;
  overlay.appendChild(dialog);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);

  window._appliancePickSensors = sensors;
  window._appliancePickDevIdx = devIdx;
  window._appliancePickOverlay = overlay;
  filterApplianceEntities();
  dialog.querySelector('#applianceEntitySearch').focus();
}

function filterApplianceEntities() {
  const q = (document.getElementById('applianceEntitySearch')?.value || '').toLowerCase();
  const sensors = window._appliancePickSensors || [];
  const filtered = sensors.filter(e => {
    const name = (e.attributes?.friendly_name || e.entity_id).toLowerCase();
    return !q || name.includes(q) || e.entity_id.toLowerCase().includes(q);
  }).slice(0, 50);
  const list = document.getElementById('applianceEntityList');
  if (!list) return;
  list.innerHTML = filtered.map(e => {
    const name = e.attributes?.friendly_name || e.entity_id;
    const val = e.state || '';
    const unit = e.attributes?.unit_of_measurement || '';
    return `<div onclick="selectApplianceEntity('${esc(e.entity_id)}')" style="padding:8px;cursor:pointer;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;align-items:center;" onmouseover="this.style.background='var(--bg-hover)'" onmouseout="this.style.background=''">
      <div><div style="font-size:13px;font-weight:500;">${esc(name)}</div><div style="font-size:11px;color:var(--text-muted);">${esc(e.entity_id)}</div></div>
      <span style="font-size:12px;color:var(--text-secondary);">${esc(val)} ${esc(unit)}</span>
    </div>`;
  }).join('');
  if (!filtered.length) list.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;">Keine Treffer</div>';
}

function selectApplianceEntity(entityId) {
  const devIdx = window._appliancePickDevIdx;
  const devices = getPath(S, 'appliance_monitor.devices') || [];
  if (!devices[devIdx]) return;
  // Entity-ID-Teile als Pattern extrahieren (ohne "sensor." Prefix)
  const shortId = entityId.replace(/^sensor\./, '');
  const patterns = devices[devIdx].patterns || [];
  if (!patterns.includes(shortId) && !patterns.includes(entityId)) {
    patterns.push(shortId);
    devices[devIdx].patterns = patterns;
    setPath(S, 'appliance_monitor.devices', devices);
    markDirty();
  }
  if (window._appliancePickOverlay) window._appliancePickOverlay.remove();
  renderApplianceDevices();
  toast('Entity "' + entityId + '" hinzugefuegt.', 'success');
}

// ---- Power Profiles: Per-Geraet Schwellwerte ----
function renderPowerProfiles() {
  const c = document.getElementById('powerProfilesContainer');
  if (!c) return;
  const devices = getPath(S, 'appliance_monitor.devices') || [];
  const profiles = getPath(S, 'appliance_monitor.power_profiles') || {};
  if (!devices.length) {
    c.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Füge zuerst Geräte oben hinzu, dann erscheinen hier die Power-Profile.</div>';
    return;
  }
  c.innerHTML = devices.map(dev => {
    const k = String(dev.key || '').replace(/[^a-zA-Z0-9_]/g, '');
    if (!k) return '';
    const p = profiles[k] || {};
    const label = dev.label || k;
    return `<div style="background:var(--bg-primary);border:1px solid var(--border-color);border-radius:var(--radius-sm);padding:10px;margin-bottom:8px;">
      <div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#9889; ${esc(label)}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
        <div class="form-group" style="margin:0;">
          <label style="font-size:11px;">Laufend ab (W)</label>
          <input type="number" class="form-input" style="font-size:12px;" value="${p.running||''}" min="1" max="20000"
            onchange="setPowerProfile('${k}','running',this.value)">
        </div>
        <div class="form-group" style="margin:0;">
          <label style="font-size:11px;">Idle unter (W)</label>
          <input type="number" class="form-input" style="font-size:12px;" value="${p.idle||''}" min="0" max="500"
            onchange="setPowerProfile('${k}','idle',this.value)">
        </div>
        <div class="form-group" style="margin:0;">
          <label style="font-size:11px;">Standby (W)</label>
          <input type="number" class="form-input" style="font-size:12px;" value="${p.standby||''}" min="0" max="100"
            onchange="setPowerProfile('${k}','standby',this.value)">
        </div>
        <div class="form-group" style="margin:0;">
          <label style="font-size:11px;">Peak (W)</label>
          <input type="number" class="form-input" style="font-size:12px;" value="${p.peak||''}" min="10" max="50000"
            onchange="setPowerProfile('${k}','peak',this.value)">
        </div>
        <div class="form-group" style="margin:0;">
          <label style="font-size:11px;">Wartezeit (Min)</label>
          <input type="number" class="form-input" style="font-size:12px;" value="${p.confirm_minutes||''}" min="1" max="60"
            onchange="setPowerProfile('${k}','confirm_minutes',this.value)">
        </div>
        <div class="form-group" style="margin:0;">
          <label style="font-size:11px;">Hysterese (W)</label>
          <input type="number" class="form-input" style="font-size:12px;" value="${p.hysteresis||''}" min="0" max="200"
            onchange="setPowerProfile('${k}','hysteresis',this.value)">
        </div>
      </div>
    </div>`;
  }).join('');
}

function setPowerProfile(deviceKey, field, value) {
  // Sanitize device key (nur alphanumerisch + Underscore)
  const safeKey = String(deviceKey).replace(/[^a-zA-Z0-9_]/g, '');
  if (!safeKey) return;
  const profiles = getPath(S, 'appliance_monitor.power_profiles') || {};
  if (!profiles[safeKey]) profiles[safeKey] = {};
  profiles[safeKey][field] = parseFloat(value) || 0;
  setPath(S, 'appliance_monitor.power_profiles', profiles);
  markDirty();
  scheduleAutoSave();
}

// ---- Character-Break Stats Loader ----
async function loadCharBreakStats() {
  const el = document.getElementById('charBreakStatsContent');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--accent);">Lade...</span>';
  try {
    const resp = await fetch('/api/assistant/character-break-stats');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    if (data.total_breaks === 0) {
      el.innerHTML = '<span style="color:var(--success);">Keine Charakter-Brueche in den letzten 7 Tagen.</span>';
      return;
    }
    let html = '<div style="margin-bottom:6px;">Gesamt: <strong>' + data.total_breaks + '</strong> Brueche</div>';
    // Typ-Aufschluesselung
    const TYPE_LABELS = {
      llm_voice: 'LLM-Stimme (zu generisch)',
      hallucination: 'Halluzination (erfundene Werte)',
      identity: 'Identitaets-Bruch ("Ich bin ein KI")',
      formal_sie: 'Formelles Sie statt Du',
      banned_starter: 'Verbotener Satzanfang'
    };
    if (data.totals && Object.keys(data.totals).length) {
      html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;">';
      for (const [type, count] of Object.entries(data.totals).sort((a,b) => b[1]-a[1])) {
        const label = TYPE_LABELS[type] || type;
        const color = count > 10 ? 'var(--danger)' : count > 3 ? 'var(--warning)' : 'var(--text-muted)';
        html += '<span style="padding:2px 8px;border-radius:10px;background:var(--bg-secondary);border:1px solid ' + color + ';font-size:11px;">' +
          '<span style="color:' + color + ';font-weight:600;">' + count + '</span> ' + label + '</span>';
      }
      html += '</div>';
    }
    // Letzte Einträge
    if (data.recent_log && data.recent_log.length) {
      html += '<details><summary style="cursor:pointer;color:var(--accent);font-size:11px;">Letzte Brueche anzeigen</summary>';
      html += '<div style="margin-top:4px;max-height:150px;overflow-y:auto;">';
      for (const entry of data.recent_log.slice(0, 10)) {
        const typeLabel = TYPE_LABELS[entry.type] || entry.type;
        const ts = entry.ts ? entry.ts.substring(5, 16).replace('T', ' ') : '';
        html += '<div style="padding:2px 0;border-bottom:1px solid var(--border-color);font-size:11px;">' +
          '<span style="color:var(--text-muted);">' + ts + '</span> ' +
          '<strong>' + typeLabel + '</strong>: ' + esc(entry.detail || '') + '</div>';
      }
      html += '</div></details>';
    }
    el.innerHTML = html;
  } catch (err) {
    el.innerHTML = '<span style="color:var(--danger);">Fehler: ' + esc(err.message) + '</span>';
  }
}

// ---- Tab 1: Allgemein ----
function renderGeneral() {
  return sectionWrap('&#9881;', 'Assistent',
    fInfo('Grundeinstellungen für deinen Assistenten — Name, Sprache und Version.') +
    fText('assistant.name', 'Name', 'So stellt sich der Assistent vor') +
    fText('assistant.version', 'Version', '', true) +
    fSelect('assistant.language', 'Sprache', [{v:'de',l:'Deutsch'},{v:'en',l:'English'}])
  ) +
  sectionWrap('&#128269;', 'Web-Suche',
    fInfo('Optionale Web-Recherche für Wissensfragen. Privacy-First: SearXNG (self-hosted) oder DuckDuckGo. Standardmaessig deaktiviert. Standard: Max. 5 Ergebnisse, Timeout 10 Sek., Cache 5 Min.') +
    fToggle('web_search.enabled', 'Web-Suche aktivieren') +
    fSelect('web_search.engine', 'Suchmaschine', [{v:'searxng',l:'SearXNG (self-hosted)'},{v:'duckduckgo',l:'DuckDuckGo'}]) +
    fText('web_search.searxng_url', 'SearXNG URL', 'Nur relevant wenn SearXNG als Engine gewählt') +
    fNum('web_search.max_results', 'Max. Ergebnisse', 1, 20, 1) +
    fNum('web_search.timeout_seconds', 'Timeout (Sekunden)', 3, 30, 1) +
    fNum('web_search.cache_ttl_seconds', 'Cache-Dauer (Sek)', 0, 900, 60) +
    fNum('web_search.rate_limit_max', 'Max. Suchen pro Fenster', 1, 30, 1) +
    fNum('web_search.rate_limit_window', 'Rate-Limit Fenster (Sek)', 10, 300, 10)
  ) +
  _renderPersonsSections() +
  sectionWrap('&#127899;', 'Geräte-Erkennung',
    fInfo('Wörter die der Assistent zur Erkennung von Geräte-Befehlen und Status-Abfragen nutzt. Ein Wort pro Zeile.') +
    fTextarea('command_detection.device_nouns', 'Geräte-Substantive', 'z.B. "rollladen", "licht", "lampe"') +
    fTextarea('command_detection.action_words', 'Aktions-Wörter', 'z.B. "auf", "zu", "an", "aus"') +
    fTextarea('command_detection.command_verbs', 'Befehls-Verben', 'z.B. "mach ", "schalte ", "stell "') +
    fTextarea('command_detection.query_markers', 'Abfrage-Marker', 'z.B. "welche", "status", "zeig"') +
    fTextarea('command_detection.action_exclusions', 'Aktions-Ausnahmen', 'z.B. "einstellen", "dimmen"') +
    fTextarea('command_detection.status_nouns', 'Status-Substantive', 'z.B. "rollladen", "rollo" (inkl. Plurale)')
  );
}

// Personen-Sektionen (eingebettet in Allgemein-Tab)
function _renderPersonsSections() {
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
    memberRows += `<div class="person-row" style="padding:12px;background:var(--bg-secondary);border-radius:var(--radius-sm);border-left:3px solid ${ri.color};margin-bottom:10px;">
      <div style="display:flex;gap:10px;align-items:center;margin-bottom:8px;">
        <span style="font-size:20px;">${ri.icon}</span>
        <input type="text" value="${esc(m.name || '')}" data-member-idx="${i}" data-member-field="name"
          placeholder="Name eingeben..." style="flex:1;font-size:14px;">
        <select data-member-idx="${i}" data-member-field="role" style="width:140px;" onchange="updateMemberRoleVisual(this)">
          <option value="owner" ${m.role==='owner'?'selected':''}>&#128081; Hausherr/in</option>
          <option value="member" ${m.role==='member'?'selected':''}>&#128100; Mitbewohner/in</option>
          <option value="guest" ${m.role==='guest'?'selected':''}>&#128587; Gast</option>
        </select>
        <button class="btn btn-danger btn-sm" onclick="removeHouseholdMember(${i})"
          style="padding:6px 10px;min-width:auto;" title="Entfernen">&#128465;</button>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;padding-left:30px;">
        <div>
          <label style="font-size:11px;color:var(--text-muted);">HA Person-Entity</label>
          <div class="entity-pick-wrap">
            <input class="form-input entity-pick-input" value="${esc(m.ha_entity || '')}"
              placeholder="&#128269; person.* zuweisen..."
              data-member-idx="${i}" data-member-field="ha_entity" data-room-map="ha_entity"
              oninput="entityPickFilter(this,'person')" onfocus="entityPickFilter(this,'person')"
              style="font-size:12px;font-family:var(--mono);padding:5px 8px;width:100%;box-sizing:border-box;">
            <div class="entity-pick-dropdown" style="display:none;"></div>
          </div>
        </div>
        <div>
          <label style="font-size:11px;color:var(--text-muted);">Anrede</label>
          <input class="form-input" value="${esc(m.title || '')}"
            data-member-idx="${i}" data-member-field="title"
            placeholder="z.B. Sir, Ma'am..."
            style="font-size:12px;padding:5px 8px;">
        </div>
      </div>
    </div>`;
  });

  const primaryEntity = getPath(S, 'household.primary_user_entity') || '';
  return sectionWrap('&#128100;', 'Hauptbenutzer',
    fInfo('Dein Name — so kennt und begruesst dich der Assistent.') +
    '<div class="form-group"><label>Dein Name</label>' +
    '<input type="text" data-path="household.primary_user" value="' + esc(primaryUser) + '" placeholder="z.B. Alex" style="font-size:15px;">' +
    '</div>' +
    '<div class="form-group"><label>HA Person-Entity</label>' +
    '<div class="entity-pick-wrap">' +
    '<input class="form-input entity-pick-input" value="' + esc(primaryEntity) + '"' +
    ' placeholder="&#128269; person.* zuweisen..." data-path="household.primary_user_entity"' +
    ' data-room-map="household.primary_user_entity"' +
    ' oninput="entityPickFilter(this,\'person\')" onfocus="entityPickFilter(this,\'person\')"' +
    ' style="font-family:var(--mono);font-size:13px;">' +
    '<div class="entity-pick-dropdown" style="display:none;"></div></div></div>'
  ) +
  sectionWrap('&#128106;', 'Haushaltsmitglieder',
    fInfo('Alle Personen im Haushalt. Die Rolle bestimmt was jeder steuern darf.') +
    '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px;">' +
    '<div style="padding:8px 12px;background:var(--accent-dim);border-radius:6px;font-size:11px;text-align:center;"><b>&#128081; Hausherr/in</b><br>Voller Zugriff</div>' +
    '<div style="padding:8px 12px;background:var(--blue-dim);border-radius:6px;font-size:11px;text-align:center;"><b>&#128100; Mitbewohner/in</b><br>Alles ausser Sicherheit</div>' +
    '<div style="padding:8px 12px;background:rgba(255,255,255,0.05);border-radius:6px;font-size:11px;text-align:center;"><b>&#128587; Gast</b><br>Nur Licht, Klima, Medien</div>' +
    '</div>' +
    '<div id="householdMembers">' + memberRows + '</div>' +
    '<button class="btn btn-secondary" onclick="addHouseholdMember()" style="margin-top:8px;width:100%;justify-content:center;">+ Person hinzufügen</button>'
  ) +
  sectionWrap('&#128101;', 'Personen-Anrede',
    fInfo('Anreden können direkt bei jedem Haushaltsmitglied oben vergeben werden. Hier kannst du sie alternativ zentral verwalten.') +
    fPersonTitles()
  );
}

function addHouseholdMember() {
  mergeCurrentTabIntoS();
  const members = getPath(S, 'household.members') || [];
  members.push({name: '', role: 'member', ha_entity: '', title: ''});
  setPath(S, 'household.members', members);
  renderCurrentTab();
  scheduleAutoSave();
}

function removeHouseholdMember(idx) {
  mergeCurrentTabIntoS();
  const members = getPath(S, 'household.members') || [];
  members.splice(idx, 1);
  setPath(S, 'household.members', members);
  renderCurrentTab();
  scheduleAutoSave();
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
    const haEntityEl = row.querySelector('[data-member-field="ha_entity"]');
    const titleEl = row.querySelector('[data-member-field="title"]');
    if (nameEl && roleEl && nameEl.value.trim()) {
      const m = {name: nameEl.value.trim(), role: roleEl.value};
      if (haEntityEl && haEntityEl.value.trim()) m.ha_entity = haEntityEl.value.trim();
      if (titleEl && titleEl.value.trim()) m.title = titleEl.value.trim();
      members.push(m);
    }
  });
  return members;
}

// ---- Tab 2: Persönlichkeit ----
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
  return sectionWrap('&#129302;', 'Modell-Routing',
    fInfo('Welche KI-Modelle sollen für welche Aufgaben genutzt werden? Deaktivierte Modelle werden übersprungen — Fallback auf das nächstkleinere.') +
    fToggle('models.enabled.fast', 'Fast — Einfache Befehle (Licht an, Timer, etc.)') +
    fToggle('models.enabled.smart', 'Smart — Konversation & Standardanfragen') +
    fToggle('models.enabled.deep', 'Deep — Komplexe Analyse & Planung') +
    fModelSelect('models.fast', 'Fast-Modell', 'Für schnelle, einfache Befehle') +
    fModelSelect('models.smart', 'Smart-Modell', 'Für normale Gespräche') +
    fModelSelect('models.deep', 'Deep-Modell', 'Für komplexe Aufgaben') +
    fRange('models.deep_min_words', 'Deep ab Wörtern', 5, 50, 1, {5:'5',10:'10',15:'15',20:'20',25:'25',30:'30',35:'35',40:'40',45:'45',50:'50'}) +
    fRange('models.options.temperature', 'Kreativitaet (Temperatur)', 0, 2, 0.1, {0:'Exakt',0.5:'Konservativ',0.7:'Standard',1:'Kreativ',1.5:'Sehr kreativ',2:'Maximum'}) +
    fRange('models.options.max_tokens', 'Antwortlänge (Max Tokens)', 64, 4096, 64) +
    fRange('ollama.num_ctx_fast', 'Kontext Fast-Modell', 1024, 65536, 1024, {1024:'1K',2048:'2K',4096:'4K',8192:'8K',16384:'16K',32768:'32K',65536:'64K'}) +
    fRange('ollama.num_ctx_smart', 'Kontext Smart-Modell', 2048, 131072, 1024, {2048:'2K',4096:'4K',8192:'8K',16384:'16K',32768:'32K',65536:'64K',131072:'128K'}) +
    fRange('ollama.num_ctx_deep', 'Kontext Deep-Modell', 2048, 131072, 1024, {2048:'2K',4096:'4K',8192:'8K',16384:'16K',32768:'32K',65536:'64K',131072:'128K'}) +
    fSubheading('GPU-Performance') +
    fSelect('ollama.keep_alive', 'Keep-Alive (Modell im VRAM halten)', [
      {v:'0',l:'Sofort entladen (spart Strom)'},
      {v:'120s',l:'2 Minuten'},
      {v:'5m',l:'5 Minuten (empfohlen)'},
      {v:'30m',l:'30 Minuten'},
      {v:'-1',l:'Nie entladen (schnellste Antworten)'}
    ]) +
    fToggle('ollama.flash_attn', 'Flash Attention (RTX 30xx+)') +
    fSelect('ollama.num_gpu', 'GPU-Layer', [
      {v:'',l:'Automatisch — Ollama entscheidet (empfohlen)'},
      {v:'99',l:'Maximum — Alles auf GPU'},
      {v:'35',l:'35 Layer (spart etwas VRAM)'},
      {v:'20',l:'20 Layer (GPU/CPU Mix)'},
      {v:'0',l:'Nur CPU (kein GPU)'}
    ])
  ) +
  _renderModelProfiles() +
  sectionWrap('&#9889;', 'Latenz-Optimierung',
    fInfo('Steuert wie aggressiv die Antwortzeit optimiert wird. Diese Einstellungen beeinflussen direkt wie schnell Jarvis antwortet — auf Kosten der Antwortqualitaet bei niedrigeren Werten.') +
    fToggle('latency_optimization.knowledge_fast_path', 'Wissensfragen Fast-Path') +
    fInfo('Bei reinen Wissensfragen ("Was ist die Hauptstadt von Frankreich?") wird der komplette Subsystem-Gather (Mood, Security, Sensoren etc.) übersprungen und direkt das LLM gefragt. Spart ~500-2000ms pro Wissensfrage. Deaktivieren wenn Wissensfragen auch Haus-Kontext beruecksichtigen sollen.') +
    fSelect('latency_optimization.think_control', 'Think-Modus Steuerung', [
      {v:'smart_off',l:'Smart aus — Thinking nur für Deep-Tier (empfohlen)'},
      {v:'auto',l:'Auto — Modell entscheidet selbst'},
      {v:'off',l:'Immer aus — Schnellste Antworten, weniger Qualitaet'},
      {v:'on',l:'Immer an — Beste Qualitaet, langsamere Antworten'}
    ]) +
    fInfo('Qwen3.5 hat einen internen "Denk-Modus" der 500-2000 extra Tokens generiert bevor die Antwort kommt (2-10s). "Smart aus" deaktiviert Thinking für normale Gespraeche (Smart-Tier) und laesst es für komplexe Aufgaben (Deep-Tier) aktiv — beste Balance aus Geschwindigkeit und Qualitaet. "Immer aus" spart maximal Zeit, kann aber bei komplexen Fragen schlechtere Antworten geben.') +
    fRange('latency_optimization.upgrade_signal_threshold', 'Deep-Upgrade Schwelle', 1, 10, 1, {1:'1 (oft Deep)',3:'3',5:'5 (Standard)',7:'7',10:'10 (selten Deep)'}) +
    fInfo('Bestimmt ab wie vielen Kontext-Signalen (Problemlösung, What-If, kritische Sicherheit) vom Smart-Modell (9B, schnell) auf das Deep-Modell (27B, langsam) gewechselt wird. Niedrig = oft Deep (3-20s langsamer, bessere Analyse). Hoch = selten Deep (schneller, reicht für die meisten Anfragen).') +
    fRange('latency_optimization.refinement_skip_max_chars', 'Refinement überspringen bis (Zeichen)', 0, 500, 10, {0:'Nie (immer Refinement)',80:'80',120:'120 (Standard)',200:'200',300:'300',500:'500 (fast immer skip)'}) +
    fInfo('Nach einem Tool-Call (z.B. Temperatur abfragen) wird normalerweise ein zweiter LLM-Call gemacht um die Rohdaten in Jarvis-Stil umzuformulieren. Bei kurzen Antworten ist das unnötig — der Humanizer-Text reicht. Höhere Werte = mehr Antworten ohne Refinement = schneller, aber weniger Persönlichkeit.') +
    fRange('latency_optimization.tools_cache_ttl', 'Tool-Cache Dauer (Sekunden)', 0, 300, 10, {0:'Aus (kein Cache)',30:'30s',60:'60s (Standard)',120:'2 Min',300:'5 Min'}) +
    fInfo('Die Tool-Definitionen (welche Geräte verfügbar sind, Parameter etc.) werden bei jedem Request neu gebaut. Mit Cache werden sie wiederverwendet. 60s ist sicher weil der Entity-Katalog alle 5 Minuten aktualisiert wird. 0 = kein Cache (langsamer aber immer aktuell).') +
    fSelect('latency_optimization.conv_summary_mode', 'Gespräche kuerzen', [
      {v:'truncate',l:'Text-Kürzung — Schnell, kein LLM-Call (empfohlen)'},
      {v:'llm',l:'LLM-Zusammenfassung — Besser, aber 500-2000ms langsamer'}
    ]) +
    fInfo('Wenn der Gesprächsverlauf zu lang wird, müssen ältere Nachrichten gekürzt werden. "Text-Kürzung" schneidet ältere Nachrichten auf 80 Zeichen ab — sofort und ohne extra LLM-Call. "LLM-Zusammenfassung" generiert eine intelligente Zusammenfassung, braucht aber einen zusätzlichen LLM-Call (500-2000ms).') +
    fSubheading('Response Cache') +
    fToggle('response_cache.enabled', 'Antwort-Cache aktiviert') +
    fInfo('Cached LLM-Antworten für wiederkehrende Status-Abfragen (z.B. "Wie warm ist es?"). Wenn die gleiche Frage innerhalb des TTL-Fensters erneut gestellt wird, kommt die Antwort sofort aus dem Cache statt über das LLM. Spart 2-8 Sekunden. Nur Status-Abfragen werden gecacht — Befehle wie "Licht an" niemals.') +
    fRange('response_cache.ttl.device_query', 'Cache-Dauer Status-Abfragen (Sekunden)', 0, 120, 5, {0:'Aus',15:'15s',30:'30s',45:'45s (Standard)',60:'1 Min',120:'2 Min'}) +
    fInfo('Wie lange gecachte Status-Antworten gueltig bleiben. Kurz = aktuellere Daten, mehr LLM-Calls. Lang = schnellere Antworten, aber Werte koennen veraltet sein. 45s ist ein guter Kompromiss — Temperaturen ändern sich nicht in 45 Sekunden.') +
    fToggle('response_cache.predictive_preload.enabled', 'Predictive Preload aktiv') +
    fInfo('Laedt Kontext-Daten fuer vorhergesagte Anfragen vorab in den Cache. Basiert auf der AnticipationEngine — wenn Jarvis weiss, dass du um 7 Uhr nach dem Wetter fragst, bereitet er die Antwort schon vor.') +
    fRange('response_cache.predictive_preload.lookahead_hours', 'Vorausschau-Fenster (Stunden)', 1, 6, 1, {1:'1h',2:'2h (Standard)',3:'3h',4:'4h',6:'6h'}) +
    fRange('response_cache.predictive_preload.preload_ttl_seconds', 'Preload-TTL (Sekunden)', 60, 900, 60, {60:'1 Min',300:'5 Min (Standard)',600:'10 Min',900:'15 Min'}) +
    fNum('response_cache.predictive_preload.max_predictions', 'Max. Vorhersagen pro Durchlauf', 1, 15) +
    fSubheading('Inkrementeller LLM-Start') +
    fToggle('incremental_llm.enabled', 'Fast-Gather für einfache Befehle') +
    fInfo('Bei einfachen Geraetebefehlen ("Licht an") und Status-Abfragen ("Wie warm?") wird der Kontext-Gather mit kurzerem Timeout ausgeführt. Subsysteme die nicht rechtzeitig antworten (Anticipation, Patterns, Insights) werden übersprungen — das LLM startet frueher. Spart 500-1500ms bei einfachen Anfragen.') +
    fRange('incremental_llm.fast_gather_timeout', 'Fast-Gather Timeout (Sekunden)', 1.0, 10.0, 0.5, {1.0:'1s (aggressiv)',2.0:'2s',3.0:'3s (Standard)',5.0:'5s',10.0:'10s (konservativ)'}) +
    fInfo('Maximale Wartezeit auf Kontext-Daten bei einfachen Befehlen. Niedrig = schnellere Antworten, aber weniger Kontext (Anticipation, gelernte Muster etc. fehlen möglicherweise). 3s reicht für Haus-Status und Raumprofil — die wichtigsten Daten für Geraetebefehle.')
  ) +
  sectionWrap('&#10024;', 'LLM Enhancer',
    fInfo('Macht Jarvis intelligenter durch gezielte LLM-Nutzung. Jedes Feature nutzt einen separaten LLM-Call — mehr Features = bessere Antworten, aber hoehere Latenz und GPU-Last. Einzeln deaktivierbar.') +
    fToggle('llm_enhancer.enabled', 'LLM Enhancer aktiviert') +
    fInfo('Hauptschalter: Deaktiviert alle vier Enhancer-Features auf einmal. Wenn aus, arbeitet Jarvis nur mit dem Basis-LLM-Call — schneller, aber weniger intelligent.') +
    fSubheading('Implizite Absichtserkennung') +
    fToggle('llm_enhancer.smart_intent.enabled', 'Smart Intent aktiviert') +
    fInfo('Erkennt versteckte Absichten hinter vagen Aussagen. Beispiel: "Mir ist kalt" erkennt Jarvis als Wunsch die Heizung hochzudrehen, statt nur "Das tut mir leid" zu antworten. Nutzt das Fast-Modell für minimale Latenz.') +
    fRange('llm_enhancer.smart_intent.min_confidence', 'Mindest-Konfidenz', 0.3, 0.95, 0.05, {0.3:'0.3 (oft)',0.5:'0.5',0.65:'0.65 (Standard)',0.8:'0.8',0.95:'0.95 (selten)'}) +
    fInfo('Ab welcher Konfidenz eine erkannte Absicht ausgeführt wird. Niedrig = Jarvis handelt oefter eigenstaendig, kann aber auch mal falsch liegen. Hoch = nur bei sehr eindeutigen Faellen.') +
    fSubheading('Gespraechs-Zusammenfassung') +
    fToggle('llm_enhancer.conversation_summary.enabled', 'Conversation Summary aktiviert') +
    fInfo('Generiert nach laengeren Gespraechen eine LLM-basierte Zusammenfassung statt einfacher Text-Kuerzung. Jarvis erinnert sich besser an den Gespraechskontext. Nutzt das Fast-Modell.') +
    fRange('llm_enhancer.conversation_summary.min_messages', 'Ab Nachrichten zusammenfassen', 2, 10, 1, {2:'2',4:'4 (Standard)',6:'6',8:'8',10:'10'}) +
    fInfo('Wie viele Nachrichten im Gespraech sein muessen bevor eine Zusammenfassung erstellt wird. Niedrig = fruehe Zusammenfassung (besseres Gedaechtnis, mehr LLM-Calls). Hoch = spaetere Zusammenfassung (weniger Calls).') +
    fSubheading('Proaktive Vorschlaege') +
    fToggle('llm_enhancer.proactive_suggestions.enabled', 'Proactive Suggestions aktiviert') +
    fInfo('Jarvis analysiert Nutzungsmuster und schlaegt von sich aus Verbesserungen vor — z.B. "Du schaltest jeden Abend um 22 Uhr das Licht aus. Soll ich eine Automation dafür erstellen?" Nutzt das Smart-Modell.') +
    fRange('llm_enhancer.proactive_suggestions.min_patterns', 'Mindest-Muster', 1, 5, 1, {1:'1 (Standard)',2:'2',3:'3',5:'5'}) +
    fInfo('Wie viele Wiederholungen eines Musters noetig sind bevor ein Vorschlag gemacht wird. Niedrig = schnellere Vorschlaege, kann aber bei Zufallsmustern nerven.') +
    fRange('llm_enhancer.proactive_suggestions.max_per_day', 'Max. Vorschlaege pro Tag', 1, 20, 1, {1:'1',3:'3',5:'5 (Standard)',10:'10',20:'20'}) +
    fInfo('Begrenzt wie oft Jarvis pro Tag mit Vorschlaegen kommt. Zu viele Vorschlaege koennen als aufdringlich empfunden werden.') +
    fSubheading('Antwort-Umformulierung') +
    fToggle('llm_enhancer.response_rewriter.enabled', 'Response Rewriter aktiviert') +
    fInfo('Formuliert kurze, technische Antworten in natürlicheren Jarvis-Stil um. Statt "Temperatur: 21.5°C" sagt Jarvis z.B. "Im Wohnzimmer sind es angenehme 21,5 Grad." Nutzt das Fast-Modell. Sehr kurze Antworten wie "Erledigt" werden übersprungen.') +
    fRange('llm_enhancer.response_rewriter.min_response_length', 'Min. Antwortlaenge (Zeichen)', 5, 50, 5, {5:'5',10:'10',15:'15 (Standard)',25:'25',50:'50'}) +
    fInfo('Antworten unter dieser Laenge werden nicht umformuliert. "Erledigt" (8 Zeichen) braucht kein Rewriting, aber "Temperatur Wohnzimmer: 21.5" (27 Zeichen) schon.') +
    fRange('llm_enhancer.response_rewriter.max_response_length', 'Max. Antwortlaenge (Zeichen)', 100, 1000, 50, {100:'100',250:'250',500:'500 (Standard)',750:'750',1000:'1000'}) +
    fInfo('Antworten über dieser Laenge werden nicht umformuliert — sie sind bereits ausführlich genug. Sehr lange Antworten wuerden beim Rewriting auch lange dauern.')
  ) +
  sectionWrap('&#129504;', 'Action Planner',
    fInfo('Der Action Planner führt komplexe Multi-Step Anfragen aus (z.B. "Mach alles fertig für morgen"). Er plant iterativ mit dem Deep-Modell und führt Tool-Calls parallel aus.') +
    fRange('planner.max_iterations', 'Max. Planungsschritte', 3, 15, 1, {3:'3',5:'5',8:'8',10:'10',15:'15'}) +
    fRange('planner.max_tokens', 'Max. Tokens pro Planungsschritt', 256, 2048, 128)
  ) +
  sectionWrap('&#127991;', 'Schnell-Erkennung',
    fInfo('Klicke auf Wörter, die das jeweilige Modell auslösen sollen. Ausgewählte Wörter sind hervorgehoben.') +
    fChipSelect('models.fast_keywords', 'Fast-Keywords — Wörter für schnelle Antworten', [
      'licht','lampe','an','aus','timer','stopp','danke','ja','nein','ok','stop',
      'wecker','alarm','pause','weiter','leiser','lauter','heller','dunkler',
      'rolladen','hoch','runter','temperatur','heizung','musik'
    ]) +
    fChipSelect('models.deep_keywords', 'Deep-Keywords — Wörter für ausführliche Analyse', [
      'warum','erklaere','vergleiche','analysiere','plane','zusammenfassung',
      'recherchiere','berechne','strategie','vor- und nachteile','unterschied',
      'optimiere','hilf mir bei','was meinst du','überblick'
    ]) +
    fChipSelect('models.cooking_keywords', 'Koch-Keywords — Wörter die den Koch-Modus aktivieren', [
      'rezept','kochen','backen','zubereiten','gericht','essen','zutaten',
      'portion','mahlzeit','frühstueck','mittagessen','abendessen','snack',
      'dessert','kuchen','suppe','salat','pizza','pasta','sauce'
    ])
  ) +
  sectionWrap('&#127917;', 'Stil & Charakter',
    fInfo('Wie soll sich der Assistent verhalten? Stil, Humor und Meinungsfreude einstellen.') +
    fSelect('personality.style', 'Grundstil', styleOpts) +
    fRange('personality.sarcasm_level', 'Sarkasmus-Level', 1, 5, 1, {1:'Sachlich',2:'Gelegentl. trocken',3:'Standard Butler',4:'Häufig',5:'Vollgas Ironie'}) +
    fRange('personality.opinion_intensity', 'Meinungs-Intensität', 0, 3, 1, {0:'Still',1:'Selten',2:'Gelegentlich',3:'Redselig'}) +
    fToggle('personality.self_irony_enabled', 'Selbstironie aktiviert') +
    fRange('personality.self_irony_max_per_day', 'Max. Selbstironie pro Tag', 0, 20, 1) +
    fSubheading('Emotionaler Zerfall') +
    fInfo('Jarvis-Stimmungen klingen natuerlich ab statt abrupt zu wechseln. Ein stolzer Jarvis wird langsam wieder neutral.') +
    fToggle('inner_state.mood_decay_enabled', 'Mood-Decay aktiv') +
    fRange('inner_state.mood_decay_minutes', 'Zerfallszeit (Minuten)', 10, 120, 10, {10:'10',20:'20',30:'30 (Standard)',60:'60',120:'120'}) +
    fToggle('inner_state.emotion_blending', 'Emotion-Blending (Mischung statt Einzelwert)') +
    fInfo('Jarvis kann mehrere Emotionen gleichzeitig empfinden — z.B. 60% stolz + 30% amuesiert.') +
    fToggle('inner_state.domain_weighted_mood', 'Domain-gewichtete Stimmung') +
    fInfo('Sicherheits-Events beeinflussen die Stimmung staerker als Routine-Aenderungen wie Lichtsteuerung.')
  ) +
  sectionWrap('&#128200;', 'Charakter-Entwicklung',
    fInfo('Der Assistent wird mit der Zeit weniger formell — wie ein echter Butler, der seinen Herrn kennenlernt.') +
    fToggle('personality.character_evolution', 'Charakter entwickelt sich über Zeit') +
    fRange('personality.formality_start', 'Formalität am Anfang', 0, 100, 5, {0:'Sehr locker',25:'Locker',50:'Normal',75:'Formell',100:'Sehr formell'}) +
    fRange('personality.formality_min', 'Minimale Formalität', 0, 100, 5, {0:'Sehr locker',25:'Locker',50:'Normal',75:'Formell',100:'Sehr formell'}) +
    fRange('personality.formality_decay_per_day', 'Abbau pro Tag', 0, 5, 0.1) +
    fToggle('personality.transition_comments', 'Uebergangs-Kommentare') +
    fInfo('Natuerliche Denkpausen und Uebergangsphrasen in Antworten ("Hm, wo war ich...", "Moment..."). Macht Jarvis menschlicher.') +
    fToggle('personality.trait_unlocks_enabled', 'Stage-basierte Trait-Unlocks') +
    fInfo('Neue Humor-Stile und Persoenlichkeits-Facetten werden erst nach einer Eingewoehnungsphase freigeschaltet.') +
    fNum('personality.trait_unlock_days_per_stage', 'Tage pro Stage', 7, 60, 7)
  ) +
  sectionWrap('&#128336;', 'Tageszeit-Stile',
    fInfo('Der Assistent passt seinen Stil je nach Tageszeit an. Waehle für jede Zeit einen passenden Stil und maximale Satzlaenge.') +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127749; Fruehmorgens (05:00 - 08:00)</div>' +
    fSelect('personality.time_layers.early_morning.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.early_morning.max_sentences', 'Max. Sätze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#9728; Morgens (08:00 - 12:00)</div>' +
    fSelect('personality.time_layers.morning.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.morning.max_sentences', 'Max. Sätze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127774; Nachmittags (12:00 - 18:00)</div>' +
    fSelect('personality.time_layers.afternoon.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.afternoon.max_sentences', 'Max. Sätze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127751; Abends (18:00 - 22:00)</div>' +
    fSelect('personality.time_layers.evening.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.evening.max_sentences', 'Max. Sätze', 1, 10, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#127769; Nachts (22:00 - 05:00)</div>' +
    fSelect('personality.time_layers.night.style', 'Stil', styleOpts) +
    fRange('personality.time_layers.night.max_sentences', 'Max. Sätze', 1, 10, 1) +
    '</div>'
  ) +
  sectionWrap('&#128566;', 'Stimmungs-Stile',
    fInfo('Wie Jarvis auf verschiedene User-Stimmungen reagiert. Stil-Anweisung wird dem System-Prompt hinzugefuegt, Satz-Modifier passt die maximale Antwortlänge an.') +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#128522; Gut gelaunt</div>' +
    fText('personality.mood_styles.good.style_addon', 'Stil-Anweisung') +
    fRange('personality.mood_styles.good.max_sentences_mod', 'Satz-Modifier', -3, 3, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#128528; Neutral</div>' +
    fText('personality.mood_styles.neutral.style_addon', 'Stil-Anweisung') +
    fRange('personality.mood_styles.neutral.max_sentences_mod', 'Satz-Modifier', -3, 3, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#128544; Gestresst</div>' +
    fText('personality.mood_styles.stressed.style_addon', 'Stil-Anweisung') +
    fRange('personality.mood_styles.stressed.max_sentences_mod', 'Satz-Modifier', -3, 3, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#128548; Frustriert</div>' +
    fText('personality.mood_styles.frustrated.style_addon', 'Stil-Anweisung') +
    fRange('personality.mood_styles.frustrated.max_sentences_mod', 'Satz-Modifier', -3, 3, 1) +
    '</div>' +
    '<div style="margin-bottom:12px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);">' +
    '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">&#128564; Muede</div>' +
    fText('personality.mood_styles.tired.style_addon', 'Stil-Anweisung') +
    fRange('personality.mood_styles.tired.max_sentences_mod', 'Satz-Modifier', -3, 3, 1) +
    '</div>'
  ) +
  sectionWrap('&#128514;', 'Humor-Templates',
    fInfo('Humor-Anweisungen pro Sarkasmus-Level. Diese Texte steuern wie witzig Jarvis sein darf (1=sachlich, 5=durchgehend trocken).') +
    fTextarea('personality.humor_templates.1', 'Level 1 — Sachlich') +
    fTextarea('personality.humor_templates.2', 'Level 2 — Gelegentlich') +
    fTextarea('personality.humor_templates.3', 'Level 3 — Butler') +
    fTextarea('personality.humor_templates.4', 'Level 4 — Sarkastisch') +
    fTextarea('personality.humor_templates.5', 'Level 5 — Durchgehend')
  ) +
  sectionWrap('&#128203;', 'Komplexitäts-Modi',
    fInfo('Text-Anweisungen pro Antwort-Modus. Der Modus wird automatisch anhand von Stimmung, Tageszeit und Befehls-Frequenz gewählt.') +
    fTextarea('personality.complexity_prompts.kurz', 'Kurz-Modus') +
    fTextarea('personality.complexity_prompts.normal', 'Normal-Modus') +
    fTextarea('personality.complexity_prompts.ausführlich', 'Ausführlich-Modus')
  ) +
  sectionWrap('&#127913;', 'Formalitäts-Stufen',
    fInfo('Ton-Anweisungen pro Formalitäts-Level. Der Score sinkt automatisch mit der Zeit (Charakter-Entwicklung).') +
    fTextarea('personality.formality_prompts.formal', 'Formal (Score >= 70)') +
    fTextarea('personality.formality_prompts.butler', 'Butler (Score >= 50)') +
    fTextarea('personality.formality_prompts.locker', 'Locker (Score >= 35)') +
    fTextarea('personality.formality_prompts.freund', 'Freund (Score < 35)')
  ) +
  sectionWrap('&#9989;', 'Bestätigungen',
    fInfo('Phrasen-Pools für Aktions-Bestätigungen. Eine Phrase pro Zeile. Platzhalter: {title} = Anrede-Titel.') +
    fTextarea('personality.confirmations.success', 'Erfolg') +
    fTextarea('personality.confirmations.success_snarky', 'Erfolg (sarkastisch, ab Level 4)') +
    fTextarea('personality.confirmations.partial', 'Teilweise erfolgreich') +
    fTextarea('personality.confirmations.failed', 'Fehlgeschlagen') +
    fTextarea('personality.confirmations.failed_snarky', 'Fehlgeschlagen (sarkastisch, ab Level 4)')
  ) +
  sectionWrap('&#128172;', 'Phrasen-Pools',
    fInfo('Einleitungs-Phrasen für Diagnosen und Warnungen. Eine Phrase pro Zeile.') +
    fTextarea('personality.diagnostic_openers', 'Diagnose-Einleitungen', 'z.B. "Mir ist aufgefallen, dass" — wird zufaellig gewählt.') +
    fTextarea('personality.casual_warnings', 'Beiläufige Warnungen', 'z.B. "Nur zur Kenntnis —" — Butler-Stil Understatement.')
  ) +
  sectionWrap('&#9888;', 'Fehler-Templates',
    fInfo('Fehlermeldungs-Templates pro Fehler-Kategorie. Platzhalter: {device} = Gerätename. Eine Phrase pro Zeile.') +
    fTextarea('personality.error_templates.unavailable', 'Geraet nicht erreichbar') +
    fTextarea('personality.error_templates.timeout', 'Zeitüberschreitung') +
    fTextarea('personality.error_templates.not_found', 'Geraet nicht gefunden') +
    fTextarea('personality.error_templates.unauthorized', 'Keine Berechtigung') +
    fTextarea('personality.error_templates.generic', 'Allgemeiner Fehler')
  ) +
  sectionWrap('&#128227;', 'Eskalations-Phrasen',
    fInfo('Formulierungen pro Warnstufe. Platzhalter: {title} = Anrede. Eine pro Zeile.') +
    fTextarea('personality.escalation_prefixes.1', 'Stufe 1 — Beiläufig (Info)') +
    fTextarea('personality.escalation_prefixes.2', 'Stufe 2 — Einwand') +
    fTextarea('personality.escalation_prefixes.3', 'Stufe 3 — Sorge') +
    fTextarea('personality.escalation_prefixes.4', 'Stufe 4 — Resignation')
  ) +
  sectionWrap('&#128520;', 'Sarkasmus-Feedback',
    fInfo('Erkennungsmuster für User-Feedback auf Sarkasmus. Wenn erkannt, wird Sarkasmus angepasst.') +
    fTextarea('personality.sarcasm_positive_patterns', 'Positives Feedback (mehr Sarkasmus)', 'z.B. "haha", "witzig", "nice"') +
    fTextarea('personality.sarcasm_negative_patterns', 'Negatives Feedback (weniger Sarkasmus)', 'z.B. "hoer auf", "nervt", "nicht witzig"')
  ) +
  sectionWrap('&#128683;', 'Antwort-Filter',
    fInfo('Unerwuenschte Phrasen aus den Antworten filtern und maximale Antwortlänge begrenzen.') +
    fToggle('response_filter.enabled', 'Antwort-Filter aktiv') +
    fRange('response_filter.max_response_sentences', 'Max. Sätze pro Antwort', 0, 20, 1, {0:'Kein Limit',1:'1',2:'2',3:'3',5:'5',10:'10',20:'20'}) +
    fRange('response_filter.auto_ban_threshold', 'Auto-Ban Schwelle', 0, 30, 1, {0:'Aus (nur manuell)',5:'5x',10:'10x (Standard)',15:'15x',20:'20x',30:'30x'}) +
    fChipSelect('response_filter.banned_phrases', 'Verbotene Phrasen', [
      'als KI','als Sprachmodell','ich bin ein KI','ich habe keine Gefuehle',
      'ich bin nur eine Maschine','als AI','language model','ich kann nicht fuehlen',
      'ich bin kein Mensch','mein Training','meine Trainingsdaten'
    ]) +
    fChipSelect('response_filter.banned_starters', 'Verbotene Satzanfaenge', [
      'Natürlich!','Selbstverstaendlich!','Klar!','Gerne!',
      'Absolut!','Definitiv!','Auf jeden Fall!','Sicher!',
      'Das ist eine gute Frage','Ich verstehe'
    ]) +
    fTextarea('response_filter.sorry_patterns', 'Entschuldigungs-Filter', 'Phrasen die aus Antworten entfernt werden. Eine pro Zeile.') +
    fTextarea('response_filter.refusal_patterns', 'Verweigerungs-Filter', 'Verweigerungs-Phrasen die entfernt werden. Eine pro Zeile.') +
    fTextarea('response_filter.chatbot_phrases', 'Chatbot-Floskeln-Filter', 'Typische Chatbot-Floskeln die entfernt werden. Eine pro Zeile.')
  );
}

// ---- Tab 3: Gedächtnis ----
function renderMemory() {
  return sectionWrap('&#128065;', 'Semantisches Gedächtnis',
    fInfo('Der Assistent merkt sich Fakten aus Gesprächen — z.B. "Du trinkst gern Kaffee". Hier steuerst du, wie das funktioniert.') +
    fToggle('memory.extraction_enabled', 'Fakten automatisch aus Gesprächen lernen') +
    fRange('memory.extraction_min_words', 'Min. Nachrichtenlänge für Extraktion', 1, 20, 1) +
    fModelSelect('memory.extraction_model', 'Modell für Fakten-Extraktion') +
    fRange('memory.extraction_temperature', 'Extraktions-Genauigkeit', 0, 1, 0.1, {0:'Sehr exakt',0.1:'Exakt',0.3:'Normal',0.5:'Flexibel',0.7:'Kreativ',1:'Sehr kreativ'}) +
    fRange('memory.extraction_max_tokens', 'Max. Antwortlänge Extraktion', 64, 2048, 64) +
    fRange('memory.max_person_facts_in_context', 'Personen-Fakten im Gespräch', 1, 20, 1) +
    fRange('memory.max_relevant_facts_in_context', 'Relevante Fakten im Gespräch', 1, 10, 1) +
    fRange('memory.min_confidence_for_context', 'Min. Sicherheit für Nutzung', 0, 1, 0.05, {0:'Alles nutzen',0.3:'Niedrig',0.5:'Mittel',0.6:'Standard',0.8:'Hoch',1:'Nur sichere'}) +
    fRange('memory.duplicate_threshold', 'Duplikat-Erkennung', 0, 1, 0.05, {0:'Streng',0.5:'Mittel',0.8:'Locker',1:'Aus'}) +
    fRange('memory.episode_min_words', 'Min. Wörter für Episode', 1, 20, 1) +
    fRange('memory.default_confidence', 'Standard-Sicherheit neuer Fakten', 0, 1, 0.05) +
    fSubheading('Kategorie-Sicherheit') +
    fInfo('Mindest-Konfidenz pro Fakten-Kategorie. Gesundheit/Sicherheit hoeher, Smalltalk niedriger.') +
    fRange('memory.category_confidence.health', 'Gesundheit', 0, 1, 0.05) +
    fRange('memory.category_confidence.person', 'Personen', 0, 1, 0.05) +
    fRange('memory.category_confidence.preference', 'Vorlieben', 0, 1, 0.05) +
    fRange('memory.category_confidence.habit', 'Gewohnheiten', 0, 1, 0.05) +
    fRange('memory.category_confidence.work', 'Arbeit', 0, 1, 0.05) +
    fRange('memory.category_confidence.intent', 'Absichten/Plaene', 0, 1, 0.05) +
    fRange('memory.category_confidence.general', 'Allgemein', 0, 1, 0.05) +
    fToggle('semantic_memory.fact_versioning', 'Fakt-Versionierung') +
    fInfo('Alte Fakten werden versioniert statt geloescht. Jarvis kann sagen: "Frueher mochtest du 20°C, seit 3 Monaten bevorzugst du 22°C."') +
    fToggle('semantic_memory.contradiction_query', 'Bei Widerspruechen nachfragen') +
    fInfo('Wenn ein neuer Fakt einem gespeicherten widerspricht, fragt Jarvis aktiv nach.')
  ) +
  sectionWrap('&#128218;', 'Wissensdatenbank (RAG)',
    fInfo('Eigene Dokumente als Wissensquelle. Dateien in config/knowledge/ werden automatisch eingelesen.') +
    fToggle('knowledge_base.enabled', 'Wissensdatenbank aktiv') +
    fToggle('knowledge_base.auto_ingest', 'Automatisch beim Start einlesen') +
    fRange('knowledge_base.chunk_size', 'Textblock-Groesse', 100, 2000, 50, {100:'Klein (100)',300:'Mittel (300)',500:'Standard (500)',1000:'Gross (1000)',2000:'Sehr gross (2000)'}) +
    fRange('knowledge_base.chunk_overlap', 'Überlappung zwischen Bloecken', 0, 500, 25) +
    fRange('knowledge_base.max_distance', 'Suchgenauigkeit', 0.5, 2, 0.1, {0.5:'Sehr genau',1:'Standard',1.5:'Breit',2:'Sehr breit'}) +
    fRange('knowledge_base.search_limit', 'Max. Treffer pro Suche', 1, 10, 1) +
    fSelect('knowledge_base.embedding_model', 'Embedding-Modell', [
      {v:'paraphrase-multilingual-MiniLM-L12-v2', l:'Multilingual MiniLM (empfohlen für Deutsch)'},
      {v:'all-MiniLM-L6-v2', l:'English MiniLM (ChromaDB Default)'},
      {v:'distiluse-base-multilingual-cased-v2', l:'Multilingual DistilUSE'},
      {v:'paraphrase-multilingual-mpnet-base-v2', l:'Multilingual MPNet (größer, genauer)'},
    ]) +
    fInfo('Nach Modellwechsel: Wissen-Seite → "Rebuild" klicken, damit alle Vektoren neu berechnet werden.') +
    fChipSelect('knowledge_base.supported_extensions', 'Unterstuetzte Dateitypen', [
      '.txt','.md','.pdf','.csv','.json','.yaml','.yml','.xml','.html','.log','.doc','.docx'
    ], 'Welche Dateitypen sollen eingelesen werden?')
  ) +
  sectionWrap('&#128221;', 'Korrektur-Lernen',
    fInfo('Wenn du den Assistenten korrigierst, merkt er sich das. Wie sicher soll er sich bei Korrekturen sein?') +
    fRange('correction.confidence', 'Sicherheit bei Korrekturen', 0, 1, 0.05, {0:'Unsicher',0.5:'Mittel',0.8:'Sicher',0.95:'Sehr sicher',1:'Absolut sicher'}) +
    fModelSelect('correction.model', 'Modell für Korrektur-Analyse') +
    fRange('correction.temperature', 'Analyse-Kreativitaet', 0, 1, 0.1, {0:'Exakt',0.3:'Normal',0.5:'Flexibel',1:'Kreativ'})
  ) +
  sectionWrap('&#128197;', 'Tages-Zusammenfassung',
    fInfo('Automatische Zusammenfassungen des Tages, der Woche und des Monats.') +
    fRange('summarizer.run_hour', 'Uhrzeit (Stunde)', 0, 23, 1) +
    fRange('summarizer.run_minute', 'Uhrzeit (Minute)', 0, 59, 1) +
    fModelSelect('summarizer.model', 'Zusammenfassungs-Modell') +
    fRange('summarizer.max_tokens_daily', 'Länge taeglich', 128, 2048, 64) +
    fRange('summarizer.max_tokens_weekly', 'Länge woechentlich', 128, 2048, 64) +
    fRange('summarizer.max_tokens_monthly', 'Länge monatlich', 128, 2048, 64)
  ) +
  sectionWrap('&#128172;', 'Kontext & Gesprächsmodus',
    fInfo('Wie viel Gesprächsverlauf Jarvis sich merkt. Im Gesprächsmodus (aktives Chatten) merkt er sich automatisch doppelt so viele Nachrichten und fasst ältere zusammen, damit der Kontext erhalten bleibt.') +
    fRange('context.recent_conversations', 'Gespräche merken (normal)', 1, 30, 1) +
    fRange('context.conversation_mode_timeout', 'Gesprächsmodus aktiv (Sek.)', 60, 900, 30, {60:'1 Min',120:'2 Min',180:'3 Min',300:'5 Min (Standard)',600:'10 Min',900:'15 Min'}) +
    fRange('context.api_timeout', 'HA-API Timeout (Sek.)', 1, 30, 1) +
    fRange('context.llm_timeout', 'LLM Timeout (Sek.)', 15, 120, 5, {15:'15s',30:'30s',45:'45s',60:'60s',90:'90s',120:'2 Min'}) +
    fSubheading('Kontext-Cache') +
    fInfo('Cached HA-States kurzzeitig um wiederholte API-Aufrufe zu vermeiden. Event-basierte Invalidierung sorgt fuer Aktualitaet.') +
    fRange('context.state_cache_ttl_seconds', 'Cache-Dauer (Sekunden)', 3, 30, 1, {3:'3s',5:'5s (Standard)',10:'10s',15:'15s',30:'30s'})
  ) +
  sectionWrap('&#127874;', 'Persönliche Daten',
    fInfo('Geburtstage, Jahrestage und andere wichtige Daten. Der Assistent erinnert proaktiv am Vorabend und integriert sie ins Morgen-Briefing. Du kannst Daten auch per Sprache hinzufügen: "Merk dir Lisas Geburtstag ist am 15. Maerz".') +
    '<div id="pdUpcoming" style="margin-bottom:16px;"></div>' +
    '<div id="pdList" style="margin-bottom:16px;"></div>' +
    fSubheading('Neues Datum hinzufügen') +
    '<div class="pd-form" style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;">' +
      '<div style="flex:1;min-width:140px;"><label style="font-size:11px;color:var(--text-muted);">Name</label>' +
        '<input type="text" id="pdName" class="form-input" placeholder="z.B. Lisa" style="font-size:13px;"></div>' +
      '<div style="min-width:120px;"><label style="font-size:11px;color:var(--text-muted);">Typ</label>' +
        '<select id="pdType" class="form-input" style="font-size:13px;">' +
          '<option value="birthday">Geburtstag</option><option value="anniversary">Jahrestag</option><option value="memorial">Gedenktag</option></select></div>' +
      '<div style="min-width:80px;"><label style="font-size:11px;color:var(--text-muted);">Tag</label>' +
        '<input type="number" id="pdDay" class="form-input" min="1" max="31" placeholder="15" style="font-size:13px;"></div>' +
      '<div style="min-width:80px;"><label style="font-size:11px;color:var(--text-muted);">Monat</label>' +
        '<input type="number" id="pdMonth" class="form-input" min="1" max="12" placeholder="3" style="font-size:13px;"></div>' +
      '<div style="min-width:80px;"><label style="font-size:11px;color:var(--text-muted);">Jahr (opt.)</label>' +
        '<input type="number" id="pdYear" class="form-input" min="1900" max="2099" placeholder="1992" style="font-size:13px;"></div>' +
      '<div style="flex:1;min-width:120px;"><label style="font-size:11px;color:var(--text-muted);">Label (opt.)</label>' +
        '<input type="text" id="pdLabel" class="form-input" placeholder="z.B. Hochzeitstag" style="font-size:13px;"></div>' +
      '<button class="btn" onclick="addPersonalDate()" style="height:36px;white-space:nowrap;">&#10010; Hinzufuegen</button>' +
    '</div>'
  ) +
  sectionWrap('&#128148;', 'Emotionales Gedächtnis',
    fInfo('Jarvis merkt sich emotionale Reaktionen auf Aktionen. Wenn du 2x negativ auf etwas reagiert hast (z.B. "Lass das!"), fragt Jarvis beim nächsten Mal vorher nach.') +
    fToggle('emotional_memory.enabled', 'Emotionales Gedächtnis aktiv') +
    fRange('emotional_memory.negative_threshold', 'Warnung ab negativen Reaktionen', 1, 5, 1, {1:'1x',2:'2x',3:'3x',4:'4x',5:'5x'}) +
    fRange('emotional_memory.decay_days', 'Erinnerung verfällt nach', 30, 365, 30, {30:'1 Monat',60:'2 Monate',90:'3 Monate',180:'6 Monate',365:'1 Jahr'})
  ) +
  sectionWrap('&#128202;', 'Lern-Transparenz',
    fInfo('"Was hast du beobachtet?" — Jarvis berichtet über erkannte Muster. Optional auch als woechentlicher automatischer Bericht.') +
    fToggle('learning.weekly_report.enabled', 'Woechentlicher Lern-Bericht') +
    fSelect('learning.weekly_report.day', 'Bericht-Tag', [
      {v:0,l:'Montag'},{v:1,l:'Dienstag'},{v:2,l:'Mittwoch'},{v:3,l:'Donnerstag'},
      {v:4,l:'Freitag'},{v:5,l:'Samstag'},{v:6,l:'Sonntag'}
    ]) +
    fNum('learning.weekly_report.hour', 'Bericht-Uhrzeit', 0, 23, 1, 'Stunde (0-23)')
  ) +
  sectionWrap('&#128203;', 'Absicht-Erkennung',
    fInfo('Erkennt offene Absichten — z.B. "Ich muss noch einkaufen" wird als Aufgabe gemerkt und später erinnert.') +
    fToggle('intent_tracking.enabled', 'Absicht-Erkennung aktiv') +
    fRange('intent_tracking.check_interval_minutes', 'Prüf-Intervall', 10, 240, 10, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std',240:'4 Std'}) +
    fRange('intent_tracking.remind_hours_before', 'Erinnerung vorher', 1, 48, 1, {1:'1 Std',2:'2 Std',4:'4 Std',12:'12 Std',24:'1 Tag',48:'2 Tage'})
  ) +
  sectionWrap('&#128173;', 'Gesprächs-Fortführung',
    fInfo('Wenn ein Gespräch unterbrochen wird — soll der Assistent später nachfragen? "Wolltest du vorhin noch was wegen...?"') +
    fToggle('conversation_continuity.enabled', 'Gespräch fortsetzen') +
    fRange('conversation_continuity.resume_after_minutes', 'Nachfragen nach', 1, 60, 1, {1:'1 Min',5:'5 Min',10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fRange('conversation_continuity.expire_hours', 'Thema vergessen nach', 1, 72, 1, {1:'1 Std',6:'6 Std',12:'12 Std',24:'1 Tag',48:'2 Tage',72:'3 Tage'})
  );
}

// ---- Personal Dates: Laden / Hinzufuegen / Loeschen ----
const _pdMonths = ['','Januar','Februar','Maerz','April','Mai','Juni','Juli','August','September','Oktober','November','Dezember'];

async function loadPersonalDates() {
  try {
    const d = await api('/api/ui/personal-dates');
    const dates = d.dates || [];
    const upcoming = d.upcoming || [];

    // Anstehende Daten
    const upEl = document.getElementById('pdUpcoming');
    if (upEl) {
      if (upcoming.length > 0) {
        upEl.innerHTML = '<div style="font-weight:600;font-size:13px;margin-bottom:8px;color:var(--accent);">Naechste Termine</div>' +
          upcoming.map(u => {
            const name = u.person ? u.person.charAt(0).toUpperCase() + u.person.slice(1) : '?';
            const label = u.label || 'Geburtstag';
            const days = u.days_until;
            const anni = u.anniversary_years;
            let timeStr = days === 0 ? '<b style="color:var(--accent);">heute</b>' : days === 1 ? '<b>morgen</b>' : `in ${days} Tagen`;
            let extra = '';
            if (u.date_type === 'birthday' && anni) extra = ` (wird ${anni})`;
            else if (anni) extra = ` (${anni}.)`;
            return `<div style="padding:6px 12px;border-left:3px solid var(--accent);margin-bottom:4px;background:var(--bg-secondary);border-radius:0 6px 6px 0;">` +
              `<span style="font-weight:600;">${esc(name)}</span> — ${esc(label)} ${timeStr}${extra}</div>`;
          }).join('');
      } else {
        upEl.innerHTML = '';
      }
    }

    // Alle Daten
    const listEl = document.getElementById('pdList');
    if (listEl) {
      if (dates.length === 0) {
        listEl.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine persönlichen Daten hinterlegt</div>';
      } else {
        listEl.innerHTML = '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">Alle gespeicherten Daten (' + dates.length + ')</div>' +
          dates.map(d => {
            const name = d.person ? d.person.charAt(0).toUpperCase() + d.person.slice(1) : '?';
            const mm = parseInt(d.date_mm_dd?.substring(0,2)||'0');
            const dd = parseInt(d.date_mm_dd?.substring(3,5)||'0');
            const mName = _pdMonths[mm] || mm;
            const dateStr = `${dd}. ${mName}`;
            const label = d.label || (d.date_type==='birthday'?'Geburtstag':d.date_type);
            const yearStr = d.year ? ` (${d.year})` : '';
            return `<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);">` +
              `<span style="flex:1;"><b>${esc(name)}</b> — ${esc(label)} am ${dateStr}${yearStr}</span>` +
              `<button class="btn btn-danger" onclick="deletePersonalDate('${esc(d.fact_id)}')" style="font-size:11px;padding:3px 10px;">Loeschen</button></div>`;
          }).join('');
      }
    }
  } catch(e) { console.error('Personal dates load fail:', e); }
}

async function addPersonalDate() {
  const name = (document.getElementById('pdName')?.value || '').trim();
  const type = document.getElementById('pdType')?.value || 'birthday';
  const day = parseInt(document.getElementById('pdDay')?.value || '0');
  const month = parseInt(document.getElementById('pdMonth')?.value || '0');
  const year = (document.getElementById('pdYear')?.value || '').trim();
  const label = (document.getElementById('pdLabel')?.value || '').trim();

  if (!name) { toast('Name fehlt', 'error'); return; }
  if (!day || !month || day < 1 || day > 31 || month < 1 || month > 12) { toast('Gueltiges Datum eingeben', 'error'); return; }

  const mm_dd = String(month).padStart(2,'0') + '-' + String(day).padStart(2,'0');
  try {
    const d = await api('/api/ui/personal-dates', 'POST', { person_name: name, date_type: type, date_mm_dd: mm_dd, year: year, label: label });
    if (d.success) {
      toast(d.message || 'Gespeichert');
      // Felder leeren
      document.getElementById('pdName').value = '';
      document.getElementById('pdDay').value = '';
      document.getElementById('pdMonth').value = '';
      document.getElementById('pdYear').value = '';
      document.getElementById('pdLabel').value = '';
      loadPersonalDates();
    } else {
      toast(d.message || 'Fehler', 'error');
    }
  } catch(e) { toast('Fehler beim Speichern', 'error'); }
}

async function deletePersonalDate(factId) {
  if (!confirm('Dieses Datum wirklich loeschen?')) return;
  try {
    const d = await api('/api/ui/personal-dates/' + factId, 'DELETE');
    if (d.success) {
      toast('Geloescht');
      loadPersonalDates();
    } else {
      toast(d.message || 'Fehler', 'error');
    }
  } catch(e) { toast('Fehler beim Loeschen', 'error'); }
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
    fRange('mood.negative_stress_boost', 'Negative Worte erhöhen Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.impatient_stress_boost', 'Ungeduld erhoeht Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.tired_boost', 'Müdigkeit erhoeht Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'}) +
    fRange('mood.repetition_stress_boost', 'Wiederholungen erhöhen Stress', 0, 0.5, 0.05, {0:'Kein Einfluss',0.1:'Schwach',0.25:'Mittel',0.5:'Stark'})
  ) +
  sectionWrap('&#128172;', 'Stimmungs-Erkennung — Wörter',
    fInfo('Klicke auf Wörter, die der Assistent als Stimmungssignal erkennen soll.') +
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
    fChipSelect('mood.tired_keywords', 'Müdigkeit', [
      'muede','schlafen','gute nacht','schlaf','bett','gaehnen',
      'erschoepft','fertig','kaputt','ausgelaugt','matt',
      'pennen','heia','einschlafen','nachts'
    ])
  ) +
  sectionWrap('&#127919;', 'Stimmung x Komplexität — Antwortlänge',
    fInfo('MCU-JARVIS passt seine Antwortlänge an deine Stimmung UND die Komplexität der Frage an. Bei Stress: ultra-kurz. Bei guter Laune und komplexer Frage: ausführlich. Werte = maximale Sätze.') +
    fToggle('mood_complexity.enabled', 'Mood x Complexity Matrix aktiv') +
    fSubheading('Gute Laune') +
    fRange('mood_complexity.matrix.good.simple', 'Einfacher Befehl', 1, 5, 1, {1:'1',2:'2',3:'3',4:'4',5:'5'}) +
    fRange('mood_complexity.matrix.good.medium', 'Mittlere Frage', 1, 6, 1, {1:'1',2:'2',3:'3',4:'4',5:'5',6:'6'}) +
    fRange('mood_complexity.matrix.good.complex', 'Komplexe Analyse', 1, 8, 1, {1:'1',2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8'}) +
    fSubheading('Neutral') +
    fRange('mood_complexity.matrix.neutral.simple', 'Einfacher Befehl', 1, 5, 1, {1:'1',2:'2',3:'3',4:'4',5:'5'}) +
    fRange('mood_complexity.matrix.neutral.medium', 'Mittlere Frage', 1, 6, 1, {1:'1',2:'2',3:'3',4:'4',5:'5',6:'6'}) +
    fRange('mood_complexity.matrix.neutral.complex', 'Komplexe Analyse', 1, 8, 1, {1:'1',2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8'}) +
    fSubheading('Gestresst / Frustriert / Muede') +
    fRange('mood_complexity.matrix.stressed.simple', 'Einfacher Befehl', 1, 5, 1, {1:'1',2:'2',3:'3',4:'4',5:'5'}) +
    fRange('mood_complexity.matrix.stressed.medium', 'Mittlere Frage', 1, 6, 1, {1:'1',2:'2',3:'3',4:'4',5:'5',6:'6'}) +
    fRange('mood_complexity.matrix.stressed.complex', 'Komplexe Analyse', 1, 8, 1, {1:'1',2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8'})
  ) +
  sectionWrap('&#127908;', 'Stimm-Analyse',
    fInfo('Der Assistent erkennt anhand deiner Sprechgeschwindigkeit ob du gestresst, muede oder entspannt bist.') +
    fToggle('voice_analysis.enabled', 'Stimm-Analyse aktiv') +
    fRange('voice_analysis.wpm_fast', 'Schnelles Sprechen ab (WPM)', 100, 300, 10, {100:'100',150:'150',180:'180',200:'200',250:'250',300:'300'}) +
    fRange('voice_analysis.wpm_slow', 'Langsames Sprechen unter (WPM)', 30, 150, 10, {30:'30',60:'60',80:'80',100:'100',120:'120',150:'150'}) +
    fRange('voice_analysis.wpm_normal', 'Normales Sprechtempo (WPM)', 50, 200, 10, {50:'50',80:'80',100:'100',120:'120',150:'150',200:'200'}) +
    fToggle('voice_analysis.use_whisper_metadata', 'Whisper-Metadaten nutzen') +
    fRange('voice_analysis.voice_weight', 'Stimm-Gewichtung', 0, 1, 0.05, {0:'Ignorieren',0.25:'Schwach',0.5:'Mittel',0.75:'Stark',1:'Voll'})
  ) +
  sectionWrap('&#127908;', 'Voice-Mood Integration',
    fInfo('Verknüpft die erkannte Stimm-Emotion (fröhlich, traurig, ärgerlich, nervös, müde) direkt mit der Stimmungserkennung. So reagiert Jarvis nicht nur auf Worte, sondern auch auf den Tonfall.') +
    fToggle('mood.voice_mood_integration', 'Voice-Emotion in Stimmung einbeziehen') +
    fToggle('mood.llm_sentiment', 'LLM-Sentiment (Text-Stimmungsanalyse per KI)')
  ) +
  sectionWrap('&#128566;', 'Stimmungs-Reaktion',
    fSubheading('Stimmungs-Reaktion') +
    fInfo('Jarvis passt seinen Kommunikationsstil an die erkannte Stimmung an. Bei Frustration: weniger Sarkasmus, klarere Sprache. Bei guter Laune: mehr Humor.') +
    fToggle('mood_reaction.enabled', 'Stimmungs-Reaktion aktiv') +
    fRange('mood_reaction.frustration_sarcasm_reduction', 'Sarkasmus-Reduktion bei Stress', 0, 3, 1, {0:'Keine',1:'-1 Level',2:'-2 Level (Standard)',3:'-3 Level'}) +
    fRange('mood_reaction.frustration_threshold', 'Frustrations-Schwelle', 1, 3, 1, {1:'Leicht',2:'Mittel (Standard)',3:'Stark'})
  );
}

// ---- Tab 5: Räume ----
// ════════════════════════════════════════════════════════════
// TAB: Sensoren (zentrale Sensor-Konfiguration)
// ════════════════════════════════════════════════════════════
function renderSensors() {
  return sectionWrap('&#128716;', 'Bettsensoren',
    fInfo('Konfiguriere Bettsensoren pro Raum (mehrere Betten pro Raum möglich). Alle Systeme greifen automatisch darauf zu:<br><br>' +
      '&#129695; <strong>Rollläden:</strong> Nicht öffnen wenn Bett belegt<br>' +
      '&#128161; <strong>Licht:</strong> Sleep-Mode und Wake-up Light<br>' +
      '&#127916; <strong>Aktivität:</strong> Schlaf-Erkennung<br>' +
      '&#127748; <strong>Routinen:</strong> Aufwach-Erkennung (z.B. Kaffee)<br><br>' +
      'Wähle den Raum und füge Betten hinzu. Jedes Bett kann einer Person zugeordnet werden.') +
    '<div id="centralBedSensorContainer" style="padding:8px;">Lade Räume...</div>'
  ) +
  sectionWrap('&#128225;', 'Weitere Sensoren',
    fInfo('Andere Sensor-Typen (Media Player, Mikrofone, PC) konfigurierst du pro Raum im <strong>Räume</strong>-Tab unter "Aktivitäts-Sensoren". Bettsensoren werden oben zentral konfiguriert.') +
    `<div class="info-box" style="margin-top:8px;cursor:pointer;" onclick="document.querySelector('[data-tab=tab-rooms]').click()">
      <span class="info-icon">&#127968;</span>Aktivitäts-Sensoren verwaltest du im <strong>Räume</strong>-Tab. Klicke hier.
    </div>`
  );
}

function renderRooms() {
  const hMode = getPath(S, 'heating.mode') || 'room_thermostat';
  const isCurve = hMode === 'heating_curve';

  return sectionWrap('&#128293;', 'Heizung',
    fInfo('Wie wird geheizt? Einzelraumregelung = jeder Raum hat eigenen Thermostat. Heizkurve = zentrale Wärmepumpe mit Offset-Steuerung.') +
    '<div class="form-group"><label>Heizungsmodus</label>' +
    '<select data-path="heating.mode" onchange="mergeCurrentTabIntoS();setPath(S,\'heating.mode\',this.value);renderCurrentTab();">' +
    '<option value="room_thermostat" ' + (hMode==='room_thermostat'?'selected':'') + '>Raumthermostate (Einzelraumregelung)</option>' +
    '<option value="heating_curve" ' + (hMode==='heating_curve'?'selected':'') + '>Heizkurve (Wärmepumpe, Vorlauf-Offset)</option>' +
    '</select></div>' +
    (isCurve ?
      fEntityPickerSingle('heating.curve_entity', 'Heizungs-Entity', ['climate'], 'z.B. climate.panasonic_heat_pump_main_z1_temp') +
      fRange('heating.curve_offset_min', 'Min. Offset (°C)', -10, 0, 0.5) +
      fRange('heating.curve_offset_max', 'Max. Offset (°C)', 0, 10, 0.5) +
      fRange('heating.night_offset', 'Nacht-Offset (°C)', -10, 0, 0.5) +
      fRange('heating.away_offset', 'Abwesenheits-Offset (°C)', -10, 0, 0.5)
    :
      fInfo('Jeder Raum hat seinen eigenen Thermostat. Temperatur-Grenzen findest du unter Sicherheit.')
    )
  ) +
  sectionWrap('&#127782;', 'Heizung: Wetter-Anpassung (sun.sun + weather)',
    fInfo('Passt die Heizung automatisch an Wetterbedingungen an:<br><br>&#10052; <strong>Vorhersage-Vorheizen:</strong> Kälteeinbruch vorhergesagt → Heizung vorab hochfahren<br>&#9728; <strong>Solar-Gain:</strong> Sonne scheint stark → Heizung reduzieren (passive Solarwärme)<br>&#128168; <strong>Wind-Kompensation:</strong> Starker Wind → mehr Wärmeverlust → leicht erhöhen') +
    fToggle('heating.weather_adjust.enabled', 'Wetter-Anpassung aktiv') +
    fRange('heating.weather_adjust.forecast_lookahead_hours', 'Vorhersage-Zeitraum (Std)', 1, 8, 1, {1:'1h',2:'2h',3:'3h',4:'4h',6:'6h',8:'8h'}) +
    fRange('heating.weather_adjust.preheat_drop_threshold', 'Vorheizen ab Temperaturabfall (°C)', 3, 10, 1, {3:'3°',5:'5°',7:'7°',10:'10°'}) +
    fRange('heating.weather_adjust.preheat_offset', 'Vorheiz-Offset (°C)', 0.5, 3, 0.5, {0.5:'0.5°',1:'1°',1.5:'1.5°',2:'2°',3:'3°'}) +
    fRange('heating.weather_adjust.solar_gain_reduction', 'Solar-Reduktion (°C)', 0, 2, 0.5, {0:'Aus',0.5:'0.5°',1:'1°',1.5:'1.5°',2:'2°'}) +
    fRange('heating.weather_adjust.wind_compensation_threshold', 'Wind-Kompensation ab (km/h)', 15, 60, 5, {15:'15',25:'25',30:'30',40:'40',50:'50',60:'60'}) +
    fRange('heating.weather_adjust.wind_offset', 'Wind-Offset (°C)', 0, 2, 0.5, {0:'Aus',0.5:'0.5°',1:'1°',1.5:'1.5°',2:'2°'})
  ) +
  sectionWrap('&#127777;', 'Raumtemperatur-Sensoren',
    fInfo('Welche Temperatursensoren sollen für die Raumtemperatur verwendet werden? Jarvis berechnet den Mittelwert aller Sensoren. Ohne Sensoren wird die Temperatur der Klimaanlage/Heizung genutzt.') +
    fEntityPicker('room_temperature.sensors', 'Temperatursensoren', ['sensor'], 'Nur sensor.*-Entities mit Temperaturwerten. z.B. sensor.temperatur_wohnzimmer') +
    '<div id="roomTempAverage" style="margin-top:8px;"></div>'
  ) +
  sectionWrap('&#128167;', 'Luftfeuchtigkeits-Sensoren',
    fInfo('Welche Sensoren sollen für die Luftfeuchtigkeits-Überwachung verwendet werden? Jarvis berechnet den Mittelwert aller Sensoren. Ohne Auswahl werden alle Feuchtigkeits-Sensoren geprüft.') +
    fEntityPicker('health_monitor.humidity_sensors', 'Feuchtigkeits-Sensoren', ['sensor'], 'Nur sensor.*-Entities mit Luftfeuchtigkeitswerten. z.B. sensor.luftfeuchtigkeit_wohnzimmer') +
    '<div id="roomHumidityAverage" style="margin-top:8px;"></div>'
  ) +
  sectionWrap('&#127968;', 'Multi-Room',
    fInfo('Der Assistent erkennt in welchem Raum du bist und antwortet dort. Praesenz-Timeout = wie lange er dich in einem Raum "merkt". Standard: Präsenz-Timeout 10 Min.') +
    fToggle('multi_room.enabled', 'Multi-Room Erkennung aktiv') +
    fRange('multi_room.presence_timeout_minutes', 'Praesenz-Timeout', 1, 60, 1, {1:'1 Min',5:'5 Min',10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fToggle('multi_room.auto_follow', 'Musik folgt automatisch in neuen Raum')
  ) +
  sectionWrap('&#128266;', 'Raum-Speaker',
    fInfo('Welcher Lautsprecher gehört zu welchem Raum? Räume werden automatisch aus MindHome erkannt.') +
    fRoomEntityMap('multi_room.room_speakers', 'Speaker-Zuordnung', ['media_player'])
  ) +
  sectionWrap('&#128694;', 'Raum-Bewegungsmelder',
    fInfo('Welcher Bewegungsmelder gehört zu welchem Raum? Damit weiss der Assistent wo du bist.') +
    fRoomEntityMap('multi_room.room_motion_sensors', 'Bewegungsmelder-Zuordnung', ['binary_sensor'])
  ) +
  sectionWrap('&#127916;', 'Aktivitäts-Sensoren',
    fInfo('Weitere Sensoren für die Aktivitätserkennung. <strong>Bettsensoren</strong> werden zentral im <strong>Sensoren</strong>-Tab konfiguriert.') +
    fEntityPicker('activity.entities.media_players', 'Media Player', ['media_player']) +
    fEntityPicker('activity.entities.mic_sensors', 'Mikrofon-Sensoren', ['binary_sensor','sensor']) +
    fEntityPicker('activity.entities.pc_sensors', 'PC-Sensoren (Arbeit-Erkennung)', ['binary_sensor','sensor']) +
    `<div class="info-box" style="margin-top:8px;cursor:pointer;" onclick="document.querySelector('[data-tab=tab-sensors]').click()">
      <span class="info-icon">&#128716;</span>Bettsensoren konfigurierst du zentral im <strong>Sensoren</strong>-Tab. Klicke hier.
    </div>`
  ) +
  sectionWrap('&#9200;', 'Aktivitäts-Zeiten',
    fInfo('Wann ist Nacht? Ab wann zählt Besuch? Wie lange muss Fokus dauern?') +
    fRange('activity.thresholds.night_start', 'Nacht beginnt um', 0, 23, 1) +
    fRange('activity.thresholds.night_end', 'Nacht endet um', 0, 23, 1) +
    fRange('activity.thresholds.guest_person_count', 'Besuch ab Personen', 1, 10, 1) +
    fRange('activity.thresholds.focus_min_minutes', 'Fokus-Modus ab Minuten', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'})
  ) +
  sectionWrap('&#128101;', 'Personen-Profile',
    fInfo('Pro Person individuell: Benachrichtigung, Raum, Humor-Level, Empathie-Stil, Antwortlänge und Formalität. Stimmung wird ebenfalls pro Person separat getrackt.') +
    fToggle('person_profiles.enabled', 'Persönlichkeits-Profile aktiv') +
    fPersonProfiles()
  ) +
  // ── Raum-Profile (room_profiles.yaml) ─────────────────────
  sectionWrap('&#128161;', 'Raum-Profile (Temperatur & Licht)',
    fInfo('Raum-Typ und Etage pro Raum. Diese Werte werden für Kontext-Empfehlungen genutzt.') +
    renderRoomProfileEditor()
  ) +
  // ── Saisonale Einstellungen (room_profiles.yaml) ─────────────
  sectionWrap('&#127808;', 'Saisonale Einstellungen',
    fInfo('Anpassungen je nach Jahreszeit. Temperatur-Offset wird auf die Raum-Defaults aufgerechnet. Briefing-Extras erscheinen im Morgen-Briefing.') +
    renderSeasonalEditor()
  );
}

// ---- Tab 6: Stimme ----
function renderVoice() {
  const soundOpts = [
    {v:'',l:'Kein Sound'},
    {v:'listening',l:'Zuhoeren-Ton'},
    {v:'confirmed',l:'Bestätigung'},
    {v:'warning',l:'Warnung'},
    {v:'alarm',l:'Alarm'},
    {v:'doorbell',l:'Tuerklingel'},
    {v:'greeting',l:'Begrüßung'},
    {v:'error',l:'Fehler'},
    {v:'goodnight',l:'Gute Nacht'},
    {v:'chime',l:'Glockenspiel'},
    {v:'notification',l:'Benachrichtigung'}
  ];
  return sectionWrap('&#127897;', 'Sprach-Engine (STT / TTS)',
    fInfo('Whisper-Modell und Piper-Stimme. Änderungen werden automatisch übernommen.') +
    fSubheading('Spracherkennung (Whisper STT)') +
    fInfo('Lokale Spracherkennung via Whisper. Standard: Modell small, Sprache de, Beam Size 5, Compute int8, Device CPU.') +
    fSelect('speech.stt_model', 'Whisper-Modell', [
      {v:'tiny',l:'Tiny — Schnellstes (schlechteste Qualitaet)'},
      {v:'base',l:'Base — Schnell'},
      {v:'small',l:'Small — Empfohlen für CPU'},
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
      {v:'int8',l:'int8 — Empfohlen für CPU'},
      {v:'float16',l:'float16 — Empfohlen für GPU'},
      {v:'float32',l:'float32 — Hoechste Praezision (langsam)'}
    ]) +
    fSelect('speech.stt_device', 'Hardware', [
      {v:'cpu',l:'CPU'},
      {v:'cuda',l:'GPU (CUDA)'}
    ]) +
    fSubheading('Sprachsynthese (Piper TTS)') +
    fInfo('Lokale Sprachsynthese via Piper. Standard: Stimme thorsten-high, Nacht-Flüstern aus.') +
    fSelect('speech.tts_voice', 'Piper-Stimme', [
      {v:'de_DE-thorsten-high',l:'Thorsten High — Beste Qualitaet (empfohlen)'},
      {v:'de_DE-thorsten-medium',l:'Thorsten Medium — Gute Qualitaet'},
      {v:'de_DE-thorsten-low',l:'Thorsten Low — Schnell, weniger natürlich'},
      {v:'de_DE-kerstin-low',l:'Kerstin — Weibliche Stimme'},
      {v:'en_US-lessac-high',l:'Lessac High — English (US)'},
      {v:'en_US-amy-medium',l:'Amy Medium — English (US)'},
      {v:'en_GB-alba-medium',l:'Alba Medium — English (UK)'}
    ]) +
    fToggle('speech.auto_night_whisper', 'Nachts automatisch flüstern')
  ) +
  sectionWrap('&#128266;', 'Sprachausgabe (TTS)',
    fInfo('Standard-Lautsprecher und TTS-Engine für Jarvis. Wenn leer, wird der erste Raum-Speaker verwendet.') +
    fEntityPickerSingle('sounds.default_speaker', 'Standard-Lautsprecher', ['media_player'], 'Welcher Lautsprecher soll Jarvis standardmaessig nutzen?') +
    fEntityPickerSingle('sounds.tts_entity', 'TTS-Engine', ['tts'], 'TTS-Service (z.B. tts.piper)') +
    fSubheading('Alexa / Echo Speaker') +
    fInfo('Alexa/Echo Geräte können keine Audio-Dateien von Piper TTS empfangen. Für diese Speaker wird stattdessen der Alexa-eigene TTS (notify.alexa_media) genutzt. Nur Geräte eintragen die über die Alexa Media Player Integration eingebunden sind.') +
    fEntityPicker('sounds.alexa_speakers', 'Alexa/Echo Speaker', ['media_player'], 'Diese Speaker erhalten TTS über den Alexa Notify-Service statt Audiodateien.') +
    fSubheading('Erweitert') +
    fInfo('Erweiterte TTS-Einstellungen: Sound-URL, Lautstaerke-Boost, SSML und Prosody. Standard: SSML aus, Prosody aus, Wetter-Boost 0.') +
    fText('sounds.sound_base_url', 'Sound-Basis-URL', 'Pfad zu den Sound-Dateien (z.B. /local/sounds)') +
    fRange('sounds.weather_volume_boost', 'Wetter-Lautstaerke-Boost', 0, 0.5, 0.05, {0:'Aus',0.1:'10%',0.15:'15%',0.2:'20%',0.3:'30%',0.5:'50%'}) +
    fToggle('tts.ssml_enabled', 'Fortgeschrittene Betonung (SSML)') +
    fToggle('tts.prosody_variation', 'Tonhoehe/Tempo variieren (Prosody)') +
    fInfo('Wenn aktiv, ändert Jarvis Tonhoehe und Geschwindigkeit je nach Nachrichtentyp (Warnung=tiefer, Frage=hoeher). Bei Deaktivierung bleibt der Ton konstant.') +
    fSubheading('Sprechgeschwindigkeit pro Situation') +
    fInfo('TTS-Geschwindigkeit je nach Kontext. Standard: 100% (Normal) für alle Situationen.') +
    fRange('tts.speed.confirmation', 'Bestätigung', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.warning', 'Warnung', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.briefing', 'Briefing', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.greeting', 'Begrüßung', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.question', 'Frage', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fRange('tts.speed.casual', 'Normal', 50, 200, 5, {50:'Langsam',100:'Normal',150:'Schnell',200:'Sehr schnell'}) +
    fSubheading('Sprechpausen') +
    fInfo('Pausen zwischen TTS-Segmenten für natürlicheren Sprachfluss. Standard: Alle Pausen 0 ms.') +
    fRange('tts.pauses.before_important', 'Vor wichtigen Infos (ms)', 0, 1000, 50) +
    fRange('tts.pauses.between_sentences', 'Zwischen Sätzen (ms)', 0, 1000, 50) +
    fRange('tts.pauses.after_greeting', 'Nach Begrüßung (ms)', 0, 1000, 50) +
    fSubheading('Flüstern') +
    fInfo('Trigger-Woerter für den Flüstern-Modus. Standard: Aktivierung bei "psst", "leise", "flüstern" etc.') +
    fChipSelect('tts.whisper_triggers', 'Flüstern aktivieren bei', [
      'psst','leise','flüstern','schlafen','baby',
      'ruhe','still','shh','nachts','nacht'
    ]) +
    fChipSelect('tts.whisper_cancel_triggers', 'Flüstern beenden bei', [
      'normal','laut','aufwachen','morgen','wach','genug geflüstert'
    ])
  ) +
  sectionWrap('&#128264;', 'Lautstärke',
    fInfo('Lautstärke je nach Tageszeit. 0 = stumm, 1 = volle Lautstärke.') +
    fRange('volume.day', '&#9728; Tag', 0, 1, 0.05) +
    fRange('volume.evening', '&#127751; Abend', 0, 1, 0.05) +
    fRange('volume.night', '&#127769; Nacht', 0, 1, 0.05) +
    fRange('volume.sleeping', '&#128164; Schlafen', 0, 1, 0.05) +
    fRange('volume.emergency', '&#128680; Notfall', 0, 1, 0.05) +
    fRange('volume.whisper', '&#129296; Flüstern', 0, 1, 0.05) +
    fSubheading('Tageszeit-Wechsel') +
    fRange('volume.morning_start', 'Morgen ab', 0, 23, 1) +
    fRange('volume.evening_start', 'Abend ab', 0, 23, 1) +
    fRange('volume.night_start', 'Nacht ab', 0, 23, 1)
  ) +
  sectionWrap('&#127925;', 'Sound-Effekte',
    fInfo('Kurze Toene bei bestimmten Ereignissen. Deaktiviere Sounds komplett oder waehle pro Ereignis.') +
    fToggle('sounds.enabled', 'Sound-Effekte aktiv') +
    fSelect('sounds.events.listening', 'Zuhoeren-Sound', soundOpts) +
    fSelect('sounds.events.confirmed', 'Bestätigung-Sound', soundOpts) +
    fSelect('sounds.events.warning', 'Warnung-Sound', soundOpts) +
    fSelect('sounds.events.alarm', 'Alarm-Sound', soundOpts) +
    fSelect('sounds.events.doorbell', 'Tuerklingel-Sound', soundOpts) +
    fSelect('sounds.events.greeting', 'Begrüßung-Sound', soundOpts) +
    fSelect('sounds.events.error', 'Fehler-Sound', soundOpts) +
    fSelect('sounds.events.goodnight', 'Gute-Nacht-Sound', soundOpts) +
    fRange('sounds.night_volume_factor', 'Nacht-Lautstärke-Faktor', 0, 1, 0.1, {0:'Stumm',0.3:'Leise',0.5:'Halb',0.7:'Etwas leiser',1:'Normal'})
  ) +
  sectionWrap('&#127916;', 'Szenen & Narration',
    fInfo('Szenen, Übergangszeiten und "Nicht stören"-Einstellungen werden zentral im Szenen-Tab verwaltet. Hier nur die globalen Narrations-Einstellungen.') +
    fToggle('narration.enabled', 'Szenen-Narration aktiv') +
    fRange('narration.default_transition', 'Standard-Übergang (Sek.)', 1, 20, 1, {1:'1s',2:'2s',3:'3s',5:'5s',7:'7s',10:'10s',15:'15s',20:'20s'}) +
    fRange('narration.step_delay', 'Verzögerung zwischen Schritten (Sek.)', 0, 10, 0.5) +
    fToggle('narration.narrate_actions', 'Aktionen ansagen ("Licht wird gedimmt...")') +
    `<div class="info-box" style="margin-top:8px;cursor:pointer;" onclick="document.querySelector('[data-tab=tab-scenes]').click()">
      <span class="info-icon">&#127916;</span>Einzelne Szenen-Übergänge konfigurierst du im <strong>Szenen</strong>-Tab. Klicke hier.
    </div>`
  ) +
  sectionWrap('&#128295;', 'STT-Korrekturen',
    fInfo('Spracherkennung macht Fehler — hier kannst du häufige Korrekturen definieren. Mehrwort-Korrekturen werden VOR Einzelwort angewendet.') +
    fKeyValue('stt_corrections.word_corrections', 'Einzelwort-Korrekturen',
      'Falsch erkannt', 'Korrektur',
      'z.B. "uber" → "über", "kuche" → "Küche"') +
    fKeyValue('stt_corrections.phrase_corrections', 'Mehrwort-Korrekturen',
      'Falsche Phrase', 'Korrektur',
      'z.B. "roll laden" → "Rollladen", "wohn zimmer" → "Wohnzimmer"')
  ) +
  sectionWrap('&#128100;', 'Sprecher-Erkennung',
    fInfo('Erkennt wer spricht über 7 Methoden: Geräte-Zuordnung, Richtung (DoA), Raum, Anwesenheit, Stimmabdruck, Voice-Features und Cache. Lernt automatisch dazu.') +
    fToggle('speaker_recognition.enabled', 'Sprecher-Erkennung aktiv') +
    fRange('speaker_recognition.min_confidence', 'Erkennungs-Sicherheit', 0, 1, 0.05, {0:'Jeder',0.3:'Niedrig',0.5:'Mittel',0.6:'Empfohlen',0.7:'Hoch',0.9:'Sehr hoch',1:'Perfekt'}) +
    fToggle('speaker_recognition.fallback_ask', 'Bei Unsicherheit nachfragen: "Wer spricht?"') +
    fRange('speaker_recognition.max_profiles', 'Max. Sprecher-Profile', 1, 50, 1) +
    fRange('speaker_recognition.enrollment_duration', 'Einlern-Dauer (Sek.)', 5, 120, 5, {5:'5s (kurz)',15:'15s',30:'30s (empfohlen)',60:'1 Min',120:'2 Min'}) +
    fKeyValue('speaker_recognition.device_mapping', 'Geräte → Person Zuordnung',
      'ESPHome Device-ID', 'Person (z.B. max)',
      'Welches Mikrofon-Gerät gehört wem? Device-ID findest du in HA → Einstellungen → Geräte → ESPHome.') +
    fTextarea('speaker_recognition.doa_mapping', 'Richtungs-Erkennung (DoA)',
      'JSON-Format. Beispiel: {"respeaker_küche":{"0-90":"max","270-360":"lisa"}}. Erfordert ReSpeaker XVF3800.') +
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
      {v:'ausführlich',l:'Ausführlich — Alle Details (Helligkeit, Soll-Temp, Medientitel)'}
    ]) +
    fChipSelect('house_status.sections', 'Angezeigte Bereiche', [
      {v:'presence',l:'Anwesenheit'},
      {v:'temperatures',l:'Temperaturen'},
      {v:'weather',l:'Wetter'},
      {v:'lights',l:'Lichter'},
      {v:'security',l:'Sicherheit'},
      {v:'media',l:'Medien'},
      {v:'open_items',l:'Offene Fenster/Türen'},
      {v:'offline',l:'Offline-Geräte'}
    ])
  ) +
  sectionWrap('&#127777;', 'Temperatur-Räume',
    fInfo('Optional: Nur bestimmte Räume im Status anzeigen. Leer = alle Räume. Raumnamen wie in Home Assistant (z.B. Wohnzimmer, Schlafzimmer).') +
    fTextarea('house_status.temperature_rooms', 'Räume (einer pro Zeile)', 'z.B.\nWohnzimmer\nSchlafzimmer\nGästezimmer')
  ) +
  sectionWrap('&#128296;', 'Health Monitor',
    fInfo('Welche Sensoren sollen überwacht werden? Nicht-Raum-Sensoren (Wärmepumpe, Prozessor etc.) werden automatisch gefiltert.') +
    fToggle('health_monitor.enabled', 'Health Monitor aktiv') +
    fNum('health_monitor.check_interval_minutes', 'Prüf-Intervall (Minuten)', 5, 60, 5) +
    fNum('health_monitor.alert_cooldown_minutes', 'Benachrichtigungs-Cooldown (Minuten)', 15, 240, 15) +
    fSubheading('Schwellwerte') +
    fNum('health_monitor.temp_low', 'Temperatur zu niedrig (°C)', 10, 20, 1) +
    fNum('health_monitor.temp_high', 'Temperatur zu hoch (°C)', 24, 35, 1) +
    fNum('health_monitor.humidity_low', 'Luftfeuchte zu niedrig (%)', 20, 40, 5) +
    fNum('health_monitor.humidity_high', 'Luftfeuchte zu hoch (%)', 60, 80, 5) +
    fNum('health_monitor.co2_warn', 'CO2 Warnung (ppm)', 800, 1500, 100) +
    fNum('health_monitor.co2_critical', 'CO2 Kritisch (ppm)', 1000, 2500, 100) +
    fTextarea('health_monitor.exclude_patterns', 'Zusätzliche Ausschluss-Patterns (einer pro Zeile)', 'z.B.\naquarea\ntablet_\nsteckdose_') +
    fSubheading('Trinkerinnerungen') +
    fRange('health_monitor.hydration_interval_hours', 'Trink-Intervall (Stunden)', 1, 4, 0.5, {1:'1 Std',1.5:'90 Min',2:'2 Std',3:'3 Std',4:'4 Std'}) +
    fRange('health_monitor.hydration_start_hour', 'Trink-Start (Uhr)', 6, 12, 1, {6:'6 Uhr',7:'7 Uhr',8:'8 Uhr',9:'9 Uhr',10:'10 Uhr'}) +
    fRange('health_monitor.hydration_end_hour', 'Trink-Ende (Uhr)', 18, 23, 1, {18:'18 Uhr',20:'20 Uhr',22:'22 Uhr',23:'23 Uhr'}) +
    fSubheading('Alert-Hysterese') +
    fInfo('Verhindert Alert-Flapping an Grenzwerten. Warnung bei Ueberschreitung, Entwarnung erst bei (Schwelle - Puffer). Verhindert "CO2 hoch/normal/hoch" alle 2 Minuten.') +
    fToggle('health_monitor.hysteresis_enabled', 'Hysterese aktiv') +
    fRange('health_monitor.hysteresis_pct', 'Puffer (%)', 1, 10, 1, {1:'1%',2:'2% (Standard)',3:'3%',5:'5%',10:'10%'}) +
    fSubheading('Raum-spezifische Schwellen') +
    fToggle('health_monitor.room_overrides_enabled', 'Raum-Overrides aktiv') +
    fInfo('Unterschiedliche Schwellen pro Raum. Z.B. hoehere CO2-Toleranz in der Kueche.') +
    fTextarea('health_monitor.room_overrides', 'Raum-Overrides (JSON)', 'Format: {"schlafzimmer": {"co2_warn": 800}, "kueche": {"co2_warn": 1200}}')
  ) +
  sectionWrap('&#129505;', 'Wellness-Advisor',
    fInfo('Ganzheitlicher Wellness-Check: Trinkerinnerungen, PC-Pausen, Mahlzeit-Erinnerungen und Spaetabend-Hinweise. Unabhaengig vom Health Monitor.') +
    fToggle('wellness.enabled', 'Wellness-Advisor aktiv') +
    fNum('wellness.check_interval_minutes', 'Prüf-Intervall (Min)', 15, 120, 15) +
    fRange('wellness.pc_break_reminder_minutes', 'PC-Pause nach', 30, 360, 30, {30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std',360:'6 Std'}) +
    fToggle('wellness.stress_check', 'Stress-Erkennung') +
    fToggle('wellness.meal_reminders', 'Mahlzeit-Erinnerungen') +
    fRange('wellness.meal_times.lunch', 'Mittagessen ab', 11, 15, 1, {11:'11 Uhr',12:'12 Uhr',13:'13 Uhr',14:'14 Uhr',15:'15 Uhr'}) +
    fRange('wellness.meal_times.dinner', 'Abendessen ab', 17, 21, 1, {17:'17 Uhr',18:'18 Uhr',19:'19 Uhr',20:'20 Uhr',21:'21 Uhr'}) +
    fToggle('wellness.late_night_nudge', 'Spaetabend-Hinweis ("Es ist schon spaet...")')
  ) +
  sectionWrap('&#127752;', 'Wetterwarnungen',
    fInfo('Schwellwerte für Wetterwarnungen die im Gespraech und bei proaktiven Meldungen beruecksichtigt werden.') +
    fToggle('weather_warnings.enabled', 'Wetterwarnungen aktiv') +
    fNum('weather_warnings.temp_high', 'Hitze-Warnung ab (°C)', 28, 45, 1) +
    fNum('weather_warnings.temp_low', 'Kaelte-Warnung ab (°C)', -20, 5, 1) +
    fNum('weather_warnings.wind_speed_high', 'Wind-Warnung ab (km/h)', 30, 100, 5)
  ) +
  sectionWrap('&#127793;', 'Humidor',
    fInfo('Dein Humidor braucht andere Feuchtigkeitswerte als normale Räume. Weise hier den Sensor zu und stelle die Schwellwerte ein. Der Sensor wird dann nicht mehr vom normalen Raumklima-Monitor erfasst.') +
    fToggle('humidor.enabled', 'Humidor-Überwachung aktiv') +
    '<div class="form-group"><label>Feuchtigkeits-Sensor</label>' +
    '<div class="entity-pick-wrap">' +
    '<input class="form-input entity-pick-input" value="' + esc(getPath(S,'humidor.sensor_entity')||'') + '"' +
    ' placeholder="&#128269; sensor.* zuweisen..." data-path="humidor.sensor_entity"' +
    ' data-room-map="humidor.sensor_entity"' +
    ' oninput="entityPickFilter(this,\'sensor\')" onfocus="entityPickFilter(this,\'sensor\')"' +
    ' style="font-family:var(--mono);font-size:13px;">' +
    '<div class="entity-pick-dropdown" style="display:none;"></div></div></div>' +
    fSubheading('Schwellwerte') +
    fNum('humidor.target_humidity', 'Ziel-Feuchtigkeit (%)', 50, 85, 1) +
    fNum('humidor.warn_below', 'Warnung unter (%)', 40, 80, 1) +
    fNum('humidor.warn_above', 'Warnung über (%)', 55, 90, 1)
  ) +
  '';
}

function renderRoutines() {
  const morningStyleOpts = [
    {v:'kompakt',l:'Kompakt — Kurzes Briefing'},
    {v:'ausführlich',l:'Ausführlich — Detailliertes Update'},
    {v:'freundlich',l:'Freundlich — Lockerer Start'},
    {v:'butler',l:'Butler — Formeller Morgengruss'},
    {v:'minimal',l:'Minimal — Nur das Wichtigste'},
    {v:'entspannt',l:'Entspannt — Gemuetlicher Start'}
  ];
  return sectionWrap('&#127748;', 'Morgen-Briefing',
    fInfo('Automatisches Update am Morgen — Wetter, Termine, Neuigkeiten. Wird ausgeloest wenn du morgens das erste Mal erkannt wirst.') +
    fToggle('routines.morning_briefing.enabled', 'Morgen-Briefing aktiv') +
    fSelect('routines.morning_briefing.trigger', 'Auslöser', [
      {v:'first_motion_after_night',l:'Erste Bewegung nach der Nacht'},
      {v:'first_voice_after_night',l:'Erstes Sprachkommando nach der Nacht'},
      {v:'alarm_dismissed',l:'Wecker ausgeschaltet'},
      {v:'manual',l:'Nur auf Anfrage'}
    ]) +
    fChipSelect('routines.morning_briefing.modules', 'Was soll im Briefing enthalten sein?', [
      {v:'greeting',l:'Begrüßung'},
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
    fSubheading('Morgen-Aktionen') +
    fToggle('routines.morning_briefing.morning_actions.covers_up', 'Rolladen automatisch hochfahren') +
    fToggle('routines.morning_briefing.morning_actions.lights_soft', 'Licht sanft einschalten')
  ) +
  sectionWrap('&#9728;', 'Aufwach-Sequenz',
    fInfo('Kontextreiches Aufwachen wie bei MCU JARVIS — Rolladen fahren stufenweise hoch, sanftes Licht geht an, Kaffeemaschine startet. Nach einer kurzen Pause folgt das Morgen-Briefing. Erfordert einen Bewegungssensor im Schlafzimmer.') +
    fToggle('routines.morning_briefing.wakeup_sequence.enabled', 'Aufwach-Sequenz aktiv') +
    fEntityPickerSingle('routines.morning_briefing.wakeup_sequence.bedroom_motion_sensor', 'Schlafzimmer Bewegungssensor', ['binary_sensor'], 'z.B. binary_sensor.motion_schlafzimmer — ohne Sensor keine automatische Ausloesung') +
    fRange('routines.morning_briefing.wakeup_sequence.min_autonomy_level', 'Ab Autonomie-Level', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fRange('routines.morning_briefing.wakeup_sequence.window_start_hour', 'Frueheste Uhrzeit', 4, 8, 1, {4:'4 Uhr',5:'5 Uhr',6:'6 Uhr',7:'7 Uhr',8:'8 Uhr'}) +
    fRange('routines.morning_briefing.wakeup_sequence.window_end_hour', 'Späteste Uhrzeit', 7, 12, 1, {7:'7 Uhr',8:'8 Uhr',9:'9 Uhr',10:'10 Uhr',11:'11 Uhr',12:'12 Uhr'}) +
    fSubheading('Rolladen stufenweise') +
    fInfo('Rolladen fahren über einen Zeitraum langsam hoch. Standard: Dauer 180 Sek. (3 Min.)') +
    fToggle('routines.morning_briefing.wakeup_sequence.steps.covers_gradual.enabled', 'Rolladen langsam öffnen') +
    fRange('routines.morning_briefing.wakeup_sequence.steps.covers_gradual.duration_seconds', 'Dauer (Sekunden)', 60, 600, 30, {60:'1 Min',120:'2 Min',180:'3 Min',240:'4 Min',300:'5 Min',600:'10 Min'}) +
    fSubheading('Aufwach-Licht') +
    fInfo('Sanftes Licht zum Aufwachen. Standard: Helligkeit 20%.') +
    fToggle('routines.morning_briefing.wakeup_sequence.steps.lights_soft.enabled', 'Sanftes Licht einschalten') +
    fRange('routines.morning_briefing.wakeup_sequence.steps.lights_soft.brightness', 'Helligkeit', 5, 60, 5, {5:'5%',10:'10%',15:'15%',20:'20%',30:'30%',40:'40%',50:'50%',60:'60%'}) +
    fSubheading('Kaffeemaschine') +
    fInfo('Kaffeemaschine wird automatisch eingeschaltet. Erfordert eine schaltbare Entity (switch/input_boolean).') +
    fToggle('routines.morning_briefing.wakeup_sequence.steps.coffee_machine.enabled', 'Kaffee automatisch starten') +
    fEntityPickerSingle('routines.morning_briefing.wakeup_sequence.steps.coffee_machine.entity', 'Kaffeemaschine Entity', ['switch','input_boolean'], 'z.B. switch.kaffeemaschine') +
    fSubheading('Timing') +
    fInfo('Zeitlicher Ablauf der Aufwach-Sequenz. Standard: Pause vor Briefing 30 Sek.') +
    fRange('routines.morning_briefing.wakeup_sequence.briefing_delay_seconds', 'Pause vor Briefing', 15, 120, 5, {15:'15 Sek',30:'30 Sek',45:'45 Sek',60:'1 Min',90:'1.5 Min',120:'2 Min'})
  ) +
  sectionWrap('&#127769;', 'Abend-Briefing',
    fInfo('Automatischer Abend-Status — Sicherheit, offene Fenster, Wetter morgen. Wird bei erster Bewegung am Abend ausgeloest. Jarvis schlägt proaktiv vor, Rollläden und Fenster zu schließen.') +
    fToggle('routines.evening_briefing.enabled', 'Abend-Briefing aktiv') +
    fRange('routines.evening_briefing.window_start_hour', 'Startzeit', 18, 23, 1, {18:'18 Uhr',19:'19 Uhr',20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr'}) +
    fRange('routines.evening_briefing.window_end_hour', 'Endzeit', 19, 24, 1, {19:'19 Uhr',20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr',24:'24 Uhr'})
  ) +
  sectionWrap('&#128197;', 'Kalender',
    fInfo('Welche Home Assistant Kalender sollen abgefragt werden? Wenn keiner gewählt ist, werden automatisch alle Kalender aus HA genutzt.') +
    fEntityPicker('calendar.entities', 'Kalender-Entities', ['calendar'], 'Nur ausgewählte Kalender abfragen — leer = alle')
  ) +
  sectionWrap('&#128164;', 'Gute-Nacht-Routine',
    fInfo('Automatische Aktionen wenn du "Gute Nacht" sagst — Lichter aus, Heizung runter, alles prüfen.') +
    fToggle('routines.good_night.enabled', 'Gute-Nacht-Routine aktiv') +
    fChipSelect('routines.good_night.triggers', 'Auslöse-Phrasen', [
      'gute nacht','schlaf gut','nacht','geh schlafen','ab ins bett',
      'ich geh pennen','bis morgen','nacht jarvis','schlafenszeit'
    ]) +
    fChipSelect('routines.good_night.checks', 'Sicherheits-Checks vor dem Schlafen', [
      {v:'doors',l:'Türen geschlossen?'},
      {v:'windows',l:'Fenster geschlossen?'},
      {v:'lights',l:'Alle Lichter aus?'},
      {v:'stove',l:'Herd aus?'},
      {v:'oven',l:'Ofen aus?'},
      {v:'iron',l:'Bügeleisen aus?'},
      {v:'garage',l:'Garage zu?'},
      {v:'alarm',l:'Alarmanlage scharf?'}
    ]) +
    fSubheading('Automatische Aktionen') +
    fToggle('routines.good_night.actions.lights_off', 'Alle Lichter ausschalten') +
    fToggle('routines.good_night.actions.heating_night', 'Heizung auf Nacht-Modus') +
    fToggle('routines.good_night.actions.covers_down', 'Rolladen runterfahren') +
    fToggle('routines.good_night.actions.alarm_arm_home', 'Alarmanlage scharf schalten')
  ) +
  sectionWrap('&#128101;', 'Gäste-Modus',
    fInfo('Wenn Besuch da ist — der Assistent wird formeller und zeigt keine privaten Infos.') +
    fChipSelect('routines.guest_mode.triggers', 'Aktivierung durch', [
      'besuch','gäste','gast','besucher','gast modus','wir haben besuch',
      'gäste da','jemand zu besuch'
    ]) +
    fToggle('routines.guest_mode.restrictions.hide_personal_info', 'Persönliche Infos verstecken') +
    fToggle('routines.guest_mode.restrictions.formal_tone', 'Formeller Ton aktivieren') +
    fToggle('routines.guest_mode.restrictions.restrict_security', 'Sicherheitsfunktionen einschränken') +
    fToggle('routines.guest_mode.restrictions.suggest_guest_wifi', 'Gäste-WLAN vorschlagen')
  ) +
  sectionWrap('&#128221;', 'Benannte Protokolle',
    fInfo('Multi-Step-Sequenzen per Sprache erstellen und ausführen. Z.B. "Erstelle Protokoll Filmabend: Licht 20%, Rolladen zu, TV an" — dann reicht "Filmabend" zum Ausführen.') +
    fToggle('protocols.enabled', 'Protokolle aktiv') +
    fNum('protocols.max_protocols', 'Maximale Anzahl Protokolle', 1, 50, 1) +
    fNum('protocols.max_steps', 'Maximale Schritte pro Protokoll', 1, 20, 1)
  ) +
  sectionWrap('&#128260;', '"Das Übliche" — Implizite Routinen',
    fInfo('Sage "das Übliche", "wie immer" oder "mach fertig" — Jarvis erkennt gelernte Muster für die aktuelle Tageszeit und führt sie aus. Basiert auf dem Vorausdenken-Modul (Anticipation Engine).') +
    fToggle('das_übliche.enabled', '"Das Übliche" aktiv') +
    fRange('das_übliche.auto_execute_confidence', 'Auto-Ausführen ab Sicherheit', 0.5, 1, 0.05, {0.5:'50%',0.6:'60%',0.7:'70%',0.8:'80%',0.9:'90%',1:'100%'}) +
    fRange('das_übliche.suggest_confidence', 'Nachfragen ab Sicherheit', 0.3, 1, 0.05, {0.3:'30%',0.4:'40%',0.5:'50%',0.6:'60%',0.7:'70%',0.8:'80%'}) +
    fTextarea('das_übliche.patterns', 'Trigger-Phrasen', 'Phrasen die "Das Übliche" auslösen. Eine pro Zeile.')
  );
}

// ---- Szenen-Konfigurator (zentrales Management) ----
// Vordefinierte Szenen — der User kann eigene hinzufügen
const _DEFAULT_SCENES = [
  {id:'filmabend',     icon:'&#127916;', label:'Filmabend',    activity:'watching',  silence:true,  transition:5,  triggers:['filmabend','film schauen','film an']},
  {id:'kino',          icon:'&#127871;', label:'Kino',         activity:'watching',  silence:true,  transition:5,  triggers:['kino','kinoabend','kino modus']},
  {id:'schlafen',      icon:'&#128164;', label:'Schlafen',     activity:'sleeping',  silence:true,  transition:7,  triggers:['schlafen','schlafmodus','ich geh schlafen']},
  {id:'gute_nacht',    icon:'&#127769;', label:'Gute Nacht',   activity:'sleeping',  silence:true,  transition:7,  triggers:['gute nacht','nacht']},
  {id:'aufwachen',     icon:'&#127780;', label:'Aufwachen',    activity:'relaxing',  silence:false, transition:10, triggers:['aufwachen','guten morgen','wach auf']},
  {id:'gemuetlich',    icon:'&#128293;', label:'Gemuetlich',   activity:'relaxing',  silence:false, transition:4,  triggers:['gemuetlich','cozy','kuscheln']},
  {id:'meditation',    icon:'&#129495;', label:'Meditation',   activity:'focused',   silence:true,  transition:3,  triggers:['meditation','meditieren']},
  {id:'konzentration', icon:'&#128187;', label:'Konzentration',activity:'focused',   silence:true,  transition:2,  triggers:['konzentration','fokus','konzentrieren']},
  {id:'telefonat',     icon:'&#128222;', label:'Telefonat',    activity:'in_call',   silence:true,  transition:1,  triggers:['telefonat','telefonieren','anruf']},
  {id:'meeting',       icon:'&#128188;', label:'Meeting',      activity:'in_call',   silence:true,  transition:1,  triggers:['meeting','besprechung','videokonferenz']},
  {id:'gäste',        icon:'&#128101;', label:'Gäste',       activity:'guests',    silence:false, transition:3,  triggers:['gäste','besuch','gäste da']},
  {id:'nicht_stören', icon:'&#128683;', label:'Nicht stören',activity:'focused',   silence:true,  transition:1,  triggers:['nicht stören','ruhe','bitte nicht stören']},
  {id:'musik',         icon:'&#127925;', label:'Musik',        activity:'relaxing',  silence:false, transition:2,  triggers:['musik','musik an','musik hoeren']},
  {id:'arbeiten',      icon:'&#128188;', label:'Arbeiten',     activity:'focused',   silence:true,  transition:1,  triggers:['arbeit','arbeiten','arbeitsmodus']},
  {id:'kochen',        icon:'&#127859;', label:'Kochen',       activity:'relaxing',  silence:false, transition:1,  triggers:['kochen','kochmodus']},
  {id:'party',         icon:'&#127881;', label:'Party',        activity:'guests',    silence:false, transition:2,  triggers:['party','feiern','partymodus']},
  {id:'hell',          icon:'&#9728;',   label:'Hell',         activity:'relaxing',  silence:false, transition:2,  triggers:['hell','alles an','volle helligkeit']},
  {id:'essen',         icon:'&#127869;', label:'Essen',        activity:'relaxing',  silence:false, transition:3,  triggers:['essen','abendessen','dinner','mahlzeit']},
  {id:'lesen',         icon:'&#128214;', label:'Lesen',        activity:'focused',   silence:true,  transition:3,  triggers:['lesen','buch','reading']},
  {id:'spielen',       icon:'&#127918;', label:'Spielen',      activity:'relaxing',  silence:false, transition:2,  triggers:['spielen','kinder','gaming']},
  {id:'morgens',       icon:'&#127748;', label:'Bad Morgens',  activity:'relaxing',  silence:false, transition:5,  triggers:['morgens','morgenroutine']},
  {id:'abends',        icon:'&#127749;', label:'Bad Abends',   activity:'relaxing',  silence:false, transition:5,  triggers:['abends','baden','entspannen bad']},
  {id:'romantisch',    icon:'&#128151;', label:'Romantisch',   activity:'relaxing',  silence:true,  transition:5,  triggers:['romantisch','romantik','kerzenschein']},
  {id:'energiesparen', icon:'&#9889;',   label:'Energiesparen',activity:'away',      silence:false, transition:1,  triggers:['energiesparen','strom sparen','eco']},
  {id:'putzen',        icon:'&#129529;', label:'Putzen',       activity:'relaxing',  silence:false, transition:1,  triggers:['putzen','sauber machen','aufräumen']},
];

const _ACTIVITY_OPTIONS = [
  {v:'sleeping',  l:'Schlafen'},
  {v:'in_call',   l:'Im Telefonat'},
  {v:'watching',  l:'TV/Film schauen'},
  {v:'focused',   l:'Konzentriert'},
  {v:'guests',    l:'Gäste da'},
  {v:'relaxing',  l:'Entspannt'},
  {v:'away',      l:'Abwesend'},
];

function _getScenes() {
  // Szenen aus settings laden, sonst Defaults verwenden
  const saved = getPath(S, 'scenes') || {};
  const moodScenes = saved.mood_scenes || {};
  const scenes = [];
  // Defaults als Basis, Overrides anwenden
  for (const def of _DEFAULT_SCENES) {
    const override = saved[def.id] || {};
    const moodOvr = moodScenes[def.id] || {};
    const defaultMood = _DEFAULT_MOOD_ACTIONS[def.id] || {};
    scenes.push({
      id: def.id,
      icon: override.icon ?? def.icon,
      label: override.label ?? def.label,
      activity: override.activity ?? def.activity,
      silence: override.silence ?? def.silence,
      transition: override.transition ?? def.transition,
      triggers: override.triggers ?? def.triggers ?? [],
      device_triggers: override.device_triggers ?? def.device_triggers ?? [],
      device_trigger_mode: override.device_trigger_mode ?? 'or',
      actions: moodOvr.actions ?? defaultMood.actions ?? null,
      climate_offset: moodOvr.climate_offset ?? defaultMood.climate_offset ?? null,
      custom: false,
    });
  }
  // Custom Szenen (nicht in Defaults)
  const defaultIds = new Set(_DEFAULT_SCENES.map(d => d.id));
  for (const [id, cfg] of Object.entries(saved)) {
    if (!defaultIds.has(id) && cfg._custom) {
      const moodOvr = moodScenes[id] || {};
      scenes.push({
        id, icon: cfg.icon || '&#127912;', label: cfg.label || id,
        activity: cfg.activity || 'relaxing', silence: cfg.silence ?? false,
        transition: cfg.transition ?? 3, triggers: cfg.triggers ?? [],
        device_triggers: cfg.device_triggers ?? [],
        device_trigger_mode: cfg.device_trigger_mode ?? 'or',
        actions: moodOvr.actions ?? cfg.actions ?? null,
        climate_offset: moodOvr.climate_offset ?? cfg.climate_offset ?? null,
        custom: true,
      });
    }
  }
  return scenes;
}

function _saveScenes(scenes) {
  // Nur Abweichungen vom Default + Custom Szenen speichern
  const data = {};
  const defaultMap = {};
  const oldSaved = getPath(S, 'scenes') || {};
  for (const d of _DEFAULT_SCENES) defaultMap[d.id] = d;
  for (const sc of scenes) {
    const def = defaultMap[sc.id];
    if (sc.custom) {
      // Custom Szene: immer komplett speichern
      data[sc.id] = {icon: sc.icon, label: sc.label, activity: sc.activity, silence: sc.silence, transition: sc.transition, triggers: sc.triggers || [], device_triggers: sc.device_triggers || [], device_trigger_mode: sc.device_trigger_mode || 'or', actions: sc.actions || null, climate_offset: sc.climate_offset ?? null, _custom: true};
    } else if (def) {
      // Default Szene: nur Abweichungen
      const diff = {};
      if (sc.label !== def.label) diff.label = sc.label;
      if (sc.activity !== def.activity) diff.activity = sc.activity;
      if (sc.silence !== def.silence) diff.silence = sc.silence;
      if (sc.transition !== def.transition) diff.transition = sc.transition;
      if (sc.icon !== def.icon) diff.icon = sc.icon;
      if (JSON.stringify(sc.triggers || []) !== JSON.stringify(def.triggers || [])) diff.triggers = sc.triggers;
      if (JSON.stringify(sc.device_triggers || []) !== JSON.stringify(def.device_triggers || [])) diff.device_triggers = sc.device_triggers;
      if (sc.device_trigger_mode !== 'or') diff.device_trigger_mode = sc.device_trigger_mode;
      // Szene hatte vorher Overrides in YAML? Dann Array-Felder immer
      // mitsenden damit deep-merge alte Werte überschreibt (nicht addiert)
      const hadOverrides = !!oldSaved[sc.id];
      if (hadOverrides) {
        diff.triggers = sc.triggers || [];
        diff.device_triggers = sc.device_triggers || [];
        if (sc.device_trigger_mode !== 'or') diff.device_trigger_mode = sc.device_trigger_mode;
      }
      if (Object.keys(diff).length > 0) data[sc.id] = diff;
    }
  }
  setPath(S, 'scenes', data);

  // Abgeleitete Werte in anderen Settings synchronisieren:
  // 1. proactive.silence_scenes
  const silenceList = scenes.filter(s => s.silence).map(s => s.id);
  setPath(S, 'proactive.silence_scenes', silenceList);
  // 2. narration.scene_transitions
  const transitions = {};
  for (const sc of scenes) {
    transitions[sc.id] = sc.transition;
  }
  setPath(S, 'narration.scene_transitions', transitions);
  // 3. scenes.trigger_map — Mapping Trigger-Phrase → Scene-ID für LLM
  const triggerMap = {};
  for (const sc of scenes) {
    if (sc.triggers && sc.triggers.length > 0) {
      triggerMap[sc.id] = sc.triggers;
    }
  }
  setPath(S, 'scenes.trigger_map', triggerMap);
  // 4. scenes.device_trigger_map — Mapping Entity-ID → Scene-ID für automatische Aktivierung
  const deviceTriggerMap = {};
  for (const sc of scenes) {
    if (sc.device_triggers && sc.device_triggers.length > 0) {
      for (const entity of sc.device_triggers) {
        if (!entity) continue;  // Leere Einträge ignorieren
        if (!deviceTriggerMap[entity]) deviceTriggerMap[entity] = [];
        deviceTriggerMap[entity].push(sc.id);
      }
    }
  }
  setPath(S, 'scenes.device_trigger_map', deviceTriggerMap);
  // 4b. scenes.device_trigger_modes — UND/ODER Modus pro Szene
  const deviceTriggerModes = {};
  for (const sc of scenes) {
    if (sc.device_trigger_mode === 'and' && sc.device_triggers && sc.device_triggers.length > 1) {
      deviceTriggerModes[sc.id] = 'and';
    }
  }
  setPath(S, 'scenes.device_trigger_modes', Object.keys(deviceTriggerModes).length > 0 ? deviceTriggerModes : {});
  // 5. scenes.mood_scenes — Actions + Climate-Offset fuer Mood-Szenen
  // Nur speichern wenn vom Default abweichend (sonst unnoetige YAML-Eintraege)
  const moodScenes = getPath(S, 'scenes.mood_scenes') || {};
  for (const sc of scenes) {
    const defMood = _DEFAULT_MOOD_ACTIONS[sc.id] || {};
    const defActions = defMood.actions || null;
    const defOffset = defMood.climate_offset ?? null;
    const actionsChanged = JSON.stringify(sc.actions || null) !== JSON.stringify(defActions);
    const offsetChanged = (sc.climate_offset ?? null) !== defOffset;
    if (actionsChanged || offsetChanged) {
      if (!moodScenes[sc.id]) moodScenes[sc.id] = {};
      moodScenes[sc.id].label = sc.label;
      if (actionsChanged && sc.actions && sc.actions.length > 0) {
        moodScenes[sc.id].actions = sc.actions;
      } else {
        delete moodScenes[sc.id].actions;
      }
      if (offsetChanged && sc.climate_offset != null) {
        moodScenes[sc.id].climate_offset = sc.climate_offset;
      } else {
        delete moodScenes[sc.id].climate_offset;
      }
      // Leere Eintraege aufräumen
      if (Object.keys(moodScenes[sc.id]).filter(k => k !== 'label').length === 0) {
        delete moodScenes[sc.id];
      }
    } else if (moodScenes[sc.id]) {
      // Zurueck auf Default → Override entfernen
      delete moodScenes[sc.id];
    }
  }
  setPath(S, 'scenes.mood_scenes', moodScenes);

  scheduleAutoSave();
}

function renderScenes() {
  const scenes = _getScenes();
  const activityLabels = {};
  for (const a of _ACTIVITY_OPTIONS) activityLabels[a.v] = a.l;

  let sceneCards = '';
  for (const sc of scenes) {
    const silenceChecked = sc.silence ? 'checked' : '';
    const isExpanded = _expandedSceneId === sc.id;
    const expandCls = isExpanded ? ' scene-expanded' : '';
    const summary = _summarizeSceneActions(sc);
    const actLabel = activityLabels[sc.activity] || sc.activity;
    let actOpts = _ACTIVITY_OPTIONS.map(a =>
      `<option value="${a.v}" ${sc.activity===a.v?'selected':''}>${a.l}</option>`
    ).join('');

    // Badges for header
    let badges = '';
    if (sc.silence) badges += '<span class="scene-badge scene-badge-silence">Stille</span>';
    if (sc.custom) badges += '<span class="scene-badge scene-badge-custom">Eigene</span>';

    sceneCards += `<div class="scene-card${sc.silence?' scene-silence':''}${expandCls}" data-scene-id="${sc.id}">
      <div class="scene-card-hdr" onclick="toggleSceneExpand('${esc(sc.id)}')">
        <span class="scene-icon">${sc.icon}</span>
        <div class="scene-hdr-info">
          <div class="scene-hdr-title">${esc(sc.label)} ${badges}</div>
          <div class="scene-hdr-summary">${actLabel} · ${sc.transition}s · ${summary}</div>
        </div>
        <div class="scene-hdr-actions" onclick="event.stopPropagation()">
          ${sc.custom ? '<button class="btn btn-sm scene-rm" onclick="removeScene(\'' + esc(sc.id) + '\')" title="Szene löschen">&#10005;</button>' : ''}
        </div>
        <span class="scene-chevron">&#9660;</span>
      </div>
      <div class="scene-card-body" style="padding-top:12px;">

        <div class="scene-section-title">Allgemein</div>
        <div class="scene-field">
          <span class="scene-field-label">Name</span>
          <input type="text" class="scene-name-input" value="${esc(sc.label)}" data-field="label"
            onclick="event.stopPropagation()"
            onchange="sceneFieldChanged('${esc(sc.id)}','label',this.value)">
        </div>
        <div class="scene-field">
          <span class="scene-field-label">Aktivität</span>
          <select data-field="activity" onchange="sceneFieldChanged('${esc(sc.id)}','activity',this.value)">${actOpts}</select>
        </div>
        <div class="scene-field">
          <span class="scene-field-label">Übergang</span>
          <div style="display:flex;align-items:center;gap:8px;flex:1;">
            <input type="range" min="1" max="20" step="1" value="${sc.transition}" data-field="transition"
              oninput="this.nextElementSibling.textContent=this.value+'s';sceneFieldChanged('${esc(sc.id)}','transition',parseInt(this.value))">
            <span style="font-size:12px;color:var(--text-muted);min-width:28px;">${sc.transition}s</span>
          </div>
        </div>
        <div class="scene-field">
          <label class="scene-silence-toggle" title="Nicht stören — proaktive Meldungen werden unterdrückt">
            <input type="checkbox" ${silenceChecked} data-field="silence"
              onchange="sceneFieldChanged('${esc(sc.id)}','silence',this.checked)">
            <span>Nicht stören</span>
          </label>
        </div>
        <div class="scene-field">
          <span class="scene-field-label">Klima-Offset</span>
          <div style="display:flex;align-items:center;gap:6px;flex:1;">
            <input type="number" step="0.5" min="-5" max="5" value="${sc.climate_offset ?? ''}"
              placeholder="z.B. -2"
              style="width:80px;font-size:12px;padding:4px 6px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:6px;"
              onchange="sceneClimateOffsetChanged('${esc(sc.id)}',this.value)">
            <span style="font-size:11px;color:var(--text-muted);">&deg;C</span>
          </div>
        </div>

        <div class="scene-section-title">Auslöser</div>
        <div class="scene-field" style="flex-direction:column;align-items:stretch;">
          <span class="scene-field-label">Sprachbefehle</span>
          <input type="text" class="scene-triggers-input" value="${esc((sc.triggers||[]).join(', '))}"
            placeholder="z.B. filmabend, film schauen, film an"
            title="Komma-getrennte Begriffe die diese Szene auslösen"
            onchange="sceneTriggersChanged('${esc(sc.id)}',this.value)">
        </div>
        <div class="scene-field" style="flex-direction:column;align-items:stretch;">
          <span class="scene-field-label" style="display:flex;align-items:center;gap:8px;">
            Geräte-Trigger
            <button type="button" class="btn btn-sm scene-dt-mode" data-scene-id="${esc(sc.id)}"
              style="padding:2px 8px;font-size:10px;font-weight:${sc.device_trigger_mode==='and'?'bold':'normal'};opacity:${sc.device_trigger_mode==='and'?'1':'0.5'};"
              onclick="toggleDeviceTriggerMode('${esc(sc.id)}')"
              title="ODER: Ein Gerät reicht. UND: Alle Geräte müssen aktiv sein.">${sc.device_trigger_mode === 'and' ? 'UND' : 'ODER'}</button>
          </span>
          <div class="scene-device-triggers" data-scene-id="${esc(sc.id)}">
            ${(sc.device_triggers||[]).map((dt, i) => `<div class="scene-dt-row" style="display:flex;gap:4px;margin-bottom:4px;align-items:center;">
              <div class="entity-pick-wrap" style="position:relative;flex:1;">
                <input type="text" class="scene-dt-input form-input entity-pick-input" value="${esc(dt)}"
                  placeholder="z.B. media_player.tv"
                  data-domains="media_player,binary_sensor,remote,switch,input_boolean,sensor"
                  oninput="entityPickFilter(this,'media_player,binary_sensor,remote,switch,input_boolean,sensor')"
                  onfocus="entityPickFilter(this,'media_player,binary_sensor,remote,switch,input_boolean,sensor')"
                  onchange="sceneDeviceTriggerChanged('${esc(sc.id)}')"
                  style="font-size:12px;font-family:var(--mono);padding:5px 8px;">
                <div class="entity-pick-dropdown" style="display:none;"></div>
              </div>
              <button type="button" class="btn btn-sm scene-dt-rm" style="padding:6px 10px;font-size:14px;min-width:36px;min-height:36px;z-index:10000;position:relative;flex-shrink:0;color:var(--danger,#ef4444);" onclick="event.stopPropagation();removeSceneDeviceTrigger('${esc(sc.id)}',${i})" ontouchend="event.preventDefault();event.stopPropagation();removeSceneDeviceTrigger('${esc(sc.id)}',${i})">&#10005;</button>
            </div>`).join('')}
            <button class="btn btn-sm" style="padding:3px 10px;font-size:11px;margin-top:4px;" onclick="addSceneDeviceTrigger('${esc(sc.id)}')">+ Gerät</button>
          </div>
        </div>

        <div class="scene-section-title">Geräte-Aktionen</div>
        <div class="scene-actions-editor" data-scene-id="${esc(sc.id)}" style="display:block;">
          ${_renderSceneActions(sc)}
        </div>

      </div>
    </div>`;
  }

  return sectionWrap('&#127916;', 'Haus-Szenen',
    fInfo('Definiere Szenen für dein Zuhause. Klicke auf eine Szene um sie aufzuklappen und zu konfigurieren. Szenen können per Sprache aktiviert werden: <strong>"Jarvis, Filmabend."</strong>') +
    `<div class="scene-list">${sceneCards}</div>
    <button class="btn btn-sm" onclick="addCustomScene()" style="margin-top:12px;">+ Eigene Szene</button>`
  );
}

// Scene accordion expand/collapse
let _expandedSceneId = null;
function toggleSceneExpand(sceneId) {
  _expandedSceneId = _expandedSceneId === sceneId ? null : sceneId;
  // Toggle without full re-render to preserve input state
  document.querySelectorAll('.scene-card').forEach(card => {
    const id = card.dataset.sceneId;
    if (id === _expandedSceneId) {
      card.classList.add('scene-expanded');
    } else {
      card.classList.remove('scene-expanded');
    }
  });
}

function sceneFieldChanged(sceneId, field, value) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc) return;
  sc[field] = value;
  _saveScenes(scenes);
  // Bei silence-Toggle visuell updaten (CSS-Klasse)
  if (field === 'silence') {
    const card = document.querySelector(`.scene-card[data-scene-id="${sceneId}"]`);
    if (card) card.classList.toggle('scene-silence', value);
  }
}

function sceneTriggersChanged(sceneId, value) {
  const triggers = value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc) return;
  sc.triggers = triggers;
  _saveScenes(scenes);
}

function toggleDeviceTriggerMode(sceneId) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc) return;
  sc.device_trigger_mode = sc.device_trigger_mode === 'and' ? 'or' : 'and';
  _saveScenes(scenes);
  // Button aktualisieren ohne komplett neu zu rendern
  const btn = document.querySelector(`.scene-dt-mode[data-scene-id="${sceneId}"]`);
  if (btn) {
    btn.textContent = sc.device_trigger_mode === 'and' ? 'UND' : 'ODER';
    btn.style.fontWeight = sc.device_trigger_mode === 'and' ? 'bold' : 'normal';
    btn.style.opacity = sc.device_trigger_mode === 'and' ? '1' : '0.5';
  }
}

function addCustomScene() {
  const id = 'szene_' + Date.now();
  const scenes = _getScenes();
  scenes.push({id, icon: '&#127912;', label: 'Neue Szene', activity: 'relaxing', silence: false, transition: 3, triggers: [], device_triggers: [], device_trigger_mode: 'or', actions: [], climate_offset: null, custom: true});
  _saveScenes(scenes);
  _expandedSceneId = id;  // Neue Szene direkt aufklappen
  renderCurrentTab();
}

function removeScene(sceneId) {
  const scenes = _getScenes().filter(s => s.id !== sceneId);
  // Auch aus S entfernen
  const saved = getPath(S, 'scenes') || {};
  delete saved[sceneId];
  setPath(S, 'scenes', saved);
  _saveScenes(scenes);
  renderCurrentTab();
}

function sceneDeviceTriggerChanged(sceneId) {
  const container = document.querySelector(`.scene-device-triggers[data-scene-id="${sceneId}"]`);
  if (!container) return;
  const inputs = container.querySelectorAll('.scene-dt-input');
  const deviceTriggers = [];
  inputs.forEach(inp => {
    const v = inp.value.trim();
    if (v) deviceTriggers.push(v);
  });
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc) return;
  sc.device_triggers = deviceTriggers;
  _saveScenes(scenes);
}

function addSceneDeviceTrigger(sceneId) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc) return;
  sc.device_triggers = sc.device_triggers || [];
  sc.device_triggers.push('');
  _saveScenes(scenes);
  renderCurrentTab();
}

let _dtRemovePending = false;
function removeSceneDeviceTrigger(sceneId, index) {
  // Debounce: ontouchend + onclick können beide feuern
  if (_dtRemovePending) return;
  _dtRemovePending = true;
  setTimeout(() => { _dtRemovePending = false; }, 300);

  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc || !sc.device_triggers) return;
  sc.device_triggers.splice(index, 1);
  _saveScenes(scenes);
  renderCurrentTab();
}

// ---- [19] Mood-Scene Actions Editor ----
const _ACTION_DOMAINS = [
  {v:'light', l:'Licht'},
  {v:'cover', l:'Rollladen'},
  {v:'climate', l:'Klima'},
  {v:'media_player', l:'Medien'},
  {v:'switch', l:'Schalter'},
  {v:'fan', l:'Ventilator'},
];
// Default Mood-Scene Actions (Spiegel von _DEFAULT_MOOD_SCENES im Backend)
const _DEFAULT_MOOD_ACTIONS = {
  gemuetlich: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:30,color_temp_kelvin:2700}},{domain:'cover',service:'close_cover',data:{}}],climate_offset:1.0},
  filmabend: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:10,color_temp_kelvin:2200}},{domain:'cover',service:'close_cover',data:{}},{domain:'media_player',service:'turn_on',data:{}}]},
  party: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:100,rgb_color:[255,100,50]}},{domain:'cover',service:'close_cover',data:{}}]},
  konzentration: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:80,color_temp_kelvin:5000}}]},
  gute_nacht: {actions:[{domain:'light',service:'turn_off',data:{}},{domain:'cover',service:'close_cover',data:{}}],climate_offset:-2.0},
  aufwachen: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:60,color_temp_kelvin:4000}},{domain:'cover',service:'open_cover',data:{}}],climate_offset:1.0},
  hell: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:100,color_temp_kelvin:5000}},{domain:'cover',service:'open_cover',data:{}}]},
  kochen: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:100,color_temp_kelvin:4500}}]},
  essen: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:60,color_temp_kelvin:2700}}]},
  schlafen: {actions:[{domain:'light',service:'turn_off',data:{}},{domain:'cover',service:'close_cover',data:{}}],climate_offset:-1.0},
  lesen: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:40,color_temp_kelvin:3000}}]},
  arbeiten: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:80,color_temp_kelvin:5000}}]},
  meeting: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:90,color_temp_kelvin:4500}}]},
  spielen: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:80,color_temp_kelvin:4000}}]},
  morgens: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:100,color_temp_kelvin:5000}}],climate_offset:2.0},
  abends: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:20,color_temp_kelvin:2200}}]},
  romantisch: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:5,color_temp_kelvin:2200}},{domain:'cover',service:'close_cover',data:{}}]},
  energiesparen: {actions:[{domain:'light',service:'turn_off',data:{}}],climate_offset:-3.0},
  putzen: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:100,color_temp_kelvin:5000}},{domain:'cover',service:'open_cover',data:{}}]},
  musik: {actions:[{domain:'light',service:'turn_on',data:{brightness_pct:40,color_temp_kelvin:2700}},{domain:'media_player',service:'turn_on',data:{}}]},
};
const _ACTION_SERVICES = {
  light: [{v:'turn_on',l:'Einschalten'},{v:'turn_off',l:'Ausschalten'}],
  cover: [{v:'open_cover',l:'Oeffnen'},{v:'close_cover',l:'Schliessen'},{v:'set_cover_position',l:'Position setzen'}],
  climate: [{v:'set_temperature',l:'Temperatur setzen'}],
  media_player: [{v:'turn_on',l:'Einschalten'},{v:'turn_off',l:'Ausschalten'}],
  switch: [{v:'turn_on',l:'Einschalten'},{v:'turn_off',l:'Ausschalten'}],
  fan: [{v:'turn_on',l:'Einschalten'},{v:'turn_off',l:'Ausschalten'}],
};

function _summarizeSceneActions(sc) {
  const actions = sc.actions || [];
  if (actions.length === 0) return '<em>Keine Aktionen definiert</em>';
  const domLabels = {};
  for (const d of _ACTION_DOMAINS) domLabels[d.v] = d.l;
  const parts = actions.map(a => {
    const dom = domLabels[a.domain] || a.domain;
    const d = a.data || {};
    if (a.domain === 'light' && a.service === 'turn_on' && d.brightness_pct != null) {
      let detail = `${dom} ${d.brightness_pct}%`;
      if (d.color_temp_kelvin) detail += ` ${d.color_temp_kelvin}K`;
      if (d.rgb_color) detail += ` RGB`;
      return detail;
    }
    if (a.service === 'turn_off') return `${dom} aus`;
    if (a.service === 'close_cover') return `${dom} zu`;
    if (a.service === 'open_cover') return `${dom} auf`;
    return dom;
  });
  const offset = sc.climate_offset != null ? `, Klima ${sc.climate_offset > 0 ? '+' : ''}${sc.climate_offset}°C` : '';
  return parts.join(', ') + offset;
}

function _renderSceneActions(sc) {
  const actions = sc.actions || [];
  let html = '<div style="margin-top:4px;">';
  if (actions.length === 0) {
    html += '<div style="font-size:12px;color:var(--text-muted);padding:8px 0;font-style:italic;">Keine Aktionen — füge Geräte hinzu die bei dieser Szene geschaltet werden sollen.</div>';
  }
  for (let i = 0; i < actions.length; i++) {
    const a = actions[i];
    const domain = a.domain || 'light';
    const service = a.service || 'turn_on';
    const data = a.data || {};
    const entityId = a.entity_id || '';
    // Domain-Dropdown
    const domOpts = _ACTION_DOMAINS.map(d =>
      `<option value="${d.v}" ${domain===d.v?'selected':''}>${d.l}</option>`
    ).join('');
    // Service-Dropdown
    const svcList = _ACTION_SERVICES[domain] || [{v:service,l:service}];
    const svcOpts = svcList.map(s =>
      `<option value="${s.v}" ${service===s.v?'selected':''}>${s.l}</option>`
    ).join('');
    html += `<div class="scene-action-row">
      <select style="flex:0 0 90px;" onchange="sceneActionDomainChanged('${esc(sc.id)}',${i},this.value)">${domOpts}</select>
      <select style="flex:0 0 120px;" onchange="sceneActionFieldChanged('${esc(sc.id)}',${i},'service',this.value)">${svcOpts}</select>
      <div class="entity-pick-wrap scene-action-entity" style="position:relative;">
        <input type="text" class="entity-pick-input scene-action-entity-input" value="${esc(entityId)}"
          placeholder="Gerät wählen (optional = alle)"
          data-scene-id="${esc(sc.id)}" data-action-idx="${i}"
          oninput="entityPickFilter(this,'${domain}')"
          onfocus="entityPickFilter(this,'${domain}')"
          onchange="sceneActionEntityChanged('${esc(sc.id)}',${i},this.value)"
          style="font-size:11px;font-family:var(--mono);padding:4px 6px;width:100%;">
        <div class="entity-pick-dropdown" style="display:none;"></div>
      </div>`;
    // Parameter-Inputs basierend auf Domain+Service
    if (domain === 'light' && service === 'turn_on') {
      html += `<input type="number" min="0" max="100" step="5" value="${data.brightness_pct ?? ''}" placeholder="% Hell."
        style="width:60px;" title="Helligkeit in %"
        onchange="sceneActionDataChanged('${esc(sc.id)}',${i},'brightness_pct',this.value)">
      <input type="number" min="2000" max="6500" step="100" value="${data.color_temp_kelvin ?? ''}" placeholder="Kelvin"
        style="width:65px;" title="Farbtemperatur in Kelvin"
        onchange="sceneActionDataChanged('${esc(sc.id)}',${i},'color_temp_kelvin',this.value)">
      <input type="color" value="${data.rgb_color ? '#'+data.rgb_color.map(c=>(c<16?'0':'')+c.toString(16)).join('') : ''}"
        title="Farbe (optional)"
        style="width:30px;height:26px;padding:0;border:1px solid var(--border);border-radius:6px;cursor:pointer;${data.rgb_color ? '' : 'opacity:0.3;'}"
        onchange="sceneActionColorChanged('${esc(sc.id)}',${i},this.value)">`;
    } else if (domain === 'cover' && service === 'set_cover_position') {
      html += `<input type="number" min="0" max="100" step="5" value="${data.position ?? ''}" placeholder="Pos. %"
        style="width:60px;" title="Position in %"
        onchange="sceneActionDataChanged('${esc(sc.id)}',${i},'position',this.value)">`;
    } else if (domain === 'climate' && service === 'set_temperature') {
      html += `<input type="number" min="15" max="30" step="0.5" value="${data.temperature ?? ''}" placeholder="°C"
        style="width:60px;" title="Temperatur in °C"
        onchange="sceneActionDataChanged('${esc(sc.id)}',${i},'temperature',this.value)">`;
    }
    html += `<button type="button" style="font-size:14px;padding:4px 10px;background:none;color:var(--danger);border:1px solid rgba(239,68,68,0.3);border-radius:6px;cursor:pointer;flex-shrink:0;transition:border-color 0.15s;"
        onmouseover="this.style.borderColor='var(--danger)'" onmouseout="this.style.borderColor='rgba(239,68,68,0.3)'"
        onclick="removeSceneAction('${esc(sc.id)}',${i})">&times;</button>
    </div>`;
  }
  html += `<button class="btn btn-sm" style="padding:4px 12px;font-size:11px;margin-top:6px;"
    onclick="addSceneAction('${esc(sc.id)}')">+ Aktion hinzufügen</button>`;
  html += '</div>';
  return html;
}

function toggleSceneActions(sceneId) {
  const el = document.querySelector(`.scene-actions-editor[data-scene-id="${sceneId}"]`);
  if (!el) return;
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function sceneActionDomainChanged(sceneId, idx, newDomain) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc || !sc.actions || !sc.actions[idx]) return;
  sc.actions[idx].domain = newDomain;
  // Service auf ersten verfügbaren setzen
  const svcList = _ACTION_SERVICES[newDomain] || [];
  sc.actions[idx].service = svcList.length > 0 ? svcList[0].v : 'turn_on';
  sc.actions[idx].data = {};
  // Entity-ID leeren (Domain hat gewechselt → altes Entity passt nicht)
  delete sc.actions[idx].entity_id;
  _saveScenes(scenes);
  const el = document.querySelector(`.scene-actions-editor[data-scene-id="${sceneId}"]`);
  if (el) el.innerHTML = _renderSceneActions(sc);
}

function sceneActionFieldChanged(sceneId, idx, field, value) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc || !sc.actions || !sc.actions[idx]) return;
  sc.actions[idx][field] = value;
  if (field === 'service') sc.actions[idx].data = {};
  _saveScenes(scenes);
  const el = document.querySelector(`.scene-actions-editor[data-scene-id="${sceneId}"]`);
  if (el) el.innerHTML = _renderSceneActions(sc);
}

function sceneActionDataChanged(sceneId, idx, key, value) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc || !sc.actions || !sc.actions[idx]) return;
  if (!sc.actions[idx].data) sc.actions[idx].data = {};
  const num = parseFloat(value);
  if (value === '' || isNaN(num)) {
    delete sc.actions[idx].data[key];
  } else {
    sc.actions[idx].data[key] = num;
    // Farbtemperatur und RGB sind exklusiv
    if (key === 'color_temp_kelvin') delete sc.actions[idx].data.rgb_color;
  }
  _saveScenes(scenes);
  // Editor neu rendern um Color-Picker zu aktualisieren
  if (key === 'color_temp_kelvin') {
    const el = document.querySelector(`.scene-actions-editor[data-scene-id="${sceneId}"]`);
    if (el && el.style.display !== 'none') el.innerHTML = _renderSceneActions(sc);
  }
}

function sceneActionColorChanged(sceneId, idx, hexColor) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc || !sc.actions || !sc.actions[idx]) return;
  if (!sc.actions[idx].data) sc.actions[idx].data = {};
  if (!hexColor || hexColor === '#000000') {
    delete sc.actions[idx].data.rgb_color;
  } else {
    const r = parseInt(hexColor.substr(1,2), 16);
    const g = parseInt(hexColor.substr(3,2), 16);
    const b = parseInt(hexColor.substr(5,2), 16);
    sc.actions[idx].data.rgb_color = [r, g, b];
    // RGB und Farbtemperatur sind exklusiv — Farbtemperatur entfernen
    delete sc.actions[idx].data.color_temp_kelvin;
  }
  _saveScenes(scenes);
  // Editor neu rendern um Farbtemp-Feld zu aktualisieren
  const el = document.querySelector(`.scene-actions-editor[data-scene-id="${sceneId}"]`);
  if (el) el.innerHTML = _renderSceneActions(sc);
}

function sceneActionEntityChanged(sceneId, idx, entityId) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc || !sc.actions || !sc.actions[idx]) return;
  if (entityId && entityId.trim()) {
    sc.actions[idx].entity_id = entityId.trim();
  } else {
    delete sc.actions[idx].entity_id;
  }
  _saveScenes(scenes);
}

function addSceneAction(sceneId) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc) return;
  if (!sc.actions) sc.actions = [];
  sc.actions.push({domain: 'light', service: 'turn_on', data: {brightness_pct: 80, color_temp_kelvin: 3000}});
  _saveScenes(scenes);
  // Nur den Actions-Editor neu rendern (statt komplettem Re-Render)
  const el = document.querySelector(`.scene-actions-editor[data-scene-id="${sceneId}"]`);
  if (el) el.innerHTML = _renderSceneActions(sc);
}

function removeSceneAction(sceneId, idx) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc || !sc.actions) return;
  sc.actions.splice(idx, 1);
  _saveScenes(scenes);
  // Nur den Actions-Editor neu rendern
  const el = document.querySelector(`.scene-actions-editor[data-scene-id="${sceneId}"]`);
  if (el) el.innerHTML = _renderSceneActions(sc);
}

function sceneClimateOffsetChanged(sceneId, value) {
  const scenes = _getScenes();
  const sc = scenes.find(s => s.id === sceneId);
  if (!sc) return;
  sc.climate_offset = value === '' ? null : parseFloat(value);
  _saveScenes(scenes);
}

// ---- Proaktiv & Vorausdenken (aus Routinen ausgelagert) ----
function renderProactive() {
  return sectionWrap('&#128276;', 'Proaktive Meldungen',
    fInfo('Der Assistent meldet sich von allein — z.B. bei offenen Fenstern oder Vergesslichkeit. Je hoeher der Autonomie-Level, desto mehr meldet er sich. Standard: Cooldown 300 Sek., Buendelung 15 Min., ab Autonomie-Level 2.') +
    fToggle('proactive.enabled', 'Proaktive Meldungen aktiv') +
    fRange('proactive.cooldown_seconds', 'Mindestabstand zwischen Meldungen', 60, 3600, 60, {60:'1 Min',120:'2 Min',300:'5 Min',600:'10 Min',1800:'30 Min',3600:'1 Std'}) +
    fSubheading('Nachricht-Bündelung') +
    fToggle('proactive.batching.enabled', 'LOW-Meldungen buendeln') +
    fRange('proactive.batching.interval_minutes', 'Bündelungs-Intervall', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('proactive.music_follow_cooldown_minutes', 'Musik-Nachfolge Pause', 1, 30, 1) +
    fRange('proactive.min_autonomy_level', 'Ab Autonomie-Level', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fToggle('proactive.departure_shopping_reminder', 'Einkaufsliste beim Verlassen erwaehnen') +
    fToggle('proactive.personality_filter', 'Proaktive Nachrichten durch Persoenlichkeit filtern') +
    fInfo('Proaktive Nachrichten werden im Jarvis-Stil formuliert statt generischer Templates.') +
    fSubheading('Duplikat-Erkennung (Cross-Module)') +
    fToggle('notifications.dedup.enabled', 'Semantische Duplikat-Erkennung aktiv') +
    fInfo('Verhindert dass mehrere Module (Insights, Anticipation, Spontan, Wellness, Musik...) die gleiche Meldung senden. Vergleicht per KI-Embedding ob eine aehnliche Nachricht kuerzlich gesendet wurde. CRITICAL/HIGH-Meldungen werden nie gefiltert.') +
    fRange('notifications.dedup.similarity_threshold', 'Aehnlichkeits-Schwelle', 0.70, 0.95, 0.05, {0.70:'0.70 (aggressiv)',0.80:'0.80',0.85:'0.85 (Standard)',0.90:'0.90',0.95:'0.95 (nur exakte)'}) +
    fNum('notifications.dedup.buffer_size', 'Buffer-Groesse', 5, 50) +
    fRange('notifications.dedup.window_minutes', 'Zeitfenster (Minuten)', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min (Standard)',60:'1 Std',120:'2 Std'}) +
    `<div class="info-box" style="margin-top:8px;cursor:pointer;" onclick="document.querySelector('[data-tab=tab-scenes]').click()">
      <span class="info-icon">&#127916;</span>"Nicht stören"-Szenen und Aktivitäts-Zuordnung werden jetzt zentral im <strong>Szenen</strong>-Tab verwaltet. Klicke hier um dorthin zu wechseln.
    </div>`
  ) +
  sectionWrap('&#128164;', 'Ambient Presence',
    fInfo('Jarvis meldet sich gelegentlich im Hintergrund — ohne dass du fragst. Z.B. "Alles ruhig, draussen regnet es leicht." Dezente Praesenz wie ein aufmerksamer Butler.') +
    fToggle('ambient_presence.enabled', 'Ambient Presence aktiv') +
    fRange('ambient_presence.interval_minutes', 'Intervall (Minuten)', 15, 180, 15, {15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std'}) +
    fRange('ambient_presence.quiet_start', 'Ruhe ab', 18, 23, 1, {18:'18 Uhr',19:'19 Uhr',20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr'}) +
    fRange('ambient_presence.quiet_end', 'Ruhe bis', 5, 10, 1, {5:'5 Uhr',6:'6 Uhr',7:'7 Uhr',8:'8 Uhr',9:'9 Uhr',10:'10 Uhr'}) +
    fToggle('ambient_presence.report_weather', 'Wetter erwaehnen') +
    fToggle('ambient_presence.report_energy', 'Energieverbrauch erwaehnen') +
    fRange('ambient_presence.all_quiet_probability', '"Alles ruhig" Chance', 0, 1, 0.1, {0:'Nie',0.2:'20%',0.5:'50%',0.8:'80%',1:'Immer'})
  ) +
  sectionWrap('&#128302;', 'Vorausschau (Foresight)',
    fInfo('Jarvis denkt voraus: Erinnert an bevorstehende Termine, warnt vor Wetterumschwuengen und bereitet rechtzeitig auf Abfahrt vor.') +
    fToggle('foresight.enabled', 'Vorausschau aktiv') +
    fRange('foresight.calendar_lookahead_minutes', 'Kalender-Vorausschau', 15, 120, 15, {15:'15 Min',30:'30 Min',45:'45 Min',60:'1 Std',90:'90 Min',120:'2 Std'}) +
    fRange('foresight.departure_warning_minutes', 'Abfahrts-Erinnerung', 15, 90, 15, {15:'15 Min',30:'30 Min',45:'45 Min',60:'1 Std',90:'90 Min'}) +
    fToggle('foresight.weather_alerts', 'Wetter-Vorwarnungen')
  ) +
  sectionWrap('&#128260;', 'Self-Follow-Up',
    fInfo('Jarvis merkt sich offene Themen und kommt spaeter darauf zurueck: "Hast du den Handwerker erreicht?" Natuerliche Nachfragen statt vergessen.') +
    fToggle('self_followup.enabled', 'Self-Follow-Up aktiv') +
    fRange('self_followup.min_age_minutes', 'Min. Wartezeit', 5, 60, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fRange('self_followup.cooldown_minutes', 'Cooldown pro Thema', 15, 180, 15, {15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std'}) +
    fNum('self_followup.max_per_check', 'Max. Nachfragen gleichzeitig', 1, 5)
  ) +
  sectionWrap('&#127777;', 'Voraussagende Beduerfnisse',
    fInfo('Jarvis erkennt situationsbedingte Beduerfnisse: Bei Hitze eine Trink-Erinnerung, bei Kaelte ein Heiz-Vorschlag.') +
    fToggle('predictive_needs.enabled', 'Beduerfnis-Erkennung aktiv') +
    fNum('predictive_needs.hot_threshold', 'Hitze ab (°C)', 25, 40, 1) +
    fNum('predictive_needs.cold_threshold', 'Kaelte ab (°C)', -10, 10, 1)
  ) +
  sectionWrap('&#128205;', 'Geo-Fence',
    fInfo('Entfernungsbasierte Erkennung: Jarvis merkt wenn du dich naehest und bereitet das Haus vor (Heizung, Licht). Nutzt HA Person-Tracker.') +
    fRange('geo_fence.approaching_km', 'Annaeherung erkennen ab', 0.5, 10, 0.5, {0.5:'500m',1:'1 km',2:'2 km',5:'5 km',10:'10 km'}) +
    fRange('geo_fence.arriving_km', '"Gleich da" ab', 0.1, 2, 0.1, {0.1:'100m',0.2:'200m',0.5:'500m',1:'1 km',2:'2 km'})
  ) +
  sectionWrap('&#9200;', 'Zeitgefühl',
    fInfo('Der Assistent erinnert dich wenn Geräte zu lange laufen — z.B. Ofen vergessen, PC-Pause nötig.') +
    fToggle('time_awareness.enabled', 'Zeitgefühl aktiv') +
    fRange('time_awareness.check_interval_minutes', 'Prüf-Intervall', 1, 30, 1, {1:'Jede Min.',5:'5 Min.',10:'10 Min.',15:'15 Min.',30:'30 Min.'}) +
    fRange('time_awareness.thresholds.oven', 'Ofen-Warnung nach', 10, 180, 5, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std'}) +
    fRange('time_awareness.thresholds.iron', 'Bügeleisen-Warnung nach', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('time_awareness.thresholds.light_empty_room', 'Licht im leeren Raum nach', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fRange('time_awareness.thresholds.window_open_cold', 'Fenster offen bei Kälte nach', 30, 600, 30, {30:'30 Min',60:'1 Std',120:'2 Std',300:'5 Std',600:'10 Std'}) +
    fRange('time_awareness.thresholds.pc_no_break', 'PC-Pause erinnern nach', 60, 720, 30, {60:'1 Std',120:'2 Std',180:'3 Std',360:'6 Std',720:'12 Std'}) +
    fToggle('time_awareness.counters.coffee_machine', 'Kaffee-Zähler (zählt deine Kaffees)')
  ) +
  sectionWrap('&#128300;', 'Vorausdenken',
    fInfo('Der Assistent lernt deine Gewohnheiten und schlägt Aktionen vor — z.B. "Du machst normalerweise jetzt das Licht an".') +
    fToggle('anticipation.enabled', 'Vorausdenken aktiv') +
    fRange('anticipation.history_days', 'Lern-Zeitraum (Tage)', 7, 90, 7, {7:'1 Woche',14:'2 Wochen',30:'1 Monat',60:'2 Monate',90:'3 Monate'}) +
    fRange('anticipation.min_confidence', 'Mindest-Sicherheit', 0, 1, 0.05, {0:'Alles vorschlagen',0.3:'Niedrig',0.5:'Mittel',0.7:'Hoch',0.9:'Sehr hoch'}) +
    fRange('anticipation.check_interval_minutes', 'Prüf-Intervall', 5, 60, 5, {5:'5 Min',10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std'}) +
    fSubheading('Ab welcher Sicherheit...') +
    fRange('anticipation.thresholds.ask', '...nachfragen?', 0, 1, 0.05, {0.3:'30%',0.5:'50%',0.6:'60%',0.7:'70%',0.8:'80%'}) +
    fRange('anticipation.thresholds.suggest', '...vorschlagen?', 0, 1, 0.05, {0.5:'50%',0.6:'60%',0.7:'70%',0.8:'80%',0.9:'90%'}) +
    fRange('anticipation.thresholds.auto', '...automatisch ausführen?', 0, 1, 0.05, {0.7:'70%',0.8:'80%',0.9:'90%',0.95:'95%',1:'100%'})
  ) +
  sectionWrap('&#128218;', 'Rückkehr-Briefing',
    fInfo('Wenn du das Haus verlässt, sammelt Jarvis alle Events. Bei Rückkehr erhältst du ein kompaktes Briefing — z.B. "Während deiner Abwesenheit (2h): Jemand hat geklingelt, Waschmaschine fertig."') +
    fToggle('return_briefing.enabled', 'Rückkehr-Briefing aktiv') +
    fRange('return_briefing.max_events', 'Max. Events pro Briefing', 5, 50, 5, {5:'5',10:'10',15:'15',20:'20',30:'30',50:'50'}) +
    fRange('return_briefing.ttl_hours', 'Max. Sammel-Dauer', 4, 48, 4, {4:'4 Std',8:'8 Std',12:'12 Std',24:'1 Tag',48:'2 Tage'}) +
    fSubheading('Events im Briefing') +
    fToggle('return_briefing.event_types.doorbell', 'Tuerklingel') +
    fToggle('return_briefing.event_types.person_arrived', 'Person angekommen') +
    fToggle('return_briefing.event_types.person_left', 'Person gegangen') +
    ((getPath(S,'appliance_monitor.devices')||[]).map(d =>
      fToggle('return_briefing.event_types.'+d.key+'_done', (d.label||d.key)+' fertig')
    ).join('') || fToggle('return_briefing.event_types.washer_done', 'Waschmaschine fertig')) +
    fToggle('return_briefing.event_types.weather_warning', 'Wetter-Warnungen') +
    fToggle('return_briefing.event_types.low_battery', 'Batterie niedrig') +
    fToggle('return_briefing.event_types.maintenance_due', 'Wartung faellig') +
    fToggle('return_briefing.event_types.conditional_executed', 'Wenn-Dann-Regeln ausgeführt')
  ) +
  sectionWrap('&#129504;', 'Jarvis denkt voraus',
    fInfo('Kreuz-referenziert Wetter, Kalender, Energie und Geräte-Status — und meldet sich proaktiv. Z.B. "Es wird gleich regnen, Fenster sind noch offen."') +
    fToggle('insights.enabled', 'Insights aktiv') +
    fRange('insights.check_interval_minutes', 'Prüf-Intervall', 10, 120, 5, {10:'10 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('insights.cooldown_hours', 'Cooldown pro Insight', 1, 24, 1, {1:'1 Std',2:'2 Std',4:'4 Std',8:'8 Std',12:'12 Std',24:'1 Tag'}) +
    fSubheading('Aktive Checks') +
    fToggle('insights.checks.weather_windows', 'Regen/Sturm + offene Fenster') +
    fToggle('insights.checks.frost_heating', 'Frost + Heizung aus/Away') +
    fToggle('insights.checks.calendar_travel', 'Reise im Kalender + Alarm/Fenster/Heizung') +
    fToggle('insights.checks.energy_anomaly', 'Energie-Verbrauch über Baseline') +
    fToggle('insights.checks.away_devices', 'Abwesend + Licht/Fenster offen') +
    fToggle('insights.checks.temp_drop', 'Ungewöhnlicher Temperatur-Abfall') +
    fToggle('insights.checks.window_temp_drop', 'Fenster offen + grosse Temp-Differenz') +
    fToggle('insights.checks.calendar_weather_cross', 'Kalender-Termin + Regen/Sturm') +
    fToggle('insights.checks.comfort_contradiction', 'Heizung + offenes Fenster') +
    fSubheading('Schwellwerte') +
    fRange('insights.thresholds.frost_temp_c', 'Frost-Warnung ab', -10, 10, 1, {'-5':'-5\u00B0C',0:'0\u00B0C',2:'2\u00B0C',5:'5\u00B0C'}) +
    fRange('insights.thresholds.energy_anomaly_percent', 'Energie-Abweichung', 10, 100, 5, {10:'10%',20:'20%',30:'30%',50:'50%',100:'100%'}) +
    fRange('insights.thresholds.away_device_minutes', 'Abwesend-Hinweis nach', 30, 480, 30, {30:'30 Min',60:'1 Std',120:'2 Std',240:'4 Std',480:'8 Std'}) +
    fRange('insights.thresholds.temp_drop_degrees_per_2h', 'Temp-Abfall Schwelle', 1, 10, 1, {1:'1\u00B0C',2:'2\u00B0C',3:'3\u00B0C',5:'5\u00B0C',10:'10\u00B0C'})
  ) +
  sectionWrap('&#128722;', 'Smart Shopping',
    fInfo('Jarvis lernt dein Einkaufsverhalten: wie oft du Artikel kaufst, an welchem Wochentag du einkaufst, und welche Zutaten für Rezepte fehlen. Erinnert proaktiv wenn etwas bald alle ist.') +
    fToggle('smart_shopping.enabled', 'Smart Shopping aktiv') +
    fRange('smart_shopping.min_purchases', 'Mindest-Käufe für Prognose', 2, 10, 1, {2:'2',3:'3',5:'5',10:'10'}) +
    fRange('smart_shopping.reminder_days_before', 'Erinnerung X Tage vorher', 0, 7, 1, {0:'Am Tag',1:'1 Tag',2:'2 Tage',3:'3 Tage',7:'1 Woche'}) +
    fRange('smart_shopping.reminder_cooldown_hours', 'Erinnerungs-Cooldown', 6, 72, 6, {6:'6 Std',12:'12 Std',24:'1 Tag',48:'2 Tage',72:'3 Tage'})
  ) +
  sectionWrap('&#9889;', 'Energie-Dashboard',
    fInfo('Live-Anzeige von Solar-Ertrag, Stromverbrauch, Netz-Einspeisung und Strompreis im Dashboard. Weise die passenden HA-Sensoren zu — ohne Sensoren nutzt Jarvis eine automatische Keyword-Suche.') +
    fToggle('energy.enabled', 'Energiemanagement aktiv') +
    fSubheading('Sensor-Entities') +
    fEntityPickerSingle('energy.entities.electricity_price', 'Strompreis-Sensor', ['sensor'], 'z.B. sensor.electricity_price — liefert ct/kWh, EUR/kWh oder EUR/MWh') +
    fEntityPickerSingle('energy.entities.total_consumption', 'Verbrauchs-Sensor', ['sensor'], 'z.B. sensor.power_consumption — aktueller Verbrauch in Watt') +
    fEntityPickerSingle('energy.entities.solar_production', 'Solar-Sensor', ['sensor'], 'z.B. sensor.solar_power — aktuelle Solar-Produktion in Watt') +
    fEntityPickerSingle('energy.entities.grid_export', 'Netz-Einspeisung Sensor', ['sensor'], 'z.B. sensor.grid_export_power — Einspeisung in Watt') +
    fSubheading('Schwellwerte') +
    fRange('energy.thresholds.price_low_cent', 'Günstiger Strom unter', 5, 30, 1, {5:'5 ct',10:'10 ct',15:'15 ct',20:'20 ct',25:'25 ct',30:'30 ct'}) +
    fRange('energy.thresholds.price_high_cent', 'Teurer Strom über', 20, 60, 1, {20:'20 ct',25:'25 ct',30:'30 ct',35:'35 ct',40:'40 ct',50:'50 ct',60:'60 ct'}) +
    fRange('energy.thresholds.solar_high_watts', 'Solar-Überschuss ab', 500, 10000, 500, {500:'500 W',1000:'1 kW',2000:'2 kW',3000:'3 kW',5000:'5 kW',10000:'10 kW'}) +
    fRange('energy.thresholds.anomaly_increase_percent', 'Anomalie-Schwelle', 10, 100, 5, {10:'10%',20:'20%',30:'30%',50:'50%',100:'100%'}) +
    fSubheading('Vorhersagen') +
    fToggle('energy.price_forecast_enabled', 'Strompreis-Vorhersage') +
    fInfo('Erkennt Preis-Trends und empfiehlt flexible Lasten zu guenstigen Zeiten.') +
    fText('energy.price_entity', 'Strompreis-Entity', 'z.B. sensor.electricity_price') +
    fToggle('energy.solar_forecast_enabled', 'Solar-Vorhersage') +
    fInfo('Nutzt Wetter-Forecast um Solarertrag vorherzusagen.') +
    fText('energy.solar_entity', 'Solar-Entity', 'z.B. sensor.solar_power')
  ) +
  sectionWrap('&#129504;', 'Konversations-Gedächtnis++',
    fInfo('Jarvis merkt sich laufende Projekte, offene Fragen und erstellt Tages-Zusammenfassungen. Sage z.B. "Merke dir: Projekt Gartenhaus — Fundament ist fertig" oder "Merke dir die Frage: Wann muss die TUeV-Plakette erneuert werden?"') +
    fToggle('conversation_memory.enabled', 'Konversations-Gedächtnis aktiv') +
    fSubheading('Limits') +
    fRange('conversation_memory.max_projects', 'Maximale Projekte', 5, 50, 5, {5:'5',10:'10',15:'15',20:'20',30:'30',50:'50'}) +
    fRange('conversation_memory.max_questions', 'Maximale offene Fragen', 10, 100, 10, {10:'10',20:'20',30:'30',50:'50',100:'100'}) +
    fSubheading('Aufbewahrung') +
    fRange('conversation_memory.summary_retention_days', 'Zusammenfassungen behalten', 7, 90, 7, {7:'1 Woche',14:'2 Wochen',30:'1 Monat',60:'2 Monate',90:'3 Monate'}) +
    fRange('conversation_memory.question_ttl_days', 'Offene Fragen behalten', 3, 60, 1, {3:'3 Tage',7:'1 Woche',14:'2 Wochen',30:'1 Monat',60:'2 Monate'})
  ) +
  sectionWrap('&#127925;', 'Multi-Room Audio',
    fInfo('Erstelle Speaker-Gruppen für synchrone Wiedergabe im ganzen Haus. Sage z.B. "Spiele Jazz auf der Gruppe Erdgeschoss" oder "Erstelle eine Gruppe Party mit Wohnzimmer und Küche". Gruppen-Presets können in settings.yaml unter multi_room_audio.presets definiert werden.') +
    fToggle('multi_room_audio.enabled', 'Multi-Room Audio aktiv') +
    fToggle('multi_room_audio.use_native_grouping', 'Native Gruppierung (Sonos/Cast)') +
    fRange('multi_room_audio.max_groups', 'Maximale Gruppen', 1, 20, 1, {1:'1',5:'5',10:'10',15:'15',20:'20'}) +
    fRange('multi_room_audio.default_volume', 'Standard-Lautstärke', 5, 100, 5, {5:'5%',20:'20%',40:'40%',60:'60%',80:'80%',100:'100%'})
  ) +
  sectionWrap('&#128226;', 'Event-Handler',
    fInfo('Prioritaeten für verschiedene Event-Typen. Event-Typen mit höherer Prioritaet durchbrechen "Nicht stören". In settings.yaml unter proactive.event_handlers anpassbar.') +
    fTextarea('proactive.event_handlers', 'Event-Handler (JSON)', 'Format: {"event_name": {"priority": "critical|high|medium|low", "description": "..."}}')
  ) +
  sectionWrap('&#128065;', 'Spontane Beobachtungen',
    fInfo('Jarvis macht 1-2x taeglich unaufgeforderte, interessante Bemerkungen — z.B. "Heute verbrauchen wir 20% weniger Energie als letzte Woche" oder "Die Waschmaschine lief 7 Mal diese Woche — Rekord!"') +
    fToggle('spontaneous.enabled', 'Spontane Beobachtungen aktiv') +
    fRange('spontaneous.max_per_day', 'Maximal pro Tag', 0, 5, 1, {0:'Aus',1:'1x',2:'2x',3:'3x',5:'5x'}) +
    fRange('spontaneous.min_interval_hours', 'Mindestabstand', 1, 8, 1, {1:'1 Std',2:'2 Std',3:'3 Std',4:'4 Std',6:'6 Std',8:'8 Std'}) +
    fNum('spontaneous.active_hours.start', 'Aktiv ab (Uhr)', 0, 23, 1) +
    fNum('spontaneous.active_hours.end', 'Aktiv bis (Uhr)', 0, 23, 1) +
    fSubheading('Aktive Checks') +
    fToggle('spontaneous.checks.energy_comparison', 'Energie-Vergleich mit Vorwoche') +
    fToggle('spontaneous.checks.streak', 'Wetter-Streaks & Fun Facts') +
    fToggle('spontaneous.checks.usage_record', 'Nutzungs-Rekorde') +
    fToggle('spontaneous.checks.device_milestone', 'Geräte-Meilensteine') +
    fToggle('spontaneous.checks.house_efficiency', 'Haus-Effizienz Beobachtungen')
  );
}

// ---- Benachrichtigungen (Silence Matrix + Volume Matrix) ----
function renderNotifications() {
  const activities = [
    {key:'sleeping', label:'Schlafen', icon:'&#128164;'},
    {key:'in_call',  label:'Im Telefonat', icon:'&#128222;'},
    {key:'watching', label:'TV/Film', icon:'&#127916;'},
    {key:'focused',  label:'Konzentriert', icon:'&#128187;'},
    {key:'guests',   label:'Gäste da', icon:'&#128101;'},
    {key:'relaxing', label:'Entspannt', icon:'&#128524;'},
    {key:'away',     label:'Abwesend', icon:'&#127968;'},
  ];
  const urgencies = ['critical','high','medium','low'];
  const urgencyLabels = {critical:'Kritisch',high:'Hoch',medium:'Mittel',low:'Niedrig'};
  const deliveryOpts = [
    {v:'tts_loud',  l:'Laut (TTS)'},
    {v:'tts_quiet', l:'Leise (TTS)'},
    {v:'led_blink', l:'Nur LED'},
    {v:'suppress',  l:'Unterdrücken'},
  ];
  // Defaults (hardcoded, matching activity.py)
  const defaultSilence = {
    sleeping:  {critical:'tts_loud',high:'led_blink',medium:'suppress',low:'suppress'},
    in_call:   {critical:'tts_loud',high:'tts_quiet',medium:'suppress',low:'suppress'},
    watching:  {critical:'tts_loud',high:'led_blink',medium:'suppress',low:'suppress'},
    focused:   {critical:'tts_loud',high:'tts_quiet',medium:'tts_quiet',low:'suppress'},
    guests:    {critical:'tts_loud',high:'tts_quiet',medium:'tts_quiet',low:'suppress'},
    relaxing:  {critical:'tts_loud',high:'tts_loud',medium:'tts_quiet',low:'suppress'},
    away:      {critical:'tts_loud',high:'suppress',medium:'suppress',low:'suppress'},
  };
  const defaultVolume = {
    sleeping:  {critical:0.6,high:0.2,medium:0.15,low:0.1},
    in_call:   {critical:0.3,high:0.2,medium:0.0,low:0.0},
    watching:  {critical:0.7,high:0.4,medium:0.3,low:0.2},
    focused:   {critical:0.8,high:0.5,medium:0.4,low:0.3},
    guests:    {critical:0.8,high:0.5,medium:0.4,low:0.3},
    relaxing:  {critical:1.0,high:0.8,medium:0.7,low:0.5},
    away:      {critical:1.0,high:0.0,medium:0.0,low:0.0},
  };

  // Build silence matrix table
  let silenceRows = '';
  for (const act of activities) {
    let cells = `<td class="nm-label">${act.icon} ${act.label}</td>`;
    for (const urg of urgencies) {
      const path = `activity.silence_matrix.${act.key}.${urg}`;
      const val = getPath(S, path) ?? defaultSilence[act.key][urg];
      let opts = deliveryOpts.map(o =>
        `<option value="${o.v}" ${val===o.v?'selected':''}>${o.l}</option>`
      ).join('');
      cells += `<td><select class="nm-select" data-path="${path}" data-default="${defaultSilence[act.key][urg]}">${opts}</select></td>`;
    }
    silenceRows += `<tr>${cells}</tr>`;
  }
  const silenceTable = `<div class="nm-table-wrap"><table class="nm-table">
    <thead><tr><th></th>${urgencies.map(u=>`<th>${urgencyLabels[u]}</th>`).join('')}</tr></thead>
    <tbody>${silenceRows}</tbody></table></div>`;

  // Build volume matrix table
  let volumeRows = '';
  for (const act of activities) {
    let cells = `<td class="nm-label">${act.icon} ${act.label}</td>`;
    for (const urg of urgencies) {
      const path = `activity.volume_matrix.${act.key}.${urg}`;
      const val = getPath(S, path) ?? defaultVolume[act.key][urg];
      const pct = Math.round((val ?? 0) * 100);
      cells += `<td><input type="range" class="nm-vol" min="0" max="100" step="5" value="${pct}"
        data-path="${path}" data-default="${defaultVolume[act.key][urg]}"
        oninput="this.nextElementSibling.textContent=this.value+'%'"
        ><span class="nm-vol-label">${pct}%</span></td>`;
    }
    volumeRows += `<tr>${cells}</tr>`;
  }
  const volumeTable = `<div class="nm-table-wrap"><table class="nm-table">
    <thead><tr><th></th>${urgencies.map(u=>`<th>${urgencyLabels[u]}</th>`).join('')}</tr></thead>
    <tbody>${volumeRows}</tbody></table></div>`;

  return sectionWrap('&#128263;', 'Stille-Matrix (Zustellung pro Aktivität)',
    fInfo('Bestimmt WIE Benachrichtigungen zugestellt werden — abhaengig von deiner aktuellen Aktivität und der Dringlichkeit der Meldung. Kritische Meldungen (Sicherheit, Notfall) sollten immer hörbar sein.') +
    silenceTable +
    `<div style="margin:8px 0 4px;font-size:11px;color:var(--text-muted);">Geänderte Zellen werden beim Verlassen automatisch gespeichert. Nur Abweichungen vom Standard werden gespeichert.</div>`
  ) +
  sectionWrap('&#128266;', 'Lautstärke-Matrix',
    fInfo('Bestimmt die Lautstärke von TTS-Durchsagen — abhaengig von Aktivität und Dringlichkeit. Nachts wird automatisch zusätzlich reduziert.') +
    volumeTable
  ) +
  sectionWrap('&#128276;', 'Benachrichtigungskanaele',
    fInfo('Welche Kanaele soll der Assistent für Benachrichtigungen nutzen? Kanaele können einzeln konfiguriert werden.') +
    '<div id="notifyChannelsContainer" style="color:var(--text-muted);font-size:12px;">Wird geladen...</div>' +
    '<div style="margin-top:10px;"><button class="btn btn-primary" style="font-size:12px;" onclick="saveNotifyChannels()">Kanaele speichern</button></div>'
  ) +
  sectionWrap('&#128164;', 'Stille-Keywords',
    fInfo('Wörter die eine Aktivität erkennen und den "Nicht stören"-Modus auslösen. Ein Wort pro Zeile.') +
    fTextarea('activity.silence_keywords.watching', 'Film/TV schauen', 'z.B. "filmabend", "netflix", "serie schauen"') +
    fTextarea('activity.silence_keywords.focused', 'Konzentriert/Meditieren', 'z.B. "meditation", "fokus", "nicht stören"') +
    fTextarea('activity.silence_keywords.sleeping', 'Schlafen', 'z.B. "gute nacht", "ich geh schlafen"')
  );
}

// Notification Matrix: nur geänderte Werte in S speichern (sparse)
function _nmSync() {
  document.querySelectorAll('.nm-select').forEach(sel => {
    const path = sel.dataset.path;
    const def = sel.dataset.default;
    if (sel.value !== def) {
      setPath(S, path, sel.value);
    } else {
      // Nicht-geänderte Werte entfernen (damit nur Overrides gespeichert werden)
      _nmRemovePath(path);
    }
  });
  document.querySelectorAll('.nm-vol').forEach(range => {
    const path = range.dataset.path;
    const def = parseFloat(range.dataset.default);
    const val = parseInt(range.value) / 100;
    if (Math.abs(val - def) > 0.01) {
      setPath(S, path, val);
    } else {
      _nmRemovePath(path);
    }
  });
}
function _nmRemovePath(path) {
  // Entferne einen einzelnen Pfad aus S (z.B. activity.silence_matrix.watching.high)
  const parts = path.split('.');
  let cur = S;
  const stack = [];
  for (let i = 0; i < parts.length - 1; i++) {
    if (!cur || typeof cur !== 'object') return;
    stack.push({obj: cur, key: parts[i]});
    cur = cur[parts[i]];
  }
  if (cur && typeof cur === 'object') {
    delete cur[parts[parts.length - 1]];
  }
  // Leere Eltern-Objekte aufraemen
  for (let i = stack.length - 1; i >= 0; i--) {
    const {obj, key} = stack[i];
    if (obj[key] && typeof obj[key] === 'object' && Object.keys(obj[key]).length === 0) {
      delete obj[key];
    }
  }
}

// Hook nm-select/nm-vol change events into auto-save
document.addEventListener('change', (e) => {
  if (e.target.classList.contains('nm-select') || e.target.classList.contains('nm-vol')) {
    _nmSync();
    scheduleAutoSave();
  }
});
document.addEventListener('input', (e) => {
  if (e.target.classList.contains('nm-vol')) {
    _nmSync();
    scheduleAutoSave();
  }
});

// ---- Jarvis-Features (Feature 1-11) ----
function renderJarvisFeatures() {
  return sectionWrap('&#128172;', 'Progressive Antworten',
    fInfo('Jarvis "denkt laut" — sendet Zwischen-Meldungen während der Verarbeitung statt still zu arbeiten. Z.B. "Ich prüfe den Hausstatus..." oder "Einen Moment, ich überlege..."') +
    fToggle('progressive_responses.enabled', 'Progressive Antworten aktiv') +
    fToggle('progressive_responses.show_context_step', '"Ich prüfe den Hausstatus..." anzeigen') +
    fToggle('progressive_responses.show_thinking_step', '"Einen Moment, ich überlege..." anzeigen') +
    fToggle('progressive_responses.show_action_step', '"Ich führe das aus..." anzeigen')
  ) +
  sectionWrap('&#129504;', 'MCU-Intelligenz',
    fInfo('Kern-Features die Jarvis wie MCU-JARVIS denken lassen: Proaktives Mitdenken, Ingenieur-Diagnosen, Kreuz-Referenzierung, Anomalie-Erkennung und implizite Befehle. Jedes Feature kann einzeln deaktiviert werden. Änderungen wirken sofort.') +
    fToggle('mcu_intelligence.proactive_thinking', 'Proaktives Mitdenken') +
    fToggle('mcu_intelligence.engineering_diagnosis', 'Ingenieur-Diagnose-Stil') +
    fToggle('mcu_intelligence.cross_references', 'Kreuz-Referenzierung (Haus-Daten)') +
    fToggle('mcu_intelligence.anomaly_detection', 'Anomalie-Erkennung im Kontext') +
    fToggle('mcu_intelligence.implicit_commands', 'Implizite Befehle ("Bin da", "Alles klar?")')
  ) +
  sectionWrap('&#127917;', 'MCU-Persönlichkeit',
    fInfo('Persönlichkeits-Features die Jarvis mehr wie MCU-JARVIS wirken lassen: natürliche Rückbezüge auf vergangene Gespräche, Lern-Bestätigungen, Vorhersagen mit Charakter, Wetter-Kommentare, Selbst-Bewusstsein und proaktive Persönlichkeit. Änderungen wirken sofort.') +
    fSubheading('Konversations-Rückbezüge') +
    fToggle('conversation_callbacks.enabled', 'Rückbezüge auf vergangene Gespräche') +
    fSelect('conversation_callbacks.personality_style', 'Referenz-Stil', [{v:'beiläufig',l:'Beiläufig (trockener Humor)'},{v:'direkt',l:'Direkt (sachlich)'}]) +
    fSubheading('Lern-Bestätigung') +
    fToggle('learning_acknowledgment.enabled', '"Ich habe mir gemerkt..." Meldungen') +
    fRange('learning_acknowledgment.max_per_session', 'Max. pro Gespräch', 1, 3, 1, {1:'1x',2:'2x',3:'3x'}) +
    fSubheading('Vorhersage-Persönlichkeit') +
    fToggle('prediction_personality.enabled', 'Vorhersagen mit Charakter') +
    fToggle('prediction_personality.show_confidence', 'Konfidenz in Prozent anzeigen') +
    fSubheading('Wetter in Persönlichkeit') +
    fToggle('weather_personality.enabled', 'Wetter beiläufig einflechten') +
    fSelect('weather_personality.intensity', 'Intensität', [{v:'subtil',l:'Subtil (nur Extreme)'},{v:'normal',l:'Normal'},{v:'ausführlich',l:'Ausführlich'}]) +
    fSubheading('Selbst-Bewusstsein &amp; Meta-Humor') +
    fToggle('self_awareness.enabled', 'Selbst-Bewusstsein aktiv') +
    fToggle('self_awareness.meta_humor', 'Meta-Humor über eigene Algorithmen') +
    fSubheading('Proaktive Persönlichkeit') +
    fToggle('proactive_personality.enabled', 'Briefings mit Charakter') +
    fToggle('proactive_personality.sarcasm_in_notifications', 'Trockener Humor in Meldungen')
  ) +
  sectionWrap('&#129505;', 'Echte Empathie',
    fInfo('Jarvis zeigt echtes Verständnis — nicht durch Therapeuten-Floskeln, sondern durch Beobachtung und Handeln. "Du klingst angespannt." statt "Ich verstehe wie du dich fuehlst." Wie MCU-JARVIS: erkennen, beiläufig ansprechen, praktisch helfen.') +
    fToggle('empathy.enabled', 'Echte Empathie aktiv') +
    fSelect('empathy.intensity', 'Intensität', [{v:'subtil',l:'Subtil (nur starke Emotionen)'},{v:'normal',l:'Normal'},{v:'ausführlich',l:'Ausführlich (aktiv mitfühlend)'}]) +
    fToggle('empathy.mood_acknowledgment', 'Stimmung beiläufig ansprechen') +
    fToggle('empathy.practical_offers', 'Praktische Hilfe anbieten') +
    fToggle('empathy.good_mood_mirror', 'Gute Stimmung spiegeln')
  ) +
  sectionWrap('&#128274;', 'Charakter-Schutz',
    fInfo('Verhindert dass das LLM aus der JARVIS-Rolle fällt und typische KI-Floskeln verwendet. Dreistufiger Schutz: Prompt-Anker am Ende, struktureller Post-Filter und automatischer Character-Retry.') +
    fToggle('character_lock.enabled', 'Charakter-Lock aktiviert') +
    fToggle('character_lock.closing_anchor', 'Prompt-Anker (Erinnerung am Prompt-Ende)') +
    fToggle('character_lock.structural_filter', 'Struktureller Filter (Listen/Aufzaehlungen entfernen)') +
    fToggle('character_lock.character_retry', 'Automatischer Retry bei LLM-Durchbruch') +
    fRange('character_lock.retry_threshold', 'Retry-Empfindlichkeit', 1, 5, 1, ['Sehr empfindlich','','Normal','','Nur bei starkem Bruch']) +
    '<div id="charBreakStats" style="margin-top:12px;padding:10px;background:var(--bg-primary);border-radius:var(--radius-sm);border:1px solid var(--border-color);font-size:12px;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
        '<span style="font-weight:600;">Charakter-Brueche (7 Tage)</span>' +
        '<button class="btn btn-secondary btn-sm" onclick="loadCharBreakStats()" style="padding:2px 8px;min-width:auto;font-size:11px;">Laden</button>' +
      '</div>' +
      '<div id="charBreakStatsContent" style="color:var(--text-muted);">Klicke "Laden" für aktuelle Statistiken.</div>' +
    '</div>'
  ) +
  sectionWrap('&#129504;', 'Persoenlichkeits-Kern',
    fInfo('Fundamentale Persoenlichkeits-Bausteine. Jeder Baustein kann einzeln deaktiviert werden — aber Vorsicht: Jarvis verliert dadurch Charakter.') +
    fToggle('core_identity.enabled', 'Kern-Identitaet (Butler-Instinkt, Situationsbewusstsein)') +
    fToggle('confidence_style.enabled', 'Confidence-Stil ("Wenn ich richtig liege...")') +
    fToggle('dramatic_timing.enabled', 'Dramatisches Timing (Pausen, Betonung)') +
    fToggle('situative_improvisation.enabled', 'Situative Improvisation') +
    fToggle('creative_problem_solving.enabled', 'Kreative Problemloesung') +
    fToggle('narrative_arcs.enabled', 'Narrative Boegen (Geschichten über mehrere Gespraeche)') +
    fToggle('inner_state.enabled', 'Innerer Zustand (Emotionale Intelligenz)')
  ) +
  sectionWrap('&#128374;', 'Geräte-Persönlichkeit',
    fInfo('Geräte bekommen Spitznamen in proaktiven Meldungen — z.B. "Die Fleissige im Keller hat ihren Job erledigt" statt "Waschmaschine ausgeschaltet".') +
    fToggle('device_narration.enabled', 'Geräte-Persönlichkeit aktiv') +
    fTextarea('device_narration.custom_nicknames', 'Eigene Spitznamen', 'JSON: {"waschmaschine": "Frau Waschkraft", "saugroboter": "Robbie"}')
  ) +
  sectionWrap('&#9889;', 'Geräte-Fertig-Erkennung',
    fInfo('Jarvis erkennt anhand des Stromverbrauchs wann Geräte fertig sind. Das Geraet muss für die eingestellte Wartezeit unter dem Idle-Schwellwert bleiben bevor "fertig" gemeldet wird — das verhindert Fehlalarme bei Zwischenphasen (z.B. zwischen Waschen und Schleudern). Du kannst beliebige Geräte hinzufügen.') +
    fSubheading('Globale Schwellwerte (Fallback)') +
    fInfo('Diese Werte gelten nur wenn kein geräte-spezifisches Power-Profil definiert ist.') +
    fRange('appliance_monitor.power_running_threshold', 'Laufend ab (Watt)', 5, 50, 5, {5:'5W',10:'10W',15:'15W',20:'20W',50:'50W'}) +
    fRange('appliance_monitor.power_idle_threshold', 'Idle unter (Watt)', 1, 20, 1, {1:'1W',2:'2W',3:'3W',5:'5W',10:'10W',20:'20W'}) +
    fRange('appliance_monitor.idle_confirm_minutes', 'Wartezeit vor Meldung', 1, 15, 1, {1:'1 Min',2:'2',3:'3',5:'5 Min',10:'10',15:'15 Min'}) +
    fSubheading('Überwachte Geräte') +
    '<div id="applianceDevicesContainer"></div>' +
    '<button class="btn btn-sm" onclick="addApplianceDevice()" style="margin-top:8px;">+ Geraet hinzufügen</button>' +
    fSubheading('Geräte-spezifische Power-Profile') +
    fInfo('Pro Gerät können eigene Schwellwerte definiert werden. Running = ab diesem Watt gilt das Gerät als laufend, Idle = darunter als idle, Hysteresis = Puffer gegen Schwankungen, Confirm = Wartezeit vor Meldung.') +
    '<div id="powerProfilesContainer"></div>'
  ) +
  sectionWrap('&#9888;', 'Daten-basierter Widerspruch',
    fInfo('Vor einer Aktion prüft Jarvis Live-Daten und warnt konkret — z.B. "Heizung auf 25? Das Bad-Fenster ist offen." Aktion wird trotzdem ausgeführt, aber die Warnung erwähnt.') +
    fToggle('pushback.enabled', 'Widerspruch aktiv') +
    fSubheading('Aktive Checks') +
    fToggle('pushback.checks.open_windows', 'Fenster offen bei Heizung') +
    fToggle('pushback.checks.empty_room', 'Leerer Raum bei Heizung/Licht') +
    fToggle('pushback.checks.daylight', 'Tageslicht bei Licht einschalten') +
    fToggle('pushback.checks.storm_warning', 'Sturmwarnung bei Rolladen öffnen') +
    fToggle('pushback.checks.unnecessary_heating', 'Heizung bei warmem Wetter') +
    fSubheading('Eskalations-Stufen') +
    fInfo('Wie MCU-JARVIS: Warnungen werden je nach Schwere anders formuliert. Stufe 1 = beiläufig ("Übrigens..."), Stufe 2 = Einwand ("Darf ich anmerken..."), Stufe 3 = Sorge ("Das würde ich nicht empfehlen."), Stufe 4 = Resignation bei wiederholter Warnung ("Wie du wuenschst.").') +
    fToggle('pushback.escalation_enabled', 'Eskalations-Stufen aktiv') +
    fRange('pushback.resignation_ttl_seconds', 'Wiederholungs-Erkennung', 300, 3600, 300, {300:'5 Min',600:'10 Min',900:'15 Min',1800:'30 Min',3600:'1 Std'})
  ) +
  sectionWrap('&#127925;', 'Smart DJ',
    fInfo('Jarvis empfiehlt kontextbewusst Musik basierend auf Stimmung, Aktivität und Tageszeit. Sag z.B. "Spiel mal was Passendes" — Jarvis wählt das Genre und lernt aus deinem Feedback.') +
    fToggle('music_dj.enabled', 'Smart DJ aktiv') +
    fRange('music_dj.default_volume', 'Standard-Lautstärke', 10, 100, 5, {10:'10%',20:'20%',30:'30%',40:'40%',50:'50%',60:'60%',70:'70%',80:'80%',100:'100%'}) +
    fToggle('music_dj.proactive_enabled', 'Proaktive Musikvorschläge') +
    fRange('music_dj.cooldown_minutes', 'Mindestabstand Vorschläge', 10, 120, 10, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fTextarea('music_dj.custom_queries', 'Eigene Genre-Queries', 'JSON: {"party_hits": "meine party playlist", "focus_lofi": "deep focus music"}')
  ) +
  sectionWrap('&#128218;', 'Erinnerungen & Beziehungen',
    fInfo('Langzeitgedächtnis, Beziehungsmodell und soziales Verhalten. Jarvis merkt sich besondere Momente, entwickelt Humor weiter, zeigt Besorgnis und fragt bei ungewöhnlichem Verhalten nach.') +
    fSubheading('Remember When — Erinnerungen') +
    fToggle('memorable_interactions.enabled', 'Erinnerungen aktiv', 'Referenziert frühere Interaktionen bei passenden Gelegenheiten. Standard: an') +
    fNum('memorable_interactions.max_entries', 'Max. gespeicherte Erinnerungen', 5, 100, 5, 'Standard: 50') +
    fNum('memorable_interactions.ttl_days', 'Speicherdauer (Tage)', 7, 365, 7, 'Standard: 90') +
    fSubheading('Beziehungsmodell') +
    fToggle('relationship_model.enabled', 'Beziehungsmodell aktiv', 'Inside Jokes, Kommunikationsstil und Meilensteine pro Person. Standard: an') +
    fSubheading('Running Gag Evolution') +
    fToggle('running_gag_evolution.enabled', 'Gag-Evolution aktiv', 'Witze werden weiterentwickelt statt wiederholt. Standard: an') +
    fSubheading('Eskalierende Besorgnis') +
    fToggle('escalating_concern.enabled', 'Eskalierende Besorgnis aktiv', 'Warnungen werden ernster wenn ignoriert (3 Stufen). Standard: an') +
    fSubheading('Neugier-Fragen') +
    fToggle('curiosity.enabled', 'Neugier-Fragen aktiv', 'Fragt bei ungewöhnlichem Verhalten vorsichtig nach. Standard: an') +
    fNum('curiosity.max_daily', 'Max. Fragen pro Tag', 1, 5, '1', 'Standard: 2') +
    fSubheading('Kontextuelles Schweigen') +
    fToggle('contextual_silence.enabled', 'Kontextuelles Schweigen aktiv', 'Passt Antwort-Stil an Aktivität an (Film=kurz, Nacht=flüstern, Gäste=diskret). Standard: an')
  ) +
  sectionWrap('&#128269;', 'Situations-Modell & Erweitert',
    fInfo('Hausstatus-Tracking, Selbst-Lernen und Tool-Optimierung für intelligentere Antworten.') +
    fSubheading('Situations-Modell') +
    fToggle('situation_model.enabled', 'Situations-Modell aktiviert', 'Merkt sich Hausstatus und erwähnt Änderungen beiläufig. Standard: an') +
    fRange('situation_model.min_pause_minutes', 'Mindest-Pause zwischen Deltas (Min)', 5, 120, 5) +
    fRange('situation_model.max_changes', 'Max. gemeldete Änderungen', 1, 10, 1) +
    fRange('situation_model.temp_threshold', 'Temperatur-Schwelle (°C)', 1, 5, 0.5) +
    fSubheading('Proaktives Selbst-Lernen') +
    fToggle('self_learning.enabled', 'Selbst-Lernen aktiv', 'Erkennt Wissenslücken und merkt sich Fragen für spätere Nachforschung. Standard: an') +
    fNum('self_learning.cooldown_minutes', 'Cooldown (Minuten)', 10, 120, 10, 'Standard: 30') +
    fSubheading('JSON-Modus für Tools') +
    fToggle('json_mode_tools.enabled', 'JSON-Modus aktiv', 'JSON-Output bei Ollama Tool-Calls für zuverlässigere Gerätesteuerung. Standard: an')
  );
}

// ---- Koch-Assistent (aus Routinen ausgelagert) ----
function renderCooking() {
  return sectionWrap('&#127859;', 'Koch-Assistent',
    fInfo('Der Assistent kann dir Rezepte vorschlagen und beim Kochen helfen — Schritt für Schritt mit Timer.') +
    fToggle('cooking.enabled', 'Koch-Assistent aktiv') +
    fSelect('cooking.language', 'Rezept-Sprache', [{v:'de',l:'Deutsch'},{v:'en',l:'English'}]) +
    fRange('cooking.default_portions', 'Standard-Portionen', 1, 12, 1) +
    fRange('cooking.max_steps', 'Max. Schritte pro Rezept', 3, 30, 1) +
    fRange('cooking.max_tokens', 'Rezept-Detailgrad', 256, 4096, 256, {256:'Kurz',512:'Normal',1024:'Ausführlich',2048:'Sehr ausführlich',4096:'Maximum'}) +
    fToggle('cooking.timer_notify_tts', 'Timer-Erinnerungen per Sprache')
  );
}

// ---- Werkstatt-Modus ----
function renderWorkshop() {
  return sectionWrap('&#128295;', 'Werkstatt-Modus',
    fInfo('J.A.R.V.I.S. als Werkstatt-Ingenieur: Reparaturen, Elektronik, 3D-Druck, Robotik.') +
    fToggle('workshop.enabled', 'Werkstatt-Modus aktiv') +
    fText('workshop.workshop_room', 'Werkstatt-Raum (HA)', 'Name des Raums in Home Assistant für Sensor-Daten') +
    fToggle('workshop.auto_safety_check', 'Auto-Sicherheits-Check') +
    fToggle('workshop.proactive_suggestions', 'Proaktive Vorschläge')
  ) +
  sectionWrap('&#128424;', '3D-Drucker',
    fInfo('Verbindung zu deinem 3D-Drucker über Home Assistant. Standard: Monitor-Intervall 30 Sek.') +
    fToggle('workshop.printer_3d.enabled', '3D-Drucker aktiviert') +
    fText('workshop.printer_3d.entity_prefix', 'Entity-Prefix', 'z.B. octoprint, bambu') +
    fToggle('workshop.printer_3d.auto_monitor', 'Auto-Monitoring') +
    fNum('workshop.printer_3d.monitor_interval_seconds', 'Monitor-Intervall (Sek.)', 10, 300, 10)
  ) +
  sectionWrap('&#129302;', 'Roboterarm',
    fInfo('Steuerung eines Roboterarms über eine REST-API. Standard: Max. Geschwindigkeit 50%, Idle-Timeout 5 Min.') +
    fToggle('workshop.robot_arm.enabled', 'Arm aktiviert') +
    fText('workshop.robot_arm.url', 'Arm URL', 'z.B. http://192.168.1.100') +
    fRange('workshop.robot_arm.max_speed', 'Max. Geschwindigkeit (%)', 10, 100, 5) +
    fToggle('workshop.robot_arm.home_on_idle', 'Home bei Idle') +
    fNum('workshop.robot_arm.idle_timeout_minutes', 'Idle-Timeout (Min.)', 1, 30, 1)
  ) +
  sectionWrap('&#128225;', 'MQTT',
    fInfo('MQTT-Broker-Verbindung für Werkstatt-Geräte (ESP32, Arduino etc.). Standard: Port 1883, Topic-Prefix workshop/') +
    fToggle('workshop.mqtt.enabled', 'MQTT aktiviert') +
    fText('workshop.mqtt.broker', 'Broker-Adresse', 'z.B. 192.168.1.1') +
    fNum('workshop.mqtt.port', 'Port', 1, 65535, 1) +
    fText('workshop.mqtt.topic_prefix', 'Topic-Prefix', 'z.B. workshop/')
  ) +
  sectionWrap('&#128247;', 'Objekt-Scanner & Kamera',
    fInfo('Nutze Kameras zur Objekterkennung in der Werkstatt. Bauteile scannen, Beschaedigungen erkennen, Teilenummern lesen. Kamera-Grundkonfig unter Sicherheit > Kameras & Vision.') +
    fText('workshop.scan_camera', 'Standard-Kamera für Werkstatt', 'Name aus der Kamera-Zuordnung, z.B. werkstatt') +
    fToggle('workshop.scan_auto_ocr', 'Automatisch OCR bei Scan ausführen')
  ) +
  '<div style="margin-top:16px;"><a href="/workshop/" target="_blank" style="color:var(--accent);text-decoration:none;font-size:13px;">Workshop-HUD öffnen &#8599;</a></div>';
}

/// ---- Tab 8: Sicherheit & Erweitert ----
function renderSecurity() {
  const hMode = getPath(S, 'heating.mode') || 'room_thermostat';
  const isCurve = hMode === 'heating_curve';

  return sectionWrap('&#128187;', 'Dashboard & PIN',
    fInfo('Der Zugang zum Dashboard ist mit einer PIN geschuetzt. Der Recovery-Key wird benötigt wenn du die PIN vergisst.') +
    '<div class="form-group"><label>PIN-Schutz</label>' +
    '<p style="font-size:12px;color:var(--success);margin-bottom:8px;">PIN ist gesetzt und aktiv</p>' +
    '<p style="font-size:11px;color:var(--text-muted);margin-bottom:12px;">PIN ändern: "PIN vergessen?" auf dem Login-Screen nutzen.</p></div>' +
    '<div class="form-group"><label>Recovery-Key</label>' +
    '<p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">Falls du deine PIN vergisst, brauchst du diesen Key zum Zurücksetzen. Sicher aufbewahren!</p>' +
    '<div style="display:flex;gap:8px;align-items:center;">' +
    '<input type="text" id="settingsRecoveryKey" readonly style="flex:1;font-family:var(--mono);font-size:14px;letter-spacing:2px;text-align:center;" value="Versteckt — Klicke Generieren" />' +
    '<button class="btn btn-primary" onclick="regenerateRecoveryKey()" style="white-space:nowrap;">Neu generieren</button>' +
    '</div>' +
    '<p style="font-size:11px;color:var(--danger);margin-top:6px;">Nach dem Generieren wird der Key nur EINMAL angezeigt. Notiere ihn sofort!</p>' +
    '</div>'
  ) +
  sectionWrap('&#128274;', 'Sicherheit',
    fInfo('Welche Aktionen brauchen eine Bestätigung? Und welche Temperatur-Grenzen gelten?') +
    fChipSelect('security.require_confirmation', 'Bestätigung erforderlich für', [
      {v:'alarm_disarm',l:'Alarm deaktivieren'},
      {v:'alarm_arm',l:'Alarm aktivieren'},
      {v:'lock_unlock',l:'Türschloss öffnen'},
      {v:'garage_open',l:'Garage öffnen'},
      {v:'heating_off',l:'Heizung ausschalten'},
      {v:'all_lights_off',l:'Alle Lichter aus'},
      {v:'cover_open',l:'Rolladen öffnen'},
      {v:'camera_disable',l:'Kamera deaktivieren'},
      {v:'automation_delete',l:'Automation loeschen'}
    ]) +
    (!isCurve ?
      fRange('security.climate_limits.min', 'Temperatur Min (°C)', 5, 25, 0.5) +
      fRange('security.climate_limits.max', 'Temperatur Max (°C)', 20, 35, 0.5)
    : fInfo('Im Heizkurven-Modus gelten die Offset-Grenzen (Räume &rarr; Heizung).')
    ) +
    fSubheading('Pushback-Verhalten') +
    fInfo('Pushback sind Warnungen wenn eine Aktion im Kontext problematisch ist (z.B. "Heizung an bei offenem Fenster"). Lernfunktion: Wenn du eine Warnung oft ignorierst, wird sie seltener angezeigt.') +
    fToggle('pushback.learning_enabled', 'Pushback-Lernfunktion') +
    fRange('pushback.suppress_after_overrides', 'Unterdruecken nach X Overrides', 3, 20, 1,
      {3:'3',5:'5 (Standard)',10:'10',15:'15',20:'20'}) +
    fRange('pushback.suppress_duration_days', 'Unterdrueckungsdauer (Tage)', 7, 90, 7,
      {7:'1 Woche',14:'2 Wochen',30:'1 Monat (Standard)',60:'2 Monate',90:'3 Monate'})
  ) +
  sectionWrap('&#128273;', 'API Key (Netzwerk-Schutz)',
    fInfo('Schuetzt die Assistant-API gegen unbefugte Netzwerkzugriffe. Diesen Key im HA-Addon und in der HA-Integration eintragen, DANN Prüfung aktivieren.') +
    '<div class="form-group" style="margin-bottom:12px;">' +
    '<label style="display:flex;align-items:center;gap:8px;cursor:pointer;">' +
    '<input type="checkbox" id="apiKeyEnforcement" onchange="toggleApiKeyEnforcement(this.checked)" style="width:18px;height:18px;" />' +
    '<span>API Key Prüfung aktiv</span>' +
    '</label>' +
    '<p id="apiKeyEnforcementHint" style="font-size:11px;color:var(--text-secondary);margin-top:4px;"></p>' +
    '</div>' +
    '<div class="form-group"><label>Aktueller API Key</label>' +
    '<div style="display:flex;gap:8px;align-items:center;">' +
    '<input type="text" id="apiKeyDisplay" readonly style="flex:1;font-family:monospace;font-size:12px;" value="Wird geladen..." />' +
    '<button onclick="copyApiKey()" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg-card);cursor:pointer;font-size:12px;">Kopieren</button>' +
    '</div></div>' +
    '<div style="margin-top:8px;"><button onclick="regenerateApiKey()" style="padding:6px 12px;border:1px solid var(--danger);border-radius:6px;background:transparent;color:var(--danger);cursor:pointer;font-size:12px;">Key neu generieren</button>' +
    '<span style="font-size:11px;color:var(--text-secondary);margin-left:8px;">Achtung: Addon + HA-Integration müssen danach aktualisiert werden!</span></div>'
  ) +
  sectionWrap('&#128272;', 'Vertrauensstufen',
    fInfo('Standard-Vertrauensstufe für neue Personen und was Gäste/Besitzer dürfen.') +
    fSelect('trust_levels.default', 'Standard für neue Personen', [
      {v:0,l:'Gast (eingeschraenkt)'},
      {v:1,l:'Mitbewohner (normal)'},
      {v:2,l:'Besitzer (voll)'}
    ]) +
    fChipSelect('trust_levels.guest_allowed_actions', 'Gäste dürfen', [
      {v:'light_control',l:'Licht steuern'},
      {v:'climate_control',l:'Temperatur ändern'},
      {v:'media_control',l:'Musik/TV steuern'},
      {v:'cover_control',l:'Rolladen steuern'},
      {v:'scene_activate',l:'Szenen aktivieren'},
      {v:'timer_set',l:'Timer stellen'},
      {v:'weather_query',l:'Wetter fragen'},
      {v:'smalltalk',l:'Smalltalk'}
    ]) +
    fChipSelect('trust_levels.security_actions', 'Nur Besitzer dürfen', [
      {v:'alarm_control',l:'Alarmanlage'},
      {v:'lock_control',l:'Tuerschlösser'},
      {v:'camera_control',l:'Kameras'},
      {v:'garage_control',l:'Garage'},
      {v:'automation_edit',l:'Automationen bearbeiten'},
      {v:'settings_change',l:'Einstellungen ändern'},
      {v:'person_manage',l:'Personen verwalten'},
      {v:'system_restart',l:'System neustarten'}
    ]) +
    fSubheading('Erweitert') +
    fTextarea('trust_levels.persons', 'Trust pro Person (JSON)', 'Format: {"max": 2, "anna": 1, "gast": 0}') +
    fTextarea('trust_levels.room_restrictions', 'Raum-Beschraenkungen (JSON)', 'Format: {"gast": ["wohnzimmer", "kueche"]} — nur diese Raeume erlaubt')
  ) +
  sectionWrap('&#128682;', 'Besucher-Management',
    fInfo('Jarvis verwaltet Besucher: Bekannte Personen speichern, erwartete Besucher anlegen, "Lass ihn rein"-Workflow mit Kamera-Erkennung und automatischer Tuer-Entriegelung.') +
    fToggle('visitor_management.enabled', 'Besucher-Management aktiv') +
    fToggle('visitor_management.auto_guest_mode', 'Gäste-Modus automatisch aktivieren') +
    fRange('visitor_management.ring_cooldown_seconds', 'Klingel-Cooldown', 10, 120, 10, {10:'10s',30:'30s',60:'1 Min',120:'2 Min'}) +
    fRange('visitor_management.history_max', 'Max. Besucher-History', 20, 500, 20, {20:'20',50:'50',100:'100',200:'200',500:'500'})
  ) +
  // --- Netzwerk-Geräte (Bekannte Geräte) ---
  sectionWrap('&#128225;', 'Netzwerk-Geräte',
    fInfo('Jarvis warnt bei unbekannten Geräten im Netzwerk. Hier kannst du Muster definieren die als bekannt gelten (z.B. "ps5", "amazon", "iphone"). Geräte deren Name ein Muster enthält werden nie als unbekannt gemeldet.') +
    fToggle('security.threat_assessment', 'Netzwerk-Überwachung aktiv') +
    fKeywords('security.known_device_patterns', 'Bekannte Geräte-Muster') +
    '<div class="form-group"><label>Aktuell bekannte Geräte</label>' +
    '<div id="knownDevicesContainer" style="color:var(--text-muted);font-size:12px;padding:8px;">Lade...</div>' +
    '<button class="btn btn-sm" onclick="loadKnownDevices()" style="margin-top:4px;">Aktualisieren</button></div>'
  ) +
  // --- Kameras & Vision ---
  sectionWrap('&#128247;', 'Kameras & Vision',
    fInfo('Kamera-Integration für Tuerklingel-Erkennung, Sicherheits-Snapshots und visuelle Analyse. Bilder werden lokal via Vision-LLM analysiert — nichts verlässt das Netzwerk.') +
    fToggle('cameras.enabled', 'Kamera-Integration aktiv') +
    fSelect('cameras.vision_model', 'Vision-Modell', [
      {v:'llava',l:'LLaVA (Standard)'},
      {v:'llava:13b',l:'LLaVA 13B (genauer)'},
      {v:'llava:34b',l:'LLaVA 34B (beste Qualitaet)'},
      {v:'qwen2-vl',l:'Qwen2-VL'},
      {v:'moondream',l:'Moondream (schnell, klein)'},
      {v:'bakllava',l:'BakLLaVA'}
    ]) +
    fKeyValue('cameras.camera_map', 'Kamera-Zuordnung', 'Name (z.B. haustuer)', 'Entity-ID (z.B. camera.front_door)',
      'Ordne Namen den Home-Assistant Kamera-Entities zu. Diese Namen kannst du dann per Sprache verwenden.') +
    fToggle('ocr.enabled', 'OCR / Texterkennung aktiv') +
    fSelect('ocr.vision_model', 'OCR Vision-Modell', [
      {v:'',l:'Deaktiviert (nur Tesseract)'},
      {v:'llava',l:'LLaVA'},
      {v:'qwen2-vl',l:'Qwen2-VL'},
      {v:'moondream',l:'Moondream'}
    ]) +
    fText('ocr.languages', 'OCR-Sprachen', 'Tesseract Sprachcodes, z.B. deu+eng')
  ) +
  // --- Notfall-Protokolle ---
  sectionWrap('&#127752;', 'Notfall-Protokolle',
    fInfo('Bei CRITICAL Events (Rauch, Einbruch, Wasser) werden automatisch Aktionen ausgeführt. Jedes Protokoll kann einzeln aktiviert werden. Geräte werden über die Rollenzuweisung zugeordnet.') +
    '<div id="emergencyProtocolsContainer" style="color:var(--text-muted);font-size:12px;padding:8px;">Lade Notfall-Protokolle...</div>'
  ) +
  sectionWrap('&#128680;', 'Bedrohungserkennung',
    fInfo('Konfiguriert wann und wie Jarvis Bedrohungen erkennt. Die Nacht-Stunden definieren den Zeitraum fuer erhoehte Wachsamkeit bei Bewegungserkennung.') +
    fToggle('threat_assessment.enabled', 'Bedrohungserkennung aktiv') +
    fToggle('threat_assessment.auto_execute_playbooks', 'Playbooks automatisch ausfuehren') +
    fRange('threat_assessment.night_start_hour', 'Nacht-Start (Uhr)', 20, 23, 1,
      {20:'20:00',21:'21:00',22:'22:00 (Standard)',23:'23:00'}) +
    fRange('threat_assessment.night_end_hour', 'Nacht-Ende (Uhr)', 5, 8, 1,
      {5:'05:00',6:'06:00 (Standard)',7:'07:00',8:'08:00'}) +
    fNum('threat_assessment.motion_cooldown_minutes', 'Bewegungs-Cooldown (Min.)', 5, 60, 5) +
    fNum('threat_assessment.state_max_age_minutes', 'Max. Sensor-Alter (Min.)', 5, 30, 5) +
    fSubheading('Eskalation') +
    fToggle('threat_assessment.emergency_autonomy_boost', 'Autonomie-Boost bei Notfall (&rarr; Level 5)') +
    fRange('threat_assessment.emergency_boost_duration_min', 'Boost-Dauer (Min.)', 5, 60, 5,
      {5:'5',10:'10',15:'15 (Standard)',30:'30',60:'60'})
  ) +
  // --- Interrupt-Queue ---
  sectionWrap('&#9889;', 'Interrupt-Queue',
    fInfo('CRITICAL-Meldungen unterbrechen sofort alle laufenden Aktionen (TTS, Streaming). Ohne Interrupt geht die Meldung den normalen Weg über das LLM.') +
    fToggle('interrupt_queue.enabled', 'Interrupt-Queue aktiviert') +
    fRange('interrupt_queue.pause_ms', 'Pause vor Notfall-Meldung (ms)', 100, 1000, 100,
      {100:'0.1s',200:'0.2s',300:'0.3s',500:'0.5s',1000:'1s'})
  ) +
  sectionWrap('&#9878;', 'Konflikt-Sicherheitsgrenzen',
    fInfo('Sicherheitsgrenzen für Kompromiss-Werte bei Konflikten (z.B. wenn zwei Personen verschiedene Temperaturen wollen).') +
    fSubheading('Klima') +
    fRange('conflict_resolution.safe_limits.climate.temperature.0', 'Temperatur Min (°C)', 10, 20, 0.5) +
    fRange('conflict_resolution.safe_limits.climate.temperature.1', 'Temperatur Max (°C)', 22, 35, 0.5) +
    fRange('conflict_resolution.safe_limits.climate.offset.0', 'Offset Min (°C)', -5, 0, 0.5) +
    fRange('conflict_resolution.safe_limits.climate.offset.1', 'Offset Max (°C)', 0, 5, 0.5) +
    fSubheading('Licht / Rollladen / Medien') +
    fRange('conflict_resolution.safe_limits.light.brightness.0', 'Helligkeit Min (%)', 0, 50, 5) +
    fRange('conflict_resolution.safe_limits.light.brightness.1', 'Helligkeit Max (%)', 50, 100, 5) +
    fRange('conflict_resolution.safe_limits.cover.position.0', 'Rollladen Min (%)', 0, 50, 5) +
    fRange('conflict_resolution.safe_limits.cover.position.1', 'Rollladen Max (%)', 50, 100, 5) +
    fRange('conflict_resolution.safe_limits.media.volume.0', 'Lautstärke Min (%)', 0, 50, 5) +
    fRange('conflict_resolution.safe_limits.media.volume.1', 'Lautstärke Max (%)', 50, 100, 5) +
    fSubheading('Kontext-Schwellwerte') +
    fInfo('Schwellwerte für die logische Konflikt-Erkennung. Z.B. ab wie viel Watt Solar als "produzierend" gilt.') +
    fNum('conflict_resolution.context_thresholds.solar_producing_w', 'Solar produziert ab (W)', 10, 1000, 10) +
    fNum('conflict_resolution.context_thresholds.high_lux', 'Tageslicht ab (Lux)', 100, 5000, 50) +
    fNum('conflict_resolution.context_thresholds.high_wind_kmh', 'Starker Wind ab (km/h)', 20, 120, 5) +
    fRange('conflict_resolution.context_thresholds.high_energy_price', 'Strompreis hoch ab (EUR/kWh)', 0.10, 1.00, 0.05, {0.10:'0.10',0.20:'0.20',0.30:'0.30',0.50:'0.50',1.00:'1.00'}) +
    fNum('conflict_resolution.context_thresholds.frost_below_c', 'Frost unter (°C)', -10, 5, 1) +
    fSubheading('Aktive Konflikt-Regeln') +
    fInfo('Einzelne logische Konflikterkennung aktivieren oder deaktivieren.') +
    fToggle('conflict_resolution.rules_enabled.window_open', 'Fenster offen bei Heizung') +
    fToggle('conflict_resolution.rules_enabled.solar_producing', 'Solar produziert bei Rollladen schliessen') +
    fToggle('conflict_resolution.rules_enabled.high_lux', 'Tageslicht bei Licht einschalten') +
    fToggle('conflict_resolution.rules_enabled.nobody_home', 'Niemand zuhause bei Heizung/Licht') +
    fToggle('conflict_resolution.rules_enabled.cooling_and_heating', 'Heizen + Kuehlen gleichzeitig') +
    fToggle('conflict_resolution.rules_enabled.goodnight_active', 'Gute-Nacht-Modus bei Licht an') +
    fToggle('conflict_resolution.rules_enabled.high_wind', 'Starker Wind bei Rollladen/Markise oeffnen') +
    fToggle('conflict_resolution.rules_enabled.door_open', 'Tuer offen bei Heizung') +
    fToggle('conflict_resolution.rules_enabled.sleeping_detected', 'Schlafenszeit bei Medien/Licht/Klima') +
    fToggle('conflict_resolution.rules_enabled.rain_detected', 'Regen bei Markise/Fenster oeffnen') +
    fToggle('conflict_resolution.rules_enabled.frost_detected', 'Frost bei Kuehlung/Rollladen oeffnen') +
    fToggle('conflict_resolution.rules_enabled.high_energy_price', 'Hoher Strompreis bei Klimatisierung') +
    fToggle('conflict_resolution.rules_enabled.media_playing', 'Medien aktiv bei hellem Licht') +
    fToggle('conflict_resolution.rules_enabled.window_scheduled_open', 'Lueften geplant bei Heizung') +
    fSubheading('Konflikt-Vorhersage') +
    fInfo('Warnt proaktiv wenn eine gerade gegebene Anweisung mit einer kuerzlichen Aktion kollidieren wird. Z.B. "Achtung: Anna hat vor 2 Min. runtergekuehlt."') +
    fToggle('conflict_resolution.prediction_enabled', 'Konflikt-Vorhersage') +
    fRange('conflict_resolution.prediction_window_seconds', 'Vorhersage-Zeitfenster (Sek.)', 60, 600, 30,
      {60:'1 Min',120:'2 Min',180:'3 Min (Standard)',300:'5 Min',600:'10 Min'})
  ) +
  sectionWrap('&#128737;', 'Prompt-Injection-Schutz',
    fInfo('Schuetzt den LLM-Kontext gegen Prompt-Injection-Angriffe. Prueft alle externen Texte (Entity-Namen, Sensordaten) auf verdächtige Muster bevor sie an das LLM übergeben werden. Deaktivierung nur für Debugging empfohlen.') +
    fToggle('prompt_injection.enabled', 'Injection-Schutz aktiv') +
    fToggle('prompt_injection.log_blocked', 'Blockierte Versuche loggen')
  ) +
  sectionWrap('&#128295;', 'Self-Automation (Sicherheit)',
    fInfo('Jarvis kann HA-Automationen aus gelernten Mustern erstellen. Hier wird festgelegt welche Services erlaubt sind. Die vollständige Whitelist/Blacklist wird in config/automation_templates.yaml verwaltet.') +
    fToggle('self_automation.enabled', 'Self-Automation aktiv') +
    fRange('self_automation.max_per_day', 'Max. Automationen pro Tag', 1, 20, 1, {1:'1',3:'3',5:'5 (Standard)',10:'10',15:'15',20:'20'})
  ) +
  sectionWrap('&#127911;', 'Audio-Event-Reaktionen',
    fInfo('Standard-Reaktionen auf erkannte Audio-Events (Glasbruch, Rauch, etc.). In settings.yaml unter ambient_audio.default_reactions anpassbar.') +
    fTextarea('ambient_audio.default_reactions', 'Reaktionen (JSON)', 'Format: {"event_typ": {"severity": "critical|high|info", "message_de": "...", "actions": [...]}}')
  );
}

// ---- Notfall-Protokolle (Emergency Protocols with Entity Assignment) ----
const EP_PROTOCOLS = [
  { key: 'fire', title: 'Feuer / Rauch', desc: 'Rauchmelder loest aus — Lichter an, Rollläden offen, Durchsage', icon: '&#128293;', feature: 'fire_co',
    roles: {light:'Lichter einschalten', cover:'Rollläden öffnen', tts_speaker:'Durchsage-Speaker', emergency_lock:'Schlösser entriegeln', hvac:'Heizung/Klima aus'} },
  { key: 'intrusion', title: 'Einbruch / Alarm', desc: 'Alarmsystem wird ausgeloest — Lichter an, Sirene, Durchsage', icon: '&#128680;', feature: 'emergency',
    roles: {light:'Lichter einschalten', siren:'Sirene aktivieren', tts_speaker:'Durchsage-Speaker', lock:'Schlösser verriegeln', cover:'Rollläden schließen'} },
  { key: 'water_leak', title: 'Wasserleck', desc: 'Wassersensor schlägt an — Ventile zu, Heizung aus, Durchsage', icon: '&#128167;', feature: 'water_leak',
    roles: {valve:'Ventile schließen', heating:'Heizung aus', tts_speaker:'Durchsage-Speaker', light:'Lichter einschalten'} },
];
let _epData = {}; // { fire: {entities: [...], config: {...}}, ... }
// ---- Netzwerk-Geräte: Bekannte Geräte laden + verwalten ----
async function loadKnownDevices() {
  const c = document.getElementById('knownDevicesContainer');
  if (!c) return;
  c.innerHTML = '<span style="color:var(--text-muted)">Lade Geräte...</span>';
  try {
    const r = await fetch('/api/ui/known-devices', {headers: {'Authorization': `Bearer ${TOKEN}`}});
    if (!r.ok) { c.innerHTML = '<span style="color:var(--danger)">Fehler beim Laden</span>'; return; }
    const data = await r.json();
    const devices = data.devices || [];
    if (!devices.length) { c.innerHTML = '<span style="color:var(--text-muted)">Keine bekannten Geräte gespeichert.</span>'; return; }
    c.innerHTML = devices.map(d => {
      const name = d.friendly_name || d.entity_id;
      const state = d.state === 'home' ? '<span style="color:var(--success)">&#9679;</span>' : '<span style="color:var(--text-muted)">&#9679;</span>';
      return `<div style="display:flex;align-items:center;gap:6px;padding:3px 0;">
        ${state} <span style="flex:1;font-size:12px;">${esc(name)}</span>
        <span style="font-size:10px;color:var(--text-muted);">${esc(d.entity_id)}</span>
        <button class="btn btn-sm" style="font-size:10px;padding:2px 6px;color:var(--danger);" onclick="removeKnownDevice('${esc(d.entity_id)}')">&#10005;</button>
      </div>`;
    }).join('');
  } catch(e) { c.innerHTML = '<span style="color:var(--danger)">Verbindungsfehler</span>'; }
}

async function removeKnownDevice(entityId) {
  if (!confirm('Geraet "' + entityId + '" aus der Liste entfernen? Beim nächsten Auftauchen wird es als unbekannt gemeldet.')) return;
  try {
    await fetch('/api/ui/known-devices', {
      method: 'DELETE', headers: {'Content-Type':'application/json', 'Authorization': `Bearer ${TOKEN}`},
      body: JSON.stringify({entity_id: entityId})
    });
    loadKnownDevices();
  } catch(e) { alert('Fehler: ' + e.message); }
}

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
    if (entityCount > 0) html += '<span style="font-size:11px;color:var(--text-muted);">' + entityCount + ' Geräte</span>';
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
          html += '<div style="font-size:11px;color:var(--text-muted);padding:4px 0;font-style:italic;">Keine Geräte zugewiesen</div>';
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
      toast('Keine passenden Geräte gefunden', 'warning');
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
    toast(added + ' Geräte erkannt und zugewiesen', 'success');
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
  if (!html) html = '<div style="font-size:12px;color:var(--text-muted);">Keine Kanaele verfügbar</div>';
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
    hint.textContent = 'Aktiv: Alle /api/assistant/* Anfragen benötigen einen gueltigen API Key.';
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
  if (!confirm('API Key wirklich neu generieren? Addon und HA-Integration müssen danach aktualisiert werden!')) return;
  try {
    const data = await api('/api/ui/api-key/regenerate', 'POST');
    const el = document.getElementById('apiKeyDisplay');
    if (el && data.api_key) el.value = data.api_key;
    toast('Neuer API Key generiert!');
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}
async function toggleApiKeyEnforcement(enabled) {
  const action = enabled ? 'aktivieren' : 'deaktivieren';
  if (enabled && !confirm('API Key Prüfung aktivieren? Stelle sicher, dass der Key bereits im HA-Addon und in der HA-Integration eingetragen ist, sonst funktioniert die Kommunikation nicht mehr!')) {
    const cb = document.getElementById('apiKeyEnforcement');
    if (cb) cb.checked = false;
    return;
  }
  try {
    const data = await api('/api/ui/api-key/enforcement', 'POST', { enabled });
    updateEnforcementHint(data.enforcement);
    toast('API Key Prüfung ' + (data.enforcement ? 'aktiviert' : 'deaktiviert'));
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
    const el = document.getElementById('settingsRecoveryKey');
    if (el && data.recovery_key) {
      el.value = data.recovery_key;
      el.style.color = 'var(--accent)';
      el.style.fontSize = '18px';
      el.style.fontWeight = '700';
    }
    toast('Neuer Recovery-Key generiert — JETZT notieren!');
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

// ---- Tab: KI-Autonomie ----
let SNAPSHOTS = [];

function renderAutonomie() {
  // --- Group 1: Autonomie-Stufen & Berechtigungen ---
  return sectionWrap('&#9889;', 'Autonomie-Stufen &amp; Berechtigungen',
    fInfo('Alles rund um Autonomie-Level, Berechtigungen, Evolution und geschuetzte Bereiche. Bestimmt WAS der Assistent eigenstaendig tun darf und welche Grenzen gelten.') +

    fSubheading('Autonomie') +
    fRange('autonomy.level', 'Autonomie-Level', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +

    fSubheading('Aktions-Berechtigungen') +
    fTextarea('autonomy.action_permissions', 'Berechtigungen (JSON)', 'Format: {"aktion": level}. z.B. {"proactive_info": 2, "adjust_temperature_small": 3}') +

    fSubheading('Evolution-Kriterien') +
    fTextarea('autonomy.evolution_criteria', 'Kriterien (JSON)', 'Format: {"2": {"min_days": 30, "min_interactions": 200, "min_acceptance": 0.7}}') +
    fSubheading('Automatische Evolution') +
    fToggle('autonomy.evolution.enabled', 'Automatischer Autonomie-Aufstieg') +
    fRange('autonomy.evolution.max_level', 'Max. automatisches Level', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +

    fSubheading('Temporale Autonomie') +
    fInfo('Unterschiedlicher Autonomie-Level je nach Tageszeit. Offset wird auf das aktuelle Level addiert. "-1" nachts bedeutet z.B. Level 3 &rarr; Level 2 zwischen 22-7 Uhr.') +
    fToggle('autonomy.temporal.enabled', 'Temporale Autonomie aktiv') +
    fRange('autonomy.temporal.night_offset', 'Nacht-Offset (22-7 Uhr)', -3, 0, 1,
      {'-3':'-3','-2':'-2','-1':'-1 (Standard)','0':'Aus'}) +
    fRange('autonomy.temporal.day_offset', 'Tag-Offset (7-22 Uhr)', 0, 2, 1,
      {'0':'\u00b10 (Standard)','1':'+1','2':'+2'}) +
    fSubheading('De-Eskalation') +
    fInfo('Automatische Level-Reduktion wenn die Akzeptanzrate dauerhaft niedrig ist. Jarvis schlaegt dann eine Rueckstufung vor — fuehrt sie nie selbst durch.') +
    fToggle('autonomy.deescalation.enabled', 'De-Eskalation aktiv') +
    fRange('autonomy.deescalation.min_acceptance_rate', 'Schwelle Akzeptanzrate', 0.3, 0.7, 0.05,
      {0.3:'30%',0.4:'40%',0.5:'50% (Standard)',0.6:'60%',0.7:'70%'}) +
    fNum('autonomy.deescalation.evaluation_days', 'Bewertungszeitraum (Tage)', 3, 14, 1) +

    fSubheading('Geschuetzte Bereiche (Immutable)') +
    fChipSelect('self_optimization.immutable_keys', 'Geschuetzte Bereiche (nicht änderbar durch KI)', [
      'security','trust_levels','response_filter.banned_phrases',
      'response_filter.banned_starters','household','assistant.name',
      'self_optimization.immutable_keys','self_optimization.approval_mode',
      'models.fast','models.smart','models.deep','autonomy.level'
    ], 'Klicke auf Bereiche die die KI NIEMALS selbst ändern darf.') +

    fSubheading('Parameter-Grenzen') +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">' +
    fNum('self_optimization.parameter_bounds.sarcasm_level.min', 'Sarkasmus Min', 1, 5) +
    fNum('self_optimization.parameter_bounds.sarcasm_level.max', 'Sarkasmus Max', 1, 5) +
    fNum('self_optimization.parameter_bounds.opinion_intensity.min', 'Meinungen Min', 0, 3) +
    fNum('self_optimization.parameter_bounds.opinion_intensity.max', 'Meinungen Max', 0, 3) +
    fNum('self_optimization.parameter_bounds.max_response_sentences.min', 'Sätze Min', 1, 10) +
    fNum('self_optimization.parameter_bounds.max_response_sentences.max', 'Sätze Max', 1, 10) +
    fNum('self_optimization.parameter_bounds.formality_min.min', 'Formalität-Min Min', 0, 100) +
    fNum('self_optimization.parameter_bounds.formality_min.max', 'Formalität-Min Max', 0, 100) +
    fNum('self_optimization.parameter_bounds.insight_cooldown_hours.min', 'Insight-Cooldown Min (h)', 1, 24) +
    fNum('self_optimization.parameter_bounds.insight_cooldown_hours.max', 'Insight-Cooldown Max (h)', 1, 24) +
    fNum('self_optimization.parameter_bounds.anticipation_min_confidence.min', 'Antizipation-Conf Min', 0, 1, 0.05) +
    fNum('self_optimization.parameter_bounds.anticipation_min_confidence.max', 'Antizipation-Conf Max', 0, 1, 0.05) +
    fNum('self_optimization.parameter_bounds.feedback_base_cooldown.min', 'Feedback-Cooldown Min (s)', 30, 1800) +
    fNum('self_optimization.parameter_bounds.feedback_base_cooldown.max', 'Feedback-Cooldown Max (s)', 30, 1800) +
    fNum('self_optimization.parameter_bounds.spontaneous_max_per_day.min', 'Spontan/Tag Min', 0, 10) +
    fNum('self_optimization.parameter_bounds.spontaneous_max_per_day.max', 'Spontan/Tag Max', 0, 10) +
    '</div>'
  ) +

  // --- Group 2: Lern-System & Selbstoptimierung ---
  sectionWrap('&#129504;', 'Lern-System &amp; Selbstoptimierung',
    fInfo('Alle Lern-Features und Selbstoptimierung: Wie der Assistent aus Interaktionen lernt, Korrekturen speichert, Ergebnisse trackt und sich innerhalb sicherer Grenzen verbessert.') +

    fSubheading('Selbstoptimierung') +
    fToggle('self_optimization.enabled', 'Selbstoptimierung aktiv') +
    fSelect('self_optimization.approval_mode', 'Genehmigungsmodus', [
      {v:'manual', l:'Manuell (nur mit Bestätigung)'},
      {v:'off', l:'Aus (keine Vorschläge)'}
    ]) +
    fSelect('self_optimization.analysis_interval', 'Analyse-Intervall', [
      {v:'weekly', l:'Woechentlich'},
      {v:'daily', l:'Taeglich'}
    ]) +
    fNum('self_optimization.max_proposals_per_cycle', 'Max. Vorschläge pro Zyklus', 1, 10) +
    fModelSelect('self_optimization.model', 'Analyse-Modell') +

    fSubheading('Vorschläge (Approval-Workflow)') +
    '<div id="proposalsList" style="margin-bottom:12px;"></div>' +
    '<button class="btn btn-secondary" style="font-size:12px;" onclick="runAnalysis()">Analyse jetzt starten</button>' +

    fSubheading('Lern-System (Global)') +
    fToggle('learning.enabled', 'Alle Lern-Features aktiv') +

    fSubheading('Wirkungstracker (Outcome Tracker)') +
    fToggle('outcome_tracker.enabled', 'Wirkungstracker aktiv') +
    fRange('outcome_tracker.observation_delay_seconds', 'Beobachtungs-Verzögerung', 60, 600, 30, {60:'1 Min',120:'2 Min',180:'3 Min',300:'5 Min',600:'10 Min'}) +
    fNum('outcome_tracker.max_results', 'Max. gespeicherte Ergebnisse', 100, 2000, 100) +
    fRange('outcome_tracker.calibration_min', 'Min. Kalibrierungsfaktor', 0.3, 0.8, 0.05, {0.3:'0.3 (aggressiv)',0.5:'0.5 (Standard)',0.7:'0.7',0.8:'0.8 (konservativ)'}) +
    fRange('outcome_tracker.calibration_max', 'Max. Kalibrierungsfaktor', 1.2, 2.0, 0.1, {1.2:'1.2',1.5:'1.5 (Standard)',1.8:'1.8',2.0:'2.0 (aggressiv)'}) +
    fInfo('Domain-Kalibrierung passt die Konfidenz pro Bereich (Licht, Klima, Medien...) an. Domains mit hohem Erfolgs-Score bekommen einen Boost, schlechte werden gedaempft. Min/Max begrenzt den Faktor — enger = stabiler, weiter = adaptiver.') +

    fSubheading('Feedback-Loops') +
    fInfo('Verbindet den Wirkungstracker mit der Antizipation und dem Lern-Observer: Fehlgeschlagene Vorhersagen verlieren Konfidenz, erfolgreiche werden gestaerkt.') +
    fToggle('outcome_tracker.anticipation_feedback', 'Anticipation-Feedback aktiv') +
    fRange('outcome_tracker.success_confidence_boost', 'Erfolgs-Boost', 0.05, 0.2, 0.01,
      {0.05:'0.05',0.1:'0.1 (Standard)',0.15:'0.15',0.2:'0.2'}) +
    fRange('outcome_tracker.failure_confidence_penalty', 'Fehl-Penalty', 0.05, 0.3, 0.01,
      {0.05:'0.05',0.1:'0.1',0.15:'0.15 (Standard)',0.2:'0.2',0.3:'0.3'}) +
    fToggle('outcome_tracker.learning_observer_feedback', 'Learning-Observer Feedback') +
    fRange('outcome_tracker.learning_boost', 'Lern-Boost bei Erfolg', 0.05, 0.2, 0.01,
      {0.05:'0.05',0.1:'0.1 (Standard)',0.15:'0.15',0.2:'0.2'}) +

    fSubheading('Korrektur-Gedächtnis') +
    fToggle('correction_memory.enabled', 'Korrektur-Gedächtnis aktiv') +
    fNum('correction_memory.max_entries', 'Max. Einträge', 50, 500, 50) +
    fNum('correction_memory.max_context_entries', 'Max. Kontext-Einträge', 1, 10) +
    fToggle('correction_memory.cross_domain_rules', 'Domain-uebergreifende Regeln') +
    fInfo('Korrekturen gelten auch fuer aehnliche Bereiche: "Raumverwechslung bei Licht" wird auch auf Klima und Medien angewendet.') +

    fSubheading('Lernende Schwellwerte (Adaptive Thresholds)') +
    fToggle('adaptive_thresholds.enabled', 'Lernende Schwellwerte aktiv') +
    fToggle('adaptive_thresholds.auto_adjust', 'Auto-Anpassung') +
    fNum('adaptive_thresholds.analysis_interval_hours', 'Analyse-Intervall (Stunden)', 24, 336, 24)
  ) +

  // --- Group 3: Antwort-Qualität & Feedback ---
  sectionWrap('&#128200;', 'Antwort-Qualitaet &amp; Feedback',
    fInfo('Antwort-Qualitaet messen, Fehlermuster erkennen, woechentliche Selbst-Reports generieren und Feedback-Verhalten steuern. Alles was die Antwort-Qualitaet und das Nutzer-Feedback betrifft.') +

    fSubheading('Antwort-Qualitaet (Response Quality)') +
    fToggle('response_quality.enabled', 'Antwort-Qualitaet aktiv') +
    fRange('response_quality.followup_window_seconds', 'Follow-Up Zeitfenster', 15, 120, 15, {15:'15s',30:'30s',60:'1 Min',90:'90s',120:'2 Min'}) +
    fRange('response_quality.rephrase_similarity_threshold', 'Umformulierungs-Schwelle', 0.3, 0.9, 0.05) +

    fSubheading('Fehlermuster-Erkennung (Error Patterns)') +
    fToggle('error_patterns.enabled', 'Fehlermuster-Erkennung aktiv') +
    fNum('error_patterns.min_occurrences_for_mitigation', 'Min. Fehler für Reaktion', 2, 10) +
    fNum('error_patterns.mitigation_ttl_hours', 'Reaktions-Dauer (Stunden)', 1, 24) +
    fInfo('Selbstdiagnose: Jarvis erkennt systemische Probleme anhand der Fehlermuster und informiert proaktiv. Die Schwellwerte bestimmen ab wie vielen Fehlern pro Typ in 24h eine Diagnose ausgeloest wird.') +
    fNum('error_patterns.self_diagnosis.timeout_threshold', 'Timeout-Schwelle (24h)', 2, 20) +
    fNum('error_patterns.self_diagnosis.service_unavailable_threshold', 'Service-Ausfall-Schwelle (24h)', 2, 10) +
    fNum('error_patterns.self_diagnosis.entity_not_found_threshold', 'Entity-nicht-gefunden-Schwelle (24h)', 2, 10) +
    fNum('error_patterns.self_diagnosis.model_overloaded_threshold', 'Modell-Ueberlast-Schwelle (24h)', 2, 20) +

    fSubheading('Woechentlicher Selbst-Report') +
    fToggle('self_report.enabled', 'Selbst-Report aktiv') +
    fModelSelect('self_report.model', 'Report-Modell') +

    fSubheading('Cross-Session &amp; Quality Feedback') +
    fToggle('cross_session_references.enabled', 'Cross-Session Referenzen') +
    fToggle('quality_feedback.enabled', 'Quality Feedback Loop') +
    fRange('quality_feedback.weak_threshold', 'Schwach-Schwelle', 0.1, 0.5, 0.05, {0.1:'0.1',0.2:'0.2',0.3:'0.3 (Standard)',0.4:'0.4',0.5:'0.5'}) +

    fSubheading('Feedback-System') +
    fRange('feedback.auto_timeout_seconds', 'Feedback-Timeout', 30, 600, 30, {30:'30s',60:'1 Min',120:'2 Min',300:'5 Min',600:'10 Min'}) +
    fRange('feedback.base_cooldown_seconds', 'Basis-Abstand', 60, 1800, 60, {60:'1 Min',120:'2 Min',300:'5 Min',600:'10 Min',1800:'30 Min'}) +
    fRange('feedback.score_suppress', 'Unterdrücken unter', 0, 1, 0.05) +
    fRange('feedback.score_reduce', 'Reduzieren unter', 0, 1, 0.05) +
    fRange('feedback.score_normal', 'Normal ab', 0, 1, 0.05) +
    fRange('feedback.score_boost', 'Boost ab', 0, 1, 0.05) +

    fSubheading('Score-Smoothing') +
    fToggle('feedback.smoothing_enabled', 'Score-Smoothing (EMA)') +
    fInfo('Verhindert dass einzelne Events den Score stark bewegen. Exponential Moving Average: 70% alter Wert + 30% neuer Wert.') +
    fRange('feedback.smoothing_factor', 'Smoothing-Faktor (Neuer Anteil)', 0.1, 0.5, 0.05,
      {0.1:'0.1 (stabil)',0.2:'0.2',0.3:'0.3 (Standard)',0.4:'0.4',0.5:'0.5 (reaktiv)'})
  ) +

  // --- Group 4: Erweiterte KI & Prompt-Optimierung ---
  sectionWrap('&#129302;', 'Erweiterte KI &amp; Prompt-Optimierung',
    fInfo('Erweiterte KI-Faehigkeiten, Few-Shot-Lernen aus guten Antworten, Prompt-Versionierung und Kontext-Kompaktierung. Fortgeschrittene Features für optimale LLM-Nutzung.') +

    fSubheading('Erweiterte KI-Features') +
    fToggle('butler_instinct.enabled', 'Butler-Instinkt (Auto-Execute bei 90%+ Konfidenz)') +
    fRange('butler_instinct.min_autonomy_level', 'Butler-Instinkt ab Level', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fToggle('multi_turn_tools.enabled', 'Multi-Turn Tools (mehrere Aufrufe pro Gespraech)') +
    fNum('multi_turn_tools.max_iterations', 'Max. Iterationen pro Turn', 1, 10) +
    fToggle('multi_sense_fusion.enabled', 'Multi-Sense Fusion (Kamera + Audio + Sensoren)') +

    fSubheading('Dynamic Few-Shot &amp; Prompt-Tracking') +
    fToggle('dynamic_few_shot.enabled', 'Dynamic Few-Shot aktiv') +
    fNum('dynamic_few_shot.max_per_category', 'Max. Beispiele pro Kategorie', 3, 20) +
    fNum('dynamic_few_shot.max_examples_in_prompt', 'Max. Beispiele im Prompt', 1, 5) +
    fToggle('prompt_versioning.enabled', 'Prompt-Versionierung aktiv') +

    fSubheading('Kontext-Kompaktierung') +
    fRange('context_compaction.threshold', 'Kompaktierungs-Schwelle', 0.5, 0.95, 0.05, {0.5:'50%',0.6:'60%',0.7:'70% (Standard)',0.8:'80%',0.9:'90%',0.95:'95%'}) +
    fToggle('context_compaction.prefer_llm', 'LLM-Kompaktierung bevorzugen') +
    fToggle('pre_compaction_flush.enabled', 'Pre-Compaction Flush (Fakten sichern)') +
    fSubheading('Kontext-Quellen') +
    fToggle('context_builder.include_threads', 'Gesprächs-Threads im Kontext') +
    fInfo('Aktive Gespraechs-Threads werden dem LLM-Kontext hinzugefuegt fuer bessere Kontinuitaet ueber mehrere Nachrichten.')
  ) +

  // --- Group 5: Automationen & Rollback ---
  sectionWrap('&#128736;', 'Automationen &amp; Rollback',
    fInfo('Automationen erstellen und verwalten, Config-Selbstmodifikation und Rollback-Sicherung. Alles was mit automatischen Änderungen und deren Absicherung zu tun hat.') +

    fSubheading('Self-Automation') +
    fToggle('self_automation.enabled', 'Self-Automation aktiv') +
    fNum('self_automation.max_per_day', 'Max. Automationen pro Tag', 1, 20) +
    fModelSelect('self_automation.model', 'Modell für Automations-Erstellung') +

    fSubheading('Automationen — Übersicht') +
    '<div id="automations-panel"><div class="muted" style="padding:8px">Lade Automationen...</div></div>' +

    fSubheading('Config-Selbstmodifikation') +
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
      '<span style="font-size:11px;color:var(--text-muted);margin-left:auto;">NUR durch User änderbar</span></div>' +
    '</div>' +

    fSubheading('Rollback &amp; Snapshots') +
    fToggle('self_optimization.rollback.enabled', 'Rollback aktiv') +
    fNum('self_optimization.rollback.max_snapshots', 'Max. gespeicherte Snapshots', 5, 100) +
    fToggle('self_optimization.rollback.snapshot_on_every_edit', 'Snapshot bei jeder Änderung') +
    '<div id="snapshotsList" style="margin-top:12px;"></div>'
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
    c.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-muted);font-size:12px;">Keine offenen Vorschläge</div>';
    return;
  }
  c.innerHTML = '<div style="font-weight:600;font-size:13px;margin-bottom:8px;">Offene Vorschläge:</div>' +
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

async function loadAutomations() {
  const panel = document.getElementById('automations-panel');
  if (!panel) return;
  try {
    const data = await api('/api/ui/automations');
    const ha = data.ha_automations || [];
    const jarvis = data.jarvis_automations || [];
    let html = '';

    // --- Jarvis-Automationen ---
    html += '<div class="field-label" style="margin-top:8px">VON JARVIS ERSTELLT (' + jarvis.length + ')</div>';
    if (jarvis.length === 0) {
      html += '<div class="muted" style="padding:4px 8px">Noch keine Jarvis-Automationen erstellt.</div>';
    } else {
      jarvis.forEach(a => {
        const active = a.state === 'on';
        const statusCls = active ? 'color:var(--accent)' : 'color:var(--muted)';
        const statusTxt = active ? 'aktiv' : 'deaktiviert';
        const lt = a.last_triggered && a.last_triggered !== 'nie' ? new Date(a.last_triggered).toLocaleString('de-DE') : 'nie';
        html += '<div class="card" style="margin:4px 0;padding:8px;display:flex;justify-content:space-between;align-items:center">';
        html += '<div><strong>' + esc(a.alias) + '</strong><br><span class="muted" style="font-size:0.85em">' + esc(a.config_id) + ' &middot; <span style="' + statusCls + '">' + statusTxt + '</span> &middot; Zuletzt: ' + lt + '</span></div>';
        html += '<div style="display:flex;gap:6px">';
        html += '<button class="btn btn-small" onclick="toggleJarvisAutomation(\'' + esc(a.entity_id) + '\')">' + (active ? 'Deaktivieren' : 'Aktivieren') + '</button>';
        html += '<button class="btn btn-small btn-danger" onclick="deleteJarvisAutomation(\'' + esc(a.config_id) + '\')">Loeschen</button>';
        html += '</div></div>';
      });
    }

    // --- HA-Automationen ---
    html += '<div class="field-label" style="margin-top:16px">HOME ASSISTANT AUTOMATIONEN (' + ha.length + ')</div>';
    if (ha.length === 0) {
      html += '<div class="muted" style="padding:4px 8px">Keine Automationen gefunden.</div>';
    } else {
      ha.forEach(a => {
        const enabled = a.enabled !== false;
        const statusCls = enabled ? 'color:var(--accent)' : 'color:var(--muted)';
        const statusTxt = enabled ? 'aktiv' : 'deaktiviert';
        const lt = a.last_triggered ? new Date(a.last_triggered).toLocaleString('de-DE') : '—';
        const triggers = a.trigger ? (Array.isArray(a.trigger) ? a.trigger : [a.trigger]) : [];
        const actions = a.action ? (Array.isArray(a.action) ? a.action : [a.action]) : [];
        const triggerTxt = triggers.map(t => t.platform || t.trigger || t.alias || JSON.stringify(t).substring(0,60)).join(', ');
        const actionTxt = actions.map(ac => ac.service || ac.action || ac.alias || JSON.stringify(ac).substring(0,60)).join(', ');
        html += '<div class="card" style="margin:4px 0;padding:8px">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center">';
        html += '<strong>' + esc(a.alias || a.id) + '</strong>';
        html += '<span style="font-size:0.85em;' + statusCls + '">' + statusTxt + '</span>';
        html += '</div>';
        if (a.description) html += '<div class="muted" style="font-size:0.85em;margin-top:2px">' + esc(a.description) + '</div>';
        html += '<div style="font-size:0.8em;margin-top:4px;color:var(--muted)">';
        if (triggerTxt) html += '<div>Trigger: ' + esc(triggerTxt) + '</div>';
        if (actionTxt) html += '<div>Aktion: ' + esc(actionTxt) + '</div>';
        if (lt !== '—') html += '<div>Zuletzt: ' + lt + '</div>';
        html += '</div></div>';
      });
    }

    panel.innerHTML = html;
  } catch(e) {
    panel.innerHTML = '<div class="muted" style="padding:8px">Fehler beim Laden: ' + esc(e.message) + '</div>';
  }
}

async function toggleJarvisAutomation(entityId) {
  try {
    const result = await api('/api/ui/automations/jarvis/' + encodeURIComponent(entityId) + '/toggle', 'POST');
    if (result.success) {
      toast('Automation ' + (result.new_state === 'on' ? 'aktiviert' : 'deaktiviert'));
      loadAutomations();
    } else { toast(result.message, 'error'); }
  } catch(e) { toast('Fehler: ' + e.message, 'error'); }
}

async function deleteJarvisAutomation(configId) {
  if (!confirm('Jarvis-Automation "' + configId + '" wirklich loeschen?')) return;
  try {
    const result = await api('/api/ui/automations/jarvis/' + encodeURIComponent(configId), 'DELETE');
    if (result.success) {
      toast('Automation gelöscht');
      loadAutomations();
    } else { toast(result.message, 'error'); }
  } catch(e) { toast('Fehler: ' + e.message, 'error'); }
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
  if (!confirm('Config auf diesen Snapshot zurücksetzen?')) return;
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
    '+ Profil hinzufügen</button>';

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
  scheduleAutoSave();
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
    if (el.classList.contains('nm-select') || el.classList.contains('nm-vol')) return; // handled by _nmSync
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
      if (k && v) {
        // Numerische Werte als Zahl speichern (z.B. Segment-IDs)
        const num = Number(v);
        obj[k] = (v !== '' && !isNaN(num) && String(num) === v) ? num : v;
      }
    });
    setPath(updates, path, obj);
  });
  // Power-Trigger editors (pt-editor divs) - collect from DOM
  document.querySelectorAll('#settingsContent .pt-editor[data-path]').forEach(el => {
    const path = el.dataset.path;
    const triggers = [];
    el.querySelectorAll('.pt-row').forEach(row => {
      const entity = row.querySelector('.pt-entity').value.trim();
      const threshold = parseFloat(row.querySelector('.pt-threshold').value) || 5;
      const room = row.querySelector('.pt-room').value.trim();
      if (entity && room) triggers.push({ entity, threshold, room });
    });
    setPath(updates, path, triggers);
  });
  // Scene-Trigger editors (st-editor divs) - collect from DOM
  document.querySelectorAll('#settingsContent .st-editor[data-path]').forEach(el => {
    const path = el.dataset.path;
    const triggers = [];
    el.querySelectorAll('.st-row').forEach(row => {
      const entity = row.querySelector('.st-entity').value.trim();
      const room = row.querySelector('.st-room').value.trim();
      if (entity && room) triggers.push({ entity, room });
    });
    setPath(updates, path, triggers);
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
  // Monitored entities: Nicht mehr nötig — Diagnostics und Device Health
  // nutzen jetzt automatisch Entity-Annotations (annotierte = überwacht, hidden = ignoriert).
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
  document.querySelectorAll('#settingsContent [data-entity-picker="list"][data-path]').forEach(el => {
    const path = el.dataset.path;
    if (!path) return;
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
let _saveAgain = false;
async function saveAllSettings(showToast) {
  if (_saving) { _saveAgain = true; return; }
  _saving = true;
  const status = document.getElementById('autoSaveStatus');
  try {
    // Erst aktuelle Tab-Werte in S übernehmen, dann S als Basis nutzen
    const tabUpdates = collectSettings();
    deepMerge(S, tabUpdates);
    // Vollständiges Settings-Objekt senden (nicht nur aktiven Tab)
    // Geschuetzte Keys entfernen die vom GET mitkommen aber per PUT
    // nicht gesendet werden dürfen (sonst False-Positive Warnung im Log)
    const updates = JSON.parse(JSON.stringify(S));
    delete updates.dashboard;
    if (updates.security) {
      delete updates.security.api_key;
      delete updates.security.api_key_required;
      if (Object.keys(updates.security).length === 0) delete updates.security;
    }
    if (updates.self_optimization) {
      delete updates.self_optimization.immutable_keys;
      if (Object.keys(updates.self_optimization).length === 0) delete updates.self_optimization;
    }
    const result = await api('/api/ui/settings', 'PUT', {settings: updates});

    if (result && result.success === false) {
      if (status) { status.textContent = 'Fehler'; status.className = 'auto-save-status error'; }
      toast(result.message || 'Ungueltige Einstellungen', 'error');
      return;
    }

    // Room-Profiles separat speichern wenn geändert
    if (_rpDirty) {
      collectRoomProfiles();
      await api('/api/ui/room-profiles', 'PUT', {profiles: RP});
      _rpDirty = false;
    }

    if (showToast) toast(result?.message || 'Einstellungen gespeichert');
  } catch(e) {
    if (status) { status.textContent = 'Fehler'; status.className = 'auto-save-status error'; }
    toast('Fehler beim Speichern' + (e.message ? ': ' + e.message : ''), 'error');
  } finally {
    _saving = false;
    if (_saveAgain) {
      _saveAgain = false;
      saveAllSettings();
    }
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
          <div style="font-weight:600;font-size:14px;">Manuelle Übersteuerung</div>
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


// ---- Entities + Annotations ----

// Standard-Rollen Labels (werden von API überschrieben)
const _ROLE_LABELS = {
  light:'Beleuchtung', dimmer:'Dimmer', color_light:'Farblicht/RGB',
  indoor_temp:'Raumtemperatur', outdoor_temp:'Aussentemperatur', humidity:'Luftfeuchtigkeit',
  window_contact:'Fensterkontakt', door_contact:'Tuerkontakt', motion:'Bewegungsmelder',
  presence:'Anwesenheit', water_leak:'Wassermelder', smoke:'Rauchmelder',
  co2:'CO2-Sensor', light_level:'Lichtsensor', power_meter:'Strommesser',
  energy:'Energiezaehler', battery:'Batterie', outlet:'Steckdose',
  valve:'Ventil', fan:'Lüfter', irrigation:'Bewässerung',
  garage_door:'Garagentor', water_temp:'Wassertemperatur', pressure:'Luftdruck',
  vibration:'Vibration',
};

function _allRoles() {
  const roles = {};
  // Standard
  for (const [k,v] of Object.entries(ENTITY_ROLES_DEFAULT)) roles[k] = v;
  // Custom überschreibt
  for (const [k,v] of Object.entries(ENTITY_ROLES_CUSTOM)) roles[k] = v;
  return roles;
}

function _roleLabel(roleId) {
  if (!roleId) return '';
  const roles = _allRoles();
  if (roles[roleId]) return roles[roleId].label || roleId;
  return _ROLE_LABELS[roleId] || roleId;
}

function _roleOptionsHtml(selected) {
  const roles = _allRoles();
  let html = `<option value=""${!selected?' selected':''}>-- keine --</option>`;
  for (const [k, v] of Object.entries(roles)) {
    const label = (v.icon ? v.icon + ' ' : '') + (v.label || k);
    html += `<option value="${esc(k)}"${k===selected?' selected':''}>${esc(label)}</option>`;
  }
  return html;
}

async function loadEntities() {
  try {
    // Parallel laden: Entities + Annotations + Roles + Room-Profiles
    const [entData, annData, roleData, rpData] = await Promise.all([
      api('/api/ui/entities'),
      api('/api/ui/entity-annotations'),
      api('/api/ui/entity-roles'),
      api('/api/ui/room-profiles').catch(() => ({})),
    ]);
    ALL_ENTITIES = entData.entities || [];
    ENTITY_ANNOTATIONS = annData.annotations || {};
    ENTITY_ROLES_DEFAULT = roleData.default_roles || {};
    ENTITY_ROLES_CUSTOM = roleData.custom_roles || {};
    // RP laden falls noch nicht geladen (für Raum-Dropdown in Entity-Annotations)
    if (rpData && Object.keys(rpData).length > 0) RP = rpData;

    // Domain-Filter
    const domains = [...new Set(ALL_ENTITIES.map(e => e.domain))].sort();
    const sel = document.getElementById('entityDomainFilter');
    sel.innerHTML = `<option value="">Alle Domains (${ALL_ENTITIES.length})</option>`;
    for (const d of domains) {
      const c = ALL_ENTITIES.filter(e => e.domain === d).length;
      sel.innerHTML += `<option value="${esc(d)}">${esc(d)} (${c})</option>`;
    }

    // Batch-Toolbar: Text-Inputs (Datalists werden on-the-fly befuellt)

    // Eigene Rollen rendern
    _renderCustomRoles();

    _annBatchSelected.clear();
    filterEntities();
  } catch(e) { console.error('Entities fail:', e); toast('Fehler beim Laden: ' + e.message, 'error'); }
}

function _renderCustomRoles() {
  // Standard-Rollen als Chips
  const chipsEl = document.getElementById('annDefaultRolesChips');
  if (chipsEl) {
    chipsEl.innerHTML = Object.entries(ENTITY_ROLES_DEFAULT).map(([k,v]) =>
      `<span class="role-chip">${esc((v.icon||'') + ' ' + (v.label||k))}</span>`
    ).join('');
  }
  // Eigene Rollen als editierbare Zeilen
  const editorEl = document.getElementById('annCustomRolesEditor');
  if (editorEl) {
    const entries = Object.entries(ENTITY_ROLES_CUSTOM);
    editorEl.innerHTML = entries.map(([k,v]) => `
      <div class="cr-row" data-cr-id="${esc(k)}">
        <input type="text" value="${esc(k)}" placeholder="rollen_id" data-cr-field="id" onchange="scheduleCustomRoleSave()">
        <input type="text" value="${esc(v.label||'')}" placeholder="Label" data-cr-field="label" onchange="scheduleCustomRoleSave()">
        <input type="text" value="${esc(v.icon||'')}" placeholder="Icon" style="width:50px" data-cr-field="icon" onchange="scheduleCustomRoleSave()">
        <button class="btn btn-secondary btn-sm" onclick="this.closest('.cr-row').remove();scheduleCustomRoleSave();">x</button>
      </div>`).join('');
  }
}

function addCustomRole() {
  const editorEl = document.getElementById('annCustomRolesEditor');
  if (!editorEl) return;
  const row = document.createElement('div');
  row.className = 'cr-row';
  row.innerHTML = `
    <input type="text" value="" placeholder="rollen_id" data-cr-field="id" onchange="scheduleCustomRoleSave()">
    <input type="text" value="" placeholder="Label" data-cr-field="label" onchange="scheduleCustomRoleSave()">
    <input type="text" value="" placeholder="Icon" style="width:50px" data-cr-field="icon" onchange="scheduleCustomRoleSave()">
    <button class="btn btn-secondary btn-sm" onclick="this.closest('.cr-row').remove();scheduleCustomRoleSave();">x</button>`;
  editorEl.appendChild(row);
}

function _collectCustomRoles() {
  const roles = {};
  document.querySelectorAll('#annCustomRolesEditor .cr-row').forEach(row => {
    const id = (row.querySelector('[data-cr-field="id"]')?.value || '').trim().toLowerCase().replace(/[^a-z0-9_]/g,'');
    const label = (row.querySelector('[data-cr-field="label"]')?.value || '').trim();
    const icon = (row.querySelector('[data-cr-field="icon"]')?.value || '').trim();
    if (id && label) roles[id] = { label, icon };
  });
  return roles;
}

function scheduleCustomRoleSave() {
  if (_roleSaveTimer) clearTimeout(_roleSaveTimer);
  const st = document.getElementById('annAutoSaveStatus');
  if (st) st.textContent = 'Ungespeichert...';
  _roleSaveTimer = setTimeout(async () => {
    try {
      const custom = _collectCustomRoles();
      await api('/api/ui/entity-roles', 'PUT', { custom_roles: custom });
      ENTITY_ROLES_CUSTOM = custom;
      if (st) { st.textContent = 'Gespeichert'; setTimeout(() => { if (st) st.textContent = ''; }, 2000); }
    } catch(e) { toast('Rollen-Speichern fehlgeschlagen: ' + e.message, 'error'); }
  }, 1500);
}

var _entityShowCount = 50; // Lazy-load batch size

function filterEntities() {
  const domain = document.getElementById('entityDomainFilter')?.value || '';
  const annFilter = document.getElementById('entityAnnotationFilter')?.value || '';
  const search = (document.getElementById('entitySearchInput')?.value || '').toLowerCase().trim();
  const hasActiveFilter = domain || annFilter || search;
  let filtered = ALL_ENTITIES;
  if (domain) filtered = filtered.filter(e => e.domain === domain);
  if (search) {
    // Relevanz-Scoring: exakter Match > Anfang > enthält
    const terms = search.split(/\s+/).filter(Boolean);
    filtered = filtered.filter(e => {
      const eid = e.entity_id.toLowerCase();
      const ename = e.name.toLowerCase();
      const desc = (ENTITY_ANNOTATIONS[e.entity_id]?.description || '').toLowerCase();
      const role = (ENTITY_ANNOTATIONS[e.entity_id]?.role || '').toLowerCase();
      return terms.every(t => eid.includes(t) || ename.includes(t) || desc.includes(t) || role.includes(t));
    });
    // Sortierung: Relevanz
    filtered.sort((a,b) => {
      const scoreEntity = (e) => {
        const eid = e.entity_id.toLowerCase();
        const ename = e.name.toLowerCase();
        let s = 0;
        for (const t of terms) {
          if (ename === t || eid === t) s += 100;
          else if (ename.startsWith(t) || eid.startsWith(t)) s += 50;
          else if (ename.includes(t)) s += 20;
          else if (eid.includes(t)) s += 10;
        }
        if (ENTITY_ANNOTATIONS[e.entity_id]) s += 5; // Annotierte leicht bevorzugen
        return s;
      };
      return scoreEntity(b) - scoreEntity(a);
    });
  } else {
    // Ohne Suchbegriff: annotierte zuerst
    filtered.sort((a,b) => {
      const aAnn = ENTITY_ANNOTATIONS[a.entity_id] ? 0 : 1;
      const bAnn = ENTITY_ANNOTATIONS[b.entity_id] ? 0 : 1;
      if (aAnn !== bAnn) return aAnn - bAnn;
      return a.name.localeCompare(b.name);
    });
  }
  if (annFilter === 'annotated') filtered = filtered.filter(e => ENTITY_ANNOTATIONS[e.entity_id]?.role || ENTITY_ANNOTATIONS[e.entity_id]?.description);
  else if (annFilter === 'unannotated') filtered = filtered.filter(e => !ENTITY_ANNOTATIONS[e.entity_id]?.role && !ENTITY_ANNOTATIONS[e.entity_id]?.description);
  else if (annFilter === 'hidden') filtered = filtered.filter(e => ENTITY_ANNOTATIONS[e.entity_id]?.hidden);

  const c = document.getElementById('entityBrowser');

  // Such-zuerst: ohne aktiven Filter nur annotierte + Hinweis zeigen
  // Alle Treffer zeigen (lazy-load)
  _entityShowCount = 50;
  _filteredEntitiesCache = filtered;
  _renderEntityBatch();
  _updateBatchBar();
}

var _filteredEntitiesCache = [];

function _renderEntityBatch() {
  const c = document.getElementById('entityBrowser');
  const filtered = _filteredEntitiesCache;
  const show = filtered.slice(0, _entityShowCount);
  const remaining = filtered.length - _entityShowCount;
  c.innerHTML = `<div style="padding:6px 12px;font-size:11px;color:var(--text-muted);border-bottom:1px solid var(--border-color,rgba(255,255,255,0.06));">${filtered.length} Treffer</div>`
    + show.map(e => _renderEntityRow(e)).join('');
  if (remaining > 0) {
    c.innerHTML += `<div style="padding:12px;text-align:center;">
      <button class="btn btn-secondary btn-sm" onclick="_entityShowMore()">
        ${Math.min(remaining, 50)} weitere laden (${remaining} uebrig)
      </button>
    </div>`;
  }
}

function _entityShowMore() {
  _entityShowCount += 50;
  _renderEntityBatch();
  _updateBatchBar();
}

function _renderEntityRow(e) {
  const ann = ENTITY_ANNOTATIONS[e.entity_id] || {};
  const hasAnn = ann.role || ann.description;
  const roleBadge = ann.role ? `<span class="role-badge">${esc(_roleLabel(ann.role))}</span>` : '';
  const roomBadge = ann.room ? `<span class="role-badge" style="background:rgba(100,200,100,0.12);color:#6a6;">${esc(ann.room)}</span>` : '';
  const hiddenBadge = ann.hidden ? `<span class="hidden-badge">versteckt</span>` : '';
  const diagOffBadge = ann.diagnostics === false ? `<span class="hidden-badge" style="background:rgba(200,160,50,0.15);color:#b90;">keine Diagnostik</span>` : '';
  const isChecked = _annBatchSelected.has(e.entity_id);
  const cssId = e.entity_id.replace(/[^a-zA-Z0-9]/g, '_');

  const roomDlId = 'dl-room-' + cssId;

  return `
    <div class="entity-item${hasAnn ? ' annotated' : ''}">
      <input type="checkbox" class="ann-check" data-eid="${esc(e.entity_id)}" ${isChecked?'checked':''} onclick="event.stopPropagation();toggleBatchSelect('${esc(e.entity_id)}',this.checked)">
      <div style="flex:1;min-width:0;cursor:pointer;" onclick="toggleEntityDetail('${cssId}')">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <span class="ename">${esc(e.name)}</span>
          ${roleBadge}${roomBadge}${hiddenBadge}${diagOffBadge}
          <span class="eid">${esc(e.entity_id)}</span>
          <span style="color:var(--text-muted);font-size:10px;">${esc(e.state)}</span>
        </div>
      </div>
      <div class="entity-detail" id="detail-${cssId}" style="display:none;">
        <div class="form-group ann-full">
          <label>Beschreibung</label>
          <input type="text" data-ann-eid="${esc(e.entity_id)}" data-ann-field="description"
                 value="${esc(ann.description || '')}" placeholder="Was macht dieses Geraet?"
                 onchange="onAnnotationChange('${esc(e.entity_id)}')">
        </div>
        <div class="form-group">
          <label>Rolle</label>
          <input type="text" data-ann-eid="${esc(e.entity_id)}" data-ann-field="role" data-is-role="1"
                 value="${esc(ann.role ? _roleLabel(ann.role) : '')}" placeholder="Rolle eingeben..."
                 list="dl-role-${cssId}" autocomplete="off"
                 oninput="_updateRoleDatalist(this,'dl-role-${cssId}')"
                 onchange="_onRoleInputChange(this,'${esc(e.entity_id)}')">
          <datalist id="dl-role-${cssId}"></datalist>
        </div>
        <div class="form-group">
          <label>Raum</label>
          <input type="text" data-ann-eid="${esc(e.entity_id)}" data-ann-field="room"
                 value="${esc(ann.room || '')}" placeholder="Raum eingeben..."
                 list="${roomDlId}" autocomplete="off"
                 oninput="_updateRoomDatalist(this,'${roomDlId}')"
                 onchange="onAnnotationChange('${esc(e.entity_id)}')">
          <datalist id="${roomDlId}"></datalist>
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
          <div class="form-group" style="display:flex;align-items:center;gap:8px;">
            <label style="margin:0;">Diagnostik</label>
            <input type="checkbox" data-ann-eid="${esc(e.entity_id)}" data-ann-field="diagnostics"
                   ${ann.diagnostics !== false ? 'checked' : ''} onchange="onAnnotationChange('${esc(e.entity_id)}')"
                   title="Benachrichtigungen bei Offline, Batterie niedrig, Sensor veraltet">
          </div>
          <div class="form-group" style="display:flex;align-items:center;gap:8px;">
            <label style="margin:0;">Verstecken</label>
            <input type="checkbox" data-ann-eid="${esc(e.entity_id)}" data-ann-field="hidden"
                   ${ann.hidden ? 'checked' : ''} onchange="onAnnotationChange('${esc(e.entity_id)}')">
          </div>
        </div>
        ${hasAnn || ann.hidden ? `<div style="margin-top:6px;"><button class="btn btn-danger btn-sm" style="font-size:11px;padding:2px 8px;" onclick="event.stopPropagation();clearAnnotation('${esc(e.entity_id)}')">Annotation entfernen</button></div>` : ''}
      </div>
    </div>`;
}

function toggleEntityDetail(cssId) {
  const el = document.getElementById('detail-' + cssId);
  if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}

function _onRoleInputChange(input, entityId) {
  const label = (input.value || '').trim();
  const roleId = _roleLabelToId(label);
  // Speichere nur wenn gültige Rolle oder leer (=entfernen)
  if (roleId || !label) {
    onAnnotationChange(entityId);
  }
}

function onAnnotationChange(entityId) {
  // Sammle Annotation aus DOM
  const ann = {};
  document.querySelectorAll(`[data-ann-eid="${entityId}"]`).forEach(el => {
    const field = el.dataset.annField;
    if (field === 'hidden' || field === 'diagnostics') ann[field] = el.checked;
    else if (el.dataset.isRole) {
      // Rolle: Label -> ID
      ann[field] = _roleLabelToId(el.value || '');
    }
    else ann[field] = el.value;
  });
  // Nur nicht-leere Felder speichern (sparse)
  const clean = {};
  if (ann.description) clean.description = ann.description;
  if (ann.role) clean.role = ann.role;
  if (ann.room) clean.room = ann.room;
  if (ann.hidden) clean.hidden = true;
  if (ann.diagnostics === false) clean.diagnostics = false;
  if (Object.keys(clean).length > 0) ENTITY_ANNOTATIONS[entityId] = clean;
  else delete ENTITY_ANNOTATIONS[entityId];

  scheduleAnnotationSave();
}

function scheduleAnnotationSave() {
  if (_annSaveTimer) clearTimeout(_annSaveTimer);
  const st = document.getElementById('annAutoSaveStatus');
  if (st) st.textContent = 'Ungespeichert...';
  _annSaveTimer = setTimeout(async () => {
    try {
      await api('/api/ui/entity-annotations', 'PUT', { annotations: ENTITY_ANNOTATIONS });
      if (st) { st.textContent = 'Gespeichert'; setTimeout(() => { if (st) st.textContent = ''; }, 2000); }
    } catch(e) { toast('Annotations-Speichern fehlgeschlagen: ' + e.message, 'error'); }
  }, 2000);
}

// Batch-Operationen
function toggleBatchSelect(eid, checked) {
  if (checked) _annBatchSelected.add(eid); else _annBatchSelected.delete(eid);
  _updateBatchBar();
}

function toggleSelectAll(checked) {
  // Alle aktuell sichtbaren Entities (de)selektieren
  document.querySelectorAll('.ann-check').forEach(el => {
    const eid = el.dataset.eid;
    el.checked = checked;
    if (checked) _annBatchSelected.add(eid); else _annBatchSelected.delete(eid);
  });
  _updateBatchBar();
}

function _updateBatchBar() {
  const bar = document.getElementById('annBatchBar');
  const cnt = document.getElementById('annBatchCount');
  if (!bar || !cnt) return;
  if (_annBatchSelected.size > 0) {
    bar.style.display = 'flex';
    cnt.textContent = _annBatchSelected.size + ' ausgewählt';
  } else {
    bar.style.display = 'none';
  }
}

function clearBatchSelection() {
  _annBatchSelected.clear();
  document.querySelectorAll('.ann-check').forEach(el => el.checked = false);
  const selectAll = document.getElementById('annSelectAll');
  if (selectAll) selectAll.checked = false;
  _updateBatchBar();
}

function batchSetRole() {
  const input = document.getElementById('annBatchRole');
  const label = (input?.value || '').trim();
  const roleId = _roleLabelToId(label);
  if (!roleId) { toast('Rolle nicht gefunden — bitte aus Vorschlägen wählen', 'error'); return; }
  for (const eid of _annBatchSelected) {
    if (!ENTITY_ANNOTATIONS[eid]) ENTITY_ANNOTATIONS[eid] = {};
    ENTITY_ANNOTATIONS[eid].role = roleId;
  }
  input.value = '';
  scheduleAnnotationSave();
  filterEntities();
  toast(`Rolle "${_roleLabel(roleId)}" für ${_annBatchSelected.size} Entities gesetzt`);
}

function _updateRoomDatalist(input, dlId) {
  const val = (input.value || '').toLowerCase();
  const dl = document.getElementById(dlId);
  if (!dl) return;
  const rooms = _getAllRooms();
  const matches = val ? rooms.filter(r => r.toLowerCase().includes(val)) : rooms;
  dl.innerHTML = matches.map(r => `<option value="${esc(r)}">`).join('');
}

function _updateRoleDatalist(input, dlId) {
  const val = (input.value || '').toLowerCase();
  const dl = document.getElementById(dlId);
  if (!dl) return;
  const roles = _allRoles();
  const matches = Object.entries(roles).filter(([k, v]) => {
    const label = ((v.icon || '') + ' ' + (v.label || k)).toLowerCase();
    return !val || label.includes(val) || k.toLowerCase().includes(val);
  });
  dl.innerHTML = matches.map(([k, v]) => {
    const label = (v.icon ? v.icon + ' ' : '') + (v.label || k);
    return `<option value="${esc(label)}" data-role-id="${esc(k)}">`;
  }).join('');
}

function _roleLabelToId(label) {
  if (!label) return '';
  const l = label.toLowerCase().trim();
  const roles = _allRoles();
  for (const [k, v] of Object.entries(roles)) {
    const full = ((v.icon ? v.icon + ' ' : '') + (v.label || k)).toLowerCase();
    if (full === l || (v.label || k).toLowerCase() === l || k.toLowerCase() === l) return k;
  }
  return '';
}

function _getAllRooms() {
  // Räume aus allen Quellen kombinieren: RP + MindHome + bekannte + Entity-Annotations
  const rooms = new Set();
  for (const r of Object.keys(RP || {})) rooms.add(r);
  if (_mhEntities && _mhEntities.rooms) {
    for (const r of Object.keys(_mhEntities.rooms)) rooms.add(r.toLowerCase());
  }
  // Räume aus bestehenden Entity-Annotations
  for (const ann of Object.values(ENTITY_ANNOTATIONS)) {
    if (ann.room) rooms.add(ann.room);
  }
  // Räume aus _getKnownRooms (room_speakers, room_motion_sensors)
  try { for (const r of _getKnownRooms()) rooms.add(r); } catch(e) {}
  return [...rooms].sort();
}

function batchSetRoom() {
  const input = document.getElementById('annBatchRoom');
  const room = (input?.value || '').trim();
  if (!room) { toast('Bitte Raum eingeben', 'error'); return; }
  for (const eid of _annBatchSelected) {
    if (!ENTITY_ANNOTATIONS[eid]) ENTITY_ANNOTATIONS[eid] = {};
    ENTITY_ANNOTATIONS[eid].room = room;
  }
  input.value = '';
  scheduleAnnotationSave();
  filterEntities();
  toast(`Raum "${room}" für ${_annBatchSelected.size} Entities gesetzt`);
}

function clearAnnotation(entityId) {
  delete ENTITY_ANNOTATIONS[entityId];
  scheduleAnnotationSave();
  filterEntities();
  toast('Annotation entfernt');
}

function batchClearAnnotations() {
  const count = _annBatchSelected.size;
  if (count === 0) return;
  for (const eid of _annBatchSelected) {
    delete ENTITY_ANNOTATIONS[eid];
  }
  scheduleAnnotationSave();
  filterEntities();
  toast(`Annotations für ${count} Entities entfernt`);
}

function batchSetHidden(hidden) {
  for (const eid of _annBatchSelected) {
    if (!ENTITY_ANNOTATIONS[eid]) ENTITY_ANNOTATIONS[eid] = {};
    if (hidden) ENTITY_ANNOTATIONS[eid].hidden = true;
    else delete ENTITY_ANNOTATIONS[eid].hidden;
    // Cleanup leere Annotations
    const ann = ENTITY_ANNOTATIONS[eid];
    if (!ann.description && !ann.role && !ann.room && !ann.hidden) delete ENTITY_ANNOTATIONS[eid];
  }
  scheduleAnnotationSave();
  filterEntities();
  toast(`${_annBatchSelected.size} Entities ${hidden ? 'versteckt' : 'eingeblendet'}`);
}

function batchSetDiagnostics(enabled) {
  for (const eid of _annBatchSelected) {
    if (!ENTITY_ANNOTATIONS[eid]) ENTITY_ANNOTATIONS[eid] = {};
    if (enabled) {
      delete ENTITY_ANNOTATIONS[eid].diagnostics;  // true = default
    } else {
      ENTITY_ANNOTATIONS[eid].diagnostics = false;
    }
    // Cleanup leere Annotations
    const ann = ENTITY_ANNOTATIONS[eid];
    if (!ann.description && !ann.role && !ann.room && !ann.hidden && ann.diagnostics !== false) delete ENTITY_ANNOTATIONS[eid];
  }
  scheduleAnnotationSave();
  filterEntities();
  toast(`Diagnostik für ${_annBatchSelected.size} Entities ${enabled ? 'aktiviert' : 'deaktiviert'}`);
}

// Auto-Erkennung
async function discoverAnnotations() {
  try {
    const data = await api('/api/ui/entity-annotations/discover');
    const suggestions = data.suggestions || [];
    if (suggestions.length === 0) { toast('Keine neuen Vorschläge gefunden'); return; }

    // Modal/Inline anzeigen
    const c = document.getElementById('entityBrowser');
    const oldContent = c.innerHTML;
    c.innerHTML = `
      <div style="padding:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <strong>${suggestions.length} Vorschläge gefunden</strong>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-primary btn-sm" onclick="acceptDiscoverAll()">Alle übernehmen</button>
            <button class="btn btn-secondary btn-sm" onclick="acceptDiscoverSelected()">Ausgewählte übernehmen</button>
            <button class="btn btn-secondary btn-sm" onclick="filterEntities()">Abbrechen</button>
          </div>
        </div>
        <div class="ann-discover-list">
          ${suggestions.map((s,i) => `
            <div class="ann-discover-item">
              <input type="checkbox" checked class="disc-check" data-idx="${i}">
              <label>${esc(s.name)} <span style="color:var(--text-muted);font-size:10px;">${esc(s.entity_id)}</span></label>
              <span class="role-badge">${esc(_roleLabel(s.suggested_role))}</span>
              <span style="color:var(--text-muted);font-size:10px;">${esc(s.state)}</span>
            </div>`).join('')}
        </div>
      </div>`;
    // Speichere suggestions global für accept-Funktionen
    window._discoverSuggestions = suggestions;
  } catch(e) { toast('Auto-Erkennung fehlgeschlagen: ' + e.message, 'error'); }
}

function acceptDiscoverAll() {
  const suggestions = window._discoverSuggestions || [];
  for (const s of suggestions) {
    if (!ENTITY_ANNOTATIONS[s.entity_id]) ENTITY_ANNOTATIONS[s.entity_id] = {};
    ENTITY_ANNOTATIONS[s.entity_id].role = s.suggested_role;
    if (s.suggested_description && !ENTITY_ANNOTATIONS[s.entity_id].description) {
      ENTITY_ANNOTATIONS[s.entity_id].description = s.suggested_description;
    }
  }
  scheduleAnnotationSave();
  filterEntities();
  toast(`${suggestions.length} Annotations übernommen`);
}

function acceptDiscoverSelected() {
  const suggestions = window._discoverSuggestions || [];
  let count = 0;
  document.querySelectorAll('.disc-check:checked').forEach(el => {
    const idx = parseInt(el.dataset.idx);
    const s = suggestions[idx];
    if (s) {
      if (!ENTITY_ANNOTATIONS[s.entity_id]) ENTITY_ANNOTATIONS[s.entity_id] = {};
      ENTITY_ANNOTATIONS[s.entity_id].role = s.suggested_role;
      if (s.suggested_description && !ENTITY_ANNOTATIONS[s.entity_id].description) {
        ENTITY_ANNOTATIONS[s.entity_id].description = s.suggested_description;
      }
      count++;
    }
  });
  scheduleAnnotationSave();
  filterEntities();
  toast(`${count} Annotations übernommen`);
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
  if (!confirm('Wissensdatenbank komplett neu aufbauen?\n\nAlle Vektoren werden gelöscht und mit dem aktuellen Embedding-Modell neu berechnet. Das kann einige Minuten dauern.')) return;
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
  fd.append('token', TOKEN || '');

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
      c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Einträge</div>';
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
  if (!confirm(`${checked.length} Wissenseinträge unwiderruflich loeschen?`)) return;
  const ids = Array.from(checked).map(cb => cb.dataset.id);
  try {
    const d = await api('/api/ui/knowledge/chunks/delete', 'POST', { ids });
    toast(`${d.deleted} Einträge gelöscht`, 'success');
    loadKnowledge();
  } catch(e) { toast('Fehler beim Loeschen', 'error'); }
}

// ---- Recipe Store ----
async function loadRecipes() {
  try {
    const d = await api('/api/ui/recipes');
    const st = d.stats || {}, fi = d.files || [];
    document.getElementById('recipeStats').innerHTML = `
      <div class="stat-card"><div class="stat-label">Status</div>
        <div class="stat-value" style="font-size:18px;color:${st.enabled?'var(--success)':'var(--danger)'};">${st.enabled?'Aktiv':'Aus'}</div></div>
      <div class="stat-card"><div class="stat-label">Chunks</div><div class="stat-value">${st.total_chunks||0}</div></div>
      <div class="stat-card"><div class="stat-label">Rezeptdateien</div><div class="stat-value">${(st.sources||[]).length}</div>
        <div class="stat-sub">${(st.sources||[]).map(s=>esc(s)).join(', ')||'keine'}</div></div>`;
    document.getElementById('recipeFiles').innerHTML = fi.length === 0
      ? '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Rezeptdateien</div>'
      : fi.map(f => `<div class="file-item" style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border);">
          <span style="font-size:16px;">&#127859;</span>
          <span class="file-name" style="flex:1;min-width:0;">${esc(f.name)}</span>
          <span class="file-size" style="color:var(--text-muted);font-size:12px;white-space:nowrap;">${fmtBytes(f.size)}</span>
          <button class="btn" onclick="reingestRecipeFile('${esc(f.name)}')" style="font-size:11px;padding:3px 10px;white-space:nowrap;" title="Chunks loeschen und Datei neu einlesen">Neu einlesen</button>
          <button class="btn btn-danger" onclick="deleteRecipeFileChunks('${esc(f.name)}')" style="font-size:11px;padding:3px 10px;white-space:nowrap;" title="Alle Chunks dieser Datei loeschen">Entfernen</button>
        </div>`).join('');
    const sel = document.getElementById('recipeSourceFilter');
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = '<option value="">Alle Quellen</option>' +
        (st.sources||[]).map(s => `<option value="${esc(s)}" ${s===cur?'selected':''}>${esc(s)}</option>`).join('');
    }
    loadRecipeChunks();
  } catch(e) { console.error('Recipe Store fail:', e); }
}

async function rebuildRecipes() {
  if (!confirm('Rezeptdatenbank komplett neu aufbauen?\n\nAlle Vektoren werden gelöscht und mit dem aktuellen Embedding-Modell neu berechnet.')) return;
  try {
    toast('Rebuild gestartet...', 'info');
    const d = await api('/api/ui/recipes/rebuild', 'POST');
    if (d.success) {
      toast(`Rebuild fertig: ${d.new_chunks} Chunks mit ${d.embedding_model}`, 'success');
    } else {
      toast(d.error || 'Rebuild fehlgeschlagen', 'error');
    }
    loadRecipes();
  } catch(e) { toast('Rebuild fehlgeschlagen', 'error'); }
}

async function uploadRecipeFile(file) {
  if (!file) return;
  const allowed = ['.txt','.md','.pdf','.csv'];
  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (!allowed.includes(ext)) { toast('Dateityp nicht erlaubt. Nur: ' + allowed.join(', '), 'error'); return; }
  if (file.size > 10 * 1024 * 1024) { toast('Datei zu gross (max 10 MB)', 'error'); return; }

  const dz = document.getElementById('recipeDropzone');
  if (dz) { dz.style.borderColor = 'var(--primary)'; dz.querySelector('div').textContent = 'Wird hochgeladen...'; }

  const fd = new FormData();
  fd.append('file', file);
  fd.append('token', TOKEN || '');

  try {
    const resp = await fetch('/api/ui/recipes/upload', { method: 'POST', body: fd });
    if (!resp.ok) { const e = await resp.json().catch(() => ({})); throw new Error(e.detail || 'Upload fehlgeschlagen'); }
    const d = await resp.json();
    toast(`"${d.filename}" hochgeladen — ${d.new_chunks} Chunks eingelesen`, 'success');
    loadRecipes();
  } catch(e) { toast(e.message || 'Upload fehlgeschlagen', 'error'); }
  finally {
    if (dz) { dz.style.borderColor = ''; dz.querySelector('div').textContent = '\u{1F373}'; }
    const inp = document.getElementById('recipeFileInput');
    if (inp) inp.value = '';
  }
}

function initRecipeDropzone() {
  const dz = document.getElementById('recipeDropzone');
  if (!dz || dz.dataset.init) return;
  dz.dataset.init = '1';
  ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.style.borderColor = 'var(--primary)'; dz.style.background = 'var(--bg-secondary)'; }));
  ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.style.borderColor = ''; dz.style.background = ''; }));
  dz.addEventListener('drop', e => { if (e.dataTransfer.files.length) uploadRecipeFile(e.dataTransfer.files[0]); });
}

async function ingestRecipes() {
  try {
    const d = await api('/api/ui/recipes/ingest', 'POST');
    toast(`${d.new_chunks} neue Chunks eingelesen`);
    loadRecipes();
  } catch(e) { toast('Fehler beim Einlesen', 'error'); }
}

async function deleteRecipeFileChunks(filename) {
  if (!confirm(`Alle Rezeptinhalte von "${filename}" aus der Datenbank entfernen?`)) return;
  try {
    const d = await api('/api/ui/recipes/file/delete', 'POST', { filename });
    toast(`${d.deleted} Chunks von "${filename}" entfernt`, 'success');
    loadRecipes();
  } catch(e) { toast('Fehler beim Entfernen', 'error'); }
}

async function reingestRecipeFile(filename) {
  try {
    toast(`"${filename}" wird neu eingelesen...`);
    const d = await api('/api/ui/recipes/file/reingest', 'POST', { filename });
    toast(`"${filename}": ${d.new_chunks} Chunks eingelesen`, 'success');
    loadRecipes();
  } catch(e) { toast('Fehler beim Einlesen', 'error'); }
}

let recipeChunksData = [];

async function loadRecipeChunks() {
  try {
    const src = document.getElementById('recipeSourceFilter')?.value || '';
    const params = src ? `&source=${encodeURIComponent(src)}` : '';
    const d = await api(`/api/ui/recipes/chunks?limit=200${params}`);
    recipeChunksData = d.chunks || [];
    const c = document.getElementById('recipeChunks');
    if (!c) return;
    if (recipeChunksData.length === 0) {
      c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Einträge</div>';
      return;
    }
    c.innerHTML = recipeChunksData.map((ch, i) => `
      <div class="chunk-item" style="display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-bottom:1px solid var(--border);${i%2?'background:var(--bg-secondary);':''}">
        <input type="checkbox" class="recipe-chunk-cb" data-id="${esc(ch.id)}" onchange="updateRecipeDeleteBtn()" style="margin-top:3px;min-width:16px;" />
        <div style="flex:1;min-width:0;">
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:2px;">${esc(ch.source)} #${ch.chunk_index}</div>
          <div style="font-size:13px;line-height:1.4;word-break:break-word;">${esc(ch.content)}</div>
        </div>
      </div>
    `).join('');
  } catch(e) { console.error('Recipe chunks fail:', e); }
}

function updateRecipeDeleteBtn() {
  const checked = document.querySelectorAll('.recipe-chunk-cb:checked');
  const btn = document.getElementById('recipeDeleteBtn');
  if (btn) btn.style.display = checked.length > 0 ? '' : 'none';
  if (btn && checked.length > 0) btn.textContent = `${checked.length} loeschen`;
}

async function deleteSelectedRecipeChunks() {
  const checked = document.querySelectorAll('.recipe-chunk-cb:checked');
  if (checked.length === 0) return;
  if (!confirm(`${checked.length} Rezepteinträge unwiderruflich loeschen?`)) return;
  const ids = Array.from(checked).map(cb => cb.dataset.id);
  try {
    const d = await api('/api/ui/recipes/chunks/delete', 'POST', { ids });
    toast(`${d.deleted} Einträge gelöscht`, 'success');
    loadRecipes();
  } catch(e) { toast('Fehler beim Loeschen', 'error'); }
}

// ---- Logs & Audit ----
let currentLogTab = 'conversations';

function switchLogTab(tab) {
  currentLogTab = tab;
  document.querySelectorAll('#logsTabBar .tab-item').forEach(t => t.classList.toggle('active', t.dataset.logtab===tab));
  document.getElementById('logsContainer').style.display = tab==='conversations' ? '' : 'none';
  document.getElementById('activityContainer').style.display = tab==='activity' ? '' : 'none';
  document.getElementById('activityFilters').style.display = tab==='activity' ? '' : 'none';
  document.getElementById('protocolContainer').style.display = tab==='protocol' ? '' : 'none';
  document.getElementById('protocolFilters').style.display = tab==='protocol' ? '' : 'none';
  document.getElementById('auditContainer').style.display = tab==='audit' ? '' : 'none';
  if (tab==='conversations') loadLogs();
  else if (tab==='activity') loadActivity();
  else if (tab==='protocol') loadProtocol();
  else loadAudit();
  // Live-Modus beim Tab-Wechsel deaktivieren (Activity + Protocol)
  if (tab!=='activity' && _activityLiveIv) { clearInterval(_activityLiveIv); _activityLiveIv=null; const cb=document.getElementById('activityLive'); if(cb) cb.checked=false; }
  if (tab!=='protocol' && _protocolLiveIv) { clearInterval(_protocolLiveIv); _protocolLiveIv=null; const cb=document.getElementById('protocolLive'); if(cb) cb.checked=false; }
}

// ---- Aktivitätsprotokoll (Alles was Jarvis intern macht) ----
let _activityData = [];
let _activityLiveIv = null;

async function loadActivity() {
  const module = document.getElementById('activityModule').value;
  const level = document.getElementById('activityLevel').value;
  const c = document.getElementById('activityContainer');
  if (!c) return;
  try {
    const params = 'limit=500' + (module ? '&module=' + encodeURIComponent(module) : '') + (level ? '&level=' + level : '');
    const d = await api('/api/ui/activity?' + params);
    _activityData = d.items || [];
    // Module-Dropdown dynamisch befuellen
    const sel = document.getElementById('activityModule');
    const curVal = sel.value;
    const modules = d.modules || [];
    sel.innerHTML = '<option value="">Alle Module</option>' + modules.map(m =>
      '<option value="' + esc(m) + '"' + (m===curVal?' selected':'') + '>' + esc(m) + '</option>'
    ).join('');
    filterActivity();
  } catch(e) {
    c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--danger);">Fehler: ' + esc(e.message) + '</div>';
  }
}

function filterActivity() {
  const search = (document.getElementById('activitySearch').value || '').toLowerCase();
  const c = document.getElementById('activityContainer');
  if (!c) return;

  const filtered = _activityData.filter(entry => {
    if (!search) return true;
    return (entry.message || '').toLowerCase().includes(search) ||
           (entry.module || '').toLowerCase().includes(search);
  });

  document.getElementById('activityCount').textContent = filtered.length +
    (_activityData.length !== filtered.length ? ' / ' + _activityData.length : '') + ' Einträge';

  if (filtered.length === 0) {
    c.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);">' +
      (search ? 'Keine Treffer für "' + esc(search) + '"' : 'Keine Aktivitäten aufgezeichnet.') + '</div>';
    return;
  }

  const levelColors = {
    'INFO': 'var(--text-muted)',
    'WARNING': 'var(--warning, #f59e0b)',
    'ERROR': 'var(--danger, #ef4444)',
    'DEBUG': 'var(--text-secondary)'
  };
  const levelIcons = {
    'INFO': '&#9432;', 'WARNING': '&#9888;', 'ERROR': '&#10060;', 'DEBUG': '&#128736;'
  };
  const moduleColors = {
    'Proaktiv': 'var(--accent)',
    'Brain': 'var(--info, #3b82f6)',
    'Raumklima': 'var(--success, #22c55e)',
    'Geräte': 'var(--warning, #f59e0b)',
    'Diagnostik': '#8b5cf6',
    'Aktionen': 'var(--accent)',
    'Home Assistant': '#06b6d4',
    'Insights': '#ec4899',
    'Lernen': '#14b8a6',
    'Situation': '#6366f1',
    'System': 'var(--text-secondary)'
  };

  c.innerHTML = filtered.map(entry => {
    const ts = entry.timestamp
      ? new Date(entry.timestamp).toLocaleString('de-DE', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'})
      : '';
    const lvl = entry.level || 'INFO';
    const mod = entry.module || '';
    const lColor = levelColors[lvl] || 'var(--text-muted)';
    const mColor = moduleColors[mod] || 'var(--text-muted)';
    const icon = levelIcons[lvl] || '&#9432;';

    return '<div class="log-entry" style="align-items:flex-start;' + (lvl==='ERROR'?'background:color-mix(in srgb, var(--danger) 5%, transparent);':'') + (lvl==='WARNING'?'background:color-mix(in srgb, var(--warning) 5%, transparent);':'') + '">' +
      '<span class="log-time">' + ts + '</span>' +
      '<span style="font-size:15px;min-width:22px;text-align:center;">' + icon + '</span>' +
      '<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:color-mix(in srgb, ' + mColor + ' 15%, transparent);color:' + mColor + ';font-weight:600;white-space:nowrap;">' + esc(mod) + '</span>' +
      '<span style="font-size:13px;flex:1;min-width:0;word-break:break-word;">' + esc(entry.message || '') + '</span>' +
    '</div>';
  }).join('');
}

function toggleActivityLive() {
  const live = document.getElementById('activityLive').checked;
  if (live) {
    loadActivity();
    _activityLiveIv = setInterval(loadActivity, 5000);
  } else {
    if (_activityLiveIv) { clearInterval(_activityLiveIv); _activityLiveIv = null; }
  }
}

async function clearActivity() {
  if (!confirm('Aktivitätsprotokoll wirklich leeren?')) return;
  try {
    await api('/api/ui/activity', 'DELETE');
    toast('Aktivitätsprotokoll geleert');
    loadActivity();
  } catch(e) { toast('Fehler beim Leeren', 'error'); }
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
    (_protocolData.length !== filtered.length ? ' / ' + _protocolData.length : '') + ' Einträge';

  if (filtered.length === 0) {
    c.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);">' +
      (search ? 'Keine Treffer für "' + esc(search) + '"' : 'Keine Jarvis-Aktionen im Zeitraum.') + '</div>';
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
      c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Audit-Einträge</div>';
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
    if (convs.length === 0) { c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Gespräche</div>'; return; }
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
    document.getElementById('errorsInfo').textContent = `${d.total} Einträge gespeichert (max. 200)`;
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
  return sectionWrap('&#128225;', 'Live-Status & Steuerung',
    fInfo('Aktuelle Positionen aller Rollläden. Ziehe den Schieberegler oder nutze die Buttons für direkte Steuerung. 0% = geschlossen, 100% = offen.') +
    '<div style="display:flex;gap:6px;margin-bottom:10px;">' +
      '<button class="btn btn-sm" onclick="coverLiveAll(100)" style="font-size:11px;">&#9650; Alle auf</button>' +
      '<button class="btn btn-sm" onclick="coverLiveAll(0)" style="font-size:11px;">&#9660; Alle zu</button>' +
      '<button class="btn btn-sm" onclick="coverLiveAll(50)" style="font-size:11px;">&#9644; Alle 50%</button>' +
      '<button class="btn btn-sm" onclick="loadCoverLive()" style="font-size:11px;">&#128260; Aktualisieren</button>' +
    '</div>' +
    '<div id="coverLiveContainer" style="color:var(--text-secondary);padding:8px;">Lade Live-Positionen...</div>'
  ) +
  sectionWrap('&#129695;', 'Rollläden & Garagentore',
    fInfo('Hier legst du fest, welche Geräte Rollläden sind und welche Garagentore. <strong>Garagentore werden NIEMALS automatisch von Jarvis gesteuert.</strong>') +
    '<div id="coverListContainer" style="color:var(--text-secondary);padding:12px;">Lade Cover-Geräte...</div>'
  ) +
  // ── Cover-Gruppen ──────────────────────────────────────────
  sectionWrap('&#128194;', 'Cover-Gruppen',
    fInfo('Fasse mehrere Rollläden zu Gruppen zusammen (z.B. "EG Sued", "Schlafzimmer"). Gruppen können dann gemeinsam gesteuert oder in Zeitplaenen verwendet werden.') +
    '<div id="coverGroupsContainer" style="color:var(--text-secondary);padding:8px;">Lade Gruppen...</div>' +
    '<button class="btn btn-sm" onclick="addCoverGroup()" style="margin-top:8px;">+ Gruppe hinzufügen</button>'
  ) +
  // ── Cover-Szenen ──────────────────────────────────────────
  sectionWrap('&#127916;', 'Cover-Szenen',
    fInfo('Vordefinierte Positionen für mehrere Rollläden gleichzeitig. Z.B. "Lueften" = 50%, "Kino" = 20%, "Nacht" = 0%. Szenen können per Sprache oder Zeitplan aktiviert werden.') +
    '<div id="coverScenesContainer" style="color:var(--text-secondary);padding:8px;">Lade Szenen...</div>' +
    '<button class="btn btn-sm" onclick="addCoverScene()" style="margin-top:8px;">+ Szene hinzufügen</button>'
  ) +
  // ── Zeitplaene ────────────────────────────────────────────
  sectionWrap('&#128339;', 'Zeitplaene',
    fInfo('Automatische Rollladensteuerung zu festen Uhrzeiten. Pro Zeitplan: Uhrzeit, Wochentage, Ziel-Position und optional ein einzelnes Cover oder eine Gruppe.') +
    '<div id="coverSchedulesContainer" style="color:var(--text-secondary);padding:8px;">Lade Zeitplaene...</div>' +
    '<button class="btn btn-sm" onclick="addCoverSchedule()" style="margin-top:8px;">+ Zeitplan hinzufügen</button>'
  ) +
  // ── Sensor-Zuordnungen ────────────────────────────────────
  sectionWrap('&#127777;', 'Sensor-Zuordnungen',
    fInfo('Ordne Sensoren der Cover-Automatik zu. Wind-, Regen-, Sonnen- und Temperatur-Sensoren werden für automatische Entscheidungen (Sturm, Hitze, Frost) genutzt.<br><br><strong>Rollen:</strong> sun_sensor = Helligkeit, temp_outdoor = Aussentemperatur, temp_indoor = Raumtemperatur, wind_sensor = Wind, rain_sensor = Regen') +
    '<div id="coverSensorsContainer" style="color:var(--text-secondary);padding:8px;">Lade Sensor-Zuordnungen...</div>' +
    '<button class="btn btn-sm" onclick="addCoverSensor()" style="margin-top:8px;">+ Sensor zuordnen</button>'
  ) +
  // ── Öffnungs-Sensoren (Fenster/Türen/Tore) ─────────────
  sectionWrap('&#128682;', 'Öffnungs-Sensoren (Fenster / Türen / Tore)',
    fInfo('Ordne jedem Kontakt-Sensor einen Typ zu: <strong>Fenster</strong> (Kippen/Offen), <strong>Tuer</strong> oder <strong>Tor</strong> (Gartentor, Garagentor).<br><br>Nur Fenster und Türen in <strong>beheizten</strong> Räumen loesen Heizungswarnungen aus. Tore und unbeheizte Bereiche werden ignoriert.<br><br>Sensoren ohne Eintrag hier werden automatisch als "Fenster / beheizt" behandelt (Fallback).') +
    '<div id="openingSensorsContainer" style="color:var(--text-secondary);padding:8px;">Lade Öffnungs-Sensoren...</div>' +
    '<div style="display:flex;gap:6px;margin-top:8px;">' +
      '<button class="btn btn-sm" onclick="discoverOpeningSensors()" style="font-size:11px;">&#128269; Auto-Erkennung aus HA</button>' +
      '<button class="btn btn-sm" onclick="addOpeningSensor()" style="font-size:11px;">+ Manuell hinzufügen</button>' +
    '</div>'
  ) +
  // ── Letzte Aktionen (Dashboard Feature 17) ────────────
  sectionWrap('&#128203;', 'Letzte automatische Aktionen',
    fInfo('Zeigt die letzten automatischen Cover-Bewegungen mit Zeitstempel, Cover-Name, Position und Grund.') +
    '<div id="coverActionLogContainer" style="color:var(--text-secondary);padding:8px;font-size:12px;">Lade Aktions-Log...</div>' +
    '<button class="btn btn-sm" onclick="loadCoverActionLog()" style="font-size:11px;margin-top:4px;">&#128260; Aktualisieren</button>'
  ) +
  // ── Addon-Systeme Konsolidierung ──────────────────────────
  sectionWrap('&#9888;', 'Automatik-Systeme (Konsolidierung)',
    fInfo('<strong>Achtung:</strong> MindHome hat zwei Cover-Steuerungen: Die <em>ProactiveEngine</em> (Assistant, empfohlen) und das <em>Addon Cover-Domain Plugin</em>. Wenn beide aktiv sind, können sie sich gegenseitig überschreiben. Empfehlung: Addon-Plugin deaktivieren.') +
    fToggle('seasonal_actions.cover_automation.disable_addon_cover_domain', 'Addon Cover-Domain Plugin deaktivieren (empfohlen)') +
    '<button class="btn btn-sm" onclick="_syncAddonCoverDomain()" style="margin-top:6px;font-size:11px;">Jetzt am Addon anwenden</button>' +
    '<div id="addonCoverDomainStatus" style="font-size:11px;margin-top:4px;color:var(--text-muted);"></div>'
  ) +
  // ── Cover-Automatik (settings.yaml) ─────────────────────
  sectionWrap('&#9728;', 'Cover-Automatik',
    fInfo('Automatische Steuerung der Rollläden basierend auf Sonnenstand, Wetter und Temperatur. Funktioniert nur wenn Cover-Profile (unten) konfiguriert sind.') +
    fToggle('seasonal_actions.enabled', 'Saisonale Aktionen aktiv') +
    fToggle('seasonal_actions.cover_automation.sun_tracking', 'Sonnenstand-Tracking (Azimut + Elevation)') +
    fToggle('seasonal_actions.cover_automation.temperature_based', 'Temperatur-basiert (Hitze/Kälteschutz)') +
    fToggle('seasonal_actions.cover_automation.weather_protection', 'Wetter/Sturmschutz') +
    fToggle('seasonal_actions.cover_automation.night_insulation', 'Nachts schließen (Isolierung)') +
    fRange('seasonal_actions.cover_automation.heat_protection_temp', 'Hitzeschutz ab Aussentemp (°C)', 20, 40, 1, {20:'20°C',25:'25°C',26:'26°C',28:'28°C',30:'30°C',35:'35°C',40:'40°C'}) +
    fRange('seasonal_actions.cover_automation.frost_protection_temp', 'Frostschutz ab (°C)', -10, 15, 1, {'-5':'-5°C',0:'0°C',5:'5°C',10:'10°C',15:'15°C'}) +
    fRange('seasonal_actions.cover_automation.storm_wind_speed', 'Sturm-Windgeschwindigkeit (km/h)', 20, 100, 5, {20:'20',30:'30',40:'40',50:'50',60:'60',80:'80',100:'100'}) +
    fToggle('seasonal_actions.cover_automation.inverted_position', 'Positionen invertiert (0=offen, 100=zu, z.B. Shelly/MQTT)') +
    fRange('seasonal_actions.cover_automation.sunset_close_elevation', 'Rolladen schließen ab Elevation (Grad)', -6, 2, 1, {'-6':'-6°','-4':'-4°','-2':'-2° (Standard)','-1':'-1°','0':'0° (Untergang)','1':'1°','2':'2°'})
  ) +
  // ── Nacht-Isolierung (Bug 5) ──────────────────────────
  sectionWrap('&#127769;', 'Nacht-Isolierung',
    fInfo('Konfiguriere wann die Nacht-Isolierung beginnt und endet. Im Winter früher starten, im Sommer später.') +
    fRange('seasonal_actions.cover_automation.night_start_hour', 'Nacht beginnt um (Stunde)', 17, 24, 1, {17:'17',18:'18',19:'19',20:'20',21:'21',22:'22',23:'23',24:'24'}) +
    fRange('seasonal_actions.cover_automation.night_end_hour', 'Nacht endet um (Stunde)', 4, 9, 1, {4:'4',5:'5',6:'6',7:'7',8:'8',9:'9'})
  ) +
  // ── Anti-Oszillation (Feature 10) ─────────────────────
  sectionWrap('&#128200;', 'Hysterese (Anti-Oszillation)',
    fInfo('Verhindert ständiges Auf/Zu an der Grenztemperatur. Beispiel: Schließen bei 26°C, erst wieder öffnen bei 24°C (2°C Hysterese).') +
    fRange('seasonal_actions.cover_automation.hysteresis_temp', 'Temperatur-Hysterese (°C)', 0, 5, 1, {0:'Keine',1:'1°C',2:'2°C',3:'3°C',4:'4°C',5:'5°C'}) +
    fRange('seasonal_actions.cover_automation.hysteresis_wind', 'Wind-Hysterese (km/h)', 0, 20, 5, {0:'Keine',5:'5',10:'10',15:'15',20:'20'})
  ) +
  // ── Intelligente Features ─────────────────────────────
  sectionWrap('&#129504;', 'Intelligente Features',
    fInfo('Erweiterte Automatik-Features für maximalen Komfort und Energieeffizienz.') +
    fToggle('seasonal_actions.cover_automation.glare_protection', 'Blendschutz (bei besetztem Platz + Sonne)') +
    fToggle('seasonal_actions.cover_automation.gradual_morning', 'Sanftes Öffnen morgens (3 Stufen)') +
    fToggle('seasonal_actions.cover_automation.wave_open', 'Wellenförmiges Öffnen (Ost→Sued→West)') +
    fToggle('seasonal_actions.cover_automation.heating_integration', 'Heizungs-Integration (Isolierung + passive Solarwärme)') +
    fToggle('seasonal_actions.cover_automation.co2_ventilation', 'CO2-Lueftungs-Unterstuetzung') +
    fToggle('seasonal_actions.cover_automation.privacy_mode', 'Privacy-Modus (Sichtschutz abends bei Licht)') +
    fRange('seasonal_actions.cover_automation.privacy_close_hour', 'Privacy ab Uhrzeit (Stunde)', 15, 22, 1, {15:'15h',16:'16h',17:'17h',18:'18h',19:'19h',20:'20h',21:'21h',22:'22h'}) +
    fToggle('seasonal_actions.cover_automation.presence_aware', 'Praesenz-basiert (niemand zuhause = alles zu)') +
    fRange('seasonal_actions.cover_automation.manual_override_hours', 'Manueller Override-Schutz (Stunden)', 0, 6, 1, {0:'Aus',1:'1h',2:'2h',3:'3h',4:'4h',5:'5h',6:'6h'})
  ) +
  // ── Aufwach-Sonnenprüfung (sun.sun) ─────────────────
  sectionWrap('&#127765;', 'Aufwach-Sonnenprüfung (sun.sun)',
    fInfo('Verhindert dass Rollläden beim Aufwachen hochfahren wenn es noch dunkel ist. Nutzt die <strong>sun.sun</strong> Integration aus Home Assistant um den Sonnenstand zu prüfen.<br><br>Wenn die Sonnenhöhe unter dem Schwellwert liegt, werden die Rollläden automatisch erst bei Dämmerung geöffnet (deferred wake-open).<br><br><strong>Referenz:</strong> -6° = Bürgerliche Dämmerung (Himmel wird hell), 0° = Sonnenaufgang, -12° = Nautische Dämmerung (noch sehr dunkel)') +
    fToggle('seasonal_actions.cover_automation.wakeup_sun_check', 'Sonnenstand beim Aufwachen prüfen') +
    fRange('seasonal_actions.cover_automation.wakeup_min_sun_elevation', 'Min. Sonnenhöhe (Grad)', -12, 5, 1, {'-12':'-12° (nautisch)','-6':'-6° (buergerl.)','-3':'-3°','0':'0° (Aufgang)','5':'5° (hell)'}) +
    fRange('seasonal_actions.cover_automation.wakeup_fallback_max_minutes', 'Fallback: Spätestens öffnen nach (Min)', 30, 180, 15, {30:'30 Min',60:'1 Std',90:'1.5 Std',120:'2 Std',150:'2.5 Std',180:'3 Std'})
  ) +
  // ── Schlafschutz ──────────────────────────────────────
  sectionWrap('&#128564;', 'Schlafschutz',
    fInfo('Verhindert dass Rollläden hochfahren während jemand schläft. Erkennung über Aktivitäts-Modul (Bettsensoren, Lichter, Uhrzeit) und manuellen Schlafmodus ("Gute Nacht").<br><br><strong>Sleep-Lock:</strong> Wenn Schlaf erkannt wird, bleibt der Schutz für die eingestellte Dauer aktiv — auch wenn ein Sensor kurz flackert (z.B. Person dreht sich um). Nur Sturmschutz wird weiterhin ausgeführt.') +
    fRange('seasonal_actions.cover_automation.sleep_lock_minutes', 'Sleep-Lock Dauer (Minuten)', 1, 30, 1, {1:'1 Min',3:'3 Min',5:'5 Min (Standard)',10:'10 Min',15:'15 Min',30:'30 Min'})
  ) +
  // ── Vorhersage-Wetterschutz (weather.forecast_home) ──
  sectionWrap('&#127782;', 'Vorhersage-Wetterschutz (weather.forecast_home)',
    fInfo('Nutzt die <strong>Wettervorhersage</strong> aus weather.forecast_home für vorausschauenden Schutz:<br><br>&#128168; <strong>Sturmschutz:</strong> Markisen einfahren BEVOR der Sturm ankommt<br>&#127783; <strong>Regenschutz:</strong> Dachfenster schließen BEVOR es regnet<br><br>Ohne diese Option wird nur auf das <em>aktuelle</em> Wetter reagiert — dann kann es schon zu spaet sein.') +
    fEntityPickerSingle('seasonal_actions.cover_automation.weather_entity', 'Wetter-Entity', ['weather'], 'Leer = automatisch (weather.forecast_home bevorzugt). Kann auch per Sprache gewechselt werden: "Jarvis, wechsle die Wetter-Integration auf weather.home"') +
    fToggle('seasonal_actions.cover_automation.forecast_weather_protection', 'Vorhersage-basierten Wetterschutz aktivieren') +
    fRange('seasonal_actions.cover_automation.forecast_lookahead_hours', 'Vorhersage-Zeitraum (Stunden)', 1, 8, 1, {1:'1h',2:'2h',3:'3h',4:'4h',5:'5h',6:'6h',7:'7h',8:'8h'})
  ) +
  // ── Urlaubs-Simulation ─────────────────────────
  sectionWrap('&#127796;', 'Urlaubs-Simulation',
    fInfo('Simuliert Anwesenheit über Rollläden wenn der Urlaubsmodus aktiv ist. Erfordert eine input_boolean Entity in Home Assistant (z.B. input_boolean.vacation_mode).') +
    fToggle('seasonal_actions.cover_automation.presence_simulation', 'Urlaubs-Simulation aktiv') +
    fEntityPickerSingle('seasonal_actions.cover_automation.vacation_mode_entity', 'Urlaubsmodus-Entity', ['input_boolean'], 'z.B. input_boolean.vacation_mode') +
    fRange('vacation_simulation.morning_hour', 'Morgens öffnen um', 5, 11, 1) +
    fRange('vacation_simulation.evening_hour', 'Abends schließen um', 16, 22, 1) +
    fRange('vacation_simulation.night_hour', 'Nachts komplett zu um', 21, 24, 1) +
    fRange('vacation_simulation.variation_minutes', 'Zufalls-Variation (Min)', 0, 60, 5, {0:'Keine',10:'10 Min',15:'15 Min',30:'30 Min',45:'45 Min',60:'1 Std'})
  ) +
  // ── Markisen-Sicherheit (room_profiles.yaml) ─────────────
  sectionWrap('&#127958;', 'Markisen-Sicherheit',
    fInfo('Automatischer Schutz für Markisen bei Wind und Regen. Diese Einstellungen werden in room_profiles.yaml gespeichert.') +
    rpRange('markisen.wind_retract_speed', 'Einfahren bei Wind ab (km/h)', 20, 80, 5, {20:'20',30:'30',40:'40',50:'50',60:'60',80:'80'}) +
    rpToggle('markisen.rain_retract', 'Bei Regen automatisch einfahren') +
    rpRange('markisen.sun_extend_temp', 'Ausfahren bei Sonne ab (°C)', 18, 35, 1, {18:'18°C',20:'20°C',22:'22°C',25:'25°C',28:'28°C',30:'30°C',35:'35°C'})
  ) +
  // ── Power-Close (Steckdose → Rollladen) ──────────────
  sectionWrap('&#9889;', 'Strom-Automatik (z.B. TV an = Rollladen zu)',
    fInfo('Wenn der Stromverbrauch einer Steckdose einen Schwellwert überschreitet, fahren ausgewählte Rollläden automatisch runter. Sobald der Verbrauch wieder sinkt, fahren sie wieder hoch.<br><br><strong>Beispiel:</strong> TV-Steckdose > 50 W → Wohnzimmer-Rollladen zu. TV aus → Rollladen wieder auf.<br><br>Die Reaktion erfolgt <strong>sofort</strong> (Echtzeit), nicht im 15-Minuten-Takt.') +
    '<div id="powerCloseContainer" style="padding:8px;color:var(--text-secondary);">Lade Regeln...</div>' +
    '<button class="btn btn-sm" onclick="addPowerCloseRule()" style="margin-top:8px;">+ Regel hinzufügen</button>'
  ) +
  // ── Cover-Profile (room_profiles.yaml) ─────────────
  sectionWrap('&#127760;', 'Cover-Profile (Fenster-Orientierung)',
    fInfo('Konfiguriere für jedes Fenster die Himmelsrichtung und den Sonneneinfalls-Winkel. Ohne diese Profile funktioniert das Sonnenstand-Tracking nicht!<br><br><strong>Azimut-Referenz:</strong> 0°=Nord, 90°=Ost, 180°=Sued, 270°=West<br><strong>Beispiel Suedfenster:</strong> Start=120°, Ende=240°<br><strong>Beispiel Ostfenster:</strong> Start=45°, Ende=135°') +
    '<div id="coverProfilesContainer" style="padding:8px;">Lade Cover-Profile...</div>' +
    '<button class="btn btn-sm" onclick="addCoverProfile()" style="margin-top:8px;">+ Cover-Profil hinzufügen</button>'
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

// ── Room-Profiles Helpers (RP statt S) ──────────────────────
function rpGetPath(path) { return path.split('.').reduce((o,k)=>o?.[k], RP); }
function rpSetPath(path, val) {
  _rpDirty = true;
  scheduleAutoSave();
  const parts = path.split('.');
  let cur = RP;
  for(let i = 0; i < parts.length-1; i++) {
    if(cur[parts[i]] == null) cur[parts[i]] = {};
    cur = cur[parts[i]];
  }
  cur[parts[parts.length-1]] = val;
}
function rpRange(path, label, min, max, step, labels) {
  const v = rpGetPath(path) ?? min;
  const lbl = labels ? (labels[v]||v) : v;
  const lblAttr = labels ? " data-labels='" + JSON.stringify(labels).replace(/'/g,'&#39;') + "'" : '';
  return '<div class="form-group"><label>' + label + '</label>' +
    '<div class="range-group"><input type="range" data-rp-path="' + path + '"' + lblAttr + ' min="' + min + '" max="' + max + '" step="' + step + '" value="' + v + '" ' +
    'oninput="updRpRange(this);rpSetPath(\'' + path + '\',parseFloat(this.value))"><span class="range-value" id="rv_rp_' + path.replace(/\./g,'_') + '">' + lbl + '</span></div></div>';
}
function updRpRange(el) {
  const path = el.dataset.rpPath;
  let display = el.value;
  if (el.dataset.labels) {
    try {
      const labels = JSON.parse(el.dataset.labels);
      display = labels[el.value] || labels[parseFloat(el.value)] || el.value;
    } catch(e) {}
  }
  const span = document.getElementById('rv_rp_' + path.replace(/\./g,'_'));
  if (span) span.textContent = display;
}
function rpToggle(path, label) {
  const v = rpGetPath(path);
  return '<div class="form-group"><div class="toggle-group"><label>' + label + '</label>' +
    '<label class="toggle"><input type="checkbox" data-rp-path="' + path + '" ' + (v?'checked':'') + ' onchange="rpSetPath(\'' + path + '\',this.checked)"><span class="toggle-track"></span><span class="toggle-thumb"></span></label></div></div>';
}
function rpNum(path, label, min, max, step, hint) {
  const v = rpGetPath(path) ?? '';
  return '<div class="form-group"><label>' + label + '</label>' +
    '<input type="number" data-rp-path="' + path + '" value="' + v + '" min="' + (min||'') + '" max="' + (max||'') + '" step="' + (step||1) + '" ' +
    'onchange="rpSetPath(\'' + path + '\',parseFloat(this.value)||0)">' + (hint?'<div class="hint">'+hint+'</div>':'') + '</div>';
}
function rpText(path, label, hint) {
  const v = rpGetPath(path) ?? '';
  return '<div class="form-group"><label>' + label + '</label>' +
    '<input type="text" data-rp-path="' + path + '" value="' + esc(String(v)) + '" ' +
    'onchange="rpSetPath(\'' + path + '\',this.value)">' + (hint?'<div class="hint">'+hint+'</div>':'') + '</div>';
}
function rpSelect(path, label, opts) {
  const v = rpGetPath(path) ?? '';
  let h = '<div class="form-group"><label>' + label + '</label><select data-rp-path="' + path + '" onchange="rpSetPath(\'' + path + '\',this.value)">';
  for(const o of opts) h += '<option value="' + o.v + '"' + (v==o.v?' selected':'') + '>' + o.l + '</option>';
  return h + '</select></div>';
}

// Sammelt RP-Formularwerte (für collectRoomProfiles)
function collectRoomProfiles() {
  document.querySelectorAll('[data-rp-path]').forEach(el => {
    const path = el.getAttribute('data-rp-path');
    let val;
    if (el.type === 'checkbox') val = el.checked;
    else if (el.type === 'number' || el.type === 'range') val = parseFloat(el.value);
    else val = el.value;
    rpSetPath(path, val);
  });
}

// ── Addon Cover-Domain Konsolidierung ──────────────────────────────
async function _syncAddonCoverDomain() {
  const status = document.getElementById('addonCoverDomainStatus');
  if (status) status.textContent = 'Wird angewendet...';
  try {
    const res = await api('/api/ui/addon/cover-domain-toggle', 'POST', {});
    if (res && res.success) {
      const enabled = res.is_enabled;
      if (status) status.textContent = enabled ? 'Addon Cover-Domain ist jetzt AKTIV' : 'Addon Cover-Domain ist jetzt DEAKTIVIERT';
      if (status) status.style.color = enabled ? 'var(--warning)' : 'var(--success, #4caf50)';
    } else {
      if (status) { status.textContent = 'Fehler: ' + (res?.detail || 'unbekannt'); status.style.color = 'var(--danger)'; }
    }
  } catch (e) {
    if (status) { status.textContent = 'Fehler: ' + e.message; status.style.color = 'var(--danger)'; }
  }
}

// ── Zentrale Bettsensoren (room_profiles.yaml → rooms[].bed_sensors[]) ──
// Neues Format: bed_sensors = [{sensor: "binary_sensor.x", person: "Max"}, ...]

function _getBedSensorsForRoom(roomName) {
  const r = (RP.rooms || {})[roomName] || {};
  // Neues Format
  if (Array.isArray(r.bed_sensors) && r.bed_sensors.length > 0) return r.bed_sensors;
  // Alt-Migration: bed_sensor (String) → bed_sensors (Array)
  if (r.bed_sensor) return [{sensor: r.bed_sensor, person: r.bed_sensor_person || ''}];
  return [];
}

function _setBedSensorsForRoom(roomName, list) {
  if (!RP.rooms) RP.rooms = {};
  if (!RP.rooms[roomName]) RP.rooms[roomName] = {};
  RP.rooms[roomName].bed_sensors = list;
  // Alt-Keys aufräumen
  delete RP.rooms[roomName].bed_sensor;
  delete RP.rooms[roomName].bed_sensor_person;
  _rpDirty = true;
  scheduleAutoSave();
}

function renderCentralBedSensors() {
  const container = document.getElementById('centralBedSensorContainer');
  if (!container) return;
  const rooms = RP.rooms || {};
  const roomNames = Object.keys(rooms);
  if (roomNames.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Keine Räume konfiguriert. Erstelle zuerst Räume im Raum-Tab.</div>';
    return;
  }
  const members = (getPath(S, 'household.members') || []).map(m => m.name).filter(Boolean);

  // Sammle alle konfigurierten Betten
  let entries = []; // {room, index, sensor, person}
  for (const name of roomNames) {
    const beds = _getBedSensorsForRoom(name);
    for (let i = 0; i < beds.length; i++) {
      entries.push({room: name, index: i, sensor: beds[i].sensor || '', person: beds[i].person || '', off_delay: beds[i].off_delay ?? 0});
    }
  }

  let html = '';
  for (let ei = 0; ei < entries.length; ei++) {
    const e = entries[ei];
    html += '<div style="padding:10px 12px;background:var(--bg-secondary);border-radius:var(--radius-sm);margin-bottom:8px;border-left:3px solid var(--accent);">';
    // Zeile 1: Raum + Entfernen
    html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">';
    html += '<span style="font-size:13px;font-weight:600;color:var(--text-primary);">&#128719; ' + esc(e.room) + '</span>';
    html += '<button type="button" onclick="_removeBedEntry(\'' + esc(e.room) + '\',' + e.index + ')" style="font-size:11px;padding:4px 10px;background:none;color:var(--danger);border:1px solid var(--danger);border-radius:4px;cursor:pointer;">&#128465;</button>';
    html += '</div>';
    // Zeile 2: Sensor-Picker
    html += '<div style="position:relative;margin-bottom:6px;">';
    html += '<input type="text" value="' + esc(e.sensor) + '" placeholder="Sensor suchen... (z.B. bett, bed, matratze)" id="bedSensor_' + esc(e.room) + '_' + e.index + '" autocomplete="off" style="width:100%;font-size:12px;padding:8px 10px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;box-sizing:border-box;" onfocus="_bedSensorAutocomplete(this,\'' + esc(e.room) + '\',' + e.index + ')" oninput="_bedSensorAutocomplete(this,\'' + esc(e.room) + '\',' + e.index + ')" onchange="_updateBedEntry(\'' + esc(e.room) + '\',' + e.index + ',\'sensor\',this.value)">';
    html += '<div id="bedSensorDD_' + esc(e.room) + '_' + e.index + '" style="display:none;position:absolute;top:100%;left:0;right:0;max-height:150px;overflow-y:auto;background:var(--bg-card);border:1px solid var(--border);border-radius:4px;z-index:9999;"></div>';
    html += '</div>';
    // Zeile 3: Person
    if (members.length > 0) {
      html += '<select style="width:100%;font-size:12px;padding:6px 8px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;" onchange="_updateBedEntry(\'' + esc(e.room) + '\',' + e.index + ',\'person\',this.value)">';
      html += '<option value=""' + (!e.person ? ' selected' : '') + '>Person zuordnen...</option>';
      for (const m of members) {
        html += '<option value="' + esc(m) + '"' + (e.person === m ? ' selected' : '') + '>' + esc(m) + '</option>';
      }
      html += '</select>';
    }
    // Zeile 4: Off-Delay Slider (Verzögerung bei Aus-Erkennung)
    const delayVal = e.off_delay || 0;
    html += '<div style="margin-top:8px;">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">';
    html += '<label style="font-size:11px;color:var(--text-muted);">&#9202; Aus-Verzögerung</label>';
    html += '<span id="bedDelay_val_' + esc(e.room) + '_' + e.index + '" style="font-size:11px;color:var(--accent);font-weight:600;">' + delayVal + 's</span>';
    html += '</div>';
    html += '<input type="range" min="0" max="30" step="1" value="' + delayVal + '" style="width:100%;accent-color:var(--accent);" oninput="document.getElementById(\'bedDelay_val_' + esc(e.room) + '_' + e.index + '\').textContent=this.value+\'s\'" onchange="_updateBedEntry(\'' + esc(e.room) + '\',' + e.index + ',\'off_delay\',parseInt(this.value))">';
    html += '<div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text-muted);"><span>0s (sofort)</span><span>30s</span></div>';
    html += '</div>';
    html += '</div>';
  }

  // "+ Bett hinzufügen"-Button
  html += '<div style="margin-top:8px;display:flex;gap:8px;align-items:center;">';
  html += '<select id="bedAddRoomSelect" style="flex:1;font-size:12px;padding:8px 10px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;">';
  html += '<option value="">Raum wählen...</option>';
  for (const name of roomNames) {
    html += '<option value="' + esc(name) + '">' + esc(name) + '</option>';
  }
  html += '</select>';
  html += '<button type="button" onclick="_addBedEntry()" class="btn btn-sm" style="white-space:nowrap;">+ Bett</button>';
  html += '</div>';

  container.innerHTML = html;
}

function _addBedEntry() {
  const sel = document.getElementById('bedAddRoomSelect');
  if (!sel) { console.error('bedAddRoomSelect not found'); return; }
  if (!sel.value) { console.warn('Kein Raum gewählt'); return; }
  const room = sel.value;
  // Kopie der bestehenden Betten + neues leeres Bett
  const beds = _getBedSensorsForRoom(room).slice();
  beds.push({sensor: '', person: '', off_delay: 0});
  _setBedSensorsForRoom(room, beds);
  renderCentralBedSensors();
}

function _removeBedEntry(room, index) {
  const beds = _getBedSensorsForRoom(room);
  beds.splice(index, 1);
  _setBedSensorsForRoom(room, beds);
  renderCentralBedSensors();
}

function _updateBedEntry(room, index, key, value) {
  const beds = _getBedSensorsForRoom(room);
  if (!beds[index]) return;
  beds[index][key] = value;
  _setBedSensorsForRoom(room, beds);
}

async function _bedSensorAutocomplete(input, roomName, bedIndex) {
  const dd = document.getElementById('bedSensorDD_' + roomName + '_' + bedIndex);
  if (!dd) return;
  const val = input.value.toLowerCase();
  await ensurePickerEntities();
  const allEntities = _pickerEntities || [];
  const matches = allEntities.filter(e => {
    const eid = (e.entity_id || '').toLowerCase();
    return eid.startsWith('binary_sensor.') && (eid.includes('bett') || eid.includes('bed') || eid.includes('matratze') || eid.includes('occupancy') || eid.includes('presence')) && (!val || eid.includes(val));
  }).slice(0, 10);
  if (matches.length === 0) { dd.style.display = 'none'; return; }
  dd.innerHTML = matches.map(e => '<div style="padding:4px 8px;font-size:11px;cursor:pointer;color:var(--text-primary);" onmousedown="event.preventDefault();document.getElementById(\'bedSensor_' + roomName + '_' + bedIndex + '\').value=\'' + esc(e.entity_id) + '\';_updateBedEntry(\'' + roomName + '\',' + bedIndex + ',\'sensor\',\'' + esc(e.entity_id) + '\');document.getElementById(\'bedSensorDD_' + roomName + '_' + bedIndex + '\').style.display=\'none\'">' + esc(e.entity_id) + (e.attributes && e.attributes.friendly_name ? ' <span style="color:var(--text-muted);">(' + esc(e.attributes.friendly_name) + ')</span>' : '') + '</div>').join('');
  dd.style.display = 'block';
  input.addEventListener('blur', () => { setTimeout(() => { dd.style.display = 'none'; }, 200); }, {once: true});
}

// ── Cover-Profile Editor (room_profiles.yaml → cover_profiles.covers[]) ──
async function loadCoverProfiles() {
  const container = document.getElementById('coverProfilesContainer');
  if (!container) return;
  const covers = (RP.cover_profiles && RP.cover_profiles.covers) || [];
  renderCoverProfileList(covers, container);
}

function renderCoverProfileList(covers, container) {
  if (covers.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;font-size:12px;">Keine Cover-Profile konfiguriert. Fuege Profile hinzu damit Sonnenstand-Tracking funktioniert.</div>';
    return;
  }
  const orientations = ['N','NE','E','SE','S','SW','W','NW'];
  const rooms = (RP.rooms ? Object.keys(RP.rooms) : []);
  let html = '';
  for (let i = 0; i < covers.length; i++) {
    const c = covers[i];
    const typeLabel = c.type === 'markise' ? '&#127958; Markise' : '&#129695; Rollladen';
    html += '<div class="s-card" style="margin-bottom:10px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
    html += '<span style="font-size:13px;font-weight:600;">' + typeLabel + ' — ' + esc(c.entity_id || 'Neu') + '</span>';
    html += '<button class="btn btn-sm" style="color:var(--danger);border-color:var(--danger);font-size:11px;" onclick="removeCoverProfile(' + i + ')">Entfernen</button>';
    html += '</div>';
    // Entity-ID (Dropdown mit cover.* Entities)
    html += '<div class="form-group"><label>Entity-ID</label>';
    html += '<div class="entity-pick-wrap" style="position:relative;">';
    html += '<input type="text" class="form-input entity-pick-input" value="' + esc(c.entity_id||'') + '"';
    html += ' placeholder="&#128269; Cover suchen..." data-domains="cover" data-cover-idx="' + i + '"';
    html += ' oninput="entityPickFilter(this,\'cover\')" onfocus="entityPickFilter(this,\'cover\')"';
    html += ' onchange="updateCoverProfile(' + i + ',\'entity_id\',this.value)"';
    html += ' style="font-family:var(--mono);font-size:13px;">';
    html += '<div class="entity-pick-dropdown" style="display:none;"></div>';
    html += '</div></div>';
    // Raum
    html += '<div class="form-group"><label>Raum</label><select onchange="updateCoverProfile(' + i + ',\'room\',this.value)">';
    html += '<option value="">— Bitte wählen —</option>';
    for (const r of rooms) html += '<option value="' + r + '"' + (c.room===r?' selected':'') + '>' + r + '</option>';
    html += '</select></div>';
    // Typ
    html += '<div class="form-group"><label>Typ</label><select onchange="updateCoverProfile(' + i + ',\'type\',this.value)">';
    html += '<option value="rollladen"' + (c.type!=='markise'?' selected':'') + '>Rollladen</option>';
    html += '<option value="markise"' + (c.type==='markise'?' selected':'') + '>Markise</option>';
    html += '</select></div>';
    // Orientierung
    html += '<div class="form-group"><label>Orientierung (Himmelsrichtung)</label><select onchange="updateCoverProfile(' + i + ',\'orientation\',this.value)">';
    for (const o of orientations) html += '<option value="' + o + '"' + (c.orientation===o?' selected':'') + '>' + o + '</option>';
    html += '</select></div>';
    // Azimut Start/End
    html += '<div style="display:flex;gap:12px;">';
    html += '<div class="form-group" style="flex:1;"><label>Sonnen-Azimut Start (°)</label><input type="number" value="' + (c.sun_exposure_start||0) + '" min="0" max="360" step="5" onchange="updateCoverProfile(' + i + ',\'sun_exposure_start\',parseInt(this.value))"></div>';
    html += '<div class="form-group" style="flex:1;"><label>Sonnen-Azimut Ende (°)</label><input type="number" value="' + (c.sun_exposure_end||0) + '" min="0" max="360" step="5" onchange="updateCoverProfile(' + i + ',\'sun_exposure_end\',parseInt(this.value))"></div>';
    html += '</div>';
    // Toggles
    html += '<div style="display:flex;gap:16px;flex-wrap:wrap;">';
    html += '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox"' + (c.allow_auto!==false?' checked':'') + ' onchange="updateCoverProfile(' + i + ',\'allow_auto\',this.checked)" style="accent-color:var(--accent);"> Automatik erlaubt</label>';
    html += '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox"' + (c.heat_protection?' checked':'') + ' onchange="updateCoverProfile(' + i + ',\'heat_protection\',this.checked)" style="accent-color:var(--accent);"> Hitzeschutz</label>';
    html += '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;" title="Aktivieren wenn 0=offen und 100=zu (z.B. Shelly, MQTT)"><input type="checkbox"' + (c.inverted?' checked':'') + ' onchange="updateCoverProfile(' + i + ',\'inverted\',this.checked)" style="accent-color:var(--accent);"> Position invertiert</label>';
    html += '</div>';
    // Privacy close hour
    html += '<div class="form-group" style="margin-top:8px;"><label>Privatsph&auml;re schließen ab (Uhr, optional)</label><input type="number" value="' + (c.privacy_close_hour||'') + '" min="0" max="23" placeholder="z.B. 17" onchange="updateCoverProfile(' + i + ',\'privacy_close_hour\',this.value?parseInt(this.value):null)"></div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

function updateCoverProfile(idx, key, value) {
  if (!RP.cover_profiles) RP.cover_profiles = {covers: []};
  if (!RP.cover_profiles.covers) RP.cover_profiles.covers = [];
  if (RP.cover_profiles.covers[idx]) {
    RP.cover_profiles.covers[idx][key] = value;
    _rpDirty = true;
    scheduleAutoSave();
  }
}

function addCoverProfile() {
  if (!RP.cover_profiles) RP.cover_profiles = {covers: []};
  if (!RP.cover_profiles.covers) RP.cover_profiles.covers = [];
  RP.cover_profiles.covers.push({
    entity_id: '', room: '', type: 'rollladen', orientation: 'S',
    sun_exposure_start: 120, sun_exposure_end: 240,
    allow_auto: true, heat_protection: true, inverted: false, privacy_close_hour: null
  });
  _rpDirty = true;
  scheduleAutoSave();
  const container = document.getElementById('coverProfilesContainer');
  if (container) renderCoverProfileList(RP.cover_profiles.covers, container);
}

function removeCoverProfile(idx) {
  if (!RP.cover_profiles || !RP.cover_profiles.covers) return;
  RP.cover_profiles.covers.splice(idx, 1);
  _rpDirty = true;
  scheduleAutoSave();
  const container = document.getElementById('coverProfilesContainer');
  if (container) renderCoverProfileList(RP.cover_profiles.covers, container);
}

// ── Cover Live-Status & Steuerung ──────────────────────────────────
let _coverLiveData = [];

async function loadCoverLive() {
  const container = document.getElementById('coverLiveContainer');
  if (!container) return;
  try {
    const d = await api('/api/ui/covers/live');
    _coverLiveData = (d.covers || []).filter(c => c.cover_type !== 'garage_door' && c.enabled !== false);
    renderCoverLive(container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--danger);padding:8px;">Fehler: ' + esc(e.message) + '</div>';
  }
}

function renderCoverLive(container) {
  if (_coverLiveData.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Keine aktiven Cover gefunden.</div>';
    return;
  }
  let html = '';
  for (const c of _coverLiveData) {
    const pos = c.current_position != null ? c.current_position : '?';
    const posNum = typeof pos === 'number' ? pos : 50;
    const stateColor = c.state === 'open' ? 'var(--success)' : c.state === 'closed' ? 'var(--danger)' : 'var(--text-muted)';
    const stateLabel = c.state === 'open' ? 'Offen' : c.state === 'closed' ? 'Zu' : c.state === 'opening' ? 'Oeffnet...' : c.state === 'closing' ? 'Schliesst...' : c.state;
    const typeIcon = c.cover_type === 'awning' ? '&#127958;' : c.cover_type === 'blind' ? '&#129695;' : c.cover_type === 'roof_window' ? '&#127968;' : '&#129695;';
    html += '<div style="display:flex;align-items:center;gap:10px;padding:10px 12px;margin-bottom:6px;border-radius:8px;background:var(--bg-card);border:1px solid var(--border);">';
    // Info
    html += '<div style="flex:1;min-width:0;">';
    html += '<div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + typeIcon + ' ' + esc(c.name) + '</div>';
    html += '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;">';
    html += '<span style="font-size:10px;color:' + stateColor + ';font-weight:600;">' + stateLabel + '</span>';
    html += '<span style="font-size:10px;color:var(--text-muted);font-family:var(--mono);">' + pos + '%</span>';
    html += '</div></div>';
    // Position Slider
    html += '<div style="flex:2;display:flex;align-items:center;gap:6px;">';
    html += '<span style="font-size:10px;color:var(--text-muted);">0</span>';
    html += '<input type="range" min="0" max="100" step="5" value="' + posNum + '" style="flex:1;accent-color:var(--accent);" onchange="setCoverLivePosition(\'' + esc(c.entity_id) + '\',parseInt(this.value))">';
    html += '<span style="font-size:10px;color:var(--text-muted);">100</span>';
    html += '</div>';
    // Buttons
    html += '<div style="display:flex;gap:4px;flex-shrink:0;">';
    html += '<button class="btn btn-sm" onclick="coverLiveOpen(\'' + esc(c.entity_id) + '\')" title="Öffnen" style="font-size:12px;padding:4px 8px;">&#9650;</button>';
    html += '<button class="btn btn-sm" onclick="coverLiveStop(\'' + esc(c.entity_id) + '\')" title="Stopp" style="font-size:12px;padding:4px 8px;">&#9632;</button>';
    html += '<button class="btn btn-sm" onclick="coverLiveClose(\'' + esc(c.entity_id) + '\')" title="Schließen" style="font-size:12px;padding:4px 8px;">&#9660;</button>';
    html += '</div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

async function setCoverLivePosition(entityId, position) {
  try {
    await api('/api/ui/covers/' + entityId + '/position', 'POST', {position});
    toast('Position ' + position + '% gesetzt');
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function coverLiveOpen(entityId) {
  try {
    await api('/api/ui/covers/' + entityId + '/open', 'POST');
    toast('Oeffne...');
    setTimeout(loadCoverLive, 2000);
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function coverLiveClose(entityId) {
  try {
    await api('/api/ui/covers/' + entityId + '/close', 'POST');
    toast('Schliesse...');
    setTimeout(loadCoverLive, 2000);
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function coverLiveStop(entityId) {
  try {
    await api('/api/ui/covers/' + entityId + '/stop', 'POST');
    toast('Gestoppt');
    setTimeout(loadCoverLive, 1000);
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function coverLiveAll(position) {
  const promises = _coverLiveData.map(c =>
    api('/api/ui/covers/' + c.entity_id + '/position', 'POST', {position}).catch(() => null)
  );
  await Promise.all(promises);
  toast('Alle Cover auf ' + position + '%');
  setTimeout(loadCoverLive, 3000);
}

// ── Cover-Gruppen CRUD ─────────────────────────────────────────────
let _coverGroups = [];

async function loadCoverGroups() {
  const container = document.getElementById('coverGroupsContainer');
  if (!container) return;
  try {
    const result = await api('/api/ui/covers/groups');
    _coverGroups = Array.isArray(result) ? result : [];
    renderCoverGroups(container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Gruppen nicht verfügbar (Addon nicht erreichbar).</div>';
  }
}

function renderCoverGroups(container) {
  if (_coverGroups.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Gruppen konfiguriert.</div>';
    return;
  }
  let html = '';
  for (const g of _coverGroups) {
    const entityList = (g.entity_ids || []).join(', ');
    html += '<div class="s-card" style="margin-bottom:8px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
    html += '<span style="font-size:13px;font-weight:600;">&#128194; ' + esc(g.name) + '</span>';
    html += '<div style="display:flex;gap:4px;">';
    html += '<button class="btn btn-sm" onclick="controlCoverGroup(' + g.id + ',100)" title="Alle öffnen" style="font-size:11px;">&#9650;</button>';
    html += '<button class="btn btn-sm" onclick="controlCoverGroup(' + g.id + ',0)" title="Alle schließen" style="font-size:11px;">&#9660;</button>';
    html += '<button class="btn btn-sm" style="color:var(--danger);border-color:var(--danger);font-size:11px;" onclick="deleteCoverGroup(' + g.id + ')">Entfernen</button>';
    html += '</div></div>';
    // Name Edit
    html += '<div class="form-group"><label>Name</label><input type="text" value="' + esc(g.name) + '" onchange="updateCoverGroup(' + g.id + ',{name:this.value})" style="font-size:12px;"></div>';
    // Entity IDs
    html += '<div class="form-group"><label>Cover-Entities (kommagetrennt)</label>';
    html += '<input type="text" value="' + esc(entityList) + '" placeholder="cover.wohnzimmer, cover.küche" onchange="updateCoverGroup(' + g.id + ',{entity_ids:this.value.split(\',\').map(s=>s.trim()).filter(Boolean)})" style="font-size:11px;font-family:var(--mono);">';
    html += '</div>';
    // Position Slider
    html += '<div style="display:flex;align-items:center;gap:8px;margin-top:4px;">';
    html += '<label style="font-size:11px;color:var(--text-secondary);min-width:60px;">Position:</label>';
    html += '<input type="range" min="0" max="100" step="5" value="50" style="flex:1;accent-color:var(--accent);" id="grpSlider_' + g.id + '">';
    html += '<button class="btn btn-sm" onclick="controlCoverGroup(' + g.id + ',parseInt(document.getElementById(\'grpSlider_' + g.id + '\').value))" style="font-size:11px;">Setzen</button>';
    html += '</div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

async function addCoverGroup() {
  try {
    const result = await api('/api/ui/covers/groups', 'POST', {name: 'Neue Gruppe', entity_ids: []});
    toast('Gruppe erstellt');
    loadCoverGroups();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function updateCoverGroup(groupId, data) {
  try {
    await api('/api/ui/covers/groups/' + groupId, 'PUT', data);
    toast('Gruppe aktualisiert');
    loadCoverGroups();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function deleteCoverGroup(groupId) {
  if (!confirm('Gruppe wirklich loeschen?')) return;
  try {
    await api('/api/ui/covers/groups/' + groupId, 'DELETE');
    toast('Gruppe gelöscht');
    loadCoverGroups();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function controlCoverGroup(groupId, position) {
  try {
    await api('/api/ui/covers/groups/' + groupId + '/control', 'POST', {position});
    toast('Gruppe auf ' + position + '%');
    setTimeout(loadCoverLive, 2000);
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

// ── Cover-Szenen CRUD ──────────────────────────────────────────────
let _coverScenes = [];

async function loadCoverScenes() {
  const container = document.getElementById('coverScenesContainer');
  if (!container) return;
  try {
    const result = await api('/api/ui/covers/scenes');
    _coverScenes = Array.isArray(result) ? result : [];
    renderCoverScenes(container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Szenen nicht verfügbar (Addon nicht erreichbar).</div>';
  }
}

function renderCoverScenes(container) {
  if (_coverScenes.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Szenen konfiguriert.</div>';
    return;
  }
  let html = '';
  for (const s of _coverScenes) {
    const positions = s.positions || {};
    const posStr = Object.entries(positions).map(([eid, pos]) => {
      if (typeof pos === 'object') return eid.replace('cover.','') + ':' + (pos.position != null ? pos.position + '%' : '') + (pos.tilt != null ? ' T' + pos.tilt : '');
      return eid.replace('cover.','') + ':' + pos + '%';
    }).join(', ');
    html += '<div class="s-card" style="margin-bottom:8px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
    html += '<span style="font-size:13px;font-weight:600;">&#127916; ' + esc(s.name) + '</span>';
    html += '<div style="display:flex;gap:4px;">';
    html += '<button class="btn btn-sm" onclick="activateCoverScene(' + s.id + ')" style="font-size:11px;background:var(--accent);color:var(--bg-primary);border-color:var(--accent);">&#9654; Aktivieren</button>';
    html += '<button class="btn btn-sm" style="color:var(--danger);border-color:var(--danger);font-size:11px;" onclick="deleteCoverScene(' + s.id + ')">Entfernen</button>';
    html += '</div></div>';
    // Name Edit
    html += '<div class="form-group"><label>Name</label><input type="text" value="' + esc(s.name) + '" onchange="updateCoverScene(' + s.id + ',{name:this.value})" style="font-size:12px;"></div>';
    // Positions display
    html += '<div class="form-group"><label>Positionen (entity:position)</label>';
    html += '<div style="font-size:11px;color:var(--text-secondary);font-family:var(--mono);padding:6px 8px;background:var(--bg-primary);border-radius:4px;border:1px solid var(--border);min-height:24px;">';
    html += posStr || '<em style="color:var(--text-muted);">Keine Positionen definiert</em>';
    html += '</div></div>';
    // Add position editor
    html += '<div id="sceneEditor_' + s.id + '">';
    html += _renderScenePositionEditor(s);
    html += '</div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

function _renderScenePositionEditor(scene) {
  const positions = scene.positions || {};
  const entries = Object.entries(positions);
  let html = '<div style="margin-top:4px;">';
  for (let i = 0; i < entries.length; i++) {
    const [eid, pos] = entries[i];
    const posVal = typeof pos === 'object' ? (pos.position || 0) : pos;
    html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">';
    html += '<input type="text" value="' + esc(eid) + '" placeholder="cover.entity" style="flex:2;font-size:11px;font-family:var(--mono);padding:2px 4px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;" data-scene-id="' + scene.id + '" data-pos-idx="' + i + '" data-field="entity">';
    html += '<input type="number" value="' + posVal + '" min="0" max="100" step="5" style="width:60px;font-size:11px;padding:2px 4px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;" data-scene-id="' + scene.id + '" data-pos-idx="' + i + '" data-field="position">';
    html += '<span style="font-size:10px;color:var(--text-muted);">%</span>';
    html += '<button type="button" onclick="removeScenePosition(' + scene.id + ',\'' + esc(eid) + '\')" style="font-size:10px;padding:1px 6px;background:none;color:var(--danger);border:1px solid var(--danger);border-radius:3px;cursor:pointer;opacity:0.7;" title="Entfernen">&times;</button>';
    html += '</div>';
  }
  html += '<button type="button" onclick="addScenePosition(' + scene.id + ')" style="margin-top:4px;font-size:11px;padding:3px 10px;background:var(--bg-hover);color:var(--accent);border:1px solid var(--border);border-radius:4px;cursor:pointer;">+ Position</button>';
  html += '</div>';
  return html;
}

async function addCoverScene() {
  try {
    await api('/api/ui/covers/scenes', 'POST', {name: 'Neue Szene', positions: {}});
    toast('Szene erstellt');
    loadCoverScenes();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function updateCoverScene(sceneId, data) {
  try {
    await api('/api/ui/covers/scenes/' + sceneId, 'PUT', data);
    toast('Szene aktualisiert');
    loadCoverScenes();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function deleteCoverScene(sceneId) {
  if (!confirm('Szene wirklich loeschen?')) return;
  try {
    await api('/api/ui/covers/scenes/' + sceneId, 'DELETE');
    toast('Szene gelöscht');
    loadCoverScenes();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function activateCoverScene(sceneId) {
  try {
    await api('/api/ui/covers/scenes/' + sceneId + '/activate', 'POST');
    toast('Szene aktiviert');
    setTimeout(loadCoverLive, 2000);
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

function addScenePosition(sceneId) {
  const scene = _coverScenes.find(s => s.id === sceneId);
  if (!scene) return;
  const positions = scene.positions || {};
  positions['cover.'] = 100;
  updateCoverScene(sceneId, {positions});
}

function removeScenePosition(sceneId, entityId) {
  const scene = _coverScenes.find(s => s.id === sceneId);
  if (!scene) return;
  const positions = {...(scene.positions || {})};
  delete positions[entityId];
  updateCoverScene(sceneId, {positions});
}

// ── Cover-Zeitplaene CRUD ──────────────────────────────────────────
let _coverSchedules = [];

async function loadCoverSchedules() {
  const container = document.getElementById('coverSchedulesContainer');
  if (!container) return;
  try {
    const result = await api('/api/ui/covers/schedules');
    _coverSchedules = Array.isArray(result) ? result : [];
    renderCoverSchedules(container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Zeitplaene nicht verfügbar (Addon nicht erreichbar).</div>';
  }
}

function renderCoverSchedules(container) {
  if (_coverSchedules.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Zeitplaene konfiguriert.</div>';
    return;
  }
  const dayLabels = ['Mo','Di','Mi','Do','Fr','Sa','So'];
  let html = '';
  for (const s of _coverSchedules) {
    const days = s.days || [0,1,2,3,4,5,6];
    const target = s.entity_id ? s.entity_id : s.group_id ? 'Gruppe #' + s.group_id : 'Alle Cover';
    html += '<div class="s-card" style="margin-bottom:8px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
    html += '<span style="font-size:13px;font-weight:600;">&#128339; ' + esc(s.time_str || '??:??') + ' &rarr; ' + s.position + '%</span>';
    html += '<div style="display:flex;gap:4px;">';
    html += '<label style="display:flex;align-items:center;gap:3px;font-size:11px;cursor:pointer;"><input type="checkbox"' + (s.is_active !== false ? ' checked' : '') + ' onchange="updateCoverSchedule(' + s.id + ',{is_active:this.checked})" style="accent-color:var(--accent);"> Aktiv</label>';
    html += '<button class="btn btn-sm" style="color:var(--danger);border-color:var(--danger);font-size:11px;" onclick="deleteCoverSchedule(' + s.id + ')">Entfernen</button>';
    html += '</div></div>';
    // Time
    html += '<div style="display:flex;gap:12px;flex-wrap:wrap;">';
    html += '<div class="form-group" style="flex:1;min-width:100px;"><label>Uhrzeit</label><input type="time" value="' + esc(s.time_str || '08:00') + '" onchange="updateCoverSchedule(' + s.id + ',{time_str:this.value})" style="font-size:12px;"></div>';
    html += '<div class="form-group" style="flex:1;min-width:100px;"><label>Position (%)</label><input type="number" value="' + (s.position ?? 100) + '" min="0" max="100" step="5" onchange="updateCoverSchedule(' + s.id + ',{position:parseInt(this.value)})" style="font-size:12px;"></div>';
    html += '</div>';
    // Target
    html += '<div class="form-group"><label>Ziel (Cover-Entity oder leer für alle)</label>';
    html += '<input type="text" value="' + esc(s.entity_id || '') + '" placeholder="cover.wohnzimmer (oder leer)" onchange="updateCoverSchedule(' + s.id + ',{entity_id:this.value||null})" style="font-size:11px;font-family:var(--mono);">';
    html += '</div>';
    // Days
    html += '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;">';
    for (let d = 0; d < 7; d++) {
      const active = days.includes(d);
      const bgColor = active ? 'var(--accent)' : 'var(--bg-primary)';
      const txtColor = active ? 'var(--bg-primary)' : 'var(--text-muted)';
      html += '<button type="button" onclick="toggleScheduleDay(' + s.id + ',' + d + ')" style="width:32px;height:28px;font-size:11px;font-weight:600;border:1px solid var(--border);border-radius:4px;cursor:pointer;background:' + bgColor + ';color:' + txtColor + ';">' + dayLabels[d] + '</button>';
    }
    html += '</div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

async function addCoverSchedule() {
  try {
    await api('/api/ui/covers/schedules', 'POST', {
      time_str: '08:00', position: 100, days: [0,1,2,3,4,5,6]
    });
    toast('Zeitplan erstellt');
    loadCoverSchedules();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function updateCoverSchedule(scheduleId, data) {
  try {
    await api('/api/ui/covers/schedules/' + scheduleId, 'PUT', data);
    toast('Zeitplan aktualisiert');
    loadCoverSchedules();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function deleteCoverSchedule(scheduleId) {
  if (!confirm('Zeitplan wirklich loeschen?')) return;
  try {
    await api('/api/ui/covers/schedules/' + scheduleId, 'DELETE');
    toast('Zeitplan gelöscht');
    loadCoverSchedules();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

function toggleScheduleDay(scheduleId, day) {
  const schedule = _coverSchedules.find(s => s.id === scheduleId);
  if (!schedule) return;
  const days = [...(schedule.days || [0,1,2,3,4,5,6])];
  const idx = days.indexOf(day);
  if (idx >= 0) days.splice(idx, 1); else days.push(day);
  days.sort();
  updateCoverSchedule(scheduleId, {days});
}

// ── Cover-Sensor-Zuordnungen ───────────────────────────────────────
let _coverSensors = [];

async function loadCoverSensors() {
  const container = document.getElementById('coverSensorsContainer');
  if (!container) return;
  try {
    const result = await api('/api/ui/covers/sensors');
    _coverSensors = Array.isArray(result) ? result : [];
    renderCoverSensors(container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Sensor-Zuordnungen nicht verfügbar (Addon nicht erreichbar).</div>';
  }
}

function renderCoverSensors(container) {
  const roleLabels = {
    sun_sensor: '&#9728; Sonnensensor',
    temp_outdoor: '&#127777; Aussentemperatur',
    temp_indoor: '&#127777; Innentemperatur',
    wind_sensor: '&#127744; Windsensor',
    rain_sensor: '&#127783; Regensensor',
    cover: '&#129695; Cover',
  };
  const roleOptions = ['sun_sensor','temp_outdoor','temp_indoor','wind_sensor','rain_sensor'];

  if (_coverSensors.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Sensoren zugeordnet. Fuege Sensoren hinzu damit die Cover-Automatik Wind, Regen und Temperatur erkennt.</div>';
    return;
  }

  let html = '';
  // Group by role
  const byRole = {};
  for (const s of _coverSensors) {
    if (!byRole[s.role]) byRole[s.role] = [];
    byRole[s.role].push(s);
  }
  for (const role of roleOptions) {
    const items = byRole[role] || [];
    if (items.length === 0) continue;
    html += '<div style="margin-bottom:10px;">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:4px;">' + (roleLabels[role] || role) + '</div>';
    for (const s of items) {
      html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;margin-bottom:3px;background:var(--bg-card);border:1px solid var(--border);border-radius:6px;">';
      html += '<span style="flex:1;font-size:12px;font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(s.entity_id) + '</span>';
      html += '<span style="font-size:10px;color:var(--text-muted);background:var(--bg-primary);padding:1px 6px;border-radius:3px;">' + esc(s.role) + '</span>';
      html += '<button type="button" onclick="deleteCoverSensor(' + s.id + ')" style="font-size:10px;padding:1px 6px;background:none;color:var(--danger);border:1px solid var(--danger);border-radius:3px;cursor:pointer;opacity:0.7;" title="Entfernen">&times;</button>';
      html += '</div>';
    }
    html += '</div>';
  }
  // Ungruppierte (cover role etc)
  const other = _coverSensors.filter(s => !roleOptions.includes(s.role));
  if (other.length > 0) {
    html += '<div style="margin-bottom:10px;">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px;">Sonstige</div>';
    for (const s of other) {
      html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;margin-bottom:3px;background:var(--bg-card);border:1px solid var(--border);border-radius:6px;">';
      html += '<span style="flex:1;font-size:12px;font-family:var(--mono);">' + esc(s.entity_id) + '</span>';
      html += '<span style="font-size:10px;color:var(--text-muted);background:var(--bg-primary);padding:1px 6px;border-radius:3px;">' + esc(s.role) + '</span>';
      html += '<button type="button" onclick="deleteCoverSensor(' + s.id + ')" style="font-size:10px;padding:1px 6px;background:none;color:var(--danger);border:1px solid var(--danger);border-radius:3px;cursor:pointer;opacity:0.7;" title="Entfernen">&times;</button>';
      html += '</div>';
    }
    html += '</div>';
  }
  container.innerHTML = html;
}

async function addCoverSensor() {
  const roleOptions = ['sun_sensor','temp_outdoor','temp_indoor','wind_sensor','rain_sensor'];
  const roleLabels = {sun_sensor:'Sonnensensor',temp_outdoor:'Aussentemperatur',temp_indoor:'Innentemperatur',wind_sensor:'Windsensor',rain_sensor:'Regensensor'};
  // Build a small inline form
  const container = document.getElementById('coverSensorsContainer');
  if (!container) return;
  // Check if form already exists
  if (document.getElementById('addSensorForm')) return;
  const form = document.createElement('div');
  form.id = 'addSensorForm';
  form.style.cssText = 'margin-top:10px;padding:12px;border:2px solid var(--accent);border-radius:8px;background:var(--bg-card);';
  let formHtml = '<div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:8px;">Neuen Sensor zuordnen</div>';
  formHtml += '<div class="form-group"><label>Entity-ID</label>';
  formHtml += '<input type="text" id="newSensorEntity" placeholder="sensor.wind_speed oder binary_sensor.rain" style="font-size:11px;font-family:var(--mono);">';
  formHtml += '</div>';
  formHtml += '<div class="form-group"><label>Rolle</label><select id="newSensorRole" style="font-size:12px;">';
  for (const r of roleOptions) formHtml += '<option value="' + r + '">' + (roleLabels[r]||r) + '</option>';
  formHtml += '</select></div>';
  formHtml += '<div style="display:flex;gap:6px;">';
  formHtml += '<button class="btn btn-sm" onclick="submitCoverSensor()" style="font-size:11px;background:var(--accent);color:var(--bg-primary);border-color:var(--accent);">Hinzufuegen</button>';
  formHtml += '<button class="btn btn-sm" onclick="document.getElementById(\'addSensorForm\').remove()" style="font-size:11px;">Abbrechen</button>';
  formHtml += '</div>';
  form.innerHTML = formHtml;
  container.parentNode.insertBefore(form, container.nextSibling.nextSibling);
}

async function submitCoverSensor() {
  const entityId = document.getElementById('newSensorEntity').value.trim();
  const role = document.getElementById('newSensorRole').value;
  if (!entityId) { toast('Entity-ID eingeben', 'error'); return; }
  try {
    await api('/api/ui/covers/sensors', 'POST', {entity_id: entityId, role: role});
    toast('Sensor zugeordnet');
    const form = document.getElementById('addSensorForm');
    if (form) form.remove();
    loadCoverSensors();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function deleteCoverSensor(assignmentId) {
  try {
    await api('/api/ui/covers/sensors/' + assignmentId, 'DELETE');
    toast('Sensor-Zuordnung entfernt');
    loadCoverSensors();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

// ── Cover Action Log (Dashboard Feature 17) ──────────────────────

async function loadCoverActionLog() {
  const container = document.getElementById('coverActionLogContainer');
  if (!container) return;
  try {
    const result = await api('/api/ui/covers/action-log?limit=10');
    const entries = Array.isArray(result) ? result : [];
    if (entries.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Noch keine automatischen Aktionen aufgezeichnet.</div>';
      return;
    }
    let html = '<div style="display:flex;flex-direction:column;gap:4px;">';
    for (const e of entries) {
      const ts = new Date(e.ts * 1000);
      const timeStr = ts.toLocaleString('de-DE', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
      const eid = (e.entity_id || '').replace('cover.', '');
      const posColor = e.position > 50 ? 'var(--accent)' : e.position === 0 ? 'var(--danger)' : 'var(--text-secondary)';
      html += '<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;background:var(--bg-card);border:1px solid var(--border);border-radius:6px;">';
      html += '<span style="font-size:10px;color:var(--text-muted);min-width:80px;font-family:var(--mono);">' + esc(timeStr) + '</span>';
      html += '<span style="font-size:11px;font-weight:600;min-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(eid) + '</span>';
      html += '<span style="font-size:11px;color:' + posColor + ';font-weight:600;min-width:35px;">' + e.position + '%</span>';
      html += '<span style="font-size:10px;color:var(--text-muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(e.reason || '') + '</span>';
      html += '</div>';
    }
    html += '</div>';
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Aktions-Log nicht verfügbar.</div>';
  }
}

// ── Power-Close Regeln (Steckdose → Rollladen) ────────────────────
let _powerCloseRules = [];

async function loadPowerCloseRules() {
  const container = document.getElementById('powerCloseContainer');
  if (!container) return;
  try {
    const result = await api('/api/ui/covers/power-close');
    _powerCloseRules = Array.isArray(result) ? result : [];
    renderPowerCloseRules(container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Power-Close nicht verfügbar.</div>';
  }
}

function renderPowerCloseRules(container) {
  if (_powerCloseRules.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Regeln konfiguriert. Klicke "+ Regel hinzufügen" um eine Steckdose mit Rollläden zu verknuepfen.</div>';
    return;
  }
  let html = '';
  for (const r of _powerCloseRules) {
    const covers = (r.cover_ids || []).join(', ');
    const activeColor = r.is_active !== false ? 'var(--accent)' : 'var(--text-muted)';
    html += '<div class="s-card" style="margin-bottom:8px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
    html += '<span style="font-size:13px;font-weight:600;color:' + activeColor + ';">&#9889; ' + esc(r.power_sensor || '???') + ' &ge; ' + (r.threshold || 50) + ' W</span>';
    html += '<div style="display:flex;gap:4px;">';
    html += '<label style="display:flex;align-items:center;gap:3px;font-size:11px;cursor:pointer;"><input type="checkbox"' + (r.is_active !== false ? ' checked' : '') + ' onchange="updatePowerCloseRule(' + r.id + ',{is_active:this.checked})" style="accent-color:var(--accent);"> Aktiv</label>';
    html += '<button class="btn btn-sm" style="color:var(--danger);border-color:var(--danger);font-size:11px;" onclick="deletePowerCloseRule(' + r.id + ')">Entfernen</button>';
    html += '</div></div>';
    // Sensor
    html += '<div style="display:flex;gap:12px;flex-wrap:wrap;">';
    html += '<div class="form-group" style="flex:1;min-width:200px;"><label>Leistungs-Sensor (Watt)</label>';
    html += '<div class="entity-pick-wrap"><input class="form-input entity-pick-input" value="' + esc(r.power_sensor || '') + '" placeholder="&#128269; sensor.steckdose_tv_power" data-domains="sensor" oninput="entityPickFilter(this,\'sensor\')" onfocus="entityPickFilter(this,\'sensor\')" onchange="updatePowerCloseRule(' + r.id + ',{power_sensor:this.value})" style="font-size:12px;font-family:var(--mono);"><div class="entity-pick-dropdown" style="display:none;"></div></div></div>';
    html += '<div class="form-group" style="width:120px;"><label>Schwelle (Watt)</label><input type="number" value="' + (r.threshold || 50) + '" min="1" max="5000" step="5" onchange="updatePowerCloseRule(' + r.id + ',{threshold:parseInt(this.value)})" style="font-size:12px;"></div>';
    html += '<div class="form-group" style="width:120px;"><label>Position (%)</label><input type="number" value="' + (r.close_position ?? 0) + '" min="0" max="100" step="5" onchange="updatePowerCloseRule(' + r.id + ',{close_position:parseInt(this.value)})" style="font-size:12px;"></div>';
    html += '</div>';
    // Covers – Entity-Picker mit Tags
    html += '<div class="form-group"><label>Rollläden</label>';
    html += '<div class="entity-pick-wrap">';
    html += '<div class="kw-editor" data-entity-picker="list" data-domains="cover" data-powerclose-id="' + r.id + '" onclick="this.querySelector(\'input\')?.focus()" style="min-height:36px;">';
    for (const cid of (r.cover_ids || [])) {
      html += '<span class="kw-tag">' + esc(cid) + '<span class="kw-rm" onclick="removePowerCloseCover(' + r.id + ',\'' + esc(cid) + '\')">&#10005;</span></span>';
    }
    html += '<input class="kw-input entity-pick-input" placeholder="&#128269; cover suchen..." data-powerclose-id="' + r.id + '" oninput="entityPickFilter(this,\'cover\')" onfocus="entityPickFilter(this,\'cover\')" style="font-size:11px;font-family:var(--mono);">';
    html += '</div>';
    html += '<div class="entity-pick-dropdown" style="display:none;"></div>';
    html += '</div></div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

async function addPowerCloseRule() {
  try {
    await api('/api/ui/covers/power-close', 'POST', {
      power_sensor: '', threshold: 50, cover_ids: [], close_position: 0
    });
    toast('Regel erstellt');
    loadPowerCloseRules();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function updatePowerCloseRule(ruleId, data) {
  try {
    await api('/api/ui/covers/power-close/' + ruleId, 'PUT', data);
    toast('Regel aktualisiert');
    loadPowerCloseRules();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

async function deletePowerCloseRule(ruleId) {
  if (!confirm('Regel wirklich loeschen?')) return;
  try {
    await api('/api/ui/covers/power-close/' + ruleId, 'DELETE');
    toast('Regel gelöscht');
    loadPowerCloseRules();
  } catch (e) { toast('Fehler: ' + e.message, 'error'); }
}

function removePowerCloseCover(ruleId, coverId) {
  const rule = _powerCloseRules.find(r => r.id === ruleId);
  if (!rule) return;
  const newCovers = (rule.cover_ids || []).filter(c => c !== coverId);
  updatePowerCloseRule(ruleId, {cover_ids: newCovers});
}

function addPowerCloseCover(ruleId, coverId) {
  const rule = _powerCloseRules.find(r => r.id === ruleId);
  if (!rule) return;
  const covers = rule.cover_ids || [];
  if (!covers.includes(coverId)) {
    covers.push(coverId);
    updatePowerCloseRule(ruleId, {cover_ids: covers});
  }
}

// ── Öffnungs-Sensoren (Fenster/Türen/Tore) ──────────────────────
let _openingSensors = {};

async function loadOpeningSensors() {
  const container = document.getElementById('openingSensorsContainer');
  if (!container) return;
  try {
    const d = await api('/api/ui/opening-sensors');
    _openingSensors = d.entities || {};
    renderOpeningSensors(container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Fehler beim Laden: ' + esc(e.message) + '</div>';
  }
}

function renderOpeningSensors(container) {
  const entries = Object.entries(_openingSensors);
  if (entries.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Öffnungs-Sensoren konfiguriert. Nutze "Auto-Erkennung" um Sensoren aus Home Assistant zu importieren.</div>';
    return;
  }
  const typeColors = {window: 'var(--accent)', door: 'var(--success)', gate: 'var(--warning, #f59e0b)'};
  const typeIcons = {window: '&#129695;', door: '&#128682;', gate: '&#9961;'};
  const rooms = RP.rooms ? Object.keys(RP.rooms) : [];

  let html = '<div style="font-size:11px;color:var(--text-muted);margin-bottom:8px;">Gesamt: ' + entries.length + ' Sensoren | ' +
    entries.filter(([,c])=>c.type==='window').length + ' Fenster, ' +
    entries.filter(([,c])=>c.type==='door').length + ' Türen, ' +
    entries.filter(([,c])=>c.type==='gate').length + ' Tore</div>';

  for (const [entityId, cfg] of entries) {
    const t = cfg.type || 'window';
    const borderColor = cfg.heated === false ? 'var(--text-muted)' : typeColors[t] || 'var(--border)';
    const opacity = cfg.heated === false ? '0.7' : '1';
    // Friendly name aus entity_id ableiten (binary_sensor.fenster_wohnzimmer → Fenster Wohnzimmer)
    const shortName = entityId.replace(/^binary_sensor\./, '').replace(/_/g, ' ');
    html += '<div style="padding:8px 10px;margin-bottom:4px;border-radius:6px;background:var(--bg-card);border:1px solid ' + borderColor + ';opacity:' + opacity + ';">';
    // Zeile 1: Name + Icon + Loeschen-Button
    html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">';
    html += '<span style="font-size:14px;">' + (typeIcons[t] || '') + '</span>';
    html += '<div style="flex:1;min-width:0;">';
    html += '<div style="font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(shortName) + '</div>';
    html += '<div style="font-size:10px;color:var(--text-muted);font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(entityId) + '">' + esc(entityId) + '</div>';
    html += '</div>';
    html += '<button type="button" onclick="removeOpeningSensor(\'' + esc(entityId) + '\')" style="flex-shrink:0;font-size:12px;padding:2px 6px;background:none;color:var(--danger);border:1px solid var(--danger);border-radius:3px;cursor:pointer;opacity:0.7;" title="Entfernen">&times;</button>';
    html += '</div>';
    // Zeile 2: Controls (flex-wrap für Mobile)
    html += '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">';
    // Typ
    html += '<div style="display:flex;align-items:center;gap:4px;min-width:90px;">';
    html += '<span style="font-size:10px;color:var(--text-muted);">Typ</span>';
    html += '<select onchange="updateOpeningSensor(\'' + esc(entityId) + '\',\'type\',this.value)" style="flex:1;font-size:11px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;padding:3px 4px;">';
    html += '<option value="window"' + (t==='window'?' selected':'') + '>Fenster</option>';
    html += '<option value="door"' + (t==='door'?' selected':'') + '>Tuer</option>';
    html += '<option value="gate"' + (t==='gate'?' selected':'') + '>Tor</option>';
    html += '</select></div>';
    // Raum
    html += '<div style="display:flex;align-items:center;gap:4px;flex:1;min-width:120px;">';
    html += '<span style="font-size:10px;color:var(--text-muted);">Raum</span>';
    html += '<select onchange="updateOpeningSensor(\'' + esc(entityId) + '\',\'room\',this.value||null)" style="flex:1;font-size:11px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;padding:3px 4px;">';
    html += '<option value="">— kein Raum —</option>';
    for (const r of rooms) html += '<option value="' + esc(r) + '"' + (cfg.room===r?' selected':'') + '>' + esc(r) + '</option>';
    html += '</select></div>';
    // Beheizt
    html += '<label style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer;flex-shrink:0;" title="Beheizt = Heizungswarnung wenn offen">';
    html += '<input type="checkbox"' + (cfg.heated !== false ? ' checked' : '') + ' onchange="updateOpeningSensor(\'' + esc(entityId) + '\',\'heated\',this.checked)" style="accent-color:var(--accent);width:16px;height:16px;">';
    html += '<span>Beheizt</span></label>';
    html += '</div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

function updateOpeningSensor(entityId, field, value) {
  if (!_openingSensors[entityId]) _openingSensors[entityId] = {type: 'window', heated: true};
  _openingSensors[entityId][field] = value;
  scheduleOpeningSensorSave();
  const container = document.getElementById('openingSensorsContainer');
  if (container) renderOpeningSensors(container);
}

function removeOpeningSensor(entityId) {
  delete _openingSensors[entityId];
  saveOpeningSensors();
  const container = document.getElementById('openingSensorsContainer');
  if (container) renderOpeningSensors(container);
}

let _osSaveTimer = null;
function scheduleOpeningSensorSave() {
  if (_osSaveTimer) clearTimeout(_osSaveTimer);
  const status = document.getElementById('autoSaveStatus');
  if (status) { status.textContent = 'Ungespeichert...'; status.className = 'auto-save-status'; }
  _osSaveTimer = setTimeout(() => _doSaveOpeningSensors(), 1500);
}
async function _doSaveOpeningSensors() {
  _osSaveTimer = null;
  const status = document.getElementById('autoSaveStatus');
  if (status) { status.textContent = 'Speichert...'; status.className = 'auto-save-status saving'; }
  try {
    await api('/api/ui/opening-sensors', 'PUT', {entities: _openingSensors});
    if (status) { status.textContent = 'Gespeichert'; status.className = 'auto-save-status saved'; setTimeout(() => { if (status && !_osSaveTimer) status.textContent = ''; }, 3000); }
  } catch (e) {
    toast('Fehler beim Speichern: ' + e.message, 'error');
    if (status) { status.textContent = 'Fehler!'; status.className = 'auto-save-status'; }
  }
}
async function saveOpeningSensors() {
  // Sofort-Save (für Loeschen/Hinzufuegen)
  const status = document.getElementById('autoSaveStatus');
  if (status) { status.textContent = 'Speichert...'; status.className = 'auto-save-status saving'; }
  try {
    await api('/api/ui/opening-sensors', 'PUT', {entities: _openingSensors});
    if (status) { status.textContent = 'Gespeichert'; status.className = 'auto-save-status saved'; setTimeout(() => { if (status && !_osSaveTimer) status.textContent = ''; }, 3000); }
  } catch (e) {
    toast('Fehler beim Speichern: ' + e.message, 'error');
    if (status) { status.textContent = 'Fehler!'; status.className = 'auto-save-status'; }
  }
}

function addOpeningSensor() {
  const container = document.getElementById('openingSensorsContainer');
  if (!container || document.getElementById('addOpeningForm')) return;
  const form = document.createElement('div');
  form.id = 'addOpeningForm';
  form.style.cssText = 'margin-top:10px;padding:12px;border:2px solid var(--accent);border-radius:8px;background:var(--bg-card);';
  let h = '<div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:8px;">Neuen Sensor hinzufügen</div>';
  h += '<div class="form-group"><label>Entity-ID</label><input type="text" id="newOpeningEntity" placeholder="binary_sensor.fenster_wohnzimmer" style="font-size:11px;font-family:var(--mono);"></div>';
  h += '<div style="display:flex;flex-wrap:wrap;gap:8px;">';
  h += '<div class="form-group" style="flex:1;min-width:100px;"><label>Typ</label><select id="newOpeningType" style="font-size:11px;"><option value="window">Fenster</option><option value="door">Tuer</option><option value="gate">Tor</option></select></div>';
  h += '<div class="form-group" style="flex:1;min-width:100px;"><label>Beheizt</label><select id="newOpeningHeated" style="font-size:11px;"><option value="true">Ja</option><option value="false">Nein</option></select></div>';
  h += '</div>';
  h += '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
  h += '<button class="btn btn-sm" onclick="submitOpeningSensor()" style="font-size:11px;background:var(--accent);color:var(--bg-primary);border-color:var(--accent);">Hinzufuegen</button>';
  h += '<button class="btn btn-sm" onclick="document.getElementById(\'addOpeningForm\').remove()" style="font-size:11px;">Abbrechen</button>';
  h += '</div>';
  form.innerHTML = h;
  container.parentNode.appendChild(form);
}

function submitOpeningSensor() {
  const eid = document.getElementById('newOpeningEntity').value.trim();
  if (!eid) { toast('Entity-ID eingeben', 'error'); return; }
  const type = document.getElementById('newOpeningType').value;
  const heated = document.getElementById('newOpeningHeated').value === 'true';
  _openingSensors[eid] = {type, heated, room: null};
  saveOpeningSensors();
  const form = document.getElementById('addOpeningForm');
  if (form) form.remove();
  const container = document.getElementById('openingSensorsContainer');
  if (container) renderOpeningSensors(container);
  toast('Sensor hinzugefuegt');
}

async function discoverOpeningSensors() {
  try {
    const d = await api('/api/ui/opening-sensors/discover');
    const sensors = d.sensors || [];
    if (sensors.length === 0) { toast('Keine passenden Sensoren in HA gefunden'); return; }
    let added = 0;
    for (const s of sensors) {
      if (!_openingSensors[s.entity_id]) {
        _openingSensors[s.entity_id] = {
          type: s.suggested_type || 'window',
          heated: s.suggested_type !== 'gate',
          room: null,
        };
        added++;
      }
    }
    if (added > 0) {
      await saveOpeningSensors();
      toast(added + ' neue Sensoren importiert');
    } else {
      toast('Alle Sensoren bereits konfiguriert');
    }
    const container = document.getElementById('openingSensorsContainer');
    if (container) renderOpeningSensors(container);
  } catch (e) { toast('Fehler bei Auto-Erkennung: ' + e.message, 'error'); }
}

// ── Licht-Tab (tab-lights) ─────────────────────────────────────
function renderLights() {
  return sectionWrap('&#127968;', 'Raum-Licht-Zuordnung',
    fInfo('Ordne jedem Raum seine Licht-Entities zu. Pro Lampe kannst du individuelle Helligkeit (Tag/Nacht) einstellen. Die Zuordnung wird in den Raum-Profilen gespeichert.') +
    '<div id="lightRoomContainer" style="padding:8px;color:var(--text-secondary);">Lade Räume und Licht-Entities...</div>'
  ) +
  sectionWrap('&#9881;', 'Automatik-Regeln',
    fInfo('Regeln für automatische Lichtsteuerung. Einmal konfigurieren — Jarvis erledigt den Rest.<br>Die Bewegungsmelder aus dem Räume-Tab werden für die Leer-Raum-Erkennung genutzt.') +
    fToggle('lighting.enabled', 'Lichtsteuerung aktiv') +
    fToggle('lighting.auto_on_dusk', 'Auto-An bei Dämmerung (wenn jemand zuhause)') +
    fToggle('lighting.auto_off_away', 'Auto-Aus bei Abwesenheit (alle weg)') +
    fRange('lighting.auto_off_empty_room_minutes', 'Licht aus nach leerem Raum (Min)', 5, 120, 5, {5:'5 Min',10:'10 Min',15:'15 Min',30:'30 Min',45:'45 Min',60:'1 Std',90:'1.5 Std',120:'2 Std'}) +
    fToggle('lighting.night_dimming', 'Nacht-Dimming (automatisch dunkler ab 21 Uhr)') +
    fRange('lighting.night_dimming_start_hour', 'Night-Dimming Start (Uhrzeit)', 19, 23, 1, {19:'19 Uhr',20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr'}) +
    fRange('lighting.night_dimming_transition', 'Night-Dimming Übergang (Sek)', 60, 600, 30, {60:'1 Min',120:'2 Min',180:'3 Min',300:'5 Min',600:'10 Min'}) +
    fToggle('lighting.daylight_off', 'Tageslicht-Hinweis (Licht an bei Sonnenschein)') +
    fToggle('lighting.dusk_only_occupied_rooms', 'Dämmerung: Nur Räume mit Praesenz einschalten') +
    fRange('lighting.default_transition', 'Standard-Übergang (Sekunden)', 0, 10, 1, {0:'Sofort',1:'1s',2:'2s',3:'3s',5:'5s',7:'7s',10:'10s'})
  ) +
  sectionWrap('&#128065;', 'Praesenz-gesteuerte Beleuchtung',
    fInfo('Bewegung im Raum erkennen und Licht automatisch einschalten. Nachts wird statt voller Helligkeit nur ein sanftes Orientierungslicht in Flur und Bad aktiviert. Pro Raum konfigurierbar in der Raum-Zuordnung oben.') +
    fToggle('lighting.presence_control.enabled', 'Praesenz-Steuerung aktiv') +
    fToggle('lighting.presence_control.auto_on_motion', 'Licht an bei Bewegung') +
    fToggle('lighting.presence_control.night_path_light', 'Nacht-Pfadlicht (sanftes Orientierungslicht)') +
    fRange('lighting.presence_control.night_path_brightness', 'Pfadlicht-Helligkeit (%)', 3, 20, 1, {3:'3%',5:'5%',8:'8%',10:'10%',15:'15%',20:'20%'}) +
    fRange('lighting.presence_control.night_path_timeout_minutes', 'Pfadlicht Auto-Aus (Min)', 2, 15, 1, {2:'2 Min',3:'3 Min',5:'5 Min',7:'7 Min',10:'10 Min',15:'15 Min'}) +
    fRange('lighting.presence_control.manual_override_minutes', 'Override-Schutz nach manueller Bedienung (Min)', 5, 180, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std'}) +
    fRange('lighting.presence_control.night_start_hour', 'Nacht beginnt (Uhrzeit)', 20, 24, 1, {20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr',24:'0 Uhr'}) +
    fRange('lighting.presence_control.night_end_hour', 'Nacht endet (Uhrzeit)', 4, 8, 1, {4:'4 Uhr',5:'5 Uhr',6:'6 Uhr',7:'7 Uhr',8:'8 Uhr'})
  ) +
  sectionWrap('&#128716;', 'Bettsensor-Integration',
    fInfo('Bettsensor erkennt Schlafen und Aufwachen. Bei Bett-Belegung abends werden alle Lichter sanft ausgeschaltet (Sleep-Mode). Beim Aufstehen morgens wird graduell aufgehellt. Nachts gibt es Pfadlicht in Flur/Bad. Bettsensor pro Raum zuordnen in der Raum-Zuordnung oben.') +
    fToggle('lighting.bed_sensors.enabled', 'Bettsensor-Integration aktiv') +
    fToggle('lighting.bed_sensors.sleep_mode', 'Sleep-Mode (alle Lichter aus bei Bett belegt)') +
    fRange('lighting.bed_sensors.sleep_dim_transition', 'Sleep-Dimming Dauer (Sek)', 60, 600, 30, {60:'1 Min',120:'2 Min',180:'3 Min',300:'5 Min',600:'10 Min'}) +
    fRange('lighting.bed_sensors.sleep_start_hour', 'Schlafmodus ab (Uhrzeit)', 20, 24, 1, {20:'20 Uhr',21:'21 Uhr',22:'22 Uhr',23:'23 Uhr',24:'0 Uhr'}) +
    fToggle('lighting.bed_sensors.wakeup_light', 'Aufwach-Licht (graduelles Aufhellen)') +
    fRange('lighting.bed_sensors.wakeup_brightness', 'Aufwach-Helligkeit (%)', 10, 80, 5, {10:'10%',20:'20%',30:'30%',40:'40%',50:'50%',60:'60%',80:'80%'}) +
    fRange('lighting.bed_sensors.wakeup_transition', 'Aufhell-Dauer (Sek)', 30, 300, 15, {30:'30s',60:'1 Min',90:'1.5 Min',120:'2 Min',180:'3 Min',300:'5 Min'}) +
    fRange('lighting.bed_sensors.wakeup_window_start', 'Aufwach-Fenster Start', 4, 8, 1, {4:'4 Uhr',5:'5 Uhr',6:'6 Uhr',7:'7 Uhr',8:'8 Uhr'}) +
    fRange('lighting.bed_sensors.wakeup_window_end', 'Aufwach-Fenster Ende', 7, 11, 1, {7:'7 Uhr',8:'8 Uhr',9:'9 Uhr',10:'10 Uhr',11:'11 Uhr'})
  ) +
  sectionWrap('&#9728;', 'Lux-adaptive Helligkeit',
    fInfo('Passt künstliches Licht automatisch an das vorhandene Tageslicht an. Bei viel Sonnenlicht wird weniger Kunstlicht verwendet, bei wenig Licht mehr. Lux-Sensor pro Raum zuordnen in der Raum-Zuordnung oben.') +
    fToggle('lighting.lux_adaptive.enabled', 'Lux-Adaptiv aktiv') +
    fRange('lighting.lux_adaptive.target_lux', 'Ziel-Beleuchtungsstaerke (Lux)', 100, 800, 50, {100:'100',200:'200',300:'300',400:'400',500:'500',600:'600',800:'800'}) +
    fRange('lighting.lux_adaptive.min_brightness_pct', 'Minimale Kunstlicht-Helligkeit (%)', 5, 30, 5, {5:'5%',10:'10%',15:'15%',20:'20%',25:'25%',30:'30%'}) +
    fRange('lighting.lux_adaptive.max_brightness_pct', 'Maximale Kunstlicht-Helligkeit (%)', 50, 100, 10, {50:'50%',60:'60%',70:'70%',80:'80%',90:'90%',100:'100%'})
  ) +
  sectionWrap('&#127782;', 'Wetter-Integration (sun.sun + weather)',
    fInfo('Nutzt die Wetterbedingung aus Home Assistant für intelligentere Lichtsteuerung:<br><br>&#9729; <strong>Wetter-Boost:</strong> Bei Bewölkung oder Regen werden eingeschaltete Lichter automatisch heller (+X%).<br>&#127769; <strong>Frühere Dämmerung:</strong> An trüben Tagen wird die Dämmerungs-Schwelle angehoben — Licht geht früher an.<br><br>Nutzt <strong>sun.sun</strong> für den Sonnenstand und die konfigurierte <strong>weather.*</strong> Entity für die Wetterlage.') +
    fToggle('lighting.weather_boost.enabled', 'Wetter-Integration aktiv') +
    fEntityPickerSingle('lighting.weather_boost.weather_entity', 'Wetter-Entity', ['weather'], 'Leer = automatisch (gleiche Entity wie Cover-Automatik)') +
    fRange('lighting.weather_boost.cloud_boost_pct', 'Helligkeits-Boost bei Bewölkung (%)', 0, 40, 5, {0:'Aus',5:'5%',10:'10%',15:'15%',20:'20%',25:'25%',30:'30%',40:'40%'}) +
    fRange('lighting.weather_boost.rain_boost_pct', 'Helligkeits-Boost bei Regen (%)', 0, 50, 5, {0:'Aus',5:'5%',10:'10%',15:'15%',20:'20%',25:'25%',30:'30%',40:'40%',50:'50%'}) +
    fToggle('lighting.weather_boost.dusk_earlier_on_cloudy', 'Dämmerung früher bei Bewölkung') +
    fRange('lighting.weather_boost.dusk_cloud_elevation_offset', 'Dämmerung-Offset bei Wolken (Grad)', 1, 8, 1, {1:'1°',2:'2°',3:'3°',4:'4°',5:'5°',6:'6°',7:'7°',8:'8°'})
  ) +
  sectionWrap('&#127749;', 'Zirkadiane Beleuchtung',
    fInfo('Passt Helligkeit (und bei tunable_white auch Farbtemperatur) automatisch an den Tagesverlauf an. dim2warm-Lampen regeln die Farbtemperatur über die Helligkeit in der Hardware — hier wird nur die Helligkeitskurve gesteuert.<br><br><strong>Modi:</strong><br>&bull; <strong>MindHome:</strong> Jarvis steuert die Helligkeitskurve komplett<br>&bull; <strong>Hybrid HCL:</strong> MDT AKD HCL läuft als Basis, Jarvis überschreibt bei Events') +
    fToggle('lighting.circadian.enabled', 'Zirkadiane Beleuchtung aktiv') +
    fSelect('lighting.circadian.mode', 'Modus', [{v:'mindhome',l:'MindHome (Jarvis steuert)'},{v:'hybrid_hcl',l:'Hybrid HCL (MDT AKD Basis)'}]) +
    fRange('lighting.circadian.transition_seconds', 'Übergangszeit (Sekunden)', 1, 15, 1, {1:'1s',2:'2s',3:'3s',5:'5s',7:'7s',10:'10s',15:'15s'}) +
    '<div id="circadianCurveEditor"></div>'
  ) +
  sectionWrap('&#127916;', 'Szenen-Übergänge',
    fInfo('Der globale Standard-Übergang wird im <strong>Sprache</strong>-Tab unter "Szenen & Narration" konfiguriert. Pro-Szene-Übergänge findest du im Szenen-Tab.') +
    `<div class="info-box" style="margin-top:8px;cursor:pointer;" onclick="document.querySelector('[data-tab=tab-voice]').click()">
      <span class="info-icon">&#127908;</span>Standard-Übergang konfigurierst du im <strong>Sprache</strong>-Tab. Klicke hier.
    </div>` +
    `<div class="info-box" style="margin-top:8px;cursor:pointer;" onclick="document.querySelector('[data-tab=tab-scenes]').click()">
      <span class="info-icon">&#127916;</span>Einzelne Szenen-Übergänge verwaltest du im <strong>Szenen</strong>-Tab. Klicke hier.
    </div>`
  );
}

// ── Zirkadiane Kurven Editor (Interaktive SVG-Grafik) ─────────
let _circDrag = null; // {curveType, index, svg, rect}

const CIRC_FIXED_TIMES = ['00:00','01:00','02:00','03:00','04:00','05:00','06:00','07:00','08:00','09:00','10:00','11:00','12:00','13:00','14:00','15:00','16:00','17:00','18:00','19:00','20:00','21:00','22:00','23:00'];
const CIRC_DEFAULT_BRI = [5, 5, 5, 5, 5, 5, 10, 40, 70, 90, 100, 100, 100, 100, 100, 100, 100, 90, 80, 60, 40, 25, 10, 5];
const CIRC_DEFAULT_CT  = [2200, 2200, 2200, 2200, 2200, 2200, 2700, 3000, 3500, 4500, 5000, 5500, 5500, 5500, 5500, 5000, 5000, 4500, 3500, 3000, 2700, 2700, 2200, 2200];

function _ensureFixedCircadianCurve(path, curveType) {
  const curve = getPath(S, path) || [];
  if (curve.length === 24) return curve;
  // Reset to 24 fixed points (one per hour) with defaults
  const defaults = curveType === 'bri' ? CIRC_DEFAULT_BRI : CIRC_DEFAULT_CT;
  const key = curveType === 'bri' ? 'pct' : 'kelvin';
  const newCurve = CIRC_FIXED_TIMES.map((t, i) => ({time: t, [key]: defaults[i]}));
  setPath(S, path, newCurve);
  return newCurve;
}

function renderCircadianCurveEditor() {
  const container = document.getElementById('circadianCurveEditor');
  if (!container) return;
  const bCurve = _ensureFixedCircadianCurve('lighting.circadian.brightness_curve', 'bri');
  const ctCurve = _ensureFixedCircadianCurve('lighting.circadian.ct_curve', 'ct');

  let html = '<div style="margin-top:12px;">';

  // Brightness Curve
  html += '<div style="margin-bottom:20px;">';
  html += '<div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:8px;">Helligkeitskurve (% über den Tag)</div>';
  html += '<div id="circBriChart"></div>';
  html += '</div>';

  // Color Temperature Curve
  html += '<div>';
  html += '<div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:8px;">Farbtemperatur-Kurve (Kelvin, nur tunable_white)</div>';
  html += '<div id="circCtChart"></div>';
  html += '</div>';

  html += '</div>';
  container.innerHTML = html;

  _renderCircadianSVG('bri', bCurve, 'pct', '%', 0, 100, '#f4b400', 'circBriChart');
  _renderCircadianSVG('ct', ctCurve, 'kelvin', 'K', 1800, 6500, '#4fc3f7', 'circCtChart');
}

function _renderCircadianSVG(curveType, curve, valueKey, unit, vMin, vMax, color, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;

  const W = 600, H = 220, PAD_L = 42, PAD_R = 12, PAD_T = 20, PAD_B = 28;
  const cW = W - PAD_L - PAD_R, cH = H - PAD_T - PAD_B;

  // Sort curve by time
  const sorted = (curve || []).slice().sort((a, b) => _timeToMin(a.time) - _timeToMin(b.time));

  let svg = `<svg width="100%" viewBox="0 0 ${W} ${H}" style="max-width:${W}px;background:var(--bg-primary);border:1px solid var(--border);border-radius:6px;user-select:none;" data-curvetype="${curveType}">`;

  // Grid lines & labels - hours
  for (let h = 0; h <= 24; h += 3) {
    const x = PAD_L + (h / 24) * cW;
    svg += `<line x1="${x}" y1="${PAD_T}" x2="${x}" y2="${PAD_T + cH}" stroke="var(--border)" stroke-width="0.5" stroke-dasharray="${h % 6 === 0 ? 'none' : '2,2'}"/>`;
    if (h % 6 === 0) svg += `<text x="${x}" y="${H - 6}" text-anchor="middle" fill="var(--text-muted)" font-size="9">${String(h).padStart(2,'0')}:00</text>`;
  }

  // Grid lines & labels - values
  const vSteps = curveType === 'ct' ? [1800, 2700, 3500, 4500, 5500, 6500] : [0, 20, 40, 60, 80, 100];
  for (const v of vSteps) {
    const y = PAD_T + cH - ((v - vMin) / (vMax - vMin)) * cH;
    svg += `<line x1="${PAD_L}" y1="${y}" x2="${PAD_L + cW}" y2="${y}" stroke="var(--border)" stroke-width="0.5" stroke-dasharray="2,2"/>`;
    svg += `<text x="${PAD_L - 4}" y="${y + 3}" text-anchor="end" fill="var(--text-muted)" font-size="8">${curveType === 'ct' ? (v/1000).toFixed(1) + 'k' : v + '%'}</text>`;
  }

  // Filled area + line
  if (sorted.length > 1) {
    let areaPath = `M ${PAD_L + (_timeToMin(sorted[0].time) / 1440) * cW} ${PAD_T + cH}`;
    let linePath = '';
    for (let i = 0; i < sorted.length; i++) {
      const x = PAD_L + (_timeToMin(sorted[i].time) / 1440) * cW;
      const y = PAD_T + cH - ((sorted[i][valueKey] - vMin) / (vMax - vMin)) * cH;
      areaPath += ` L ${x} ${y}`;
      linePath += (i === 0 ? 'M' : ' L') + ` ${x} ${y}`;
    }
    areaPath += ` L ${PAD_L + (_timeToMin(sorted[sorted.length-1].time) / 1440) * cW} ${PAD_T + cH} Z`;
    svg += `<path d="${areaPath}" fill="${color}" fill-opacity="0.1"/>`;
    svg += `<path d="${linePath}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
  }

  // Points (draggable)
  for (let i = 0; i < sorted.length; i++) {
    const origIdx = curve.indexOf(sorted[i]);
    const x = PAD_L + (_timeToMin(sorted[i].time) / 1440) * cW;
    const y = PAD_T + cH - ((sorted[i][valueKey] - vMin) / (vMax - vMin)) * cH;
    svg += `<circle cx="${x}" cy="${y}" r="5" fill="${color}" stroke="var(--bg-primary)" stroke-width="1.5" style="cursor:ns-resize;" data-idx="${origIdx}" onmousedown="_circStartDrag(event,'${curveType}',${origIdx})" ontouchstart="_circStartDrag(event,'${curveType}',${origIdx})"/>`;
    // Value label above point
    svg += `<text x="${x}" y="${y - 8}" text-anchor="middle" fill="var(--text-primary)" font-size="7" font-weight="600" pointer-events="none">${sorted[i][valueKey]}${unit}</text>`;
  }

  svg += '</svg>';

  // Selected point info / delete
  svg += `<div id="circInfo_${curveType}" style="min-height:24px;margin-top:4px;font-size:11px;color:var(--text-muted);"></div>`;

  el.innerHTML = svg;
}

function _timeToMin(t) {
  if (!t) return 720;
  const [h, m] = t.split(':').map(Number);
  return (h || 0) * 60 + (m || 0);
}

function _minToTime(m) {
  m = Math.max(0, Math.min(1439, Math.round(m)));
  return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
}

function _circStartDrag(e, curveType, index) {
  e.preventDefault();
  e.stopPropagation();
  const svg = e.target.closest('svg');
  if (!svg) return;
  _circDrag = {curveType, index, svg, rect: svg.getBoundingClientRect()};

  const onMove = (ev) => {
    if (!_circDrag) return;
    const clientY = ev.touches ? ev.touches[0].clientY : ev.clientY;
    const rect = _circDrag.rect;
    const svgH = rect.height;
    const W = 600, H = 220, PAD_T = 20, PAD_B = 28;
    const cH = H - PAD_T - PAD_B;
    const scaleY = svgH / H;

    const relY = (clientY - rect.top) / scaleY - PAD_T;

    const path = _circDrag.curveType === 'bri' ? 'lighting.circadian.brightness_curve' : 'lighting.circadian.ct_curve';
    const curve = getPath(S, path) || [];
    const pt = curve[_circDrag.index];
    if (!pt) return;

    // Time is fixed – only vertical (value) dragging allowed

    if (_circDrag.curveType === 'bri') {
      const pct = Math.max(0, Math.min(100, Math.round((1 - relY / cH) * 100 / 5) * 5));
      pt.pct = pct;
    } else {
      const kelvin = Math.max(1800, Math.min(6500, Math.round((1 - relY / cH) * (6500 - 1800) / 100) * 100 + 1800));
      pt.kelvin = kelvin;
    }

    setPath(S, path, curve);
    renderCircadianCurveEditor();
  };

  const onUp = () => {
    if (_circDrag) {
      _circDrag = null;
      scheduleAutoSave();
    }
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onUp);
  };

  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
  document.addEventListener('touchmove', onMove, {passive: false});
  document.addEventListener('touchend', onUp);
}

// _circChartClick removed – fixed 10 points, no click-to-add

function updateCircadianPoint(curveType, index, field, value) {
  const path = curveType === 'bri' ? 'lighting.circadian.brightness_curve' : 'lighting.circadian.ct_curve';
  const curve = getPath(S, path) || [];
  if (curve[index]) {
    curve[index][field] = value;
    setPath(S, path, curve);
    scheduleAutoSave();
  }
}

// addCircadianPoint removed – fixed 10 points

function removeCircadianPoint(curveType, index) {
  const path = curveType === 'bri' ? 'lighting.circadian.brightness_curve' : 'lighting.circadian.ct_curve';
  const curve = getPath(S, path) || [];
  curve.splice(index, 1);
  setPath(S, path, curve);
  scheduleAutoSave();
  renderCircadianCurveEditor();
}

function _circDeletePoint(curveType, index) {
  removeCircadianPoint(curveType, index);
}

async function loadLightEntities() {
  const container = document.getElementById('lightRoomContainer');
  if (!container) return;
  try {
    const d = await api('/api/ui/lights');
    const haLights = d.lights || [];
    renderLightRoomAssignment(haLights, container);
  } catch (e) {
    container.innerHTML = '<div style="color:var(--danger);padding:8px;">Fehler beim Laden: ' + esc(e.message) + '</div>';
  }
  // Render circadian curve editor after settings are loaded
  renderCircadianCurveEditor();
}

function renderLightRoomAssignment(haLights, container) {
  const rooms = RP.rooms || {};
  const roomNames = Object.keys(rooms);
  if (roomNames.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">Keine Räume in room_profiles.yaml gefunden.</div>';
    return;
  }
  const floorLabels = {eg:'EG', og:'OG'};
  const typeLabels = {
    living:'Wohnzimmer', bedroom:'Schlafzimmer', kitchen:'Küche',
    office:'Buero', bathroom:'Badezimmer', hallway:'Flur',
    outdoor:'Aussen', dressing:'Ankleide'
  };
  const lightTypeOpts = [
    {v:'standard', l:'Standard (nur Helligkeit)'},
    {v:'dim2warm', l:'dim2warm (Farbtemp über Helligkeit)'},
    {v:'tunable_white', l:'tunable_white (Helligkeit + Farbtemp)'}
  ];
  // Motion sensors from settings for cross-reference
  const motionSensors = getPath(S, 'multi_room.room_motion_sensors') || {};

  // Group rooms by floor
  const floors = {};
  for (const name of roomNames) {
    const r = rooms[name];
    const fl = r.floor || 'og';
    if (!floors[fl]) floors[fl] = [];
    floors[fl].push(name);
  }

  let html = '';
  for (const [floor, floorRooms] of Object.entries(floors)) {
    html += '<div style="margin-bottom:16px;">';
    html += '<div style="font-size:14px;font-weight:700;color:var(--accent);margin-bottom:8px;border-bottom:1px solid var(--border);padding-bottom:4px;">' + (floorLabels[floor] || floor).toUpperCase() + '</div>';
    for (const name of floorRooms) {
      const r = rooms[name];
      const assigned = r.light_entities || [];
      const lightBri = r.light_brightness || {};
      const icon = r.type==='bedroom' ? '&#128716;' : r.type==='kitchen' ? '&#127859;' :
                   r.type==='office' ? '&#128187;' : r.type==='bathroom' ? '&#128704;' :
                   r.type==='hallway' ? '&#128682;' : r.type==='living' ? '&#128715;' :
                   r.type==='dressing' ? '&#128087;' : '&#127968;';
      // Find motion sensor for this room
      const roomMotion = motionSensors[name] || '';
      html += '<div class="s-card" style="margin-bottom:8px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
      html += '<span style="font-size:13px;font-weight:600;">' + icon + ' ' + esc(name) + '</span>';
      html += '<span style="font-size:10px;color:var(--text-muted);background:var(--bg-primary);padding:1px 6px;border-radius:3px;">' + (typeLabels[r.type] || r.type) + '</span>';
      html += '</div>';
      // Motion sensor info badge
      if (roomMotion) {
        html += '<div style="display:flex;align-items:center;gap:4px;margin-bottom:8px;padding:4px 8px;background:var(--bg-primary);border-radius:4px;font-size:10px;color:var(--text-secondary);">';
        html += '<span style="color:var(--success);">&#9679;</span> Präsenzmelder: <span style="font-family:var(--mono);color:var(--accent);">' + esc(roomMotion) + '</span>';
        html += '</div>';
      } else {
        html += '<div style="display:flex;align-items:center;gap:4px;margin-bottom:8px;padding:4px 8px;background:var(--bg-primary);border-radius:4px;font-size:10px;color:var(--text-muted);">';
        html += '<span style="opacity:0.4;">&#9679;</span> Kein Präsenzmelder zugeordnet <span style="opacity:0.6;">(konfigurierbar unter Räume &rarr; Bewegungsmelder)</span>';
        html += '</div>';
      }
      // Light Entity Picker (multi-select checklist)
      html += '<div class="form-group"><label>Licht-Entities</label>';
      html += '<div style="max-height:150px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;padding:4px;background:var(--bg-primary);">';
      if (haLights.length === 0) {
        html += '<div style="color:var(--text-muted);font-size:11px;padding:4px;">Keine light.* Entities in HA gefunden.</div>';
      } else {
        for (const light of haLights) {
          const isChecked = assigned.includes(light.entity_id);
          const stateColor = light.state === 'on' ? 'var(--success)' : 'var(--text-muted)';
          const briInfo = light.brightness != null ? ' (' + light.brightness + '%)' : '';
          html += '<label style="display:flex;align-items:center;gap:6px;padding:3px 4px;cursor:pointer;font-size:12px;border-radius:4px;" onmouseover="this.style.background=\'var(--bg-hover)\'" onmouseout="this.style.background=\'none\'">';
          html += '<input type="checkbox"' + (isChecked ? ' checked' : '') + ' onchange="toggleLightEntity(\'' + esc(name) + '\',\'' + esc(light.entity_id) + '\',this.checked)" style="accent-color:var(--accent);flex-shrink:0;">';
          html += '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(light.name) + '</span>';
          html += '<span style="font-size:10px;font-family:var(--mono);color:' + stateColor + ';flex-shrink:0;">' + light.state + briInfo + '</span>';
          html += '</label>';
        }
      }
      html += '</div></div>';
      // Light type
      html += '<div class="form-group"><label>Lampentyp</label><select onchange="setRoomLightType(\'' + esc(name) + '\',this.value)">';
      for (const o of lightTypeOpts) {
        html += '<option value="' + o.v + '"' + ((r.light_type||'standard')===o.v ? ' selected' : '') + '>' + o.l + '</option>';
      }
      html += '</select></div>';
      // Per-light brightness (only for assigned lights)
      if (assigned.length > 0) {
        html += '<div style="margin-top:4px;">';
        html += '<div style="font-size:11px;font-weight:600;color:var(--text-secondary);margin-bottom:4px;">Helligkeit pro Lampe</div>';
        for (const entityId of assigned) {
          const lightInfo = haLights.find(l => l.entity_id === entityId);
          const displayName = lightInfo ? lightInfo.name : entityId.replace('light.','');
          const perLight = lightBri[entityId] || {};
          const dayVal = perLight.day != null ? perLight.day : (r.default_brightness || 70);
          const nightVal = perLight.night != null ? perLight.night : (r.night_brightness || 20);
          html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;padding:4px 6px;background:var(--bg-primary);border-radius:4px;">';
          html += '<span style="flex:1;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(entityId) + '">' + esc(displayName) + '</span>';
          html += '<label style="font-size:10px;color:var(--text-muted);display:flex;align-items:center;gap:3px;">Tag <input type="number" value="' + dayVal + '" min="0" max="100" step="5" style="width:48px;font-size:10px;padding:1px 3px;background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border);border-radius:3px;" onchange="setLightBrightness(\'' + esc(name) + '\',\'' + esc(entityId) + '\',\'day\',parseInt(this.value))">%</label>';
          html += '<label style="font-size:10px;color:var(--text-muted);display:flex;align-items:center;gap:3px;">Nacht <input type="number" value="' + nightVal + '" min="0" max="100" step="5" style="width:48px;font-size:10px;padding:1px 3px;background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border);border-radius:3px;" onchange="setLightBrightness(\'' + esc(name) + '\',\'' + esc(entityId) + '\',\'night\',parseInt(this.value))">%</label>';
          html += '</div>';
        }
        html += '</div>';
      } else {
        // Fallback: room-level brightness when no lights assigned
        html += '<div style="display:flex;gap:12px;flex-wrap:wrap;">';
        html += '<div class="form-group" style="flex:1;min-width:100px;"><label>Helligkeit Tag (%)</label><input type="number" value="' + (r.default_brightness||70) + '" min="0" max="100" step="5" onchange="setRoomLightVal(\'' + esc(name) + '\',\'default_brightness\',parseInt(this.value))"></div>';
        html += '<div class="form-group" style="flex:1;min-width:100px;"><label>Helligkeit Nacht (%)</label><input type="number" value="' + (r.night_brightness||20) + '" min="0" max="100" step="5" onchange="setRoomLightVal(\'' + esc(name) + '\',\'night_brightness\',parseInt(this.value))"></div>';
        html += '</div>';
      }
      // ── NEU: Sensor-Zuordnung + Praesenz-Optionen ──
      html += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border);">';
      html += '<div style="font-size:11px;font-weight:600;color:var(--text-secondary);margin-bottom:6px;">Sensor-Zuordnung &amp; Praesenz</div>';
      // Bettsensor: Verweis auf zentrale Konfiguration im Sensoren-Tab
      if (r.type === 'bedroom') {
        const bedCount = _getBedSensorsForRoom(name).filter(b => b.sensor).length;
        html += '<div style="font-size:10px;color:var(--text-muted);margin-bottom:4px;">' +
          (bedCount > 0 ? '&#9989; ' + bedCount + ' Bettsensor' + (bedCount > 1 ? 'en' : '') + ' konfiguriert' : '&#9675; Kein Bettsensor') +
          ' <span style="cursor:pointer;color:var(--accent);text-decoration:underline;" onclick="showTab(\'tab-sensors\')">(Sensoren-Tab)</span></div>';
      }
      // Lux-Sensor
      const luxSensor = r.lux_sensor || '';
      html += '<div class="form-group" style="margin-bottom:4px;"><label style="font-size:10px;">Lux-Sensor</label>';
      html += '<input type="text" value="' + esc(luxSensor) + '" placeholder="sensor.lux_' + esc(name) + '" style="font-size:11px;" onchange="setRoomLightVal(\'' + esc(name) + '\',\'lux_sensor\',this.value)">';
      html += '</div>';
      // Toggles
      html += '<div style="display:flex;gap:12px;flex-wrap:wrap;">';
      const presAutoOn = r.presence_auto_on !== false;
      html += '<label style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer;">';
      html += '<input type="checkbox"' + (presAutoOn ? ' checked' : '') + ' onchange="setRoomLightVal(\'' + esc(name) + '\',\'presence_auto_on\',this.checked)" style="accent-color:var(--accent);">';
      html += 'Praesenz-Auto-An</label>';
      // Nacht-Pfadlicht (nur bei hallway/bathroom/flur/bad)
      if (r.type === 'hallway' || r.type === 'bathroom') {
        const nightPath = r.night_path_light || false;
        html += '<label style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer;">';
        html += '<input type="checkbox"' + (nightPath ? ' checked' : '') + ' onchange="setRoomLightVal(\'' + esc(name) + '\',\'night_path_light\',this.checked)" style="accent-color:var(--accent);">';
        html += 'Nacht-Pfadlicht</label>';
      }
      html += '</div>';
      html += '</div>';
      html += '</div>';
    }
    html += '</div>';
  }
  container.innerHTML = html;
}

function toggleLightEntity(room, entityId, checked) {
  if (!RP.rooms || !RP.rooms[room]) return;
  if (!RP.rooms[room].light_entities) RP.rooms[room].light_entities = [];
  const list = RP.rooms[room].light_entities;
  if (checked && !list.includes(entityId)) {
    list.push(entityId);
  } else if (!checked) {
    const idx = list.indexOf(entityId);
    if (idx >= 0) list.splice(idx, 1);
  }
  _rpDirty = true;
  scheduleAutoSave();
}

function setRoomLightType(room, lightType) {
  if (!RP.rooms || !RP.rooms[room]) return;
  RP.rooms[room].light_type = lightType;
  _rpDirty = true;
  scheduleAutoSave();
}

function setRoomLightVal(room, key, val) {
  if (!RP.rooms || !RP.rooms[room]) return;
  RP.rooms[room][key] = val;
  _rpDirty = true;
  scheduleAutoSave();
}

function setLightBrightness(room, entityId, timeOfDay, val) {
  if (!RP.rooms || !RP.rooms[room]) return;
  if (!RP.rooms[room].light_brightness) RP.rooms[room].light_brightness = {};
  if (!RP.rooms[room].light_brightness[entityId]) RP.rooms[room].light_brightness[entityId] = {};
  RP.rooms[room].light_brightness[entityId][timeOfDay] = val;
  _rpDirty = true;
  scheduleAutoSave();
}

// ── Room-Profile Editor (room_profiles.yaml → rooms) ──────────
function renderRoomProfileEditor() {
  const rooms = RP.rooms || {};
  const roomNames = Object.keys(rooms);
  if (roomNames.length === 0) {
    return '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Keine Räume in room_profiles.yaml gefunden.</div>';
  }
  const typeLabels = {
    living:'Wohnzimmer', bedroom:'Schlafzimmer', kitchen:'Küche',
    office:'Buero', bathroom:'Badezimmer', hallway:'Flur',
    outdoor:'Aussen', dressing:'Ankleide'
  };
  const floorLabels = {eg:'Erdgeschoss', og:'Obergeschoss'};
  let html = '';
  for (const name of roomNames) {
    const r = rooms[name];
    const icon = r.type==='bedroom' ? '&#128716;' : r.type==='kitchen' ? '&#127859;' :
                 r.type==='office' ? '&#128187;' : r.type==='bathroom' ? '&#128704;' :
                 r.type==='hallway' ? '&#128682;' : r.type==='living' ? '&#128715;' :
                 r.type==='dressing' ? '&#128087;' : '&#127968;';
    const floorBadge = '<span style="font-size:10px;font-family:var(--mono);color:var(--text-muted);background:var(--bg-primary);padding:1px 6px;border-radius:3px;margin-left:6px;">' + (floorLabels[r.floor]||r.floor||'') + '</span>';
    html += '<div class="s-card" style="margin-bottom:8px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
    html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;">' + icon + ' ' + esc(name) + floorBadge + '</div>';
    // Raum-Typ
    html += '<div class="form-group"><label>Typ</label><select data-rp-path="rooms.' + name + '.type" onchange="rpSetPath(\'rooms.' + name + '.type\',this.value)">';
    for (const [tv, tl] of Object.entries(typeLabels)) {
      html += '<option value="' + tv + '"' + (r.type===tv?' selected':'') + '>' + tl + '</option>';
    }
    html += '</select></div>';
    // Etage
    html += '<div class="form-group"><label>Etage</label><select data-rp-path="rooms.' + name + '.floor" onchange="rpSetPath(\'rooms.' + name + '.floor\',this.value)">';
    html += '<option value="eg"' + (r.floor==='eg'?' selected':'') + '>Erdgeschoss (EG)</option>';
    html += '<option value="og"' + (r.floor==='og'?' selected':'') + '>Obergeschoss (OG)</option>';
    html += '</select></div>';
    html += '</div>';
  }
  return html;
}

// ── Seasonal Editor (room_profiles.yaml → seasonal) ──────────
function renderSeasonalEditor() {
  const seasonal = RP.seasonal || {};
  const seasons = [
    {key:'spring', icon:'&#127800;', label:'Fruehling'},
    {key:'summer', icon:'&#9728;', label:'Sommer'},
    {key:'autumn', icon:'&#127810;', label:'Herbst'},
    {key:'winter', icon:'&#10052;', label:'Winter'}
  ];
  let html = '';
  for (const s of seasons) {
    const cfg = seasonal[s.key] || {};
    html += '<div class="s-card" style="margin-bottom:8px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
    html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;">' + s.icon + ' ' + s.label + '</div>';
    html += rpRange('seasonal.' + s.key + '.temp_offset', 'Temperatur-Offset (°C)', -5, 5, 0.5, {'-3':'-3','-2':'-2','-1':'-1',0:'0',1:'+1',2:'+2',3:'+3'});
    html += rpText('seasonal.' + s.key + '.cover_hint', 'Rolladen-Hinweis', 'z.B. "Rolladen bei Sonne schließen"');
    html += rpText('seasonal.' + s.key + '.ventilation', 'Lueftungs-Tipp', 'z.B. "Kurz stosslueften"');
    html += '</div>';
  }
  return html;
}

// ── Fernbedienung Tab (Harmony etc.) ──────────────────────────
function renderRemote() {
  const cfg = getPath(S, 'remote') || {};
  const remotes = cfg.remotes || {};
  const entries = Object.entries(remotes);

  let remoteCards = '';
  for (const [key, rcfg] of entries) {
    const eid = rcfg.entity_id || '';
    const name = rcfg.name || key;
    const activities = rcfg.activities || {};
    const actEntries = Object.entries(activities);

    let actRows = actEntries.map(([alias, harmony]) =>
      `<div class="kv-row">
        <input type="text" class="kv-key" value="${esc(alias)}" placeholder="Alias (z.B. fernsehen)">
        <span class="kv-arrow">&#8594;</span>
        <input type="text" class="kv-val" value="${esc(harmony)}" placeholder="Harmony-Name (z.B. Watch TV)">
        <button class="kv-rm" onclick="rmRemoteActivity('${esc(key)}',this)" title="Entfernen">&#10005;</button>
      </div>`
    ).join('');

    remoteCards += `<div class="s-section" style="margin-bottom:14px;">
      <div class="s-section-hdr" onclick="toggleSec(this)">
        <h3>&#128261; ${esc(name)}</h3><span class="arrow">&#9660;</span>
      </div>
      <div class="s-section-body">
        <div class="form-group">
          <label>NAME</label>
          <input type="text" data-path="remote.remotes.${esc(key)}.name" value="${esc(name)}">
        </div>
        <div class="form-group">
          <label>ENTITY-ID (HOME ASSISTANT)</label>
          <input type="text" data-path="remote.remotes.${esc(key)}.entity_id" value="${esc(eid)}" placeholder="remote.harmony_wohnzimmer" style="font-family:var(--mono);font-size:11px;">
        </div>
        <div class="form-group">
          <label>AKTIVITAETEN-ALIASE</label>
          <div class="info-box" style="margin-bottom:8px;font-size:11px;">
            <span class="info-icon">&#128161;</span>Links: deutscher Name (für Sprachsteuerung). Rechts: exakter Harmony-Aktivitätsname.
          </div>
          <div class="kv-editor" data-path="remote.remotes.${esc(key)}.activities">
            ${actRows}
            <button class="kv-add" onclick="kvAdd(this,'remote.remotes.${esc(key)}.activities','Alias','Harmony-Name')">+ Aktivität</button>
          </div>
        </div>
        <button class="btn btn-sm" style="color:var(--danger);border-color:var(--danger);margin-top:8px;font-size:11px;" onclick="removeRemoteEntry('${esc(key)}')">Fernbedienung entfernen</button>
      </div>
    </div>`;
  }

  if (!remoteCards) {
    remoteCards = '<div style="color:var(--text-muted);font-size:12px;padding:12px;">Keine Fernbedienungen konfiguriert. Fuege eine hinzu.</div>';
  }

  return sectionWrap('&#128261;', 'Fernbedienungen (Harmony)',
    fInfo('Konfiguriere deine Logitech Harmony Fernbedienungen. Jarvis kann Aktivitäten starten (z.B. "Fernseher an"), IR-Befehle senden und den aktuellen Status abfragen. Aktivitäten werden per Sprachbefehl über den deutschen Alias angesprochen: "Jarvis, starte Fernsehen."') +
    fToggle('remote.enabled', 'Fernbedienung-Steuerung aktiv') +
    remoteCards +
    '<button class="btn btn-sm" onclick="addRemoteEntry()" style="margin-top:8px;">+ Fernbedienung hinzufügen</button>'
  ) +
  sectionWrap('&#127916;', 'Szenen-Integration',
    fInfo('Wenn eine Szene eine Harmony-Aktivität enthält (z.B. Filmabend → "Watch TV"), startet Jarvis automatisch die passende Aktivität. Konfiguriere die Szenen-Zuordnung im Szenen-Tab.') +
    `<div class="info-box" style="cursor:pointer;" onclick="document.querySelector('[data-tab=tab-scenes]').click()">
      <span class="info-icon">&#127916;</span>Szenen konfigurieren im <strong>Szenen</strong>-Tab. Klicke hier.
    </div>`
  ) +
  sectionWrap('&#128218;', 'Sprachbefehle',
    fInfo('So steuerst du die Fernbedienung per Sprache:') +
    `<div style="font-size:12px;line-height:1.9;color:var(--text-secondary);padding:4px 8px;">
      <div><code>"Jarvis, schalte den Fernseher ein"</code> — Startet die Standard-Aktivität</div>
      <div><code>"Jarvis, starte Fernsehen"</code> — Startet eine benannte Aktivität</div>
      <div><code>"Jarvis, mach den Fernseher aus"</code> — Schaltet alles aus (PowerOff)</div>
      <div><code>"Jarvis, mach lauter / leiser"</code> — Sendet Volume-Befehle</div>
      <div><code>"Jarvis, was läuft gerade?"</code> — Zeigt aktive Aktivität</div>
      <div><code>"Jarvis, welche Aktivitäten hat die Fernbedienung?"</code> — Listet alle Optionen</div>
    </div>`
  );
}

function addRemoteEntry() {
  const key = 'remote_' + Date.now();
  setPath(S, `remote.remotes.${key}`, {entity_id: '', name: 'Neue Fernbedienung', activities: {aus: 'PowerOff'}});
  scheduleAutoSave();
  renderCurrentTab();
}

function removeRemoteEntry(key) {
  const remotes = getPath(S, 'remote.remotes') || {};
  delete remotes[key];
  setPath(S, 'remote.remotes', remotes);
  scheduleAutoSave();
  renderCurrentTab();
}

function rmRemoteActivity(remoteKey, btn) {
  btn.closest('.kv-row').remove();
  const editor = document.querySelector(`.kv-editor[data-path="remote.remotes.${remoteKey}.activities"]`);
  if (editor) kvSync(editor, `remote.remotes.${remoteKey}.activities`);
}

// ── Saugroboter Tab ──────────────────────────────────────
function renderVacuum() {
  return sectionWrap('&#129529;', 'Saugroboter',
    fInfo('Konfiguriere deine Dreame-Saugroboter. Für raum-genaues Saugen müssen die Segment-IDs eingetragen werden (findest du in der Dreame-App unter Raumverwaltung).') +
    fToggle('vacuum.enabled', 'Saugroboter-Steuerung aktiv') +
    renderVacuumRobot('eg', 'Erdgeschoss (EG)') +
    renderVacuumRobot('og', 'Obergeschoss (OG)')
  ) +
  sectionWrap('&#128168;', 'Reinigungsoptionen',
    fInfo('Standard-Einstellungen für Saugstaerke und Reinigungsmodus wenn nichts anderes angegeben wird.') +
    fSelect('vacuum.default_fan_speed', 'Standard-Saugstaerke', [
      {v:'quiet',l:'Leise'}, {v:'standard',l:'Standard'},
      {v:'strong',l:'Stark'}, {v:'turbo',l:'Turbo'}
    ]) +
    fSelect('vacuum.default_mode', 'Standard-Modus', [
      {v:'vacuum',l:'Nur Saugen'}, {v:'mop',l:'Nur Wischen'},
      {v:'vacuum_and_mop',l:'Saugen & Wischen'}
    ])
  ) +
  sectionWrap('&#128694;', 'Anwesenheits-Steuerung',
    fInfo('Steuert ob der Saugroboter nur bei Abwesenheit fahren darf. Gilt für ALLE Trigger (Auto-Clean, Steckdosen, Szenen). Kann die Alarmanlage automatisch umschalten.') +
    fToggle('vacuum.presence_guard.enabled', 'Anwesenheits-Steuerung aktiv') +
    fToggle('vacuum.presence_guard.switch_alarm_for_cleaning', 'Alarmanlage umschalten') +
    '<div class="form-group"><label>Alarm-Entity' + helpBtn('vacuum.presence_guard.alarm_entity') + '</label>' +
      '<div class="entity-pick-wrap" style="position:relative;">' +
        '<input type="text" class="entity-pick-alarm form-input entity-pick-input" value="' + esc(getPath(S,'vacuum.presence_guard.alarm_entity')||'') + '"' +
          ' placeholder="alarm_control_panel.alarmo" data-domains="alarm_control_panel"' +
          ' oninput="entityPickFilter(this,\'alarm_control_panel\')" onfocus="entityPickFilter(this,\'alarm_control_panel\')"' +
          ' onblur="setTimeout(function(){var el=document.querySelector(\'.entity-pick-alarm\');if(el)setPath(S,\'vacuum.presence_guard.alarm_entity\',el.value.trim());scheduleAutoSave();},500)"' +
          ' style="font-size:12px;font-family:var(--mono);">' +
        '<div class="entity-pick-dropdown" style="display:none;"></div>' +
      '</div>' +
    '</div>' +
    fToggle('vacuum.presence_guard.pause_on_arrival', 'Bei Heimkehr: Pausieren & Ladestation') +
    fToggle('vacuum.presence_guard.resume_on_departure', 'Bei Abwesenheit: Reinigung fortsetzen') +
    fRange('vacuum.presence_guard.resume_delay_minutes', 'Verzögerung Fortsetzung (Min)', 1, 15, 1, {1:'1 Min',2:'2 Min',3:'3 Min',5:'5 Min',10:'10 Min',15:'15 Min'})
  ) +
  sectionWrap('&#128296;', 'Auto-Clean',
    fInfo('Automatische Reinigung — entweder an festen Wochentagen oder automatisch wenn niemand zuhause ist.') +
    fToggle('vacuum.auto_clean.enabled', 'Auto-Clean aktiv') +
    fSelect('vacuum.auto_clean.mode', 'Modus', [
      {v:'smart',l:'Smart (wenn niemand zuhause)'},
      {v:'schedule',l:'Fester Wochenplan'},
      {v:'both',l:'Beides (Wochenplan + Smart)'}
    ]) +
    fChipSelect('vacuum.auto_clean.schedule_days', 'Reinigungstage', [
      {v:'mon',l:'Mo'}, {v:'tue',l:'Di'}, {v:'wed',l:'Mi'},
      {v:'thu',l:'Do'}, {v:'fri',l:'Fr'}, {v:'sat',l:'Sa'}, {v:'sun',l:'So'}
    ], 'Gilt für Modus "Fester Wochenplan" und "Beides".') +
    fRange('vacuum.auto_clean.schedule_time', 'Uhrzeit (Wochenplan)', 2, 20, 1, {2:'02:00',3:'03:00',4:'04:00',5:'05:00',6:'06:00',7:'07:00',8:'08:00',9:'09:00',10:'10:00',11:'11:00',12:'12:00',13:'13:00',14:'14:00',15:'15:00',16:'16:00',17:'17:00',18:'18:00',19:'19:00',20:'20:00'}) +
    fToggle('vacuum.auto_clean.when_nobody_home', 'Nur wenn niemand zuhause (Smart-Modus)') +
    fRange('vacuum.auto_clean.min_hours_between', 'Mindestabstand (Std)', 6, 72, 6, {6:'6 Std',12:'12 Std',24:'1 Tag',48:'2 Tage',72:'3 Tage'}) +
    fRange('vacuum.auto_clean.preferred_time_start', 'Smart: Bevorzugt ab (Uhr)', 6, 18, 1) +
    fRange('vacuum.auto_clean.preferred_time_end', 'Smart: Bevorzugt bis (Uhr)', 10, 22, 1) +
    fSelect('vacuum.auto_clean.auto_fan_speed', 'Saugstaerke (Auto-Clean)', [
      {v:'quiet',l:'Leise'}, {v:'standard',l:'Standard'},
      {v:'strong',l:'Stark'}, {v:'turbo',l:'Turbo'}
    ]) +
    fSelect('vacuum.auto_clean.auto_mode', 'Modus (Auto-Clean)', [
      {v:'vacuum',l:'Nur Saugen'}, {v:'mop',l:'Nur Wischen'},
      {v:'vacuum_and_mop',l:'Saugen & Wischen'}
    ]) +
    fChipSelect('vacuum.auto_clean.not_during', 'Nicht starten während', [
      {v:'meeting',l:'Meeting'}, {v:'schlafen',l:'Schlafen'},
      {v:'gäste',l:'Gäste'}, {v:'filmabend',l:'Filmabend'},
      {v:'telefonat',l:'Telefonat'}
    ])
  ) +
  sectionWrap('&#9889;', 'Steckdosen-Trigger',
    fInfo('Wenn eine Steckdose mit Leistungsmessung abschaltet (Leistung fällt unter Schwellwert), wird automatisch der zugehoerige Raum gereinigt.') +
    fToggle('vacuum.power_trigger.enabled', 'Steckdosen-Trigger aktiv') +
    fRange('vacuum.power_trigger.delay_minutes', 'Verzögerung nach Abschalten', 1, 30, 1, {1:'1 Min',2:'2 Min',5:'5 Min',10:'10 Min',15:'15 Min',20:'20 Min',30:'30 Min'}) +
    fRange('vacuum.power_trigger.cooldown_hours', 'Cooldown (nicht nochmal)', 1, 48, 1, {1:'1 Std',2:'2 Std',4:'4 Std',6:'6 Std',8:'8 Std',12:'12 Std',24:'1 Tag',48:'2 Tage'}) +
    _renderPowerTriggerList()
  ) +
  sectionWrap('&#127917;', 'Szenen-Trigger',
    fInfo('Wenn eine Szene aktiviert wird, reinigt der Saugroboter automatisch den zugehoerigen Raum. Z.B. scene.kuche_aus wird aktiviert → Küche saugen.') +
    fToggle('vacuum.scene_trigger.enabled', 'Szenen-Trigger aktiv') +
    fRange('vacuum.scene_trigger.delay_minutes', 'Verzögerung nach Aktivierung', 1, 30, 1, {1:'1 Min',2:'2 Min',5:'5 Min',10:'10 Min',15:'15 Min',20:'20 Min',30:'30 Min'}) +
    fRange('vacuum.scene_trigger.cooldown_hours', 'Cooldown (nicht nochmal)', 1, 48, 1, {1:'1 Std',2:'2 Std',4:'4 Std',6:'6 Std',8:'8 Std',12:'12 Std',24:'1 Tag',48:'2 Tage'}) +
    _renderSceneTriggerList()
  ) +
  sectionWrap('&#128295;', 'Wartungs-Überwachung',
    fInfo('Jarvis warnt wenn Verschleißteile des Saugroboters gewechselt werden müssen.') +
    fToggle('vacuum.maintenance.enabled', 'Wartungs-Überwachung aktiv') +
    fRange('vacuum.maintenance.check_interval_hours', 'Prüf-Intervall', 6, 72, 6, {6:'6 Std',12:'12 Std',24:'1 Tag',48:'2 Tage',72:'3 Tage'}) +
    fRange('vacuum.maintenance.warn_at_percent', 'Warnung bei', 5, 30, 5, {5:'5%',10:'10%',15:'15%',20:'20%',30:'30%'})
  );
}

// Hilfsfunktion: Alle konfigurierten Vacuum-Räume aus robots.*.rooms sammeln
function _getVacuumRooms() {
  const robots = getPath(S, 'vacuum.robots') || {};
  const rooms = new Set();
  for (const floor of Object.values(robots)) {
    const rm = floor.rooms || {};
    for (const name of Object.keys(rm)) rooms.add(name);
  }
  return [...rooms].sort();
}

// Hilfsfunktion: Entity-Dropdown mit Suchfeld rendern
function _entityDropdownHtml(cls, domain, value, placeholder) {
  return `<div class="entity-pick-wrap" style="position:relative;">
    <input type="text" class="${cls} form-input entity-pick-input" value="${esc(value)}"
      placeholder="${placeholder}" data-domains="${domain}"
      oninput="entityPickFilter(this,'${domain}')" onfocus="entityPickFilter(this,'${domain}')"
      style="font-size:12px;font-family:var(--mono);">
    <div class="entity-pick-dropdown" style="display:none;"></div>
  </div>`;
}

// Hilfsfunktion: Raum-Dropdown aus Vacuum-Rooms rendern
function _roomSelectHtml(cls, value, syncFn) {
  const rooms = _getVacuumRooms();
  let opts = '<option value="">-- Raum wählen --</option>';
  for (const r of rooms) {
    opts += `<option value="${esc(r)}"${r === value ? ' selected' : ''}>${esc(r)}</option>`;
  }
  // Option für manuellen Eintrag falls value nicht in rooms
  if (value && !rooms.includes(value)) {
    opts += `<option value="${esc(value)}" selected>${esc(value)}</option>`;
  }
  const onchangeAttr = syncFn ? ` onchange="${syncFn}(this.closest('.${syncFn === 'ptSync' ? 'pt' : 'st'}-editor'))"` : '';
  return `<select class="${cls} form-input" style="font-size:12px;"${onchangeAttr}>${opts}</select>`;
}

function _renderPowerTriggerList() {
  const triggers = getPath(S, 'vacuum.power_trigger.triggers') || [];
  let rows = triggers.map((t, i) =>
    `<div class="pt-row" style="display:grid;grid-template-columns:1fr 80px 1fr 32px;gap:8px;align-items:center;margin-bottom:6px;">
       ${_entityDropdownHtml('pt-entity', 'sensor', t.entity || '', '&#128269; Sensor suchen...')}
       <input type="number" class="pt-threshold form-input" value="${t.threshold ?? 5}" min="0" max="1000" step="1" placeholder="W" style="font-size:12px;text-align:center;" onchange="ptSync(this.closest('.pt-editor'))">
       ${_roomSelectHtml('pt-room', t.room || '', 'ptSync')}
       <button class="kv-rm" onclick="ptRemove(this)" title="Entfernen" style="font-size:14px;">&#10005;</button>
     </div>`
  ).join('');
  return `<div class="pt-editor" data-path="vacuum.power_trigger.triggers">
    <div style="display:grid;grid-template-columns:1fr 80px 1fr 32px;gap:8px;margin-bottom:4px;font-size:11px;color:var(--text-muted);font-weight:600;">
      <span>Steckdosen-Entity</span><span style="text-align:center;">Schwelle (W)</span><span>Raum</span><span></span>
    </div>
    ${rows}
    <button class="kv-add" onclick="ptAdd(this)">+ Steckdosen-Trigger</button>
  </div>`;
}
function ptAdd(btn) {
  const editor = btn.closest('.pt-editor');
  const row = document.createElement('div');
  row.className = 'pt-row';
  row.style.cssText = 'display:grid;grid-template-columns:1fr 80px 1fr 32px;gap:8px;align-items:center;margin-bottom:6px;';
  row.innerHTML = `${_entityDropdownHtml('pt-entity', 'sensor', '', '&#128269; Sensor suchen...')}
    <input type="number" class="pt-threshold form-input" value="5" min="0" max="1000" step="1" placeholder="W" style="font-size:12px;text-align:center;" onchange="ptSync(this.closest('.pt-editor'))">
    ${_roomSelectHtml('pt-room', '', 'ptSync')}
    <button class="kv-rm" onclick="ptRemove(this)" title="Entfernen" style="font-size:14px;">&#10005;</button>`;
  editor.insertBefore(row, btn);
  ptSync(editor);
}
function ptRemove(btn) {
  const editor = btn.closest('.pt-editor');
  btn.closest('.pt-row').remove();
  ptSync(editor);
}
function ptSync(editor) {
  const triggers = [];
  editor.querySelectorAll('.pt-row').forEach(row => {
    const entity = row.querySelector('.pt-entity').value.trim();
    const threshold = parseFloat(row.querySelector('.pt-threshold').value) || 5;
    const room = row.querySelector('.pt-room').value;
    if (entity && room) triggers.push({ entity, threshold, room });
  });
  setPath(S, 'vacuum.power_trigger.triggers', triggers);
  scheduleAutoSave();
}

function _renderSceneTriggerList() {
  const triggers = getPath(S, 'vacuum.scene_trigger.triggers') || [];
  let rows = triggers.map((t, i) =>
    `<div class="st-row" style="display:grid;grid-template-columns:1fr 1fr 32px;gap:8px;align-items:center;margin-bottom:6px;">
       ${_entityDropdownHtml('st-entity', 'scene', t.entity || '', '&#128269; Szene suchen...')}
       ${_roomSelectHtml('st-room', t.room || '', 'stSync')}
       <button class="kv-rm" onclick="stRemove(this)" title="Entfernen" style="font-size:14px;">&#10005;</button>
     </div>`
  ).join('');
  return `<div class="st-editor" data-path="vacuum.scene_trigger.triggers">
    <div style="display:grid;grid-template-columns:1fr 1fr 32px;gap:8px;margin-bottom:4px;font-size:11px;color:var(--text-muted);font-weight:600;">
      <span>Szene</span><span>Raum</span><span></span>
    </div>
    ${rows}
    <button class="kv-add" onclick="stAdd(this)">+ Szenen-Trigger</button>
  </div>`;
}
function stAdd(btn) {
  const editor = btn.closest('.st-editor');
  const row = document.createElement('div');
  row.className = 'st-row';
  row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr 32px;gap:8px;align-items:center;margin-bottom:6px;';
  row.innerHTML = `${_entityDropdownHtml('st-entity', 'scene', '', '&#128269; Szene suchen...')}
    ${_roomSelectHtml('st-room', '', 'stSync')}
    <button class="kv-rm" onclick="stRemove(this)" title="Entfernen" style="font-size:14px;">&#10005;</button>`;
  editor.insertBefore(row, btn);
  stSync(editor);
}
function stRemove(btn) {
  const editor = btn.closest('.st-editor');
  btn.closest('.st-row').remove();
  stSync(editor);
}
function stSync(editor) {
  const triggers = [];
  editor.querySelectorAll('.st-row').forEach(row => {
    const entity = row.querySelector('.st-entity').value.trim();
    const room = row.querySelector('.st-room').value;
    if (entity && room) triggers.push({ entity, room });
  });
  setPath(S, 'vacuum.scene_trigger.triggers', triggers);
  scheduleAutoSave();
}

function renderVacuumRobot(floor, floorLabel) {
  const prefix = 'vacuum.robots.' + floor;
  let html = '<div class="s-card" style="margin:10px 0;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);">';
  html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;">&#129529; ' + floorLabel + '</div>';
  html += fEntityPickerSingle(prefix + '.entity_id', 'Entity-ID', ['vacuum'], 'z.B. vacuum.dreame_' + floor);
  html += fText(prefix + '.name', 'Name', 'z.B. Saugroboter ' + floor.toUpperCase());
  html += fText(prefix + '.nickname', 'Spitzname', 'z.B. der Kleine');
  html += fKeyValue(prefix + '.rooms', 'Raum-Segmente (Dreame Raum-IDs)', 'Raumname', 'Segment-ID',
    'Raumname frei eingeben, Segment-ID aus der Dreame-App (Räume verwalten → Nummer).');
  html += '</div>';
  return html;
}

function renderDevices() {
  return sectionWrap('&#128268;', 'Geräteüberwachung',
    fInfo('Wähle welche Geräte der Health-Monitor überwacht. Wenn keine ausgewählt sind, werden alle Sensoren überwacht.') +
    fToggle('device_health.enabled', 'Health-Monitor aktiv') +
    fRange('device_health.check_interval_minutes', 'Prüfintervall', 15, 180, 15, {15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std',180:'3 Std'}) +
    fRange('device_health.alert_cooldown_minutes', 'Alert-Cooldown', 60, 2880, 60, {60:'1 Std',360:'6 Std',720:'12 Std',1440:'24 Std',2880:'48 Std'})
  ) +
  sectionWrap('&#128295;', 'Diagnostik',
    fInfo('Automatische Prüfung von Sensoren, Batterien und Gerätestatus. Alle annotierten Entities (siehe Entities-Tab) werden automatisch überwacht. Versteckte Entities werden ignoriert.') +
    fToggle('diagnostics.enabled', 'Geräte-Diagnostik aktiv') +
    fRange('diagnostics.check_interval_minutes', 'Prüf-Intervall', 5, 120, 5, {5:'5 Min',15:'15 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('diagnostics.battery_warning_threshold', 'Batterie-Warnung ab', 5, 50, 5, {5:'5%',10:'10%',15:'15%',20:'20%',30:'30%',50:'50%'}) +
    fRange('diagnostics.stale_sensor_minutes', 'Sensor veraltet nach', 30, 600, 30, {30:'30 Min',60:'1 Std',120:'2 Std',300:'5 Std',600:'10 Std'}) +
    fRange('diagnostics.offline_threshold_minutes', 'Geraet offline nach', 10, 120, 10, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std'}) +
    fRange('diagnostics.alert_cooldown_minutes', 'Wiederholung frühestens nach', 10, 240, 10, {10:'10 Min',30:'30 Min',60:'1 Std',120:'2 Std',240:'4 Std'}) +
    fRange('diagnostics.suppress_after_cycles', 'Auto-Suppress nach Zyklen', 2, 10, 1, {2:'2',3:'3',4:'4',5:'5',6:'6',8:'8',10:'10'}) +
    fChipSelect('diagnostics.monitor_domains', 'Überwachte Domains (für nicht-annotierte Entities)', [
        {v:'sensor',l:'Sensoren'}, {v:'binary_sensor',l:'Binaer-Sensoren'},
        {v:'light',l:'Lichter'}, {v:'switch',l:'Schalter'},
        {v:'cover',l:'Rolladen'}, {v:'climate',l:'Klima'},
        {v:'lock',l:'Schlösser'}, {v:'fan',l:'Ventilatoren'},
        {v:'water_heater',l:'Warmwasser'}, {v:'media_player',l:'Media Player'},
        {v:'camera',l:'Kameras'}, {v:'alarm_control_panel',l:'Alarmanlagen'}
    ], 'Nicht-annotierte Entities werden nur aus diesen Domains geprüft') +
    fKeywords('diagnostics.exclude_patterns', 'Ignorierte Patterns (Entity-ID)')
  ) +
  sectionWrap('&#128736;', 'Wartung',
    fInfo('Automatische Wartungshinweise für Geräte im Haushalt.') +
    fToggle('maintenance.enabled', 'Wartungs-Erinnerungen aktiv')
  ) +
  sectionWrap('&#127899;', 'Entity-Rollen',
    fInfo('Standard-Rollen für Entity-Erkennung werden aus config/entity_roles_defaults.yaml geladen. Eigene Rollen oder Overrides hier definieren (überschreiben Defaults).') +
    fTextarea('entity_roles', 'Eigene Entity-Rollen (JSON)', 'Format: {"rolle_id": {"label": "Name", "icon": "Emoji", "keywords": ["wort1", "wort2"]}}')
  );
}

// Entity-Picker für Monitoring entfernt — Diagnostics und Device Health nutzen
// jetzt automatisch Entity-Annotations (annotierte = überwacht, hidden = ignoriert).
let _mhEntities = null;
async function loadMindHomeEntities() {
  // Laedt MindHome-Entities für Raumnamen-Erkennung (kein Entity-Picker mehr)
  try {
    _mhEntities = await api('/api/ui/entities/mindhome');
  } catch(e) { _mhEntities = null; }
}

let _updating = false;

function renderSystem() {
  return sectionWrap('&#128300;', 'System-Status',
    '<div id="sysStatusBox" style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);">Lade...</div>' +
    '<button class="btn btn-secondary" style="margin-top:12px;font-size:12px;" onclick="loadSystemStatus()">Status aktualisieren</button>'
  ) +
  sectionWrap('&#128640;', 'System-Update',
    fInfo('Holt neuen Code von Git und baut die Container neu. Der Assistant startet dabei kurz neu.') +
    '<div id="sysUpdateCheck" style="margin-bottom:12px;"></div>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
      '<button class="btn btn-primary" id="btnSysQuickUpdate" onclick="doSystemUpdate(false)">&#128640; Quick Update</button>' +
      '<button class="btn btn-primary" id="btnSysFullUpdate" onclick="doSystemUpdate(true)" style="background:var(--accent-tertiary,#dc6317);border-color:var(--accent-tertiary,#dc6317);">&#128230; Full Update</button>' +
      '<button class="btn btn-secondary" id="btnSysCheckUpdate" onclick="checkForUpdates()">&#128269; Auf Updates prüfen</button>' +
    '</div>' +
    '<div id="sysUpdateLog" style="display:none;margin-top:16px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:12px;max-height:300px;overflow-y:auto;">' +
      '<div style="font-size:11px;font-family:var(--font-mono);white-space:pre-wrap;" id="sysUpdateLogContent"></div>' +
    '</div>'
  ) +
  sectionWrap('&#128260;', 'Container neustarten',
    fInfo('Startet alle Container neu ohne Rebuild. Schneller als ein volles Update.') +
    '<button class="btn btn-secondary" id="btnSysRestart" onclick="doSystemRestart()">&#128260; Container neustarten</button>'
  ) +
  sectionWrap('&#129302;', 'Ollama-Modelle aktualisieren',
    fInfo('Aktualisiert alle installierten LLM-Modelle auf die neueste Version.') +
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
      ${git.changes ? '<div style="margin-top:8px;padding:8px;background:var(--bg-hover);border-radius:4px;"><strong>Lokale Änderungen:</strong><pre style="margin:4px 0 0;font-size:11px;">' + esc(git.changes) + '</pre></div>' : ''}
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
  btn.textContent = 'Prüfe...';
  try {
    const data = await api('/api/ui/system/update-check');
    if (data.updates_available) {
      const commits = (data.new_commits || []).map(c => '<div style="padding:2px 0;">' + esc(c) + '</div>').join('');
      box.innerHTML = '<div style="padding:10px;background:var(--bg-hover);border-left:3px solid var(--accent);border-radius:4px;">' +
        '<strong style="color:var(--accent);">&#9889; Updates verfügbar!</strong> (' + esc(data.local) + ' &rarr; ' + esc(data.remote) + ')' +
        '<div style="margin-top:8px;font-size:11px;font-family:var(--font-mono);">' + commits + '</div></div>';
    } else {
      box.innerHTML = '<div style="padding:8px;color:var(--success);"><strong>&#10003;</strong> System ist aktuell (' + esc(data.local || '') + ')</div>';
    }
  } catch(e) {
    box.innerHTML = '<span style="color:var(--danger);">Fehler: ' + esc(e.message) + '</span>';
  } finally {
    btn.disabled = false;
    btn.textContent = '\u{1F50D} Auf Updates prüfen';
  }
}

let _restartPoll = null;
function _waitForRestart() {
  // Pollt alle 3s bis der Server wieder antwortet, dann Reload
  if (_restartPoll) clearInterval(_restartPoll);
  toast('Container startet neu... bitte kurz warten.');
  let attempts = 0;
  _restartPoll = setInterval(async () => {
    attempts++;
    try {
      const r = await fetch('/api/assistant/health');
      if (r.ok) { clearInterval(_restartPoll); _restartPoll = null; location.reload(); }
    } catch(e) { /* noch nicht bereit */ }
    if (attempts > 40) { clearInterval(_restartPoll); _restartPoll = null; location.reload(); }
  }, 3000);
}

async function doSystemUpdate(full) {
  if (_updating) return;
  const label = full ? 'Full Update' : 'Quick Update';
  const confirmMsg = full
    ? 'Full Update starten?\n\nContainer werden komplett neu gebaut. Das kann einige Minuten dauern.'
    : 'Quick Update starten?\n\nCode wird aktualisiert und der Container kurz neu gestartet.';
  if (!confirm(confirmMsg)) return;
  _updating = true;
  const btnQuick = document.getElementById('btnSysQuickUpdate');
  const btnFull = document.getElementById('btnSysFullUpdate');
  const logBox = document.getElementById('sysUpdateLog');
  const logContent = document.getElementById('sysUpdateLogContent');
  if (btnQuick) { btnQuick.disabled = true; btnQuick.textContent = 'Update läuft...'; }
  if (btnFull) { btnFull.disabled = true; btnFull.textContent = 'Update läuft...'; }
  if (logBox) logBox.style.display = 'block';
  if (logContent) logContent.textContent = label + ' gestartet...\n';

  try {
    const payload = full ? {full: true} : {};
    const data = await api('/api/ui/system/update', 'POST', payload);
    if (logContent) logContent.textContent = (data.log || []).join('\n');
    if (data.success) {
      toast(label + ' erfolgreich! Container startet neu...');
      _waitForRestart();
    } else {
      toast(label + ' fehlgeschlagen — siehe Log', 'error');
      _updating = false;
      if (btnQuick) { btnQuick.disabled = false; btnQuick.textContent = '\u{1F680} Quick Update'; }
      if (btnFull) { btnFull.disabled = false; btnFull.textContent = '\u{1F4E6} Full Update'; }
    }
  } catch(e) {
    if (logContent) logContent.textContent += '\nFehler: ' + e.message;
    if (e.message.includes('Failed to fetch') || e.message.includes('NetworkError')) {
      _waitForRestart();
    } else {
      toast(label + '-Fehler: ' + e.message, 'error');
      _updating = false;
      if (btnQuick) { btnQuick.disabled = false; btnQuick.textContent = '\u{1F680} Quick Update'; }
      if (btnFull) { btnFull.disabled = false; btnFull.textContent = '\u{1F4E6} Full Update'; }
    }
  }
}

async function doSystemRestart() {
  if (!confirm('Alle Container jetzt neustarten?')) return;
  const btn = document.getElementById('btnSysRestart');
  if (btn) { btn.disabled = true; btn.textContent = 'Neustart läuft...'; }
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

// ============================================================
// Gedächtnis-Seite (Fakten + Episoden)
// ============================================================

let _memFacts = [];
let _memEpisodes = [];

const _factCategoryLabels = {
  preference: 'Vorliebe',
  person: 'Person',
  habit: 'Gewohnheit',
  health: 'Gesundheit',
  work: 'Arbeit',
  personal_date: 'Datum',
  intent: 'Absicht',
  conversation_topic: 'Thema',
  general: 'Allgemein',
};

function _fmtTs(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleDateString('de-DE', {day:'2-digit',month:'2-digit',year:'2-digit'}) + ' ' +
           d.toLocaleTimeString('de-DE', {hour:'2-digit',minute:'2-digit'});
  } catch(e) { return ts; }
}

async function loadMemoryPage() {
  const statsEl = document.getElementById('memStats');
  if (statsEl) statsEl.innerHTML = '<div class="stat-card"><div class="stat-label">Lade...</div></div>';

  try {
    const [factsData, episodesData] = await Promise.all([
      api('/api/ui/memory/facts'),
      api('/api/ui/memory/episodes?limit=500'),
    ]);

    _memFacts = factsData.facts || [];
    _memEpisodes = episodesData.episodes || [];
    const stats = factsData.stats || {};

    // Stats rendern
    if (statsEl) {
      statsEl.innerHTML = `
        <div class="stat-card"><div class="stat-label">Fakten</div><div class="stat-value">${stats.total_facts || 0}</div></div>
        <div class="stat-card"><div class="stat-label">Episoden</div><div class="stat-value">${episodesData.total || 0}</div></div>
        <div class="stat-card"><div class="stat-label">Personen</div><div class="stat-value">${(stats.persons || []).length}</div></div>
      `;
    }

    // Filter befuellen
    const catFilter = document.getElementById('memFactFilter');
    if (catFilter) {
      const cats = Object.keys(stats.categories || {});
      catFilter.innerHTML = '<option value="">Alle Kategorien</option>' +
        cats.map(c => `<option value="${c}">${_factCategoryLabels[c] || c} (${stats.categories[c]})</option>`).join('');
    }
    const persFilter = document.getElementById('memPersonFilter');
    if (persFilter) {
      const persons = (stats.persons || []).sort();
      persFilter.innerHTML = '<option value="">Alle Personen</option>' +
        persons.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('');
    }

    renderFacts(_memFacts);
    renderEpisodes(_memEpisodes);
  } catch(e) {
    toast('Fehler beim Laden: ' + e.message, 'error');
  }
}

function filterMemoryFacts() {
  const cat = document.getElementById('memFactFilter')?.value || '';
  const pers = document.getElementById('memPersonFilter')?.value || '';
  let filtered = _memFacts;
  if (cat) filtered = filtered.filter(f => f.category === cat);
  if (pers) filtered = filtered.filter(f => f.person === pers);
  renderFacts(filtered);
}

function renderFacts(facts) {
  const c = document.getElementById('memFacts');
  if (!c) return;
  if (facts.length === 0) {
    c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Fakten vorhanden</div>';
    return;
  }
  c.innerHTML = facts.map((f, i) => `
    <div class="mem-item" style="display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-bottom:1px solid var(--border);${i%2?'background:var(--bg-secondary);':''}">
      <input type="checkbox" class="mem-fact-cb" data-id="${esc(f.fact_id)}" onchange="updateMemFactDeleteBtn()" style="margin-top:3px;min-width:16px;" />
      <div style="flex:1;min-width:0;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:3px;">
          <span style="font-size:11px;padding:1px 6px;border-radius:4px;background:var(--primary);color:#fff;">${esc(_factCategoryLabels[f.category] || f.category)}</span>
          <span style="font-size:11px;padding:1px 6px;border-radius:4px;background:var(--bg-tertiary);color:var(--text-muted);">${esc(f.person)}</span>
          <span style="font-size:11px;color:var(--text-muted);">${_fmtTs(f.created_at)}</span>
        </div>
        <div style="font-size:13px;line-height:1.4;word-break:break-word;">${esc(f.content)}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Konfidenz: ${(f.confidence * 100).toFixed(0)}% &middot; ${f.times_confirmed}x bestaetigt</div>
      </div>
    </div>
  `).join('');
}

function updateMemFactDeleteBtn() {
  const checked = document.querySelectorAll('.mem-fact-cb:checked');
  const btn = document.getElementById('memFactDeleteBtn');
  if (btn) {
    btn.style.display = checked.length > 0 ? '' : 'none';
    btn.textContent = checked.length + ' loeschen';
  }
}

async function deleteSelectedFacts() {
  const checked = document.querySelectorAll('.mem-fact-cb:checked');
  if (checked.length === 0) return;
  if (!confirm(checked.length + ' Fakten unwiderruflich loeschen?')) return;
  const ids = Array.from(checked).map(cb => cb.dataset.id);
  try {
    const d = await api('/api/ui/memory/facts/delete', 'POST', { ids });
    toast(d.deleted + ' Fakten gelöscht', 'success');
    loadMemoryPage();
  } catch(e) { toast('Fehler: ' + e.message, 'error'); }
}

function filterMemoryEpisodes() {
  const q = (document.getElementById('memEpisodeSearch')?.value || '').toLowerCase();
  if (!q) { renderEpisodes(_memEpisodes); return; }
  renderEpisodes(_memEpisodes.filter(e => e.content.toLowerCase().includes(q)));
}

function renderEpisodes(episodes) {
  const c = document.getElementById('memEpisodes');
  if (!c) return;
  if (episodes.length === 0) {
    c.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">Keine Episoden vorhanden</div>';
    return;
  }
  c.innerHTML = episodes.map((ep, i) => `
    <div class="mem-item" style="display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-bottom:1px solid var(--border);${i%2?'background:var(--bg-secondary);':''}">
      <input type="checkbox" class="mem-ep-cb" data-id="${esc(ep.id)}" onchange="updateMemEpDeleteBtn()" style="margin-top:3px;min-width:16px;" />
      <div style="flex:1;min-width:0;">
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:2px;">
          ${_fmtTs(ep.timestamp)}
          ${ep.total_chunks > 1 ? ' &middot; Teil ' + (parseInt(ep.chunk_index)+1) + '/' + ep.total_chunks : ''}
        </div>
        <div style="font-size:13px;line-height:1.4;word-break:break-word;white-space:pre-wrap;">${esc(ep.content)}</div>
      </div>
    </div>
  `).join('');
}

function updateMemEpDeleteBtn() {
  const checked = document.querySelectorAll('.mem-ep-cb:checked');
  const btn = document.getElementById('memEpDeleteBtn');
  if (btn) {
    btn.style.display = checked.length > 0 ? '' : 'none';
    btn.textContent = checked.length + ' loeschen';
  }
}

async function deleteSelectedEpisodes() {
  const checked = document.querySelectorAll('.mem-ep-cb:checked');
  if (checked.length === 0) return;
  if (!confirm(checked.length + ' Episoden unwiderruflich loeschen?')) return;
  const ids = Array.from(checked).map(cb => cb.dataset.id);
  try {
    const d = await api('/api/ui/memory/episodes/delete', 'POST', { ids });
    toast(d.deleted + ' Episoden gelöscht', 'success');
    loadMemoryPage();
  } catch(e) { toast('Fehler: ' + e.message, 'error'); }
}

// ---- Gedächtnis komplett zurücksetzen (PIN-geschuetzt) ----

function showMemoryResetDialog() {
  const overlay = document.getElementById('memResetOverlay');
  if (!overlay) return;
  overlay.style.display = 'flex';
  const pinInput = document.getElementById('memResetPin');
  if (pinInput) { pinInput.value = ''; pinInput.focus(); }
  const err = document.getElementById('memResetError');
  if (err) err.style.display = 'none';
}

function hideMemoryResetDialog() {
  const overlay = document.getElementById('memResetOverlay');
  if (overlay) overlay.style.display = 'none';
}

async function confirmMemoryReset() {
  const pin = document.getElementById('memResetPin')?.value || '';
  const errEl = document.getElementById('memResetError');
  const btn = document.getElementById('memResetConfirmBtn');

  if (!pin) {
    if (errEl) { errEl.textContent = 'PIN eingeben'; errEl.style.display = 'block'; }
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = 'Wird zurückgesetzt...'; }

  try {
    const d = await api('/api/ui/memory/reset', 'POST', { pin });
    hideMemoryResetDialog();
    toast('Gedächtnis komplett zurückgesetzt', 'success');
    loadMemoryPage();
  } catch(e) {
    if (errEl) {
      errEl.textContent = e.message === 'Auth' ? 'Sitzung abgelaufen' : (e.message || 'Falscher PIN');
      errEl.style.display = 'block';
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Zurücksetzen'; }
  }
}

// ---- Grundeinstellung / Factory Reset (PIN-geschuetzt) ----

function showFactoryResetDialog() {
  const overlay = document.getElementById('factoryResetOverlay');
  if (!overlay) return;
  overlay.style.display = 'flex';
  const pinInput = document.getElementById('factoryResetPin');
  if (pinInput) { pinInput.value = ''; pinInput.focus(); }
  const uploads = document.getElementById('factoryResetUploads');
  if (uploads) uploads.checked = false;
  const err = document.getElementById('factoryResetError');
  if (err) err.style.display = 'none';
}

function hideFactoryResetDialog() {
  const overlay = document.getElementById('factoryResetOverlay');
  if (overlay) overlay.style.display = 'none';
}

async function confirmFactoryReset() {
  const pin = document.getElementById('factoryResetPin')?.value || '';
  const includeUploads = document.getElementById('factoryResetUploads')?.checked || false;
  const errEl = document.getElementById('factoryResetError');
  const btn = document.getElementById('factoryResetConfirmBtn');

  if (!pin) {
    if (errEl) { errEl.textContent = 'PIN eingeben'; errEl.style.display = 'block'; }
    return;
  }

  if (btn) { btn.disabled = true; btn.textContent = 'Wird zurückgesetzt...'; }

  try {
    const d = await api('/api/ui/factory-reset', 'POST', { pin, include_uploads: includeUploads });
    hideFactoryResetDialog();
    const details = [];
    if (d.redis_keys_deleted) details.push(d.redis_keys_deleted + ' Redis-Keys');
    if (d.facts_deleted) details.push('Fakten');
    if (d.knowledge_base_cleared) details.push('Wissensdatenbank');
    if (d.recipes_cleared) details.push('Rezepte');
    if (d.uploads_deleted) details.push(d.uploads_deleted + ' Uploads');
    toast('Grundeinstellung wiederhergestellt' + (details.length ? ': ' + details.join(', ') : ''), 'success');
    loadMemoryPage();
  } catch(e) {
    if (errEl) {
      errEl.textContent = e.message === 'Auth' ? 'Sitzung abgelaufen' : (e.message || 'Falscher PIN');
      errEl.style.display = 'block';
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Grundeinstellung'; }
  }
}


// ══════════════════════════════════════════════════════════════
// Deklarative Analyse-Tools
// ══════════════════════════════════════════════════════════════

let _declTools = [];
let _declEditMode = null; // null = neues Tool, string = Name des editierten Tools

const DECL_TOOL_TYPES = [
  {v:'entity_comparison', l:'Entity-Vergleich', desc:'Vergleicht zwei Entities (z.B. Strom heute vs. gestern)'},
  {v:'multi_entity_formula', l:'Multi-Entity-Formel', desc:'Kombiniert mehrere Entities (Durchschnitt, Summe, Min, Max)'},
  {v:'event_counter', l:'Event-Zähler', desc:'Zählt State-Änderungen (z.B. Türöffnungen)'},
  {v:'threshold_monitor', l:'Schwellwert-Monitor', desc:'Prüft ob Wert im definierten Bereich liegt'},
  {v:'trend_analyzer', l:'Trend-Analyse', desc:'Analysiert Trend über Zeitraum (steigend/fallend/stabil)'},
  {v:'entity_aggregator', l:'Entity-Aggregation', desc:'Aggregiert über mehrere Entities (Durchschnitt aller Räume)'},
  {v:'schedule_checker', l:'Zeitplan-Check', desc:'Prüft zeitbasierte Regeln (Nachtmodus, Arbeitszeit)'},
  {v:'state_duration', l:'Zustandsdauer', desc:'Wie lange war ein Zustand aktiv (z.B. Heizung lief X Stunden)'},
  {v:'time_comparison', l:'Zeitvergleich', desc:'Vergleicht Entity mit sich selbst (heute vs. gestern/Woche/Monat)'},
];

const DECL_OPERATIONS = [
  {v:'difference', l:'Differenz (A - B)'},
  {v:'ratio', l:'Verhältnis (A / B)'},
  {v:'percentage_change', l:'Prozentuale Änderung'},
];
const DECL_FORMULAS = [
  {v:'average', l:'Durchschnitt'},{v:'weighted_average', l:'Gewichteter Durchschnitt'},
  {v:'sum', l:'Summe'},{v:'min', l:'Minimum'},{v:'max', l:'Maximum'},
  {v:'difference', l:'Differenz (Erste - Zweite)'},
];
const DECL_AGGREGATIONS = [
  {v:'average', l:'Durchschnitt'},{v:'min', l:'Minimum'},{v:'max', l:'Maximum'},{v:'sum', l:'Summe'},
];
const DECL_TIME_RANGES = [
  {v:'1h', l:'1 Stunde'},{v:'6h', l:'6 Stunden'},{v:'12h', l:'12 Stunden'},
  {v:'24h', l:'24 Stunden'},{v:'48h', l:'48 Stunden'},{v:'7d', l:'7 Tage'},{v:'30d', l:'30 Tage'},
];
const DECL_COMPARE_PERIODS = [
  {v:'yesterday', l:'Gestern'},{v:'last_week', l:'Letzte Woche'},{v:'last_month', l:'Letzter Monat'},
];

// ── Vorlagen ─────────────────────────────────────────────────
const DECL_PRESETS = [
  // ── Entity-Vergleich ──────────────────────────────
  {name:'stromvergleich', desc:'Vergleicht aktuellen mit gestrigem Stromverbrauch', type:'entity_comparison',
   config:{entity_a:'sensor.strom_heute', entity_b:'sensor.strom_gestern', operation:'difference'}},
  {name:'innen_vs_aussen', desc:'Temperaturunterschied innen vs. aussen', type:'entity_comparison',
   config:{entity_a:'sensor.wohnzimmer_temperatur', entity_b:'sensor.aussen_temperatur', operation:'difference'}},
  {name:'solar_vs_verbrauch', desc:'Solarertrag vs. Stromverbrauch (Verhältnis)', type:'entity_comparison',
   config:{entity_a:'sensor.solar_produktion', entity_b:'sensor.stromverbrauch', operation:'ratio'}},

  // ── Multi-Entity-Formel ───────────────────────────
  {name:'komfort_index', desc:'Gewichteter Komfort-Index aus Temperatur und Luftfeuchtigkeit', type:'multi_entity_formula',
   config:{entities:{temp:'sensor.wohnzimmer_temperatur', hum:'sensor.wohnzimmer_luftfeuchtigkeit'}, formula:'weighted_average', weights:{temp:0.6, hum:0.4}}},
  {name:'gesamt_stromverbrauch', desc:'Summe aller Stromzaehler', type:'multi_entity_formula',
   config:{entities:{küche:'sensor.strom_küche', wohnzimmer:'sensor.strom_wohnzimmer', buero:'sensor.strom_buero'}, formula:'sum'}},

  // ── Event-Zähler ─────────────────────────────────
  {name:'türbewegungen', desc:'Zählt Türöffnungen heute', type:'event_counter',
   config:{entities:['binary_sensor.haustuer_kontakt'], count_state:'on', time_range:'24h'}},
  {name:'licht_schaltungen', desc:'Wie oft wurden Lichter heute geschaltet?', type:'event_counter',
   config:{entities:['light.wohnzimmer','light.küche','light.flur'], count_state:'on', time_range:'24h'}},
  {name:'fenster_oeffnungen', desc:'Fenster-Öffnungen diese Woche', type:'event_counter',
   config:{entities:['binary_sensor.fenster_wohnzimmer','binary_sensor.fenster_schlafzimmer'], count_state:'on', time_range:'7d'}},

  // ── Schwellwert-Monitor ───────────────────────────
  {name:'luftfeuchtigkeit_check', desc:'Prüft ob Luftfeuchtigkeit im Komfortbereich (40-60%)', type:'threshold_monitor',
   config:{entity:'sensor.wohnzimmer_luftfeuchtigkeit', thresholds:{min:40, max:60}}},
  {name:'co2_warnung', desc:'CO2-Wert unter 1000 ppm halten', type:'threshold_monitor',
   config:{entity:'sensor.co2', thresholds:{max:1000}}},
  {name:'batterie_check', desc:'Batterie-Sensor nicht unter 20% fallen lassen', type:'threshold_monitor',
   config:{entity:'sensor.tuersensor_batterie', thresholds:{min:20}}},
  {name:'raumtemperatur_check', desc:'Raumtemperatur im Wohlfuehlbereich (19-23 Grad)', type:'threshold_monitor',
   config:{entity:'sensor.wohnzimmer_temperatur', thresholds:{min:19, max:23}}},

  // ── Trend-Analyse ─────────────────────────────────
  {name:'temperatur_trend', desc:'Temperatur-Trend der letzten 24 Stunden', type:'trend_analyzer',
   config:{entity:'sensor.aussen_temperatur', time_range:'24h'}},
  {name:'stromverbrauch_trend', desc:'Stromverbrauch-Trend der letzten 7 Tage', type:'trend_analyzer',
   config:{entity:'sensor.stromverbrauch', time_range:'7d'}},
  {name:'luftfeuchtigkeit_trend', desc:'Luftfeuchtigkeit-Entwicklung letzte 12 Stunden', type:'trend_analyzer',
   config:{entity:'sensor.wohnzimmer_luftfeuchtigkeit', time_range:'12h'}},

  // ── Entity-Aggregation ────────────────────────────
  {name:'raumtemperaturen', desc:'Durchschnittstemperatur aller Räume', type:'entity_aggregator',
   config:{entities:['sensor.wohnzimmer_temperatur','sensor.schlafzimmer_temperatur','sensor.küche_temperatur'], aggregation:'average'}},
  {name:'kaeltester_raum', desc:'Findet den kältesten Raum', type:'entity_aggregator',
   config:{entities:['sensor.wohnzimmer_temperatur','sensor.schlafzimmer_temperatur','sensor.küche_temperatur','sensor.bad_temperatur'], aggregation:'min'}},
  {name:'feuchtester_raum', desc:'Hoechste Luftfeuchtigkeit aller Räume', type:'entity_aggregator',
   config:{entities:['sensor.wohnzimmer_luftfeuchtigkeit','sensor.schlafzimmer_luftfeuchtigkeit','sensor.bad_luftfeuchtigkeit'], aggregation:'max'}},

  // ── Zeitplan-Check ────────────────────────────────
  {name:'nachtmodus', desc:'Prüft ob Nachtmodus aktiv ist (22-07 Uhr)', type:'schedule_checker',
   config:{schedules:[{label:'Nachtmodus', start:'22:00', end:'07:00'}]}},
  {name:'arbeitszeit', desc:'Prüft Arbeitszeit (Mo-Fr 9-17 Uhr)', type:'schedule_checker',
   config:{schedules:[{label:'Arbeitszeit', start:'09:00', end:'17:00', days:['monday','tuesday','wednesday','thursday','friday']}]}},

  // ── Zustandsdauer (NEU) ───────────────────────────
  {name:'heizung_laufzeit', desc:'Wie lange lief die Heizung heute?', type:'state_duration',
   config:{entity:'climate.wohnzimmer', target_state:'heating', time_range:'24h'}},
  {name:'licht_brenndauer', desc:'Wie lange brannte das Wohnzimmerlicht heute?', type:'state_duration',
   config:{entity:'light.wohnzimmer', target_state:'on', time_range:'24h'}},
  {name:'fenster_offen_dauer', desc:'Wie lange war das Fenster heute geöffnet?', type:'state_duration',
   config:{entity:'binary_sensor.fenster_wohnzimmer', target_state:'on', time_range:'24h'}},
  {name:'tv_nutzung', desc:'Fernseher-Betriebsstunden diese Woche', type:'state_duration',
   config:{entity:'media_player.fernseher', target_state:'on', time_range:'7d'}},
  {name:'Wärmepumpe_laufzeit', desc:'Wärmepumpe Laufzeit letzte 7 Tage', type:'state_duration',
   config:{entity:'switch.Wärmepumpe', target_state:'on', time_range:'7d'}},

  // ── Zeitvergleich (NEU) ───────────────────────────
  {name:'strom_vs_gestern', desc:'Stromverbrauch heute vs. gestern', type:'time_comparison',
   config:{entity:'sensor.stromverbrauch', compare_period:'yesterday', aggregation:'average'}},
  {name:'temperatur_vs_vorwoche', desc:'Temperatur diese vs. letzte Woche', type:'time_comparison',
   config:{entity:'sensor.aussen_temperatur', compare_period:'last_week', aggregation:'average'}},
  {name:'heizkosten_monatsvergleich', desc:'Heizenergie diesen vs. letzten Monat', type:'time_comparison',
   config:{entity:'sensor.heizung_verbrauch', compare_period:'last_month', aggregation:'sum'}},
];

// ── Entity-Picker Helfer (standalone, ohne Settings-Binding) ─
function _declEntityInput(id, label, domains, placeholder, value) {
  const domStr = (domains||[]).join(',');
  return '<div class="form-group"><label>' + label + '</label>' +
    '<div class="entity-pick-wrap">' +
    '<input class="form-input entity-pick-input" id="' + id + '" value="' + esc(value||'') + '"' +
    ' data-room-map="' + id + '" data-domains="' + domStr + '"' +
    ' placeholder="' + (placeholder||'&#128269; Entity suchen...') + '"' +
    ' oninput="entityPickFilter(this,\'' + domStr + '\')" onfocus="entityPickFilter(this,\'' + domStr + '\')"' +
    ' style="font-family:var(--mono);font-size:13px;">' +
    '<div class="entity-pick-dropdown" style="display:none;"></div>' +
    '</div></div>';
}

function _declEntityListInput(id, label, domains, placeholder, values) {
  const domStr = (domains||[]).join(',');
  const arr = values || [];
  let tags = arr.map(function(k) {
    return '<span class="kw-tag">' + esc(k) + '<span class="kw-rm" onclick="declRmEntityTag(this)">&#10005;</span></span>';
  }).join('');
  return '<div class="form-group"><label>' + label + '</label>' +
    '<div class="entity-pick-wrap">' +
    '<div class="kw-editor" id="' + id + '" data-domains="' + domStr + '" onclick="this.querySelector(\'input\')?.focus()">' +
    tags + '<input class="kw-input entity-pick-input" placeholder="' + (placeholder||'&#128269; Entity suchen...') + '"' +
    ' oninput="entityPickFilter(this,\'' + domStr + '\')" onfocus="entityPickFilter(this,\'' + domStr + '\')"' +
    ' data-decl-list="' + id + '">' +
    '</div>' +
    '<div class="entity-pick-dropdown" style="display:none;"></div>' +
    '</div></div>';
}

function declRmEntityTag(el) { el.parentElement.remove(); }

// ── Multi-Entity-Formula Key-Value Editor ────────────────────
var _declMefCounter = 0;

function declMefAddRow(label, entityId, weight) {
  var container = document.getElementById('declCfg_mef_rows');
  if (!container) return;
  var idx = _declMefCounter++;
  var domStr = 'sensor,number,input_number';
  var row = document.createElement('div');
  row.className = 'decl-mef-row';
  row.style.cssText = 'display:flex;gap:8px;align-items:flex-start;margin-bottom:6px;';
  row.innerHTML =
    '<div style="flex:1;max-width:120px;">' +
    '<input type="text" class="form-input" id="declMef_label_' + idx + '" value="' + esc(label || '') + '" placeholder="Label" style="font-size:12px;"></div>' +
    '<div style="flex:2;" class="entity-pick-wrap">' +
    '<input class="form-input entity-pick-input" id="declMef_entity_' + idx + '" value="' + esc(entityId || '') + '"' +
    ' data-domains="' + domStr + '" placeholder="&#128269; Entity suchen..."' +
    ' oninput="entityPickFilter(this,\'' + domStr + '\')" onfocus="entityPickFilter(this,\'' + domStr + '\')"' +
    ' style="font-family:var(--mono);font-size:12px;">' +
    '<div class="entity-pick-dropdown" style="display:none;"></div></div>' +
    '<div style="flex:0 0 70px;">' +
    '<input type="number" class="form-input" id="declMef_weight_' + idx + '" value="' + (weight != null ? weight : '') + '" placeholder="Gew." step="0.1" style="font-size:12px;"></div>' +
    '<button type="button" class="btn btn-sm btn-danger" onclick="this.closest(\'.decl-mef-row\').remove()" style="padding:4px 8px;margin-top:1px;">&#10005;</button>';
  container.appendChild(row);
}

function _collectDeclMefEntities() {
  var container = document.getElementById('declCfg_mef_rows');
  if (!container) return {entities: {}, weights: {}};
  var entities = {}, weights = {};
  var rows = container.querySelectorAll('.decl-mef-row');
  rows.forEach(function(row) {
    var labelEl = row.querySelector('[id^="declMef_label_"]');
    var entityEl = row.querySelector('[id^="declMef_entity_"]');
    var weightEl = row.querySelector('[id^="declMef_weight_"]');
    var label = (labelEl?.value || '').trim();
    var entity = (entityEl?.value || '').trim();
    if (label && entity) {
      entities[label] = entity;
      var w = weightEl?.value;
      if (w !== '' && w != null) weights[label] = parseFloat(w);
    }
  });
  return {entities: entities, weights: weights};
}

function _getDeclEntityList(id) {
  const editor = document.getElementById(id);
  if (!editor) return [];
  return [...editor.querySelectorAll('.kw-tag')].map(function(t) {
    return (t.childNodes[0]?.textContent || '').trim();
  }).filter(Boolean);
}

// Hook: entityPickSelect für data-decl-list Inputs
(function() {
  const _orig = window.entityPickSelect;
  if (typeof _orig !== 'function') return;
  window.entityPickSelect = function(item, entityId) {
    var wrap = item.closest('.entity-pick-wrap');
    var input = wrap ? wrap.querySelector('[data-decl-list]') : null;
    if (input) {
      var listId = input.dataset.declList;
      var editor = document.getElementById(listId);
      if (editor) {
        var existing = _getDeclEntityList(listId);
        if (!existing.includes(entityId)) {
          var tag = document.createElement('span');
          tag.className = 'kw-tag';
          tag.innerHTML = esc(entityId) + '<span class="kw-rm" onclick="declRmEntityTag(this)">&#10005;</span>';
          editor.insertBefore(tag, input);
        }
        input.value = '';
        var dd = wrap.querySelector('.entity-pick-dropdown');
        if (dd) dd.style.display = 'none';
      }
      return;
    }
    // Alarm-Entity Picker: Wert direkt in Settings speichern
    var alarmInput = wrap ? wrap.querySelector('.entity-pick-alarm') : null;
    if (alarmInput) {
      alarmInput.value = entityId;
      setPath(S, 'vacuum.presence_guard.alarm_entity', entityId);
      scheduleAutoSave();
      var dd2 = wrap.querySelector('.entity-pick-dropdown');
      if (dd2) dd2.style.display = 'none';
      return;
    }
    _orig(item, entityId);
  };
})();

// ── Tool-Liste ───────────────────────────────────────────────
async function loadDeclarativeTools() {
  try {
    const d = await api('/api/ui/declarative-tools');
    _declTools = d.tools || [];
    _declEnabled = d.enabled !== false;
    _declSpontaneous = d.use_in_spontaneous !== false;
    _declMaxTools = d.max_tools || 20;
    _renderDeclToolList();
    _updateDeclEnabledUI();
  } catch(e) { console.error('Declarative tools load fail:', e); }
}

function _renderDeclToolList() {
  const container = document.getElementById('declToolList');
  if (!container) return;
  if (_declTools.length === 0) {
    container.innerHTML = '<div style="padding:16px;color:var(--text-secondary);font-style:italic;">Noch keine Analyse-Tools erstellt. Erstelle unten ein neues oder nutze eine Vorlage.</div>';
    return;
  }
  let h = '<div style="margin-bottom:8px;font-size:12px;color:var(--text-secondary);">' + _declTools.length + '/' + _declMaxTools + ' Tools</div>';
  for (const t of _declTools) {
    const typeInfo = DECL_TOOL_TYPES.find(tt => tt.v === t.type) || {l: t.type};
    h += '<div style="border:1px solid var(--border);border-radius:var(--radius-md);padding:14px;margin-bottom:10px;background:var(--bg-card);">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">' +
      '<div><strong style="color:var(--accent);font-size:14px;">' + esc(t.name) + '</strong>' +
      '<span style="margin-left:8px;font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(0,212,255,0.08);color:var(--text-secondary);">' + esc(typeInfo.l) + '</span></div>' +
      '<div style="display:flex;gap:6px;">' +
      '<button class="btn btn-sm" onclick="testDeclTool(\'' + esc(t.name) + '\')" style="padding:4px 10px;font-size:12px;">&#9654; Test</button>' +
      '<button class="btn btn-sm" onclick="editDeclTool(\'' + esc(t.name) + '\')" style="padding:4px 10px;font-size:12px;">&#9998; Bearbeiten</button>' +
      '<button class="btn btn-sm btn-danger" onclick="deleteDeclTool(\'' + esc(t.name) + '\')" style="padding:4px 10px;font-size:12px;">&#10005;</button>' +
      '</div></div>' +
      '<div style="margin-top:6px;font-size:12px;color:var(--text-secondary);">' + esc(t.description || '') + '</div>' +
      '<div id="declTestResult_' + esc(t.name) + '" style="display:none;margin-top:10px;padding:10px;background:var(--bg-secondary);border-radius:var(--radius-sm);font-size:12px;font-family:var(--mono);white-space:pre-wrap;"></div>' +
      '</div>';
  }
  container.innerHTML = h;
}

async function testDeclTool(name) {
  const el = document.getElementById('declTestResult_' + name);
  if (!el) return;
  el.style.display = 'block';
  el.style.color = 'var(--text-secondary)';
  el.textContent = 'Ausführen...';
  try {
    const r = await api('/api/ui/declarative-tools/' + encodeURIComponent(name) + '/test', 'POST');
    el.style.color = r.success ? 'var(--success)' : 'var(--danger)';
    el.textContent = r.message || JSON.stringify(r, null, 2);
  } catch(e) {
    el.style.color = 'var(--danger)';
    el.textContent = 'Fehler: ' + e.message;
  }
}

async function deleteDeclTool(name) {
  if (!confirm('Tool "' + name + '" wirklich loeschen?')) return;
  try {
    await api('/api/ui/declarative-tools/' + encodeURIComponent(name), 'DELETE');
    toast('Tool "' + name + '" gelöscht', 'success');
    loadDeclarativeTools();
  } catch(e) { toast('Fehler: ' + e.message, 'error'); }
}

// ── Bearbeiten ───────────────────────────────────────────────
function editDeclTool(name) {
  const tool = _declTools.find(t => t.name === name);
  if (!tool) return;
  _declEditMode = name;
  const nameEl = document.getElementById('declNewName');
  const descEl = document.getElementById('declNewDesc');
  const typeEl = document.getElementById('declNewType');
  const btnEl = document.getElementById('declSubmitBtn');
  const cancelBtn = document.getElementById('declCancelBtn');
  if (nameEl) { nameEl.value = name; nameEl.readOnly = true; nameEl.style.opacity = '0.6'; }
  if (descEl) descEl.value = tool.description || '';
  if (typeEl) { typeEl.value = tool.type || ''; onDeclTypeChange(); }
  if (btnEl) btnEl.innerHTML = '&#9998; Tool aktualisieren';
  if (cancelBtn) cancelBtn.style.display = 'inline-block';
  setTimeout(function() { _prefillDeclConfig(tool.type, tool.config || {}); }, 60);
  var formSection = document.getElementById('declFormSection');
  if (formSection) formSection.scrollIntoView({behavior:'smooth', block:'start'});
}

function cancelDeclEdit() {
  _declEditMode = null;
  var nameEl = document.getElementById('declNewName');
  var descEl = document.getElementById('declNewDesc');
  var typeEl = document.getElementById('declNewType');
  var btnEl = document.getElementById('declSubmitBtn');
  var cancelBtn = document.getElementById('declCancelBtn');
  if (nameEl) { nameEl.value = ''; nameEl.readOnly = false; nameEl.style.opacity = '1'; }
  if (descEl) descEl.value = '';
  if (typeEl) typeEl.value = '';
  if (btnEl) btnEl.innerHTML = '&#10010; Tool erstellen';
  if (cancelBtn) cancelBtn.style.display = 'none';
  document.getElementById('declConfigFields').innerHTML = '';
  _clearDeclValidation();
}

function _prefillDeclConfig(type, config) {
  switch(type) {
    case 'entity_comparison': {
      var a = document.getElementById('declCfg_entity_a');
      var b = document.getElementById('declCfg_entity_b');
      var op = document.getElementById('declCfg_operation');
      if (a) a.value = config.entity_a || '';
      if (b) b.value = config.entity_b || '';
      if (op) op.value = config.operation || 'difference';
      break;
    }
    case 'multi_entity_formula': {
      var f = document.getElementById('declCfg_formula');
      if (f) f.value = config.formula || 'average';
      var ents = config.entities || {};
      var wts = config.weights || {};
      _declMefCounter = 0;
      var mefContainer = document.getElementById('declCfg_mef_rows');
      if (mefContainer) mefContainer.innerHTML = '';
      Object.keys(ents).forEach(function(label) {
        declMefAddRow(label, ents[label], wts[label]);
      });
      break;
    }
    case 'event_counter':
    case 'entity_aggregator': {
      var listEl = document.getElementById('declCfg_entities_list');
      if (listEl && Array.isArray(config.entities)) {
        var inp = listEl.querySelector('.kw-input');
        config.entities.forEach(function(eid) {
          var tag = document.createElement('span');
          tag.className = 'kw-tag';
          tag.innerHTML = esc(eid) + '<span class="kw-rm" onclick="declRmEntityTag(this)">&#10005;</span>';
          if (inp) listEl.insertBefore(tag, inp);
        });
      }
      if (type === 'event_counter') {
        var cs = document.getElementById('declCfg_count_state');
        if (cs) cs.value = config.count_state || 'on';
      }
      if (type === 'entity_aggregator') {
        var agg = document.getElementById('declCfg_aggregation');
        if (agg) agg.value = config.aggregation || 'average';
      }
      var tr = document.getElementById('declCfg_time_range');
      if (tr && config.time_range) tr.value = config.time_range;
      break;
    }
    case 'threshold_monitor': {
      var ent = document.getElementById('declCfg_entity');
      var mn = document.getElementById('declCfg_th_min');
      var mx = document.getElementById('declCfg_th_max');
      if (ent) ent.value = config.entity || '';
      if (mn && config.thresholds?.min != null) mn.value = config.thresholds.min;
      if (mx && config.thresholds?.max != null) mx.value = config.thresholds.max;
      break;
    }
    case 'trend_analyzer': {
      var ent2 = document.getElementById('declCfg_entity');
      var tr2 = document.getElementById('declCfg_time_range');
      if (ent2) ent2.value = config.entity || '';
      if (tr2) tr2.value = config.time_range || '24h';
      break;
    }
    case 'schedule_checker': {
      var s = document.getElementById('declCfg_schedules');
      if (s) s.value = JSON.stringify(config.schedules || [], null, 2);
      break;
    }
    case 'state_duration': {
      var ent3 = document.getElementById('declCfg_entity');
      var ts = document.getElementById('declCfg_target_state');
      var tr3 = document.getElementById('declCfg_time_range');
      if (ent3) ent3.value = config.entity || '';
      if (ts) ts.value = config.target_state || '';
      if (tr3) tr3.value = config.time_range || '24h';
      break;
    }
    case 'time_comparison': {
      var ent4 = document.getElementById('declCfg_entity');
      var cp = document.getElementById('declCfg_compare_period');
      var agg2 = document.getElementById('declCfg_aggregation');
      if (ent4) ent4.value = config.entity || '';
      if (cp) cp.value = config.compare_period || 'yesterday';
      if (agg2) agg2.value = config.aggregation || 'average';
      break;
    }
  }
}

// ── Vorlagen laden ───────────────────────────────────────────
function loadDeclPreset(idx) {
  var preset = DECL_PRESETS[idx];
  if (!preset) return;
  cancelDeclEdit();
  var nameEl = document.getElementById('declNewName');
  var descEl = document.getElementById('declNewDesc');
  var typeEl = document.getElementById('declNewType');
  if (nameEl) nameEl.value = preset.name;
  if (descEl) descEl.value = preset.desc;
  if (typeEl) typeEl.value = preset.type;
  onDeclTypeChange();
  setTimeout(function() { _prefillDeclConfig(preset.type, preset.config); }, 60);
  var formSection = document.getElementById('declFormSection');
  if (formSection) formSection.scrollIntoView({behavior:'smooth', block:'start'});
  toast('Vorlage "' + preset.name + '" geladen — Entity-IDs anpassen!', 'success');
}

// ── Config-Felder mit Entity-Picker ──────────────────────────
function _declTypeConfigFields(type) {
  switch(type) {
    case 'entity_comparison':
      return _declEntityInput('declCfg_entity_a', 'Entity A', ['sensor','number','input_number'], 'z.B. sensor.strom_heute') +
        _declEntityInput('declCfg_entity_b', 'Entity B', ['sensor','number','input_number'], 'z.B. sensor.strom_gestern') +
        '<div class="form-group"><label>Operation' + helpBtn('decl_tools.operation') + '</label><select id="declCfg_operation">' +
        DECL_OPERATIONS.map(o => '<option value="' + o.v + '">' + o.l + '</option>').join('') +
        '</select></div>';
    case 'multi_entity_formula':
      return '<div class="form-group"><label>Entities' + helpBtn('decl_tools.entities') + '</label>' +
        '<div id="declCfg_mef_rows"></div>' +
        '<button type="button" class="btn btn-sm" onclick="declMefAddRow()" style="margin-top:6px;">&#10010; Entity hinzufügen</button>' +
        '<div class="hint">Label = Bezeichner in der Ausgabe, Entity = HA-Sensor</div></div>' +
        '<div class="form-group"><label>Formel' + helpBtn('decl_tools.formula') + '</label><select id="declCfg_formula">' +
        DECL_FORMULAS.map(o => '<option value="' + o.v + '">' + o.l + '</option>').join('') +
        '</select></div>' +
        '<div class="form-group"><label>Gewichte (optional)</label>' +
        '<div class="hint">Gewichte pro Label (nur bei "Gewichteter Durchschnitt"). Leer = gleich gewichtet.</div>' +
        '<div id="declCfg_weights_info" style="font-size:12px;color:var(--text-secondary);margin-top:4px;">Gewichte werden automatisch aus den Entity-Zeilen generiert.</div></div>';
    case 'event_counter':
      return _declEntityListInput('declCfg_entities_list', 'Entities', ['binary_sensor','sensor'], 'Entity suchen...') +
        '<div class="form-group"><label>State zaehlen</label>' +
        '<input type="text" id="declCfg_count_state" placeholder="on" value="on">' +
        '<div class="hint">State-Wert der gezählt wird (z.B. "on", "open")</div></div>' +
        '<div class="form-group"><label>Zeitraum' + helpBtn('decl_tools.time_range') + '</label><select id="declCfg_time_range">' +
        DECL_TIME_RANGES.map(o => '<option value="' + o.v + '"' + (o.v==='24h'?' selected':'') + '>' + o.l + '</option>').join('') +
        '</select></div>';
    case 'threshold_monitor':
      return _declEntityInput('declCfg_entity', 'Entity', ['sensor','number','input_number'], 'z.B. sensor.luftfeuchtigkeit') +
        '<div style="display:flex;gap:12px;">' +
        '<div class="form-group" style="flex:1;"><label>Minimum' + helpBtn('decl_tools.thresholds') + '</label>' +
        '<input type="number" id="declCfg_th_min" placeholder="z.B. 40"></div>' +
        '<div class="form-group" style="flex:1;"><label>Maximum</label>' +
        '<input type="number" id="declCfg_th_max" placeholder="z.B. 60"></div></div>';
    case 'trend_analyzer':
      return _declEntityInput('declCfg_entity', 'Entity', ['sensor','number'], 'z.B. sensor.temperatur') +
        '<div class="form-group"><label>Zeitraum' + helpBtn('decl_tools.time_range') + '</label><select id="declCfg_time_range">' +
        DECL_TIME_RANGES.map(o => '<option value="' + o.v + '"' + (o.v==='24h'?' selected':'') + '>' + o.l + '</option>').join('') +
        '</select></div>';
    case 'entity_aggregator':
      return _declEntityListInput('declCfg_entities_list', 'Entities (min. 2)', ['sensor','number','input_number'], 'Entity suchen...') +
        '<div class="form-group"><label>Aggregation</label><select id="declCfg_aggregation">' +
        DECL_AGGREGATIONS.map(o => '<option value="' + o.v + '">' + o.l + '</option>').join('') +
        '</select></div>';
    case 'schedule_checker':
      return '<div class="form-group"><label>Zeitplaene (JSON-Array)</label>' +
        '<textarea id="declCfg_schedules" rows="5" style="font-family:var(--mono);font-size:12px;" placeholder=\'[{"label":"Nachtmodus","start":"22:00","end":"06:00"}]\'></textarea>' +
        '<div class="hint">label, start (HH:MM), end (HH:MM). Optional: days (Array). Nacht-Zeitplaene (22:00-06:00) werden korrekt erkannt.</div></div>';
    case 'state_duration':
      return _declEntityInput('declCfg_entity', 'Entity', ['sensor','binary_sensor','climate','switch','light','cover'], 'z.B. climate.wohnzimmer') +
        '<div class="form-group"><label>Ziel-State</label>' +
        '<input type="text" id="declCfg_target_state" placeholder="z.B. on, heating, open">' +
        '<div class="hint">Der State-Wert dessen Dauer gemessen wird</div></div>' +
        '<div class="form-group"><label>Zeitraum</label><select id="declCfg_time_range">' +
        DECL_TIME_RANGES.map(o => '<option value="' + o.v + '"' + (o.v==='24h'?' selected':'') + '>' + o.l + '</option>').join('') +
        '</select></div>';
    case 'time_comparison':
      return _declEntityInput('declCfg_entity', 'Entity', ['sensor','number','input_number'], 'z.B. sensor.stromverbrauch') +
        '<div class="form-group"><label>Vergleichszeitraum</label><select id="declCfg_compare_period">' +
        DECL_COMPARE_PERIODS.map(o => '<option value="' + o.v + '">' + o.l + '</option>').join('') +
        '</select></div>' +
        '<div class="form-group"><label>Aggregation</label><select id="declCfg_aggregation">' +
        DECL_AGGREGATIONS.map(o => '<option value="' + o.v + '">' + o.l + '</option>').join('') +
        '</select></div>';
    default:
      return '<div style="color:var(--text-secondary);padding:8px;">Bitte Typ wählen.</div>';
  }
}

// ── Config sammeln mit Validierung ───────────────────────────
function _collectDeclConfig(type) {
  var cfg = {};
  var errors = [];
  switch(type) {
    case 'entity_comparison':
      cfg.entity_a = (document.getElementById('declCfg_entity_a')?.value || '').trim();
      cfg.entity_b = (document.getElementById('declCfg_entity_b')?.value || '').trim();
      cfg.operation = document.getElementById('declCfg_operation')?.value || 'difference';
      if (!cfg.entity_a) errors.push('Entity A ist erforderlich');
      if (!cfg.entity_b) errors.push('Entity B ist erforderlich');
      break;
    case 'multi_entity_formula': {
      var mef = _collectDeclMefEntities();
      cfg.entities = mef.entities;
      cfg.formula = document.getElementById('declCfg_formula')?.value || 'average';
      if (Object.keys(cfg.entities).length < 2) errors.push('Mindestens 2 Entities mit Label erforderlich');
      if (Object.keys(mef.weights).length > 0) cfg.weights = mef.weights;
      break;
    }
    case 'event_counter':
      cfg.entities = _getDeclEntityList('declCfg_entities_list');
      cfg.count_state = (document.getElementById('declCfg_count_state')?.value || 'on').trim();
      cfg.time_range = document.getElementById('declCfg_time_range')?.value || '24h';
      if (cfg.entities.length === 0) errors.push('Mindestens eine Entity erforderlich');
      break;
    case 'threshold_monitor':
      cfg.entity = (document.getElementById('declCfg_entity')?.value || '').trim();
      cfg.thresholds = {};
      var thMin = document.getElementById('declCfg_th_min')?.value;
      var thMax = document.getElementById('declCfg_th_max')?.value;
      if (thMin !== '' && thMin != null) cfg.thresholds.min = parseFloat(thMin);
      if (thMax !== '' && thMax != null) cfg.thresholds.max = parseFloat(thMax);
      if (!cfg.entity) errors.push('Entity ist erforderlich');
      if (cfg.thresholds.min == null && cfg.thresholds.max == null) errors.push('Min oder Max Schwellwert erforderlich');
      break;
    case 'trend_analyzer':
      cfg.entity = (document.getElementById('declCfg_entity')?.value || '').trim();
      cfg.time_range = document.getElementById('declCfg_time_range')?.value || '24h';
      if (!cfg.entity) errors.push('Entity ist erforderlich');
      break;
    case 'entity_aggregator':
      cfg.entities = _getDeclEntityList('declCfg_entities_list');
      cfg.aggregation = document.getElementById('declCfg_aggregation')?.value || 'average';
      if (cfg.entities.length < 2) errors.push('Mindestens 2 Entities erforderlich');
      break;
    case 'schedule_checker':
      try { cfg.schedules = JSON.parse(document.getElementById('declCfg_schedules')?.value || '[]'); }
      catch(e) { errors.push('Zeitplaene: Ungueltiges JSON'); break; }
      if (!Array.isArray(cfg.schedules) || cfg.schedules.length === 0) errors.push('Mindestens ein Zeitplan erforderlich');
      break;
    case 'state_duration':
      cfg.entity = (document.getElementById('declCfg_entity')?.value || '').trim();
      cfg.target_state = (document.getElementById('declCfg_target_state')?.value || '').trim();
      cfg.time_range = document.getElementById('declCfg_time_range')?.value || '24h';
      if (!cfg.entity) errors.push('Entity ist erforderlich');
      if (!cfg.target_state) errors.push('Ziel-State ist erforderlich');
      break;
    case 'time_comparison':
      cfg.entity = (document.getElementById('declCfg_entity')?.value || '').trim();
      cfg.compare_period = document.getElementById('declCfg_compare_period')?.value || 'yesterday';
      cfg.aggregation = document.getElementById('declCfg_aggregation')?.value || 'average';
      if (!cfg.entity) errors.push('Entity ist erforderlich');
      break;
  }
  if (errors.length > 0) { _showDeclValidation(errors); return null; }
  _clearDeclValidation();
  return cfg;
}

// ── Validierung ──────────────────────────────────────────────
function _showDeclValidation(errors) {
  var el = document.getElementById('declValidation');
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML = errors.map(function(e) { return '<div style="color:var(--danger);font-size:12px;margin-bottom:4px;">&#9888; ' + esc(e) + '</div>'; }).join('');
}
function _clearDeclValidation() {
  var el = document.getElementById('declValidation');
  if (el) { el.style.display = 'none'; el.innerHTML = ''; }
}

function onDeclTypeChange() {
  var type = document.getElementById('declNewType')?.value || '';
  var container = document.getElementById('declConfigFields');
  if (container) container.innerHTML = _declTypeConfigFields(type);
  var typeInfo = DECL_TOOL_TYPES.find(function(t) { return t.v === type; });
  var descField = document.getElementById('declNewDesc');
  if (descField && !descField.value && typeInfo) descField.placeholder = typeInfo.desc;
  _clearDeclValidation();
  // Bei multi_entity_formula: 2 leere Zeilen als Startpunkt
  if (type === 'multi_entity_formula') {
    _declMefCounter = 0;
    declMefAddRow('', '', null);
    declMefAddRow('', '', null);
  }
}

async function createDeclTool() {
  var name = (document.getElementById('declNewName')?.value || '').trim();
  var desc = (document.getElementById('declNewDesc')?.value || '').trim();
  var type = document.getElementById('declNewType')?.value || '';
  var errors = [];
  if (!name) errors.push('Name ist erforderlich');
  else if (!/^[a-zA-Z0-9_-]+$/.test(name)) errors.push('Name: Nur Buchstaben, Zahlen, _ und - erlaubt');
  if (!desc) errors.push('Beschreibung ist erforderlich');
  if (!type) errors.push('Bitte Typ wählen');
  if (errors.length > 0) { _showDeclValidation(errors); return; }
  var config = _collectDeclConfig(type);
  if (config === null) return;
  var isEdit = _declEditMode != null;
  try {
    await api('/api/ui/declarative-tools', 'POST', {name:name, description:desc, type:type, config:config});
    toast('Tool "' + name + '" ' + (isEdit ? 'aktualisiert' : 'erstellt'), 'success');
    cancelDeclEdit();
    loadDeclarativeTools();
  } catch(e) {
    _showDeclValidation([e.detail || e.message || 'Unbekannter Fehler']);
  }
}

// ── Feature-Toggle ───────────────────────────────────────────
let _declEnabled = true;
let _declSpontaneous = true;
let _declMaxTools = 20;

async function toggleDeclEnabled() {
  _declEnabled = !_declEnabled;
  try {
    await api('/api/ui/settings', 'PUT', {settings: {declarative_tools: {enabled: _declEnabled}}});
    toast('Analyse-Tools ' + (_declEnabled ? 'aktiviert' : 'deaktiviert'), 'success');
  } catch(e) { toast('Fehler: ' + (e.message || e), 'error'); _declEnabled = !_declEnabled; }
  _updateDeclEnabledUI();
}

async function toggleDeclSpontaneous() {
  _declSpontaneous = !_declSpontaneous;
  try {
    await api('/api/ui/settings', 'PUT', {settings: {declarative_tools: {use_in_spontaneous: _declSpontaneous}}});
    toast('Proaktive Nutzung ' + (_declSpontaneous ? 'aktiviert' : 'deaktiviert'), 'success');
  } catch(e) { toast('Fehler: ' + (e.message || e), 'error'); _declSpontaneous = !_declSpontaneous; }
  var t = document.getElementById('declSpontaneousToggle');
  if (t) t.checked = _declSpontaneous;
}

async function updateDeclMaxTools(val) {
  _declMaxTools = parseInt(val) || 20;
  try {
    await api('/api/ui/settings', 'PUT', {settings: {declarative_tools: {max_tools: _declMaxTools}}});
    toast('Max. Tools: ' + _declMaxTools, 'success');
  } catch(e) { toast('Fehler: ' + (e.message || e), 'error'); }
}

function _updateDeclEnabledUI() {
  var toggle = document.getElementById('declEnabledToggle');
  if (toggle) toggle.checked = _declEnabled;
  var spToggle = document.getElementById('declSpontaneousToggle');
  if (spToggle) spToggle.checked = _declSpontaneous;
  var slider = document.getElementById('declMaxToolsSlider');
  if (slider) slider.value = _declMaxTools;
  var sliderVal = document.getElementById('declMaxToolsVal');
  if (sliderVal) sliderVal.textContent = _declMaxTools;
  var body = document.getElementById('declBody');
  if (body) {
    body.style.opacity = _declEnabled ? '1' : '0.4';
    body.style.pointerEvents = _declEnabled ? 'auto' : 'none';
  }
}

// ── Vorschläge (Suggestions) ─────────────────────────────────
let _declSuggestions = [];
let _declSuggestLoading = false;
let _declSuggestBusy = false;  // Sperrt alle Suggestion-Buttons während async Ops

async function generateDeclSuggestions() {
  if (_declSuggestLoading) return;
  _declSuggestLoading = true;
  var btn = document.getElementById('declSuggestBtn');
  var container = document.getElementById('declSuggestionsList');
  if (btn) { btn.disabled = true; btn.innerHTML = '&#9203; Analysiere Entities...'; }
  if (container) container.innerHTML = '<div style="padding:16px;color:var(--text-secondary);font-style:italic;">Jarvis analysiert deine Home-Assistant-Entities und generiert Vorschläge...</div>';
  try {
    var r = await api('/api/ui/declarative-tools/suggest', 'POST', {use_llm: true});
    _declSuggestions = r.suggestions || [];
    _renderDeclSuggestions();
    if (_declSuggestions.length === 0) {
      toast('Keine neuen Vorschläge — alle sinnvollen Tools existieren bereits!', 'success');
    } else {
      toast(_declSuggestions.length + ' Vorschläge generiert', 'success');
    }
  } catch(e) {
    toast('Fehler: ' + (e.message || e), 'error');
    if (container) container.innerHTML = '<div style="padding:16px;color:var(--danger);">Fehler beim Generieren: ' + esc(e.message || String(e)) + '</div>';
  } finally {
    _declSuggestLoading = false;
    if (btn) { btn.disabled = false; btn.innerHTML = '&#128161; Vorschläge generieren'; }
  }
}

function _renderDeclSuggestions() {
  var container = document.getElementById('declSuggestionsList');
  if (!container) return;
  if (_declSuggestions.length === 0) {
    container.innerHTML = '<div style="padding:16px;color:var(--text-secondary);font-style:italic;">Keine Vorschläge vorhanden. Klicke "Vorschläge generieren" um Jarvis deine Entities analysieren zu lassen.</div>';
    return;
  }
  var h = '<div style="margin-bottom:8px;font-size:12px;color:var(--text-secondary);">' + _declSuggestions.length + ' Vorschläge</div>';
  _declSuggestions.forEach(function(s, i) {
    var typeInfo = DECL_TOOL_TYPES.find(function(t) { return t.v === s.type; }) || {l: s.type};
    h += '<div class="decl-suggestion" style="border:1px solid var(--border);border-radius:var(--radius-md);padding:14px;margin-bottom:10px;background:var(--bg-card);border-left:3px solid var(--accent);">' +
      '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">' +
      '<div style="flex:1;">' +
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
      '<strong style="color:var(--accent);font-size:14px;">' + esc(s.name) + '</strong>' +
      '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(0,212,255,0.08);color:var(--text-secondary);">' + esc(typeInfo.l) + '</span>' +
      '</div>' +
      '<div style="margin-top:6px;font-size:13px;color:var(--text-primary);">' + esc(s.description) + '</div>' +
      '<div style="margin-top:4px;font-size:12px;color:var(--text-secondary);font-style:italic;">' + esc(s.reason || '') + '</div>' +
      '</div>' +
      '<div style="display:flex;gap:6px;flex-shrink:0;">' +
      '<button class="btn btn-sm" onclick="acceptDeclSuggestion(' + i + ')" style="padding:6px 12px;font-size:12px;background:var(--success);color:#fff;border:none;">&#10003; Annehmen</button>' +
      '<button class="btn btn-sm" onclick="rejectDeclSuggestion(' + i + ')" style="padding:6px 12px;font-size:12px;">&#10005; Ablehnen</button>' +
      '</div></div></div>';
  });
  // "Alle annehmen" Button wenn mehrere
  if (_declSuggestions.length > 1) {
    h += '<div style="display:flex;gap:8px;margin-top:8px;">' +
      '<button class="btn btn-sm" onclick="acceptAllDeclSuggestions()" style="padding:6px 16px;font-size:12px;background:var(--success);color:#fff;border:none;">&#10003; Alle annehmen (' + _declSuggestions.length + ')</button>' +
      '<button class="btn btn-sm" onclick="rejectAllDeclSuggestions()" style="padding:6px 16px;font-size:12px;">&#10005; Alle ablehnen</button>' +
      '</div>';
  }
  container.innerHTML = h;
}

async function acceptDeclSuggestion(idx) {
  if (_declSuggestBusy) return;
  var s = _declSuggestions[idx];
  if (!s) return;
  _declSuggestBusy = true;
  try {
    await api('/api/ui/declarative-tools', 'POST', {
      name: s.name, description: s.description, type: s.type, config: s.config
    });
    toast('Tool "' + s.name + '" erstellt', 'success');
    _declSuggestions.splice(idx, 1);
    _renderDeclSuggestions();
    loadDeclarativeTools();
  } catch(e) {
    toast('Fehler: ' + (e.message || e), 'error');
  } finally {
    _declSuggestBusy = false;
  }
}

function rejectDeclSuggestion(idx) {
  var s = _declSuggestions[idx];
  if (!s) return;
  _declSuggestions.splice(idx, 1);
  _renderDeclSuggestions();
  toast('Vorschlag "' + s.name + '" abgelehnt', 'success');
}

async function acceptAllDeclSuggestions() {
  if (_declSuggestBusy) return;
  if (!confirm(_declSuggestions.length + ' Vorschläge annehmen?')) return;
  _declSuggestBusy = true;
  var accepted = 0;
  var errors = 0;
  var lastError = '';
  // Copy before mutating
  var all = _declSuggestions.slice();
  var failed = [];
  for (var i = 0; i < all.length; i++) {
    var s = all[i];
    try {
      await api('/api/ui/declarative-tools', 'POST', {
        name: s.name, description: s.description, type: s.type, config: s.config
      });
      accepted++;
    } catch(e) {
      errors++;
      lastError = e.message || String(e);
      failed.push(s);
    }
  }
  _declSuggestBusy = false;
  _declSuggestions = failed;
  _renderDeclSuggestions();
  loadDeclarativeTools();
  if (errors > 0) {
    toast(accepted + ' Tools erstellt, ' + errors + ' Fehler (' + lastError + ')', 'warning');
  } else {
    toast(accepted + ' Tools erstellt', 'success');
  }
}

function rejectAllDeclSuggestions() {
  if (_declSuggestBusy) return;
  if (!confirm(_declSuggestions.length + ' Vorschläge ablehnen?')) return;
  _declSuggestions = [];
  _renderDeclSuggestions();
  toast('Alle Vorschläge abgelehnt', 'success');
}

// ---- Tab: Intelligenz — Quick Wins ----
function renderIntelligence() {
  return sectionWrap('&#127919;', 'Domain-spezifische Autonomie',
    fInfo('Unterschiedliche Autonomie-Level pro Bereich. Z.B. Level 4 bei Klima (darf Temperatur selbst anpassen), aber Level 2 bei Sicherheit (nur informieren). Wenn deaktiviert gilt das globale Level für alle Bereiche.') +
    fToggle('autonomy.domain_levels_enabled', 'Domain-Autonomie aktivieren') +
    fSubheading('Level pro Domaene') +
    fRange('autonomy.domain_levels.climate', 'Klima & Heizung', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fRange('autonomy.domain_levels.light', 'Licht & Beleuchtung', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fRange('autonomy.domain_levels.media', 'Medien & Musik', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fRange('autonomy.domain_levels.cover', 'Rollläden', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fRange('autonomy.domain_levels.security', 'Sicherheit', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fRange('autonomy.domain_levels.automation', 'Automationen & Routinen', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fRange('autonomy.domain_levels.notification', 'Benachrichtigungen', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'})
  ) +
  sectionWrap('&#128197;', 'Kalender-Intelligenz',
    fInfo('Erkennt Gewohnheiten aus wiederkehrenden Terminen, warnt bei Zeitkonflikten (Pendelzeit vs. Meeting) und zeigt freie Zeitfenster an.') +
    fToggle('calendar_intelligence.enabled', 'Kalender-Intelligenz aktiv') +
    fNum('calendar_intelligence.commute_minutes', 'Pendelzeit (Minuten)', 5, 120, 5) +
    fNum('calendar_intelligence.habit_min_occurrences', 'Min. Wiederholungen für Gewohnheit', 2, 10) +
    fNum('calendar_intelligence.conflict_lookahead_hours', 'Konflikt-Vorschau (Stunden)', 6, 72, 6) +
    fSubheading('Erkennungs-Module') +
    fToggle('calendar_intelligence.habit_detection', 'Gewohnheits-Erkennung') +
    fToggle('calendar_intelligence.conflict_detection', 'Konflikt-Erkennung') +
    fToggle('calendar_intelligence.break_detection', 'Pausen-Erkennung') +
    fToggle('calendar_intelligence.per_route_commute', 'Per-Route Pendelzeiten lernen') +
    fInfo('Lernt individuelle Pendelzeiten pro Ziel statt eines globalen Durchschnittswerts.')
  ) +
  sectionWrap('&#128161;', 'Erklärbarkeit',
    fInfo('Jarvis erklaert auf Nachfrage warum er etwas getan hat. Jede automatische Aktion wird mit Begründung geloggt. Frage z.B. "Warum hast du das Licht eingeschaltet?"') +
    fToggle('explainability.enabled', 'Erklärbarkeit aktiv') +
    fSelect('explainability.detail_level', 'Detail-Stufe', [
      {v:'minimal', l:'Minimal (nur Aktion + Grund)'},
      {v:'normal', l:'Normal (+ Kontext)'},
      {v:'verbose', l:'Ausführlich (+ Konfidenz, Sensordaten)'}
    ]) +
    fToggle('explainability.auto_explain', 'Automatisch erwaehnen') +
    fNum('explainability.max_history', 'Max. gespeicherte Entscheidungen', 10, 200, 10) +
    fSubheading('Erweiterte Erklaerungen') +
    fToggle('explainability.counterfactual_enabled', 'Was-waere-wenn Erklaerungen') +
    fToggle('explainability.reasoning_chains', 'Kausalketten anzeigen') +
    fToggle('explainability.confidence_display', 'Konfidenz in Erklaerungen') +
    fSelect('explainability.explanation_style', 'Erklaerungs-Stil', [
      {v:'template', l:'Template (schnell, deterministisch)'},
      {v:'llm', l:'LLM (natuerlich, Butler-Stil)'},
      {v:'auto', l:'Auto (Template fuer einfach, LLM fuer komplex)'}
    ])
  ) +
  sectionWrap('&#129504;', 'Lern-Transfer',
    fInfo('Überträgt Präferenzen zwischen ähnlichen Räumen. Wenn du warmes Licht in der Küche bevorzugst, schlägt Jarvis das auch für das Esszimmer vor.') +
    fToggle('learning_transfer.enabled', 'Lern-Transfer aktiv') +
    fToggle('learning_transfer.auto_suggest', 'Automatische Vorschläge') +
    fToggle('learning_transfer.notify_user', 'Über Transfers benachrichtigen') +
    fInfo('Benachrichtigt wenn Praeferenzen zwischen Raeumen uebertragen werden, z.B. "Lichteinstellung aus Kueche auf Esszimmer uebertragen."') +
    fNum('learning_transfer.min_observations', 'Min. Beobachtungen vor Transfer', 2, 10) +
    fRange('learning_transfer.transfer_confidence', 'Transfer-Konfidenz', 0.3, 1.0, 0.05, {0.3:'0.3',0.5:'0.5',0.7:'0.7',0.8:'0.8',0.9:'0.9',1.0:'1.0'}) +
    fSubheading('Aktive Domaenen') +
    fChipSelect('learning_transfer.domains', 'Transfer-Domaenen', [
      {v:'light', l:'Licht'},
      {v:'climate', l:'Klima'},
      {v:'media', l:'Medien'}
    ], 'Für welche Bereiche sollen Präferenzen übertragen werden?') +
    fSubheading('Raum-Gruppen') +
    fInfo('Räume in der gleichen Gruppe werden als ähnlich betrachtet. Änderungen hier überschreiben die Standard-Gruppen.') +
    fTextarea('learning_transfer.room_groups', 'Raum-Gruppen (JSON)', 'Format: {"wohnbereich": ["wohnzimmer", "esszimmer"], "schlafbereich": ["schlafzimmer", "gästezimmer"]}')
  ) +
  sectionWrap('&#128161;', 'Think-Ahead Hinweise',
    fInfo('Nach einer Aktion schlägt Jarvis einen logischen nächsten Schritt vor. Z.B. nach "Licht im Flur an" → "Soll ich auch die Heizung im Flur hochdrehen?" Statisch, kein LLM-Overhead.') +
    fToggle('next_step_hints.enabled', 'Think-Ahead aktiv') +
    fToggle('brain.think_ahead_enabled', 'Kontext-basierte Folgeaktionen') +
    fInfo('Analysiert den aktuellen Kontext (Raum, Tageszeit, offene Fenster) und schlaegt passende Folgeaktionen vor — z.B. "Fenster ist offen, soll ich die Heizung pausieren?"')
  ) +
  // --- Antizipation & Erkennung ---
  '<div class="cat-header">&#128268; Antizipation &amp; Mustererkennung</div>' +
  sectionWrap('&#128279;', 'Kausalketten-Erkennung',
    fInfo('Jarvis erkennt wiederkehrende Handlungsketten: Wenn du 3x hintereinander "Licht an, Heizung hoch, Musik an" machst, schlägt er beim nächsten Mal die gesamte Kette vor.') +
    fNum('anticipation.causal_chain_window_min', 'Erkennungsfenster (Minuten)', 5, 30) +
    fNum('anticipation.causal_chain_min_occurrences', 'Min. Wiederholungen', 2, 10) +
    fSubheading('Implizite Beduerfnisse') +
    fInfo('Erkennt Beduerfnisse auch ohne bekanntes Pattern — z.B. "Es ist dunkel und kalt" ergibt Licht + Heizung vorschlagen.') +
    fToggle('anticipation.implicit_needs_enabled', 'Implizite Beduerfnis-Erkennung') +
    fRange('anticipation.implicit_needs_min_confidence', 'Min. Konfidenz', 0.5, 0.9, 0.05, {0.5:'50%',0.6:'60%',0.7:'70% (Standard)',0.8:'80%',0.9:'90%'})
  ) +
  sectionWrap('&#128200;', '3D+ Insight Checks',
    fInfo('Mehrdimensionale Kreuzreferenz-Prüfungen: Kalender x Sicherheit x Hausstatus. Erkennt z.B. "Gäste kommen in 2h aber Haus nicht vorbereitet" oder "Alle weg aber Alarm nicht scharf".') +
    fToggle('insight_checks.guest_preparation', 'Gäste-Vorbereitung (Kalender x Haus)') +
    fToggle('insight_checks.away_security_full', 'Abwesenheits-Sicherheit (Praesenz x Alarm)') +
    fToggle('insight_checks.health_work_pattern', 'Arbeits-Muster (Aktivität x Dauer)') +
    fToggle('insight_checks.humidity_contradiction', 'Feuchtigkeits-Widerspruch (Geräte x Wetter)') +
    fToggle('insight_checks.night_security', 'Nacht-Sicherheit (Uhrzeit x Fenster x Türen)') +
    fToggle('insight_checks.heating_vs_sun', 'Heizung vs Sonne (Klima x Wetter x Rollladen)') +
    fToggle('insight_checks.forgotten_devices', 'Vergessene Geräte (Media x Abwesenheit)') +
    fToggle('insight_checks.deduplication', 'Alert-Deduplizierung') +
    fInfo('Verhindert mehrfache Alerts fuer die gleiche Entity bei verschiedenen Insight-Checks.')
  ) +
  sectionWrap('&#129504;', 'LLM Kausal-Analyse',
    fInfo('Das LLM analysiert Sensordaten der letzten Stunden und sucht nach ungewöhnlichen Korrelationen die kein Mensch als Regel kodiert haette. Z.B. "Temperatur sinkt obwohl Heizung laeuft — Fenster offen?"') +
    fToggle('insight_llm_causal.enabled', 'LLM Kausal-Analyse aktiv')
  ) +
  sectionWrap('&#128279;', 'Prozedurales Lernen',
    fInfo('Jarvis lernt Multi-Step-Sequenzen: "Filmabend" = Licht dimmen → Rolladen zu → TV an. Erstellt verkettete HA-Automationen mit Delays.') +
    fToggle('procedural_learning.enabled', 'Prozedurales Lernen aktiv') +
    fNum('procedural_learning.max_steps', 'Max. Schritte pro Sequenz', 2, 20)
  ) +
  sectionWrap('&#128270;', 'Routine-Abweichungen',
    fInfo('Erkennt wenn jemand von seiner normalen Routine abweicht — z.B. "Max ist normalerweise um 18 Uhr zuhause, heute nicht." Nutzt Presence-Tracker und Kalender.') +
    fToggle('routine_deviation.enabled', 'Routine-Abweichungen erkennen')
  ) +
  sectionWrap('&#128680;', 'Routine-Anomalie-Erkennung',
    fInfo('Erkennt wenn erwartete Routinen ausbleiben und fragt sanft nach. Z.B. "Du gehst normalerweise um 7:30 aus dem Haus — heute nicht. Alles okay?" Nur bei hoher Konfidenz und nie nachts.') +
    fToggle('routine_anomaly.enabled', 'Anomalie-Erkennung aktiv') +
    fRange('routine_anomaly.min_confidence', 'Min. Konfidenz', 0.6, 0.95, 0.05, {0.6:'60%',0.7:'70%',0.8:'80% (Standard)',0.9:'90%',0.95:'95%'}) +
    fRange('routine_anomaly.grace_period_minutes', 'Toleranz (Minuten)', 10, 60, 5, {10:'10',15:'15',20:'20',30:'30 (Standard)',45:'45',60:'60'}) +
    fNum('routine_anomaly.max_daily_checks', 'Max. Nachfragen pro Tag', 1, 5, 1) +
    fNum('routine_anomaly.min_pattern_days', 'Min. Tage fuer Routine', 7, 30, 1)
  ) +
  sectionWrap('&#128736;', 'Proaktiver Sequenz-Planner',
    fInfo('Bei Kontext-Änderungen (Ankunft, Wetterwechsel, Kalender-Event) plant Jarvis automatisch mehrstufige Aktionsketten. Z.B. Ankunft → Licht + Heizung + Musik. Sicherheitsaktionen NIE automatisch.') +
    fToggle('proactive_planner.enabled', 'Sequenz-Planner aktiv') +
    fRange('proactive_planner.min_autonomy_for_auto', 'Min. Autonomie für Auto-Ausführung', 1, 5, 1, {1:'Assistent',2:'Butler',3:'Mitbewohner',4:'Vertrauter',5:'Autopilot'}) +
    fToggle('vacation_simulation.use_learned_patterns', 'Urlaubs-Simulation mit gelernten Mustern') +
    fInfo('Spielt gelernte Verhaltensmuster im Urlaub nach statt zufaelliger Licht-An/Aus-Zyklen.')
  ) +
  sectionWrap('&#127808;', 'Saisonale Intelligenz',
    fInfo('Jarvis lernt jahreszeitlich wiederkehrende Muster: "Letztes Jahr um diese Zeit hast du die Heizung früher eingeschaltet." Vergleicht Verhalten über Jahre und gibt saisonale Tipps.') +
    fToggle('seasonal_insights.enabled', 'Saisonale Intelligenz aktiv') +
    fNum('seasonal_insights.check_interval_hours', 'Prüf-Intervall (Stunden)', 6, 48, 6) +
    fNum('seasonal_insights.min_history_months', 'Min. Historie (Monate)', 1, 12) +
    fToggle('seasonal_insight.hybrid_detection', 'Hybrid-Erkennung (Temp + Tageslicht)') +
    fInfo('Nutzt Temperatur + Tageslichtdauer + Monat statt nur den Kalendermonat fuer praezisere Jahreszeit-Erkennung.') +
    fSubheading('Wetter-Vorhersage') +
    fInfo('Nutzt die HA Wetter-Forecast-API fuer vorausschauende Aktionen: Rolllaeden schliessen bevor Sturm kommt, Heizung hochdrehen bevor es kalt wird.') +
    fToggle('weather_forecast.enabled', 'Wetter-Vorhersage aktiv') +
    fNum('weather_forecast.lookahead_hours', 'Vorhersage-Horizont (Stunden)', 2, 24, 2) +
    fText('weather_forecast.entity', 'Wetter-Entity', 'z.B. weather.home')
  ) +
  // --- Medium Effort Features ---
  '<div class="cat-header">&#9889; Kontext &amp; Vorhersage</div>' +
  sectionWrap('&#128172;', 'Dialogführung',
    fInfo('Echte Gesprächsführung: Jarvis merkt sich besprochene Geräte und Räume und loest Referenzen auf ("Mach es aus" → letztes besprochenes Licht). Klärungsfragen bei Mehrdeutigkeit ("Welches Licht?").') +
    fToggle('dialogue.enabled', 'Dialogführung aktiv') +
    fToggle('dialogue.auto_resolve_references', 'Referenzen automatisch auflösen') +
    fToggle('dialogue.clarification_enabled', 'Klärungsfragen stellen') +
    fNum('dialogue.timeout_seconds', 'Dialog-Timeout (Sek.)', 60, 600, 30) +
    fNum('dialogue.max_clarification_options', 'Max. Optionen bei Klärung', 2, 10) +
    fNum('dialogue.max_references', 'Max. gespeicherte Referenzen', 10, 50, 5) +
    fInfo('Wie viele Geraete/Raeume sich Jarvis im Gespraech merkt. Bei langen Gespraechen gehen fruehere Referenzen sonst verloren.')
  ) +
  sectionWrap('&#127777;', 'Klima-Modell (Digitaler Zwilling)',
    fInfo('Einfaches thermisches Modell für Was-wäre-wenn-Fragen: "Wenn ich das Fenster schliesse, wie warm wird es in 30 Min?" Basiert auf Wärmeverlust, Heizleistung und Fensterzustand.') +
    fToggle('climate_model.enabled', 'Klima-Modell aktiv') +
    fNum('climate_model.max_simulation_minutes', 'Max. Simulationsdauer (Min.)', 30, 480, 30) +
    fSubheading('Thermische Parameter (Global)') +
    fRange('climate_model.default_params.heat_loss_coefficient', 'Wärmeverlust-Koeffizient', 0.005, 0.05, 0.005, {0.005:'Gut isoliert',0.01:'Normal',0.015:'Standard',0.025:'Maessig',0.05:'Schlecht isoliert'}) +
    fRange('climate_model.default_params.heating_power_per_min', 'Heizleistung (Grad/Min)', 0.02, 0.2, 0.01, {0.02:'Schwach',0.05:'Normal',0.08:'Standard',0.12:'Stark',0.2:'Sehr stark'}) +
    fRange('climate_model.default_params.window_open_factor', 'Fenster-Faktor', 1, 10, 1, {1:'Gekippt',3:'Halb offen',5:'Standard',7:'Weit offen',10:'Durchzug'}) +
    fRange('climate_model.default_params.thermal_mass_factor', 'Thermische Masse', 0.5, 2.0, 0.1, {0.5:'Leichtbau',1.0:'Standard',1.5:'Massiv',2.0:'Schwerer Beton'}) +
    fSubheading('Was-Waere-Wenn Energiepreise') +
    fInfo('Preise für Energie-Berechnungen in Was-Waere-Wenn Szenarien (z.B. "Was kostet es wenn ich 2h alle Fenster offen lasse?").') +
    fRange('whatif_simulation.strompreis_kwh', 'Strompreis (€/kWh)', 0.1, 0.6, 0.01, {0.1:'0.10€',0.2:'0.20€',0.3:'0.30€',0.4:'0.40€',0.5:'0.50€',0.6:'0.60€'}) +
    fRange('whatif_simulation.gaspreis_kwh', 'Gaspreis (€/kWh)', 0.03, 0.2, 0.01, {0.03:'0.03€',0.05:'0.05€',0.08:'0.08€',0.1:'0.10€',0.15:'0.15€',0.2:'0.20€'}) +
    fSubheading('Proaktive Was-Waere-Wenn') +
    fToggle('whatif_simulation.proactive_enabled', 'Proaktiv vorschlagen') +
    fInfo('Jarvis bietet aktiv Was-Waere-Wenn-Szenarien an wenn die Konfidenz hoch genug ist.') +
    fRange('whatif_simulation.proactive_min_confidence', 'Min. Konfidenz', 0.5, 0.9, 0.05, {0.5:'50%',0.6:'60%',0.7:'70% (Standard)',0.8:'80%',0.9:'90%'})
  ) +
  sectionWrap('&#128295;', 'Prädiktive Wartung',
    fInfo('Vorhersage von Geräteausfaellen: Batterie-Drain-Rate, Lebensdauer-Tracking, Health-Score pro Geraet. Warnt z.B. "Batterie von Bewegungsmelder Flur in 14 Tagen leer".') +
    fToggle('predictive_maintenance.enabled', 'Prädiktive Wartung aktiv') +
    fNum('predictive_maintenance.lookback_days', 'Analyse-Zeitraum (Tage)', 30, 365, 30) +
    fRange('predictive_maintenance.failure_probability_threshold', 'Warnschwelle', 0.3, 1.0, 0.05, {0.3:'Empfindlich',0.5:'Mittel',0.7:'Standard',0.9:'Nur kritisch'}) +
    fNum('predictive_maintenance.battery_drain_alert_pct_per_week', 'Batterie-Drain Warnung (%/Woche)', 1, 20, 1) +
    fToggle('predictive_maintenance.seasonal_baseline', 'Saisonale Baselines') +
    fInfo('Baselines werden pro Saison getrennt. Verhindert Fehlalarme wenn sich z.B. Heizungsverbrauch zwischen Winter und Sommer unterscheidet.')
  ) +
  // --- Proaktive Intelligenz ---
  '<div class="cat-header">&#129504; Proaktive Intelligenz</div>' +
  sectionWrap('&#9888;', 'Konsequenz-Bewusstsein',
    fInfo('Vor jeder Aktion prüft Jarvis ob sie im aktuellen Kontext sinnvoll ist. Z.B. "Heizung hoch bei offenem Fenster", "Rollladen runter bei Sturm", "Alle Lichter aus obwohl jemand aktiv ist". Blockiert nie — gibt nur Hinweise.') +
    fToggle('consequence_checks.enabled', 'Konsequenz-Checks aktiv')
  ) +
  sectionWrap('&#128065;', 'Unaufgeforderte Beobachtungen',
    fInfo('Jarvis prüft periodisch den Haus-Zustand und teilt relevante Beobachtungen mit: Licht brennt in leerem Raum, Fenster offen bei Heizung, Alarm seit Tagen nicht aktiviert, Batterie-Warnungen.') +
    fToggle('observation_loop.enabled', 'Beobachtungen aktiv') +
    fNum('observation_loop.interval_hours', 'Prüf-Intervall (Stunden)', 1, 12) +
    fNum('observation_loop.max_daily', 'Max. Beobachtungen pro Tag', 1, 5) +
    fToggle('wellness.suppress_when_away', 'Wellness-Hinweise bei Abwesenheit unterdruecken')
  ) +
  // --- Fortgeschrittene Intelligenz ---
  '<div class="cat-header">&#129504; Fortgeschrittene Intelligenz</div>' +
  sectionWrap('&#129504;', 'Background Reasoning',
    fInfo('Wenn niemand mit Jarvis spricht, analysiert er im Hintergrund den Haus-Status mit dem Smart-Modell. Insights werden beim nächsten User-Kontakt beiläufig eingewoben. GPU-Contention-Guard: Analyse wird übersprungen wenn ein User-Request aktiv ist.') +
    fToggle('background_reasoning.enabled', 'Background Reasoning aktiv') +
    fNum('background_reasoning.idle_minutes', 'Idle-Zeit (Minuten)', 2, 30) +
    fNum('background_reasoning.cooldown_minutes', 'Cooldown (Minuten)', 10, 120, 10)
  ) +
  sectionWrap('&#127793;', 'Abstrakte Konzepte (Dynamic Skills)',
    fInfo('Lernt zusammengehoerige Aktionen als abstrakte Konzepte: "Feierabend" = Licht dimmen + Musik an + Heizung hoch. Erkennt Kern-Aktionen (>50% Haeufigkeit) und schlaegt das Konzept nach N Beobachtungen vor.') +
    fToggle('dynamic_skills.enabled', 'Abstrakte Konzepte aktiv') +
    fNum('dynamic_skills.min_observations', 'Min. Beobachtungen', 2, 10)
  ) +
  sectionWrap('&#128270;', 'Semantic History Search',
    fInfo('Neues Tool für Jarvis: Durchsucht vergangene Gespraeche per Keyword-Suche. Frag z.B. "Was habe ich gestern über das Licht gesagt?" oder "Wann haben wir über die Heizung geredet?"') +
    fToggle('semantic_history_search.enabled', 'History-Suche aktiv')
  ) +
  sectionWrap('&#128295;', 'Automation-Debugging',
    fInfo('Neues Tool: Jarvis analysiert HA-Automatisierungen auf Probleme. Zeigt Status, Trigger, letzte Ausführung und erkennt Automatisierungen die aktiv aber lange nicht ausgeloest wurden. Frag z.B. "Warum hat die Nachtlicht-Automation nicht funktioniert?"') +
    fToggle('automation_debugging.enabled', 'Automation-Debugging aktiv')
  );
}

// ── Haupt-Render ─────────────────────────────────────────────
function renderDeclarativeTools() {
  return sectionWrap('&#128736;', 'Analyse-Tools',
    '<div class="form-group"><div class="toggle-group"><label>Analyse-Tools aktiviert</label>' +
    '<label class="toggle"><input type="checkbox" id="declEnabledToggle" onchange="toggleDeclEnabled()" checked>' +
    '<span class="toggle-track"></span><span class="toggle-thumb"></span></label></div></div>' +
    '<div class="form-group"><div class="toggle-group"><label>Proaktive Nutzung (Jarvis erwähnt Ergebnisse spontan)</label>' +
    '<label class="toggle"><input type="checkbox" id="declSpontaneousToggle" onchange="toggleDeclSpontaneous()" checked>' +
    '<span class="toggle-track"></span><span class="toggle-thumb"></span></label></div></div>' +
    '<div class="form-group"><label>Maximale Anzahl Tools</label>' +
    '<div class="range-group"><input type="range" id="declMaxToolsSlider" min="10" max="250" step="10" value="20" onchange="updateDeclMaxTools(this.value)" oninput="document.getElementById(\'declMaxToolsVal\').textContent=this.value">' +
    '<span class="range-value" id="declMaxToolsVal">20</span></div></div>' +
    fInfo('Deklarative Tools führen vordefinierte Berechnungen auf Home-Assistant-Daten aus (nur Lese-Zugriff).' + helpBtn('decl_tools.overview'))
  ) +
  '<div id="declBody">' +
  sectionWrap('&#128202;', 'Aktive Tools',
    '<div id="declToolList" style="margin-top:12px;"><div style="padding:16px;color:var(--text-secondary);">Lade...</div></div>'
  ) +
  sectionWrap('&#128161;', 'Jarvis-Vorschläge',
    fInfo('Jarvis analysiert deine Home-Assistant-Entities und schlägt passende Analyse-Tools vor. Du entscheidest bei jedem Vorschlag ob du ihn annimmst oder ablehnst.') +
    '<div style="margin-top:12px;margin-bottom:12px;">' +
    '<button class="btn btn-primary" id="declSuggestBtn" onclick="generateDeclSuggestions()" style="padding:8px 20px;">&#128161; Vorschläge generieren</button>' +
    '</div>' +
    '<div id="declSuggestionsList"><div style="padding:16px;color:var(--text-secondary);font-style:italic;">Klicke "Vorschläge generieren" um Jarvis deine Entities analysieren zu lassen.</div></div>'
  ) +
  sectionWrap('&#128220;', 'Vorlagen',
    fInfo('Vorgefertigte Vorlagen — ein Klick befuellt das Formular. Entity-IDs danach an dein System anpassen.') +
    '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;">' +
    DECL_PRESETS.map(function(p, i) {
      var ti = DECL_TOOL_TYPES.find(function(t) { return t.v === p.type; }) || {l:p.type};
      return '<button class="btn btn-sm" onclick="loadDeclPreset(' + i + ')" style="padding:6px 12px;font-size:12px;text-align:left;">' +
        '<span style="color:var(--accent);">' + esc(ti.l) + '</span><br>' +
        '<span style="font-size:11px;">' + esc(p.desc) + '</span></button>';
    }).join('') +
    '</div>'
  ) +
  '<div id="declFormSection">' +
  sectionWrap('&#10010;', 'Neues Tool erstellen',
    '<div class="form-group"><label>Name' + helpBtn('decl_tools.overview') + '</label>' +
    '<input type="text" id="declNewName" placeholder="z.B. stromvergleich, raumtemperaturen" oninput="_clearDeclValidation()">' +
    '<div class="hint">Nur Buchstaben, Zahlen, _ und - erlaubt</div></div>' +
    '<div class="form-group"><label>Beschreibung</label>' +
    '<input type="text" id="declNewDesc" placeholder="Was macht dieses Tool?" oninput="_clearDeclValidation()"></div>' +
    '<div class="form-group"><label>Typ' + helpBtn('decl_tools.type') + '</label><select id="declNewType" onchange="onDeclTypeChange()">' +
    '<option value="">-- Typ wählen --</option>' +
    DECL_TOOL_TYPES.map(function(t) { return '<option value="' + t.v + '">' + t.l + ' — ' + t.desc + '</option>'; }).join('') +
    '</select></div>' +
    '<div id="declConfigFields" style="margin-top:12px;"></div>' +
    '<div id="declValidation" style="display:none;margin-top:8px;padding:10px;background:rgba(255,61,61,0.05);border:1px solid rgba(255,61,61,0.2);border-radius:var(--radius-sm);"></div>' +
    '<div style="display:flex;gap:8px;margin-top:16px;">' +
    '<button class="btn btn-primary" id="declSubmitBtn" onclick="createDeclTool()">&#10010; Tool erstellen</button>' +
    '<button class="btn btn-secondary" id="declCancelBtn" onclick="cancelDeclEdit()" style="display:none;">Abbrechen</button>' +
    '</div>'
  ) + '</div>' +
  sectionWrap('&#128214;', 'Tipps',
    fInfo('Du kannst Jarvis auch bitten: "Jarvis, bau mir ein Tool das die Raumtemperaturen vergleicht" — er nutzt dann create_declarative_tool automatisch.') +
    '<div style="font-size:12px;color:var(--text-secondary);margin-top:8px;">' +
    '<strong>Verfügbare Typen:</strong><br>' +
    DECL_TOOL_TYPES.map(function(t) { return '<span style="color:var(--accent);">' + t.l + '</span> — ' + t.desc; }).join('<br>') +
    '</div>'
  ) +
  '</div>'; // Ende declBody
}

// Phase 9B: Jarvis Insights Widget
(function() {
  function loadInsights() {
    fetch('/api/jarvis/insights').then(function(r) { return r.json(); }).then(function(data) {
      var list = document.getElementById('insights-list');
      if (!list || !data.insights) return;
      if (data.insights.length === 0) { list.innerHTML = '<em>Keine aktuellen Beobachtungen</em>'; return; }
      list.innerHTML = data.insights.map(function(i) { return '<div style="margin:4px 0">\u2022 ' + (i.text || '') + '</div>'; }).join('');
    }).catch(function() {});
  }
  if (document.getElementById('insights-list')) { loadInsights(); setInterval(loadInsights, 30000); }
})();

// Phase 9C: Autonomie & Lernfortschritt
(function() {
  function loadProgress() {
    fetch('/api/jarvis/learning-progress').then(function(r) { return r.json(); }).then(function(data) {
      var el = document.getElementById('learning-progress');
      if (!el) return;
      el.innerHTML = '<strong>Patterns:</strong> ' + (data.patterns_learned || 0) +
        ' | <strong>Korrekturen:</strong> ' + (data.corrections_applied || 0) +
        ' | <strong>Features:</strong> ' + (data.active_features || []).length;
    }).catch(function() {});
  }
  fetch('/api/jarvis/status').then(function(r) { return r.json(); }).then(function(data) {
    var el = document.getElementById('autonomy-level');
    if (el) el.textContent = 'Autonomie: Level ' + (data.autonomy_level || 2) + '/5';
  }).catch(function() {});
  if (document.getElementById('learning-progress')) { loadProgress(); setInterval(loadProgress, 60000); }
})();
