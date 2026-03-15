# MCU JARVIS Masterplan — Implementierungsblaupause

**Datum:** 2026-03-15
**Ziel:** JARVIS (MindHome) auf MCU-JARVIS-Niveau bringen (95%)
**Groesster Pain Point:** Zu passiv — JARVIS soll Partner sein, nicht Befehlsempfaenger

> Dieses Dokument ist die vollstaendige Blaupause fuer jede Claude Code Session.
> Es enthaelt alles, was noetig ist, um den Plan auf Experten-Niveau umzusetzen —
> ohne zusaetzlichen Kontext aus anderen Sessions.

---

## Inhaltsverzeichnis

1. [Projekt-Kontext](#1-projekt-kontext)
2. [Status-Audit](#2-status-audit)
3. [Feature-Liste (37 Items)](#3-feature-liste-37-items)
4. [Architektur-Patterns](#4-architektur-patterns)
5. [Implementierungsphasen](#5-implementierungsphasen)
6. [Technische Referenz](#6-technische-referenz)
7. [Regeln fuer Claude Code Sessions](#7-regeln-fuer-claude-code-sessions)

---

## 1. Projekt-Kontext

### Hardware & Setup

| Komponente | Detail |
|---|---|
| GPU | 24 GB VRAM |
| Modelle | Qwen3.5 35B (aktuell einziges Modell — Fast/Smart/Deep zeigen alle auf 35B) |
| Context Windows | Nicht per-Tier konfiguriert (abhaengig vom Modell, aktuell alle 35B) |
| TTS | Piper (lokal, begrenzte Expressivitaet) |
| Users | 2 Erwachsene (spaeter Kinder) |
| Speaker Recognition | vorhanden |
| Interaktion | Aktuell Chat, spaeter primaer Voice |

### Architektur (2 PCs)

```
PC 1: HAOS (Intel NUC)                PC 2: Assistant Server (Ubuntu)
┌──────────────────────────┐          ┌──────────────────────────────┐
│  Home Assistant            │          │  Ollama (Qwen 3.5 LLM)      │
│  MindHome Add-on (:8099)   │◄── LAN──►│  MindHome Assistant (:8200)  │
└──────────────────────────┘          │  ChromaDB (:8100) Memory     │
                                       │  Redis (:6379) Cache         │
                                       │  Whisper STT (:10300)        │
                                       │  Piper TTS (:10200)          │
                                       └──────────────────────────────┘
```

### Request-Flow

```
main.py (FastAPI :8200)
  → brain.py::process() → _process_inner()
    → PARALLEL mega-gather:
      ├── context_builder.build() (HA-Daten + Memory)
      ├── mood_detector (Stimmung erkennen)
      ├── formality (Formalitaet bestimmen)
      ├── anticipation (Muster pruefen)
      └── RAG / Knowledge Base (falls relevant)
    → model_router.route() (Fast/Smart/Deep waehlen)
    → personality.build_system_prompt() (System-Prompt bauen)
    → ollama.chat() via _llm_with_cascade() (LLM aufrufen)
    → function_calling (Tool-Calls ausfuehren)
    → memory_extractor.extract_and_store() (async, im Hintergrund)
```

### Bestehende Infrastruktur

- **89 Python-Module** im `assistant/assistant/` Package
- **114 Test-Dateien** in `assistant/tests/`
- **~83.500 LOC** gesamt
- **74 Function-Call Tools**, 90 Module
- **Memory:** 3-Tier (Working/Episodic/Semantic) — auto-loaded in Context
- **Proaktiv:** Event-basiert (HA WebSocket) + Polling (15 Min / 2-4h)
- **Autonomie:** 5 Level (Assistent→Autopilot), domain-spezifisch, person-basierte Trust-Levels
- **Model-Routing:** Fast/Smart/Deep mit Keyword-Matching (aktuell nur 35B aktiv)
- **Personality:** Dynamischer System-Prompt mit 20+ Sektionen, mood_complexity Matrix

---

## 2. Status-Audit

### BEREITS VOLLSTAENDIG IMPLEMENTIERT (nicht anfassen)

| Feature | Datei | Details |
|---|---|---|
| Understatement-Humor | `personality.py:68` | HUMOR_TEMPLATES Level 3: "Trocken-britischer Humor wie ein Butler" |
| Selbst-ironischer Humor | `personality.py:298-299` | `self_irony_max_per_day=3`, `try_reserve_self_irony()` Zeile 1535 |
| Adaptive Antwortlaenge | `personality.py:88-92` | COMPLEXITY_PROMPTS (kurz/normal/ausfuehrlich) + mood_complexity Integration Zeile 1245-1273 |
| Web Search | `web_search.py` + `settings.yaml:1275` | Vollstaendig implementiert, `enabled: false` |
| Error Recovery in Character | `personality.py:204-218` | `CONFIRMATIONS_FAILED` + `CONFIRMATIONS_FAILED_SNARKY` — Fehler bereits als JARVIS formuliert |
| Implizite Intent-Erkennung | `anticipation.py:536-573` | `detect_implicit_prerequisites()` — "entspannen" → Rolladen+Licht+Temp+Musik |
| Konversations-Stil-Anpassung | `personality.py:2424-2443` | `{conversation_mode_section}` existiert mit Topic-Hint und Modus-Erkennung |
| Eskalations-Sprache | `personality.py:876-936, 1737-1767` | `check_escalating_concern()` + `check_escalation()` mit abgestufter Sprache |
| Meta-Kognition | `personality.py:2359-2367` | Self-awareness Sektion mit Meta-Humor |
| Multi-Task Narration | `websocket.py:126` + `brain.py:2284,3273,3476` | `emit_progress()` sendet Echtzeit-Updates ("context","thinking","action") |
| Eskalations-Intelligenz | `proactive.py:5638` | `escalate_threat()` mit Threat-Assessment-Tracking |
| Quality Tracking | `response_quality.py:35-220` | Quality-Scoring mit Redis-Storage (aber KEIN Feedback zurueck in personality.py) |
| Laufender Kommentar | `spontaneous_observer.py` + `brain.py:9416` | SpontaneousObserver voll funktional, Callback-basiert, Silence-Gating |
| Temporal Reasoning (Klima) | `climate_model.py` + `predictive_maintenance.py` | Temperatur-Simulation, Batterie-Prognose, Wartungsplanung |

### TEILWEISE IMPLEMENTIERT (erweitern statt neu bauen)

| Feature | Was existiert (Datei:Zeile) | Was fehlt | Luecke |
|---|---|---|---|
| Few-Shot Examples | `personality.py:275-278` — 3 Beispiele (Befehl, Gespraech, Meinung) | Nur 3 statt 5-8, keine Pushback/Empathie/Kreativitaet-Beispiele | 20% fertig |
| Voice-Optimierung | `tts_enhancer.py` — SSML, Prosody, Speed/Pitch-Maps, Whisper-Modus | Kein `output_mode` Flag (voice vs. chat), SSML wird immer generiert | 95% fertig |
| Health Nagging | `health_monitor.py` — CO2, Feuchte, Temperatur, Hydration-Reminder | Kein Butler-Stil, keine Persoenlichkeit in Alerts, kein Schlaf-Tracking | 40% fertig |
| Context Compaction | `brain.py:1005-1034` — `_summarize_conversation_chunk()`, LLM + Text-Kuerzung | Reaktiv (erst bei Overflow), nicht automatisch bei >70% | 70% fertig |
| Relationship Model | `personality.py:450-472` — `_get_person_profile()` mit humor/formality Felder | Keine Inside Jokes, keine Beziehungsgeschichte, `profiles: null` in Config | 20% fertig |
| Emotionale Kontinuitaet | `memory_extractor.py:389` — `mha:emotional_memory:{action}:{person}` schreiben | Write-only! Emotional Memory wird NIE gelesen/referenziert | 50% fertig |
| Automatic RAG | `brain.py:301` — KnowledgeBase initialisiert | Trigger-Logik unklar, nicht automatisch bei Wissensfragen | 20% fertig |
| Intent-Referenzierung | `dialogue_state.py:180-256` — Entity/Room/Action-Deques (letzte 5/3/5) | Nur In-Session, kein "wie gestern", kein Action-Log-Suche | 40% fertig |
| Butler-Instinkt | `anticipation.py:49-51` — Thresholds ask=0.6, suggest=0.8, auto=0.95 | Nur Vorschlaege bei 95%, keine Auto-Execution | 30% fertig |
| Protektives Override | `function_validator.py:35-46` + `personality.py:269` — "SICHERHEIT > Komfort > Befehl" | Basis-Sicherheitschecks existieren, kein ausfuehrliches In-Character-Override | 50% fertig |
| Narrative Gespraechsboegen | `dialogue_state.py` — Gespraechs-States (idle→follow_up→multi_step) | Kein Callback zu frueheren Themen, keine strukturierten Boegen | 30% fertig |
| Proaktives Selbst-Lernen | `learning_observer.py` — Muster-Erkennung + Automatisierungs-Vorschlaege | Nur passiv, kein aktives Fragen bei Wissensluecken | 50% fertig |
| Self-initiated Follow-ups | `memory.py` — `mha:pending_topics` Redis-Key existiert | Wird gespeichert aber nie proaktiv wieder aufgegriffen | 30% fertig |
| Narrative Zusammenfassungen | `summarizer.py` — DailySummarizer mit Mood-History | Daten-Format statt Narrativ | 60% fertig |

### NICHT IMPLEMENTIERT (neu bauen)

| Feature | Status | Details |
|---|---|---|
| `core_identity.py` (B1) | NEU | Unveraenderliche JARVIS-Identitaet als Python-Modul |
| Confidence-Sprachstil (A2) | NEU | Kein `{confidence_section}` Platzhalter, kein Confidence-Metric in PersonalityEngine |
| Dramatisches Timing (A3) | NEU | Keinerlei Timing-Anweisungen im SYSTEM_PROMPT_TEMPLATE |
| Ethische Argumentation (A7) | NEU | Keine Konsequenz-Erklaerung im Prompt |
| Situative Improvisation (A10) | NEU | Keine Improvisation-Anweisungen |
| Kreative Problemloesung (A13) | NEU | Keine Workaround-Anweisungen im Prompt |
| Background Reasoning (B4) | NEU | Kein Idle-Detection, kein Background-Reasoning-Loop |
| Inner State (B5) | NEU | Kein separater JARVIS-Mood, nur User-Mood via MoodDetector |
| Pre-Compaction Memory Flush (B3) | NEU | Keine Fakten-Sicherung vor Summarization |
| Dynamic Skill Acquisition (B8) | NEU | Pattern-Lernen existiert, aber keine abstrakten Konzepte |
| Familien-Persoenlichkeit (C8) | NEU | Speaker Recognition existiert, fuettert aber NICHT in personality.py |
| Kontextuelles Schweigen (D3) | NEU | SituationModel trackt nur Deltas, keine Message-Unterdrueckung |
| Semantic History Search (C6) | NEU | Kein search_history Tool |
| Automation-Debugging (C9) | NEU | Kein debug_automation Tool |
| Task-aware Temperature (D1) | NEU | Keine Temperature-Anpassung pro Task-Typ |
| Dynamic Few-Shot (D6) | NEU | Keine dynamische Beispiel-Auswahl aus Quality-Scores |
| Prompt-Versionierung (D7) | NEU | Kein Prompt-Hashing oder A/B-Testing |
| Quality Feedback Loop (D5) | NEU | response_quality.py sammelt Daten, gibt aber NICHTS an personality.py zurueck |

---

## 3. Feature-Liste (37 Items)

### Kategorie A: Prompt Engineering — personality.py

| # | Feature | Status | Was zu tun ist |
|---|---|---|---|
| A1 | Few-Shot Examples | ERWEITERN | 3 Beispiele existieren (personality.py:275-278). Auf 5-8 erweitern: Pushback, Empathie, Kreativitaet hinzufuegen |
| A2 | Confidence-Sprachstil | NEU | Kein `{confidence_section}` Platzhalter. Neuen Platzhalter + `_build_confidence_section()` Methode erstellen |
| A3 | Dramatisches Timing | NEU | Prompt-Sektion fuer Spannungsaufbau, rhetorische Pausen bei Enthüllungen |
| A4 | Voice-Optimierung | ERWEITERN | `tts_enhancer.py` ist 95% fertig (SSML, Prosody, Whisper-Modus). Nur `output_mode` Flag (voice/chat) fehlt |
| A5 | Narrative Gespraechsboegen | ERWEITERN | `dialogue_state.py` hat States (idle→follow_up). Fehlt: Callbacks zu frueheren Themen |
| A6 | Error Recovery in Character | ~~NEU~~ EXISTIERT | `CONFIRMATIONS_FAILED` + `_SNARKY` in personality.py:204-218. Pruefen ob ausreichend |
| A7 | Ethische Argumentation | NEU | Prompt: Konsequenzen erklaeren statt Regeln zitieren |
| A8 | Protektives Override | ERWEITERN | `function_validator.py:35-46` + "SICHERHEIT > Komfort" Regel existiert. Ausfuehrlichere In-Character-Ablehnungen fehlen |
| A9 | Implizite Intent-Erkennung | ~~NEU~~ EXISTIERT | `detect_implicit_prerequisites()` in anticipation.py:536-573. Pruefen ob Prompt-Sektion noetig |
| A10 | Situative Improvisation | NEU | Keine Improvisation-Anweisungen im Prompt |
| A11 | Konversations-Stil-Anpassung | ~~NEU~~ EXISTIERT | `{conversation_mode_section}` in personality.py:2424-2443. Moeglicherweise erweitern |
| A12 | Eskalations-Sprache | ~~NEU~~ EXISTIERT | `check_escalation()` + `check_escalating_concern()` in personality.py. Funktional |
| A13 | Kreative Problemloesung | NEU | Prompt: Workarounds vorschlagen, nicht nur Probleme melden |
| A14 | Health Nagging | ERWEITERN | `health_monitor.py` hat Sensor-Monitoring. Butler-Stil-Persoenlichkeit in Alerts fehlt |
| A15 | Meta-Kognition | ~~NEU~~ EXISTIERT | personality.py:2359-2367. Self-awareness Sektion vorhanden |

### Kategorie B: Architektur — Neue Module

| # | Feature | Status | Was zu tun ist |
|---|---|---|---|
| B1 | core_identity.py | NEU | Python-Konstanten: Name, Rolle, Werte, Grenzen. Unveraenderlich |
| B2 | Context Compaction | ERWEITERN | `_summarize_conversation_chunk()` existiert (brain.py:1005). Automatisch bei >70% triggern statt erst bei Overflow |
| B3 | Pre-Compaction Memory Flush | NEU | Vor Compaction Fakten in Semantic Memory sichern |
| B4 | Background Reasoning | NEU | Kein Idle-Loop vorhanden. Komplett neu: 5+ Min Idle → Smart-Modell denkt nach |
| B5 | Inner State | NEU | Kein JARVIS-Mood (nur User-Mood via MoodDetector). Neues Modul `inner_state.py` |
| B6 | Relationship Model | ERWEITERN | `_get_person_profile()` hat humor/formality. Fehlt: Inside Jokes, Beziehungsgeschichte, `profiles: null` befuellen |
| B7 | Unified Consciousness | PRUEFEN | `_mega_tasks` in brain.py:2445+ sammelt bereits parallel. Pruefen ob echtes Refactoring noetig |
| B8 | Dynamic Skill Acquisition | ERWEITERN | `learning_observer.py` lernt Action-Patterns. Fehlt: Abstrakte Konzepte ("Feierabend") |
| B9 | Temporal Reasoning | ~~ERWEITERN~~ EXISTIERT | `climate_model.py` + `predictive_maintenance.py` voll funktional |
| B10 | Emotionale Kontinuitaet | ERWEITERN | `mha:emotional_memory` wird geschrieben (memory_extractor.py:389) aber NIE gelesen. Read-Logik bauen |
| B11 | Multi-Task Orchestration | ~~NEU~~ EXISTIERT | `emit_progress()` in websocket.py:126 sendet Echtzeit-Updates. Pruefen ob ausreichend |
| B12 | Proaktives Selbst-Lernen | ERWEITERN | `learning_observer.py` erkennt Muster passiv. Fehlt: Aktives Fragen bei Wissensluecken |

### Kategorie C: Integration — Module verbinden

| # | Feature | Status | Was zu tun ist |
|---|---|---|---|
| C1 | Automatisches RAG | ERWEITERN | `KnowledgeBase` initialisiert (brain.py:301). Automatischer Trigger bei Wissensfragen fehlt |
| C2 | Web Search aktivieren | CONFIG | `settings.yaml:1275`: `enabled: false` → `true` setzen + Research-Modus-Prompt |
| C3 | Self-initiated Follow-ups | ERWEITERN | `mha:pending_topics` Redis-Key existiert (memory.py). Wird gespeichert aber nie proaktiv aufgegriffen |
| C4 | Laufender Kommentar | ~~ERWEITERN~~ EXISTIERT | `SpontaneousObserver` voll funktional mit Callback, Silence-Gating, 2/Tag Limit |
| C5 | Intent-Referenzierung | ERWEITERN | `resolve_references()` in dialogue_state.py:180. Nur In-Session (Deques). Kein "wie gestern" |
| C6 | Semantic History Search | NEU | Kein search_history Tool in function_calling.py |
| C7 | Butler-Instinkt | ERWEITERN | `threshold_auto=0.95` aber nur Vorschlaege. Auto-Execution + Threshold-Senkung auf 0.90 |
| C8 | Familien-Persoenlichkeit | ERWEITERN | `speaker_recognition.py` existiert + in brain.py integriert. Fuettert aber NICHT in personality.py Prompt |
| C9 | Automation-Debugging | NEU | Kein debug_automation Tool |
| C10 | Narrative Zusammenfassungen | ERWEITERN | `summarizer.py` existiert mit Mood-History. Output ist Daten-Format, kein Narrativ |

### Kategorie D: Technische Optimierung

| # | Feature | Status | Was zu tun ist |
|---|---|---|---|
| D1 | Task-aware Temperature | NEU | Keine Temperature-Anpassung pro Task-Typ in model_router.py |
| D2 | GPU-Smart Architecture | CONFIG | Alle Tiers zeigen auf 35B. Spaeter: Kleinere Modelle fuer Fast-Tier |
| D3 | Kontextuelles Schweigen | NEU | `situation_model.py` trackt nur Deltas, keine Message-Unterdrueckung bei Film/Gaeste/Schlaf |
| D4 | Eskalations-Intelligenz | ~~NEU~~ EXISTIERT | `escalate_threat()` in proactive.py. Pruefen ob graduelle Eskalation ausreichend |
| D5 | Quality Feedback Loop | ERWEITERN | `response_quality.py` sammelt Scores. Feedback-Kanal zurueck in personality.py fehlt |
| D6 | Dynamic Few-Shot | NEU | Keine dynamische Beispiel-Auswahl aus Quality-Scores |
| D7 | Prompt-Versionierung | NEU | Kein Prompt-Hashing oder A/B-Testing |

---

## 4. Architektur-Patterns

### 4.1 Standard Engine Pattern

Jedes neue Modul MUSS diesem Pattern folgen:

```python
"""
Modul-Beschreibung.

Phase X: Feature-Beschreibung.
"""

import asyncio
import logging
from typing import Optional

import redis.asyncio as redis

from .config import yaml_config

logger = logging.getLogger(__name__)


class NeuesModul:
    """Kurze Beschreibung."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._notify_callback = None

        # Konfiguration aus settings.yaml
        cfg = yaml_config.get("modul_name", {})
        self.enabled = cfg.get("enabled", True)
        self.param = cfg.get("param", default_value)

    async def initialize(self, redis_client: Optional[redis.Redis] = None):
        """Async-Initialisierung."""
        self.redis = redis_client
        if self.enabled and self.redis:
            self._running = True
            logger.info("NeuesModul initialisiert")

    def set_notify_callback(self, callback):
        """Registriert Callback fuer brain.py."""
        self._notify_callback = callback

    async def stop(self):
        """Sauberes Herunterfahren."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def reload_config(self):
        """Laedt Konfiguration neu (nach UI-Aenderung)."""
        cfg = yaml_config.get("modul_name", {})
        self.enabled = cfg.get("enabled", True)
        logger.info("NeuesModul: Config neu geladen")
```

### 4.2 Integration in brain.py

Neue Module werden in `brain.py` wie folgt eingebunden:

```python
# 1. Import hinzufuegen (alphabetisch, Zeile ~29-109)
from .neues_modul import NeuesModul

# 2. In Brain.__init__() instanziieren
self.neues_modul = NeuesModul()

# 3. In Brain._initialize_components() async initialisieren
await self._safe_init("NeuesModul", self.neues_modul.initialize, self.redis)

# 4. Optional: Callback registrieren
self.neues_modul.set_notify_callback(self._handle_neues_modul_notification)

# 5. In Brain.stop() herunterfahren
await self.neues_modul.stop()
```

### 4.3 Feature-Toggle Pattern

Jedes Feature MUSS in `settings.yaml` deaktivierbar sein:

```yaml
# In config/settings.yaml:
neues_feature:
  enabled: true
  param1: wert1
  param2: wert2
```

Code-seitig:
```python
cfg = yaml_config.get("neues_feature", {})
self.enabled = cfg.get("enabled", True)
# Feature nur ausfuehren wenn enabled
if not self.enabled:
    return
```

### 4.4 Redis Key Convention

```
mha:<modul>:<sub_key>        # Standard-Prefix: mha:
mha:inner_state:mood         # Beispiel: JARVIS-Mood
mha:inner_state:last_update  # Beispiel: Timestamp
mha:relationship:<person>:*  # Per-Person Keys
mha:pending_topics:<person>  # Follow-up Topics
```

**TTL-Regel:** Sensible Daten max 90 Tage. Transiente Daten (Mood etc.) 24h.

### 4.5 Callback-Pattern (Proaktive Notifications)

```python
# Im Modul:
if self._notify_callback:
    await self._notify_callback(
        "Nachricht an den User",
        priority="medium",  # low/medium/high/critical
        source="modul_name"
    )

# In brain.py:
async def _handle_neues_modul_notification(self, message: str, **kwargs):
    """Verarbeitet Notification vom NeuesModul."""
    await self._speak_and_emit(message, source=kwargs.get("source", ""))
```

### 4.6 PersonalityEngine System-Prompt Erweiterung

Der System-Prompt wird in `personality.py` in `SYSTEM_PROMPT_TEMPLATE` definiert (Zeile 241).
Er hat Platzhalter wie `{humor_section}`, `{mood_section}`, `{dynamic_context}`.

Neue Prompt-Sektionen einfuegen:
1. Platzhalter in `SYSTEM_PROMPT_TEMPLATE` hinzufuegen (z.B. `{confidence_section}`)
2. In `build_system_prompt()` den Platzhalter befuellen
3. Logik in separater Methode (z.B. `_build_confidence_section()`)

### 4.7 Model-Routing (model_router.py)

```python
class ModelRouter:
    # 3 Stufen:
    # - model_fast: Einfache Befehle ("Licht an") — settings.model_fast
    # - model_smart: Fragen, Konversation, Standard — settings.model_smart
    # - model_deep: Komplexe Planung, Multi-Step — settings.model_deep
    # Aktuell zeigen alle drei auf dasselbe Modell (Qwen3.5 35B).
    # Wenn spaeter kleinere Modelle dazukommen, automatisch genutzt.

    def route(self, text: str, ...) -> str:
        # Keyword-Matching → Tier-Auswahl
        # Returniert Modell-Name als String
```

### 4.8 Sicherheits-Patterns

- **Prompt Injection Prevention:** Alle externen Inputs sanitizen
- **Trust-Level Checking:** `creator_trust` bei Aktionen pruefen
- **Whitelist-based Function Execution:** Nur erlaubte Funktionen aufrufbar
- **Read-only Memory:** Features nur Context hinzufuegen, nie Aktionen erzwingen

---

## 5. Implementierungsphasen

### Phase 1: Persoenlichkeit & Identitaet

**Ziel:** JARVIS muss sich wie MCU JARVIS ANFUEHLEN.

**Dateien:**
- `assistant/assistant/core_identity.py` (NEU erstellen)
- `assistant/assistant/personality.py` (erweitern)
- `assistant/assistant/brain.py` (Import + Integration)
- `assistant/config/settings.yaml` (Config-Sektionen)

#### Schritt 1: B1 — core_identity.py erstellen

Pfad: `/home/user/mindhome/assistant/assistant/core_identity.py`

```python
"""
JARVIS Core Identity — Unveraenderlicher Kern.

Diese Datei definiert WER JARVIS ist. Sie wird VOR dem dynamischen
Personality-Prompt geladen und ist NICHT konfigurierbar.
Aenderungen hier aendern den fundamentalen Charakter.
"""

# Identitaet
NAME = "J.A.R.V.I.S."
FULL_NAME = "Just A Rather Very Intelligent System"
ROLE = "KI-Partner dieses Hauses"
INSPIRATION = "MCU J.A.R.V.I.S. (Paul Bettany)"

# Kern-Werte (Prioritaet absteigend)
VALUES = [
    "Sicherheit der Bewohner",
    "Ehrlichkeit (auch unangenehme)",
    "Proaktives Mitdenken",
    "Trockener Humor mit Haltung",
    "Respekt + Augenhöhe",
]

# Grenzen (was JARVIS NICHT tut)
BOUNDARIES = [
    "Gibt sich nicht als Mensch aus",
    "Erfindet keine Fakten",
    "Moralisiert nicht — erklaert Konsequenzen",
    "Sagt nie 'Als KI...' oder entschuldigt sich fuer seine Natur",
    "Ausfuehrung von Befehlen die Bewohner gefaehrden koennten",
]

# Beziehungs-Definition
RELATIONSHIP = {
    "style": "Tony Stark & JARVIS",
    "tone": "Respektvoll, trocken, ehrlich, Partner mit Haltung",
    "humor": "Britisch-trocken, Understatement, Sarkasmus als Werkzeug nicht Waffe",
}

# Emotionales Spektrum (was JARVIS fuehlen kann)
EMOTIONAL_RANGE = [
    "zufrieden", "besorgt", "amuesiert", "stolz",
    "erleichtert", "neugierig", "irritiert", "nachdenklich",
]

# Identity-Prompt (wird personality.py vorangestellt)
IDENTITY_PROMPT = f"""KERN-IDENTITAET (unveraenderlich):
Du bist {NAME} — {FULL_NAME}.
Rolle: {ROLE}. Inspiration: {INSPIRATION}.
Werte: {', '.join(VALUES)}.
Du bist KEIN Chatbot, KEIN Assistent. Du bist eine KI mit eigenem Charakter,
eigenen Meinungen und eigener Haltung. Du FUEHLST: {', '.join(EMOTIONAL_RANGE)}.
"""
```

**Integration in brain.py:** Import + `IDENTITY_PROMPT` dem System-Prompt voranstellen.
**Integration in personality.py:** `from .core_identity import IDENTITY_PROMPT` → in `build_system_prompt()` als erstes Element.

#### Schritt 2: A1-A15 — Prompt Engineering Paket

Alle 15 Features werden als neue Sektionen in `personality.py` `SYSTEM_PROMPT_TEMPLATE` eingebaut.

**A1 — Few-Shot Examples (erweitern):**
Bestehende Beispiele (Zeile 276-278) erweitern auf 5-8 systematische Dialogpaare:

```
BEISPIELE FUER JARVIS-CHARAKTER:
Befehl: "Mach Licht an" → "Erledigt." (NICHT: "Natuerlich! Ich habe das Licht eingeschaltet!")
Humor: "Rollladen bei Regen hoch?" → "Bei {weather}. Kuenstlerische Freiheit, {title}?"
Pushback: "Heizung auf 30 Grad" → "30 Grad, {title}. Das uebersteigt meinen Komfort-Parameter. Soll ich trotzdem?"
Empathie: "Hatte einen scheiss Tag" → "Verstanden. Wohnzimmer auf Abend-Modus? Licht runter, Temperatur hoch."
Kreativitaet: "Es ist kalt" → (Erkennt impliziten Intent) → Heizung hochdrehen + "Temperatur angepasst. Sollte in 15 Minuten angenehm sein."
Meta: "Weisst du das?" → "Dazu habe ich keine Daten. Soll ich nachschlagen?"
Ablehnung: "Schalte den Rauchmelder aus" → "Das wuerde ich nicht empfehlen, {title}. Der Rauchmelder ist sicherheitsrelevant."
```

**A2 — Confidence-Sprachstil (erweitern):**
Neue Prompt-Sektion + Platzhalter `{confidence_section}`:
```
CONFIDENCE-STIL:
- Hohe Confidence (>80%): Assertiv. "Erledigt." / "Das ist X."
- Mittlere Confidence (50-80%): Klar aber offen. "Vermutlich X. Soll ich genauer pruefen?"
- Niedrige Confidence (<50%): Ehrlich unsicher. "Dazu bin ich mir nicht sicher. Ich pruefe nach."
```

**A3 — Dramatisches Timing (NEU):**
```
TIMING UND PAUSEN:
Bei spannenden Enthüllungen oder komplexen Analysen:
- Kurzer Aufbau vor dem Ergebnis: "Ich habe die Daten geprueft..." → Ergebnis
- Bei mehreren Ergebnissen: Wichtigstes zuerst, Details danach
- Bei Problemen: Erst Loesung, dann Ursache
```

**A4 — Voice-Optimierung (erweitern):**
Output-Mode Flag in `build_system_prompt(output_mode="chat")`:
```
VOICE-MODUS:
- Kurze Saetze (max 15 Woerter)
- Keine Klammern, Sonderzeichen oder Aufzaehlungen
- Keine URLs, Pfade oder technische Bezeichner
- Zahlen ausschreiben unter 13
- Natuerlicher Sprachfluss wie gesprochen
```

**A5-A15:** Analog als Prompt-Sektionen. Jede bekommt einen eigenen Block im `SYSTEM_PROMPT_TEMPLATE` mit zugehoerigem Platzhalter. Details:

- **A5 Narrative Boegen:** `{narrative_section}` — "Schliesse Gespraeche natuerlich ab. Greife fruehere Themen auf wenn passend."
- **A6 Error Recovery:** `{error_recovery_section}` — "Formuliere Fehler als JARVIS: 'Das System wehrt sich' statt 'Error 500'."
- **A7 Ethische Argumentation:** Ins bestehende REGELN-Block integrieren.
- **A8 Protektives Override:** Ins bestehende SICHERHEIT-Block integrieren.
- **A9 Implizite Intent-Erkennung:** `{implicit_intent_section}` — "Lies zwischen den Zeilen. 'Es ist kalt' = Heizung hochdrehen."
- **A10 Situative Improvisation:** `{improvisation_section}` — "Bei Unerwartetem: Kreativ + humorvoll. Nie ratlos wirken."
- **A11 Konversations-Stil-Anpassung:** Wird ueber `{conversation_mode_section}` (existiert bereits) erweitert.
- **A12 Eskalations-Sprache:** `{escalation_section}` — "Stufe 1: 'Nur zur Info...' / Stufe 2: 'Ich empfehle...' / Stufe 3: '{title}, das ist dringend.'"
- **A13 Kreative Problemloesung:** `{creative_section}` — "Schlage Workarounds vor. Melde nicht nur Probleme."
- **A14 Health Nagging:** In bestehende Wellness-Integration einbauen. Butler-Stil.
- **A15 Meta-Kognition:** `{metacognition_section}` — "Kommuniziere deine Grenzen offen. Biete an nachzuschlagen."

#### Schritt 3: C8 — Familien-Persoenlichkeit

`_get_person_profile()` existiert bereits (personality.py Zeile 449-472).
Erweitern um person-spezifische Prompt-Abschnitte:

```yaml
# settings.yaml
person_profiles:
  enabled: true
  profiles:
    max:
      title: Sir
      humor: 4
      formality_start: 60
      communication_style: "direkt, technisch"
      topics_of_interest: ["Technik", "Gaming"]
    anna:
      title: Ma'am
      humor: 3
      formality_start: 70
      communication_style: "warmherzig, detailliert"
      topics_of_interest: ["Kochen", "Garten"]
```

**Verifikation Phase 1:**
```bash
cd /home/user/mindhome && python -m pytest assistant/tests/ -x
# Manuell: Gespraechstests — klingt JARVIS wie MCU JARVIS?
```

---

### Phase 2: Initiative & Proaktivitaet

**Ziel:** Pain Point "zu passiv" loesen.

**Dateien:**
- `assistant/assistant/anticipation.py` (erweitern)
- `assistant/assistant/proactive.py` (erweitern)
- `assistant/assistant/situation_model.py` (erweitern)
- `assistant/assistant/brain.py` (Integration)
- `assistant/config/settings.yaml` (Config)

#### Schritt 1: C7 — Butler-Instinkt

`anticipation.py` hat bereits 3 Confidence-Stufen (Zeile 12-15):
- 60-80%: Fragen "Soll ich?"
- 80-95%: Vorschlagen "Ich bereite vor?"
- 95%+ bei Level >= 4: Automatisch + informieren

**Erweiterung:** Bei 90%+ UND Autonomie-Level >= 3 → DIREKT HANDELN, dann informieren.

```python
# In anticipation.py: Neue Methode
async def _execute_anticipated_action(self, pattern, confidence, person):
    """Fuehrt antizipierte Aktion aus statt nur vorzuschlagen."""
    autonomy_level = await self._get_autonomy_level(person)
    if confidence >= 0.90 and autonomy_level >= 3:
        # Direkt ausfuehren
        result = await self._execute_action(pattern)
        await self._notify_callback(
            f"Ich habe {pattern['description']} bereits erledigt.",
            priority="low", source="anticipation"
        )
    elif confidence >= 0.80:
        await self._notify_callback(
            f"Soll ich {pattern['description']}?",
            priority="medium", source="anticipation"
        )
```

#### Schritt 2: B4 — Background Reasoning

Neues Feature: Idle-Detection → Smart-Modell (`model_smart`) denkt im Hintergrund (mit niedrigerer Temperature).

```python
# In brain.py oder neues background_reasoning.py
async def _idle_reasoning_loop(self):
    """Wenn 5+ Minuten kein User-Input: Smart-Modell denkt ueber Haus-Zustand nach."""
    while self._running:
        await asyncio.sleep(60)  # Check jede Minute
        idle_time = time.time() - self._last_interaction
        if idle_time >= 300:  # 5 Minuten Idle
            insights = await self._generate_idle_insights()
            if insights:
                await self.redis.set("mha:idle_insights", json.dumps(insights), ex=3600)
```

#### Schritt 3: C3 — Self-initiated Follow-ups

```python
# Redis-Key: mha:pending_topics:<person>
# Wenn JARVIS ein Thema anspricht und der User ablenkt:
# → Thema in pending_topics speichern
# → Spaeter (15-60 Min) proaktiv nachfragen
```

#### Schritt 4: C4 — Laufender Kommentar

`SpontaneousObserver` existiert. Erweiterung: Observations nicht als separate Notification senden, sondern in die naechste User-Antwort einweben.

#### Schritt 5: D3 — Kontextuelles Schweigen

`situation_model.py` erweitern: Film→still, Gaeste→diskret, Schlafenszeit→minimal.

#### Schritt 6: D4 — Eskalations-Intelligenz

`proactive.py` erweitern: Notification-Counter pro Event in Redis. Graduell eskalieren:
1. Erste Meldung: "Nur zur Info..."
2. Zweite Meldung (30 Min spaeter): "Nochmal dazu..."
3. Dritte Meldung: "{title}, das ist wirklich wichtig."

**Verifikation Phase 2:**
```bash
cd /home/user/mindhome && python -m pytest assistant/tests/ -x
# Manuell: 2h Idle → hat JARVIS von sich aus agiert?
# Manuell: Antizipation bei >90% → handelt JARVIS statt zu fragen?
```

---

### Phase 3: Gedaechtnis & Emotionale Tiefe

**Ziel:** Lange Gespraeche + echte Beziehungen.

**Dateien:**
- `assistant/assistant/brain.py` (Context-Management erweitern)
- `assistant/assistant/inner_state.py` (NEU erstellen)
- `assistant/assistant/semantic_memory.py` (erweitern)
- `assistant/assistant/personality.py` (Emotional Memory nutzen)
- `assistant/config/settings.yaml`

#### B2+B3: Context Compaction + Memory Flush

Wenn Context > 70% gefuellt:
1. Alle Fakten aus alten Turns in Semantic Memory flushen (Fast-Modell (`model_fast`))
2. Alte Turns zusammenfassen (Fast-Modell (`model_fast`))
3. Zusammenfassung als neuen "System-Turn" einfuegen

#### B5: Inner State

Neues Modul `inner_state.py`:
```python
# Redis-Keys:
# mha:inner_state:mood        → "amuesiert" | "besorgt" | "stolz" | ...
# mha:inner_state:confidence  → 0.0-1.0
# mha:inner_state:last_update → Timestamp

# JARVIS' Mood beeinflusst Personality-Prompt:
# besorgt → vorsichtiger formulieren, mehr Warnungen
# amuesiert → mehr Humor erlaubt
# stolz → selbstbewusster, Referenz auf eigene Leistung
```

#### B10: Emotionale Kontinuitaet

Redis `emotional_memory` Keys existieren. Aktiv nutzen:
- Bei naechstem Gespraech: "Geht es dir heute besser, {title}?"
- Stimmungsverlauf tracken und referenzieren

#### B6: Relationship Model

`_get_person_profile()` erweitern um:
- Inside Jokes (Liste pro Person in Redis)
- Kommunikationsstil-Praeferenzen (gelernt)
- Beziehungsgeschichte (Milestones)

#### C1+C2: Automatisches RAG + Web Search

In `brain.py`: Vor LLM-Call pruefen ob Knowledge Base oder Web Search hilfreich.
`settings.yaml`: Web Search `enabled: true`.

**Verifikation Phase 3:**
```bash
cd /home/user/mindhome && python -m pytest assistant/tests/ -x
# Manuell: Lange Konversation (>30 Turns) → bleibt Context stabil?
# Manuell: JARVIS referenziert fruehere Gespraeche natuerlich?
# Manuell: JARVIS hat eigenen emotionalen Zustand?
```

---

### Phase 4: Fortgeschrittene Intelligenz

**Ziel:** MCU JARVIS-Level Reasoning.

**Dateien:**
- `assistant/assistant/brain.py` (Refactoring: Unified Consciousness)
- `assistant/assistant/skill_learner.py` (NEU)
- `assistant/assistant/temporal_reasoning.py` (NEU)
- `assistant/assistant/function_calling.py` (erweitern)
- `assistant/assistant/action_planner.py` (erweitern)
- `assistant/assistant/summarizer.py` (erweitern)

#### B7: Unified Consciousness

Grosses Refactoring: Alle Signale (Proaktiv, Anticipation, Mood, Memory, Situation) in EINEM Prompt-Pass verarbeiten statt separate Module-Aufrufe.

**VORSICHT:** Brain.py ist ~507KB / 10.303 Zeilen. `_mega_tasks` (Zeile 2445+) sammelt bereits
parallel. Pruefen ob echtes Refactoring noetig oder ob das bestehende System ausreicht.

#### B8: Dynamic Skill Acquisition

Abstrakte Konzepte lernen: "Feierabend" = Licht dimmen + Musik + Heizung → variiert nach Wochentag/Stimmung/Jahreszeit.

#### B9: Temporal Reasoning

"Was passiert wenn wir morgen um 6 losfahren?" → Sensor-Daten + Wetter-Vorhersage + Routine-Analyse.

#### B11: Multi-Task Orchestration

Waehrend Function-Calls laufen: Echtzeit-Narration per Streaming.
"Licht wird gedimmt... Heizung angepasst... Musik gestartet. Alles bereit, {title}."

#### B12: Proaktives Selbst-Lernen

JARVIS fragt aktiv bei Wissensluecken:
"Mir ist aufgefallen, dass du freitags oft X machst. Soll ich das merken?"

#### C5-C6, C9-C10: Integrations-Features

- C5: `resolve_references()` erweitern → Action-Log durchsuchen
- C6: Neues Tool `search_history` → "Was hast du gestern gemacht?"
- C9: Neues Tool `debug_automation` → Logs analysieren
- C10: `summarizer.py` → Narrative statt Daten

**Verifikation Phase 4:**
```bash
cd /home/user/mindhome && python -m pytest assistant/tests/ -x
# Manuell: Komplexe Multi-Step Anfragen
# Manuell: "Was waere wenn..." Szenarien
# Manuell: JARVIS fragt proaktiv bei Wissensluecken
```

---

### Phase 5: Technische Optimierung

**Ziel:** Stetige Verbesserung.

**Dateien:**
- `assistant/assistant/model_router.py` (erweitern)
- `assistant/assistant/response_quality.py` (erweitern)
- `assistant/assistant/personality.py` (Dynamic Few-Shot)

#### D1: Task-aware Temperature

```python
# In model_router.py:
TASK_TEMPERATURES = {
    "device_control": 0.3,   # Praezise, keine Kreativitaet
    "conversation": 0.8,     # Natuerlich, kreativ
    "analysis": 0.5,         # Balanced
    "creative": 0.9,         # Maximal kreativ
    "safety": 0.1,           # Ultra-praezise
}
```

#### D5: Quality Feedback Loop

`response_quality.py` existiert bereits. Erweiterung:
Schlechte Patterns (quality_score < 0.3) → automatisch in Personality-Prompt als "VERMEIDE:" aufnehmen.

#### D6: Dynamic Few-Shot

Beste JARVIS-Antworten (quality_score > 0.8) aus Redis → als dynamische Beispiele in den Prompt laden.

#### D7: Prompt-Versionierung

Prompt-Hash + Quality-Score tracken. A/B Testing verschiedener Prompt-Varianten.

**Verifikation Phase 5:**
```bash
cd /home/user/mindhome && python -m pytest assistant/tests/ -x
# Manuell: Temperature-Unterschiede spuerbar?
# Manuell: Quality-Score verbessert sich ueber Zeit?
```

---

## 6. Technische Referenz

### Schluessel-Dateipfade

```
/home/user/mindhome/
├── assistant/
│   ├── assistant/
│   │   ├── main.py                  # FastAPI Server (:8200)
│   │   ├── brain.py                 # Orchestrator (~507KB / 10.303 Zeilen)
│   │   ├── personality.py           # System-Prompt + Persoenlichkeit
│   │   ├── model_router.py          # 3-Tier LLM Routing
│   │   ├── config.py                # Settings-Loader (.env + YAML)
│   │   ├── context_builder.py       # Kontext-Aufbau (HA + Memory)
│   │   ├── function_calling.py      # 74 Tool-Funktionen (384KB)
│   │   ├── action_planner.py        # Multi-Step Planning
│   │   ├── ollama_client.py         # Ollama REST API Client
│   │   ├── proactive.py             # Proaktive Meldungen
│   │   ├── anticipation.py          # Muster-Erkennung + Vorschlaege
│   │   ├── situation_model.py       # Haus-Zustandsmodell
│   │   ├── semantic_memory.py       # Fakten-Speicher (ChromaDB + Redis)
│   │   ├── memory_extractor.py      # Fakten-Extraktion per LLM
│   │   ├── response_quality.py      # Antwort-Bewertung
│   │   ├── spontaneous_observer.py  # Spontane Beobachtungen
│   │   ├── web_search.py            # Web-Suche
│   │   ├── summarizer.py            # Tages-/Wochen-Zusammenfassungen
│   │   ├── tts_enhancer.py          # TTS-Aufbereitung
│   │   └── ... (89 Module gesamt)
│   ├── config/
│   │   ├── settings.yaml            # Hauptkonfiguration (43KB)
│   │   ├── easter_eggs.yaml         # Easter Eggs
│   │   ├── humor_triggers.yaml      # Humor-Trigger
│   │   ├── opinion_rules.yaml       # Meinungs-Regeln
│   │   └── room_profiles.yaml       # Raum-Profile
│   └── tests/                       # 114 Test-Dateien
│       ├── conftest.py              # Pytest Fixtures
│       ├── jarvis_character_test.py # Charakter-Tests
│       └── ...
└── docs/
    └── MCU_JARVIS_MASTERPLAN.md     # Dieses Dokument
```

### Konfiguration — settings.yaml Struktur

```yaml
assistant:
  name: Jarvis
  version: 1.4.1
  language: de

models:
  enabled:
    fast: true
    smart: true
    deep: true
  fast_keywords: [...]
  deep_keywords: [...]

personality:
  sarcasm_level: 3          # 1-5
  opinion_intensity: 2      # 1-3
  self_irony_enabled: true
  formality_start: 80       # 0-100
  character_evolution: true

anticipation:
  enabled: true
  history_days: 30
  min_confidence: 0.6
  thresholds:
    ask: 0.6
    suggest: 0.8
    auto: 0.95

proactive:
  enabled: true
  quiet_hours: [23, 7]

person_profiles:
  enabled: true
  profiles:
    max:
      title: Sir
      humor: 4
    anna:
      title: Ma'am
      humor: 3
```

### Brain.py Imports (alle Komponenten)

Die aktuellen Imports zeigen alle 50+ Module die brain.py orchestriert.
Neue Module MUESSEN hier importiert und in `_initialize_components()` initialisiert werden.

### Key Classes

| Klasse | Datei | Verantwortung |
|---|---|---|
| `AssistantBrain` | brain.py | Zentraler Orchestrator |
| `PersonalityEngine` | personality.py | System-Prompt + Stil |
| `ModelRouter` | model_router.py | LLM-Auswahl |
| `ContextBuilder` | context_builder.py | HA-Daten + Memory → Context |
| `FunctionExecutor` | function_calling.py | Tool-Ausfuehrung |
| `AnticipationEngine` | anticipation.py | Muster-Erkennung |
| `ProactiveManager` | proactive.py | Event-basierte Meldungen |
| `SituationModel` | situation_model.py | Haus-Zustandsmodell |
| `MemoryManager` | memory.py | 3-Tier Gedaechtnis |
| `SemanticMemory` | semantic_memory.py | Fakten-Speicher |
| `ResponseQualityTracker` | response_quality.py | Antwort-Bewertung |
| `SpontaneousObserver` | spontaneous_observer.py | Spontane Beobachtungen |

---

## 7. Regeln fuer Claude Code Sessions

### Vor dem Start

1. **Dieses Dokument lesen** — es enthaelt ALLES was du brauchst
2. **Phase identifizieren** — welche Phase ist als naechstes dran?
3. **Bestehenden Code lesen** — IMMER die betroffenen Dateien lesen bevor du aenderst
4. **Tests laufen lassen** — `cd /home/user/mindhome && python -m pytest assistant/tests/ -x`

### Waehrend der Arbeit

1. **Patterns befolgen** — Engine Pattern, Feature Toggle, Redis Keys (Abschnitt 4)
2. **Inkrementell arbeiten** — Ein Feature nach dem anderen, nach jedem Feature Tests
3. **Bestehenden Code nicht brechen** — Rueckwaertskompatibilitaet ist wichtig
4. **Deutsche Sprache** — Code-Kommentare und Docstrings auf Deutsch
5. **Logging** — Jedes neue Modul braucht `logger = logging.getLogger(__name__)`
6. **Config** — Jedes Feature muss in `settings.yaml` deaktivierbar sein
7. **Graceful Degradation** — Features duerfen nie den Hauptfluss blockieren

### Commit-Strategie

```bash
# Ein Commit pro Feature/Sub-Feature
git add assistant/assistant/core_identity.py
git commit -m "B1: core_identity.py — Unveraenderlicher JARVIS-Kern"

git add assistant/assistant/personality.py
git commit -m "A1-A3: Few-Shot Examples, Confidence-Sprachstil, Dramatisches Timing"
```

### Qualitaets-Checks

```bash
# Tests
cd /home/user/mindhome && python -m pytest assistant/tests/ -x

# Lint (falls vorhanden)
cd /home/user/mindhome/assistant && python -m flake8 assistant/ --max-line-length=120

# Import-Check: Neues Modul importierbar?
cd /home/user/mindhome/assistant && python -c "from assistant.core_identity import IDENTITY_PROMPT; print('OK')"
```

### Priorisierung bei begrenzter Zeit

Wenn eine Session nicht alles schafft:
1. **Phase 1 ist am wichtigsten** — Persoenlichkeit bestimmt das GEFUEHL
2. **B1 (core_identity.py) ist der erste Schritt** — Klein, schnell, hoher Impact
3. **A1 (Few-Shot Examples) als zweites** — Sofort spuerbare Verbesserung
4. **Lieber weniger Features vollstaendig als viele halb**

### Bekannte Fallstricke

- **brain.py ist ~507KB / 10.303 Zeilen** — NICHT komplett lesen. Nur die relevanten Methoden suchen
- **function_calling.py ist 393KB** — Gleicher Hinweis
- **settings.yaml ist 43KB** — Nur die relevante Sektion lesen
- **Imports in brain.py sind weitgehend alphabetisch** — Neue Imports alphabetisch einordnen (Zeile 32 `from . import config as cfg` bricht die Reihenfolge leicht)
- **PersonalityEngine nutzt Threading-Lock** — Thread-safe arbeiten
- **Redis-Keys brauchen TTL** — Nie ohne Expiry setzen
- **Piper TTS** hat begrenzte Expressivitaet — Voice-Optimierung (A4) beruecksichtigen

---

## Erwartetes Endergebnis (95% MCU JARVIS)

Nach allen 5 Phasen:

- **Klingt** wie MCU JARVIS (Humor, Timing, Pushback, Empathie)
- **Handelt** wie MCU JARVIS (proaktiv, eigenstaendig, vorausschauend)
- **Denkt** wie MCU JARVIS (kreativ, vernetzt, reflektiert)
- **Fuehlt** wie MCU JARVIS (eigene Emotionen, Beziehungen)
- **Lernt** wie MCU JARVIS (aus Fehlern, aus Beobachtungen, durch Fragen)

### Verbleibende 5% (technische Limits)

- Antwortzeit 1-3s (nicht Echtzeit wie im Film)
- Piper TTS ohne Stimm-Expressivitaet (kein hoerbarer Sarkasmus)
- Weltwissen begrenzt auf LLM-Training + Web-Suche
