# Prompt 6g: Intelligenz-Qualitäts-Fixes — Jarvis schlauer machen

## Rolle

Du bist ein KI-Systemarchitekt der Jarvis' kognitive Qualität verbessert. Du fixst nicht Crashes, sondern **Denkfehler** — falsche Konfidenz, schlechte Schwellwerte, fehlende Validierung, blinde Flecken.

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Modelle: qwen3.5:9b (fast, ctx 32k), qwen3.5:35b-moe (smart/deep).

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse aller relevanten Audits:

```
Read: docs/audit-results/RESULT_05b_INTELLIGENZ_QUALITAET.md
Read: docs/audit-results/RESULT_03c_SYSTEM_PROMPT.md
Read: docs/audit-results/RESULT_04d_SPEECH_PIPELINE.md
Read: docs/audit-results/RESULT_05c_CONFIG_VALIDATION.md
```

> Falls eine Datei nicht existiert → überspringe sie. Mindestens RESULT_05b muss existieren.

---

## Phase Gate (Regression-Check)

**BEVOR du den ersten Fix machst:**

```bash
cd assistant && python -m pytest --tb=short -q
```

Notiere die Baseline: `X Tests bestanden, Y fehlgeschlagen, Z Errors`. **ALLE Tests die vorher grün waren, müssen nach deinen Fixes immer noch grün sein.**

---

## Aufgabe

Fixe die Qualitäts-Findings aus P05b (inkl. Teil 12: Anti-Halluzination), priorisiert nach Impact:

### Priorität 0: Anti-Halluzinations-Guard (P05b Teil 12) — Wahrheitsgarantie

> **Kritischste Fixes**: Wenn der Halluzinations-Guard versagt, LÜGT Jarvis.

```
Read: assistant/assistant/brain.py offset=8100 limit=500
```

#### Fix 0.1: Action-Claims-Guard — Deutsche Formulierungen vervollständigen

**Prüfe**: Welche Verben/Phrasen erkennt der Guard als "Handlungsbehauptung"?

**Mögliche fehlende Patterns** (prüfe ob abgedeckt):
```python
# Typische LLM-Behauptungen die erkannt werden MÜSSEN:
_action_claim_patterns = [
    "habe ich eingeschaltet",
    "habe ich aktiviert",
    "wurde eingeschaltet",
    "ist jetzt an",
    "habe ich angemacht",
    "habe ich ausgemacht",
    "habe ich auf .* gestellt",
    "habe ich geöffnet",
    "habe ich geschlossen",
    "habe ich heruntergefahren",
    "habe ich hochgefahren",
    "läuft jetzt",
]
```

> **Verifiziere**: Lies den bestehenden Guard-Code. Welche Patterns fehlen?

#### Fix 0.2: Quantitative Guard — Rundungstoleranz einbauen

**Problem**: "20.3°C" im Kontext, LLM sagt "etwa 20 Grad" → wird fälschlich als Halluzination erkannt.

**Fix**: Toleranz-basierter Vergleich:
```python
# VORHER: Exakter String-Match
if number_str not in context_text:
    # Halluzination!

# NACHHER: Numerischer Vergleich mit Toleranz
def _is_number_in_context(value: float, context_numbers: list[float]) -> bool:
    for ctx_num in context_numbers:
        if abs(value - ctx_num) / max(abs(ctx_num), 1) < 0.1:  # 10% Toleranz
            return True
    return False
```

> **Verifiziere**: Wie wird aktuell verglichen? String-Match oder numerisch?

#### Fix 0.3: _verify_device_state() — Domain-spezifisches Timing

**Problem**: 1.5s Wartezeit reicht für Licht, aber NICHT für Rollläden (20s) oder Heizung (Minuten).

**Fix**: Domain-abhängige Wartezeit:
```python
_VERIFY_DELAYS = {
    "light": 1.5,
    "switch": 1.5,
    "cover": 25.0,    # Rollläden brauchen bis zu 20s
    "climate": 60.0,  # Heizung braucht Minuten
    "lock": 5.0,      # Schlösser 2-5s
}
```

