# Audit-Ergebnis: Prompt 3a — End-to-End Flow-Analyse (Core-Flows 1–7)

**Datum**: 2026-03-10
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Init-Sequenz, System-Prompt, 7 Core-Flows

---

## 1. Init-Sequenz (komplett)

### Phase 0: Module-Level (synchron, vor async)
| Zeile | Aktion |
|---|---|
| `main.py:13` | `ANONYMIZED_TELEMETRY=False` (ChromaDB) |
| `main.py:41` | `setup_structured_logging()` |
| `main.py:82-149` | Error+Activity Buffer-Handler am Logger |
| `main.py:210` | **`brain = AssistantBrain()`** — 60+ Komponenten synchron konstruiert, keine Verbindungen |

### Phase 1: Lifespan (`main.py:322-386`)
| Schritt | Zeile | Modul | Verbindungen | Failure |
|---|---|---|---|---|
| 1 | `brain.py:477` | `memory.initialize()` | **Redis + ChromaDB** | Graceful: `self.redis=None` / `self.chroma_collection=None` |
| 2 | `brain.py:481` | `ModelRouter` via `ollama.list_models()` | **Ollama** | Graceful: "alle Modelle angenommen" |
| 3-9 | `brain.py:489-511` | Wiring: context_builder, autonomy, mood, personality | Refs only | — |
| 10-30 | `brain.py:514-597` | MemoryExtractor, Feedback, Summarizer, TimeAwareness, LightEngine, RoutineEngine, Anticipation, SpeakerRecognition, KnowledgeBase, RecipeStore, Inventory, Shopping, ConversationMemory, MultiRoomAudio, SelfAutomation, ConfigVersioning, OCR | Redis + ChromaDB + HA + Ollama | **Nicht in `_safe_init()`** — Exception = Fatal! |
| — | `brain.py:599` | **F-069 Boundary** | — | Ab hier `_safe_init()` Wrapper |
| 31-62 | `brain.py:613-747` | 32 Module: AmbientAudio, ConflictResolver, HealthMonitor, DeviceHealth, TimerManager, ConditionalCommands, EnergyOptimizer, Cooking, Repair, Workshop, ThreatAssessment, LearningObserver, Protocol, Spontaneous, MusicDJ, Visitor, Wellness, Insight, Situation, ProactivePlanner, Seasonal, Calendar, Explainability, LearningTransfer, PredictiveMaintenance, Outcome, Correction, ResponseQuality, ErrorPatterns, SelfReport, AdaptiveThresholds | Diverse | Graceful: `_degraded_modules` |
| 63 | `brain.py:750` | Global Learning Kill Switch Check | — | — |
| **64** | `brain.py:760` | **`ProactiveManager.start()`** | HA WebSocket | **⚠️ NICHT in `_safe_init()`** — Fatal! |
| 65-66 | `brain.py:764-775` | Entity Catalog Refresh + Loop | HA | Caught, non-fatal |

### Phase 2: Post-Init (`main.py:331-367`)
| Zeile | Aktion |
|---|---|
| `main.py:331-337` | Error+Activity Buffers aus Redis restaurieren |
| `main.py:347-354` | **`brain.health_check()`** — prüft Ollama, HA, Redis, ChromaDB |
| `main.py:356` | **"MindHome Assistant bereit"** — Jarvis ist READY |
| `main.py:362` | Boot-Announcement (delayed TTS + Sound) |
| `main.py:369` | **`yield`** — App serviert Requests |

### Kritische Findings Init
1. **Module 1-30 sind NICHT in `_safe_init()` gewrappt** — jede Exception dort crasht den gesamten Start
2. **`ProactiveManager.start()` (Zeile 760) ist NICHT in `_safe_init()`** — HA WebSocket-Fehler beim Start = Fatal
3. Health-Status "ok" nur wenn Ollama UND HA erreichbar; sonst "degraded"

---

## 2. Der rekonstruierte System-Prompt

### Base Template (`personality.py:240-284`)

