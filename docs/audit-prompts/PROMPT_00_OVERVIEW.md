# Jarvis Audit — Prompt-Serie (Übersicht)

Diese Prompts sind dafür gedacht, **der Reihe nach** an ein LLM übergeben zu werden. Jeder Prompt ist fokussiert auf ein Thema und liefert als Output den Input für den nächsten.

> **Für einen weiteren Durchlauf**: Nutze `PROMPT_RESET.md` **vor** Prompt 1, um den Kontext sauber zurückzusetzen und die Ergebnisse des vorherigen Durchlaufs als Vergleichsbasis zu sichern.

## Das System

Jarvis besteht aus **drei Services + HA-Integration + Shared-Module**:
1. **Assistant** (`/assistant/assistant/`, 89 Module, FastAPI) — KI-Kern (inkl. `brain.py` 10.231 Zeilen, `main.py` 8.000+ Zeilen)
2. **Addon** (`/addon/rootfs/opt/mindhome/`, 67 Module, Flask) — Smart-Home-Logik (14 Kern + 16 Engines + 23 Domains + 17 Routes)
3. **Speech** (`/speech/`, 2 Module, Whisper STT) — Spracheingabe
4. **HA-Integration** (`/ha_integration/`, 3 Python-Dateien + `manifest.json` + `strings.json`) — Bridge zwischen HA Voice Pipeline und Assistant
5. **Shared** (`/shared/`, 6 Dateien) — **API-Verträge** zwischen Services: `ChatRequest`, `ChatResponse`, `MindHomeEvent`, Ports, Event-Namen, Konstanten

Dazu: 103 Test-Dateien, 3 Dockerfiles, 2 docker-compose Konfigurationen, 2 Frontend-Dateien (`app.jsx`, `app.js`), 2 Übersetzungsdateien (`de.json`, `en.json`), 3 `requirements.txt`, 5 Shell-Scripts.

> **Modul-Definition**: Ein Modul = eine `.py`-Datei (ohne `__init__.py` und Test-Dateien).

## Reihenfolge

