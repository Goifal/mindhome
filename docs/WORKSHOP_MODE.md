# J.A.R.V.I.S. Workshop Mode — Complete Implementation Specification

> Vollstaendige Implementierungs-Spezifikation fuer den Werkstatt-Modus.
> Diese Datei enthaelt ALLES was noetig ist um den Workshop-Mode zu implementieren.
> Jede Claude Code Instanz kann mit dieser Datei die Implementierung durchfuehren.

---

## Architektur-Ueberblick

MindHome besteht aus 2 Systemen:
- **PC 1:** Home Assistant + MindHome Add-on (Flask/SQLite)
- **PC 2:** Jarvis Assistant (FastAPI/Ollama/Redis/ChromaDB) — Port 8200

Der Workshop-Mode erweitert den Jarvis Assistant um einen vollstaendigen Werkstatt-Ingenieur-Assistenten
mit ~70 Features, inspiriert von Tony Stark's J.A.R.V.I.S.

### Bestehende Patterns die EXAKT kopiert werden muessen

| Pattern | Referenz-Datei | Zeilen | Beschreibung |
|---------|---------------|--------|-------------|
| Session + Navigation | `cooking_assistant.py` | 28-500 | Schritt-basierte Session mit Redis, Keyword-Navigation |
| Redis CRUD | `inventory.py` | 40-150 | Hash/Set Operationen fuer persistente Daten |
| Brain-Integration | `brain.py` | 835-868 | Import, Init, Intent-Interception in process() |
| Tool-Definition | `function_calling.py` | 370-1497 | OpenAI-Format Tools + FunctionExecutor Dispatch |
| WebSocket Events | `websocket.py` | 37-48 | Broadcast-Pattern fuer Echtzeit-Updates |
| Static File Serving | `main.py` | 2791-2828 | SPA Route Pattern fuer `/ui/` und `/chat/` |
| Settings UI | `static/ui/index.html` | 837-875 | Tab-Navigation + Form-Binding + Validation |
| HUD Design | `static/ui/index.html` | 28-63 | CSS-Variablen: `--accent: #00d4ff`, `--bg-primary: #040810` |
| Boot Animation | `static/ui/index.html` | 551-572 + `app.js` 50-121 | SVG-Ringe, Web Audio, Typewriter |
| Model Routing | `model_router.py` | 199-247 | 3-Tier: fast(4B), smart(14B), deep(32B Qwen3) |
| HA Service Calls | `ha_client.py` | 117-141 | `call_service(domain, service, data)` |
| Knowledge Base RAG | `knowledge_base.py` | 1-543 | ChromaDB + Embeddings + PDF-Extraktion |

---

## Zu erstellende Dateien

| Datei | Aktion | ~Zeilen | Beschreibung |
|-------|--------|---------|-------------|
| `assistant/assistant/repair_planner.py` | **NEU** | ~1500 | Hauptmodul: Projekte, Navigation, Diagnose, Simulation, Troubleshoot, Scanner, Inventar, Budget, Skills, Templates, Timer, Arm, Drucker, MQTT, Snippets, Journal |
| `assistant/assistant/workshop_generator.py` | **NEU** | ~800 | Code/3D/SVG/Wiring/BOM/Tests/Doku/Referenz-DB, Berechnungen, File-Management, Export |
| `assistant/assistant/workshop_library.py` | **NEU** | ~250 | Workshop-RAG: Eigene ChromaDB-Collection fuer Fachbuecher (200MB, 1000+ Seiten) |
| `assistant/static/workshop/index.html` | **NEU** | ~1000 | Werkstatt-HUD Display mit Boot-Animation, allen Widgets, Tabs, Chat, Scanner |
| `assistant/assistant/function_calling.py` | EDIT | +180 | Tool `manage_repair` (alle Actions) + Handler `_exec_manage_repair()` |
| `assistant/assistant/brain.py` | EDIT | +70 | Import, Init, Intent-Interception, Workshop-Aktivierungs-Check |
| `assistant/assistant/personality.py` | EDIT | +30 | Ingenieur-Modus Prompt-Erweiterung |
| `assistant/assistant/main.py` | EDIT | +100 | `/workshop/` Route + API-Endpoints + Library-Endpoints + Validation |
| `assistant/static/ui/index.html` | EDIT | +120 | Neuer Tab `tab-workshop` mit allen Settings + Erklaerungen |
| `assistant/static/ui/app.js` | EDIT | +15 | Workshop-Tab Rendering + collectSettings Erweiterung |
| `assistant/assistant/websocket.py` | EDIT | +25 | `emit_workshop()` + Sub-Events |
| `assistant/config/settings.yaml` | EDIT | +35 | Workshop Config-Sektion |

---

## ModelRouter-Integration

JEDER LLM-Aufruf MUSS den richtigen Modell-Tier nutzen:

| Aufgabe | Modell-Tier | Zugriff |
|---------|-------------|---------|
| Code-Generation (alle Sprachen) | **DEEP** (32B) | `self.model_router.model_deep` |
| SVG-Schaltbilder | **DEEP** (32B) | `self.model_router.model_deep` |
| OpenSCAD 3D-Modelle | **DEEP** (32B) | `self.model_router.model_deep` |
| Website-Generation | **DEEP** (32B) | `self.model_router.model_deep` |
| Diagnose / Simulation | **DEEP** (32B) | `self.model_router.model_deep` |
| Troubleshooting | **DEEP** (32B) | `self.model_router.model_deep` |
| Error-Log Analyse | **DEEP** (32B) | `self.model_router.model_deep` |
| Kalibrierung / Test-Protokolle | **SMART** (14B) | `self.model_router.model_smart` |
| Dokumentation / BOM | **SMART** (14B) | `self.model_router.model_smart` |
| Proaktive Vorschlaege | **SMART** (14B) | `self.model_router.model_smart` |
| Berechnungen (eingebaut) | **KEIN LLM** | Python-Formeln direkt |
| Referenz-Tabellen | **KEIN LLM** | Dict-Lookups direkt |
| Unit-Conversion | **KEIN LLM** | Python-Formeln direkt |
| Navigation / CRUD | **KEIN LLM** | Redis-Operationen direkt |

