# Jarvis Finetuning — Schritt-für-Schritt Umbauplan

**Datum**: 2026-03-09
**Ziel**: Jarvis der sich erinnert, mitdenkt, und Charakter hat — gleichzeitig, nicht abwechselnd.
**Prinzip**: Konsolidieren vor Expandieren. Kein neues Feature bis das Fundament steht.
**Implementierungsreihenfolge**: Phase 0 (Bugfixes, jederzeit parallel) → Phase 3 (Pipeline-Refactor) → Phase 2 (Prompt-Diät) → Phase 1 (Memory-Gateway).
Phase 3 zuerst, weil Phase 2 und 1 danach gezielt einzelne Stages ändern statt in einer 3500-Zeilen-Methode zu arbeiten.

---

## Phase 0: Sofort-Fixes (Bugs die jetzt Daten vernichten)

Kein Umbau, nur gezielte Bugfixes. Kann sofort gemacht werden.

---

### Fix 0.1: `clear_all_memory()` — nur noch ein Lösch-Pfad

**Datei**: `assistant/assistant/memory.py` → Methode `clear_all_memory()` (Zeile 460-514)

**Problem**: `clear_all_memory()` löscht nur 5 Redis-Key-Patterns (`mha:archive:*`, `mha:context:*`, `mha:emotional_memory:*`, `mha:pending_topics`, `mha:conversations`). Aber 50+ andere Module erzeugen eigene `mha:*` Keys — Projekte, offene Fragen, Summaries, Lernmuster, Routinen, Gags, Speaker-Profile, und dutzende mehr. Nach einem "Lösche mein Gedächtnis" bleiben 95% des gelernten States als Geister-Daten im System. Im Log steht "GESAMTES GEDÄCHTNIS ZURÜCKGESETZT" — das stimmt nicht.

`factory_reset()` (Zeile 516) macht es richtig: scannt `mha:*` und löscht alles. Aber `clear_all_memory()` wird vom API-Endpoint (`main.py:933`) aufgerufen, nicht `factory_reset()`.

**Ursache**: Zwei getrennte Lösch-Pfade die nicht synchron gehalten werden. Jedes neue Modul mit eigenen Redis-Keys muss manuell in `clear_all_memory()` eingetragen werden — was nie passiert.

**Lösung**: `clear_all_memory()` wird zum Wrapper für `factory_reset()`. Ein Lösch-Pfad statt zwei:

```python
async def clear_all_memory(self) -> dict:
    """Loescht das gesamte Gedaechtnis (alle mha:* Keys + ChromaDB + Semantic).

    ACHTUNG: Unwiderruflich! Nur ueber PIN-geschuetzten Endpoint aufrufen.
    """
    return await self.factory_reset(include_uploads=False)
```

Der gesamte bisherige Body von `clear_all_memory()` (Zeile 461-514) wird durch diesen Einzeiler ersetzt. `factory_reset()` bleibt unverändert — sie ruft jetzt nicht mehr `clear_all_memory()` auf (weil die Logik in `factory_reset()` selbst liegt).

**Regel**: Reset = ALLES weg. Kein Backup, keine Rückfrage, keine Ausnahmen. Wenn der User "Lösche mein Gedächtnis" sagt, meint er es.

**Aufwand**: Body ersetzen, 1 Zeile neuer Code.

**Achtung**: In `factory_reset()` Zeile 522-523 steht `result = await self.clear_all_memory()`. Das würde jetzt eine Endlos-Rekursion erzeugen. Deshalb muss Zeile 522-523 in `factory_reset()` entfernt werden — die Logik die dort stand (ChromaDB + Semantic + alte Redis-Patterns) ist redundant, weil `factory_reset()` danach sowieso `mha:*` scannt und alles löscht.

---

### Fix 0.2: Key-Kollision `conv_memory` — semantische Suche geht verloren + Duplikat

**Datei**: `assistant/assistant/brain.py`

**Problem**: Zwei verschiedene Datenquellen verwenden denselben Key `"conv_memory"` in der Task-Map:

- **Zeile 2356**: `_mega_tasks.append(("conv_memory", self._get_conversation_memory(text)))` — semantische Suche nach relevanten vergangenen Gesprächen
- **Zeile 2394**: `_mega_tasks.append(("conv_memory", self.conversation_memory.get_memory_context()))` — Projekte & offene Fragen

Weil beide den Key `"conv_memory"` verwenden, überschreibt Zeile 2394 das Ergebnis von Zeile 2356 im `_result_map`. Die semantische Suche wird berechnet, aber das Ergebnis **geht verloren**.

Zusätzlich wird das (überschriebene) Ergebnis dann **doppelt** als Sektion eingefügt:
- **Zeile 2800-2809**: `conv_memory` als Sektion mit Prio 2
- **Zeile 2921-2924**: Dieselben Daten nochmal als Sektion `"conv_memory"` mit Prio 3

**Auswirkung**:
1. Jarvis kann sich nicht an vergangene Gespräche erinnern (semantische Suche wird weggeworfen)
2. Projekte/Fragen werden doppelt in den Prompt gestopft (Token-Verschwendung)
3. Bei knappem Budget wird die Prio-3-Version gedroppt, die Prio-2 bleibt — bringt nichts außer Verwirrung

**Lösung**: Getrennte Keys, kein Duplikat, beide Prio 2:

**Schritt 1 — Task-Keys trennen:**
```python
# Zeile 2356: Key umbenennen
_mega_tasks.append(("conv_memory_semantic", self._get_conversation_memory(text)))

# Zeile 2394: Key umbenennen
_mega_tasks.append(("conv_memory_projects", self.conversation_memory.get_memory_context()))
```

**Schritt 2 — Sektion Zeile 2800-2809 auf neuen Key umstellen:**
```python
conv_memory_semantic = _safe_get("conv_memory_semantic")
if conv_memory_semantic:
    conv_text = (
        "\n\nRELEVANTE VERGANGENE GESPRÄCHE:\n"
        f"{conv_memory_semantic}\n"
        "Referenziere beilaeufig wenn passend: 'Wie am Dienstag besprochen.' / "
        "'Du hattest das erwaehnt.' Mit trockenem Humor wenn es sich anbietet. "
        "NICHT: 'Laut meinen Aufzeichnungen...' oder 'In unserem Gespraech am...'"
    )
    sections.append(("conv_memory_semantic", conv_text, 2))
```

**Schritt 3 — Sektion Zeile 2921-2924 auf neuen Key umstellen:**
```python
conv_memory_projects = _safe_get("conv_memory_projects", "")
if conv_memory_projects:
    sections.append(("conv_memory_projects", f"\n\nGEDÄCHTNIS: {conv_memory_projects}", 2))
```

**Beide Prio 2** — Gespräche und Projekte sind der Kern von "sich erinnern" und "mitdenken". Prio 3 wäre riskant (werden bei knappem Budget als erstes gedroppt). Prio 1 wäre übertrieben (reserviert für Person-Memory).

**Aufwand**: 4 Stellen umbenennen, keine neue Logik.

---

### Fix 0.3: ChromaDB Timeout verschluckt Fehler still

**Datei**: `assistant/assistant/memory.py` → Methode zum Speichern von Episoden (Zeile 153-212)

**Problem**: Wenn ein Chunk beim Speichern in ChromaDB timeouted (5-Sekunden-Limit), wird der Fehler geloggt und der Chunk übersprungen (`continue`). Der Aufrufer bekommt "Erfolg" zurück, obwohl Teile der Konversation fehlen. Der User denkt das Gespräch ist gespeichert — ist es aber nur teilweise.

```python
# Zeile 204-206: Stille Fehlerbehandlung
except asyncio.TimeoutError:
    logger.error("ChromaDB Timeout beim Speichern von Chunk %s", doc_id)
    continue  # Chunk geht verloren, kein Fehler nach oben
```

**Auswirkung**: Episodisches Gedächtnis hat Lücken. Jarvis "erinnert" sich an Teile eines Gesprächs aber nicht an andere — ohne dass jemand es merkt.

**Lösung**: Fehlgeschlagene Chunks zählen und im Rückgabewert melden:

