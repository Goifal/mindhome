# Prompt 3: End-to-End Flow-Analyse

## Rolle

Du bist ein Elite-Software-Architekt mit tiefem Wissen in AsyncIO, FastAPI, Flask, LLM-Integration, Function Calling, Speech Processing und Smart Home (Home Assistant). Du kennst J.A.R.V.I.S. aus dem MCU als Goldstandard für einen kohärenten, koordinierten Assistenten.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–2 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier ein:
> - Kontext-Block aus Prompt 1 (Konflikt-Karte, besonders Konflikt F: Assistant ↔ Addon)
> - Kontext-Block aus Prompt 2 (Memory-Analyse, Root Cause, Memory-Flow)

---

## Aufgabe

Verfolge die **9 kritischen Pfade** Zeile für Zeile durch den Code. Für jeden Pfad:

1. Dokumentiere **exakt** welche Funktionen in welcher Reihenfolge aufgerufen werden
2. Finde **Bruchstellen** wo der Flow unterbrochen wird oder fehlschlägt
3. Finde **Kollisionen** wo sich Pfade gegenseitig stören

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

### Flow 8: Addon-Automation (NEU — KRITISCH)

```
Addon erkennt ein Event / Pattern / Zeitplan
  → addon/automation_engine.py oder addon/pattern_engine.py
    → addon/event_bus.py: Event verteilen
      → addon/domains/*.py: Aktion ausführen (z.B. Licht, Cover)
        → addon/ha_connection.py: HA-API-Call
```

**Prüfe besonders**:
- Läuft dieser Flow **komplett unabhängig** vom Assistant?
- Weiß der Assistant dass der Addon gerade eine Aktion ausführt?
- Kann der Addon eine Entity steuern die der Assistant gerade AUCH steuert?
- Nutzt der Addon dieselbe HA-Instanz? Gleiche Credentials?
- Gibt es Addon-Engines (z.B. `circadian.py`, `cover_control.py`) die **dasselbe** tun wie Assistant-Module (`light_engine.py`, `cover_config.py`)?

---

### Flow 9: Domain-Assistenten (NEU)

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
- `workshop_library.py` / `workshop_generator.py` → DIY-Projekte

**Prüfe besonders**:
- Werden Domain-Assistenten **korrekt geroutet**? Wer entscheidet welcher Assistent?
- Gehen sie durch die **gleiche** Persönlichkeits-Pipeline?
- Haben sie Zugriff auf **Memory** und **Kontext**?
- Oder sind es isolierte Module die den Jarvis-Charakter verlieren?

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

### 1. Flow-Dokumentation

Für jeden der 9 Flows:
```
### Flow X: Name
**Status**: ✅ Funktioniert / ⚠️ Teilweise / ❌ Kaputt / 🔍 Nicht verbunden

**Ablauf**:
1. [Funktion] in [datei.py:zeile] → [was passiert]
2. [Funktion] in [datei.py:zeile] → [was passiert]
...

**Bruchstellen**:
- [datei.py:zeile]: Beschreibung des Problems

**Kollisionen mit anderen Flows**:
- Flow X kollidiert mit Flow Y bei [Beschreibung]
```

### 2. Kollisions-Tabelle (ausgefüllt)

### 3. Service-Interaktions-Analyse

Wie kommunizieren die drei Services (Assistant, Addon, Speech) in jedem Flow?

### 4. Kritische Findings

Top-5 Probleme, sortiert nach Impact, mit konkretem Fix-Vorschlag.

---

## Regeln

- Folge dem Code **Zeile für Zeile** — keine Annahmen
- Jede Aussage mit **Datei:Zeile** belegen
- **Alle 9 Flows** prüfen — die neuen (7, 8, 9) sind genauso wichtig
- Fokus auf **Bruchstellen und Kollisionen** — nicht auf Code-Stil
- Wenn ein Flow komplett fehlt (z.B. keine Queue): Dokumentiere es als Feature-Gap
- **Addon-Kollisionen** besonders beachten — das ist der blinde Fleck des Projekts
- MCU-Jarvis-Test: Würde sich der echte Jarvis so verhalten?

---

## ⚡ Übergabe an Prompt 4

Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block** für Prompt 4:

```
## KONTEXT AUS PROMPT 3: Flow-Analyse

### Flow-Status-Übersicht
| Flow | Status | Kritischste Bruchstelle |
|---|---|---|
| 1: Sprach-Input → Antwort | ✅/⚠️/❌ | ... |
| ... | ... | ... |

### Top-Bruchstellen
[Die 5 kritischsten Bruchstellen mit Datei:Zeile]

### Kollisionen
[Die kritischsten Kollisionen zwischen Flows]

### Feature-Gaps
[Flows/Features die komplett fehlen]
```

**Wenn du Prompt 4 in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke (Prompt 1 + 2 + 3) automatisch ein.
