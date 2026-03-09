# Jarvis Audit — Prompt-Serie (Übersicht)

Diese **10 Prompts** sind dafür gedacht, **der Reihe nach** an ein LLM übergeben zu werden. Jeder Prompt ist fokussiert auf ein Thema und liefert als Output den Input für den nächsten.

> **Für einen weiteren Durchlauf**: Nutze `PROMPT_RESET.md` **vor** Prompt 1, um den Kontext sauber zurückzusetzen und die Ergebnisse des vorherigen Durchlaufs als Vergleichsbasis zu sichern.

## Das System

Jarvis besteht aus **drei Services + HA-Integration + Shared-Module**:
1. **Assistant** (`/assistant/assistant/`, 88 Module, FastAPI) — KI-Kern (inkl. `brain.py` 10.231 Zeilen, `main.py` 8.000+ Zeilen)
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
| 3 | `PROMPT_03_FLOWS.md` | **13 kritische Pfade** inkl. Speech, Addon, Domain-Assistenten | Nutzt Ergebnisse aus #1 + #2 |
| 4 | `PROMPT_04_BUGS.md` | Systematische Bug-Jagd (**155 Module**, Security, Resilience, **Performance**) | Nutzt Architektur-Verständnis aus #1–#3 |
| 5 | `PROMPT_05_PERSONALITY.md` | Persönlichkeit, Config, MCU-Authentizität | Nutzt Bug-Liste aus #4 |
| 6a | `PROMPT_06a_STABILISIERUNG.md` | **Kritische Bugs fixen** + **Memory reparieren** | 🔴 Bugs aus #4 + Memory-Fix aus #2 |
| 6b | `PROMPT_06b_ARCHITEKTUR.md` | **Architektur-Entscheidungen** + Konflikte + Flows + **Performance** | Konflikte aus #1 + Flows aus #3 |
| 6c | `PROMPT_06c_CHARAKTER.md` | **Persönlichkeit harmonisieren** + Config + 🟡 Bugs + Dead Code | Personality aus #5 + Bugs aus #4 |
| 6d | `PROMPT_06d_HAERTUNG.md` | **Security** + **Resilience** + **Addon-Koordination** | Security/Resilience aus #4 + Konflikt F aus #1 |
| 7 | `PROMPT_07_TESTING_DEPLOYMENT.md` | Tests, Docker, **Performance-Verifikation**, Resilience | Verifiziert die Fixes aus #6a–6d |
| ↻ | `PROMPT_RESET.md` | **Reset für neuen Durchlauf** | Nach #7, vor erneutem #1 |

## Wie verwenden

### Option A: Claude Code (empfohlen)

Die Prompts sind für **Claude Code** (Anthropics CLI-Tool) optimiert. Übergib jeden Prompt als User-Message:

1. Starte eine Claude-Code-Session im Projekt-Root (`/home/user/mindhome`)
2. Kopiere den Inhalt von Prompt 1 als Nachricht
3. Claude Code führt die Analyse durch — liest Dateien, sucht mit Grep, führt Befehle aus
4. Kopiere dann Prompt 2 als Nachricht — Claude Code nutzt seine Ergebnisse automatisch
5. Wiederhole bis Prompt 7

> **Context-Window-Strategie**: Claude Code komprimiert die Konversation automatisch. Bei einem Projekt dieser Größe (276 Python-Dateien) wird der Kontext ab ca. Prompt 3–4 komprimiert. Die Kontext-Blöcke am Ende jedes Prompts (`## KONTEXT AUS PROMPT X`) sichern die wichtigsten Ergebnisse gegen Kompression.

**Wenn der Kontext zu knapp wird**: Starte eine neue Session und füge die Kontext-Blöcke aus den vorherigen Prompts manuell ein (siehe Abschnitt in jedem Prompt).

### Option B: Separate Sessions (bei Context-Limits)

1. Starte mit Prompt 1 in einer **neuen Claude-Code-Session**
2. Am Ende jeder Analyse erstellt Claude Code einen kompakten **Kontext-Block** (markiert mit `## KONTEXT AUS PROMPT X`)
3. Kopiere diesen Block in den `## Kontext aus vorherigen Prompts`-Abschnitt des nächsten Prompts
4. Starte eine neue Session und übergib den nächsten Prompt mit dem eingefügten Kontext
5. Wiederhole bis Prompt 7

