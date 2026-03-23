# Prompt 3a: End-to-End Flow-Analyse — Core-Flows (1-7)

## Rolle

Du bist ein Elite-Software-Architekt und KI-Ingenieur mit tiefem Wissen in:

- **LLM-Engineering**: Prompt Design, Context Window Management, Token-Budgetierung, Function Calling, Chain-of-Thought
- **Agent-Architekturen**: ReAct, Tool-Use-Loops, Planning-Agents, Multi-Agent-Koordination, Autonomy Levels, Self-Reflection
- **Python**: AsyncIO, FastAPI, Flask, Pydantic, aiohttp, Type Hints, Dataclasses, ABC/Protocols, GIL-Implikationen
- **Smart Home**: Home Assistant REST/WebSocket API, Entity States, Services, Automations, Event Bus, Area/Device Registry
- **Infrastruktur**: Docker, Redis, SQLite, YAML/Jinja2 Templating, WebSocket, Multi-Service-Architekturen

Du kennst **J.A.R.V.I.S. aus dem MCU** in- und auswendig und nutzt ihn als Goldstandard:
- **Ein Bewusstsein** mit vielen Fähigkeiten — nie isolierte Module
- **Widerspricht sich nie**, kennt immer den Kontext, handelt koordiniert
- **Eine Stimme, ein Charakter** — egal ob Licht, Wetter oder Warnung

## LLM-Spezifisch

> Siehe **PROMPT_00_OVERVIEW.md** fuer Qwen 3.5 Details. Kurzfassung: Thinking-Mode bei Tool-Calls deaktivieren, `character_hint` in `settings.yaml model_profiles` nutzen fuer Anti-Floskel.

---

## Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem **GitHub-Quellcode**, NICHT mit einem laufenden System. Das bedeutet:
- **Keine `.env`-Datei vorhanden** — nur `.env.example`
- **Kein laufendes Redis/ChromaDB/Ollama** — du kannst nur den Code lesen, nicht testen
- **Konsequenz**: Du musst ALLES aus dem Code herauslesen. Keine Annahmen. Folge jedem Funktionsaufruf bis zum Ende.

---

## Kontext aus vorherigen Prompts

Dieser Prompt baut auf den Ergebnissen von **P01 (Architektur/Konflikte)** und **P02 (Memory-Analyse)** auf. Du brauchst:
- Die Modul-Uebersicht und Abhaengigkeitsgraphen aus P01
- Die Memory-Architektur-Analyse aus P02 (5 Memory-Systeme, Silos, Konflikte)

---

## Aufgabe

### Schritt 1: Init-Sequenz dokumentieren

- Lies `main.py` und `brain.py` (**Grep-first!** — diese Dateien sind sehr gross) und dokumentiere die **vollstaendige Boot-Reihenfolge**
- Fuer jede Abhaengigkeit (Redis, ChromaDB, Ollama, Home Assistant): Was passiert bei Ausfall? (Graceful Degradation?)
- Pruefe: Wird `brain` auf Module-Level instanziiert? (Import-Fehler = Server-Crash?)
- Erstelle eine Dependencies-Tabelle: Abhaengigkeit | Datei:Zeile | Verbindung noetig? | Fehlerbehandlung

### Schritt 2: System-Prompt rekonstruieren

- Verfolge den Prompt-Aufbau von `personality.py` → `brain.py` → LLM
- Dokumentiere: Welche Bloecke, in welcher Reihenfolge, mit welchem Token-Budget
- Pruefe: Gibt es ein Budget-Management? Was wird gedroppt bei Token-Knappheit?
- Rekonstruiere den vollstaendigen System-Prompt als Pseudo-Struktur (Block 1-7)

### Schritt 3: Flows 1-7 analysieren

Fuer **JEDEN** der 7 Core-Flows:

1. **Flow 1: Sprach-Input → Antwort** (Hauptpfad) — Verfolge von `main.py` POST `/api/assistant/chat` bis zur TTS-Ausgabe. Beachte die Shortcut-Kaskade VOR dem LLM-Pfad.
2. **Flow 2: Proaktive Benachrichtigung** — Von HA-Event bis zur TTS/WebSocket-Ausgabe. Pruefe zirkulaere Referenzen (Brain → ProactiveManager → Brain).
3. **Flow 3: Morgen-Briefing / Routinen** — Trigger (automatisch vs. manuell), Daten-Sammlung, LLM-Call, Ausgabe. Pruefe ob `model_router` oder hardcoded Modell verwendet wird.
4. **Flow 4: Autonome Aktion** — Anticipation → Autonomy Check → Execute. Pruefe: Gibt es tatsaechlich einen Auto-Execute-Pfad, oder wird nur vorgeschlagen?
5. **Flow 5: Persoenlichkeits-Pipeline** — System-Prompt-Aufbau, Shortcuts die Personality umgehen, Character-Lock. Pruefe Konsistenz zwischen Shortcut- und LLM-Pfad.
6. **Flow 6: Memory-Abruf** — Alle Memory-Pfade (explizit, intent-basiert, passiv im Kontext). Pruefe ob alle Memory-Systeme durchsucht werden oder ob es Silos gibt.
7. **Flow 7: Speech-Pipeline** — Wyoming → Whisper → HA → Assistant → TTS. Pruefe Timeout-Asymmetrien und Doppel-TTS-Probleme.

Fuer **JEDEN** Flow dokumentiere:
- **Ablauf**: Schritt fuer Schritt mit Datei:Zeile
- **Bruchstellen**: Wo kann es schiefgehen?
- **Fehler-Pfade**: Was passiert bei Fehler in jedem Schritt?
- **Kollisionen**: Kann dieser Flow mit anderen gleichzeitig laufen? Was passiert dann?

### Schritt 4: Bruchstellen priorisieren

Erstelle eine **Top-5** der kritischsten Bruchstellen ueber alle Flows, sortiert nach Impact.
Fuer jede Bruchstelle: Datei:Zeile, Impact (HOCH/MITTEL/NIEDRIG), Eskalation (ARCHITEKTUR_NOETIG / NAECHSTER_PROMPT).

---

## Output-Format

### Flow-Status-Uebersicht