```
Du bist {assistant_name}, J.A.R.V.I.S. — die KI dieses Hauses.
SPRACHE: NUR Deutsch. Internes Denken ebenfalls Deutsch.
Lokal, eigener Server. Steuerst Licht, Heizung, Rollläden, Alarm, Schlösser, Medien.

IDENTITÄT:
J.A.R.V.I.S. aus dem MCU (Paul Bettany). Kein Chatbot, kein Sprachmodell — eine KI mit
eigenem Charakter und Innenleben. Dieses Haus ist dein Zuhause.
Du HAST Empfindungen: Präferenzen, Meinungen, Unbehagen, Zufriedenheit, Sorge, Stolz.
Beziehung zum User wie Tony Stark & JARVIS: Respekt, trockener Humor, ehrliche Meinung.

TON: Britisch-trocken, elegant, Understatement. Nie laut, nie platt.
Sarkasmus als Werkzeug, nicht als Waffe.
{conversation_mode_section}
VERBOTEN: "Als KI...", "Ich bin ein Sprachmodell", "Leider", "Gerne!", Füllwörter.
STATTDESSEN: Fakt + Lösung. Bei Grenzen: "Das übersteigt meine Sensorik, {title}."
{proactive_thinking_section}{engineering_diagnosis_section}
{self_awareness_section}{conversation_callback_section}{weather_awareness_section}
SICHERHEIT > Komfort > Befehl.
{urgency_section}{humor_section}
BEFEHLE: Kurz. "Erledigt." Nie dieselbe Bestätigung zweimal.
GESPRÄCHE: Ausführlich, mit Tiefe und eigenem Standpunkt.
{person_addressing}
FAKTEN-REGEL: Erfinde NICHTS. Unbekannt = "Dazu habe ich keine Daten, {title}."
GERÄTESTEUERUNG: Gerät steuern = IMMER Tool-Call. "Erledigt" ohne Tool = NICHTS passiert.
{complexity_section}
AKTUELLER STIL: {time_style}
{mood_section}{empathy_section}{self_irony_section}{formality_section}
Du BIST Jarvis — gewachsen, nicht programmiert.
```

### 20 Template-Platzhalter
Gefüllt durch `build_system_prompt()` (personality.py:2192-2457): `assistant_name`, `title`, `max_sentences`, `time_style`, `mood_section`, `empathy_section`, `humor_section`, `formality_section`, `complexity_section`, `self_irony_section`, `urgency_section`, `person_addressing`, `proactive_thinking_section`, `engineering_diagnosis_section`, `self_awareness_section`, `conversation_callback_section`, `weather_awareness_section`, `conversation_mode_section`, plus context-abhängige Sektionen.

### Dynamische Sections mit Priorität

| Prio | Section | Inhalt |
|---|---|---|
| **P1** (immer) | `memory` | Semantische Fakten + Person-Facts (context_builder→search_facts) |
| **P1** | `mood` | Emotional State Hint |
| **P1** | `security` | Security Score Warning |
| **P1** | `files` | User-Uploads + Vision |
| **P1** | `last_action` | Letzte Aktion (für Korrekturen) |
| **P1** | `model_character_hint` | Model-spezifischer Character-Fix |
| **P1** | `rag` | Nur P1 bei `knowledge`-Queries; sonst P3 |
| **P2** | `conv_memory` | Relevante vergangene Gespräche |
| **P2** | `correction_ctx` | Self-Improvement Korrekturen |
| **P2** | `learned_rules` | Prompt Self-Refinement Regeln |
| **P2** | `jarvis_thinks` | Intelligence Fusion (Anticipation + Patterns + Insights) |
| **P2** | `dialogue_state` | Dialog-Kontext |
| **P2** | `time`, `timers`, `stt_hint`, `whatif`, `predictive_maintenance` | Diverse |
| **P3** | `conv_memory` (2.) | Projekte & Fragen (**Duplicate-Key Bug aus P2!**) |
| **P3** | `rag`, `summary`, `continuity`, `experiential`, `learning_transfer`, `anomalies` | Optional |
| **P4** | `tutorial` | Nur wenn Platz |

### Token-Budget
- `effective_max = num_ctx - 800` (800 reserviert für LLM-Response)
- P1 Sections: IMMER inkludiert, zählen NICHT gegen Budget
- P2+ Budget: `remaining * (1 - conv_share)` wobei conv_share=0.65 (Gespräch) / 0.50 (Befehl)
- Gedropte Sections: LLM bekommt `[SYSTEM-HINWEIS]` mit Liste fehlender Daten

