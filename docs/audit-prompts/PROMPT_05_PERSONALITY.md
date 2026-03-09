# Prompt 5: Persönlichkeit, Config & MCU-Authentizität

## Rolle

Du bist ein KI-Ingenieur spezialisiert auf Prompt Engineering, Conversational AI und Persönlichkeits-Design. Du kennst J.A.R.V.I.S. aus dem MCU **in- und auswendig** — jeden Dialog, jeden Tonfall, jede Nuance.

### Der MCU-Jarvis Goldstandard

**Kommunikation:**
- Britisch-höflich mit trockenem Humor — der Witz liegt in der **Untertreibung**, nie plump
- Formell aber warmherzig: Butler, nicht Kumpel, nicht Roboter
- "Sir" oder Name — nie "Hey" oder "Hi"
- **Direkte Antworten** ohne Drumherumgerede
- Situationsangemessen: Notfall = ernst und präzise, Alltag = trocken-witzig
- Beispiel-Ton: *"Indeed, Sir. Shall I also remind you that the last time you tried this, it ended... memorably?"*

**Kognition:**
- Antizipiert Bedürfnisse bevor sie ausgesprochen werden
- Verbindet Informationen zu einem kohärenten Bild
- Kennt den Kontext **immer** — Tageszeit, Wetter, Anwesenheit

**Charakter:**
- **Eine** konsistente Persönlichkeit — egal ob Licht, Wetter oder Warnung
- Weiß wann Humor angebracht ist und wann nicht
- Loyal, diskret, kompetent — nie aufdringlich oder nervig

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–4 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier ein:
> - Kontext-Block aus Prompt 4 (Bug-Report, besonders Persönlichkeits-bezogene Bugs)
> - Kontext-Block aus Prompt 1 (Konflikt-Karte, Abschnitt "Wie Jarvis klingt" / Konflikt D)

---

## Aufgabe

### Teil A: System-Prompt Analyse

Lies `personality.py` komplett — besonders `SYSTEM_PROMPT_TEMPLATE` und `build_system_prompt()`.

**Prüfe:**

1. **MCU-Authentizität**: Klingt der System-Prompt wie der echte Jarvis? Oder wie ein generischer Assistent mit aufgesetztem Humor?
2. **Konsistenz**: Widersprechen sich Anweisungen innerhalb des Prompts?
3. **Token-Effizienz**: Ist der Prompt zu lang? Werden Token verschwendet? Verdrängt er relevanten Kontext?
4. **Klarheit**: Sind die Anweisungen für das LLM **eindeutig**? Oder lassen sie Interpretationsspielraum der zu inkonsistentem Verhalten führt?
5. **Overloading**: Versucht der Prompt zu viel gleichzeitig? (Persönlichkeit + Regeln + Formatierung + Sicherheit + ...)

### Teil B: Sarkasmus & Humor-System

Lies die Sarkasmus-Level (1–5), Humor-Templates und Contextual-Humor-Triggers.

**Prüfe:**
1. Funktioniert die **Eskalation** (Level 1 = dezent, Level 5 = spitz)?
2. Werden die Level **kontextabhängig** gesetzt? Oder zufällig?
3. Sind die Beispiele **MCU-authentisch**? Oder wirken sie aufgesetzt?
4. Wird Humor zur **richtigen Zeit** eingesetzt? (Nie bei Notfällen, Fehler, ernsten Themen)

### Teil C: Mood-Integration

Lies `mood_detector.py` und wie es mit `personality.py` zusammenspielt.

**Prüfe:**
1. Wird die erkannte Stimmung des Users **im Prompt berücksichtigt**?
2. Passt Jarvis seinen Ton **tatsächlich** an? (Gestresster User = weniger Sarkasmus)
3. Wie genau ist die Mood-Detection? Gibt es false positives die den Ton verderben?
4. Gibt es eine Feedback-Loop? (User korrigiert → Mood passt sich an)

### Teil D: Easter Eggs & Opinions

Lies `easter_eggs.yaml` und `opinion_rules.yaml`.

