# Prompt 4: Systematische Bug-Jagd

## Rolle

Du bist ein Elite-Debugging-Experte für Python, AsyncIO, FastAPI, Flask, Redis, ChromaDB und Home Assistant. Du findest Bugs die andere übersehen — fehlende awaits, stille Exceptions, Race Conditions, Type-Fehler, Security-Lücken.

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode, nicht mit einem laufenden System. Prüfe auch wie der Code mit fehlenden `.env`-Werten, fehlenden Credentials und nicht-erreichbaren Services umgeht.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–3 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier ein:
> - Kontext-Block aus Prompt 1 (Konflikt-Karte)
> - Kontext-Block aus Prompt 2 (Memory-Analyse)
> - Kontext-Block aus Prompt 3 (Flow-Analyse, besonders Bruchstellen und Kollisionen)

---

## Aufgabe

Prüfe **jedes Modul** systematisch auf die folgenden **12 Fehlerklassen**. Arbeite die Module in der angegebenen Prioritätsreihenfolge ab.

---

## Die 12 Fehlerklassen

| # | Klasse | Was suchen | Beispiel |
|---|---|---|---|
| 1 | **Async-Fehler** | Fehlende `await`, Fire-and-Forget, nicht-awaited Coroutines | `memory.store(data)` statt `await memory.store(data)` |
| 2 | **Stille Fehler** | `except: pass`, `except Exception: pass`, leere Catch-Blöcke | `try: ... except: logger.debug(...)` ohne Re-raise |
| 3 | **Race Conditions** | Shared State ohne Locks, gleichzeitige Dict/List-Zugriffe | Zwei Coroutines modifizieren gleichzeitig ein Dict |
| 4 | **None-Fehler** | Zugriff auf Attribute/Keys von None, fehlende None-Checks | `result["key"]` wenn result None sein kann |
| 5 | **Init-Fehler** | Race Conditions beim Start, fehlende Dependencies | Modul A braucht B, aber B ist noch nicht initialisiert |
| 6 | **API-Fehler** | Falsche HA-Endpunkte, fehlende Timeouts, Auth-Probleme | API-Call ohne Timeout |
| 7 | **Daten-Fehler** | Falsche JSON-Serialisierung, Redis-Encoding | `json.dumps(obj)` wenn obj nicht serialisierbar |
| 8 | **Config-Fehler** | settings.yaml-Werte die nicht geladen/genutzt werden | Key existiert nicht in YAML |
| 9 | **Memory Leaks** | Listen/Dicts die unbegrenzt wachsen, fehlende Cleanup | `self.history.append(...)` ohne Limit |
| 10 | **Logik-Fehler** | Falsche if-Bedingungen, Off-by-One, invertierte Booleans | Dead Code, unerreichbare Branches |
| 11 | **Security** | Prompt Injection, unvalidierte Inputs, fehlende Auth | User-Input direkt im System-Prompt ohne Sanitization |
| 12 | **Resilience** | Fehlende Fehlertoleranz bei Service-Ausfall | Was wenn Ollama/Redis/ChromaDB/HA down ist? |

---

## Modul-Priorität

### Priorität 1 — Kern (MUSS komplett geprüft werden)
1. `brain.py` — Orchestrator, höchster Impact
2. `brain_callbacks.py` — Event Hooks
3. `main.py` — FastAPI-Server, Endpoints
4. `websocket.py` — WebSocket-Server

### Priorität 2 — Memory-Kette
5. `memory.py` — Working Memory
6. `semantic_memory.py` — Langzeit-Fakten
7. `ha_integration/.../conversation.py` — HA Voice Pipeline Bridge (prüfe ob korrekt mit Assistant verbunden)
8. `conversation_memory.py` — Konversations-Gedächtnis
9. `memory_extractor.py` — Fakten-Extraktion
10. `correction_memory.py` — Korrektur-Lernen
11. `dialogue_state.py` — Konversations-State
12. `embeddings.py` — Embedding-Modelle
13. `embedding_extractor.py` — Text → Embedding

### Priorität 3 — Prompt & Persönlichkeit
14. `context_builder.py` — Prompt-Bau (Security! Prompt Injection!)
15. `personality.py` — Persönlichkeits-Engine
16. `mood_detector.py` — Stimmungserkennung
17. `situation_model.py` — Situations-Kontext
18. `time_awareness.py` — Tageszeit