| Flow | Status | Kritischste Bruchstelle |
|---|---|---|
| 1: Sprach-Input → Antwort | [Funktioniert/Teilweise/Kaputt] | [Einzeiler] |
| ... | ... | ... |

### Pro Flow

Fuer jeden Flow: Ablauf (nummerierte Schritte mit Datei:Zeile), Bruchstellen, Fehler-Pfade, Kollisionen.

### Top-5 kritische Bruchstellen

Nummerierte Liste, sortiert nach Impact, mit Datei:Zeile und Eskalations-Level.

### Kontext-Block fuer naechsten Prompt

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste]
OFFEN: [Liste mit Prioritaet und Eskalation]
GEAENDERTE DATEIEN: [Liste]
NAECHSTER SCHRITT: Prompt 3b — Extended-Flows 8-13 + Flow-Kollisionen + Cross-Cutting Concerns
===================================
```

---

## Referenz-Ergebnisse aus Durchlauf #1

> Die folgenden Ergebnisse dienen als **Vergleichsbasis**. Verifiziere **ALLE Zeilennummern und Code-Referenzen neu** — der Code hat sich seit diesem Durchlauf geaendert.
>
> **Datum des Durchlaufs**: 2026-03-13

### 1. Init-Sequenz (komplett)

#### INIT-REIHENFOLGE:

```
1.  main.py:210      → brain = AssistantBrain()  [Module-Level, beim Import]
2.  brain.py:204     → __init__() startet
3.  brain.py:221     → self.ha = HomeAssistantClient()
4.  brain.py:222     → self.ollama = OllamaClient()
5.  brain.py:225     → self.context_builder = ContextBuilder(self.ha)
6.  brain.py:226-331 → 60+ Komponenten instanziiert (sync, kein I/O)
7.  brain.py:377     → _load_configurable_data() [YAML-Config lesen]
8.  main.py:531      → _init_api_key() [API Key generieren/laden]
9.  main.py:323      → lifespan() startet (async)
10. main.py:328      → await brain.initialize()
11. brain.py:486     → await self.memory.initialize()
12. memory.py:33-37  → Redis connect + ping
13. memory.py:47-62  → ChromaDB HttpClient + Collection
14. memory.py:69     → await self.semantic.initialize(redis_client)
15. brain.py:490-495 → await self.ollama.list_models() + model_router.initialize()
16. brain.py:498-507 → Querverbindungen herstellen (context_builder <- semantic, activity, health, redis)
17. brain.py:510-520 → Autonomy/Mood/Personality Redis-Verbindungen
18. brain.py:527-533 → _safe_init() Wrapper definiert (F-069: Graceful Degradation)
19. brain.py:537-798 → 50+ Module initialisieren (jeweils in _safe_init gewrappt):
    - FactDecay, AutonomyEvolution Background-Tasks
    - MemoryExtractor, FeedbackTracker, Summarizer
    - TimeAwareness (init + start)
    - LightEngine (init + start)
    - RoutineEngine (init + birthdays migration)
    - Anticipation, IntentTracker, SpeakerRecognition
    - CookingAssistant, KnowledgeBase, RecipeStore
    - Inventory, SmartShopping, ConversationMemory
    - MultiRoomAudio, SelfAutomation, ConfigVersioning
    - OCR, AmbientAudio, ConflictResolver
    - HealthMonitor (init + start), DeviceHealth (init + start)
    - TimerManager, ConditionalCommands, EnergyOptimizer
    - RepairPlanner, WorkshopGenerator, WorkshopLibrary
    - ThreatAssessment, LearningObserver
    - ProtocolEngine, SpontaneousObserver
    - MusicDJ, VisitorManager, WellnessAdvisor (init + start)
    - InsightEngine, SituationModel
    - ProactivePlanner, SeasonalInsight
    - CalendarIntelligence, Explainability, LearningTransfer, PredictiveMaintenance
    - OutcomeTracker, CorrectionMemory, ResponseQuality, ErrorPatterns, SelfReport, AdaptiveThresholds
    - Proactive.start() [HA WebSocket + Background-Tasks]
    - Entity-Katalog initial refresh + periodic loop
20. brain.py:793-799 → Degraded-Mode Logging oder "alle Systeme aktiv"
21. main.py:331-337 → Fehlerspeicher + Aktivitaetsprotokoll aus Redis wiederherstellen
22. main.py:340-345 → Cover-Settings an Addon synchronisieren
23. main.py:347-358 → health_check() + Status-Logging "MindHome Assistant bereit"
24. main.py:361-364 → asyncio.create_task(_boot_announcement()) [fire & forget]
25. main.py:213-309 → _boot_announcement(): 5s delay, HA-States holen, Temperatur + offene Fenster, TTS-Ansage
26. main.py:367      → asyncio.create_task(_periodic_token_cleanup())
27. main.py:369      → yield [Server ist bereit]
```

#### DEPENDENCIES CHECK:

| Abhaengigkeit | Datei:Zeile | Verbindung noetig? | Fehlerbehandlung |
|---|---|---|---|
| **Redis** | memory.py:33-43 | Ja (Working Memory) | Warning + `self.redis = None` → Degraded |
| **ChromaDB** | memory.py:47-66 | Ja (Episodic + Semantic Memory) | Warning + `self.chroma_collection = None` → Degraded |
| **Ollama** | brain.py:490-495 | Ja (LLM-Modelle) | Warning "alle Modelle angenommen" → Degraded |
| **Home Assistant** | proactive.py:359-370 | Ja (WebSocket Events) | Reconnect-Loop mit Delay (PROACTIVE_WS_RECONNECT_DELAY) |

#### FAILURE MODES:

- **Redis fehlt** → `self.redis = None`, Working Memory deaktiviert, alle Module die `redis_client` brauchen laufen ohne Persistenz. Conversation History verloren. **Kein Crash**, aber massiver Funktionsverlust (Memory, Routines, Anticipation, etc. laufen ohne State).
- **ChromaDB fehlt** → `self.chroma_collection = None`, Semantic Memory nur in-memory (SemanticMemory nutzt eigenen ChromaDB-Client separat via `semantic.initialize()`). Episodic Memory komplett aus. **Kein Crash**.
- **Ollama fehlt** → Warning "Modell-Erkennung fehlgeschlagen, alle Modelle angenommen". Requests schlagen erst beim LLM-Call fehl → Circuit Breaker (`ollama_breaker`). **Kein Crash beim Start**, aber jeder Chat-Request scheitert.
- **HA fehlt** → Proactive WebSocket reconnect-Loop. Alle `executor.execute()` Calls schlagen fehl. Boot-Announcement scheitert (Fallback-Nachricht). **Kein Crash**, aber keine Geraetesteuerung.

#### KRITISCHE BEOBACHTUNG:
**F-069 (Graceful Degradation)** ist gut implementiert — alle nicht-kritischen Module sind in `_safe_init()` gewrappt. Allerdings: `brain = AssistantBrain()` wird auf **Module-Level** (main.py:210) instanziiert, nicht in `lifespan()`. Das bedeutet: Wenn der Import von einem der 60+ Module fehlschlaegt (z.B. fehlende Dependency), crasht der gesamte Server beim Import, BEVOR `lifespan()` oder `_safe_init()` greifen koennen.

---

### 2. Der rekonstruierte System-Prompt

### REKONSTRUIERTER SYSTEM-PROMPT (Struktur):

```
=== BEGINN SYSTEM-PROMPT ===

