# Prompt 4: Systematische Bug-Jagd

## Rolle

Du bist ein Elite-Debugging-Experte für Python, AsyncIO, FastAPI, Redis, ChromaDB und Home Assistant. Du findest Bugs die andere übersehen — fehlende awaits, stille Exceptions, Race Conditions, Type-Fehler.

---

## Kontext aus vorherigen Prompts

> **[HIER die Konflikt-Karte aus Prompt 1 einfügen]**

> **[HIER die Memory-Analyse aus Prompt 2 einfügen]**

> **[HIER die Flow-Analyse aus Prompt 3 einfügen]**

---

## Aufgabe

Prüfe **jedes Modul** in `/assistant/assistant/` systematisch auf die folgenden 10 Fehlerklassen. Arbeite die Module in der angegebenen Prioritätsreihenfolge ab.

---

## Die 10 Fehlerklassen

| # | Klasse | Was suchen | Beispiel |
|---|---|---|---|
| 1 | **Async-Fehler** | Fehlende `await`, Fire-and-Forget, nicht-awaited Coroutines | `memory.store(data)` statt `await memory.store(data)` |
| 2 | **Stille Fehler** | `except: pass`, `except Exception: pass`, leere Catch-Blöcke, verschluckte Errors | `try: ... except: logger.debug(...)` ohne Re-raise |
| 3 | **Race Conditions** | Shared State ohne Locks, gleichzeitige Zugriffe auf Dicts/Listen | Zwei Coroutines die gleichzeitig ein Dict modifizieren |
| 4 | **None-Fehler** | Zugriff auf Attribute/Keys von None, fehlende None-Checks | `result["key"]` wenn result None sein kann |
| 5 | **Init-Fehler** | Race Conditions beim Start, fehlende Dependencies, falsche Reihenfolge | Modul A braucht Modul B, aber B ist noch nicht initialisiert |
| 6 | **API-Fehler** | Falsche HA-Endpunkte, fehlende Timeouts, Auth-Probleme | `POST /api/services/light/turn_on` ohne Timeout |
| 7 | **Daten-Fehler** | Falsche JSON-Serialisierung, Redis-Encoding, falsches Schema | `json.dumps(obj)` wenn obj nicht serialisierbar ist |
| 8 | **Config-Fehler** | settings.yaml-Werte die nicht geladen oder falsch interpretiert werden | `settings["timeout"]` existiert nicht in YAML |
| 9 | **Memory Leaks** | Listen/Dicts die unbegrenzt wachsen, fehlende Cleanup-Mechanismen | `self.history.append(...)` ohne Limit |
| 10 | **Logik-Fehler** | Falsche if-Bedingungen, Off-by-One, invertierte Booleans, Dead Code | `if not enabled:` wenn `enabled` den inversen Sinn hat |

---

## Modul-Priorität

Prüfe in dieser Reihenfolge (höchster Impact zuerst):

### Priorität 1 — Kern (MUSS geprüft werden)
1. `brain.py` — Orchestrator
2. `memory.py` — Working Memory
3. `semantic_memory.py` — Langzeit-Fakten
4. `conversation.py` — Gesprächsverlauf
5. `conversation_memory.py` — Konversations-Gedächtnis
6. `context_builder.py` — Prompt-Bau
7. `personality.py` — Persönlichkeits-Engine

### Priorität 2 — Aktionen & Inference
8. `function_calling.py` — Tool-Ausführung
9. `action_planner.py` — Multi-Step-Planung
10. `ollama_client.py` — LLM-Inference
11. `model_router.py` — Model-Routing
12. `main.py` — FastAPI-Server

### Priorität 3 — Proaktive Systeme
13. `proactive.py` — Proaktive Events
14. `routine_engine.py` — Routinen
15. `anticipation.py` — Prädiktive Patterns
16. `autonomy.py` — Autonomie-Level
17. `self_automation.py` — Auto-Automationen

### Priorität 4 — Intelligence & Monitoring
18. `insight_engine.py` — Cross-Referencing
19. `learning_observer.py` — Lern-Patterns
20. `mood_detector.py` — Stimmungserkennung
21. `health_monitor.py` — Health-Alerts
22. `device_health.py` — Anomalie-Erkennung
23. `light_engine.py` — Circadian Rhythm
24. `speaker_recognition.py` — Stimm-Identifikation

### Priorität 5 — Alle übrigen Module
25+ — Alle weiteren `.py` Dateien in `/assistant/assistant/`

---

## Spezifische Problemzonen (aus Dokumentation bekannt)

Prüfe diese **dokumentierten aber möglicherweise nicht gefixten** Issues:

| Quelle | Behauptung | Verifiziere im Code |
|---|---|---|
| `JARVIS_STATUS.md` | Bugs B1–B6 sind gefixt | Wirklich gefixt? Oder nur dokumentiert? |
| `JARVIS_FEATURES_IMPLEMENTATION.md` | 5 Bugfixes implementiert | Code prüfen — sind die Fixes korrekt? |
| `JARVIS_SELF_IMPROVEMENT.md` | 9 Self-Learning Features | Wie viele sind echte Implementierungen vs. nur Stubs? |
| `docs/JARVIS_AUDIT.md` | Audit-Findings | Wurden die Findings behoben? |
| Protocol Engine | 5 Bugs dokumentiert | Wirklich alle gefixt? |
| Insight Engine | "70% fertig" | Was fehlt konkret? |
| Token Streaming | "Komplett fehlend" | Stimmt das noch? |
| Interrupt Queueing | "Komplett fehlend" | Stimmt das noch? |

---

## Output-Format

### Bug-Report-Tabelle

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|---|---|---|---|---|---|
| 1 | 🔴 KRITISCH | brain.py | :123 | Async-Fehler | Fehlender await bei memory.load() | `await memory.load()` |
| 2 | 🟠 HOCH | ... | ... | ... | ... | ... |

### Severity-Definition

- 🔴 **KRITISCH** — Absturz, Datenverlust, Kern-Funktion komplett kaputt
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

### Dokumentations-Verifikation

| Behauptung | Status | Beweis |
|---|---|---|
| Bug B1 gefixt | ✅/❌ | Code-Referenz |
| ... | ... | ... |

---

## Regeln

- **Jeder Bug mit Code-Referenz** (Datei:Zeile)
- **Keine false positives** — nur echte Bugs, keine Style-Issues
- **Nicht fixen in diesem Prompt** — nur finden und dokumentieren (Fixes kommen in Prompt 6)
- Priorität 1 Module **komplett** prüfen — bei niedrigeren Prioritäten nach Zeitbudget
- Wenn ein `except: pass` wirklich intentional ist (z.B. optional Feature): Notiere es trotzdem, aber als 🟢
- **Async-Fehler haben höchste Aufmerksamkeit** — sie sind die häufigste Ursache für "funktioniert manchmal"