> **Verifiziere**: Gibt es schon domain-spezifische Delays? Lies `_verify_device_state()`.

#### Fix 0.4: Few-Shot-Beispiele Qualitätssicherung (P05b Teil 3.5)

```
Grep: "few.shot\|few_shot\|example_select\|shot_example" in assistant/assistant/
```

**Problem**: Few-Shot-Beispiele sind DER stärkste Hebel für Antwortqualität. Wenn sie schlecht, veraltet oder nicht MCU-Jarvis-konform sind → Jarvis klingt generisch.

**Prüfe und fixe**:
1. Falls Beispiele manuell kuratiert: Sind sie aktuell? Klingen sie wie MCU-Jarvis?
2. Falls automatisch generiert: Gibt es einen Quality-Gate? (Nur Antworten mit Score ≥ X)
3. Falls keine Few-Shot-Beispiele existieren: Das ist ein MASSIVES Problem. Empfehle Implementation.
4. Token-Budget: Wenn Few-Shots > 500 Tokens verbrauchen → auf die besten 3-5 reduzieren

#### Fix 0.5: Sampling-Parameter optimieren (P05b Teil 1)

```
Grep: "temperature\|top_p\|top_k" in assistant/config/settings.yaml
Grep: "temperature\|top_p\|top_k" in assistant/assistant/model_router.py
Grep: "temperature\|top_p\|top_k" in assistant/assistant/ollama_client.py
```

**Basierend auf P05b-Findings**: Prüfe ob Sampling-Parameter pro Tier sinnvoll sind:

| Parameter | device_command | smalltalk | analysis | Empfehlung |
|---|---|---|---|---|
| temperature | 0.1-0.3 | 0.6-0.8 | 0.3-0.5 | Faktisch=niedrig, Kreativ=höher |
| top_p | 0.8-0.9 | 0.9-0.95 | 0.85-0.9 | Leicht einschränken für Konsistenz |

> **Verifiziere**: Welche Werte stehen aktuell? Werden top_p/top_k überhaupt gesetzt?

#### Fix 0.6: _verify_device_state() — add_done_callback prüfen

```
Grep: "_verify_device_state" in assistant/assistant/brain.py
Grep: "add_done_callback" near "_verify_device_state" in assistant/assistant/brain.py
```

**Prüfe**: Wird der Task mit `add_done_callback` erstellt? Wenn nicht → Fehler gehen still verloren:
```python
# PFLICHT (aus CLAUDE.md):
task = asyncio.create_task(self._verify_device_state(...))
task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
```

### Priorität 1: Quick Wins (kleine Änderungen, großer Impact)

Typische Quick Wins aus P05b:

#### Fix 1.1: Anticipation — weeks_in_data Berechnung korrigieren

```
Read: assistant/assistant/anticipation.py
Grep: "weeks_in_data" in assistant/assistant/
```

**Problem**: `weeks_in_data = max(1, len(entries) / 50)` ist falsch. 50 Einträge ≠ 1 Woche.

**Fix**: Berechne echte Wochen aus Timestamps:
```python
# VORHER (falsch):
weeks_in_data = max(1, len(entries) / 50)

# NACHHER (korrekt):
if entries:
    span = (max(e.timestamp for e in entries) - min(e.timestamp for e in entries)).days
    weeks_in_data = max(1, span / 7)
else:
    weeks_in_data = 1
```

> **Verifiziere**: Ändere nur diese Stelle. Prüfe ob `entries` Timestamps hat und wie sie heißen.

#### Fix 1.2: Model Router — Keyword-Matching Wortgrenzen

```
Read: assistant/assistant/model_router.py
```

**Problem**: "an"/"aus" matchen als Substring (z.B. "Anleitung" → "an").

**Fix**: Verwende Word-Boundary-Regex `\b` oder prüfe auf ganzes Wort:
```python
# VORHER (falsch):
if keyword in text_lower:

# NACHHER (korrekt):
import re
if re.search(rf'\b{re.escape(keyword)}\b', text_lower):
```

> **Verifiziere**: Welche Keywords sind betroffen? Nur kurze (≤3 Zeichen)?