### Priorität 4 — Aktionen & Inference
19. `function_calling.py` — Tool-Ausführung
20. `function_validator.py` — Validierung
21. `declarative_tools.py` — Tool-Definitionen
22. `action_planner.py` — Multi-Step-Planung
23. `ollama_client.py` — LLM-Inference
24. `model_router.py` — Model-Routing
25. `pre_classifier.py` — Intent-Vorklassifikation
26. `request_context.py` — Request State

### Priorität 5 — Proaktive Systeme
27. `proactive.py` — Proaktive Events
28. `proactive_planner.py` — Proaktive Planung
29. `routine_engine.py` — Routinen
30. `anticipation.py` — Prädiktive Patterns
31. `spontaneous_observer.py` — Ungefragte Beobachtungen
32. `autonomy.py` — Autonomie-Level
33. `self_automation.py` — Auto-Automationen
34. `conditional_commands.py` — If/Then
35. `protocol_engine.py` — Protokolle

### Priorität 6 — HA-Integration & Audio
36. `ha_client.py` — HA-API Client (Timeouts! Auth! Resilience!)
37. `light_engine.py` — Circadian Rhythm
38. `climate_model.py` — Klima-Steuerung
39. `cover_config.py` — Rollladen
40. `camera_manager.py` — Kameras
41. `tts_enhancer.py` — TTS-Aufbereitung
42. `sound_manager.py` — Audio-Wiedergabe
43. `ambient_audio.py` — Hintergrund-Audio
44. `multi_room_audio.py` — Multi-Room
45. `speaker_recognition.py` — Stimm-ID

### Priorität 7 — Intelligence & Self-Improvement
46. `insight_engine.py` — Cross-Referencing
47. `learning_observer.py` — Lern-Patterns
48. `learning_transfer.py` — Wissenstransfer
49. `self_optimization.py` — Self-Improvement
50. `self_report.py` — Diagnostik
51. `feedback.py` — User-Feedback
52. `response_quality.py` — Antwort-Qualität
53. `intent_tracker.py` — Intent-Tracking
54. `outcome_tracker.py` — Outcome-Tracking

### Priorität 8 — Resilience & Sicherheit
55. `error_patterns.py` — Error-Klassifikation
56. `circuit_breaker.py` — Fehlertoleranz
57. `conflict_resolver.py` — Konflikt-Lösung
58. `adaptive_thresholds.py` — Dynamische Schwellwerte
59. `threat_assessment.py` — Bedrohungserkennung
60. `config.py` — Config-Laden
61. `constants.py` — Konstanten
62. `config_versioning.py` — Config-Versionierung

### Priorität 9 — Domain-Assistenten & Monitoring
63. `cooking_assistant.py`, `recipe_store.py`
64. `music_dj.py`
65. `smart_shopping.py`
66. `calendar_intelligence.py`
67. `inventory.py`
68. `web_search.py`, `knowledge_base.py`, `summarizer.py`
69. `ocr.py`, `file_handler.py`
70. `workshop_library.py`, `workshop_generator.py`
71. `health_monitor.py`, `device_health.py`
72. `energy_optimizer.py`, `predictive_maintenance.py`, `repair_planner.py`
73. `visitor_manager.py`, `follow_me.py`
74. `wellness_advisor.py`, `activity.py`
75. `seasonal_insight.py`
76. `explainability.py`
77. `diagnostics.py`
78. `task_registry.py`

### Priorität 10 — Addon-Module (NICHT vergessen!)
79. `addon/rootfs/opt/mindhome/app.py` — Flask-App
80. `addon/rootfs/opt/mindhome/ha_connection.py` — HA-Anbindung
81. `addon/rootfs/opt/mindhome/event_bus.py` — Event-Bus
82. `addon/rootfs/opt/mindhome/automation_engine.py` — Automationen
83. `addon/rootfs/opt/mindhome/pattern_engine.py` — Pattern-Matching
84. `addon/rootfs/opt/mindhome/domains/*.py` — Alle Domain-Module
85. `addon/rootfs/opt/mindhome/engines/*.py` — Alle Engine-Module

### Priorität 11 — Speech-Server
86. `speech/server.py`
87. `speech/handler.py`

