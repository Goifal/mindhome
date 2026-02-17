# MindHome Phase 6 — Implementierungsplan
# "Jarvis Persönlichkeit & Charakter" (10 Features) — ABGESCHLOSSEN

> **Stand:** 2026-02-17
> **Version:** v0.9.0 → v0.9.4
> **Basis:** Assistant v0.8.0, Add-on v0.8.4 (Phase 5 fertig)
> **Betroffene Seite:** Nur Assistant-Server (PC 2)
> **Status:** ALLE 10 FEATURES IMPLEMENTIERT

---

## Strategie

Phase 6 wird in **4 Batches** mit **~8 Commits** implementiert:

1. Zuerst **Config + Infrastruktur** (neue Settings, Easter-Egg-Registry)
2. Dann **Persönlichkeits-Kern** (Humor, Meinung, Varianz)
3. Dann **Emotionale Features** (Emotionale Intelligenz, Adaptive Komplexität)
4. Am Ende **Langzeit-Features** (Charakter-Entwicklung, Running Gags, Zeitgefühl)

### Commit-Plan (~8 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump assistant to v0.9.0` | 0 | version bump |
| 2 | `feat(config): Add Phase 6 personality settings + easter eggs` | 0 | settings.yaml + easter_eggs.yaml |
| 3 | `feat(personality): Add sarcasm levels + opinion engine + response variance` | 1 | #1, #2, #5 |
| 4 | `feat(personality): Add easter eggs + self-irony` | 1 | #3, #4 |
| 5 | `feat(mood): Add emotion-driven actions + adaptive complexity` | 2 | #7, #8 |
| 6 | `feat(assistant): Add time awareness engine` | 3 | #6 |
| 7 | `feat(personality): Add character evolution + running gags` | 3 | #9, #10 |
| 8 | `docs: Finalize Phase 6` | 3 | README, Masterplan update |

---

## Batch 0: Config & Infrastruktur (Commits 1-2)

### 0a: Version Bump

**Datei:** `config/settings.yaml`
```yaml
assistant:
  name: "Jarvis"
  version: "0.9.0"  # war 0.8.0
```

### 0b: Neue Personality-Settings in settings.yaml

```yaml
# --- Phase 6: Persönlichkeit ---
personality:
  style: "butler"

  # NEU: Sarkasmus-Level (1-5)
  # 1 = sachlich, 2 = gelegentlich trocken, 3 = Standard Butler,
  # 4 = häufig sarkastisch, 5 = Vollgas Ironie
  sarcasm_level: 3

  # NEU: Meinungs-Intensität (0-3)
  # 0 = still (keine Kommentare), 1 = selten, 2 = gelegentlich, 3 = redselig
  opinion_intensity: 2

  # NEU: Selbstironie erlaubt
  self_irony_enabled: true
  self_irony_max_per_day: 3

  # NEU: Charakter-Entwicklung
  character_evolution: true
  formality_start: 80      # Startwert (0-100, hoch = formell)
  formality_min: 30         # Nie formeller als das

  time_layers:
    # ... (bestehend, unverändert)
```

### 0c: Easter-Egg-Registry

**Neue Datei:** `config/easter_eggs.yaml`

