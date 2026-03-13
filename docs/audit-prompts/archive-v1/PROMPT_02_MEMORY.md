# Prompt 2: Memory-System — Gezielte Reparatur der 6 bekannten Bugs

## Rolle

Du bist ein Elite-Software-Ingenieur spezialisiert auf Memory-Systeme in Conversational AI. Du fixst **bekannte, verifizierte Bugs** — keine Analyse, keine Exploration, sondern **Read -> Grep -> Edit -> Verify** fuer jeden Fix.

**LLM-Hinweis (Qwen 3.5 / Codestral)**: Dieses Prompt ist optimiert fuer praezise Code-Edits. Jeder Fix hat exakte Datei, Zeile und Code-Aenderung. Arbeite die Fixes **sequentiell** ab — ein Fix nach dem anderen. Nutze Read um die aktuelle Zeile zu verifizieren, dann Edit um die Aenderung zu machen, dann Grep um sicherzustellen dass nichts kaputt ist.

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
  - `assistant/assistant/personality.py`

---

## Alle 12 Memory-relevanten Module

Lies JEDES dieser Module mit Read, um die Memory-Architektur vollstaendig zu verstehen:

| # | Modul | Pfad | Funktion |
|---|---|---|---|
| 1 | memory.py | assistant/assistant/memory.py | Redis Working Memory, get_recent_conversations() |
| 2 | semantic_memory.py | assistant/assistant/semantic_memory.py | ChromaDB Langzeit-Fakten, search_facts(), get_facts_by_person() |
| 3 | conversation_memory.py | assistant/assistant/conversation_memory.py | Projekt-Tracking, offene Fragen, Daily Summaries |
| 4 | memory_extractor.py | assistant/assistant/memory_extractor.py | Fakten-Extraktion aus Gespraechen |
| 5 | correction_memory.py | assistant/assistant/correction_memory.py | Gelernte Korrekturen |
| 6 | dialogue_state.py | assistant/assistant/dialogue_state.py | Konversations-Zustandsmaschine |
| 7 | embeddings.py | assistant/assistant/embeddings.py | Embedding-Generierung fuer Memory-Suche |
| 8 | embedding_extractor.py | assistant/assistant/embedding_extractor.py | Feature-Extraktion |
| 9 | learning_observer.py | assistant/assistant/learning_observer.py | Gelerntes aus Verhalten |
| 10 | learning_transfer.py | assistant/assistant/learning_transfer.py | Wissenstransfer zwischen Domains |
| 11 | knowledge_base.py | assistant/assistant/knowledge_base.py | Lokales Wissen |
| 12 | personality.py | assistant/assistant/personality.py | build_memory_callback_section() — eigenes Memory-System! |

> **ACHTUNG**: Module 1-4 sind die KERN-Memory-Module. Module 5-12 ergaenzen das Memory-System. Pruefe ob sie ALLE korrekt in brain.py integriert sind.

---

## DAS PROBLEM: Jarvis hat Alzheimer

Jarvis vergisst **alles**. Trotz 3 separater Memory-Systeme (Redis, ChromaDB, SemanticMemory) funktioniert die Erinnerung nicht. Die Root Causes sind **bekannt und verifiziert**:

### Die 3 Memory-Systeme (NICHT verbunden)

```
System 1: Redis Working Memory (memory.py)
  -> Speichert letzte 3-50 Konversationen
  -> get_recent_conversations(limit=3) — NUR 3!

System 2: ChromaDB Episodic Memory (memory.py:276 search_memories())
  -> Semantische Suche ueber vergangene Gespraeche
  -> Wird NUR bei intent_type=="memory" abgefragt (brain.py:3204)

System 3: Semantic Facts (semantic_memory.py:469 search_facts(), :507 get_facts_by_person())
  -> Gespeicherte Fakten ueber Personen
  -> Werden NUR bei intent_type=="memory" geladen
  -> _build_memory_context() (brain.py:5562) baut den Prompt-Abschnitt
  -> Aber nur wenn relevant_facts UND person_facts gefuellt sind!

System 4 (Bonus): conversation_memory.py
  -> Projekt-Tracking, offene Fragen, Daily Summaries
  -> Geladen bei brain.py:2438 mit get_memory_context()
  -> Hat Priority 3 im System-Prompt (brain.py:2973) — wird GEDROPPT bei Token-Knappheit

System 5 (Bonus): personality.py:739 build_memory_callback_section()
  -> Liest aus mha:personality:memorable:{person}
  -> ANDERES Memory-System als semantic_facts!
```

**Ergebnis**: User sagt "Mein Geburtstag ist am 15. Maerz" — 5 Nachrichten spaeter ist das vergessen, weil:
1. Nur 3 Konversationen im Context (Fix 1)
2. Semantic Facts werden nicht geladen ausser bei Memory-Intent (Fix 2)
3. Memory-Intent-Erkennung ist zu eng (Fix 3)
4. Memory-Kontext hat falsche Prioritaet — wird gedroppt (Fix 5)

---

## Bekannte kritische Memory-Bugs (aus vorherigen Audits)

Diese Bugs wurden in vorherigen Durchlaeufen identifiziert und MUESSEN gefixt werden:

### BUG 1: get_recent_conversations(limit=3) — zu wenig Kontext

**Dateien:** brain.py Zeile ~3080 und ~2442
**Problem:** Nur die letzten 3 Konversationen werden als Kontext geladen. User erwartet Erinnerung an die letzten 10+ Nachrichten.
**Fix:**
```python
# VORHER:
recent = await self.memory.get_recent_conversations(limit=3)
# NACHHER:
recent = await self.memory.get_recent_conversations(limit=10)
```
**Verify:** `grep "get_recent_conversations" brain.py` → limit muss 10 sein