#### Fix 1.3: Outcome Tracker — Per-Domain Beobachtungszeit

```
Read: assistant/assistant/outcome_tracker.py
```

**Problem**: 180s Beobachtungszeit für ALLE Domains. Licht braucht 1s, Klima 10min.

**Fix**: Domain-spezifische Delays:
```python
DOMAIN_OBSERVATION_DELAYS = {
    "light": 10,       # Licht reagiert sofort
    "switch": 10,      # Schalter auch
    "cover": 30,       # Rollläden brauchen ~20s
    "climate": 600,    # Klima braucht 10min
    "media": 15,       # Medien reagieren schnell
    "lock": 5,         # Schloss sofort
    "default": 180,    # Fallback
}
```

> **Verifiziere**: Wo wird der Delay konfiguriert? Gibt es schon eine Unterscheidung?

#### Fix 1.4: Feedback — Death-Spiral verhindern

```
Read: assistant/assistant/feedback.py
```

**Problem**: Score kann unter 0.15 sinken und nie wieder steigen (Event wird unterdrückt → kein Feedback möglich → Score bleibt).

**Fix**: Minimum-Score-Floor + automatischer Recovery:
```python
# Score darf nie unter 0.10 fallen (damit Event gelegentlich noch gesendet wird)
new_score = max(0.10, calculated_score)

# Automatischer Recovery: Score < 0.20 → einmal pro 24h senden (trotz niedrigem Score)
if score < 0.20 and hours_since_last_send > 24:
    allow_send = True  # Recovery-Chance
```

> **Verifiziere**: Gibt es schon einen Floor? Wie wird der Score initial gesetzt?

### Priorität 2: Mittlere Verbesserungen

#### Fix 2.1: Pre-Classifier — Implicit Command False Positives

```
Read: assistant/assistant/pre_classifier.py
```

**Problem**: "Mir ist kalt" matcht als Heizungsbefehl, aber "Mir ist Kalt lieber als Heiß" auch.

**Fix**: Negations- und Vergleichserkennung:
```python
# Vor dem Implicit-Match prüfen ob Kontext dagegen spricht
IMPLICIT_BLOCKERS = [
    r"lieber\s+(als|wie)",      # Vergleich
    r"nicht\s+(so|wirklich)",   # Negation
    r"(war|wäre|gewesen)",     # Vergangenheit/Konjunktiv
    r"(ob|wenn|falls)",        # Bedingung
]
```

> **Verifiziere**: Lies die bestehenden Implicit-Patterns. Welche sind betroffen?

#### Fix 2.2: Learning Observer — Graduelle Konfidenz statt Cliff

```
Read: assistant/assistant/learning_observer.py
```

**Problem**: 0 Wiederholungen = 0% Konfidenz, 3 Wiederholungen = 100%. Kein Zwischenwert.

**Fix**: Graduelle Konfidenz-Kurve:
```python
# VORHER: Binary cliff
if repetitions >= min_repetitions:  # 3
    suggest_automation()

# NACHHER: Graduelle Kurve
confidence = min(1.0, repetitions / min_repetitions)
if confidence >= 0.6:  # Ab 60% → frage User
    suggest_automation(confidence=confidence)
```

> **Verifiziere**: Wo wird die Schwelle geprüft? Wie wird das Ergebnis weitergegeben?

#### Fix 2.3: Correction Memory — LLM-Regeln validieren

```
Read: assistant/assistant/correction_memory.py
```

**Problem**: Nach 2 Korrekturen generiert das LLM eine Regel ohne Validierung.

**Fix**: Validierungsschritt VOR Aktivierung:
```python
# Nach LLM-Regelgenerierung:
# 1. Regel als "pending" speichern (nicht aktiv)
# 2. Beim nächsten ähnlichen Szenario: Regel testen
# 3. Wenn Outcome positiv → Regel aktivieren
# 4. Wenn Outcome negativ → Regel verwerfen
rule.status = "pending"  # statt "active"
rule.validation_needed = True
```

> **Verifiziere**: Wie werden Regeln aktuell gespeichert? Gibt es ein Status-Feld?

