# Prompt 4b: Systematische Bug-Jagd — Extended-Module (Priorität 5–9)

## Rolle

Du bist ein Elite-Debugging-Experte für Python, AsyncIO, FastAPI, Flask, Redis, ChromaDB und Home Assistant. Du findest Bugs die andere übersehen — fehlende awaits, stille Exceptions, Race Conditions, Type-Fehler, Security-Lücken.

---

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## ⚠️ Arbeitsumgebung: GitHub-Repository

Du arbeitest mit dem Quellcode, nicht mit einem laufenden System. Prüfe auch wie der Code mit fehlenden `.env`-Werten, fehlenden Credentials und nicht-erreichbaren Services umgeht.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–4a bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier ein:
> - Kontext-Block aus Prompt 1 (Konflikt-Karte)
> - Kontext-Block aus Prompt 2 (Memory-Analyse)
> - Kontext-Block aus Prompt 3a + 3b (Flow-Analyse)
> - Kontext-Block aus Prompt 4a (Core-Bugs — besonders die "Patterns die weitergesucht werden sollten")
>
> **⚠️ OHNE den Kontext-Block aus P4a fehlen dir die Bug-Patterns aus den Core-Modulen!** Die gleichen Fehler-Patterns (z.B. fehlende awaits) wiederholen sich oft in Extended-Modulen. Wenn du den Block nicht hast, starte zuerst mit Prompt 4a.

---

## Aufgabe

Prüfe die **Extended-Module** (Priorität 5–9, 63 Module) systematisch auf die **13 Fehlerklassen** (siehe P04a).

> **Modul-Existenz-Verifikation (Pflicht!)**
> Nicht alle 63 Module muessen existieren. BEVOR du die Batches analysierst:
> ```
> Glob: pattern="*.py" path="assistant/assistant/"
> ```
> Dokumentiere welche Module aus den Listen NICHT gefunden wurden → als "existiert nicht" markieren und ueberspringen.

> **Dieser Prompt ist Teil 2 von 3** der Bug-Jagd:
> - **P04a**: Core-Module (brain, main, memory, context, actions) — ✅ erledigt
> - **P04b** (dieser): Extended-Module (proaktiv, HA, audio, intelligence, resilience, domains) — Priorität 5–9
> - **P04c**: Addon + Security-Audit + Performance-Analyse — Priorität 10–12

---

## Die 13 Fehlerklassen (Kurzreferenz)

| # | Klasse | Kurzform |
|---|---|---|
| 1 | Async-Fehler | Fehlende `await` |
| 2 | Stille Fehler | `except: pass` |
| 3 | Race Conditions | Shared State ohne Lock |
| 4 | None-Fehler | Zugriff auf None |
| 5 | Init-Fehler | Fehlende Dependencies beim Start |
| 6 | API-Fehler | Fehlende Timeouts, Auth |
| 7 | Daten-Fehler | JSON/Redis-Encoding |
| 8 | Config-Fehler | YAML-Werte nicht geladen |
| 9 | Memory Leaks | Listen ohne Limit |
| 10 | Logik-Fehler | Falsche Bedingungen |
| 11 | Security | Unvalidierte Inputs |
| 12 | Resilience | Fehlende Fehlertoleranz |
| 13 | Performance | Sequentielle statt parallele Calls |

---

## Modul-Priorität (nur dieses Prompt!)

### Priorität 5 — Proaktive Systeme
27. `proactive.py` — Proaktive Events
28. `proactive_planner.py` — Proaktive Planung
29. `routine_engine.py` — Routinen
30. `anticipation.py` — Prädiktive Patterns
31. `spontaneous_observer.py` — Ungefragte Beobachtungen
32. `autonomy.py` — Autonomie-Level
33. `self_automation.py` — Auto-Automationen
34. `conditional_commands.py` — If/Then
35. `protocol_engine.py` — Protokolle