### BUG 2: Semantische Fakten nur bei intent_type=="memory" geladen

**Datei:** brain.py ca. Zeile 2430 (_mega_tasks)
**Problem:** search_facts() und get_facts_by_person() werden NUR aufgerufen wenn brain.py den Intent als "memory" klassifiziert. Bei normalen Gespraechen fehlen gespeicherte Fakten KOMPLETT im System-Prompt.
**Fix:** In _mega_tasks IMMER semantic facts laden:
```python
# HINZUFUEGEN in _mega_tasks (ca. Zeile 2430):
_mega_tasks.append(("person_facts", self.memory.semantic.get_facts_by_person(person or "")))
_mega_tasks.append(("relevant_facts", self.memory.semantic.search_facts(text, limit=5)))
```
Dann im Context-Build (nach Zeile 2462):
```python
person_facts = _safe_get("person_facts", [])
relevant_facts = _safe_get("relevant_facts", [])
```
**Verify:** `grep "search_facts\|get_facts_by_person" brain.py` → muss in _mega_tasks stehen

### BUG 3: Memory-Prioritaet 3 statt 1

**Datei:** brain.py ca. Zeile 2973
**Problem:** conv_memory_ext hat Prioritaet 3. Bei knappem Token-Budget wird das Gedaechtnis WEGGELASSEN. Memory ist aber KERNFUNKTION.
**Fix:**
```python
# VORHER:
sections.append(("conv_memory_ext", f"\n\nGEDAECHTNIS: {conv_memory_ctx}", 3))
# NACHHER:
sections.append(("conv_memory_ext", f"\n\nGEDAECHTNIS: {conv_memory_ctx}", 1))
```
**Verify:** `grep "conv_memory_ext" brain.py` → Prioritaet muss 1 sein

### BUG 4: Memory-Kontext-Header zu vage

**Datei:** brain.py _build_memory_context() ca. Zeile 5562
**Problem:** Der Header "nutze mit Haltung wie ein alter Bekannter" ist zu unspezifisch. Das LLM weiss nicht dass das SEINE Erinnerungen sind.
**Fix:** Header aendern zu:
```python
header = (
    "DEIN GEDAECHTNIS — folgende Fakten WEISST DU ueber den User:\n"
    "Nutze sie AKTIV aber BEILAEUFIG. Nicht als Datenbank-Abfrage.\n"
)
```

### BUG 5: Memory-Intent-Erkennung zu eng

**Datei:** brain.py (wo intent_type erkannt wird)
**Problem:** Nur wenige Keywords loesen "memory"-Intent aus. Viele Erinnerungs-Fragen werden nicht erkannt.
**Fix:** Keywords erweitern:
```python
memory_keywords = [
    "weisst du", "kennst du", "erinnerst du",
    "was habe ich", "wer bin ich", "wie heisse ich",
    "mein name", "mein geburtstag", "meine frau", "mein mann",
    "wo wohne ich", "was mag ich", "was habe ich gesagt",
    "letzte woche", "gestern", "remember", "erinnere dich",
]
```

### BUG 6: 🔴 _should_extract() Wort-Minimum zu hoch — kurze Fakten werden IGNORIERT

**Dateien:** `assistant/assistant/memory_extractor.py` Zeile 175 UND `assistant/assistant/brain.py` Zeile ~4380
**Problem:** Es gibt eine **DOPPELTE Wort-Zaehlung** die zusammen wirkt:

1. `brain.py:4380`: `if self.memory_extractor and len(text.split()) > 3:` — MINDESTENS 4 Woerter noetig damit Extraktion ueberhaupt startet
2. `memory_extractor.py:175`: `if len(user_text.split()) < max(self._min_words, 5):` — MINDESTENS 5 Woerter noetig um nicht gefiltert zu werden

Ergebnis: Text braucht MINDESTENS 5 Woerter um durch beide Filter zu kommen. Viele wertvolle Fakten sind kuerzer:
- "Meine Frau heisst Lisa" = 4 Woerter → NICHT extrahiert!
- "Ich mag 21 Grad" = 4 Woerter → NICHT extrahiert!
- "Mein Name ist Max" = 4 Woerter → NICHT extrahiert!

**Das ist DER Hauptgrund warum keine neuen Fakten gespeichert werden.**

**Fix:**
```python
# VORHER (memory_extractor.py:175):
if len(user_text.split()) < max(self._min_words, 5):
    return False

# NACHHER: Minimum auf 3 Woerter senken
if len(user_text.split()) < max(self._min_words, 3):
    return False
```

**AUCH in brain.py** (ca. Zeile 4380):
```python
# VORHER:
if self.memory_extractor and len(text.split()) > 3:
# NACHHER:
if self.memory_extractor and len(text.split()) > 2:
```
Damit gehen auch 3-Woerter-Saetze ("Ich mag Kaffee") durch den ersten Filter.

**Zusaetzlich** in `assistant/config/settings.yaml` (falls konfiguriert):
```yaml
memory:
  extraction_min_words: 3  # War 5, jetzt 3
```

**Verify:**
```
Grep: pattern="min_words|_min_words|extraction_min_words" path="assistant/assistant/memory_extractor.py" output_mode="content"
Grep: pattern="extraction_min_words" path="assistant/config/" output_mode="content"
```

### BUG 7: 🟠 LLM-Extraktion scheitert leise — kein Logging bei JSON-Parse-Fehler

