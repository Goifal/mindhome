# Prompt 3b: End-to-End Flow-Analyse — Extended-Flows (8–13) + Kollisionen

## Rolle

Du bist ein Elite-Software-Architekt mit tiefem Wissen in AsyncIO, FastAPI, Flask, LLM-Integration, Function Calling, Speech Processing und Smart Home (Home Assistant). Du kennst J.A.R.V.I.S. aus dem MCU als Goldstandard für einen kohärenten, koordinierten Assistenten.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–3a bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Füge hier ein:
> - Kontext-Block aus Prompt 1 (Konflikt-Karte, besonders Konflikt F: Assistant ↔ Addon)
> - Kontext-Block aus Prompt 2 (Memory-Analyse)
> - Kontext-Block aus Prompt 3a (Init-Sequenz, System-Prompt, Core-Flows 1–7 Status + Bruchstellen)
>
> **⚠️ OHNE den Kontext-Block aus P3a fehlen dir die Core-Flow-Ergebnisse!** Die Extended-Flows (8–13) interagieren mit den Core-Flows. Besonders die Init-Sequenz und der System-Prompt aus P3a sind essentiell.

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode, nicht mit einem laufenden System. Folge jedem Funktionsaufruf bis zur letzten Zeile.

---

## Aufgabe

> **Dieser Prompt ist Teil 2 von 2** der Flow-Analyse:
> - **P03a**: Vorab-Analyse (Init + System-Prompt) + Core-Flows 1–7 — ✅ erledigt
> - **P03b** (dieser): Extended-Flows 8–13 + Flow-Kollisionen + Service-Interaktionsanalyse

---

### Flow 8: Addon-Automation (KRITISCH)

```
Addon erkennt ein Event / Pattern / Zeitplan
  → addon/automation_engine.py oder addon/pattern_engine.py
    → addon/event_bus.py: Event verteilen
      → addon/domains/*.py: Aktion ausführen (z.B. Licht, Cover)
        → addon/ha_connection.py: HA-API-Call
```

**Prüfe besonders**:
- Nutzt der Addon die **Shared Schemas** (`shared/schemas/`) oder hat er eigene Request/Response-Definitionen?
- Nutzt der Addon die **Shared Constants** (`shared/constants.py`) für Ports und Event-Namen?
- Läuft dieser Flow **komplett unabhängig** vom Assistant?
- Weiß der Assistant dass der Addon gerade eine Aktion ausführt?
- Kann der Addon eine Entity steuern die der Assistant gerade AUCH steuert?
- Nutzt der Addon dieselbe HA-Instanz? Gleiche Credentials?
- Gibt es Addon-Engines (z.B. `circadian.py`, `cover_control.py`) die **dasselbe** tun wie Assistant-Module (`light_engine.py`, `cover_config.py`)?

---

### Flow 9: Domain-Assistenten

```
User: "Was kann ich heute kochen?"
  → brain.py: Erkennt als Domain-spezifisch
    → cooking_assistant.py / recipe_store.py
      → Rezept-Suche / Inventar-Check (inventory.py)
        → LLM: Antwort generieren
```

Analog für:
- `music_dj.py` → Musik-Steuerung
- `smart_shopping.py` → Einkaufsliste
- `calendar_intelligence.py` → Termine
- `web_search.py` → Internet-Suche

**Prüfe besonders**:
- Werden Domain-Assistenten **korrekt geroutet**? Wer entscheidet welcher Assistent?
- Gehen sie durch die **gleiche** Persönlichkeits-Pipeline?
- Haben sie Zugriff auf **Memory** und **Kontext**?
- Oder sind es isolierte Module die den Jarvis-Charakter verlieren?

---

### Flow 10: Workshop-System (Großes Sub-System!)

> ⚠️ **Der Workshop ist ein eigenständiges Sub-System mit 80+ API-Endpoints in main.py!**

