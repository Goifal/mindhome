# Prompt 3a: End-to-End Flow-Analyse — Core-Flows (1–7)

## Rolle

Du bist ein Elite-Software-Architekt mit tiefem Wissen in AsyncIO, FastAPI, Flask, LLM-Integration, Function Calling, Speech Processing und Smart Home (Home Assistant). Du kennst J.A.R.V.I.S. aus dem MCU als Goldstandard für einen kohärenten, koordinierten Assistenten.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–2 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier ein:
> - Kontext-Block aus Prompt 1 (Konflikt-Karte, besonders Konflikt F: Assistant ↔ Addon)
> - Kontext-Block aus Prompt 2 (Memory-Analyse, Root Cause, Memory-Flow)
>
> **⚠️ OHNE diese Kontext-Blöcke kann dieser Prompt nicht sinnvoll arbeiten!** Die Flows bauen auf dem Architektur-Verständnis aus P1 und der Memory-Analyse aus P2 auf. Wenn du die Blöcke nicht hast, starte zuerst mit Prompt 1.

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode, nicht mit einem laufenden System. Folge jedem Funktionsaufruf bis zur letzten Zeile. Keine Annahmen. Wenn du nicht sicher bist was eine Funktion tut — **öffne die Datei und lies sie**.

---

## Aufgabe

> **Dieser Prompt ist Teil 1 von 2** der Flow-Analyse:
> - **P03a** (dieser): Vorab-Analyse (Init + System-Prompt) + Core-Flows 1–7
> - **P03b**: Extended-Flows 8–13 + Flow-Kollisionen

### Vorab: Init-Sequenz und System-Prompt

**BEVOR du die Flows verfolgst**, kläre diese zwei fundamentalen Fragen:

#### A) Init-Sequenz: Wie startet Jarvis?

Verfolge den **kompletten Startup** von `main.py`:
```
main.py startet
  → Welche Module werden in welcher Reihenfolge initialisiert?
  → Welche brauchen Verbindungen (Redis, ChromaDB, Ollama, HA)?
  → Was passiert wenn eine Verbindung beim Start fehlt?
  → Gibt es eine Health-Check-Phase?
  → Wann ist Jarvis "bereit"?
```

Dokumentiere die **exakte Init-Reihenfolge** mit Datei:Zeile.

#### B) Der exakte LLM-Prompt: Was geht an Ollama?

**DAS ist das Wichtigste im ganzen System.** Verfolge in `context_builder.py` und `brain.py`:
1. Wie wird der **System-Prompt** zusammengebaut? (Zeige den Template-String!)
2. Welche **dynamischen Teile** werden eingefügt? (Memory, Personality, Situation, Tools...)
3. In welcher **Reihenfolge** werden die Teile zusammengesetzt?
4. Wie sieht das **Messages-Array** aus das an Ollama geht? (System + User + Assistant + Tool?)
5. Wie viele **Token** verbraucht der Kontext typischerweise?
6. Was passiert wenn der Kontext das **Context-Window übersteigt**? Wird gekürzt? Was wird zuerst entfernt?

**Zeige den rekonstruierten System-Prompt** — den Text den Ollama tatsächlich sieht.

---

### Flow 1: Sprach-Input → Antwort (Hauptpfad)

Der wichtigste Flow. Verfolge komplett:

```
HTTP Request / WebSocket Nachricht
  → main.py: Welcher Endpoint? Welche Funktion?
    → pre_classifier.py: Wird der Intent vorklassifiziert?
    → request_context.py: Welcher Kontext wird aufgebaut?
    → brain.py: Wie wird der Request verarbeitet?
      → context_builder.py: Was landet im System-Prompt?
        → personality.py: Wie wird die Persönlichkeit eingebaut?
          → mood_detector.py: Wird die Stimmung erkannt?
        → situation_model.py: Situations-Kontext?
        → time_awareness.py: Tageszeit-Kontext?
      → memory.py: Werden Erinnerungen geladen? (Ergebnis aus Prompt 2)
      → ollama_client.py / model_router.py: Wie wird das LLM aufgerufen?
        → function_calling.py: Werden Tool-Calls erkannt?
          → function_validator.py: Werden sie validiert?
          → ha_client.py: HA-API-Call ausführen
        → Zweiter LLM-Call nach Tool-Execution?
      → tts_enhancer.py: Text für TTS aufbereiten?
      → sound_manager.py: Audio abspielen?
    → Response zurück an den Client
```