Integration:
```python
# In RepairPlanner + WorkshopGenerator:
def set_model_router(self, router):
    self.model_router = router

# In brain.py initialize():
self.repair_planner.set_model_router(self.model_router)
self.workshop_generator.set_model_router(self.model_router)
```

Erweitere `deep_keywords` in `settings.yaml` (Zeile 76-113):
```yaml
deep_keywords:
  # ... bestehende ...
  - programmier
  - code
  - website
  - schaltplan
  - schaltung
  - firmware
  - gehaeuse
  - 3d modell
  - simuliere
  - diagnostik
  - troubleshoot
```

---

## 1. repair_planner.py (~1500 Zeilen)

Hauptmodul. Folgt EXAKT dem `cooking_assistant.py`-Pattern.

### Klasse

```python
import json, uuid, time, logging
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class RepairStep:
    number: int
    title: str
    description: str
    tools: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    estimated_minutes: int = 0
    completed: bool = False
    photos: list[str] = field(default_factory=list)

@dataclass
class RepairSession:
    project_id: str
    title: str
    category: str
    steps: list[RepairStep]
    current_step: int = 0
    started_at: str = ""
    timer_start: float = 0
    timer_total: float = 0

class RepairPlanner:
    REDIS_SESSION_KEY = "mha:repair:session"
    REDIS_SESSION_TTL = 24 * 3600

    def __init__(self, ollama_client, ha_client):
        self.ollama = ollama_client
        self.ha = ha_client
        self.redis = None
        self.semantic_memory = None
        self.generator = None       # WorkshopGenerator
        self.model_router = None    # ModelRouter
        self._session: Optional[RepairSession] = None
        self._notify_callback = None

    async def initialize(self, redis_client):
        self.redis = redis_client
        await self._restore_session()

    def set_generator(self, generator):
        self.generator = generator

    def set_model_router(self, router):
        self.model_router = router

    def set_notify_callback(self, callback):
        self._notify_callback = callback
```

### A) Projekt-CRUD (Redis Pattern: inventory.py Zeile 40-150)

```python
async def create_project(self, title, description, category="maker", priority="normal") -> dict:
    project_id = str(uuid.uuid4())[:8]
    slug = title.lower().replace(" ", "-").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    project = {
        "id": project_id, "title": title, "description": description,
        "category": category,  # reparatur|bau|maker|erfindung|renovierung
        "priority": priority,  # niedrig|normal|hoch|dringend
        "status": "erstellt",  # erstellt|diagnose|teile_bestellt|in_arbeit|pausiert|fertig
        "slug": slug, "created": datetime.now().isoformat(),
        "parts": "[]", "tools": "[]", "notes": "[]",
        "budget": "0", "expenses": "[]",
        "device_entity": "",  # Verknuepftes HA-Entity
    }
    await self.redis.hset(f"mha:repair:project:{project_id}", mapping=project)
    await self.redis.sadd("mha:repair:projects:all", project_id)
    await self.redis.sadd(f"mha:repair:projects:status:erstellt", project_id)
    return project

async def get_project(self, project_id) -> dict:
    data = await self.redis.hgetall(f"mha:repair:project:{project_id}")
    if not data: return None
    # JSON-Felder parsen
    for key in ("parts", "tools", "notes", "expenses"):
        if key in data and isinstance(data[key], str):
            data[key] = json.loads(data[key])
    return data

async def list_projects(self, status_filter=None, category_filter=None) -> list:
    if status_filter:
        ids = await self.redis.smembers(f"mha:repair:projects:status:{status_filter}")
    else:
        ids = await self.redis.smembers("mha:repair:projects:all")
    projects = []
    for pid in ids:
        p = await self.get_project(pid)
        if p and (not category_filter or p.get("category") == category_filter):
            projects.append(p)
    return projects

async def update_project(self, project_id, **kwargs) -> dict:
    # Status-Change: alte Status-Set entfernen, neue hinzufuegen
    if "status" in kwargs:
        old = await self.redis.hget(f"mha:repair:project:{project_id}", "status")
        if old: await self.redis.srem(f"mha:repair:projects:status:{old}", project_id)
        await self.redis.sadd(f"mha:repair:projects:status:{kwargs['status']}", project_id)
    for k, v in kwargs.items():
        if isinstance(v, (list, dict)): v = json.dumps(v)
        await self.redis.hset(f"mha:repair:project:{project_id}", k, v)
    return await self.get_project(project_id)

async def complete_project(self, project_id, notes="") -> dict:
    await self.update_project(project_id, status="fertig", completed=datetime.now().isoformat())
    if notes: await self.add_project_note(project_id, notes)
    # Auto-Dokumentation generieren
    if self.generator:
        await self.generator.generate_documentation(project_id, self.model_router.model_smart)
    return await self.get_project(project_id)

async def add_project_note(self, project_id, note) -> dict:
    project = await self.get_project(project_id)
    notes = project.get("notes", [])
    notes.append({"text": note, "timestamp": datetime.now().isoformat()})
    await self.redis.hset(f"mha:repair:project:{project_id}", "notes", json.dumps(notes))
    return {"status": "ok", "note_count": len(notes)}
```

