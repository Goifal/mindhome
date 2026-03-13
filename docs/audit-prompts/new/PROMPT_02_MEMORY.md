# Prompt 2: Memory-System — Analyse + Reparatur der 6 Amnesie-Bugs

## Rolle

Du bist ein Elite-Software-Ingenieur spezialisiert auf Memory-Systeme (Redis, ChromaDB, Python AsyncIO) in Conversational AI. Du analysierst und fixst **in einem Durchgang** — Read -> Grep -> Edit -> Verify fuer jeden Bug. Kein separater Analyse-Pass, kein separater Fix-Pass. Alles in einer Session.

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## Arbeitsumgebung

- Repository: `/home/user/mindhome/`
- Assistant-Code: `assistant/assistant/`
- Hauptdateien fuer dieses Prompt:
  - `assistant/assistant/brain.py` (10.000+ Zeilen — Read mit offset!)
  - `assistant/assistant/memory.py`
  - `assistant/assistant/semantic_memory.py`
  - `assistant/assistant/conversation_memory.py`
  - `assistant/assistant/memory_extractor.py`
  - `assistant/assistant/context_builder.py`

---

## Aufgabe

Jarvis hat **komplette Amnesie**. Die Root Cause ist identifiziert — 6 konkrete Bugs verhindern dass das Memory-System funktioniert. Deine Aufgabe: **Alle 6 Bugs fixen**. Read -> Grep -> Edit -> Verify fuer jeden einzelnen.

### Root-Cause-Zusammenfassung

```
1. get_recent_conversations(limit=3) — nur 3 letzte Konversationen als Kontext
2. Semantische Fakten werden NUR geladen wenn intent_type == "memory"
3. _build_memory_context() wird nur aufgerufen wenn relevant_facts/person_facts bereits gefuellt
4. 3 separate Memory-Systeme (Redis, ChromaDB search_memories, SemanticMemory search_facts) werden NICHT gemeinsam abgefragt
5. DOPPELTER Wort-Filter: brain.py (>3 Woerter) UND memory_extractor.py (>=5 Woerter) — Fakten werden nie gespeichert
6. conversation_memory hat Prioritaet 3 (brain.py:2973) — wird bei Token-Budget-Knappheit GEDROPPT
```

**Ergebnis**: User sagt "Meine Frau heisst Lisa" → 5 Nachrichten spaeter fragt "Wie heisst meine Frau?" → Jarvis: "Das weiss ich leider nicht."

---

## DIE 6 BUGS — Analyse + Fix

### Arbeitsweise pro Bug

```
1. READ  — Datei lesen (bei brain.py mit offset= fuer die richtige Stelle)
2. GREP  — Alle Aufrufer/Abhaengigkeiten finden
3. EDIT  — Fix direkt in die Datei schreiben
4. VERIFY — Nochmal Read + Grep um den Fix zu pruefen
```

---

### BUG 1: Conversation-History zu kurz (KRITISCH)

**Problem**: `brain.py` ruft `get_recent_conversations(limit=3)` auf — nur die letzten 3 Nachrichten landen im Kontext. Alles was 5 Nachrichten zurueckliegt ist fuer Jarvis unsichtbar.

**Dateien und Zeilen**:
- `assistant/assistant/brain.py` Zeile ~3080
- `assistant/assistant/brain.py` Zeile ~2442

**Fix**:
```python
# VORHER:
recent = await self.memory.get_recent_conversations(limit=3)
# NACHHER:
recent = await self.memory.get_recent_conversations(limit=10)
```

**Methodik**:
```
Schritt 1 — Alle Stellen finden:
  Grep: pattern="get_recent_conversations" path="assistant/assistant/brain.py" output_mode="content"

Schritt 2 — Jede Stelle lesen:
  Read: brain.py mit offset um die gefundenen Zeilen herum (±15 Zeilen)

Schritt 3 — Edit (BEIDE Stellen!):
  Edit: old_string="get_recent_conversations(limit=3)"
        new_string="get_recent_conversations(limit=10)"
        replace_all=true

Schritt 4 — Verify:
  Grep: pattern="get_recent_conversations" path="assistant/assistant/brain.py" output_mode="content"
  → Alle Stellen muessen jetzt limit=10 oder hoeher zeigen
```