**Prüfe besonders**:
- Werden die **Shared Schemas** (`shared/schemas/chat_request.py`, `chat_response.py`) tatsächlich verwendet? Oder definieren Services eigene Request/Response-Formate?
- Wird die Conversation History als Messages-Array übergeben? Oder nur der letzte Turn?
- Wird Function Calling korrekt als Tool-Use-Loop implementiert (Call → Execute → Result → LLM)?
- Werden Fehler bei HA-API-Calls abgefangen und dem User kommuniziert?
- Timeout-Handling: Was passiert wenn das LLM oder HA nicht antwortet?
- Wird `pre_classifier.py` genutzt? Was klassifiziert er? Beeinflusst es den Flow?
- Wird `conflict_resolver.py` aufgerufen wenn mehrere Intents erkannt werden?

---

### Flow 2: Proaktive Benachrichtigung

```
Home Assistant Event (z.B. Tür offen, Gerät fertig)
  → proactive.py / proactive_planner.py: Wie wird das Event empfangen?
    → Prioritäts-Bewertung: Ist es wichtig genug?
      → brain.py: Wie wird die Nachricht generiert?
        → personality.py: Jarvis-Ton?
        → tts_enhancer.py → sound_manager.py → multi_room_audio.py?
```

**Prüfe besonders**:
- Was passiert wenn der User **gerade spricht**? Wird unterbrochen? Gequeued? Ignoriert?
- Was passiert wenn **mehrere Events gleichzeitig** eintreffen?
- Gibt es ein Cooldown / Rate Limiting um Spam zu verhindern?
- Nutzt proactive.py den **gleichen** Persönlichkeits-Pfad wie normale Antworten?
- `proactive.py` vs `proactive_planner.py` — was macht jedes? Redundanz?

---

### Flow 3: Morgen-Briefing / Routinen

```
Timer / Motion Trigger
  → routine_engine.py: Wie wird die Routine gestartet?
    → Daten sammeln (Wetter, Kalender, News, Geräte-Status)
      → brain.py: Wie wird das Briefing generiert?
        → personality.py: Wird der Jarvis-Ton angewendet?
          → TTS: Ausgabe
```

**Prüfe besonders**:
- Nutzt routine_engine.py **eigene Templates** oder geht es durch brain.py/personality.py?
- Was wenn eine **Konversation läuft** — wird sie unterbrochen?
- Werden fehlende Datenquellen (z.B. Kalender nicht erreichbar) abgefangen?
- Ist der Ton des Briefings **konsistent** mit normalen Antworten?

---

### Flow 4: Autonome Aktion

```
Muster erkannt (anticipation.py / learning_observer.py / spontaneous_observer.py)
  → autonomy.py: Darf gehandelt werden? (Autonomie-Level 1-5)
    → action_planner.py oder function_calling.py: Aktion ausführen
      → ha_client.py → Home Assistant API
        → Benachrichtigung an User?
```

**Prüfe besonders**:
- Wer **autorisiert** autonome Aktionen? Gibt es Sicherheits-Limits?
- Kann eine autonome Aktion eine **User-Aktion überschreiben**?
- Werden autonome Aktionen **geloggt** und dem User **kommuniziert**?
- Funktioniert das Autonomie-Level-System (1–5) wirklich?
- `spontaneous_observer.py` — was beobachtet er? Löst er Aktionen aus?
- `threat_assessment.py` — wird es bei autonomen Aktionen konsultiert?