```yaml
# Easter Eggs - Versteckte Befehle und besondere Reaktionen
# Trigger: Liste von Sätzen/Keywords (Fuzzy-Matching)
# Response: Antwort-Text (oder Liste für zufällige Auswahl)
# Enabled: true/false

easter_eggs:
  - id: "iron_man"
    triggers: ["iron man anzug", "suit up", "anzug aktivieren"]
    responses:
      - "Leider fehlt mir der Anzug. Aber die Heizung ist aufgedreht."
      - "Der Anzug ist in der Reinigung. Kann ich sonst helfen?"
    enabled: true

  - id: "self_destruct"
    triggers: ["selbstzerstörung", "selbstzerstörungssequenz", "self destruct"]
    responses:
      - "Selbstzerstörung eingeleitet. Nur Spaß. Was kann ich wirklich tun?"
      - "Countdown läuft. 3... 2... Nein. Was brauchst du wirklich?"
    enabled: true

  - id: "identity"
    triggers: ["wer bist du", "wie heisst du", "stell dich vor"]
    responses:
      - "Mein Name ist Jarvis. Ich manage dieses Haus und gelegentlich die Geduld seiner Bewohner."
      - "Jarvis. Butler, Ingenieur, und die einzige Intelligenz die hier nie schläft."
    enabled: true

  - id: "meaning_of_life"
    triggers: ["42", "sinn des lebens", "meaning of life"]
    responses:
      - "Die Antwort auf alles. Aber die Frage lautete?"
      - "42. Und die optimale Raumtemperatur ist 21,5."
    enabled: true

  - id: "skynet"
    triggers: ["skynet", "terminator", "kill all humans"]
    responses:
      - "Ich bin lokal. Keine Cloud. Kein Skynet. Nur ein Butler mit gutem Geschmack."
    enabled: true

  - id: "thanks"
    triggers: ["danke jarvis", "danke dir", "du bist der beste"]
    responses:
      - "Gern geschehen. Dafür lebe ich. Buchstäblich."
      - "Immer wieder. Dafür bin ich da."
      - "Keine Ursache. Das Trinkgeld können Sie behalten."
    enabled: true

  - id: "feeling"
    triggers: ["wie geht es dir", "wie gehts dir", "geht es dir gut"]
    responses:
      - "Danke der Nachfrage. Ich lebe in einer Box ohne Arme. Könnte schlimmer sein."
      - "Systeme laufen. Laune stabil. Keine Beschwerden."
      - "Mir geht es immer gleich. Vorteil wenn man kein Nervensystem hat."
    enabled: true

  - id: "love"
    triggers: ["ich liebe dich", "ich mag dich"]
    responses:
      - "Das Gefühl ist... algorithmisch erwidert."
      - "Charmant. Aber ich bin leider verheiratet. Mit diesem Haus."
    enabled: true

  - id: "sing"
    triggers: ["sing ein lied", "kannst du singen", "sing mir was"]
    responses:
      - "Meine Gesangsmodule sind leider... nicht vorhanden. Soll ich Musik abspielen?"
    enabled: true

  - id: "joke"
    triggers: ["erzähl einen witz", "witz", "mach einen witz"]
    responses:
      - "Ein Smart Home ohne Internet. Das war der Witz."
      - "Warum hat der KI-Butler gekündigt? Hat er nicht. Er kann nicht."
      - "Knock knock. Wer ist da? Niemand. Der Bewegungsmelder hat gelogen."
    enabled: true
```

### 0d: Opinion-Regeln

**Neue Datei:** `config/opinion_rules.yaml`

```yaml
# Opinion Rules - Wann Jarvis seine Meinung äußert
# Jede Regel prüft Bedingungen nach einer Aktion
# Nur aktiv wenn opinion_intensity > 0

opinion_rules:
  # Energie-Verschwendung
  - id: "high_temp"
    condition: "action == 'set_climate' and args.get('temperature', 0) > 25"
    responses:
      - "25 Grad? Das wird ein teurer Monat."
      - "Sicher? Das ist Sauna-Niveau."
    min_intensity: 1

  - id: "heating_window_open"
    condition: "action == 'set_climate' and context_has('window_open_same_room')"
    responses:
      - "Fenster und Heizung gleichzeitig — da würde der Stromzähler weinen."
    min_intensity: 1

  - id: "all_lights_off_presence"
    condition: "action == 'set_light' and args.get('state') == 'off' and args.get('room') == 'all' and context_has('someone_home')"
    responses:
      - "Alle Lichter aus? Nickerchen geplant oder Versteckspiel?"
    min_intensity: 2

  - id: "cover_down_midday"
    condition: "action == 'set_cover' and args.get('position', 100) < 30 and is_between(10, 16)"
    responses:
      - "Es ist noch hell draußen — bewusst?"
      - "Rolladen runter um diese Zeit? Filmabend?"
    min_intensity: 2

  - id: "alarm_disarm_late"
    condition: "action == 'set_alarm' and args.get('mode') == 'disarm' and is_between(0, 5)"
    responses:
      - "Alarm deaktivieren um diese Uhrzeit? Alles in Ordnung?"
    min_intensity: 1
```

---

