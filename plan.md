# Implementierungsplan: Pre-Classifier fuer selektive Subsystem-Aktivierung

## Ziel
Einen leichtgewichtigen Pre-Classifier **vor** den teuren `context_builder.build()` und `asyncio.gather()` Calls (brain.py:1066-1117) einbauen, der bestimmt welche der 10+ parallelen Subsysteme wirklich gebraucht werden. Das spart bei einfachen Befehlen ("Licht an") mehrere hundert Millisekunden Latenz.

---

## Architektur-Uebersicht

### Aktueller Ablauf (brain.py:1066-1117)
```
User-Input → Pre-Classification Shortcuts (Zeile 478-1049)
           → Context Build (IMMER alles, 10s timeout)
           → asyncio.gather (IMMER alle 10 Subsysteme)
           → Model Selection → LLM → Response
```

### Neuer Ablauf
```
User-Input → Pre-Classification Shortcuts (unveraendert)
           → RequestProfile = pre_classify(text)  ← NEU
           → Context Build (nur benoetigte Daten)
           → asyncio.gather (nur benoetigte Subsysteme)
           → Model Selection → LLM → Response
```

---

## Schritt 1: `RequestProfile` Dataclass + `PreClassifier` Klasse

**Neue Datei:** `assistant/assistant/pre_classifier.py`

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class RequestProfile:
    """Bestimmt welche Subsysteme fuer eine Anfrage aktiviert werden."""
    category: str  # "device_command", "knowledge", "memory", "general"

    # Context Builder Flags
    need_house_status: bool = True      # HA states (fast, ~50ms)
    need_mindhome_data: bool = True     # REST to addon (~100ms)
    need_activity: bool = True          # Activity detection
    need_room_profile: bool = True      # Raum-Profil
    need_weather: bool = True           # Wetter-Warnungen
    need_memories: bool = True          # Semantic Memory search

    # Parallel Subsystem Flags (asyncio.gather)
    need_mood: bool = True              # MoodDetector.analyze()
    need_formality: bool = True         # PersonalityEngine.get_formality_score()
    need_irony: bool = True             # PersonalityEngine._get_self_irony_count_today()
    need_time_hints: bool = True        # TimeAwareness.get_context_hints()
    need_security: bool = True          # ThreatAssessment.get_security_score()
    need_cross_room: bool = True        # _get_cross_room_context()
    need_guest_mode: bool = True        # RoutineEngine.is_guest_mode_active()
    need_tutorial: bool = True          # _get_tutorial_hint()
    need_summary: bool = True           # _get_summary_context()
    need_rag: bool = True               # _get_rag_context()
```

### Vordefinierte Profile (Class-Methods / Konstanten):

| Profil | Beschreibung | Deaktivierte Subsysteme |
|--------|-------------|------------------------|
| `DEVICE_FAST` | "Licht an", "Rollladen hoch" | mood, rag, summary, tutorial, cross_room, security, mindhome_data, memories |
| `KNOWLEDGE` | "Wie funktioniert X?" | security, cross_room, tutorial, activity, mindhome_data |
| `MEMORY_QUERY` | "Erinnerst du dich..." | security, tutorial, activity, rag, summary |
| `GENERAL` | Alles andere | Nichts deaktiviert (Status Quo) |

---

## Schritt 2: `PreClassifier.classify(text)` Methode

Die Methode nutzt die **gleiche Logik** wie `_classify_intent()` (brain.py:3850-3930), aber wird **frueher** aufgerufen und liefert ein `RequestProfile` statt nur einen String.

**Wichtig:** `_classify_intent()` (Zeile 1276) bleibt bestehen, weil es spaeter fuer Intent-Routing (knowledge vs. delegation vs. memory) gebraucht wird. Der Pre-Classifier bestimmt nur **welche Subsysteme laufen**, nicht die LLM-Routing-Entscheidung.

Regex-basiert, kein LLM-Call:
- Kurze Saetze (≤6 Woerter) + Device-Keywords → `DEVICE_FAST`
- Wissensfragen-Muster ohne Smart-Home-Keywords → `KNOWLEDGE`
- Memory-Keywords → `MEMORY_QUERY`
- Alles andere → `GENERAL`

---

## Schritt 3: Integration in `brain.py:process()`

### 3a. Einfuegen VOR Zeile 1066 (nach den Pre-Classification Shortcuts):

```python
# NEU: Pre-Classification fuer selektive Subsystem-Aktivierung
profile = self.pre_classifier.classify(text)
logger.info("Pre-Classification: %s", profile.category)
```

### 3b. Context Builder bedingt aufrufen (Zeile 1066-1080):

Der Context Builder bekommt ein `profile`-Argument:
```python
context = await asyncio.wait_for(
    self.context_builder.build(
        trigger="voice", user_text=text, person=person or "",
        profile=profile,  # NEU
    ),
    timeout=ctx_timeout,
)
```

### 3c. asyncio.gather bedingt aufrufen (Zeile 1095-1117):

Statt immer alle 10 Tasks zu starten, nur die noetig sind:

```python
# Koroutinen nur starten wenn Profil es verlangt
gather_tasks = []
gather_keys = []