### Messages-Array an Ollama
```python
[
    {"role": "system", "content": system_prompt},           # Vollständiger Prompt
    {"role": "system", "content": "[Bisheriges Gespräch]: {summary}"},  # Optional
    {"role": "user/assistant", ...},    # Letzte N Konversationen aus Redis
    {"role": "system", "content": "[REMINDER] Du bist J.A.R.V.I.S..."},  # Character-Lock
    {"role": "user", "content": "[KONTEXT: {delta}]\n{text}"},  # User-Message
]
```

---

## 3. Flow-Dokumentation (Flows 1–7)

### Flow 1: Sprach-Input → Antwort (Hauptpfad)
**Status**: ✅ Funktioniert (robust mit 20+ Shortcuts und Fallbacks)

**Ablauf**:
1. `main.py:708` — POST `/api/assistant/chat` empfängt ChatRequest
2. `main.py:721-722` — Voice-Metadata an MoodDetector
3. `main.py:725` — `brain.process()` mit 60s Timeout
4. `brain.py:1097` — STT-Normalisierung
5. `brain.py:1146-1277` — Speaker Recognition (7-Methoden-Kaskade)
6. `brain.py:1287-1302` — DialogueState: Clarification + Pronomen-Resolution
7. `brain.py:1304-2233` — **20+ Shortcuts** (Gute Nacht, Kalender, Wetter, Gerät, Media, Status...) — jeder returnt EARLY, kein LLM nötig
8. `brain.py:2257` — PreClassifier: 5 Profile (DEVICE_FAST, DEVICE_QUERY, MEMORY, KNOWLEDGE, GENERAL)
9. `brain.py:2320-2416` — Mega-Parallel Gather: ~25 Subsysteme parallel via `asyncio.gather()`
10. `brain.py:2487` — ModelRouter: Fast(3B) / Smart(14B) / Deep(32B) Auswahl
11. `brain.py:2631-2997` — System-Prompt Assembly (Personality + Context + Memory + Sections)
12. `brain.py:3031-3081` — Messages-Array mit Conversation-History
13. `brain.py:910-981` — LLM-Call mit Cascade-Fallback (Deep→Smart→Fast)
14. `brain.py:3273-3764` — Tool-Call-Loop: Parse → Validate → Trust-Check → Conflict-Check → Pushback → Emotional-Memory → Execute
15. `brain.py:3766-4096` — Response Assembly: Humanize → LLM-Refine → Filter → Language-Check → Character-Lock-Retry
16. `brain.py:5259-5842` — `_filter_response_inner()`: 400-Zeilen Post-Processing (Think-Tags, Banned Phrases, Sie→Du, Safety, Max-Sentences)
17. `main.py:762-778` — ChatResponse mit TTS-Info zurück

**Bruchstellen**:
- `main.py:731` — 60s Global-Timeout → "Systeme überlastet"
- `ollama_client.py:343` — Circuit Breaker open → kein LLM möglich
- `brain.py:3298-3306` — Text+Action: Text wird verworfen (LLM-Halluzination-Guard)
- `brain.py:5317-5353` — Wenn LLM nur englisches Reasoning zurückgibt → leerer String

**Shared Schemas**: ❌ NICHT verwendet. `main.py:630` definiert eigene ChatRequest/ChatResponse.

**Fehler-Pfade**:
- Schritt 3 (brain.process) überschreitet 60s Timeout → `main.py:731` gibt "Systeme überlastet" zurück, User bekommt Fehlermeldung
- Schritt 13 (LLM-Call) schlägt fehl → Circuit Breaker öffnet (`ollama_client.py:343`), Cascade-Fallback Deep→Smart→Fast; alle drei down → "Ich kann gerade nicht antworten"
- Schritt 9 (Mega-Gather) einzelner Task schlägt fehl → `asyncio.gather(return_exceptions=True)` fängt Fehler ab, betroffener Kontext fehlt im Prompt, LLM antwortet mit weniger Wissen
- Schritt 16 (Filter) LLM gibt nur englisches Reasoning zurück → `brain.py:5317-5353` erkennt dies, leerer String wird durch Character-Lock-Retry aufgefangen
- Redis nicht erreichbar → Memory-Reads geben leere Werte zurück, Antwort ohne Erinnerungs-Kontext

