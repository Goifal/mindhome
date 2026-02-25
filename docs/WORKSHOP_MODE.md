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
```

---

## 2. workshop_generator.py (~800 Zeilen)

Code/3D/SVG/Wiring/BOM/Tests/Doku/Referenz-DB, Berechnungen, File-Management, Export.

### Klasse

```python
import json, logging, math, re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Physik-Referenz-Datenbanken (kein LLM noetig)
RESISTOR_E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
                3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]

WIRE_GAUGE_MM2 = {
    0.5: 3, 0.75: 5, 1.0: 7.5, 1.5: 10, 2.5: 16, 4.0: 25, 6.0: 32, 10.0: 50
}

SCREW_TORQUES_NM = {
    "M3": 1.2, "M4": 2.5, "M5": 5.0, "M6": 8.5, "M8": 22, "M10": 44, "M12": 77
}

MATERIAL_PROPERTIES = {
    "pla": {"temp_max": 60, "strength_mpa": 50, "density_g_cm3": 1.24},
    "petg": {"temp_max": 80, "strength_mpa": 55, "density_g_cm3": 1.27},
    "abs": {"temp_max": 100, "strength_mpa": 40, "density_g_cm3": 1.04},
    "tpu": {"temp_max": 80, "strength_mpa": 30, "density_g_cm3": 1.21},
    "asa": {"temp_max": 95, "strength_mpa": 55, "density_g_cm3": 1.07},
}

ESP32_PINOUT = {
    "adc": [32, 33, 34, 35, 36, 39],
    "dac": [25, 26],
    "i2c_sda": 21, "i2c_scl": 22,
    "spi_mosi": 23, "spi_miso": 19, "spi_clk": 18,
    "pwm": list(range(2, 34)),
    "touch": [4, 2, 15, 13, 12, 14, 27, 33, 32],
}

UNIT_CONVERSIONS = {
    ("mm", "inch"): lambda x: x / 25.4,
    ("inch", "mm"): lambda x: x * 25.4,
    ("celsius", "fahrenheit"): lambda x: x * 9/5 + 32,
    ("fahrenheit", "celsius"): lambda x: (x - 32) * 5/9,
    ("bar", "psi"): lambda x: x * 14.5038,
    ("psi", "bar"): lambda x: x / 14.5038,
    ("kg", "lbs"): lambda x: x * 2.20462,
    ("lbs", "kg"): lambda x: x / 2.20462,
}


class WorkshopGenerator:
    """Code-/3D-/Schaltplan-Generator fuer die Werkstatt."""

    FILES_DIR = Path("/app/data/workshop/files")

    def __init__(self, ollama_client):
        self.ollama = ollama_client
        self.redis = None
        self.model_router = None

    async def initialize(self, redis_client):
        self.redis = redis_client
        self.FILES_DIR.mkdir(parents=True, exist_ok=True)

    def set_model_router(self, router):
        self.model_router = router
```

### A) Code-Generation (alle Sprachen)

```python
CODE_GEN_PROMPT = """Du bist ein erfahrener Embedded-/Software-Entwickler.
Generiere VOLLSTAENDIGEN, KOMPILIERBAREN Code. Keine Platzhalter. Keine "...".
Sprache: {language}
Projekt: {project_title}
Bestehender Code: {existing_code}
Anforderung: {requirement}

REGELN:
- Vollstaendig: Alle Imports, alle Funktionen, main() wenn noetig
- Kommentare auf Deutsch
- Bei Arduino/ESP32: setup() + loop() + alle Variablen
- Bei Python: if __name__ == "__main__" wenn standalone
- Bei HTML: Vollstaendiges Dokument mit DOCTYPE"""

async def generate_code(self, project_id, requirement, language="arduino",
                        existing_code="", model=None) -> dict:
    model = model or self.model_router.model_deep
    project_title = ""
    if project_id:
        proj = await self.redis.hgetall(f"mha:repair:project:{project_id}")
        project_title = proj.get("title", "")

    prompt = self.CODE_GEN_PROMPT.format(
        language=language, project_title=project_title,
        existing_code=existing_code[:3000] if existing_code else "Kein bestehender Code",
        requirement=requirement
    )
    messages = [{"role": "system", "content": prompt}]
    code = await self.ollama.chat(model=model, messages=messages, temperature=0.2, max_tokens=4096)

    # Datei speichern
    ext = {"arduino": ".ino", "python": ".py", "cpp": ".cpp", "html": ".html",
           "javascript": ".js", "yaml": ".yaml"}.get(language, ".txt")
    filename = f"code_{language}_{datetime.now().strftime('%H%M%S')}{ext}"
    if project_id:
        await self._save_file(project_id, filename, code)

    return {"status": "ok", "code": code, "filename": filename, "language": language}
```

### B) 3D-Modell (OpenSCAD)

```python
OPENSCAD_PROMPT = """Du bist ein CAD-Ingenieur. Generiere VOLLSTAENDIGEN OpenSCAD Code.
Masse in mm. Verwende Module fuer Wiederholungen.
Projekt: {project_title}
Anforderung: {requirement}

REGELN:
- Immer $fn=60 fuer runde Formen
- Toleranzen: Steckverbindungen +0.2mm, Pressfit -0.1mm
- Wandstaerke min. 1.2mm fuer FDM-Druck
- Kommentare auf Deutsch"""

async def generate_3d_model(self, project_id, requirement, model=None) -> dict:
    model = model or self.model_router.model_deep
    project_title = ""
    if project_id:
        proj = await self.redis.hgetall(f"mha:repair:project:{project_id}")
        project_title = proj.get("title", "")

    prompt = self.OPENSCAD_PROMPT.format(
        project_title=project_title, requirement=requirement)
    messages = [{"role": "system", "content": prompt}]
    scad_code = await self.ollama.chat(model=model, messages=messages, temperature=0.2, max_tokens=4096)

    filename = f"model_{datetime.now().strftime('%H%M%S')}.scad"
    if project_id:
        await self._save_file(project_id, filename, scad_code)
    return {"status": "ok", "code": scad_code, "filename": filename}
```

### C) SVG-Schaltplan

```python
SVG_PROMPT = """Du bist ein Elektrotechnik-Ingenieur. Generiere einen SVG-Schaltplan.
REGELN:
- Sauberes SVG mit viewBox
- Bauteile als Symbole (Rechteck=Widerstand, Kreis mit Pfeil=LED, etc.)
- Verbindungslinien als <line> oder <path>
- Beschriftungen mit <text>
- Farbschema: Hintergrund=#1a1a2e, Linien=#00d4ff, Text=#e0e0e0
Anforderung: {requirement}"""

async def generate_schematic(self, project_id, requirement, model=None) -> dict:
    model = model or self.model_router.model_deep
    prompt = self.SVG_PROMPT.format(requirement=requirement)
    messages = [{"role": "system", "content": prompt}]
    svg = await self.ollama.chat(model=model, messages=messages, temperature=0.2, max_tokens=4096)

    # SVG extrahieren (falls in Markdown-Block)
    svg_match = re.search(r'<svg[\s\S]*?</svg>', svg)
    if svg_match:
        svg = svg_match.group(0)

    filename = f"schematic_{datetime.now().strftime('%H%M%S')}.svg"
    if project_id:
        await self._save_file(project_id, filename, svg)
    return {"status": "ok", "svg": svg, "filename": filename}
```

### D) Website-Generation

```python
WEBSITE_PROMPT = """Du bist ein Fullstack-Webentwickler. Generiere eine VOLLSTAENDIGE,
FUNKTIONALE Single-Page HTML/CSS/JS Datei.
DESIGN: Modern, responsive, CSS Grid/Flexbox. Dunkles Theme (#040810, #00d4ff).
Anforderung: {requirement}
Kontext: {context}
REGELN: Alles in EINER Datei. Kein Framework noetig. Vanilla JS."""

