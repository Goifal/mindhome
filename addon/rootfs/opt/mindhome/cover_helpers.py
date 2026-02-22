# MindHome - cover_helpers.py
"""
Gemeinsame Hilfsfunktionen fuer Cover/Rollladen-Steuerung.

Wird von engines/cover_control.py und domains/cover.py genutzt,
um Code-Duplikation zu vermeiden.
"""

import re
import logging

logger = logging.getLogger("mindhome.cover_helpers")

# Cover-Typen die NIEMALS automatisch gesteuert werden duerfen
UNSAFE_COVER_TYPES = {"garage_door", "gate", "door"}
UNSAFE_DEVICE_CLASSES = {"garage_door", "gate", "door"}

# Keywords fuer Bettbelegungssensoren
_BED_KEYWORDS = ("bett", "bed", "matratze", "mattress")
_BEDROOM_KEYWORDS = ("schlafzimmer", "bedroom")


def is_bed_occupied(states) -> bool:
    """Prueft ob ein Bettbelegungssensor aktiv ist (jemand schlaeft).

    Args:
        states: Liste der HA-Entity-States (list[dict]).

    Returns:
        True wenn mindestens ein Bettbelegungssensor aktiv ist.
    """
    try:
        bed_sensors = [
            s for s in (states or [])
            if s.get("entity_id", "").startswith("binary_sensor.")
            and s.get("attributes", {}).get("device_class") == "occupancy"
            and any(kw in s.get("entity_id", "").lower() for kw in _BED_KEYWORDS)
        ]
        if not bed_sensors:
            # Fallback: Occupancy-Sensoren in Schlafzimmern
            bed_sensors = [
                s for s in (states or [])
                if s.get("entity_id", "").startswith("binary_sensor.")
                and s.get("attributes", {}).get("device_class") == "occupancy"
                and any(kw in s.get("entity_id", "").lower() for kw in _BEDROOM_KEYWORDS)
            ]
        if bed_sensors:
            return any(s.get("state") == "on" for s in bed_sensors)
    except Exception:
        pass
    return False


def is_garage_or_gate_by_entity_id(entity_id: str) -> bool:
    """Prueft anhand der Entity-ID ob es ein Garagentor/Tor ist.

    Word-Boundary fuer 'tor' damit 'motor', 'monitor' etc. nicht matchen.
    """
    eid_lower = entity_id.lower()
    if "garage" in eid_lower or "gate" in eid_lower:
        return True
    if re.search(r'(?:^|[_.])tor(?:$|[_.])', eid_lower):
        return True
    return False


def is_unsafe_device_class(device_class: str) -> bool:
    """Prueft ob die HA device_class unsicher ist (garage_door, gate, door)."""
    return device_class in UNSAFE_DEVICE_CLASSES


def is_unsafe_cover_type(cover_type) -> bool:
    """Prueft ob der CoverConfig cover_type unsicher ist."""
    return cover_type in UNSAFE_COVER_TYPES