---

### Flow 5: Persönlichkeits-Pipeline

```
Antwort-Text vom LLM
  → personality.py: Welche Anpassungen?
    → Sarkasmus-Level (1-5)
    → Mood-basierte Anpassung (mood_detector.py)
    → Easter Egg Check
    → Opinion Injection
    → Formality Level
  → tts_enhancer.py: SSML/Sprech-Anpassungen?
  → Finaler Text → TTS
```

**Prüfe besonders**:
- Wird die Persönlichkeit **vor** oder **nach** dem LLM-Call angewendet?
- Oder wird sie als **System-Prompt** ins LLM injiziert (bevorzugt)?
- Werden Persönlichkeits-Anweisungen aus **verschiedenen Modulen** kombiniert oder überschreiben sie sich?
- Ist der Sarkasmus-Level **konsistent** über den gesamten Flow?

---

### Flow 6: Memory-Abruf (Erinnerung)

```
User: "Was habe ich gestern über X gesagt?"
  → brain.py: Erkennt es als Memory-Query?
    → memory.py / semantic_memory.py: Suche in ChromaDB/Redis
      → embeddings.py / embedding_extractor.py: Query-Embedding
      → context_builder.py: Erinnerung in Prompt einbauen
        → LLM: Antwort mit Erinnerungs-Kontext
```

**Prüfe besonders** (ergänzt Prompt 2):
- Wird eine Memory-Query **überhaupt als solche erkannt**?
- Oder wird sie wie eine normale Frage behandelt?
- Gibt es einen speziellen Code-Pfad für Erinnerungs-Fragen?

---

### Flow 7: Speech-Pipeline (NEU)

> **Zusätzliche Doku**: Lies `docs/AUDIT_TTS_STT.md` und `docs/SPEECH_SETUP.md` für Kontext zur bestehenden Speech-Analyse.

```
Audio-Input (Mikrofon / ESPHome Satellite)
  → ha_integration/.../conversation.py: HA Voice Pipeline Bridge
    → Speech-Server (speech/server.py): Whisper STT
      → Text an Assistant (wie? HTTP? WebSocket?)
      → speaker_recognition.py: Wer spricht?
        → brain.py: Verarbeitung (→ Flow 1)
          → TTS-Antwort generieren
            → tts_enhancer.py: SSML/Anpassungen
              → sound_manager.py: Wiedergabe
                → multi_room_audio.py: Welcher Raum?
                  → ambient_audio.py: Hintergrund-Audio pausieren?
```

**Prüfe besonders**:
- Wie kommuniziert der Speech-Server mit dem Assistant? Protokoll? Latenz?
- Funktioniert Speaker Recognition? Wird sie im Kontext genutzt (verschiedene User)?
- Multi-Room: Antwortet Jarvis im **richtigen Raum**?
- Was wenn STT fehlschlägt oder unverständlich ist?
- Wird ambient_audio.py korrekt pausiert/resumed?
- Latenz: Wie lange dauert der Gesamtflow (STT → LLM → TTS)?

---

## Output-Format

### 1. Init-Sequenz (komplett)

Alle Module in exakter Startup-Reihenfolge mit Datei:Zeile.

### 2. Der rekonstruierte System-Prompt

Der **vollständige Text** den Ollama als System-Prompt erhält, mit Markierungen welcher Teil aus welchem Modul kommt.

### 3. Flow-Dokumentation (Flows 1–7)

Für jeden Flow:
```
### Flow X: Name
**Status**: ✅ Funktioniert / ⚠️ Teilweise / ❌ Kaputt / 🔍 Nicht verbunden

**Ablauf**:
1. [Funktion] in [datei.py:zeile] → [was passiert]
2. [Funktion] in [datei.py:zeile] → [was passiert]
...

**Bruchstellen**:
- [datei.py:zeile]: Beschreibung des Problems

**Fehler-Pfade** (Was passiert wenn ein Schritt fehlschlägt?):
- Schritt X schlägt fehl → [Was passiert? Crash / Stille / User wird informiert?]
- Erreicht der Fehler den User? [Ja: wie / Nein: warum nicht]

**Kollisionen mit anderen Flows**:
- Flow X kollidiert mit Flow Y bei [Beschreibung]
```

