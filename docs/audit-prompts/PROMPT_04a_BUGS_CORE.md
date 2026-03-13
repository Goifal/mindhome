# Prompt 4a: Systematische Bug-Jagd — Assistant-Core (Priorität 1–4)

## Rolle

Du bist ein Elite-Debugging-Experte für Python, AsyncIO, FastAPI, Redis, ChromaDB und Home Assistant. Du findest Bugs die andere übersehen — fehlende awaits, stille Exceptions, Race Conditions, Type-Fehler, Security-Lücken.

---

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode, nicht mit einem laufenden System. Prüfe auch wie der Code mit fehlenden `.env`-Werten, fehlenden Credentials und nicht-erreichbaren Services umgeht.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–3b bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier ein:
> - Kontext-Block aus Prompt 1 (Konflikt-Karte)
> - Kontext-Block aus Prompt 2 (Memory-Analyse)
> - Kontext-Block aus Prompt 3a + 3b (Flow-Analyse, besonders Bruchstellen und Kollisionen)
>
> **⚠️ OHNE diese Kontext-Blöcke fehlt dir das Architektur-Verständnis für die Bug-Analyse!** Besonders die Konflikt-Karte (P1) und Flow-Bruchstellen (P3a/3b) sind essentiell um Bugs im Kontext zu verstehen. Wenn du die Blöcke nicht hast, starte zuerst mit Prompt 1.

---

## Aufgabe

Prüfe die **Core-Module** (Priorität 1–4, ca. 26 Module) systematisch auf die folgenden **13 Fehlerklassen**.

> **Dieser Prompt ist Teil 1 von 3** der Bug-Jagd:
> - **P04a** (dieser): Core-Module (brain, main, memory, context, actions) — Priorität 1–4
> - **P04b**: Extended-Module (proaktiv, HA, audio, intelligence, resilience, domains) — Priorität 5–9
> - **P04c**: Addon + Security-Audit + Performance-Analyse — Priorität 10–12

---

## Die 13 Fehlerklassen

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
| 13 | **Performance & Latenz** | Unnötige Wartezeiten, sequentielle statt parallele Calls, fehlende Caches | `await a(); await b()` statt `await asyncio.gather(a(), b())` |

### Zusätzlich: Cross-Modul-Prüfung (bei JEDEM Modul!)

Wenn du ein Modul prüfst, prüfe auch die **Schnittstellen zu anderen Modulen**:

1. **Return-Werte**: Wenn Modul A `Modul_B.get_data()` aufruft — was gibt B zurück? Behandelt A den Fall `None` / leere Liste / Exception?
2. **Fehler-Weitergabe**: Wenn B eine Exception wirft — fängt A sie ab? Wird der User informiert oder stirbt der Request still?
3. **Parameter-Kompatibilität**: Übergibt A die richtigen Typen und Keys? (z.B. `brain.py` ruft `memory.load(user_id=...)` auf — akzeptiert `memory.py` diesen Parameter?)
4. **Async-Konsistenz**: Ist die aufgerufene Funktion `async`? Wird sie mit `await` aufgerufen?

> **Regel**: Wenn du schreibst "Modul A ruft B auf" — **öffne B und verifiziere** dass die Signatur passt und der Return-Wert korrekt behandelt wird.

---

## Modul-Priorität (nur dieses Prompt!)

### Priorität 1 — Kern (MUSS komplett geprüft werden)
1. `brain.py` — Orchestrator, höchster Impact (**⚠️ 10.000+ Zeilen! Read in 2000-Zeilen-Abschnitten: offset=1/2001/4001/6001/8001/10001**)
2. `brain_callbacks.py` — Event Hooks
3. `main.py` — FastAPI-Server, Endpoints (**⚠️ 8000+ Zeilen! Read in 2000-Zeilen-Abschnitten: offset=1/2001/4001/6001/8001**)
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

---

## Spezifische Problemzonen (aus Dokumentation bekannt)

| Quelle | Behauptung | Verifiziere im Code |
|---|---|---|
| `JARVIS_STATUS.md` | Bugs B1–B6 sind gefixt | Wirklich gefixt? |
| `docs/JARVIS_FEATURES_IMPLEMENTATION.md` | 5 Bugfixes implementiert | Fixes korrekt? |
| `docs/JARVIS_SELF_IMPROVEMENT.md` | 9 Self-Learning Features | Implementiert oder nur Stubs? |
| `docs/JARVIS_AUDIT.md` | Audit-Findings | Findings behoben? |
| Token Streaming | "Komplett fehlend" | Stimmt noch? |
| Interrupt Queueing | "Komplett fehlend" | Stimmt noch? |

---

## Batching-Strategie

