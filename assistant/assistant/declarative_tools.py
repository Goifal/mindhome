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

Sicherheit:
- Kein Python-Code wird ausgefuehrt
- Nur Lese-Zugriff auf HA-Daten (get_state, get_history)
- Schema-Validierung fuer alle Configs
- Max 20 aktive Tools
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
            if not thresholds.get("min") and not thresholds.get("max"):
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

        return None


# ── Executor ──────────────────────────────────────────────────
class DeclarativeToolExecutor:
    """Fuehrt deklarative Tools aus — nur Lese-Zugriff auf HA."""

    def __init__(self, ha_client):
        self.ha = ha_client
        self.registry = DeclarativeToolRegistry()

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
        weekday = now.strftime("%A").lower()

        active_schedule = None
        for sched in schedules:
            # Wochentage pruefen (optional)
            days = sched.get("days", [])
            if days and weekday not in [d.lower() for d in days]:
                continue

            start = sched.get("start", "00:00")
            end = sched.get("end", "23:59")
            sh, sm = (int(x) for x in start.split(":"))
            eh, em = (int(x) for x in end.split(":"))
            start_min = sh * 60 + sm
            end_min = eh * 60 + em

            if start_min <= current_time_min <= end_min:
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


# ── Globale Instanz (lazy) ────────────────────────────────────
_registry: Optional[DeclarativeToolRegistry] = None


def get_registry() -> DeclarativeToolRegistry:
    """Liefert die globale Registry (lazy init)."""
    global _registry
    if _registry is None:
        _registry = DeclarativeToolRegistry()
    return _registry
