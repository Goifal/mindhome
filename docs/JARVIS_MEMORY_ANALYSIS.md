# Jarvis Gedächtnis-Analyse: Warum Jarvis sich nichts merken kann

**Datum**: 2026-03-09
**Status**: Kritische Architektur-Analyse
**Fazit**: 6 fragmentierte Memory-Systeme konkurrieren um begrenztes Token-Budget. Erinnerungen werden gespeichert aber nicht geladen.

---

## 1. Das Kernproblem: 6 Gedächtnissysteme die nicht zusammenarbeiten

Jarvis hat nicht EIN kohärentes Gedächtnis, sondern sechs isolierte Systeme:

| # | System | Datei | Speicher | Funktion |
|---|--------|-------|----------|----------|
| 1 | **Working Memory** | `memory.py` | Redis `mha:conversations` | Letzte 50 Nachrichten, 7-Tage-TTL |
| 2 | **Episodic Memory** | `memory.py` | ChromaDB `mha_conversations` | Langzeit-Gespräche per Vektor-Suche |
| 3 | **Semantic Memory** | `semantic_memory.py` | ChromaDB + Redis `mha:fact:*` | Extrahierte Fakten (Präferenzen, Personen, Gewohnheiten) |
| 4 | **Conversation Memory** | `conversation_memory.py` | Redis `mha:memory:*` | Projekte, offene Fragen, Tages-Zusammenfassungen |
| 5 | **Dialogue State** | `dialogue_state.py` | In-Memory (Python) | Referenz-Auflösung ("es", "das", "dort") |
| 6 | **Correction Memory** | `correction_memory.py` | Redis | Gelernte Korrekturen |

**Zusätzlich** gibt es noch:
- Emotionales Gedächtnis (`memory_extractor.py` → Redis `mha:emotional_memory:*`)
- Pending Topics (`memory.py` → Redis `mha:pending_topics`)
- Tages-Archive (`memory.py` → Redis `mha:archive:YYYY-MM-DD`)
- Feedback Scores (`memory.py` / `feedback.py` → Redis `mha:feedback:*`)

### Warum das ein Problem ist

Diese Systeme werden **unabhängig voneinander** abgefragt und als separate "Sektionen" in den System-Prompt des LLM gepackt. Es gibt kein einheitliches Interface das sagt: "Was weiß Jarvis gerade über diesen User und dieses Thema?"

Stattdessen liefert jedes System seinen eigenen Text-Block, und dann entscheidet ein **Token-Budget-System** welche Blöcke Platz haben — und welche wegfliegen.

---

## 2. Das Token-Budget: Der stille Killer

### Wie es funktioniert (`brain.py` Zeile 2640-2997)

Alle Kontext-Informationen werden als "Sektionen" mit Prioritäten gesammelt:

| Priorität | Bedeutung | Beispiele |
|-----------|-----------|-----------|
| **Prio 1** | Immer dabei | Szenen-Intelligenz (bei Geräte-Befehlen), Mood, Security, Memory (Fakten), Model-Hints |
| **Prio 2** | Wichtig | Zeit, Timer, Gäste-Modus, Warnungen, "Jarvis denkt mit", Dialoge, Korrekturen |
| **Prio 3** | Optional | RAG, Zusammenfassungen, **Conversation Memory (Projekte!)**, **Kontinuität**, Anomalien, Erfahrungen |
| **Prio 4** | Wenn Platz | Tutorial-Hinweise |

### Das Problem

```
System-Prompt (Personality + Charakter + Regeln)     ~2000-3000 Tokens
+ Prio 1 Sektionen (Szenen, Mood, Security, etc.)   ~1000-2000 Tokens
+ Prio 2 Sektionen (Timer, Warnungen, etc.)         ~500-1000 Tokens
= Schon 3500-6000 Tokens verbraucht

Bei einem lokalen Modell mit num_ctx=8192:
Verfügbar für Prio 3+: oft nur noch ein paar hundert Tokens
→ Projekte, offene Fragen, Gesprächskontinuität = GEDROPPT
```