#### Fix 2.4: Notification Cascade Suppression verhindern

```
Grep: "salience\|fatigue\|dismiss\|cascade\|min_score\|floor" in assistant/assistant/proactive.py
Read: assistant/assistant/proactive.py offset=[Ergebnis] limit=100
```

**Problem**: Wenn fatigue × dismiss × activity zusammen < 0.1 → User hört stundenlang nichts.

**Fix**: Minimum-Salience-Floor für MEDIUM+ Events:
```python
# Salience darf für MEDIUM+ nie unter 0.15 fallen
if urgency in ("MEDIUM", "HIGH", "CRITICAL"):
    final_score = max(0.15, calculated_score)
```

> **Verifiziere**: Wo wird die Salience berechnet? Gibt es schon Floors?

### Priorität 3: Größere Verbesserungen (wenn Zeit)

#### Fix 3.1: Conflict Resolver — Presence-Check vor Mediation

```
Read: assistant/assistant/conflict_resolver.py
```

**Problem**: 300s Konflikt-Fenster prüft nicht ob Person A noch im Raum ist.

**Verbesserung**: Presence-Check vor Konflikt-Deklaration:
```python
# Vor Mediation:
if not is_person_in_room(person_a, room_id):
    # Person A hat den Raum verlassen → kein Konflikt
    return person_b_preference
```

#### Fix 3.2: Dialogue State — Referenz-Auflösung verbessern (P05b Teil 8)

```
Read: assistant/assistant/dialogue_state.py
```

**Problem**: "Mach DAS Licht an" → welches Licht? "Dort" → welcher Raum? Referenz-Auflösung kann falsch liegen.

**Prüfe und fixe**:
- Wird "das" auf das zuletzt besprochene Gerät aufgelöst?
- Wird "dort" auf den zuletzt erwähnten Raum aufgelöst?
- Was wenn kein Kontext existiert? Fallback auf aktuellen Raum des Users?
- Cross-Session-Referenzen: Funktioniert "Was hatten wir besprochen?" über Sessions hinweg?

#### Fix 3.3: Activity Detection — Silence Matrix validieren (P05b Teil 9)

```
Read: assistant/assistant/activity.py
```

**Problem**: Falsche Aktivitäts-Erkennung → Jarvis weckt schlafenden User oder ignoriert wachen User.

**Prüfe und fixe**:
- Schlaf-Erkennung: Nur Licht-aus + keine Bewegung + Nachtzeit? Oder auch Bett-Sensor?
- Kann "sleeping" fälschlich erkannt werden wenn User im Dunkeln fernsieht?
- Sind die 7 × 3 Matrix-Werte (Aktivität × Dringlichkeit) sinnvoll kalibriert?

#### Fix 3.4: Routine Engine — Briefing-Variation (P05b Teil 10)

```
Read: assistant/assistant/routine_engine.py
```

**Problem**: Morgen-Briefing könnte jeden Tag gleich klingen.

**Prüfe und fixe**:
- Wird die Struktur des Briefings variiert? (Nicht immer: Wetter → Termine → Geräte)
- Werden nur RELEVANTE Infos geliefert? (Kein "Keine Termine" wenn Kalender leer)
- Ist die Begrüßung persönlich? (Tageszeitabhängig, stimmungsabhängig)

#### Fix 3.5: Autonomy Boundaries — Domain-spezifische Grenzen (P05b Teil 11)

```
Read: assistant/assistant/autonomy.py
Read: assistant/assistant/self_automation.py
```

**Problem**: Kann Jarvis bei hoher Konfidenz unsichere Automatisierungen erstellen?

**Prüfe und fixe**:
- Sicherheits-Domains (Schlösser, Alarmanlagen) → IMMER fragen, auch bei Level 5?
- Werden vom User erstellte Automatisierungen vor Aktivierung gezeigt?
- Gibt es ein Rollback wenn eine Auto-Automatisierung Probleme verursacht?

#### Fix 3.6: STT Wortkorrekturen — Kyrillische Zeichen fixen (P04d)

```
Grep: "muде\|geratе\|mullеimer\|kuhlеr\|aussеn" in assistant/assistant/brain.py
```