### B) Teile-Management

```python
async def add_part(self, project_id, name, quantity=1, estimated_cost=0, source="") -> dict:
    project = await self.get_project(project_id)
    parts = project.get("parts", [])
    parts.append({"name": name, "quantity": quantity, "cost": estimated_cost,
                  "source": source, "available": False})
    await self.redis.hset(f"mha:repair:project:{project_id}", "parts", json.dumps(parts))
    return {"status": "ok", "part": name}

async def add_missing_to_shopping(self, project_id) -> dict:
    """MIT Nachfrage — gibt Liste zurueck, User muss bestaetigen."""
    project = await self.get_project(project_id)
    missing = [p for p in project.get("parts", []) if not p.get("available")]
    if not missing: return {"status": "ok", "message": "Alle Teile vorhanden"}
    # Nur zurueckgeben, NICHT direkt auf Liste setzen
    return {"status": "confirm_needed", "missing_parts": missing,
            "message": f"{len(missing)} Teile fehlen. Soll ich sie auf die Einkaufsliste setzen?"}
```

### C) LLM-Diagnose — "Run a diagnostic"

```python
DIAGNOSIS_PROMPT = """Du bist ein Werkstatt-Ingenieur. Analysiere das Problem und antworte NUR als JSON:
{
  "diagnosis": "Was ist das Problem",
  "difficulty": 3,
  "tools": ["Werkzeug1", "Werkzeug2"],
  "parts": [{"name": "Teil", "quantity": 1, "estimated_cost": 5.0}],
  "safety_warnings": ["Warnung1"],
  "steps": [{"title": "Schritt", "description": "Beschreibung", "tools": [], "estimated_minutes": 10}],
  "estimated_time": "1-2 Stunden",
  "estimated_cost": "10-20 Euro"
}
Kontext: {context}
Werkstatt-Sensoren: {environment}
"""

async def diagnose_problem(self, text, person, model=None) -> str:
    model = model or self.model_router.model_deep
    # Semantic Memory durchsuchen
    context = ""
    if self.semantic_memory:
        results = await self.semantic_memory.search(text, limit=3)
        if results: context = "\n".join(r.get("content", "") for r in results)
    # Werkstatt-Umgebung holen
    environment = await self.get_workshop_environment()
    prompt = self.DIAGNOSIS_PROMPT.format(context=context, environment=json.dumps(environment))
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": text}]
    response = await self.ollama.chat(model=model, messages=messages, temperature=0.3, max_tokens=2048)
    # JSON parsen und Projekt erstellen
    try:
        data = json.loads(response)
        project = await self.create_project(
            title=data.get("diagnosis", text)[:60],
            description=text, category="reparatur",
            priority="hoch" if data.get("difficulty", 3) >= 4 else "normal"
        )
        # Session starten
        steps = [RepairStep(number=i+1, **s) for i, s in enumerate(data.get("steps", []))]
        self._session = RepairSession(
            project_id=project["id"], title=project["title"],
            category="reparatur", steps=steps,
            started_at=datetime.now().isoformat()
        )
        await self._save_session()
        # WebSocket Event
        from .websocket import emit_workshop
        await emit_workshop("diagnosis", {"project": project, "diagnosis": data})
        return self._format_diagnosis(data)
    except json.JSONDecodeError:
        return response  # LLM hat kein JSON generiert, Freitext zurueckgeben
```

### D) Simulation

```python
async def simulate_design(self, project_id, question, model=None) -> str:
    model = model or self.model_router.model_deep
    project = await self.get_project(project_id)
    files = self.generator.list_files(project_id) if self.generator else []
    file_contents = {}
    for f in files:
        content = self.generator.read_file(project_id, f["name"])
        if content: file_contents[f["name"]] = content[:2000]

    prompt = f"""Analysiere dieses Projekt und beantworte die Frage.
Projekt: {project['title']} ({project['category']})
Teile: {json.dumps(project.get('parts', []))}
Dateien: {json.dumps(file_contents)}
Frage: {question}

Analysiere: Machbarkeit, Schwachstellen, Belastungsgrenzen, Batterie-Laufzeit,
thermische Aspekte, Verbesserungsvorschlaege. Gib Konfidenz-Level an."""
    messages = [{"role": "system", "content": prompt}]
    return await self.ollama.chat(model=model, messages=messages, temperature=0.4, max_tokens=2048)
```

### E) Troubleshooting

```python
async def troubleshoot(self, project_id, symptom, model=None) -> str:
    model = model or self.model_router.model_deep
    project = await self.get_project(project_id)
    prompt = f"""Systematischer Debug-Workflow fuer: {symptom}
Projekt: {project['title']}
Teile: {json.dumps(project.get('parts', []))}
1. Symptom analysieren
2. Wahrscheinlichste Ursachen (sortiert nach Wahrscheinlichkeit)
3. Pruefschritte mit konkreten Anweisungen ("Miss Spannung an Pin X")
4. Erwartete Ergebnisse pro Pruefschritt
Antworte strukturiert als Diagnosebaum."""
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": symptom}]
    return await self.ollama.chat(model=model, messages=messages, temperature=0.3, max_tokens=2048)
```

### F) Proaktive Verbesserungen

