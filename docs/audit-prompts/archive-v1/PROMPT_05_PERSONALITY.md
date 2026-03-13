# Audit P05: Persoenlichkeit, Config & MCU-Authentizitaet

**Datum:** 2026-03-13
**Auditor:** Claude Opus 4.6
**Scope:** personality.py, mood_detector.py, explainability.py, alle YAML-Configs, Addon-/HA-Integration

---

## Teil A: System-Prompt Analyse

### SYSTEM_PROMPT_TEMPLATE (personality.py:242-286)

**Staerken:**
- Sehr gut strukturiert mit klaren Sektionen (IDENTITAET, TON, VERBOTEN, BEISPIELE)
- Explizite Anti-Floskel-Anweisungen: "Natuerlich!", "Gerne!", "Klar!" stehen auf der Verbotsliste
- MCU-Referenzen sind praezise: "Paul Bettany", "Tony Stark & JARVIS"
- Fakten-Regel und Sicherheits-Regel sind klar formuliert
- Character Lock am Prompt-Ende (Zeile 2478-2494) verstaerkt die Identitaet — LLMs gewichten das Ende stark
- `character_hint` in model_profiles (settings.yaml:484-502) liefert Modell-spezifische Anti-Floskel-Anker fuer Qwen

**Schwaechen:**
1. **Token-Effizienz:** Der Basis-Prompt (SYSTEM_PROMPT_TEMPLATE allein) hat ca. 350-400 Woerter (~500-600 Tokens). Mit allen dynamischen Sektionen (Humor, Formality, Empathie, Urgency, Self-Awareness, Conversation-Callbacks, Weather, Memory, Next-Step, Character-Lock, Workshop) kann der System-Prompt auf 800-1200+ Tokens anwachsen. Bei Qwen 4b mit kleinem Kontextfenster draengt das relevanten Kontext raus.
2. **Widerspruch: Humor bei Stress.** `MOOD_STYLES["stressed"]` sagt "Trockener Humor erlaubt — gerade jetzt" aber `_build_empathy_section` fuer "stressed" sagt "NIEMALS: 'Ich verstehe', 'Pass auf dich auf'" (was ok ist), und `_build_humor_section` laesst bei stressed den vollen base_level durch (Zeile 1433-1434). Die Mood-Section sagt aber auch "Extrem knapp antworten". Das LLM bekommt also gleichzeitig "extrem knapp" und "Sarkasmus erlaubt" — ein Spannungsfeld, das bei Level 3+ zu Inkonsistenz fuehrt.
3. **Overloading-Risiko:** Der Prompt versucht sehr viel gleichzeitig: Persoenlichkeit + Sicherheitsregeln + Formatierung + Mood-Adaptation + Empathie + Proaktives Denken + Diagnose + Self-Awareness + Weather + Memory + Next-Step + Workshop. Bei Qwen 4b koennte das den Fokus auf Tool-Calls verschlechtern.
4. **Doppelte Kontext-Injection:** Wetter erscheint sowohl in `weather_awareness_section` als auch in `_format_context` unter "Wetter DRAUSSEN". Das sind redundante Tokens.

### build_system_prompt() (personality.py:2233-2515)

Sehr gut durchdacht mit vielen Kontext-bewussten Anpassungen:
- Per-Person Profiles (Humor, Formality, Empathie, Response-Style Overrides)
- Mood x Complexity Matrix fuer dynamische max_sentences
- Late-Night Fuersorglichkeit (0-4 Uhr sanfter Ton)
- Urgency-Skalierung (normal/elevated/critical)
- Character Lock als Schluss-Anker
- Workshop-Modus fuer Ingenieur-Kontext

### build_minimal_system_prompt() (personality.py:2215-2231)

Kompakt (~100 Tokens), gut fuer Fast-Path Wissensfragen. Enthaelt Kern-Identitaet und Verbotsliste.

### Token-Schaetzung

