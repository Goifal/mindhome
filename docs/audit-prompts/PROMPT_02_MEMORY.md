# Prompt 2: Memory-System — End-to-End-Analyse & Reparatur

## Rolle

Du bist ein Elite-Software-Architekt und KI-Ingenieur mit tiefem Wissen in:

- **RAG & Memory**: ChromaDB, FAISS, Sentence-Transformers, Embedding-Modelle, Cosine Similarity, MemGPT-Patterns
- **Conversational AI**: Dialogue State, Multi-Turn Memory, Sliding Window, Session Handling
- **Python**: AsyncIO, Redis, SQLite, aiohttp, Type Hints
- **LLM-Engineering**: Context Window Management, Token-Budgetierung, Prompt Design

Du kennst **J.A.R.V.I.S. aus dem MCU** als Goldstandard:
- Merkt sich **alles** — Gespräche, Vorlieben, Muster, Gewohnheiten
- Lernt aus Korrekturen und macht denselben Fehler **nie zweimal**
- Verbindet Informationen aus verschiedenen Quellen zu einem **kohärenten Bild**

---

## Kontext aus Prompt 1

> **Wenn du Prompt 1 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Block) automatisch als Kontext. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier den Kontext-Block aus Prompt 1 ein, besonders Konflikt C ("Wer bestimmt was Jarvis WEISS?") und Konflikt F ("Assistant ↔ Addon Interaktion").

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem **GitHub-Quellcode**, nicht mit einem laufenden System. Redis, ChromaDB und Ollama sind nicht verfügbar. Du musst ALLES aus dem Code herauslesen — jede Zeile, jeden Funktionsaufruf, jeden Key-Namen, jeden TTL-Wert.

---

## Das Problem

Jarvis merkt sich **keine Gespräche**. Trotz eines 3-Tier Memory Systems (Redis Working Memory, ChromaDB Episodic, Semantic Facts) funktioniert die Erinnerung nicht.

### ALLE Memory-bezogenen Module

Es gibt **nicht 4, sondern mindestens 12** Module die mit Memory/Wissen zu tun haben:

> **Achtung**: `conversation.py` existiert nur als HA-Integration (`ha_integration/.../conversation.py`) — es ist eine Bridge zwischen der HA Voice Pipeline und dem Assistant, **kein** Memory-Modul. Das eigentliche Gesprächs-Memory ist `conversation_memory.py`.

| Modul | Aufgabe | Technologie |
|---|---|---|
| `memory.py` | Working Memory | Redis |
| `semantic_memory.py` | Langzeit-Fakten & Vektor-Suche | ChromaDB |
| `conversation_memory.py` | Konversations-Gedächtnis & Gesprächsverlauf | ? |
| `memory_extractor.py` | Extrahiert Fakten aus Gesprächen | ? |
| `correction_memory.py` | Lernt aus User-Korrekturen | ? |
| `dialogue_state.py` | Konversations-Zustandsmaschine | ? |
| `learning_observer.py` | Muster aus Verhalten | ? |
| `learning_transfer.py` | Wissenstransfer zwischen Domains | ? |
| `knowledge_base.py` | Lokales Wissens-Repository | ? |
| `context_builder.py` | Was tatsächlich im LLM-Prompt landet | Prompt-String |
| `embeddings.py` | Embedding-Modell-Verwaltung | ? |
| `embedding_extractor.py` | Text → Embedding-Vektor | ? |

**Kritische Frage**: Wie hängen diese 12 Module zusammen? Oder sind es 12 isolierte Inseln?

---

## Aufgabe

### Schritt 1 — Dokumentation prüfen

Lies und **verifiziere im Code**:
- `docs/JARVIS_SELF_IMPROVEMENT.md` — 9 Self-Learning Features: Wie viele sind wirklich implementiert?
- `docs/JARVIS_FEATURES_IMPLEMENTATION.md` — Memory-bezogene Bugfixes: Wirklich gefixt?

### Schritt 2 — Memory-Modul-Abhängigkeiten kartieren

Bevor du den Datenfluss verfolgst: Lies **jedes** der 12 Module und erstelle eine **Abhängigkeitskarte**:

| Modul | Importiert von | Wird importiert von | Shared State? |
|---|---|---|---|
| `memory.py` | ? | ? | ? |
| `semantic_memory.py` | ? | ? | ? |
| `conversation_memory.py` | ? | ? | ? |
| `memory_extractor.py` | ? | ? | ? |
| `correction_memory.py` | ? | ? | ? |
| `dialogue_state.py` | ? | ? | ? |
| `learning_observer.py` | ? | ? | ? |
| `learning_transfer.py` | ? | ? | ? |
| `knowledge_base.py` | ? | ? | ? |
| `embeddings.py` | ? | ? | ? |
| `embedding_extractor.py` | ? | ? | ? |
| `context_builder.py` | ? | ? | ? |