**Datei:** `assistant/assistant/memory_extractor.py` Zeile 262-264, 288-289
**Problem:** Wenn Qwen 3.5 kein valides JSON zurueckgibt (was haeufig vorkommt bei kleinen Modellen), wird der Fehler nur als `logger.debug` geloggt. Der User merkt NICHTS. Fakten verschwinden leise.

**Fix:**
```python
# VORHER (memory_extractor.py:262-264):
except Exception as e:
    logger.error("Fehler bei Fakten-Extraktion: %s", e)
    return []

# NACHHER: Detailliertes Logging + Metriken
except Exception as e:
    logger.error("Fehler bei Fakten-Extraktion: %s (model=%s, text_len=%d)",
                 e, self._extraction_model, len(conversation))
    return []
```

Und in `_parse_facts()`:
```python
# VORHER (memory_extractor.py:291):
logger.debug("Konnte LLM-Antwort nicht parsen: %s", text[:200])

# NACHHER: Von debug auf warning erhoehen
logger.warning("Fakten-JSON-Parse fehlgeschlagen (Qwen-Output war kein valides JSON): %s", text[:300])
```

**Verify:**
```
Grep: pattern="logger\.(debug|warning|error).*pars|logger\.(debug|warning|error).*Extraktion" path="assistant/assistant/memory_extractor.py" output_mode="content"
```

### BUG 8: 🟠 Fire-and-Forget ohne Retry bei Extraktions-Fehler

**Datei:** `assistant/assistant/brain.py` Zeile 4380-4386
**Problem:** `_extract_facts_background()` wird als Background-Task gestartet. Wenn sie fehlschlaegt, gibt es keinen Retry und keinen Hinweis. Wertvolle Fakten gehen verloren.

**Fix:** Retry-Logik in `_extract_facts_background()`:
```python
# NACHHER (brain.py _extract_facts_background):
async def _extract_facts_background(self, user_text, assistant_response, person, context):
    """Extrahiert Fakten im Hintergrund mit 1x Retry."""
    for attempt in range(2):  # Max 2 Versuche
        try:
            facts = await self.memory_extractor.extract_and_store(
                user_text=user_text,
                assistant_response=assistant_response,
                person=person,
                context=context,
            )
            if facts:
                logger.info("Hintergrund-Extraktion: %d Fakt(en) gespeichert (Versuch %d)",
                           len(facts), attempt + 1)
            return
        except Exception as e:
            if attempt == 0:
                logger.warning("Fakten-Extraktion Versuch 1 fehlgeschlagen, retrying: %s", e)
                await asyncio.sleep(1)
            else:
                logger.error("Fakten-Extraktion endgueltig fehlgeschlagen: %s", e)
```

### BUG 2 — KORREKTUR: context_builder laedt Fakten BEREITS immer

> **UPDATE**: Die Code-Analyse zeigt dass `context_builder.py:322-340` die Fakten bereits IMMER laedt (nicht hinter `intent_type=="memory"`). BUG 2 wie oben beschrieben ist moeglicherweise BEREITS GEFIXT.
>
> **Methodik**: Pruefe ZUERST mit Read/Grep ob search_facts() und get_facts_by_person() schon in `context_builder.py:_get_relevant_memories()` stehen. Falls ja → BUG 2 ist bereits gefixt, ueberspringe den Fix. Falls nein → Fix wie oben beschrieben anwenden.
>
> ```
> Grep: pattern="search_facts|get_facts_by_person" path="assistant/assistant/context_builder.py" output_mode="content"
> ```
> Erwartetes Ergebnis: Mindestens 2 Treffer in `_get_relevant_memories()`.

### BUG 9: 🔴 Keine Whitelist fuer explizite Merk-Befehle in _should_extract()

**Datei:** `assistant/assistant/memory_extractor.py` Zeile 166-211
**Problem:** `_should_extract()` prueft Wort-Minimum und Blacklists, hat aber KEINE Whitelist fuer explizite Merk-Befehle. Wenn der User sagt "Merk dir: Kaffee schwarz" (4 Woerter), wird es durch BUG 6 geblockt. Aber selbst mit Fix 6 (min=3) fehlt eine Erzwungene-Extraktion fuer:
- "Merk dir dass..."
- "Vergiss nicht dass..."
- "Ab sofort immer..."
- "Von jetzt an..."
- "Ich heiße..." / "Mein Name ist..."

Diese Pattern MUESSEN immer extrahiert werden, egal wie kurz.

**Fix:** Whitelist VOR den Filtern einbauen:
```python
# NACHHER (memory_extractor.py, am Anfang von _should_extract):
def _should_extract(self, user_text: str, assistant_response: str) -> bool:
    text_lower = user_text.lower().strip().rstrip("!?.")

    # WHITELIST: Diese Patterns IMMER extrahieren, egal wie kurz
    force_extract_patterns = [
        "merk dir", "merkt euch", "merke dir",
        "vergiss nicht", "vergiss das nicht",
        "ab sofort", "von jetzt an", "ab heute",
        "ich heisse", "ich heiße", "mein name ist",
        "meine frau", "mein mann", "mein partner",
        "mein geburtstag", "ich bin geboren",
        "ich mag", "ich hasse", "ich bevorzuge",
        "ich bin allergisch", "ich vertrage kein",
    ]
    if any(p in text_lower for p in force_extract_patterns):
        return True  # Erzwungene Extraktion!

    # Rest der bestehenden Filter...
    if len(user_text.split()) < max(self._min_words, 3):
        return False
    # ... (bestehender Code)
```

**Verify:**
```
Grep: pattern="force_extract|WHITELIST|merk dir|von jetzt an" path="assistant/assistant/memory_extractor.py" output_mode="content"
```

### BUG 10: 🟠 Relevance-Filter (0.3) und Confidence-Filter (0.6) zu streng