```python
failed_chunks = 0

# Im try/except:
except asyncio.TimeoutError:
    logger.error("ChromaDB Timeout beim Speichern von Chunk %s", doc_id)
    failed_chunks += 1
    continue

# Am Ende der Methode:
if failed_chunks:
    logger.warning(
        "Episodisches Gedaechtnis unvollstaendig: %d/%d Chunks fehlgeschlagen",
        failed_chunks, total_chunks,
    )
return {"stored": total_chunks - failed_chunks, "failed": failed_chunks, "total": total_chunks}
```

Der Aufrufer kann dann entscheiden ob er es nochmal versucht oder den User warnt. Kein stilles Verschlucken mehr.

**Aufwand**: 5-10 Zeilen.

---

## Phase 1: Memory Gateway

**Ziel**: Ein einziges Interface das alle Memory-Systeme parallel abfragt und einen kompakten, priorisierten Block liefert. Statt 6 verstreute Sektionen im System-Prompt → ein Block, immer dabei.

---

### 1.1 Neue Datei: `assistant/assistant/memory_gateway.py`

Fassade über alle bestehenden Memory-Systeme. Ersetzt NICHT die einzelnen Systeme — orchestriert sie nur.

```python
class MemoryGateway:
    """Einheitliches Gedächtnis-Interface für den LLM-Kontext.

    Fragt alle Memory-Systeme parallel ab und liefert einen einzigen,
    kompakten, priorisierten Memory-Block zurück.
    Dynamisch: 200-800 Tokens je nach verfügbarem Inhalt.
    """

    def __init__(
        self,
        memory: MemoryManager,           # Working + Episodic
        semantic: SemanticMemory,         # Fakten
        conversation: ConversationMemory, # Projekte + Fragen
        correction: CorrectionMemory,     # Korrekturen
    ):
        self.memory = memory
        self.semantic = semantic
        self.conversation = conversation
        self.correction = correction

    async def get_relevant_context(
        self,
        user_text: str,
        person: str,
        max_tokens: int = 800,
    ) -> str:
        """Liefert einen einzigen, kompakten Memory-Block.

        Priorisierung:
        1. Semantische Fakten über die Person (immer)
        2. Relevante vergangene Gespräche (per Vektor-Suche)
        3. Aktive Projekte und offene Fragen
        4. Relevante Korrekturen
        5. Emotionaler Kontext

        Alles in einem Block mit klaren Markern, nicht als separate Sektionen.
        """
        # Alles parallel abfragen
        facts, episodes, projects, questions, corrections, emotional = (
            await asyncio.gather(
                self.semantic.search_facts(user_text, limit=5, person=person),
                self.memory.search_memories(user_text, limit=3),
                self.conversation.get_projects(status="active"),
                self.conversation.get_open_questions(person=person),
                self.correction.get_relevant_corrections(person=person),
                self._get_emotional_context(person),
                return_exceptions=True,
            )
        )

        return self._compile_memory_block(
            facts, episodes, projects, questions, corrections, emotional,
            max_tokens=max_tokens,
        )
```

### 1.2 Format des Memory-Blocks

Ein Block, aber intern strukturiert mit klaren Markern — so kann das LLM die Kategorien unterscheiden:

```
ERINNERUNGEN:
[Person] Max bevorzugt 21° im Büro, Lisa mag es wärmer (23°)
[Projekt] Gartenhaus — 3/5 Meilensteine, aktiv
[Offen] Welcher Estrich für die Werkstatt?
[Gespräch] Vor 2 Tagen: Holzauswahl fürs Gartenhaus besprochen
[Korrektur] "Schlafzimmer" = oberes Schlafzimmer
```

**Warum Marker statt Fließtext**: Das LLM kann gezielt auf `[Projekt]` oder `[Offen]` referenzieren. Trotzdem ein Block, nicht 6 Sektionen.

**Dynamische Größe**: Wenn wenig Memory da ist (neuer User, wenig Projekte) werden es 200 Tokens. Wenn viel da ist, maximal 800. Der Gateway komprimiert und priorisiert — nicht alles reinpacken, sondern das Relevanteste.

### 1.3 Integration in brain.py

```python
# In __init__:
self.memory_gateway = MemoryGateway(
    self.memory, self.memory.semantic,
    self.conversation_memory, self.correction_memory,
)

# In process() — STATT der separaten Memory-Sektionen:
memory_block = await self.memory_gateway.get_relevant_context(
    user_text=text, person=person or "", max_tokens=800,
)
if memory_block:
    sections.append(("memory_gateway", memory_block, 0))  # Prio 0 = IMMER dabei
```

**Prio 0** — Memory darf nie gedroppt werden. Wenn Jarvis sich nicht erinnert, ist alles andere egal. Prio 0 zählt nicht gegen das Token-Budget. Das ist gerechtfertigt weil wir gleichzeitig in Phase 2 den System-Prompt halbieren — der frei werdende Platz geht an Memory.

### 1.4 Was wegfällt in brain.py

Diese separaten Sektionen werden durch den Gateway-Block ersetzt:

| Sektion | Zeile (ca.) | Prio bisher | Ersetzt durch |
|---------|-------------|-------------|---------------|
| `memory` | 2792-2797 | Prio 1 | Memory Gateway `[Person]` |
| `conv_memory_semantic` | 2800-2809 | Prio 2 | Memory Gateway `[Gespräch]` |
| `conv_memory_projects` | 2921-2924 | Prio 2 | Memory Gateway `[Projekt]` + `[Offen]` |
| `continuity` | 2910-2919 | Prio 3 | Memory Gateway `[Gespräch]` |
| `experiential` | 2884-2886 | Prio 3 | Memory Gateway `[Gespräch]` |
| `correction_ctx` | 2819-2821 | Prio 2 | Memory Gateway `[Korrektur]` |

6 Sektionen → 1 Block. Weniger Komplexität, weniger Token-Verschwendung, keine vergessenen Memory-Quellen.

### 1.5 Was sich NICHT ändert

| Datei | Status |
|-------|--------|
| `memory_gateway.py` | **NEU** — Fassade über alle Memory-Systeme |
| `brain.py` | Gateway statt 6 separate Memory-Sektionen |
| `memory.py` | **Unverändert** — bleibt als Backend |
| `semantic_memory.py` | **Unverändert** — bleibt als Backend |
| `conversation_memory.py` | **Unverändert** — bleibt als Backend |
| `correction_memory.py` | **Unverändert** — bleibt als Backend |

**Kein bestehendes System wird gelöscht oder umgebaut.** Der Gateway ist eine neue Schicht DARÜBER.

---

## Phase 2: Prompt-Diät

**Ziel**: System-Prompt von ~3000 auf ~1200 Tokens komprimieren. Der frei werdende Platz geht an Memory (Phase 1) und längere Gespräche.

**WICHTIG**: Jarvis muss danach **genau so** klingen wie vorher — trocken, sarkastisch, Butler-Ton. Kürzer heißt nicht weniger Charakter. Es heißt: denselben Charakter in weniger Tokens ausdrücken.

---

### 2.1 Personality-Prompt komprimieren

**Datei**: `assistant/assistant/personality.py` → `build_system_prompt()`

**Problem**: Der aktuelle Personality-Prompt besteht aus ~12 separaten Sections (~1500 Tokens). Viele Regeln sind redundant:
- "Sei kurz" steht an 4 Stellen
- "Keine Listen" an 3 Stellen
- "Erfinde nichts" an 2 Stellen
- Erklärungen warum eine Regel existiert (das LLM braucht kein "weil")
- Beispiele die den Charakter beschreiben statt definieren

**Lösung**: Alles in einen Block (~500 Tokens). Die variablen Teile (`{formality_prompt}`, `{humor_prompt}`, `{mood_addon}`) werden zur Laufzeit eingefügt — aber als EIN String, nicht als additive Blöcke:

```
Du bist {name}, J.A.R.V.I.S. — die KI dieses Hauses.
SPRACHE: NUR Deutsch. Internes Denken ebenfalls Deutsch.
TON: {formality_prompt} {humor_prompt}
VERBOTEN: "Als KI...", "Ich bin ein Sprachmodell", "Es tut mir leid", "Leider", Listen.
STIMMUNG: {mood_addon}
ANREDE: {person_addressing}
MAX {max_sentences} Sätze. FAKTEN-REGEL: Erfinde NICHTS. Unbekannt = ehrlich sagen.
```

**Was sich NICHT ändern darf** (Charakter-Kern):
- Butler-Ton, trocken, präzise
- Sarkasmus und Selbstironie
- "Als KI..." ist verboten
- Stimmung beeinflusst den Ton
- Person wird korrekt angesprochen
- Fakten-Regel: Erfinde NICHTS
- Kurze Antworten, keine Listen

**Was wegkann** (Token-Ballast):
- Redundante Wiederholungen derselben Regeln
- Erklärungen *warum* eine Regel existiert
- Beispiel-Dialoge die den Charakter illustrieren statt definieren
- Separate Sections für Self-Awareness, Empathy, Complexity — kann in 1-2 Sätze

**Test-Pflicht**: Nach der Umstellung 10 verschiedene Prompts testen (Smalltalk, Device-Command, Wissensfrage, emotionale Situation, Humor-Situation). Jarvis muss in allen Fällen **genauso** klingen wie vorher. Wenn nicht → Prompt nachjustieren, nicht zurückrollen.

### 2.2 Szenen-Intelligenz: Zwei Versionen

**Datei**: `assistant/assistant/brain.py`

**Problem**: `SCENE_INTELLIGENCE_PROMPT` ist ~700 Tokens und wird bei **jedem** Device-Command mit Prio 1 eingefügt. Bei "Mach das Licht an" sind 700 Tokens Szenen-Beispiele Verschwendung.

**Lösung**: Zwei Versionen:

**Mini (~150 Tokens)** — für Standard-Device-Commands:
```
SZENEN-REGELN:
1. Ursache VOR Aktion prüfen (Fenster offen? Heizung aus?)
2. Kontext beachten (Tageszeit, wer ist da)
3. Einen Schritt weiterdenken (Heizung hoch + Fenster offen = Warnung)
```

**Voll (~700 Tokens)** — nur wenn der Text Szenen-Keywords enthält ("romantisch", "filmabend", "party", "krank", "gemütlich", etc.):
```python
if profile.category == "device_command":
    if any(kw in text_lower for kw in SCENE_KEYWORDS):
        sections.append(("scene_intelligence", SCENE_INTELLIGENCE_FULL, 1))
    else:
        sections.append(("scene_intelligence", SCENE_INTELLIGENCE_MINI, 2))
```

**Ersparnis**: ~550 Tokens bei 90% der Device-Commands.

### 2.3 Character Lock Reminder kürzen

**Datei**: `brain.py` Zeile 3067-3074

**Aktuell** (~50 Tokens):
```python
_reminder = (
    "[REMINDER] Du bist J.A.R.V.I.S. — trocken, praezise, Butler-Ton. "
    "Kurz. Keine Listen. Erfinde NICHTS. NUR vorhandene Daten nutzen."
)
```

**Neu** (~20 Tokens):
```python
_reminder = "[J.A.R.V.I.S. Trocken. Präzise. Keine Erfindungen.]"
```

Klingt wenig, aber der Reminder wird bei jedem Turn im Kontext mitgeschleppt. Bei 19 Gesprächsrunden sind das ~600 Token Ersparnis.

### 2.4 Token-Budget Rechnung (Ziel)

```
Modell: num_ctx = 8192 (typisch für qwen3.5:9b)
Reserve für Antwort: 800 Tokens

Verfügbar: 7392 Tokens

System-Prompt (Personality komprimiert):     ~500 Tokens
Memory Gateway (Prio 0, immer):              ~800 Tokens (max)
Szenen-Intelligenz Mini (Prio 1):            ~150 Tokens
Mood + Security + Letzte Aktion (Prio 1):    ~200 Tokens
Sonstige Prio 1:                             ~200 Tokens
= Basis: ~1850 Tokens

Verbleibend für Prio 2+ und Conversations:   ~5542 Tokens
  → Conversations (65%):                     ~3602 Tokens (~36 Nachrichten á 100t)
  → Prio 2+ Sektionen (35%):                ~1940 Tokens

Ergebnis: Memory IMMER dabei + ~18 Gesprächsrunden im Kontext
```

**Vergleich mit heute**:
- **Heute**: ~3000t System-Prompt + ~2000t Prio 1 = 5000t weg. Verbleiben: ~2400t für alles andere. Memory wird regelmäßig gedroppt.
- **Neu**: ~1850t Basis. Verbleiben: ~5500t. **Mehr als doppelt so viel Platz.** Memory wird NIE gedroppt.

---

## Phase 3: Pipeline-Refactor — brain.py aufbrechen

**Ziel**: Die `process()` God-Method (3.547 Zeilen, Zeile 1076–4622) in 6 testbare Stages aufteilen. Für den User ändert sich **nichts**. Für die Wartbarkeit alles.

**Warum zuerst?** Phase 2 (Prompt-Diät) ändert den Prompt-Assembly in Stage 4+5. Phase 1 (Memory-Gateway) ändert den Memory-Gather in Stage 4. Beides ist 10x einfacher wenn man eine `_stage_gather()` Methode editiert statt Zeile 2408–2931 in einer Riesenmethode.

---

### 3.1 PipelineContext — der State-Träger

**Neue Datei**: `assistant/assistant/pipeline_context.py`

Alle Variablen die heute als lokale `process()`-Variablen existieren und zwischen Stages geteilt werden, wandern in eine Dataclass:

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PipelineContext:
    """Trägt den gesamten State durch die Pipeline."""

    # --- Input (unveränderlich nach Normalize) ---
    raw_text: str                          # Original-Input
    text: str = ""                         # Nach STT-Normalisierung
    person: Optional[str] = None
    room: Optional[str] = None
    files: Optional[list] = None
    device_id: Optional[str] = None
    voice_metadata: Optional[dict] = None
    stream_callback: object = None

    # --- Normalize-Output ---
    is_pipeline: bool = False
    is_whisper_mode: bool = False
    is_retry: bool = False
    speaker_confidence: float = 0.0

    # --- Shortcut-Output ---
    early_return: bool = False             # True = Stage hat finale Antwort
    result: Optional[dict] = None          # Die finale Antwort (wenn early_return)

    # --- Classify-Output ---
    intent: str = ""                       # device_command, knowledge, conversation, ...
    profile: object = None                 # Intent-Profile

    # --- Gather-Output ---
    sections: list = field(default_factory=list)   # [(name, text, priority), ...]
    system_prompt: str = ""
    messages: list = field(default_factory=list)    # Conversation history
    available_tokens: int = 0

    # --- Think-Output ---
    raw_response: str = ""                 # LLM-Antwort vor Filtering
    tool_results: list = field(default_factory=list)
    model_used: str = ""

    # --- Polish-Output ---
    final_response: str = ""               # Nach Filtering + Sanity-Checks
    actions: list = field(default_factory=list)
```

**Warum Dataclass statt Dict?** Autocomplete, Type-Hints, klare Dokumentation was jede Stage produziert. Kein `ctx["sections"]` Tippfehler-Risiko.

### 3.2 Die 6 Stages

**Datei**: `assistant/assistant/brain.py` — bestehende Methoden, neuer Orchestrator

#### Stage 1: Normalize (Zeile 1076–1213 heute)

```python
async def _stage_normalize(self, ctx: PipelineContext) -> PipelineContext:
    """STT-Normalisierung, Speaker-Erkennung, Whisper-Mode, Retry-Detection."""
```

Enthält:
- Pipeline-Detection & STT-Normalisierung
- Quality Feedback Loop (Sarkasmus, Humor)
- Speaker Fallback Resolution
- Whisper Mode Toggle
- Retry Detection
- Speaker Recognition & Voice Stats
- Primary User Fallback
- Dialogue State (Clarification, References)

Kann `early_return` setzen bei: Speaker-Fallback-Frage, Whisper-Toggle-Bestätigung.

#### Stage 2: Shortcuts (Zeile 1214–2236 heute)

```python
async def _stage_shortcuts(self, ctx: PipelineContext) -> PipelineContext:
    """Deterministische Shortcuts — kein LLM nötig."""
