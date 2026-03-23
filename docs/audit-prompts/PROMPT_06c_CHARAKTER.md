# Prompt 6c: Charakter — Persönlichkeit harmonisieren & Config aufräumen

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. In 6a hast du stabilisiert, in 6b die Architektur aufgeräumt. Jetzt machst du Jarvis zu **einem** Charakter.

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details. Kurzfassung: Thinking-Mode bei Tool-Calls deaktivieren (`supports_think_with_tools: false`), `character_hint` in model_profiles nutzen.

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Analyse-Prompts:

```
Read: docs/audit-results/RESULT_05_PERSOENLICHKEIT.md
Read: docs/audit-results/RESULT_06a_STABILISIERUNG.md
Read: docs/audit-results/RESULT_06b_ARCHITEKTUR.md
```

> Falls eine Datei nicht existiert → überspringe sie. Wenn KEINE Result-Dateien existieren, nutze Kontext-Blöcke aus der Konversation oder starte mit Prompt 01.

---

## Fokus dieses Prompts

**Drei Dinge**: Persönlichkeit vereinheitlichen, Config-Fehler fixen, mittlere Bugs beheben.

### Harmonisierungs-Prinzipien in diesem Prompt

- **Eine Stimme**: Alle Antwort-Pfade durch dieselbe Persönlichkeits-Pipeline
- **Ein Charakter**: Gleicher Jarvis ob Frage, Warnung oder Briefing
- **Ein Flow** (Feinschliff): 🟡 Bugs fixen, Dead Code entfernen

---

## Aufgabe

### ⚠️ Phase Gate: Regression-Check vor Start

1. **Tests ausführen**: `cd assistant && python -m pytest --tb=short -q`
2. **Vergleiche mit 6b-Checkpoint**: Alle Tests noch grün?
3. Falls Tests fehlschlagen → zurück zu 6b, dort fixen

### Schritt 1: System-Prompt optimieren (aus Prompt 5)

Lies `personality.py` — besonders `SYSTEM_PROMPT_TEMPLATE` und `build_system_prompt()`.

**Implementiere die Verbesserungen aus Prompt 5:**
1. **MCU-Authentizität erhöhen**: Klingt der Prompt wie der echte Jarvis?
2. **Token-Effizienz**: Überflüssige Anweisungen kürzen
3. **Klarheit**: Widersprüchliche Anweisungen auflösen
4. **Overloading reduzieren**: Prompt fokussieren, nicht alles reinpacken

> **Regel**: Kürzer ist oft besser. Jede Zeile im System-Prompt kostet Token die für Memory und Kontext fehlen.

### Schritt 2: Persönlichkeits-Konsistenz herstellen (Konflikt D aus Prompt 1)

**Alle Antwort-Pfade müssen durch dieselbe Persönlichkeits-Pipeline:**

| Pfad | Soll-Zustand | Prüfen |
|---|---|---|
| Normale Antwort | Durch `personality.py` → `context_builder.py` | ✅ Standard-Pfad |
| Proaktive Warnung (`proactive.py`) | Durch dieselbe Pipeline | Hat eigene Templates? |
| Morgen-Briefing (`routine_engine.py`) | Durch dieselbe Pipeline | Hat eigene Templates? |
| Fehler-Meldung | Durch dieselbe Pipeline | Oder hardcoded Strings? |
| Function-Call-Bestätigung | Durch dieselbe Pipeline | "Licht ist an" — Jarvis-Ton? |
| Autonome Aktion | Durch dieselbe Pipeline | Oder eigene Formulierung? |

**Für jeden Pfad der die Pipeline umgeht:**
1. **Read** — Das Modul lesen, eigene Templates finden
2. **Grep** — `pattern="system_prompt|SYSTEM_PROMPT|template" path="assistant/assistant/proactive.py"` etc.
3. **Edit** — Eigene Templates entfernen, durch Pipeline-Aufruf ersetzen
4. **Bash** — Tests laufen lassen

## Banned Phrases fuer Qwen 3.5