**Datei:** `assistant/assistant/context_builder.py` Zeile 320, 328-330, 338
**Problem:** Zwei Filter verhindern dass gespeicherte Fakten im System-Prompt erscheinen:

1. `relevance > 0.3` (Zeile 329): ChromaDB-Vektorabstand muss < 0.7 sein. Bei kurzen oder anders formulierten Fragen (z.B. "Wie trinke ich Kaffee?" vs. gespeichert "Kaffee schwarz") kann die Relevance unter 0.3 fallen → Fakt wird nicht gezeigt.

2. `confidence >= 0.6` (Zeile 338): Fakten mit Kategorie "general" starten bei 0.5 → werden NIE gezeigt. Nach Decay sinken auch andere Fakten unter 0.6.

**Fix:**
```python
# VORHER (context_builder.py:320):
min_confidence = float(mem_cfg.get("min_confidence_for_context", 0.6))
# NACHHER:
min_confidence = float(mem_cfg.get("min_confidence_for_context", 0.4))

# VORHER (context_builder.py:329):
if f.get("relevance", 0) > 0.3
# NACHHER:
if f.get("relevance", 0) > 0.2
```

**Zusaetzlich** in `assistant/config/settings.yaml`:
```yaml
memory:
  min_confidence_for_context: 0.4  # War 0.6 — zu streng fuer neue/general Fakten
```

**Verify:**
```
Grep: pattern="min_confidence|relevance.*>" path="assistant/assistant/context_builder.py" output_mode="content"
Grep: pattern="min_confidence_for_context" path="assistant/config/" output_mode="content"
```

### BUG 11: 🟠 Guest-Mode blockiert Memory KOMPLETT ohne Feedback

**Datei:** `assistant/assistant/context_builder.py` Zeile 301-306
**Problem:** Wenn `mha:routine:guest_mode` in Redis auf "active" steht, werden KEINE Fakten geladen — nicht mal fuer den Hauptbenutzer. Falls dieser Redis-Key versehentlich gesetzt wurde (z.B. durch einen fehlerhaften Automation-Trigger), ist das gesamte Gedaechtnis stumm.

**Debug-Schritt** (VOR dem Fix):
```
Bash: redis-cli GET "mha:routine:guest_mode" 2>/dev/null || echo "Redis nicht erreichbar"
```
Falls Ergebnis "active" → DAS ist der Grund warum keine Fakten ankommen!

**Fix:** Logging hinzufuegen damit der Zustand sichtbar wird:
```python
# NACHHER (context_builder.py, ca. Zeile 301):
if guest_mode_active:
    logger.info("Guest-Mode aktiv — Memory-Abruf uebersprungen")
else:
    if self.semantic and user_text:
        context["memories"] = await self._get_relevant_memories(user_text, person)
```

**Verify:**
```
Grep: pattern="guest.*mode.*aktiv|guest.*mode.*skip|Guest-Mode" path="assistant/assistant/context_builder.py" output_mode="content"
```

### ARCHITEKTUR-HINWEIS: ConversationMemory + CorrectionMemory sind isolierte Silos

> **Kein direkter Bug, aber Architektur-Schwaeche:**
>
> Die Code-Analyse zeigt dass die 5 Memory-Systeme NICHT vollstaendig verbunden sind:
>
> | System | Verbunden mit | Status |
> |---|---|---|
> | SemanticMemory | MemoryManager, ContextBuilder, MemoryExtractor | ✅ Verbunden |
> | MemoryManager (Working/Episodic) | SemanticMemory | ✅ Verbunden |
> | ConversationMemory | NUR brain.py direkt | ❌ Silo |
> | CorrectionMemory | NUR brain.py direkt | ❌ Silo |
> | Personality Memory (mha:personality:memorable) | NUR personality.py | ❌ Silo |
>
> **Auswirkung:** Korrekturen (CorrectionMemory) beeinflussen nicht die Fakten-Extraktion. Wenn der User sagt "Nein, nicht 21 Grad, ich mag 22 Grad" → die Korrektur wird in CorrectionMemory gespeichert, aber SemanticMemory hat immer noch "21 Grad". Ebenso: personality.py hat ein EIGENES Memory-System (`mha:personality:memorable:{person}`) das nicht mit SemanticMemory synchronisiert ist.
>
> **Empfehlung fuer spaetere Prompts (P06b Architektur):** Memory-Silos konsolidieren. CorrectionMemory → sollte SemanticMemory-Fakten updaten. Personality-Memory → sollte mit SemanticMemory zusammengefuehrt werden.
>
> **KEIN Fix in P02** — das ist eine Architektur-Entscheidung fuer P06b.

---

## DIE 5 FIXES

### Arbeitsweise pro Fix

```
1. READ  — Datei lesen (bei brain.py mit offset= fuer die richtige Stelle)
2. GREP  — Alle Aufrufer/Abhaengigkeiten finden
3. EDIT  — Fix direkt in die Datei schreiben
4. VERIFY — Nochmal Read um den Fix zu pruefen + Grep um Seiteneffekte zu finden
```

---

### FIX 1: Konversations-Limit von 3 auf 10 erhoehen

**Problem**: `get_recent_conversations(limit=3)` — Jarvis sieht nur die letzten 3 Nachrichten. Alles was 5 Nachrichten zurueckliegt ist unsichtbar.

**Dateien und Zeilen**:
- `assistant/assistant/brain.py` Zeile ~3080: `get_recent_conversations(limit=3)`
- `assistant/assistant/brain.py` Zeile ~2442: `get_recent_conversations(limit=3)`

**Methodik**:

