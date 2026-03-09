# Jarvis Finetuning — Schritt-für-Schritt Umbauplan

**Datum**: 2026-03-09
**Ziel**: Jarvis der sich erinnert, mitdenkt, und Charakter hat — gleichzeitig, nicht abwechselnd.
**Prinzip**: Konsolidieren vor Expandieren. Kein neues Feature bis das Fundament steht.
**Reihenfolge ist kritisch**: Phase 0 → 1 → 2 → 3. Jede Phase baut auf der vorherigen auf.

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