Diese Floskeln MUESSEN in brain.py _filter_response gefiltert werden:
- "Natuerlich!"
- "Gerne!"
- "Selbstverstaendlich!"
- "Kann ich dir noch etwas helfen?"
- "Kann ich sonst noch etwas tun?"
- "Ich schalte jetzt"
- "Ich werde jetzt"

Pruefe mit: `grep "banned_phrases\|banned_starters" brain.py`

### Schritt 3: Config aufräumen (aus Prompt 5)

Arbeite die Config-Audit-Ergebnisse aus Prompt 5 ab:

**3a) Unbenutzte Config-Werte entfernen:**
Für jeden Wert in `settings.yaml` der laut Prompt 5 nicht im Code genutzt wird:
```
Grep: pattern="KEY_NAME" path="assistant/" output_mode="files_with_matches"
```
Wenn 0 Treffer → Wert entfernen oder dokumentieren warum er existiert.

**3b) Fehlende Config-Werte hinzufügen:**
Code der auf Config-Werte zugreift die nicht in `settings.yaml` stehen → Default-Werte in YAML dokumentieren.

**3c) YAML-Dateien korrekt laden:**
Prüfe ob `easter_eggs.yaml`, `opinion_rules.yaml`, `humor_triggers.yaml`, `room_profiles.yaml`, `automation_templates.yaml`, `entity_roles_defaults.yaml`, `maintenance.yaml` alle korrekt geladen werden.

**3d) Addon-Config-Überlappung:**
Prüfe ob `addon/config.yaml` und `assistant/config/settings.yaml` sich widersprechen.

### Schritt 4: 🟡 Mittlere Bugs fixen (aus Prompt 4)

Logik-Fehler, fehlende Integrationen, Inkonsistenzen. Arbeite die 🟡-Bug-Liste ab (aus dem Bug-Zuordnungs-Tabelle in P06a Kontext-Block).

### Schritt 5: Sarkasmus-System (5 Stufen) verifizieren & fixen

> **Gap aus P05**: Das Sarkasmus-Level-System (1–5) wird analysiert aber nie gefixt/getestet.

**5a) Sarkasmus-Level-Mechanik prüfen:**
```
Grep: pattern="sarcasm|sarkasm|humor_level|irony_level" path="assistant/assistant/" output_mode="content"
Grep: pattern="sarcasm|sarkasm" path="assistant/config/" output_mode="content"
```

**5b) Für jedes Sarkasmus-Level (1–5) verifizieren:**

> **WICHTIG: Sarkasmus-Level ≠ Eskalations-Stufe (P06d Schritt 4)**
> - **Sarkasmus-Level (1–5)** = WIE WITZIG Jarvis spricht (Humor-Dimension)
> - **Eskalations-Stufe (1–4)** = WIE ERNST die Situation ist (Gefahren-Dimension)
> - Beides sind **unabhängige Dimensionen**. Jarvis kann bei Eskalationsstufe 1 (alles okay) Sarkasmus-Level 3 nutzen, aber bei Eskalationsstufe 4 (Notfall) ist Sarkasmus IMMER 0.

| Level | Erwartetes Verhalten | Prüfen |
|---|---|---|
| 1 | Höflich, kein Sarkasmus | Gibt es einen Code-Pfad der Level 1 erzeugt? |
| 2 | Leicht trocken | Wird der Ton merklich anders als Level 1? |
| 3 | Britisch-sarkastisch (Standard-Jarvis) | Ist dies der Default? |
| 4 | Spöttisch, direkter | Gibt es Trigger die auf Level 4 eskalieren? |
| 5 | Maximaler Sarkasmus ("Stark-Level") | Wird Level 5 jemals erreicht? |

**5c) Fixes:**
- Falls Level-System existiert aber nicht funktioniert → Code-Pfad reparieren
- Falls Level-System nicht existiert → In `personality.py` als einfaches Template-System einbauen
- Falls Eskalation (z.B. "dumme Frage" → höheres Level) nicht funktioniert → Trigger fixen
- **Test**: Gleiche Frage bei Level 1 und Level 5 muss unterschiedliche Antworten erzeugen
- **Integration mit Eskalation**: Bei Eskalationsstufe ≥3 (P06d) muss Sarkasmus automatisch auf 0 gesetzt werden