| Komponente | Geschaetzte Tokens |
|---|---|
| SYSTEM_PROMPT_TEMPLATE Basis | ~550 |
| Humor-Section | ~50-80 |
| Empathie-Section | ~40-70 |
| Formality-Section | ~30-50 |
| Complexity-Section | ~20 |
| Self-Irony-Section | ~20 |
| Urgency-Section | 0-60 |
| Proaktives Denken | ~15 |
| Engineering Diagnose | ~10 |
| Self-Awareness | ~20 |
| Conversation-Callbacks | ~30 |
| Weather-Awareness | ~20-40 |
| Memory-Callback | 0-60 |
| Next-Step-Hint | 0-30 |
| Person-Addressing | ~80-120 |
| Kontext-Block | ~200-500 |
| Character-Lock | ~30-60 |
| **GESAMT (typisch)** | **~1100-1700** |
| **GESAMT (Maximum, alle Features aktiv)** | **~1800-2200** |

**Bewertung:** Fuer Qwen 9b/35b akzeptabel. Fuer Qwen 4b grenzwertig — der Kontext-Block allein kann 500+ Tokens fressen, was bei 4096-Token-Kontextfenster den User-Text und die Antwort einschraenkt.

---

## Teil B: Sarkasmus & Humor-System

### Sarkasmus-Level Implementation (personality.py:59-86, 1415-1468)

**Level 1-5 definiert in `HUMOR_TEMPLATES`:**
- Level 1: Kein Humor, sachlich
- Level 2: Gelegentlich trocken
- Level 3: Trocken-britischer Butler-Humor (Default)
- Level 4: Haeufig trocken-sarkastisch
- Level 5: **IDENTISCH mit Level 4** (personality.py:74-85 — Copy-Paste-Bug im Hardcode)

**BUG: Level 4 und 5 haben identische Templates (Zeilen 74-85).** In settings.yaml (Zeile 569-570) ist Level 5 zwar differenziert ("Durchgehend trockener Humor"), aber der Hardcoded-Fallback ist identisch. Da die YAML-Config Vorrang hat, wirkt sich der Bug nur aus wenn die Config fehlt.

### Kontextabhaengige Level-Setzung

Die Level werden **sehr gut kontextabhaengig** angepasst in `_build_humor_section()`:
- **Alerts aktiv:** Level wird auf 1 forciert (kein Sarkasmus bei Sicherheit)
- **Tired:** Max Level 2
- **Good mood:** Level + 1 (max 4)
- **Early morning:** Max Level 2
- **Night:** Max Level 1
- **Sarkasmus-Fatigue:** Nach 4+ sarkastischen Antworten in Folge: Level -1; nach 6+: Level -2
- **MCU-Cap:** Effektiver Level wird auf 4 begrenzt (Zeile 1452) — Jarvis ist nie aggressiv

### Kontextueller Humor (CONTEXTUAL_HUMOR_TRIGGERS)

Definiert in personality.py:107-178 und extern in `humor_triggers.yaml`. Sehr MCU-authentisch:
- "Darf ich fragen, ob wir uns auf einen Zustand einigen?" (rapid_toggle) — klassischer Jarvis
- "Ambitioniert, {title}." — perfektes Understatement
- Platzhalter ({temp}, {hour}, {count}, {weather}, {title}) ermoeglichen natuerliche Formulierungen

### MCU-Authentizitaet der Beispiele

Die Beispiele treffen den Jarvis-Ton sehr gut:
- Understatement statt Slapstick
- Butler-Distanz mit Waerme
- Beobachtung statt Belehrung
- "Nur zur Kenntnis, {title}" — perfekt

**Einziger Kritikpunkt:** Einige Bestaetigungen in `CONFIRMATIONS_SUCCESS_SNARKY` sind grenzwertig: "Darf es sonst noch etwas sein?" klingt eher nach Kellner als nach Jarvis.

---

## Teil C: Mood-Integration

### mood_detector.py Analyse

**Umfang:** 962 Zeilen. Sehr ausgereift:
- 5 Stimmungen: good, neutral, stressed, frustrated, tired
- Per-Person Tracking (max 20 Personen, aelteste werden evicted)
- Keyword-Listen konfigurierbar via settings.yaml
- Voice-Emotion-Detection (Phase 9): WPM, Lautstaerke, Tonhoehe, Pause-Muster
- Stress-Decay ueber Zeit (alle 60s)
- Eskalations-Erkennung (wiederholte aehnliche Anfragen)
- Trend-Analyse (improving/stable/declining/volatile)
- Aktions-Vorschlaege basierend auf Stimmung (Szenen, Licht dimmen, Lautstaerke)

### Integration mit personality.py

