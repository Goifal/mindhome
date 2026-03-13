# Prompt 01: Architektur & Core-Flows — Analyse

---

## HEADER

**Was dieser Prompt tut:**
Liest und dokumentiert die Jarvis-Architektur: 3 kritische Konflikte + 7 Core-Flows End-to-End.
Reine Analyse — kein Code wird geaendert.

**Ersetzt:** PROMPT_01 (Architektur), PROMPT_03a (Flows Core), PROMPT_03b (Flows Extended)

**Geschaetzte Dauer:** 30–45 Minuten

**Modus:** NUR LESEN. Keine Edits, keine Fixes. Ziel ist eine vollstaendige Karte fuer Folge-Prompts.

---

## Rolle

Du bist ein Elite-Software-Architekt und KI-Ingenieur mit tiefem Wissen in:

- **LLM-Engineering**: Prompt Design, Context Window, Token-Budget, Function Calling, Chain-of-Thought
- **Agent-Architekturen**: ReAct, Tool-Use-Loops, Autonomy Levels, Self-Reflection
- **Python**: AsyncIO, FastAPI, Flask, Pydantic, aiohttp, Dataclasses, GIL-Implikationen
- **Smart Home**: Home Assistant REST/WebSocket API, Entity States, Services, Event Bus
- **Infrastruktur**: Docker, Redis, SQLite, YAML/Jinja2, WebSocket, Multi-Service-Architekturen

Du kennst **J.A.R.V.I.S. aus dem MCU** als Goldstandard: Ein Bewusstsein, eine Stimme, nie widerspruechlich.

---

## LLM-Spezifisch (Qwen 3.5)

```
LLM-SPEZIFISCH (Qwen 3.5):
- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel
```

Behalte diese Eigenheiten im Kopf wenn du die Flows analysierst — besonders beim System-Prompt-Bau (Flow 5) und Tool-Call-Handling (Flow 1).

---

## Arbeitsumgebung

Du arbeitest mit dem **GitHub-Quellcode**, nicht mit einem laufenden System:
- Keine `.env`-Datei — nur `.env.example`
- Kein laufendes Redis/ChromaDB/Ollama
- Du kannst nur Code lesen, nicht testen
- **Folge jedem Funktionsaufruf bis zum Ende. Keine Annahmen.**

---

## Kontext: Projekt-Struktur

Jarvis besteht aus **drei Services**:

1. **Assistant-Server** (`/assistant/assistant/`, FastAPI)
   - KI-Kern: LLM, Memory, Persoenlichkeit, Function Calling
   - Kommuniziert mit HA ueber REST/WebSocket

2. **Addon-Server** (`/addon/rootfs/opt/mindhome/`, Flask)
   - Smart-Home-Logik: Domain-Controller, Automation-Engine
   - Eigener Event-Bus, eigene HA-Connection
   - 25+ Domain-Module, 14+ Engines, 17+ API-Routes

3. **Speech-Server** (`/speech/`, Python)
   - STT (Whisper/faster-whisper) und TTS (Piper)
   - WebSocket-Kommunikation mit Assistant

---

## Dateien die du lesen musst

Lies diese Dateien **in dieser Reihenfolge** bevor du mit der Analyse beginnst:

| # | Datei | Offset-Hinweise | Zweck |
|---|-------|-----------------|-------|
| 1 | `assistant/assistant/brain.py` | `process()` ~Z.1100, `_process_inner` ~Z.1132, `_mega_tasks` ~Z.2430, `_filter_response` ~Z.4868, `_deterministic_tool_call` ~Z.6916 | Haupt-Verarbeitungsschleife |
| 2 | `assistant/assistant/personality.py` | `SYSTEM_PROMPT_TEMPLATE` ~Z.242, `build_system_prompt` | System-Prompt-Konstruktion |
| 3 | `assistant/assistant/function_calling.py` | `get_assistant_tools` ~Z.3143, `FunctionExecutor` ~Z.3202 | Tool-Definitionen + Ausfuehrung |
| 4 | `assistant/assistant/sound_manager.py` | `speak_response` ~Z.495 | TTS-Ausgabe |
| 5 | `assistant/assistant/memory.py` | komplett | Fact Storage |
| 6 | `assistant/assistant/semantic_memory.py` | komplett | Semantische Suche |
| 7 | `assistant/assistant/config.py` | `ModelProfile`, `get_model_profile` | Modell-Konfiguration |
| 8 | `assistant/assistant/model_router.py` | komplett | Modell-Auswahl (fast/smart/deep) |
| 9 | `assistant/assistant/ollama_client.py` | komplett | LLM-API-Kommunikation |
| 10 | `assistant/assistant/context_builder.py` | komplett | Kontext-Zusammenbau fuer LLM |
| 11 | `assistant/config/settings.yaml` | `model_profiles` Sektion | Konfiguration + character_hint |