```
Schritt 1 — Alle Stellen finden:
  Grep: pattern="get_recent_conversations" path="assistant/assistant/" output_mode="content"

Schritt 2 — Jede Stelle lesen:
  Read: brain.py mit offset um die Zeilen 3070-3090 und 2430-2450 zu sehen

Schritt 3 — Edit (BEIDE Stellen!):
  Edit: old_string="get_recent_conversations(limit=3)"
        new_string="get_recent_conversations(limit=10)"

Schritt 4 — Verify:
  Grep: pattern="get_recent_conversations" path="assistant/assistant/" output_mode="content"
  -> Alle Stellen muessen jetzt limit=10 haben
```

**Code-Aenderung**:
```python
# VORHER (brain.py:3080 und brain.py:2442):
get_recent_conversations(limit=3)

# NACHHER:
get_recent_conversations(limit=10)
```

**Warum 10?** 3 ist absurd wenig — der User kann nicht mal ein kurzes Gespraech fuehren ohne den Kontext zu verlieren. 10 gibt genuegend Kontext fuer Multi-Turn-Dialoge ohne das Token-Budget zu sprengen. Bei durchschnittlich 50-100 Tokens pro Nachricht sind 10 Nachrichten ca. 500-1000 Tokens — kein Problem fuer Qwen 3.5 mit 32k Context.

---

### FIX 2: Semantic Facts IMMER laden (nicht nur bei Memory-Intent)

**Problem**: `person_facts` und `relevant_facts` werden NUR gefuellt wenn `intent_type == "memory"` (brain.py:3204). Bei einer normalen Frage wie "Wie heisst meine Frau?" mit intent_type="question" werden KEINE gespeicherten Fakten geladen.

**Dateien und Zeilen**:
- `assistant/assistant/brain.py` Zeile ~2430 (Bereich der `_mega_tasks` / parallelen Task-Erstellung)
- `assistant/assistant/brain.py` Zeile ~3204 (die `if intent_type == "memory"` Bedingung)

**Methodik**:

```
Schritt 1 — Aktuellen Code lesen:
  Read: brain.py mit offset um die _mega_tasks-Erstellung zu sehen (~2420-2460)
  Read: brain.py mit offset um die intent_type=="memory" Bedingung zu sehen (~3195-3215)

Schritt 2 — Verstehen wo person_facts/relevant_facts gesetzt werden:
  Grep: pattern="person_facts|relevant_facts" path="assistant/assistant/brain.py" output_mode="content"

Schritt 3 — Fix: Semantic-Facts-Laden in _mega_tasks verschieben (IMMER ausfuehren)
  Die Tasks fuer search_facts() und get_facts_by_person() muessen in die
  allgemeine Task-Liste verschoben werden, NICHT hinter der intent_type=="memory" Bedingung.

Schritt 4 — Verify:
  Grep: pattern="search_facts|get_facts_by_person" path="assistant/assistant/brain.py" output_mode="content"
  -> Muessen jetzt AUSSERHALB der intent_type-Bedingung stehen
```

**Konzept der Aenderung**:
```python
# VORHER (brain.py ~3204):
if intent_type == "memory":
    relevant_facts = await self.semantic_memory.search_facts(query)
    person_facts = await self.semantic_memory.get_facts_by_person(person)

# NACHHER: In die allgemeine _mega_tasks-Liste verschieben (~2430):
# Diese Tasks werden IMMER ausgefuehrt, unabhaengig vom intent_type
mega_tasks = {
    # ... bestehende Tasks ...
    "semantic_facts": self.semantic_memory.search_facts(query),
    "person_facts": self.semantic_memory.get_facts_by_person(person),
}
```

**ACHTUNG**: Die exakten Variablennamen und Task-Struktur muessen aus dem Code gelesen werden.
Methodik:
1. `Grep: pattern="_mega_tasks" path="assistant/assistant/brain.py" output_mode="content"` → Finde die Stelle wo Tasks definiert werden
2. `Read: brain.py` mit offset um diese Stelle herum (±30 Zeilen) → Verstehe das Task-Format (dict, list, oder anderes)
3. Fuege die zwei neuen Tasks im SELBEN Format hinzu wie die bestehenden Tasks
4. `Grep: pattern="intent_type.*memory|intent.*==.*memory" path="assistant/assistant/brain.py" output_mode="content"` → Finde die alte Bedingung
5. Entferne oder kommentiere die alte `if intent_type == "memory"` Bedingung fuer search_facts/get_facts_by_person

**Warum?** Semantic Facts sind das Langzeitgedaechtnis von Jarvis. Wenn der User sagt "Meine Frau heisst Lisa" und spaeter fragt "Wie heisst meine Frau?", wird das als intent_type="question" klassifiziert — und Lisa wird nie gefunden. Das ist der Hauptgrund warum Jarvis vergisst.

---

### FIX 3: Memory-Intent-Erkennung erweitern

**Problem**: Die Intent-Erkennung in brain.py klassifiziert zu wenige Anfragen als "memory". Fragen wie "Weisst du noch...?", "Erinnerst du dich...?" oder "Was habe ich gesagt ueber...?" werden nicht als Memory-Intent erkannt.

**Methodik**:

```
Schritt 1 — Intent-Erkennung finden:
  Grep: pattern="intent.*memory|memory.*intent|intent_type.*memory" path="assistant/assistant/brain.py" output_mode="content"

Schritt 2 — Aktuelle Keywords lesen:
  Read: brain.py an der Stelle wo intent_type=="memory" bestimmt wird

Schritt 3 — Keywords erweitern:
  Edit: Zusaetzliche Keywords hinzufuegen
```

