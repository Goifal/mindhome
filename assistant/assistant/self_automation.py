"""
Self Automation - Jarvis erstellt HA-Automationen aus natuerlicher Sprache.

Phase 13.2: Automation-Generierung mit Sicherheitskonzept.
- LLM-basierte Uebersetzung: natuerliche Sprache -> HA-Automation
- Service/Domain-Whitelist (kein shell_command, kein script)
- Approval-Modus: Jarvis schlaegt vor, User bestaetigt
- Rate-Limiting: Max N Automationen pro Tag
- Audit-Log: Alles wird protokolliert
- Kill-Switch: Alle Jarvis-Automationen per Label deaktivierbar
- Template-Bibliothek fuer haeufige Muster
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import settings, yaml_config
from .ha_client import HomeAssistantClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# Config-Pfad fuer Templates
_CONFIG_DIR = Path(__file__).parent.parent / "config"
_TEMPLATES_PATH = _CONFIG_DIR / "automation_templates.yaml"

def _load_templates() -> dict:
    """Laedt die Automation-Templates und Security-Config."""
    if _TEMPLATES_PATH.exists():
        with open(_TEMPLATES_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


class SelfAutomation:
    """Generiert und verwaltet HA-Automationen aus natuerlicher Sprache."""

    def __init__(self, ha_client: HomeAssistantClient, ollama: OllamaClient):
        self.ha = ha_client
        self.ollama = ollama

        # Config laden
        self._cfg = yaml_config.get("self_automation", {})
        self._templates_cfg = _load_templates()
        self._security = self._templates_cfg.get("security", {})
        self._templates = self._templates_cfg.get("templates", {})

        # Security: Whitelists/Blacklists
        self._allowed_services = set(self._security.get("allowed_services", [
            "light.turn_on", "light.turn_off", "light.toggle",
            "switch.turn_on", "switch.turn_off", "switch.toggle",
            "climate.set_temperature", "climate.set_hvac_mode",
            "cover.open_cover", "cover.close_cover", "cover.set_cover_position",
            "media_player.media_play", "media_player.media_pause",
            "media_player.media_stop", "media_player.volume_set",
            "scene.turn_on",
            "notify.notify",
            "input_boolean.turn_on", "input_boolean.turn_off",
            "input_boolean.toggle",
            "input_number.set_value",
            "input_select.select_option",
        ]))
        self._blocked_services = set(self._security.get("blocked_services", [
            "shell_command", "script", "python_script",
            "rest_command", "homeassistant.restart",
            "homeassistant.stop", "homeassistant.reload_all",
            "automation.turn_off", "automation.turn_on",
            "automation.trigger", "automation.reload",
            "lock.unlock",
        ]))
        self._allowed_trigger_platforms = set(self._security.get("allowed_trigger_platforms", [
            "state", "time", "sun", "zone",
            "numeric_state", "template",
            "homeassistant",
        ]))

        # Rate-Limit
        self._max_per_day = self._cfg.get("max_per_day", 5)
        self._daily_count = 0
        self._daily_reset: Optional[datetime] = None

        # Pending Automations (warten auf Bestaetigung)
        self._pending: dict[str, dict] = {}

        # Audit-Log (In-Memory + Redis wenn verfuegbar)
        self._audit_log: list[dict] = []
        self._redis = None

    async def initialize(self, redis_client=None):
        """Initialisiert den Automation Manager."""
        self._redis = redis_client
        if self._redis:
            try:
                count = await self._redis.get("mha:automation:daily_count")
                if count:
                    self._daily_count = int(count)
            except Exception as e:
                logger.debug("Redis daily_count laden: %s", e)
        logger.info(
            "SelfAutomation initialisiert (Whitelist: %d Services, Blacklist: %d, "
            "Templates: %d, Limit: %d/Tag)",
            len(self._allowed_services),
            len(self._blocked_services),
            len(self._templates),
            self._max_per_day,
        )

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    async def generate_automation(
        self,
        description: str,
        person: str = "",
    ) -> dict:
        """
        Generiert eine HA-Automation aus natuerlicher Sprache.

        Gibt eine Vorschau zurueck die der User bestaetigen muss.

        Args:
            description: Natuerlichsprachliche Beschreibung
            person: Name des Anforderers

        Returns:
            Dict mit pending_id, preview, yaml_preview
        """
        # Rate-Limit pruefen
        if not self._check_rate_limit():
            return {
                "success": False,
                "message": f"Tageslimit erreicht ({self._max_per_day} Automationen pro Tag). "
                           "Morgen koennen wir weitermachen.",
            }

        # Template-Match versuchen (schnell, ohne LLM)
        template_match = await self._match_template(description)
        if template_match:
            automation = template_match
            generation_method = "template"
        else:
            # LLM-basierte Generierung
            automation = await self._generate_with_llm(description)
            if not automation:
                return {
                    "success": False,
                    "message": "Das konnte ich leider nicht in eine Automation umsetzen. "
                               "Versuche es mit einer klareren Beschreibung.",
                }
            generation_method = "llm"

        # Sicherheits-Validierung
        validation = self._validate_automation(automation)
        if not validation["valid"]:
            self._audit("blocked", description, person, automation, validation["reason"])
            return {
                "success": False,
                "message": f"Sicherheitscheck: {validation['reason']}",
            }

        # Pending-ID generieren
        pending_id = str(uuid.uuid4())[:8]

        # Automation-Metadaten anreichern
        automation["description"] = (
            f"Erstellt von {settings.assistant_name}: {description}"
        )
        automation.setdefault("mode", "single")
        # Kill-Switch Identifikation: Alle Jarvis-Automationen beginnen mit "jarvis_"
        # im automation_id (-> entity_id: automation.jarvis_*).
        # HA REST API unterstuetzt kein "labels"-Feld in der Automation-Config,
        # daher nutzen wir den Prefix-Ansatz.

        # Vorschau erstellen
        preview = self._build_preview(automation, description)
        yaml_preview = yaml.dump(
            automation, allow_unicode=True, default_flow_style=False, sort_keys=False,
        )

        # In Pending speichern
        self._pending[pending_id] = {
            "automation": automation,
            "description": description,
            "person": person,
            "created": datetime.now().isoformat(),
            "method": generation_method,
        }

        self._audit("proposed", description, person, automation)

        return {
            "success": True,
            "pending_id": pending_id,
            "preview": preview,
            "yaml_preview": yaml_preview,
            "message": (
                f"Ich wuerde Folgendes einrichten: {preview}. "
                f"Soll ich das aktivieren?"
            ),
        }

    async def confirm_automation(self, pending_id: str) -> dict:
        """
        Bestaetigt und deployed eine pending Automation.

        Args:
            pending_id: ID aus generate_automation

        Returns:
            Dict mit success, message, automation_id
        """
        pending = self._pending.pop(pending_id, None)
        if not pending:
            return {
                "success": False,
                "message": f"Keine ausstehende Automation mit ID '{pending_id}' gefunden.",
            }

        automation = pending["automation"]
        description = pending["description"]
        person = pending["person"]

        # HA Automation-ID generieren
        automation_id = f"jarvis_{pending_id}_{datetime.now().strftime('%Y%m%d')}"

        # Via HA REST API erstellen
        try:
            result = await self._deploy_to_ha(automation_id, automation)
            if result:
                self._increment_daily_count()
                self._audit("deployed", description, person, automation, automation_id=automation_id)
                alias = automation.get("alias", description)
                return {
                    "success": True,
                    "automation_id": automation_id,
                    "message": f"Eingerichtet. '{alias}' ist ab sofort aktiv.",
                }
            else:
                self._audit("deploy_failed", description, person, automation)
                return {
                    "success": False,
                    "message": "Die Automation konnte nicht in Home Assistant erstellt werden.",
                }
        except Exception as e:
            logger.error("Automation-Deploy fehlgeschlagen: %s", e)
            self._audit("deploy_error", description, person, automation, str(e))
            return {
                "success": False,
                "message": f"Fehler beim Erstellen: {e}",
            }

    async def list_jarvis_automations(self) -> dict:
        """Listet alle von Jarvis erstellten Automationen auf."""
        try:
            states = await self.ha.get_states()
            jarvis_automations = []

            for state in (states or []):
                entity_id = state.get("entity_id", "")
                if not entity_id.startswith("automation.jarvis_"):
                    continue

                attrs = state.get("attributes", {})
                jarvis_automations.append({
                    "entity_id": entity_id,
                    "alias": attrs.get("friendly_name", entity_id),
                    "state": state.get("state", "unknown"),
                    "last_triggered": attrs.get("last_triggered", "nie"),
                })

            if not jarvis_automations:
                return {
                    "success": True,
                    "automations": [],
                    "message": "Ich habe noch keine Automationen erstellt.",
                }

            lines = [f"{len(jarvis_automations)} Jarvis-Automation(en):"]
            for auto in jarvis_automations:
                status = "aktiv" if auto["state"] == "on" else "deaktiviert"
                lines.append(
                    f"- {auto['alias']} [{status}] "
                    f"(zuletzt: {auto['last_triggered']})"
                )

            return {
                "success": True,
                "automations": jarvis_automations,
                "message": "\n".join(lines),
            }
        except Exception as e:
            logger.error("Automationen auflisten fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Fehler: {e}"}

    async def delete_jarvis_automation(self, automation_id: str) -> dict:
        """Loescht eine von Jarvis erstellte Automation."""
        # Sicherheits-Check: Nur Jarvis-Automationen loeschbar
        if not automation_id.startswith("jarvis_"):
            return {
                "success": False,
                "message": "Nur von mir erstellte Automationen koennen geloescht werden.",
            }

        try:
            session = await self.ha._get_session()
            url = f"{self.ha.ha_url}/api/config/automation/config/{automation_id}"
            async with session.delete(url, headers=self.ha._ha_headers) as resp:
                if resp.status in (200, 204):
                    self._audit("deleted", automation_id, "", {})
                    return {
                        "success": True,
                        "message": f"Automation '{automation_id}' geloescht.",
                    }
                body = await resp.text()
                logger.warning("Automation loeschen: %d — %s", resp.status, body[:200])
                return {
                    "success": False,
                    "message": f"Loeschen fehlgeschlagen (HTTP {resp.status}).",
                }
        except Exception as e:
            logger.error("Automation loeschen fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Fehler: {e}"}

    async def disable_all_jarvis_automations(self) -> dict:
        """Kill-Switch: Deaktiviert alle Jarvis-Automationen."""
        states = await self.ha.get_states()
        disabled_count = 0

        for state in (states or []):
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("automation.jarvis_") and state.get("state") == "on":
                success = await self.ha.call_service(
                    "automation", "turn_off", {"entity_id": entity_id}
                )
                if success:
                    disabled_count += 1

        self._audit("kill_switch", f"Deaktiviert: {disabled_count}", "", {})

        if disabled_count == 0:
            return {
                "success": True,
                "message": "Keine aktiven Jarvis-Automationen gefunden.",
            }
        return {
            "success": True,
            "message": f"{disabled_count} Jarvis-Automation(en) deaktiviert.",
        }

    def get_pending_count(self) -> int:
        """Gibt die Anzahl ausstehender Automationen zurueck."""
        return len(self._pending)

    def health_status(self) -> str:
        """Status-String fuer Health-Check."""
        pending = len(self._pending)
        return (
            f"active (daily: {self._daily_count}/{self._max_per_day}, "
            f"pending: {pending}, templates: {len(self._templates)})"
        )

    # ------------------------------------------------------------------
    # LLM-basierte Generierung
    # ------------------------------------------------------------------

    async def _generate_with_llm(self, description: str) -> Optional[dict]:
        """Nutzt das LLM um eine Automation aus natuerlicher Sprache zu generieren."""
        # Entity-Liste holen fuer Kontext
        states = await self.ha.get_states()
        entity_examples = self._get_entity_examples(states)

        system_prompt = f"""Du bist ein Home Assistant Automation-Generator.