### Priorität 6 — HA-Integration & Audio
36. `ha_client.py` — HA-API Client (Timeouts! Auth! Resilience!)
37. `light_engine.py` — Circadian Rhythm
38. `climate_model.py` — Klima-Steuerung
39. `cover_config.py` — Rollladen
40. `camera_manager.py` — Kameras
41. `tts_enhancer.py` — TTS-Aufbereitung
42. `sound_manager.py` — Audio-Wiedergabe
43. `ambient_audio.py` — Hintergrund-Audio
44. `multi_room_audio.py` — Multi-Room
45. `speaker_recognition.py` — Stimm-ID

### Priorität 7 — Intelligence & Self-Improvement
46. `insight_engine.py` — Cross-Referencing
47. `learning_observer.py` — Lern-Patterns
48. `learning_transfer.py` — Wissenstransfer
49. `self_optimization.py` — Self-Improvement
50. `self_report.py` — Diagnostik
51. `feedback.py` — User-Feedback
52. `response_quality.py` — Antwort-Qualität
53. `intent_tracker.py` — Intent-Tracking
54. `outcome_tracker.py` — Outcome-Tracking

### Priorität 8 — Resilience & Sicherheit
55. `error_patterns.py` — Error-Klassifikation
56. `circuit_breaker.py` — Fehlertoleranz
57. `conflict_resolver.py` — Konflikt-Lösung
58. `adaptive_thresholds.py` — Dynamische Schwellwerte
59. `threat_assessment.py` — Bedrohungserkennung
60. `config.py` — Config-Laden
61. `constants.py` — Konstanten
62. `config_versioning.py` — Config-Versionierung

### Priorität 9 — Domain-Assistenten & Monitoring
63. `cooking_assistant.py`, `recipe_store.py`
64. `music_dj.py`
65. `smart_shopping.py`
66. `calendar_intelligence.py`
67. `inventory.py`
68. `web_search.py`, `knowledge_base.py`, `summarizer.py`
69. `ocr.py`, `file_handler.py`
70. `workshop_library.py`, `workshop_generator.py`
71. `health_monitor.py`, `device_health.py`
72. `energy_optimizer.py`, `predictive_maintenance.py`, `repair_planner.py`
73. `visitor_manager.py`, `follow_me.py`
74. `wellness_advisor.py`, `activity.py`
75. `seasonal_insight.py`
76. `explainability.py`
77. `diagnostics.py`
78. `task_registry.py`
79. `timer_manager.py` — Timer-Verwaltung

---

## Spezifische Problemzonen

| Quelle | Behauptung | Verifiziere im Code |
|---|---|---|
| Protocol Engine | 5 Bugs dokumentiert | Alle gefixt? |
| Insight Engine | "70% fertig" | Was fehlt? |
| `circuit_breaker.py` | Wird es überhaupt genutzt? | Von welchen Modulen importiert? |
| `threat_assessment.py` | Funktioniert es? | Wird es aufgerufen? |

---

## Batching-Strategie

> **Arbeite die Module in Batches ab, parallel mit Read (5–7 gleichzeitig):**
>
> - **Batch 5** (Priorität 5 — Proaktiv): `proactive.py`, `proactive_planner.py`, `routine_engine.py`, `anticipation.py`, `spontaneous_observer.py`, `autonomy.py`, `self_automation.py`
> - **Batch 6** (Priorität 5+6): `conditional_commands.py`, `protocol_engine.py`, `ha_client.py`, `light_engine.py`, `climate_model.py`, `cover_config.py`, `camera_manager.py`
> - **Batch 7** (Priorität 6 — Audio): `tts_enhancer.py`, `sound_manager.py`, `ambient_audio.py`, `multi_room_audio.py`, `speaker_recognition.py`
> - **Batch 8** (Priorität 7 — Intelligence): `insight_engine.py`, `learning_observer.py`, `learning_transfer.py`, `self_optimization.py`, `self_report.py`, `feedback.py`, `response_quality.py`
> - **Batch 9** (Priorität 7+8): `intent_tracker.py`, `outcome_tracker.py`, `error_patterns.py`, `circuit_breaker.py`, `conflict_resolver.py`, `adaptive_thresholds.py`, `threat_assessment.py`
> - **Batch 10** (Priorität 8+9): `config.py`, `constants.py`, `config_versioning.py`, `cooking_assistant.py`, `recipe_store.py`, `music_dj.py`, `smart_shopping.py`
> - **Batch 11** (Priorität 9 — Domain): `calendar_intelligence.py`, `inventory.py`, `web_search.py`, `knowledge_base.py`, `summarizer.py`, `ocr.py`, `file_handler.py`
> - **Batch 12** (Priorität 9 — Monitoring): `workshop_library.py`, `workshop_generator.py`, `health_monitor.py`, `device_health.py`, `energy_optimizer.py`, `predictive_maintenance.py`, `repair_planner.py`
> - **Batch 13** (Priorität 9 — Rest): `visitor_manager.py`, `follow_me.py`, `wellness_advisor.py`, `activity.py`, `seasonal_insight.py`, `explainability.py`, `diagnostics.py`, `task_registry.py`, `timer_manager.py`

