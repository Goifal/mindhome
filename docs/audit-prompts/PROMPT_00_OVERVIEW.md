# Jarvis Audit — Prompt-Serie v2 (Übersicht)

Diese Prompts sind dafür gedacht, **der Reihe nach** an ein LLM übergeben zu werden. Jeder Prompt ist fokussiert auf ein Thema und liefert als Output den Input für den nächsten.

> **Für einen weiteren Durchlauf**: Nutze `PROMPT_RESET.md` **vor** Prompt 1, um den Kontext sauber zurückzusetzen und die Ergebnisse des vorherigen Durchlaufs als Vergleichsbasis zu sichern.

> **v2**: Kombiniert das Beste aus v1 (gründliche Bug-Jagd über alle Module) mit neuen fokussierten Fix-Prompts (konkrete Code-Beispiele, Praxis-Testszenarien, User-Pain-Points).

## Das System

Jarvis besteht aus **drei Services + HA-Integration + Shared-Module**:
1. **Assistant** (`/assistant/assistant/`, 89 Module, FastAPI) — KI-Kern (inkl. `brain.py` 10.231 Zeilen, `main.py` 8.000+ Zeilen)
2. **Addon** (`/addon/rootfs/opt/mindhome/`, 67 Module, Flask) — Smart-Home-Logik (14 Kern + 16 Engines + 23 Domains + 17 Routes)
3. **Speech** (`/speech/`, 2 Module, Whisper STT) — Spracheingabe
4. **HA-Integration** (`/ha_integration/`, 3 Python-Dateien + `manifest.json` + `strings.json`) — Bridge zwischen HA Voice Pipeline und Assistant
5. **Shared** (`/shared/`, 6 Dateien) — **API-Verträge** zwischen Services: `ChatRequest`, `ChatResponse`, `MindHomeEvent`, Ports, Event-Namen, Konstanten

Dazu: 103 Test-Dateien, 3 Dockerfiles, 2 docker-compose Konfigurationen, 2 Frontend-Dateien (`app.jsx`, `app.js`), 2 Übersetzungsdateien (`de.json`, `en.json`), 3 `requirements.txt`, 5 Shell-Scripts.

> **Modul-Definition**: Ein Modul = eine `.py`-Datei (ohne `__init__.py` und Test-Dateien).

## Reihenfolge (10 Prompts)