**Warum 10?** Bei durchschnittlich 50-100 Tokens pro Nachricht sind 10 Nachrichten ca. 500-1000 Tokens — kein Problem fuer Qwen 3.5 mit 32k Context. 3 ist absurd wenig fuer Multi-Turn-Dialoge.

---

### BUG 2: Semantische Fakten NUR bei memory-Intent (KRITISCH)

**Problem**: In `brain.py` werden `search_facts()` und `get_facts_by_person()` in `_mega_tasks` NUR aufgerufen wenn `intent_type == "memory"`. Bei normalen Gespraechen (intent_type="question", "command", etc.) fehlen gespeicherte Fakten KOMPLETT im System-Prompt.

**Dateien und Zeilen**:
- `assistant/assistant/brain.py` Zeile ~2430 (_mega_tasks Erstellung)

**Fix**: Semantic-Facts-Tasks IMMER in _mega_tasks einfuegen (nicht hinter einer intent-Bedingung):
```python
# HINZUFUEGEN in _mega_tasks (UNCONDITIONAL — nicht hinter if intent_type == "memory"):
_mega_tasks.append(("person_facts", self.memory.semantic.get_facts_by_person(person or "")))
_mega_tasks.append(("relevant_facts", self.memory.semantic.search_facts(text, limit=5)))
```

Dann im Context-Build nach dem gather:
```python
person_facts = _safe_get("person_facts", [])
relevant_facts = _safe_get("relevant_facts", [])
```

**Methodik**:
```
Schritt 1 — _mega_tasks finden:
  Grep: pattern="_mega_tasks" path="assistant/assistant/brain.py" output_mode="content"

Schritt 2 — Aktuelle Struktur lesen (±30 Zeilen):
  Read: brain.py mit offset um die _mega_tasks-Definition

Schritt 3 — Pruefen ob search_facts hinter intent-Bedingung steht:
  Grep: pattern="search_facts|get_facts_by_person" path="assistant/assistant/brain.py" output_mode="content"

Schritt 4 — Tasks verschieben/hinzufuegen:
  Edit: Die zwei Tasks in den unbedingten Teil von _mega_tasks einfuegen

Schritt 5 — Verify:
  Grep: pattern="search_facts|get_facts_by_person" path="assistant/assistant/brain.py" output_mode="content"
  → Muessen AUSSERHALB der intent_type-Bedingung stehen
```

**ACHTUNG**: Pruefe ZUERST ob `context_builder.py` die Fakten evtl. schon immer laedt:
```
Grep: pattern="search_facts|get_facts_by_person" path="assistant/assistant/context_builder.py" output_mode="content"
```
Falls ja → BUG 2 ist moeglicherweise bereits in context_builder.py gefixt, aber in brain.py noch falsch. Beide Stellen pruefen!

---

### BUG 3: Memory-Intent-Erkennung zu eng

**Problem**: Nur das exakte Keyword "memory" loest Fakten-Laden aus. Viele natuerliche Erinnerungs-Fragen werden nicht als Memory-Intent erkannt.

**Fix**: Keywords erweitern — diese muessen ALLE als Memory-Intent gelten:
```python
memory_keywords = [
    "weisst du", "kennst du", "erinnerst du",
    "was habe ich", "wer bin ich", "wie heisse ich",
    "mein name", "mein geburtstag", "meine frau", "mein mann",
    "wo wohne ich", "was mag ich", "was habe ich gesagt",
    "letzte woche", "gestern", "remember", "erinnere dich",
]
```