**Erweiterte Keywords (Deutsch + Englisch)**:
```python
memory_keywords = [
    # Bestehende Keywords (aus dem Code lesen!)
    # ... plus diese neuen:
    "erinnerst du dich", "weisst du noch", "habe ich dir gesagt",
    "habe ich erwaehnt", "habe ich erzaehlt", "was weisst du ueber",
    "was habe ich gesagt", "kennst du mein", "kennst du meine",
    "wann habe ich", "wann ist mein", "wie heisst mein", "wie heisst meine",
    "wo wohne ich", "wo arbeite ich", "was mache ich beruflich",
    "mein geburtstag", "mein name", "meine frau", "mein mann",
    "remember", "do you know my", "what did i tell you",
    "what do you know about", "did i mention",
]
```

**ACHTUNG**: Lies ZUERST die bestehende Keyword-Liste aus dem Code und fuege nur die fehlenden hinzu. Dupliziere keine bestehenden Keywords.

---

### FIX 4: _build_memory_context() Header-Text verbessern

**Problem**: `_build_memory_context()` (brain.py:5562) baut den Memory-Abschnitt fuer den System-Prompt, aber der Header-Text ist unklar. Das LLM versteht nicht, dass dies Jarvis' eigene Erinnerungen sind, die es aktiv nutzen soll.

**Methodik**:

```
Schritt 1 — Aktuellen Header lesen:
  Read: brain.py mit offset um Zeile 5562 herum (5550-5580)

Schritt 2 — Header verbessern:
  Edit: Header-Text aendern
```

**Code-Aenderung**:
```python
# VORHER (den exakten Text aus dem Code lesen!):
# Vermutlich etwas wie "## Memory" oder "## Erinnerungen"

# NACHHER:
"""## Deine Erinnerungen und Wissen ueber den Benutzer

Die folgenden Fakten hast DU dir gemerkt. Nutze sie AKTIV in deinen Antworten.
Wenn der Benutzer nach Informationen fragt die hier stehen, antworte damit.
Ignoriere diese Fakten NICHT — sie sind dein Gedaechtnis."""
```

**Warum?** LLMs behandeln System-Prompt-Abschnitte unterschiedlich je nach Formulierung. Ein klarer, direktiver Header ("Deine Erinnerungen", "Nutze sie AKTIV") sorgt dafuer, dass Qwen 3.5 die Fakten tatsaechlich in Antworten einbezieht, statt sie als Hintergrundinformation zu ignorieren.

---

### FIX 5: conversation_memory.py Prioritaet von 3 auf 1 erhoehen

**Problem**: `conversation_memory.py` liefert Projekt-Tracking, offene Fragen und Daily Summaries. Diese werden bei brain.py:2438 mit `get_memory_context()` geladen, haben aber Priority 3 im System-Prompt (brain.py:2973). Bei Token-Knappheit wird der gesamte Konversations-Kontext GEDROPPT.

**Methodik**:

```
Schritt 1 — Priority-Zuweisung finden:
  Grep: pattern="priority.*3|priority.*conversation_memory|get_memory_context" path="assistant/assistant/brain.py" output_mode="content"

Schritt 2 — Stelle lesen:
  Read: brain.py mit offset um Zeile 2973 herum (2960-2990)

Schritt 3 — Priority aendern:
  Edit: priority=3 -> priority=1

Schritt 4 — Verify:
  Read: Stelle nochmal lesen, pruefen ob priority=1
  Grep: pattern="priority" path="assistant/assistant/brain.py" output_mode="content"
  -> Pruefen ob die neue Priority-Reihenfolge Sinn macht
```

**Code-Aenderung**:
```python
# VORHER (brain.py ~2973):
# ... etwas wie: {"content": memory_context, "priority": 3, ...}

# NACHHER:
# ... {"content": memory_context, "priority": 1, ...}
```

**Warum Priority 1?** Memory ist Jarvis' Kern-Identitaet. Ohne Erinnerungen ist Jarvis ein generisches LLM. Der Konversations-Kontext (offene Fragen, Projekt-Status, Zusammenfassungen) muss IMMER im Prompt sein — er darf nie gedroppt werden. Priority 1 stellt sicher, dass Memory vor optionalen Prompt-Abschnitten (z.B. Home-Assistant-Status, Wetter) steht.

---

## NACH ALLEN FIXES: Integrations-Check

### Pruefen ob die Memory-Systeme jetzt verbunden sind

```
Grep: pattern="_build_memory_context|build_memory_callback_section" path="assistant/assistant/" output_mode="content"
```

Stelle sicher:
1. `_build_memory_context()` wird IMMER aufgerufen (nicht nur bei intent_type=="memory")
2. `relevant_facts` und `person_facts` sind gefuellt wenn `_build_memory_context()` laeuft
3. `personality.py:build_memory_callback_section()` nutzt `mha:personality:memorable:{person}` — pruefen ob dies redundant zu semantic_facts ist oder ergaenzend

### Pruefen ob conversation_memory.py korrekt integriert ist

```
Grep: pattern="get_memory_context|conversation_memory" path="assistant/assistant/brain.py" output_mode="content"
```

Stelle sicher:
1. `get_memory_context()` wird aufgerufen
2. Das Ergebnis landet im System-Prompt
3. Priority ist jetzt 1 (nicht mehr 3)

---

## PRAXIS-TEST-DIALOGE

Simuliere mental diese Dialoge und verfolge den Code-Pfad nach den Fixes:

### Test 1: Geburtstag merken