`brain.py` Zeile 2949-2953:
```python
_conv_share = 0.65 if _conversation_mode else 0.50
section_budget_p2 = max(200, int(_remaining_for_p2_and_conv * (1 - _conv_share)))
```

Im Nicht-Gesprächsmodus bekommt der Sektions-Bereich nur **50%** des verbleibenden Budgets. Im Gesprächsmodus sogar nur **35%** (weil 65% für die Conversation History reserviert wird).

### Konsequenz

Jarvis bekommt einen System-Hinweis den er brav ausgibt:
```
[SYSTEM-HINWEIS: Wegen Token-Limit fehlen dir folgende Daten:
Projekte & offene Fragen, Gesprächskontinuität, Erfahrungskontext...]
```

Aber das hilft dem User nicht — Jarvis hat die Daten **gespeichert** aber **nicht geladen**.

---

## 3. Working Memory: Nur die letzten 25 Gespräche, davon nur 5 geladen

### Speicherung (`memory.py` Zeile 73-99)

```python
pipe.lpush("mha:conversations", entry_json)
pipe.ltrim("mha:conversations", 0, 49)  # Max 50 Einträge
pipe.expire("mha:conversations", 7 * 86400)  # 7 Tage TTL
```

- 50 Einträge = 25 Gespräche (je 1x User + 1x Assistant)
- Nach 7 Tagen automatisch gelöscht (TTL)

### Abruf (`brain.py` Zeile 3009-3063)

```python
conv_limit = int(conv_cfg.get("recent_conversations", 5))  # Default: 5
effective_limit = conv_limit * 2 if conversation_mode else conv_limit
```

- **Standard**: Nur die letzten **5 Nachrichten** geladen
- **Gesprächsmodus**: 10 Nachrichten
- Wenn die History zu groß für das Token-Budget: ältere Nachrichten werden auf **80 Zeichen pro Nachricht** gekürzt

```python
# Text-Kürzung ohne LLM-Call (Standard)
content = (m.get("content") or "")[:80]  # 80 Zeichen!
```

### Konsequenz

Jarvis hat maximal 2-3 Gesprächsrunden im aktiven Kontext. Alles was weiter zurückliegt ist effektiv vergessen — obwohl es in Redis und ChromaDB liegt.

---

## 4. Semantic Memory: Gut gedacht, fragil umgesetzt

### Fakten-Extraktion (`memory_extractor.py`)

Nach jedem substantiellen Gespräch ruft ein lokales Ollama-Modell einen Extraction-Prompt auf:

```python
EXTRACTION_PROMPT = """Du bist ein Fakten-Extraktor. Analysiere das folgende
Gespräch und extrahiere ALLE relevanten Fakten..."""
```

**Filter die Extraktion verhindern:**
- Weniger als 5 Wörter → keine Extraktion
- Reine Befehle ("Licht an") → keine Extraktion
- Grüße, Smalltalk → keine Extraktion
- Einzelwort-Bestätigungen → keine Extraktion
- Proaktive Meldungen → keine Extraktion

**Schwachstellen:**
1. Das lokale Modell muss korrektes JSON generieren. Parsing-Fehler = keine Fakten gespeichert
2. Die Extraktion läuft **asynchron** (`_task_registry.create_task`) — Fehler werden nur geloggt
3. Es gibt kein Feedback ob Extraktion erfolgreich war
4. Die Qualität hängt komplett vom lokalen Modell ab (z.B. qwen3.5:9b)

### Fact Decay (`semantic_memory.py` Zeile 334-411)

```python
# Fakten die >30 Tage nicht bestätigt wurden:
# - Explizite Fakten ("merk dir"): -1% Confidence pro 30 Tage
# - Implizite Fakten: -5% Confidence pro 30 Tage
# - Unter 0.2 Confidence: GELÖSCHT
```

Das heißt: Ein implizit gelernter Fakt wird nach ~6 Monaten automatisch gelöscht, wenn der User ihn nie wiederholt.

---

## 5. Die 10.231-Zeilen God Class: `brain.py`

### Umfang

