# Masterplan: MindHome Jarvis → MCU Jarvis

**Datum**: 2026-03-09
**Ziel**: Jarvis der sich erinnert, mitdenkt, und Charakter hat — gleichzeitig, nicht abwechselnd.
**Prinzip**: Konsolidieren vor Expandieren. Kein neues Feature bis das Fundament steht.

---

## Übersicht: 4 Phasen

| Phase | Name | Ziel | Geschätzter Umfang |
|-------|------|------|-------------------|
| **0** | Sofort-Fixes | Bugs die Daten verlieren oder Token verschwenden | 5 gezielte Eingriffe |
| **1** | Memory Gateway | Ein Interface für alle Gedächtnissysteme | 1 neue Datei, 3 Dateien anpassen |
| **2** | Prompt-Diät | System-Prompt halbieren, Memory auf Prio 0 | 2 Dateien anpassen |
| **3** | Pipeline-Refactor | brain.py aufbrechen in testbare Stages | brain.py → 5-6 Dateien |

**Reihenfolge ist kritisch**: Phase 0 → 1 → 2 → 3. Jede Phase baut auf der vorherigen auf.

---

## Phase 0: Sofort-Fixes (Bugs die jetzt Daten vernichten)

Kein Umbau, nur gezielte Bugfixes. Kann sofort gemacht werden.

### Fix 0.1: `clear_all_memory()` — fehlende Keys

**Datei**: `assistant/assistant/memory.py` Zeile 493-507

**Problem**: `mha:memory:projects`, `mha:memory:open_questions`, `mha:memory:summary:*` werden bei Memory-Reset nicht gelöscht.

**Lösung**: Drei Zeilen in die Scan-Schleife einfügen:
```python
async for key in self.redis.scan_iter(match="mha:memory:*"):
    keys.append(key)
```

### Fix 0.2: Doppelte `conv_memory`-Sektion

**Datei**: `assistant/assistant/brain.py` Zeile 2800 und 2922

**Problem**: `conv_memory` wird zweimal als Sektion hinzugefügt (Prio 2 + Prio 3). Doppelte Token-Verschwendung.

**Lösung**: Die zweite Instanz (Zeile 2921-2924) entfernen. Die Prio-2-Version (Zeile 2800) behalten — sie hat die höhere Priorität und ist sowieso besser.

### Fix 0.3: `_last_executed_action` persistent machen

**Datei**: `assistant/assistant/brain.py` Zeile 352-354

**Problem**: Überlebt keinen Restart. "Mach das wieder aus" funktioniert nur innerhalb einer Session.

**Lösung**: Bei jeder Aktion in Redis speichern, beim Start aus Redis laden:
```python
# Speichern (nach Aktion-Ausführung):
await self.memory.redis.setex("mha:last_action", 3600, json.dumps({
    "action": func_name,
    "args": func_args,
}))

# Laden (in initialize()):
raw = await self.memory.redis.get("mha:last_action")
if raw:
    data = json.loads(raw)
    self._last_executed_action = data["action"]
    self._last_executed_action_args = data["args"]
```

TTL von 1 Stunde — danach ist "mach das wieder aus" ohnehin nicht mehr sinnvoll.

### Fix 0.4: Addon-History auf Redis-Fallback

**Datei**: `addon/rootfs/opt/mindhome/routes/chat.py`

**Problem**: `/api/chat/history` gibt nur die In-Memory-Liste zurück. Nach Addon-Restart: leer.

**Lösung**: Wenn die In-Memory-Liste leer ist, History vom Assistant-Server holen:
```python
@chat_bp.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    with _history_lock:
        if not _conversation_history:
            # Fallback: History vom Assistant laden
            try:
                resp = requests.get(f"{assistant_url}/api/assistant/conversations", timeout=5)
                if resp.ok:
                    return jsonify(resp.json())
            except Exception:
                pass
        # ... bestehende Logik
```

Dafür braucht der Assistant einen neuen Endpoint `/api/assistant/conversations` der die Redis Working Memory zurückgibt. Der existiert noch nicht, ist aber trivial.

### Fix 0.5: Fact Decay Benachrichtigung

**Datei**: `assistant/assistant/semantic_memory.py` Zeile 334-411

