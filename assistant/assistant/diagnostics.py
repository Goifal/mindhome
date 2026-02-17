"""
Diagnostics Engine - Phase 10: Selbst-Diagnostik + Wartungs-Assistent.

Feature 10.4: Sensor-Watchdog
- Erkennt offline Entities, niedrige Batterien, stale Sensoren
- Meldet Probleme ueber ProactiveManager

Feature 10.5: Wartungs-Assistent
- Prueft faellige Wartungsaufgaben aus maintenance.yaml
- Sanfte Erinnerungen (LOW Priority)
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Wartungs-Config Pfad
_CONFIG_DIR = Path(__file__).parent.parent / "config"


class DiagnosticsEngine:
    """Ueberwacht System-Gesundheit und Wartungsaufgaben."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client

        # Konfiguration
        diag_cfg = yaml_config.get("diagnostics", {})
        self.enabled = diag_cfg.get("enabled", True)
        self.check_interval = diag_cfg.get("check_interval_minutes", 30)
        self.battery_threshold = diag_cfg.get("battery_warning_threshold", 20)
        self.stale_minutes = diag_cfg.get("stale_sensor_minutes", 120)
        self.offline_minutes = diag_cfg.get("offline_threshold_minutes", 30)
        self.alert_cooldown = diag_cfg.get("alert_cooldown_minutes", 60)

        # Wartungs-Config
        maint_cfg = yaml_config.get("maintenance", {})
        self.maintenance_enabled = maint_cfg.get("enabled", True)
        self._maintenance_file = _CONFIG_DIR / "maintenance.yaml"

        # Cooldown-Tracking: {alert_key: last_alert_time}
        self._alert_cooldowns: dict[str, datetime] = {}

        if self.enabled:
            logger.info(
                "DiagnosticsEngine initialisiert (battery<%d%%, stale>%dmin, offline>%dmin)",
                self.battery_threshold, self.stale_minutes, self.offline_minutes,
            )

    async def check_all(self) -> dict:
        """Fuehrt alle Diagnostik-Checks durch.

        Returns:
            Dict mit:
                issues: Liste von Problem-Dicts
                maintenance_due: Liste faelliger Wartungen
                healthy: bool - Alles OK?
        """
        result = {
            "issues": [],
            "maintenance_due": [],
            "healthy": True,
        }

        if self.enabled:
            issues = await self.check_entities()
            result["issues"] = issues
            if issues:
                result["healthy"] = False

        if self.maintenance_enabled:
            due = self.check_maintenance()
            result["maintenance_due"] = due

        return result

    # ------------------------------------------------------------------
    # Feature 10.4: Entity-Diagnostik
    # ------------------------------------------------------------------

    async def check_entities(self) -> list[dict]:
        """Prueft alle HA-Entities auf Probleme.

        Returns:
            Liste von Problem-Dicts mit:
                entity_id, issue_type, message, severity
        """
        if not self.enabled:
            return []

        states = await self.ha.get_states()
        if not states:
            return []

        issues = []
        now = datetime.now()

        for state in states:
            entity_id = state.get("entity_id", "")
            current_state = state.get("state", "")
            attrs = state.get("attributes", {})
            last_changed = state.get("last_changed", "")
            friendly_name = attrs.get("friendly_name", entity_id)

            # 1. Offline-Check: Entity "unavailable" seit > Schwellwert
            if current_state == "unavailable":
                if last_changed:
                    try:
                        changed_dt = datetime.fromisoformat(
                            last_changed.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                        offline_mins = (now - changed_dt).total_seconds() / 60
                        if offline_mins >= self.offline_minutes:
                            issue = {
                                "entity_id": entity_id,
                                "issue_type": "offline",
                                "message": f"{friendly_name} offline seit {int(offline_mins)} Minuten",
                                "severity": "warning",
                                "minutes": int(offline_mins),
                            }
                            if self._check_cooldown(f"offline:{entity_id}"):
                                issues.append(issue)
                    except (ValueError, TypeError):
                        pass

            # 2. Batterie-Check
            battery = attrs.get("battery_level") or attrs.get("battery")
            if battery is not None:
                try:
                    bat_val = float(battery)
                    if bat_val < self.battery_threshold:
                        issue = {
                            "entity_id": entity_id,
                            "issue_type": "low_battery",
                            "message": f"{friendly_name} Batterie niedrig: {int(bat_val)}%",
                            "severity": "warning" if bat_val > 5 else "critical",
                            "battery_level": int(bat_val),
                        }
                        if self._check_cooldown(f"battery:{entity_id}"):
                            issues.append(issue)
                except (ValueError, TypeError):
                    pass

            # 3. Stale-Sensor-Check: Sensor hat sich lange nicht aktualisiert
            if entity_id.startswith("sensor.") or entity_id.startswith("binary_sensor."):
                if current_state not in ("unavailable", "unknown") and last_changed:
                    try:
                        changed_dt = datetime.fromisoformat(
                            last_changed.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                        stale_mins = (now - changed_dt).total_seconds() / 60
                        if stale_mins >= self.stale_minutes:
                            # Nur bei Sensoren die sich normalerweise aendern
                            device_class = attrs.get("device_class", "")
                            if device_class in (
                                "motion", "temperature", "humidity",
                                "power", "energy", "battery",
                            ):
                                issue = {
                                    "entity_id": entity_id,
                                    "issue_type": "stale",
                                    "message": f"{friendly_name} seit {int(stale_mins)} Minuten unveraendert",
                                    "severity": "info",
                                    "minutes": int(stale_mins),
                                }
                                if self._check_cooldown(f"stale:{entity_id}"):
                                    issues.append(issue)
                    except (ValueError, TypeError):
                        pass

        return issues

    async def get_system_status(self) -> dict:
        """Erstellt einen vollstaendigen System-Status-Report."""
        states = await self.ha.get_states()
        if not states:
            return {"error": "Keine HA-Verbindung"}

        total = len(states)
        unavailable = sum(1 for s in states if s.get("state") == "unavailable")
        unknown = sum(1 for s in states if s.get("state") == "unknown")

        # Batterie-Uebersicht
        low_batteries = []
        for state in states:
            attrs = state.get("attributes", {})
            battery = attrs.get("battery_level") or attrs.get("battery")
            if battery is not None:
                try:
                    bat_val = float(battery)
                    if bat_val < self.battery_threshold:
                        name = attrs.get("friendly_name", state.get("entity_id", ""))
                        low_batteries.append({"name": name, "level": int(bat_val)})
                except (ValueError, TypeError):
                    pass

        # Domain-Zusammenfassung
        domains = {}
        for state in states:
            eid = state.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else "unknown"
            if domain not in domains:
                domains[domain] = {"total": 0, "unavailable": 0}
            domains[domain]["total"] += 1
            if state.get("state") == "unavailable":
                domains[domain]["unavailable"] += 1

        return {
            "total_entities": total,
            "unavailable": unavailable,
            "unknown": unknown,
            "healthy_percent": round((total - unavailable - unknown) / max(total, 1) * 100, 1),
            "low_batteries": low_batteries,
            "domains": domains,
        }

    def _check_cooldown(self, alert_key: str) -> bool:
        """Prueft ob ein Alert gesendet werden darf (Cooldown)."""
        now = datetime.now()
        last = self._alert_cooldowns.get(alert_key)
        if last and (now - last) < timedelta(minutes=self.alert_cooldown):
            return False
        self._alert_cooldowns[alert_key] = now
        return True

    # ------------------------------------------------------------------
    # Feature 10.5: Wartungs-Assistent
    # ------------------------------------------------------------------

    def check_maintenance(self) -> list[dict]:
        """Prueft welche Wartungsaufgaben faellig sind.

        Returns:
            Liste faelliger Aufgaben mit name, days_overdue, priority
        """
        if not self.maintenance_enabled:
            return []

        tasks = self._load_maintenance_tasks()
        due = []
        today = datetime.now().date()

        for task in tasks:
            name = task.get("name", "")
            interval = task.get("interval_days", 0)
            last_done = task.get("last_done")
            priority = task.get("priority", "low")

            if not interval:
                continue

            if last_done:
                try:
                    if isinstance(last_done, str):
                        last_date = datetime.strptime(last_done, "%Y-%m-%d").date()
                    else:
                        last_date = last_done
                    next_due = last_date + timedelta(days=interval)
                    if today >= next_due:
                        days_overdue = (today - next_due).days
                        due.append({
                            "name": name,
                            "days_overdue": days_overdue,
                            "priority": priority,
                            "last_done": str(last_date),
                            "description": task.get("description", ""),
                        })
                except (ValueError, TypeError):
                    # Ungueltiges Datum → als faellig markieren
                    due.append({
                        "name": name,
                        "days_overdue": 0,
                        "priority": priority,
                        "last_done": None,
                        "description": task.get("description", ""),
                    })
            else:
                # Noch nie gemacht → faellig
                due.append({
                    "name": name,
                    "days_overdue": 0,
                    "priority": priority,
                    "last_done": None,
                    "description": task.get("description", ""),
                })

        return due

    def complete_task(self, task_name: str) -> bool:
        """Markiert eine Wartungsaufgabe als erledigt.

        Args:
            task_name: Name der Aufgabe

        Returns:
            True wenn erfolgreich
        """
        tasks = self._load_maintenance_tasks()
        found = False

        for task in tasks:
            if task.get("name", "").lower() == task_name.lower():
                task["last_done"] = datetime.now().strftime("%Y-%m-%d")
                found = True
                break

        if found:
            self._save_maintenance_tasks(tasks)
            logger.info("Wartungsaufgabe erledigt: %s", task_name)

        return found

    def get_maintenance_tasks(self) -> list[dict]:
        """Gibt alle Wartungsaufgaben zurueck."""
        return self._load_maintenance_tasks()

    def _load_maintenance_tasks(self) -> list[dict]:
        """Laedt Wartungsaufgaben aus YAML."""
        try:
            if self._maintenance_file.exists():
                with open(self._maintenance_file) as f:
                    data = yaml.safe_load(f)
                    return data.get("tasks", [])
        except Exception as e:
            logger.warning("maintenance.yaml laden fehlgeschlagen: %s", e)
        return []

    def _save_maintenance_tasks(self, tasks: list[dict]):
        """Speichert Wartungsaufgaben in YAML."""
        try:
            data = {"tasks": tasks}
            with open(self._maintenance_file, "w") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            logger.error("maintenance.yaml speichern fehlgeschlagen: %s", e)

    def health_status(self) -> str:
        """Gibt den eigenen Status zurueck."""
        if not self.enabled:
            return "disabled"
        return "active"
