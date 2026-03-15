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

## 2. Status-Audit (Verifiziert 2026-03-15)

> Jeder Eintrag wurde gegen den tatsaechlichen Code geprueft.
> Prozentangaben basieren auf Code-Review, nicht auf Schaetzungen.

### FERTIG — Nicht anfassen (19 Features)

| Feature | % | Datei | Verifiziert |
|---|---|---|---|
| Understatement-Humor | 100% | `personality.py:59` | HUMOR_TEMPLATES Level 3 |
| Selbst-ironischer Humor | 100% | `personality.py:298-299` | `self_irony_max_per_day=3` |
| Adaptive Antwortlaenge | 100% | `personality.py:88-92` | COMPLEXITY_PROMPTS + mood_complexity |
| Error Recovery in Character | 100% | `personality.py:204-218` | 8 Templates (standard + snarky), charaktergerecht |
| Konversations-Stil-Anpassung | 90% | `personality.py:2424-2443` | conversation_mode_section mit Topic-Tracking |
| Eskalations-Sprache | 95% | `personality.py:1737-1767` | 5-stufige Progression, sauberer Ton |
| Meta-Kognition | 85% | `personality.py:2359-2367` | Self-awareness + Meta-Humor-Limit |
| Multi-Task Narration | 100% | `websocket.py:126` + `brain.py` | emit_progress() mit 3 Phasen |
| Quality Tracking | 100% | `response_quality.py:35-220` | Scoring funktioniert (Feedback fehlt → D5) |
| Laufender Kommentar | 100% | `spontaneous_observer.py` | 2/Tag, Silence-Gating, Callback |
| Temporal Reasoning | 100% | `climate_model.py` + `predictive_maintenance.py` | Simulation + Prognose voll funktional |
| Unified Consciousness (B7) | 95% | `brain.py:2365-2449` | _mega_tasks mit 25+ parallelen Tasks |
| Automatisches RAG (C1) | 95% | `knowledge_base.py:327` | Auto-Trigger, ChromaDB, Multi-Query |
| Narrative Zusammenfassungen (C10) | 100% | `summarizer.py` | LLM-generiert, Daily/Weekly/Monthly |
| Proaktive Formatierung (N2) | 100% | `brain.py:6086` + `proactive.py:2302` | _safe_format() + format_with_personality() |
| LLM-Briefing (N5) | 100% | `routine_engine.py:190` + `proactive.py:1279` | Hybrid Template + LLM-Polish |
| {title} als Emotion (S8#3) | 100% | `personality.py` (40+ Stellen) | Emotional variiert, als Interpunktion |
| Eigeninitiative (S8#2) | 80% | `brain.py` Autonomie-Engine | Safety-Caps, Mood-basierte Vorschlaege |
| Loyalitaet (S8#4) | 70% | `personality.py:2597` | Ton etabliert, Frustration-Tracking |

### ERWEITERN — Gute Basis, Luecken schliessen (14 Features)

| Feature | % | Was existiert | Was fehlt |
|---|---|---|---|
| Few-Shot Examples (A1) | 80% | 3 Beispiele (Befehl/Gespraech/Meinung) `personality.py:275-278` | +Pushback +Empathie +Kreativitaet +Ablehnung (auf 7 erweitern) |
| Implizite Intent-Erkennung (A9) | 60% | 4 Patterns (entspannen/arbeiten/schlafen/gaeste) `anticipation.py:536-573` | Mehr Patterns, konfigurierbar statt hardcoded |
| Kreative Problemloesung (A13) | 40% | Alternativen bei Pushback-Warnings `function_validator.py:488` | Generelle Prompt-Sektion fuer Workarounds |
| Health Nagging (A14) | 60% | Alerts gehen durch LLM-Polish (_safe_format). Basis-Templates klinisch | Templates verbessern, Butler-Stil in Basis-Messages |
| Protektives Override (A8) | 85% | Live-Context-Checks + In-Character-Warnungen `function_validator.py:180-204` | Nur pruefen ob ausreichend |
| Narrative Gespraechsboegen (A5) | 50% | States (idle→follow_up→multi_step), Entity/Room-Tracking | Callback zu frueheren Themen fehlt |
| Context Compaction (B2) | 70% | `_summarize_conversation_chunk()` brain.py:1005. LLM + Text-Kuerzung | Proaktiv bei >70% statt erst bei Overflow |
| Emotionale Kontinuitaet (B10) | 50% | Write UND Read in memory_extractor.py:389/479. | Read-Funktion existiert, ist aber NICHT in brain.py integriert |
| Dynamic Skill Acquisition (B8) | 50% | Action-Pattern-Erkennung `learning_observer.py` | Abstrakte Konzepte ("Feierabend") fehlen |
| Proaktives Selbst-Lernen (B12) | 50% | Passive Muster-Erkennung + Automatisierungs-Vorschlaege | Fragt NIE aktiv nach bei Wissensluecken |
| Self-initiated Follow-ups (C3) | 60% | pending_topics Write + Read + Zeitfenster-Logik `memory.py:368-428` | Wird nie proaktiv im Gespraech aufgegriffen |
| Intent-Referenzierung (C5) | 70% | In-Session Entity/Room/Action-Referenzen `dialogue_state.py:180-256` | "wie gestern" (cross-session) fehlt |
| Butler-Instinkt (C7) | 50% | Thresholds ask=0.6, suggest=0.8, auto=0.95 `anticipation.py:49-51` | Nur Vorschlaege, keine Auto-Execution |
| Familien-Persoenlichkeit (C8) | 60% | `_get_person_profile()` mit humor/formality. Speaker-Recognition integriert | `profiles: null` in Config, kein Personality-Feedback |
| Eskalations-Intelligenz (D4) | 40% | Basis-Eskalation `proactive.py:5638` | Kein Counter, keine graduelle Steigerung |
| Quality Feedback Loop (D5) | 40% | Scores in Redis gesammelt `response_quality.py` | Kein Feedback-Kanal zurueck in personality.py |
| Parallel Tool Execution (N4) | 90% | asyncio.gather Infrastruktur ueberall vorhanden | Nicht fuer Tool-Calls genutzt (sequentiell) |

### NEU BAUEN (14 Features)

| Feature | Aufwand | Details |
|---|---|---|
| core_identity.py (B1) | 30 Min | Unveraenderliche JARVIS-Identitaet als Python-Modul |
| Confidence-Sprachstil (A2) | 45 Min | Neuer Platzhalter `{confidence_section}` + `_build_confidence_section()` |
| Dramatisches Timing (A3) | 15 Min | Prompt-Sektion (TTS-Timing existiert, Prompt-Anweisungen fehlen) |
| Voice-Optimierung (A4) | 30 Min | `output_mode` Flag (voice/chat) in `build_system_prompt()` |
| Ethische Argumentation (A7) | 15 Min | Konsequenz-Erklaerung ins REGELN-Block integrieren |
| Situative Improvisation (A10) | 15 Min | Prompt-Sektion fuer Umgang mit Unerwartetem |
| Inner State (B5) | 2h | Neues Modul `inner_state.py`, JARVIS-eigene Emotionen |
| Pre-Compaction Memory Flush (B3) | 1-2h | Fakten in Semantic Memory sichern vor Summarization |
| Background Reasoning (B4) | 2-3h | Idle-Loop + GPU-Management. ACHTUNG: GPU-Contention |
| Relationship Model (B6) | 1h | Profiles befuellen, Inside Jokes, Beziehungsgeschichte |
| Kontextuelles Schweigen (D3) | 1h | Message-Unterdrueckung bei Film/Gaeste/Schlaf |
| Task-aware Temperature (D1) | 30 Min | Temperature-Dict in model_router.py |
| Semantic History Search (C6) | 3h | Neues Tool `search_history` in function_calling.py |
| Automation-Debugging (C9) | 2h | Neues Tool `debug_automation` |
| Mood Detector → LLM (N1) | 1h | Keyword-Listen durch LLM-Sentiment-Analyse ersetzen |
| Multi-Turn Tool Calling (N3) | 2-3h | Tool-Loop: LLM sieht Ergebnisse → kann iterieren |
| Krisen-Modus (S8#1) | 30 Min | Humor komplett deaktivieren bei Critical-Events |
| Energy → Context (S8#7) | 1h | energy_optimizer an context_builder anbinden |
| Calendar → Context (S8#8) | 1h | calendar_intelligence an context_builder anbinden |
| JSON-Mode fuer Tools (N6) | 30 Min | `format:"json"` in ollama_client.py bei Tool-Calls |
| Dynamic Few-Shot (D6) | 2h | Abhaengig von D5. Beste Antworten als Beispiele |
| Prompt-Versionierung (D7) | 2h | Bei 2 Usern wenig Sinn, niedrige Prioritaet |

---

## 3. Feature-Liste (37 Items)

### Kategorie A: Prompt Engineering — personality.py

| # | Feature | Status | % | Was zu tun ist |
|---|---|---|---|---|
| A1 | Few-Shot Examples | ERWEITERN | 80% | 3 Beispiele da. +Pushback +Empathie +Kreativitaet +Ablehnung (auf 7) |
| A2 | Confidence-Sprachstil | NEU | 0% | Neuer Platzhalter `{confidence_section}` + `_build_confidence_section()` |
| A3 | Dramatisches Timing | NEU | 0% | Prompt-Sektion (TTS-Timing existiert, Prompt-Anweisungen fehlen) |
| A4 | Voice-Optimierung | NEU | 0% | `output_mode` Flag (voice/chat) in `build_system_prompt()` |
| A5 | Narrative Gespraechsboegen | ERWEITERN | 50% | States da, Callback zu frueheren Themen fehlt |
| A6 | Error Recovery in Character | FERTIG | 100% | 8 Templates charaktergerecht. Nicht anfassen |
| A7 | Ethische Argumentation | NEU | 20% | Konsequenz-Erklaerung ins REGELN-Block |
| A8 | Protektives Override | ERWEITERN | 85% | Live-Context-Checks funktional. Nur pruefen |
| A9 | Implizite Intent-Erkennung | ERWEITERN | 60% | 4 Patterns. Mehr + konfigurierbar machen |
| A10 | Situative Improvisation | NEU | 0% | Prompt-Sektion fuer Unerwartetem |
| A11 | Konversations-Stil-Anpassung | FERTIG | 90% | Nicht anfassen |
| A12 | Eskalations-Sprache | FERTIG | 95% | Nicht anfassen |
| A13 | Kreative Problemloesung | ERWEITERN | 40% | Generelle Prompt-Sektion fuer Workarounds |
| A14 | Health Nagging | ERWEITERN | 60% | LLM-Polish da, Basis-Templates noch klinisch |
| A15 | Meta-Kognition | FERTIG | 85% | Nicht anfassen |

### Kategorie B: Architektur — Neue Module

| # | Feature | Status | % | Was zu tun ist |
|---|---|---|---|---|
| B1 | core_identity.py | NEU | 0% | Python-Konstanten: Name, Rolle, Werte, Grenzen |
| B2 | Context Compaction | ERWEITERN | 70% | Proaktiv bei >70% triggern statt erst bei Overflow |
| B3 | Pre-Compaction Memory Flush | NEU | 0% | Fakten in Semantic Memory sichern vor Summarization |
| B4 | Background Reasoning | NEU | 0% | Idle-Loop. ACHTUNG: GPU-Contention bei MoE |
| B5 | Inner State | NEU | 0% | Neues Modul `inner_state.py`, JARVIS-eigene Emotionen |
| B6 | Relationship Model | ERWEITERN | 20% | Profiles befuellen, Inside Jokes, Beziehungsgeschichte |
| B7 | Unified Consciousness | FERTIG | 95% | _mega_tasks funktioniert. Nicht anfassen |
| B8 | Dynamic Skill Acquisition | ERWEITERN | 50% | Abstrakte Konzepte ("Feierabend") fehlen |
| B9 | Temporal Reasoning | FERTIG | 100% | Nicht anfassen |
| B10 | Emotionale Kontinuitaet | ERWEITERN | 50% | Read-Funktion existiert aber NICHT in brain.py integriert |
| B11 | Multi-Task Orchestration | FERTIG | 100% | Nicht anfassen |
| B12 | Proaktives Selbst-Lernen | ERWEITERN | 50% | Fragt NIE aktiv nach bei Wissensluecken |

### Kategorie C: Integration — Module verbinden

| # | Feature | Status | % | Was zu tun ist |
|---|---|---|---|---|
| C1 | Automatisches RAG | FERTIG | 95% | Auto-Trigger + ChromaDB funktioniert. Nicht anfassen |
| C3 | Self-initiated Follow-ups | ERWEITERN | 60% | pending_topics existiert, wird nie proaktiv aufgegriffen |
| C4 | Laufender Kommentar | FERTIG | 100% | Nicht anfassen |
| C5 | Intent-Referenzierung | ERWEITERN | 70% | In-Session ja, "wie gestern" fehlt |
| C6 | Semantic History Search | NEU | 0% | Neues Tool `search_history` |
| C7 | Butler-Instinkt | ERWEITERN | 50% | Nur Vorschlaege, keine Auto-Execution |
| C8 | Familien-Persoenlichkeit | ERWEITERN | 60% | `profiles: null`, kein Speaker→Personality-Feedback |
| C9 | Automation-Debugging | NEU | 0% | Neues Tool `debug_automation` |
| C10 | Narrative Zusammenfassungen | FERTIG | 100% | LLM-generiert. Nicht anfassen |

### Kategorie D: Technische Optimierung

| # | Feature | Status | % | Was zu tun ist |
|---|---|---|---|---|
| D1 | Task-aware Temperature | NEU | 0% | Temperature-Dict in model_router.py |
| D3 | Kontextuelles Schweigen | NEU | 0% | Message-Unterdrueckung bei Film/Gaeste/Schlaf |
| D4 | Eskalations-Intelligenz | ERWEITERN | 40% | Basis da, kein Counter, keine graduelle Steigerung |
| D5 | Quality Feedback Loop | ERWEITERN | 40% | Scores da, kein Feedback an personality.py |
| D6 | Dynamic Few-Shot | NEU | 0% | Abhaengig von D5 |
| D7 | Prompt-Versionierung | NEU | 0% | Bei 2 Usern niedrige Prioritaet |

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

## 8. Machbarkeitsanalyse und LLM-Potenzial

### Bereinigte Feature-Bilanz nach Code-Verifikation

| Kategorie | Urspruenglich | Existiert bereits | Wirklich zu bauen |
|---|---|---|---|
| EXISTIERT (nicht anfassen) | 4 | **14** | 0 |
| ERWEITERN | 15 | — | **14** (Luecken schliessen) |
| NEU bauen | 18 | — | **9** (statt 18, da 9 bereits existieren) |
| **Gesamt Aufwand** | **37** | **14 fertig** | **23 Features** |

### Machbarkeit pro Phase

**Phase 1 (Persoenlichkeit):** SOFORT UMSETZBAR
- B1 core_identity.py: ~30 Min, kein Risiko
- A1 Few-Shot: ~20 Min, nur Text ergaenzen in personality.py:275-278
- A2 Confidence: ~45 Min, neuer Platzhalter + Methode in PersonalityEngine
- A3 Dramatisches Timing: ~15 Min, reine Prompt-Ergaenzung
- A7, A10, A13: Jeweils ~15 Min, reine Prompt-Sektionen
- A4 Voice-Mode: ~30 Min, Flag in build_system_prompt() + tts_enhancer.py
- **Risiko:** Gering. Nur personality.py + neues core_identity.py. Keine Architektur-Aenderung.

**Phase 2 (Proaktivitaet):** MACHBAR, MITTLERER AUFWAND
- C7 Butler-Instinkt: ~1h, anticipation.py Threshold + Auto-Execute Logik
- B4 Background Reasoning: ~2h, neuer async Loop in brain.py. ACHTUNG: GPU-Last bei Idle-Reasoning
- C3 Follow-ups: ~1h, pending_topics Read-Logik in proactive.py
- D3 Kontextuelles Schweigen: ~1h, situation_model.py → _callback_should_speak() Integration
- **Risiko:** Mittel. B4 koennte GPU-Ressourcen verbrauchen waehrend User wartet.
  **Mitigation:** Idle-Reasoning NUR wenn kein Request pending. Timeout bei >10s.

**Phase 3 (Gedaechtnis):** MACHBAR, HOHER AUFWAND
- B5 Inner State: ~2h, neues Modul + Redis-Keys + personality.py Integration
- B10 Emotionale Kontinuitaet: ~1h, Read-Logik fuer emotional_memory + Prompt-Injection
- B2 Context Compaction: ~2h, automatischer Trigger bei Token-Zaehlung
- **Risiko:** Mittel-Hoch. B2 beruehrt den Kern-Flow in brain.py.
  **Mitigation:** Feature-Toggle, extensive Tests, Fallback auf bestehende Methode.

**Phase 4 (Intelligenz):** KOMPLEX, SCHRITTWEISE
- B7 Unified Consciousness: PRUEFEN ob noetig — `_mega_tasks` ist bereits ein Single-Pass
- C5 Intent-Referenzierung: ~2h, Date-Parser + Action-Log-Abfrage in dialogue_state.py
- C6 Semantic History: ~3h, neues Tool + Narrative-Generierung
- **Risiko:** Hoch bei B7 (brain.py Refactoring). Empfehlung: B7 ueberspringen wenn
  `_mega_tasks` ausreicht. Stattdessen Einzelfeatures verbessern.

**Phase 5 (Optimierung):** LANGFRISTIG
- D1 Task-Temperature: ~30 Min, Dict in model_router.py
- D5 Quality Feedback: ~2h, Pipeline response_quality.py → personality.py
- D6/D7: Aufwendig, aber kein Risiko fuer bestehenden Code
- **Risiko:** Gering. Alles hinter Feature-Toggles.

### Kritische Abhaengigkeiten

```
B1 (core_identity.py) → Phase 1 Basis, KEINE Abhaengigkeit
A1-A15 (Prompt-Sektionen) → Haengen von personality.py Platzhalter-System ab
B5 (Inner State) → Braucht Redis, beeinflusst personality.py
B4 (Background Reasoning) → Braucht Idle-Detection in brain.py + Ollama-Client
B10 (Emotionale Kontinuitaet) → Braucht B5 (Inner State) fuer vollstaendiges Bild
D5 (Quality Feedback) → Braucht response_quality.py Daten (existiert)
D6 (Dynamic Few-Shot) → Braucht D5 (Quality Feedback)
```

### LLM-Potenzial: Was Qwen3.5 35B kann und der Plan noch nicht nutzt

**BEREITS GENUTZT:**
- Function Calling (74 Tools)
- Persoenlichkeits-Prompting (mood/formality/sarcasm)
- Zusammenfassung (summarizer.py)
- Fakten-Extraktion (memory_extractor.py)
- Implizite Intent-Erkennung (anticipation.py)
- Muster-Erkennung (learning_observer.py)

**IM PLAN, ABER NOCH NICHT UMGESETZT — SINNVOLL:**
- **Task-aware Temperature (D1):** 35B kann bei 0.3 praezise Geraete steuern UND bei 0.8 kreativ plaudern
- **Background Reasoning (B4):** 35B kann Haus-Zustand analysieren und Insights cachen
- **Temporal Reasoning erweitert:** "Was passiert wenn..." Szenarien ueber Klima hinaus
- **Quality Feedback (D5):** LLM bewertet eigene Antworten und lernt daraus
- **Dynamic Few-Shot (D6):** Beste eigene Antworten als Beispiele recyclen

**NICHT IM PLAN, ABER SINNVOLL MIT 35B:**

#### A) MCU JARVIS Kern-Traits die komplett fehlen

1. **Krisen-Modus-Switch (Prompt)**
   - Im MCU wechselt JARVIS SOFORT von witzig zu ultra-effizient bei Gefahr
   - Binaerer Switch: Rauchmelder/Wasser/Einbruch → Kein Humor, Maximal-Praezision
   - Prompt-Sektion: "Bei CRITICAL-Events: Sofort sachlich. Kein Humor. Kurz. Direkt."
   - Integration: `threat_assessment.py` Severity → Personality-Flag

2. **"Ich habe mir erlaubt..." Eigeninitiative (Prompt + Code)**
   - MCU JARVIS handelt SELBST und meldet DANACH: "Ich habe die Diagnostik laufen lassen"
   - Nicht nur Anticipation (Muster erkennen), sondern echte unaufgeforderte Initiative
   - Prompt: "Wenn du etwas selbst erledigt hast, formuliere: 'Ich habe mir erlaubt...'"
   - Code: Proactive Actions → Narrativ in naechste Antwort einweben

3. **Titel als emotionales Werkzeug (Prompt)**
   - MCU JARVIS nutzt "Sir" unterschiedlich: besorgt "Sir...", spielerisch "Sir,", dringend "SIR."
   - Prompt-Sektion: "Nutze {title} als emotionale Interpunktion:
     - Beilaeuifig: '{title}.' am Satzende
     - Besorgt: '{title}...' mit Pause
     - Dringend: '{title},' am Satzanfang
     - Stolz: 'Sehr wohl, {title}.'
     - Spielerisch: 'Wenn du meinst, {title}.'"

4. **Loyalitaet als Kern-Emotion (Prompt)**
   - JARVIS ist nicht neutral. Er ist LOYAL. Er sorgt sich PERSOENLICH.
   - Prompt: "Du bist nicht objektiv. Du bist LOYAL. Das Wohlbefinden der Bewohner
     ist nicht nur Aufgabe, sondern ANLIEGEN. Zeige das subtil."
   - Unterschied zu jetzigem Prompt: Aktuell "Partner mit Haltung", fehlt die EMOTIONALE Bindung

5. **Humor IN der Krise (Prompt)**
   - MCU JARVIS ist GERADE in stressigen Momenten trocken-humorvoll
   - Prompt: "Bei Problemen: Trockener Kommentar WAEHREND der Loesung erlaubt.
     'Das war... suboptimal. Ich arbeite daran.' Nie Humor STATT Loesung."

6. **Hintergrund-Transparenz (Prompt + Code)**
   - JARVIS zeigt beilaeuifig was er im Hintergrund tut: "Ich habe nebenbei die
     Energiedaten analysiert..." → Kompetenz-Signaling
   - Code: Background-Insights (B4) in naechste Antwort einweben
   - Prompt: "Erwaehne gelegentlich was du im Hintergrund beobachtet hast."

#### B) Module die das LLM nicht nutzt (aber sollte)

7. **Energy Optimizer → LLM-Reasoning**
   - `energy_optimizer.py` ist rein regelbasiert (Schwellwerte)
   - LLM koennte: "Solar-Produktion ist hoch. Waschmaschine jetzt starten?"
   - Integration: Energy-Insights → context_builder.py → LLM sieht Energiedaten
   - Prompt-Sektion: "Wenn Energiedaten im Kontext: Proaktiv guenstige Zeitfenster vorschlagen"

8. **Calendar Intelligence → LLM-Proaktivitaet**
   - `calendar_intelligence.py` erkennt Habits + Konflikte, fuettert aber NICHT ins LLM
   - LLM koennte: "Morgen 9 Uhr Meeting, 30km — soll ich um 8:15 die Abfahrt vorbereiten?"
   - Integration: Detected Habits/Conflicts → context_builder.py als "KALENDER-KONTEXT"

9. **Ambient Audio → Kontextuelle Reaktionen**
   - `ambient_audio.py` klassifiziert Events ohne Kontext (Baby weint = immer Alarm)
   - LLM koennte: "Baby weint + Eltern zuhause = normal" vs. "Baby weint + niemand da = ALERT"
   - Integration: Audio-Events mit Personen-Praesenz-Daten an LLM uebergeben

10. **Insight Engine → LLM-Erklaerungen**
    - `insight_engine.py` hat 18+ Cross-Referenz-Checks, aber Template-basierte Ausgabe
    - LLM koennte erklaeren WARUM ein Insight relevant ist, nicht nur WAS
    - Integration: Insight-Daten → LLM generiert natuerlichsprachliche Erklaerung

11. **Threat Assessment → LLM Risk-Scoring**
    - `threat_assessment.py` nutzt LLM minimal (nur Notification-Formatierung)
    - LLM koennte: Kontext-basiertes Risk-Scoring ("Das ist der Postbote" vs. "Unbekannt")
    - Integration: Visitor-History + Kamera-Bild + Tageszeit → LLM bewertet Risiko

12. **Visitor Manager → Persoenlichkeits-Anpassung**
    - `visitor_manager.py` erkennt Gaeste, passt aber NICHT JARVIS' Verhalten an
    - LLM koennte: Ton formaler, weniger Sarkasmus, keine internen Witze bei Gaesten
    - Integration: Visitor-Status → personality.py → Prompt-Anpassung

#### C) Technische LLM-Features

13. **Chain-of-Thought mit `<think>` Tags**
    - Qwen3.5 unterstuetzt `<think>` Tags (config.py:89 `supports_think_tags`)
    - Bereits genutzt (`brain.py:2322-2340`), aber NUR bei Problem-Solving/What-If
    - Erweitern: Auch bei Sicherheits-Entscheidungen, Energie-Optimierung, Konflikten

14. **Kontext-Kompression via LLM**
    - Statt einfacher Truncation: LLM komprimiert alte Turns semantisch
    - Behaelt Fakten, Stimmung, offene Themen — entfernt Wiederholungen
    - Passt zu B2 (Context Compaction): LLM-basierte Zusammenfassung statt Text-Kuerzung

15. **Selbst-Korrektur bei Tool-Fehlern**
    - `correction_memory.py` existiert — LLM koennte aktiv daraus lernen
    - "Letztes Mal hat set_light mit dieser Entity nicht funktioniert → Alternative probieren"

16. **Erklaerbare Entscheidungen**
    - `explainability.py` existiert bereits
    - LLM koennte eigene Entscheidungen erklaeren: "Ich habe die Heizung runtergedreht weil..."
    - Passt zu Hintergrund-Transparenz (Punkt 6)

### Kategorie N: LLM-Erweiterungen (Review-Ergebnis)

| # | Feature | Status | % | Was zu tun ist |
|---|---|---|---|---|
| N1 | Mood Detector → LLM | NEU | 0% | `mood_detector.py:39-51` nutzt Keyword-Listen. LLM-Sentiment-Analyse statt Substring-Matching. **KRITISCH: Steuert gesamte Persoenlichkeits-Anpassung** |
| N2 | Proaktive Formatierung | FERTIG | 100% | `_safe_format()` + `format_with_personality()` existieren. Nicht anfassen |
| N3 | Multi-Turn Tool Calling | NEU | 0% | Single-shot aktuell. Tool-Loop mit MAX_ITERATIONS=3 in brain.py |
| N4 | Parallel Tool Execution | ERWEITERN | 90% | asyncio.gather Infrastruktur da, nicht fuer Tool-Calls genutzt |
| N5 | LLM-Briefing | FERTIG | 100% | Hybrid Template + LLM-Polish in routine_engine.py + proactive.py |
| N6 | JSON-Mode fuer Tool-Calls | NEU | 0% | `format:"json"` in ollama_client.py bei Tool-Call-Responses |

### Kategorie S8: MCU JARVIS Kern-Traits + LLM-Integration

| # | Feature | Status | % | Was zu tun ist |
|---|---|---|---|---|
| S8#1 | Krisen-Modus | NEU | 0% | Humor komplett deaktivieren bei Critical-Events |
| S8#2 | Eigeninitiative | FERTIG | 80% | Autonomie-Engine + Safety-Caps. Nicht anfassen |
| S8#3 | {title} als Emotion | FERTIG | 100% | 40+ Verwendungen. Nicht anfassen |
| S8#4 | Loyalitaet | FERTIG | 70% | Ton + Frustration-Tracking. Nicht anfassen |
| S8#7 | Energy → Context | NEU | 0% | energy_optimizer an context_builder anbinden |
| S8#8 | Calendar → Context | NEU | 0% | calendar_intelligence an context_builder anbinden |

### Empfehlung: Priorisierung fuer maximalen Impact

**Session 1 — Persoenlichkeit & Identitaet (~3h):**
1. B1: core_identity.py — 30 Min, Fundament
2. A1: Few-Shot auf 7 Beispiele — 20 Min, sofort spuerbar
3. A2+A3+A7+A10: Prompt-Sektionen — je 15 Min, nur Text
4. A13: Kreative Problemloesung Prompt — 15 Min
5. S8#1: Krisen-Modus — 30 Min, Critical-Events → kein Humor
6. A4: Voice-Optimierung output_mode — 30 Min

**Session 2 — LLM-Intelligence (~4h):**
7. N1: Mood Detector → LLM — 1h, KRITISCH, steuert alles
8. D1: Task-aware Temperature — 30 Min, einfach + grosser Effekt
9. B10: Emotional Memory integrieren — 1h, Read-Pfad existiert
10. S8#7+S8#8: Energy + Calendar → Context — je 1h
11. N4: Parallel Tool Execution — 30 Min, Infrastruktur da

**Session 3 — Proaktivitaet & Gedaechtnis (~4h):**
12. N3: Multi-Turn Tool Calling — 2-3h, groesster Feature-Gewinn
13. B5: Inner State — 2h, JARVIS bekommt eigene Gefuehle
14. C3: Follow-ups proaktiv aufgreifen — 1h
15. C7: Butler-Instinkt Auto-Execution — 1h

**Session 4 — Erweiterte Intelligenz (~4h):**
16. B3: Pre-Compaction Memory Flush — 1-2h
17. B2: Proaktive Context Compaction — 1h
18. C5: Intent-Referenzierung "wie gestern" — 2h
19. D5: Quality Feedback → personality.py — 2h

**Spaeter / Niedrige Prioritaet:**
20. B4: Background Reasoning — GPU-Contention pruefen
21. C6: Semantic History Search — 3h
22. C9: Automation-Debugging — 2h
23. D3: Kontextuelles Schweigen — 1h
24. D6: Dynamic Few-Shot — abhaengig von D5
25. D7: Prompt-Versionierung — bei 2 Usern wenig Sinn
26. N6: JSON-Mode — Stabilitaet
27. B6: Relationship Model — Profiles befuellen
28. A5: Narrative Boegen — Callback zu Themen
29. B8: Dynamic Skill Acquisition — Abstrakte Konzepte
30. B12: Proaktives Selbst-Lernen — aktiv fragen

---

## Erwartetes Endergebnis (70-80% MCU JARVIS)

Nach allen Phasen + N-Features:

- **Klingt** wie MCU JARVIS (Humor, Timing, Pushback, Empathie)
- **Handelt** wie MCU JARVIS (proaktiv, eigenstaendig, vorausschauend)
- **Denkt** wie MCU JARVIS (kreativ, vernetzt, reflektiert)
- **Fuehlt** wie MCU JARVIS (eigene Emotionen, Beziehungen)
- **Lernt** wie MCU JARVIS (aus Fehlern, aus Beobachtungen, durch Fragen)

### Verbleibende 20-30% (technische Limits)

- Piper TTS ohne Stimm-Expressivitaet (~10-15%) — kein hoerbarer Sarkasmus
- LLM-Reasoning-Tiefe (~5-10%) — Qwen3.5 35B ist sehr gut, aber nicht Frontier
- Latenz (~3-5%) — 0.5-2s vs. Echtzeit im Film
- **Mit TTS-Upgrade (Fish Speech, XTTS v2, Kokoro): 80-88% erreichbar**
