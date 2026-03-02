"""
Declarative Tool Builder — Deklarative Tools per YAML-Config statt Python-Code.

Jarvis kann Tools definieren die auf vordefinierte Berechnungs-Typen zugreifen:
- entity_comparison: Vergleich zweier Entities ueber Zeit
- multi_entity_formula: Kombination mehrerer Entities (avg, weighted_avg, diff, min, max)
- event_counter: Zaehlt State-Aenderungen einer Entity
- threshold_monitor: Prueft ob Wert in definiertem Bereich
- trend_analyzer: Trend-Analyse ueber Zeitraum
- entity_aggregator: Aggregation ueber mehrere Entities
- schedule_checker: Zeitbasierte Checks
- state_duration: Wie lange war ein Zustand aktiv (z.B. Heizung lief X Stunden)
- time_comparison: Vergleich einer Entity mit sich selbst ueber verschiedene Zeitraeume

Sicherheit:
- Kein Python-Code wird ausgefuehrt
- Nur Lese-Zugriff auf HA-Daten (get_state, get_history)
- Schema-Validierung fuer alle Configs
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import yaml_config

logger = logging.getLogger(__name__)

# ── Konstanten ────────────────────────────────────────────────
DEFAULT_MAX_TOOLS = 20
TOOLS_FILE = Path(__file__).parent.parent / "config" / "declarative_tools.yaml"


def _get_max_tools() -> int:
    """Gibt das konfigurierte Maximum an Tools zurueck."""
    return yaml_config.get("declarative_tools", {}).get("max_tools", DEFAULT_MAX_TOOLS)

VALID_TYPES = frozenset({
    "entity_comparison",
    "multi_entity_formula",
    "event_counter",
    "threshold_monitor",
    "trend_analyzer",
    "entity_aggregator",
    "schedule_checker",
    "state_duration",
    "time_comparison",
})

VALID_OPERATIONS = frozenset({
    "difference", "ratio", "percentage_change",
})

VALID_FORMULAS = frozenset({
    "average", "weighted_average", "sum", "min", "max", "difference",
})

# Zeitraum-Kuerzel -> Stunden
TIME_RANGE_MAP = {
    "1h": 1, "2h": 2, "3h": 3, "6h": 6, "12h": 12,
    "24h": 24, "today": 24, "48h": 48, "7d": 168, "30d": 720,
}


# ── Registry ──────────────────────────────────────────────────
class DeclarativeToolRegistry:
    """Verwaltet deklarative Tools: Laden, Speichern, Validieren."""

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._load()

    def _load(self):
        """Laedt Tools von Disk."""
        if not TOOLS_FILE.exists():
            self._tools = {}
            return
        try:
            with open(TOOLS_FILE) as f:
                data = yaml.safe_load(f) or {}
            self._tools = data.get("tools", {})
            logger.info("Declarative Tools geladen: %d", len(self._tools))
        except Exception as e:
            logger.error("Fehler beim Laden von declarative_tools.yaml: %s", e)
            self._tools = {}

    def _save(self):
        """Speichert Tools auf Disk."""
        TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOOLS_FILE, "w") as f:
            yaml.dump({"tools": self._tools}, f, default_flow_style=False, allow_unicode=True)

    def list_tools(self) -> list[dict]:
        """Liefert alle Tools als Liste."""
        result = []
        for name, cfg in self._tools.items():
            result.append({"name": name, **cfg})
        return result

    def get_tool(self, name: str) -> Optional[dict]:
        """Liefert ein Tool nach Name."""
        cfg = self._tools.get(name)
        if cfg:
            return {"name": name, **cfg}
        return None

    def create_tool(self, name: str, config: dict) -> dict:
        """Erstellt oder aktualisiert ein deklaratives Tool."""
        # Validierung
        err = self._validate(name, config)
        if err:
            return {"success": False, "message": err}

        max_tools = _get_max_tools()
        if name not in self._tools and len(self._tools) >= max_tools:
            return {"success": False, "message": f"Maximum {max_tools} Tools erreicht."}

        self._tools[name] = config
        self._save()
        logger.info("Declarative Tool erstellt/aktualisiert: %s", name)
        return {"success": True, "message": f"Tool '{name}' gespeichert."}

    def delete_tool(self, name: str) -> dict:
        """Loescht ein Tool."""
        if name not in self._tools:
            return {"success": False, "message": f"Tool '{name}' nicht gefunden."}
        del self._tools[name]
        self._save()
        logger.info("Declarative Tool geloescht: %s", name)
        return {"success": True, "message": f"Tool '{name}' geloescht."}

    def reload_config(self):
        """Hot-Reload: Laedt Tools von Disk neu (z.B. nach Settings-Aenderung)."""
        self._load()

    def _validate(self, name: str, cfg: dict) -> Optional[str]:
        """Validiert eine Tool-Config. Gibt Fehlertext oder None zurueck."""
        if not name or not name.replace("_", "").replace("-", "").isalnum():
            return "Ungueltiger Name. Nur Buchstaben, Zahlen, _ und - erlaubt."

        tool_type = cfg.get("type", "")
        if tool_type not in VALID_TYPES:
            return f"Unbekannter Typ '{tool_type}'. Erlaubt: {', '.join(sorted(VALID_TYPES))}"

        if not cfg.get("description"):
            return "Beschreibung erforderlich."

        config = cfg.get("config", {})
        if not config:
            return "Config-Block erforderlich."

        # Typ-spezifische Validierung
        if tool_type == "entity_comparison":
            if not config.get("entity_a") or not config.get("entity_b"):
                return "entity_a und entity_b erforderlich."
            op = config.get("operation", "difference")
            if op not in VALID_OPERATIONS:
                return f"Ungueltige Operation '{op}'. Erlaubt: {', '.join(sorted(VALID_OPERATIONS))}"

        elif tool_type == "multi_entity_formula":
            entities = config.get("entities", {})
            if not entities or not isinstance(entities, dict) or len(entities) < 2:
                return "Mindestens 2 Entities als Dict erforderlich (z.B. {temp: sensor.xyz})."
            formula = config.get("formula", "")
            if formula not in VALID_FORMULAS:
                return f"Ungueltige Formel '{formula}'. Erlaubt: {', '.join(sorted(VALID_FORMULAS))}"

        elif tool_type == "event_counter":
            if not config.get("entities"):
                return "Mindestens eine Entity erforderlich."
            if not config.get("count_state"):
                return "count_state erforderlich (z.B. 'on')."

        elif tool_type == "threshold_monitor":
            if not config.get("entity"):
                return "entity erforderlich."
            thresholds = config.get("thresholds", {})
            if thresholds.get("min") is None and thresholds.get("max") is None:
                return "Mindestens min oder max Schwellwert erforderlich."

        elif tool_type == "trend_analyzer":
            if not config.get("entity"):
                return "entity erforderlich."

        elif tool_type == "entity_aggregator":
            entities = config.get("entities", [])
            if not entities or not isinstance(entities, list) or len(entities) < 2:
                return "Mindestens 2 Entities als Liste erforderlich."
            agg = config.get("aggregation", "")
            if agg not in ("average", "min", "max", "sum"):
                return f"Ungueltige Aggregation '{agg}'. Erlaubt: average, min, max, sum"

        elif tool_type == "schedule_checker":
            schedules = config.get("schedules", [])
            if not schedules:
                return "Mindestens ein Schedule erforderlich."

        elif tool_type == "state_duration":
            if not config.get("entity"):
                return "entity erforderlich."
            if not config.get("target_state"):
                return "target_state erforderlich (z.B. 'on', 'heating')."

        elif tool_type == "time_comparison":
            if not config.get("entity"):
                return "entity erforderlich."
            period = config.get("compare_period", "")
            if period not in ("yesterday", "last_week", "last_month"):
                return f"Ungueltiger compare_period '{period}'. Erlaubt: yesterday, last_week, last_month"

        return None


# ── Executor ──────────────────────────────────────────────────
class DeclarativeToolExecutor:
    """Fuehrt deklarative Tools aus — nur Lese-Zugriff auf HA."""

    def __init__(self, ha_client):
        self.ha = ha_client
        self.registry = get_registry()

    async def execute(self, tool_name: str) -> dict:
        """Fuehrt ein deklaratives Tool aus und gibt Ergebnis zurueck."""
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return {"success": False, "message": f"Tool '{tool_name}' nicht gefunden."}

        tool_type = tool.get("type", "")
        config = tool.get("config", {})

        try:
            handler = getattr(self, f"_exec_{tool_type}", None)
            if not handler:
                return {"success": False, "message": f"Unbekannter Typ: {tool_type}"}
            return await handler(config, tool.get("description", ""))
        except Exception as e:
            logger.error("Declarative Tool '%s' Fehler: %s", tool_name, e)
            return {"success": False, "message": f"Fehler bei Ausfuehrung: {e}"}

    def _parse_time_range(self, config: dict) -> int:
        """Parst time_range zu Stunden."""
        tr = config.get("time_range", "24h")
        return TIME_RANGE_MAP.get(tr, 24)

    async def _get_numeric_value(self, entity_id: str) -> Optional[float]:
        """Holt aktuellen numerischen Wert einer Entity."""
        state = await self.ha.get_state(entity_id)
        if not state:
            return None
        try:
            return float(state.get("state", ""))
        except (ValueError, TypeError):
            return None

    async def _get_entity_name(self, entity_id: str) -> str:
        """Holt friendly_name einer Entity."""
        state = await self.ha.get_state(entity_id)
        if state:
            return state.get("attributes", {}).get("friendly_name", entity_id)
        return entity_id

    async def _get_entity_unit(self, entity_id: str) -> str:
        """Holt unit_of_measurement einer Entity."""
        state = await self.ha.get_state(entity_id)
        if state:
            return state.get("attributes", {}).get("unit_of_measurement", "")
        return ""

    # ── entity_comparison ─────────────────────────────────────
    async def _exec_entity_comparison(self, config: dict, description: str) -> dict:
        """Vergleicht zwei Entities."""
        entity_a = config["entity_a"]
        entity_b = config["entity_b"]
        operation = config.get("operation", "difference")

        val_a = await self._get_numeric_value(entity_a)
        val_b = await self._get_numeric_value(entity_b)

        if val_a is None:
            return {"success": False, "message": f"Kein Wert fuer {entity_a}"}
        if val_b is None:
            return {"success": False, "message": f"Kein Wert fuer {entity_b}"}

        name_a = await self._get_entity_name(entity_a)
        name_b = await self._get_entity_name(entity_b)
        unit = await self._get_entity_unit(entity_a)

        if operation == "difference":
            result = val_a - val_b
            result_text = f"{result:+.1f}{unit}"
        elif operation == "ratio":
            result = val_a / val_b if val_b != 0 else 0
            result_text = f"{result:.2f}x"
        elif operation == "percentage_change":
            result = ((val_a - val_b) / val_b * 100) if val_b != 0 else 0
            result_text = f"{result:+.1f}%"
        else:
            result = val_a - val_b
            result_text = f"{result:+.1f}{unit}"

        trend = "hoeher" if result > 0 else ("niedriger" if result < 0 else "gleich")

        msg = (
            f"{description}\n"
            f"{name_a}: {val_a:.1f}{unit}\n"
            f"{name_b}: {val_b:.1f}{unit}\n"
            f"Ergebnis: {result_text} ({trend})"
        )
        return {"success": True, "message": msg, "result": result}

    # ── multi_entity_formula ──────────────────────────────────
    async def _exec_multi_entity_formula(self, config: dict, description: str) -> dict:
        """Kombiniert mehrere Entities mit einer Formel."""
        entities = config["entities"]  # Dict: {label: entity_id}
        formula = config.get("formula", "average")
        weights = config.get("weights", {})

        values = {}
        names = {}
        for label, entity_id in entities.items():
            val = await self._get_numeric_value(entity_id)
            if val is not None:
                values[label] = val
                names[label] = await self._get_entity_name(entity_id)

        if not values:
            return {"success": False, "message": "Keine Werte verfuegbar."}

        vals = list(values.values())

        if formula == "average":
            result = sum(vals) / len(vals)
        elif formula == "weighted_average":
            total_weight = 0
            weighted_sum = 0
            for label, val in values.items():
                w = weights.get(label, 1)
                weighted_sum += val * w
                total_weight += w
            result = weighted_sum / total_weight if total_weight else 0
        elif formula == "sum":
            result = sum(vals)
        elif formula == "min":
            result = min(vals)
        elif formula == "max":
            result = max(vals)
        elif formula == "difference":
            keys = list(values.keys())
            result = values[keys[0]] - values[keys[1]] if len(keys) >= 2 else 0
        else:
            result = sum(vals) / len(vals)

        lines = [description]
        for label, val in values.items():
            name = names.get(label, label)
            lines.append(f"  {name}: {val:.1f}")
        lines.append(f"Ergebnis ({formula}): {result:.1f}")

        return {"success": True, "message": "\n".join(lines), "result": result}

    # ── event_counter ─────────────────────────────────────────
    async def _exec_event_counter(self, config: dict, description: str) -> dict:
        """Zaehlt State-Aenderungen."""
        entities = config["entities"]
        if isinstance(entities, str):
            entities = [entities]
        count_state = config["count_state"]
        hours = self._parse_time_range(config)

        total_count = 0
        breakdown = []

        for entity_id in entities:
            try:
                history = await self.ha.get_history(entity_id, hours=hours)
            except Exception:
                history = None
            if not history:
                continue

            count = sum(1 for entry in history if entry.get("state") == count_state)
            total_count += count
            name = await self._get_entity_name(entity_id)
            breakdown.append(f"  {name}: {count}x")

        msg = f"{description}\nGesamt: {total_count}x"
        if breakdown:
            msg += "\n" + "\n".join(breakdown)

        return {"success": True, "message": msg, "count": total_count}

    # ── threshold_monitor ─────────────────────────────────────
    async def _exec_threshold_monitor(self, config: dict, description: str) -> dict:
        """Prueft ob Wert in definiertem Bereich."""
        entity_id = config["entity"]
        thresholds = config.get("thresholds", {})
        th_min = thresholds.get("min")
        th_max = thresholds.get("max")

        val = await self._get_numeric_value(entity_id)
        if val is None:
            return {"success": False, "message": f"Kein Wert fuer {entity_id}"}

        name = await self._get_entity_name(entity_id)
        unit = await self._get_entity_unit(entity_id)

        status = "OK"
        if th_min is not None and val < th_min:
            status = f"ZU NIEDRIG (unter {th_min}{unit})"
        elif th_max is not None and val > th_max:
            status = f"ZU HOCH (ueber {th_max}{unit})"

        labels = config.get("labels", {})
        status_label = labels.get("ok", "OK") if status == "OK" else status

        msg = (
            f"{description}\n"
            f"{name}: {val:.1f}{unit}\n"
            f"Status: {status_label}\n"
            f"Bereich: {th_min or '—'}{unit} bis {th_max or '—'}{unit}"
        )
        return {"success": True, "message": msg, "value": val, "in_range": status == "OK"}

    # ── trend_analyzer ────────────────────────────────────────
    async def _exec_trend_analyzer(self, config: dict, description: str) -> dict:
        """Analysiert Trend ueber Zeitraum."""
        entity_id = config["entity"]
        hours = self._parse_time_range(config)

        try:
            history = await self.ha.get_history(entity_id, hours=hours)
        except Exception as e:
            return {"success": False, "message": f"Fehler: {e}"}

        if not history:
            return {"success": False, "message": f"Keine Historie fuer {entity_id}"}

        name = await self._get_entity_name(entity_id)
        unit = await self._get_entity_unit(entity_id)

        numeric_vals = []
        for entry in history:
            try:
                numeric_vals.append(float(entry.get("state", "")))
            except (ValueError, TypeError):
                pass

        if not numeric_vals:
            return {"success": False, "message": f"Keine numerischen Werte fuer {name}"}

        avg = sum(numeric_vals) / len(numeric_vals)
        val_min = min(numeric_vals)
        val_max = max(numeric_vals)
        current = numeric_vals[-1]

        # Trend berechnen
        n = len(numeric_vals)
        trend = "stabil"
        trend_diff = 0.0
        if n >= 5:
            chunk = max(1, n // 5)
            first_avg = sum(numeric_vals[:chunk]) / chunk
            last_avg = sum(numeric_vals[-chunk:]) / chunk
            trend_diff = last_avg - first_avg
            if abs(trend_diff) > 0.1:
                trend = "steigend" if trend_diff > 0 else "fallend"

        msg = (
            f"{description}\n"
            f"{name} (letzte {hours}h, {n} Werte):\n"
            f"  Aktuell: {current:.1f}{unit}\n"
            f"  Min: {val_min:.1f}{unit} | Max: {val_max:.1f}{unit} | Avg: {avg:.1f}{unit}\n"
            f"  Trend: {trend} ({trend_diff:+.1f}{unit})"
        )
        return {
            "success": True, "message": msg,
            "current": current, "avg": avg, "min": val_min, "max": val_max,
            "trend": trend, "trend_diff": trend_diff,
        }

    # ── entity_aggregator ─────────────────────────────────────
    async def _exec_entity_aggregator(self, config: dict, description: str) -> dict:
        """Aggregiert ueber mehrere Entities."""
        entities = config["entities"]
        aggregation = config.get("aggregation", "average")

        values = {}
        for entity_id in entities:
            val = await self._get_numeric_value(entity_id)
            if val is not None:
                name = await self._get_entity_name(entity_id)
                values[name] = val

        if not values:
            return {"success": False, "message": "Keine Werte verfuegbar."}

        vals = list(values.values())
        if aggregation == "average":
            result = sum(vals) / len(vals)
        elif aggregation == "min":
            result = min(vals)
        elif aggregation == "max":
            result = max(vals)
        elif aggregation == "sum":
            result = sum(vals)
        else:
            result = sum(vals) / len(vals)

        # Einheit vom ersten Entity
        first_eid = entities[0]
        unit = await self._get_entity_unit(first_eid)

        lines = [description]
        for name, val in values.items():
            lines.append(f"  {name}: {val:.1f}{unit}")
        lines.append(f"{aggregation.capitalize()}: {result:.1f}{unit}")

        # Zusaetzlich: waermstes/kaeltestes bei avg
        if aggregation == "average" and len(values) >= 2:
            sorted_items = sorted(values.items(), key=lambda x: x[1])
            lines.append(f"Niedrigster: {sorted_items[0][0]} ({sorted_items[0][1]:.1f}{unit})")
            lines.append(f"Hoechster: {sorted_items[-1][0]} ({sorted_items[-1][1]:.1f}{unit})")

        return {"success": True, "message": "\n".join(lines), "result": result, "values": values}

    # ── schedule_checker ──────────────────────────────────────
    async def _exec_schedule_checker(self, config: dict, description: str) -> dict:
        """Prueft zeitbasierte Schedules."""
        schedules = config.get("schedules", [])
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        current_time_min = current_hour * 60 + current_minute
        # Locale-unabhaengige Wochentag-Namen (englisch + deutsch)
        _WEEKDAY_NAMES = {
            0: ("monday", "montag"),
            1: ("tuesday", "dienstag"),
            2: ("wednesday", "mittwoch"),
            3: ("thursday", "donnerstag"),
            4: ("friday", "freitag"),
            5: ("saturday", "samstag"),
            6: ("sunday", "sonntag"),
        }
        weekday_aliases = _WEEKDAY_NAMES.get(now.weekday(), ())

        active_schedule = None
        for sched in schedules:
            # Wochentage pruefen (optional)
            days = sched.get("days", [])
            if days:
                days_lower = [d.lower() for d in days]
                if not any(alias in days_lower for alias in weekday_aliases):
                    continue

            start = sched.get("start", "00:00")
            end = sched.get("end", "23:59")
            sh, sm = (int(x) for x in start.split(":"))
            eh, em = (int(x) for x in end.split(":"))
            start_min = sh * 60 + sm
            end_min = eh * 60 + em

            # Nacht-Zeitplaene (z.B. 22:00-06:00) beruecksichtigen
            if start_min <= end_min:
                match = start_min <= current_time_min <= end_min
            else:
                match = current_time_min >= start_min or current_time_min <= end_min

            if match:
                active_schedule = sched
                break

        if active_schedule:
            label = active_schedule.get("label", "Aktiv")
            msg = f"{description}\nStatus: {label}\nZeit: {now.strftime('%H:%M')} (aktiv seit {active_schedule.get('start', '?')})"
        else:
            msg = f"{description}\nStatus: Kein aktiver Zeitplan\nZeit: {now.strftime('%H:%M')}"

        return {
            "success": True,
            "message": msg,
            "active": active_schedule is not None,
            "schedule": active_schedule.get("label", "") if active_schedule else "",
        }


    # ── state_duration ─────────────────────────────────────────
    async def _exec_state_duration(self, config: dict, description: str) -> dict:
        """Berechnet wie lange eine Entity in einem bestimmten Zustand war."""
        entity_id = config["entity"]
        target_state = config["target_state"]
        hours = self._parse_time_range(config)

        try:
            history = await self.ha.get_history(entity_id, hours=hours)
        except Exception as e:
            return {"success": False, "message": f"Fehler: {e}"}

        if not history:
            return {"success": False, "message": f"Keine Historie fuer {entity_id}"}

        name = await self._get_entity_name(entity_id)

        # Dauer berechnen: Zeitdifferenz zwischen State-Wechseln
        total_seconds = 0
        in_target = False
        last_ts = None

        for entry in history:
            state = entry.get("state", "")
            ts_str = entry.get("last_changed", "") or entry.get("last_updated", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            if in_target and last_ts:
                total_seconds += (ts - last_ts).total_seconds()

            in_target = state == target_state
            last_ts = ts

        # Wenn aktuell noch im Target-State: bis jetzt zaehlen
        if in_target and last_ts:
            from datetime import timezone
            now = datetime.now(timezone.utc)
            total_seconds += (now - last_ts).total_seconds()

        total_minutes = total_seconds / 60
        total_hours = total_seconds / 3600

        if total_hours >= 1:
            duration_text = f"{total_hours:.1f} Stunden"
        else:
            duration_text = f"{total_minutes:.0f} Minuten"

        # Prozent der Gesamtzeit
        total_period = hours * 3600
        pct = (total_seconds / total_period * 100) if total_period else 0

        msg = (
            f"{description}\n"
            f"{name}: '{target_state}' fuer {duration_text} (letzte {hours}h)\n"
            f"Anteil: {pct:.1f}% der Gesamtzeit"
        )
        return {
            "success": True, "message": msg,
            "duration_seconds": total_seconds, "duration_hours": total_hours,
            "percentage": pct,
        }

    # ── time_comparison ───────────────────────────────────────
    async def _exec_time_comparison(self, config: dict, description: str) -> dict:
        """Vergleicht eine Entity mit sich selbst ueber verschiedene Zeitraeume."""
        entity_id = config["entity"]
        compare_period = config.get("compare_period", "yesterday")
        aggregation = config.get("aggregation", "average")

        # Zeitraeume bestimmen
        if compare_period == "yesterday":
            current_hours = 24
            offset_hours = 24
            period_label = "gestern"
        elif compare_period == "last_week":
            current_hours = 168
            offset_hours = 168
            period_label = "letzte Woche"
        elif compare_period == "last_month":
            current_hours = 720
            offset_hours = 720
            period_label = "letzter Monat"
        else:
            current_hours = 24
            offset_hours = 24
            period_label = "vorheriger Zeitraum"

        name = await self._get_entity_name(entity_id)
        unit = await self._get_entity_unit(entity_id)

        # Aktuelle Periode
        try:
            current_history = await self.ha.get_history(entity_id, hours=current_hours)
        except Exception:
            current_history = None

        # Vorherige Periode (doppelter Zeitraum holen, erste Haelfte nehmen)
        try:
            full_history = await self.ha.get_history(entity_id, hours=current_hours + offset_hours)
        except Exception:
            full_history = None

        def _aggregate(entries):
            if not entries:
                return None
            vals = []
            for e in entries:
                try:
                    vals.append(float(e.get("state", "")))
                except (ValueError, TypeError):
                    pass
            if not vals:
                return None
            if aggregation == "average":
                return sum(vals) / len(vals)
            elif aggregation == "min":
                return min(vals)
            elif aggregation == "max":
                return max(vals)
            elif aggregation == "sum":
                return sum(vals)
            return sum(vals) / len(vals)

        current_val = _aggregate(current_history)
        if current_val is None:
            return {"success": False, "message": f"Keine aktuellen Daten fuer {name}"}

        # Vorherige Periode: alle Eintraege die NICHT in current_history sind
        previous_val = None
        if full_history and current_history:
            current_count = len(current_history)
            previous_entries = full_history[:-current_count] if current_count < len(full_history) else []
            previous_val = _aggregate(previous_entries)

        if previous_val is None:
            return {"success": False, "message": f"Keine historischen Daten fuer Vergleich ({period_label})"}

        diff = current_val - previous_val
        pct_change = ((diff / previous_val) * 100) if previous_val != 0 else 0
        trend = "hoeher" if diff > 0 else ("niedriger" if diff < 0 else "gleich")

        msg = (
            f"{description}\n"
            f"{name} ({aggregation}):\n"
            f"  Aktuell: {current_val:.1f}{unit}\n"
            f"  {period_label.capitalize()}: {previous_val:.1f}{unit}\n"
            f"  Aenderung: {diff:+.1f}{unit} ({pct_change:+.1f}%) — {trend}"
        )
        return {
            "success": True, "message": msg,
            "current": current_val, "previous": previous_val,
            "diff": diff, "pct_change": pct_change,
        }


# ── Globale Instanz (lazy) ────────────────────────────────────
_registry: Optional[DeclarativeToolRegistry] = None


def get_registry() -> DeclarativeToolRegistry:
    """Liefert die globale Registry (lazy init)."""
    global _registry
    if _registry is None:
        _registry = DeclarativeToolRegistry()
    return _registry


# ══════════════════════════════════════════════════════════════
# Tool-Vorschlaege: Regel-basierte Analyse + LLM-Verfeinerung
# ══════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    """Erzeugt einen Tool-Namen aus einem Text."""
    import re
    slug = text.lower().replace(" ", "_").replace("-", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:40] or "entity"


def generate_suggestions(states: list[dict], existing_tools: dict) -> list[dict]:
    """Analysiert HA-Entities und generiert Tool-Vorschlaege (regel-basiert).

    Args:
        states: Alle HA-Entity-States (von ha.get_states())
        existing_tools: Bereits existierende Tools (name → config)

    Returns:
        Liste von Vorschlaegen: [{name, description, type, config, reason}]
    """
    if not states:
        return []

    existing_names = set(existing_tools.keys())

    # Entities nach Typ gruppieren
    temp_sensors: list[dict] = []      # {eid, friendly, outdoor}
    humidity_sensors: list[dict] = []
    energy_sensors: list[dict] = []
    power_sensors: list[dict] = []
    binary_window: list[dict] = []
    binary_door: list[dict] = []
    binary_motion: list[dict] = []
    co2_sensors: list[dict] = []
    battery_sensors: list[dict] = []
    lights: list[dict] = []
    climate_entities: list[dict] = []
    media_players: list[dict] = []
    switches: list[dict] = []

    outdoor_kw = ("aussen", "outdoor", "balkon", "garten", "terrasse",
                  "draussen", "exterior", "outside", "weather", "wetter")

    # Hidden-Entities filtern (is_entity_hidden aus function_calling)
    try:
        from .function_calling import is_entity_hidden
    except ImportError:
        is_entity_hidden = None

    for s in states:
        eid = s.get("entity_id", "")
        attrs = s.get("attributes", {}) or {}
        friendly = attrs.get("friendly_name", "")
        dc = attrs.get("device_class", "")
        unit = attrs.get("unit_of_measurement", "")
        if "." not in eid:
            continue
        # Versteckte Entities ueberspringen
        if is_entity_hidden and is_entity_hidden(eid):
            continue
        domain = eid.split(".")[0]
        lower_eid = eid.lower()
        lower_friendly = friendly.lower() if friendly else ""
        is_outdoor = any(kw in lower_eid or kw in lower_friendly for kw in outdoor_kw)

        if domain == "sensor":
            if dc == "temperature" or unit in ("°C", "°F"):
                temp_sensors.append({"eid": eid, "friendly": friendly, "outdoor": is_outdoor})
            elif dc == "humidity" or (unit in ("%", "%rH") and ("humid" in lower_eid or "feucht" in lower_eid or "luftfeuch" in lower_eid)):
                humidity_sensors.append({"eid": eid, "friendly": friendly})
            elif dc == "energy" or unit in ("kWh", "Wh"):
                energy_sensors.append({"eid": eid, "friendly": friendly})
            elif dc == "power" or unit in ("W", "kW"):
                power_sensors.append({"eid": eid, "friendly": friendly})
            elif dc in ("co2", "carbon_dioxide") or (unit == "ppm" and "co2" in lower_eid):
                co2_sensors.append({"eid": eid, "friendly": friendly})
            elif dc == "battery":
                battery_sensors.append({"eid": eid, "friendly": friendly})
        elif domain == "binary_sensor":
            # Nur Name-Teil nach dem Punkt fuer Keyword-Matching (vermeidet False Positives)
            name_part = "_" + lower_eid.split(".", 1)[1] + "_" if "." in lower_eid else lower_eid
            if dc in ("window", "opening") or "_fenster" in name_part or ("_window" in name_part and "_windows_" not in name_part):
                binary_window.append({"eid": eid, "friendly": friendly})
            elif dc == "door" or "_tuer" in name_part or ("_door" in name_part and "_outdoor" not in name_part and "_indoor" not in name_part):
                binary_door.append({"eid": eid, "friendly": friendly})
            elif dc == "motion" or "_motion" in name_part or "_bewegung" in name_part:
                binary_motion.append({"eid": eid, "friendly": friendly})
        elif domain == "light":
            lights.append({"eid": eid, "friendly": friendly})
        elif domain == "climate":
            climate_entities.append({"eid": eid, "friendly": friendly})
        elif domain == "media_player":
            media_players.append({"eid": eid, "friendly": friendly})
        elif domain == "switch":
            switches.append({"eid": eid, "friendly": friendly})

    suggestions: list[dict] = []

    def _add(name: str, desc: str, tool_type: str, config: dict, reason: str):
        if name not in existing_names and not any(sg["name"] == name for sg in suggestions):
            suggestions.append({
                "name": name, "description": desc,
                "type": tool_type, "config": config, "reason": reason,
            })

    # ── Temperatur-Vorschlaege ────────────────────────────────
    indoor = [t for t in temp_sensors if not t["outdoor"]]
    outdoor = [t for t in temp_sensors if t["outdoor"]]

    # Innen vs. Aussen Vergleich
    if indoor and outdoor:
        _add("innen_vs_aussen",
             f"Temperaturunterschied {indoor[0]['friendly'] or 'innen'} vs. {outdoor[0]['friendly'] or 'aussen'}",
             "entity_comparison",
             {"entity_a": indoor[0]["eid"], "entity_b": outdoor[0]["eid"], "operation": "difference"},
             "Du hast Innen- und Aussen-Temperatursensoren — der Vergleich hilft bei Lueftungsentscheidungen.")

    # Durchschnittstemperatur aller Raeume
    if len(indoor) >= 2:
        _add("raumtemperaturen",
             f"Durchschnittstemperatur aller {len(indoor)} Raeume",
             "entity_aggregator",
             {"entities": [t["eid"] for t in indoor[:8]], "aggregation": "average"},
             f"{len(indoor)} Temperatursensoren gefunden — so sehe ich den Durchschnitt und den kaeltesten Raum.")

    # Kaeltester Raum
    if len(indoor) >= 3:
        _add("kaeltester_raum",
             "Findet den kaeltesten Raum",
             "entity_aggregator",
             {"entities": [t["eid"] for t in indoor[:8]], "aggregation": "min"},
             "Bei mehreren Raeumen kann ich erkennen wo es zu kalt ist.")

    # Aussen-Temperatur Trend
    if outdoor:
        _add("temperatur_trend_aussen",
             f"Temperatur-Trend aussen ({outdoor[0]['friendly'] or outdoor[0]['eid']})",
             "trend_analyzer",
             {"entity": outdoor[0]["eid"], "time_range": "24h"},
             "Der Trend der Aussentemperatur hilft bei Empfehlungen zu Heizung und Lueftung.")

    # Raumtemperatur Komfortbereich
    if indoor:
        _add("raumtemperatur_check",
             f"Raumtemperatur Komfortbereich ({indoor[0]['friendly'] or 'Hauptsensor'})",
             "threshold_monitor",
             {"entity": indoor[0]["eid"], "thresholds": {"min": 19, "max": 23}},
             "Ich kann warnen wenn die Raumtemperatur aus dem Wohlfuehlbereich faellt.")

    # ── Luftfeuchtigkeit ──────────────────────────────────────
    if humidity_sensors:
        _add("luftfeuchtigkeit_check",
             f"Luftfeuchtigkeit Komfortbereich ({humidity_sensors[0]['friendly'] or humidity_sensors[0]['eid']})",
             "threshold_monitor",
             {"entity": humidity_sensors[0]["eid"], "thresholds": {"min": 40, "max": 60}},
             "Luftfeuchtigkeit zwischen 40-60% ist optimal — darauf kann ich hinweisen.")

    if len(humidity_sensors) >= 2:
        _add("feuchtester_raum",
             "Hoechste Luftfeuchtigkeit finden",
             "entity_aggregator",
             {"entities": [h["eid"] for h in humidity_sensors[:6]], "aggregation": "max"},
             f"{len(humidity_sensors)} Feuchtigkeitssensoren — ich finde den feuchtesten Raum.")

    # ── CO2 ───────────────────────────────────────────────────
    if co2_sensors:
        _add("co2_warnung",
             f"CO2-Warnung ({co2_sensors[0]['friendly'] or co2_sensors[0]['eid']})",
             "threshold_monitor",
             {"entity": co2_sensors[0]["eid"], "thresholds": {"max": 1000}},
             "CO2 ueber 1000 ppm beeintraechtigt die Konzentration — ich kann rechtzeitig warnen.")

    # ── Energie ───────────────────────────────────────────────
    if energy_sensors:
        _add("stromverbrauch_trend",
             f"Stromverbrauch Trend ({energy_sensors[0]['friendly'] or energy_sensors[0]['eid']})",
             "trend_analyzer",
             {"entity": energy_sensors[0]["eid"], "time_range": "7d"},
             "Ein 7-Tage-Trend zeigt ob der Stromverbrauch steigt oder sinkt.")

        _add("strom_vs_gestern",
             f"Stromverbrauch heute vs. gestern ({energy_sensors[0]['friendly'] or energy_sensors[0]['eid']})",
             "time_comparison",
             {"entity": energy_sensors[0]["eid"], "compare_period": "yesterday", "aggregation": "average"},
             "Tagesvergleich zeigt ob heute mehr oder weniger Strom verbraucht wird.")

    if len(energy_sensors) >= 2:
        # Eindeutige Labels erzeugen (Kollisionsvermeidung)
        energy_entities = {}
        for e in energy_sensors[:5]:
            label = _slugify(e["friendly"] or e["eid"].split(".")[1])
            if label in energy_entities:
                label = _slugify(e["eid"].split(".")[1])
            # Immer noch Kollision? Suffix anhaengen
            base = label
            counter = 2
            while label in energy_entities:
                label = f"{base}_{counter}"
                counter += 1
            energy_entities[label] = e["eid"]
        _add("gesamt_stromverbrauch",
             "Summe aller Energiezaehler",
             "multi_entity_formula",
             {"entities": energy_entities, "formula": "sum"},
             f"{len(energy_sensors)} Energiezaehler — die Summe gibt den Gesamtverbrauch.")

    # Strom: 2 Power-Sensoren vergleichen (z.B. Solar vs. Verbrauch)
    if len(power_sensors) >= 2:
        solar = [p for p in power_sensors if any(kw in p["eid"].lower() for kw in ("solar", "pv", "photovoltaik"))]
        consumption = [p for p in power_sensors if p not in solar]
        if solar and consumption:
            _add("solar_vs_verbrauch",
                 f"Solar vs. Verbrauch ({solar[0]['friendly'] or 'Solar'} / {consumption[0]['friendly'] or 'Verbrauch'})",
                 "entity_comparison",
                 {"entity_a": solar[0]["eid"], "entity_b": consumption[0]["eid"], "operation": "ratio"},
                 "Verhaeltnis Solar-Erzeugung zu Verbrauch — zeigt die Eigenverbrauchs-Quote.")

    # ── Batterie ──────────────────────────────────────────────
    if battery_sensors:
        lowest_bat = battery_sensors[0]
        _add("batterie_check",
             f"Batterie-Warnung ({lowest_bat['friendly'] or lowest_bat['eid']})",
             "threshold_monitor",
             {"entity": lowest_bat["eid"], "thresholds": {"min": 20}},
             "Ich warne wenn die Batterie unter 20% faellt — bevor der Sensor ausfaellt.")

    # ── Fenster ───────────────────────────────────────────────
    if binary_window:
        _add("fenster_oeffnungen",
             f"Fenster-Oeffnungen zaehlen ({len(binary_window)} Sensoren)",
             "event_counter",
             {"entities": [w["eid"] for w in binary_window[:6]], "count_state": "on", "time_range": "24h"},
             f"{len(binary_window)} Fensterkontakte — ich zaehle wie oft gelueftet wurde.")

        _add("fenster_offen_dauer",
             f"Fenster-Oeffnungsdauer ({binary_window[0]['friendly'] or binary_window[0]['eid']})",
             "state_duration",
             {"entity": binary_window[0]["eid"], "target_state": "on", "time_range": "24h"},
             "Wie lange war das Fenster heute offen? Hilft bei der Heizungs-Optimierung.")

    # ── Tueren ────────────────────────────────────────────────
    if binary_door:
        _add("tuer_oeffnungen",
             f"Tuer-Oeffnungen zaehlen ({len(binary_door)} Sensoren)",
             "event_counter",
             {"entities": [d["eid"] for d in binary_door[:6]], "count_state": "on", "time_range": "24h"},
             f"{len(binary_door)} Tuerkontakte — ich sehe wie aktiv der Haushalt ist.")

    # ── Bewegung ──────────────────────────────────────────────
    if binary_motion:
        _add("bewegung_aktivitaet",
             f"Bewegungsmelder-Aktivitaet ({len(binary_motion)} Sensoren)",
             "event_counter",
             {"entities": [m["eid"] for m in binary_motion[:6]], "count_state": "on", "time_range": "24h"},
             f"{len(binary_motion)} Bewegungsmelder — zeigt Aktivitaetsmuster im Haus.")

    # ── Heizung ───────────────────────────────────────────────
    if climate_entities:
        _add("heizung_laufzeit",
             f"Heizungs-Laufzeit ({climate_entities[0]['friendly'] or climate_entities[0]['eid']})",
             "state_duration",
             {"entity": climate_entities[0]["eid"], "target_state": "heating", "time_range": "24h"},
             "Wie viele Stunden hat die Heizung heute gelaufen? Wichtig fuer Energiekosten.")

    # ── Medien ────────────────────────────────────────────────
    if media_players:
        tv = [m for m in media_players if any(kw in m["eid"].lower()
              for kw in ("tv", "fernseh", "fire_tv", "apple_tv", "chromecast"))]
        if tv:
            _add("tv_nutzung",
                 f"TV-Nutzung ({tv[0]['friendly'] or tv[0]['eid']})",
                 "state_duration",
                 {"entity": tv[0]["eid"], "target_state": "on", "time_range": "7d"},
                 "Wie viele Stunden lief der Fernseher diese Woche?")

    # ── Licht ─────────────────────────────────────────────────
    if len(lights) >= 3:
        _add("licht_schaltungen",
             f"Licht-Schaltungen zaehlen ({len(lights)} Lichter)",
             "event_counter",
             {"entities": [l["eid"] for l in lights[:8]], "count_state": "on", "time_range": "24h"},
             f"{len(lights)} Lichter — zeigt wie oft Lichter geschaltet wurden (Automatisierungs-Potential).")

    return suggestions


async def refine_suggestions_with_llm(
    suggestions: list[dict],
    ollama_client,
    model: str = "",
) -> list[dict]:
    """Verfeinert Vorschlaege per LLM (Beschreibungen verbessern, Priorisierung).

    Args:
        suggestions: Regel-basierte Vorschlaege
        ollama_client: OllamaClient Instanz
        model: Optionaler Modellname

    Returns:
        Verfeinerte Vorschlaege mit besseren Beschreibungen und Prioritaet
    """
    if not suggestions:
        return []

    # Vorschlaege als kompaktes Format fuer das LLM aufbereiten
    items = []
    for i, s in enumerate(suggestions):
        items.append(f"{i+1}. Name: {s['name']}, Typ: {s['type']}, "
                     f"Beschreibung: {s['description']}, Grund: {s['reason']}")

    prompt = (
        "Du bist Jarvis, ein Smart-Home-Assistent. "
        "Ich habe folgende Analyse-Tool-Vorschlaege basierend auf den vorhandenen Home-Assistant-Entities generiert. "
        "Bitte:\n"
        "1. Verbessere jede Beschreibung (kurz, deutsch, natuerlich formuliert)\n"
        "2. Ordne die Vorschlaege nach Nuetzlichkeit (wichtigste zuerst)\n"
        "3. Gib fuer jeden einen verbesserten 'reason' (1 Satz, warum das dem User hilft)\n\n"
        "Vorschlaege:\n" + "\n".join(items) + "\n\n"
        "Antworte NUR als JSON-Array. Jedes Element: "
        '{\"index\": 1, \"description\": \"...\", \"reason\": \"...\"}\n'
        "Keine Erklaerungen, nur das JSON-Array."
    )

    try:
        if not model:
            model = yaml_config.get("models", {}).get("fast", "")
        if not model:
            # Fallback auf smart-Model
            model = yaml_config.get("models", {}).get("smart", "")
        if not model:
            logger.debug("Kein LLM-Model konfiguriert — Verfeinerung uebersprungen")
            return suggestions

        response = await ollama_client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.3,
            max_tokens=2000,
        )

        if not response or not isinstance(response, dict):
            return suggestions
        if "error" in response:
            logger.debug("LLM-Fehler: %s", response["error"])
            return suggestions
        content = response.get("message", {}).get("content", "").strip()

        # JSON parsen
        import json
        text = content.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.debug("LLM-Antwort kein JSON-Array: %s", text[:200])
            return suggestions

        refined = json.loads(text[start:end + 1])
        if not isinstance(refined, list):
            return suggestions

        # Index-basiertes Mapping: LLM-Reihenfolge bestimmt Prioritaet
        idx_map = {}
        for item in refined:
            idx = item.get("index")
            if isinstance(idx, (int, float)) and 1 <= int(idx) <= len(suggestions):
                idx_map[int(idx) - 1] = item

        # Beschreibungen + Reasons aktualisieren, Reihenfolge beibehalten
        result = []
        # Erst die vom LLM priorisierten (in LLM-Reihenfolge)
        ordered_indices = []
        for item in refined:
            idx = item.get("index")
            if isinstance(idx, (int, float)) and 1 <= int(idx) <= len(suggestions):
                ordered_indices.append(int(idx) - 1)

        seen = set()
        for i in ordered_indices:
            if i in seen or i >= len(suggestions):
                continue
            seen.add(i)
            s = dict(suggestions[i])
            if i in idx_map:
                ref = idx_map[i]
                if ref.get("description"):
                    s["description"] = str(ref["description"])[:200]
                if ref.get("reason"):
                    s["reason"] = str(ref["reason"])[:200]
            result.append(s)

        # Restliche die das LLM nicht erwaehnt hat
        for i, s in enumerate(suggestions):
            if i not in seen:
                result.append(s)

        logger.info("LLM-Verfeinerung: %d/%d Vorschlaege verfeinert", len(idx_map), len(suggestions))
        return result

    except Exception as e:
        logger.warning("LLM-Verfeinerung fehlgeschlagen (Fallback auf Regel-Basis): %s", e)
        return suggestions
