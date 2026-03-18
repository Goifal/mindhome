"""
MindHome Workshop-Modus — Werkstatt-Ingenieur-Assistent.

Features:
- Projekt-Management (CRUD, Multi-Projekt, Templates)
- LLM-Diagnose, Simulation, Troubleshooting
- Schritt-basierte Navigation per Sprache
- Werkstatt-Inventar, Budget, Journal, Snippets
- 3D-Drucker Steuerung (via HA)
- Roboterarm Steuerung (Stub)
- Werkzeug-Verleih, Wartungs-Tracking
- Geräte-Management via Home Assistant
"""

import asyncio
import json
import logging
import re
import time
import uuid as uuid_mod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class RepairStep:
    """Ein einzelner Reparatur-/Bau-Schritt."""
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
    """Eine aktive Werkstatt-Session mit Projekt und Schritten."""
    project_id: str
    title: str
    category: str
    steps: list[RepairStep] = field(default_factory=list)
    current_step: int = 0
    started_at: str = ""
    timer_start: float = 0
    timer_total: float = 0

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def is_finished(self) -> bool:
        return self.current_step >= self.total_steps

    def get_current_step(self) -> Optional[RepairStep]:
        if 0 <= self.current_step < self.total_steps:
            return self.steps[self.current_step]
        return None


# ============================================================
# Navigation-Keywords (Pattern: cooking_assistant.py)
# ============================================================

NAV_NEXT = {"weiter", "nächster schritt", "nächster schritt", "next",
            "und dann", "weiter gehts"}
NAV_PREV = {"zurück", "zurück", "vorheriger schritt", "back",
            "einen zurück", "einen zurück"}
NAV_REPEAT = {"nochmal", "wiederhole", "repeat", "wie war das"}
NAV_STATUS = {"status", "wo bin ich", "übersicht", "übersicht",
              "wo stehe ich"}
NAV_PARTS = {"was brauche ich", "teile", "teileliste", "material"}
NAV_TOOLS = {"welches werkzeug", "werkzeugliste",
             "was brauch ich an werkzeug"}
NAV_SHOP = {"bestell das", "einkaufsliste", "kaufen", "shopping"}
NAV_SAVE = {"merk dir das", "speicher das", "merken"}
NAV_CODE = {"zeig den code", "programmier", "code generieren", "firmware"}
NAV_3D = {"3d modell", "gehaeuse", "openscad"}
NAV_CALC = {"berechne", "welcher widerstand", "rechne", "umrechnen",
            "konvertiere"}
NAV_SCAN = {"scan das", "schau dir an", "was ist das",
            "analysiere das teil"}
NAV_SIM = {"simuliere", "teste das design", "haelt das", "hält das"}
NAV_PRINT = {"druck", "drucke", "print", "3d druck starten"}
NAV_ARM = {"gib mir", "halt das", "greif", "arm", "robot"}
NAV_TIMER = {"erinnere mich", "timer", "wecker"}
NAV_JOURNAL = {"was hab ich heute", "journal", "tagebuch"}
NAV_STOP = {"pause", "fertig", "stop", "beenden"}
EMERGENCY_STOP = {"stopp"}  # Hoechste Priorität für Arm

# Intent-Erkennung
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

ACTIVATION_ON = {"werkstatt modus an", "werkstatt aktivieren",
                 "workshop an", "werkstattmodus an"}
ACTIVATION_OFF = {"werkstatt modus aus", "werkstatt deaktivieren",
                  "workshop aus", "werkstattmodus aus"}

# Templates
TEMPLATES = {
    "esp_sensor": {
        "title": "ESP32 Sensor-Projekt", "category": "maker",
        "parts": [{"name": "ESP32 DevKit", "quantity": 1}],
        "tools": ["Loetkolben", "Multimeter"],
    },
    "led_strip": {
        "title": "LED-Strip Steuerung", "category": "maker",
        "parts": [
            {"name": "ESP32", "quantity": 1},
            {"name": "WS2812 Strip", "quantity": 1},
        ],
    },
    "3d_enclosure": {"title": "3D-Druck Gehaeuse", "category": "maker"},
    "furniture": {"title": "Moebelbau Projekt", "category": "bau"},
    "repair_standard": {"title": "Standard-Reparatur", "category": "reparatur"},
}


# ============================================================
# LLM-Prompts
# ============================================================

DIAGNOSIS_PROMPT = """Du bist ein Werkstatt-Ingenieur. Analysiere das Problem und antworte NUR als JSON:
{{
  "diagnosis": "Was ist das Problem",
  "difficulty": 3,
  "tools": ["Werkzeug1", "Werkzeug2"],
  "parts": [{{"name": "Teil", "quantity": 1, "estimated_cost": 5.0}}],
  "safety_warnings": ["Warnung1"],
  "steps": [{{"title": "Schritt", "description": "Beschreibung", "tools": [], "estimated_minutes": 10}}],
  "estimated_time": "1-2 Stunden",
  "estimated_cost": "10-20 Euro"
}}
Kontext: {context}
Werkstatt-Sensoren: {environment}"""


# ============================================================
# Hauptklasse
# ============================================================