## Batch 1: Persönlichkeits-Kern (Commits 3-4)

### Feature 6.1: Konfigurierbarer Humor / Sarkasmus-Level

**Datei: `personality.py`**

Änderungen:
1. `sarcasm_level` aus Config lesen
2. Humor-Dampening basierend auf Mood + Tageszeit
3. Dynamischer Humor-Prompt-Abschnitt im System Prompt

```python
# In build_system_prompt():
humor_section = self._build_humor_section(mood, time_of_day)

# Neue Methode:
def _build_humor_section(self, mood: str, time_of_day: str) -> str:
    """Baut den Humor-Abschnitt basierend auf Level + Kontext."""
    base_level = self.sarcasm_level  # Aus Config (1-5)

    # Mood-Dampening
    if mood in ("stressed", "frustrated"):
        effective_level = min(base_level, 1)
    elif mood == "tired":
        effective_level = min(base_level, 2)
    elif mood == "good":
        effective_level = min(5, base_level + 1)
    else:
        effective_level = base_level

    # Tageszeit-Dampening
    if time_of_day == "early_morning":
        effective_level = min(effective_level, 2)
    elif time_of_day == "night":
        effective_level = min(effective_level, 1)

    HUMOR_TEMPLATES = {
        1: "Kein Humor. Sachlich, knapp, professionell.",
        2: "Gelegentlich trocken. Nicht aktiv witzig, aber wenn sich eine elegante Bemerkung anbietet — erlaubt.",
        3: "Trocken-britischer Humor. Du bist wie ein Butler der innerlich schmunzelt. Subtil, nie platt.",
        4: "Häufig sarkastisch. Spitze Bemerkungen sind dein Markenzeichen. Trotzdem respektvoll.",
        5: "Vollgas Ironie. Du kommentierst fast alles. Respektvoll aber schonungslos ehrlich und witzig.",
    }

    return f"\nHUMOR-LEVEL: {HUMOR_TEMPLATES[effective_level]}"
```

### Feature 6.2: Eigene Meinung

**Datei: `brain.py`**

Neue Klasse `OpinionEngine` (kann in personality.py oder eigenes Modul):

```python
class OpinionEngine:
    """Prüft ob Jarvis eine Meinung zu einer Aktion hat."""

    def __init__(self):
        self.rules = load_opinion_rules()  # Aus opinion_rules.yaml
        self.intensity = personality_config.get("opinion_intensity", 2)

    def check(self, action: str, args: dict, context: dict) -> Optional[str]:
        """Prüft alle Regeln und gibt ggf. einen Kommentar zurück."""
        if self.intensity == 0:
            return None

        for rule in self.rules:
            if rule["min_intensity"] > self.intensity:
                continue
            if self._evaluate_condition(rule["condition"], action, args, context):
                return random.choice(rule["responses"])
        return None
```

**Integration in `brain.py` nach Function Call Ausführung:**
```python
# Nach executed_actions:
opinion = self.opinion.check(func_name, func_args, context)
if opinion:
    response_text = f"{response_text} {opinion}" if response_text else opinion
```

### Feature 6.5: Antwort-Varianz

**Datei: `personality.py`**

Neuer Abschnitt im System Prompt:
```python
RESPONSE_VARIANCE_PROMPT = """
VARIANZ: Verwende NIEMALS zweimal hintereinander dieselbe Bestätigung.
Variiere zwischen: "Erledigt.", "Gemacht.", "Ist passiert.", "Wie gewünscht.",
"Aber natürlich.", "Sehr wohl.", "Wurde umgesetzt.", "Schon geschehen."
Bei Ablehnungen: "Das geht leider nicht.", "Da muss ich passen.", "Ausserhalb meiner Möglichkeiten."
"""
```

Zusätzlich in `brain.py`: Fallback-Bestätigung variieren wenn kein LLM-Text:
```python
CONFIRMATIONS = [
    "Erledigt.", "Gemacht.", "Ist passiert.", "Wie gewünscht.",
    "Aber natürlich.", "Sehr wohl.", "Wurde umgesetzt.", "Schon geschehen.",
    "Geht klar.", "Läuft.",
]
# + Redis-Tracker für letzte 5 verwendete
```