**Problem**: Fakten werden still gelöscht.

**Lösung**: Vor dem Löschen den Fakt in eine Redis-Liste `mha:decay:deleted` schreiben. Ein neuer API-Endpoint `/api/assistant/memory/decayed` kann diese Liste zurückgeben. Optional: Proaktive Meldung wenn wichtige Fakten (confidence > 0.5) gelöscht werden.

```python
if new_confidence < 0.2:
    # Fakt merken bevor er gelöscht wird
    if self.redis:
        await self.redis.lpush("mha:decay:deleted", json.dumps({
            "content": data.get("content", ""),
            "person": data.get("person", ""),
            "category": data.get("category", ""),
            "deleted_at": datetime.now().isoformat(),
        }))
        await self.redis.ltrim("mha:decay:deleted", 0, 99)  # Max 100
    await self.delete_fact(fact_id)
    deleted += 1
```

---

## Phase 1: Memory Gateway

**Ziel**: Ein einziges Interface das auf "Was ist relevant?" die richtige Antwort gibt.

### 1.1 Neue Datei: `assistant/assistant/memory_gateway.py`

Diese Klasse orchestriert ALLE bestehenden Memory-Systeme. Sie ersetzt NICHT die einzelnen Systeme — sie ist die Fassade davor.

```python
class MemoryGateway:
    """Einheitliches Gedächtnis-Interface für den LLM-Kontext.

    Fragt alle Memory-Systeme ab und liefert einen einzigen,
    kompakten, priorisierten Memory-Block zurück.
    Max 500 Tokens, aber die RICHTIGEN 500 Tokens.
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
        max_tokens: int = 500,
    ) -> str:
        """Liefert einen einzigen, kompakten Memory-Block.

        Priorisierung:
        1. Semantische Fakten über die Person (immer)
        2. Relevante vergangene Gespräche (per Vektor-Suche)
        3. Aktive Projekte und offene Fragen
        4. Relevante Korrekturen
        5. Emotionaler Kontext

        Alles zusammengefasst in einem Block, nicht als separate Sektionen.
        """
```

### Wie der Memory-Block aussieht

Statt 6 separate Sektionen im System-Prompt:
```
ERINNERUNGEN:
• Max bevorzugt 21° im Büro, Lisa mag es wärmer (23°)
• Max arbeitet an Projekt "Gartenhaus" (3 Meilensteine erreicht)
• Offene Frage: Welcher Estrich für die Werkstatt?
• Letztes Gespräch zum Thema: Vor 2 Tagen über Holzauswahl gesprochen
• Korrektur: "Schlafzimmer" meint immer das obere Schlafzimmer
```

Ein Block. Kompakt. Immer dabei. Prio 0.

### 1.2 Parallele Abfrage aller Systeme

Intern fragt der Gateway alle Systeme parallel ab (wie der bestehende mega-gather, aber gezielter):

```python
async def get_relevant_context(self, user_text, person, max_tokens=500):
    # Alles parallel abfragen
    facts, episodes, projects, questions, corrections, emotional = await asyncio.gather(
        self.semantic.search_facts(user_text, limit=5, person=person),
        self.memory.search_memories(user_text, limit=3),
        self.conversation.get_projects(status="active"),
        self.conversation.get_open_questions(person=person),
        self.correction.get_relevant_corrections(person=person),
        self._get_emotional_context(person),
        return_exceptions=True,
    )

    # Priorisieren und zusammenfassen
    return self._compile_memory_block(
        facts, episodes, projects, questions, corrections, emotional,
        max_tokens=max_tokens,
    )
```

### 1.3 Integration in brain.py

In `brain.py` wird der Gateway in `__init__` erstellt und in `initialize()` verkabelt:

```python
# __init__:
self.memory_gateway = MemoryGateway(
    self.memory, self.memory.semantic,
    self.conversation_memory, self.correction_memory,
)

# In process() — STATT der 6 separaten Memory-Sektionen:
memory_block = await self.memory_gateway.get_relevant_context(
    user_text=text, person=person or "", max_tokens=500,
)
# Dieser Block wird als EINZIGE Memory-Sektion mit Prio 0 eingefügt
```

### 1.4 Was sich ändert, was bleibt