class RepairPlanner:
    """Werkstatt-Assistent: Projekte, Diagnose, Navigation, Hardware."""

    REDIS_SESSION_KEY = "mha:repair:session"
    REDIS_SESSION_TTL = 24 * 3600  # 24h

    def __init__(self, ollama_client, ha_client):
        self.ollama = ollama_client
        self.ha = ha_client
        self.redis = None
        self.semantic_memory = None
        self.generator = None       # WorkshopGenerator (Phase 2)
        self.model_router = None    # ModelRouter
        self._session: Optional[RepairSession] = None
        self._notify_callback = None
        self.camera_manager = None   # CameraManager (set by brain)
        self.ocr_engine = None       # OCREngine (set by brain)
        self._background_tasks: set = set()  # prevent GC of fire-and-forget tasks

        # Config
        ws_cfg = yaml_config.get("workshop", {})
        self.enabled = ws_cfg.get("enabled", False)
        self.workshop_room = ws_cfg.get("workshop_room", "werkstatt")
        self.auto_safety_check = ws_cfg.get("auto_safety_check", True)
        self.proactive_suggestions = ws_cfg.get("proactive_suggestions", True)

    async def initialize(self, redis_client):
        """Initialisiert mit Redis und lädt ggf. eine gespeicherte Session."""
        self.redis = redis_client
        if self.redis:
            await self._restore_session()
        logger.info("RepairPlanner initialisiert (enabled=%s)", self.enabled)

    def set_generator(self, generator):
        """Verknuepft den WorkshopGenerator."""
        self.generator = generator

    def set_model_router(self, router):
        """Setzt den ModelRouter für LLM-Tier-Auswahl."""
        self.model_router = router

    def set_notify_callback(self, callback):
        """Setzt den Callback für Timer-Benachrichtigungen."""
        self._notify_callback = callback

    # ── Session Persistence ──────────────────────────────────

    async def _save_session(self):
        """Speichert die aktive Session in Redis."""
        if not self.redis or not self._session:
            return
        data = {
            "project_id": self._session.project_id,
            "title": self._session.title,
            "category": self._session.category,
            "steps": [asdict(s) for s in self._session.steps],
            "current_step": self._session.current_step,
            "started_at": self._session.started_at,
            "timer_start": self._session.timer_start,
            "timer_total": self._session.timer_total,
        }
        await self.redis.setex(
            self.REDIS_SESSION_KEY,
            self.REDIS_SESSION_TTL,
            json.dumps(data),
        )

    async def _restore_session(self):
        """Lädt eine gespeicherte Session aus Redis."""
        if not self.redis:
            return
        raw = await self.redis.get(self.REDIS_SESSION_KEY)
        if not raw:
            return
        try:
            data = json.loads(raw)
            steps = [RepairStep(**s) for s in data.get("steps", [])]
            self._session = RepairSession(
                project_id=data["project_id"],
                title=data["title"],
                category=data.get("category", "maker"),
                steps=steps,
                current_step=data.get("current_step", 0),
                started_at=data.get("started_at", ""),
                timer_start=data.get("timer_start", 0),
                timer_total=data.get("timer_total", 0),
            )
            logger.info("Workshop-Session wiederhergestellt: %s (Schritt %d/%d)",
                        self._session.title, self._session.current_step + 1,
                        self._session.total_steps)
        except Exception as e:
            logger.warning("Workshop-Session Restore fehlgeschlagen: %s", e)
            self._session = None

    async def _clear_session(self):
        """Loescht die aktive Session."""
        self._session = None
        if self.redis:
            await self.redis.delete(self.REDIS_SESSION_KEY)

    # ── Projekt-CRUD (Redis Pattern: inventory.py) ───────────

    async def create_project(self, title, description="", category="maker",
                             priority="normal") -> dict:
        """Erstellt ein neues Werkstatt-Projekt."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        project_id = str(uuid_mod.uuid4())[:12]  # S3: Mehr Entropy (16^12 statt 16^8)
        slug = (title.lower().replace(" ", "-")
                .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue"))
        project = {
            "id": project_id,
            "title": title,
            "description": description,
            "category": category,   # reparatur|bau|maker|erfindung|renovierung
            "priority": priority,   # niedrig|normal|hoch|dringend
            "status": "erstellt",   # erstellt|diagnose|teile_bestellt|in_arbeit|pausiert|fertig
            "slug": slug,
            "created": datetime.now().isoformat(),
            "parts": "[]",
            "tools": "[]",
            "notes": "[]",
            "budget": "0",
            "expenses": "[]",
            "device_entity": "",
        }
        await self.redis.hset(f"mha:repair:project:{project_id}", mapping=project)
        await self.redis.sadd("mha:repair:projects:all", project_id)
        await self.redis.sadd("mha:repair:projects:status:erstellt", project_id)
        logger.info("Workshop-Projekt erstellt: %s (%s)", title, project_id)
        return project

    async def get_project(self, project_id) -> Optional[dict]:
        """Holt ein Projekt aus Redis."""
        if not self.redis:
            return None
        data = await self.redis.hgetall(f"mha:repair:project:{project_id}")
        if not data:
            return None
        # Redis returns bytes – decode to str
        data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
        # JSON-Felder parsen
        for key in ("parts", "tools", "notes", "expenses"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = json.loads(data[key])
                except (json.JSONDecodeError, TypeError):
                    data[key] = []
        return data

    async def list_projects(self, status_filter=None,
                            category_filter=None) -> list:
        """Listet alle Projekte, optional gefiltert."""
        if not self.redis:
            return []
        if status_filter:
            ids = await self.redis.smembers(
                f"mha:repair:projects:status:{status_filter}")
        else:
            ids = await self.redis.smembers("mha:repair:projects:all")
        if not ids:
            return []
        decoded_ids = [
            pid.decode() if isinstance(pid, bytes) else pid
            for pid in ids
        ]
        pipe = self.redis.pipeline()
        for pid in decoded_ids:
            pipe.hgetall(f"mha:repair:project:{pid}")
        results = await pipe.execute()
        projects = []
        for data in results:
            if not data:
                continue
            # Redis returns bytes – decode to str
            data = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in data.items()
            }
            # JSON-Felder parsen
            for key in ("parts", "tools", "notes", "expenses"):
                if key in data and isinstance(data[key], str):
                    try:
                        data[key] = json.loads(data[key])
                    except (json.JSONDecodeError, TypeError):
                        data[key] = []
            if not category_filter or data.get("category") == category_filter:
                projects.append(data)
        return projects

    async def update_project(self, project_id, **kwargs) -> Optional[dict]:
        """Aktualisiert ein Projekt."""
        if not self.redis:
            return None
        # Status-Change: alte Status-Set entfernen, neue hinzufuegen
        if "status" in kwargs:
            old = await self.redis.hget(
                f"mha:repair:project:{project_id}", "status")
            if old:
                old = old.decode() if isinstance(old, bytes) else old
                await self.redis.srem(
                    f"mha:repair:projects:status:{old}", project_id)
            await self.redis.sadd(
                f"mha:repair:projects:status:{kwargs['status']}", project_id)
        for k, v in kwargs.items():
            if isinstance(v, (list, dict)):
                v = json.dumps(v)
            await self.redis.hset(
                f"mha:repair:project:{project_id}", k, str(v))
        return await self.get_project(project_id)

    async def complete_project(self, project_id, notes="") -> Optional[dict]:
        """Schliesst ein Projekt ab."""
        await self.update_project(
            project_id, status="fertig",
            completed=datetime.now().isoformat())
        if notes:
            await self.add_project_note(project_id, notes)
        # Auto-Dokumentation generieren
        if self.generator:
            try:
                model = (self.model_router.model_smart
                         if self.model_router else None)
                await self.generator.generate_documentation(
                    project_id, model=model)
            except Exception as e:
                logger.warning("Auto-Doku fehlgeschlagen: %s", e)
        return await self.get_project(project_id)

    async def add_project_note(self, project_id, note) -> dict:
        """Fuegt eine Notiz zum Projekt hinzu."""
        project = await self.get_project(project_id)
        if not project:
            return {"status": "error", "message": "Projekt nicht gefunden"}
        notes = project.get("notes", [])
        notes.append({"text": note, "timestamp": datetime.now().isoformat()})
        await self.redis.hset(
            f"mha:repair:project:{project_id}", "notes", json.dumps(notes))
        return {"status": "ok", "note_count": len(notes)}

    async def add_part(self, project_id, name, quantity=1,
                       estimated_cost=0, source="") -> dict:
        """Fuegt ein Bauteil zum Projekt hinzu."""
        project = await self.get_project(project_id)
        if not project:
            return {"status": "error", "message": "Projekt nicht gefunden"}
        parts = project.get("parts", [])
        parts.append({
            "name": name, "quantity": quantity,
            "cost": estimated_cost, "source": source,
            "available": False,
        })
        await self.redis.hset(
            f"mha:repair:project:{project_id}", "parts", json.dumps(parts))
        return {"status": "ok", "part": name}

    async def add_missing_to_shopping(self, project_id) -> dict:
        """Gibt fehlende Teile zurück — User muss bestätigen."""
        project = await self.get_project(project_id)
        if not project:
            return {"status": "error", "message": "Projekt nicht gefunden"}
        missing = [p for p in project.get("parts", [])
                   if not p.get("available")]
        if not missing:
            return {"status": "ok", "message": "Alle Teile vorhanden"}
        return {
            "status": "confirm_needed", "missing_parts": missing,
            "message": (f"{len(missing)} Teile fehlen. "
                        "Soll ich sie auf die Einkaufsliste setzen?"),
        }

    # ── LLM-Diagnose ────────────────────────────────────────

    async def diagnose_problem(self, text, person="",
                               model=None) -> str:
        """Analysiert ein Problem und erstellt Diagnose + Projekt."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar für Diagnose."

        # Semantic Memory durchsuchen
        context = ""
        if self.semantic_memory:
            try:
                results = await self.semantic_memory.search(text, limit=3)
                if results:
                    context = "\n".join(
                        r.get("content", "") for r in results)
            except Exception as e:
                logger.debug("Semantic memory search fallback failed: %s", e)

        # Werkstatt-Umgebung holen
        environment = await self.get_workshop_environment()

        prompt = DIAGNOSIS_PROMPT.format(
            context=context or "Kein Vorwissen",
            environment=json.dumps(environment) if environment else "Keine Sensoren")
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

        try:
            response = await self.ollama.chat(
                model=model, messages=messages,
                temperature=0.3, max_tokens=2048)
        except Exception as e:
            logger.error("Diagnose LLM-Fehler: %s", e)
            return f"Diagnose fehlgeschlagen: {e}"

        # JSON parsen und Projekt erstellen
        try:
            _content = response.get("message", {}).get("content", "")
            data = json.loads(_content)
            project = await self.create_project(
                title=data.get("diagnosis", text)[:60],
                description=text, category="reparatur",
                priority="hoch" if data.get("difficulty", 3) >= 4 else "normal",
            )
            # Session starten
            steps = []
            for i, s in enumerate(data.get("steps", [])):
                steps.append(RepairStep(
                    number=i + 1,
                    title=s.get("title", f"Schritt {i + 1}"),
                    description=s.get("description", ""),
                    tools=s.get("tools", []),
                    estimated_minutes=s.get("estimated_minutes", 0),
                ))
            self._session = RepairSession(
                project_id=project["id"],
                title=project["title"],
                category="reparatur",
                steps=steps,
                started_at=datetime.now().isoformat(),
            )
            await self._save_session()

            # WebSocket Event
            try:
                from .websocket import emit_workshop
                await emit_workshop("diagnosis", {
                    "project": project, "diagnosis": data,
                })
            except Exception as e:
                logger.debug("Diagnosis websocket emit failed: %s", e)

            return self._format_diagnosis(data)
        except (json.JSONDecodeError, TypeError, KeyError):
            return _content  # LLM hat kein JSON generiert

    def _format_diagnosis(self, data: dict) -> str:
        """Formatiert eine Diagnose für die Sprachausgabe."""
        parts = [f"Diagnose: {data.get('diagnosis', 'Unbekannt')}"]
        if data.get("difficulty"):
            parts.append(f"Schwierigkeit: {data['difficulty']}/5")
        if data.get("estimated_time"):
            parts.append(f"Geschaetzte Zeit: {data['estimated_time']}")
        if data.get("estimated_cost"):
            parts.append(f"Geschaetzte Kosten: {data['estimated_cost']}")
        if data.get("safety_warnings"):
            parts.append("Sicherheit: " + ", ".join(data["safety_warnings"]))
        steps = data.get("steps", [])
        if steps:
            parts.append(f"\n{len(steps)} Schritte erstellt. "
                         "Sage 'weiter' um zu beginnen.")
        return "\n".join(parts)

    # ── Simulation ───────────────────────────────────────────

    async def simulate_design(self, project_id, question,
                              model=None) -> str:
        """Simuliert ein Design und beantwortet Fragen dazu."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar."
        project = await self.get_project(project_id)
        if not project:
            return "Projekt nicht gefunden."

        files = []
        file_contents = {}
        if self.generator:
            files = await self.generator.list_files(project_id)
            for f in files[:5]:
                content = await self.generator.read_file(
                    project_id, f["name"])
                if content:
                    file_contents[f["name"]] = content[:2000]

        prompt = f"""Analysiere dieses Projekt und beantworte die Frage.
