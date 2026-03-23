# Prompt 08a — Code-Qualität: Dokumentation, Dependencies & CI/CD

> **Abhängigkeit**: Nach P07b (Deployment). Nutzt Ergebnisse aller vorherigen Prompts.
> **Dauer**: ~30–45 Minuten
> **Fokus**: Alles was NICHT Code-Logik ist — aber trotzdem die Projekt-Stabilität beeinflusst.

---

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Du analysierst und fixst die nicht-funktionalen Aspekte des MindHome-Projekts: Dokumentation, Dependencies, Build-Pipeline.

---

## Kontext

MindHome ist ein lokal betriebener KI-Home-Assistant mit 3 Services:
- **Assistant** (`/assistant/`, FastAPI, 89 Module)
- **Addon** (`/addon/`, Flask, 67 Module)
- **Speech** (`/speech/`, Whisper STT, 2 Module)
- **Shared** (`/shared/`, API-Verträge)
- **HA-Integration** (`/ha_integration/`)

---

## Teil 1: Dokumentations-Konsistenz

### Schritt 1 — README vs. Code-Realität

```
Read: /home/user/mindhome/README.md
```

Prüfe systematisch:

| Check | Methode | ✅ PASS | ❌ FAIL |
|---|---|---|---|
| Feature-Liste aktuell? | Grep nach Features im Code | Jedes Feature existiert als Modul/Funktion | Feature dokumentiert aber nicht implementiert (oder umgekehrt) |
| Versions-Nummer konsistent? | Grep `version` in README, `version.py`, `manifest.json`, `config.yaml` | Alle gleich | Abweichung |
| Install-Anweisungen korrekt? | Prüfe ob Schritte funktionieren würden | Alle Pfade/Commands existieren | Veraltete Pfade oder fehlende Schritte |
| Architektur-Diagramm aktuell? | Vergleiche mit P01-Ergebnissen | Alle 3 Services + Shared + HA erwähnt | Fehlende oder veraltete Komponenten |
| Konfiguration dokumentiert? | Prüfe ob alle `settings.yaml` Keys erklärt sind | Alle Keys dokumentiert | Undokumentierte Keys |

```
Grep: pattern="version" path="." glob="version.py" output_mode="content"
Grep: pattern="\"version\"" path="." glob="manifest.json" output_mode="content"
Grep: pattern="version:" path="." glob="*.yaml" output_mode="content"
```

### Schritt 2 — Code-Kommentare vs. Realität

Prüfe in den **5 größten Dateien** (brain.py, main.py, personality.py, function_calling.py, context_builder.py):

```
# Suche nach TODO/FIXME/HACK/XXX Kommentaren
Grep: pattern="TODO|FIXME|HACK|XXX|DEPRECATED" path="assistant/assistant/" output_mode="content"
Grep: pattern="TODO|FIXME|HACK|XXX|DEPRECATED" path="addon/rootfs/opt/mindhome/" output_mode="content"
```

| Kategorie | Aktion |
|---|---|
| `TODO` ohne Kontext | → Recherchiere ob erledigt, dann entweder implementieren oder TODO entfernen |
| `FIXME` | → Ist der Bug noch da? Wenn ja → 🟡 Bug. Wenn nein → Kommentar entfernen |
| `HACK` | → Gibt es jetzt eine bessere Lösung? |
| `DEPRECATED` | → Wird der Code noch genutzt? Wenn nein → entfernen |

**Aktion**: Veraltete TODOs/FIXMEs direkt fixen oder entfernen. Nicht nur dokumentieren — reparieren!
**Erfolgskriterium**: Null veraltete TODOs/FIXMEs. Jeder Kommentar reflektiert den aktuellen Stand.

### Schritt 3 — Inline-Docs & Docstrings

Prüfe ob die **öffentlichen Funktionen** der Core-Module Docstrings haben:

```
# Funktionen ohne Docstring finden
Grep: pattern="def (process|handle|build|create|get|set|update|delete|search|send|receive)" path="assistant/assistant/" output_mode="content"
```

**Pflicht-Docstrings** für:
- Alle `brain.py` öffentlichen Methoden
- Alle `main.py` API-Endpoints
- Alle `memory.py` / `semantic_memory.py` Speicher/Abruf-Funktionen
- Alle Shared Schema Klassen

