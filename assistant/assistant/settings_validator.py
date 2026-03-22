"""
Settings Validator — Validiert settings.yaml beim Start.

Prueft die wichtigsten Sektionen auf korrekte Typen, Pflichtfelder
und Wertebereiche. Warnt bei fehlender Konfiguration statt zu crashen.

Aufruf: validate_settings(yaml_config) beim Start in config.py
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Schema-Definition: {key: {type, required_fields, validators}}
# Nur die kritischsten Sektionen — nicht die 130+ optionalen.
_SCHEMA = {
    "assistant": {
        "type": dict,
        "fields": {
            "name": {"type": str, "required": True},
        },
    },
    "household": {
        "type": dict,
        "fields": {
            "primary_user": {"type": str, "required": True},
            "members": {"type": list, "required": False},
        },
    },
    "ollama": {
        "type": dict,
        "fields": {
            "num_ctx_fast": {"type": int, "min": 512, "max": 131072},
            "num_ctx_smart": {"type": int, "min": 512, "max": 131072},
            "num_ctx_deep": {"type": int, "min": 512, "max": 131072},
        },
    },
    "models": {
        "type": dict,
        "fields": {
            "fast": {"type": str, "required": True},
            "smart": {"type": str, "required": True},
        },
    },
    "personality": {
        "type": dict,
        "fields": {
            "humor_level": {"type": (int, float), "min": 1, "max": 10},
            "sarcasm_level": {"type": (int, float), "min": 1, "max": 10},
        },
    },
    "security": {
        "type": dict,
        "fields": {
            "confirm_dangerous_actions": {"type": bool},
        },
    },
    "memory": {
        "type": dict,
        "fields": {
            "max_conversations": {"type": int, "min": 5, "max": 1000},
        },
    },
    "routines": {
        "type": dict,
        "fields": {
            "morning_briefing": {"type": dict},
        },
    },
    "energy": {
        "type": dict,
        "fields": {
            "enabled": {"type": bool},
        },
    },
}

# Household member schema
_MEMBER_SCHEMA = {
    "name": {"type": str, "required": True},
    "role": {
        "type": str,
        "required": True,
        "values": ["owner", "member", "child", "guest"],
    },
}


def validate_settings(config: dict) -> list[str]:
    """Validiert settings.yaml und gibt eine Liste von Warnungen zurueck.

    Gibt eine leere Liste zurueck wenn alles OK ist.
    Crasht NICHT — loggt nur Warnungen.
    """
    warnings = []

    if not config or not isinstance(config, dict):
        warnings.append("settings.yaml ist leer oder kein Dict")
        return warnings

    for section_name, schema in _SCHEMA.items():
        section = config.get(section_name)
        if section is None:
            # Optionale Sektionen nicht warnen
            continue

        # Typ-Check
        expected_type = schema["type"]
        if not isinstance(section, expected_type):
            warnings.append(
                f"{section_name}: Erwartet {expected_type.__name__}, "
                f"bekommen {type(section).__name__}"
            )
            continue

        # Feld-Validierung
        for field_name, field_schema in schema.get("fields", {}).items():
            value = section.get(field_name)

            # Pflichtfeld
            if field_schema.get("required") and value is None:
                warnings.append(f"{section_name}.{field_name}: Pflichtfeld fehlt")
                continue

            if value is None:
                continue

            # Typ-Check
            field_type = field_schema.get("type")
            if field_type and not isinstance(value, field_type):
                warnings.append(
                    f"{section_name}.{field_name}: Erwartet {field_type}, "
                    f"bekommen {type(value).__name__} ({value!r})"
                )
                continue

            # Wertebereich
            if "min" in field_schema and isinstance(value, (int, float)):
                if value < field_schema["min"]:
                    warnings.append(
                        f"{section_name}.{field_name}: {value} < Minimum {field_schema['min']}"
                    )
            if "max" in field_schema and isinstance(value, (int, float)):
                if value > field_schema["max"]:
                    warnings.append(
                        f"{section_name}.{field_name}: {value} > Maximum {field_schema['max']}"
                    )

            # Erlaubte Werte
            if "values" in field_schema and value not in field_schema["values"]:
                warnings.append(
                    f"{section_name}.{field_name}: '{value}' nicht in {field_schema['values']}"
                )

    # Household-Members validieren
    members = (config.get("household") or {}).get("members", [])
    if isinstance(members, list):
        for i, member in enumerate(members):
            if not isinstance(member, dict):
                warnings.append(f"household.members[{i}]: Kein Dict")
                continue
            for field_name, field_schema in _MEMBER_SCHEMA.items():
                val = member.get(field_name)
                if field_schema.get("required") and not val:
                    warnings.append(
                        f"household.members[{i}].{field_name}: Pflichtfeld fehlt"
                    )
                if (
                    val
                    and "values" in field_schema
                    and val not in field_schema["values"]
                ):
                    warnings.append(
                        f"household.members[{i}].{field_name}: '{val}' nicht in "
                        f"{field_schema['values']}"
                    )

    # Log-Ausgabe
    if warnings:
        for w in warnings:
            logger.warning("Settings-Validierung: %s", w)
        logger.warning("Settings-Validierung: %d Problem(e) gefunden", len(warnings))
    else:
        logger.info("Settings-Validierung: OK (alle kritischen Sektionen valide)")

    return warnings