| # | Datei | Fokus | Typ | Abhängigkeit |
|---|---|---|---|---|
| 1 | `PROMPT_01_ARCHITEKTUR_FLOWS.md` | Architektur + Konflikte + **alle 13 Flows** | Analyse | Keine — Startpunkt |
| 2 | `PROMPT_02_MEMORY.md` | Memory-System **Analyse + Fix** (6 bekannte Bugs) | Analyse+Fix | Nutzt Konflikt-Karte aus #1 |
| 3 | `PROMPT_03_GERAETESTEUERUNG.md` | **Tool-Calling** + System-Prompt + Gerätesteuerung | Fix | Nutzt Architektur aus #1 |
| 4 | `PROMPT_04_TTS_RESPONSE.md` | **speak-Filter** + Meta-Leakage + TTS-Pipeline | Fix | Unabhängig (kann parallel zu #3) |
| 4a | `PROMPT_04a_BUGS_CORE.md` | Bug-Jagd: **Core-Module** (Prio 1–4, 26 Module, 13 Fehlerklassen) | Analyse | Nutzt Architektur aus #1–#4 |
| 4b | `PROMPT_04b_BUGS_EXTENDED.md` | Bug-Jagd: **Extended-Module** (Prio 5–9, 63 Module) | Analyse | Nutzt Patterns aus #4a |
| 5 | `PROMPT_05_BUGFIXES.md` | **Systematische Bug-Fixes** (max 20/Durchlauf) | Fix | Nutzt Bug-Liste aus #4a + #4b |
| 6 | `PROMPT_06_PERSOENLICHKEIT.md` | Persönlichkeit + MCU-Charakter + Config | Analyse+Fix | Nutzt Ergebnisse aus #1-#5 |
| 7 | `PROMPT_07_SICHERHEIT.md` | **Top-5 Security** + Resilience + Addon + Circuit Breaker | Analyse+Fix | Nutzt Ergebnisse aus #1-#6 |
| ↻ | `PROMPT_RESET.md` | **Reset für neuen Durchlauf** | Reset | Nach #7, vor erneutem #1 |

### Parallelisierung

Mehrere Prompts können **parallel** ausgeführt werden:

```
#1 (Architektur) → #2 (Memory) → #3 (Geräte) ─┐
                                  #4 (TTS)    ──┤
                                  #4a (Bugs)  ──┤→ #5 (Bugfixes) → #6 (Persönlichkeit) → #7 (Sicherheit) → RESET
                                  #4b (Bugs)  ──┘
```

> **P03, P04, P04a, P04b** können alle gleichzeitig laufen (separate Claude-Code-Sessions).
> **P04b** braucht die Patterns aus P04a — entweder nacheinander oder P04a-Kontext-Block in P04b einfügen.

## Wie verwenden

### Option A: Claude Code (empfohlen)

Die Prompts sind für **Claude Code** (Anthropics CLI-Tool) optimiert:

1. Starte eine Claude-Code-Session im Projekt-Root (`/home/user/mindhome`)
2. Kopiere den Inhalt von Prompt 1 als Nachricht
3. Claude Code führt die Analyse durch — liest Dateien, sucht mit Grep, führt Befehle aus
4. Kopiere dann Prompt 2 als Nachricht — Claude Code nutzt seine Ergebnisse automatisch
5. Wiederhole bis Prompt 7

> **Context-Window-Strategie**: Claude Code komprimiert die Konversation automatisch. Die Kontext-Blöcke am Ende jedes Prompts (`=== KONTEXT FUER NAECHSTEN PROMPT ===`) sichern die wichtigsten Ergebnisse gegen Kompression.

### Option B: Separate Sessions (bei Context-Limits)

1. Starte mit Prompt 1 in einer **neuen Claude-Code-Session**
2. Am Ende erstellt Claude Code einen kompakten **Kontext-Block**
3. Kopiere diesen Block in den `## Kontext aus vorherigen Prompts`-Abschnitt des nächsten Prompts
4. Starte eine neue Session und übergib den nächsten Prompt mit dem eingefügten Kontext

---

## Claude Code — Tool-Strategie

| Tool | Wofür | Statt |
|---|---|---|
| **Read** | Einzelne Dateien lesen. **Limit: 2000 Zeilen pro Aufruf!** Große Dateien in Abschnitten lesen. | ~~cat, head, tail~~ |
| **Grep** | Muster im Code suchen (Imports, Funktionsaufrufe, Redis-Keys, `await`) | ~~grep, rg~~ |
| **Glob** | Dateien finden (`**/*.py`, `**/test_*.py`) | ~~find, ls~~ |
| **Bash** | Befehle ausführen (`pytest`, `docker build`, `pylint`) | — |
| **Edit** | Code-Änderungen direkt in Dateien schreiben | ~~Diff zeigen~~ |

### Parallelisierung

Claude Code kann **mehrere Dateien gleichzeitig lesen** (5–7 parallele Read-Aufrufe).

---

## Was jeder Prompt abdeckt

| Aspekt | P1 | P2 | P3 | P4 | P4a | P4b | P5 | P6 | P7 |
|---|---|---|---|---|---|---|---|---|---|
| Architektur & Konflikte | ✅ | - | - | - | - | - | - | - | - |
| Flows (13 Pfade) | ✅ | - | - | - | - | - | - | - | - |
| Memory (12 Module) | - | ✅ | - | - | ✅ | - | ✅ | - | - |
| Gerätesteuerung/Tool-Calling | - | - | ✅ | - | - | - | - | - | - |
| TTS/Meta-Leakage | - | - | - | ✅ | - | - | - | - | - |
| Bug-Jagd Core (26 Module) | - | - | - | - | ✅ | - | - | - | - |
| Bug-Jagd Extended (63 Module) | - | - | - | - | - | ✅ | - | - | - |
| Bug-Fixes (max 20/Lauf) | - | - | - | - | - | - | ✅ | - | - |
| Persönlichkeit / MCU | - | - | - | - | - | - | - | ✅ | - |
| Security & Resilience | - | - | - | - | - | - | - | - | ✅ |
| Addon-Module | ✅ | - | - | - | - | - | ✅ | - | ✅ |
| Config / YAML | - | ✅ | ✅ | ✅ | - | - | - | ✅ | - |
| Docker / Deployment | - | - | - | - | - | - | - | - | ✅ |

## LLM-Spezifisch (Qwen 3.5)

Alle Prompts enthalten diesen Block:

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu höflichen Floskeln ("Natürlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen für Anti-Floskel

## Gemeinsame Elemente in jedem Prompt

### Einzelfix-Methodik (Fix-Prompts)
Für JEDEN Bug: Read → Grep Caller → Edit → Verify. NIEMALS überspringen.

### Rollback-Regel
Vor dem ersten Edit: git stash oder Backup notieren. Bei ImportError/SyntaxError → SOFORT revert.

### Kontext-Übergabe
Jeder Prompt endet mit:
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

### Eskalations-Schema

| Kategorie | Bedeutung | Was passiert |
|---|---|---|
| `NAECHSTER_PROMPT` | Bug gehört thematisch in einen späteren Prompt | Wird dort aufgegriffen |
| `ARCHITEKTUR_NOETIG` | Fix erfordert größeren Umbau | Nächster Durchlauf |
| `MENSCH` | Braucht Domainwissen oder Architektur-Entscheidung | Eigene beste Entscheidung treffen, Wahl dokumentieren |

### Erfolgs-Check
Jeder Prompt endet mit prüfbaren Kriterien (grep-Befehle, Import-Checks).

### Praxis-Testszenarien
Fix-Prompts (02, 03, 04) enthalten konkrete Dialog-Tests die NACH dem Fix funktionieren MÜSSEN.

## Rahmenbedingungen

### GitHub-Repository, kein laufendes System
Der Code liegt auf GitHub. Kein laufendes Redis, ChromaDB, Ollama oder Home Assistant. `.env` fehlt (nur `.env.example`).

### Ziel-Hardware
**AMD Ryzen 7 3700X**, **64GB DDR4**, **RTX 3090 (24GB VRAM)**, 500GB NVMe + 1TB SATA SSD. GPU für Ollama LLM-Inference.

### Gründlichkeits-Pflicht
- **Jede Datei mit Read-Tool lesen** — nicht raten
- **Grep nutzen** für projektübergreifende Suche
- **Jede Aussage mit Code-Referenz belegen** — Datei:Zeile
- **Kein Modul überspringen**
- **Parallele Reads nutzen**

## Erwarteter Gesamt-Output nach allen Prompts

1. **Konflikt-Karte + Flow-Dokumentation** — Architektur, 13 Flows, Kollisionen (P01)
2. **Repariertes Memory-System** — 6 Bugs gefixt, Fakten-Abruf funktioniert (P02)
3. **Funktionierende Gerätesteuerung** — Tool-Calling zuverlässig, System-Prompt optimiert (P03)
4. **Saubere Sprachausgabe** — Kein Meta-Leakage in TTS (P04)
5. **Vollständige Bug-Liste** — Alle 89+ Module mit 13 Fehlerklassen geprüft (P04a+P04b)
6. **Stabilisierte Codebase** — Top-20 Bugs gefixt pro Durchlauf (P05)
7. **Harmonisierter Charakter** — MCU-Score ≥7/10, Config sauber (P06)
8. **Gehärtetes System** — Top-5 Security + Resilience (P07)

## Vergleich v1 → v2

| Aspekt | v1 (20 Prompts) | v2 (10 Prompts) |
|---|---|---|
| Analyse-Prompts | 8 (P01-P05) | 3 (P01, P04a, P04b) |
| Fix-Prompts | 8 (P06a-P06f, P07a-P07b) | 6 (P02-P07) |
| User-Pain-Points | Nicht adressiert | P03 (Geräte), P04 (TTS) |
| Bug-Jagd Gründlichkeit | 13 Klassen, 89+ Module | Gleich (P04a+P04b beibehalten) |
| Bug-Fix-Scope | Unbegrenzt (~200+) | Max 20 pro Durchlauf |
| Code-Beispiele in Fixes | Keine | In jedem Fix-Prompt |
| Testszenarien | Nur P07a | In P02, P03, P04 |
| Context-Window-Verbrauch | Hoch (viel Redundanz) | Niedrig (fokussiert) |