### Priorität 12 — Shared-Module & HA-Integration
88. `shared/constants.py` — Stimmen die Port-Definitionen mit den tatsächlich genutzten Ports überein?
89. `shared/schemas/chat_request.py` — Wird `ChatRequest` überall verwendet wo Requests gesendet werden?
90. `shared/schemas/chat_response.py` — Wird `ChatResponse` überall verwendet wo Responses erzeugt werden?
91. `shared/schemas/events.py` — Werden die Event-Typen konsistent genutzt?
92. `ha_integration/.../config_flow.py` — Validierung, Error Handling
93. `ha_integration/.../__init__.py` — Setup/Teardown korrekt?

---

## Spezifische Problemzonen (aus Dokumentation bekannt)

| Quelle | Behauptung | Verifiziere im Code |
|---|---|---|
| `JARVIS_STATUS.md` | Bugs B1–B6 sind gefixt | Wirklich gefixt? |
| `JARVIS_FEATURES_IMPLEMENTATION.md` | 5 Bugfixes implementiert | Fixes korrekt? |
| `JARVIS_SELF_IMPROVEMENT.md` | 9 Self-Learning Features | Implementiert oder nur Stubs? |
| `docs/JARVIS_AUDIT.md` | Audit-Findings | Findings behoben? |
| Protocol Engine | 5 Bugs dokumentiert | Alle gefixt? |
| Insight Engine | "70% fertig" | Was fehlt? |
| Token Streaming | "Komplett fehlend" | Stimmt noch? |
| Interrupt Queueing | "Komplett fehlend" | Stimmt noch? |

## Security-Checks (NEU)

Prüfe **besonders**:

| # | Security-Check | Modul | Was prüfen |
|---|---|---|---|
| 1 | Prompt Injection | `context_builder.py` | Wird User-Input sanitized bevor er im System-Prompt landet? |
| 2 | Input Validation | `main.py`, `websocket.py` | Werden API-Inputs validiert? (**200+ Endpoints in main.py!**) |
| 3 | HA-Auth | `ha_client.py` | Werden Credentials sicher gehandhabt? |
| 4 | Function Call Safety | `function_calling.py`, `function_validator.py` | Können bösartige Tool-Calls ausgeführt werden? |
| 5 | Self-Automation Safety | `self_automation.py` | Kann Jarvis gefährliche HA-Automationen generieren? |
| 6 | Autonomy Limits | `autonomy.py` | Gibt es harte Grenzen für autonome Aktionen? |
| 7 | Threat Assessment | `threat_assessment.py` | Funktioniert es? Wird es genutzt? |
| 8 | **Factory Reset** | `main.py` | Ist `/api/ui/factory-reset` ausreichend geschützt? Wer kann es aufrufen? |
| 9 | **System Update/Restart** | `main.py` | Sind `/api/ui/system/update` und `/restart` geschützt? Kann ein Angreifer das System übernehmen? |
| 10 | **API-Key Management** | `main.py` | Ist `/api/ui/api-key/regenerate` geschützt? Recovery-Key-Logik sicher? |
| 11 | **PIN-Auth** | `main.py` | Ist die PIN-Authentifizierung (`/api/ui/auth`) sicher? Brute-Force-Schutz? |
| 12 | **File Upload** | `main.py`, `file_handler.py`, `ocr.py` | Path Traversal, Injection über Dateinamen, Dateigröße, MIME-Type? |
| 13 | **Workshop Hardware-Steuerung** | `main.py` | Sind `/api/workshop/arm/*` (Roboter-Arm) und `/api/workshop/printer/*` (3D-Drucker) Trust-Level-geschützt? |
| 14 | **Sensitive Data in Logs** | `main.py` | Werden API-Keys/Tokens in Error/Activity Buffer redacted? |
| 15 | **WebSearch SSRF** | `web_search.py` | IP-Blocklist, DNS-Rebinding-Check, URL-Validierung |

## Resilience-Checks (NEU)

| # | Szenario | Was sollte passieren | Was passiert? | Code-Referenz |
|---|---|---|---|---|
| 1 | Ollama nicht erreichbar | Graceful Error, User informieren | ? | ? |
| 2 | Redis nicht erreichbar | Degraded Mode ohne Memory | ? | ? |
| 3 | ChromaDB nicht erreichbar | Fallback auf Redis-only | ? | ? |
| 4 | Home Assistant nicht erreichbar | Fehlermeldung, kein Crash | ? | ? |
| 5 | Speech-Server nicht erreichbar | Text-only Mode | ? | ? |
| 6 | Addon nicht erreichbar | Assistant funktioniert standalone | ? | ? |
| 7 | Netzwerk-Timeout bei LLM-Call | Retry mit Backoff? Timeout-Wert? | ? | ? |
| 8 | Ungültiges LLM-Response-Format | Parsing-Fehler abfangen | ? | ? |
| 9 | `circuit_breaker.py` | Wird es überhaupt genutzt? Von welchen Modulen? | ? | ? |
| 10 | `error_patterns.py` | Werden Fehler klassifiziert? Führt das zu Verbesserungen? | ? | ? |