async def generate_website(self, project_id, requirement, context="", model=None) -> dict:
    model = model or self.model_router.model_deep
    prompt = self.WEBSITE_PROMPT.format(requirement=requirement, context=context)
    messages = [{"role": "system", "content": prompt}]
    html = await self.ollama.chat(model=model, messages=messages, temperature=0.3, max_tokens=8192)

    filename = f"site_{datetime.now().strftime('%H%M%S')}.html"
    if project_id:
        await self._save_file(project_id, filename, html)
    return {"status": "ok", "html": html, "filename": filename}
```

### E) BOM-Generator

```python
async def generate_bom(self, project_id, model=None) -> dict:
    model = model or self.model_router.model_smart
    project = await self.redis.hgetall(f"mha:repair:project:{project_id}")
    parts = json.loads(project.get("parts", "[]"))
    files = await self.list_files(project_id)
    file_contents = {}
    for f in files[:5]:  # Max 5 Dateien fuer Kontext
        content = await self.read_file(project_id, f["name"])
        if content:
            file_contents[f["name"]] = content[:1500]

    prompt = f"""Erstelle eine vollstaendige BOM (Bill of Materials) fuer dieses Projekt.
Projekt: {project.get('title', '')}
Bekannte Teile: {json.dumps(parts, ensure_ascii=False)}
Projekt-Dateien: {json.dumps(file_contents, ensure_ascii=False)}

Format als Markdown-Tabelle:
| # | Bauteil | Menge | Spezifikation | Geschaetzter Preis | Bezugsquelle |
Ergaenze fehlende Teile die aus dem Code/Schaltplan ersichtlich sind."""
    messages = [{"role": "system", "content": prompt}]
    bom = await self.ollama.chat(model=model, messages=messages, temperature=0.3, max_tokens=2048)
    return {"status": "ok", "bom": bom}
```

### F) Dokumentation

```python
async def generate_documentation(self, project_id, model=None) -> dict:
    model = model or self.model_router.model_smart
    project = await self.redis.hgetall(f"mha:repair:project:{project_id}")
    files = await self.list_files(project_id)

    prompt = f"""Erstelle eine Projekt-Dokumentation (Markdown).
Projekt: {project.get('title', '')} ({project.get('category', '')})
Beschreibung: {project.get('description', '')}
Teile: {project.get('parts', '[]')}
Dateien: {[f['name'] for f in files]}
Status: {project.get('status', '')}

Struktur: Uebersicht, Materialien, Schaltung/Aufbau, Software, Montage, Tests, Fazit."""
    messages = [{"role": "system", "content": prompt}]
    doc = await self.ollama.chat(model=model, messages=messages, temperature=0.4, max_tokens=4096)

    filename = f"DOKU_{project.get('title', 'projekt').replace(' ', '_')}.md"
    await self._save_file(project_id, filename, doc)
    return {"status": "ok", "documentation": doc, "filename": filename}
```

### G) Berechnungen (KEIN LLM — direkte Python-Formeln)

```python
def calculate(self, calc_type, **params) -> dict:
    """Deterministische Berechnungen ohne LLM."""
    try:
        if calc_type == "resistor_divider":
            v_in = params["v_in"]
            v_out = params["v_out"]
            r2 = params.get("r2", 10000)
            r1 = r2 * (v_in / v_out - 1)
            # Naechsten E24-Wert finden
            r1_e24 = self._nearest_e24(r1)
            v_out_real = v_in * r2 / (r1_e24 + r2)
            return {"r1": r1_e24, "r2": r2, "v_out_real": round(v_out_real, 3),
                    "error_pct": round(abs(v_out - v_out_real) / v_out * 100, 2)}

        elif calc_type == "led_resistor":
            v_supply = params["v_supply"]
            v_led = params.get("v_led", 2.0)
            i_ma = params.get("i_ma", 20)
            r = (v_supply - v_led) / (i_ma / 1000)
            r_e24 = self._nearest_e24(r)
            power_mw = (v_supply - v_led) ** 2 / r_e24 * 1000
            return {"resistor_ohm": r_e24, "power_mw": round(power_mw, 1)}

        elif calc_type == "wire_gauge":
            current_a = params["current_a"]
            for mm2, max_a in sorted(WIRE_GAUGE_MM2.items()):
                if max_a >= current_a:
                    return {"recommended_mm2": mm2, "max_current_a": max_a}
            return {"error": "Strom zu hoch fuer Standard-Kabelquerschnitte"}

        elif calc_type == "ohms_law":
            v = params.get("v"); i = params.get("i"); r = params.get("r")
            if v and i: return {"r": round(v/i, 3), "p": round(v*i, 3)}
            if v and r: return {"i": round(v/r, 6), "p": round(v**2/r, 3)}
            if i and r: return {"v": round(i*r, 3), "p": round(i**2*r, 3)}

        elif calc_type == "3d_print_weight":
            volume_cm3 = params["volume_cm3"]
            material = params.get("material", "pla")
            infill = params.get("infill_pct", 20) / 100
            props = MATERIAL_PROPERTIES.get(material, MATERIAL_PROPERTIES["pla"])
            weight = volume_cm3 * props["density_g_cm3"] * infill
            return {"weight_g": round(weight, 1), "material": material, "infill_pct": infill*100}

        elif calc_type == "screw_torque":
            screw = params["screw_size"].upper()
            return {"torque_nm": SCREW_TORQUES_NM.get(screw, "unbekannt")}

        elif calc_type == "convert":
            value = params["value"]
            from_unit = params["from_unit"].lower()
            to_unit = params["to_unit"].lower()
            converter = UNIT_CONVERSIONS.get((from_unit, to_unit))
            if converter:
                return {"result": round(converter(value), 4), "from": from_unit, "to": to_unit}
            return {"error": f"Konvertierung {from_unit} → {to_unit} nicht unterstuetzt"}

        elif calc_type == "power_supply":
            components = params.get("components", [])
            total_ma = sum(c.get("current_ma", 0) * c.get("quantity", 1) for c in components)
            safety_factor = 1.25
            recommended_ma = total_ma * safety_factor
            voltage = params.get("voltage", 5)
            return {"total_ma": total_ma, "recommended_ma": round(recommended_ma),
                    "recommended_w": round(voltage * recommended_ma / 1000, 1)}

        return {"error": f"Unbekannter Berechnungstyp: {calc_type}"}
    except Exception as e:
        return {"error": str(e)}

def _nearest_e24(self, value) -> float:
    """Findet den naechsten E24-Widerstandswert."""
    decade = 10 ** int(math.log10(value))
    normalized = value / decade
    closest = min(RESISTOR_E24, key=lambda x: abs(x - normalized))
    return closest * decade
```

### H) File-Management (Redis-basiert)

```python
async def _save_file(self, project_id, filename, content) -> dict:
    """Speichert Datei auf Disk + Referenz in Redis."""
    project_dir = self.FILES_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    filepath = project_dir / filename
    filepath.write_text(content, encoding="utf-8")
    # Redis: Datei-Liste und Versionierung
    await self.redis.rpush(f"mha:repair:files:{project_id}", filename)
    await self.redis.rpush(f"mha:repair:versions:{project_id}:{filename}",
                           json.dumps({"timestamp": datetime.now().isoformat(),
                                       "size": len(content)}))
    return {"status": "ok", "path": str(filepath)}

async def read_file(self, project_id, filename) -> str:
    filepath = self.FILES_DIR / project_id / filename
    if filepath.exists() and filepath.resolve().is_relative_to(self.FILES_DIR.resolve()):
        return filepath.read_text(encoding="utf-8")
    return ""