**Kein** Docstring nötig für:
- Private Methoden (`_helper()`)
- Triviale Getter/Setter
- Test-Funktionen

---

## Teil 2: Dependency-Audit

### Schritt 1 — Requirements-Dateien inventarisieren

```
Glob: pattern="**/requirements*.txt"
Read: /home/user/mindhome/assistant/requirements.txt
Read: /home/user/mindhome/speech/requirements.txt
Glob: pattern="**/requirements*.txt" path="/home/user/mindhome/addon/"
```

### Schritt 2 — Dependency-Checks

| Check | Methode | ✅ PASS | ❌ FAIL |
|---|---|---|---|
| **Version Pinning** | Jede Dependency hat Version (`==` oder `>=`) | Alle gepinnt | Unpinned Dependencies (z.B. `requests` statt `requests==2.31.0`) |
| **Unused Dependencies** | Grep nach Import für jede Dependency | Import existiert | Dependency installiert aber nie importiert |
| **Missing Dependencies** | Grep nach Imports die nicht in requirements stehen | Alle Imports abgedeckt | Import ohne zugehörige Dependency |
| **Duplikate** | Gleiche Dependency in mehreren requirements.txt | Gleiche Version | Verschiedene Versionen desselben Pakets |
| **Bekannte CVEs** | `pip audit` oder manuelle Prüfung kritischer Pakete | Keine bekannten CVEs | CVE in Produktions-Dependency |

```
# Alle importierten Pakete finden
Grep: pattern="^import |^from " path="assistant/assistant/" output_mode="content" head_limit=100
Grep: pattern="^import |^from " path="addon/rootfs/opt/mindhome/" output_mode="content" head_limit=100
```

**Kritische Pakete** die besonders geprüft werden müssen:
- `fastapi` / `flask` — Web-Framework-Version
- `pydantic` — v1 vs v2 Kompatibilität
- `chromadb` — Breaking Changes zwischen Versionen
- `redis` / `aioredis` — Async-Kompatibilität
- `ollama` — API-Kompatibilität mit Qwen 3.5

### Schritt 3 — Python-Version Konsistenz

```
Grep: pattern="python_requires|python-version|FROM python" path="." output_mode="content"
Grep: pattern="python" path="." glob="Dockerfile*" output_mode="content"
```

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| Alle Dockerfiles nutzen gleiche Python-Version | `FROM python:3.11-slim` überall | Verschiedene Versionen |
| requirements.txt kompatibel mit Python-Version | Alle Pakete unterstützen die Ziel-Version | Paket braucht neuere Python-Version |

---

## Teil 3: CI/CD & Build-Pipeline

### Schritt 1 — Aktueller Stand

```
Glob: pattern=".github/**/*"
Glob: pattern="Makefile"
Glob: pattern="*.sh" path="/home/user/mindhome/"
Glob: pattern="**/.pre-commit-config.yaml"
```

### Schritt 2 — Fehlende Pipeline-Elemente bewerten

| Element | Existiert? | Priorität | Empfehlung |
|---|---|---|---|
| **GitHub Actions Workflow** | ? | 🔴 HOCH | CI für Tests bei jedem Push |
| **Pre-commit Hooks** | ? | 🟠 MITTEL | Linting + Formatting vor Commit |
| **Dockerfile Lint** (hadolint) | ? | 🟡 NIEDRIG | Docker Best Practices |
| **Dependency Scanning** | ? | 🟠 MITTEL | `pip-audit` in CI |
| **Test-Automation** | ? | 🔴 HOCH | pytest bei jedem PR |
| **Build-Automation** | ? | 🟠 MITTEL | Docker-Build-Test in CI |

### Schritt 3 — Minimale CI/CD erstellen (wenn fehlend)

Wenn keine GitHub Actions existieren, erstelle eine **minimale** `.github/workflows/ci.yml`:

```yaml
# Nur erstellen wenn .github/ Verzeichnis nicht existiert!
name: MindHome CI
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test-assistant:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r assistant/requirements.txt
      - run: cd assistant && python -m pytest --tb=short -q

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install ruff
      - run: ruff check assistant/ addon/ speech/ shared/

  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t mindhome-assistant ./assistant
      - run: docker build -t mindhome-speech ./speech
      - run: docker build -t mindhome-addon ./addon
```