```
User: "Mein Geburtstag ist am 15. Maerz"
  -> memory_extractor.py extrahiert: {person: "user", fact: "Geburtstag am 15. Maerz"}
  -> semantic_memory.py speichert den Fakt

[5 Nachrichten spaeter]

User: "Wann habe ich Geburtstag?"
  -> intent_type = "question" (NICHT "memory"!)
  -> VORHER: person_facts nicht geladen -> Jarvis weiss es nicht
  -> NACHHER (Fix 2): person_facts IMMER geladen -> Fakt "Geburtstag am 15. Maerz" gefunden
  -> NACHHER (Fix 4): Header sagt "Nutze diese Fakten AKTIV"
  -> Jarvis antwortet: "Dein Geburtstag ist am 15. Maerz!"

ERWARTETES ERGEBNIS: Korrekte Antwort "15. Maerz"
FEHLERFALL OHNE FIX: "Das weiss ich leider nicht" oder halluziniertes Datum
```

### Test 2: Reiseplan merken

```
User: "Ich fahre morgen nach Muenchen"
  -> Gespeichert in Redis (memory.py) als Konversation
  -> memory_extractor.py extrahiert: {person: "user", fact: "Faehrt nach Muenchen"}

[Pause — 8 Nachrichten ueber andere Themen]

User: "Wohin fahre ich morgen?"
  -> VORHER (Fix 1): limit=3 -> Die Muenchen-Nachricht ist laengst aus dem Window
  -> NACHHER (Fix 1): limit=10 -> Die Muenchen-Nachricht ist noch im Kontext
  -> NACHHER (Fix 2): Semantic Fact "Faehrt nach Muenchen" wird auch geladen
  -> Jarvis antwortet: "Du faehrst morgen nach Muenchen!"

ERWARTETES ERGEBNIS: "Muenchen"
FEHLERFALL OHNE FIX: "Das weiss ich nicht" (Nachricht ausserhalb des 3er-Windows)
```

### Test 3: Name der Ehefrau

```
User: "Meine Frau heisst Lisa"
  -> memory_extractor.py extrahiert: {person: "user", fact: "Frau heisst Lisa", category: "family"}
  -> semantic_memory.py speichert

[Naechste Session oder 20 Nachrichten spaeter]

User: "Wie heisst meine Frau?"
  -> intent_type = "question"
  -> VORHER: Semantic Facts nicht geladen (kein memory-Intent) -> Jarvis weiss nichts
  -> NACHHER (Fix 2): get_facts_by_person("user") liefert "Frau heisst Lisa"
  -> NACHHER (Fix 3): "wie heisst meine" matcht evtl. sogar als memory-Intent
  -> NACHHER (Fix 4): Header macht klar: "Nutze diese Fakten AKTIV"
  -> Jarvis antwortet: "Deine Frau heisst Lisa!"

ERWARTETES ERGEBNIS: "Lisa"
FEHLERFALL OHNE FIX: "Das hast du mir nicht gesagt" oder Halluzination
```

### Test 4: Konversations-Kontext bei Token-Knappheit

```
[Langer System-Prompt mit vielen HA-Entities, Wetter, Tools...]

User: "Was stand auf meiner Todo-Liste?"
  -> conversation_memory.py hat die Todo-Liste als offene Frage/Projekt
  -> VORHER (Fix 5): Priority 3 -> Bei Token-Knappheit GEDROPPT -> Jarvis weiss nichts
  -> NACHHER (Fix 5): Priority 1 -> IMMER im Prompt -> Jarvis hat die Info

ERWARTETES ERGEBNIS: Todo-Liste wird korrekt wiedergegeben
FEHLERFALL OHNE FIX: "Ich habe keine Informationen ueber deine Todo-Liste"
```

---

## Praxis-Testszenarien

Diese Dialoge MUESSEN nach den Fixes funktionieren:

```
TEST 1: Fakten-Speicherung + Abruf
  User: "Mein Geburtstag ist am 15. Maerz"
  → Jarvis speichert Fakt (semantic_memory.store_fact)
  User: "Wann habe ich Geburtstag?"
  → Jarvis: "Am 15. Maerz, Sir." (NICHT "Dazu habe ich keine Daten")

TEST 2: Kurzzeit-Gedaechtnis
  User: "Ich fahre morgen nach Muenchen"
  [30 Sekunden Pause]
  User: "Wohin fahre ich morgen?"
  → Jarvis: "Nach Muenchen." (aus recent_conversations, limit MUSS >3)

TEST 3: Personen-Fakten
  User: "Meine Frau heisst Lisa"
  User: "Wie heisst meine Frau?"
  → Jarvis: "Lisa." (aus semantic_memory.get_facts_by_person)

TEST 4: Token-Budget-Test
  → Memory-Sektion darf NIEMALS wegen Token-Budget wegfallen (Prioritaet 1!)
```

---

## ERFOLGSMETRIKEN

Nach allen 5 Fixes muessen diese Bedingungen erfuellt sein:

| # | Metrik | Pruefung | Ziel |
|---|---|---|---|
| 1 | Konversations-Window | Grep nach `get_recent_conversations` | Alle Stellen: `limit=10` |
| 2 | Semantic Facts immer geladen | `search_facts`/`get_facts_by_person` in context_builder.py | Ausserhalb von intent-Bedingung |
| 3 | Memory Keywords | Mindestens 20 Keywords in der Liste | Deutsche + Englische Keywords |
| 4 | Memory Header | `_build_memory_context()` Header | Direktiver Text mit "Nutze AKTIV" |
| 5 | Memory Priority | conversation_memory Priority | `priority=1` |
| 6 | Wort-Minimum | `_should_extract()` min_words | `max(self._min_words, 3)` (NICHT 5!) |
| 7 | Parse-Logging | `_parse_facts()` Logger-Level | `logger.warning` (NICHT debug!) |
| 8 | Retry-Logik | `_extract_facts_background()` | Mindestens 2 Versuche |
| 9 | Whitelist | `_should_extract()` hat force_extract_patterns | "merk dir", "ich mag", etc. VOR den Filtern |
| 10 | Confidence-Schwelle | `min_confidence_for_context` | `0.4` (NICHT 0.6!) |
| 11 | Relevance-Filter | `context_builder.py` relevance > | `0.2` (NICHT 0.3!) |
| 12 | Guest-Mode-Logging | `context_builder.py` Guest-Mode | Logger.info wenn Guest-Mode Fakten blockiert |
| 13 | Keine Regressionen | `cd /home/user/mindhome/assistant && python -m pytest tests/ -x --tb=short -q` | Tests bestehen |