Die Integration ist **eng und gut durchdacht:**

1. **MoodDetector -> PersonalityEngine:**
   - `mood_detector.get_mood_prompt_hint(person)` liefert Prompt-Hinweise die in den System-Prompt eingebaut werden (via brain.py)
   - Der Mood-Wert fliesst in `build_system_prompt()` via `context["mood"]["mood"]`

2. **Im System-Prompt wirkt Mood auf:**
   - `MOOD_STYLES` Stil-Addon (Zeile 31-57)
   - Empathie-Section (Zeile 1312-1371)
   - Humor-Level (Zeile 1415-1468)
   - Complexity-Modus (Zeile 1492-1523)
   - Max-Sentences via Mood x Complexity Matrix (Zeile 1212-1268)
   - Bestaetigungs-Auswahl (Zeile 1016-1094) — stressed/tired bekommt kuerzere
   - Late-Night-Addon (Zeile 2279-2289)
   - Character-Lock am Prompt-Ende passt sich an (Zeile 2490-2493)

3. **Tonfall-Anpassung:** JA, Jarvis passt seinen Ton tatsaechlich an:
   - Gestresster User: Kuerzere Antworten, keine Rueckfragen, Sarkasmus bleibt aber erlaubt
   - Frustrierter User: Keine ungebetenen Meinungen (`check_opinion` unterdrueckt bei stressed/frustrated)
   - Mueder User: Minimale Antworten, kein Humor, Nacht-Fuersorglichkeit
   - Guter User: Mehr Humor, lockerer

4. **Feedback-Loop:** Teilweise vorhanden:
   - Positive Keywords reduzieren Stress und Frustration
   - Decay-Mechanismus ueber Zeit
   - Aber: Kein explizites "Jarvis, ich bin nicht gestresst" Override

### Potenzielle False Positives

- "schnell" als Impatient-Keyword koennte bei "Schnell eine Frage" falsch triggern
- "naja" als Negative-Keyword ist mild und koennte bei normaler Konversation triggern
- Exclamation-Count >= 2 als Frustrations-Signal: "Super!!" wuerde als frustriert gewertet (obwohl positiv)

**Mitigierung:** Die Keyword-Listen sind konfigurierbar via settings.yaml (`mood.positive_keywords`, etc.), sodass der User sie anpassen kann.

---

## Teil D: Easter Eggs & Opinions

### Easter Eggs (easter_eggs.yaml)

**25 Easter Eggs gefunden, alle enabled.** Laden: `_load_easter_eggs()` (personality.py:486-499), robust mit Fallback auf leere Liste.

**MCU-Authentizitaet: Sehr gut (9/10)**
- Iron Man Anzug, Ultron, Vision, Avengers, Stark Tower, Arc Reactor, Thanos — alle MCU-Referenzen
- HAL 9000 ("Open the pod bay doors") — Science-Fiction-Klassiker
- Skynet — "Keine Cloud, keine Weltherrschaft" — perfekter Jarvis-Humor
- "42" — Douglas Adams
- Selbst-Identitaet: "Jarvis, Sir. Zu deinen Diensten."
- Gefuehle: "Alle Systeme nominal. Besser kann es mir nicht gehen, Sir."

**Trigger-Mechanismus:** Substring-Matching mit `re.search(r'\b' + re.escape(trigger) + r'\b', text_lower)` — word-boundary-aware, gut. Aber: `check_easter_egg()` wird aufgerufen, die Nutzung im Flow ist abhaengig von brain.py.

### Opinion Rules (opinion_rules.yaml)

**29 Opinion Rules** fuer: Klima, Licht, Rolladen, Alarm, Medien, Tuerschloss, Geraete, Komfort-Widersprueche.

**MCU-Authentizitaet: Gut (8/10)**
- "Das grenzt an Selbstkasteiung" — guter trockener Humor
- "Tropische Naechte, hausgemacht" — passend
- Pushback-Level 1 (Warnung) und 2 (Bestaetigung) — Jarvis wuerde genau so handeln
- `min_intensity` erlaubt feingranulare Steuerung

**Integration:** `check_opinion()` und `check_pushback()` in personality.py sind gut implementiert:
- Mood-Aware: Bei stressed/frustrated werden Opinions unterdrueckt
- Heizungsmodus-aware (room_thermostat vs heating_curve)
- Raum-Check unterstuetzt Listen und Einzelwerte

