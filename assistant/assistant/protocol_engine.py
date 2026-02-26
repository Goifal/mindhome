"""
ProtocolEngine — Benannte Multi-Step-Sequenzen.

Feature 2: User erstellt/ruft Protokolle per Sprache auf:
  "Jarvis, Filmabend" → Licht 20%, Rolladen zu, TV an
  "Erstelle Protokoll Filmabend: Licht 20%, Rolladen zu, TV an"
  "Protokoll Filmabend rueckgaengig"

Architektur:
  1. LLM extrahiert Schritte aus natuerlicher Beschreibung
  2. Schritte werden gegen bekannte Tools validiert
  3. Gespeichert in Redis (mha:protocol:{name})
  4. Ausfuehrung via FunctionExecutor (sequentiell)
  5. Undo: Reverse-Schritte werden automatisch generiert
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config, get_person_title
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_PREFIX = "mha:protocol"
_LIST_KEY = f"{_PREFIX}:list"

# Prompt fuer LLM-basiertes Step-Parsing
_PARSE_PROMPT = """Du bist ein Smart-Home-Protokoll-Parser. Extrahiere Aktionsschritte aus der Beschreibung.

Verfuegbare Tools:
- set_light: Licht steuern (room, state: on/off, brightness: 0-100)
- set_cover: Rolladen steuern (room, action: open/close, position: 0-100)
- set_climate: Temperatur steuern (room, temperature)
- set_switch: Steckdose schalten (entity_id, state: on/off)
- play_media: Medien abspielen (room, media_type, action: play/pause/stop)

Beschreibung: {description}

Antworte NUR mit einem JSON-Array von Schritten. Beispiel:
[
  {{"tool": "set_light", "args": {{"room": "Wohnzimmer", "brightness": 20}}}},
  {{"tool": "set_cover", "args": {{"room": "Wohnzimmer", "action": "close"}}}}
]

Wenn die Beschreibung unklar ist, gib ein leeres Array zurueck: []