> **WICHTIG:** CI/CD erstellen, NICHT nur empfehlen. Aber NUR wenn `.github/workflows/` noch nicht existiert oder unvollständig ist. Wenn `.github/workflows/` nicht existiert, erstelle die minimale Pipeline. Der Audit fixiert — er empfiehlt nicht nur.

---

## Teil 4: Shell-Scripts & Build-Dateien

```
Glob: pattern="*.sh" path="/home/user/mindhome/"
```

Für jedes Shell-Script:

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| Shebang vorhanden (`#!/bin/bash`) | Ja | Fehlt |
| `set -euo pipefail` am Anfang | Ja | Fehlt → Stille Fehler möglich |
| Referenzierte Pfade existieren | Alle Pfade gültig | Veraltete oder falsche Pfade |
| Executable Flag gesetzt | `chmod +x` | Nicht ausführbar |
| Hardcoded Credentials | Keine | Passwörter/Keys im Script |

---

## Teil 5: Lokalisierung & Übersetzungen

```
Read: /home/user/mindhome/addon/rootfs/opt/mindhome/translations/de.json (oder ähnlich)
Glob: pattern="**/translations/**" path="/home/user/mindhome/"
Glob: pattern="**/{de,en}.json" path="/home/user/mindhome/"
```

| Check | ✅ PASS | ❌ FAIL |
|---|---|---|
| Alle UI-Strings übersetzt | de.json und en.json haben gleiche Keys | Keys fehlen in einer Sprache |
| Keine hardcoded Strings | Alle User-facing Strings über i18n | Hardcoded deutsch/englisch im Code |
| Konsistente Terminologie | "Jarvis" überall gleich, Befehle einheitlich | Inkonsistente Begriffe |

---

## Claude Code Tool-Einsatz

| Aufgabe | Tool | Befehl |
|---|---|---|
| README lesen | **Read** | `Read: /home/user/mindhome/README.md` |
| Version finden | **Grep** | `pattern="version" path="/home/user/mindhome/" glob="*.py"` |
| TODOs finden | **Grep** | `pattern="TODO\|FIXME" path="."` |
| Requirements lesen | **Read** | Alle `requirements.txt` |
| GitHub Actions prüfen | **Glob** | `pattern=".github/**/*"` |
| Scripts prüfen | **Glob** + **Read** | Alle `*.sh` |

---

## Erfolgskriterien

- □ README vs. Code-Realität geprüft — alle Abweichungen dokumentiert
- □ Veraltete TODOs/FIXMEs identifiziert und gefixt oder entfernt
- □ Alle requirements.txt analysiert — Pinning, Duplikate, Missing, CVEs
- □ Python-Version Konsistenz über alle Dockerfiles verifiziert
- □ CI/CD-Status dokumentiert — Empfehlung wenn fehlend
- □ Shell-Scripts geprüft — Shebang, error handling, Pfade
- □ Übersetzungs-Konsistenz geprüft

```
Checkliste:
□ README ist aktuell
□ Versions-Nummern konsistent
□ Null veraltete TODO/FIXME Kommentare
□ Dependencies gepinnt und aktuell
□ Keine unused/missing Dependencies
□ CI/CD dokumentiert oder erstellt
□ Shell-Scripts safe (set -euo pipefail)
□ Übersetzungen vollständig
```

---

## Output

Am Ende erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
THEMA: Code-Qualität (Docs, Dependencies, CI/CD)

DOKUMENTATION:
- README-Status: [AKTUELL / VERALTET + was fehlt]
- Veraltete TODOs: [Anzahl gefunden → Anzahl gefixt]
- Docstring-Abdeckung: [% der öffentlichen Core-Funktionen]

DEPENDENCIES:
- Unpinned: [Anzahl und welche]
- Unused: [Anzahl und welche]
- Missing: [Anzahl und welche]
- CVEs: [Anzahl und welche Pakete]
- Python-Version: [konsistent? welche?]

CI/CD:
- GitHub Actions: [VORHANDEN / FEHLT → erstellt / EMPFOHLEN]
- Pre-commit: [VORHANDEN / FEHLT]
- Test-Automation: [VORHANDEN / FEHLT]

SHELL-SCRIPTS:
- Geprüft: [Anzahl] | Probleme: [Anzahl]

LOKALISIERUNG:
- Fehlende Keys: [Anzahl]
- Hardcoded Strings: [Anzahl]

GEFIXT: [Liste der Fixes mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste]
===================================
```