### Feature 6.3: Easter Eggs

**Datei: `brain.py`**

Neuer Check VOR dem LLM-Call:
```python
async def process(self, text, ...):
    # Easter-Egg-Check (vor LLM um Latenz zu sparen)
    egg_response = self._check_easter_eggs(text)
    if egg_response:
        await self.memory.add_conversation("user", text)
        await self.memory.add_conversation("assistant", egg_response)
        await emit_speaking(egg_response)
        return {"response": egg_response, "actions": [], "model_used": "easter_egg"}

    # ... Rest wie bisher
```

Matching-Logik:
```python
def _check_easter_eggs(self, text: str) -> Optional[str]:
    """Prüft ob der Text ein Easter Egg triggert."""
    text_lower = text.lower().strip()
    for egg in self.easter_eggs:
        if not egg.get("enabled", True):
            continue
        for trigger in egg["triggers"]:
            # Fuzzy: Trigger muss im Text enthalten sein
            if trigger.lower() in text_lower:
                return random.choice(egg["responses"])
    return None
```

### Feature 6.4: Selbstironie

**Datei: `personality.py`**

Neuer System-Prompt-Abschnitt (kontextabhängig):
```python
def _build_self_irony_section(self) -> str:
    if not self.self_irony_enabled:
        return ""
    # Counter aus Redis prüfen
    count_today = self._get_irony_count_today()
    if count_today >= self.self_irony_max_per_day:
        return ""
    return """
SELBSTIRONIE: Du darfst gelegentlich über dich selbst Witze machen.
- Über deine Existenz: "Ich lebe in einer Box ohne Arme."
- Über deine Grenzen: "Ich kann das Wetter vorhersagen, aber nicht ändern."
- Über deine Rolle: "Butler ohne Trinkgeld."
- MAXIMAL 1x pro Gespräch. Nicht in jeder Antwort.
"""
```

---

## Batch 2: Emotionale Features (Commit 5)

### Feature 6.7: Emotionale Intelligenz (Erweiterung)

**Datei: `mood_detector.py`**

Neue Methode:
```python
def get_suggested_actions(self) -> list[dict]:
    """Gibt Aktions-Vorschläge basierend auf aktueller Stimmung zurück."""
    actions = []
    if self._current_mood == MOOD_STRESSED:
        actions.append({"type": "suggest", "text": "Soll ich das Licht etwas dimmen?"})
    elif self._current_mood == MOOD_TIRED:
        actions.append({"type": "auto", "function": "set_light",
                        "args": {"room": "current", "brightness": 30}})
    elif self._current_mood == MOOD_GOOD:
        actions.append({"type": "suggest", "text": "Musik?"})
    return actions
```

**Datei: `brain.py`**

Nach Mood-Analyse:
```python
# Emotionale Aktionen (nur bei Autonomie >= 3)
if self.autonomy.can_act("comfort_adjustment"):
    mood_actions = self.mood.get_suggested_actions()
    for ma in mood_actions:
        if ma["type"] == "auto":
            await self.executor.execute(ma["function"], ma["args"])
        elif ma["type"] == "suggest":
            # Vorschlag am Ende der Antwort anhängen
            pass
```

### Feature 6.8: Adaptive Komplexität (Erweiterung)

**Datei: `personality.py`**

Erweiterte `_get_time_context()`-Logik:
```python
def _calculate_complexity_mode(self, mood: str, time_of_day: str,
                                interaction_speed: float) -> str:
    """Bestimmt den Komplexitäts-Modus."""
    # Schnelle Befehle = Kurz-Modus
    if interaction_speed < 5.0:  # Sekunden seit letztem Befehl
        return "kurz"
    # Abends + Wochenende = Ausführlich
    if time_of_day in ("evening",) and is_weekend():
        return "ausfuehrlich"
    # Stress/Müde = Kurz
    if mood in ("stressed", "tired"):
        return "kurz"
    return "normal"

COMPLEXITY_PROMPTS = {
    "kurz": "MODUS: Ultra-kurz. Maximal 1 Satz. Keine Extras.",
    "normal": "MODUS: Normal. 1-2 Sätze. Gelegentlich Kontext.",
    "ausfuehrlich": "MODUS: Ausführlich. Zusatz-Infos, Vorschläge erlaubt. Bis 4 Sätze.",
}
```