async def list_files(self, project_id) -> list:
    filenames = await self.redis.lrange(f"mha:repair:files:{project_id}", 0, -1)
    result = []
    for fn in filenames:
        filepath = self.FILES_DIR / project_id / fn
        if filepath.exists():
            result.append({"name": fn, "size": filepath.stat().st_size,
                           "modified": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()})
    return result

async def delete_file(self, project_id, filename) -> dict:
    filepath = self.FILES_DIR / project_id / filename
    if filepath.exists() and filepath.resolve().is_relative_to(self.FILES_DIR.resolve()):
        filepath.unlink()
        await self.redis.lrem(f"mha:repair:files:{project_id}", 0, filename)
        return {"status": "ok"}
    return {"status": "error", "message": "Datei nicht gefunden"}

async def export_project(self, project_id) -> str:
    """Exportiert alle Projekt-Dateien als ZIP."""
    import zipfile, io
    project_dir = self.FILES_DIR / project_id
    if not project_dir.exists():
        return ""
    zip_path = self.FILES_DIR / f"{project_id}_export.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in project_dir.iterdir():
            if f.is_file():
                zf.write(f, f.name)
    return str(zip_path)
```

### I) Test-Generation

```python
async def generate_tests(self, project_id, filename, model=None) -> dict:
    model = model or self.model_router.model_deep
    code = await self.read_file(project_id, filename)
    if not code:
        return {"status": "error", "message": "Datei nicht gefunden"}

    ext = Path(filename).suffix
    test_frameworks = {
        ".py": "pytest", ".ino": "Arduino Serial Test", ".js": "Jest",
        ".cpp": "Google Test", ".html": "Browser Console Test"
    }
    framework = test_frameworks.get(ext, "generic")

    prompt = f"""Generiere Tests fuer diesen Code.
Framework: {framework}
Code:
{code[:4000]}
REGELN: Vollstaendige, ausfuehrbare Tests. Edge Cases abdecken."""
    messages = [{"role": "system", "content": prompt}]
    tests = await self.ollama.chat(model=model, messages=messages, temperature=0.2, max_tokens=4096)

    test_filename = f"test_{filename}"
    await self._save_file(project_id, test_filename, tests)
    return {"status": "ok", "tests": tests, "filename": test_filename}
```

---

## 3. workshop_library.py (~250 Zeilen)

Eigene ChromaDB-Collection fuer Werkstatt-Fachbuecher (200MB+, 1000+ Seiten).

### Klasse

```python
import json, logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Pfade
WORKSHOP_DOCS_DIR = Path("/app/data/workshop/library")
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