### Erfolgs-Check (Schnellpruefung)

```
□ grep "get_recent_conversations" brain.py → limit muss 10 sein (NICHT 3)
□ grep "search_facts\|get_facts_by_person" context_builder.py → muss in _get_relevant_memories
□ grep "conv_memory_ext" brain.py → Prioritaet muss 1 sein (NICHT 3)
□ grep "DEIN GEDAECHTNIS" brain.py → neuer Header in _build_memory_context
□ grep "min_words.*3\|_min_words.*3" memory_extractor.py → Minimum muss 3 sein (NICHT 5!)
□ grep "logger.warning.*pars\|logger.warning.*JSON" memory_extractor.py → Warning statt Debug
□ grep "for attempt\|range(2)" brain.py → Retry-Logik vorhanden
□ grep "force_extract\|merk dir" memory_extractor.py → Whitelist existiert VOR Filtern
□ grep "min_confidence_for_context.*0.4\|min_confidence.*0.4" context_builder.py → 0.4 nicht 0.6
□ grep "relevance.*0.2" context_builder.py → 0.2 nicht 0.3
□ grep "Guest-Mode\|guest.*mode.*aktiv" context_builder.py → Logging vorhanden
□ python -c "import assistant.brain" → kein ImportError
□ python -c "import assistant.memory" → kein ImportError
```

---

## ROLLBACK-STRATEGIE

Falls ein Fix unerwartete Probleme verursacht:

```bash
# Vor dem Start: Branch erstellen
cd /home/user/mindhome
git checkout -b fix/memory-system
git add -A && git commit -m "Checkpoint: Vor Memory-Fixes"

# Nach jedem Fix: Commit
git add assistant/assistant/brain.py && git commit -m "Fix 1: Conversation limit 3->10"
git add assistant/assistant/brain.py && git commit -m "Fix 2: Semantic facts always loaded"
# ... etc.

# Falls Rollback noetig:
git log --oneline -10  # Letzten guten Commit finden
git revert <commit-hash>  # Einzelnen Fix rueckgaengig machen
```

### Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren: "Fix X verursacht Regression Y"
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

---

## OUTPUT-FORMAT

Wenn du alle Fixes abgeschlossen hast, erstelle diesen Kontext-Block:

```
## KONTEXT AUS PROMPT 2: Memory-Reparatur

### Durchgefuehrte Fixes
1. [x] Fix 1: get_recent_conversations limit=3 -> limit=10 (brain.py:XXXX und brain.py:XXXX)
2. [x] Fix 2: Semantic Facts in _mega_tasks verschoben (brain.py:XXXX)
3. [x] Fix 3: Memory-Keywords erweitert (brain.py:XXXX, +XX neue Keywords)
4. [x] Fix 4: _build_memory_context() Header verbessert (brain.py:XXXX)
5. [x] Fix 5: conversation_memory Priority 3->1 (brain.py:XXXX)

### Verifizierung
- [ ] Grep: Alle get_recent_conversations Stellen = limit=10
- [ ] Grep: search_facts/get_facts_by_person NICHT hinter intent_type=="memory"
- [ ] Grep: Memory-Keywords-Liste hat 20+ Eintraege
- [ ] Read: _build_memory_context() Header ist direktiv
- [ ] Read: conversation_memory Priority = 1
- [ ] Tests: pytest bestanden

### Noch offen / Beobachten
- personality.py:build_memory_callback_section() nutzt SEPARATES Memory-System (mha:personality:memorable:{person})
  -> Konsolidierung mit semantic_memory in spaeteren Prompts pruefen
- Token-Budget nach Erhoehung auf limit=10 beobachten (evtl. Anpassung noetig)
- memory_extractor.py: Pruefen ob Fakten-Extraktion zuverlaessig laeuft (eigener Fix)

### Memory-Flow nach Fixes
User Input -> Redis (limit=10) + SemanticMemory (IMMER) + ConversationMemory (Priority 1)
           -> Alles im System-Prompt mit direktivem Header
           -> LLM antwortet mit Kontext
           -> memory_extractor.py speichert neue Fakten
```

---

## REGELN

1. **Read -> Grep -> Edit -> Verify** fuer JEDEN Fix. Kein Fix ohne Verifizierung.
2. **Exakte Zeilennummern** koennen abweichen — immer ZUERST mit Read/Grep die aktuelle Stelle finden.
3. **Kein Refactoring** — nur die 5 Fixes. Keine Architektur-Aenderungen.
4. **Wenn ein Fix nicht moeglich ist** (Code hat sich geaendert, Stelle existiert nicht mehr): Dokumentiere WARUM und gehe zum naechsten Fix.
5. **Tests muessen bestehen** — wenn ein Fix Tests bricht, Fix anpassen.
6. **Ein Fix pro Commit** — damit Rollback granular moeglich ist.

---

## OUTPUT

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