if profile.need_mood:
    gather_tasks.append(self.mood.analyze(text, person or ""))
    gather_keys.append("mood")
else:
    # Kein gather_task, Ergebnis spaeter als None/Default setzen
    pass

# ... analog fuer alle 10 Subsysteme

results = await asyncio.gather(*gather_tasks)

# Ergebnisse per Key zuordnen
result_map = dict(zip(gather_keys, results))
mood_result = result_map.get("mood")
formality_score = result_map.get("formality", 0.5)  # Defaults
# ... etc.
```

---

## Schritt 4: Context Builder anpassen

**Datei:** `assistant/assistant/context_builder.py`

`build()` Methode bekommt optionalen `profile` Parameter:

```python
async def build(self, trigger="voice", user_text="", person="", profile=None):
    context = {}
    context["time"] = ...  # IMMER (trivial, kein I/O)

    if not profile or profile.need_house_status:
        states = await self.ha.get_states()
        ...

    if not profile or profile.need_mindhome_data:
        mindhome_data = await self._get_mindhome_data()
        ...

    if not profile or profile.need_activity:
        if self._activity_engine:
            ...

    # etc.
```

---

## Schritt 5: Brain `__init__` erweitern

```python
from .pre_classifier import PreClassifier
# In __init__:
self.pre_classifier = PreClassifier()
```

---

## Dateien die geaendert werden

| Datei | Aenderung |
|-------|-----------|
| `assistant/assistant/pre_classifier.py` | **NEU** - PreClassifier + RequestProfile |
| `assistant/assistant/brain.py` | Import + Instanziierung + profile-basierte Steuerung in `process()` |
| `assistant/assistant/context_builder.py` | `build()` bekommt optionalen `profile` Parameter |

---

## Risikobewertung

- **Kein Verhaltens-Regression fuer `GENERAL`**: Das Default-Profil aktiviert ALLE Subsysteme → identisch zum aktuellen Verhalten
- **Fallback-sicher**: Wenn `profile=None` uebergeben wird, laueft alles wie bisher
- **Kein Breaking Change**: `_classify_intent()` bleibt unveraendert, Intent-Routing aendert sich nicht
- **Testbar**: Jedes Profil kann unit-getestet werden (Regex-Pattern → erwartetes Profil)

---

## Performance-Erwartung

| Anfrage-Typ | Vorher (Subsysteme) | Nachher | Geschaetzte Ersparnis |
|-------------|--------------------|---------|-----------------------|
| "Licht an" | 10 parallele + Context Build | 2-3 parallele + minimaler Context | ~200-400ms |
| "Wie funktioniert X?" | 10 parallele + Context Build | 5-6 parallele + reduzierter Context | ~100-200ms |
| "Erinnerst du dich..." | 10 parallele + Context Build | 5-6 parallele + reduzierter Context | ~100-200ms |
| Komplexe Anfrage | 10 parallele + Context Build | 10 parallele + voller Context | 0ms (identisch) |