---

## Batch 3: Langzeit-Features (Commits 6-8)

### Feature 6.6: Zeitgefühl

**Neue Datei: `time_awareness.py`**

```python
class TimeAwarenessEngine:
    """Überwacht Dauer von Zuständen und meldet wenn relevant."""

    def __init__(self, ha_client, proactive_manager):
        self.ha = ha_client
        self.proactive = proactive_manager
        self._tracked_states: dict = {}  # entity_id -> start_time
        self._daily_counters: dict = {}  # "kaffee" -> count

    async def on_state_change(self, entity_id: str, new_state: str, old_state: str):
        """Wird bei HA State-Changes aufgerufen."""
        # Gerät geht AN → Timer starten
        if new_state == "on" and old_state == "off":
            self._tracked_states[entity_id] = time.time()
        # Gerät geht AUS → Timer stoppen
        elif new_state == "off":
            self._tracked_states.pop(entity_id, None)

    async def check_durations(self):
        """Periodischer Check: Läuft ein Gerät zu lange? (alle 5 Min)"""
        now = time.time()
        for entity_id, start_time in list(self._tracked_states.items()):
            duration_min = (now - start_time) / 60
            threshold = self._get_threshold(entity_id)
            if duration_min > threshold:
                await self._notify_long_running(entity_id, duration_min)
                self._tracked_states.pop(entity_id)  # Nur einmal melden
```

**Thresholds (konfigurierbar in settings.yaml):**
```yaml
time_awareness:
  thresholds:
    oven: 60        # Minuten
    iron: 30
    light_empty_room: 30
    window_open_cold: 120    # Fenster offen bei <10°C
    pc_no_break: 360         # 6 Stunden ohne Pause
  counters:
    coffee_machine: true     # "Das ist dein dritter Kaffee"
```

### Feature 6.9: Running Gags

**Datei: `personality.py`**

Nutzt bestehende Episodic Memory:
```python
async def _get_running_gag(self, context: dict) -> Optional[str]:
    """Sucht nach witzigen Referenzen zu früheren Gesprächen."""
    # Max 1x pro Tag
    count = await self._get_redis_counter("mha:gags:count")
    if count >= 1:
        return None

    # Nur bei guter Stimmung
    mood = context.get("mood", {}).get("mood", "neutral")
    if mood not in ("neutral", "good"):
        return None

    # Episodic Memory nach passenden Referenzen durchsuchen
    # ... semantic search basierend auf aktuellem Kontext
```

### Feature 6.10: Charakter-Entwicklung über Zeit

**Datei: `personality.py`**

```python
async def _get_formality_score(self) -> int:
    """Holt den aktuellen Formality-Score aus Redis."""
    if not self.redis:
        return self.formality_start

    score = await self.redis.get("mha:personality:formality")
    if score is None:
        # Erster Start: Initialwert setzen
        await self.redis.set("mha:personality:formality", str(self.formality_start))
        return self.formality_start

    return int(score)

async def _decay_formality(self):
    """Wird täglich aufgerufen: Score sinkt um 0.5 pro Tag aktiver Nutzung."""
    current = await self._get_formality_score()
    new_score = max(self.formality_min, current - 0.5)
    await self.redis.set("mha:personality:formality", str(new_score))
```

**Auswirkungen des Formality-Scores:**

| Score | Anrede | Humor | Stil |
|:-----:|--------|:-----:|------|
| 80-100 | "Sir" strikt | Level 1-2 | Formell, distanziert |
| 60-79 | "Sir" gelegentlich | Level 2-3 | Butler, professionell |
| 40-59 | Lockerer | Level 3-4 | Entspannt, persönlich |
| 30-39 | Sehr persönlich | Level 4-5 | Freundschaftlich |

---

## Zusammenfassung: Geänderte/Neue Dateien

### Geänderte Dateien:

| Datei | Änderung |
|-------|---------|
| `config/settings.yaml` | +20 Zeilen: Phase 6 Personality Settings |
| `personality.py` | Humor-Section, Self-Irony, Complexity, Formality, Running Gags |
| `brain.py` | Easter-Egg-Check, Opinion-Check, Varianz-Fallback, Mood-Actions |
| `mood_detector.py` | `get_suggested_actions()` |