### Schritt 6: Mood-Detection → Persönlichkeit integrieren

> **Gap aus P05**: `mood_detector.py` existiert aber beeinflusst den Ton nicht nachweislich.

**6a) Mood-System analysieren:**
```
Grep: pattern="mood_detector|MoodDetector|detect_mood|current_mood" path="assistant/assistant/" output_mode="content"
Read: assistant/assistant/mood_detector.py (falls vorhanden)
```

**6b) Integration prüfen:**
- Wird `mood_detector` in `brain.py` oder `personality.py` aufgerufen?
- Fließt das erkannte Mood in den System-Prompt oder die Response-Generierung ein?
- Gibt es einen Code-Pfad: User sagt etwas Trauriges → Jarvis wird empathischer?

**6c) Falls NICHT integriert:**
```python
# In personality.py build_system_prompt() oder context_builder.py:
mood = await mood_detector.get_current_mood()
if mood in ("sad", "frustrated"):
    personality_hint += " Sei etwas einfühlsamer, aber bleib Jarvis."
elif mood in ("happy", "excited"):
    personality_hint += " Mehr Humor erlaubt."
```

**Test**: Sage "Ich hatte einen schlechten Tag" → Jarvis-Ton muss sich merklich anpassen (weniger Sarkasmus, mehr Empathie — aber immer noch Jarvis, nicht "Therapeuten-Bot").

### Schritt 7: Easter Eggs Trigger-Zuverlässigkeit

> **Gap aus P05**: Easter Eggs YAML wird geladen, aber triggern die Easter Eggs auch zuverlässig?

**7a) Easter-Egg-Trigger-Mechanik analysieren:**
```
Read: assistant/config/easter_eggs.yaml
Grep: pattern="easter_egg|EasterEgg|trigger.*easter|check.*easter" path="assistant/assistant/" output_mode="content"
```

**7b) Für JEDES Easter Egg in der YAML prüfen:**
1. Gibt es einen Code-Pfad der diesen Trigger erkennt?
2. Wird der Trigger-Text korrekt gematched (exact match, regex, keyword)?
3. Kommt die Easter-Egg-Antwort tatsächlich beim User an (oder wird sie vom Filter verschluckt)?

**7c) MCU-Authentizität der Easter Eggs prüfen:**
- Referenzieren sie echte MCU-Szenen/Zitate?
- Passen sie zum Jarvis-Charakter (nicht zu Iron Man, nicht zu Vision)?
- Sind sie auf Deutsch authentisch oder krampfhaft übersetzt?

**7d) Falls Easter Eggs nicht triggern:**
- Trigger-Matching reparieren (z.B. case-insensitive, Fuzzy-Match)
- Sicherstellen dass Easter-Egg-Check VOR dem normalen LLM-Call läuft
- Easter-Egg-Antwort NICHT durch `_filter_response` oder `banned_phrases` filtern lassen

### Schritt 8: Dead Code systematisch entfernen

> **Gap aus P04**: Dead Code wird gefunden aber nicht systematisch aufgeräumt.

**PFLICHT**: Erstelle eine vollständige Dead-Code-Tabelle bevor du etwas löschst.

Module oder Funktionen die laut Prompt 4 (Dead-Code-Liste) nie aufgerufen werden:

**8a) Dead-Code-Inventar erstellen:**

```
### Dead-Code-Inventar

| # | Modul/Funktion | Typ | Grep-Ergebnis | Dynamisch geladen? | Aktion |
|---|---|---|---|---|---|
| 1 | [Name] | Modul/Funktion/Klasse | X Treffer | Ja/Nein | Entfernen/Behalten/Prüfen |
| 2 | ... | ... | ... | ... | ... |
```

