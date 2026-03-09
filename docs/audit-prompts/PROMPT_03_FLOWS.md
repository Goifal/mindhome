# Prompt 3: End-to-End Flow-Analyse

## Rolle

Du bist ein Elite-Software-Architekt mit tiefem Wissen in AsyncIO, FastAPI, LLM-Integration, Function Calling und Smart Home (Home Assistant). Du kennst J.A.R.V.I.S. aus dem MCU als Goldstandard für einen kohärenten, koordinierten Assistenten.

---

## Kontext aus vorherigen Prompts

> **[HIER die Konflikt-Karte aus Prompt 1 einfügen]**

> **[HIER die Memory-Analyse aus Prompt 2 einfügen]**

---

## Aufgabe

Verfolge die 6 kritischen Pfade **Zeile für Zeile** durch den Code. Für jeden Pfad:

1. Dokumentiere **exakt** welche Funktionen in welcher Reihenfolge aufgerufen werden
2. Finde **Bruchstellen** wo der Flow unterbrochen wird oder fehlschlägt
3. Finde **Kollisionen** wo sich Pfade gegenseitig stören

---

### Flow 1: Sprach-Input → Antwort (Hauptpfad)

Der wichtigste Flow. Verfolge komplett:

```
HTTP Request / WebSocket Nachricht
  → main.py: Welcher Endpoint? Welche Funktion?
    → brain.py: Wie wird der Request verarbeitet?
      → context_builder.py: Was landet im System-Prompt?
        → personality.py: Wie wird die Persönlichkeit eingebaut?
          → mood_detector.py: Wird die Stimmung erkannt?
      → memory.py: Werden Erinnerungen geladen? (Ergebnis aus Prompt 2)
      → ollama_client.py / model_router.py: Wie wird das LLM aufgerufen?
        → function_calling.py: Werden Tool-Calls erkannt und ausgeführt?
          → Home Assistant API: Werden Aktionen korrekt ausgeführt?
        → Zweiter LLM-Call nach Tool-Execution?
      → TTS: Wie wird die Antwort gesprochen?
    → Response zurück an den Client
```

**Prüfe besonders**:
- Wird die Conversation History als Messages-Array übergeben? Oder nur der letzte Turn?
- Wird Function Calling korrekt als Tool-Use-Loop implementiert (Call → Execute → Result → LLM)?
- Werden Fehler bei HA-API-Calls abgefangen und dem User kommuniziert?
- Timeout-Handling: Was passiert wenn das LLM oder HA nicht antwortet?

---

### Flow 2: Proaktive Benachrichtigung

```
Home Assistant Event (z.B. Tür offen, Gerät fertig)
  → proactive.py: Wie wird das Event empfangen?
    → Prioritäts-Bewertung: Ist es wichtig genug?
      → brain.py: Wie wird die Nachricht generiert?
        → TTS: Wie wird sie ausgesprochen?
```

**Prüfe besonders**:
- Was passiert wenn der User **gerade spricht**? Wird unterbrochen? Gequeued? Ignoriert?
- Was passiert wenn **mehrere Events gleichzeitig** eintreffen?
- Gibt es ein Cooldown / Rate Limiting um Spam zu verhindern?
- Nutzt proactive.py den gleichen Persönlichkeits-Pfad wie normale Antworten?

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
Muster erkannt (anticipation.py / learning_observer.py)
  → autonomy.py: Darf gehandelt werden? (Autonomie-Level)
    → action_planner.py oder function_calling.py: Aktion ausführen
      → Home Assistant API
        → Benachrichtigung an User?
```

**Prüfe besonders**:
- Wer **autorisiert** autonome Aktionen? Gibt es Sicherheits-Limits?
- Kann eine autonome Aktion eine **User-Aktion überschreiben**?
- Werden autonome Aktionen **geloggt** und dem User **kommuniziert**?
- Funktioniert das Autonomie-Level-System (1–5) wirklich?

---

### Flow 5: Persönlichkeits-Pipeline

```
Antwort-Text vom LLM
  → personality.py: Welche Anpassungen?
    → Sarkasmus-Level (1-5)
    → Mood-basierte Anpassung
    → Easter Egg Check
    → Opinion Injection
    → Formality Level
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
      → context_builder.py: Erinnerung in Prompt einbauen
        → LLM: Antwort mit Erinnerungs-Kontext
```

**Prüfe besonders** (ergänzt Prompt 2):
- Wird eine Memory-Query **überhaupt als solche erkannt**?
- Oder wird sie wie eine normale Frage behandelt?
- Gibt es einen speziellen Code-Pfad für Erinnerungs-Fragen?

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

---

## Output-Format

### 1. Flow-Dokumentation

Für jeden der 6 Flows:
```
### Flow X: Name
**Status**: ✅ Funktioniert / ⚠️ Teilweise / ❌ Kaputt

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

### 3. Kritische Findings

Top-5 Probleme, sortiert nach Impact, mit konkretem Fix-Vorschlag.

---

## Regeln

- Folge dem Code **Zeile für Zeile** — keine Annahmen
- Jede Aussage mit **Datei:Zeile** belegen
- Fokus auf **Bruchstellen und Kollisionen** — nicht auf Code-Stil
- Wenn ein Flow komplett fehlt (z.B. keine Queue): Dokumentiere es als Feature-Gap
- MCU-Jarvis-Test: Würde sich der echte Jarvis so verhalten?