| # | Datei | Fokus | Abhängigkeit |
|---|---|---|---|
| 1 | `PROMPT_01_ARCHITEKTUR.md` | Architektur, Modul-Konflikte, **3-Service-Interaktion** | Keine — Startpunkt |
| 2 | `PROMPT_02_MEMORY.md` | Memory-System End-to-End (**alle 12 Module**) | Nutzt Konflikt-Karte aus #1 |
| 3a | `PROMPT_03a_FLOWS_CORE.md` | Init-Sequenz, System-Prompt, **Core-Flows 1–7** | Nutzt Ergebnisse aus #1 + #2 |
| 3b | `PROMPT_03b_FLOWS_EXTENDED.md` | **Extended-Flows 8–13** + Flow-Kollisionen | Nutzt Ergebnisse aus #3a |
| 4a | `PROMPT_04a_BUGS_CORE.md` | Bug-Jagd: **Core-Module** (Prio 1–4, ~26 Module) | Nutzt Architektur aus #1–#3b |
| 4b | `PROMPT_04b_BUGS_EXTENDED.md` | Bug-Jagd: **Extended-Module** (Prio 5–9, 63 Module) | Nutzt Patterns aus #4a |
| 4c | `PROMPT_04c_BUGS_ADDON_SECURITY.md` | Bug-Jagd: **Addon + Security + Performance** (Prio 10–12) | Nutzt Findings aus #4a + #4b |
| 5 | `PROMPT_05_PERSONALITY.md` | Persönlichkeit, Config, MCU-Authentizität | Nutzt Bug-Liste aus #4a–4c |
| 6a | `PROMPT_06a_STABILISIERUNG.md` | **Kritische Bugs fixen** + **Memory reparieren** | 🔴 Bugs aus #4a–4c + Memory-Fix aus #2 |
| 6b | `PROMPT_06b_ARCHITEKTUR.md` | **Architektur-Entscheidungen** + Konflikte + Flows + **Performance** | Konflikte aus #1 + Flows aus #3a/3b |
| 6c | `PROMPT_06c_CHARAKTER.md` | **Persönlichkeit harmonisieren** + Config + 🟡 Bugs + Dead Code | Personality aus #5 + Bugs aus #4a–4c |
| 6d | `PROMPT_06d_HAERTUNG.md` | **Security** + **Resilience** + **Addon-Koordination** | Security aus #4c + Konflikt F aus #1 |
| 6e | `PROMPT_06e_GERAETESTEUERUNG.md` | **Tool-Calling** + **System-Prompt** + Gerätesteuerung | Pain-Point: Geräte reagieren nicht |
| 6f | `PROMPT_06f_TTS_RESPONSE.md` | **speak-Filter** + **Meta-Leakage** + TTS-Pipeline | Pain-Point: "speak" in Sprachausgabe |
| 7a | `PROMPT_07a_TESTING.md` | Tests + Coverage + **Security-Endpoint-Tests** | Verifiziert Fixes aus #6a–6f |
| 7b | `PROMPT_07b_DEPLOYMENT.md` | Docker + Deployment + **Resilience** + **Performance** | Nutzt Test-Ergebnisse aus #7a |
| 7c | `PROMPT_07c_INTEGRATION_TESTS.md` | **Integration-Tests**: End-to-End Flows (Chat, Memory, Proaktiv, Resilience, Security) | Nach #7b |
| 8a | `PROMPT_08a_CODEQUALITAET.md` | **Docs** + **Dependencies** + **CI/CD** + Lokalisierung | Nach #7c |
| 8b | `PROMPT_08b_BETRIEB.md` | **Multi-User** + **Frontend** + **Monitoring** + Persistenz | Nach #8a |
| 9a | `PROMPT_09a_FIX_CODEQUALITAET.md` | **Fix: alle P08a Findings** — Docs, Deps, CI/CD, Scripts | Nutzt Findings aus #8a |
| 9b | `PROMPT_09b_FIX_BETRIEB.md` | **Fix: alle P08b Findings** — Concurrency, Logging, Health | Nutzt Findings aus #8b |
| 10 | `PROMPT_10_FINAL_VALIDATION.md` | **Zero-Bug Abschluss** — ALLE offenen Bugs fixen, Regression-Test | Nutzt ALLE Kontext-Blöcke |
| 11 | `PROMPT_11_CLEANUP.md` | **Cleanup**: Result-Dateien löschen, nur `OPEN_BUGS.md` behalten | Nach #10 |
| ↻ | `PROMPT_RESET.md` | **Reset für neuen Durchlauf** | Nach #11, vor erneutem #1 |

## Wie verwenden

### Option A: Claude Code (empfohlen)

Die Prompts sind für **Claude Code** (Anthropics CLI-Tool) optimiert. Übergib jeden Prompt als User-Message:

1. Starte eine Claude-Code-Session im Projekt-Root (`/home/user/mindhome`)
2. Kopiere den Inhalt von Prompt 1 als Nachricht
3. Claude Code führt die Analyse durch — liest Dateien, sucht mit Grep, führt Befehle aus
4. Kopiere dann Prompt 2 als Nachricht — Claude Code nutzt seine Ergebnisse automatisch
5. Wiederhole bis Prompt 7b

> **Context-Window-Strategie**: Claude Code komprimiert die Konversation automatisch. Die Kontext-Blöcke am Ende jedes Prompts (`## KONTEXT AUS PROMPT X`) sichern die wichtigsten Ergebnisse gegen Kompression. Bei 276 Python-Dateien wird typischerweise ab Prompt 3–4 komprimiert.

**Wenn der Kontext zu knapp wird**: Starte eine neue Session und füge die Kontext-Blöcke aus den vorherigen Prompts manuell ein (siehe Abschnitt in jedem Prompt).