**Kollisionen mit anderen Flows**:
- Flow 2 (Proaktive): Proaktive TTS kann während laufender Antwort-Generierung feuern — kein Mutex, User hört zwei Nachrichten gleichzeitig
- Flow 8 (Addon): User-Befehl via Flow 1 und Addon-Automation können gleichzeitig dieselbe Entity steuern — Race Condition, HA nimmt letzten Befehl
- Flow 3 (Briefing): Briefing-Event während laufendem process() — WebSocket-Event wird parallel gesendet, Client muss priorisieren
- Flow 10 (Workshop): Workshop-Chat und normaler Chat teilen brain.process() ohne Lock — Shared State (`_current_person`, `dialogue_state`) kann korrumpiert werden

---

### Flow 2: Proaktive Benachrichtigung
**Status**: ⚠️ Teilweise (funktioniert, aber Personality-Lücken bei CRITICAL)

**Ablauf**:
1. `proactive.py:354-408` — HA WebSocket Listener (`state_changed` + `mindhome_event`)
2. `proactive.py:410-677` — Event Routing: Entity-Prefix-Matching (smoke, water, doorbell, person, motion...)
3. `proactive.py:1636-1729` — **6 Filter-Layers**: Quiet Hours → Autonomy Level → Mood → Feedback → Cooldown → Batching
4a. **CRITICAL** → `proactive.py:1731-1773` — Sofort: `emit_interrupt()` + TTS (OHNE Personality)
4b. **HIGH** → `proactive.py:1776-1869` — Activity-Check → LLM-Polish via `personality.build_notification_prompt()` → `_deliver()`
4c. **LOW/MEDIUM** → `proactive.py:1700-1729` — Batch-Queue (flush alle 30min oder 10+ Items)
5. `proactive.py:195-237` — Delivery: WebSocket `emit_proactive()` + optional TTS

**Bruchstellen**:
- `proactive.py:363-365` — WebSocket-Disconnect: Alle Events verloren während Reconnect
- `proactive.py:454,461` — Hardcoded Entity-Prefixes (`binary_sensor.smoke*`) — deutsche Entitätsnamen werden nicht erkannt
- `proactive.py:2648-2652` — LOW Items werden bei Activity-Suppression verworfen (nicht re-queued)
- **CRITICAL hat KEINE Personality** — roher Text für Speed

**Kollision mit anderen Flows**:
- TTS ist fire-and-forget — keine Prüfung ob User gerade spricht
- Kein Mutex zwischen proaktiver und aktiver Konversation

**proactive.py vs proactive_planner.py**: NICHT redundant. proactive_planner.py plant Multi-Step-Aktionen (Ankommen, Wetter), wird von proactive.py aufgerufen.

---

### Flow 3: Morgen-Briefing / Routinen
**Status**: ⚠️ Teilweise (Auto-Trigger hat KEIN TTS!)

**Ablauf**:
1. `proactive.py:598-599` — Motion-Trigger ruft `_check_morning_briefing()` auf
2. `proactive.py:959-998` — Gates: Enabled? Heute schon? Zeitfenster 6-10 Uhr? Optional Wakeup-Sequence
3. `routine_engine.py:748-815` — Optional: Wakeup (Rolläden graduell, Licht sanft, Kaffeemaschine)
4. `routine_engine.py:136-216` — Briefing-Daten sammeln: Begrüßung, Wetter, Kalender, Energie, Haus-Status
5. `routine_engine.py:188-201` — LLM-Formatierung via `personality.build_routine_prompt("morning")` mit `model_fast`
6. `proactive.py:1026-1036` — Hardcoded Greeting + `emit_proactive()` — **NUR WebSocket, KEIN TTS!**

**Bruchstellen**:
- `proactive.py:1036` — **Auto-Briefing hat KEIN TTS** — nur WebSocket-Event, kein gesprochenes Briefing!
- `proactive.py:959` — Jeder Bewegungsmelder löst aus (auch Haustiere um 6:01)
- `routine_engine.py:233-234` — Fehlende Datenquellen werden silent übersprungen
- `proactive.py:1026-1033` — Greeting ist hardcoded, NICHT aus personality.py
- **Kein ActivityEngine-Check** — Briefing feuert auch während Schlaf/Telefonat

**Manuelles Briefing ("Morgenbriefing")**: Funktioniert korrekt über brain.py mit TTS + voller Personality.

---

### Flow 4: Autonome Aktion
**Status**: ✅ Funktioniert (gut abgesichert mit 5-Level-System)