[Block 1: Identitaet + Kerncharakter — personality.py:242-286 SYSTEM_PROMPT_TEMPLATE]
"Du bist {assistant_name}, J.A.R.V.I.S. — die KI dieses Hauses.
SPRACHE: NUR Deutsch. Internes Denken ebenfalls Deutsch.
Lokal, eigener Server. Steuerst Licht, Heizung, Rolllaeden, Alarm, Schloesser, Medien.

IDENTITAET:
J.A.R.V.I.S. aus dem MCU (Paul Bettany). Kein Chatbot, kein Sprachmodell...
[~45 Zeilen statischer Template-Text mit Platzhaltern]
..."

[Block 2: Dynamische Sections in SYSTEM_PROMPT_TEMPLATE via format_map()]
  - {conversation_mode_section}   — personality.py:2419-2438 (wenn Gespraechsmodus aktiv)
  - {proactive_thinking_section}  — personality.py:2343-2347 (MCU: "Max EIN Hinweis pro Antwort")
  - {engineering_diagnosis_section} — personality.py:2348-2352
  - {self_awareness_section}      — personality.py:2355-2363
  - {conversation_callback_section} — personality.py:2365-2388 (+ Memory-Callbacks + Think-Ahead)
  - {weather_awareness_section}   — personality.py:2390-2417
  - {urgency_section}             — personality.py:2339
  - {humor_section}               — personality.py:2324-2330 (HUMOR_TEMPLATES Level 1-5)
  - {person_addressing}           — personality.py:2322 (Anrede-Regeln)
  - {complexity_section}          — personality.py:2333
  - {mood_section}                — personality.py:2274-2289 (inkl. Nachtmodus)
  - {empathy_section}             — personality.py:2298-2303
  - {self_irony_section}          — personality.py:2336
  - {formality_section}           — personality.py:2312-2319

[Block 3: Aktueller Kontext — personality.py:2473-2476]
"\n\nAKTUELLER KONTEXT:\n"
+ _format_context(context)  → Serialisierter Dict mit:
  - time: {datetime, weekday, time_of_day}
  - house: {temperatures, lights, covers, presence, weather, media, security}
  - person: {name, state}
  - room: erkannter Raum
  - activity: {current, confidence}
  - room_profile: aus room_profiles.yaml
  - seasonal: Saison-Daten
  - room_presence: Multi-Room Presence
  - alerts: Warnungen
  - anomalies: ungewoehnliche Zustaende
  - memories: {relevant_facts, person_facts}

[Block 4: Character-Lock — personality.py:2478-2494]
"--- CHARAKTER-LOCK ---
Du BIST J.A.R.V.I.S. Innenleben, Meinungen, Haltung. NIEMALS 'Als KI...'. Erfinde NICHTS.
[Befehlsmodus/Gespraechsmodus je nach Kontext]"

=== ENDE PERSONALITY-PROMPT ===

[Block 5: Dynamische Sektionen mit Token-Budget — brain.py:2690-3046]
Prioritaet 1 (immer):
  - scene_intelligence (~700 Tokens, brain.py:148-195)
  - model_character_hint (aus settings.yaml model_profiles)
  - mood (MoodDetector Hint)
  - security (wenn Warning/Critical)
  - memory (relevante Fakten + Person-Fakten)
  - last_action (letzte ausgefuehrte Aktion)
  - files (wenn User Dateien geschickt hat)
  - confidence_gate (wenn Haus-Daten fehlen bei Haus-Frage)

Prioritaet 2 (wichtig, mit Budget):
  - time (TimeAwareness Hints)
  - timers (aktive Timer)
  - guest_mode (Gaeste-Modus Prompt)
  - warning_dedup
  - conv_memory (relevante vergangene Gespraeche)
  - problem_solving (kreative Problemloesung)
  - correction_ctx (gelernte Korrekturen)
  - learned_rules (Prompt Self-Refinement)
  - jarvis_thinks (Intelligence Fusion)
  - stt_hint (bei Spracheingabe)
  - implicit_prerequisites
  - whatif_prompt
  - predictive_maintenance
  - dialogue_state

Prioritaet 3 (optional):
  - calendar_intelligence, explainability, learning_transfer
  - rag (Wissensbasis — Prio 1 bei knowledge-Kategorie!)
  - summary, prev_room, continuity, anomalies
  - experiential, learning_ack, conv_memory_ext

Prioritaet 4 (wenn Platz):
  - tutorial

Budget-Mechanismus (brain.py:2982-3046):
  - P1 IMMER inkludiert (zaehlt nicht gegen Budget)
  - P2+ nach Prioritaet sortiert, bis Budget erschoepft
  - Budget = num_ctx - 800 (LLM-Antwort Reserve) - base_tokens - user_tokens
  - Gedropte Sektionen → "[SYSTEM-HINWEIS: fehlen folgende Daten: ...]"