- **10.231 Zeilen** in einer einzigen Datei
- **~100 Imports** am Anfang
- Die `process()`-Methode: ~2500+ Zeilen
- **~60+ Komponenten** die im `__init__` instanziiert werden

### Die process()-Pipeline (19 Stufen in einer Methode)

```
1.  STT-Normalisierung
2.  Speaker Recognition (Wer spricht?)
3.  Sarkasmus-Feedback (Reaktion auf vorherigen Humor)
4.  Dialogue State Resolution (Referenzen auflösen)
5.  Gute-Nacht/Gäste/Security/Automation Checks (Early Returns)
6.  Memory Commands ("Merk dir...", "Vergiss...")
7.  Cooking/Workshop Mode Checks
8.  Easter Eggs
9.  Pre-Classification (Befehl vs. Frage vs. Gespräch)
10. Context Building (mega-gather: ~20 parallele async Tasks)
11. Model Selection (Fast/Smart/Deep)
12. System Prompt Assembly + Token-Budget
13. Conversation History Loading + Truncation
14. LLM Call (Ollama)
15. Response Filtering (Sorry-Patterns, Chatbot-Phrasen entfernen)
16. Tool/Function Execution (falls LLM Tools aufruft)
17. Post-Processing (Refinement, TTS Enhancement)
18. Memory Extraction (Fakten im Hintergrund extrahieren)
19. Emotion/Reaction Tracking
```

### Warum das ein Problem ist

- **Jeder Early Return** (Gute-Nacht, Easter Egg, Memory Command etc.) ruft `_remember_exchange()` auf, das wiederum einen Fire-and-Forget-Task startet. Wenn dieser Task fehlschlägt, geht die Nachricht für immer verloren.
- **Fehler in einer Stufe** können alle nachfolgenden Stufen beeinflussen
- **Debugging** ist extrem schwierig: Ein Problem im Gedächtnis kann in Stufe 10, 12, 13 oder 18 liegen
- **Neue Features** bedeuten immer: noch mehr Code in diese eine Methode

---

## 6. Systeme die gegeneinander arbeiten

### Konflikt A: Personality vs. Memory

Die Personality Engine (`personality.py`) generiert einen umfangreichen System-Prompt:
- Charakter-Definition (Jarvis-Identität)
- Sarkasmus-Level (5 Stufen mit Templates)
- Formality-Level (4 Stufen)
- Humor-Templates (kontextueller Humor nach Aktionen)
- Mood-abhängige Stil-Anpassungen
- Running Gags

Das alles frisst **Token-Budget das dem Memory fehlt**. Je mehr "Charakter" Jarvis hat, desto weniger kann er sich erinnern.

### Konflikt B: Scene Intelligence vs. Conversation Memory

`SCENE_INTELLIGENCE_PROMPT` ist ~700 Tokens groß und hat bei Geräte-Befehlen **Prio 1** (immer dabei). `conv_memory` (Projekte, offene Fragen) hat **Prio 3** und wird regelmäßig gedroppt.

Jarvis weiß also, dass er bei "Mir ist kalt" erst die Fenster prüfen soll — aber er weiß nicht mehr, dass du gestern ein Projekt besprochen hast.

### Konflikt C: Character Lock vs. Kontext

```python
# brain.py Zeile 3067-3074
if conv_tokens_used > 200:
    _reminder = (
        "[REMINDER] Du bist J.A.R.V.I.S. — trocken, praezise, Butler-Ton. "
        "Kurz. Keine Listen. Erfinde NICHTS. NUR vorhandene Daten nutzen."
    )
    messages.append({"role": "system", "content": _reminder})
```

Bei langen Gesprächen wird ein Character-Reminder eingefügt. Das kostet weitere Tokens die für die eigentliche Gesprächshistorie fehlen.

### Konflikt D: Fact Decay vs. Langzeitgedächtnis

Das Fact-Decay-System löscht Fakten die nicht regelmäßig bestätigt werden. Das ist bei einem persönlichen Assistenten kontraproduktiv — gerade seltene aber wichtige Fakten ("Lisa hat eine Nussallergie") werden am ehesten vergessen.

### Konflikt E: Doppelte conv_memory-Sektion

