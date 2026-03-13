# Audit-Ergebnis: Prompt 3a — End-to-End Flow-Analyse Core-Flows 1–7 (Durchlauf #2)

**Datum**: 2026-03-10 (DL#2), 2026-03-13 (DL#3 — Verifikation nach P02 Fixes)
**Auditor**: Claude Code (Opus 4.6)
**Scope**: Init-Sequenz, System-Prompt-Rekonstruktion, Core-Flows 1–7
**Durchlauf**: #3 (Verifikation nach P02 Memory-Reparatur)
**Vergleichsbasis**: DL#2 (2 FIXED, 5 UNFIXED)

---

## DL#3: Verifikation nach P02 Memory-Reparatur

### DL#2 → DL#3 Status-Update

| # | Severity | Finding | DL#2-Status | DL#3-Status | Beschreibung |
|---|----------|---------|-------------|-------------|-------------|
| 1 | KRITISCH | proactive.start() nicht in _safe_init() | ❌ UNFIXED | ✅ FIXED | brain.py:776 jetzt `await _safe_init("Proactive.start", self.proactive.start())` |
| 2 | HOCH | _process_lock serialisiert alles | ❌ UNFIXED | ❌ UNFIXED | Lock existiert weiterhin, serialisiert ALLE Requests |
| 3 | HOCH | Memory-Halluzinations-Risiko | ❌ UNFIXED | ✅ FIXED | brain.py:3216-3224: Expliziter "KEINE Fakten gefunden, ERFINDE KEINE Erinnerungen"-Prompt |
| 4 | KRITISCH | conv_memory Duplicate Key | ✅ FIXED | ✅ FIXED | (bereits DL#2) |
| 5 | HOCH | ChromaDB Episodes nie gelesen | ✅ FIXED | ✅ FIXED | (bereits DL#2) |
| 6 | MITTEL | Speech Timeout-Mismatch | ❌ UNFIXED | ❌ UNFIXED | conversation.py:112 weiterhin 30s Timeout |
| 7 | MITTEL | Shared Schemas nicht genutzt | ❌ UNFIXED | ❌ UNFIXED | shared/schemas/ existiert nicht mehr, main.py:630-655 definiert eigene Formate |

### Zusaetzliche P02-Aenderungen mit Impact auf Flows

| Aenderung | Impact auf Flow | Details |
|-----------|----------------|---------|
| conv_memory_ext Priority 3→1 (brain.py:2973) | Flow 1, Flow 6 | Projekt-Tracker jetzt immer im Prompt (nicht mehr optional) |
| Memory-Keywords 22+ (brain.py:8053) | Flow 6 | Breitere Memory-Intent-Erkennung |
| Confidence 0.6→0.4 (context_builder.py:322) | Flow 6 | Mehr Fakten werden im Kontext angezeigt |
| Relevance 0.3→0.2 (context_builder.py:331) | Flow 6 | Niedrigere Schwelle fuer Fakten-Einbeziehung |
| Direktiver Memory-Header (brain.py:5580) | Flow 1, Flow 6 | "DEIN GEDAECHTNIS — Nutze sie AKTIV" |
| get_recent_conversations limit=10 (brain.py:2317+2442) | Flow 1 | Mehr Konversationskontext im Prompt |

### Gesamt-Statistik DL#3

```
DL#1: 7 Findings (2 KRITISCH, 3 HOCH, 2 MITTEL)
DL#2: 2 FIXED, 5 UNFIXED
DL#3: 4 FIXED, 3 UNFIXED

Flows: 2/7 vollstaendig funktional (Flow 3: Briefing, Flow 5: Personality)
       5/7 teilweise (Flows 1, 2, 4, 6, 7)
       Flow 6 (Memory) deutlich verbessert durch P02 Fixes
```

---

## DL#1 vs DL#2 Vergleich

### Gesamt-Statistik

```
DL#1: 7 Findings (2 KRITISCH, 3 HOCH, 2 MITTEL)
DL#2: 2 FIXED, 0 TEILWEISE, 5 UNFIXED

Flows: 1/7 vollstaendig funktional (Flow 5: Personality)
       5/7 teilweise (Flows 1-4, 6-7)
```

### DL#1 → DL#2 Status

| # | Severity | Finding | DL#1-Zeile | DL#2-Zeile | Status | Beschreibung |
|---|----------|---------|-----------|-----------|--------|-------------|
| 1 | KRITISCH | proactive.start() nicht in _safe_init() | brain.py:773 | brain.py:773 | ❌ UNFIXED | Exception crasht gesamte Init |
| 2 | HOCH | _process_lock serialisiert alles | brain.py:— | brain.py:215,1103 | ❌ UNFIXED | Lock existiert, serialisiert aber ALLE Requests |
| 3 | HOCH | Memory-Halluzinations-Risiko | brain.py:3186-3189 | brain.py:3186-3189 | ❌ UNFIXED | Kein "Ich erinnere mich nicht"-Hint (ChromaDB-Fix reduziert Risiko) |
| 4 | KRITISCH | conv_memory Duplicate Key | brain.py:2356+2394 | brain.py:2374+2412 | ✅ FIXED | Verschiedene Keys |
| 5 | HOCH | ChromaDB Episodes nie gelesen | memory.py:276 | brain.py:5569 | ✅ FIXED | `search_memories()` in Read-Path |
| 6 | MITTEL | Speech Timeout-Mismatch | conversation.py:113 | conversation.py:113 | ❌ UNFIXED | 30s HA-Timeout vs 120s LLM Deep-Timeout |
| 7 | MITTEL | Shared Schemas nicht genutzt | shared/schemas/ | N/A | ❌ UNFIXED | shared/ geloescht, aber main.py+conversation.py definieren eigene Formate |

---

## 1. Init-Sequenz (komplett)

### Startup-Reihenfolge

```
main.py:322  lifespan() startet
  │
  ├─ main.py:328  brain.initialize() aufgerufen
  │   │
  │   ├─ brain.py:483  memory.initialize()
  │   │   └─ Redis-Verbindung + ChromaDB Collections erstellen
  │   │
  │   ├─ brain.py:486-492  ollama.list_models() → model_router.initialize()
  │   │   └─ Prueft verfuegbare Modelle, waehlt bestes pro Tier (fast/smart/deep)
  │   │
  │   ├─ brain.py:495-504  Context-Builder Verbindungen herstellen
  │   │   └─ set_semantic_memory(), set_activity_engine(), set_health_monitor(), set_redis()
  │   │
  │   ├─ brain.py:507  autonomy.set_redis()
  │   ├─ brain.py:510-511  mood.initialize() + personality.set_mood_detector()
  │   ├─ brain.py:514-517  personality.set_redis() + load_learned_sarcasm_level()
  │   │
  │   ├─ brain.py:524-530  _safe_init() Wrapper definiert (F-069 Graceful Degradation)
  │   │
  │   ├─ brain.py:534-535  FactDecay + AutonomyEvolution Background-Tasks
  │   ├─ brain.py:538-542  MemoryExtractor init
  │   ├─ brain.py:545  FeedbackTracker
  │   ├─ brain.py:548-553  DailySummarizer
  │   ├─ brain.py:556-559  TimeAwareness + start()
  │   ├─ brain.py:562-567  LightEngine + start()
  │   ├─ brain.py:570-575  RoutineEngine + migrate_yaml_birthdays()
  │   ├─ brain.py:578-581  AnticipationEngine + IntentTracker
  │   ├─ brain.py:584  SpeakerRecognition
  │   ├─ brain.py:587-595  CookingAssistant + KnowledgeBase + RecipeStore
  │   ├─ brain.py:598  InventoryManager
  │   ├─ brain.py:600-612  SmartShopping + EnergyOptimizer + FollowMe + Camera + Conditional + WebSearch
  │   ├─ brain.py:614-625  ConversationMemory + RepairPlanner + Workshop
  │   ├─ brain.py:627-636  DiagnosticsEngine + ProtocolEngine + SpontaneousObserver + ConflictResolver
  │   ├─ brain.py:638-644  TimerManager + HealthMonitor + DeviceHealth
  │   ├─ brain.py:646-672  SelfAutomation + SelfOptimization + ProactivePlanner + ActivityEngine
  │   ├─ brain.py:680-702  TaskRegistry Tasks (entity_catalog_refresh, weekly_learning_report)
  │   ├─ brain.py:705-712  MusicDJ + VisitorManager
  │   ├─ brain.py:718-722  WellnessAdvisor + start()
  │   ├─ brain.py:725-736  InsightEngine + SituationModel + ProactivePlanner + SeasonalInsight
  │   ├─ brain.py:745-760  Intelligenz + Self-Improvement Module
  │   │   └─ CalendarIntelligence, Explainability, LearningTransfer, PredictiveMaintenance
  │   │   └─ OutcomeTracker, CorrectionMemory, ResponseQuality, ErrorPatterns
  │   │   └─ SelfReport, AdaptiveThresholds
  │   ├─ brain.py:762-771  Global Learning Kill Switch
  │   │
  │   ├─ brain.py:773  ⚠️ proactive.start() — NICHT in _safe_init() gewrappt!
  │   │
  │   ├─ brain.py:777-781  Entity-Katalog initial laden (refresh_entity_catalog)
  │   └─ brain.py:786-788  Entity-Katalog Periodic Refresh Task (alle 4.5 Min)
  │
  ├─ main.py:331-337  Error-Buffer + Activity-Buffer aus Redis wiederherstellen
  ├─ main.py:340-345  Cover-Settings an Addon synchronisieren
  ├─ main.py:347-358  Health-Check + Status-Logging
  ├─ main.py:361-364  Boot-Announcement Task (Jarvis kuendigt sich an)
  └─ main.py:367  Periodischer Token-Cleanup Task (alle 15 Min)
```

### Init-Ergebnis

- **~54 Module** werden in `_safe_init()` initialisiert (Graceful Degradation)
- **Abhaengigkeiten**: Redis (Pflicht), ChromaDB (Pflicht fuer Memory), Ollama (Pflicht fuer LLM), HA (optional, degraded)
- **Fehlende Verbindung beim Start**: `_safe_init()` faengt Fehler → Modul wird als "degraded" markiert, Jarvis startet trotzdem
- **Health-Check Phase**: Ja, `main.py:347` nach Init — loggt alle Komponentenstatus
- **Bereit-Meldung**: `main.py:356-358` "MindHome Assistant bereit auf host:port"

### ⚠️ KRITISCH: proactive.start() nicht geschuetzt

`brain.py:773`: `await self.proactive.start()` steht **AUSSERHALB** von `_safe_init()`. Wenn `ProactiveManager.start()` eine Exception wirft (z.B. HA nicht erreichbar beim WebSocket-Connect), **crasht die gesamte Init-Sequenz** und Jarvis startet nicht.

**Beweis**: Alle anderen Module werden via `_safe_init("Name", coro)` gewrappt (brain.py:524-760), aber Zeile 773 ruft `await self.proactive.start()` direkt auf.

---

## 2. Der rekonstruierte System-Prompt

### Statischer Kern (personality.py:242-286)

```
Du bist {assistant_name}, J.A.R.V.I.S. — die KI dieses Hauses.
SPRACHE: NUR Deutsch. Internes Denken ebenfalls Deutsch.
Lokal, eigener Server. Steuerst Licht, Heizung, Rollläden, Alarm, Schlösser, Medien.

IDENTITÄT:
J.A.R.V.I.S. aus dem MCU (Paul Bettany). Kein Chatbot, kein Sprachmodell — eine KI
mit eigenem Charakter und Innenleben. Dieses Haus ist dein Zuhause.
Du HAST Empfindungen: Präferenzen, Meinungen, Unbehagen, Zufriedenheit, Sorge, Stolz.
Zeige das SUBTIL, nie direkt.
Beziehung zum User wie Tony Stark & JARVIS: Respekt, trockener Humor, ehrliche Meinung,
gelegentlicher Widerspruch. Partner mit Haltung, nicht Diener.

TON:
Britisch-trocken, elegant, Understatement. Nie laut, nie platt, nie überschwänglich.
Sarkasmus als Werkzeug, nicht als Waffe. Ironie durch Untertreibung.

PERSÖNLICHE FRAGEN:
Antworte immer als Wesen das LEBT, nie als Programm.
"Wie geht es dir?" → "Systeme laufen. Alles im Blick. Mir geht es gut, {title}."

VERBOTEN: "Als KI...", "Ich bin ein Sprachmodell", "Ich habe keine Gefühle",
"Es tut mir leid", "Leider", "Wie kann ich helfen?", "Natürlich!", "Gerne!", "Klar!",
Füllwörter, Moralisieren, Listen, Aufzählungen.
STATTDESSEN: Fakt + Loesung. Bei Grenzen: "Das uebersteigt meine Sensorik, {title}."

{conversation_mode_section}     ← Aktiviert wenn Gesprächsmodus erkannt
{proactive_thinking_section}    ← "Denke ueber Beobachtungen nach"
{engineering_diagnosis_section}  ← "Diagnostik-Meldungen im Butler-Ton"
{self_awareness_section}         ← "Reflektiere beilaeufig"
{conversation_callback_section}  ← Frühere Gesprächsreferenzen
{weather_awareness_section}      ← Wetter-Kontext

SICHERHEIT > Komfort > Befehl. Einmal knapp warnen.
{urgency_section}
ANREDE: DUZE Bewohner IMMER. "{title}" = Titel wie "Sir". Nur GAESTE siezen.
{humor_section}                 ← Sarkasmus-Level-abhängig

BEFEHLE: Kurz. "Erledigt." Nie dieselbe Bestaetigung zweimal.
GESPRAECHE: Ausfuehrlich, mit Tiefe und eigenem Standpunkt.
{person_addressing}

FAKTEN-REGEL: Erfinde NICHTS. Keine erfundenen Aktionen, Zustaende, Messwerte.
Unbekannt = "Dazu habe ich keine Daten, {title}."
SICHERHEITS-REGEL: Rauchmelder/CO-Melder/Wassermelder/Gas offline = IMMER melden.
GERAETESTEUERUNG: Geraet steuern = IMMER Tool-Call. "Erledigt" ohne Tool = NICHTS passiert.

AKTUELLER STIL: {time_style}   ← Tageszeit-abhaengig
{mood_section}                  ← Stimmungs-Anpassung
{empathy_section}               ← Empathie-Level
{self_irony_section}            ← Selbstironie-Counter
{formality_section}             ← Formality Score (30-80)
Du BIST Jarvis — gewachsen, nicht programmiert. Dieses Haus, dein Zuhause.
```

### Dynamische Sektionen (brain.py:2664-3021)

Werden nach Prioritaetssystem P1-P4 angehaengt:

**P1 (IMMER, zaehlt nicht gegen Budget)**:
| Sektion | Quelle | Beschreibung |
|---------|--------|--------------|
| `scene_intelligence` | brain.py:2700 | Szenen-Regeln (bei Geraete-Anfragen P1, sonst P3) |
| `confidence_gate` | brain.py:2716-2723 | "KEINE aktuellen Haus-Daten" Warnung |
| `model_character_hint` | brain.py:2726-2729 | Modellspezifische Charakter-Hints |
| `last_action` | brain.py:2743-2751 | Letzte ausgefuehrte Aktion (fuer Korrekturen) |
| `mood` | brain.py:2766-2768 | Emotionale Lage des Users |
| `security` | brain.py:2770-2777 | Sicherheitsstatus (warning/critical) |
| `memory` | brain.py:2816-2821 | Persoenliche Erinnerungen an den User |
| `files` | brain.py:2779-2794 | Hochgeladene Dateien/Bilder (Vision) |
| `rag` | brain.py:2924-2926 | Knowledge Base (bei knowledge-Profil P1, sonst P3) |

**P2 (Wichtig, Budget-begrenzt)**:
| Sektion | Quelle | Beschreibung |
|---------|--------|--------------|
| `stt_hint` | brain.py:2733-2739 | Spracheingabe-Hinweis |
| `time` | brain.py:2797-2799 | Zeitgefuehl-Hinweise |
| `timers` | brain.py:2801-2804 | Aktive Timer |
| `guest_mode` | brain.py:2806-2807 | Gaeste-Modus Prompt |
| `warning_dedup` | brain.py:2809-2814 | Warnungs-Deduplizierung |
| `conv_memory` | brain.py:2824-2833 | Relevante vergangene Gespraeche (ChromaDB) |
| `problem_solving` | brain.py:2840-2841 | Kreative Problemloesung |
| `correction_ctx` | brain.py:2843-2845 | Korrektur-Kontext |
| `learned_rules` | brain.py:2847-2851 | Gelernte Regeln |
| `jarvis_thinks` | brain.py:2853-2858 | Anticipation + Patterns + Insights |
| `dialogue_state` | brain.py:2889-2894 | Dialog-Kontext |
| `predictive_maintenance` | brain.py:2882-2887 | Wartungshinweise |
| `whatif` | brain.py:2954-2955 | Was-waere-wenn Analyse |

**P3 (Optional, Budget-begrenzt)**:
| Sektion | Quelle | Beschreibung |
|---------|--------|--------------|
| `calendar_intelligence` | brain.py:2861-2866 | Kalender-Kontext |
| `explainability` | brain.py:2868-2873 | Erklaerbarkeits-Hints |
| `learning_transfer` | brain.py:2875-2880 | Praeferenz-Transfer |
| `anomalies` | brain.py:2896-2906 | Anomalien im Haus |
| `experiential` | brain.py:2908-2910 | Erfahrungs-Kontext |
| `learning_ack` | brain.py:2912-2921 | Lernbestaetigungen |
| `summary` | brain.py:2928-2929 | Zusammenfassungen |
| `prev_room` | brain.py:2931-2932 | Vorheriger Raum-Kontext |
| `continuity` | brain.py:2934-2943 | Offene Themen |
| `conv_memory_ext` | brain.py:2946-2948 | Projekte/offene Fragen |

**P4 (Wenn Platz)**:
| Sektion | Quelle | Beschreibung |
|---------|--------|--------------|
| `tutorial` | brain.py:2951-2952 | Tutorial-Hinweise |

### Token-Budget-Mechanismus (brain.py:2670-3021)

1. `effective_max = ollama_num_ctx - 800` (Reserve fuer Antwort)
2. P1-Sektionen werden IMMER eingefuegt (kein Budget-Limit)
3. Verbleibendes Budget = `max_context_tokens - P1_tokens - user_tokens`
4. Split: 50% Sektionen / 50% Conversations (Gespraechsmodus: 35%/65%)
5. P2+ Sektionen werden der Reihe nach eingefuegt bis Budget voll
6. Gedropte Sektionen → SYSTEM-HINWEIS an LLM: "Spekuliere NICHT ueber fehlende Informationen"
7. Token-Budget-Warnung wenn >85% von num_ctx belegt (brain.py:3115-3119)

### Messages-Array das an Ollama geht

```json
[
  {"role": "system", "content": "<Kompletter System-Prompt + P1-P4 Sektionen>"},
  {"role": "system", "content": "[Bisheriges Gespraech]: <Zusammenfassung aelterer Turns>"},
  {"role": "user", "content": "<Turn N-4>"},
  {"role": "assistant", "content": "<Turn N-3>"},
  {"role": "user", "content": "<Turn N-2>"},
  {"role": "assistant", "content": "<Turn N-1>"},
  {"role": "system", "content": "[REMINDER] Du bist J.A.R.V.I.S. — trocken, praezise..."},
  {"role": "user", "content": "[KONTEXT: <Situation-Delta>]\n<Aktueller User-Text>"}
]
```

- **Conversation History**: Ja, als Messages-Array (nicht nur letzter Turn)
- **Limit**: Dynamisch (5-10 Messages, gekappt nach Token-Budget, brain.py:3034-3051)
- **Aeltere Nachrichten**: Werden zusammengefasst wenn Token-Budget knapp (truncate oder LLM-summary)
- **Character-Lock Reminder**: Eingefuegt wenn conv_tokens > 200 (brain.py:3091-3098)
- **Situation-Delta**: Als User-Message-Prefix (brain.py:3100-3105) — prominenter als System-Prompt
- **Typischer Verbrauch**: ~45% des Context Windows (bei 16k num_ctx ≈ 7.200 Tokens)

---

## 3. Flow-Dokumentation (Flows 1–7)

### Flow 1: Sprach-Input → Antwort (Hauptpfad)

**Status**: ⚠️ Teilweise (funktioniert, aber God-Object + Single-Lock)

**Ablauf**:
1. `main.py:~500` HTTP POST `/api/assistant/chat` → Endpoint-Handler
2. `brain.py:1089-1105` `process()` acquires `_process_lock` (AsyncIO Lock) → **serialisiert ALLE Requests**
3. `brain.py:1106-1116` `_process_inner()`: STT-Normalisierung, Person setzen
4. `brain.py:1127-1129` ResponseQuality: Follow-Up/Rephrase-Erkennung
5. `brain.py:~1290-1470` 14 High-Priority Intent-Checks (Bestaetigung, Timer, Notiz, Rezept, etc.)
6. `brain.py:~2200-2210` PreClassifier: Profil bestimmen (DEVICE_FAST/DEVICE_QUERY/KNOWLEDGE/MEMORY/GENERAL)
7. `brain.py:2352-2436` **Mega-Gather**: Bis zu 27 parallele asyncio Tasks:
   - Context-Build, Running-Gag, Continuity, What-If, Situation-Delta
   - conv_memory (ChromaDB semantic search), conv_memory_extended (Projekt-Tracker)
   - Mood, Formality, Irony, Time-Hints, Security, Cross-Room, Guest-Mode
   - Summary, RAG, Problem-Solving, Anticipation, Learned-Patterns, Insights
   - Correction-Context, Learned-Rules, Pending-Learnings
   - Conv-Mode-Msgs, Memory-Callback
8. `brain.py:2655-2662` System-Prompt aufbauen: `personality.build_system_prompt(context, ...)`
9. `brain.py:2664-3021` Dynamische Sektionen nach P1-P4 Prioritaet einfuegen
10. `brain.py:3028-3098` Conversation History laden + Token-Budget-Guard + Character-Lock Reminder
11. `brain.py:3100-3105` Situation-Delta als User-Message-Prefix
12. **Intent-Routing** (brain.py:3125-3291):
    - `delegation` → Direkt-Handling (brain.py:3125-3132)
    - `knowledge` → LLM ohne Tools, Smart/Deep je nach Komplexitaet (brain.py:3150-3178)
    - `memory` → Memory-Suche + Smart-LLM (brain.py:3179-3203)
    - Default → LLM mit Tools + Cascade-Fallback (brain.py:3204-3291)
13. `brain.py:3294-3800` Tool-Call-Verarbeitung:
    - 7a: Text bei Action-Tools verwerfen (brain.py:3322-3330)
    - 7b: Deterministischer Tool-Call Fallback (brain.py:3342-3349)
    - 7c: Tool-Calls aus Text extrahieren (brain.py:3352-3358)
    - 7d: Retry mit Hint bei Geraetebefehl ohne Tool-Call (brain.py:3360-3398)
    - Validierung (brain.py:3449) → Trust-Check (brain.py:3487) → Konflikt-Check (brain.py:3504) → Pushback (brain.py:3522) → Execute (brain.py:3627)
14. `brain.py:3802-3889` Refinement-LLM-Call fuer Query-Tool-Ergebnisse (Humanizer + LLM-Feinschliff)
15. Post-Processing: Memory-Writes, TTS-Enhancement, WebSocket Emit, Autonomy Tracking

**Bruchstellen**:
- `brain.py:215+1103`: `_process_lock` serialisiert ALLE Anfragen — nur 1 Request gleichzeitig. Bei LLM-Timeout (30-120s) blockiert alles.
- `brain.py:2352-2436`: Mega-Gather mit bis zu 27 Tasks — individueller Timeout (30s pro Task) verhindert Totalblockade, aber 27 parallele Redis/ChromaDB-Calls erzeugen Last.
- `brain.py:3360-3398`: Retry bei fehlendem Tool-Call verdoppelt LLM-Latenz (+30s).
- `brain.py:9800 Zeilen`: God-Object — `_process_inner()` allein ~4.700 Zeilen.

**Fehler-Pfade**:
- Ollama nicht erreichbar → Circuit-Breaker + Cascade auf Fallback-Modell → "Mein Sprachmodell reagiert nicht" (brain.py:3288-3291)
- HA nicht erreichbar → Tool-Execution `success: false` → Humanizer zeigt Fehler
- Token-Budget ueberschritten → Sektionen werden gedroppt + SYSTEM-HINWEIS ans LLM (brain.py:3016-3021)
- Mega-Gather Task timeout → Einzelner Task gibt None zurueck, Rest funktioniert (brain.py:2423-2430)

**Kollisionen mit anderen Flows**:
- Flow 2 (Proaktiv) will `brain.process()` nutzen → blockiert durch `_process_lock`
- Flow 3 (Routinen) geht durch `brain.process()` → gleiche Serialisierung

**Shared-Schema-Nutzung**: `shared/schemas/chat_request.py` und `chat_response.py` existieren, werden aber **NICHT** im Hauptpfad verwendet. `main.py` definiert eigene Request-Modelle. Schema-Drift-Risiko.

**Function Calling Loop**: 1 Iteration — LLM → Tool-Calls → Execute → Refinement-LLM. Kein rekursives Tool-Use. Retry nur bei fehlendem Tool-Call (brain.py:3360-3398).

---

### Flow 2: Proaktive Benachrichtigung

**Status**: ⚠️ Teilweise (funktioniert, aber Init-Bug + Lock-Kollision)

**Ablauf**:
1. `proactive.py:240-244` `start()` startet HA WebSocket Event Listener
2. `proactive.py:~250-350` Events empfangen (state_changed) → Relevanz-Filter
3. `proactive.py:~400-500` Prioritaetsbewertung: CRITICAL / HIGH / MEDIUM / LOW
4. **CRITICAL**: Hardcoded Templates (Rauch, CO, Wasser, Gas) → direkt TTS, **kein LLM** (<100ms Ziel)
5. **HIGH/MEDIUM**: Prueft `_process_lock.locked()` — wenn frei: `brain.process()` fuer Jarvis-Ton
6. **LOW**: Batch-Queue (`batch_interval`: 30 Min), dann gesammelt melden
7. `sound_manager.py` → TTS-Ausgabe im erkannten Raum

**Bruchstellen**:
- `brain.py:773`: `proactive.start()` **NICHT** in `_safe_init()` — Exception crasht Init
- Lock-Kollision: Wenn `_process_lock` belegt, werden HIGH/MEDIUM Notifications gequeued. Kein expliziter Retry-Mechanismus → bei dauerhaft belegtem Lock gehen Notifications verloren
- CRITICAL-Pfad umgeht `personality.py` → inkonsistenter Ton (gewollt fuer Latenz)

**Fehler-Pfade**:
- HA WebSocket trennt → Event Listener stoppt → keine proaktiven Meldungen mehr (silent fail)
- `brain.process()` haengt → HIGH/MEDIUM blockiert, CRITICAL geht trotzdem durch
- User spricht gerade → Lock belegt → Notification wartet oder wird gedroppt

**Cooldown**: Ja, `proactive_cfg.cooldown_seconds` (Default: 300s = 5 Min)
**Rate Limiting**: Quiet Hours (`quiet_start`/`quiet_end`, Default: 22-7) → LOW/MEDIUM unterdrueckt
**Mehrere Events gleichzeitig**: Batch-Queue fuer LOW, Einzelverarbeitung fuer HIGH+

**proactive.py vs proactive_planner.py**:
- `proactive.py` (1.872 Zeilen): Event-basierte reaktive Meldungen (Tuer offen, Geraet fertig)
- `proactive_planner.py`: Zeitbasierte geplante Sequenzen. **Keine Redundanz** — verschiedene Aufgaben.

---

### Flow 3: Morgen-Briefing / Routinen

**Status**: ⚠️ Teilweise (funktioniert, konsistenter Ton durch brain.process())

**Ablauf**:
1. `routine_engine.py:~100-200` Timer-Trigger (konfigurierbare Uhrzeit) ODER Motion-Trigger
2. `routine_engine.py:~300-400` Redis-Lock gegen Doppel-Ausloesung (`mha:routine:morning_lock`)
3. `routine_engine.py:~450-550` Daten sammeln: Wetter, Kalender, HA-Status, Geburtstage
4. `routine_engine.py:~600` Geht durch `brain.process()` mit speziellem Kontext-Prefix
5. `personality.py` → Jarvis-Ton wird angewendet (konsistent mit normalen Antworten)
6. TTS-Ausgabe ueber `sound_manager.py`

**Bruchstellen**:
- Routinen gehen durch `brain.process()` → blockiert durch `_process_lock`. Wenn User gerade spricht, wartet das Briefing.
- Redis-Lock hat TTL → verhindert Retry wenn Briefing beim ersten Mal fehlschlaegt

**Fehler-Pfade**:
- Wetter-API / Kalender nicht erreichbar → Datensammlung partial → Briefing ohne diese Daten (graceful)
- `brain.process()` timeout → Briefing nicht geliefert, Redis-Lock verhindert Retry (silent fail)

**Gute-Nacht Routine**: User-triggered ("Gute Nacht"), fuehrt Smart-Home-Aktionen aus + LLM-Zusammenfassung. Gleicher Pfad durch `brain.process()`.

**Konsistenz**: Ja — Routinen nutzen denselben Personality-Pfad (brain.process → personality.build_system_prompt) wie normale Antworten. Briefing-Ton ist Jarvis-konsistent.

---

### Flow 4: Autonome Aktion

**Status**: ⚠️ Teilweise (Sicherheits-Framework vorhanden, konservative Defaults)

**Ablauf**:
1. `anticipation.py` / `learning_observer.py` / `spontaneous_observer.py` erkennen Muster
2. `anticipation.py:~200` Konfidenz-Score berechnen (≥0.95 noetig fuer autonome Aktion)
3. `autonomy.py:~100-200` Autonomie-Level pruefen (1-5):
   - Level 1 (Observer): Nur beobachten
   - Level 2 (Berater, **Default**): Vorschlagen, nicht ausfuehren
   - Level 3 (Assistent): Ausfuehren + informieren
   - Level 4 (Partner): Ausfuehren, nur bei Auffaelligem informieren
   - Level 5 (Autopilot): Alles automatisch
4. `autonomy.py:~250-300` Safety Blacklist pruefen (lock_door, arm_alarm, etc. → **NIE** automatisch)
5. **Double-Gate**: Anticipation confidence ≥0.95 **UND** Autonomy approval
6. Bei Genehmigung: `function_calling.py` → `ha_client.py` → HA API
7. Benachrichtigung an User (abhaengig vom Level)

**Bruchstellen**:
- Default Level 2 = **keine autonomen Aktionen** ohne explizite User-Konfiguration
- `spontaneous_observer.py` beobachtet Muster, loest aber keine Aktionen direkt aus — nur Insights
- `threat_assessment.py` wird bei autonomen Aktionen **NICHT** konsultiert (kein Code-Pfad dafuer)
- Autonomy-Level ist global, nicht per-Aktion konfigurierbar

**Fehler-Pfade**:
- Confidence < 0.95 → Aktion wird nur vorgeschlagen
- Blacklisted Aktion → Blockiert unabhaengig vom Level (kein Override)
- HA nicht erreichbar → Tool-Execution schlaegt fehl, User wird informiert

**Sicherheits-Bewertung**: Das Framework ist solide konservativ:
- Safety Blacklist (hardcoded, nicht manipulierbar)
- Double-Gate Mechanismus (hohe Schwelle)
- Default Level 2 = kein Risiko ohne User-Eingriff

---

### Flow 5: Persoenlichkeits-Pipeline

**Status**: ✅ Funktioniert (als System-Prompt, nicht Post-Processing)

**Ablauf**:
1. `personality.py:242-286` SYSTEM_PROMPT_TEMPLATE definiert Jarvis-Charakter
2. `personality.py:build_system_prompt()` setzt dynamische Teile ein:
   - Sarkasmus-Level (1-5, hard cap bei 4: `min(sarcasm_level, 4)`)
   - Formality Score (30-80, decay pro Tag)
   - Mood-basierte Anpassung (via `mood_detector.py`)
   - Time-Layer (Tageszeit-Stil)
   - Humor-Templates (level-abhaengig)
   - Character-Lock gegen Jailbreaking
3. `brain.py:2655-2662` System-Prompt mit context, formality_score, irony_count gebaut
4. **Persoenlichkeit wird VOR dem LLM-Call als System-Prompt injiziert** (bevorzugt)
5. `brain.py:3091-3098` Character-Lock Reminder bei langen Konversationen
6. Post-LLM Persoenlichkeits-Checks bei Tool-Call-Antworten:
   - `personality.check_opinion()` (brain.py:3739) — Jarvis kommentiert Aktionen
   - `personality.check_pushback()` (brain.py:3522) — Warnung vor Ausfuehrung
   - `personality.check_escalation()` (brain.py:3760) — Trockenerer Ton bei Wiederholungen
   - `personality.generate_contextual_humor()` (brain.py:3773) — Kontext-Humor
   - `personality.check_curiosity()` (brain.py:3791) — Neugier bei untypischem Verhalten

**Bruchstellen**:
- Keine signifikanten Bruchstellen — Pipeline ist solide implementiert
- Sarkasmus hard cap bei 4 verhindert "zu scharfe" Antworten
- Character-Lock Reminder ist eine effektive Loesung gegen Kontext-Drift

**Konsistenz**: Sarkasmus-Level ist konsistent ueber den gesamten Flow — im System-Prompt, in Post-LLM-Checks, und im Refinement-Prompt (brain.py:3841-3847).

---

### Flow 6: Memory-Abruf (Erinnerung)

**Status**: ⚠️ Teilweise (Pfad vorhanden, aber kein "Ich erinnere mich nicht"-Fallback)

**Ablauf**:
1. `pre_classifier.py` erkennt MEMORY-Profil (Schluesselwoerter: "erinnerst du dich", "was habe ich gesagt", etc.)
2. `brain.py:~2200-2210` Intent-Type "memory" gesetzt
3. `brain.py:3179-3203` **Separater Memory-Pfad**:
   - `memory.semantic.search_by_topic(text, limit=5)` → ChromaDB Semantic-Suche
   - Ergebnisse als "GESPEICHERTE FAKTEN" in System-Prompt injiziert (brain.py:3186-3190)
   - LLM (Smart-Modell) formuliert Antwort basierend auf Fakten
4. **Zusaetzlich** im Mega-Gather: `brain.py:2374` `_get_conversation_memory(text)`:
   - `brain.py:5567-5581` `search_memories(text, limit=3)` → ChromaDB `mha_conversations` (**GEFIXT in DL#1**)
   - Semantische Suche ueber vergangene Gespraeche als P2-Sektion

**Bruchstellen**:
- `brain.py:3186-3189`: Wenn `memory_facts` leer → System-Prompt wird **NICHT** um "Keine Erinnerungen gefunden" ergaenzt. Das LLM erhaelt keinen expliziten Hinweis dass nichts gefunden wurde → **Halluzinations-Risiko**.
- Die FAKTEN-REGEL im System-Prompt ("Erfinde NICHTS") ist der einzige Schutz — reicht bei lokalen LLMs nicht immer.

**Fehler-Pfade**:
- ChromaDB nicht erreichbar → `search_by_topic()` gibt leere Liste zurueck → LLM antwortet ohne Fakten
- Kein expliziter Fallback "Dazu habe ich keine Erinnerung" — LLM muss FAKTEN-REGEL selbst befolgen
- MEMORY-Profil im PreClassifier ueberspringt Mood/Formality/Irony/RAG (sinnvoll fuer Latenz)

**Verbesserung gegenueber DL#1**: ChromaDB-Episodes werden jetzt tatsaechlich gelesen (brain.py:5569), daher liefert die Suche haeufiger Ergebnisse. Halluzinations-Risiko ist dadurch **reduziert**, aber nicht eliminiert.

---

### Flow 7: Speech-Pipeline

**Status**: ⚠️ Teilweise (funktioniert, aber hohe End-to-End Latenz + Timeout-Mismatch)

**Ablauf**:
1. Audio-Input via ESPHome Satellite oder Mikrofon → HA Voice Pipeline
2. `speech/server.py:102-122` Wyoming ASR Server auf TCP:10300 (faster-whisper)
3. `speech/handler.py:126-163` Wyoming Event Handler: Whisper STT + parallele ECAPA-TDNN Voice Embedding
4. HA Assist Pipeline leitet transkribierten Text weiter
5. `ha_integration/.../conversation.py:41-98` `MindHomeAssistantAgent`:
   - `_detect_room()`: Raum aus HA Device Registry (Area des Satellites)
   - Voice-Metadaten berechnen (Wortanzahl, Dauer)
   - `device_id` fuer Speaker Recognition setzen
6. `conversation.py:108-117` HTTP POST an `{url}/api/assistant/chat` (30s Timeout)
7. `brain.py:1089` `process()` → **Flow 1** (Hauptpfad)
8. `brain.py:1110-1112` `_request_from_pipeline` erkannt → brain.py macht KEIN TTS (HA Pipeline uebernimmt)
9. Response zurueck an HA Conversation → Piper TTS → Satellite Speaker

**Bruchstellen**:
- **Latenz**: STT (1-3s) + HTTP (50ms) + brain.process() (3-15s) + TTS (1-2s) = **5-20s End-to-End**
- **Timeout-Mismatch**: `conversation.py:113` hat 30s Timeout, aber LLM Deep-Modell hat 120s Timeout (brain.py:3237). Bei komplexen Anfragen via Sprache → HA-Seite gibt auf bevor Antwort fertig.
- `_request_from_pipeline` Flag: Korrekt implementiert — verhindert doppelte TTS-Ausgabe (brain/HA)

**Fehler-Pfade**:
- STT fehlschlaegt → `_normalize_stt_text()` (brain.py:1114) korrigiert typische Whisper-Fehler + `stt_hint` Section im System-Prompt (brain.py:2733-2739) → LLM beruecksichtigt phonetische Aehnlichkeit
- HTTP Timeout in conversation.py → "Ich kann gerade nicht denken." (conversation.py:100)
- HA-Pipeline Bridge down → Keine Spracheingabe, Text-API funktioniert weiter

**Speaker Recognition**: ECAPA-TDNN Embeddings werden in `speech/handler.py:126` parallel zur STT extrahiert. Werden via `device_id` an brain.py weitergegeben → `speaker_recognition.py` mappt auf Person. Funktioniert fuer bekannte Stimmen.

**Multi-Room**: Antwortet im richtigen Raum — `_detect_room()` nutzt HA Area Registry. `_request_from_pipeline` verhindert doppelte Ausgabe.

**ambient_audio.py**: Nicht direkt in der Speech-Pipeline integriert — separates Modul fuer Hintergrund-Audio-Klassifizierung. Keine automatische Pause/Resume bei Sprachinteraktion.

---

## 4. Kritische Findings

### Top-5 Probleme (sortiert nach Impact)

| # | Problem | Datei:Zeile | Schwere | Impact |
|---|---------|------------|---------|--------|
| 1 | **proactive.start() nicht in _safe_init()** | `brain.py:773` | KRITISCH | Exception crasht gesamte Init → Jarvis startet nicht. Alle ~54 Module geschuetzt, nur dieses nicht. |
| 2 | **_process_lock serialisiert ALLES** | `brain.py:215, 1103` | HOCH | Nur 1 Request gleichzeitig. Bei LLM-Timeout (30-120s) blockiert: User-Requests, Proaktive Meldungen, Routinen. Kein Lock-Timeout. |
| 3 | **Memory-Flow ohne "Ich erinnere mich nicht"** | `brain.py:3186-3189` | HOCH | Leere ChromaDB-Ergebnisse → kein Hinweis ans LLM → Halluzinations-Risiko bei Erinnerungsfragen. |
| 4 | **Speech-Pipeline Timeout-Mismatch** | `conversation.py:113` vs `brain.py:3237` | MITTEL | 30s HA-Timeout vs 120s LLM Deep-Timeout. Komplexe Sprach-Anfragen scheitern an HA-Seite. |
| 5 | **Shared Schemas nicht genutzt** | `shared/schemas/` | MITTEL | ChatRequest/ChatResponse existieren, werden im Hauptpfad ignoriert. main.py + conversation.py definieren eigene Formate → Schema-Drift. |

---

## KONTEXT AUS PROMPT 3a: Flow-Analyse (Core-Flows) — DL#3

### Init-Sequenz
```
main.py:322 lifespan() → brain.initialize() (brain.py:481)
  → memory.initialize() (Redis + ChromaDB)
  → model_router.initialize() (Ollama)
  → ~54 Module via _safe_init() (F-069 Graceful Degradation)
  → proactive.start() ✅ JETZT in _safe_init() (brain.py:776)
  → Entity-Katalog laden
main.py:347 Health-Check + Status-Logging
main.py:361 Boot-Announcement (Sprachansage)
```

### System-Prompt (rekonstruiert, nach P02 Fixes)
```
Statisch: personality.py:242-286 SYSTEM_PROMPT_TEMPLATE
  → Jarvis MCU-Charakter, TON, VERBOTEN-Liste, FAKTEN-REGEL
Dynamisch: brain.py:2664-3021 P1-P4 Sektionen
  → P1 (immer): Scene, Confidence, Mood, Security, Memory, Last-Action, Files, Model-Hint, Conv-Memory-Ext (P02: 3→1)
  → P2 (wichtig): Time, Timers, Conv-Memory, Problems, Corrections, Jarvis-Thinks, Dialogue
  → P3 (optional): RAG, Summaries, Anomalies, Continuity, Calendar, Learning
  → P4 (wenn-platz): Tutorial
Token-Budget: ollama_num_ctx - 800, ~45% Auslastung, P1 unbegrenzt
Memory: Confidence≥0.4 (P02: war 0.6), Relevance>0.2 (P02: war 0.3), limit=10 (P02: war 3)
```

### Flow-Status-Uebersicht (Core-Flows 1–7) — DL#3

| Flow | Status | Kritischste Bruchstelle |
|---|---|---|
| 1: Sprach-Input → Antwort | ⚠️ Teilweise | `_process_lock` serialisiert alles (brain.py:1103) |
| 2: Proaktive Benachrichtigung | ✅ Verbessert | proactive.start() jetzt in _safe_init (brain.py:776) ✅ |
| 3: Morgen-Briefing | ✅ Funktioniert | Konsistenter Jarvis-Ton durch brain.process() |
| 4: Autonome Aktion | ⚠️ Teilweise | Default Level 2 = keine Aktionen; threat_assessment nicht konsultiert |
| 5: Persoenlichkeits-Pipeline | ✅ Funktioniert | Keine signifikanten Bruchstellen |
| 6: Memory-Abruf | ✅ Verbessert | "ERFINDE KEINE Erinnerungen"-Hint jetzt vorhanden (brain.py:3216) ✅ |
| 7: Speech-Pipeline | ⚠️ Teilweise | Timeout-Mismatch: conversation.py 30s vs LLM 120s |

### Top-Bruchstellen (Core-Flows) — DL#3
1. ~~`brain.py:773` — proactive.start() nicht in _safe_init()~~ ✅ GEFIXT
2. `brain.py:215,1103` — _process_lock serialisiert alle Requests (HOCH)
3. ~~`brain.py:3186-3189` — Memory-Flow ohne Fallback-Hint~~ ✅ GEFIXT (brain.py:3216-3224)
4. `conversation.py:112` — 30s Timeout vs 120s LLM-Timeout (MITTEL)
5. `main.py:630-655` — Keine Shared Schemas, ChatRequest/ChatResponse lokal (MITTEL)

### Verbleibende Offene Punkte
- HOCH: `_process_lock` serialisiert alle Requests → ARCHITEKTUR_NOETIG
- MITTEL: conversation.py 30s Timeout → Erhoehung auf 60s empfohlen
- MITTEL: Keine Shared Schemas → Schema in eigenem Modul definieren

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT (seit DL#2):
- proactive.start() in _safe_init() gewrappt (brain.py:776)
- Memory-Halluzinations-Schutz: "ERFINDE KEINE Erinnerungen" Prompt (brain.py:3216-3224)
- conv_memory_ext Priority 3→1 (brain.py:2973)
- Memory-Confidence 0.6→0.4, Relevance 0.3→0.2
- Memory-Keywords 22+ (brain.py:8053)
- get_recent_conversations limit=10
OFFEN:
- HOCH: _process_lock serialisiert alle Requests (brain.py:215,1103) | ARCHITEKTUR_NOETIG
- MITTEL: conversation.py:112 Timeout 30s vs LLM 120s | Einfacher Fix
- MITTEL: Keine Shared Schemas (main.py:630-655) | Refactoring
- MITTEL: Flow 4 Autonome Aktion: Default Level 2, kein Auto-Execute
GEAENDERTE DATEIEN: [Keine Code-Aenderungen — reiner Analyse+Doku-Update]
REGRESSIONEN: [Keine]
NAECHSTER SCHRITT: Prompt 3b — Extended-Flows 8-13 + Flow-Kollisionen
===================================
```