**Kontext-Block-Regeln:**
- **Max. 30 Zeilen pro Block** — nur Findings, keine Erklärungen
- **Format**: `Datei:Zeile — Kurzbeschreibung` (eine Zeile pro Finding)
- **Nur 🔴/🟠 Bugs** im Block — 🟡/🟢 nur als Zähler (`🟡: 12 Findings`)
- **Keine Prosa** — Listen statt Absätze

**Beispiel eines Kontext-Blocks** (so sieht der Output am Ende jedes Prompts aus):
```
## KONTEXT AUS PROMPT 1: Architektur-Analyse

### Konflikt-Karte
- A (WER SAGT): personality.py:242 + context_builder.py + mood_detector.py → kein Koordinator
- B (WER TUT): function_calling.py:3143 + action_planner.py:89 → kein Mutex
- F (ASSISTANT↔ADDON): Beide steuern HA-Entities, kein Locking

### Service-Interaktion
Assistant ←HTTP→ Addon (:5000), Assistant ←WS→ HA, Addon ←WS→ HA (eigene Connection)

### Top-5 Architektur-Probleme
1. 🔴 brain.py God-Object (10.231 Zeilen)
2. 🔴 Addon+Assistant steuern gleiche Entities ohne Koordination
3. 🟠 12 Memory-Silos ohne Integration
4. 🟠 main.py zweites God-Object (8.037 Zeilen, 200+ Endpoints)
5. 🟡 Kein zentraler State-Manager
```

### Option B: Separate Sessions (bei Context-Limits)

1. Starte mit Prompt 1 in einer **neuen Claude-Code-Session**
2. Am Ende jeder Analyse erstellt Claude Code einen kompakten **Kontext-Block** (markiert mit `## KONTEXT AUS PROMPT X`)
3. Kopiere diesen Block in den `## Kontext aus vorherigen Prompts`-Abschnitt des nächsten Prompts
4. Starte eine neue Session und übergib den nächsten Prompt mit dem eingefügten Kontext
5. Wiederhole bis Prompt 7b

> **Vorteil**: Frischer Context Window für jeden Prompt. Maximale Gründlichkeit pro Prompt.

### Result-Dateien als Kontextquelle

Ab Durchlauf #2+ können Prompts ihre Vorgänger-Ergebnisse direkt aus `docs/audit-results/RESULT_*.md` lesen. Das ist zuverlässiger als Konversations-Kontext, da:
- Keine Kompression durch Claude Code
- Exakte Ergebnisse statt zusammengefasste Kontext-Blöcke
- Funktioniert auch in neuen Sessions ohne manuelles Kopieren

**Voraussetzung**: Die Result-Dateien müssen nach jedem Prompt-Durchlauf in `docs/audit-results/` gespeichert werden.

---

## Claude Code — Tool-Strategie

Claude Code hat spezialisierte Tools. Jeder Prompt nutzt sie gezielt:

### Verfügbare Tools und wann sie eingesetzt werden

| Tool | Wofür | Statt |
|---|---|---|
| **Read** | Einzelne Dateien lesen (`brain.py`, `main.py`, YAML-Configs). **⚠️ Limit: 2000 Zeilen pro Aufruf!** Große Dateien (brain.py=10.231, main.py=8.037 Zeilen) müssen in Abschnitten gelesen werden: `offset=1 limit=2000`, dann `offset=2001 limit=2000`, usw. | ~~cat, head, tail~~ |
| **Grep** | Muster im Code suchen (Imports, Funktionsaufrufe, Redis-Keys, `await`) | ~~grep, rg~~ |
| **Glob** | Dateien finden (`**/*.py`, `**/test_*.py`) | ~~find, ls~~ |
| **Bash** | Befehle ausführen (`pytest`, `docker build`, `pylint`, `pip list`) | — |
| **Edit** | Code-Änderungen direkt in Dateien schreiben | ~~Diff zeigen~~ |

### Parallelisierung