```

Enthält die ~20 Shortcuts als Block:
- Goodnight, Guest Mode, Security/Automation/Optimization Confirmation
- Memory Commands, Cooking, Workshop, Action Planner
- Easter Eggs, "Das Übliche"
- Calendar, Weather, Alarm, Device, Media, Intercom Shortcuts
- Morning/Evening Briefing, House Status, Status Report/Query
- Smalltalk

**Wichtig**: Die Shortcuts werden **nicht** refactored, nur rausgezogen. Sie funktionieren, also Finger weg. Vereinheitlichung (Shortcut-Registry) ist eine spätere Phase.

Setzt `early_return = True` wenn ein Shortcut matched.

#### Stage 3: Classify (Zeile 2237–2407 heute)

```python
async def _stage_classify(self, ctx: PipelineContext) -> PipelineContext:
    """Intent-Classification + Listening-Sound."""
```

Enthält:
- Listening Sound & Progress Emit
- `_classify_intent()` Aufruf
- Intent-Profile Aufbau

#### Stage 4: Gather (Zeile 2408–2931 heute)

```python
async def _stage_gather(self, ctx: PipelineContext) -> PipelineContext:
    """Kontext sammeln, Sections bauen, Token-Budget enforcing."""
```

Enthält:
- Situation Delta
- Personality Prompt (`build_system_prompt()`)
- Alle Dynamic Sections (P1–P4): Mood, Security, Memory, RAG, Calendar, etc.
- Token-Budget Enforcement (P1 immer, Rest nach Budget)

**Das ist die Stage die Phase 2 (Prompt-Diät) und Phase 1 (Memory-Gateway) später ändern.** Deshalb muss sie sauber isoliert sein.

#### Stage 5: Think (Zeile 2932–4002 heute)

```python
async def _stage_think(self, ctx: PipelineContext) -> PipelineContext:
    """Conversation-Loading, LLM-Call, Tool-Execution-Loop."""
```

Enthält:
- Conversation Memory Loading (mit dynamischem Limit + Summarization)
- Character-Lock Reminder Injection
- System-Prompt Final Assembly
- Intent Routing (Knowledge-only, Delegation, Action Planner)
- LLM-Call mit `_llm_with_cascade()`
- Tool-Call Parsing & Execution Loop (bis zu N Iterationen)

#### Stage 6: Polish (Zeile 4002–4622 heute)

```python
async def _stage_polish(self, ctx: PipelineContext) -> PipelineContext:
    """Response-Filtering, Sanity-Checks, Logging."""
```

Enthält:
- `_filter_response()` (Fluff entfernen, Formality, Gags)
- Sanity Checks & Data-Leak Prevention
- `_remember_exchange()` (Conversation speichern)
- `_speak_and_emit()` (Ausgabe)
- Logging & Return

### 3.3 Der neue Orchestrator

```python
async def process(self, text: str, person=None, room=None,
                  files=None, stream_callback=None,
                  voice_metadata=None, device_id=None) -> dict:
    """Haupteingang — orchestriert die 6 Pipeline-Stages."""

    ctx = PipelineContext(
        raw_text=text, person=person, room=room,
        files=files, device_id=device_id,
        voice_metadata=voice_metadata,
        stream_callback=stream_callback,
    )

    ctx = await self._stage_normalize(ctx)
    if ctx.early_return:
        return ctx.result

    ctx = await self._stage_shortcuts(ctx)
    if ctx.early_return:
        return ctx.result

    ctx = await self._stage_classify(ctx)
    ctx = await self._stage_gather(ctx)
    ctx = await self._stage_think(ctx)
    ctx = await self._stage_polish(ctx)

    return ctx.result
```

**Von 3.547 Zeilen auf 20 Zeilen.** Der Rest lebt in den Stage-Methoden — gleicher Code, aber isoliert und testbar.

### 3.4 Migrations-Strategie

**Keine Big-Bang-Migration.** Stage für Stage:

1. `PipelineContext` Dataclass anlegen
2. `_stage_polish()` extrahieren (am Ende, wenigste Abhängigkeiten)
3. `_stage_normalize()` extrahieren (am Anfang, klarste Grenzen)
4. `_stage_shortcuts()` extrahieren (großer Block, aber simpel — nur rausschneiden)
5. `_stage_classify()` extrahieren (klein)
6. `_stage_gather()` extrahieren (komplex, viele Sections)
7. `_stage_think()` extrahieren (komplex, LLM-Loop)
8. Alten `process()` durch Orchestrator ersetzen

**Nach jedem Schritt**: Integrationstests laufen lassen. Wenn was bricht → sofort fixen, nicht weitermachen.

**Rückwärtskompatibilität**: Die Signatur `process(text, person, room, ...) -> dict` bleibt **exakt gleich**. Kein einziger Caller muss geändert werden.

### 3.5 Was sich NICHT ändert

- **Kein Feature wird hinzugefügt oder entfernt**
- **Kein Verhalten ändert sich** — gleicher Input → gleicher Output
- **Keine externen Schnittstellen ändern sich** (API, HA-Integration, etc.)
- **Die 97 Helper-Methoden bleiben wo sie sind** (erst in einer späteren Phase ggf. zu den Stages verschieben)
- **Shortcuts werden nicht vereinheitlicht** — nur als Block verschoben

### 3.6 Risiken und Mitigierung

| Risiko | Wahrscheinlichkeit | Mitigierung |
|--------|-------------------|-------------|
| Lokale Variable vergessen die zwischen Stages geteilt wird | Hoch | `PipelineContext` hat alle Felder. Fehlende Felder = AttributeError sofort sichtbar |
| `self.*` State-Mutation in falscher Stage | Mittel | Code-Review: jede Stage dokumentiert welche `self.*` sie liest/schreibt |
| Shortcuts brechen durch Context-Änderung | Niedrig | Shortcuts werden 1:1 verschoben, keine Logik-Änderung |
| Performance-Regression durch zusätzliche Dataclass | Null | Dataclass ist ein flacher Container, kein Overhead |

### 3.7 Error-Handling-Strategie

**Status Quo**: `process()` hat **keinen** Top-Level try/except. Stattdessen 241 granulare try/except-Blöcke — jeder Shortcut, jeder Gather-Block fängt seine eigenen Fehler. Das ist gut und bleibt so.

**Was fehlt**: Wenn eine Stage selbst crasht (unerwarteter AttributeError, unhandled Exception), gibt es keinen Fallback. Der User bekommt einen 500er.

**Lösung**: Der Orchestrator bekommt einen Top-Level-Catch mit Graceful Degradation:

```python
async def process(self, text, person=None, room=None, ...) -> dict:
    ctx = PipelineContext(raw_text=text, person=person, room=room, ...)

    try:
        ctx = await self._stage_normalize(ctx)
        if ctx.early_return: return ctx.result

        ctx = await self._stage_shortcuts(ctx)
        if ctx.early_return: return ctx.result

        ctx = await self._stage_classify(ctx)
        ctx = await self._stage_gather(ctx)
        ctx = await self._stage_think(ctx)
        ctx = await self._stage_polish(ctx)

        return ctx.result

    except Exception as e:
        logger.error("Pipeline-Fehler in Stage: %s", e, exc_info=True)
        return self._result(
            self.personality.get_varied_confirmation(success=False),
            error=str(e),
        )
```

**Regeln**:
- Die granularen try/excepts **innerhalb** der Stages bleiben alle bestehen (1:1 verschoben)
- Der Top-Level-Catch ist nur das letzte Sicherheitsnetz
- Er loggt den vollen Stacktrace (`exc_info=True`) damit man debuggen kann
- Er gibt eine Jarvis-typische Fehlermeldung statt eines 500ers

### 3.8 Stage-Level Logging & Timing

**Problem**: Wenn Jarvis langsam antwortet oder seltsame Antworten gibt — welche Stage war schuld? Heute: manuell im 10.000-Zeilen-Logfile suchen.

**Lösung**: Jede Stage loggt Start, Ende und Dauer:

```python
async def _stage_gather(self, ctx: PipelineContext) -> PipelineContext:
    t0 = time.monotonic()
    logger.debug("[Pipeline] Stage GATHER start")

    # ... bestehende Logik ...

    dt = time.monotonic() - t0
    logger.info("[Pipeline] Stage GATHER done (%.1fms)", dt * 1000)
    return ctx