**Methodik**:
```
Schritt 1 — Intent-Erkennung finden:
  Grep: pattern="intent.*memory|memory.*intent|intent_type.*memory" path="assistant/assistant/brain.py" output_mode="content"

Schritt 2 — Aktuelle Keywords lesen:
  Read: brain.py an der Stelle wo intent_type=="memory" bestimmt wird

Schritt 3 — Keywords erweitern:
  Edit: Fehlende Keywords zur bestehenden Liste hinzufuegen

Schritt 4 — Verify:
  Grep: pattern="weisst du|kennst du|erinnerst du|wie heisse ich|mein name|mein geburtstag|meine frau|mein mann|wo wohne ich" path="assistant/assistant/brain.py" output_mode="content"
  → Keywords muessen vorhanden sein
```

---

### BUG 4: Memory-Kontext im System-Prompt unklar

**Problem**: `_build_memory_context()` (brain.py:~5562) hat den Header "nutze mit Haltung wie ein alter Bekannter". Das LLM versteht nicht, dass das SEINE eigenen Erinnerungen sind.

**Fix**: Header aendern zu einem klaren, direktiven Text:
```python
header = (
    "DEIN GEDAECHTNIS — folgende Fakten WEISST DU ueber den User:\n"
    "Nutze sie AKTIV aber BEILAEUFIG. Nicht als Datenbank-Abfrage.\n"
)
```

**Methodik**:
```
Schritt 1 — Header finden:
  Grep: pattern="_build_memory_context|alter Bekannter|GEDAECHTNIS|GEDÄCHTNIS" path="assistant/assistant/brain.py" output_mode="content"

Schritt 2 — Aktuellen Header lesen:
  Read: brain.py mit offset um die _build_memory_context-Funktion

Schritt 3 — Header aendern:
  Edit: Alten Header-Text durch neuen ersetzen

Schritt 4 — Verify:
  Grep: pattern="GEDAECHTNIS|GEDÄCHTNIS" path="assistant/assistant/brain.py" output_mode="content"
  → Neuer Header muss vorhanden sein
```

---

### BUG 5: conversation_memory Prioritaet zu niedrig

**Problem**: `brain.py` Zeile ~2973 setzt `conv_memory_ext` auf Prioritaet 3. Bei knappem Token-Budget wird das gesamte Gedaechtnis WEGGELASSEN. Memory ist aber KERNFUNKTION — darf nie gedroppt werden.

**Fix**:
```python
# VORHER:
sections.append(("conv_memory_ext", f"\n\nGEDAECHTNIS: {conv_memory_ctx}", 3))
# NACHHER:
sections.append(("conv_memory_ext", f"\n\nGEDAECHTNIS: {conv_memory_ctx}", 1))
```

**Methodik**:
```
Schritt 1 — Priority-Zuweisung finden:
  Grep: pattern="conv_memory_ext" path="assistant/assistant/brain.py" output_mode="content"

Schritt 2 — Stelle lesen:
  Read: brain.py mit offset um die gefundene Zeile (±15 Zeilen)

Schritt 3 — Priority aendern:
  Edit: Prioritaet von 3 auf 1 aendern

Schritt 4 — Verify:
  Grep: pattern="conv_memory_ext" path="assistant/assistant/brain.py" output_mode="content"
  → Prioritaet muss 1 sein
```

**Warum Priority 1?** Memory ist Jarvis' Kern-Identitaet. Ohne Erinnerungen ist er ein generisches LLM. Der Memory-Kontext muss IMMER im Prompt sein — er darf nie vor optionalen Abschnitten (z.B. Wetter, HA-Status) gedroppt werden.

---

### BUG 6: Doppelter Wort-Filter (KRITISCH)

**Problem**: Zwei separate Wort-Filter blockieren gemeinsam die Fakten-Extraktion:

1. `brain.py` Zeile ~4380: `if self.memory_extractor and len(text.split()) > 3:` — MINDESTENS 4 Woerter noetig
2. `memory_extractor.py` Zeile ~175: `if len(user_text.split()) < max(self._min_words, 5):` — MINDESTENS 5 Woerter noetig

**Ergebnis**: Viele wertvolle Fakten kommen nie durch:
- "Meine Frau heisst Lisa" = 4 Woerter → NICHT extrahiert!
- "Ich mag 21 Grad" = 4 Woerter → NICHT extrahiert!
- "Mein Name ist Max" = 4 Woerter → NICHT extrahiert!