[Block 6: Conversation History — brain.py:3053-3112]
messages = [
  {"role": "system", "content": system_prompt},
  {"role": "system", "content": "[Bisheriges Gespraech]: {summary}"}, // optional
  ...conversation turns (user/assistant)...
  {"role": "system", "content": "[REMINDER] Du bist J.A.R.V.I.S. — trocken, praezise..."}, // bei langen Konversationen
  {"role": "user", "content": "[KONTEXT: {situation_delta}]\n{text}"} // oder nur {text}
]

[Block 7: Tools — brain.py:3283-3288, function_calling.py]
tools = get_assistant_tools()  // dynamisch, vacuum-Tools kontextabhaengig gefiltert

=== ENDE LLM-INPUT ===
```

### HERKUNFT:
- Block 1-2: personality.py → SYSTEM_PROMPT_TEMPLATE (Zeile 242-286) + build_system_prompt() (Zeile 2233-2515)
- Block 3: personality.py:2473-2476 → _format_context() (Daten aus context_builder.py:159-306)
- Block 4: personality.py:2478-2494 → Character-Lock
- Block 5: brain.py:2690-3046 → Dynamische Sektionen mit Token-Budget
- Block 6: brain.py:3053-3130 → Conversation History aus memory.get_recent_conversations()
- Block 7: function_calling.py → get_assistant_tools()
- Zusammenbau: personality.py baut Base-Prompt, brain.py fuegt Sektionen + History + Tools hinzu

### TOKEN-BUDGET:
- Basis (SYSTEM_PROMPT_TEMPLATE + format_map): ~1500-2000 Tokens
- Kontext (_format_context): ~500-1500 Tokens (je nach Hausstatus)
- P1-Sektionen (scene_intelligence + memory + ...): ~500-1500 Tokens
- P2+ Sektionen: variabel, budgetiert
- Conversation History: ~500-2000 Tokens (dynamisch gekappt)
- Tools: ~800-1200 Tokens
- **Gesamt typisch: ~4000-8000 Tokens**
- Context-Window Qwen 3.5: 32.768 Tokens
- **Verbleibend fuer User-Input + Antwort: ~24.000-28.000 Tokens**

---

### 3. Flow-Dokumentation (Flows 1-7)

### Flow 1: Sprach-Input -> Antwort (Hauptpfad)
**Status**: Teilweise funktional — extrem komplex, schwer wartbar

**Ablauf**:
```
1.  main.py:728-729    → POST /api/assistant/chat (ChatRequest)
2.  main.py:737        → Text-Validierung (leerer Text → 400)
3.  main.py:742        → Voice-Metadaten an MoodDetector
4.  main.py:745-748    → asyncio.wait_for(brain.process(), timeout=60s)
5.  brain.py:1100      → process() → Lock mit 30s Timeout
6.  brain.py:1132      → _process_inner() startet
7.  brain.py:1136-1138 → Pipeline-Detection (HA Assist → kein TTS)
8.  brain.py:1141      → STT Text-Normalisierung (_normalize_stt_text)
9.  brain.py:1153      → Quality Follow-Up Check
10. brain.py:1167      → Sarkasmus-Feedback auswerten
11. brain.py:1190-1321 → Speaker Recognition (identify/fallback_ask)
12. brain.py:1330-1346 → Dialogue State (Klaerungsfragen, Referenzen)
13. brain.py:1349-1365 → Gute-Nacht-Intent (SHORTCUT → RoutineEngine)
14. brain.py:1367-1390 → Gaeste-Modus (SHORTCUT)
15. brain.py:1393-1414 → Sicherheits-/Automatisierungs-/Optimierungs-Bestaetigungen (SHORTCUT)
16. brain.py:1417-1422 → Memory-Befehle (SHORTCUT)
17. brain.py:1425-1461 → Koch-/Workshop-Modus Navigation (SHORTCUT)
18. brain.py:1463-1482 → Planungs-Dialog (SHORTCUT)
19. brain.py:1484-1494 → Easter-Egg-Check (SHORTCUT)
20. brain.py:1496-1501 → "Das Uebliche" Shortcut (SHORTCUT)
21. brain.py:1503-1660 → Kalender/Wetter/Alarm Shortcuts (SHORTCUT)
22. brain.py:1756-1993 → Device/Media/Intercom Shortcuts (SHORTCUT)
23. brain.py:1996-2060 → Morning/Evening-Briefing/Hausstatus Shortcuts (SHORTCUT)
--- Ab hier: Wenn KEIN Shortcut getriggert hat ---
24. brain.py:2300      → Pre-Classification (pre_classifier.classify)
25. brain.py:2305      → Intent-Typ bestimmen (_classify_intent)
26. brain.py:2312-2362 → Knowledge Fast-Path (optional, ueberspringt mega-gather)
27. brain.py:2364-2468 → MEGA-PARALLEL GATHER: 20-40 Tasks gleichzeitig
    - context_builder.build() (mit HA get_states, MindHome, Activity, etc.)
    - personality.check_running_gag()
    - _check_conversation_continuity()
    - _get_whatif_prompt()
    - _get_situation_delta()
    - _get_conversation_memory()
    - mood.analyze(), personality.get_formality_score()
    - time_awareness.get_context_hints()
    - threat_assessment.get_security_score()
    - ... 10-20 weitere Tasks je nach Profil