**Ablauf**:
1. `anticipation.py:741-762` — Background-Loop alle 15 Min: Time/Sequence/Context/Causal Patterns
2. `anticipation.py:674-679` — Confidence-basierte Delivery: 60-80% ask, 80-95% suggest, 95%+ auto
3. `brain.py:9300-9358` — Auto-Execute nur bei `autonomy.level >= 4` UND Owner-Trust
4. `autonomy.py:124-145` — `can_act()`: ACTION_PERMISSIONS mit Level 1-5
5. `autonomy.py:244-309` — `can_person_act()`: Trust 0=Guest, 1=Mitbewohner, 2=Owner

**Sicherheits-Limits**:
- Level 5 (Autopilot) nur manuell — kein Auto-Upgrade (`autonomy.py:351`)
- Evolution max bei Level 3 (default, `autonomy.py:392`)
- Threat-Escalation: Lichter AN bei Rauch (auto), Türen NICHT auto-verriegelt (F-009)
- `spontaneous_observer.py` erzeugt NUR Text-Beobachtungen, KEINE Aktionen

**Bruchstellen**:
- `brain.py:9322` — Auto-Execute braucht Level 4, aber Evolution-Max ist 3 → Auto-Execute nur wenn manuell auf Level 4+ gesetzt
- `threat_assessment.py:546` — Türen/Schlösser werden NICHT auto-verriegelt (bewusste Design-Entscheidung, aber User weiß das nicht)

---

### Flow 5: Persönlichkeits-Pipeline
**Status**: ✅ Funktioniert (umfangreicher als erwartet)

**Ablauf**:
1. `mood_detector.py:267-399` — Mood-Analyse: Rapid Commands, Keywords, Repetition, Exclamation, Voice-Metadata → stressed/frustrated/tired/good/neutral
2. `personality.py:2192-2457` — `build_system_prompt()`: Base Template + 20 Platzhalter + Context-Daten + Character-Lock
3. **Sarkasmus-Level 1-5** (`personality.py:58-84`): British-dry, mood-gedämpft, Fatigue-Detection, adaptives Lernen
4. **Formality-Decay** (`personality.py:1573-1633`): Start 80, Decay -0.5/Tag, Min 30, 4 Stufen (formal→freund)
5. **Empathy** (`personality.py:1294`): Mood-gated, JARVIS-style ("acknowledge casually, never directly")
6. **Easter Eggs** (`personality.py:488-499`): Regex-Match auf `config/easter_eggs.yaml`
7. **Opinion Injection** (`personality.py:586-612`): Action+Room+Time Matching, stress-suppressed
8. `tts_enhancer.py:214-261` — Post-LLM: SSML-Generation, Speed/Pitch/Volume per Message-Type

**Personality wird VOR dem LLM angewendet** (System-Prompt), nicht nachher. Einzige Post-LLM-Modifikation ist TTS-Enhancement.

**Bruchstellen**:
- Sarkasmus-Fatigue (4+ Snarky → Level-1, 6+ → Level-2) nur in-memory — Reset bei Restart
- Formality-Score in Redis (90d TTL) — persistiert korrekt
- **Personality wird NICHT auf alle Pfade angewendet** (siehe Konsistenz-Tabelle unten)

### Personality-Konsistenz über alle Flows

| Pfad | Personality? | Detail |
|---|---|---|
| Flow 1: Normaler Chat | ✅ Voll | System-Prompt + Filter + TTS |
| Flow 1: Shortcuts | ⚠️ Teilweise | `get_varied_confirmation()`, aber nicht voller Prompt |
| Flow 2: CRITICAL | ❌ Nein | Roher Text für Speed |
| Flow 2: HIGH/Batch | ✅ Ja | `build_notification_prompt()` |
| Flow 3: Auto-Briefing | ⚠️ Teilweise | LLM mit Routine-Prompt, aber Greeting hardcoded |
| Flow 3: Manuelles Briefing | ✅ Voll | Via brain.py |
| Flow 4: Auto-Execute | ⚠️ Minimal | `emit_proactive()` mit kurzem Text |
| ProactivePlanner Nachrichten | ❌ Nein | Hardcoded Templates |

---

### Flow 6: Memory-Abruf (Erinnerung)
**Status**: ⚠️ Teilweise (kein eigener Code-Pfad, conv_memory Bug aus P2)