> **Vorteil**: Frischer Context Window für jeden Prompt. Maximale Gründlichkeit pro Prompt.

---

## Claude Code — Tool-Strategie

Claude Code hat spezialisierte Tools. Jeder Prompt nutzt sie gezielt:

### Verfügbare Tools und wann sie eingesetzt werden

| Tool | Wofür | Statt |
|---|---|---|
| **Read** | Einzelne Dateien lesen (`brain.py`, `main.py`, YAML-Configs) | ~~cat, head, tail~~ |
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

## Was jeder Prompt abdeckt

| Aspekt | P1 | P2 | P3 | P4 | P5 | P6a | P6b | P6c | P6d | P7 |
|---|---|---|---|---|---|---|---|---|---|---|
| Assistant-Module | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Addon-Module | ✅ | ✅ | ✅ | ✅ | ✅ | - | - | - | ✅ | ✅ |
| Shared-Module (API-Verträge) | ✅ | - | ✅ | ✅ | - | - | - | - | - | ✅ |
| Speech-Service | ✅ | - | ✅ | ✅ | - | - | - | - | - | ✅ |
| Architektur | ✅ | - | - | - | - | - | ✅ | - | - | - |
| Memory (12 Module) | - | ✅ | ✅ | ✅ | - | ✅ | - | - | - | ✅ |
| Flows (13 Pfade) | - | - | ✅ | - | - | - | ✅ | - | - | ✅ |
| Bug-Jagd (13 Klassen) | - | - | - | ✅ | - | ✅ | ✅ | ✅ | ✅ | - |
| **Performance & Latenz** | - | - | - | ✅ | - | - | ✅ | - | - | ✅ |
| Security | - | - | - | ✅ | - | - | - | - | ✅ | ✅ |
| Resilience | - | - | - | ✅ | - | - | - | - | ✅ | ✅ |
| Persönlichkeit / MCU | ✅ | - | ✅ | - | ✅ | - | - | ✅ | - | - |
| Config / YAML | - | - | - | ✅ | ✅ | - | - | ✅ | - | - |
| Tests (103 Dateien) | - | - | - | - | - | - | - | - | - | ✅ |
| Docker / Deployment | - | - | - | - | - | - | - | - | - | ✅ |
| Frontend (app.jsx, app.js) | - | - | - | ✅ | - | - | - | - | ✅ | ✅ |
| Dependencies (requirements.txt) | - | - | - | ✅ | - | - | - | - | - | ✅ |
| Translations / Manifests | - | - | - | - | ✅ | - | - | - | - | - |

## Wichtige Rahmenbedingungen

### GitHub-Repository, kein laufendes System
Der Code liegt auf GitHub. Es gibt kein laufendes Redis, ChromaDB, Ollama oder Home Assistant. `.env` fehlt (nur `.env.example`). Das LLM muss **alles aus dem Code herauslesen** — keine Annahmen, keine "das wird schon funktionieren".

### Ziel-Hardware
Das System läuft auf: **AMD Ryzen 7 3700X**, **64GB DDR4**, **RTX 3090 (24GB VRAM)**, 500GB NVMe + 1TB SATA SSD. Die GPU wird für Ollama LLM-Inference genutzt. Relevant für Prompt 7 (Docker/GPU-Setup, OOM-Szenarien, Modell-Empfehlungen).

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

## Erwarteter Gesamt-Output nach allen 10 Prompts

1. **Konflikt-Karte** — Welche Module gegeneinander arbeiten (inkl. Addon ↔ Assistant)
2. **Memory-Diagnose** — Warum Jarvis vergisst + Fix
3. **Flow-Dokumentation** — 13 Pfade mit allen Bruchstellen
4. **Bug-Report** — Alle Bugs mit Severity, Security-, Resilience- und **Performance**-Analyse
5. **Persönlichkeits-Audit** — MCU-Score + Inkonsistenzen + Config-Probleme
6a. **Stabilisierte Codebase** — Kritische Bugs gefixt, Memory repariert
6b. **Optimierte Architektur** — Konflikte aufgelöst, Flows repariert, **Latenz optimiert**
6c. **Harmonisierter Charakter** — Eine Stimme, saubere Config, Dead Code entfernt
6d. **Gehärtetes System** — Security geschlossen, Resilience implementiert, Addon koordiniert
7. **Verifizierung** — Tests bestehen, Docker läuft, **Performance gemessen**, Resilience getestet