> **Arbeite die Module in Batches ab, parallel mit Read (5–7 gleichzeitig):**
>
> - **Batch 1** (Priorität 1 — Kern): `brain.py`, `brain_callbacks.py`, `main.py`, `websocket.py`
> - **Batch 2** (Priorität 2 — Memory): `memory.py`, `semantic_memory.py`, `conversation.py`, `conversation_memory.py`, `memory_extractor.py`, `correction_memory.py`, `dialogue_state.py`
> - **Batch 3** (Priorität 2+3): `embeddings.py`, `embedding_extractor.py`, `context_builder.py`, `personality.py`, `mood_detector.py`, `situation_model.py`, `time_awareness.py`
> - **Batch 4** (Priorität 4 — Aktionen): `function_calling.py`, `function_validator.py`, `declarative_tools.py`, `action_planner.py`, `ollama_client.py`, `model_router.py`, `pre_classifier.py`, `request_context.py`
>
> **Wichtig**: Nutze die Grep-Bulk-Suche (Fehlerklassen 1–13) **vor** den Batches um die verdächtigsten Stellen zu identifizieren. Dann lies die Module in Batch-Reihenfolge und achte besonders auf die Grep-Treffer.

---

## Grep für systematische Bug-Suche

Führe diese Suchen **vor** dem Batch-Reading durch:

```
# Fehlerklasse 1: Fehlende awaits finden
# ACHTUNG: [^await ] ist eine Character Class, NICHT "not preceded by await"!
# Nutze stattdessen Negative Lookbehind:
Grep: pattern="(?<!await )self\.(memory|semantic_memory|ha_client)\." path="assistant/assistant/" output_mode="content"
# Alternativ: Alle self.X.Y()-Aufrufe finden und manuell prüfen welche await brauchen:
Grep: pattern="^\s+self\.\w+\.\w+\(" path="assistant/assistant/" output_mode="content"

# Fehlerklasse 2: Stille Fehler
Grep: pattern="except.*:[\s]*pass|except.*:[\s]*$|except Exception" path="assistant/assistant/" output_mode="content"

# Fehlerklasse 3: Race Conditions — Shared State ohne Lock
Grep: pattern="self\.\w+\[|self\.\w+\.append" path="assistant/assistant/" output_mode="content"
# Dann prüfen ob asyncio.Lock verwendet wird:
Grep: pattern="asyncio\.Lock|async with.*lock" path="assistant/assistant/" output_mode="content"

# Fehlerklasse 6: API-Calls ohne Timeout
Grep: pattern="aiohttp|requests\.(get|post)|fetch" path="assistant/assistant/" output_mode="content"
Grep: pattern="timeout" path="assistant/assistant/ha_client.py" output_mode="content"

# Fehlerklasse 9: Memory Leaks — Listen ohne Limit
Grep: pattern="\.append\(|\.extend\(" path="assistant/assistant/" output_mode="content"

# Fehlerklasse 11: Security — User-Input im Prompt
Grep: pattern="f\"|f'" path="assistant/assistant/context_builder.py" output_mode="content"
```

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
Gesamt: X Bugs (Priorität 1–4)
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

### Gründlichkeits-Pflicht

> **Lies JEDES Modul in der Prioritätsliste mit Read. KEIN Modul überspringen.**
>
> Für jedes Modul: Lies die Datei mit Read, prüfe jeden `try/except`, jeden `await`, jeden Dict/List-Zugriff, jede API-Call. Wenn du ein Modul nicht geprüft hast, dokumentiere WARUM.
>
> Ein übersehener kritischer Bug kann das ganze System zum Absturz bringen. Lieber langsam und gründlich als schnell und oberflächlich.

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Befehl |
|---|---|---|
| Grep-Bulk-Suche | **Grep** (parallel, mehrere Patterns) | Siehe oben |
| Module lesen | **Read** (parallel: 5–7 gleichzeitig) | `brain.py`, `main.py`, etc. |
| Statische Analyse | **Bash** | `cd assistant && python -m py_compile assistant/brain.py 2>&1` |

- **Jeder Bug mit Code-Referenz** (Datei:Zeile)
- **Keine false positives** — nur echte Bugs, keine Style-Issues
- **Nicht fixen in diesem Prompt** — nur finden und dokumentieren (Fixes kommen in Prompt 6a–6d)
- **Async-Fehler haben höchste Aufmerksamkeit** — häufigste Ursache für "funktioniert manchmal"

---

## Erfolgskriterien

Alle Module gelesen, Bugs nach 13 Fehlerklassen kategorisiert, Datei:Zeile Referenzen

---

## ⚡ Übergabe an Prompt 4b

Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block** für Prompt 4b:

```
## KONTEXT AUS PROMPT 4a: Bug-Report (Core-Module)

### Statistik
Gesamt: X Bugs in Priorität 1–4 (🔴 X, 🟠 X, 🟡 X, 🟢 X)

### Kritische Bugs (🔴)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Hohe Bugs (🟠)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Patterns die in 4b weitergesucht werden sollten
[z.B. "Fehlende awaits bei self.memory-Aufrufen — in allen Modulen prüfen"]
```

**Wenn du Prompt 4b in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke automatisch ein.

---

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN: [Liste der nicht gefixten Issues mit Grund]
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