Erzeuge aus der Beschreibung eine HA-Automation als JSON.

VERFUEGBARE ENTITIES (Beispiele):
{entity_examples}

ERLAUBTE TRIGGER-PLATTFORMEN: {', '.join(sorted(self._allowed_trigger_platforms))}
ERLAUBTE SERVICES: {', '.join(sorted(self._allowed_services))}

FORMAT — antworte NUR mit validem JSON:
{{
  "alias": "Kurzer Name der Automation",
  "trigger": [
    {{"platform": "state|time|sun|zone|numeric_state", ...}}
  ],
  "condition": [],
  "action": [
    {{"service": "domain.service", "target": {{"entity_id": "..."}}, "data": {{}}}}
  ]
}}

REGELN:
- Nutze NUR erlaubte Services und Trigger-Plattformen
- entity_id muss zu den verfuegbaren Entities passen
- Alias auf Deutsch
- Keine shell_command, script oder python_script
- Keine lock.unlock Aktionen
- Kein JSON-Kommentar, nur reines JSON"""

        user_prompt = f"Erstelle eine Automation fuer: {description}"

        try:
            model = self._cfg.get("model", settings.model_smart)
            result = await self.ollama.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
                temperature=0.2,
                max_tokens=512,
            )

            content = result.get("message", {}).get("content", "")
            if not content:
                return None

            # JSON aus der Antwort extrahieren
            automation = self._extract_json(content)
            if not automation:
                return None

            # Minimale Struktur validieren
            if not isinstance(automation.get("trigger"), list):
                return None
            if not isinstance(automation.get("action"), list):
                return None
            if not automation.get("alias"):
                automation["alias"] = description[:60]

            return automation

        except Exception as e:
            logger.error("LLM Automation-Generierung fehlgeschlagen: %s", e)
            return None

    # ------------------------------------------------------------------
    # Template-Matching
    # ------------------------------------------------------------------

    async def _match_template(self, description: str) -> Optional[dict]:
        """Versucht die Beschreibung auf ein vordefiniertes Template zu matchen."""
        desc_lower = description.lower()

        for template_id, template in self._templates.items():
            triggers = template.get("match_keywords", [])
            if not triggers:
                continue

            # Alle Keywords muessen vorkommen
            if all(kw.lower() in desc_lower for kw in triggers):
                # Template klonen (deep copy um Original nicht zu aendern)
                import copy
                automation = {
                    "alias": template.get("alias", description[:60]),
                    "trigger": copy.deepcopy(template.get("trigger", [])),
                    "condition": copy.deepcopy(template.get("condition", [])),
                    "action": copy.deepcopy(template.get("action", [])),
                }

                # PLACEHOLDERs mit echten Entities aufloesen
                resolved = await self._resolve_placeholders(automation, desc_lower)
                if not resolved:
                    logger.warning(
                        "Template '%s' gematcht, aber PLACEHOLDERs konnten nicht aufgeloest werden",
                        template_id,
                    )
                    # Fallback auf LLM-Generierung
                    return None

                logger.info("Template-Match: '%s' -> %s", description, template_id)
                return automation

        return None

    async def _resolve_placeholders(self, automation: dict, description: str) -> bool:
        """Loest PLACEHOLDER in einem Template mit echten HA-Entities auf.

        Sucht passende Entities aus der HA-Installation anhand des Kontexts.
        Gibt False zurueck wenn ein Pflicht-Placeholder nicht aufgeloest werden konnte.
        """
        states = await self.ha.get_states()
        if not states:
            return False

        # Entity-Index aufbauen: domain -> [entity_id, ...]
        entity_index: dict[str, list[str]] = {}
        for s in states:
            eid = s.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            entity_index.setdefault(domain, []).append(eid)

        # Hauptperson aus Config
        main_person = settings.user_name.lower()
        main_person_entity = None
        for eid in entity_index.get("person", []):
            if main_person in eid.lower():
                main_person_entity = eid
                break
        # Fallback: Erste Person
        if not main_person_entity and entity_index.get("person"):
            main_person_entity = entity_index["person"][0]

        # Raumname aus Beschreibung extrahieren (einfache Keyword-Suche)
        room_hint = self._extract_room_hint(description)

        def resolve_entity(placeholder_entity: str) -> Optional[str]:
            """Loest eine einzelne entity_id mit PLACEHOLDER auf."""
            if "PLACEHOLDER" not in str(placeholder_entity):
                return placeholder_entity

            domain = placeholder_entity.split(".")[0] if "." in placeholder_entity else ""

            # person.PLACEHOLDER -> Hauptperson
            if domain == "person":
                return main_person_entity

            # Andere Domains: Raum-basierte Suche
            candidates = entity_index.get(domain, [])
            if not candidates:
                return None

            # Raum-Hint verwenden wenn vorhanden
            if room_hint:
                for eid in candidates:
                    if room_hint in eid.lower():
                        return eid

            # Fallback: Erste Entity der Domain
            return candidates[0] if candidates else None

        # Alle PLACEHOLDERs in trigger/condition/action aufloesen
        unresolved = False

        for section in ("trigger", "condition", "action"):
            for item in automation.get(section, []):
                for key, value in list(item.items()):
                    if isinstance(value, str) and "PLACEHOLDER" in value:
                        resolved = resolve_entity(value)
                        if resolved:
                            item[key] = resolved
                        else:
                            unresolved = True
                    # Auch in verschachtelten dicts (target, data)
                    elif isinstance(value, dict):
                        for sub_key, sub_value in list(value.items()):
                            if isinstance(sub_value, str) and "PLACEHOLDER" in sub_value:
                                resolved = resolve_entity(sub_value)
                                if resolved:
                                    value[sub_key] = resolved
                                else:
                                    unresolved = True

        return not unresolved

    @staticmethod
    def _extract_room_hint(description: str) -> str:
        """Extrahiert einen Raumnamen aus der Beschreibung."""
        room_keywords = {
            "wohnzimmer": "wohnzimmer",
            "schlafzimmer": "schlafzimmer",
            "kueche": "kueche",
            "küche": "kueche",
            "bad": "bad",
            "badezimmer": "bad",
            "buero": "buero",
            "büro": "buero",
            "flur": "flur",
            "kinderzimmer": "kinderzimmer",
            "keller": "keller",
            "garage": "garage",
            "garten": "garten",
            "terrasse": "terrasse",
            "balkon": "balkon",
            "esszimmer": "esszimmer",
        }
        desc_lower = description.lower()
        for keyword, room_id in room_keywords.items():
            if keyword in desc_lower:
                return room_id
        return ""

    # ------------------------------------------------------------------
    # Sicherheits-Validierung
    # ------------------------------------------------------------------

    def _validate_automation(self, automation: dict) -> dict:
        """Validiert eine Automation gegen Sicherheitsregeln."""
        # 1. Actions pruefen
        for action in automation.get("action", []):
            service = action.get("service", "")

            # Explizit geblockte Services
            service_domain = service.split(".")[0] if "." in service else service
            if service in self._blocked_services or service_domain in self._blocked_services:
                return {
                    "valid": False,
                    "reason": f"Service '{service}' ist aus Sicherheitsgruenden gesperrt.",
                }

            # Whitelist-Check (wenn Whitelist definiert)
            if self._allowed_services:
                # Pruefen ob Service oder Domain.* erlaubt
                domain_wildcard = f"{service_domain}.*"
                if service not in self._allowed_services and domain_wildcard not in self._allowed_services:
                    return {
                        "valid": False,
                        "reason": f"Service '{service}' ist nicht in der Whitelist.",
                    }

        # 2. Trigger pruefen
        for trigger in automation.get("trigger", []):
            platform = trigger.get("platform", "")
            if platform and platform not in self._allowed_trigger_platforms:
                return {
                    "valid": False,
                    "reason": f"Trigger-Plattform '{platform}' ist nicht erlaubt.",
                }

        # 3. Keine leeren Automationen
        if not automation.get("action"):
            return {"valid": False, "reason": "Automation hat keine Aktionen."}
        if not automation.get("trigger"):
            return {"valid": False, "reason": "Automation hat keinen Trigger."}

        return {"valid": True, "reason": ""}

    # ------------------------------------------------------------------
    # HA REST API Integration
    # ------------------------------------------------------------------

    async def _deploy_to_ha(self, automation_id: str, automation: dict) -> bool:
        """Erstellt eine Automation in HA via REST API."""
        session = await self.ha._get_session()
        url = f"{self.ha.ha_url}/api/config/automation/config/{automation_id}"

        try:
            async with session.put(
                url,
                headers=self.ha._ha_headers,
                json=automation,
            ) as resp:
                if resp.status in (200, 201):
                    logger.info("Automation '%s' deployed: %s", automation_id, automation.get("alias"))
                    return True
                body = await resp.text()
                logger.error(
                    "Automation deploy fehlgeschlagen: %d — %s",
                    resp.status, body[:300],
                )
                return False
        except Exception as e:
            logger.error("Automation deploy Fehler: %s", e)
            return False

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    def _build_preview(self, automation: dict, description: str) -> str:
        """Erstellt eine natuerlichsprachliche Vorschau der Automation (Jarvis-Stil)."""
        # Trigger natuerlich formulieren
        trigger_parts = []
        for t in automation.get("trigger", []):
            platform = t.get("platform", "")
            if platform == "state":
                entity = t.get("entity_id", "")
                to_state = t.get("to", "")
                trigger_parts.append(self._humanize_state_trigger(entity, to_state))
            elif platform == "time":
                at = t.get("at", "?")
                trigger_parts.append(f"taeglich um {at} Uhr")
            elif platform == "sun":
                event = t.get("event", "sunset")
                offset = t.get("offset", "")
                word = "Sonnenuntergang" if event == "sunset" else "Sonnenaufgang"
                if offset:
                    trigger_parts.append(f"bei {word} ({offset})")
                else:
                    trigger_parts.append(f"bei {word}")
            elif platform == "numeric_state":
                entity = t.get("entity_id", "")
                name = self._humanize_entity(entity)
                above = t.get("above")
                below = t.get("below")
                if above is not None:
                    trigger_parts.append(f"wenn {name} ueber {above} steigt")
                elif below is not None:
                    trigger_parts.append(f"wenn {name} unter {below} faellt")
            elif platform == "zone":
                event = t.get("event", "enter")
                zone = t.get("zone", "")
                zone_name = self._humanize_entity(zone)
                verb = "ankommt" if event == "enter" else "weggeht"
                trigger_parts.append(f"wenn jemand {zone_name} {verb}")

        # Actions natuerlich formulieren
        action_parts = []
        for a in automation.get("action", []):
            action_parts.append(self._humanize_action(a))

        # Zusammenbauen
        trigger_text = " und ".join(trigger_parts) if trigger_parts else description
        action_text = " und ".join(action_parts) if action_parts else "die entsprechende Aktion ausfuehren"

        return f"{trigger_text} — {action_text}"

    @staticmethod
    def _humanize_entity(entity_id: str) -> str:
        """Macht eine Entity-ID menschenlesbar: 'light.wohnzimmer' -> 'Wohnzimmer-Licht'."""
        if not entity_id or "." not in entity_id:
            return entity_id

        domain, name = entity_id.split(".", 1)
        name_clean = name.replace("_", " ").title()

        domain_labels = {
            "light": "Licht",
            "switch": "Schalter",
            "climate": "Thermostat",
            "cover": "Rolladen",
            "media_player": "Player",
            "sensor": "Sensor",
            "binary_sensor": "Sensor",
            "person": "",
            "scene": "Szene",
        }
        label = domain_labels.get(domain, "")
        if domain == "person":
            return name_clean
        if label:
            return f"{name_clean}-{label}"
        return name_clean

    @staticmethod
    def _humanize_state_trigger(entity_id: str, to_state: str) -> str:
        """Formuliert einen State-Trigger natuerlich."""
        if not entity_id:
            return "bei Zustandsaenderung"

        domain = entity_id.split(".")[0] if "." in entity_id else ""
        name = entity_id.split(".", 1)[1].replace("_", " ").title() if "." in entity_id else entity_id

        if domain == "person":
            if to_state == "home":
                return f"wenn {name} nach Hause kommt"
            elif to_state == "not_home":
                return f"wenn {name} das Haus verlaesst"
            return f"wenn {name} Status '{to_state}' hat"
        elif domain == "binary_sensor":
            if to_state == "on":
                return f"wenn {name} ausloest"
            return f"wenn {name} zuruecksetzt"

        return f"wenn {entity_id} zu '{to_state}' wechselt"

    @staticmethod
    def _humanize_action(action: dict) -> str:
        """Formuliert eine Action natuerlich."""
        service = action.get("service", "")
        target = action.get("target", {})
        entity = target.get("entity_id", "")
        data = action.get("data", {})

        # Entity-Name extrahieren
        if entity and entity != "all":
            entity_name = entity.split(".", 1)[1].replace("_", " ").title() if "." in entity else entity
        elif entity == "all":
            entity_name = "alle"
        else:
            entity_name = ""

        # Service natuerlich formulieren
        service_map = {
            "light.turn_on": f"{entity_name}-Licht einschalten",
            "light.turn_off": f"{entity_name}-Licht ausschalten",
            "light.toggle": f"{entity_name}-Licht umschalten",
            "switch.turn_on": f"{entity_name} einschalten",
            "switch.turn_off": f"{entity_name} ausschalten",
            "climate.set_temperature": f"{entity_name}-Thermostat",
            "climate.set_hvac_mode": f"{entity_name}-Heizmodus aendern",
            "cover.open_cover": f"{entity_name}-Rolladen hochfahren",
            "cover.close_cover": f"{entity_name}-Rolladen runterfahren",
            "cover.set_cover_position": f"{entity_name}-Rolladen positionieren",
            "media_player.media_play": f"Wiedergabe starten ({entity_name})",
            "media_player.media_pause": f"Wiedergabe pausieren ({entity_name})",
            "media_player.media_stop": f"Wiedergabe stoppen ({entity_name})",
            "scene.turn_on": f"Szene '{entity_name}' aktivieren",
            "notify.notify": "Benachrichtigung senden",
        }

        text = service_map.get(service, f"{service}")
        if entity == "all":
            text = text.replace("alle-Licht", "alle Lichter")
            text = text.replace("alle-Rolladen", "alle Rolladen")

        # Zusatzinfos aus Data
        if "temperature" in data:
            text += f" auf {data['temperature']}°C"
        if "brightness_pct" in data:
            text += f" ({data['brightness_pct']}%)"
        if "color_temp_kelvin" in data:
            kelvin = data["color_temp_kelvin"]
            if kelvin <= 3000:
                text += " (warmweiss)"
            elif kelvin >= 5500:
                text += " (kaltweiss)"

        return text

    def _get_entity_examples(self, states: list[dict], max_per_domain: int = 5) -> str:
        """Erstellt eine kompakte Entity-Liste fuer den LLM-Kontext."""
        if not states:
            return "(Keine Entities verfuegbar)"

        domains: dict[str, list[str]] = {}
        for s in states:
            entity_id = s.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else ""
            if domain in ("person", "light", "switch", "climate", "cover",
                          "media_player", "sensor", "binary_sensor", "scene",
                          "input_boolean", "input_number", "input_select", "zone"):
                domains.setdefault(domain, []).append(entity_id)

        lines = []
        for domain in sorted(domains):
            entities = domains[domain][:max_per_domain]
            lines.append(f"  {domain}: {', '.join(entities)}")

        return "\n".join(lines) if lines else "(Keine relevanten Entities)"

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extrahiert JSON aus einem LLM-Response (auch wenn drumherum Text steht)."""
        # Versuche zuerst den ganzen Text als JSON
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # JSON-Block suchen (```json ... ``` oder { ... })
        import re
        # Markdown Code-Block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # Erstes { ... } Paar
        brace_start = text.find("{")
        if brace_start != -1:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start:i + 1])
                        except (json.JSONDecodeError, TypeError):
                            pass
                        break
        return None

    def _check_rate_limit(self) -> bool:
        """Prueft ob das Tageslimit erreicht ist."""
        now = datetime.now()
        if self._daily_reset is None or now.date() > self._daily_reset.date():
            self._daily_count = 0
            self._daily_reset = now
        return self._daily_count < self._max_per_day

    def _increment_daily_count(self):
        """Erhoeht den Tages-Zaehler."""
        self._daily_count += 1
        if self._redis:
            import asyncio
            asyncio.create_task(self._save_daily_count())

    async def _save_daily_count(self):
        """Speichert den Tages-Zaehler in Redis."""
        try:
            key = "mha:automation:daily_count"
            await self._redis.set(key, self._daily_count)
            # Expire um Mitternacht (max 24h)
            await self._redis.expire(key, 86400)
        except Exception as e:
            logger.debug("Redis daily_count speichern: %s", e)

    def _audit(
        self,
        action: str,
        description: str,
        person: str,
        automation: dict,
        detail: str = "",
        automation_id: str = "",
    ):
        """Protokolliert eine Automation-Aktion im Audit-Log."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "description": description,
            "person": person,
            "automation_alias": automation.get("alias", "") if isinstance(automation, dict) else "",
            "detail": detail,
            "automation_id": automation_id,
        }
        self._audit_log.append(entry)
        # Log maximal 100 Eintraege behalten
        if len(self._audit_log) > 100:
            self._audit_log = self._audit_log[-100:]

        logger.info(
            "Automation-Audit [%s]: %s (Person: %s, Detail: %s)",
            action, description[:80], person or "?", detail[:80] if detail else "-",
        )

    def get_audit_log(self, limit: int = 20) -> list[dict]:
        """Gibt die letzten Audit-Log-Eintraege zurueck."""
        return self._audit_log[-limit:]