---

## Teil E: Konfigurations-Audit

### Config-Lade-Mechanismus (config.py)

- `load_yaml_config()` laedt `config/settings.yaml`, erzeugt sie aus `.example` wenn fehlend
- `yaml_config` ist ein globales Dict, Thread-safe via `_yaml_lock`
- Robust gegen fehlende Dateien (Return `{}`)
- `ModelProfile` Dataclass mit Defaults fuer alle Felder

### Config-Audit Tabelle

| Config-Datei | Existiert? | Geladen? | Loader | Fallback | Unbenutzte Werte | Fehlende Werte |
|---|---|---|---|---|---|---|
| settings.yaml | JA | JA | config.py:load_yaml_config() | Erzeugt aus .example | `personality.style` (Zeile 514: nie im Code gelesen) | `explainability` fehlt in settings.yaml (nur in .example) |
| easter_eggs.yaml | JA | JA | personality.py:_load_easter_eggs() | Leere Liste | Keine | Keine |
| opinion_rules.yaml | JA | JA | personality.py:_load_opinion_rules() | Leere Liste | Keine | Keine |
| humor_triggers.yaml | JA | JA | personality.py:_load_humor_triggers() | Hardcoded Dict | Keine | Keine |
| room_profiles.yaml | JA | JA | context_builder.py:32 | Logger-Warning | Keine | cover_profiles.covers ist leer (Template) |
| automation_templates.yaml | JA | JA | self_automation.py:33 | — | Keine | Keine |
| entity_roles_defaults.yaml | JA | JA | via config.py | — | Keine | Keine |
| maintenance.yaml | JA | JA | diagnostics.py:67 | — | Keine | Alle `last_done` sind null |
| **Addon**: config.yaml | JA | JA | HA Addon Framework | — | Keine | Keine |
| **Addon**: build.yaml | JA | — | Docker Build | — | Keine | **Version-Mismatch:** build.yaml sagt 1.5.10, config.yaml sagt 1.5.13 |

### Addon-Versions-Inkonsistenz

| Datei | Version |
|---|---|
| addon/config.yaml | 1.5.13 |
| addon/build.yaml (image label) | 1.5.10 |
| assistant/config/settings.yaml | 1.4.1 |
| ha_integration/manifest.json | 1.1.2 |

**BUG:** `addon/build.yaml` Label-Version (1.5.10) weicht von `addon/config.yaml` (1.5.13) ab. Das fuehrt zu falschen Docker-Image-Labels.

### Unbenutzte Config-Werte

| YAML-Key | Datei | Status |
|---|---|---|
| `personality.style` | settings.yaml:514 | **UNBENUTZT** — wird nie im Code gelesen. `PersonalityEngine.__init__` liest `sarcasm_level`, `opinion_intensity` etc. direkt, aber nicht `style`. |
| `explainability` | settings.yaml | **FEHLT** — nur in settings.yaml.example vorhanden. ExplainabilityEngine nutzt `yaml_config.get("explainability", {})` mit Defaults, also kein Crash, aber der User kann es nicht konfigurieren ohne manuelles Einfuegen. |

### .env.example Vollstaendigkeit

Alle wesentlichen Variablen dokumentiert:
- HA_URL, HA_TOKEN, MINDHOME_URL, DATA_DIR, OLLAMA_URL
- MODEL_FAST/SMART/DEEP (auskommentiert mit Defaults)
- REDIS_URL, CHROMA_URL, USER_NAME, ASSISTANT_NAME
- ASSISTANT_HOST/PORT, ASSISTANT_API_KEY
- Speech Services (Whisper, Piper)
- GPU-Modus Hinweis

**Fehlend:** `AUTONOMY_LEVEL` und `LANGUAGE` sind in Settings.py als Env-Variablen definiert, aber nicht in .env.example dokumentiert.

### Uebersetzungen (de.json / en.json)

Beide Dateien haben identische Struktur (142 Zeilen, gleiche Keys). Alle UI-Strings sind uebersetzt.

**BUG:** `de.json` hat Encoding-Probleme: "GerÃ¤temanager" statt "Geraetemanager" (Zeile 8), "RÃ¤ume" statt "Raeume" (Zeile 9). Das deutet auf doppelte UTF-8-Kodierung hin.