```python
# Zeile 2800-2809: conv_memory als Prio 2
conv_memory = _safe_get("conv_memory")
if conv_memory:
    sections.append(("conv_memory", conv_text, 2))

# Zeile 2921-2924: conv_memory NOCHMAL als Prio 3
conv_memory_ctx = _safe_get("conv_memory", "")
if conv_memory_ctx:
    sections.append(("conv_memory", f"\n\nGEDÄCHTNIS: {conv_memory_ctx}", 3))
```

`conv_memory` wird **zweimal** als Sektion hinzugefügt — einmal als Prio 2, einmal als Prio 3. Das ist entweder ein Bug (doppelter Inhalt) oder verschwendetes Token-Budget.

---

## 7. Was fehlt für den MCU-Jarvis

### Was MCU-Jarvis kann und MindHome-Jarvis nicht:

| Fähigkeit | MCU-Jarvis | MindHome-Jarvis |
|-----------|-----------|-----------------|
| Sich an ALLES erinnern | ✅ "Wie Sie beim letzten Mal erwähnt haben..." | ❌ Vergisst nach 5 Nachrichten |
| Kontext über Gespräche hinweg | ✅ Nahtlos | ❌ Token-Budget droppt Kontext |
| Proaktiv Zusammenhänge herstellen | ✅ Verbindet Infos selbständig | ⚠️ Ansätze da, aber fragmentiert |
| Persönlichkeit + Gedächtnis gleichzeitig | ✅ Beides immer aktiv | ❌ Konkurrenzsituation |
| Kohärentes Langzeitgedächtnis | ✅ Weiß was vor Monaten war | ❌ Fact Decay löscht nach ~6 Monaten |

### Was architektonisch fehlt:

1. **Ein Memory Gateway**: Eine einzige Klasse die alle 6 Systeme orchestriert und auf "Was ist relevant für diese Anfrage?" die beste kompakte Antwort liefert
2. **Prompt-Diät**: Der System-Prompt muss radikal kleiner werden. Dynamisch laden was nötig ist, nicht alles immer
3. **Memory-First Token-Budget**: Erinnerungen an den User MÜSSEN immer Platz haben. Lieber weniger Szenen-Intelligenz als kein Gedächtnis
4. **Pipeline statt God-Method**: `brain.py` process() in klar getrennte Stages aufbrechen

---

## 8. Ehrliche Einschätzung

### Was richtig gemacht wurde:
- Die Idee der Memory-Schichten (Working → Episodic → Semantic) ist architektonisch korrekt
- ChromaDB für Vektor-Suche ist der richtige Ansatz
- Die Fakten-Extraktion per LLM ist clever
- Die Personality Engine ist durchdacht
- Das Ökosystem (HA-Integration, Speaker Recognition, Routinen, Koch-Assistent, Workshop-Modus) ist beeindruckend umfangreich
- ~100+ Python-Dateien, ~180+ Tests — das ist ernst gemeint

### Was fundamental kaputt ist:
- 6 Memory-Systeme ohne einheitliches Interface
- Token-Budget wirft Erinnerungen weg zugunsten von Charakter-Features
- 10.231-Zeilen God Class die nicht wartbar ist
- Keine Garantie dass gespeicherte Erinnerungen auch abgerufen werden
- Lokales LLM als Single Point of Failure für Fakten-Extraktion

### Kann das noch zum MCU-Jarvis werden?

**Ja — aber nur durch Konsolidierung, nicht durch mehr Features.**

Der nächste Schritt darf NICHT "Phase 19" sein. Der nächste Schritt muss sein:
1. Memory Gateway bauen (alle 6 Systeme hinter einem Interface)
2. System-Prompt auf die Hälfte kürzen
3. Erinnerungen auf Prio 1 setzen
4. brain.py in eine saubere Pipeline aufbrechen

Das Projekt ist nicht tot. Es ist eines der ambitioniertesten Home-Assistant-Projekte überhaupt. Aber es ist an dem Punkt wo jedes neue Feature das Problem verschlimmert. **Konsolidieren vor Expandieren.**