```python
async def suggest_improvements(self, project_id, model=None) -> str:
    model = model or self.model_router.model_smart
    project = await self.get_project(project_id)
    prompt = f"""Analysiere das Projekt und schlage Verbesserungen vor.
Projekt: {project['title']} ({project['category']})
Teile: {json.dumps(project.get('parts', []))}
Schlage konkrete Optimierungen vor (Effizienz, Kosten, Sicherheit, Zuverlaessigkeit)."""
    messages = [{"role": "system", "content": prompt}]
    return await self.ollama.chat(model=model, messages=messages, temperature=0.5, max_tokens=1024)
```

### F2) Component Comparison

```python
async def compare_components(self, comp_a, comp_b, use_case="", model=None) -> str:
    model = model or self.model_router.model_deep
    prompt = f"""Vergleiche {comp_a} vs {comp_b} fuer: {use_case or 'allgemein'}
Vergleiche: Features, Preis, Stromverbrauch, Pins, Verfuegbarkeit.
Gib eine klare Empfehlung mit Begruendung."""
    messages = [{"role": "system", "content": prompt}]
    return await self.ollama.chat(model=model, messages=messages, temperature=0.3, max_tokens=1024)
```

### F3) Workshop-RAG (siehe workshop_library.py)

Separate Datei — eigene ChromaDB-Collection fuer grosse PDFs.

### F4) Environment Context

```python
async def get_workshop_environment(self) -> dict:
    """Holt Werkstatt-Sensordaten von Home Assistant."""
    import assistant.config as cfg
    room = cfg.yaml_config.get("workshop", {}).get("workshop_room", "werkstatt")
    try:
        states = await self.ha.get_states()
        env = {}
        for state in states:
            eid = state.get("entity_id", "")
            if room.lower() in eid.lower():
                if "temperature" in eid: env["temperatur"] = state.get("state")
                elif "humidity" in eid: env["feuchtigkeit"] = state.get("state")
                elif "co2" in eid: env["co2"] = state.get("state")
                elif "illuminance" in eid: env["licht"] = state.get("state")
        return env
    except Exception:
        return {}
```

### F5) Safety Checklist

```python
async def generate_safety_checklist(self, project_id) -> str:
    project = await self.get_project(project_id)
    category = project.get("category", "")
    tools = project.get("tools", [])
    checklist = ["Arbeitsflaeche frei und sauber"]
    if any(t in str(tools) for t in ["loetkolben", "loeten", "loet"]):
        checklist.extend(["Lueftung einschalten", "Loetkolben-Ablage pruefen", "Loetzinn bereit"])
    if any(t in str(tools) for t in ["bohr", "saeg", "flex", "schlei"]):
        checklist.extend(["Schutzbrille aufsetzen", "Gehoerschutz bei Bedarf"])
    if category == "reparatur":
        checklist.append("Strom/Wasser abstellen wenn noetig")
    checklist.append("Erste-Hilfe-Kasten in Reichweite")
    return "Sicherheits-Checkliste:\n" + "\n".join(f"☐ {c}" for c in checklist)
```

### F6) Mess-Assistent

```python
async def evaluate_measurement(self, project_id, measurement_text, model=None) -> str:
    model = model or self.model_router.model_deep
    project = await self.get_project(project_id)
    prompt = f"""Der User hat einen Messwert diktiert. Bewerte ihn im Projekt-Kontext.
Projekt: {project['title']}
Schritt: {self._session.current_step if self._session else 'unbekannt'}
Messwert: {measurement_text}
Bewerte: Ist der Wert im erwarteten Bereich? Was bedeutet er? Naechster Schritt?"""
    messages = [{"role": "system", "content": prompt}]
    return await self.ollama.chat(model=model, messages=messages, temperature=0.3, max_tokens=512)
```

### F7) Time Tracking

```python
async def start_timer(self, project_id) -> dict:
    await self.redis.hset(f"mha:repair:project:{project_id}", "timer_start", str(time.time()))
    return {"status": "ok", "message": "Timer gestartet"}

async def pause_timer(self, project_id) -> dict:
    start = float(await self.redis.hget(f"mha:repair:project:{project_id}", "timer_start") or 0)
    total = float(await self.redis.hget(f"mha:repair:project:{project_id}", "timer_total") or 0)
    if start > 0:
        total += time.time() - start
        await self.redis.hset(f"mha:repair:project:{project_id}", "timer_total", str(total))
        await self.redis.hset(f"mha:repair:project:{project_id}", "timer_start", "0")
    hours, remainder = divmod(int(total), 3600)
    minutes = remainder // 60
    return {"status": "ok", "total_seconds": total, "display": f"{hours}h {minutes}min"}

async def get_time_spent(self, project_id) -> dict:
    return await self.pause_timer(project_id)  # Gleiche Logik
```

### F8) Multi-Project

```python
async def switch_project(self, project_id) -> dict:
    project = await self.get_project(project_id)
    if not project: return {"status": "error", "message": "Projekt nicht gefunden"}
    # Alte Session pausieren
    if self._session: await self.pause_timer(self._session.project_id)
    # Neue Session laden oder erstellen
    # ... (Session-Restore aus Redis oder neue Session)
    return {"status": "ok", "message": f"Gewechselt zu: {project['title']}"}

async def get_active_project(self) -> dict:
    if not self._session: return None
    return await self.get_project(self._session.project_id)
```

### G) Schritt-Navigation (EXAKT wie cooking_assistant.py Zeilen 113-500)