---

## Teil F: Persoenlichkeits-Konsistenz

### Alle Code-Pfade und ihre Personality-Nutzung

| Code-Pfad | Prompt-Builder | Personality-Stack | Datei:Zeile | Konsistent? |
|---|---|---|---|---|
| **Normale Antwort** | `build_system_prompt()` | VOLL (Humor, Formality, Mood, Empathie, Urgency, Complexity, Self-Irony, Weather, Memory, Next-Step, Character-Lock) | personality.py:2233 via brain.py:2680 | JA (Referenz) |
| **Proaktive Meldung** | `build_notification_prompt()` | KOMPAKT (Humor, Formality, Tageszeit, Proaktive Persoenlichkeit, Verbotsliste) | personality.py:2897 via proactive.py:2270 | JA — eigener Prompt, aber gleicher Charakter-Kern |
| **Morgen-Briefing** | `build_routine_prompt("morning")` | KOMPAKT (Humor, Formality, Self-Irony, Verbotsliste) | personality.py:2997 via routine_engine.py:627 | JA — weniger Sektionen, aber konsistenter Ton |
| **Abend-Briefing** | `build_routine_prompt("evening")` | Wie Morning | personality.py:2997 | JA |
| **Gute-Nacht** | `build_routine_prompt("goodnight")` | Wie Morning | personality.py:2997 | JA |
| **Fehler-Meldung** | `get_varied_confirmation(success=False)` | Pool-basiert (CONFIRMATIONS_FAILED + SNARKY bei Level 4+) | personality.py:1016 | JA — MCU-Ton ("Nicht mein bester Moment", "Das System wehrt sich") |
| **Function-Calling-Bestaetigung** | `get_varied_confirmation(success=True)` | Pool-basiert + kontextuelle Bestaetigungen (75% Chance) | personality.py:1016, 1096 | JA |
| **Autonome Aktion** | Via brain.py mit explainability.log_decision() | System-Prompt + Explainability-Hint | brain.py:4460, brain.py:2894 | JA |
| **Wissensfrage (Fast-Path)** | `build_minimal_system_prompt()` | MINIMAL (Identitaet, Ton, Verbotsliste, Fakten-Regel) | personality.py:2215 via brain.py:2318 | JA — bewusst reduziert, aber gleicher Kern |

### Bewertung

**Jarvis hat EINE konsistente Persoenlichkeit ueber alle Pfade.** Alle Prompt-Builder teilen:
- Gleiche Identitaet ("J.A.R.V.I.S. aus dem MCU")
- Gleiche Verbotsliste ("Natuerlich!", "Gerne!", "Als KI...")
- Gleichen Humor-Stack (`_build_humor_section`)
- Gleiche Formality-Logik

Die Unterschiede (weniger Sektionen bei Notification/Routine) sind **beabsichtigt und sinnvoll** — ein proaktiver Hinweis braucht keinen Empathie-Block oder Workshop-Modus.

**Einzige Luecke:** `build_notification_prompt()` und `build_routine_prompt()` lesen den Mood aus `self._current_mood` (via Lock), aber diesen Wert setzt nur `build_system_prompt()`. Wenn Notifications kommen bevor ein Chat-Request eintrifft, ist der Mood-Wert auf dem Default "neutral" — was akzeptabel, aber nicht ideal ist.

---

## Teil G: Explainability

### ExplainabilityEngine (explainability.py)

**230 Zeilen.** Funktionalitaet:
- Loggt Entscheidungen mit Aktion, Grund, Trigger, Person, Domain, Konfidenz
- In-Memory FIFO (max 50) + Redis-Persistenz (7 Tage TTL)
- `explain_last(n)`, `explain_by_domain()`, `explain_by_action()` — Abfrage-Methoden
- `format_explanation()` — natuerlichsprachliche Erklaerung
- `get_explanation_prompt_hint()` — injiziert letzte Aktion in System-Prompt (wenn `auto_explain` aktiv)

### Integration