**brain.py ist ~10.000 Zeilen.** Nutze die Offset-Hinweise um gezielt zu den relevanten Funktionen zu springen. Du musst nicht jede Zeile lesen — fokussiere dich auf die genannten Funktionen.

---

## Teil 1: Drei kritische Konflikte

Analysiere diese drei Konflikte. Fuer jeden: **Problem** (1 Zeile), **Root Cause** (1 Zeile), **Fix-Vorschlag** (1 Zeile).

### Konflikt A: brain.py process_lock serialisiert alles

**Was du pruefen musst:**
- Wo wird `_process_lock` definiert und genutzt?
- Welche Operationen werden dadurch serialisiert die eigentlich parallel laufen koennten?
- Wie lange blockiert ein typischer `process()`-Aufruf?
- Was passiert wenn waehrend eines laufenden Calls eine proaktive Notification kommt?

**Dokumentiere:** Lock-Scope, betroffene Methoden, konkrete Datei:Zeile-Referenzen.

### Konflikt D: Personality-Inkonsistenz

**Was du pruefen musst:**
- Wie wird der System-Prompt in `personality.py` zusammengebaut?
- Wie viele dynamische Sektionen gibt es? (Zaehle sie!)
- Welche Sektionen koennen sich widersprechen?
- Wie gross wird der System-Prompt im Worst Case (Token-Schaetzung)?
- Interaktion mit Qwen 3.5: Verliert das Modell bei langem System-Prompt den Tool-Call-Fokus?

**Dokumentiere:** Anzahl Sektionen, Widerspruchs-Paare, Token-Schaetzung, Datei:Zeile-Referenzen.

### Konflikt F: Assistant <-> Addon Koordination

**Was du pruefen musst:**
- Wie kommunizieren Assistant und Addon? (REST? WebSocket? Events?)
- Gibt es doppelte HA-Connections? (Assistant: `ha_client.py`, Addon: `ha_connection.py`)
- Wer entscheidet was — gibt es Race Conditions oder widerspruechliche Aktionen?
- Wie werden Addon-Funktionen aus dem Assistant aufgerufen? (Tool-Calls → HTTP → Addon?)

**Dokumentiere:** Kommunikationswege, doppelte Logik, Datei:Zeile-Referenzen.

---

## Teil 2: Sieben Core-Flows

Verfolge jeden Flow End-to-End durch den Code. Dokumentiere fuer jeden:
- **Pfad**: Datei:Funktion → Datei:Funktion → ... (exakte Aufrufkette)
- **Status**: ✅ funktioniert | ⚠️ fragil | ❌ kaputt
- **Problem** (1 Zeile, falls ⚠️ oder ❌)
- **Root Cause** (1 Zeile)
- **Fix-Vorschlag** (1 Zeile)

### Flow 1: Voice Input → Tool-Call → Device → Response → TTS

```
Speech-Server empfaengt Audio
  → STT (Whisper)
  → Text an Assistant (WebSocket/REST?)
  → brain.py process()
  → LLM generiert Tool-Call
  → function_calling.py fuehrt Tool aus
  → HA-Geraet wird gesteuert
  → LLM generiert Antwort
  → TTS (Piper)
  → Audio zurueck an Speech-Server
```

**Fokus:** Wo kann der Flow haengenbleiben? Was passiert bei Tool-Call-Fehlern?

### Flow 2: Proactive Notification Pipeline

```
Addon erkennt Event (z.B. Tuer offen)
  → Notification an Assistant
  → brain.py verarbeitet proaktiv
  → TTS-Ausgabe ohne User-Input
```

**Fokus:** Wie kommt die Notification an? Blockiert der process_lock? Wird die Notification verworfen?

### Flow 3: Morning Briefing

```
Zeitgesteuerter Trigger
  → Wetter + Kalender + Geraetestatus sammeln
  → LLM generiert Briefing
  → TTS-Ausgabe
```

**Fokus:** Woher kommen die Daten? Wie viele API-Calls? Was wenn einer fehlschlaegt?

### Flow 4: Autonomous Action (Autonomy Levels)