Schritte (JSON-Array):"""


class ProtocolEngine:
    """Verwaltet benannte Multi-Step-Protokolle."""

    def __init__(self, ollama: OllamaClient, executor=None):
        self.ollama = ollama
        self.executor = executor
        self.redis: Optional[aioredis.Redis] = None

        cfg = yaml_config.get("protocols", {})
        self.enabled = cfg.get("enabled", True)
        self.max_protocols = cfg.get("max_protocols", 20)
        self.max_steps = cfg.get("max_steps", 10)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        logger.info("ProtocolEngine initialisiert (enabled: %s)", self.enabled)

    def set_executor(self, executor):
        """Setzt den FunctionExecutor fuer die Ausfuehrung."""
        self.executor = executor

    async def create_protocol(self, name: str, description: str, person: str = "") -> dict:
        """Erstellt ein neues Protokoll aus natuerlicher Beschreibung.

        Args:
            name: Name des Protokolls (z.B. "Filmabend")
            description: Natuerliche Beschreibung der Schritte
            person: Ersteller

        Returns:
            Dict mit success, message, steps
        """
        if not self.enabled:
            return {"success": False, "message": "Protokolle sind deaktiviert."}
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        name_normalized = self._normalize_name(name)
        if not name_normalized:
            return {"success": False, "message": "Bitte gib einen Namen fuer das Protokoll an."}

        # Maximale Anzahl pruefen
        existing = await self.redis.scard(_LIST_KEY) or 0
        if existing >= self.max_protocols:
            return {
                "success": False,
                "message": f"Maximale Anzahl von {self.max_protocols} Protokollen erreicht.",
            }

        # LLM: Schritte aus Beschreibung extrahieren
        steps = await self._parse_steps(description)
        if not steps:
            return {
                "success": False,
                "message": "Ich konnte keine Schritte aus der Beschreibung erkennen.",
            }

        if len(steps) > self.max_steps:
            steps = steps[:self.max_steps]

        # Undo-Schritte generieren
        undo_steps = self._generate_undo_steps(steps)

        protocol = {
            "name": name,
            "name_normalized": name_normalized,
            "created_by": person,
            "created_at": datetime.now().isoformat(),
            "description": description,
            "steps": steps,
            "undo_steps": undo_steps,
        }

        # In Redis speichern
        await self.redis.set(f"{_PREFIX}:{name_normalized}", json.dumps(protocol))
        await self.redis.sadd(_LIST_KEY, name_normalized)

        title = get_person_title(person)
        return {
            "success": True,
            "message": (
                f"Protokoll '{name}' gespeichert mit {len(steps)} Schritten, {title}. "
                f"Sag einfach '{name}' um es auszufuehren."
            ),
            "steps": steps,
        }

    async def execute_protocol(self, name: str, person: str = "") -> dict:
        """Fuehrt ein gespeichertes Protokoll aus.

        Args:
            name: Name des Protokolls
            person: Ausfuehrender

        Returns:
            Dict mit success, message, steps_executed
        """
        if not self.enabled or not self.redis or not self.executor:
            return {"success": False, "message": "Protokoll-Ausfuehrung nicht moeglich."}

        name_normalized = self._normalize_name(name)
        protocol_raw = await self.redis.get(f"{_PREFIX}:{name_normalized}")
        if not protocol_raw:
            return {"success": False, "message": f"Protokoll '{name}' nicht gefunden."}

        try:
            protocol = json.loads(protocol_raw.decode() if isinstance(protocol_raw, bytes) else protocol_raw)
        except (json.JSONDecodeError, AttributeError):
            return {"success": False, "message": "Protokoll konnte nicht geladen werden."}

        steps = protocol.get("steps", [])
        if not steps:
            return {"success": False, "message": "Protokoll hat keine Schritte."}

        # Vor Ausfuehrung: Aktuellen Zustand snapshotten fuer praezises Undo
        live_undo_steps = await self._snapshot_undo_steps(steps)

        # Sequentiell ausfuehren
        executed = []
        errors = []
        for step in steps:
            tool = step.get("tool", "")
            args = step.get("args", {})
            try:
                result = await self.executor.execute(tool, args)
                executed.append({"tool": tool, "args": args, "result": result})
                if not isinstance(result, dict) or not result.get("success", True):
                    errors.append(f"{tool}: {result}")
            except Exception as e:
                errors.append(f"{tool}: {e}")

        # Live-Undo-Steps im Protokoll aktualisieren (ueberschreibt Defaults)
        if live_undo_steps:
            protocol["undo_steps"] = live_undo_steps
            try:
                await self.redis.set(f"{_PREFIX}:{name_normalized}", json.dumps(protocol))
            except Exception:
                pass  # Fallback: alte Undo-Steps bleiben

        # Letzten Ausfuehrungsstatus speichern (fuer Undo)
        last_exec = {
            "protocol": name_normalized,
            "executed_at": datetime.now().isoformat(),
            "person": person,
            "steps_executed": len(executed),
        }
        await self.redis.setex(
            f"{_PREFIX}:last_executed:{name_normalized}",
            3600,  # 1 Stunde Undo-Fenster
            json.dumps(last_exec),
        )

        title = get_person_title(person)
        if errors:
            return {
                "success": False,
                "message": (
                    f"Protokoll '{protocol.get('name', name)}': "
                    f"{len(executed)} von {len(steps)} Schritten ausgefuehrt, "
                    f"{len(errors)} Fehler."
                ),
                "steps_executed": len(executed),
            }

        return {
            "success": True,
            "message": (
                f"Protokoll '{protocol.get('name', name)}' ausgefuehrt, {title}. "
                f"{len(executed)} Schritte erfolgreich."
            ),
            "steps_executed": len(executed),
        }

    async def undo_protocol(self, name: str, person: str = "") -> dict:
        """Macht ein Protokoll rueckgaengig.

        Args:
            name: Name des Protokolls

        Returns:
            Dict mit success, message
        """
        if not self.enabled or not self.redis or not self.executor:
            return {"success": False, "message": "Undo nicht moeglich."}

        name_normalized = self._normalize_name(name)

        # Pruefen ob kuerzlich ausgefuehrt
        last_exec = await self.redis.get(f"{_PREFIX}:last_executed:{name_normalized}")
        if not last_exec:
            return {"success": False, "message": f"Kein kuerzlich ausgefuehrtes Protokoll '{name}' gefunden."}

        # Protokoll laden
        protocol_raw = await self.redis.get(f"{_PREFIX}:{name_normalized}")
        if not protocol_raw:
            return {"success": False, "message": f"Protokoll '{name}' nicht gefunden."}

        try:
            protocol = json.loads(protocol_raw.decode() if isinstance(protocol_raw, bytes) else protocol_raw)
        except (json.JSONDecodeError, AttributeError):
            return {"success": False, "message": "Protokoll konnte nicht geladen werden."}

        undo_steps = protocol.get("undo_steps", [])
        if not undo_steps:
            return {"success": False, "message": "Keine Undo-Schritte vorhanden."}

        # Undo-Schritte in umgekehrter Reihenfolge ausfuehren
        executed = 0
        for step in reversed(undo_steps):
            try:
                await self.executor.execute(step.get("tool", ""), step.get("args", {}))
                executed += 1
            except Exception as e:
                logger.debug("Undo-Schritt fehlgeschlagen: %s", e)

        # Last-Executed Marker loeschen
        await self.redis.delete(f"{_PREFIX}:last_executed:{name_normalized}")

        title = get_person_title(person)
        return {
            "success": True,
            "message": f"Protokoll '{protocol.get('name', name)}' rueckgaengig gemacht, {title}.",
        }

    async def list_protocols(self) -> list[dict]:
        """Gibt alle gespeicherten Protokolle zurueck."""
        if not self.redis:
            return []

        members = await self.redis.smembers(_LIST_KEY)
        if not members:
            return []

        protocols = []
        for member in members:
            name = member.decode() if isinstance(member, bytes) else member
            raw = await self.redis.get(f"{_PREFIX}:{name}")
            if raw:
                try:
                    p = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                    protocols.append({
                        "name": p.get("name", name),
                        "steps": len(p.get("steps", [])),
                        "created_by": p.get("created_by", ""),
                        "description": p.get("description", ""),
                    })
                except (json.JSONDecodeError, AttributeError):
                    continue

        return protocols

    async def delete_protocol(self, name: str) -> dict:
        """Loescht ein Protokoll."""
        if not self.redis:
            return {"success": False, "message": "Redis nicht verfuegbar."}

        name_normalized = self._normalize_name(name)
        exists = await self.redis.exists(f"{_PREFIX}:{name_normalized}")
        if not exists:
            return {"success": False, "message": f"Protokoll '{name}' nicht gefunden."}

        await self.redis.delete(f"{_PREFIX}:{name_normalized}")
        await self.redis.srem(_LIST_KEY, name_normalized)

        return {"success": True, "message": f"Protokoll '{name}' geloescht."}

    async def detect_protocol_intent(self, text: str) -> Optional[str]:
        """Prueft ob der Text ein bekanntes Protokoll triggert.

        Args:
            text: User-Text

        Returns:
            Protokoll-Name (normalized) wenn Match, sonst None
        """
        if not self.enabled or not self.redis:
            return None

        members = await self.redis.smembers(_LIST_KEY)
        if not members:
            return None

        text_lower = text.lower().strip()
        # Entferne "jarvis" Prefix und gaeengige Trigger-Woerter
        for prefix in ["jarvis ", "hey jarvis ", "protokoll ", "starte ", "mach "]:
            if text_lower.startswith(prefix):
                text_lower = text_lower[len(prefix):].strip()

        for member in members:
            name = member.decode() if isinstance(member, bytes) else member
            if name in text_lower or text_lower == name:
                return name

        return None

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalisiert einen Protokoll-Namen."""
        # Lowercase, Umlaute ersetzen, Sonderzeichen entfernen
        name = name.lower().strip()
        name = name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        name = name.replace("ß", "ss")
        name = re.sub(r"[^a-z0-9_]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")
        return name[:50]

    async def _parse_steps(self, description: str) -> list[dict]:
        """Parst Schritte aus natuerlicher Beschreibung via LLM."""
        prompt = _PARSE_PROMPT.replace("{description}", description)

        try:
            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=yaml_config.get("models", {}).get("fast", "qwen3:4b"),
                temperature=0.1,
                max_tokens=512,
            )

            if "error" in response:
                logger.error("LLM Fehler bei Protokoll-Parsing: %s", response["error"])
                return []

            content = response.get("message", {}).get("content", "").strip()
            return self._extract_steps_json(content)
        except Exception as e:
            logger.error("Fehler bei Protokoll-Parsing: %s", e)
            return []

    @staticmethod
    def _extract_steps_json(text: str) -> list[dict]:
        """Extrahiert JSON-Array aus LLM-Antwort."""
        text = text.strip()
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return [s for s in result if isinstance(s, dict) and s.get("tool")]
            return []
        except json.JSONDecodeError:
            pass

        # Fallback: JSON-Array suchen
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, list):
                    return [s for s in result if isinstance(s, dict) and s.get("tool")]
            except json.JSONDecodeError:
                pass

        return []

    async def _snapshot_undo_steps(self, steps: list[dict]) -> list[dict]:
        """Snapshotten den aktuellen Zustand VOR Ausfuehrung fuer praezises Undo."""
        if not self.executor or not hasattr(self.executor, 'ha'):
            return []

        try:
            states = await self.executor.ha.get_states() or []
        except Exception:
            return []

        state_map = {s.get("entity_id"): s for s in states if s.get("entity_id")}
        undo = []

        for step in steps:
            tool = step.get("tool", "")
            args = step.get("args", {})
            entity_id = args.get("entity_id", "")

            # Entity aus Raum ableiten wenn noetig
            room = args.get("room", "")
            domain_map = {"set_light": "light", "set_climate": "climate",
                          "set_cover": "cover", "set_switch": "switch"}
            if not entity_id and room and tool in domain_map:
                prefix = domain_map[tool]
                entity_id = next(
                    (eid for eid in state_map if eid.startswith(f"{prefix}.") and room.lower() in eid.lower()),
                    "",
                )

            current = state_map.get(entity_id, {})
            attrs = current.get("attributes", {})
            current_state = current.get("state", "")

            if tool == "set_light" and current_state:
                undo_args = dict(args)
                undo_args["state"] = current_state
                if current_state == "on":
                    undo_args["brightness"] = attrs.get("brightness", 255)
                undo.append({"tool": "set_light", "args": undo_args})

            elif tool == "set_climate" and current_state:
                undo_args = dict(args)
                undo_args["temperature"] = attrs.get("temperature", 21)
                undo.append({"tool": "set_climate", "args": undo_args})

            elif tool == "set_cover" and current_state:
                undo_args = dict(args)
                undo_args["action"] = "close" if current_state == "open" else "open"
                undo.append({"tool": "set_cover", "args": undo_args})

            elif tool == "set_switch" and current_state:
                undo_args = dict(args)
                undo_args["state"] = current_state
                undo.append({"tool": "set_switch", "args": undo_args})

            elif tool == "play_media":
                undo_args = dict(args)
                undo_args["action"] = "stop"
                undo.append({"tool": "play_media", "args": undo_args})

        return undo

    @staticmethod
    def _generate_undo_steps(steps: list[dict]) -> list[dict]:
        """Generiert Fallback-Undo-Schritte (wenn kein HA-Snapshot moeglich)."""
        undo = []
        for step in steps:
            tool = step.get("tool", "")
            args = step.get("args", {})

            if tool == "set_light":
                undo_args = dict(args)
                # Licht war vorher an (default) → zuruecksetzen
                if args.get("state") == "off" or args.get("brightness", 100) < 50:
                    undo_args["state"] = "on"
                    undo_args["brightness"] = 80
                else:
                    undo_args["state"] = "off"
                undo.append({"tool": "set_light", "args": undo_args})

            elif tool == "set_cover":
                undo_args = dict(args)
                if args.get("action") == "close":
                    undo_args["action"] = "open"
                else:
                    undo_args["action"] = "close"
                undo.append({"tool": "set_cover", "args": undo_args})

            elif tool == "set_climate":
                # Temperatur auf Standard zuruecksetzen
                undo_args = dict(args)
                undo_args["temperature"] = 21
                undo.append({"tool": "set_climate", "args": undo_args})

            elif tool == "set_switch":
                undo_args = dict(args)
                if args.get("state") == "on":
                    undo_args["state"] = "off"
                else:
                    undo_args["state"] = "on"
                undo.append({"tool": "set_switch", "args": undo_args})

            elif tool == "play_media":
                undo_args = dict(args)
                undo_args["action"] = "stop"
                undo.append({"tool": "play_media", "args": undo_args})

        return undo