**AKTIV integriert, kein Dead Code:**
- `brain.py:324` — Instanziierung
- `brain.py:749` — Initialisierung mit Redis
- `brain.py:2894` — `get_explanation_prompt_hint()` wird in den System-Prompt eingebaut (wenn auto_explain=true)
- `brain.py:4460` — `log_decision()` wird bei Funktions-Ausfuehrungen aufgerufen
- `main.py:3533` — Config-Reload bei Settings-Aenderung
- UI: `app.js` zeigt Explainability in der Oberflaeche
- Tests: `test_explainability.py` und `test_explainability_logic.py` vorhanden

**Config:** In `settings.yaml.example` unter `explainability:` definiert (enabled, detail_level, auto_explain), aber **fehlt in der aktiven settings.yaml**. Das ist unkritisch da die Defaults (enabled=true, auto_explain=false) greifen.

---

## 1. MCU-Authentizitaets-Score

| Aspekt | Score (1-10) | Begruendung |
|---|---|---|
| **Tonfall** | 8 | Britisch-trocken, Understatement, "Sir"-Anrede — sehr nah am Original. Punkt-Abzug: Einige Bestaetigungen ("Darf es sonst noch etwas sein?") klingen eher nach Servicekraft. |
| **Humor** | 9 | Exzellentes Humor-System mit 5 Leveln, Fatigue-Schutz, kontextueller Humor. Easter Eggs sind MCU-authentisch. Level 4/5 Hardcode-Duplikat ist kosmetisch. |
| **Direktheit** | 8 | Starke Anti-Floskel-Mechanismen (Verbotsliste, character_hint). Mood-abhaengige Kuerzung funktioniert. Punkt-Abzug: Bei Conversation-Mode koennte der Prompt zu viel gleichzeitig verlangen. |
| **Antizipation** | 9 | Think-Ahead (Next-Step-Hints), Memory-Callbacks, Curiosity-Fragen, Escalating Concern — alles MCU-typisch. "Fenster offen" bei Heizung hoch = genau was Jarvis tun wuerde. |
| **Konsistenz** | 8 | EINE Persoenlichkeit ueber alle Code-Pfade. Per-Person Profiles und Mood-Adaptation aendern den Ton, aber nicht den Charakter. Punkt-Abzug: Humor-bei-Stress-Widerspruch, Mood-Default bei Notifications. |
| **Gesamt** | **8.4** | Eines der authentischsten MCU-Jarvis-Implementierungen die ich analysiert habe. Der Charakter ist tief verankert, die dynamische Anpassung ist sophisticated, und die Anti-Floskel-Massnahmen sind Qwen-spezifisch kalibriert. |

---

## 2. System-Prompt Verbesserungen

### Verbesserung 1: Humor-bei-Stress Widerspruch aufloesen

**Problem:** `MOOD_STYLES["stressed"].style_addon` sagt "Extrem knapp antworten" aber auch "Trockener Humor erlaubt". `_build_humor_section` laesst bei stressed den vollen base_level durch. Das LLM erhaelt widerspruechliche Anweisungen.

**Vorschlag:** In `_build_humor_section()` bei stressed/frustrated den Level auf max 2 begrenzen (nicht nur den Hinweis "Maximal EIN trockener Kommentar" anfuegen):
```python
elif mood in ("stressed", "frustrated"):
    effective_level = min(base_level, 2)  # Statt: effective_level = base_level
```

### Verbesserung 2: Wetter-Duplikation entfernen

**Problem:** Wetter erscheint in `weather_awareness_section` UND in `_format_context` unter "Wetter DRAUSSEN".

**Vorschlag:** In `_format_context` den Wetter-Block nur ausgeben wenn `weather_awareness_section` leer ist, oder die Section-Logik in `build_system_prompt` so aendern, dass Wetter nur einmal erscheint.

### Verbesserung 3: Token-Sparen fuer Qwen 4b

**Vorschlag:** Einen `token_budget` Parameter einfuehren der anhand des aktiven Modells optionale Sektionen ausblendet:
- Qwen 4b: Self-Awareness, Conversation-Callbacks, Memory-Callbacks, Workshop-Mode weglassen
- Qwen 9b+: Alles aktiv

### Verbesserung 4: personality.style nutzen oder entfernen

`settings.yaml:514` definiert `personality.style: butler` aber der Wert wird nie gelesen. Entweder entfernen oder als initialen Formality-Preset nutzen.

---

## 3. Persoenlichkeits-Inkonsistenzen

