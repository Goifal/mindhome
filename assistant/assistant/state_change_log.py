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

# Geraete-Abhaengigkeiten: Welche Zustaende sich gegenseitig beeinflussen
# Prefix-Match: "binary_sensor.fenster" matcht auch "binary_sensor.fenster_kueche"
DEVICE_DEPENDENCIES = [
    # === FENSTER / TUEREN → KLIMA ===
    {
        "condition": ("binary_sensor.fenster", "on"),
        "affects": "climate",
        "effect": "Heizung/Kuehlung ineffizient bei offenem Fenster",
        "hint": "Fenster offen → Heizenergie geht verloren",
    },
    {
        "condition": ("binary_sensor.window", "on"),
        "affects": "climate",
        "effect": "Heizung/Kuehlung ineffizient bei offenem Fenster",
        "hint": "Fenster offen → Heizenergie geht verloren",
    },
    {
        "condition": ("binary_sensor.tuer", "on"),
        "affects": "climate",
        "effect": "Waermeverlust durch offene Tuer",
        "hint": "Tuer offen → beeinflusst Raumtemperatur",
    },
    {
        "condition": ("binary_sensor.door", "on"),
        "affects": "climate",
        "effect": "Waermeverlust durch offene Tuer",
        "hint": "Tuer offen → beeinflusst Raumtemperatur",
    },
    # === ROLLLADEN → KLIMA / LICHT ===
    {
        "condition": ("cover.", "open"),
        "affects": "climate",
        "effect": "Sonneneinstrahlung erhoeht Raumtemperatur / Waermeverlust nachts",
        "hint": "Rollladen offen → beeinflusst Raumklima",
    },
    {
        "condition": ("cover.", "closed"),
        "affects": "light",
        "effect": "Kein Tageslicht bei geschlossenem Rollladen",
        "hint": "Rollladen zu → Kunstlicht noetig",
    },
    # === KLIMA → ENERGIE ===
    {
        "condition": ("climate.", "heat"),
        "affects": "energy",
        "effect": "Hoher Energieverbrauch durch aktive Heizung",
        "hint": "Heizung aktiv → Energieverbrauch steigt",
    },
    {
        "condition": ("climate.", "cool"),
        "affects": "energy",
        "effect": "Hoher Energieverbrauch durch aktive Kuehlung",
        "hint": "Kuehlung aktiv → Energieverbrauch steigt",
    },
    {
        "condition": ("climate.", "heat_cool"),
        "affects": "energy",
        "effect": "Hoher Energieverbrauch durch aktive Klimaanlage",
        "hint": "Klimaanlage aktiv → Energieverbrauch steigt",
    },
    # === LICHT → ENERGIE ===
    {
        "condition": ("light.", "on"),
        "affects": "energy",
        "effect": "Stromverbrauch durch Beleuchtung",
        "hint": "Licht an → Stromverbrauch",
    },
    # === PRAESENZ → LICHT / KLIMA / MEDIA ===
    {
        "condition": ("binary_sensor.motion", "on"),
        "affects": "light",
        "effect": "Bewegung erkannt → Licht koennte automatisch geschaltet werden",
        "hint": "Bewegung → Licht-Automation moeglich",
    },
    {
        "condition": ("binary_sensor.presence", "off"),
        "affects": "climate",
        "effect": "Niemand zuhause → Heizung/Kuehlung unnoetig",
        "hint": "Abwesend → Energie sparen moeglich",
    },
    {
        "condition": ("binary_sensor.presence", "off"),
        "affects": "light",
        "effect": "Niemand zuhause → Licht unnoetig",
        "hint": "Abwesend → Licht sollte aus sein",
    },
    {
        "condition": ("binary_sensor.presence", "off"),
        "affects": "media_player",
        "effect": "Niemand zuhause → Medien unnoetig",
        "hint": "Abwesend → Medien sollten aus sein",
    },
    {
        "condition": ("binary_sensor.occupancy", "off"),
        "affects": "light",
        "effect": "Raum leer → Licht unnoetig",
        "hint": "Raum leer → Licht verschwenden",
    },
    {
        "condition": ("binary_sensor.occupancy", "off"),
        "affects": "climate",
        "effect": "Raum leer → Heizung/Kuehlung unnoetig",
        "hint": "Raum leer → Energie sparen moeglich",
    },
    # === PERSON HOME/AWAY → SICHERHEIT / ENERGIE ===
    {
        "condition": ("person.", "not_home"),
        "affects": "light",
        "effect": "Person nicht zuhause → Licht brennt unnoetig",
        "hint": "Niemand da → Licht sollte aus sein",
    },
    {
        "condition": ("person.", "not_home"),
        "affects": "climate",
        "effect": "Person nicht zuhause → Energie-Verschwendung",
        "hint": "Niemand da → Heizung runterdrehen",
    },
    # === SICHERHEIT ===
    {
        "condition": ("binary_sensor.smoke", "on"),
        "affects": "alarm_control_panel",
        "effect": "Rauchmelder ausgeloest → Alarm sollte aktiv sein",
        "hint": "Rauch erkannt → ALARM",
    },
    {
        "condition": ("binary_sensor.rauch", "on"),
        "affects": "alarm_control_panel",
        "effect": "Rauchmelder ausgeloest → Alarm sollte aktiv sein",
        "hint": "Rauch erkannt → ALARM",
    },
    {
        "condition": ("binary_sensor.water_leak", "on"),
        "affects": "alarm_control_panel",
        "effect": "Wasserleck erkannt → sofort handeln",
        "hint": "Wasserleck → ALARM",
    },
    {
        "condition": ("binary_sensor.leck", "on"),
        "affects": "alarm_control_panel",
        "effect": "Wasserleck erkannt → sofort handeln",
        "hint": "Wasserleck → ALARM",
    },
    # === MEDIEN → LICHT ===
    {
        "condition": ("media_player.", "playing"),
        "affects": "light",
        "effect": "Medien spielen → Kino-Modus (Licht dimmen) sinnvoll",
        "hint": "Film/Musik laeuft → Licht anpassen",
    },
    # === WASCHMASCHINE / TROCKNER → BENACHRICHTIGUNG ===
    {
        "condition": ("sensor.wasch", "idle"),
        "affects": "notify",
        "effect": "Waschmaschine fertig → Waesche rausholen",
        "hint": "Waschmaschine fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.trockner", "idle"),
        "affects": "notify",
        "effect": "Trockner fertig → Waesche rausholen",
        "hint": "Trockner fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.dryer", "idle"),
        "affects": "notify",
        "effect": "Trockner fertig → Waesche rausholen",
        "hint": "Trockner fertig → User benachrichtigen",
    },
    {
        "condition": ("sensor.washer", "idle"),
        "affects": "notify",
        "effect": "Waschmaschine fertig → Waesche rausholen",
        "hint": "Waschmaschine fertig → User benachrichtigen",
    },
    # === STAUBSAUGER → PRAESENZ ===
    {
        "condition": ("vacuum.", "cleaning"),
        "affects": "binary_sensor",
        "effect": "Staubsauger kann Bewegungsmelder ausloesen",
        "hint": "Saugroboter aktiv → Bewegungsmelder ignorieren",
    },
    # === TEMPERATUR → KLIMA ===
    {
        "condition": ("binary_sensor.cold", "on"),
        "affects": "climate",
        "effect": "Frost-Warnung → Heizung sicherstellen",
        "hint": "Frost → Heizung muss laufen",
    },
    {
        "condition": ("binary_sensor.heat", "on"),
        "affects": "climate",
        "effect": "Hitze-Warnung → Kuehlung/Rollladen",
        "hint": "Hitze → Kuehlung oder Beschattung noetig",
    },
    # === FEUCHTE → KLIMA ===
    {
        "condition": ("binary_sensor.moisture", "on"),
        "affects": "climate",
        "effect": "Hohe Feuchtigkeit → Lueften oder Entfeuchten",
        "hint": "Hohe Luftfeuchtigkeit → Schimmelgefahr",
    },
    {
        "condition": ("binary_sensor.feucht", "on"),
        "affects": "climate",
        "effect": "Hohe Feuchtigkeit → Lueften oder Entfeuchten",
        "hint": "Hohe Luftfeuchtigkeit → Schimmelgefahr",
    },
    # === SCHLOSS → SICHERHEIT ===
    {
        "condition": ("lock.", "unlocked"),
        "affects": "alarm_control_panel",
        "effect": "Schloss offen → Sicherheitsrisiko bei Abwesenheit",
        "hint": "Tuer nicht abgeschlossen → Sicherheit pruefen",
    },
    # === GARAGENTOR → SICHERHEIT ===
    {
        "condition": ("cover.garage", "open"),
        "affects": "alarm_control_panel",
        "effect": "Garagentor offen → Sicherheitsrisiko",
        "hint": "Garage offen → Sicherheit pruefen",
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

    def detect_conflicts(self, states: dict) -> list[dict]:
        """Prueft aktuelle HA-States gegen DEVICE_DEPENDENCIES.

        Args:
            states: Dict entity_id → state-string (z.B. "on", "heat", "open")

        Returns:
            Liste aktiver Konflikte mit Hinweisen fuers LLM.
        """
        conflicts = []
        for dep in DEVICE_DEPENDENCIES:
            cond_entity, cond_state = dep["condition"]

            # Prefix-Match: "binary_sensor.fenster" matcht "binary_sensor.fenster_kueche"
            matching = [
                eid for eid, st in states.items()
                if eid.startswith(cond_entity) and st == cond_state
            ]
            if not matching:
                continue

            # Pruefen ob betroffene Domain aktiv ist
            affected_domain = dep["affects"]
            affected_active = any(
                eid.startswith(f"{affected_domain}.")
                and val not in ("off", "unavailable", "unknown", "idle")
                for eid, val in states.items()
            )

            for eid in matching:
                conflicts.append({
                    "trigger_entity": eid,
                    "trigger_state": cond_state,
                    "affected_domain": affected_domain,
                    "affected_active": affected_active,
                    "effect": dep["effect"],
                    "hint": dep["hint"],
                })
        return conflicts

    def format_conflicts_for_prompt(self, states: dict) -> str:
        """Formatiert aktive Geraete-Konflikte als LLM-Kontext.

        Args:
            states: Dict entity_id → state-string

        Returns:
            Prompt-Sektion oder leerer String.
        """
        conflicts = self.detect_conflicts(states)
        if not conflicts:
            return ""

        # Nur Konflikte wo betroffene Domain aktiv ist (echte Konflikte)
        active_conflicts = [c for c in conflicts if c["affected_active"]]
        if not active_conflicts:
            return ""

        lines = []
        seen = set()
        for c in active_conflicts:
            key = (c["trigger_entity"], c["affected_domain"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {c['hint']} ({c['effect']})")

        return (
            "\n\nAKTIVE GERAETE-KONFLIKTE:\n"
            + "\n".join(lines)
            + "\nWeise den User beilaeufig auf diese Konflikte hin, "
            "wenn er nach Energie, Heizung oder Raumklima fragt."
        )

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