Claude Code kann **mehrere Dateien gleichzeitig lesen**. Wenn ein Prompt sagt "Lies alle 12 Memory-Module", bedeutet das:
- Starte mehrere **parallele Read-Aufrufe** (5–7 Dateien gleichzeitig)
- Nicht sequentiell eine nach der anderen

### Grep statt "jede Datei öffnen"

Wenn ein Prompt sagt "Prüfe ob Modul X importiert wird":
- **Nutze Grep**: `pattern: "from.*memory import|import memory"` über das gesamte Projekt
- **Nicht**: Jede der 276 Dateien einzeln öffnen und die Import-Zeilen lesen

### Bash für Verifikation

Wenn ein Prompt sagt "Prüfe ob Tests bestehen":
- **Führe aus**: `cd assistant && python -m pytest --tb=short -q`
- **Nicht**: Tests nur lesen und gedanklich simulieren

### Edit für Fixes

Wenn ein Prompt sagt "Implementiere den Fix":
- **Nutze Edit**: Ändere die Datei direkt mit dem Edit-Tool
- **Nicht**: Zeige nur einen Diff oder Code-Vorschlag

## Bug-Typ → Fix-Prompt Zuordnung

Wenn ein Bug in P04a-P04c gefunden wird, muss er dem richtigen Fix-Prompt zugeordnet werden:

| Bug-Typ | Fix-Prompt | Beispiele |
|---|---|---|
| **Memory** (Fakten vergessen, Kontext fehlt, Priorität) | **P06a** | limit=3, intent_type=="memory", Priority 3 |
| **Architektur** (God-Object, Dopplungen, Flows) | **P06b** | brain.py Refactoring, Service-Koordination |
| **Persönlichkeit** (Floskeln, Humor, MCU-Bruch) | **P06c** | "Natürlich!", Sarkasmus-Level falsch, Dead Code |
| **Security** (Injection, Auth, Race Conditions) | **P06d** | User-Input unescaped, fehlende Locks, kein Timeout |
| **Tool-Calling** (Gerät reagiert nicht, falsche Entity) | **P06e** | Tool-Call fehlgeschlagen, entity_id falsch, kein Fallback |
| **TTS/Sprache** ("speak" in Ausgabe, Meta-Leakage) | **P06f** | "speak:", Markdown in TTS, Funktionsnamen hörbar |
| **Fehlende awaits** | **P06a** (🔴) oder **P06b** (🟠) | Je nach Schweregrad |
| **Stille Fehler** (except: pass) | **P06a** (🔴) oder **P06d** | Je nach Sicherheitsrelevanz |

> **Regel**: 🔴 Bugs (Crash/Datenverlust) → P06a. 🔴 Bugs (Security) → P06d. 🟠 Bugs → P06b-P06f je nach Typ. 🟡 Bugs → P06c. Wenn unklar → P06a.

## Was jeder Prompt abdeckt