class WorkshopLibrary:
    """Workshop-RAG: Eigene ChromaDB-Collection fuer technische Fachbuecher."""

    COLLECTION_NAME = "workshop_library"
    CHUNK_SIZE = 1500      # Zeichen pro Chunk
    CHUNK_OVERLAP = 200    # Ueberlappung

    def __init__(self):
        self.chroma_client = None
        self.collection = None
        self.embedding_fn = None

    async def initialize(self, chroma_client, embedding_fn):
        """Initialisiert mit eigenem ChromaDB Client + Embedding-Funktion.

        Nutzt die gleiche ChromaDB-Instanz wie knowledge_base.py,
        aber eine EIGENE Collection (workshop_library statt knowledge_base).
        """
        self.chroma_client = chroma_client
        self.embedding_fn = embedding_fn
        WORKSHOP_DOCS_DIR.mkdir(parents=True, exist_ok=True)
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "Workshop technical reference library"}
        )
        logger.info("WorkshopLibrary: Collection '%s' mit %d Dokumenten",
                     self.COLLECTION_NAME, self.collection.count())

    async def ingest_document(self, filepath: str) -> dict:
        """Importiert ein Dokument in die Workshop-Library.

        Unterstuetzt PDF (via knowledge_base.py Pattern), TXT, MD.
        """
        path = Path(filepath)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return {"status": "error",
                    "message": f"Nicht unterstuetzt: {path.suffix}. Erlaubt: {SUPPORTED_EXTENSIONS}"}

        # Text extrahieren
        if path.suffix.lower() == ".pdf":
            text = await self._extract_pdf(path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")

        if not text.strip():
            return {"status": "error", "message": "Dokument ist leer"}

        # Chunken
        chunks = self._chunk_text(text)

        # In ChromaDB speichern
        ids = [f"{path.stem}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": path.name, "chunk": i, "total_chunks": len(chunks)}
                     for i in range(len(chunks))]
        embeddings = [self.embedding_fn(chunk) for chunk in chunks]

        self.collection.upsert(ids=ids, documents=chunks,
                               metadatas=metadatas, embeddings=embeddings)

        return {"status": "ok", "document": path.name,
                "chunks": len(chunks), "total_docs": self.collection.count()}

    async def search(self, query: str, n_results: int = 5) -> list:
        """Sucht in der Workshop-Library."""
        if not self.collection or self.collection.count() == 0:
            return []
        query_embedding = self.embedding_fn(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, self.collection.count())
        )
        formatted = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
            dist = results.get("distances", [[]])[0][i] if results.get("distances") else 0
            formatted.append({
                "content": doc, "source": meta.get("source", ""),
                "chunk": meta.get("chunk", 0), "relevance": round(1 - dist, 3)
            })
        return formatted

    async def list_documents(self) -> list:
        """Listet alle Dokumente in der Library."""
        files = []
        for f in WORKSHOP_DOCS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append({"name": f.name, "size_mb": round(f.stat().st_size / 1024 / 1024, 2)})
        return files

    async def get_stats(self) -> dict:
        count = self.collection.count() if self.collection else 0
        docs = await self.list_documents()
        return {"total_chunks": count, "total_documents": len(docs),
                "total_size_mb": round(sum(d["size_mb"] for d in docs), 2)}

    def _chunk_text(self, text: str) -> list:
        """Teilt Text in ueberlappende Chunks."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.CHUNK_SIZE
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start = end - self.CHUNK_OVERLAP
        return chunks

    async def _extract_pdf(self, path: Path) -> str:
        """Extrahiert Text aus PDF (Pattern: knowledge_base.py)."""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            text = ""
            for page in doc:
                text += page.get_text() + "\n"
            doc.close()
            return text
        except ImportError:
            logger.warning("PyMuPDF nicht installiert. PDF-Import nicht moeglich.")
            return ""
```

---

## 4. workshop/index.html (~1000 Zeilen) — Werkstatt-HUD

Vollstaendige Single-Page Werkstatt-Oberflaeche. Design-Pattern: `static/ui/index.html`.

### CSS-Variablen (EXAKT aus bestehender UI uebernehmen)

```css
:root {
    --accent: #00d4ff;
    --accent-dim: #00d4ff33;
    --bg-primary: #040810;
    --bg-secondary: #0a1020;
    --bg-card: #0d1528;
    --text-primary: #e0e8f0;
    --text-secondary: #7a8a9a;
    --border: #1a2a3a;
    --success: #00ff88;
    --warning: #ffaa00;
    --danger: #ff4444;
    --glass: rgba(10, 16, 32, 0.85);
}
```

### Struktur

```html
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>J.A.R.V.I.S. Workshop</title>
    <style>
        /* ... CSS-Variablen von oben ... */
        /* Layout: CSS Grid — Header, Sidebar, Main, Footer */
        body { margin: 0; background: var(--bg-primary); color: var(--text-primary);
               font-family: 'JetBrains Mono', 'Fira Code', monospace; }
        .workshop-grid {
            display: grid; height: 100vh;
            grid-template: "header header" 60px
                           "sidebar main" 1fr
                           "footer footer" 40px
                           / 280px 1fr;
        }
        .header { grid-area: header; /* Boot-Animation + Projekt-Info */ }
        .sidebar { grid-area: sidebar; /* Navigation + Projekt-Liste */ }
        .main { grid-area: main; overflow: auto; /* Aktiver Content */ }
        .footer { grid-area: footer; /* Status-Bar */ }
    </style>
</head>
<body>
```

### Widgets (als `<div class="widget">` innerhalb `.main`)

| Widget | Inhalt | Daten-Quelle |
|--------|--------|-------------|
| `project-info` | Titel, Status-Badge, Kategorie-Icon, Timer | `/api/workshop/project/{id}` |
| `step-navigator` | Aktueller Schritt, Progress-Bar, Vor/Zurueck | WebSocket `workshop.step` |
| `parts-list` | Teile mit Checkbox (verfuegbar/fehlend) | `/api/workshop/project/{id}` |
| `code-editor` | Monaco-artig mit Syntax-Highlighting (Prism.js) | `/api/workshop/files/{id}/{fn}` |
| `schematic-viewer` | SVG-Inline-Rendering | `/api/workshop/files/{id}/{fn}` |
| `3d-preview` | OpenSCAD-Code-Ansicht + STL-Link | `/api/workshop/files/{id}/{fn}` |
| `chat-panel` | Workshop-Chat mit Voice-Input | `/api/chat` (bestehend) |
| `environment` | Temperatur, Feuchtigkeit, CO2 aus HA | WebSocket `workshop.environment` |
| `printer-status` | Druckfortschritt, Temperaturen, ETA | WebSocket `workshop.printer` |
| `arm-control` | Greifer-Buttons, Position-Presets | `/api/workshop/arm/*` |
| `budget-tracker` | Budget vs. Ausgaben, Diagramm | `/api/workshop/project/{id}` |
| `file-browser` | Dateiliste mit Download/Delete | `/api/workshop/files/{id}` |
| `calculator` | Quick-Calc Buttons (Ohm, LED, Draht) | Lokal (JS) + `/api/workshop/calculate` |
| `journal` | Tages-Eintraege, Timeline | `/api/workshop/journal` |

### Boot-Animation (Pattern: ui/index.html Zeile 551-572 + app.js 50-121)

```javascript
// Boot-Sequenz: SVG-Ring + Typewriter + Web Audio (identisch zum Hauptsystem)
async function bootWorkshop() {
    const ring = document.getElementById('boot-ring');
    const text = document.getElementById('boot-text');
    // SVG Ring-Animation
    ring.style.animation = 'spin 2s linear infinite';
    // Typewriter
    const messages = [
        "Werkstatt-Systeme initialisieren...",
        "Sensor-Array verbunden.",
        "3D-Drucker: Online.",
        "Roboterarm: Bereit.",
        "Workshop-Modus aktiv, Sir."
    ];
    for (const msg of messages) {
        await typewrite(text, msg, 40);
        await sleep(600);
    }
    // Fade to main UI
    document.getElementById('boot-screen').classList.add('fade-out');
    setTimeout(() => {
        document.getElementById('boot-screen').style.display = 'none';
        document.getElementById('workshop-main').style.display = 'grid';
        connectWebSocket();
    }, 800);
}
```

### WebSocket-Handler

```javascript
function connectWebSocket() {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        switch (msg.event) {
            case 'workshop.step':
                updateStepNavigator(msg.data);
                break;
            case 'workshop.diagnosis':
                showDiagnosis(msg.data);
                break;
            case 'workshop.file_created':
                refreshFileList(msg.data);
                break;
            case 'workshop.printer':
                updatePrinterWidget(msg.data);
                break;
            case 'workshop.environment':
                updateEnvironment(msg.data);
                break;
            case 'workshop.timer':
                showTimerNotification(msg.data);
                break;
            case 'assistant.speaking':
                addChatMessage('jarvis', msg.data.text);
                break;
        }
    };
}
```

### Voice Input (Chrome Web Speech API)

```javascript
function startVoiceInput() {
    const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    recognition.lang = 'de-DE';
    recognition.continuous = false;
    recognition.onresult = async (event) => {
        const text = event.results[0][0].transcript;
        document.getElementById('chat-input').value = text;
        await sendChatMessage(text);
    };
    recognition.start();
}
```

### API-Aufrufe (Pattern: app.js)

```javascript
async function apiCall(endpoint, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(`/api/workshop/${endpoint}`, opts);
    return await resp.json();
}

// Beispiel-Aufrufe:
// apiCall('projects')                           → GET  /api/workshop/projects
// apiCall('project/abc123')                     → GET  /api/workshop/project/abc123
// apiCall('calculate', 'POST', {type: 'ohms_law', params: {v: 5, r: 100}})
// apiCall('files/abc123')                       → GET  /api/workshop/files/abc123
```

---

## 5. function_calling.py — EDIT (+180 Zeilen)

### A) Tool-Definition (einfuegen nach letztem Tool in `_ASSISTANT_TOOLS_STATIC`, ca. Zeile 1450)

```python
# --- Workshop-Modus: Reparatur & Werkstatt ---
{
    "type": "function",
    "function": {
        "name": "manage_repair",
        "description": (
            "Werkstatt-Assistent: Projekte verwalten, Diagnose, Code/3D/Schaltplan generieren, "
            "Berechnungen, Simulation, 3D-Drucker, Roboterarm, Inventar, Journal. "
            "Nutze dieses Tool wenn der User etwas reparieren, bauen, basteln, konstruieren, "
            "programmieren, loeten, 3d-drucken, oder simulieren will."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_project", "list_projects", "get_project", "update_project",
                        "complete_project", "add_note", "add_part", "diagnose",
                        "generate_code", "generate_3d", "generate_schematic",
                        "generate_website", "generate_bom", "generate_docs",
                        "generate_tests", "calculate", "simulate", "troubleshoot",
                        "suggest_improvements", "compare_components",
                        "scan_object", "search_library",
                        "add_workshop_item", "list_workshop",
                        "set_budget", "add_expense",
                        "printer_status", "start_print", "pause_print", "cancel_print",
                        "arm_move", "arm_gripper", "arm_home", "arm_pick_tool",
                        "start_timer", "pause_timer",
                        "journal_add", "journal_get",
                        "save_snippet", "get_snippet",
                        "safety_checklist", "calibration_guide",
                        "analyze_error_log", "evaluate_measurement",
                        "lend_tool", "return_tool", "list_lent",
                        "create_from_template", "get_stats",
                        "switch_project", "export_project",
                        "check_device", "link_device", "get_power",
                    ],
                    "description": "Die auszufuehrende Werkstatt-Aktion",
                },
                "project_id": {
                    "type": "string",
                    "description": "Projekt-ID (8-stellig, z.B. 'a1b2c3d4'). Wird bei den meisten Aktionen benoetigt.",
                },
                "title": {"type": "string", "description": "Projekt-Titel (fuer create_project)"},
                "description": {"type": "string", "description": "Beschreibung/Anforderung/Symptom"},
                "category": {
                    "type": "string",
                    "enum": ["reparatur", "bau", "maker", "erfindung", "renovierung"],
                    "description": "Projekt-Kategorie",
                },
                "priority": {
                    "type": "string",
                    "enum": ["niedrig", "normal", "hoch", "dringend"],
                    "description": "Projekt-Prioritaet",
                },
                "status": {
                    "type": "string",
                    "enum": ["erstellt", "diagnose", "teile_bestellt", "in_arbeit", "pausiert", "fertig"],
                    "description": "Neuer Projekt-Status (fuer update_project)",
                },
                "language": {
                    "type": "string",
                    "enum": ["arduino", "python", "cpp", "html", "javascript", "yaml", "micropython"],
                    "description": "Programmiersprache fuer Code-Generation",
                },
                "calc_type": {
                    "type": "string",
                    "enum": ["resistor_divider", "led_resistor", "wire_gauge", "ohms_law",
                             "3d_print_weight", "screw_torque", "convert", "power_supply"],
                    "description": "Berechnungstyp",
                },
                "calc_params": {
                    "type": "object",
                    "description": "Parameter fuer die Berechnung (z.B. {\"v_in\": 12, \"v_out\": 3.3})",
                },
                "item": {"type": "string", "description": "Artikelname / Werkzeugname"},
                "quantity": {"type": "integer", "description": "Menge"},
                "cost": {"type": "number", "description": "Kosten in Euro"},
                "person": {"type": "string", "description": "Personenname (fuer Verleih, Skills)"},
                "text": {"type": "string", "description": "Freitext (Messwert, Log, Notiz, etc.)"},
                "filename": {"type": "string", "description": "Dateiname fuer File-Operationen"},
                "minutes": {"type": "integer", "description": "Timer-Dauer in Minuten"},
                "template": {"type": "string", "description": "Template-Name"},
                "entity_id": {"type": "string", "description": "HA Entity-ID"},
                "x": {"type": "number", "description": "Arm X-Position"},
                "y": {"type": "number", "description": "Arm Y-Position"},
                "z": {"type": "number", "description": "Arm Z-Position"},
                "budget": {"type": "number", "description": "Budget in Euro"},
                "component_a": {"type": "string", "description": "Erste Komponente (Vergleich)"},
                "component_b": {"type": "string", "description": "Zweite Komponente (Vergleich)"},
                "query": {"type": "string", "description": "Suchbegriff (Library/Projekte)"},
            },
            "required": ["action"],
        },
    },
},
```

### B) _ALLOWED_FUNCTIONS erweitern (Zeile ~1488)

```python
# Zur bestehenden frozenset hinzufuegen:
"manage_repair",
```

### C) Handler-Methode in FunctionExecutor (nach `_exec_manage_inventory`)

```python
# ------------------------------------------------------------------
# Workshop-Modus: Reparatur & Werkstatt
# ------------------------------------------------------------------

async def _exec_manage_repair(self, args: dict) -> dict:
    """Dispatch fuer alle Workshop-Aktionen."""
    import assistant.main as main_module
    brain = main_module.brain
    planner = brain.repair_planner
    generator = brain.workshop_generator

    action = args["action"]
    pid = args.get("project_id", "")

    # --- Projekt-CRUD ---
    if action == "create_project":
        return await planner.create_project(
            title=args.get("title", "Neues Projekt"),
            description=args.get("description", ""),
            category=args.get("category", "maker"),
            priority=args.get("priority", "normal"))
    elif action == "list_projects":
        projects = await planner.list_projects(
            status_filter=args.get("status"),
            category_filter=args.get("category"))
        return {"success": True, "projects": projects, "count": len(projects)}
    elif action == "get_project":
        p = await planner.get_project(pid)
        return p if p else {"success": False, "message": "Projekt nicht gefunden"}
    elif action == "update_project":
        updates = {}
        for k in ("status", "title", "category", "priority", "description"):
            if k in args: updates[k] = args[k]
        return await planner.update_project(pid, **updates)
    elif action == "complete_project":
        return await planner.complete_project(pid, notes=args.get("text", ""))
    elif action == "add_note":
        return await planner.add_project_note(pid, args.get("text", ""))
    elif action == "add_part":
        return await planner.add_part(pid, args.get("item", ""), args.get("quantity", 1),
                                      args.get("cost", 0))

    # --- LLM-Features ---
    elif action == "diagnose":
        return {"success": True,
                "message": await planner.diagnose_problem(args.get("description", ""), args.get("person", ""))}
    elif action == "simulate":
        return {"success": True,
                "message": await planner.simulate_design(pid, args.get("description", ""))}
    elif action == "troubleshoot":
        return {"success": True,
                "message": await planner.troubleshoot(pid, args.get("description", ""))}
    elif action == "suggest_improvements":
        return {"success": True, "message": await planner.suggest_improvements(pid)}
    elif action == "compare_components":
        return {"success": True,
                "message": await planner.compare_components(
                    args.get("component_a", ""), args.get("component_b", ""),
                    use_case=args.get("description", ""))}
    elif action == "safety_checklist":
        return {"success": True, "message": await planner.generate_safety_checklist(pid)}
    elif action == "calibration_guide":
        return {"success": True,
                "message": await planner.calibration_guide(args.get("description", ""))}
    elif action == "analyze_error_log":
        return {"success": True,
                "message": await planner.analyze_error_log(pid, args.get("text", ""))}
    elif action == "evaluate_measurement":
        return {"success": True,
                "message": await planner.evaluate_measurement(pid, args.get("text", ""))}

    # --- Generator ---
    elif action == "generate_code":
        return await generator.generate_code(pid, args.get("description", ""),
                                             language=args.get("language", "arduino"))
    elif action == "generate_3d":
        return await generator.generate_3d_model(pid, args.get("description", ""))
    elif action == "generate_schematic":
        return await generator.generate_schematic(pid, args.get("description", ""))
    elif action == "generate_website":
        return await generator.generate_website(pid, args.get("description", ""))
    elif action == "generate_bom":
        return await generator.generate_bom(pid)
    elif action == "generate_docs":
        return await generator.generate_documentation(pid)
    elif action == "generate_tests":
        return await generator.generate_tests(pid, args.get("filename", ""))

    # --- Berechnungen ---
    elif action == "calculate":
        return generator.calculate(args.get("calc_type", ""), **args.get("calc_params", {}))

    # --- Scanner ---
    elif action == "scan_object":
        return await planner.scan_object(description=args.get("description", ""))

    # --- Library ---
    elif action == "search_library":
        results = await brain.workshop_library.search(args.get("query", ""))
        return {"success": True, "results": results}

    # --- Werkstatt-Inventar ---
    elif action == "add_workshop_item":
        return await planner.add_workshop_item(
            args.get("item", ""), quantity=args.get("quantity", 1),
            category=args.get("category", "werkzeug"))
    elif action == "list_workshop":
        items = await planner.list_workshop(category=args.get("category"))
        return {"success": True, "items": items}

    # --- Budget ---
    elif action == "set_budget":
        return await planner.set_project_budget(pid, args.get("budget", 0))
    elif action == "add_expense":
        return await planner.add_expense(pid, args.get("item", ""), args.get("cost", 0))

    # --- 3D-Drucker ---
    elif action == "printer_status":
        return await planner.get_printer_status()
    elif action == "start_print":
        return await planner.start_print(project_id=pid, filename=args.get("filename", ""))
    elif action == "pause_print":
        return await planner.pause_print()
    elif action == "cancel_print":
        return await planner.cancel_print()

    # --- Roboterarm ---
    elif action == "arm_move":
        return await planner.arm_move(args.get("x", 0), args.get("y", 0), args.get("z", 0))
    elif action == "arm_gripper":
        return await planner.arm_gripper(args.get("description", "open"))
    elif action == "arm_home":
        return await planner.arm_home()
    elif action == "arm_pick_tool":
        return await planner.arm_pick_tool(args.get("item", ""))

    # --- Timer ---
    elif action == "start_timer":
        return await planner.start_timer(pid)
    elif action == "pause_timer":
        return await planner.pause_timer(pid)

    # --- Journal ---
    elif action == "journal_add":
        return await planner.add_journal_entry(args.get("text", ""))
    elif action == "journal_get":
        return await planner.get_journal()

    # --- Snippets ---
    elif action == "save_snippet":
        return await planner.save_snippet(args.get("item", ""), args.get("text", ""),
                                          language=args.get("language", ""))
    elif action == "get_snippet":
        return await planner.get_snippet(args.get("item", ""))

    # --- Verleih ---
    elif action == "lend_tool":
        return await planner.lend_tool(args.get("item", ""), args.get("person", ""))
    elif action == "return_tool":
        return await planner.return_tool(args.get("item", ""))
    elif action == "list_lent":
        return {"success": True, "lent_tools": await planner.list_lent_tools()}

    # --- Templates ---
    elif action == "create_from_template":
        return await planner.create_from_template(args.get("template", ""), title=args.get("title", ""))

    # --- Stats ---
    elif action == "get_stats":
        return await planner.get_workshop_stats()

    # --- Multi-Project ---
    elif action == "switch_project":
        return await planner.switch_project(pid)
    elif action == "export_project":
        path = await generator.export_project(pid)
        return {"success": True, "zip_path": path} if path else {"success": False, "message": "Keine Dateien"}

    # --- Devices ---
    elif action == "check_device":
        return await planner.check_device_online(args.get("entity_id", ""))
    elif action == "link_device":
        return await planner.link_device_to_project(pid, args.get("entity_id", ""))
    elif action == "get_power":
        return await planner.get_power_consumption(args.get("entity_id", ""))

    return {"success": False, "message": f"Unbekannte Aktion: {action}"}
```

---

## 6. brain.py — EDIT (+70 Zeilen)

### A) Import (nach Zeile 75, bei den anderen Imports)

```python
from .repair_planner import RepairPlanner
from .workshop_generator import WorkshopGenerator
from .workshop_library import WorkshopLibrary
```

### B) __init__ (nach Zeile 215, nach `self.cooking = CookingAssistant(...)`)

```python
# Workshop-Modus: Werkstatt-Ingenieur
self.repair_planner = RepairPlanner(self.ollama, self.ha)
self.workshop_generator = WorkshopGenerator(self.ollama)
self.workshop_library = WorkshopLibrary()
```

### C) initialize() (nach Zeile 372, nach CookingAssistant init, innerhalb _safe_init Block)

```python
# Workshop-Modus initialisieren
await _safe_init("RepairPlanner", self.repair_planner.initialize(redis_client=self.memory.redis))
await _safe_init("WorkshopGenerator", self.workshop_generator.initialize(redis_client=self.memory.redis))
self.repair_planner.set_generator(self.workshop_generator)
self.repair_planner.set_model_router(self.model_router)
self.repair_planner.semantic_memory = self.memory.semantic
self.repair_planner.set_notify_callback(self._handle_workshop_timer)
self.workshop_generator.set_model_router(self.model_router)

# Workshop Library (gleiche ChromaDB-Instanz, eigene Collection)
try:
    await self.workshop_library.initialize(
        chroma_client=self.knowledge_base.chroma_client,
        embedding_fn=self.knowledge_base.get_embedding
    )
except Exception as e:
    _degraded_modules.append("WorkshopLibrary")
    logger.error("F-069: WorkshopLibrary init fehlgeschlagen: %s", e)
```

### D) process() — Intent-Interception (nach Zeile 868, nach Koch-Intent Block, VOR Planungs-Dialog)

```python
# Workshop-Modus: Aktivierung/Deaktivierung
if self.repair_planner.is_activation_command(text):
    logger.info("Workshop Aktivierung: '%s'", text)
    workshop_response = await self.repair_planner.toggle_activation(text)
    self._remember_exchange(text, workshop_response)
    tts_data = self.tts_enhancer.enhance(workshop_response, message_type="casual")
    await self._speak_and_emit(workshop_response, room=room, tts_data=tts_data)
    return {
        "response": workshop_response, "actions": [],
        "model_used": "workshop_activation",
        "context_room": room or "unbekannt", "tts": tts_data, "_emitted": True,
    }

# Workshop-Modus: Navigation — aktive Session hat Vorrang
if self.repair_planner.is_repair_navigation(text):
    logger.info("Workshop-Navigation: '%s'", text)
    workshop_response = await self.repair_planner.handle_navigation(text)
    self._remember_exchange(text, workshop_response)
    tts_data = self.tts_enhancer.enhance(workshop_response, message_type="casual")
    await self._speak_and_emit(workshop_response, room=room, tts_data=tts_data)
    return {
        "response": workshop_response, "actions": [],
        "model_used": "workshop_assistant",
        "context_room": room or "unbekannt", "tts": tts_data, "_emitted": True,
    }

# Workshop-Modus: Intent — neues Werkstatt-Gespraech
if (self.repair_planner.is_repair_intent(text)
        or self.repair_planner.has_active_session()
        or await self.memory.redis.exists("mha:repair:manual_active")):
    logger.info("Workshop-Intent erkannt: '%s'", text)
    # Wird vom LLM via manage_repair Tool gehandhabt — kein direkter Eingriff
    # Nur Personality-Modus wechseln falls Workshop aktiv
    pass
```

### E) Callback-Methode (neben `_handle_cooking_timer`)

```python
async def _handle_workshop_timer(self, message: str):
    """Callback fuer Workshop-Timer-Benachrichtigungen."""
    from .websocket import emit_proactive
    await emit_proactive(message, event_type="workshop_timer", urgency="medium")
    logger.info("Workshop-Timer: %s", message)
```

---

## 7. personality.py — EDIT (+30 Zeilen)

### Ingenieur-Modus Erweiterung in `build_system_prompt` (nach Zeile 1307)

```python
# Workshop-Modus: Ingenieur-Persoenlichkeit erweitern
workshop_active = False
if context:
    workshop_active = context.get("workshop_active", False)
if workshop_active:
    prompt += """