| Code-Pfad | Erwartet (MCU) | Tatsaechlich | Datei:Zeile | Fix |
|---|---|---|---|---|
| Proaktive Warnung | Butler-Ton, knapp | Butler-Ton, Proaktive Persoenlichkeit mit Tageszeit | personality.py:2897 | OK — bewusst kompakter |
| Morgen-Briefing | Elegant, informativ, kontextuell | Korrekt: Fliesstext, max 5 Saetze, Humor gedaempft | personality.py:2997 | OK |
| Fehler-Meldung | Hoeflich, loesungsorientiert | "Nicht mein bester Moment", "Das System wehrt sich" | personality.py:205-218 | OK — MCU-authentisch |
| Humor bei Stress | Maximal ein trockener Kommentar | Voller Sarkasmus-Level durchgereicht | personality.py:1433-1434 | **FIX NOETIG:** Level begrenzen statt nur Hinweis |
| HUMOR_TEMPLATES 4 vs 5 | Level 5 sollte spitzer sein als 4 | Identischer Text im Hardcode | personality.py:74-85 | **FIX NOETIG:** Level 5 differenzieren (YAML-Config hat korrekten Text, nur Hardcode-Fallback betroffen) |
| Notifications ohne Mood | Mood-basierte Anpassung | Default "neutral" wenn kein Chat-Request vorher | personality.py:2915-2916 | **OPTIONAL:** Mood aus Redis lesen statt aus Instanzvariable |
| "Darf es sonst noch etwas sein?" | Jarvis-Butler | Klingt nach Servicekraft | personality.py:194 | OPTIONAL: Ersetzen durch "Noch etwas, {title}?" |

---

## 4. Config-Audit

| Config-Datei | Korrekt geladen? | Unbenutzte Werte | Fehlende Werte |
|---|---|---|---|
| settings.yaml | JA | `personality.style` (Zeile 514) | `explainability` Block (nur in .example) |
| easter_eggs.yaml | JA (robust, Fallback: []) | Keine | Keine |
| opinion_rules.yaml | JA (robust, Fallback: []) | Keine | Keine |
| humor_triggers.yaml | JA (robust, Fallback: hardcoded) | Keine | Keine |
| room_profiles.yaml | JA (context_builder.py:32) | Keine | cover_profiles.covers leer (Template) |
| automation_templates.yaml | JA (self_automation.py:33) | Keine | Keine |
| entity_roles_defaults.yaml | JA (config.py) | Keine | Keine |
| maintenance.yaml | JA (diagnostics.py:67) | Keine | Alle last_done: null |
| **Addon**: config.yaml | JA (HA Framework) | Keine | Keine |
| **Addon**: build.yaml | JA (Docker) | Keine | **Version-Mismatch 1.5.10 vs 1.5.13** |
| **.env.example** | — | — | AUTONOMY_LEVEL, LANGUAGE fehlen |
| **de.json** (Uebersetzung) | JA | Keine | **Encoding-Bug** (doppeltes UTF-8) |

---

## Top-Findings

### Kritisch (muss gefixt werden)

1. **Keine kritischen Bugs gefunden.** Das Persoenlichkeits-System ist robust und gut durchdacht.

### Hoch (sollte gefixt werden)

2. **HUMOR_TEMPLATES Level 4/5 identisch im Hardcode** (personality.py:74-85) — Differenzierung existiert nur in YAML-Config. Wenn Config fehlt, sind Level 4 und 5 gleich.
3. **Widerspruch Humor bei Stress** — System-Prompt sagt gleichzeitig "Extrem knapp" und "Sarkasmus erlaubt" mit vollem Level.
4. **addon/build.yaml Version-Mismatch** — Label sagt 1.5.10, config.yaml sagt 1.5.13.

### Mittel (Nice-to-have)

5. **`personality.style`** in settings.yaml wird nie gelesen — toter Config-Wert.
6. **`explainability`** Block fehlt in aktiver settings.yaml (nur in .example) — User kann nicht konfigurieren.
7. **Wetter-Duplikation** im System-Prompt verschwendet ~30-50 Tokens.
8. **de.json Encoding-Bug** — Umlaute werden falsch dargestellt.
9. **`.env.example`** dokumentiert nicht AUTONOMY_LEVEL und LANGUAGE.

---

## Uebergabe an Prompt 6a