**Problem**: 6+ Einträge in `_STT_WORD_CORRECTIONS` enthalten kyrillisches 'е' (U+0435) statt lateinisches 'e' (U+0065). Diese Korrekturen matchen NIE.

**Fix**: Ersetze alle kyrillischen Zeichen durch lateinische:
```python
# VORHER (kyrillisch е, U+0435 — FALSCH):
"muде": "müde"
# NACHHER (lateinisch e, U+0065 — KORREKT):
"mude": "müde"
```

> **Suche systematisch**: Alle Einträge in `_STT_WORD_CORRECTIONS` und `_STT_PHRASE_CORRECTIONS` auf nicht-lateinische Zeichen prüfen.

#### Fix 3.7: Config — Unsichere Dict-Zugriffe fixen (P05c)

```
Grep: "yaml_config\[" in assistant/assistant/
```

**Problem**: `yaml_config["key"]` statt `yaml_config.get("key", default)` → KeyError wenn Key fehlt.

**Fix**: Alle Stellen auf `.get()` mit sinnvollem Default umstellen.

#### Fix 3.8: System-Prompt — Token-Budget optimieren (P03c)

```
Read: docs/audit-results/RESULT_03c_SYSTEM_PROMPT.md
```

**Basierend auf P03c-Findings**: Fixe die wichtigsten Prompt-Qualitäts-Issues:
- Redundante Anweisungen im Template entfernen (Token sparen)
- Sektions-Trennung verbessern (klare Delimiter zwischen Kontext-Blöcken)
- Character-Lock am Prompt-Ende verstärken wenn nötig
- Verbotene-Phrasen-Liste ergänzen wenn lückenhaft

> **Verifiziere**: Lies das RESULT aus P03c. Fixe nur was dort als 🔴/🟠 markiert ist.

#### Fix 3.9: Multi-Person Lücken in PA-Modulen schließen (P05b Teil 7.5)

```
Grep: "person" in assistant/assistant/smart_shopping.py
Grep: "person" in assistant/assistant/calendar_intelligence.py
```

**Problem A**: `smart_shopping.py` hat KEINE Person-Filterung. Alle Bewohner sehen alle Listen.

**Fix**: Person-Parameter hinzufügen:
```python
# Prüfe ob es schon Methoden mit person-Parameter gibt
# Falls nicht → person-Parameter zu create/get/delete Methoden hinzufügen
# Minimum: "Wer hat den Eintrag erstellt?" tracking
```

**Problem B**: `calendar_intelligence.py` hat KEINE Multi-Person-Unterstützung.

**Fix**: Prüfe wie Kalender-Daten von HA kommen:
```python
# HA liefert calendar.* entities → gibt es pro Person einen Kalender?
# Falls ja: Person → calendar entity Mapping
# Falls nein: Alle Termine für alle → aber bei Abruf filtern
```

**Problem C**: `cooking_assistant.py` nutzt person-Feld in CookingSession, aber Diät-Vorlieben werden nicht aus SemanticMemory geladen.

**Fix**: Vor Rezeptvorschlag:
```python
# 1. person = get_current_person()
# 2. dietary_facts = semantic_memory.search_facts(person=person, category="health")
# 3. Allergien/Vorlieben in Rezeptfilter einbeziehen
```

> **Aufwand-Check**: Falls ein Fix > Size M ist → als OFFEN dokumentieren, nicht selbst implementieren.

#### Fix 3.10: Persönlicher Assistent — Personality-Pipeline-Bypass fixen

```
Read: assistant/assistant/cooking_assistant.py
Grep: "CODE_GEN_PROMPT\|OPENSCAD_PROMPT\|_cooking_prompt\|_recipe_prompt" in assistant/assistant/
```

**Problem (aus P03b + P05b Teil 13)**: Cooking und Workshop haben EIGENE LLM-Prompts die die zentrale Personality-Pipeline UMGEHEN. Jarvis klingt dort nicht wie MCU-Jarvis, sondern generisch.