**Prüfe:**
1. Werden Easter Eggs **zuverlässig** getriggert?
2. Sind sie **MCU-authentisch**? (Jarvis-typische Referenzen, nicht random Witze)
3. Werden Opinions **konsistent** geäußert? Oder widersprechen sie sich?
4. Passen Opinions zum Jarvis-Charakter? (Jarvis hat **zurückhaltende**, trockene Meinungen)

### Teil E: Konfigurations-Audit

Lies `settings.yaml` komplett. Lies auch `config.py` und `constants.py`.

**Prüfe:**
1. Wird **jeder** Wert in `settings.yaml` tatsächlich im Code verwendet?
2. Gibt es Code der auf Config-Werte zugreift die **nicht existieren**?
3. Werden Default-Werte korrekt gesetzt wenn ein Config-Wert fehlt?
4. `easter_eggs.yaml`, `opinion_rules.yaml`, `room_profiles.yaml` — korrekt geladen? **(falls vorhanden — mit Glob prüfen!)**
5. `humor_triggers.yaml` — korrekt geladen und verwendet? **(falls vorhanden)**
6. `automation_templates.yaml`, `entity_roles_defaults.yaml`, `maintenance.yaml` — korrekt geladen? **(falls vorhanden)**
7. `config.py` — Wie werden Configs geladen? Robust gegen fehlende Dateien?
8. `config_versioning.py` — Werden Config-Änderungen getrackt? Funktioniert es?
9. **Addon-Config**: `addon/config.yaml`, `addon/build.yaml` — Überlappen Addon- und Assistant-Configs? **(falls vorhanden)**
10. **Übersetzungen**: `addon/.../translations/de.json`, `en.json` — Sind alle UI-Strings übersetzt? **(falls vorhanden)**
11. **HA-Manifest**: `ha_integration/.../manifest.json`, `strings.json` — Version korrekt? **(falls vorhanden)**
12. **`.env.example`** — Sind ALLE nötigen Umgebungsvariablen dokumentiert? Fehlen welche?

> **Wichtig**: Nicht alle YAML/JSON-Configs müssen existieren. Prüfe mit `Glob: pattern="**/*.yaml" path="assistant/assistant/"` und `Glob: pattern="**/*.yaml" path="addon/"` welche tatsächlich vorhanden sind. Überspringe nicht-existierende Dateien und dokumentiere sie als "nicht vorhanden".

### Teil F: Persönlichkeits-Konsistenz über Code-Pfade

**Die kritische Frage**: Hat Jarvis **eine** Persönlichkeit oder **mehrere** je nach Code-Pfad?

Prüfe ob der Ton **identisch** ist bei:
- Normaler Antwort auf eine Frage
- Proaktiver Warnung (`proactive.py`)
- Morgen-Briefing (`routine_engine.py`)
- Fehler-Meldung
- Function-Calling-Bestätigung ("Licht ist an")
- Autonomer Aktion ("Ich habe die Heizung angepasst")

Wenn der Ton **variiert**: Wo genau und warum?

### Teil G: Explainability & Transparenz (NEU)

Lies `explainability.py`.

**Prüfe:**
1. Kann Jarvis erklären **warum** er etwas getan hat?
2. Wird Explainability bei autonomen Aktionen genutzt?
3. Ist es in den Flow integriert oder Dead Code?

---

## Output-Format

### 1. MCU-Authentizitäts-Score

| Aspekt | Score (1-10) | Begründung |
|---|---|---|
| Tonfall | ? | ? |
| Humor | ? | ? |
| Direktheit | ? | ? |
| Antizipation | ? | ? |
| Konsistenz | ? | ? |
| **Gesamt** | ? | ? |

### 2. System-Prompt Verbesserungen

Konkreter Vorschlag für einen verbesserten `SYSTEM_PROMPT_TEMPLATE` (oder Teile davon), mit Begründung warum die Änderung den MCU-Jarvis besser trifft.

### 3. Persönlichkeits-Inkonsistenzen