| Aspekt | P1 | P2 | P3a | P3b | P4a | P4b | P4c | P5 | P6a | P6b | P6c | P6d | P6e | P6f | P7a | P7b | P8a | P8b | P9a | P9b | P10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Assistant-Module | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Addon-Module | ✅ | ✅ | - | ✅ | - | - | ✅ | ✅ | - | - | - | ✅ | - | - | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Shared-Module (API-Verträge) | ✅ | - | ✅ | ✅ | - | - | ✅ | - | - | - | - | - | - | - | - | ✅ | ✅ | - | ✅ | - | ✅ |
| Speech-Service | ✅ | - | ✅ | - | - | - | ✅ | - | - | - | - | - | - | - | - | ✅ | - | ✅ | - | ✅ | ✅ |
| Architektur | ✅ | - | - | - | - | - | - | - | - | ✅ | - | - | - | - | - | - | - | - | - | - | - |
| Memory (12 Module) | - | ✅ | ✅ | - | ✅ | - | - | - | ✅ | - | - | - | - | - | ✅ | - | - | - | - | - | ✅ |
| Flows (13 Pfade) | - | - | ✅ | ✅ | - | - | - | - | - | ✅ | - | - | - | - | - | ✅ | - | - | - | - | - |
| Bug-Jagd (13 Klassen) | - | - | - | - | ✅ | ✅ | ✅ | - | ✅ | ✅ | ✅ | ✅ | - | - | - | - | - | - | - | - | ✅ |
| **Gerätesteuerung/Tool-Calling** | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | - | - | - | - | - | - | ✅ |
| **TTS/Meta-Leakage** | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | - | - | - | - | - | ✅ |
| **Performance & Latenz** | - | - | - | - | - | - | ✅ | - | - | ✅ | - | - | - | - | - | ✅ | - | ✅ | - | ✅ | ✅ |
| Security | - | - | - | - | - | - | ✅ | - | - | - | - | ✅ | - | - | ✅ | - | - | ✅ | - | ✅ | ✅ |
| Resilience | - | - | - | - | - | - | ✅ | - | - | - | - | ✅ | - | - | - | ✅ | - | ✅ | - | ✅ | ✅ |
| Persönlichkeit / MCU | ✅ | - | ✅ | - | - | - | - | ✅ | - | - | ✅ | - | - | - | - | - | - | - | - | - | - |
| Config / YAML | - | - | - | - | - | - | - | ✅ | - | - | ✅ | - | ✅ | ✅ | - | - | ✅ | - | ✅ | - | - |
| Tests (103 Dateien) | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | - | - | - | - | ✅ |
| Docker / Deployment | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | ✅ | - | ✅ | ✅ |
| Frontend (app.jsx, app.js) | - | - | - | - | - | - | ✅ | - | - | - | - | ✅ | - | - | - | ✅ | - | ✅ | - | ✅ | ✅ |
| Dependencies (requirements.txt) | - | - | - | - | - | - | ✅ | - | - | - | - | - | - | - | - | ✅ | ✅ | - | ✅ | - | ✅ |
| Translations / Manifests | - | - | - | - | - | - | - | ✅ | - | - | - | - | - | - | - | - | ✅ | - | ✅ | - | - |
| **Dokumentation (README)** | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | ✅ | - | ✅ |
| **CI/CD Pipeline** | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | ✅ | - | - |
| **Multi-User / Concurrency** | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | ✅ | ✅ |
| **Logging / Monitoring** | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | ✅ | ✅ |
| **Daten-Persistenz / Backup** | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | ✅ | ✅ |
| **Shell-Scripts** | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ✅ | - | ✅ | - | - |

## Wichtige Rahmenbedingungen

### GitHub-Repository, kein laufendes System
Der Code liegt auf GitHub. Es gibt kein laufendes Redis, ChromaDB, Ollama oder Home Assistant. `.env` fehlt (nur `.env.example`). Das LLM muss **alles aus dem Code herauslesen** — keine Annahmen, keine "das wird schon funktionieren".

### Ziel-Hardware
Das System läuft auf: **AMD Ryzen 7 3700X**, **64GB DDR4**, **RTX 3090 (24GB VRAM)**, 500GB NVMe + 1TB SATA SSD. Die GPU wird für Ollama LLM-Inference genutzt. Relevant für Prompt 7b (Docker/GPU-Setup, OOM-Szenarien, Modell-Empfehlungen).

### Kontext-Block-Größe & Akkumulation

Jeder Prompt generiert am Ende einen **Kontext-Block** für den nächsten Prompt.

- **Max. 30 Zeilen pro Kontext-Block** — kompakte Listen, keine Prosa
- **Nur 🔴/🟠 Findings** im Block — 🟡/🟢 nur als Zähler
- **Code-Referenzen kompakt**: `brain.py:123` statt langer Erklärungen