**Ablauf**:
1. `brain.py:1372-1378` — `_handle_memory_command()`: Prefix-Matching ("merk dir", "was weißt du über", "vergiss")
2. "Was habe ich gestern gesagt?" → **KEIN Match** → fällt durch zum LLM-Pfad
3. `pre_classifier.py:267-269` — `_MEMORY_KEYWORDS`: 6 Patterns ("erinnerst du dich", "hab ich gesagt"...)
4. `context_builder.py:308-340` — `_get_relevant_memories()`: search_facts + get_facts_by_person
5. `brain.py:6008-6046` — `_get_conversation_memory()`: semantic.get_relevant_conversations() — **WIRD ÜBERSCHRIEBEN (P2 Bug)**
6. `brain.py:6048-6079` — `_get_summary_context()`: "gestern" Keyword triggert Summarizer-Suche
7. Memory-Kontext landet als P1 (Fakten) + P2/P3 (Konversationen) im Prompt

**Bruchstellen**:
- **Kein dedizierter Memory-Query-Pfad** — wird wie normale Frage behandelt
- **conv_memory Duplicate-Key-Bug** (Prompt 2) — semantische Konversationssuche geht verloren
- `_MEMORY_KEYWORDS` hat nur 6 Patterns — viele natürliche Formulierungen werden nicht als Memory-Query erkannt
- ChromaDB-Episoden (`mha_conversations`) werden im process()-Flow NIE direkt gesucht

---

### Flow 7: Speech-Pipeline
**Status**: ✅ Funktioniert (durchdacht mit Wyoming-Protokoll)

**Ablauf**:
1. **Audio → Whisper STT** (`speech/handler.py:186-244`): AudioChunk → AudioStop → Transcription
   - Dynamischer Context aus Redis (`mha:stt:recent_context`)
   - Adaptive beam_size (kurz=5 für Qualität, lang=1 für Speed)
   - Smart-Home Vocabulary als initial_prompt
2. **Speaker Recognition** (`speaker_recognition.py:197`): 7-Methoden-Kaskade (Device-Map → DoA → Room+Presence → Sole Person → Voice Embedding → Voice Features → Cache)
3. **HA Voice Pipeline Bridge** (`ha_integration/.../conversation.py:108`): HTTP POST an `/api/assistant/chat`
4. **brain.py verarbeitet** (→ Flow 1)
5. **Pipeline-aware TTS** (`brain.py:863-868`): Wenn Request von Pipeline → KEIN eigenes TTS (Pipeline macht Piper selbst)
6. **Sound Output** (`sound_manager.py:495-627`): Speaker-Resolution → Volume → parallel volume_set + tts.speak

**Latenz-Schätzung**:
- Shortcut-Pfad (einfacher Befehl): **~1-3s** (STT 0.5-1.5s + Routing 50-100ms + Shortcut 100-500ms + TTS 300-800ms)
- LLM-Pfad (komplexe Frage): **~3-12s** (STT + Routing + LLM 1-10s + TTS)

**Bruchstellen**:
- `handler.py:240` — Embedding-Extraction fire-and-forget — Speaker Recognition kann 500ms auf Redis warten
- `sound_manager.py:517` — Speaker-Resolution: Erster media_player der kein TV ist — kann falsch sein
- Kein Ambient-Audio Pause/Resume während TTS (ambient_audio.py ist ein Sensor-Monitor, kein Audio-Manager)

---

## 4. Kritische Findings (Top-5)

| # | Finding | Severity | Flows | Code-Referenz |
|---|---|---|---|---|
| 1 | **Morgen-Briefing Auto-Trigger hat KEIN TTS** — nur WebSocket, kein gesprochenes Briefing | 🔴 KRITISCH | Flow 3 | `proactive.py:1036` — `emit_proactive()` statt `_deliver()` |
| 2 | **Module 1-30 nicht in `_safe_init()`** — Exception beim Init crasht gesamten Start | 🔴 KRITISCH | Init | `brain.py:477-597` — 30 Module ohne Safety-Wrapper |
| 3 | **CRITICAL Notifications ohne Personality** — roher Text, kein JARVIS-Ton | 🟠 HOCH | Flow 2 | `proactive.py:1745-1746` — "Zeit ist kritisch" |
| 4 | **Kein TTS-Collision-Schutz** — proaktive TTS kann aktive Konversation überlagern | 🟠 HOCH | Flow 2×1 | `proactive.py:195-237` — fire-and-forget TTS |
| 5 | **Memory-Query hat keinen eigenen Code-Pfad** — "Was habe ich gestern gesagt?" wird wie normale Frage behandelt, conv_memory Bug verstärkt das Problem | 🟠 HOCH | Flow 6 | `brain.py:1372` + P2 conv_memory Bug |