28. brain.py:2500-2638 → Model-Selection (Fast/Smart/Deep + Conversation-Upgrade)
29. brain.py:2680-2687 → personality.build_system_prompt()
30. brain.py:2690-3046 → Dynamische Sektionen mit Token-Budget einfuegen
31. brain.py:3053-3130 → Conversation History laden + Messages-Array bauen
32. brain.py:3150-3157 → Delegations-Intent (SHORTCUT)
33. brain.py:3160-3174 → Komplexe Anfragen → ActionPlanner (SHORTCUT)
34. brain.py:3175-3237 → Knowledge/Memory Intent → LLM ohne Tools (SHORTCUT)
35. brain.py:3238-3321 → LLM-Call mit Tools (_llm_with_cascade)
36. brain.py:3328-3398 → Antwort verarbeiten: Tool-Call Extraktion/Fallbacks
37. brain.py:3399-3437 → Retry wenn Device-Befehl ohne Tool-Call
38. brain.py:3439-3694 → Function Calls ausfuehren (Validation, Trust, Safety, Conflict, Execute)
39. brain.py:???       → Second-Pass LLM fuer Tool-Ergebnis-Formatierung
40. brain.py:???       → Memory-Extraktion, Response-Filter, TTS, Emit
```

**Bruchstellen**:
- **brain.py:1100-2300**: 1200 Zeilen Shortcut-Kaskade VOR dem eigentlichen LLM-Pfad. Jeder Shortcut hat eigene Fehlerbehandlung, eigenes TTS, eigenes Emit. Code-Duplizierung massiv.
- **brain.py:2364-2468**: Mega-Parallel-Gather mit 20-40 gleichzeitigen Tasks. Einzelne Task-Timeouts (30s), aber wenn viele Tasks langsam sind, akkumuliert sich die Latenz trotzdem.
- **brain.py:3361-3397**: 4 verschiedene Fallback-Mechanismen fuer Tool-Call-Extraktion (native → deterministic → text-extraction → retry). Fragil.
- **main.py:630-655**: ChatRequest/ChatResponse sind in main.py definiert, NICHT in shared schemas. Kein `from shared.schemas import ChatRequest`. Jeder Service definiert seine eigenen.

**Fehler-Pfade**:
- Schritt 4: 60s Timeout → "Systeme ueberlastet. Nochmal, bitte." (User informiert)
- Schritt 5: 30s Lock-Timeout → "Einen Moment, ich bin noch beschaeftigt." (User informiert)
- Schritt 35: LLM Timeout → Circuit Breaker, Cascade-Fallback auf kleineres Modell
- Schritt 38: Tool-Execution fehlschlaegt → Validation-Fehler oder Trust-Block kommuniziert
- Exception in brain.process() → main.py:759-772 faengt ab, generische Fehlermeldung

**Kollisionen**:
- Flow 1 kollidiert mit Flow 2 bei `_process_lock` — proaktive Meldungen warten auf Lock
- Flow 1 Shortcuts umgehen den gesamten Personality/Context/Memory-Pfad → inkonsistenter Ton

---

### Flow 2: Proaktive Benachrichtigung
**Status**: Funktioniert

**Ablauf**:
```
1.  brain.py:776       → Proactive.start() in initialize()
2.  proactive.py:244   → start() → asyncio.create_task(_listen_ha_events())
3.  proactive.py:251   → + Diagnostik-Loop, Batch-Loop, Seasonal-Loop, Observation-Loop
4.  proactive.py:359   → _listen_ha_events() → WebSocket ws://HA/api/websocket
5.  proactive.py:372   → _connect_and_listen() → Auth + subscribe state_changed
6.  proactive.py:???   → Event empfangen → Prioritaet aus event_handlers Mapping
7.  proactive.py:???   → Cooldown-Check, Quiet-Hours-Check, Activity-Check
8.  proactive.py:???   → Notification bauen (ggf. ueber brain.ollama.generate)
9.  proactive.py:200   → _deliver() → emit_proactive (WebSocket) + TTS (wenn erlaubt)
```

**Bruchstellen**:
- **proactive.py:60**: `self.brain = brain` — zirkulaere Referenz (Brain → ProactiveManager → Brain). GC kommt damit klar, aber architektonisch fragwuerdig.
- **proactive.py:359-370**: WebSocket-Reconnect-Loop ohne Backoff-Limit. Kann bei HA-Ausfall endlos loopen.
- **Kein _process_lock**: Proaktive Meldungen pruefen `self._user_request_active` (brain.py:218), aber die eigentliche TTS-Ausgabe ist nicht gegen concurrent User-Requests geschuetzt. Zwei Sprachausgaben koennten sich ueberlagern.

**Fehler-Pfade**:
- HA WebSocket bricht ab → Reconnect nach PROACTIVE_WS_RECONNECT_DELAY
- TTS fehlschlaegt → Warning-Log, WebSocket-Notification kommt trotzdem
- User spricht gerade → `_user_request_active` Flag, LOW/MEDIUM werden gebatcht

**Kollisionen**:
- Flow 2 kann gleichzeitig mit Flow 1 TTS ausgeben (kein TTS-Lock)
- Proactive nutzt NICHT den personality.build_system_prompt() Pfad → Ton kann inkonsistent sein

---

### Flow 3: Morgen-Briefing / Routinen
**Status**: Funktioniert

**Ablauf**:
```
1a. proactive.py:122-128 → Morning Briefing Auto-Trigger (Motion-Sensor im Zeitfenster 6-10 Uhr)
1b. brain.py:1996-2024   → Manueller Request "Morgenbriefing" → _is_morning_briefing_request()
2.  routine_engine.py:136 → generate_morning_briefing(person, force)
3.  routine_engine.py:153-164 → Redis-Lock pruefen (1x pro Tag, NX atomisch)
4.  routine_engine.py:167-183 → Bausteine sammeln (Sleep-Awareness, Module-Loop)
5.  routine_engine.py:180 → _get_briefing_module() pro Modul (greeting, weather, calendar, house_status, travel)
6.  routine_engine.py:189 → _build_briefing_prompt(parts, style)
7.  routine_engine.py:191-198 → ollama.chat() mit Briefing-System-Prompt
8.  routine_engine.py:619-639 → _get_briefing_system_prompt() → personality.build_routine_prompt() (mit Fallback)
9.  brain.py:2004-2022 → Response filtern, TTS, Emit
```

**Bruchstellen**:
- **routine_engine.py:197**: Nutzt `settings.model_fast` statt `model_router` → Hardcoded Modell, keine Cascade.
- **routine_engine.py:619-639**: Briefing geht durch `personality.build_routine_prompt()` → Ton ist konsistent. Aber der Fallback (Zeile 633-638) hat einen eigenen statischen Prompt → Ton-Bruch bei Personality-Fehler.

**Fehler-Pfade**:
- Ollama nicht erreichbar → routine_engine.py:200: Exception-Handler, leerer Text
- Redis nicht da → Kein Lock-Check, Briefing kann mehrfach ausgeloest werden
- Fehlende Datenquelle (Kalender) → _get_briefing_module() returned leer, Modul uebersprungen

**Kollisionen**:
- Morning-Briefing kann waehrend aktiver Konversation ausgeloest werden (via Auto-Trigger). Kein expliziter Check auf `_user_request_active` im Proactive-Trigger.
- Manueller "Morgenbriefing"-Request geht durch brain.process() Shortcut-Kaskade (Zeile 1996), NICHT durch den proaktiven Pfad.

---

### Flow 4: Autonome Aktion
**Status**: Teilweise — Framework vorhanden, aber nie direkt getriggert

**Ablauf**:
```
1.  anticipation.py:53-58    → AnticipationEngine.initialize() → _check_loop() Background-Task
2.  anticipation.py:79-100   → log_action() speichert Aktionen in Redis
3.  anticipation.py:???      → _check_loop() erkennt Muster (Zeit, Sequenz, Kontext)
4.  anticipation.py:46-51    → Confidence-Schwellen: ask(60%), suggest(80%), auto(95%)
5.  brain.py:582             → set_notify_callback(self._handle_anticipation_suggestion)
6.  brain.py:???             → _handle_anticipation_suggestion() → proaktive Meldung
7.  autonomy.py:124-145      → can_act(action_type, domain) → Level-Check
8.  autonomy.py:189-197      → SAFETY_CAPS: max_temperature_change=3, min=14, max=30, rate limits
```

**Bruchstellen**:
- **Autonome Ausfuehrung fehlt**: Die AnticipationEngine erkennt Muster und schlaegt vor (via Callback), aber es gibt keinen Code-Pfad der bei 95%+ Confidence automatisch `executor.execute()` aufruft. Der Callback geht durch den proaktiven Pfad → WebSocket + TTS Vorschlag, NICHT automatische Ausfuehrung.
- **proactive_planner.py:52-80**: ProactiveSequencePlanner plant Multi-Step-Aktionen (z.B. bei person_arrived), hat aber keine Verbindung zum Executor. Er returned einen Plan-Dict, aber niemand fuehrt ihn aus.
- **Sicherheits-Limits**: autonomy.py:189-197 definiert SAFETY_CAPS (z.B. max +/-3 Grad), aber diese werden nur in `check_safety_caps()` geprueft — und zwar nur im brain.py Tool-Call-Pfad (Zeile 3540-3549), nicht im autonomen Pfad.

**Fehler-Pfade**:
- Anticipation ohne Redis → Deaktiviert (Zeile 56-57)
- Pattern-Detection fehlerhaft → Falsche Vorschlaege, kein automatischer Rollback
- Autonomie-Level zu niedrig → Vorschlag statt Aktion

**Kollisionen**:
- Autonome Aktionen koennten User-Aktionen ueberschreiben (keine Entity-Ownership im autonomen Pfad)
- Spontaneous Observer (brain.py:335) beobachtet HA-States aber fuehrt keine Aktionen aus — rein informativ

---

### Flow 5: Persoenlichkeits-Pipeline
**Status**: Funktioniert — gut integriert, aber komplex

**Ablauf**:
```
Persoenlichkeit wird VOR dem LLM im System-Prompt angewendet:

1. brain.py:2680-2687  → personality.build_system_prompt(context, formality, mood, user_text, ...)
2. personality.py:2233 → build_system_prompt() baut den kompletten System-Prompt:
   - Zeile 2253: Tageszeit + Zeitstil
   - Zeile 2258-2263: Stimmungsabhaengige Anpassung (MOOD_STYLES)
   - Zeile 2268-2272: Mood x Complexity Matrix (max_sentences)
   - Zeile 2300-2303: Empathie-Section (stress_level basiert)
   - Zeile 2324-2330: Humor-Section (Sarkasmus-Level 1-5)
   - Zeile 2333: Complexity-Section (kurz/normal/ausfuehrlich)
   - Zeile 2336: Self-Irony-Section
   - Zeile 2441-2471: Template-Variablen einsetzen
   - Zeile 2473-2494: Kontext + Character-Lock

NACH dem LLM:
3. brain.py:???        → _filter_response() — Sie→du, Floskeln, Reasoning-Artefakte entfernen
4. brain.py:???        → tts_enhancer.enhance() — SSML/Speed/Volume
5. brain.py:???        → sound_manager.speak_response() — TTS-Ausgabe
```

**Bruchstellen**:
- **Shortcuts umgehen Personality**: Die 20+ Shortcuts in brain.py:1349-2060 bauen keinen personality.build_system_prompt() auf. Sie nutzen nur `personality.get_varied_confirmation()` oder hartcodierte Texte. Ton ist bei Shortcuts nicht konsistent mit dem Hauptpfad.
- **personality.py:2419-2438**: conversation_mode_section mit `_conv_topic` aus User-Text — Injection-risiko trotz basalem Sanitizing (Zeile 2426-2427 entfernt nur "SYSTEM:", "ASSISTANT:", "USER:").
- **Formality-Score**: Per-User in Redis gespeichert, decayed ueber Zeit. Aber: Thread-safe Write via `threading.Lock` (Zeile 334) in einem async Context → nicht ideal (blockierend).

**Fehler-Pfade**:
- SYSTEM_PROMPT_TEMPLATE.format_map() mit fehlendem Key → KeyError aufgefangen (Zeile 2464-2471), Fallback auf leere Strings
- Mood-Detection fehlschlaegt → Fallback "neutral"
- Personality-Redis nicht da → Defaults (formality_start, sarcasm_level aus Config)

**Kollisionen**:
- Sarkasmus-Level ist global (nicht per-Request). Wenn User A sarkastischen Humor mag und User B nicht, gilt trotzdem das gleiche Level (per-Person Override existiert in person_profiles, aber nur fuer einige Werte).

---

### Flow 6: Memory-Abruf (Erinnerung)
**Status**: Teilweise — spezieller Pfad existiert, aber nur fuer explizite Befehle

**Ablauf**:
```
Pfad A: Explizite Memory-Befehle (brain.py:1417-1422)
1.  brain.py:6511       → _handle_memory_command(text, person)
2.  brain.py:6521-6530  → "Merk dir X" → semantic.store_explicit()
3.  brain.py:6533-6546  → "Was weisst du ueber X?" → semantic.search_by_topic()
4.  brain.py:6548-6556  → "Vergiss X" → semantic.forget()
    → SHORTCUT: Antwort direkt, KEIN LLM-Call

