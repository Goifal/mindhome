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

Fixe die Qualitäts-Findings aus P05b, priorisiert nach Impact:

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
Read: assistant/assistant/proactive.py
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

#### Fix 3.9: Response Quality — Follow-Up-Erkennung verbessern

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