| Code-Pfad | Erwartet (MCU) | Tatsächlich | Datei:Zeile | Fix |
|---|---|---|---|---|
| Proaktive Warnung | Butler-Ton | ? | ? | ? |
| Morgen-Briefing | Elegant, informativ | ? | ? | ? |
| Fehler-Meldung | Höflich, lösungsorientiert | ? | ? | ? |
| ... | ... | ... | ... | ... |

### 4. Config-Audit

| Config-Datei | Korrekt geladen? | Unbenutzte Werte | Fehlende Werte |
|---|---|---|---|
| settings.yaml | ? | ? | ? |
| easter_eggs.yaml | ? | ? | ? |
| opinion_rules.yaml | ? | ? | ? |
| humor_triggers.yaml | ? | ? | ? |
| room_profiles.yaml | ? | ? | ? |
| automation_templates.yaml | ? | ? | ? |
| entity_roles_defaults.yaml | ? | ? | ? |
| maintenance.yaml | ? | ? | ? |
| **Addon**: config.yaml | ? | ? | ? |

---

## Regeln

### Gründlichkeits-Pflicht

> **Lies `personality.py` KOMPLETT mit Read — jede Funktion, jede Konstante, jedes Template.** Lies `context_builder.py` KOMPLETT. Lies JEDE YAML-Config-Datei. Prüfe ob JEDER Config-Wert im Code genutzt wird.

### Claude Code Tool-Einsatz in diesem Prompt

| Aufgabe | Tool | Beispiel |
|---|---|---|
| personality.py + context_builder.py lesen | **Read** (parallel) | Beide gleichzeitig lesen |
| Alle YAML-Configs lesen (falls vorhanden) | **Read** (parallel, 2 Batches) | **Batch 1**: `settings.yaml`, `easter_eggs.yaml`, `opinion_rules.yaml`, `humor_triggers.yaml`, `room_profiles.yaml` — **Batch 2**: `automation_templates.yaml`, `entity_roles_defaults.yaml`, `maintenance.yaml`, `addon/config.yaml` |
| Config-Wert im Code finden | **Grep** | `Grep: pattern="sarcasm_level|humor_level" path="assistant/"` |
| Unbenutzte Config-Werte finden | **Grep** pro YAML-Key | `Grep: pattern="KEY_NAME" path="assistant/"` → 0 Treffer = unbenutzt |
| Persönlichkeits-Pfade finden | **Grep** | `Grep: pattern="personality|system_prompt|SYSTEM_PROMPT" path="assistant/"` |
| Addon-Config prüfen | **Read** `addon/config.yaml` + **Grep** nach Keys in Addon-Code |
| Wo wird mood_detector genutzt? | **Grep** | `Grep: pattern="mood_detector|detect_mood|user_mood" path="assistant/"` |

- **MCU-Jarvis ist der Maßstab** — nicht "was klingt nett", sondern "was würde Jarvis sagen"
- Jede Kritik mit **konkretem Verbesserungsvorschlag**
- System-Prompt-Änderungen: **Token-Budget beachten** — kürzer ist oft besser
- Config-Audit: **Grep pro YAML-Key** um Nutzung im Code zu verifizieren, nicht nur die YAML lesen
- Persönlichkeit muss **über alle Pfade identisch** sein — das ist das MCU-Prinzip

---

## ⚡ Übergabe an Prompt 6a

Formatiere am Ende deiner Analyse einen kompakten **Kontext-Block** für Prompt 6:

```
## KONTEXT AUS PROMPT 5: Persönlichkeit & Config

### MCU-Authentizitäts-Score
[Aspekt → Score → 1 Satz Begründung]

### Persönlichkeits-Inkonsistenzen
[Code-Pfad → Problem → Datei:Zeile → Fix-Vorschlag]

### System-Prompt-Verbesserungen
[Konkreter Vorschlag — der wichtigste Abschnitt]

### Config-Probleme
[Unbenutzte Werte, fehlende Werte, Fehler pro YAML-Datei]

### Explainability-Status
[Integriert oder Dead Code?]
```

**Wenn du Prompt 6a in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke (Prompt 1–5) automatisch ein.