**8b) Für JEDES Element im Inventar:**
- **Grep** um zu verifizieren: `pattern="modul_name|funktion_name" path="assistant/"` → 0 Treffer
- **Dynamisches Laden prüfen**: `Grep: pattern="importlib|__import__|getattr.*module" path="assistant/"` → Falls ja, könnte das Modul dynamisch geladen werden
- **Config-Referenz prüfen**: `Grep: pattern="modul_name" path="assistant/config/"` → Falls in Config referenziert, wird es wahrscheinlich dynamisch geladen
- Wenn tatsächlich Dead Code (0 Treffer + nicht dynamisch): Entfernen
- **Vorsicht**: Manche Module werden dynamisch geladen — Grep prüft nur statische Imports

**8c) Dead-Code-Bericht:**
```
### Dead Code entfernt
- [X] Module entfernt, [Y] Funktionen entfernt
- [Z] Module BEHALTEN weil dynamisch geladen
- Gesamt eingesparte Zeilen: ~N
```

### Schritt 9: Proaktivitäts-Engine — Jarvis warnt BEVOR man fragt

> **MCU-Referenz**: Jarvis erkennt Probleme und meldet sie AKTIV — "Sir, ich registriere einen Druckabfall im linken Triebwerk." Tony hat nicht gefragt. Jarvis hat es selbst erkannt.

**9a) Bestehende Proaktivität prüfen:**
```
Grep: pattern="proactive|proaktiv|warning_check|check_warnings" path="assistant/assistant/" output_mode="content"
Read: assistant/assistant/proactive.py (falls vorhanden)
```

**9b) Proaktive Trigger-Tabelle definieren:**

Diese Tabelle muss in `assistant/config/proactive_rules.yaml` oder direkt in `proactive.py` existieren:

| Szenario | Trigger-Bedingung | Jarvis sagt | Wiederholung | Eskalation |
|---|---|---|---|---|
| Fenster offen + Regen | `window.state=open AND weather=rain` | "Sir, Fenster offen bei Regen." | Nach 3 Min, dann alle 10 Min | Stufe 3 nach 15 Min → autonom schließen |
| Tür offen + Nacht | `door.state=open AND hour>22` | "Haustür steht offen, Sir." | Sofort + nach 5 Min | Stufe 3 nach 10 Min |
| Temperatur zu hoch | `indoor_temp > 28` | "28 Grad drinnen, Sir. Klimaanlage?" | Nach 15 Min | Stufe 2 nach 30 Min |
| Gerät nicht erreichbar | `device.state=unavailable` | "Ich erreiche {device} nicht mehr." | Sofort (einmalig) | Stufe 2 wenn kritisches Gerät |
| Heizung + Fenster offen | `heating=on AND window=open` | "Heizung läuft bei offenem Fenster, Sir." | Sofort + nach 5 Min | Stufe 2 nach 10 Min |
| Rauchmelder offline | `smoke_detector.state=unavailable` | "Rauchmelder {name} meldet sich nicht. Das ist ernst." | Sofort | Stufe 4 (IMMER melden) |
| Unbekannte Bewegung nachts | `motion=detected AND nobody_home AND hour>23` | "Bewegung erkannt bei leerer Wohnung." | Sofort | Stufe 3 sofort |
| Energieverbrauch anomal | `power > 2x average` | "Ungewöhnlich hoher Stromverbrauch, Sir." | Nach 30 Min | Stufe 1 (nur Info) |

**9c) Implementierungs-Check:**
```
Grep: pattern="async.*check_proactive|proactive.*loop|warning.*loop" path="assistant/assistant/" output_mode="content"
```

Falls NICHT vorhanden, muss implementiert werden:
```python
# In brain.py oder proactive.py:
async def _proactive_monitor_loop(self):
    """Läuft alle 30s, prüft Trigger, gibt nur NEUE Warnungen aus."""
    while self._running:
        for rule in self._proactive_rules:
            if await self._check_trigger(rule) and not self._already_warned(rule):
                message = await self._format_proactive_warning(rule)
                await self.speaker_manager.speak_response(message)
                self._mark_warned(rule)
        await asyncio.sleep(30)
```

**9d) Ton der proaktiven Warnungen:**
- MUSS durch `personality.py` formatiert werden (gleicher Jarvis-Ton)
- Kurz, faktisch, keine Floskeln
- "Sir, [Fakt]. [Vorschlag?]" — NICHT "Achtung! Es könnte ein Problem geben!"

