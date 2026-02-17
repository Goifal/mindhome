# MindHome Phase 8 — Implementierungsplan
# "Jarvis Gedaechtnis & Vorausdenken" (7 Features) — ABGESCHLOSSEN

> **Stand:** 2026-02-17
> **Version:** v0.9.6 → v0.9.8
> **Basis:** Assistant v0.9.6 (Phase 7 fertig)
> **Status:** ALLE 7 FEATURES IMPLEMENTIERT

---

## Strategie

Phase 8 wird in **3 Batches** mit **~6 Commits** implementiert:

1. **Gedaechtnis-Erweiterung** (Explizites Notizbuch, Wissensabfragen, Konversations-Kontinuitaet)
2. **Vorausdenken** (Anticipatory Actions, Intent-Extraktion, Was-waere-wenn)
3. **Langzeit-Anpassung** (Personality-Metrics, Summarizer-Evolution)

### Commit-Plan (~6 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump to v0.9.7 + Phase 8 plan` | 0 | Version bump |
| 2 | `feat(memory): Add explicit notebook + knowledge queries + conversation continuity` | 1 | #8.2, #8.3, #8.6 |
| 3 | `feat(brain): Add intent routing + what-if simulation` | 1 | #8.3, #8.4 |
| 4 | `feat(anticipation): Add anticipation engine + intent tracker` | 2 | #8.1, #8.5 |
| 5 | `feat(personality): Add long-term personality metrics + evolution` | 3 | #8.7 |
| 6 | `docs: Mark Phase 8 complete` | 3 | Docs |

---

## Batch 0: Version Bump

**Datei:** `config/settings.yaml`
```yaml
assistant:
  version: "0.9.7"
```

---

## Batch 1: Gedaechtnis-Erweiterung (Commits 2-3)

### Feature 8.2: Explizites Wissens-Notizbuch

**Datei:** `semantic_memory.py` — Neue Methoden

- `store_explicit(content, category, person)` — Speichert mit Confidence 1.0
- `search_by_topic(topic, limit)` — Semantische Suche nach Thema
- `forget(topic)` — Loescht Fakten die zum Thema passen
- `get_todays_learnings()` — Neue Fakten seit heute 00:00

**Datei:** `brain.py` — Intent-Erkennung fuer Memory-Befehle
- "Merk dir X" → `store_explicit()`
- "Was weisst du ueber X?" → `search_by_topic()`
- "Vergiss X" → `forget()`
- "Was hast du heute gelernt?" → `get_todays_learnings()`

### Feature 8.3: Wissensabfragen (Intent-Routing)

**Datei:** `brain.py` — Neuer Intent-Classifier

- Drei Pfade:
  1. Smart-Home-Befehl → Function Calling (bestehend)
  2. Wissensfrage → LLM direkt (ohne Tools, 14B)
  3. Erinnerungsfrage → Memory-Suche
- Erkennung via Keywords + LLM-basierter Fallback
- Wissensfragen brauchen keine HA-Tools

### Feature 8.6: Konversations-Kontinuitaet

**Datei:** `memory.py` — Neue Methoden

- `mark_conversation_pending(topic, context)` — Flaggt offenes Thema
- `get_pending_conversations()` — Offene Themen abrufen
- `resolve_conversation(topic)` — Thema als erledigt markieren
- Redis-Key `mha:pending_topics` mit 24h TTL

**Datei:** `brain.py` — Check bei neuer Interaktion
- Wenn pending topic existiert und > 10 Min vergangen:
  "Wir waren vorhin bei [Thema] — noch relevant?"

---

## Batch 2: Vorausdenken (Commit 4)

### Feature 8.1: Anticipatory Actions

**Neue Datei:** `assistant/anticipation.py`

- `AnticipationEngine` — Pattern Detection auf Action-History
- Muster-Typen:
  - Zeit-Muster: "Jeden Freitag 18 Uhr → TV an"
  - Sequenz-Muster: "Licht an → Heizung hoch → Musik"
  - Kontext-Muster: "Regen + Abend → Rolladen runter"
- Confidence-basierte Vorschlaege:
  - 60-80%: Fragen "Soll ich?"
  - 80-95%: Vorschlagen "Ich bereite vor?"
  - 95%+ bei Level >= 4: Machen + informieren
- Nutzt Redis fuer Action-Log, Feedback-Loop

### Feature 8.5: Aktive Intent-Extraktion

**Neue Datei:** `assistant/intent_tracker.py`

- `IntentTracker` — Speichert erkannte Absichten mit Deadline
- `track_intent(text, person, deadline)` — Neuer Intent
- `get_due_intents()` — Faellige Intents abrufen
- `dismiss_intent(intent_id)` — Intent als erledigt markieren
- Laeuft als Hintergrund-Check (stuendlich)

**Datei:** `memory_extractor.py` — Neuer Prompt-Abschnitt
- Zusaetzlich zu Fakten: Erkennt Absichten mit Zeitangaben
- "Naechstes WE kommen meine Eltern" → Intent: Besuch, Deadline: naechstes WE

---

## Batch 3: Langzeit-Anpassung (Commit 5)

### Feature 8.7: Langzeit-Persoenlichkeitsanpassung

**Datei:** `personality.py` — Neue Methoden

- `track_interaction_metrics(mood, response_accepted)` — Zaehlt Interaktionen
- `get_personality_evolution()` — Aktueller Stand der Entwicklung
- Metrics in Redis:
  - `mha:personality:total_interactions` — Gesamt-Interaktionen
  - `mha:personality:positive_reactions` — Positive Reaktionen
  - `mha:personality:avg_mood` — Durchschnittliche Stimmung
  - `mha:personality:topics_discussed` — Haeufige Themen

**Datei:** `summarizer.py` — Monatliche Personality-Summary
- Neuer Abschnitt in Monats-Summary: Personality-Evolution
- Trends: Wird der User lockerer? Formeller? Gestresster?

---

## Geaenderte/Neue Dateien

### Neue Dateien:
| Datei | Beschreibung |
|-------|-------------|
| `assistant/anticipation.py` | Pattern-Erkennung + Vorschlag-Pipeline |
| `assistant/intent_tracker.py` | Absichten mit Deadline tracken |

### Geaenderte Dateien:
| Datei | Aenderung |
|-------|---------|
| `config/settings.yaml` | Version bump, Anticipation-Config |
| `semantic_memory.py` | Explizites Notizbuch (store_explicit, search_by_topic, forget) |
| `memory_extractor.py` | Intent-Extraktion Prompt |
| `memory.py` | Pending Conversations |
| `brain.py` | Intent-Routing, Memory-Befehle, Was-waere-wenn, Continuity |
| `personality.py` | Personality-Metrics |
| `summarizer.py` | Personality-Evolution Summary |
