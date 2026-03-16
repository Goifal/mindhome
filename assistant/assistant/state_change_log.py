"""
State Change Log — Trackt WARUM Geraete ihren Zustand aendern.

Jede State-Change wird mit Quelle geloggt:
- jarvis: JARVIS hat die Aktion ausgefuehrt (voice/chat command)
- automation: HA-Automation hat gefeuert
- user_physical: Physischer Schalter/App (manuell)
- unknown: Quelle nicht bestimmbar

Die letzten N Aenderungen werden im Ring-Buffer gehalten und
koennen dem LLM als Kontext mitgegeben werden.
"""

import json
import logging
import time
from collections import deque
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_KEY_LOG = "mha:state_change_log"
MAX_LOG_ENTRIES = 30
LOG_TTL_SECONDS = 6 * 3600  # 6 Stunden

# =========================================================================
# DEVICE DEPENDENCIES — Rollen-basiertes Matching via Entity Annotations
# =========================================================================
#
# WICHTIG: Diese Regeln steuern NICHTS. Sie geben JARVIS rein kognitives
# Verstaendnis darueber welche Geraetezustaende sich gegenseitig beeinflussen.
#
# Format:
#   "role":    Entity-Annotation-Rolle (aus entity_roles_defaults.yaml)
#   "state":   Zustand der die Regel triggert ("on", "heat", "playing", ...)
#   "affects": Betroffene Rolle ODER HA-Domain
#   "effect":  Beschreibung des Effekts
#   "hint":    Kurzer Hinweis fuer den LLM-Prompt
#   "same_room": (optional) True = Konflikt nur im selben Raum relevant
#
# Matching: Jede Entity wird ueber get_entity_annotation() ihrer Rolle
# zugeordnet. Dadurch matcht z.B. role="window_contact" ALLE Fensterkontakte
# unabhaengig von Benennung (binary_sensor.fenster_kueche, binary_sensor.wz_01, ...)
#
DEVICE_DEPENDENCIES = [

    # =====================================================================
    # 1. SICHERHEIT — RAUCH / GAS / CO / WASSER / EINBRUCH (immer aktiv)
    # =====================================================================
    {
        "role": "smoke", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Rauchmelder ausgeloest → Alarm sollte aktiv sein",
        "hint": "Rauch erkannt → ALARM",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "light", "same_room": False,
        "effect": "Rauchmelder → alle Lichter an fuer Fluchtweg",
        "hint": "Rauch → Beleuchtung fuer Fluchtweg einschalten",
    },
    {
        "role": "smoke", "state": "on",
        "affects": "blinds", "same_room": False,
        "effect": "Rauchmelder → Rolllaeden hoch fuer Fluchtweg",
        "hint": "Rauch → Rolllaeden oeffnen fuer Fluchtweg",
    },
    {
        "role": "co", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Kohlenmonoxid erkannt → LEBENSGEFAHRLICH",
        "hint": "CO erkannt → SOFORT ALARM, Fenster oeffnen, Haus verlassen",
    },
    {
        "role": "co", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "CO erkannt → Lueftung auf Maximum",
        "hint": "CO → maximale Belueftung noetig",
    },
    {
        "role": "gas", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Gas erkannt → Explosionsgefahr",
        "hint": "Gas erkannt → SOFORT ALARM, kein Funke, Haus verlassen",
    },
    {
        "role": "water_leak", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Wasserleck erkannt → sofort handeln",
        "hint": "Wasserleck → ALARM, Hauptventil schliessen",
    },
    {
        "role": "tamper", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Sabotage-Kontakt ausgeloest → Geraet manipuliert",
        "hint": "Sabotage erkannt → Geraet wurde manipuliert",
    },
    {
        "role": "oven", "state": "on",
        "affects": "alarm", "same_room": False,
        "effect": "Herd an + niemand in Kueche → Brandgefahr",
        "hint": "Herd an → Brandgefahr wenn unbeaufsichtigt",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "light", "same_room": False,
        "effect": "Alarm ausgeloest → alle Lichter an zur Abschreckung",
        "hint": "ALARM AUSGELOEST → alle Lichter an",
    },
    {
        "role": "alarm", "state": "triggered",
        "affects": "notify", "same_room": False,
        "effect": "Alarm ausgeloest → sofort benachrichtigen",
        "hint": "ALARM → sofortige Benachrichtigung",
    },

    # =====================================================================
    # 2. SICHERHEIT — nur bei scharfem Alarm (requires_state)
    # =====================================================================
    {
        "role": "window_contact", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Fenster offen bei Abwesenheit → Einbruchsrisiko",
        "hint": "Fenster offen → Sicherheitsrisiko bei Abwesenheit",
    },
    {
        "role": "door_contact", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Tuer offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Haustuer steht offen → Sicherheit pruefen",
    },
    {
        "role": "garage_door", "state": "open",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Garagentor offen → Sicherheitsrisiko",
        "hint": "Garage offen → Sicherheit pruefen",
    },
    {
        "role": "gate", "state": "open",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Tor offen → ungesicherter Zugang zum Grundstueck",
        "hint": "Tor offen → Grundstueck nicht gesichert",
    },
    {
        "role": "motion", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Bewegung bei aktivem Alarm → moeglicher Einbruch",
        "hint": "Bewegung bei scharfem Alarm → Einbruch-Warnung",
    },
    {
        "role": "vibration", "state": "on",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Vibration erkannt → Einbruchsversuch moeglich",
        "hint": "Vibration an Tuer/Fenster → Einbruchsversuch?",
    },
    {
        "role": "lock", "state": "unlocked",
        "affects": "alarm", "same_room": False,
        "requires_state": {"armed_away", "armed_night"},
        "effect": "Schloss offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Tuer nicht abgeschlossen → Sicherheit pruefen",
    },

    # =====================================================================
    # 3. ENERGIEVERSCHWENDUNG — widersprüchliche Zustaende
    # =====================================================================
    {
        "role": "thermostat", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Thermostat heizt + Fenster offen → Energieverschwendung",
        "hint": "Heizung an + Fenster offen → Energie wird verschwendet",
    },
    {
        "role": "floor_heating", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Fussbodenheizung + Fenster offen → viel Energieverlust",
        "hint": "Fussbodenheizung → Fenster kurz lueften, nicht kippen",
    },
    {
        "role": "radiator", "state": "heat",
        "affects": "window_contact", "same_room": True,
        "effect": "Heizkoerper heizt + Fenster offen → Energieverschwendung",
        "hint": "Heizkoerper an + Fenster offen → Energie geht verloren",
    },
    {
        "role": "rain", "state": "on",
        "affects": "irrigation", "same_room": False,
        "effect": "Regen → Bewaesserung unnoetig, Wasserverschwendung",
        "hint": "Es regnet → Bewaesserung stoppen",
    },

    # =====================================================================
    # 4. SCHADENSPRAEVENTION — Wetter / Wind / Regen
    # =====================================================================
    {
        "role": "wind_speed", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Starker Wind → Markise einfahren, Beschaedigungsgefahr",
        "hint": "Wind stark → Markise/Sonnensegel einfahren",
    },
    {
        "role": "rain", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Regen → Dachfenster und offene Fenster pruefen",
        "hint": "Es regnet → Fenster pruefen, Dachfenster schliessen",
    },
    {
        "role": "rain", "state": "on",
        "affects": "awning", "same_room": False,
        "effect": "Regen → Markise einfahren",
        "hint": "Regen → Markise einfahren",
    },
    {
        "role": "rain_sensor", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Regen erkannt → offene Fenster schliessen",
        "hint": "Regensensor → Fenster pruefen",
    },

    # =====================================================================
    # 5. GESUNDHEIT — Luftqualitaet / Schimmel / Radon
    # =====================================================================
    {
        "role": "co2", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "CO2-Wert hoch → dringend lueften",
        "hint": "CO2 hoch → Fenster oeffnen oder Lueftung verstaerken",
    },
    {
        "role": "voc", "state": "on",
        "affects": "ventilation", "same_room": True,
        "effect": "VOC hoch → Schadstoffe in der Luft, lueften",
        "hint": "VOC hoch → Lueften, Schadstoffe in der Luft",
    },
    {
        "role": "pm25", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Feinstaub hoch draussen → Fenster geschlossen halten",
        "hint": "Feinstaub draussen hoch → Fenster zu, Luftreiniger an",
    },
    {
        "role": "pm10", "state": "on",
        "affects": "window_contact", "same_room": False,
        "effect": "Grobstaub hoch → Fenster geschlossen halten",
        "hint": "Feinstaub hoch → Fenster zu lassen",
    },
    {
        "role": "dew_point", "state": "on",
        "affects": "climate", "same_room": True,
        "effect": "Taupunkt erreicht → Schimmelgefahr",
        "hint": "Taupunkt → Schimmelgefahr, heizen oder lueften",
    },
    {
        "role": "radon", "state": "on",
        "affects": "ventilation", "same_room": False,
        "effect": "Radon-Wert hoch → Gesundheitsgefahr, sofort lueften",
        "hint": "Radon hoch → DRINGEND lueften, Gesundheitsgefahr",
    },

    # =====================================================================
    # 6. FEHLALARM-VERMEIDUNG — Vacuum / Saugroboter
    # =====================================================================
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "motion", "same_room": True,
        "effect": "Saugroboter kann Bewegungsmelder ausloesen",
        "hint": "Saugroboter aktiv → Bewegungsmelder ignorieren",
    },
    {
        "role": "vacuum", "state": "cleaning",
        "affects": "alarm", "same_room": False,
        "effect": "Saugroboter loest Bewegungsmelder aus → kein Einbruch",
        "hint": "Saugroboter aktiv → Fehlalarm vermeiden",
    },

    # =====================================================================
    # 7. INFRASTRUKTUR — Netz-Ueberlast
    # =====================================================================
    {
        "role": "ev_charger", "state": "on",
        "affects": "heat_pump", "same_room": False,
        "effect": "Wallbox + Waermepumpe gleichzeitig → Netzueberlast moeglich",
        "hint": "Wallbox laedt + Waermepumpe → Sicherung/Netzueberlast pruefen",
    },
]



