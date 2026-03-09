# Jarvis Audit — Prompt-Serie (Übersicht)

Diese 6 Prompts sind dafür gedacht, **der Reihe nach** an ein LLM übergeben zu werden. Jeder Prompt ist fokussiert auf ein Thema und liefert als Output den Input für den nächsten.

## Reihenfolge

| # | Datei | Fokus | Abhängigkeit |
|---|---|---|---|
| 1 | `PROMPT_01_ARCHITEKTUR.md` | Architektur-Analyse & Modul-Konflikte | Keine — Startpunkt |
| 2 | `PROMPT_02_MEMORY.md` | Memory-System End-to-End | Nutzt Konflikt-Karte aus #1 |
| 3 | `PROMPT_03_FLOWS.md` | Kritische Pfade Zeile für Zeile | Nutzt Ergebnisse aus #1 + #2 |
| 4 | `PROMPT_04_BUGS.md` | Systematische Bug-Jagd aller Module | Nutzt Architektur-Verständnis aus #1–#3 |
| 5 | `PROMPT_05_PERSONALITY.md` | Persönlichkeit, Config & MCU-Authentizität | Nutzt Bug-Liste aus #4 |
| 6 | `PROMPT_06_HARMONISIERUNG.md` | Integration & Kohärenz | Baut auf allem auf |

## Wie verwenden

1. Starte mit Prompt 1 in einer **neuen Konversation**
2. Lass das LLM die Analyse durchführen
3. Kopiere das **Output** (Konflikt-Karte, Bug-Report etc.) als Kontext in den nächsten Prompt
4. Wiederhole bis Prompt 6

> **Tipp**: Jeder Prompt enthält einen `## Kontext aus vorherigen Prompts`-Abschnitt. Füge dort die Ergebnisse der vorherigen Runde ein.

## Gemeinsame Rolle (in jedem Prompt enthalten)

Alle Prompts nutzen dieselbe Rollen-Definition: Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Die Rolle wird in jedem Prompt wiederholt, damit sie auch einzeln funktionieren.