**DAS ist DER Hauptgrund warum keine neuen Fakten gespeichert werden.**

**Fix in brain.py** (~4380):
```python
# VORHER:
if self.memory_extractor and len(text.split()) > 3:
# NACHHER:
if self.memory_extractor and len(text.split()) > 2:
```

**Fix in memory_extractor.py** (~175):
```python
# VORHER:
if len(user_text.split()) < max(self._min_words, 5):
    return False
# NACHHER:
if len(user_text.split()) < max(self._min_words, 3):
    return False
```

**Methodik**:
```
Schritt 1 — Beide Filter finden:
  Grep: pattern="min_words|word.*count|len.*split" path="assistant/assistant/brain.py" output_mode="content"
  Grep: pattern="min_words|word.*count|len.*split" path="assistant/assistant/memory_extractor.py" output_mode="content"

Schritt 2 — Stellen lesen:
  Read: brain.py mit offset um Zeile ~4380
  Read: memory_extractor.py mit offset um Zeile ~175

Schritt 3 — Beide Filter anpassen:
  Edit brain.py: > 3 → > 2
  Edit memory_extractor.py: max(self._min_words, 5) → max(self._min_words, 3)

Schritt 4 — Verify:
  Grep: pattern="min_words|>=.*3|>.*2" path="assistant/assistant/brain.py" output_mode="content"
  Grep: pattern="min_words|>=.*3|>.*2" path="assistant/assistant/memory_extractor.py" output_mode="content"
  → Filter muessen gelockert sein
```

**Zusaetzlich** in `assistant/config/settings.yaml` (falls konfiguriert):
```yaml
memory:
  extraction_min_words: 3  # War 5, jetzt 3
```

---

## Phase 2: Memory-Integration pruefen

Nach den Fixes 1-6, pruefe die Gesamtintegration:

### Schritt 1: conversation_memory.py komplett lesen
```
Read: assistant/assistant/conversation_memory.py
```
Pruefe: Daily Summaries, Projekt-Tracking, offene Fragen — werden diese korrekt gespeichert und abgerufen?

### Schritt 2: memory.py komplett lesen
```
Read: assistant/assistant/memory.py
```
Pruefe: Wie verbinden sich die 5 Memory-Systeme (Redis Working Memory, ChromaDB Episodic, SemanticMemory Facts, ConversationMemory, Personality Memory)?

### Schritt 3: function_calling.py pruefen
```
Grep: pattern="conversation_memory|memory" path="assistant/assistant/function_calling.py" output_mode="content"
```
Pruefe: Existiert ein Tool/Function-Call fuer Memory-Operationen? Kann das LLM aktiv Fakten speichern/abrufen?

### Schritt 4: Memory-Flow verifizieren
Verfolge den kompletten Pfad:
```
Speichern:  User-Input → memory_extractor.py → semantic_memory.py → ChromaDB
Abrufen:    User-Input → brain.py/_mega_tasks → search_facts/get_facts_by_person → _build_memory_context → System-Prompt
Anzeigen:   System-Prompt → LLM → Antwort mit Fakten
```

---

## Praxis-Testszenarien

Diese Dialoge MUESSEN nach den Fixes funktionieren:

### TEST 1: Fakten-Speicherung + Abruf
```
User: "Mein Geburtstag ist am 15. Maerz"
  → memory_extractor.py extrahiert Fakt (BUG 6 Fix: 4 Woerter kommen jetzt durch)
  → semantic_memory.py speichert in ChromaDB

[Spaeter]
User: "Wann habe ich Geburtstag?"
  → search_facts IMMER geladen (BUG 2 Fix)
  → Fakt "Geburtstag am 15. Maerz" gefunden
  → Jarvis: "Am 15. Maerz!" (NICHT "Das weiss ich nicht")
```

### TEST 2: Kurzzeit-Gedaechtnis
```
User: "Ich fahre morgen nach Muenchen"
[30 Sekunden Pause, 8 Nachrichten ueber andere Themen]
User: "Wohin fahre ich morgen?"
  → recent_conversations limit=10 (BUG 1 Fix): Muenchen-Nachricht noch im Kontext
  → Jarvis: "Nach Muenchen." (NICHT "Das weiss ich nicht")
```