class StateChangeLog:
    """Protokolliert Geraete-Aenderungen mit Quellen-Erkennung."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._log: deque[dict] = deque(maxlen=MAX_LOG_ENTRIES)
        # Jarvis-Marker: Entity-IDs die JARVIS gerade aendert (TTL 10s)
        self._jarvis_pending: dict[str, float] = {}

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        # Bestehende Eintraege laden
        if self.redis:
            try:
                raw = await self.redis.lrange(REDIS_KEY_LOG, 0, MAX_LOG_ENTRIES - 1)
                for entry in reversed(raw):
                    try:
                        self._log.append(json.loads(entry))
                    except (json.JSONDecodeError, TypeError):
                        pass
            except Exception as e:
                logger.debug("State-Change-Log laden fehlgeschlagen: %s", e)
        logger.info("StateChangeLog initialisiert (%d Eintraege)", len(self._log))

    def mark_jarvis_action(self, entity_id: str):
        """Markiert dass JARVIS gleich eine Aktion auf dieser Entity ausfuehrt."""
        self._jarvis_pending[entity_id] = time.time()

    def _detect_source(self, entity_id: str, new_state: dict) -> str:
        """Erkennt die Quelle einer State-Change.

        Nutzt:
        - Jarvis-Marker (mark_jarvis_action)
        - HA context.user_id (None = Automation, vorhanden = User/API)
        - HA context.parent_id (vorhanden = durch andere Automation ausgeloest)
        """
        # Jarvis-Marker pruefen (10s Fenster)
        jarvis_ts = self._jarvis_pending.pop(entity_id, None)
        if jarvis_ts and (time.time() - jarvis_ts) < 10:
            return "jarvis"

        # HA Context auswerten
        ha_context = new_state.get("context", {})
        if isinstance(ha_context, dict):
            user_id = ha_context.get("user_id")
            parent_id = ha_context.get("parent_id")

            if parent_id:
                # Durch eine andere Automation/Script ausgeloest
                return "automation"
            if user_id:
                # User-Aktion (App, Dashboard, API)
                return "user_app"
            # Kein user_id, kein parent_id → physischer Trigger oder HA-interne Automation
            return "automation"

        return "unknown"

    async def log_change(
        self, entity_id: str, old_val: str, new_val: str,
        new_state: dict, friendly_name: str = "",
    ):
        """Loggt eine State-Change mit Quellen-Erkennung."""
        source = self._detect_source(entity_id, new_state)
        name = friendly_name or new_state.get("attributes", {}).get(
            "friendly_name", entity_id
        )

        entry = {
            "entity_id": entity_id,
            "name": name,
            "old": old_val,
            "new": new_val,
            "source": source,
            "ts": time.time(),
            "time_str": time.strftime("%H:%M"),
        }

        self._log.append(entry)

        # In Redis persistieren
        if self.redis:
            try:
                await self.redis.lpush(
                    REDIS_KEY_LOG,
                    json.dumps(entry, ensure_ascii=False),
                )
                await self.redis.ltrim(REDIS_KEY_LOG, 0, MAX_LOG_ENTRIES - 1)
                await self.redis.expire(REDIS_KEY_LOG, LOG_TTL_SECONDS)
            except Exception as e:
                logger.debug("State-Change-Log Redis-Fehler: %s", e)

    def get_recent(self, n: int = 10, domain: str = "") -> list[dict]:
        """Gibt die letzten N State-Changes zurueck.

        Args:
            n: Anzahl (default 10)
            domain: Optional filtern nach Domain (light, climate, etc.)
        """
        if domain:
            filtered = [
                e for e in self._log
                if e.get("entity_id", "").startswith(f"{domain}.")
            ]
            return list(filtered)[-n:]
        return list(self._log)[-n:]

    @staticmethod
    def _get_entity_role(entity_id: str) -> str:
        """Holt die Annotation-Rolle fuer eine Entity.

        Lazy-Import um zirkulaere Imports zu vermeiden.
        Faellt auf HA-Domain zurueck wenn keine Annotation vorhanden.
        """
        try:
            from .function_calling import get_entity_annotation
            ann = get_entity_annotation(entity_id)
            if ann and ann.get("role"):
                return ann["role"]
        except Exception:
            pass
        # Fallback: HA-Domain als Pseudo-Rolle (z.B. "light", "climate")
        return entity_id.split(".")[0] if "." in entity_id else ""

    @staticmethod
    def _get_entity_room(entity_id: str) -> str:
        """Holt den Raum fuer eine Entity aus Annotations oder MindHome.

        Lazy-Import um zirkulaere Imports zu vermeiden.
        """
        try:
            from .function_calling import get_entity_annotation, _mindhome_device_rooms
            ann = get_entity_annotation(entity_id)
            if ann and ann.get("room"):
                return ann["room"].lower()
            # Fallback: MindHome Device-Room-Mapping
            if _mindhome_device_rooms and entity_id in _mindhome_device_rooms:
                return _mindhome_device_rooms[entity_id].lower()
        except Exception:
            pass
        return ""

    def detect_conflicts(self, states: dict) -> list[dict]:
        """Prueft aktuelle HA-States gegen DEVICE_DEPENDENCIES.

        Nutzt Entity-Annotation-Rollen fuer praezises Matching.
        Beruecksichtigt Raum-Zuordnung fuer same_room-Regeln.

        Args:
            states: Dict entity_id -> state-string (z.B. "on", "heat", "open")

        Returns:
            Liste aktiver Konflikte mit Hinweisen fuers LLM.
        """
        # Entity-Rollen und Raeume einmalig cachen
        entity_roles: dict[str, str] = {}
        entity_rooms: dict[str, str] = {}
        for eid in states:
            entity_roles[eid] = self._get_entity_role(eid)
            entity_rooms[eid] = self._get_entity_room(eid)

        conflicts = []
        for dep in DEVICE_DEPENDENCIES:
            cond_role = dep["role"]
            cond_state = dep["state"]
            same_room = dep.get("same_room", False)

            # Finde alle Entities die diese Rolle + State haben
            matching = [
                eid for eid, st in states.items()
                if entity_roles.get(eid) == cond_role and st == cond_state
            ]
            if not matching:
                continue

            # Betroffene Rolle/Domain
            affected = dep["affects"]
            required_states = dep.get("requires_state")

            # Pruefen ob betroffene Rolle/Domain aktiv ist
            # Matcht sowohl gegen Rollen als auch HA-Domains
            for trigger_eid in matching:
                trigger_room = entity_rooms.get(trigger_eid, "")

                affected_active = False
                for eid, val in states.items():
                    if val in ("off", "unavailable", "unknown", "idle"):
                        continue
                    eid_role = entity_roles.get(eid, "")
                    eid_domain = eid.split(".")[0] if "." in eid else ""

                    # Match gegen Rolle ODER Domain
                    if eid_role != affected and eid_domain != affected:
                        continue

                    # requires_state: Nur Konflikt wenn Entity in passendem State
                    if required_states and val not in required_states:
                        continue

                    # same_room Check
                    if same_room and trigger_room:
                        eid_room = entity_rooms.get(eid, "")
                        if eid_room and eid_room != trigger_room:
                            continue

                    affected_active = True
                    break

                conflicts.append({
                    "trigger_entity": trigger_eid,
                    "trigger_role": cond_role,
                    "trigger_state": cond_state,
                    "trigger_room": trigger_room,
                    "affected_role": affected,
                    "affected_active": affected_active,
                    "same_room": same_room,
                    "effect": dep["effect"],
                    "hint": dep["hint"],
                })
        return conflicts

    def format_conflicts_for_prompt(self, states: dict) -> str:
        """Formatiert aktive Geraete-Konflikte als LLM-Kontext.

        Args:
            states: Dict entity_id -> state-string

        Returns:
            Prompt-Sektion oder leerer String.
        """
        conflicts = self.detect_conflicts(states)
        if not conflicts:
            return ""

        # Nur Konflikte wo betroffene Domain/Rolle aktiv ist (echte Konflikte)
        active_conflicts = [c for c in conflicts if c["affected_active"]]
        if not active_conflicts:
            return ""

        # F-090: Sanitization — Room-Namen und Hints koennen aus
        # Annotations/HA stammen → Prompt-Injection verhindern
        try:
            from .context_builder import _sanitize_for_prompt
        except ImportError:
            _sanitize_for_prompt = None

        lines = []
        seen = set()
        for c in active_conflicts:
            # Raum-Info in Hinweis einbauen wenn vorhanden
            room = c.get("trigger_room", "")
            if room and _sanitize_for_prompt:
                room = _sanitize_for_prompt(room, 50, "conflict_room")
            room_info = f" [{room}]" if room else ""
            hint = c.get("hint", "")
            effect = c.get("effect", "")
            if _sanitize_for_prompt:
                hint = _sanitize_for_prompt(hint, 200, "conflict_hint")
                effect = _sanitize_for_prompt(effect, 200, "conflict_effect")
            if not hint:
                continue
            key = (c["trigger_entity"], c["affected_role"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {hint}{room_info} ({effect})")

        if not lines:
            return ""

        return (
            "\n\nAKTIVE GERAETE-KONFLIKTE (rein informativ):\n"
            + "\n".join(lines)
            + "\nWeise den User beilaeufig auf diese Konflikte hin, "
            "wenn er nach Energie, Heizung oder Raumklima fragt. "
            "WICHTIG: Diese Konflikte sind nur Hinweise — verweigere "
            "NIEMALS eine Aktion des Users wegen eines Konflikts."
        )

    @staticmethod
    def check_action_dependencies(
        action_function: str,
        action_args: dict,
        ha_states: list[dict],
    ) -> list[str]:
        """Prueft ob eine geplante Aktion Device-Dependency-Konflikte ausloest.

        Wiederverwendbare Methode fuer alle Module (action_planner, protocol_engine,
        conflict_resolver, self_automation, conditional_commands).

        Args:
            action_function: Funktionsname (z.B. "set_climate", "set_light")
            action_args: Argumente der Funktion
            ha_states: Aktuelle HA-States als Liste von State-Dicts

        Returns:
            Liste von Hinweis-Strings. Leer wenn keine Konflikte.
        """
        hints = []
        try:
            state_dict = {
                s["entity_id"]: s.get("state", "")
                for s in ha_states
                if "entity_id" in s
            }
            # Hypothetischen neuen State eintragen
            target_entity = action_args.get("entity_id", "")
            new_state_val = action_args.get("state", action_args.get("action", ""))
            if target_entity and new_state_val:
                state_dict[target_entity] = str(new_state_val).lower()

            scl = StateChangeLog.__new__(StateChangeLog)
            conflicts = scl.detect_conflicts(state_dict)

            if target_entity and conflicts:
                relevant = [
                    c for c in conflicts
                    if target_entity in c.get("entities", [])
                ]
                for c in relevant[:3]:
                    room_info = f" ({c.get('room', '')})" if c.get("room") else ""
                    hints.append(f"{c['hint']}{room_info}")
            elif not target_entity and conflicts:
                # Ohne target_entity: Domain-basiert filtern
                domain = action_function.replace("set_", "").replace("_room", "")
                relevant = [
                    c for c in conflicts
                    if domain in c.get("affected_role", "") or domain in c.get("trigger_role", "")
                ]
                for c in relevant[:3]:
                    room_info = f" ({c.get('room', '')})" if c.get("room") else ""
                    hints.append(f"{c['hint']}{room_info}")
        except Exception as e:
            logger.debug("check_action_dependencies Fehler: %s", e)
        return hints

    def format_for_prompt(self, n: int = 10) -> str:
        """Formatiert die letzten Aenderungen als LLM-Kontext.

        Returns:
            Prompt-Sektion oder leerer String.
        """
        recent = self.get_recent(n)
        if not recent:
            return ""

        # Nur Aenderungen der letzten 30 Minuten
        cutoff = time.time() - 1800
        recent = [e for e in recent if e.get("ts", 0) > cutoff]
        if not recent:
            return ""

        source_labels = {
            "jarvis": "JARVIS",
            "automation": "HA-Automation",
            "user_app": "User (App/Dashboard)",
            "user_physical": "User (physisch)",
            "unknown": "unbekannt",
        }

        lines = []
        for e in recent:
            source = source_labels.get(e.get("source", ""), e.get("source", "?"))
            name = e.get("name", e.get("entity_id", "?"))
            lines.append(
                f"- {e.get('time_str', '?')}: {name} "
                f"{e.get('old', '?')} → {e.get('new', '?')} "
                f"(Quelle: {source})"
            )

        return (
            "\n\nLETZTE GERAETE-AENDERUNGEN:\n"
            + "\n".join(lines)
            + "\nNutze diese Info um zu erklaeren warum Geraete ihren "
            "Zustand geaendert haben, wenn der User danach fragt."
        )

    @staticmethod
    def format_automations_for_prompt(automation_states: list[dict]) -> str:
        """Formatiert HA-Automationen als LLM-Kontext.

        Gibt dem LLM Wissen darueber welche Automationen existieren und
        kuerzlich ausgeloest wurden, damit es erklaeren kann warum
        Geraete ihren Zustand geaendert haben.

        Args:
            automation_states: Liste von HA-State-Dicts fuer automation.*

        Returns:
            Prompt-Sektion oder leerer String.
        """
        if not automation_states:
            return ""

        lines = []
        recently_triggered = []
        now = time.time()

        for auto in automation_states:
            entity_id = auto.get("entity_id", "")
            if not entity_id.startswith("automation."):
                continue

            attrs = auto.get("attributes", {})
            friendly = attrs.get("friendly_name", entity_id)
            state = auto.get("state", "off")
            last_triggered = attrs.get("last_triggered", "")

            # Kuerzlich ausgeloest? (letzte 30 Min)
            is_recent = False
            if last_triggered:
                try:
                    from datetime import datetime, timezone
                    if isinstance(last_triggered, str) and last_triggered:
                        # ISO-Format parsen
                        _lt = last_triggered.replace("Z", "+00:00")
                        _dt = datetime.fromisoformat(_lt)
                        _age = now - _dt.timestamp()
                        if _age < 1800:  # 30 Min
                            is_recent = True
                            recently_triggered.append(
                                f"- {friendly} (vor {int(_age // 60)} Min)"
                            )
                except (ValueError, TypeError, OSError):
                    pass

            if state == "on" and not is_recent:
                lines.append(f"- {friendly} (aktiv)")

        if not lines and not recently_triggered:
            return ""

        parts = []
        if recently_triggered:
            parts.append(
                "Kuerzlich ausgeloeste Automationen:\n"
                + "\n".join(recently_triggered)
            )
        if lines and len(lines) <= 15:
            # Nur anzeigen wenn nicht zu viele (sonst Token-Verschwendung)
            parts.append(
                "Aktive Automationen:\n"
                + "\n".join(lines)
            )

        return (
            "\n\nHA-AUTOMATIONEN:\n"
            + "\n".join(parts)
            + "\nNutze diese Info um zu erklaeren welche Automation "
            "eine Geraete-Aenderung ausgeloest haben koennte."
        )