> **Akkumulations-Strategie nach Phase:**
> - **P01–P05 (Analyse)**: Vollständige Kontext-Blöcke mitgeben (max. 30 Zeilen pro Block)
> - **P06a–P06f (Fixes)**: Nur die OFFEN-Liste und Bug-Zuordnungstabelle mitgeben, nicht alle Analyse-Blöcke
> - **P07a–P09b**: Nur die OFFEN-Liste der verbleibenden Bugs
> - **P10 (Final)**: Nur die OFFEN-Liste — alles was hier steht MUSS gefixt werden
>
> **Falls der Kontext trotzdem eng wird**: Starte eine neue Session (Option B) und gib nur die OFFEN-Liste mit.

### Bewusste Redundanzen
Einige Elemente wiederholen sich in mehreren Prompts (Phase-Gate, 13 Fehlerklassen, Rolle). Das ist **gewollt** — jeder Prompt muss standalone funktionieren, falls er in einer separaten Session genutzt wird. Referenz-Definitionen:
- **13 Fehlerklassen**: Vollständig in P04a, Kurzreferenz in P04b/P04c
- **Phase Gate (Regression-Check)**: In jedem Fix-Prompt (P06a–P09b, P10)
- **Eskalations-Schema**: Vollständig in P00, referenziert in allen Fix-Prompts

### Gründlichkeits-Pflicht
Jeder Prompt enthält eine **Gründlichkeits-Pflicht**:
- **Jede Datei mit Read-Tool lesen** — nicht raten was drin steht
- **Grep nutzen** um Funktionsaufrufe, Imports und Patterns projektübergreifend zu finden
- **Jeden Funktionsaufruf bis zum Ende verfolgen** — nicht bei der ersten Ebene aufhören
- **Jede Aussage mit Code-Referenz belegen** — Datei:Zeile oder es zählt nicht
- **Kein Modul überspringen** — auch wenn es "unwichtig" aussieht
- **Parallele Reads nutzen** — mehrere Dateien gleichzeitig lesen wenn möglich

## Gemeinsame Rolle

Alle Prompts nutzen dieselbe Rollen-Definition: Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Die Rolle wird in jedem Prompt wiederholt, damit sie auch einzeln funktionieren.

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:9b (fast, ctx 32k), qwen3.5:35b-moe (smart, ctx 32k), qwen3.5:35b-moe (deep, ctx 64k)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

## Erwarteter Gesamt-Output nach allen Prompts

1. **Konflikt-Karte** — Welche Module gegeneinander arbeiten (inkl. Addon ↔ Assistant)
2. **Memory-Diagnose** — Warum Jarvis vergisst + Fix
3a. **Core-Flows** — Flows 1–7 mit Init-Sequenz und System-Prompt
3b. **Extended-Flows** — Flows 8–13 mit Kollisionen
4a. **Core-Bug-Report** — Bugs in brain.py, main.py, memory, context, actions
4b. **Extended-Bug-Report** — Bugs in proaktiven Systemen, HA, audio, intelligence
4c. **Addon/Security/Performance** — Addon-Bugs, Security-Audit, Latenz-Analyse
5. **Persönlichkeits-Audit** — MCU-Score + Inkonsistenzen + Config-Probleme
6a. **Stabilisierte Codebase** — Kritische Bugs gefixt, Memory repariert
6b. **Optimierte Architektur** — Konflikte aufgelöst, Flows repariert, **Latenz optimiert**
6c. **Harmonisierter Charakter** — Eine Stimme, saubere Config, Dead Code entfernt
6d. **Gehärtetes System** — Security geschlossen, Resilience implementiert, Addon koordiniert
6e. **Funktionierende Gerätesteuerung** — Tool-Calling zuverlässig, System-Prompt optimiert, deterministic Fallback erweitert
6f. **Saubere Sprachausgabe** — Kein "speak"/Meta-Leakage in TTS, Response-Filter gehärtet
7a. **Test-Report** — Tests bestehen, Coverage-Lücken geschlossen, Security-Endpoints verifiziert
7b. **Deployment-Report** — Docker läuft, **Performance gemessen**, Resilience getestet
8a. **Code-Qualitäts-Report** — README aktuell, Dependencies sauber, CI/CD bewertet, Lokalisierung geprüft
8b. **Betriebs-Report** — Multi-User sicher, Frontend gehärtet, Logging strukturiert, Persistenz gesichert
9a. **Code-Qualität gefixt** — Alle P08a Findings behoben: Docs, Deps, CI/CD, Scripts, Übersetzungen
9b. **Betrieb gefixt** — Alle P08b Findings behoben: Locks, Logging, Health-Endpoints, Volumes
10. **Zero-Bug Declaration** — ALLE offenen Bugs gefixt, Regression-Test bestanden, Security clean

