# Jarvis Audit — Prompt-Serie (Übersicht)

Diese 7 Prompts sind dafür gedacht, **der Reihe nach** an ein LLM übergeben zu werden. Jeder Prompt ist fokussiert auf ein Thema und liefert als Output den Input für den nächsten.

## Das System

Jarvis besteht aus **drei Services**:
1. **Assistant** (`/assistant/assistant/`, ~89 Module, FastAPI) — KI-Kern
2. **Addon** (`/addon/rootfs/opt/mindhome/`, ~71 Module, Flask) — Smart-Home-Logik
3. **Speech** (`/speech/`, 2 Module, Whisper STT) — Spracheingabe

Dazu: 105 Test-Dateien, 3 Dockerfiles, 2 docker-compose Konfigurationen.

## Reihenfolge

| # | Datei | Fokus | Abhängigkeit |
|---|---|---|---|
| 1 | `PROMPT_01_ARCHITEKTUR.md` | Architektur, Modul-Konflikte, **3-Service-Interaktion** | Keine — Startpunkt |
| 2 | `PROMPT_02_MEMORY.md` | Memory-System End-to-End (**alle 13 Module**) | Nutzt Konflikt-Karte aus #1 |
| 3 | `PROMPT_03_FLOWS.md` | **9 kritische Pfade** inkl. Speech, Addon, Domain-Assistenten | Nutzt Ergebnisse aus #1 + #2 |
| 4 | `PROMPT_04_BUGS.md` | Systematische Bug-Jagd (**87+ Module**, Security, Resilience) | Nutzt Architektur-Verständnis aus #1–#3 |
| 5 | `PROMPT_05_PERSONALITY.md` | Persönlichkeit, Config, MCU-Authentizität | Nutzt Bug-Liste aus #4 |
| 6 | `PROMPT_06_HARMONISIERUNG.md` | Integration, Kohärenz, **Addon-Koordination** | Baut auf allem auf |
| 7 | `PROMPT_07_TESTING_DEPLOYMENT.md` | Tests, Docker, Resilience, **Verifikation** | Verifiziert die Fixes aus #6 |

## Wie verwenden

1. Starte mit Prompt 1 in einer **neuen Konversation**
2. Lass das LLM die Analyse durchführen
3. Kopiere das **Output** (Konflikt-Karte, Bug-Report etc.) als Kontext in den nächsten Prompt
4. Wiederhole bis Prompt 7

> **Tipp**: Jeder Prompt enthält einen `## Kontext aus vorherigen Prompts`-Abschnitt. Füge dort die Ergebnisse der vorherigen Runde ein.

## Was jeder Prompt abdeckt

| Aspekt | P1 | P2 | P3 | P4 | P5 | P6 | P7 |
|---|---|---|---|---|---|---|---|
| Assistant-Module | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Addon-Module | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Speech-Service | ✅ | - | ✅ | ✅ | - | - | ✅ |
| Architektur | ✅ | - | - | - | - | ✅ | - |
| Memory (13 Module) | - | ✅ | ✅ | ✅ | - | ✅ | ✅ |
| Flows (9 Pfade) | - | - | ✅ | - | - | ✅ | ✅ |
| Bug-Jagd (12 Klassen) | - | - | - | ✅ | - | ✅ | - |
| Security | - | - | - | ✅ | - | ✅ | ✅ |
| Resilience | - | - | - | ✅ | - | ✅ | ✅ |
| Persönlichkeit / MCU | ✅ | - | ✅ | - | ✅ | ✅ | - |
| Config / YAML | - | - | - | ✅ | ✅ | ✅ | - |
| Tests (105 Dateien) | - | - | - | - | - | - | ✅ |
| Docker / Deployment | - | - | - | - | - | - | ✅ |

## Gemeinsame Rolle

Alle Prompts nutzen dieselbe Rollen-Definition: Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Die Rolle wird in jedem Prompt wiederholt, damit sie auch einzeln funktionieren.

## Erwarteter Gesamt-Output nach allen 7 Prompts

1. **Konflikt-Karte** — Welche Module gegeneinander arbeiten (inkl. Addon ↔ Assistant)
2. **Memory-Diagnose** — Warum Jarvis vergisst + Fix
3. **Flow-Dokumentation** — 9 Pfade mit allen Bruchstellen
4. **Bug-Report** — Alle Bugs mit Severity, Security- und Resilience-Analyse
5. **Persönlichkeits-Audit** — MCU-Score + Inkonsistenzen + Config-Probleme
6. **Harmonisierte Codebase** — Implementierte Fixes
7. **Verifizierung** — Tests bestehen, Docker läuft, Resilience getestet