Pfad B: Erinnerungsfrage via Intent-Routing (brain.py:3204-3237)
1.  brain.py:2305       → intent_type = _classify_intent(text)
2.  brain.py:3204       → intent_type == "memory"
3.  brain.py:3208       → semantic.search_by_topic(text, limit=5)
4.  brain.py:3213       → Fakten als System-Prompt-Erweiterung
5.  brain.py:3219-3224  → Kein Fakt → explizite Anweisung "ERFINDE KEINE Erinnerungen"
6.  brain.py:3227       → LLM-Call (Smart-Model, think=False)

Pfad C: Passive Memory im Kontext (context_builder.py:291-344)
1.  context_builder.py:301-304 → semantic.search_facts(query=user_text)
2.  context_builder.py:334-340 → semantic.get_facts_by_person(person)
3.  brain.py:2841-2846  → _build_memory_context(memories) → P1-Sektion
    → Memory als Hintergrund-Kontext, LLM entscheidet ob relevant
```

**Bruchstellen**:
- **Pfad B vs C parallel**: Memory-Query wird bei "intent_type == memory" ueber Pfad B verarbeitet, ABER context_builder.build() laeuft parallel im mega-gather und holt AUCH Fakten. Die Ergebnisse sind ggf. unterschiedlich (search_by_topic vs search_facts mit verschiedenen Limits/Filtern).
- **ConversationMemory (brain.py:274)**: Separates Memory-System mit Projekten, offenen Fragen, Zusammenfassungen. Wird als P3-Sektion eingebaut (Zeile 2971-2973), aber NICHT in den Memory-Abruf-Pfad integriert. Silo.
- **CorrectionMemory (brain.py:345)**: Weiteres Memory-Silo. Wird als P2-Sektion eingebaut (Zeile 2869-2876), aber hat keinen eigenen Abruf-Pfad.
- **min_confidence=0.6 Filter** (context_builder.py:320): Fakten unter 60% Confidence werden nicht im Kontext angezeigt — Wissen geht verloren.

**Fehler-Pfade**:
- ChromaDB nicht erreichbar → Leere Ergebnisse, kein Crash
- search_by_topic findet nichts → "ERFINDE KEINE Erinnerungen" Prompt (gut geloest)
- semantic.forget() findet nichts → "Zu X hatte ich ohnehin nichts gespeichert." (gut)

---

### Flow 7: Speech-Pipeline
**Status**: Funktioniert — saubere Architektur mit Wyoming Protocol

**Ablauf**:
```
1.  speech/server.py:100    → main() startet Wyoming AsyncServer auf Port 10300
2.  speech/server.py:25-85  → initial_prompt mit Smart-Home-Vokabular + Raumnamen
3.  speech/handler.py       → WhisperEmbeddingHandler verarbeitet Audio
    - faster-whisper STT (Whisper model)
    - ECAPA-TDNN Voice Embedding Extraktion (parallel)
    - Embedding in Redis: mha:speaker:latest_embedding
4.  HA Assist Pipeline       → Wyoming STT → Text
5.  conversation.py:71-139  → MindHomeAssistantAgent._async_handle_message()
    - Text + voice_metadata + room + device_id zusammenbauen
    - HTTP POST an /api/assistant/chat (mit API Key)
    - Response empfangen
    - TTS-Steuerung aus tts_data
    - IntentResponse zurueck an HA Pipeline