```
User: "Hilf mir beim Reparieren meiner Lampe" / Workshop-UI
  → main.py: /api/workshop/* Endpoints (80+ Stück!)
    → repair_planner.py: Projekt-Management, Schritt-Navigation, Diagnose
    → workshop_generator.py: Code-Generierung (Arduino, Python, C++), 3D-Modelle (OpenSCAD), SVGs, BOMs
    → workshop_library.py: Technische Referenz-Dokumentation (ChromaDB RAG)
    → Kalkulationen: Widerstandsteiler, LED-Vorwiderstände, Ohm'sches Gesetz, 3D-Druck-Gewicht
    → 3D-Drucker-Steuerung: Start/Pause/Cancel über HA
    → Roboter-Arm-Steuerung: Move/Gripper/Home/Save-Position/Pick-Tool
    → Tool-Lending: Werkzeug-Verleih-Tracking
    → Inventar: Workshop-Bestandsverwaltung
```

**Prüfe besonders**:
- Ist der Workshop **in brain.py integriert** oder ein **separates System in main.py**?
- Geht der Workshop-Chat durch die **Persönlichkeits-Pipeline**? Oder ist es ein eigener LLM-Call?
- 3D-Drucker- und Roboter-Arm-Steuerung: Über `ha_client.py` oder direkte API-Calls?
- Sicherheit: Kann jeder User Roboter-Arme steuern? Trust-Level-Check?

---

### Flow 11: Boot-Sequenz & Startup-Announcement

```
Docker-Start → main.py: lifespan()
  → brain.py: initialize() — Alle Module starten
    → Redis, ChromaDB, Ollama Connections
    → Health-Check aller Dependencies
  → main.py: _boot_announcement()
    → HA-States abfragen (Temperatur, offene Fenster/Türen)
    → Zufällige Boot-Nachricht auswählen
    → Fehlende Komponenten melden
    → TTS-Ausgabe: "Alle Systeme online, Sir."
```

**Prüfe besonders**:
- Was passiert wenn Dependencies beim Start fehlen? Startet Jarvis degraded oder crasht er?
- Wird die Boot-Announcement durch die Persönlichkeits-Pipeline geleitet?
- Wann ist Jarvis "bereit"? Gibt es einen Ready-Status?

---

### Flow 12: File-Upload & OCR

```
User lädt Datei hoch (Bild, PDF, Dokument)
  → main.py: /api/assistant/chat/upload
    → file_handler.py: Validierung (50MB Limit, Typ-Check, Path-Traversal-Schutz)
      → ocr.py: Text-Extraktion (Tesseract) + optionale Vision-LLM-Beschreibung
        → brain.py: Chat mit Datei-Kontext
```

**Prüfe besonders**:
- Sicherheit: Path Traversal, Injection über Dateinamen?
- Wird der extrahierte Text ins LLM-Context-Window passen (4000 char Limit)?

---

### Flow 13: WebSocket-Streaming

```
Client verbindet sich → main.py: /api/assistant/ws
  → WebSocket-Manager: Client registrieren
    → Events empfangen: thinking, speaking, action, proactive, sound, audio
    → Streaming: emit_stream_start → emit_stream_token (Token für Token) → emit_stream_end
    → Bidirektionale Kommunikation
```

**Prüfe besonders**:
- Reconnection-Handling wenn WebSocket abbricht?
- Werden alle Antwort-Pfade (normal, proaktiv, routine) über WebSocket gestreamt?
- Backpressure: Was wenn der Client nicht schnell genug konsumiert?

---

## Flow-Kollisionen

Prüfe diese **Gleichzeitigkeits-Szenarien**:

| Szenario | Was sollte passieren | Was passiert tatsächlich? | Code-Referenz |
|---|---|---|---|
| Proaktive Warnung während User spricht | Queue, nach Antwort ausspielen | ? | ? |
| Morgen-Briefing während Konversation | Briefing verzögern oder ankündigen | ? | ? |
| Zwei autonome Aktionen gleichzeitig | Priorisieren, eine zuerst | ? | ? |
| Function Call + autonome Aktion | User-Aktion hat Vorrang | ? | ? |
| Memory-Speicherung während nächster Request | Nicht blockieren, async | ? | ? |
| **Addon-Automation + Assistant-Aktion** | Wer gewinnt? | ? | ? |
| **Addon-Cover-Control + Assistant-Cover-Config** | Gleiche Rollläden? | ? | ? |
| **Addon-Circadian + Assistant-Light-Engine** | Gleiche Lampen? | ? | ? |
| **Speech in Raum A + Speech in Raum B** | Parallel oder sequentiell? | ? | ? |