---

## Output-Format

### Bug-Report-Tabelle

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|---|---|---|---|---|---|
| 1 | 🔴 KRITISCH | brain.py | :123 | Async-Fehler | Fehlender await bei memory.load() | `await memory.load()` |
| 2 | 🟠 HOCH | ... | ... | ... | ... | ... |

### Severity-Definition

- 🔴 **KRITISCH** — Absturz, Datenverlust, Security-Lücke, Kern-Funktion komplett kaputt
- 🟠 **HOCH** — Feature funktioniert nicht, aber kein Crash
- 🟡 **MITTEL** — Logik-Fehler, Inkonsistenz, fehlende Integration
- 🟢 **NIEDRIG** — Code-Qualität, Performance, nicht-funktionale Probleme

### Statistik

```
Gesamt: X Bugs
  🔴 KRITISCH: X
  🟠 HOCH: X
  🟡 MITTEL: X
  🟢 NIEDRIG: X

Häufigste Fehlerklasse: [Name] (X Vorkommen)
Am stärksten betroffenes Modul: [Name] (X Bugs)
```

### Security-Report

| # | Risiko | Modul | Beschreibung | Empfehlung |
|---|---|---|---|---|
| 1 | ? | ? | ? | ? |

### Resilience-Report (ausgefüllt)

### Dokumentations-Verifikation

| Behauptung | Status | Beweis |
|---|---|---|
| Bug B1 gefixt | ✅/❌ | Code-Referenz |
| ... | ... | ... |

### Dead-Code-Liste

Module oder Funktionen die existieren aber **nie aufgerufen** werden.

---

## Regeln

### Gründlichkeits-Pflicht

> **Öffne JEDES Modul in der Prioritätsliste. KEIN Modul überspringen.**
>
> Für jedes Modul: Öffne die Datei, lies die Klasse/Funktionen, prüfe jeden `try/except`, jeden `await`, jeden Dict/List-Zugriff, jede API-Call. Wenn du ein Modul nicht geprüft hast, dokumentiere WARUM.
>
> Ein übersehener kritischer Bug kann das ganze System zum Absturz bringen. Lieber langsam und gründlich als schnell und oberflächlich.

- **Jeder Bug mit Code-Referenz** (Datei:Zeile)
- **Keine false positives** — nur echte Bugs, keine Style-Issues
- **Nicht fixen in diesem Prompt** — nur finden und dokumentieren (Fixes kommen in Prompt 6)
- **ALLE Module prüfen** — Priorität 1–4 besonders gründlich, aber KEIN Modul überspringen (Priorität 1–12). Jedes Modul mindestens auf die Top-5 Fehlerklassen (Async, Stille Fehler, Race Conditions, None, Init) checken
- **Async-Fehler haben höchste Aufmerksamkeit** — häufigste Ursache für "funktioniert manchmal"
- **Security-Bugs sind immer 🔴 KRITISCH**
- **Addon-Module NICHT vergessen** — sie haben eigene Bugs und eigene HA-Integration
- Wenn ein `except: pass` intentional ist: Trotzdem notieren als 🟢

---

## ⚡ Übergabe an Prompt 5

Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block** für Prompt 5:

```
## KONTEXT AUS PROMPT 4: Bug-Report

### Statistik
Gesamt: X Bugs (🔴 X, 🟠 X, 🟡 X, 🟢 X)

### Kritische Bugs (🔴)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Hohe Bugs (🟠)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Security-Report
[Findings mit Severity]

### Resilience-Report
[Welche Ausfälle abgefangen werden, welche nicht]

### Dokumentations-Verifikation
[Welche behaupteten Fixes stimmen, welche nicht]

### Dead-Code-Liste
[Module/Funktionen die nie aufgerufen werden]
```

**Wenn du Prompt 5 in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke (Prompt 1–4) automatisch ein.