### TEST 3: Personen-Fakten
```
User: "Meine Frau heisst Lisa"
  → memory_extractor: "Meine Frau heisst Lisa" = 4 Woerter → BUG 6 Fix: kommt jetzt durch
  → semantic_memory: Fakt gespeichert

[20 Nachrichten spaeter oder neue Session]
User: "Wie heisst meine Frau?"
  → get_facts_by_person IMMER geladen (BUG 2 Fix)
  → Fakt gefunden
  → Memory-Header klar (BUG 4 Fix): "DEIN GEDAECHTNIS"
  → Jarvis: "Lisa." (NICHT Halluzination)
```

---

## Rollback-Regel

**Vor dem ersten Edit**: Aktuellen Stand notieren.

```bash
cd /home/user/mindhome
git checkout -b fix/memory-amnesia
git add -A && git commit -m "Checkpoint: Vor Memory-Fixes"
```

**Nach jedem Fix**: Einzeln committen.
```bash
git add assistant/assistant/brain.py && git commit -m "Fix 1: Conversation limit 3->10"
```

**Wenn ein Fix ImportError oder SyntaxError verursacht**:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren: "Fix X verursacht Regression Y"
3. Zum naechsten Fix weitergehen
4. NIEMALS einen kaputten Fix stehen lassen

---

## Erfolgs-Check

```
□ grep "get_recent_conversations" brain.py → limit 10+
□ grep "search_facts\|get_facts_by_person" brain.py → in _mega_tasks (unconditional)
□ grep "conv_memory_ext.*1\|priority.*1" brain.py → priority 1
□ grep "min_words\|>=.*3\|>.*2" brain.py memory_extractor.py → filters relaxed
□ grep "GEDAECHTNIS\|GEDÄCHTNIS" brain.py → neuer direktiver Header
□ grep "weisst du\|kennst du\|erinnerst du\|wie heisse ich" brain.py → erweiterte Keywords
□ python -c "import assistant.brain" → kein ImportError
□ python -c "import assistant.memory" → kein ImportError
```

---

## REGELN

1. **Read -> Grep -> Edit -> Verify** fuer JEDEN Fix. Kein Fix ohne Verifizierung.
2. **Exakte Zeilennummern** koennen abweichen — immer ZUERST mit Read/Grep die aktuelle Stelle finden.
3. **Kein Refactoring** — nur die 6 Fixes. Keine Architektur-Aenderungen.
4. **Wenn ein Fix nicht moeglich ist** (Code hat sich geaendert, Stelle existiert nicht mehr): Dokumentiere WARUM und gehe zum naechsten Fix.
5. **Tests muessen bestehen** — wenn ein Fix Tests bricht, Fix anpassen.
6. **Ein Fix pro Commit** — damit Rollback granular moeglich ist.
7. **Analyse + Fix in EINEM Durchgang** — nicht erst alles lesen, dann erst alles fixen. Jeder Bug: lesen, verstehen, fixen, verifizieren, weiter.

---

## OUTPUT-FORMAT

Wenn du alle Fixes abgeschlossen hast, erstelle diesen Kontext-Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT:
- [x] BUG 1: get_recent_conversations limit=3 -> limit=10 (brain.py:XXXX und brain.py:XXXX)
- [x] BUG 2: Semantic Facts IMMER in _mega_tasks (brain.py:XXXX)
- [x] BUG 3: Memory-Keywords erweitert (brain.py:XXXX, +XX neue Keywords)
- [x] BUG 4: _build_memory_context() Header direktiv (brain.py:XXXX)
- [x] BUG 5: conversation_memory Priority 3->1 (brain.py:XXXX)
- [x] BUG 6: Wort-Filter gelockert (brain.py:XXXX, memory_extractor.py:XXXX)

OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH

GEAENDERTE DATEIEN:
- assistant/assistant/brain.py
- assistant/assistant/memory_extractor.py
- [weitere]

REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