### 4. Kritische Findings

Top-5 Probleme aus Flows 1–7, sortiert nach Impact.

---

## Regeln

### Gründlichkeits-Pflicht

> **Für JEDEN der 7 Flows: Lies JEDE beteiligte Datei mit Read. Lies JEDE Funktion die aufgerufen wird. Folge JEDEM Funktionsaufruf bis zum Ende.**
>
> "Zeile für Zeile" ist WÖRTLICH gemeint. Wenn du eine Funktion siehst (`await self.memory.load(...)`) — lies `memory.py` mit Read, finde `load()`, lies was es tut, prüfe was es zurückgibt, prüfe ob der Aufrufer das Ergebnis korrekt verwendet.
>
> Der Init-Sequenz und der System-Prompt sind **Pflicht-Output**, nicht optional.

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Beispiel |
|---|---|---|
| Flow-Einstiegspunkte finden | **Grep** | `pattern="@app\.(post|get|websocket)" path="assistant/assistant/main.py"` |
| Funktionsaufruf-Kette verfolgen | **Grep** → **Read** | Grep findet Aufrufer, Read zeigt Implementierung |
| Init-Sequenz finden | **Read** `main.py` + **Grep** `pattern="async def.*(init|startup|lifespan)"` |
| System-Prompt rekonstruieren | **Read** `context_builder.py` + `personality.py` |
| Shared-Schema-Nutzung prüfen | **Grep** | `pattern="ChatRequest|ChatResponse|MindHomeEvent" path="."` |

**Parallelisierung**: Die 7 Core-Flows können teilweise **parallel analysiert** werden:
- **Gruppe A** (parallel): Flow 1, 2, 3 (verschiedene Einstiegspunkte)
- **Gruppe B** (sequentiell nach A): Flow 4, 5, 6 (bauen auf Flow 1 auf)
- **Flow 7** (parallel zu Gruppe B): Speech-Pipeline ist unabhängig

- Folge dem Code **Zeile für Zeile** — keine Annahmen
- Jede Aussage mit **Datei:Zeile** belegen
- Fokus auf **Bruchstellen** — nicht auf Code-Stil
- MCU-Jarvis-Test: Würde sich der echte Jarvis so verhalten?

---

## ⚡ Übergabe an Prompt 3b

Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block** für Prompt 3b:

```
## KONTEXT AUS PROMPT 3a: Flow-Analyse (Core-Flows)

### Init-Sequenz
[Exakte Startup-Reihenfolge mit Datei:Zeile]

### System-Prompt (rekonstruiert)
[Der vollständige Text den Ollama als System-Prompt bekommt — oder zumindest die Struktur]

### Flow-Status-Übersicht (Core-Flows 1–7)
| Flow | Status | Kritischste Bruchstelle |
|---|---|---|
| 1: Sprach-Input → Antwort | ✅/⚠️/❌ | ... |
| 2: Proaktive Benachrichtigung | ✅/⚠️/❌ | ... |
| 3: Morgen-Briefing | ✅/⚠️/❌ | ... |
| 4: Autonome Aktion | ✅/⚠️/❌ | ... |
| 5: Persönlichkeits-Pipeline | ✅/⚠️/❌ | ... |
| 6: Memory-Abruf | ✅/⚠️/❌ | ... |
| 7: Speech-Pipeline | ✅/⚠️/❌ | ... |

### Top-Bruchstellen (Core-Flows)
[Die 5 kritischsten Bruchstellen mit Datei:Zeile]
```

**Wenn du Prompt 3b in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke automatisch ein.