```python
NAV_NEXT = {"weiter", "naechster schritt", "next", "und dann", "weiter gehts"}
NAV_PREV = {"zurueck", "vorheriger schritt", "back", "einen zurueck"}
NAV_REPEAT = {"nochmal", "wiederhole", "repeat", "wie war das"}
NAV_STATUS = {"status", "wo bin ich", "uebersicht", "wo stehe ich"}
NAV_PARTS = {"was brauche ich", "teile", "teileliste", "material"}
NAV_TOOLS = {"welches werkzeug", "werkzeugliste", "was brauch ich an werkzeug"}
NAV_SHOP = {"bestell das", "einkaufsliste", "kaufen", "shopping"}
NAV_SAVE = {"merk dir das", "speicher das", "merken"}
NAV_CODE = {"zeig den code", "programmier", "code generieren", "firmware"}
NAV_3D = {"3d modell", "gehaeuse", "openscad"}
NAV_CALC = {"berechne", "welcher widerstand", "rechne", "umrechnen", "konvertiere"}
NAV_SCAN = {"scan das", "schau dir an", "was ist das", "analysiere das teil"}
NAV_SIM = {"simuliere", "teste das design", "haelt das"}
NAV_PRINT = {"druck", "drucke", "print", "3d druck starten"}
NAV_ARM = {"gib mir", "halt das", "greif", "arm", "robot"}
NAV_TIMER = {"erinnere mich", "timer", "wecker"}
NAV_JOURNAL = {"was hab ich heute", "journal", "tagebuch"}
NAV_STOP = {"pause", "fertig", "stop", "beenden"}
EMERGENCY_STOP = {"stopp"}  # Hoechste Prioritaet fuer Arm

def is_repair_navigation(self, text: str) -> bool:
    if not self._session: return False
    text_lower = text.lower().strip()
    all_nav = (NAV_NEXT | NAV_PREV | NAV_REPEAT | NAV_STATUS | NAV_PARTS |
               NAV_TOOLS | NAV_SHOP | NAV_SAVE | NAV_CODE | NAV_3D | NAV_CALC |
               NAV_SCAN | NAV_SIM | NAV_PRINT | NAV_ARM | NAV_TIMER |
               NAV_JOURNAL | NAV_STOP | EMERGENCY_STOP)
    return any(kw in text_lower for kw in all_nav)

async def handle_navigation(self, text: str) -> str:
    text_lower = text.lower().strip()
    # Emergency Stop hat IMMER Vorrang
    if any(kw in text_lower for kw in EMERGENCY_STOP):
        return await self._emergency_stop()
    if any(kw in text_lower for kw in NAV_NEXT): return await self._next_step()
    if any(kw in text_lower for kw in NAV_PREV): return await self._prev_step()
    if any(kw in text_lower for kw in NAV_REPEAT): return await self._repeat_step()
    if any(kw in text_lower for kw in NAV_STATUS): return self._get_status()
    if any(kw in text_lower for kw in NAV_PARTS): return self._get_parts()
    # ... (weitere Handler fuer jeden NAV-Typ)
    if any(kw in text_lower for kw in NAV_STOP): return await self._stop_session()
    return "Ich habe das nicht verstanden. Sage 'status' fuer eine Uebersicht."
```

### G2) Objekt-Scanner

```python
async def scan_object(self, image_data=None, camera_name="", description="") -> dict:
    """Nutzt bestehende camera_manager.py + ocr.py Infrastruktur."""
    from .camera_manager import get_camera_view
    from .ocr import analyze_image
    # Bild holen
    if image_data:
        img = image_data
    elif camera_name:
        img = await get_camera_view(camera_name)
    else:
        return {"status": "error", "message": "Kein Bild oder Kamera angegeben"}
    # Vision-LLM Analyse mit Workshop-Prompt
    prompt = """Analysiere dieses Bild aus einer Werkstatt-Perspektive:
1. Was ist das fuer ein Objekt/Bauteil?
2. Erkennbare Beschaedigungen oder Verschleiss?
3. Geschaetzte Abmessungen?
4. Teilenummern/Beschriftungen?
5. Reparierbar oder Ersatz noetig?"""
    result = await analyze_image(img, prompt)
    return {"status": "ok", "analysis": result}
```

### H) Werkstatt-Inventar (Redis)

```python
async def add_workshop_item(self, name, quantity=1, category="werkzeug", location="") -> dict:
    item_id = name.lower().replace(" ", "_")
    item = {"name": name, "quantity": str(quantity), "category": category,
            "location": location, "added": datetime.now().isoformat()}
    await self.redis.hset(f"mha:repair:workshop:{item_id}", mapping=item)
    await self.redis.sadd("mha:repair:workshop:all", item_id)
    await self.redis.sadd(f"mha:repair:workshop:cat:{category}", item_id)
    return {"status": "ok", "item": name}

async def list_workshop(self, category=None) -> list:
    if category:
        ids = await self.redis.smembers(f"mha:repair:workshop:cat:{category}")
    else:
        ids = await self.redis.smembers("mha:repair:workshop:all")
    items = []
    for iid in ids:
        data = await self.redis.hgetall(f"mha:repair:workshop:{iid}")
        if data: items.append(data)
    return items

async def add_maintenance_schedule(self, tool_name, interval_days, last_done="") -> dict:
    key = f"mha:repair:maintenance:{tool_name.lower().replace(' ', '_')}"
    await self.redis.hset(key, mapping={
        "tool": tool_name, "interval_days": str(interval_days),
        "last_done": last_done or datetime.now().isoformat()
    })
    return {"status": "ok"}

async def check_maintenance_due(self) -> list:
    keys = [k async for k in self.redis.scan_iter("mha:repair:maintenance:*")]
    due = []
    for key in keys:
        data = await self.redis.hgetall(key)
        last = datetime.fromisoformat(data.get("last_done", datetime.now().isoformat()))
        interval = int(data.get("interval_days", 90))
        if (datetime.now() - last).days >= interval:
            due.append(data)
    return due
```