---

## Output-Format

### Bug-Report-Tabelle

| # | Severity | Modul | Zeile | Fehlerklasse | Beschreibung | Fix |
|---|---|---|---|---|---|---|
| 1 | 🔴 KRITISCH | ha_client.py | :45 | API-Fehler | API-Call ohne Timeout | `timeout=aiohttp.ClientTimeout(total=10)` |

### Dead-Code-Liste

Module oder Funktionen die existieren aber **nie aufgerufen** werden.

### Statistik

```
Gesamt: X Bugs (Priorität 5–9)
  🔴 KRITISCH: X
  🟠 HOCH: X
  🟡 MITTEL: X
  🟢 NIEDRIG: X
```

---

## Regeln

- **Lies JEDES Modul mit Read. KEIN Modul überspringen.**
- **Jeder Bug mit Code-Referenz** (Datei:Zeile)
- **Keine false positives** — nur echte Bugs
- **Nicht fixen** — nur finden und dokumentieren
- **Priorität 5–7 gründlich**, Priorität 8–9 mindestens auf Top-6 Fehlerklassen (Async, Stille Fehler, Race Conditions, None, Init, Performance)

---

## Erfolgskriterien

- Alle Extended-Module (Prio 5-9) gelesen, Bugs nach 13 Fehlerklassen kategorisiert
- Jeder Bug hat: Datei:Zeile, Fehlerklasse, Severity, konkreten Fix-Vorschlag
- Mindestens 30 Bugs in den Extended-Modulen gefunden

### Erfolgs-Check (Schnellpruefung)

```
□ Bug-Report enthaelt Datei:Zeile fuer jeden Bug
□ Bugs sind nach 13 Fehlerklassen kategorisiert
□ Severity-Verteilung dokumentiert (KRITISCH/HOCH/MITTEL/NIEDRIG)
□ Proaktive Module geprueft: grep "async def\|await" proactive.py proactive_planner.py
□ Intelligence-Module geprueft: grep "except\|try:" insight_engine.py anticipation.py learning_observer.py
□ Audio-Module geprueft: grep "await\|async" sound_manager.py tts_enhancer.py multi_room_audio.py
```

---

## ⚡ Übergabe an Prompt 4c

Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block** für Prompt 4c:

```
## KONTEXT AUS PROMPT 4b: Bug-Report (Extended-Module)

### Statistik
Gesamt: X Bugs in Priorität 5–9 (🔴 X, 🟠 X, 🟡 X, 🟢 X)

### Kritische Bugs (🔴)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Hohe Bugs (🟠)
[Liste: Modul + Zeile + Kurzbeschreibung + Fix]

### Dead-Code-Liste
[Module/Funktionen die nie aufgerufen werden]

### Resilience-Findings
[Welche Module fehlen bei Service-Ausfall]
```

**Wenn du Prompt 4c in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke automatisch ein.

---

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN: [Liste der nicht gefixten Issues mit Grund]
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