| Datei | Änderung |
|-------|----------|
| `memory_gateway.py` | **NEU** — Fassade über alle Memory-Systeme |
| `brain.py` | Gateway statt 6 separate Memory-Abfragen im mega-gather. Sektionen `memory`, `conv_memory` (beide!), `continuity`, `experiential`, `correction_ctx` durch EINEN Gateway-Block ersetzen |
| `memory.py` | **Unverändert** — bleibt als Backend |
| `semantic_memory.py` | **Unverändert** — bleibt als Backend |
| `conversation_memory.py` | **Unverändert** — bleibt als Backend |
| `correction_memory.py` | **Unverändert** — bleibt als Backend |

**Kein bestehendes System wird gelöscht oder umgebaut.** Der Gateway ist eine neue Schicht DARÜBER.

---

## Phase 2: Prompt-Diät

**Ziel**: System-Prompt von ~3000 auf ~1200 Tokens. Memory bekommt Prio 0.

### 2.1 Personality-Prompt komprimieren

**Datei**: `assistant/assistant/personality.py` → `build_system_prompt()`

Der aktuelle System-Prompt enthält:
- Charakter-Definition (~300 Tokens)
- Formality-Section (~100 Tokens)
- Humor-Section (~200 Tokens)
- Mood-Section (~100 Tokens)
- Self-Irony-Section (~80 Tokens)
- Empathy-Section (~100 Tokens)
- Complexity-Section (~50 Tokens)
- Person-Addressing (~80 Tokens)
- Proaktives Mitdenken (~50 Tokens)
- Engineering-Diagnose (~50 Tokens)
- Self-Awareness (~80 Tokens)
- Conversation-Callbacks (~100 Tokens)
- Memory-Callbacks (~100 Tokens)
- Think-Ahead (~100 Tokens)
- **Summe: ~1500+ Tokens nur Personality**

**Ziel-Prompt** (komprimiert auf ~500 Tokens):

```
Du bist {name}, J.A.R.V.I.S. — die KI dieses Hauses.
SPRACHE: NUR Deutsch. Internes Denken ebenfalls Deutsch.
TON: {formality_prompt} {humor_prompt}
VERBOTEN: "Als KI...", "Ich bin ein Sprachmodell", "Es tut mir leid", "Leider", Listen.
STIMMUNG: {mood_addon}
ANREDE: {person_addressing}
MAX {max_sentences} Sätze. FAKTEN-REGEL: Erfinde NICHTS. Unbekannt = ehrlich sagen.
```

Alles in einem Block. Keine separaten Sections. Die variablen Teile (`{formality_prompt}`, `{humor_prompt}`, `{mood_addon}`) werden zur Laufzeit eingefügt — aber als EIN String, nicht als additive Blöcke.

### 2.2 Szenen-Intelligenz nur bei Bedarf

**Datei**: `assistant/assistant/brain.py`

`SCENE_INTELLIGENCE_PROMPT` ist ~700 Tokens und hat bei Device-Commands Prio 1. Das ist zu viel.

**Lösung**: Zwei Versionen:
- **Mini** (~150 Tokens): Nur die Reasoning-Regeln (Ursache vor Aktion, Kontext beachten)
- **Voll** (~700 Tokens): Mit allen Beispielen — nur bei komplexen Szenen-Anfragen

```python
SCENE_INTELLIGENCE_MINI = """
SZENEN-REGELN:
1. Ursache VOR Aktion prüfen (Fenster offen? Heizung aus?)
2. Kontext beachten (Tageszeit, wer ist da)
3. Einen Schritt weiterdenken (Heizung hoch + Fenster offen = Warnung)
"""
```

Die volle Version nur laden wenn `profile.category == "device_command"` UND der Text Szenen-Keywords enthält ("romantisch", "filmabend", "party", "krank", etc.).

### 2.3 Neue Token-Budget-Prioritäten

Aktuelle Prioritäten vs. neue:

| Sektion | Aktuell | Neu | Begründung |
|---------|---------|-----|------------|
| **Memory Gateway** | (existiert nicht) | **Prio 0** | Jarvis MUSS sich erinnern |
| Szenen-Intelligenz | Prio 1 (bei Device) | **Prio 1 mini / Prio 2 voll** | Mini reicht meistens |
| Mood | Prio 1 | **Prio 1** | Bleibt — wichtig für Tonalität |
| Security | Prio 1 | **Prio 1** | Bleibt — Sicherheit |
| Letzte Aktion | Prio 1 | **Prio 1** | Bleibt — Korrektur-Fähigkeit |
| Model Character Hint | Prio 1 | **Prio 2** | Weniger kritisch |
| Confidence Gate | Prio 1 | **Prio 1** | Bleibt — verhindert Halluzination |
| "Jarvis denkt mit" | Prio 2 | **Prio 2** | Bleibt |
| RAG (Wissensbasis) | Prio 1/3 | **Prio 1** (bei Knowledge) | Bleibt |
| Timer, Zeit | Prio 2 | **Prio 2** | Bleibt |
| Conv Memory (Projekte) | Prio 3 | **→ im Memory Gateway (Prio 0)** | Aufgelöst |
| Continuity | Prio 3 | **→ im Memory Gateway (Prio 0)** | Aufgelöst |
| Experiential | Prio 3 | **→ im Memory Gateway (Prio 0)** | Aufgelöst |
| Correction | Prio 2 | **→ im Memory Gateway (Prio 0)** | Aufgelöst |
| Anomalien | Prio 3 | **Prio 3** | Bleibt |
| Tutorial | Prio 4 | **Entfernen** | Spart Tokens, kaum Nutzen |

### 2.4 Token-Budget Rechnung (Ziel)

```
Modell: num_ctx = 8192 (typisch für qwen3.5:9b)
Reserve für Antwort: 800 Tokens

Verfügbar: 7392 Tokens

System-Prompt (Personality komprimiert):     ~500 Tokens
Memory Gateway (Prio 0, immer):              ~500 Tokens
Szenen-Intelligenz Mini (Prio 1):            ~150 Tokens
Mood + Security + Letzte Aktion (Prio 1):    ~200 Tokens
Sonstige Prio 1:                             ~200 Tokens
= Basis: ~1550 Tokens

Verbleibend für Prio 2+ und Conversations:   ~5842 Tokens
  → Conversations (65%):                     ~3797 Tokens (~38 Nachrichten á 100t)
  → Prio 2+ Sektionen (35%):                ~2045 Tokens

Ergebnis: Memory IMMER dabei + ~19 Gesprächsrunden im Kontext
```

Vergleich mit heute:
- **Heute**: ~3000t System-Prompt + ~2000t Prio 1 = 5000t weg. Verbleiben: ~2400t für alles andere.
- **Neu**: ~1550t Basis. Verbleiben: ~5800t. **Mehr als doppelt so viel Platz für Erinnerungen und Gespräche.**

### 2.5 Character Lock Reminder kürzen

**Datei**: `brain.py` Zeile 3067-3074

Aktuell:
```python
_reminder = (
    "[REMINDER] Du bist J.A.R.V.I.S. — trocken, praezise, Butler-Ton. "
    "Kurz. Keine Listen. Erfinde NICHTS. NUR vorhandene Daten nutzen."
)
```

Kürzen auf:
```python
_reminder = "[J.A.R.V.I.S. Trocken. Präzise. Keine Erfindungen.]"
```

Spart ~50 Tokens pro Gespräch. Klingt wenig, aber bei 19 Gesprächsrunden im Kontext zählt das.

---

## Phase 3: Pipeline-Refactor

**Ziel**: `brain.py` (10.231 Zeilen, eine God-Method) in testbare Stages aufbrechen.

### 3.1 Die Pipeline