```
Situation erkannt (z.B. niemand zuhause, Licht an)
  → Autonomy-Level pruefen
  → Level 1: Nur informieren
  → Level 2: Vorschlagen
  → Level 3: Ausfuehren mit Bestaetigung
  → Level 4: Autonom ausfuehren
```

**Fokus:** Wo sind die Autonomy-Levels definiert? Wer prueft sie? Kann das System ohne Erlaubnis handeln?

### Flow 5: Personality Pipeline (System-Prompt-Konstruktion)

```
Request kommt rein
  → personality.py build_system_prompt()
  → Basis-Template laden
  → Dynamische Sektionen einfuegen (Uhrzeit, Stimmung, Raum, ...)
  → character_hint aus model_profiles
  → Fertiger System-Prompt an LLM
```

**Fokus:** Wie viele Token? Welche Sektionen sind dynamisch? Widerspruechs-Risiko mit Qwen 3.5?

### Flow 6: Memory Retrieval (Fact Storage → Fact Recall)

```
User sagt etwas Merkwuerdiges
  → memory.py speichert Fakt
  → Spaeter: User fragt nach gespeichertem Fakt
  → semantic_memory.py sucht aehnliche Fakten
  → Kontext wird an LLM angehaengt
  → LLM antwortet mit gespeichertem Wissen
```

**Fokus:** Wie wird entschieden was gespeichert wird? Wie wird gesucht? Redis vs. ChromaDB?

### Flow 7: Speech Pipeline (STT → Brain → TTS)

```
Mikrofon-Input
  → VAD (Voice Activity Detection)
  → Whisper STT
  → Text an brain.py
  → Antwort von LLM
  → Piper TTS
  → Audio-Output
```

**Fokus:** Latenz-Kette. Wo sind die groessten Verzoegerungen? Streaming oder Batch?

---

## Output-Format

Dein Output muss diese Struktur haben:

### Konflikt-Analyse

```
## Konflikt A: process_lock
- Problem: [1 Zeile]
- Root Cause: [1 Zeile] — Datei:Zeile
- Fix-Vorschlag: [1 Zeile]

## Konflikt D: Personality
- Problem: [1 Zeile]
- Root Cause: [1 Zeile] — Datei:Zeile
- Fix-Vorschlag: [1 Zeile]

## Konflikt F: Assistant-Addon
- Problem: [1 Zeile]
- Root Cause: [1 Zeile] — Datei:Zeile
- Fix-Vorschlag: [1 Zeile]
```

### Flow-Analyse

```
## Flow N: [Name]
- Pfad: datei:funktion → datei:funktion → ...
- Status: ✅/⚠️/❌
- Problem: [1 Zeile, falls nicht ✅]
- Root Cause: [1 Zeile]
- Fix-Vorschlag: [1 Zeile]
```

---

## Rollback-Regel

```
ROLLBACK-REGEL:
Dieser Prompt macht KEINE Edits — nur Analyse.
Falls ein Folge-Prompt basierend auf dieser Analyse Edits macht:
1. Vor dem ersten Edit: Merke dir den aktuellen Stand
2. Wenn ein Fix einen ImportError oder SyntaxError verursacht: SOFORT revert
3. Im OFFEN-Block dokumentieren
4. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.
```

---

## Erfolgs-Check

```
ERFOLGS-CHECK:
□ Alle 3 Konflikte (A, D, F) analysiert mit konkreten Datei:Zeile Referenzen
□ Alle 7 Core-Flows dokumentiert mit Status (✅/⚠️/❌)
□ Jeder Flow hat exakte Aufrufkette (Datei:Funktion → Datei:Funktion)
□ Jeder nicht-✅ Flow hat mindestens 1 konkreten Fix-Vorschlag
□ Token-Schaetzung fuer System-Prompt vorhanden
□ Qwen-3.5-spezifische Risiken bei Flow 1 und 5 dokumentiert
□ Output-Block (Kontext-Handoff) enthaelt alle Felder
```

---

## Kontext-Handoff

Schliesse deine Analyse mit diesem Block ab — er wird in den naechsten Prompt kopiert:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste — bei reiner Analyse: "Nichts (Analyse-only)"]
OFFEN: [Liste der gefundenen Probleme mit Prioritaet]
GEAENDERTE DATEIEN: [Liste — bei reiner Analyse: "Keine"]
REGRESSIONEN: [Liste — bei reiner Analyse: "Keine"]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll, z.B. "Konflikt A fixen: process_lock aufbrechen"]
===================================
```