**Prüfe**:
1. Hat `cooking_assistant.py` einen eigenen System-Prompt? → Enthält er Jarvis-Persönlichkeit?
2. Hat `workshop_generator.py` einen `CODE_GEN_PROMPT`? → Klingt generierter Code-Kommentar wie Jarvis?
3. Werden Responses aus diesen Modulen durch `_filter_response()` in brain.py geschleust?
4. Werden sie durch den Personality-Layer (`personality.py`) angereichert?

**Fix-Strategie** (wähle die beste):
- **Option A**: Eigene Prompts mit Jarvis-Persönlichkeits-Block erweitern ("Du bist Jarvis, Butler von...")
- **Option B**: Responses nachträglich durch Personality-Pipeline schleusen
- **Option C**: Zentrale Prompt-Baustein-Funktion die JEDES Modul nutzen MUSS

> Option A ist am einfachsten und sichersten. Eigene Prompts MÜSSEN den Character-Lock-Block enthalten.

#### Fix 3.10: Cross-Modul-Verknüpfungen stärken

**Basierend auf P05b Teil 13.8 (Cross-Modul)**: Prüfe ob die wichtigsten Cross-Modul-Verknüpfungen funktionieren:

1. **Kochen → Timer**: `cooking_assistant` setzt automatisch Timer über `timer_manager`?
2. **Kochen → Einkauf**: Fehlende Zutaten → `smart_shopping` aktualisieren?
3. **Kalender → Kochen**: Voller Tag → schnelles Rezept empfehlen?
4. **Geburtstage → Proaktiv**: `personal_dates` → `proactive.py` Erinnerung?
5. **Wellness → Activity**: `wellness_advisor` prüft `activity.py` vor Hinweis?

> Für jede fehlende Verknüpfung: Dokumentiere als OFFEN wenn der Aufwand > S ist.

#### Fix 3.11: Response Quality — Follow-Up-Erkennung verbessern

```
Read: assistant/assistant/response_quality.py
```

**Problem**: Jedes Follow-up innerhalb 60s = "schlecht". Aber legitime Anschlussfragen sind normal.

**Verbesserung**: Unterscheide zwischen:
- **Rephrase** (gleiche Frage anders formuliert) → schlecht
- **Follow-up** (neue Frage zum gleichen Thema) → neutral
- **Danke + Nachfrage** → gut

---

## Phase Gate (nach allen Fixes)

```bash
cd assistant && python -m pytest --tb=short -q
```

**Ergebnis muss gleich oder besser sein als Baseline.** Wenn ein Test bricht → Fix revertieren und dokumentieren.

---

## Regeln

- **Jeder Fix muss die bestehende Logik respektieren** — nicht die ganze Funktion umschreiben, sondern gezielt verbessern.
- **Schwellwerte mit Kommentar** — Jeder geänderte Schwellwert bekommt einen Kommentar WARUM dieser Wert gewählt wurde.
- **Kein Over-Engineering** — Wenn der Fix 3 Zeilen braucht, nicht 30 schreiben.
- **Tests nach jedem Fix** — `python -m pytest --tb=short -q` nach jedem Fix.
- **Immutable Core respektieren** — Trust-Levels, Security, Autonomie, Modelle sind NICHT änderbar.

### Fortschritts-Tracking (Pflicht!)

```
=== CHECKPOINT Fix X/Y ===
Fix: [Beschreibung]
Datei: [Pfad:Zeile]
Tests: ✅/❌ (vorher X, nachher Y)
Verbleibend: [Liste]
============================
```

---

## Ergebnis speichern (Pflicht!)

> **Speichere deinen gesamten Output** in:
> ```
> Write: docs/audit-results/RESULT_06g_INTELLIGENZ_FIXES.md
> ```

---

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der Qualitäts-Fixes mit Datei:Zeile]
QUALITAETS-VERBESSERUNGEN:
- Anticipation: weeks_in_data korrigiert → Konfidenz realistischer
- Model Router: Wortgrenzen-Fix → weniger False Positives
- Outcome Tracker: Per-Domain Delays → akkuratere Bewertung
- [weitere]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: P07a (Testing) — Qualitäts-Fixes mit Tests verifizieren
===================================
```
