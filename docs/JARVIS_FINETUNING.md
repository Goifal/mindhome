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