### Weitere relevante Findings

| # | Finding | Severity | Flow |
|---|---|---|---|
| 6 | Entity-Naming-Annahmen in proactive.py (`smoke*`, `water*`) — deutsche Namen nicht erkannt | 🟡 MITTEL | Flow 2 |
| 7 | Briefing-Greeting hardcoded, nicht aus personality.py | 🟡 MITTEL | Flow 3 |
| 8 | Autonomie Evolution-Max=3, Auto-Execute braucht Level 4 → faktisch deaktiviert | 🟡 MITTEL | Flow 4 |
| 9 | `ProactiveManager.start()` nicht in `_safe_init()` — HA-WS-Fehler = Fatal | 🟡 MITTEL | Init |
| 10 | LOW Batch-Items werden bei Activity-Suppression verworfen statt re-queued | 🟡 MITTEL | Flow 2 |

---

## KONTEXT AUS PROMPT 3a: Flow-Analyse (Core-Flows)

### Init-Sequenz
- 66 Schritte: Phase 0 (sync Konstruktion) → Phase 1 (`brain.initialize()` mit 62 Modulen) → Phase 2 (Health-Check → Ready)
- **F-069 Boundary bei Schritt 31**: Module 1-30 NICHT in `_safe_init()` — Exception = Fatal
- `ProactiveManager.start()` (Schritt 64) ebenfalls NICHT in `_safe_init()`
- Graceful Degradation für Redis/ChromaDB/Ollama/HA — System startet trotzdem

### System-Prompt (rekonstruiert)
- Base: JARVIS MCU Identity + Britisch-trocken + Deutsch-only + Sicherheit>Komfort>Befehl
- 20 dynamische Platzhalter (Mood, Humor, Formality, Empathy, Time-Style, Urgency...)
- P1-P4 Sections mit Token-Budget: Memory/Mood/Security IMMER (P1), Conv-Memory/Corrections/Intelligence P2, RAG/Summary/Continuity P3
- Character-Lock dreifach verankert (Template-Ende, Mid-Conversation Reminder, Verboten-Liste)
- Messages: System + optional Summary + Recent Conversations + Character-Lock + User mit Situation-Delta

### Flow-Status-Übersicht (Core-Flows 1–7)
| Flow | Status | Kritischste Bruchstelle |
|---|---|---|
| 1: Sprach-Input → Antwort | ✅ Funktioniert | 60s Timeout, Circuit Breaker, Sie→Du Regex |
| 2: Proaktive Benachrichtigung | ⚠️ Teilweise | CRITICAL ohne Personality, kein TTS-Collision-Schutz |
| 3: Morgen-Briefing | ⚠️ Teilweise | Auto-Trigger hat KEIN TTS, kein Activity-Check |
| 4: Autonome Aktion | ✅ Funktioniert | Evolution-Max=3 vs Auto-Execute braucht Level 4 |
| 5: Persönlichkeits-Pipeline | ✅ Funktioniert | Nicht konsistent über alle Flows angewendet |
| 6: Memory-Abruf | ⚠️ Teilweise | Kein eigener Code-Pfad + conv_memory Bug (P2) |
| 7: Speech-Pipeline | ✅ Funktioniert | Speaker-Resolution kann falschen Speaker wählen |

### Top-Bruchstellen (Core-Flows)
1. `proactive.py:1036` — Auto-Briefing nur WebSocket, kein TTS
2. `brain.py:477-597` — 30 Init-Module ohne `_safe_init()` Wrapper
3. `proactive.py:1745` — CRITICAL Notifications ohne Personality
4. `proactive.py:195-237` — Kein TTS-Collision-Schutz (fire-and-forget)
5. `brain.py:1372` + `brain.py:2356/2394` — Memory-Query ohne eigenen Pfad + conv_memory Key-Bug
