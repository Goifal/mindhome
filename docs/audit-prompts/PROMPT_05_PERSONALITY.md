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

> **[HIER Bug-Report aus Prompt 4 einfügen]**

> **[HIER Konflikt-Karte (Abschnitt "Wie Jarvis klingt") aus Prompt 1 einfügen]**

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

Lies `settings.yaml` komplett.

**Prüfe:**
1. Wird **jeder** Wert in `settings.yaml` tatsächlich im Code verwendet?
2. Gibt es Code der auf Config-Werte zugreift die **nicht existieren**?
3. Werden Default-Werte korrekt gesetzt wenn ein Config-Wert fehlt?
4. `easter_eggs.yaml`, `opinion_rules.yaml`, `room_profiles.yaml` — korrekt geladen?
5. `humor_triggers.yaml` — korrekt geladen und verwendet?

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

---

## Regeln

- **MCU-Jarvis ist der Maßstab** — nicht "was klingt nett", sondern "was würde Jarvis sagen"
- Jede Kritik mit **konkretem Verbesserungsvorschlag**
- System-Prompt-Änderungen: **Token-Budget beachten** — kürzer ist oft besser
- Config-Audit: Jeden Wert **im Code nachverfolgen**, nicht nur die YAML lesen
- Persönlichkeit muss **über alle Pfade identisch** sein — das ist das MCU-Prinzip