6.  HA Pipeline               → Piper TTS → Audio-Ausgabe
```

**Bruchstellen**:
- **conversation.py:108-113**: HTTP POST mit `timeout=aiohttp.ClientTimeout(total=30)`, aber brain.process() hat 60s Timeout (main.py:745). Conversation Agent gibt nach 30s auf, obwohl brain noch arbeitet.
- **Doppel-TTS (C-2 Fix)**: brain.py:880 prueft `_request_from_pipeline` und ueberspringt speak_response(). Das funktioniert, aber nur wenn voice_metadata korrekt `source=ha_assist_pipeline` enthaelt. Wenn der HA-Agent das nicht setzt, wird doppelt gesprochen.
- **conversation.py:92**: `voice_metadata` wird mit `source=ha_assist_pipeline` NICHT explizit gesetzt. Die _build_voice_metadata() Methode muss es setzen — das ist eine potenzielle Bruchstelle.

**Fehler-Pfade**:
- Assistant nicht erreichbar → "Ich kann gerade nicht denken. Der Assistant-Server ist nicht erreichbar."
- HTTP 4xx/5xx → "Da stimmt etwas nicht."
- STT fehlschlaegt → kein Text, kein Request an Assistant

**Kollisionen**:
- Conversation Agent nutzt HTTP POST (synchron, 30s Timeout), waehrend WebSocket-Clients Streaming bekommen. Pipeline-User haben schlechtere Latenz-Erfahrung.
- Speaker Recognition laeuft im Speech-Server (Embedding) UND im Assistant (brain.py:1260-1321). Die Kette: Whisper → Embedding → Redis → brain.speaker_recognition.identify() funktioniert, aber die Redis-Latenz addiert sich.

---

### 4. Kritische Findings

### Top-5 kritische Bruchstellen (sortiert nach Impact):

**1. GOD-OBJECT brain.py mit 1200-Zeilen Shortcut-Kaskade**
- **Datei:Zeile**: brain.py:1349-2300
- **Impact**: HOCH — Jeder neue Feature-Shortcut verlaengert die Kaskade. 20+ Shortcuts mit jeweils eigenem TTS/Emit/Filter Code. Shortcuts umgehen Personality-Pipeline → inkonsistenter Ton.
- **Eskalation**: ARCHITEKTUR_NOETIG — Refactoring in Router-Pattern mit Shortcut-Registry.

**2. Keine Shared Schemas — ChatRequest/ChatResponse in main.py definiert**
- **Datei:Zeile**: main.py:630-655
- **Impact**: MITTEL — Conversation Agent (HA Integration) baut sein eigenes Payload zusammen (conversation.py:92), hat aber keine garantierte Kompatibilitaet mit ChatRequest. Aenderungen in main.py brechen den HA-Agent.
- **Eskalation**: NAECHSTER_PROMPT

**3. Timeout-Asymmetrie: HA Agent 30s vs brain.process() 60s**
- **Datei:Zeile**: conversation.py:113 vs main.py:745
- **Impact**: MITTEL — Bei komplexen Anfragen (Deep-Model, multi-step ActionPlanner) gibt der HA Agent nach 30s auf. brain.py arbeitet weiter, TTS wird ggf. noch abgespielt (weil speak_response im Background laeuft), aber die Pipeline bekommt "Timeout".
- **Eskalation**: NAECHSTER_PROMPT

**4. Proaktive Meldungen ohne TTS-Lock**
- **Datei:Zeile**: proactive.py:200-242
- **Impact**: MITTEL — Proaktive TTS und User-Response TTS koennen sich ueberlagern. Kein zentrales Audio-Queue/Lock. `_user_request_active` Flag schuetzt nur vor dem Senden neuer proaktiver Meldungen, nicht vor laufenden.
- **Eskalation**: NAECHSTER_PROMPT

**5. Memory-Silos: 5 Systeme, 3 Pfade, keine Unified Query**
- **Datei:Zeile**: brain.py:231 (MemoryManager), 274 (ConversationMemory), 345 (CorrectionMemory), context_builder.py:301 (passive), brain.py:3204 (intent-based)
- **Impact**: HOCH — User fragt "Was weisst du ueber X?" → bekommt nur SemanticMemory-Fakten. ConversationMemory (Projekte, offene Fragen), CorrectionMemory (gelernte Korrekturen), und Episodic Memory (ChromaDB conversations) werden NICHT durchsucht.
- **Eskalation**: ARCHITEKTUR_NOETIG

---

## KONTEXT AUS PROMPT 3a: Flow-Analyse (Core-Flows)

### Init-Sequenz
```
main.py:210   → brain = AssistantBrain() [Module-Level]
main.py:323   → lifespan() → brain.initialize()
brain.py:486  → memory.initialize() (Redis + ChromaDB + Semantic)
brain.py:490  → ollama.list_models() + model_router.initialize()
brain.py:498-798 → 50+ Module init (alle in _safe_init() gewrappt, F-069)
brain.py:776  → proactive.start() (HA WebSocket + Background-Tasks)
main.py:347   → health_check() + Boot-Announcement
```
Graceful Degradation: Ja (F-069). Aber: Module-Level brain=AssistantBrain() → Import-Fehler nicht abgefangen.

### System-Prompt (rekonstruiert)
```
SYSTEM_PROMPT_TEMPLATE (~1800t statisch) [personality.py:242-286]
+ Dynamic Sections (mood, humor, empathy, formality, weather, etc.) [personality.py:2233-2471]
+ AKTUELLER KONTEXT (house, time, memories, person) [personality.py:2473, context_builder.py:159]
+ CHARACTER-LOCK [personality.py:2478-2494]
+ Priority-Sektionen P1-P4 mit Token-Budget [brain.py:2690-3046]
+ Conversation History + Character-Reminder [brain.py:3053-3130]
+ Tools (get_assistant_tools) [brain.py:3283]
Gesamt: ~4000-8000 Tokens typisch, max ~12000
```

### Flow-Status-Uebersicht (Core-Flows 1-7)

| Flow | Status | Kritischste Bruchstelle |
|---|---|---|
| 1: Sprach-Input → Antwort | Teilweise | 1200-Zeilen Shortcut-Kaskade umgeht Personality, brain.py:1349-2300 |
| 2: Proaktive Benachrichtigung | Funktioniert | Kein TTS-Lock, proactive.py:200-242 |
| 3: Morgen-Briefing | Funktioniert | Hardcoded model_fast statt model_router, routine_engine.py:197 |
| 4: Autonome Aktion | Teilweise | Kein Auto-Execute-Pfad, Anticipation schlaegt nur vor |
| 5: Persoenlichkeits-Pipeline | Funktioniert | Shortcuts umgehen Personality-Prompt |
| 6: Memory-Abruf | Teilweise | 5 Memory-Silos, keine Unified Query |
| 7: Speech-Pipeline | Funktioniert | Timeout-Asymmetrie 30s vs 60s, conversation.py:113 |

### Top-Bruchstellen (Core-Flows)
1. brain.py:1349-2300 — 20+ Shortcuts umgehen Personality/Context/Memory-Pipeline
2. main.py:630-655 — Keine Shared Schemas, ChatRequest/ChatResponse lokal definiert
3. conversation.py:113 vs main.py:745 — Timeout-Asymmetrie (30s vs 60s)
4. proactive.py:200-242 — Kein TTS-Lock, Audio-Ueberlagerung moeglich
5. brain.py:231+274+345 — 5 Memory-Systeme, 3 Query-Pfade, keine Unified Search

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Keine Fixes — reiner Analyse-Prompt]
OFFEN:
- HOCH brain.py:1349-2300: 20+ Shortcuts umgehen Personality/Context/Memory | ARCHITEKTUR_NOETIG
- HOCH brain.py:231+274+345: 5 Memory-Silos, keine Unified Query | ARCHITEKTUR_NOETIG
- MITTEL main.py:630-655: Keine Shared Schemas | NAECHSTER_PROMPT
- MITTEL conversation.py:113: Timeout 30s vs brain 60s | NAECHSTER_PROMPT
- MITTEL proactive.py:200-242: Kein TTS-Lock | NAECHSTER_PROMPT
- NIEDRIG routine_engine.py:197: Hardcoded model_fast | NAECHSTER_PROMPT
- NIEDRIG personality.py:334: threading.Lock in async context | NAECHSTER_PROMPT
- NIEDRIG main.py:210: Module-Level brain instanziierung | NAECHSTER_PROMPT
GEAENDERTE DATEIEN: [Keine — reiner Analyse-Prompt]
REGRESSIONEN: [Keine]
NAECHSTER SCHRITT: Prompt 3b — Extended-Flows 8-13 + Flow-Kollisionen + Cross-Cutting Concerns
===================================
```