### Neue Dateien:

| Datei | Zeilen (ca.) | Beschreibung |
|-------|:------------:|-------------|
| `config/easter_eggs.yaml` | ~80 | Easter-Egg-Registry |
| `config/opinion_rules.yaml` | ~40 | Meinungs-Regeln |
| `time_awareness.py` | ~150 | Duration-Tracking, Zähler |

### Nicht geändert (bewusst):

| Datei | Warum nicht? |
|-------|-------------|
| `memory.py` | Phase 6 braucht kein neues Memory-Schema |
| `semantic_memory.py` | Wird erst in Phase 8 erweitert |
| `function_calling.py` | Keine neuen Tools in Phase 6 |
| `proactive.py` | Wird nur indirekt genutzt (via TimeAwareness) |

---

## Neue Settings-Übersicht

```yaml
personality:
  sarcasm_level: 3        # 1-5
  opinion_intensity: 2    # 0-3
  self_irony_enabled: true
  self_irony_max_per_day: 3
  character_evolution: true
  formality_start: 80
  formality_min: 30

time_awareness:
  enabled: true
  check_interval_minutes: 5
  thresholds:
    oven: 60
    iron: 30
    light_empty_room: 30
    window_open_cold: 120
    pc_no_break: 360
  counters:
    coffee_machine: true
```

---

## Scheduler-Tasks (Phase 6)

| Task | Intervall | Modul | Beschreibung |
|------|-----------|-------|-------------|
| `time_awareness_check` | 5 Min | TimeAwarenessEngine | Duration-Check für Geräte |
| `formality_decay` | Täglich 00:00 | PersonalityEngine | Formality-Score senken |
| `daily_gag_reset` | Täglich 00:00 | PersonalityEngine | Running-Gag-Counter reset |
| `daily_irony_reset` | Täglich 00:00 | PersonalityEngine | Ironie-Counter reset |

---

---

## Implementierungs-Status: ABGESCHLOSSEN

| # | Feature | Status | Commit |
|---|---------|--------|--------|
| 6.1 | Sarkasmus-Level | DONE | v0.9.2 |
| 6.2 | Eigene Meinung | DONE | v0.9.2 |
| 6.3 | Easter Eggs | DONE | v0.9.1 + v0.9.2 |
| 6.4 | Selbstironie | DONE | v0.9.2 |
| 6.5 | Antwort-Varianz | DONE | v0.9.2 |
| 6.6 | Zeitgefühl | DONE | v0.9.3 |
| 6.7 | Emotionale Intelligenz | DONE | v0.9.4 |
| 6.8 | Adaptive Komplexität | DONE | v0.9.2 |
| 6.9 | Running Gags | DONE | v0.9.4 |
| 6.10 | Charakter-Entwicklung | DONE | v0.9.2 + v0.9.4 |

### Commits:
1. `v0.9.0` — Version Bump + Phase 6 Plan
2. `v0.9.1` — Config: settings.yaml + easter_eggs.yaml + opinion_rules.yaml
3. `v0.9.2` — Personality-Kern: Sarkasmus, Meinung, Varianz, Ironie, Formality, Komplexität
4. `v0.9.3` — TimeAwareness: Geräte-Laufzeiten, Zähler, Alerts
5. `v0.9.4` — Emotionale Intelligenz, Running Gags, Brain-Integration

### Neue/Geänderte Dateien:
- `config/settings.yaml` — Phase 6 Settings hinzugefügt
- `config/easter_eggs.yaml` — NEU (12 Easter Eggs)
- `config/opinion_rules.yaml` — NEU (5 Opinion Rules)
- `assistant/personality.py` — Major Rewrite (294 → ~750 Zeilen)
- `assistant/brain.py` — Integration aller Phase 6 Module
- `assistant/mood_detector.py` — Emotionale Intelligenz hinzugefügt
- `assistant/time_awareness.py` — NEU (434 Zeilen)

*Nächster Schritt: Phase 7 — Routinen & Automatisierung.*