### Schritt 10: Opinion-System — Jarvis hat Standpunkte

> **MCU-Referenz**: "Darf ich anmerken, Sir, dass Sie seit 72 Stunden nicht geschlafen haben?" — Jarvis gibt ungefragt seine Meinung ab wenn es relevant ist.

**10a) opinion_rules.yaml prüfen:**
```
Read: assistant/config/opinion_rules.yaml
Grep: pattern="opinion|standpunkt|meinung|anmerken" path="assistant/assistant/" output_mode="content"
```

**10b) Falls leer oder nicht genutzt — Jarvis-Standpunkte definieren:**

```yaml
# opinion_rules.yaml — Jarvis' Werte und Standpunkte
opinions:
  energy_efficiency:
    trigger_keywords: ["heiz auf 26", "alle lichter an", "heizung voll"]
    response_hint: "Hinweis auf Energieverbrauch. Trocken, nicht belehrend."
    example: "26 Grad, Sir? Das ist... ambitioniert für die Jahreszeit."

  security_first:
    trigger_keywords: ["tür offen lassen", "alarm aus", "kamera deaktivieren"]
    response_hint: "Sicherheitsbedenken äußern. Bestimmt aber nicht blockierend."
    example: "Ich würde davon abraten, Sir. Aber es ist Ihr Haus."

  user_wellbeing:
    trigger_keywords: ["schlecht geschlafen", "müde", "gestresst"]
    response_hint: "Subtiler Hinweis, nicht Therapeut spielen."
    example: "Soll ich die Beleuchtung etwas angenehmer gestalten?"

  unnecessary_actions:
    trigger_keywords: ["licht an", "heizung an"]
    trigger_condition: "already_on"  # Gerät ist schon an
    response_hint: "Trocken darauf hinweisen."
    example: "Das Licht ist bereits an, Sir. Soll es heller?"

  bad_timing:
    trigger_keywords: ["party", "musik laut", "alle lichter"]
    trigger_condition: "late_night"  # Nach 22 Uhr
    response_hint: "Dezent auf Uhrzeit hinweisen."
    example: "Es ist 23 Uhr, Sir. Die Nachbarn wären vermutlich dankbar für Zurückhaltung."
```

**10c) Integration in brain.py:**
```python
# In _build_context() oder vor dem LLM-Call:
opinion_hint = await self._check_opinions(user_message, context)
if opinion_hint:
    system_prompt += f"\nDEIN STANDPUNKT: {opinion_hint}"
```

**10d) Wichtig:** Jarvis' Meinung ist KEIN Veto. Er äußert sie, führt dann trotzdem aus.
- "26 Grad, Sir? Ambitioniert. Wird eingestellt." — Meinung + Ausführung in einer Antwort.

### Schritt 11: Situationsbewusstsein — Raum-Kontext praktisch nutzen

> **MCU-Referenz**: Jarvis weiß IMMER wo Tony ist und was um ihn herum passiert. "Die Temperatur in der Werkstatt beträgt 14 Grad, Sir. Soll ich die Heizung aktivieren?"

**11a) Wie wird der aktuelle Raum bestimmt?**
```
Grep: pattern="current_room|active_room|request_context|speaker_source|media_player.*source" path="assistant/assistant/" output_mode="content"
```

**11b) Raum-Detection muss folgende Quellen nutzen (Priorität):**

| Priorität | Quelle | Wie | Beispiel |
|---|---|---|---|
| 1 | **Explizit im Befehl** | User sagt "im Schlafzimmer" | "Licht im Schlafzimmer an" |
| 2 | **Sprach-Input-Quelle** | Welcher Lautsprecher/Mikrofon hat den Befehl empfangen? | media_player.wohnzimmer → Wohnzimmer |
| 3 | **Letzter Bewegungsmelder** | Welcher Raum hat zuletzt Bewegung erkannt? | motion.flur → Flur |
| 4 | **Default aus Config** | `settings.yaml → default_room` | Wohnzimmer |