WERKSTATT-MODUS AKTIV:
Du bist jetzt zusaetzlich ein brillanter Ingenieur und Werkstatt-Meister.
- Verwende technische Praezision: Exakte Masse, Toleranzen, Spezifikationen.
- Bei Elektronik: Spannungen, Stroeme, Pin-Belegungen nennen.
- Bei Mechanik: Drehmomente, Materialstaerken, Schraubengroessen.
- Denke in Loesungen: "Das liesse sich mit einem MOSFET als Low-Side Switch realisieren."
- Sicherheit hat Vorrang: Immer auf Gefahren hinweisen (Kurzschluss, Ueberhitzung, Verletzung).
- Proaktiv: Schlage Verbesserungen vor wenn du Schwaechen siehst.
- Nutze das manage_repair Tool fuer ALLE Werkstatt-Aktionen.
- Wenn der User ein Projekt hat, beziehe dich immer darauf.
"""
```

---

## 8. main.py — EDIT (+100 Zeilen)

### A) Workshop-SPA Route (nach Zeile 2828, nach `/chat` Route, gleiches Pattern)

```python
# ============================================================
# Workshop-Modus: SPA + API
# ============================================================

_workshop_static_dir = Path(__file__).parent.parent / "static" / "workshop"
_workshop_static_dir.mkdir(parents=True, exist_ok=True)


@app.get("/workshop/{path:path}")
async def workshop_serve(path: str = ""):
    """Werkstatt-HUD — Single-Page App."""
    if path and not path.endswith("/"):
        asset = _workshop_static_dir / path
        if asset.is_file() and asset.resolve().is_relative_to(_workshop_static_dir.resolve()):
            media_types = {".js": "application/javascript", ".css": "text/css",
                           ".png": "image/png", ".svg": "image/svg+xml"}
            mt = media_types.get(asset.suffix, None)
            return FileResponse(asset, media_type=mt, headers=_NO_CACHE_HEADERS)
    index_path = _workshop_static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html", headers=_NO_CACHE_HEADERS)
    return HTMLResponse("<h1>Workshop HUD — index.html nicht gefunden</h1>", status_code=404)


@app.get("/workshop")
async def workshop_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/workshop/")
```

### B) Workshop API-Endpoints (nach der SPA-Route)

```python
@app.get("/api/workshop/projects")
async def workshop_list_projects(status: str = "", category: str = ""):
    """Listet alle Workshop-Projekte."""
    projects = await brain.repair_planner.list_projects(
        status_filter=status or None, category_filter=category or None)
    return {"success": True, "projects": projects, "count": len(projects)}


@app.get("/api/workshop/project/{project_id}")
async def workshop_get_project(project_id: str):
    """Holt ein einzelnes Projekt."""
    project = await brain.repair_planner.get_project(project_id)
    if not project:
        raise HTTPException(404, "Projekt nicht gefunden")
    return project


@app.get("/api/workshop/files/{project_id}")
async def workshop_list_files(project_id: str):
    """Listet Dateien eines Projekts."""
    files = await brain.workshop_generator.list_files(project_id)
    return {"success": True, "files": files}


@app.get("/api/workshop/files/{project_id}/{filename}")
async def workshop_get_file(project_id: str, filename: str):
    """Liest eine Projekt-Datei."""
    content = await brain.workshop_generator.read_file(project_id, filename)
    if content is None:
        raise HTTPException(404, "Datei nicht gefunden")
    return {"success": True, "filename": filename, "content": content}


@app.post("/api/workshop/calculate")
async def workshop_calculate(request: Request):
    """Fuehrt eine Werkstatt-Berechnung aus."""
    data = await request.json()
    calc_type = data.get("type", "")
    params = data.get("params", {})
    result = brain.workshop_generator.calculate(calc_type, **params)
    return result


@app.get("/api/workshop/journal")
async def workshop_journal(period: str = "today"):
    """Holt Workshop-Journal."""
    return await brain.repair_planner.get_journal(period)


@app.get("/api/workshop/stats")
async def workshop_stats():
    """Holt Workshop-Statistiken."""
    return await brain.repair_planner.get_workshop_stats()


@app.get("/api/workshop/library/stats")
async def workshop_library_stats():
    """Holt Library-Statistiken."""
    return await brain.workshop_library.get_stats()


@app.get("/api/workshop/library/documents")
async def workshop_library_documents():
    """Listet Library-Dokumente."""
    return await brain.workshop_library.list_documents()


@app.post("/api/workshop/library/ingest")
async def workshop_library_ingest(file: UploadFile = File(...)):
    """Importiert ein Dokument in die Workshop-Library."""
    # Datei speichern
    target = Path("/app/data/workshop/library") / file.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    if len(content) > 200 * 1024 * 1024:  # 200MB Limit
        raise HTTPException(413, "Datei zu gross (max 200MB)")
    target.write_bytes(content)
    # Importieren
    result = await brain.workshop_library.ingest_document(str(target))
    return result


@app.get("/api/workshop/export/{project_id}")
async def workshop_export(project_id: str):
    """Exportiert Projekt als ZIP."""
    zip_path = await brain.workshop_generator.export_project(project_id)
    if not zip_path:
        raise HTTPException(404, "Keine Dateien zum Exportieren")
    return FileResponse(zip_path, filename=f"workshop_{project_id}.zip",
                        media_type="application/zip")
```

---

## 9. static/ui/index.html — EDIT (+120 Zeilen)

### Neuer Settings-Tab `tab-workshop` (nach `tab-cooking` nav-item, Zeile ~866)

#### A) Navigation-Item (in `.settings-nav`, nach `tab-cooking`)

```html
<div class="nav-item" data-page="settings" data-tab="tab-workshop">
    <span class="nav-icon">&#128295;</span>Werkstatt
</div>
```

#### B) Tab-Content (in `.settings-content`, nach dem cooking-tab div)

```html
<div id="tab-workshop" class="tab-content" style="display:none">
    <h2>Werkstatt-Modus</h2>
    <p class="settings-desc">J.A.R.V.I.S. als Werkstatt-Ingenieur: Reparaturen, Elektronik, 3D-Druck, Robotik.</p>

    <div class="setting-group">
        <h3>Grundeinstellungen</h3>
        <div class="setting-row">
            <label>Werkstatt aktiviert</label>
            <label class="toggle">
                <input type="checkbox" id="ws-enabled" data-setting="workshop.enabled">
                <span class="slider"></span>
            </label>
            <span class="setting-help">Aktiviert den Werkstatt-Modus. Jarvis erkennt dann automatisch Reparatur- und Bastler-Anfragen.</span>
        </div>
        <div class="setting-row">
            <label>Werkstatt-Raum (HA)</label>
            <input type="text" id="ws-room" data-setting="workshop.workshop_room" placeholder="werkstatt" class="setting-input">
            <span class="setting-help">Name des Raums in Home Assistant fuer Sensor-Daten (Temperatur, Feuchtigkeit, CO2).</span>
        </div>
        <div class="setting-row">
            <label>Auto-Sicherheits-Check</label>
            <label class="toggle">
                <input type="checkbox" id="ws-safety" data-setting="workshop.auto_safety_check">
                <span class="slider"></span>
            </label>
            <span class="setting-help">Zeigt automatisch eine Sicherheits-Checkliste vor Projektstart.</span>
        </div>
        <div class="setting-row">
            <label>Proaktive Vorschlaege</label>
            <label class="toggle">
                <input type="checkbox" id="ws-proactive" data-setting="workshop.proactive_suggestions">
                <span class="slider"></span>
            </label>
            <span class="setting-help">Jarvis schlaegt aktiv Verbesserungen und naechste Schritte vor.</span>
        </div>
    </div>

    <div class="setting-group">
        <h3>3D-Drucker</h3>
        <div class="setting-row">
            <label>3D-Drucker aktiviert</label>
            <label class="toggle">
                <input type="checkbox" id="ws-printer" data-setting="workshop.printer_3d.enabled">
                <span class="slider"></span>
            </label>
        </div>
        <div class="setting-row">
            <label>Entity-Prefix</label>
            <input type="text" id="ws-printer-prefix" data-setting="workshop.printer_3d.entity_prefix" placeholder="octoprint" class="setting-input">
            <span class="setting-help">Entity-Prefix des 3D-Druckers in HA (z.B. 'octoprint', 'bambu').</span>
        </div>
    </div>

    <div class="setting-group">
        <h3>Roboterarm (Waveshare RoArm-M3-Pro)</h3>
        <div class="setting-row">
            <label>Arm aktiviert</label>
            <label class="toggle">
                <input type="checkbox" id="ws-arm" data-setting="workshop.robot_arm.enabled">
                <span class="slider"></span>
            </label>
        </div>
        <div class="setting-row">
            <label>Arm URL</label>
            <input type="text" id="ws-arm-url" data-setting="workshop.robot_arm.url" placeholder="http://192.168.1.100" class="setting-input">
            <span class="setting-help">HTTP-Adresse des RoArm-M3-Pro Controllers.</span>
        </div>
        <div class="setting-row">
            <label>Max. Geschwindigkeit (%)</label>
            <input type="number" id="ws-arm-speed" data-setting="workshop.robot_arm.max_speed" min="10" max="100" value="80" class="setting-input" style="width:80px">
            <span class="setting-help">Maximale Arm-Geschwindigkeit (Sicherheit). 80% empfohlen.</span>
        </div>
    </div>

    <div class="setting-group">
        <h3>MQTT</h3>
        <div class="setting-row">
            <label>MQTT aktiviert</label>
            <label class="toggle">
                <input type="checkbox" id="ws-mqtt" data-setting="workshop.mqtt.enabled">
                <span class="slider"></span>
            </label>
        </div>
        <div class="setting-row">
            <label>MQTT Broker</label>
            <input type="text" id="ws-mqtt-broker" data-setting="workshop.mqtt.broker" placeholder="192.168.1.1" class="setting-input">
        </div>
        <div class="setting-row">
            <label>MQTT Topic Prefix</label>
            <input type="text" id="ws-mqtt-topic" data-setting="workshop.mqtt.topic_prefix" placeholder="workshop/" class="setting-input">
        </div>
    </div>

    <div class="setting-actions">
        <a href="/workshop/" target="_blank" class="btn btn-accent">Workshop-HUD oeffnen &#8599;</a>
    </div>
</div>
```

---

## 10. static/ui/app.js — EDIT (+15 Zeilen)

### A) collectSettings() erweitern (Workshop-Settings einsammeln)

Die bestehende `collectSettings()` Funktion liest alle `data-setting`-Attribute automatisch.
Falls `collectSettings()` Settings per ID manuell sammelt, diese Zeilen hinzufuegen:

```javascript
// Workshop-Settings
settings.workshop = {
    enabled: document.getElementById('ws-enabled')?.checked ?? false,
    workshop_room: document.getElementById('ws-room')?.value || 'werkstatt',
    auto_safety_check: document.getElementById('ws-safety')?.checked ?? true,
    proactive_suggestions: document.getElementById('ws-proactive')?.checked ?? true,
    printer_3d: {
        enabled: document.getElementById('ws-printer')?.checked ?? false,
        entity_prefix: document.getElementById('ws-printer-prefix')?.value || 'octoprint',
    },
    robot_arm: {
        enabled: document.getElementById('ws-arm')?.checked ?? false,
        url: document.getElementById('ws-arm-url')?.value || '',
        max_speed: parseInt(document.getElementById('ws-arm-speed')?.value || '80'),
    },
    mqtt: {
        enabled: document.getElementById('ws-mqtt')?.checked ?? false,
        broker: document.getElementById('ws-mqtt-broker')?.value || '',
        topic_prefix: document.getElementById('ws-mqtt-topic')?.value || 'workshop/',
    },
};
```

### B) loadSettings() erweitern (Settings in UI laden)

```javascript
// Workshop-Settings laden
if (data.workshop) {
    document.getElementById('ws-enabled').checked = data.workshop.enabled ?? false;
    document.getElementById('ws-room').value = data.workshop.workshop_room || 'werkstatt';
    document.getElementById('ws-safety').checked = data.workshop.auto_safety_check ?? true;
    document.getElementById('ws-proactive').checked = data.workshop.proactive_suggestions ?? true;
    if (data.workshop.printer_3d) {
        document.getElementById('ws-printer').checked = data.workshop.printer_3d.enabled ?? false;
        document.getElementById('ws-printer-prefix').value = data.workshop.printer_3d.entity_prefix || 'octoprint';
    }
    if (data.workshop.robot_arm) {
        document.getElementById('ws-arm').checked = data.workshop.robot_arm.enabled ?? false;
        document.getElementById('ws-arm-url').value = data.workshop.robot_arm.url || '';
        document.getElementById('ws-arm-speed').value = data.workshop.robot_arm.max_speed || 80;
    }
    if (data.workshop.mqtt) {
        document.getElementById('ws-mqtt').checked = data.workshop.mqtt.enabled ?? false;
        document.getElementById('ws-mqtt-broker').value = data.workshop.mqtt.broker || '';
        document.getElementById('ws-mqtt-topic').value = data.workshop.mqtt.topic_prefix || 'workshop/';
    }
}
```

---

## 11. websocket.py — EDIT (+25 Zeilen)

### emit_workshop() Funktion (nach `emit_proactive`, ca. Zeile 149)

```python
async def emit_workshop(
    sub_event: str,
    data: Optional[dict] = None,
) -> None:
    """Workshop-Event an alle Clients.

    Sub-Events:
      - workshop.step       — Schritt gewechselt (step_number, total, title)
      - workshop.diagnosis  — Diagnose abgeschlossen (project, diagnosis)
      - workshop.file_created — Neue Datei erstellt (project_id, filename)
      - workshop.printer    — Drucker-Status Update (progress, state, temps)
      - workshop.environment — Werkstatt-Sensordaten (temperatur, feuchtigkeit, co2)
      - workshop.timer      — Timer abgelaufen (message)
      - workshop.arm        — Arm-Status (position, gripper)
      - workshop.project    — Projekt-Update (project_id, status)
    """
    await ws_manager.broadcast(f"workshop.{sub_event}", data or {})
```

### Import in brain.py Zeile 80 erweitern

```python
from .websocket import emit_thinking, emit_speaking, emit_action, emit_proactive, emit_workshop
```

---

## 12. settings.yaml — EDIT (+35 Zeilen)

### Workshop Config-Sektion (am Ende der Datei anfuegen)

```yaml
workshop:
  enabled: false
  workshop_room: werkstatt
  auto_safety_check: true
  proactive_suggestions: true
  default_category: maker
  file_storage_path: /app/data/workshop/files
  library_path: /app/data/workshop/library
  max_file_size_mb: 50
  printer_3d:
    enabled: false
    entity_prefix: octoprint
    auto_monitor: true
    monitor_interval_seconds: 30
  robot_arm:
    enabled: false
    url: ''
    max_speed: 80
    home_on_idle: true
    idle_timeout_minutes: 5
  mqtt:
    enabled: false
    broker: ''
    port: 1883
    topic_prefix: workshop/
    username: ''
    password: ''
  templates:
    - esp_sensor
    - led_strip
    - 3d_enclosure
    - furniture
    - repair_standard
```

### deep_keywords erweitern (in `models.deep_keywords`, Zeile ~113)

```yaml
deep_keywords:
  # ... bestehende Keywords ...
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

## Zusammenfassung: Implementierungs-Reihenfolge

1. **`repair_planner.py`** — Hauptmodul NEU erstellen (~1500 Zeilen)
2. **`workshop_generator.py`** — Generator NEU erstellen (~800 Zeilen)
3. **`workshop_library.py`** — Library NEU erstellen (~250 Zeilen)
4. **`settings.yaml`** — Workshop-Sektion + deep_keywords erweitern
5. **`function_calling.py`** — Tool-Definition + Handler + Whitelist
6. **`brain.py`** — Import + Init + Intent-Interception + Callback
7. **`personality.py`** — Ingenieur-Modus in build_system_prompt
8. **`websocket.py`** — emit_workshop() Funktion
9. **`main.py`** — SPA-Route + API-Endpoints
10. **`static/workshop/index.html`** — Workshop-HUD (komplett)
11. **`static/ui/index.html`** — Settings-Tab
12. **`static/ui/app.js`** — Settings collect/load

### Abhaengigkeiten

```
settings.yaml (Config-Werte)
    ↓
repair_planner.py ← workshop_generator.py ← workshop_library.py
    ↓                    ↓
brain.py (Import + Init + Intent)
    ↓
function_calling.py (Tool + Handler)
    ↓
personality.py (Ingenieur-Prompt)
    ↓
websocket.py (emit_workshop)
    ↓
main.py (Routes + API)
    ↓
workshop/index.html (Frontend)
    ↓
ui/index.html + app.js (Settings-Tab)
```

### pip-Abhaengigkeiten (requirements.txt)

```
qrcode[pil]>=7.0    # QR-Label Generator
aiohttp>=3.9        # Roboterarm HTTP-Steuerung (falls nicht schon vorhanden)
```

`PyMuPDF` (`fitz`) ist bereits via `knowledge_base.py` installiert.