## Erfolgsmetriken

**Analyse-Phase (P01–P05):**
- Alle Module mit Datei:Zeile Referenzen geprüft
- Jeder Prompt liefert einen Kontext-Block (max. 30 Zeilen) für den nächsten Prompt
- Alle 13 Flows dokumentiert mit Status und Bruchstellen
- Alle 6 Konfliktkarten ausgefüllt mit Code-Referenzen

**Fix-Phase (P06a–P09b):**
- `cd assistant && python -m pytest --tb=short -q` grün nach jeder Fix-Phase
- `python -m py_compile` erfolgreich für alle geänderten Dateien
- Jeder Fix committet mit beschreibender Nachricht

**Abschluss (P10–P11):**
- OFFEN-Liste enthält keine 🔴/🟠 Bugs mehr (nur 🟡 mit Begründung erlaubt)
- Alle Result-Dateien gelöscht, nur `OPEN_BUGS.md` verbleibt (falls Bugs offen)
- `cd assistant && python -m pytest --tb=short -q` grün

## Eskalations-Schema fuer offene Bugs

Jeder Bug der in einem Fix-Prompt (P06a–P06f) nicht geloest werden kann, MUSS mit Severity und Eskalations-Kategorie dokumentiert werden. **Kein Bug darf stillschweigend uebersprungen werden.**

### OFFEN-Block Format

```
OFFEN:
- 🔴 [KRITISCH] Beschreibung | Datei:Zeile | GRUND: [warum nicht loesbar]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
- 🟠 [HOCH] Beschreibung | Datei:Zeile | GRUND: [warum nicht loesbar]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
```

### Eskalations-Kategorien

| Kategorie | Bedeutung | Was passiert |
|---|---|---|
| `NAECHSTER_PROMPT` | Bug gehoert thematisch in einen spaeteren Prompt | Wird dort aufgegriffen (z.B. Security-Bug in P06a → P06d) |
| `ARCHITEKTUR_NOETIG` | Fix erfordert groesseren Umbau der nicht in diesen Prompt passt | P06b (Architektur) oder naechster Durchlauf |
| `MENSCH` | LLM kann Bug nicht allein loesen — braucht Domainwissen oder Architektur-Entscheidung | **Eigene beste Entscheidung treffen, Wahl + Begruendung dokumentieren. User wird am Ende informiert.** |

### Regeln

1. **Jeder Fix-Prompt prueft zuerst** die OFFEN-Liste des vorherigen Prompts auf Bugs mit `→ ESKALATION: NAECHSTER_PROMPT`
2. **P07a (Testing) validiert** alle OFFEN-Bugs: Sind sie wirklich nicht loesbar oder wurde etwas uebersehen?
3. **RESET uebernimmt** alle verbleibenden OFFEN-Bugs als priorisierte Checkliste fuer den naechsten Durchlauf
4. **MENSCH-Bugs: NICHT stoppen.** Triff die beste Entscheidung selbst, dokumentiere WARUM du dich so entschieden hast, und mach weiter. Der User wird am Ende ueber alle MENSCH-Entscheidungen informiert.
5. **Kein Bug verschwindet** — er wird entweder GEFIXT, ESKALIERT, oder im naechsten Durchlauf erneut geprueft

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