```
UserInput
    │
    ▼
┌─────────────────────┐
│  Stage 1: Input      │  input_stage.py
│  - STT Normalisierung│
│  - Speaker Recognition│
│  - Retry-Erkennung   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 2: Shortcuts  │  shortcut_stage.py
│  - Gute Nacht       │
│  - Gäste-Modus      │
│  - Security Confirm  │
│  - Memory Commands   │
│  - Easter Eggs       │
│  - Smalltalk         │
│  - Status-Query      │
└─────────┬───────────┘
          │ (wenn kein Shortcut greift)
          ▼
┌─────────────────────┐
│  Stage 3: Context    │  context_stage.py
│  - Pre-Classification│
│  - Memory Gateway    │
│  - mega-gather       │
│  - Model Selection   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 4: LLM        │  llm_stage.py
│  - Prompt Assembly   │
│  - Token-Budget      │
│  - Conversation Load │
│  - Ollama Call       │
│  - Cascade/Fallback  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 5: Execution  │  execution_stage.py
│  - Tool Call Parse   │
│  - Function Execute  │
│  - Response Filter   │
│  - Refinement        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 6: Post       │  post_stage.py
│  - Memory Store      │
│  - Fact Extraction   │
│  - Emotion Tracking  │
│  - TTS Enhancement   │
│  - Dialogue State    │
└─────────────────────┘
```

### 3.2 Das Pipeline-Objekt

```python
@dataclass
class PipelineContext:
    """Fließt durch alle Stages. Jede Stage liest und schreibt darauf."""

    # Input
    text: str
    person: str
    room: str
    files: list
    voice_metadata: dict
    device_id: str
    stream_callback: Optional[callable]

    # Zwischen-Ergebnisse (werden von Stages gefüllt)
    profile: Optional[RequestProfile] = None
    intent_type: str = ""
    context: dict = field(default_factory=dict)
    memory_block: str = ""
    model: str = ""
    system_prompt: str = ""
    messages: list = field(default_factory=list)

    # Output
    response_text: str = ""
    actions: list = field(default_factory=list)
    tts_data: dict = field(default_factory=dict)
    error: str = ""

    # Flags
    is_shortcut: bool = False  # True = Shortcut hat geantwortet, Pipeline stoppt
```

### 3.3 brain.py wird zum Orchestrator

```python
class AssistantBrain:
    """Orchestriert die Pipeline. Keine Logik mehr direkt hier."""

    async def process(self, text, person=None, room=None, ...):
        ctx = PipelineContext(text=text, person=person, room=room, ...)

        ctx = await self.input_stage.process(ctx)
        ctx = await self.shortcut_stage.process(ctx)
        if ctx.is_shortcut:
            return self._result_from_context(ctx)

        ctx = await self.context_stage.process(ctx)
        ctx = await self.llm_stage.process(ctx)
        ctx = await self.execution_stage.process(ctx)
        ctx = await self.post_stage.process(ctx)

        return self._result_from_context(ctx)
```

### 3.4 Was wohin wandert

| Aktuell in brain.py | Neue Datei | Zeilen (ca.) |
|---------------------|------------|-------------|
| STT-Normalisierung, Speaker Recognition | `stages/input_stage.py` | ~300 |
| Gute-Nacht, Gäste, Security, Memory Commands, Easter Eggs, Smalltalk, Status-Shortcuts | `stages/shortcut_stage.py` | ~1000 |
| Pre-Classification, mega-gather, Model Selection | `stages/context_stage.py` | ~500 |
| System-Prompt Assembly, Token-Budget, Conversation Loading, LLM Call | `stages/llm_stage.py` | ~800 |
| Tool-Call Parsing, Function Execution, Response Filtering | `stages/execution_stage.py` | ~600 |
| Memory Store, Fact Extraction, Emotion Tracking, TTS | `stages/post_stage.py` | ~400 |
| Orchestrierung + Callbacks | `brain.py` (bleibt) | ~800 |
| Helper-Methoden (STT corrections, deterministic tools, etc.) | `brain_helpers.py` | ~1500 |
| Konstanten, Error Templates, Patterns | Bleiben in `brain.py` oder `constants.py` | ~500 |

**brain.py schrumpft von 10.231 auf ~800 Zeilen.**

### 3.5 Was NICHT geändert wird

- Alle ~60 Komponenten (`personality.py`, `memory.py`, etc.) bleiben unverändert
- Alle `__init__`-Instanziierungen bleiben in `brain.py`
- Alle `initialize()`-Verkabelungen bleiben in `brain.py`
- Die `_result()`-Methode bleibt in `brain.py`
- Callback-Methoden (BrainCallbacksMixin) bleiben

Nur die `process()`-Methode und ihre Helpers werden aufgeteilt.

---

## Abhängigkeiten und Reihenfolge