Projekt: {project['title']} ({project['category']})
Teile: {json.dumps(project.get('parts', []))}
Dateien: {json.dumps(file_contents)}
Frage: {question}

Analysiere: Machbarkeit, Schwachstellen, Belastungsgrenzen, Batterie-Laufzeit,
thermische Aspekte, Verbesserungsvorschläge. Gib Konfidenz-Level an."""
        messages = [{"role": "system", "content": prompt}]
        _resp = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.4, max_tokens=2048)
        return _resp.get("message", {}).get("content", "")

    # ── Troubleshooting ──────────────────────────────────────

    async def troubleshoot(self, project_id, symptom,
                           model=None) -> str:
        """Systematisches Troubleshooting."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar."
        project = await self.get_project(project_id)
        if not project:
            return "Projekt nicht gefunden."

        prompt = f"""Systematischer Debug-Workflow für: {symptom}
Projekt: {project['title']}
Teile: {json.dumps(project.get('parts', []))}
1. Symptom analysieren
2. Wahrscheinlichste Ursachen (sortiert nach Wahrscheinlichkeit)
3. Pruefschritte mit konkreten Anweisungen ("Miss Spannung an Pin X")
4. Erwartete Ergebnisse pro Pruefschritt
Antworte strukturiert als Diagnosebaum."""
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": symptom},
        ]
        _resp = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.3, max_tokens=2048)
        return _resp.get("message", {}).get("content", "")

    # ── Proaktive Verbesserungen ─────────────────────────────

    async def suggest_improvements(self, project_id,
                                   model=None) -> str:
        """Schlaegt Verbesserungen für ein Projekt vor."""
        model = model or (self.model_router.model_smart
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar."
        project = await self.get_project(project_id)
        if not project:
            return "Projekt nicht gefunden."

        prompt = f"""Analysiere das Projekt und schlage Verbesserungen vor.
Projekt: {project['title']} ({project['category']})
Teile: {json.dumps(project.get('parts', []))}
Schlage konkrete Optimierungen vor (Effizienz, Kosten, Sicherheit, Zuverlaessigkeit)."""
        messages = [{"role": "system", "content": prompt}]
        _resp = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.5, max_tokens=1024)
        return _resp.get("message", {}).get("content", "")

    # ── Komponenten-Vergleich ────────────────────────────────

    async def compare_components(self, comp_a, comp_b,
                                 use_case="", model=None) -> str:
        """Vergleicht zwei Komponenten."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar."

        prompt = f"""Vergleiche {comp_a} vs {comp_b} für: {use_case or 'allgemein'}
Vergleiche: Features, Preis, Stromverbrauch, Pins, Verfügbarkeit.
Gib eine klare Empfehlung mit Begruendung."""
        messages = [{"role": "system", "content": prompt}]
        _resp = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.3, max_tokens=1024)
        return _resp.get("message", {}).get("content", "")

    # ── Error-Log Analyse ────────────────────────────────────

    async def analyze_error_log(self, project_id, log_text,
                                model=None) -> str:
        """Analysiert einen Error-Log/Serial-Output."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar."
        project = await self.get_project(project_id)
        if not project:
            return "Projekt nicht gefunden."

        files = []
        if self.generator:
            files = await self.generator.list_files(project_id)

        prompt = f"""Analysiere diesen Error-Log/Serial-Output.
Projekt: {project['title']}
Projekt-Dateien: {[f['name'] for f in files]}
Error-Log:
{log_text[:3000]}
Erklaere den Fehler und schlage einen konkreten Fix vor."""
        messages = [{"role": "system", "content": prompt}]
        _resp = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.2, max_tokens=1024)
        return _resp.get("message", {}).get("content", "")

    # ── Mess-Assistent ───────────────────────────────────────

    async def evaluate_measurement(self, project_id, measurement_text,
                                   model=None) -> str:
        """Bewertet einen Messwert im Projekt-Kontext."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar."
        project = await self.get_project(project_id)
        if not project:
            return "Projekt nicht gefunden."

        current_step = "unbekannt"
        if self._session:
            current_step = str(self._session.current_step + 1)

        prompt = f"""Der User hat einen Messwert diktiert. Bewerte ihn im Projekt-Kontext.
Projekt: {project['title']}
Schritt: {current_step}
Messwert: {measurement_text}
Bewerte: Ist der Wert im erwarteten Bereich? Was bedeutet er? Nächster Schritt?"""
        messages = [{"role": "system", "content": prompt}]
        _resp = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.3, max_tokens=512)
        return _resp.get("message", {}).get("content", "")

    # ── Kalibrierung ─────────────────────────────────────────

    async def calibration_guide(self, device_type, model=None) -> str:
        """Erstellt eine Kalibrierungsanleitung."""
        model = model or (self.model_router.model_smart
                          if self.model_router else None)
        if not model:
            return "Kein LLM-Modell verfügbar."

        prompt = f"""Erstelle eine Schritt-für-Schritt Kalibrierungsanleitung für: {device_type}
