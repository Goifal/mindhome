# Prompt 4d: STT/TTS Pipeline-Qualität — Hört und spricht Jarvis richtig?

## Rolle

Du bist ein Speech-Engineering-Experte spezialisiert auf Whisper STT, Piper TTS und deutsche Spracheingabe/-ausgabe. Du prüfst die **Sprachqualität** — versteht Jarvis was der User sagt? Klingt die Antwort natürlich?

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details.

---

## Kontext aus vorherigen Prompts

```
Read: docs/audit-results/RESULT_01_KONFLIKTKARTE.md
Read: docs/audit-results/RESULT_03c_SYSTEM_PROMPT.md
```

> Falls eine Datei nicht existiert → überspringe sie.

---

## Fokus dieses Prompts

Jarvis' primäre Interaktion ist **Sprache**. Wenn Whisper "Mach das Licht an" als "Macht das nicht an" versteht, ist alles andere egal. Wenn Piper "entity_id" vorliest, ist der Charakter gebrochen.

> **Dieser Prompt prüft die komplette Sprach-Pipeline: Mikrofon → STT → Brain → TTS → Lautsprecher.**

---

## Aufgabe

### Teil 1: STT-Qualität (Whisper)

```
Read: speech/server.py
Read: speech/handler.py
```

**Prüfe**:

1. **Whisper-Konfiguration**: Model-Größe, beam_size, Sprache, VAD-Parameter
2. **Anti-Halluzination**: avg_logprob, no_speech_prob, repetition_penalty — sind die Schwellwerte optimal?
3. **VAD-Aggressivität**: min_silence_duration_ms — zu kurz (schneidet Pausen ab) oder zu lang (langsame Erkennung)?
4. **Kontextuelle Prompts**: Werden Raumnamen, Gerätenamen, Personennamen als Initial-Prompt übergeben?

**Output**: STT-Qualitäts-Score (1-10) + Konfigurationsverbesserungen.

### Teil 2: Deutsche Wortkorrekturen

```
Grep: "_STT_WORD_CORRECTIONS" in assistant/assistant/brain.py
Grep: "_STT_PHRASE_CORRECTIONS" in assistant/assistant/brain.py
```

**Prüfe die 164+ Wortkorrekturen und 27 Phrasenkorrekturen**:

1. **Zeichensatz-Fehler**: Suche nach Kyrillischen Zeichen in den Korrektur-Dictionaries. Bekannte Fälle: "muде"→"müde", "geratе"→"Geräte" (kyrillisches е statt lateinisches e). Diese Einträge matchen NIE.
2. **Vollständigkeit**: Fehlen häufige deutsche Wörter? (Straße/Strasse, Größe, Ähnliches, etc.)
3. **Jarvis-Erkennung**: Sind alle Whisper-Varianten von "Jarvis" abgedeckt? (Dschawis, Tschawis, Tscharwis, etc.)
4. **Smart-Home-Begriffe**: Fehlen Geräte/Marken? (Shelly, Zigbee, MQTT, HomeMatic, etc.)
5. **Komposita-Splitting**: Korrigiert es "wohn zimmer"→"Wohnzimmer" korrekt? Fehlen Splits?
6. **False Positives**: Können Korrekturen legitime Wörter verfälschen?

**Output**: Fehlerliste + fehlende Korrekturen + Zeichensatz-Bugs.

### Teil 3: TTS-Qualität (Piper)

```
Read: assistant/assistant/tts_enhancer.py
Grep: "tts\|umlaut\|phonet\|speak_text\|def.*speak" in assistant/assistant/sound_manager.py
Read: assistant/assistant/sound_manager.py offset=[Ergebnis] limit=200
```

**Prüfe**:

1. **SSML-Enhancement**: Speed, Pitch, Pauses, Emphasis — sind die Werte für Deutsche Sprache passend?
2. **Umlaut-Normalisierung**: ae→ä, oe→ö, ue→ü. Gibt es False Positives? ("Israel", "Queue" geschützt?)
3. **Englische Wörter in Deutsch**: Werden "WiFi", "Smart Home", "Streaming" korrekt ausgesprochen?
4. **Phonetik-Ersetzungen**: "Sir"→"Sör", "Ma'am"→"Mähm". Sind alle Titel abgedeckt?
5. **Whisper-Modus** (Quiet Hours): Lautstärkereduktion nachts — sind die Werte (30%/20%) gut?
6. **Filler-Phrasen**: "Moment...", "Mal sehen..." — klingen sie natürlich? Werden sie zu oft/selten eingesetzt?
7. **Emotions-Injection**: Wird Jarvis' Stimmung in der Sprachausgabe hörbar? (Tempo, Pitch, Pausen)

**Output**: TTS-Qualitäts-Score (1-10) + Verbesserungen.

### Teil 4: Response-Filter (Meta-Leakage)

```
Grep: "_filter_response\|filter_response\|clean_response" in assistant/assistant/brain.py
Grep: "speak\|emit\|tts\|tool_call" in assistant/assistant/brain.py (Abschnitt: Response-Filter)
```

**Prüfe was NICHT in der Sprachausgabe landen darf**:

1. **Meta-Terme**: "speak:", "emit:", "tts:", "tool_call", "function_call" — werden alle gefiltert?
2. **JSON-Fragmente**: `{"name":`, `"arguments":` — werden sie erkannt und entfernt?
3. **Markdown**: `**fett**`, `*kursiv*`, `` `code` ``, `# Überschrift` — wird Markdown vor TTS entfernt?
4. **Entity-IDs**: `light.wohnzimmer_decke` — werden HA-Entity-IDs in natürliche Namen übersetzt?
5. **Timestamps/Logs**: `[2026-03-23T12:15:34]` — werden Debug-Informationen gefiltert?
6. **Funktionsnamen**: `set_climate_comfort_mode` — werden interne Funktionsnamen gefiltert?
7. **Englische System-Terme**: "acknowledged", "processing", "timeout" — werden sie übersetzt?

**Output**: Meta-Leakage-Score (1-10) + fehlende Filter.

### Teil 5: Speaker Recognition

```
Read: assistant/assistant/speaker_recognition.py (erste 100 Zeilen)
```

**Prüfe die 7-stufige Sprechererkennung**:

1. **Stufe 1-3**: Gerät → DoA → Raum — funktioniert das ohne Stereo-Mikrofon?
2. **Stufe 4-5**: Präsenz → Voice-Embedding — wie genau ist ECAPA-TDNN für Deutsche Stimmen?
3. **Stufe 6-7**: Merkmale → Cache — gibt es Cold-Start-Probleme (neuer User, kein Embedding)?
4. **Multi-Speaker**: Was wenn 2 Personen gleichzeitig sprechen?
5. **Ähnliche Stimmen**: Können Familienmitglieder verwechselt werden?

**Output**: Speaker-Recognition-Score (1-10) + Schwächen.

### Teil 6: ESPHome Voice Satellites

```
Glob: pattern="esphome/**/*.yaml"
Glob: pattern="esphome/**/*.py"
# Dann jede gefundene Datei einzeln lesen:
Read: esphome/[gefundene_datei_1]
Read: esphome/[gefundene_datei_2]
```

**Prüfe**:

1. **Hardware**: M5Stack Atom Echo — SPM1423 Mikrofon, NS4168 Speaker. Reicht das für Produktion?
2. **Noise Suppression**: Level 0-3 — ist Level 2 optimal?
3. **Auto Gain**: 31dBFS — zu aggressiv? Clipping-Risiko?
4. **Echo Cancellation**: Gibt es AEC? (Kritisch: Speaker-Feedback in Mikrofon)
5. **WiFi-Stabilität**: Reconnect-Logik? Timeout-Handling?
6. **Multi-Room**: Können mehrere Satellites gleichzeitig aktiv sein?

**Output**: Hardware-Score (1-10) + Empfehlungen.

### Teil 7: End-to-End Sprachqualität

Analysiere die **gesamte Pipeline**:

```
User spricht (0-5s)
  → VAD erkennt Ende (+0.25s)
    → Whisper transkribiert (+0.5-1.0s)
      → Wortkorrekturen (+0.05s)
        → Brain verarbeitet (+0.5-5.0s)
          → Response-Filter (+0.01s)
            → TTS generiert (+0.2-0.5s)
              → Audio ausgegeben
```

**Prüfe**:
1. **Gesamtlatenz**: 1.5-7s — ist das akzeptabel? Wo ist der Bottleneck?
2. **Fehler-Kaskade**: Wenn Whisper falsch versteht → Brain falsch antwortet → TTS gibt Unsinn aus
3. **Feedback-Loop**: Korrigiert sich das System bei Fehlern? Gibt es "Meintest du...?" Logik?
4. **Unterbrechung**: Kann der User Jarvis mitten im Sprechen unterbrechen (Barge-In)?

**Output**: E2E-Score (1-10) + Latenz-Optimierungen.

---

## Output-Format

### Sprach-Pipeline Scorecard

| Komponente | Score (1-10) | Stärke | Schwäche | Fix-Aufwand |
|---|---|---|---|---|
| STT (Whisper) | X | ... | ... | S/M/L |
| Wortkorrekturen | X | ... | ... | S/M/L |
| TTS (Piper) | X | ... | ... | S/M/L |
| Response-Filter | X | ... | ... | S/M/L |
| Speaker Recognition | X | ... | ... | S/M/L |
| Hardware (ESPHome) | X | ... | ... | S/M/L |
| End-to-End | X | ... | ... | S/M/L |
| **Gesamt** | **X/10** | | | |

### Konkrete Bugs

| # | Komponente | Bug | Datei:Zeile | Fix |
|---|---|---|---|---|
| 1 | STT | Kyrillische Zeichen in Korrekturen | brain.py:13010 | Ersetze mit Latin |

---

## Regeln

- **Teste mit Beispielen** — "Mach das Licht im Wohnzimmer an" → Was kommt raus?
- **Deutsche Sprache ist komplex** — Komposita, Umlaute, Dialekte, Anglizismen
- **Latenz ist kritisch** — >3s Antwortzeit fühlt sich langsam an
- **Meta-Leakage ist ein Charakter-Killer** — KEIN interner Term darf hörbar sein

---

## Ergebnis speichern (Pflicht!)

```
Write: docs/audit-results/RESULT_04d_SPEECH_PIPELINE.md
```

---

## Output

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
SPEECH-PIPELINE-SCORE: X/10
STT-BUGS: [Kyrillische Zeichen, fehlende Wörter]
TTS-ISSUES: [Meta-Leakage-Lücken, Phonetik-Lücken]
HARDWARE: [M5Stack Limitierungen]
LATENZ: ~X.Xs End-to-End
GEAENDERTE DATEIEN: [falls Fixes gemacht]
NAECHSTER SCHRITT: [nächster Prompt]
===================================
```