---

## Output-Format

### 1. Flow-Dokumentation (Flows 8–13)

Für jeden Flow:
```
### Flow X: Name
**Status**: ✅ Funktioniert / ⚠️ Teilweise / ❌ Kaputt / 🔍 Nicht verbunden

**Ablauf**:
1. [Funktion] in [datei.py:zeile] → [was passiert]
...

**Bruchstellen**:
- [datei.py:zeile]: Beschreibung

**Kollisionen mit anderen Flows**:
- Flow X kollidiert mit Flow Y bei [Beschreibung]
```

### 2. Kollisions-Tabelle (ausgefüllt)

### 3. Service-Interaktions-Analyse

Wie kommunizieren die drei Services (Assistant, Addon, Speech) in jedem Flow?

### 4. Kritische Findings

Top-5 Probleme aus Flows 8–13, sortiert nach Impact.

### 5. Feature-Gaps

Flows/Features die komplett fehlen.

---

## Regeln

### Gründlichkeits-Pflicht

> **Für JEDEN der 6 Flows: Lies JEDE beteiligte Datei mit Read. Folge JEDEM Funktionsaufruf.**

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Beispiel |
|---|---|---|
| Addon-Endpoints finden | **Grep** | `pattern="@.*route|@app\." path="addon/"` |
| WebSocket-Events finden | **Grep** | `pattern="emit_stream|ws_send|websocket" path="assistant/"` |
| Flow-Kollisionen aufdecken | **Grep** | `pattern="asyncio\.Lock|async with.*lock|Queue" path="assistant/"` |

**Parallelisierung**:
- **Gruppe A** (parallel): Flow 8, 9 (Addon, Domain — unabhängig)
- **Gruppe B** (parallel): Flow 11, 12, 13 (Boot, Upload, WebSocket)
- **Flow 10** (eigener Durchgang): Workshop ist groß genug für eigenen Batch

- Folge dem Code **Zeile für Zeile**
- Jede Aussage mit **Datei:Zeile** belegen
- **Addon-Kollisionen** besonders beachten — das ist der blinde Fleck des Projekts
- MCU-Jarvis-Test: Würde sich der echte Jarvis so verhalten?

---

## ⚡ Übergabe an Prompt 4a

Formatiere am Ende einen kompakten **Kontext-Block** für Prompt 4a:

```
## KONTEXT AUS PROMPT 3 (gesamt: 3a + 3b): Flow-Analyse

### Init-Sequenz
[Aus P3a — Exakte Startup-Reihenfolge]

### System-Prompt (rekonstruiert)
[Aus P3a — Struktur des System-Prompts]

### Flow-Status-Übersicht (alle 13 Flows)
| Flow | Status | Kritischste Bruchstelle |
|---|---|---|
| 1–7 | [Aus P3a] | ... |
| 8: Addon-Automation | ✅/⚠️/❌ | ... |
| 9: Domain-Assistenten | ✅/⚠️/❌ | ... |
| 10: Workshop-System | ✅/⚠️/❌ | ... |
| 11: Boot-Sequenz | ✅/⚠️/❌ | ... |
| 12: File-Upload & OCR | ✅/⚠️/❌ | ... |
| 13: WebSocket-Streaming | ✅/⚠️/❌ | ... |

### Top-Bruchstellen (alle Flows)
[Die 5 kritischsten Bruchstellen mit Datei:Zeile]

### Kollisionen
[Die kritischsten Kollisionen zwischen Flows]

### Feature-Gaps
[Flows/Features die komplett fehlen]
```

**Wenn du Prompt 4a in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke (Prompt 1 + 2 + 3a + 3b) automatisch ein.