Gib konkrete Werte, Pruefschritte und erwartete Ergebnisse an."""
        messages = [{"role": "system", "content": prompt}]
        _resp = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.3, max_tokens=1024)
        return _resp.get("message", {}).get("content", "")

    # ── Werkstatt-Umgebung ───────────────────────────────────

    async def get_workshop_environment(self) -> dict:
        """Holt Werkstatt-Sensordaten von Home Assistant."""
        room = self.workshop_room
        try:
            states = await self.ha.get_states()
            env = {}
            for state in states:
                eid = state.get("entity_id", "")
                if room.lower() in eid.lower():
                    if "temperature" in eid:
                        env["temperatur"] = state.get("state")
                    elif "humidity" in eid:
                        env["feuchtigkeit"] = state.get("state")
                    elif "co2" in eid:
                        env["co2"] = state.get("state")
                    elif "illuminance" in eid:
                        env["licht"] = state.get("state")
            return env
        except Exception as e:
            logger.warning("Workshop environment query failed: %s", e)
            return {}

    # ── Sicherheits-Checkliste ───────────────────────────────

    async def generate_safety_checklist(self, project_id) -> str:
        """Generiert eine Sicherheits-Checkliste (kein LLM)."""
        project = await self.get_project(project_id)
        if not project:
            return "Projekt nicht gefunden."
        tools = project.get("tools", [])
        category = project.get("category", "")

        checklist = ["Arbeitsflaeche frei und sauber"]
        if any(t in str(tools) for t in ["loetkolben", "loeten", "loet"]):
            checklist.extend([
                "Lüftung einschalten",
                "Loetkolben-Ablage prüfen",
                "Loetzinn bereit",
            ])
        if any(t in str(tools) for t in ["bohr", "saeg", "flex", "schlei"]):
            checklist.extend([
                "Schutzbrille aufsetzen",
                "Gehoerschutz bei Bedarf",
            ])
        if category == "reparatur":
            checklist.append("Strom/Wasser abstellen wenn nötig")
        checklist.append("Erste-Hilfe-Kasten in Reichweite")

        return ("Sicherheits-Checkliste:\n"
                + "\n".join(f"- {c}" for c in checklist))

    # ── Navigation (Pattern: cooking_assistant.py) ───────────

    def is_repair_navigation(self, text: str) -> bool:
        """Erkennt ob der User durch eine aktive Session navigiert."""
        if not self._session:
            return False
        text_lower = text.lower().strip()
        all_nav = (NAV_NEXT | NAV_PREV | NAV_REPEAT | NAV_STATUS | NAV_PARTS
                   | NAV_TOOLS | NAV_SHOP | NAV_SAVE | NAV_CODE | NAV_3D
                   | NAV_CALC | NAV_SCAN | NAV_SIM | NAV_PRINT | NAV_ARM
                   | NAV_TIMER | NAV_JOURNAL | NAV_STOP | EMERGENCY_STOP)
        return any(kw in text_lower for kw in all_nav)

    async def handle_navigation(self, text: str) -> str:
        """Verarbeitet einen Navigations-Befehl."""
        text_lower = text.lower().strip()

        # Emergency Stop hat IMMER Vorrang
        if any(kw in text_lower for kw in EMERGENCY_STOP):
            return await self._emergency_stop()
        if any(kw in text_lower for kw in NAV_NEXT):
            return await self._next_step()
        if any(kw in text_lower for kw in NAV_PREV):
            return await self._prev_step()
        if any(kw in text_lower for kw in NAV_REPEAT):
            return await self._repeat_step()
        if any(kw in text_lower for kw in NAV_STATUS):
            return self._get_status()
        if any(kw in text_lower for kw in NAV_PARTS):
            return self._get_parts()
        if any(kw in text_lower for kw in NAV_TOOLS):
            return self._get_tools()
        if any(kw in text_lower for kw in NAV_STOP):
            return await self._stop_session()

        return "Ich habe das nicht verstanden. Sage 'status' für eine Übersicht."

    async def _next_step(self) -> str:
        """Geht zum nächsten Schritt."""
        if not self._session:
            return "Keine aktive Session."
        if self._session.current_step >= self._session.total_steps - 1:
            return ("Das war der letzte Schritt! "
                    "Sage 'fertig' um das Projekt abzuschliessen.")
        self._session.current_step += 1
        await self._save_session()

        step = self._session.get_current_step()
        try:
            from .websocket import emit_workshop
            await emit_workshop("step", {
                "step_number": step.number,
                "total": self._session.total_steps,
                "title": step.title,
            })
        except Exception as e:
            logger.debug("Step websocket emit failed: %s", e)

        return self._format_step(step)

    async def _prev_step(self) -> str:
        """Geht zum vorherigen Schritt."""
        if not self._session:
            return "Keine aktive Session."
        if self._session.current_step <= 0:
            return "Du bist bereits beim ersten Schritt."
        self._session.current_step -= 1
        await self._save_session()
        step = self._session.get_current_step()
        return self._format_step(step)

    async def _repeat_step(self) -> str:
        """Wiederholt den aktuellen Schritt."""
        if not self._session:
            return "Keine aktive Session."
        step = self._session.get_current_step()
        if not step:
            return "Kein aktueller Schritt."
        return self._format_step(step)

    def _get_status(self) -> str:
        """Gibt den aktuellen Status zurück."""
        if not self._session:
            return "Keine aktive Session."
        s = self._session
        step = s.get_current_step()
        return (f"Projekt: {s.title}\n"
                f"Schritt {s.current_step + 1} von {s.total_steps}: "
                f"{step.title if step else 'Fertig'}\n"
                f"Sage 'weiter' oder 'zurück' zum Navigieren.")

    def _get_parts(self) -> str:
        """Listet die benötigten Teile."""
        if not self._session:
            return "Keine aktive Session."
        step = self._session.get_current_step()
        if not step or not step.parts:
            return "Für diesen Schritt werden keine speziellen Teile benötigt."
        return "Benötigte Teile:\n" + "\n".join(
            f"- {p}" for p in step.parts)

    def _get_tools(self) -> str:
        """Listet das benötigte Werkzeug."""
        if not self._session:
            return "Keine aktive Session."
        step = self._session.get_current_step()
        if not step or not step.tools:
            return "Für diesen Schritt wird kein spezielles Werkzeug benötigt."
        return "Benötigtes Werkzeug:\n" + "\n".join(
            f"- {t}" for t in step.tools)

    async def _stop_session(self) -> str:
        """Beendet die aktive Session."""
        if not self._session:
            return "Keine aktive Session."
        project_id = self._session.project_id
        title = self._session.title
        await self._clear_session()
        return f"Session für '{title}' beendet. Projekt bleibt gespeichert."

    def _format_step(self, step: RepairStep) -> str:
        """Formatiert einen Schritt für die Sprachausgabe."""
        parts = [
            f"Schritt {step.number} von {self._session.total_steps}: "
            f"{step.title}",
        ]
        parts.append(step.description)
        if step.tools:
            parts.append("Werkzeug: " + ", ".join(step.tools))
        if step.estimated_minutes:
            parts.append(f"Geschaetzte Dauer: {step.estimated_minutes} Minuten")
        return "\n".join(parts)

    # ── Objekt-Scanner ───────────────────────────────────────

    async def scan_object(self, image_data=None, camera_name="",
                          description="") -> dict:
        """Objekterkennung via CameraManager + Vision-LLM."""
        ws_cfg = yaml_config.get("workshop", {})
        # Fallback: Standard-Kamera aus Workshop-Config
        if not camera_name and not image_data:
            camera_name = ws_cfg.get("scan_camera", "")

        # Fall 1: Kamera-Name → CameraManager nutzen
        if camera_name and self.camera_manager:
            result = await self.camera_manager.get_camera_view(
                camera_name=camera_name)
            if not result.get("success"):
                return {"status": "error",
                        "message": result.get("message", "Kamera nicht verfuegbar")}
            scan_result = {"status": "ok", "analysis": result.get("message", "")}
            # Auto-OCR: Wenn aktiviert, zusaetzlich Texterkennung auf Snapshot
            if ws_cfg.get("scan_auto_ocr") and self.ocr_engine:
                snapshot = result.get("snapshot")
                if snapshot and isinstance(snapshot, bytes):
                    import tempfile, pathlib
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                        f.write(snapshot)
                        tmp_path = pathlib.Path(f.name)
                    try:
                        ocr_text = self.ocr_engine.extract_text(tmp_path)
                        if ocr_text:
                            scan_result["ocr_text"] = ocr_text
                    finally:
                        tmp_path.unlink(missing_ok=True)
            return scan_result

        # Fall 2: Bild-Daten direkt → Vision-LLM Analyse
        if image_data and self.ollama:
            import base64
            image_b64 = base64.b64encode(image_data).decode("utf-8")
            vision_model = yaml_config.get("cameras", {}).get(
                "vision_model", "llava")
            prompt = (
                "Analysiere dieses Bild aus einer Werkstatt-Perspektive:\n"
                "1. Was ist das fuer ein Objekt/Bauteil?\n"
                "2. Erkennbare Beschaedigungen oder Verschleiss?\n"
                "3. Geschaetzte Abmessungen?\n"
                "4. Teilenummern/Beschriftungen?\n"
                "5. Reparierbar oder Ersatz noetig?"
            )
            result = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt,
                           "images": [image_b64]}],
                model=vision_model, temperature=0.3, max_tokens=500)
            if "error" not in result:
                text = result.get("message", {}).get("content", "")
                return {"status": "ok", "analysis": text}
            return {"status": "error", "message": "Vision-LLM Analyse fehlgeschlagen"}

        # Fall 3: Beschreibung → LLM-Textanalyse
        if description and self.ollama:
            prompt = (
                "Du bist ein Werkstatt-Ingenieur. Der Benutzer beschreibt ein Objekt/Bauteil:\n"
                f'"{description}"\n\n'
                "Analysiere:\n"
                "1. Was koennte das fuer ein Objekt/Bauteil sein?\n"
                "2. Moegliche Beschaedigungen oder Verschleiss?\n"
                "3. Reparierbar oder Ersatz noetig?\n"
                "4. Empfohlene naechste Schritte?"
            )
            result = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4, max_tokens=500)
            if "error" not in result:
                text = result.get("message", {}).get("content", "")
                return {"status": "ok", "analysis": text}
            return {"status": "error", "message": "LLM-Analyse fehlgeschlagen"}

        return {"status": "error",
                "message": "Kein Bild, keine Kamera und keine Beschreibung angegeben"}

    # ── Werkstatt-Inventar (Redis) ───────────────────────────

    async def add_workshop_item(self, name, quantity=1,
                                category="werkzeug",
                                location="") -> dict:
        """Fuegt ein Werkstatt-Item hinzu."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        item_id = name.lower().replace(" ", "_")
        item = {
            "name": name, "quantity": str(quantity),
            "category": category, "location": location,
            "added": datetime.now().isoformat(),
        }
        await self.redis.hset(
            f"mha:repair:workshop:{item_id}", mapping=item)
        await self.redis.sadd("mha:repair:workshop:all", item_id)
        await self.redis.sadd(
            f"mha:repair:workshop:cat:{category}", item_id)
        return {"status": "ok", "item": name}

    async def list_workshop(self, category=None) -> list:
        """Listet Werkstatt-Items."""
        if not self.redis:
            return []
        if category:
            ids = await self.redis.smembers(
                f"mha:repair:workshop:cat:{category}")
        else:
            ids = await self.redis.smembers("mha:repair:workshop:all")
        items = []
        decoded_ids = [iid.decode() if isinstance(iid, bytes) else iid for iid in ids]
        if decoded_ids:
            pipe = self.redis.pipeline()
            for iid in decoded_ids:
                pipe.hgetall(f"mha:repair:workshop:{iid}")
            results = await pipe.execute()
            for data in results:
                if data:
                    data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
                    items.append(data)
        return items

    async def add_maintenance_schedule(self, tool_name,
                                       interval_days,
                                       last_done="") -> dict:
        """Fuegt einen Wartungsplan hinzu."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        key = f"mha:repair:maintenance:{tool_name.lower().replace(' ', '_')}"
        await self.redis.hset(key, mapping={
            "tool": tool_name,
            "interval_days": str(interval_days),
            "last_done": last_done or datetime.now().isoformat(),
        })
        return {"status": "ok"}

    async def check_maintenance_due(self) -> list:
        """Prüft welche Werkzeuge gewartet werden muessen."""
        if not self.redis:
            return []
        keys = [k async for k in self.redis.scan_iter(
            "mha:repair:maintenance:*")]
        if not keys:
            return []
        # P1: Parallel statt sequentiell
        all_data = await asyncio.gather(
            *[self.redis.hgetall(key) for key in keys],
            return_exceptions=True,
        )
        due = []
        for data in all_data:
            if isinstance(data, Exception):
                continue
            # Redis returns bytes – decode to str
            data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
            try:
                last = datetime.fromisoformat(
                    data.get("last_done", "2000-01-01T00:00:00"))
                interval = int(data.get("interval_days", 90))
                if (datetime.now() - last).days >= interval:
                    due.append(data)
            except (ValueError, TypeError) as e:
                logger.debug("S6: Maintenance check skipped: %s", e)
        return due

    # ── Budget ───────────────────────────────────────────────

    async def set_project_budget(self, project_id, budget) -> dict:
        """Setzt das Budget eines Projekts."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        await self.redis.hset(
            f"mha:repair:project:{project_id}", "budget", str(budget))
        return {"status": "ok"}

    async def add_expense(self, project_id, item, cost) -> dict:
        """Fuegt eine Ausgabe hinzu."""
        project = await self.get_project(project_id)
        if not project:
            return {"status": "error", "message": "Projekt nicht gefunden"}
        expenses = project.get("expenses", [])
        expenses.append({
            "item": item, "cost": float(cost),
            "date": datetime.now().isoformat(),
        })
        await self.redis.hset(
            f"mha:repair:project:{project_id}",
            "expenses", json.dumps(expenses))
        total = sum(e["cost"] for e in expenses)
        return {"status": "ok", "total": total}

    # ── Skills ───────────────────────────────────────────────

    async def record_skill(self, person, skill,
                           level="beginner") -> dict:
        """Speichert ein Skill-Level."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        key = f"mha:repair:skills:{person.lower()}"
        await self.redis.hset(key, skill, level)
        return {"status": "ok"}

    # ── Statistiken ──────────────────────────────────────────

    async def get_workshop_stats(self, period="month") -> dict:
        """Holt Werkstatt-Statistiken."""
        all_projects = await self.list_projects()
        completed = [p for p in all_projects
                     if p.get("status") == "fertig"]
        categories = {}
        for cat in ["reparatur", "bau", "maker", "erfindung", "renovierung"]:
            categories[cat] = len(
                [p for p in all_projects if p.get("category") == cat])
        return {
            "total_projects": len(all_projects),
            "completed": len(completed),
            "in_progress": len(all_projects) - len(completed),
            "categories": categories,
        }

    # ── Templates ────────────────────────────────────────────

    async def create_from_template(self, template_name,
                                   title="") -> dict:
        """Erstellt ein Projekt aus einem Template."""
        tmpl = TEMPLATES.get(template_name)
        if not tmpl:
            return {"status": "error",
                    "message": f"Template '{template_name}' nicht gefunden. "
                    f"Verfügbar: {', '.join(TEMPLATES.keys())}"}
        project = await self.create_project(
            title=title or tmpl["title"],
            description=f"Aus Template: {template_name}",
            category=tmpl.get("category", "maker"),
        )
        for part in tmpl.get("parts", []):
            await self.add_part(project["id"], **part)
        return project

    # ── Werkzeug-Verleih ─────────────────────────────────────

    async def lend_tool(self, tool_name, person) -> dict:
        """Vermerkt ein verliehenes Werkzeug."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        key = f"mha:repair:lent:{tool_name.lower().replace(' ', '_')}"
        await self.redis.hset(key, mapping={
            "tool": tool_name, "person": person,
            "since": datetime.now().isoformat(),
        })
        return {"status": "ok",
                "message": f"{tool_name} an {person} verliehen"}

    async def return_tool(self, tool_name) -> dict:
        """Vermerkt ein zurückgegebenes Werkzeug."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        key = f"mha:repair:lent:{tool_name.lower().replace(' ', '_')}"
        await self.redis.delete(key)
        return {"status": "ok",
                "message": f"{tool_name} zurückgegeben"}

    async def list_lent_tools(self) -> list:
        """Listet alle verliehenen Werkzeuge."""
        if not self.redis:
            return []
        keys = [k async for k in self.redis.scan_iter(
            "mha:repair:lent:*")]
        results = []
        if keys:
            pipe = self.redis.pipeline()
            for k in keys:
                pipe.hgetall(k)
            all_data = await pipe.execute()
            for data in all_data:
                data = {dk.decode() if isinstance(dk, bytes) else dk: dv.decode() if isinstance(dv, bytes) else dv for dk, dv in data.items()}
                results.append(data)
        return results

    # ── 3D-Drucker Steuerung (via HA) ────────────────────────

    async def get_printer_status(self) -> dict:
        """Liest 3D-Drucker Status via HA-Entities."""
        ws_cfg = yaml_config.get("workshop", {})
        printer_cfg = ws_cfg.get("printer_3d", {})
        if not printer_cfg.get("enabled"):
            return {"status": "disabled",
                    "message": "3D-Drucker nicht aktiviert"}
        prefix = printer_cfg.get("entity_prefix", "octoprint")
        try:
            states = await self.ha.get_states()
        except Exception as e:
            logger.debug("HA-Verbindung fehlgeschlagen: %s", e)
            return {"status": "error",
                    "message": "Home Assistant nicht erreichbar"}

        printer = {}
        for s in states:
            eid = s.get("entity_id", "")
            if prefix in eid:
                if "progress" in eid:
                    printer["progress"] = s.get("state")
                elif "bed_temp" in eid:
                    printer["bed_temp"] = s.get("state")
                elif "tool_temp" in eid or "hotend" in eid:
                    printer["hotend_temp"] = s.get("state")
                elif "state" in eid or "status" in eid:
                    printer["state"] = s.get("state")
                elif "time_remaining" in eid:
                    printer["eta"] = s.get("state")
        return printer if printer else {
            "status": "not_found",
            "message": "Kein 3D-Drucker in HA gefunden",
        }

    async def start_print(self, project_id="", filename="") -> dict:
        """Startet einen 3D-Druck."""
        status = await self.get_printer_status()
        if status.get("status") in ("disabled", "not_found", "error"):
            return status
        if status.get("state") not in (
            "idle", "ready", "operational", None
        ):
            return {"status": "error",
                    "message": f"Drucker nicht bereit: {status.get('state')}"}
        ws_cfg = yaml_config.get("workshop", {})
        prefix = ws_cfg.get("printer_3d", {}).get(
            "entity_prefix", "octoprint")
        try:
            await self.ha.call_service(
                "button", "press",
                {"entity_id": f"button.{prefix}_resume_job"})
        except Exception as e:
            logger.error("3D-Druck Start fehlgeschlagen: %s", e)
            return {"status": "error", "message": "Druck konnte nicht gestartet werden"}
        return {"status": "ok", "message": "Druck gestartet"}

    async def pause_print(self) -> dict:
        """Pausiert den 3D-Druck."""
        ws_cfg = yaml_config.get("workshop", {})
        printer_cfg = ws_cfg.get("printer_3d", {})
        if not printer_cfg.get("enabled"):
            return {"status": "disabled"}
        prefix = printer_cfg.get("entity_prefix", "octoprint")
        try:
            await self.ha.call_service(
                "button", "press",
                {"entity_id": f"button.{prefix}_pause_job"})
        except Exception as e:
            logger.error("3D-Druck Pause fehlgeschlagen: %s", e)
            return {"status": "error", "message": "Druck konnte nicht pausiert werden"}
        return {"status": "ok", "message": "Druck pausiert"}

    async def cancel_print(self) -> dict:
        """Bricht den 3D-Druck ab."""
        ws_cfg = yaml_config.get("workshop", {})
        printer_cfg = ws_cfg.get("printer_3d", {})
        if not printer_cfg.get("enabled"):
            return {"status": "disabled"}
        prefix = printer_cfg.get("entity_prefix", "octoprint")
        try:
            await self.ha.call_service(
                "button", "press",
                {"entity_id": f"button.{prefix}_cancel_job"})
        except Exception as e:
            logger.error("3D-Druck Abbruch fehlgeschlagen: %s", e)
            return {"status": "error", "message": "Druck konnte nicht abgebrochen werden"}
        return {"status": "ok", "message": "Druck abgebrochen"}

    # ── Roboterarm-Steuerung (Stub) ──────────────────────────

    async def _arm_command(self, cmd: dict) -> dict:
        """Sendet JSON-Kommando an den Arm via HTTP.

        F-081: SSRF-Schutz — URL wird validiert (Scheme, Hostname, DNS-Check).
        F-085: Echte DNS-Resolution + Cloud-Metadata-Schutz + Response-Size-Limit.
        """
        arm_cfg = yaml_config.get("workshop", {}).get("robot_arm", {})
        if not arm_cfg.get("enabled"):
            return {"status": "disabled",
                    "message": "Roboterarm nicht aktiviert"}
        url = arm_cfg.get("url", "")
        if not url:
            return {"status": "error",
                    "message": "Arm-URL nicht konfiguriert"}
        # F-081: URL-Scheme + Struktur validieren
        try:
            from urllib.parse import urlparse
            import ipaddress
            import socket
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                logger.warning("Arm-URL: Ungueltiges Scheme '%s'", parsed.scheme)
                return {"status": "error",
                        "message": "Arm-URL ungueltig"}
            # F-082: Userinfo blockieren
            if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
                return {"status": "error",
                        "message": "Arm-URL ungueltig (Userinfo)"}
            # F-085: Query-String/Fragment in Basis-URL blockieren (Path-Injection)
            if parsed.query or parsed.fragment:
                return {"status": "error",
                        "message": "Arm-URL ungueltig (Query/Fragment)"}
            hostname = parsed.hostname or ""
            if not hostname:
                return {"status": "error",
                        "message": "Arm-URL ohne Hostname"}
            # F-085: Bekannte interne Services + Cloud-Metadata blockieren
            _ARM_BLOCKED_HOSTNAMES = frozenset(
                {"redis", "chromadb", "ollama", "homeassistant", "ha",
                 "localhost", "metadata.google.internal", "metadata.azure.internal"}
            )
            if hostname in _ARM_BLOCKED_HOSTNAMES:
                logger.warning("Arm-URL zeigt auf blockierten Service: '%s'", hostname)
                return {"status": "error",
                        "message": "Arm-URL zeigt auf internen Service"}
            # F-085: Echte DNS-Resolution — Cloud-Metadata IPs blockieren
            # (Arm darf auf LAN-IPs, aber NICHT auf Loopback/Link-Local/Metadata)
            _ARM_BLOCKED_NETS = [
                ipaddress.ip_network("127.0.0.0/8"),      # Loopback
                ipaddress.ip_network("0.0.0.0/8"),         # "This host"
                ipaddress.ip_network("169.254.0.0/16"),    # Link-Local / Cloud Metadata
                ipaddress.ip_network("100.64.0.0/10"),     # CGNAT
                ipaddress.ip_network("::1/128"),
                ipaddress.ip_network("fe80::/10"),
            ]
            try:
                addr = ipaddress.ip_address(hostname)
                # IPv4-mapped IPv6 entpacken
                if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
                    addr = addr.ipv4_mapped
                for net in _ARM_BLOCKED_NETS:
                    if addr in net:
                        logger.warning("Arm-URL: IP %s blockiert", addr)
                        return {"status": "error",
                                "message": "Arm-URL zeigt auf blockierte IP"}
            except ValueError:
                # Hostname, nicht IP-Literal — DNS aufloesen
                try:
                    loop = asyncio.get_running_loop()
                    infos = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM),
                        ),
                        timeout=5.0,
                    )
                    for _fam, _type, _proto, _cname, sockaddr in (infos or []):
                        try:
                            resolved = ipaddress.ip_address(sockaddr[0])
                            if isinstance(resolved, ipaddress.IPv6Address) and resolved.ipv4_mapped:
                                resolved = resolved.ipv4_mapped
                            for net in _ARM_BLOCKED_NETS:
                                if resolved in net:
                                    logger.warning("Arm-URL: DNS '%s' → blockierte IP %s", hostname, resolved)
                                    return {"status": "error",
                                            "message": "Arm-URL loest auf blockierte IP auf"}
                        except ValueError:
                            pass
                except (asyncio.TimeoutError, socket.gaierror) as e:
                    logger.warning("Arm-URL: DNS-Auflösung fehlgeschlagen für '%s': %s", hostname, e)
                    return {"status": "error",
                            "message": "Arm-URL nicht erreichbar"}
        except Exception as e:
            logger.error("Arm-URL Validierung fehlgeschlagen: %s", e)
            return {"status": "error",
                    "message": "Arm-URL Validierung fehlgeschlagen"}
        try:
            import aiohttp
            # F-085: URL sicher zusammenbauen (Scheme + Host + Port + /js)
            port_str = f":{parsed.port}" if parsed.port else ""
            target_url = f"{parsed.scheme}://{parsed.hostname}{port_str}/js"
            _MAX_ARM_RESPONSE = 64 * 1024  # 64 KB max
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5, sock_read=3)
            ) as session:
                async with session.post(
                    target_url,
                    json=cmd,
                    allow_redirects=False,  # F-081: Redirect-Blocking
                ) as resp:
                    # F-081: Content-Type prüfen
                    ct = resp.headers.get("Content-Type", "")
                    if "json" not in ct.lower():
                        logger.warning("Arm-Response: unerwarteter Content-Type '%s'", ct[:80])
                        return {"status": "error",
                                "message": "Arm-Antwort hat falsches Format"}
                    # F-085: Response-Size-Limit
                    raw = await resp.content.read(_MAX_ARM_RESPONSE + 1)
                    if len(raw) > _MAX_ARM_RESPONSE:
                        return {"status": "error",
                                "message": "Arm-Antwort zu gross"}
                    import json as _json
                    data = _json.loads(raw)
                    # F-085: Nur erwartete Keys zurückgeben (kein Spread von Fremd-Daten)
                    return {
                        "status": data.get("status", "ok"),
                        "x": data.get("x"),
                        "y": data.get("y"),
                        "z": data.get("z"),
                    }
        except Exception as e:
            # F-078: Exception-Details NICHT leaken
            logger.error("Arm-Kommando fehlgeschlagen: %s", e)
            return {"status": "error",
                    "message": "Roboterarm-Kommunikation fehlgeschlagen"}

    async def arm_move(self, x, y, z, speed=50) -> dict:
        """Bewegt den Arm zu einer Position.

        F-085: Input-Validierung — Typ, Range, Division-by-Zero-Schutz.
        """
        arm_cfg = yaml_config.get("workshop", {}).get("robot_arm", {})
        max_speed = arm_cfg.get("max_speed", 80)
        min_speed = arm_cfg.get("min_speed", 5)
        # F-085: Typvalidierung
        try:
            x, y, z = float(x), float(y), float(z)
            speed = float(speed)
        except (ValueError, TypeError):
            return {"status": "error", "message": "Ungueltige Koordinaten oder Geschwindigkeit"}
        # F-085: Range-Validierung
        coord_max = arm_cfg.get("coord_max", 500)
        for val, name in [(x, "x"), (y, "y"), (z, "z")]:
            if abs(val) > coord_max:
                return {"status": "error",
                        "message": f"Koordinate {name}={val} ausserhalb Limit ({coord_max})"}
        # F-085: Speed-Clamping (min/max) — verhindert Division by Zero
        speed = max(min_speed, min(speed, max_speed))
        return await self._arm_command({
            "T": 104, "x": x, "y": y, "z": z,
            "t": int(2000 / (speed / 100)),
        })

    async def arm_gripper(self, action="open") -> dict:
        """Oeffnet oder schliesst den Greifer."""
        cmd = 1 if action == "open" else 0
        return await self._arm_command({"T": 106, "cmd": cmd})

    async def arm_home(self) -> dict:
        """Faehrt den Arm in die Home-Position."""
        return await self._arm_command({"T": 100})

    async def arm_save_position(self, name, position=None) -> dict:
        """Speichert eine Arm-Position.

        F-085: Redis Key Injection Schutz + Position-Validierung.
        """
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        # F-085: Name validieren (nur alphanumerisch + Unterstrich/Bindestrich)
        import re as _re
        if not name or not _re.match(r'^[a-zA-Z0-9_-]+$', str(name)):
            return {"status": "error",
                    "message": "Ungueltiger Positionsname (nur a-z, 0-9, _, -)"}
        if position is None:
            result = await self._arm_command({"T": 100})
            position = result
        # F-085: Nur erwartete Keys speichern
        _ALLOWED_KEYS = {"x", "y", "z", "status", "T", "t"}
        safe_mapping = {}
        for k, v in position.items():
            if k in _ALLOWED_KEYS:
                safe_mapping[k] = str(v)
        key = f"mha:repair:arm:positions:{name.lower()}"
        await self.redis.hset(key, mapping=safe_mapping)
        return {"status": "ok",
                "message": f"Position '{name}' gespeichert"}

    async def arm_pick_tool(self, tool_name) -> dict:
        """Greift ein Werkzeug an einer gespeicherten Position."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        key = f"mha:repair:arm:positions:{tool_name.lower()}"
        raw_pos = await self.redis.hgetall(key)
        if not raw_pos:
            return {"status": "error",
                    "message": f"Position '{tool_name}' nicht gespeichert"}
        pos = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw_pos.items()}
        await self.arm_gripper("open")
        await self.arm_move(
            float(pos.get("x", 0)),
            float(pos.get("y", 0)),
            float(pos.get("z", 0)),
        )
        await self.arm_gripper("close")
        return {"status": "ok", "message": f"Greife {tool_name}"}

    async def _emergency_stop(self) -> str:
        """NOTFALL-STOPP für den Arm."""
        await self._arm_command({"T": 0})
        return "NOTFALL-STOPP! Arm angehalten."

    # ── Timer ────────────────────────────────────────────────

    async def start_timer(self, project_id) -> dict:
        """Startet den Projekt-Timer."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        await self.redis.hset(
            f"mha:repair:project:{project_id}",
            "timer_start", str(time.time()))
        return {"status": "ok", "message": "Timer gestartet"}

    async def pause_timer(self, project_id) -> dict:
        """Pausiert den Projekt-Timer und gibt Gesamtzeit zurück."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        start = float(await self.redis.hget(
            f"mha:repair:project:{project_id}", "timer_start") or 0)
        total = float(await self.redis.hget(
            f"mha:repair:project:{project_id}", "timer_total") or 0)
        if start > 0:
            total += time.time() - start
            await self.redis.hset(
                f"mha:repair:project:{project_id}",
                "timer_total", str(total))
            await self.redis.hset(
                f"mha:repair:project:{project_id}",
                "timer_start", "0")
        hours, remainder = divmod(int(total), 3600)
        minutes = remainder // 60
        return {"status": "ok", "total_seconds": total,
                "display": f"{hours}h {minutes}min"}

    async def set_workshop_timer(self, minutes, reason="") -> dict:
        """Setzt einen Countdown-Timer mit Callback."""
        timer_id = str(uuid_mod.uuid4())[:6]

        async def _timer_callback():
            await asyncio.sleep(minutes * 60)
            _title = yaml_config.get("person", {}).get("title", "Sir")
            msg = f"{_title}, {minutes} Minuten sind um"
            if reason:
                msg += f" — {reason}"
            if self._notify_callback:
                await self._notify_callback(msg)

        task = asyncio.create_task(_timer_callback())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return {"status": "ok", "timer_id": timer_id,
                "minutes": minutes, "reason": reason}

    # ── Journal ──────────────────────────────────────────────

    async def get_journal(self, period="today") -> dict:
        """Holt Journal-Einträge."""
        if not self.redis:
            return {"date": "", "entries": []}
        key = f"mha:repair:journal:{datetime.now().strftime('%Y-%m-%d')}"
        entries = await self.redis.lrange(key, 0, -1)
        return {
            "date": datetime.now().strftime('%Y-%m-%d'),
            "entries": [json.loads(e.decode() if isinstance(e, bytes) else e) for e in entries],
        }

    async def add_journal_entry(self, note) -> dict:
        """Fuegt einen Journal-Eintrag hinzu."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        key = f"mha:repair:journal:{datetime.now().strftime('%Y-%m-%d')}"
        entry = {"text": note, "time": datetime.now().strftime('%H:%M')}
        await self.redis.rpush(key, json.dumps(entry))
        await self.redis.expire(key, 90 * 86400)  # 90 Tage
        return {"status": "ok"}

    # ── Snippets ─────────────────────────────────────────────

    async def save_snippet(self, name, code, language="",
                           tags=None) -> dict:
        """Speichert ein Code-Snippet."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        key = f"mha:repair:snippet:{name.lower().replace(' ', '_')}"
        await self.redis.hset(key, mapping={
            "name": name, "code": code, "language": language,
            "tags": json.dumps(tags or []),
            "created": datetime.now().isoformat(),
        })
        return {"status": "ok"}

    async def get_snippet(self, name) -> dict:
        """Holt ein Code-Snippet."""
        if not self.redis:
            return {}
        key = f"mha:repair:snippet:{name.lower().replace(' ', '_')}"
        data = await self.redis.hgetall(key)
        return {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}

    # ── Multi-Projekt ────────────────────────────────────────

    async def switch_project(self, project_id) -> dict:
        """Wechselt zum angegebenen Projekt."""
        project = await self.get_project(project_id)
        if not project:
            return {"status": "error", "message": "Projekt nicht gefunden"}
        # Alte Session pausieren
        if self._session:
            await self.pause_timer(self._session.project_id)
        # Neue Session (ohne Schritte, die kommen bei Diagnose)
        self._session = RepairSession(
            project_id=project_id,
            title=project.get("title", ""),
            category=project.get("category", "maker"),
            started_at=datetime.now().isoformat(),
        )
        await self._save_session()
        return {"status": "ok",
                "message": f"Gewechselt zu: {project['title']}"}

    async def get_active_project(self) -> Optional[dict]:
        """Gibt das aktive Projekt zurück."""
        if not self._session:
            return None
        return await self.get_project(self._session.project_id)

    async def search_projects(self, query,
                              include_completed=True) -> list:
        """Sucht in Projekten."""
        all_projects = await self.list_projects()
        if not include_completed:
            all_projects = [p for p in all_projects
                           if p.get("status") != "fertig"]
        results = [p for p in all_projects
                   if query.lower() in json.dumps(p).lower()]
        return results

    # ── Geräte-Management ───────────────────────────────────

    async def check_device_online(self, entity_id) -> dict:
        """Prüft ob ein HA-Gerät online ist."""
        try:
            states = await self.ha.get_states()
        except Exception as e:
            logger.debug("HA-Status Abruf fehlgeschlagen: %s", e)
            return {"entity": entity_id, "state": "ha_unavailable"}
        for s in states:
            if s.get("entity_id") == entity_id:
                return {
                    "entity": entity_id,
                    "state": s.get("state", "unknown"),
                    "last_updated": s.get("last_updated", ""),
                }
        return {"entity": entity_id, "state": "not_found"}

    async def get_power_consumption(self, entity_id) -> dict:
        """Liest den Stromverbrauch eines Geräts."""
        try:
            states = await self.ha.get_states()
        except Exception as e:
            logger.debug("HA-Status Abruf fehlgeschlagen: %s", e)
            return {"status": "error",
                    "message": "Home Assistant nicht erreichbar"}
        for s in states:
            if s.get("entity_id") == entity_id:
                return {
                    "entity": entity_id,
                    "power_w": s.get("state", "0"),
                    "unit": s.get("attributes", {}).get(
                        "unit_of_measurement", "W"),
                }
        return {"status": "not_found"}

    async def link_device_to_project(self, project_id,
                                     entity_id) -> dict:
        """Verknuepft ein HA-Gerät mit einem Projekt."""
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfügbar"}
        await self.redis.hset(
            f"mha:repair:project:{project_id}",
            "device_entity", entity_id)
        return {"status": "ok"}

    async def check_all_devices(self) -> list:
        """Prüft alle verknuepften Geräte."""
        projects = await self.list_projects()
        # Collect all entities that need checking
        entity_projects = [
            (p.get("device_entity"), p.get("title"))
            for p in projects if p.get("device_entity")
        ]
        if not entity_projects:
            return []
        # Fetch all states once instead of N sequential calls
        try:
            states = await self.ha.get_states()
        except Exception as e:
            logger.debug("HA-Status Abruf fehlgeschlagen: %s", e)
            return [
                {"entity": entity, "state": "ha_unavailable", "project": title}
                for entity, title in entity_projects
            ]
        states_by_id = {
            s.get("entity_id"): s for s in (states or [])
        }
        devices = []
        for entity, title in entity_projects:
            s = states_by_id.get(entity)
            if s:
                status = {
                    "entity": entity,
                    "state": s.get("state", "unknown"),
                    "last_updated": s.get("last_updated", ""),
                }
            else:
                status = {"entity": entity, "state": "not_found"}
            status["project"] = title
            devices.append(status)
        return devices

    # ── Push-Benachrichtigung ────────────────────────────────

    async def notify_user(self, message,
                          title="Werkstatt") -> dict:
        """Push-Benachrichtigung via HA Notify."""
        try:
            await self.ha.call_service(
                "notify", "notify",
                {"title": title, "message": message})
            return {"status": "ok"}
        except Exception as e:
            logger.debug("HA-Status Abruf fehlgeschlagen: %s", e)
            return {"status": "error"}

    # ── Intent-Erkennung ─────────────────────────────────────

    def is_repair_intent(self, text: str) -> bool:
        """Erkennt ob der User etwas Werkstatt-bezogenes will."""
        if not self.enabled:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in REPAIR_KEYWORDS)

    def is_activation_command(self, text: str) -> bool:
        """Erkennt Werkstatt-Modus An/Aus Befehle."""
        text_lower = text.lower().strip()
        return text_lower in (ACTIVATION_ON | ACTIVATION_OFF)

    async def toggle_activation(self, text: str) -> str:
        """Schaltet den Werkstatt-Modus an/aus."""
        text_lower = text.lower().strip()
        if text_lower in ACTIVATION_ON:
            if self.redis:
                await self.redis.setex(
                    "mha:repair:manual_active",
                    self.REDIS_SESSION_TTL, "1")
            _title = yaml_config.get("person", {}).get("title", "Sir")
            return f"Werkstatt-Modus aktiviert, {_title}."
        else:
            if self.redis:
                await self.redis.delete("mha:repair:manual_active")
            _title = yaml_config.get("person", {}).get("title", "Sir")
            return f"Werkstatt-Modus deaktiviert. Bis zum nächsten Mal, {_title}."

    def has_active_session(self) -> bool:
        """Prüft ob eine aktive Session existiert."""
        return self._session is not None

    async def is_manually_activated(self) -> bool:
        """Prüft ob der Werkstatt-Modus manuell aktiviert ist."""
        if not self.redis:
            return False
        return bool(await self.redis.exists("mha:repair:manual_active"))
