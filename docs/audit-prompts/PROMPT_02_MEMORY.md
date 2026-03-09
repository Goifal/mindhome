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

> **[HIER die Konflikt-Karte aus Prompt 1 einfügen, besonders Konflikt C: "Wer bestimmt was Jarvis WEISS?"]**

---

## Das Problem

Jarvis merkt sich **keine Gespräche**. Trotz eines 3-Tier Memory Systems (Redis Working Memory, ChromaDB Episodic, Semantic Facts) funktioniert die Erinnerung nicht.

### Memory-Module im Projekt

| Modul | Aufgabe | Technologie |
|---|---|---|
| `memory.py` | Working Memory | Redis |
| `semantic_memory.py` | Langzeit-Fakten | ChromaDB |
| `conversation.py` | Gesprächsverlauf | ? |
| `conversation_memory.py` | Konversations-Gedächtnis | ? |
| `context_builder.py` | Was tatsächlich im LLM-Prompt landet | Prompt-String |
| `learning_observer.py` | Muster aus Verhalten | ? |

---

## Aufgabe

### Schritt 1 — Dokumentation prüfen

Lies und **verifiziere im Code**:
- `docs/JARVIS_SELF_IMPROVEMENT.md` — 9 Self-Learning Features: Wie viele sind wirklich implementiert?
- `docs/JARVIS_FEATURES_IMPLEMENTATION.md` — Memory-bezogene Bugfixes: Wirklich gefixt?

### Schritt 2 — Kompletten Memory-Datenfluss verfolgen

Verfolge den **exakten Code-Pfad** einer Erinnerung. Lies jeden beteiligten File und jede Funktion:

```
1. User sagt etwas (main.py / brain.py Eingang)
   → Wo genau wird die Nachricht gespeichert?
   → Welche Funktion? Welche Zeile?

2. Vor der LLM-Antwort
   → Wird memory.py aufgerufen um relevante Erinnerungen zu laden?
   → Wird semantic_memory.py abgefragt?
   → Wird conversation.py / conversation_memory.py abgefragt?
   → Werden die Ergebnisse an context_builder.py übergeben?
   → Landen sie im LLM-Prompt?

3. Nach der LLM-Antwort
   → Wird die Konversation gespeichert?
   → Werden Fakten automatisch extrahiert?
   → Werden sie in ChromaDB geschrieben?
   → Werden sie in Redis geschrieben?

4. Bei einem späteren Abruf
   → User fragt "Was habe ich gestern gesagt?"
   → Welcher Code-Pfad wird durchlaufen?
   → Wird ChromaDB korrekt abgefragt?
   → Kommt das Ergebnis im LLM-Prompt an?
```

### Schritt 3 — Spezifische Checks

Prüfe jeden einzelnen Punkt und dokumentiere das Ergebnis mit Code-Referenz:

| # | Check | Ergebnis | Code-Referenz |
|---|---|---|---|
| 1 | Wird `memory.py` in `brain.py` **vor** jeder Antwort aufgerufen? | ? | ? |
| 2 | Wird `memory.py` in `brain.py` **nach** jeder Konversation aufgerufen? | ? | ? |
| 3 | Werden geladene Erinnerungen in den LLM-Prompt **injiziert**? | ? | ? |
| 4 | Redis TTL: Laufen Erinnerungen stillschweigend ab? Welche TTL-Werte? | ? | ? |
| 5 | Async: Werden Memory-Operationen korrekt **awaited**? | ? | ? |
| 6 | Race Condition: Wird die Antwort generiert **bevor** Memory-Abfrage fertig? | ? | ? |
| 7 | ChromaDB: Stimmen die Embeddings? Wird das richtige Modell verwendet? | ? | ? |
| 8 | ChromaDB: Wird überhaupt geschrieben? Oder nur gelesen? | ? | ? |
| 9 | Conversation History: Wird sie als Messages-Array ans LLM übergeben? | ? | ? |
| 10 | Conversation History: Wird sie zwischen Sessions persistiert? | ? | ? |
| 11 | Fakten-Extraktion: Gibt es Code der aus Gesprächen Fakten extrahiert? | ? | ? |
| 12 | Fakten-Extraktion: Wird er aufgerufen? Funktioniert er? | ? | ? |
| 13 | `conversation.py` vs `conversation_memory.py`: Was macht jedes? Überlappen sie? | ? | ? |
| 14 | `learning_observer.py`: Werden gelernte Muster im Prompt verwendet? | ? | ? |

### Schritt 4 — Root Cause finden

Basierend auf den Checks: **Warum genau** funktioniert die Erinnerung nicht?

Mögliche Root Causes (prüfe jede):
- [ ] Memory wird gespeichert aber nie abgerufen
- [ ] Memory wird abgerufen aber nicht in den Prompt injiziert
- [ ] Memory wird in den Prompt injiziert aber nach dem Context-Limit abgeschnitten
- [ ] Redis TTL löscht Erinnerungen zu schnell
- [ ] ChromaDB wird nicht korrekt initialisiert
- [ ] Embeddings passen nicht zum Query-Embedding
- [ ] Async-Fehler: Memory-Abfrage wird nicht awaited
- [ ] Race Condition: Antwort kommt vor Memory-Abruf
- [ ] conversation.py und conversation_memory.py arbeiten gegeneinander
- [ ] Der Code existiert aber wird nie aufgerufen (Dead Code)

### Schritt 5 — Fix implementieren ODER Alternative vorschlagen

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

---

## Output-Format

### 1. Memory-Flow-Diagramm (textuell)

```
User Input → [wo gespeichert?] → [wie abgerufen?] → [wo im Prompt?] → LLM → [was persistiert?]
```
Mit konkreten Funktionsnamen und Datei:Zeile.

### 2. Check-Tabelle (ausgefüllt)

Die 14 Checks aus Schritt 3, alle beantwortet mit Code-Referenzen.

### 3. Root Cause Analyse

Die wahrscheinlichste(n) Ursache(n) mit Beweis aus dem Code.

### 4. Fix oder Alternative

Konkreter Code für den Fix, oder Vorschlag für eine alternative Implementierung mit Code-Skizze.

### 5. Bug-Report

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

- **Nur Memory** in diesem Prompt — keine anderen Bugs jagen
- Folge dem Code, nicht der Dokumentation
- Wenn du einen `await` vermisst oder eine Race Condition findest: Datei + Zeile + Beweis
- Prüfe ob die 4 Memory-Module **überhaupt voneinander wissen** oder isolierte Silos sind
- Einfach > Komplex: Wenn SQLite + Sliding Window robuster ist als 3-Tier mit Redis+ChromaDB, sag es