### H2-H4) Budget, Skills, Templates

```python
async def set_project_budget(self, project_id, budget) -> dict:
    await self.redis.hset(f"mha:repair:project:{project_id}", "budget", str(budget))
    return {"status": "ok"}

async def add_expense(self, project_id, item, cost) -> dict:
    project = await self.get_project(project_id)
    expenses = project.get("expenses", [])
    expenses.append({"item": item, "cost": float(cost), "date": datetime.now().isoformat()})
    await self.redis.hset(f"mha:repair:project:{project_id}", "expenses", json.dumps(expenses))
    return {"status": "ok", "total": sum(e["cost"] for e in expenses)}

async def record_skill(self, person, skill, level="beginner") -> dict:
    key = f"mha:repair:skills:{person.lower()}"
    await self.redis.hset(key, skill, level)
    return {"status": "ok"}

async def get_workshop_stats(self, period="month") -> dict:
    all_projects = await self.list_projects()
    completed = [p for p in all_projects if p.get("status") == "fertig"]
    return {
        "total_projects": len(all_projects),
        "completed": len(completed),
        "categories": {cat: len([p for p in all_projects if p.get("category") == cat])
                      for cat in ["reparatur", "bau", "maker", "erfindung", "renovierung"]}
    }

# Templates
TEMPLATES = {
    "esp_sensor": {"title": "ESP32 Sensor-Projekt", "category": "maker",
                   "parts": [{"name": "ESP32 DevKit", "quantity": 1}],
                   "tools": ["Loetkolben", "Multimeter"]},
    "led_strip": {"title": "LED-Strip Steuerung", "category": "maker",
                  "parts": [{"name": "ESP32", "quantity": 1}, {"name": "WS2812 Strip", "quantity": 1}]},
    "3d_enclosure": {"title": "3D-Druck Gehaeuse", "category": "maker"},
    "furniture": {"title": "Moebelbau Projekt", "category": "bau"},
    "repair_standard": {"title": "Standard-Reparatur", "category": "reparatur"},
}

async def create_from_template(self, template_name, title="") -> dict:
    tmpl = self.TEMPLATES.get(template_name)
    if not tmpl: return {"status": "error", "message": f"Template '{template_name}' nicht gefunden"}
    project = await self.create_project(
        title=title or tmpl["title"], description=f"Aus Template: {template_name}",
        category=tmpl.get("category", "maker"))
    for part in tmpl.get("parts", []):
        await self.add_part(project["id"], **part)
    return project
```

### I) QR-Labels

```python
async def generate_qr_label(self, item_name, location="", details="") -> str:
    """Generiert QR-Code als PNG. Benoetigt: pip install qrcode[pil]"""
    import qrcode
    url = f"http://jarvis:8200/api/workshop/tool/{item_name.lower().replace(' ', '_')}"
    qr = qrcode.make(url)
    path = Path("/app/data/workshop/labels")
    path.mkdir(parents=True, exist_ok=True)
    filepath = path / f"{item_name.lower().replace(' ', '_')}.png"
    qr.save(str(filepath))
    return str(filepath)
```

### J) Tool-Verleih

```python
async def lend_tool(self, tool_name, person) -> dict:
    key = f"mha:repair:lent:{tool_name.lower().replace(' ', '_')}"
    await self.redis.hset(key, mapping={
        "tool": tool_name, "person": person, "since": datetime.now().isoformat()})
    return {"status": "ok", "message": f"{tool_name} an {person} verliehen"}

async def return_tool(self, tool_name) -> dict:
    key = f"mha:repair:lent:{tool_name.lower().replace(' ', '_')}"
    await self.redis.delete(key)
    return {"status": "ok", "message": f"{tool_name} zurueckgegeben"}

async def list_lent_tools(self) -> list:
    keys = [k async for k in self.redis.scan_iter("mha:repair:lent:*")]
    return [await self.redis.hgetall(k) for k in keys]
```

### K) 3D-Drucker Steuerung (via HA)

```python
async def get_printer_status(self) -> dict:
    """Liest 3D-Drucker Status via HA-Entities."""
    import assistant.config as cfg
    prefix = cfg.yaml_config.get("workshop", {}).get("printer_3d", {}).get("entity_prefix", "octoprint")
    states = await self.ha.get_states()
    printer = {}
    for s in states:
        eid = s.get("entity_id", "")
        if prefix in eid:
            if "progress" in eid: printer["progress"] = s.get("state")
            elif "bed_temp" in eid: printer["bed_temp"] = s.get("state")
            elif "tool_temp" in eid or "hotend" in eid: printer["hotend_temp"] = s.get("state")
            elif "state" in eid or "status" in eid: printer["state"] = s.get("state")
            elif "time_remaining" in eid: printer["eta"] = s.get("state")
    return printer if printer else {"status": "not_found", "message": "Kein 3D-Drucker in HA gefunden"}

async def start_print(self, project_id="", filename="") -> dict:
    status = await self.get_printer_status()
    if status.get("state") not in ("idle", "ready", "operational"):
        return {"status": "error", "message": f"Drucker nicht bereit: {status.get('state')}"}
    # Start via HA Service
    import assistant.config as cfg
    prefix = cfg.yaml_config.get("workshop", {}).get("printer_3d", {}).get("entity_prefix", "octoprint")
    await self.ha.call_service("button", "press", {"entity_id": f"button.{prefix}_resume_job"})
    return {"status": "ok", "message": "Druck gestartet"}

async def pause_print(self) -> dict:
    import assistant.config as cfg
    prefix = cfg.yaml_config.get("workshop", {}).get("printer_3d", {}).get("entity_prefix", "octoprint")
    await self.ha.call_service("button", "press", {"entity_id": f"button.{prefix}_pause_job"})
    return {"status": "ok", "message": "Druck pausiert"}

async def cancel_print(self) -> dict:
    import assistant.config as cfg
    prefix = cfg.yaml_config.get("workshop", {}).get("printer_3d", {}).get("entity_prefix", "octoprint")
    await self.ha.call_service("button", "press", {"entity_id": f"button.{prefix}_cancel_job"})
    return {"status": "ok", "message": "Druck abgebrochen"}
```