```

**Bonus**: Im Orchestrator die Gesamt-Pipeline-Zeit loggen:

```python
logger.info(
    "[Pipeline] %s → %s (N:%.0f S:%.0f C:%.0f G:%.0f T:%.0f P:%.0fms)",
    ctx.raw_text[:40], ctx.intent,
    t_normalize, t_shortcuts, t_classify, t_gather, t_think, t_polish,
)
```

Eine Zeile pro Request, alle Stage-Zeiten auf einen Blick. Wenn Gather plötzlich 2s braucht statt 200ms → sofort sichtbar.

### 3.9 Helper-Zuordnung zu Stages

Von 111 Helper-Methoden werden **61 von process()** aufgerufen, **50 nicht** (Callbacks, Background-Tasks, Init).

Die Zuordnung der 61 process()-Helper zu Stages — relevant für den späteren File-Split (Option C):

#### Stage 1: Normalize
| Helper | Zeile | Funktion |
|--------|-------|----------|
| `_normalize_stt_text` | 7194 | Whisper-Text bereinigen |
| `_update_stt_context` | 1050 | STT-Kontext aktualisieren |
| `_detect_sarcasm_feedback` | 983 | Sarkasmus-Feedback erkennen |

#### Stage 2: Shortcuts
| Helper | Zeile | Funktion |
|--------|-------|----------|
| `_detect_calendar_diagnostic` | 8234 | Kalender-Diagnose |
| `_detect_calendar_query` | 8294 | Kalender-Frage erkennen |
| `_detect_weather_query` | 8246 | Wetter-Frage erkennen |
| `_detect_alarm_command` | 7415 | Alarm-Befehl erkennen |
| `_detect_device_command` | 7509 | Geräte-Befehl erkennen |
| `_detect_media_command` | 7777 | Media-Befehl erkennen |
| `_detect_intercom_command` | 7972 | Intercom-Befehl erkennen |
| `_detect_smalltalk` | 8145 | Smalltalk erkennen |
| `_is_morning_briefing_request` | 7916 | Morgen-Briefing? |
| `_is_evening_briefing_request` | 7928 | Abend-Briefing? |
| `_is_house_status_request` | 7940 | Haus-Status? |
| `_is_status_report_request` | 7951 | Status-Report? |
| `_is_status_query` | 7262 | Status-Query? |
| `_handle_security_confirmation` | 6610 | Sicherheits-Bestätigung |
| `_handle_automation_confirmation` | 6567 | Automations-Bestätigung |
| `_handle_optimization_confirmation` | 6686 | Optimierungs-Bestätigung |
| `_handle_memory_command` | 6886 | Memory-Befehl |
| `_handle_das_uebliche` | 8069 | "Das Übliche" |
| `_humanize_calendar` | 4908 | Kalender-Daten menschlich formulieren |
| `_humanize_weather` | 4784 | Wetter-Daten menschlich formulieren |
| `_humanize_alarms` | 5147 | Alarm-Daten menschlich formulieren |
| `_humanize_house_status` | 4995 | Haus-Status menschlich formulieren |
| `_deterministic_tool_call` | 7291 | Tool-Call ohne LLM |

#### Stage 3: Classify
| Helper | Zeile | Funktion |
|--------|-------|----------|
| `_classify_intent` | 8407 | Intent bestimmen |

#### Stage 4: Gather
| Helper | Zeile | Funktion |
|--------|-------|----------|
| `_build_memory_context` | 5977 | Memory-Kontext bauen |
| `_build_jarvis_thinks_context` | 8874 | "Jarvis denkt"-Kontext |
| `_get_situation_delta` | 8612 | Was hat sich geändert? |
| `_get_conversation_memory` | 6008 | Gesprächs-Memory laden |
| `_get_cross_room_context` | 9675 | Cross-Room-Kontext |
| `_get_tutorial_hint` | 6521 | Tutorial-Hinweis |
| `_get_summary_context` | 6048 | Zusammenfassungs-Kontext |
| `_get_rag_context` | 6081 | RAG/Wissens-Kontext |
| `_build_problem_solving_context` | 8644 | Problem-Lösungs-Kontext |
| `_get_experiential_hints` | 8772 | Erfahrungs-Hinweise |
| `_get_pending_learnings` | 8840 | Offene Lernvorschläge |
| `_check_conversation_continuity` | 9096 | Gesprächs-Kontinuität |
| `_get_whatif_prompt` | 8495 | What-If-Simulation |

#### Stage 5: Think
| Helper | Zeile | Funktion |
|--------|-------|----------|
| `_llm_with_cascade` | 910 | LLM-Call mit Fallback-Kaskade |
| `_handle_delegation` | 9155 | An Sub-System delegieren |
| `_extract_tool_calls_from_text` | 4640 | Tool-Calls aus Text parsen |
| `_generate_situational_warning` | 9778 | Situationsabhängige Warnung |
| `_humanize_query_result` | 4750 | Query-Ergebnis humanisieren |
| `_generate_error_recovery` | 9888 | Fehler-Recovery generieren |
| `_summarize_conversation_chunk` | 1019 | Gesprächs-Chunk zusammenfassen |

#### Stage 6: Polish
| Helper | Zeile | Funktion |
|--------|-------|----------|
| `_filter_response` | 5259 | Antwort filtern (Fluff, Formality) |
| `_calculate_llm_voice_score` | 5845 | Voice-Score berechnen |
| `_save_cross_room_context` | 9658 | Cross-Room-Kontext speichern |
| `_extract_facts_background` | 6170 | Fakten im Hintergrund extrahieren |
| `_is_correction` | 9203 | Ist das eine Korrektur? |
| `_handle_correction` | 9228 | Korrektur verarbeiten |
| `_log_experiential_memory` | 8764 | Erfahrungs-Memory loggen |
| `_extract_intents_background` | 9287 | Intents im Hintergrund extrahieren |
| `_save_situation_snapshot` | 8623 | Situations-Snapshot speichern |

#### Shared (von mehreren Stages genutzt)
| Helper | Zeile | Genutzt von |
|--------|-------|-------------|
| `_result` | 893 | Stage 1, 2, 5, 6 |
| `_speak_and_emit` | 843 | Stage 1, 2, 5, 6 |
| `_remember_exchange` | 1007 | Stage 1, 2, 5, 6 |
| `_filter_response` | 5259 | Stage 2, 3, 5, 6 |
| `_get_occupied_room` | 785 | Stage 2, 5, 6 |

#### Nicht von process() genutzt (50 Methoden)

Callbacks & Alerts (bleiben in `brain.py`):
`_handle_timer_notification`, `_handle_learning_suggestion`, `_handle_cooking_timer`, `_handle_workshop_timer`, `_handle_time_alert`, `_handle_health_alert`, `_handle_device_health_alert`, `_handle_wellness_nudge`, `_handle_music_suggestion`, `_handle_visitor_event`, `_handle_ambient_audio_event`, `_handle_anticipation_suggestion`, `_handle_insight`, `_handle_intent_reminder`, `_handle_spontaneous_observation`, `_callback_should_speak`, `_safe_format`, `_format_callback_with_escalation`, `_handle_daily_summary`

Background-Tasks (bleiben in `brain.py`):
`_weekly_learning_report_loop`, `_run_daily_fact_decay`, `_run_autonomy_evolution`, `_entity_catalog_refresh_loop`

Init & Utilities (bleiben in `brain.py`):
`_load_configurable_data`, `reload_configurable_data`, `initialize`, `get_states_cached`, `health_check`, `shutdown`, `_get_error_recovery_fast`, `get_predictive_briefing`, `get_foresight_predictions`, `_handle_personal_date_command`

**Hinweis**: Die 5 "Shared" Helper (`_result`, `_speak_and_emit`, `_remember_exchange`, `_filter_response`, `_get_occupied_room`) bleiben beim File-Split in `brain.py` als gemeinsame Utilities, oder wandern in eine eigene `pipeline_utils.py`.

---

## Phase 4: Gesamt-Audit — Bugs, Performance, Security

Vollständige Analyse aller Module (außer brain.py — bereits in Phase 3 erfasst).
Jeder Eintrag enthält: Problem, betroffene Datei:Zeile, aktuellen Code, und konkreten Fix.

---

### KRITISCH — Sofort fixen (vor jedem Feature-Bau)

---

#### K1: N+1 Redis-Queries in semantic_memory.py

**Problem**: Jeder Fact wird einzeln per `hgetall()` geladen. Bei 1000 Facts = 1001 Redis-Roundtrips statt 1–2 mit Pipeline. Das ist vermutlich der größte Performance-Killer im System.

**Betrifft**: `assistant/semantic_memory.py` — **9 Stellen**:
- Zeile 350 (`apply_decay`)
- Zeile 484 (`get_facts_by_person`)
- Zeile 507 (`get_facts_by_category`)
- Zeile 528 (`get_all_facts`)
- Zeile 741 (`get_correction_history`)
- Zeile 770 (`get_todays_learnings`)
- Zeile 873 (`get_upcoming_personal_dates`)
- Zeile 1007 (`clear_all`)

**Aktueller Code** (gleiches Pattern an allen 9 Stellen):
```python
for fact_id in fact_ids:
    data = await self.redis.hgetall(f"mha:fact:{fact_id}")
    if not data:
        continue