```
Phase 0 (Bugfixes)
    │
    ├── Fix 0.1-0.5 sind UNABHÄNGIG voneinander
    │   → Können parallel oder einzeln gemacht werden
    │
    ▼
Phase 1 (Memory Gateway)
    │
    ├── Braucht: Phase 0 (saubere Memory-Systeme)
    ├── Ergebnis: Ein `memory_block` String pro Request
    │
    ▼
Phase 2 (Prompt-Diät)
    │
    ├── Braucht: Phase 1 (Memory Gateway als Prio 0)
    ├── Ergebnis: ~50% kleinerer System-Prompt, doppelt so viel Platz
    │
    ▼
Phase 3 (Pipeline-Refactor)
    │
    ├── Braucht: Phase 2 (kompakter Prompt macht die Stages übersichtlicher)
    ├── Kann auch VOR Phase 2, aber einfacher danach
    └── Ergebnis: Testbare, wartbare Pipeline
```

---

## Was sich für den User ändert

### Nach Phase 0:
- Memory-Reset funktioniert vollständig (keine verwaisten Projekte)
- "Mach das wieder aus" funktioniert auch nach Restart
- Addon zeigt History auch nach Restart
- User wird informiert wenn Fakten vergessen werden

### Nach Phase 1:
- **Jarvis erinnert sich.** Nicht nur an die letzten 5 Sätze, sondern an Fakten, Projekte, offene Fragen, vergangene Gespräche — alles in einem Block, immer präsent.
- "Weißt du noch was ich gestern über das Gartenhaus gesagt habe?" → Funktioniert.

### Nach Phase 2:
- **Jarvis erinnert sich UND hat Charakter.** Der komprimierte Prompt gibt Platz für beides.
- Gespräche können länger werden ohne Kontextverlust (~19 Runden statt ~5).
- Weniger "Token-Budget dropped: Projekte & offene Fragen" Warnungen.

### Nach Phase 3:
- Für den User: Kein sichtbarer Unterschied.
- Für die Entwicklung: Bugs lassen sich lokalisieren. Neue Features können in einer Stage hinzugefügt werden ohne alle anderen zu beeinflussen. Tests können einzelne Stages testen.

---

## Was NICHT in diesem Masterplan steht

Folgendes wird bewusst NICHT gemacht:

1. **Keine neuen Features** bis Phase 3 abgeschlossen ist
2. **Kein Umbau der einzelnen Memory-Systeme** (memory.py, semantic_memory.py etc.) — sie funktionieren einzeln gut, nur die Integration fehlt
3. **Kein Wechsel der Datenbanken** (Redis, ChromaDB bleiben)
4. **Kein Wechsel des LLM-Backends** (Ollama bleibt)
5. **Keine Änderung am Addon** (außer Fix 0.4)
6. **Keine Änderung an der HA-Integration**
7. **Keine Änderung an den ~60 Komponenten** (Personality, Routines, etc.)

Der Umbau betrifft primär:
- 1 neue Datei (`memory_gateway.py`)
- 6 neue Dateien (`stages/*.py`, `brain_helpers.py`)
- 3 bestehende Dateien anpassen (`brain.py`, `personality.py`, `memory.py`)

---

## Erfolgskriterien

### Jarvis ist MCU-Jarvis wenn:

1. **"Was habe ich letzte Woche über X gesagt?"** → Korrekte Antwort mit Kontext
2. **5 Minuten Gespräch, dann Themenwechsel, dann zurück** → Jarvis hat alles behalten
3. **Restart des Assistants** → Nächste Interaktion nahtlos, als wäre nichts passiert
4. **Token-Budget Log zeigt** → Memory-Block IMMER inkludiert, NIE gedroppt
5. **Personality bleibt** → Sarkasmus, Butler-Ton, Humor — alles noch da, nicht abgeschwächt
6. **Antwortzeit** → Gleich oder besser als vorher (Gateway ist parallel, Prompt ist kleiner)

### Messbar:

- Token-Budget: Memory dropped = 0% (aktuell: geschätzt 30-50%)
- Conversation-Runden im Kontext: >= 15 (aktuell: ~5)
- System-Prompt Tokens: < 1500 (aktuell: ~3000+)
- brain.py Zeilen: < 1000 (aktuell: 10.231)