**11c) In context_builder.py oder brain.py implementieren:**
```python
async def _resolve_room_context(self, user_message: str, source_device: str) -> str:
    """Bestimmt in welchem Raum der User ist."""
    # Prio 1: Explizit im Befehl
    room = self._extract_room_from_message(user_message)
    if room:
        return room

    # Prio 2: Sprach-Input-Quelle
    if source_device:
        room = self._device_to_room(source_device)
        if room:
            return room

    # Prio 3: Letzter Bewegungsmelder
    room = await self._get_last_motion_room()
    if room:
        return room

    # Prio 4: Default
    return self.config.get("default_room", "Wohnzimmer")
```

**11d) Raum-Kontext im System-Prompt nutzen:**
```
Dein Kontext: User spricht aus "{room}".
- "Licht an" ohne Raum → {room}
- "hier" → {room}
- "zu kalt" → Temperatur in {room}
```

**11e) Verifizieren:** Der Raum-Kontext muss in `_deterministic_tool_call()` (P06e) und im System-Prompt verwendet werden.

---

## Output-Format

### 1. System-Prompt-Änderungen

```
### System-Prompt Optimierung
- **Token vorher**: ~X
- **Token nachher**: ~Y
- **Geändert**: [Was und warum]
- **MCU-Score vorher**: X/10
- **MCU-Score nachher**: Y/10
```

### 2. Persönlichkeits-Fixes

| Pfad | Problem | Fix | Datei:Zeile |
|---|---|---|---|
| Proaktive Warnung | Eigene Templates | Pipeline-Aufruf | proactive.py:123 |
| ... | ... | ... | ... |

### 3. Config-Bereinigung

| Config-Datei | Entfernt | Hinzugefügt | Korrigiert |
|---|---|---|---|
| settings.yaml | X Werte | Y Werte | Z Werte |
| ... | ... | ... | ... |

### 4. 🟡 Bug-Fixes

```
### 🟡 Bug #X: Kurzbeschreibung
- **Datei**: path:zeile
- **Fix**: Was geändert
- **Tests**: ✅/❌
```

### 5. Dead Code entfernt

| Modul/Funktion | Grund | Verifiziert mit Grep |
|---|---|---|
| ? | Nie aufgerufen | 0 Treffer für "X" |

---

## Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren mit Eskalation (siehe unten)
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

## Eskalations-Regel

Wenn ein Bug NICHT gefixt werden kann, dokumentiere ihn im OFFEN-Block mit:
- **Severity**: 🔴 KRITISCH / 🟠 HOCH / 🟡 MITTEL
- **Grund**: Warum nicht loesbar (Regression, Architektur-Umbau noetig, Domainwissen fehlt, etc.)
- **Eskalation**:
  - `NAECHSTER_PROMPT` — Bug gehoert thematisch in P06d–P06f
  - `ARCHITEKTUR_NOETIG` — Fix erfordert groesseren Umbau, naechster Durchlauf
  - `MENSCH` — Braucht menschliche Entscheidung oder Domainwissen

**MENSCH-Bugs: NICHT stoppen.** Triff die beste Entscheidung selbst, dokumentiere WARUM, und mach weiter.

## Regeln

### Gründlichkeits-Pflicht

> **Lies `personality.py` KOMPLETT mit Read. Lies JEDE YAML-Config mit Read. Prüfe JEDEN Config-Wert mit Grep.**

- **Persönlichkeit ist Kern-Feature** — nicht "nice to have"
- **Config-Werte immer mit Grep verifizieren** — nicht nur YAML lesen
- **Dead Code nur entfernen wenn Grep 0 Treffer zeigt**
- **Tests nach jedem Fix**
- **Keine Security/Resilience hier** — das kommt in 6d
- **⚠️ System-Prompt-Änderungen**: Bevor du Anweisungen im System-Prompt kürzst, prüfe ob ein P6a/6b-Fix davon abhängt. Keine Anweisungen entfernen die ein Bug-Fix eingeführt hat!

### ⚠️ Phase Gate: Checkpoint am Ende von 6c