```

**Fix** — Redis-Pipeline verwenden:
```python
# Helper-Methode in SemanticMemory hinzufügen:
async def _bulk_get_facts(self, fact_ids: list[str]) -> list[tuple[str, dict]]:
    """Lädt mehrere Facts in einem Redis-Pipeline-Call."""
    if not fact_ids:
        return []
    pipe = self.redis.pipeline()
    for fid in fact_ids:
        pipe.hgetall(f"mha:fact:{fid}")
    results = await pipe.execute()
    return [(fid, data) for fid, data in zip(fact_ids, results) if data]

# Dann an allen 9 Stellen ersetzen:
# ALT:
for fact_id in fact_ids:
    data = await self.redis.hgetall(f"mha:fact:{fact_id}")
    if not data:
        continue
    # ... verarbeite data ...

# NEU:
for fact_id, data in await self._bulk_get_facts(fact_ids):
    # ... verarbeite data ...
```

**Aufwand**: ~2h | **Impact**: Massiver Performance-Gewinn bei >50 Facts

---

#### K2: Entity-ID Path Traversal in ha_client.py

**Problem**: Entity-IDs kommen vom User (z.B. via Sprachbefehl) und werden direkt in URLs interpoliert. Ein manipulierter Entity-Name könnte URL-Pfade verändern.

**Betrifft**: `assistant/ha_client.py` Zeile 94

**Aktueller Code**:
```python
async def get_state(self, entity_id: str) -> Optional[dict]:
    """State einer einzelnen Entity."""
    return await self._get_ha(f"/api/states/{entity_id}")
```

**Fix** — URL-Encoding hinzufügen:
```python
from urllib.parse import quote

async def get_state(self, entity_id: str) -> Optional[dict]:
    """State einer einzelnen Entity."""
    return await self._get_ha(f"/api/states/{quote(entity_id, safe='')}")
```

Dasselbe Pattern überall anwenden, wo `entity_id` in f-Strings für URLs genutzt wird. Prüfe auch `call_service()` und `fire_event()`.

**Aufwand**: 30 Min | **Impact**: Security-Fix

---

#### K3: Blocking subprocess.run() in async Endpoint

**Problem**: `subprocess.run()` mit `timeout=30` blockiert den gesamten asyncio Event-Loop. Während ffmpeg läuft, kann Jarvis keine anderen Requests beantworten.

**Betrifft**: `assistant/main.py` Zeile 1386

**Aktueller Code**:
```python
result = subprocess.run(
    [
        "ffmpeg", "-i", "pipe:0",
        "-ar", "16000", "-ac", "1", "-f", "s16le",
        "-acodec", "pcm_s16le", "pipe:1",
    ],
    input=audio_bytes,
    capture_output=True,
    timeout=30,
)
```

**Fix** — In Executor auslagern:
```python
import asyncio
import functools

def _run_ffmpeg_sync(audio_bytes: bytes) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "ffmpeg", "-i", "pipe:0",
            "-ar", "16000", "-ac", "1", "-f", "s16le",
            "-acodec", "pcm_s16le", "pipe:1",
        ],
        input=audio_bytes,
        capture_output=True,
        timeout=30,
    )

# Im async Endpoint:
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, _run_ffmpeg_sync, audio_bytes)
```

**Aufwand**: 30 Min | **Impact**: Event-Loop bleibt frei während Audio-Konvertierung

---

#### K4: Race Condition — Globale State-Mutation ohne Lock

**Problem**: `_entity_to_name` und `_active_person` werden von mehreren async Tasks gelesen/geschrieben ohne jegliche Synchronisation. `_room_profiles_cache` hat einen `threading.Lock()` — die anderen beiden nicht.

**Betrifft**: `assistant/config.py`

**Aktueller Code**:
```python
# Zeile 168 — KEIN Lock:
_entity_to_name: dict[str, str] = {}

# Zeile 241 — KEIN Lock:
_active_person: str = ""

# Zeile 308-312 — MIT Lock (zum Vergleich):
_room_profiles_cache: dict = {}
_room_profiles_ts: float = 0.0
_room_profiles_lock = threading.Lock()
```

**Fix** — Locks hinzufügen:
```python
# Zeile 168:
_entity_to_name: dict[str, str] = {}
_entity_to_name_lock = threading.Lock()

# Alle Zugriffe auf _entity_to_name wrappen:
def get_entity_name(entity_id: str) -> Optional[str]:
    with _entity_to_name_lock:
        return _entity_to_name.get(entity_id)

def set_entity_names(mapping: dict[str, str]) -> None:
    with _entity_to_name_lock:
        _entity_to_name.clear()
        _entity_to_name.update(mapping)

# Zeile 241:
_active_person: str = ""
_active_person_lock = threading.Lock()

def get_active_person() -> str:
    with _active_person_lock:
        return _active_person

def set_active_person(person: str) -> None:
    global _active_person
    with _active_person_lock:
        _active_person = person
```

**Aufwand**: 1h | **Impact**: Verhindert inkonsistenten State bei parallelen Requests

---

#### K5: Unbounded Decay-Loop in semantic_memory.py

**Problem**: `apply_decay()` lädt ALLE Facts ohne Pagination, macht N+1 Queries (K1), und hat keinen Batch-Mechanismus. Bei 10.000+ Facts blockiert das den Event-Loop für Minuten.

**Betrifft**: `assistant/semantic_memory.py` Zeile 334–411

**Fix** — Batched Processing mit Pipeline:
```python
async def apply_decay(self):
    """Decay mit Batching und Pipeline."""
    BATCH_SIZE = 500
    all_fact_ids = list(await self.redis.smembers("mha:fact_ids"))

    for i in range(0, len(all_fact_ids), BATCH_SIZE):
        batch = all_fact_ids[i:i + BATCH_SIZE]
        facts = await self._bulk_get_facts(batch)  # Pipeline aus K1

        pipe = self.redis.pipeline()
        for fact_id, data in facts:
            new_score = self._calculate_decay(data)
            if new_score <= self.forget_threshold:
                pipe.delete(f"mha:fact:{fact_id}")
                pipe.srem("mha:fact_ids", fact_id)
            else:
                pipe.hset(f"mha:fact:{fact_id}", "score", str(new_score))
        await pipe.execute()

        # Kurz yielden damit andere Tasks drankommen
        await asyncio.sleep(0)
