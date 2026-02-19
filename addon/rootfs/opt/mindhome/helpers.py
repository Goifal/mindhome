# MindHome - helpers.py | see version.py for version info
"""
Shared helper functions used across all route modules.
Extracted from the monolithic app.py to avoid duplication.
"""

import os
import re
import json
import logging
import time
import hashlib
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from functools import wraps

from db import get_db_session, get_db_readonly, get_db

logger = logging.getLogger("mindhome")

# ==============================================================================
# Timezone
# ==============================================================================

_ha_tz = None


def init_timezone(ha_connection):
    """Initialize timezone from HA."""
    global _ha_tz
    try:
        import zoneinfo
        tz_name = ha_connection.get_timezone()
        _ha_tz = zoneinfo.ZoneInfo(tz_name)
        logger.info(f"Using HA timezone: {tz_name}")
    except Exception as e:
        logger.warning(f"Could not get HA timezone: {e}, falling back to UTC")
        _ha_tz = timezone.utc


def get_ha_timezone():
    """Get HA timezone as zoneinfo object, cached."""
    global _ha_tz
    if _ha_tz:
        return _ha_tz
    return timezone.utc


def local_now():
    """Get current time in HA's timezone."""
    tz = get_ha_timezone()
    return datetime.now(tz)


def utc_iso(dt):
    """Convert datetime to ISO string with Z suffix for UTC. Handles None."""
    if dt is None:
        return None
    s = dt.isoformat()
    if not dt.tzinfo and not s.endswith('Z'):
        s += 'Z'
    return s


# ==============================================================================
# Rate Limiting
# ==============================================================================

_rate_limit_data = defaultdict(list)
_rate_limit_lock = __import__('threading').Lock()
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 600


def rate_limit_check(ip):
    """Check if current request exceeds rate limit. Thread-safe."""
    now = time.time()
    with _rate_limit_lock:
        _rate_limit_data[ip] = [t for t in _rate_limit_data[ip] if now - t < _RATE_LIMIT_WINDOW]
        if len(_rate_limit_data[ip]) >= _RATE_LIMIT_MAX:
            return False
        _rate_limit_data[ip].append(now)
    return True


# ==============================================================================
# Input Sanitization
# ==============================================================================

_SANITIZE_RE = re.compile(r'[<>]')


def sanitize_input(value, max_length=500):
    """Sanitize user input - strip angle brackets, limit length."""
    if not isinstance(value, str):
        return value
    return _SANITIZE_RE.sub('', value.strip()[:max_length])


def sanitize_dict(data, keys=None):
    """Sanitize string values in a dict."""
    if not isinstance(data, dict):
        return data
    return {
        k: (sanitize_input(v) if isinstance(v, str) and (not keys or k in keys) else v)
        for k, v in data.items()
    }


# ==============================================================================
# Audit Log
# ==============================================================================

def audit_log(action, details=None, user_id=None):
    """Log an audit trail entry."""
    try:
        from models import ActionLog
        with get_db_session() as session:
            entry = ActionLog(
                action_type="audit",
                user_id=user_id,
                action_data={"action": action, "details": details},
                reason=f"user:{user_id}" if user_id else "system",
            )
            session.add(entry)
    except Exception:
        pass


# ==============================================================================
# Debug Mode
# ==============================================================================

_debug_mode = False


def is_debug_mode():
    global _debug_mode
    return _debug_mode


def set_debug_mode(enabled):
    global _debug_mode
    _debug_mode = enabled


# ==============================================================================
# Settings Helpers
# ==============================================================================

def get_setting(key, default=None):
    """Get a system setting value."""
    from models import SystemSetting
    with get_db_readonly() as session:
        setting = session.query(SystemSetting).filter_by(key=key).first()
        return setting.value if setting else default


def set_setting(key, value):
    """Set a system setting value."""
    from models import SystemSetting
    with get_db_session() as session:
        setting = session.query(SystemSetting).filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = SystemSetting(key=key, value=str(value))
            session.add(setting)


def get_language():
    """Get current language setting."""
    return os.environ.get("MINDHOME_LANGUAGE", "de")


def localize(de_text, en_text):
    """Return text in current language."""
    return de_text if get_language() == "de" else en_text


# ==============================================================================
# Entity Attribute Helpers
# ==============================================================================

def extract_display_attributes(entity_id, attrs):
    """Extract human-readable attributes from HA state attributes."""
    result = {}
    ha_domain = entity_id.split(".")[0] if entity_id else ""

    if "brightness" in attrs and attrs["brightness"] is not None:
        try:
            result["brightness_pct"] = round(int(attrs["brightness"]) / 255 * 100)
        except (ValueError, TypeError):
            pass

    if "color_temp_kelvin" in attrs:
        result["color_temp_kelvin"] = attrs["color_temp_kelvin"]
    elif "color_temp" in attrs:
        result["color_temp"] = attrs["color_temp"]

    if "current_position" in attrs:
        result["position_pct"] = attrs["current_position"]

    if "temperature" in attrs:
        result["target_temp"] = attrs["temperature"]
    if "current_temperature" in attrs:
        result["current_temp"] = attrs["current_temperature"]
    if "hvac_mode" in attrs or "hvac_action" in attrs:
        result["hvac_mode"] = attrs.get("hvac_mode")
        result["hvac_action"] = attrs.get("hvac_action")
    if "humidity" in attrs:
        result["humidity"] = attrs["humidity"]

    for key in ["current_power_w", "power", "current", "voltage",
                "total_energy_kwh", "energy", "total_increasing"]:
        if key in attrs and attrs[key] is not None:
            result[key] = attrs[key]

    for key in ["co2", "voc", "pm25", "pm10", "aqi"]:
        if key in attrs and attrs[key] is not None:
            result[key] = attrs[key]

    if "unit_of_measurement" in attrs and attrs["unit_of_measurement"]:
        result["unit"] = attrs["unit_of_measurement"]

    return result


def build_state_reason(device_name, old_val, new_val, new_display_attrs):
    """Build a human-readable reason string including attributes."""
    reason = f"{device_name}: {old_val} → {new_val}"

    details = []
    if "brightness_pct" in new_display_attrs:
        details.append(f"{new_display_attrs['brightness_pct']}%")
    if "position_pct" in new_display_attrs:
        details.append(f"Position {new_display_attrs['position_pct']}%")
    if "target_temp" in new_display_attrs:
        details.append(f"{new_display_attrs['target_temp']}°C")
    if "current_temp" in new_display_attrs:
        details.append(f"Ist: {new_display_attrs['current_temp']}°C")

    if details:
        reason += f" ({', '.join(details)})"

    return reason