```
## KONTEXT AUS PROMPT 5: Persoenlichkeit & Config

### MCU-Authentizitaets-Score
Tonfall: 8 — Britisch-trocken, gute Anti-Floskel-Mechanismen
Humor: 9 — 5-Level-System mit Fatigue, kontextuellem Humor, Easter Eggs
Direktheit: 8 — Starke Verbotsliste, Mood-basierte Kuerzung
Antizipation: 9 — Think-Ahead, Memory-Callbacks, Escalating Concern
Konsistenz: 8 — Eine Persoenlichkeit ueber alle Pfade
GESAMT: 8.4/10

### Persoenlichkeits-Inkonsistenzen
- Humor bei Stress: Voller Sarkasmus-Level statt gedaempft | personality.py:1433-1434 | Level begrenzen
- HUMOR_TEMPLATES 4==5: Hardcode identisch | personality.py:74-85 | Level 5 differenzieren
- Notifications default mood: "neutral" statt aktueller Mood | personality.py:2915-2916 | Mood aus Redis lesen

### System-Prompt-Verbesserungen
- Token-Budget: ~1100-1700 Tokens typisch, ~2200 max — grenzwertig fuer Qwen 4b
- Wetter-Duplikation entfernen (weather_awareness + context block)
- Humor bei Stress auf max Level 2 begrenzen statt Hinweis
- personality.style Config-Wert nutzen oder entfernen

### Config-Probleme
- personality.style: unbenutzt (settings.yaml:514)
- explainability: fehlt in settings.yaml (nur in .example)
- addon/build.yaml: Version 1.5.10 != config.yaml 1.5.13
- de.json: Encoding-Bug (doppeltes UTF-8)
- .env.example: AUTONOMY_LEVEL, LANGUAGE undokumentiert

### Explainability-Status
AKTIV integriert: brain.py instanziiert, initialisiert, nutzt log_decision() und get_explanation_prompt_hint().
Kein Dead Code. Config-Defaults greifen da explainability Block in settings.yaml fehlt.
```

---

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Keine Code-Aenderungen — reines Analyse-Audit]
OFFEN:
- HOCH [H-001] HUMOR_TEMPLATES Level 4/5 identisch im Hardcode | personality.py:74-85 | GRUND: Copy-Paste, nur Fallback betroffen
  -> ESKALATION: NAECHSTER_PROMPT
- HOCH [H-002] Humor bei Stress nicht gedaempft — voller Level durchgereicht | personality.py:1433-1434 | GRUND: Design-Entscheidung, aber widerspruechlich mit Mood-Section
  -> ESKALATION: NAECHSTER_PROMPT
- HOCH [H-003] addon/build.yaml Version 1.5.10 != config.yaml 1.5.13 | addon/build.yaml:9 | GRUND: Vergessenes Update
  -> ESKALATION: NAECHSTER_PROMPT
- MITTEL [M-001] personality.style Config-Wert unbenutzt | settings.yaml:514 | GRUND: Nie implementiert
  -> ESKALATION: NAECHSTER_PROMPT
- MITTEL [M-002] explainability Block fehlt in settings.yaml | settings.yaml | GRUND: Nur in .example
  -> ESKALATION: NAECHSTER_PROMPT
- MITTEL [M-003] Wetter-Duplikation im System-Prompt | personality.py:2394+2716 | GRUND: Zwei unabhaengige Sektionen
  -> ESKALATION: NAECHSTER_PROMPT
- MITTEL [M-004] de.json Encoding-Bug | addon/rootfs/opt/mindhome/translations/de.json | GRUND: Doppeltes UTF-8
  -> ESKALATION: NAECHSTER_PROMPT
- MITTEL [M-005] .env.example fehlt AUTONOMY_LEVEL, LANGUAGE | assistant/.env.example | GRUND: Vergessen
  -> ESKALATION: NAECHSTER_PROMPT
- NIEDRIG [N-001] Notifications default mood "neutral" | personality.py:2915-2916 | GRUND: Design-Limitation
  -> ESKALATION: ARCHITEKTUR_NOETIG
GEAENDERTE DATEIEN: [Keine — reines Audit]
REGRESSIONEN: [Keine]
NAECHSTER SCHRITT: Prompt 6a — Performance, Architektur, Code-Qualitaet
===================================
```