**Ziel**: Verstehen ob es einen kohärenten Memory-Stack gibt oder 12 isolierte Systeme.

#### Claude Code Strategie — Memory-Module parallel lesen

Lies alle 12 Memory-Module **parallel** mit Read (5-7 gleichzeitig):
- **Batch 1**: `memory.py`, `semantic_memory.py`, `conversation_memory.py`, `memory_extractor.py`, `correction_memory.py`
- **Batch 2**: `dialogue_state.py`, `learning_observer.py`, `learning_transfer.py`, `knowledge_base.py`
- **Batch 3**: `embeddings.py`, `embedding_extractor.py`, `context_builder.py`

### Schritt 2b — Datenbank-Schemas aus dem Code extrahieren

#### Claude Code Strategie — Grep für Bulk-Suche

**Redis**: Nutze Grep um ALLE Redis-Aufrufe projektübergreifend zu finden:
```
Grep: pattern="redis\.|\.set\(|\.get\(|\.delete\(|\.expire\(|\.ttl\(" path="assistant/assistant/" output_mode="content"
```

Dokumentiere:

| Key-Pattern | Modul | Operation (SET/GET/DEL) | TTL | Datenformat |
|---|---|---|---|---|
| ? | memory.py | ? | ? | ? |
| ? | ... | ? | ? | ? |

**ChromaDB**: Nutze Grep um ALLE ChromaDB-Aufrufe zu finden:
```
Grep: pattern="chroma|collection\.|\.add\(|\.query\(|\.delete\(" path="assistant/assistant/" output_mode="content"
```

Dokumentiere:

| Collection-Name | Modul | Operation (add/query/delete) | Embedding-Modell | Metadaten-Schema |
|---|---|---|---|---|
| ? | semantic_memory.py | ? | ? | ? |
| ? | ... | ? | ? | ? |

**SQLite**: Nutze Grep:
```
Grep: pattern="sqlite|\.execute\(|CREATE TABLE|INSERT INTO" path="." output_mode="content"
```

> **Wichtig**: Nur was im Code steht. Grep findet alle Stellen — dann mit Read die Details prüfen.

### Schritt 3 — Kompletten Memory-Datenfluss verfolgen

Verfolge den **exakten Code-Pfad** einer Erinnerung. Lies jeden beteiligten File und jede Funktion:

```
1. User sagt etwas (main.py / brain.py Eingang)
   → Wo genau wird die Nachricht gespeichert?
   → Welche Funktion? Welche Zeile?
   → Wird dialogue_state.py aktualisiert?

2. Vor der LLM-Antwort
   → Wird memory.py aufgerufen um relevante Erinnerungen zu laden?
   → Wird semantic_memory.py abgefragt?
   → Wird conversation_memory.py abgefragt?
   → Wird correction_memory.py geprüft (frühere Korrekturen)?
   → Wird knowledge_base.py einbezogen?
   → Werden die Ergebnisse an context_builder.py übergeben?
   → Landen sie im LLM-Prompt?
   → Wie viele Token verbraucht der Memory-Kontext?

3. Nach der LLM-Antwort
   → Wird die Konversation gespeichert?
   → Wird memory_extractor.py aufgerufen um Fakten zu extrahieren?
   → Werden Fakten in ChromaDB geschrieben? (semantic_memory.py)
   → Werden sie in Redis geschrieben? (memory.py)
   → Wird learning_observer.py informiert?
   → Wird learning_transfer.py aktualisiert?

4. Bei einem späteren Abruf
   → User fragt "Was habe ich gestern gesagt?"
   → Welcher Code-Pfad wird durchlaufen?
   → Welches Embedding-Modell wird für die Query verwendet? (embeddings.py)
   → Wird ChromaDB korrekt abgefragt?
   → Kommt das Ergebnis im LLM-Prompt an?
```

### Schritt 4 — Spezifische Checks

Prüfe jeden einzelnen Punkt und dokumentiere das Ergebnis mit Code-Referenz:

| # | Check | Ergebnis | Code-Referenz |
|---|---|---|---|
| 1 | Wird `memory.py` in `brain.py` **vor** jeder Antwort aufgerufen? | ? | ? |
| 2 | Wird `memory.py` in `brain.py` **nach** jeder Konversation aufgerufen? | ? | ? |
| 3 | Werden geladene Erinnerungen in den LLM-Prompt **injiziert**? | ? | ? |
| 4 | Redis TTL: Laufen Erinnerungen stillschweigend ab? Welche TTL-Werte? | ? | ? |
| 5 | Async: Werden Memory-Operationen korrekt **awaited**? | ? | ? |
| 6 | Race Condition: Wird die Antwort generiert **bevor** Memory-Abfrage fertig? | ? | ? |
| 7 | ChromaDB: Wird das richtige Embedding-Modell verwendet? | ? | ? |
| 8 | ChromaDB: Wird überhaupt geschrieben? Oder nur gelesen? | ? | ? |
| 9 | Conversation History: Wird sie als Messages-Array ans LLM übergeben? | ? | ? |
| 10 | Conversation History: Wird sie zwischen Sessions persistiert? | ? | ? |
| 11 | `memory_extractor.py`: Wird er aufgerufen? Extrahiert er korrekt Fakten? | ? | ? |
| 12 | `correction_memory.py`: Werden Korrekturen gespeichert und bei nächster Antwort genutzt? | ? | ? |
| 13 | `dialogue_state.py`: Wird der State korrekt verwaltet? Multi-Turn? | ? | ? |
| 14 | `conversation_memory.py`: Verwaltet es sowohl Kurz- als auch Langzeit-Konversationen? | ? | ? |
| 15 | `learning_observer.py`: Werden gelernte Muster im Prompt verwendet? | ? | ? |
| 16 | `learning_transfer.py`: Funktioniert Wissenstransfer? Oder Dead Code? | ? | ? |
| 17 | `knowledge_base.py`: Was enthält es? Wird es im Prompt genutzt? | ? | ? |
| 18 | `embeddings.py` vs `embedding_extractor.py`: Redundanz? Verschiedene Modelle? | ? | ? |
| 19 | **Addon-Daten**: Weiß der Assistant was der Addon über Muster/Verhalten weiß? | ? | ? |
| 20 | **Addon-DB**: Was speichert `addon/db.py` / `addon/models.py`? Welche Tabellen? Welche Daten? | ? | ? |
| 21 | **Addon-Pattern-Engine**: Was lernt `addon/pattern_engine.py`? Werden diese Muster dem Assistant zugänglich gemacht? | ? | ? |
| 22 | **Addon-Event-Bus**: Werden Memory-relevante Events über `addon/event_bus.py` an den Assistant weitergeleitet? | ? | ? |

> **Claude Code**: Für Checks 19–22 nutze `Grep: pattern="pattern_engine\|db\.\|models\.\|event_bus" path="addon/"` und dann Read für Details.

### Schritt 5 — Root Cause finden

Basierend auf den Checks: **Warum genau** funktioniert die Erinnerung nicht?

Mögliche Root Causes (prüfe jede):
- [ ] Memory wird gespeichert aber nie abgerufen
- [ ] Memory wird abgerufen aber nicht in den Prompt injiziert
- [ ] Memory wird in den Prompt injiziert aber nach dem Context-Limit abgeschnitten
- [ ] Redis TTL löscht Erinnerungen zu schnell
- [ ] ChromaDB wird nicht korrekt initialisiert
- [ ] Embeddings passen nicht zum Query-Embedding (falsches Modell?)
- [ ] Async-Fehler: Memory-Abfrage wird nicht awaited
- [ ] Race Condition: Antwort kommt vor Memory-Abruf
- [ ] conversation_memory.py speichert/lädt nicht korrekt
- [ ] memory_extractor.py wird nie aufgerufen (Dead Code)
- [ ] correction_memory.py wird nie abgefragt
- [ ] dialogue_state.py wird nicht korrekt aktualisiert
- [ ] 12 isolierte Memory-Silos ohne Verbindung
- [ ] Der Code existiert aber wird nie aufgerufen (Dead Code)

### Schritt 6 — Fix implementieren ODER Alternative vorschlagen

**Option A**: Das aktuelle System reparieren, wenn die Bugs behebbar sind.

**Option B**: Falls das System fundamental kaputt ist, eine **einfachere, robustere Alternative** implementieren. Bewerte diese Ansätze:

| Ansatz | Pro | Contra | Empfehlung? |
|---|---|---|---|
| **SQLite statt Redis** für History | Persistent, kein TTL | Langsamer für Echtzeit | ? |
| **In-Memory-Liste** in brain.py | Einfach, schnell, zuverlässig | Verlust bei Restart | ? |
| **Sliding Window** (letzte N Nachrichten) | Vorhersagbar, einfach | Kein Langzeitgedächtnis | ? |
| **MemGPT-Pattern** | Bewährt, skalierbar | Komplex zu implementieren | ? |
| **Hybrid**: Sliding Window + SQLite | Kurzzeitgedächtnis + Archiv | Mittlere Komplexität | ? |
| **Aktuelles System fixen** | Kein Umbau nötig | Evtl. Design-Fehler | ? |
| **Konsolidierung**: 12 Module → 3 | Weniger Silos, klarer | Umbau nötig | ? |

---

## Output-Format

### 1. Memory-Abhängigkeitskarte (ausgefüllt)

Die Tabelle aus Schritt 2 — wer importiert wen, wer teilt State.

### 2. Memory-Flow-Diagramm (textuell)

```
User Input → [wo gespeichert?] → [wie abgerufen?] → [wo im Prompt?] → LLM → [was persistiert?]
```
Mit konkreten Funktionsnamen und Datei:Zeile.

### 3. Check-Tabelle (ausgefüllt)

Die 19 Checks aus Schritt 4, alle beantwortet mit Code-Referenzen.

### 4. Root Cause Analyse

Die wahrscheinlichste(n) Ursache(n) mit Beweis aus dem Code.

### 5. Dead-Code-Liste

Module die existieren aber **nie aufgerufen** werden.

### 6. Fix oder Alternative

Konkreter Code für den Fix, oder Vorschlag für eine alternative Implementierung mit Code-Skizze.

### 7. Bug-Report

Für jeden Memory-Bug:
```
### [SEVERITY] Kurzbeschreibung
- **Datei**: path/to/file.py:123
- **Problem**: Was ist falsch
- **Auswirkung**: Was der User merkt
- **Fix**: Code-Änderung
```

---

## Regeln

### Gründlichkeits-Pflicht

> **Lies JEDE der 12 Memory-Dateien mit Read. Lies JEDE Funktion. Folge JEDEM Aufruf.**
>
> Wenn du schreibst "wird aufgerufen" — zeige die Zeile. Wenn du schreibst "wird nicht aufgerufen" — **beweise es mit Grep** (z.B. `Grep: pattern="memory_extractor" path="assistant/"` zeigt 0 Treffer). Keine Vermutungen.

### Claude Code Tool-Einsatz in diesem Prompt

| Aufgabe | Tool | Beispiel |
|---|---|---|
| 12 Memory-Module lesen | **Read** (parallel, 3 Batches) | Siehe Strategie oben |
| Redis-Aufrufe finden | **Grep** | `pattern="redis\.\|\.set\(\|\.get\("` |
| ChromaDB-Aufrufe finden | **Grep** | `pattern="chroma\|collection\."` |
| Wer ruft memory.store() auf? | **Grep** | `pattern="memory\.store\|memory\.save"` |
| Wird Modul X importiert? | **Grep** | `pattern="from.*memory_extractor import"` |
| Fehlende awaits finden | **Grep** | `pattern="[^await ]self\.memory\."` |
| Addon-Memory prüfen | **Grep** + **Read** | `pattern="pattern_engine\|db\." path="addon/"` |

- **Nur Memory** in diesem Prompt — keine anderen Bugs jagen
- Folge dem Code, nicht der Dokumentation
- **ALLE 12 Module** prüfen — nicht nur die offensichtlichen 4
- Wenn du einen `await` vermisst oder eine Race Condition findest: Datei + Zeile + Beweis
- Prüfe ob die Module **voneinander wissen** oder isolierte Silos sind
- Einfach > Komplex: Wenn weniger Module robuster sind, sag es
- Prüfe auch ob der **Addon** eigene Memory/Pattern-Daten hat die dem Assistant fehlen

---

## ⚡ Übergabe an Prompt 3

Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block** für Prompt 3:

```
## KONTEXT AUS PROMPT 2: Memory-Analyse

### Memory-Abhängigkeitskarte
[Welches Modul importiert/nutzt welches — kompakt]

### Memory-Flow (Ist-Zustand)
[User Input → Speicherung → Abruf → Prompt — mit Datei:Zeile]

### Root Cause
[Warum funktioniert Memory nicht — 2-3 Sätze]

### Empfohlener Fix
[Welcher Ansatz, warum — 2-3 Sätze]

### Memory-Bugs
[Liste: Severity + Modul + Kurzbeschreibung]

### Dead-Code-Module
[Module die existieren aber nie aufgerufen werden]
```

**Wenn du Prompt 3 in derselben Konversation erhältst**: Setze diesen Kontext-Block + den aus Prompt 1 automatisch ein.