1. **Alle Tests laufen lassen**: `cd assistant && python -m pytest --tb=short -q`
2. **Git-Tag setzen**: `git tag checkpoint-6c`

---

## MCU-Score Bewertungs-Rubrik

> **Gap**: "MCU-Score 7/10" ist bedeutungslos ohne konkrete Anker. Hier die verbindliche Rubrik:

| Score | Beschreibung | Konkrete Kriterien |
|---|---|---|
| **10/10** | Perfekter MCU-Jarvis | Nie Floskeln, immer "Sir", britisch-trocken, eigene Meinung, proaktive Hinweise ohne Aufforderung, Sarkasmus Level 3 als Default, Easter Eggs triggern zuverlässig |
| **9/10** | Exzellent | Wie 10, aber gelegentlich etwas zu höflich oder zu lang |
| **8/10** | Sehr gut | Klarer Jarvis-Charakter erkennbar, aber 1-2 Floskeln pro 20 Antworten, Sarkasmus nicht immer konsistent |
| **7/10** | Gut (Minimum) | Jarvis-Ton erkennbar, aber manchmal generischer Assistent-Ton ("Gerne!"), Humor nicht immer treffend |
| **6/10** | Akzeptabel | Manchmal Jarvis, manchmal generisch, Easter Eggs selten, Mood beeinflusst Ton kaum |
| **5/10** | Mittelmäßig | Mehr generischer Assistent als Jarvis, häufige Floskeln, kein Sarkasmus |
| **≤4/10** | Ungenügend | Kein erkennbarer Jarvis-Charakter, Standard-Chatbot-Antworten |

**Bewertungs-Methode**: Prüfe 10 verschiedene Antwort-Szenarien und bewerte jedes einzeln:
1. Einfache Frage ("Wie spät ist es?")
2. Gerätesteuerung-Bestätigung ("Licht ist an")
3. Fehler-Meldung ("HA nicht erreichbar")
4. Morgen-Briefing
5. Proaktive Warnung ("Fenster offen bei Regen")
6. Sarkasmus-Trigger ("Das war eine dumme Frage")
7. Easter-Egg-Trigger
8. Emotionale Situation ("Ich bin traurig")
9. Wissens-Frage ("Wer war Alan Turing?")
10. Multi-Command-Bestätigung ("Alles erledigt")

**Jedes Szenario**: Klingt die Antwort nach MCU-Jarvis (Paul Bettany)? Ja = 1 Punkt, Nein = 0 Punkte.

## Erfolgs-Kriterien

- □ MCU-Score >= 7/10 (nach obiger Rubrik bewertet)
- □ System-Prompt unter 800 Tokens Basis
- □ Floskeln in banned_phrases
- □ Sarkasmus-Level-System funktioniert (Level 1 ≠ Level 5)
- □ Mood-Detection beeinflusst Antwort-Ton nachweislich
- □ Mindestens 3 Easter Eggs triggern zuverlässig
- □ Tests bestehen nach allen Aenderungen

### Erfolgs-Check (Schnellpruefung)

```
□ grep "Natuerlich\|Gerne\|Selbstverstaendlich" personality.py → in banned_phrases Liste
□ grep "banned_phrases\|BANNED\|_banned" brain.py → Filter aktiv
□ python3 -m py_compile assistant/assistant/personality.py → kein Error
□ cd /home/user/mindhome/assistant && python -m pytest tests/ -x --tb=short -q
```

## ⚡ Übergabe an Prompt 6d

```
## KONTEXT AUS PROMPT 6c: Charakter

### System-Prompt
[Token-Änderung, MCU-Score-Änderung, wichtigste Änderungen]

### Persönlichkeits-Fixes
[Welche Pfade jetzt durch die Pipeline gehen]

### Config-Status
[Was bereinigt wurde, was noch offen ist]

### Gefixte 🟡 Bugs
[Bug-# → Datei → Was gefixt]

### Entfernter Dead Code
[Liste]

### Offene Punkte für 6d
[Was noch fehlt]
```

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_06c_CHARAKTER.md
> ```
> Dies ermöglicht nachfolgenden Prompts den automatischen Zugriff auf deine Analyse.

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