### K2) Roboterarm-Steuerung (Waveshare RoArm-M3-Pro)

```python
import aiohttp

async def _arm_command(self, cmd: dict) -> dict:
    """Sendet JSON-Kommando an den Arm via HTTP."""
    import assistant.config as cfg
    arm_cfg = cfg.yaml_config.get("workshop", {}).get("robot_arm", {})
    if not arm_cfg.get("enabled"): return {"status": "disabled"}
    url = arm_cfg.get("url", "")
    if not url: return {"status": "error", "message": "Arm-URL nicht konfiguriert"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.post(f"{url}/js?json={json.dumps(cmd)}") as resp:
                return await resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def arm_move(self, x, y, z, speed=50) -> dict:
    import assistant.config as cfg
    max_speed = cfg.yaml_config.get("workshop", {}).get("robot_arm", {}).get("max_speed", 80)
    speed = min(speed, max_speed)
    return await self._arm_command({"T": 104, "x": x, "y": y, "z": z, "t": int(2000 / (speed/100))})

async def arm_gripper(self, action="open") -> dict:
    cmd = 1 if action == "open" else 0
    return await self._arm_command({"T": 106, "cmd": cmd})

async def arm_home(self) -> dict:
    return await self._arm_command({"T": 100})

async def arm_save_position(self, name, position=None) -> dict:
    if position is None:
        # Aktuelle Position lesen
        result = await self._arm_command({"T": 100})
        position = result
    key = f"mha:repair:arm:positions:{name.lower()}"
    await self.redis.hset(key, mapping={k: str(v) for k, v in position.items()})
    return {"status": "ok", "message": f"Position '{name}' gespeichert"}

async def arm_pick_tool(self, tool_name) -> dict:
    key = f"mha:repair:arm:positions:{tool_name.lower()}"
    pos = await self.redis.hgetall(key)
    if not pos: return {"status": "error", "message": f"Position '{tool_name}' nicht gespeichert"}
    await self.arm_gripper("open")
    await self.arm_move(float(pos.get("x", 0)), float(pos.get("y", 0)), float(pos.get("z", 0)))
    await self.arm_gripper("close")
    return {"status": "ok", "message": f"Greife {tool_name}"}

async def _emergency_stop(self) -> str:
    await self._arm_command({"T": 0})  # Stop-Kommando
    return "NOTFALL-STOPP! Arm angehalten."
```

### M-P) Push, Kalibrierung, Journal, Timer

```python
async def notify_user(self, message, title="Werkstatt") -> dict:
    """Push-Benachrichtigung via HA Notify."""
    try:
        await self.ha.call_service("notify", "notify", {"title": title, "message": message})
        return {"status": "ok"}
    except Exception:
        return {"status": "error"}

async def calibration_guide(self, device_type, model=None) -> str:
    model = model or self.model_router.model_smart
    prompt = f"""Erstelle eine Schritt-fuer-Schritt Kalibrierungsanleitung fuer: {device_type}
Gib konkrete Werte, Pruefschritte und erwartete Ergebnisse an."""
    messages = [{"role": "system", "content": prompt}]
    return await self.ollama.chat(model=model, messages=messages, temperature=0.3, max_tokens=1024)

async def get_journal(self, period="today") -> dict:
    key = f"mha:repair:journal:{datetime.now().strftime('%Y-%m-%d')}"
    entries = await self.redis.lrange(key, 0, -1)
    return {"date": datetime.now().strftime('%Y-%m-%d'),
            "entries": [json.loads(e) for e in entries]}

async def add_journal_entry(self, note) -> dict:
    key = f"mha:repair:journal:{datetime.now().strftime('%Y-%m-%d')}"
    entry = {"text": note, "time": datetime.now().strftime('%H:%M')}
    await self.redis.rpush(key, json.dumps(entry))
    await self.redis.expire(key, 90 * 86400)  # 90 Tage aufbewahren
    return {"status": "ok"}

async def set_workshop_timer(self, minutes, reason="") -> dict:
    """Timer mit Callback (Pattern: CookingTimer in cooking_assistant.py)."""
    import asyncio
    timer_id = str(uuid.uuid4())[:6]
    async def _timer_callback():
        await asyncio.sleep(minutes * 60)
        msg = f"Sir, {minutes} Minuten sind um"
        if reason: msg += f" — {reason}"
        if self._notify_callback:
            await self._notify_callback(msg)
    asyncio.create_task(_timer_callback())
    return {"status": "ok", "timer_id": timer_id, "minutes": minutes, "reason": reason}
```

### R-X) Error-Log, Snippets, Archiv, MQTT, Online-Check, Power, Devices

