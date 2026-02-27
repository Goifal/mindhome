"""
Situation Model - Trackt Veraenderungen im Haus zwischen Gespraechen.

JARVIS merkt sich den Hausstatus bei jedem Gespraech und vergleicht
beim naechsten Gespraech was sich veraendert hat. So kann er sagen:
"Seit wir zuletzt gesprochen haben: Temperatur ist um 3 Grad gesunken,
das Kuechen-Fenster wurde geoeffnet, und die Waschmaschine ist fertig."

Gespeichert wird ein kompakter Snapshot in Redis (TTL: 24h).
"""

import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config

logger = logging.getLogger(__name__)

# Redis-Keys
KEY_LAST_SNAPSHOT = "mha:situation:last_snapshot"
KEY_LAST_INTERACTION = "mha:situation:last_interaction"
SNAPSHOT_TTL = 86400  # 24h


class SituationModel:
    """Trackt Haus-Veraenderungen zwischen Gespraechen."""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        cfg = yaml_config.get("situation_model", {})
        self.enabled = cfg.get("enabled", True)
        self.min_pause_minutes = cfg.get("min_pause_minutes", 5)
        self.max_changes = cfg.get("max_changes", 5)
        self.temp_threshold = cfg.get("temp_threshold", 2)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis."""
        self.redis = redis_client
        logger.info("SituationModel initialisiert (enabled: %s)", self.enabled)

    async def take_snapshot(self, states: list[dict]):
        """Speichert einen kompakten Hausstatus-Snapshot.

        Wird am Ende jedes Gespraechs aufgerufen.
        """
        if not self.enabled or not self.redis or not states:
            return

        snapshot = self._build_snapshot(states)
        try:
            await self.redis.setex(
                KEY_LAST_SNAPSHOT, SNAPSHOT_TTL,
                json.dumps(snapshot, ensure_ascii=False),
            )
            await self.redis.setex(
                KEY_LAST_INTERACTION, SNAPSHOT_TTL,
                datetime.now().isoformat(),
            )
        except Exception as e:
            logger.debug("Snapshot speichern fehlgeschlagen: %s", e)

    async def get_situation_delta(self, current_states: list[dict]) -> Optional[str]:
        """Vergleicht aktuellen Zustand mit letztem Snapshot.

        Returns:
            Menschenlesbarer Delta-Text oder None wenn nichts Interessantes.
        """
        if not self.enabled or not self.redis or not current_states:
            return None

        try:
            raw_snapshot = await self.redis.get(KEY_LAST_SNAPSHOT)
            raw_time = await self.redis.get(KEY_LAST_INTERACTION)
        except Exception as e:
            logger.debug("Snapshot laden fehlgeschlagen: %s", e)
            return None

        if not raw_snapshot:
            return None

        try:
            old_snapshot = json.loads(raw_snapshot)
        except (json.JSONDecodeError, TypeError):
            return None

        last_time = ""
        if raw_time:
            t = raw_time if isinstance(raw_time, str) else raw_time.decode()
            try:
                last_dt = datetime.fromisoformat(t)
                diff = datetime.now() - last_dt
                minutes = int(diff.total_seconds() / 60)
                if minutes < self.min_pause_minutes:
                    return None  # Zu kurz her, kein Delta noetig
                elif minutes < 60:
                    last_time = f"vor {minutes} Minuten"
                elif minutes < 1440:
                    hours = minutes // 60
                    last_time = f"vor {hours} Stunde{'n' if hours > 1 else ''}"
                else:
                    days = minutes // 1440
                    last_time = f"vor {days} Tag{'en' if days > 1 else ''}"
            except (ValueError, TypeError):
                pass

        current_snapshot = self._build_snapshot(current_states)
        changes = self._compare_snapshots(old_snapshot, current_snapshot)

        if not changes:
            return None

        # Maximal N Aenderungen melden (die wichtigsten)
        changes = changes[:self.max_changes]

        header = f"Seit dem letzten Gespraech ({last_time}):" if last_time else "Seit dem letzten Gespraech:"
        delta_text = f"\n\nSITUATIONS-DELTA:\n{header}\n"
        for change in changes:
            delta_text += f"- {change}\n"
        delta_text += "Erwaehne relevante Aenderungen beilaeufig wenn es zum Gespraech passt."

        return delta_text

    def _build_snapshot(self, states: list[dict]) -> dict:
        """Baut einen kompakten Snapshot aus HA-States."""
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "temperatures": {},
            "open_windows": [],
            "open_doors": [],
            "lights_on": [],
            "locks_unlocked": [],
            "covers_open": [],
            "persons": {},
            "media_playing": [],
            "climate_targets": {},
        }

        for s in states:
            eid = s.get("entity_id", "")
            state_val = s.get("state", "")
            attrs = s.get("attributes", {})
            friendly = attrs.get("friendly_name", eid)

            # Temperaturen (Climate + Sensor)
            if eid.startswith("climate."):
                current = attrs.get("current_temperature")
                target = attrs.get("temperature")
                if current is not None:
                    try:
                        snapshot["temperatures"][friendly] = round(float(current), 1)
                    except (ValueError, TypeError):
                        pass
                if target is not None:
                    try:
                        snapshot["climate_targets"][friendly] = round(float(target), 1)
                    except (ValueError, TypeError):
                        pass

            elif eid.startswith("sensor.") and "temperature" in eid.lower():
                try:
                    val = float(state_val)
                    if -40 < val < 60:  # Plausibilitaet
                        snapshot["temperatures"][friendly] = round(val, 1)
                except (ValueError, TypeError):
                    pass

            # Fenster / Tueren (binary_sensor)
            elif eid.startswith("binary_sensor.") and state_val == "on":
                eid_lower = eid.lower()
                if any(kw in eid_lower for kw in ("window", "fenster")):
                    snapshot["open_windows"].append(friendly)
                elif any(kw in eid_lower for kw in ("door", "tuer")):
                    snapshot["open_doors"].append(friendly)

            # Lichter
            elif eid.startswith("light.") and state_val == "on":
                snapshot["lights_on"].append(friendly)

            # Schloesser
            elif eid.startswith("lock.") and state_val == "unlocked":
                snapshot["locks_unlocked"].append(friendly)

            # Rolllaeden
            elif eid.startswith("cover.") and state_val == "open":
                snapshot["covers_open"].append(friendly)

            # Personen
            elif eid.startswith("person."):
                snapshot["persons"][friendly] = state_val

            # Medien
            elif eid.startswith("media_player.") and state_val == "playing":
                snapshot["media_playing"].append(friendly)

        return snapshot

    def _compare_snapshots(self, old: dict, new: dict) -> list[str]:
        """Vergleicht zwei Snapshots und gibt menschenlesbare Aenderungen zurueck.

        Returns sortiert nach Wichtigkeit (Sicherheit > Komfort > Info).
        """
        changes: list[tuple[int, str]] = []  # (priority, text)

        # 1. Temperatur-Aenderungen (> 2 Grad)
        old_temps = old.get("temperatures", {})
        new_temps = new.get("temperatures", {})
        temp_drops = {}  # name → diff (nur negative = gesunken)
        temp_rises = {}
        for name in set(old_temps) & set(new_temps):
            diff = new_temps[name] - old_temps[name]
            if abs(diff) >= self.temp_threshold:
                if diff < 0:
                    temp_drops[name] = diff
                else:
                    temp_rises[name] = diff

        # 2. Fenster geoeffnet/geschlossen
        old_win = set(old.get("open_windows", []))
        new_win = set(new.get("open_windows", []))
        opened = new_win - old_win
        closed = old_win - new_win

        # Kausale Verknuepfung: Fenster geoeffnet UND Temperatur gesunken
        causal_matched_temps = set()
        if opened and temp_drops:
            window_names = ", ".join(sorted(opened))
            for name, diff in temp_drops.items():
                causal_matched_temps.add(name)
                changes.append((
                    2,
                    f"{name}: Temperatur um {abs(diff):.1f} Grad gesunken "
                    f"({old_temps[name]:.0f} → {new_temps[name]:.0f}°C) "
                    f"— vermutlich weil {window_names} geoeffnet wurde"
                ))

        # Verbleibende Temperatur-Aenderungen (nicht kausal verknuepft)
        for name, diff in temp_drops.items():
            if name not in causal_matched_temps:
                changes.append((
                    3,
                    f"{name}: Temperatur um {abs(diff):.1f} Grad gesunken "
                    f"({old_temps[name]:.0f} → {new_temps[name]:.0f}°C)"
                ))
        for name, diff in temp_rises.items():
            changes.append((
                3,
                f"{name}: Temperatur um {abs(diff):.1f} Grad gestiegen "
                f"({old_temps[name]:.0f} → {new_temps[name]:.0f}°C)"
            ))

        for w in opened:
            changes.append((2, f"{w} wurde geoeffnet"))
        for w in closed:
            changes.append((4, f"{w} wurde geschlossen"))

        # 3. Tueren geoeffnet/geschlossen
        old_doors = set(old.get("open_doors", []))
        new_doors = set(new.get("open_doors", []))
        for d in (new_doors - old_doors):
            changes.append((2, f"{d} wurde geoeffnet"))
        for d in (old_doors - new_doors):
            changes.append((4, f"{d} wurde geschlossen"))

        # 4. Schloesser (Sicherheit — hohe Prio)
        old_locks = set(old.get("locks_unlocked", []))
        new_locks = set(new.get("locks_unlocked", []))
        for l in (new_locks - old_locks):
            changes.append((1, f"{l} wurde entriegelt"))
        for l in (old_locks - new_locks):
            changes.append((3, f"{l} wurde verriegelt"))

        # 5. Personen — gekommen/gegangen
        old_persons = old.get("persons", {})
        new_persons = new.get("persons", {})
        for name in set(old_persons) | set(new_persons):
            old_state = old_persons.get(name)
            new_state = new_persons.get(name)
            if old_state != new_state:
                if new_state == "home" and old_state != "home":
                    changes.append((2, f"{name} ist nach Hause gekommen"))
                elif old_state == "home" and new_state != "home":
                    changes.append((2, f"{name} hat das Haus verlassen"))

        # 6. Lichter (nur zusammenfassend wenn viele sich geaendert haben)
        old_lights = set(old.get("lights_on", []))
        new_lights = set(new.get("lights_on", []))
        lights_on = new_lights - old_lights
        lights_off = old_lights - new_lights
        if len(lights_on) >= 3:
            changes.append((4, f"{len(lights_on)} Lichter wurden eingeschaltet"))
        elif lights_on:
            for l in lights_on:
                changes.append((5, f"{l} wurde eingeschaltet"))
        if len(lights_off) >= 3:
            changes.append((4, f"{len(lights_off)} Lichter wurden ausgeschaltet"))

        # 7. Medien
        old_media = set(old.get("media_playing", []))
        new_media = set(new.get("media_playing", []))
        for m in (new_media - old_media):
            changes.append((4, f"{m} spielt jetzt Musik"))
        for m in (old_media - new_media):
            changes.append((5, f"{m} wurde gestoppt"))

        # Sortieren nach Prioritaet (niedrig = wichtig)
        changes.sort(key=lambda c: c[0])
        return [text for _, text in changes]