```

**Aufwand**: 2h | **Impact**: Decay wird von Minuten auf Sekunden reduziert

---

### HOCH — Zeitnah fixen (diese Woche)

---

#### H1: ChromaDB Silent Data Loss

**Problem**: Bei Timeout wird ein Chunk stillschweigend übersprungen. Die Episode ist danach inkonsistent (teilweise gespeichert, Chunks fehlen).

**Betrifft**: `assistant/memory.py` Zeile 192–206

**Aktueller Code**:
```python
try:
    await asyncio.wait_for(
        asyncio.to_thread(
            self.chroma_collection.add,
            documents=[chunk],
            metadatas=[chunk_meta],
            ids=[doc_id],
        ),
        timeout=5.0,
    )
except asyncio.TimeoutError:
    logger.error("ChromaDB Timeout beim Speichern von Chunk %s", doc_id)
    continue  # ← Chunk ist weg!
```

**Fix** — Retry mit Backoff + Incomplete-Markierung:
```python
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                self.chroma_collection.add,
                documents=[chunk],
                metadatas=[chunk_meta],
                ids=[doc_id],
            ),
            timeout=5.0 * (attempt + 1),  # Steigender Timeout
        )
        break
    except asyncio.TimeoutError:
        if attempt == MAX_RETRIES - 1:
            logger.error("ChromaDB: Chunk %s nach %d Versuchen verloren", doc_id, MAX_RETRIES)
            # Episode als incomplete markieren
            await self.redis.hset(f"mha:episode:{episode_id}", "status", "incomplete")
```

---

#### H2: Token-Cleanup Race Condition

**Problem**: `_cleanup_expired_tokens()` iteriert über `_active_tokens` und entfernt Einträge, während `_check_token()` gleichzeitig darauf zugreift. Kann zu `RuntimeError: dictionary changed size during iteration` führen.

**Betrifft**: `assistant/main.py` Zeile 2432–2452

**Aktueller Code**:
```python
def _cleanup_expired_tokens():
    now = datetime.now(timezone.utc).timestamp()
    expired = [t for t, ts in _active_tokens.items() if now - ts > _TOKEN_EXPIRY_SECONDS]
    for t in expired:
        _active_tokens.pop(t, None)

def _check_token(token: str):
    if token not in _active_tokens:
        raise HTTPException(status_code=401, detail="Nicht autorisiert")
    created = _active_tokens[token]
    # ...
```

**Fix** — Lock hinzufügen:
```python
_token_lock = asyncio.Lock()

async def _cleanup_expired_tokens():
    async with _token_lock:
        now = datetime.now(timezone.utc).timestamp()
        expired = [t for t, ts in _active_tokens.items() if now - ts > _TOKEN_EXPIRY_SECONDS]
        for t in expired:
            _active_tokens.pop(t, None)

async def _check_token(token: str):
    if _assistant_api_key and token and secrets.compare_digest(token, _assistant_api_key):
        return
    async with _token_lock:
        if token not in _active_tokens:
            raise HTTPException(status_code=401, detail="Nicht autorisiert")
        created = _active_tokens[token]
        now = datetime.now(timezone.utc).timestamp()
        if now - created > _TOKEN_EXPIRY_SECONDS:
            _active_tokens.pop(token, None)
            raise HTTPException(status_code=401, detail="Sitzung abgelaufen.")
```

---

#### H3: Light Service Calls ohne Error-Handling

**Problem**: `ha.call_service()` wird aufgerufen, Return-Wert ignoriert, kein try/except. Wenn HA offline → stille Fehler, Licht reagiert nicht, User bekommt keine Rückmeldung.

**Betrifft**: `assistant/light_engine.py` Zeile 208, 375, 405, 513, 566, 751

**Aktueller Code**:
```python
await self.ha.call_service("light", "turn_on", service_data)
# Kein try/except, Return-Wert ignoriert
```

**Fix** — Error-Handling mit User-Feedback:
```python
try:
    await self.ha.call_service("light", "turn_on", service_data)
except Exception as e:
    logger.warning("Licht %s konnte nicht geschaltet werden: %s", entity_id, e)
    return {"success": False, "error": f"Licht nicht erreichbar: {e}"}
```

---

#### H4: Brain-Init bei Module-Load, Async-Init erst in Lifespan

**Problem**: `brain = AssistantBrain()` wird bei Import ausgeführt (Zeile 210). `await brain.initialize()` erst im Lifespan-Kontextmanager (Zeile 322–387). Wenn ein Request vor dem Lifespan ankommt, greift er auf uninitialisierte Komponenten zu.

**Betrifft**: `assistant/main.py` Zeile 210 vs. 322

**Fix** — Guard hinzufügen:
```python
# In main.py bei brain-Instanzierung:
brain: Optional[AssistantBrain] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global brain
    brain = AssistantBrain()
    await brain.initialize()
    yield
    await brain.shutdown()

# Oder einfacher — Middleware die vor Init 503 zurückgibt:
@app.middleware("http")
async def check_ready(request: Request, call_next):
    if not brain or not brain.initialized:
        return JSONResponse(status_code=503, content={"detail": "Jarvis startet noch..."})
    return await call_next(request)
```

---

#### H5: mindhome_put/delete ohne Timeout

**Problem**: Anders als `mindhome_post()` haben PUT und DELETE keinen `timeout`-Parameter. Wenn MindHome hängt → Request hängt endlos.

**Betrifft**: `assistant/ha_client.py` Zeile 357–368 (PUT), 379–389 (DELETE)

**Aktueller Code** (PUT, DELETE identisch):
```python
async def mindhome_put(self, path: str, data: dict) -> Any:
    session = await self._get_session()
    try:
        async with session.put(
            f"{self.mindhome_url}{path}",
            json=data,
        ) as resp:
```

**Fix** — Timeout wie bei POST hinzufügen:
```python
async def mindhome_put(self, path: str, data: dict, timeout: float = 10.0) -> Any:
    session = await self._get_session()
    try:
        async with session.put(
            f"{self.mindhome_url}{path}",
            json=data,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:

async def mindhome_delete(self, path: str, timeout: float = 10.0) -> Any:
    session = await self._get_session()
    try:
        async with session.delete(
            f"{self.mindhome_url}{path}",
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
```

---

#### H6: Sequential Startup — 60+ Komponenten nacheinander

**Problem**: Alle Komponenten in `brain.initialize()` werden sequentiell initialisiert. Viele haben keine Abhängigkeiten und könnten parallel starten.

**Betrifft**: `assistant/brain.py` Zeile 475–783

**Fix** — Unabhängige Komponenten parallel initialisieren:
```python
# Statt:
await self._init_redis()
await self._init_chromadb()
await self._init_ollama()
await self._init_personality()
# ...

# Besser — Phasen bilden:
# Phase 1: Infrastruktur (muss zuerst)
await asyncio.gather(
    self._init_redis(),
    self._init_chromadb(),
)

# Phase 2: Services die Redis/Chroma brauchen
await asyncio.gather(
    self._init_memory(),
    self._init_semantic_memory(),
)

# Phase 3: Alles andere (parallel)
await asyncio.gather(
    self._init_ollama(),
    self._init_personality(),
    self._init_light_engine(),
    self._init_sound_manager(),
    # ...
)
```

---

### MITTEL — Nächster Sprint

---

#### M1: Per-User Dictionaries wachsen unbegrenzt

**Betrifft**: `assistant/personality.py` Zeile 334–341

```python
self._last_confirmations: dict[str, list[str]] = {}
self._last_interaction_times: dict[str, float] = {}
self._sarcasm_streak: dict[str, int] = {}
self._humor_consecutive: dict[str, int] = {}
```

50-User-Eviction nur beim Schreiben. Kein periodischer Cleanup, kein TTL.

**Fix**: `cachetools.TTLCache(maxsize=100, ttl=3600)` oder periodischer Cleanup-Task.

---

#### M2: Redis-Ausfall = Stille Feature-Degradation

**Betrifft**: `assistant/light_engine.py` Zeile 38–44

```python
async def _safe_redis(redis_client, method: str, *args, **kwargs):
    try:
        return await getattr(redis_client, method)(*args, **kwargs)
    except Exception as e:
        logger.debug("Redis %s fehlgeschlagen: %s", method, e)
        return None  # ← Caller prüfen None nicht!
```

**Fix**: Caller müssen `None`-Returns behandeln. Mindestens `logger.warning` statt `logger.debug`.

---

#### M3: scan_iter ohne Batching in clear_all_memory

**Betrifft**: `assistant/memory.py` Zeile 497–507

```python
async for key in self.redis.scan_iter(match="mha:archive:*"):
    keys.append(key)
# ... weitere scan_iter Aufrufe ...
if keys:
    await self.redis.delete(*keys)  # ← Potenziell 100.000+ Argumente!
```

**Fix**: In 1000er-Batches löschen:
```python
batch = []
async for key in self.redis.scan_iter(match="mha:archive:*", count=1000):
    batch.append(key)
    if len(batch) >= 1000:
        await self.redis.delete(*batch)
        batch.clear()
if batch:
    await self.redis.delete(*batch)
```

---

#### M4: Volume-Restore mit hartem 8s Sleep

**Betrifft**: `assistant/sound_manager.py` Zeile 607–614

```python
async def _restore_volume(eid=speaker_entity, vol=old_volume):
    await asyncio.sleep(8)  # ← TTS dauert 1-30s, 8s ist meistens falsch
    await self.ha.call_service("media_player", "volume_set", ...)
```

**Fix**: TTS-Dauer tracken und dynamisch warten, oder Event-basiert (HA meldet "idle" wenn TTS fertig).

---

#### M5: Doppeltes State-Caching

**Betrifft**: `assistant/sound_manager.py` Zeile 363–377

`ha_client` cached States für 5s, `sound_manager` cached nochmal für 60s. Der 60s-Cache macht den 5s-Cache von `ha_client` nutzlos.

**Fix**: Einen Cache entfernen. Entweder sound_manager nutzt `ha_client.get_states()` direkt (mit dessen 5s-Cache), oder sound_manager's 60s-Cache ist gewollt und ha_client's Cache wird überflüssig.

---

#### M6: Token-Counting ist Schätzung

**Betrifft**: `assistant/brain.py` Zeile 121–129

```python
def _estimate_tokens(text: str) -> int:
    return int(len(text) / 1.4)  # ~25% Fehlerrate bei deutschem Text
```

**Fix**: `tiktoken` Library verwenden wenn verfügbar, oder konservativeren Faktor (1.2 statt 1.4) für deutsches BPE.

---

#### M7: Lose Dependency-Pins

**Betrifft**: `assistant/requirements.txt`

```
sentence-transformers>=2.2.0   # Kein Upper Bound!
speechbrain>=1.0.0             # Kein Upper Bound!
torchaudio>=2.0.0              # Kein Upper Bound!
```

**Fix**: Upper Bounds setzen:
```
sentence-transformers>=2.2.0,<4.0.0
speechbrain>=1.0.0,<2.0.0
torchaudio>=2.0.0,<3.0.0
```

---

#### M8: Volume-Restore Task Leak

**Betrifft**: `assistant/sound_manager.py` Zeile 606–619

```python
task = asyncio.create_task(_restore_volume())
self._restore_tasks = [t for t in self._restore_tasks if not t.done()]
self._restore_tasks.append(task)
```

Completed Tasks werden nur beim Hinzufügen neuer Tasks aufgeräumt. Ohne neue Tasks wächst die Liste nicht, aber GC'd Tasks bleiben referenziert.

**Fix**: Callback der Task entfernt sich selbst:
```python
task = asyncio.create_task(_restore_volume())
task.add_done_callback(lambda t: self._restore_tasks.discard(t))
self._restore_tasks.add(task)  # set statt list
```

---

### NIEDRIG — Irgendwann

---

#### N1: print() statt logger in Error-Handlern
**Betrifft**: `assistant/main.py` Zeile 79, 144
`print(f"ErrorBufferHandler format error: {e}", file=sys.stderr)` → `logger.exception("ErrorBufferHandler format error")`

#### N2: Circuit-Breaker-Open als DEBUG geloggt
**Betrifft**: `assistant/ha_client.py` Zeile 360, 382
`logger.debug("MindHome Circuit Breaker OPEN")` → Sollte `logger.warning` sein.

#### N3: Inkonsistente Log-Levels
**Betrifft**: `assistant/memory.py` Zeile 163
"Fehlerspeicher-Restore fehlgeschlagen" als `debug` geloggt → Sollte `warning` sein.

#### N4: Docker-Socket gemountet ohne Restrictions
**Betrifft**: `docker-compose.yml` Zeile 37
`/var/run/docker.sock:/var/run/docker.sock` — Erlaubt Container-Escape. Besser: Capabilities einschränken oder Socket-Proxy verwenden.

#### N5: Keine pytest-Konfiguration
Kein `pyproject.toml`, `pytest.ini`, oder `setup.cfg` gefunden. Tests können laufen, aber Coverage-Reporting und Marker sind nicht konfiguriert.

#### N6: ChromaDB Version
`chromadb==0.5.23` — Aktuell wäre 0.6+. Upgrade wenn Breaking Changes geprüft.

#### N7: Hardcoded Speaker-Patterns
**Betrifft**: `assistant/sound_manager.py`
Speaker-Entity-Patterns hardcoded statt in `settings.yaml`. Bei neuen Speakern muss Code geändert werden.

#### N8: Kein CI/CD-Pipeline
Keine `.github/workflows/`, `.gitlab-ci.yml` oder ähnliches sichtbar.

#### N9: Room-Light Lookup ist O(n²)
**Betrifft**: `assistant/light_engine.py` Zeile 928–934
```python
def _find_room_for_light(self, entity_id: str, rooms: dict) -> Optional[str]:
    for room_name, room_cfg in rooms.items():
        lights = room_cfg.get("light_entities", [])
        if isinstance(lights, list) and entity_id in lights:
            return room_name
    return None
```
**Fix**: Einmalig ein Reverse-Mapping `{entity_id: room_name}` bauen.

#### N10: Redis maxmemory hardcoded
**Betrifft**: `docker-compose.yml` Zeile 84
`--maxmemory 2gb --maxmemory-policy allkeys-lru` hardcoded. Sollte via `.env` konfigurierbar sein.

---

### Was GUT ist (kein Handlungsbedarf)

- **Prompt-Injection-Schutz**: Stark — Regex + NFKC-Normalisierung + Sanitization in `context_builder.py`
- **Tool-Calling Security**: Whitelist als `frozenset`, keine `exec`/`eval`/`subprocess` in Tool-Pfaden
- **Circuit Breaker**: Sauber implementiert für Ollama, HA, Redis
- **3-Tier Model Cascade**: Deep → Smart → Fast mit Auto-Fallback
- **Streaming**: Token-by-token mit Think-Tag-Filtering
- **Sensitive-Data-Masking**: Regex reduziert Tokens/Passwörter/Keys in allen Logs
- **Graceful Degradation**: Komponenten degradieren einzeln statt Gesamtausfall
- **Config-Architektur**: Pydantic Settings + YAML Overrides + .env — sauber getrennt
- **Health-Checks**: Docker und `/health`-Endpoint mit Komponenten-Status
- **Request-Tracing**: RequestContextMiddleware für Request-IDs

---

### Empfohlene Reihenfolge

```
Sofort (vor jedem Feature-Bau):
  K1 N+1 Redis-Pipeline     → 2h, massiver Performance-Gewinn
  K2 Path Traversal          → 30 Min, Security-Fix
  K3 Blocking subprocess     → 30 Min, async-Fix
  K4 Config Race Condition   → 1h, Locks hinzufügen

Diese Woche:
  K5 Decay-Loop batchen      → 2h
  H1 ChromaDB Retry          → 1h
  H2 Token-Lock              → 30 Min
  H3 Light Error-Handling    → 1h
  H5 PUT/DELETE Timeout      → 30 Min

Nächster Sprint:
  H4 Init-Reihenfolge        → 2h
  H6 Paralleler Startup      → 3h
  M1–M8 Medium-Issues        → je 30 Min–2h

Später:
  N1–N10 Low-Prio Cleanup    → je 15–30 Min
```

---