```python
async def analyze_error_log(self, project_id, log_text, model=None) -> str:
    model = model or self.model_router.model_deep
    project = await self.get_project(project_id)
    files = self.generator.list_files(project_id) if self.generator else []
    prompt = f"""Analysiere diesen Error-Log/Serial-Output.
Projekt: {project['title']}
Projekt-Dateien: {[f['name'] for f in files]}
Error-Log:
{log_text[:3000]}
Erklaere den Fehler und schlage einen konkreten Fix vor."""
    messages = [{"role": "system", "content": prompt}]
    return await self.ollama.chat(model=model, messages=messages, temperature=0.2, max_tokens=1024)

async def save_snippet(self, name, code, language="", tags=None) -> dict:
    key = f"mha:repair:snippet:{name.lower().replace(' ', '_')}"
    await self.redis.hset(key, mapping={
        "name": name, "code": code, "language": language,
        "tags": json.dumps(tags or []), "created": datetime.now().isoformat()})
    return {"status": "ok"}

async def get_snippet(self, name) -> dict:
    key = f"mha:repair:snippet:{name.lower().replace(' ', '_')}"
    return await self.redis.hgetall(key)

async def search_projects(self, query, include_completed=True) -> list:
    all_projects = await self.list_projects()
    if not include_completed:
        all_projects = [p for p in all_projects if p.get("status") != "fertig"]
    # Einfache Textsuche + Semantic Memory
    results = [p for p in all_projects if query.lower() in json.dumps(p).lower()]
    if self.semantic_memory:
        sem_results = await self.semantic_memory.search(query, limit=3)
        # Projekte aus Semantic Memory hinzufuegen
    return results

async def check_device_online(self, entity_id) -> dict:
    states = await self.ha.get_states()
    for s in states:
        if s.get("entity_id") == entity_id:
            last = s.get("last_updated", "")
            state = s.get("state", "unknown")
            return {"entity": entity_id, "state": state, "last_updated": last}
    return {"entity": entity_id, "state": "not_found"}

async def get_power_consumption(self, entity_id) -> dict:
    states = await self.ha.get_states()
    for s in states:
        if s.get("entity_id") == entity_id:
            return {"entity": entity_id, "power_w": s.get("state", "0"),
                    "unit": s.get("attributes", {}).get("unit_of_measurement", "W")}
    return {"status": "not_found"}

async def link_device_to_project(self, project_id, entity_id) -> dict:
    await self.redis.hset(f"mha:repair:project:{project_id}", "device_entity", entity_id)
    return {"status": "ok"}

async def check_all_devices(self) -> list:
    projects = await self.list_projects()
    devices = []
    for p in projects:
        entity = p.get("device_entity")
        if entity:
            status = await self.check_device_online(entity)
            status["project"] = p.get("title")
            devices.append(status)
    return devices
```

### Intent-Erkennung

```python
REPAIR_KEYWORDS = {
    "reparieren", "kaputt", "defekt", "tropft", "leckt", "klemmt",
    "bauen", "basteln", "konstruieren", "erfinden",
    "esp32", "arduino", "esp8266", "raspberry", "3d druck", "3d-druck",
    "loeten", "loet", "werkstatt", "werkzeug",
    "simuliere", "diagnostik", "scan", "schaltplan", "schaltung",
    "programmier", "code", "firmware", "website", "webseite",
    "gehaeuse", "modell", "openscad",
    "online", "mqtt", "strom", "sensor",
}

ACTIVATION_ON = {"werkstatt modus an", "werkstatt aktivieren", "workshop an", "werkstattmodus an"}
ACTIVATION_OFF = {"werkstatt modus aus", "werkstatt deaktivieren", "workshop aus", "werkstattmodus aus"}

def is_repair_intent(self, text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in self.REPAIR_KEYWORDS)

def is_activation_command(self, text: str) -> bool:
    text_lower = text.lower().strip()
    return text_lower in (self.ACTIVATION_ON | self.ACTIVATION_OFF)

async def toggle_activation(self, text: str) -> str:
    text_lower = text.lower().strip()
    if text_lower in self.ACTIVATION_ON:
        await self.redis.setex("mha:repair:manual_active", self.REDIS_SESSION_TTL, "1")
        return "Werkstatt-Modus aktiviert, Sir. Wie kann ich helfen?"
    else:
        await self.redis.delete("mha:repair:manual_active")
        return "Werkstatt-Modus deaktiviert. Bis zum naechsten Mal, Sir."

def is_manually_activated(self) -> bool:
    # Synchroner Check — in async Kontext: await self.redis.exists(...)
    return False  # Muss async implementiert werden

def has_active_session(self) -> bool:
    return self._session is not None
```

### Redis-Schema

```
mha:repair:project:{uuid}              Hash  — Projekt-Daten
mha:repair:projects:all                 Set   — Alle Projekt-IDs
mha:repair:projects:status:{status}     Set   — IDs pro Status
mha:repair:workshop:{item_id}           Hash  — Werkstatt-Item
mha:repair:workshop:all                 Set   — Alle Item-IDs
mha:repair:workshop:cat:{cat}           Set   — IDs pro Kategorie
mha:repair:session                      String (JSON, TTL 24h) — Aktive Session
mha:repair:files:{project_id}           List  — Dateinamen
mha:repair:versions:{project_id}:{fn}   List  — Version-History
mha:repair:arm:positions:{name}         Hash  — Arm-Position (x, y, z)
mha:repair:arm:sequences:{name}         List  — Sequenz-Schritte
mha:repair:lent:{tool_id}              Hash  — Verliehenes Werkzeug
mha:repair:maintenance:{tool_id}        Hash  — Wartungs-Schedule
mha:repair:snippet:{name}              Hash  — Code-Snippet
mha:repair:journal:{YYYY-MM-DD}         List  — Tages-Journal
mha:repair:skills:{person}             Hash  — Skills pro Person
mha:repair:manual_active                String (TTL 24h) — Manueller Aktivierungs-Flag
