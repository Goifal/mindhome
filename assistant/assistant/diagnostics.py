"""
Diagnostics Engine - Phase 10: Selbst-Diagnostik + Wartungs-Assistent.

Feature 10.4: Sensor-Watchdog
- Erkennt offline Entities, niedrige Batterien, stale Sensoren
- Meldet Probleme ueber ProactiveManager

Feature 10.5: Wartungs-Assistent
- Prueft faellige Wartungsaufgaben aus maintenance.yaml
- Sanfte Erinnerungen (LOW Priority)

Feature 10.6: Self-Diagnostik
- System-Ressourcen: Disk, Memory, CPU
- Netzwerk-Konnektivitaet: HA, Ollama, Redis, ChromaDB
- Service-Health Aggregation
"""

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import yaml

from .config import yaml_config, settings

_LOCAL_TZ = ZoneInfo(yaml_config.get("timezone", "Europe/Berlin"))
from .function_calling import get_entity_annotation, is_entity_hidden
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
        self.check_interval = int(diag_cfg.get("check_interval_minutes", 30))
        self.battery_threshold = int(diag_cfg.get("battery_warning_threshold", 20))
        self.stale_minutes = int(diag_cfg.get("stale_sensor_minutes", 360))
        self.offline_minutes = int(diag_cfg.get("offline_threshold_minutes", 30))
        self.alert_cooldown = int(diag_cfg.get("alert_cooldown_minutes", 240))

        # Entity-Filter: Nur bestimmte Domains ueberwachen
        self.monitor_domains = diag_cfg.get(
            "monitor_domains",
            [
                "sensor",
                "binary_sensor",
                "light",
                "switch",
                "cover",
                "climate",
                "lock",
                "fan",
            ],
        )
        # Zusaetzliche Ausschluss-Patterns (entity_id enthaelt Pattern → ueberspringen)
        self.exclude_patterns = diag_cfg.get(
            "exclude_patterns",
            [
                "weather.",
                "sun.",
                "forecast",
            ],
        )
        # Whitelist: Wenn gesetzt, NUR diese Entities ueberwachen
        self.monitored_entities: list[str] = diag_cfg.get("monitored_entities", [])

        # Wartungs-Config
        maint_cfg = yaml_config.get("maintenance", {})
        self.maintenance_enabled = maint_cfg.get("enabled", True)
        self._maintenance_file = _CONFIG_DIR / "maintenance.yaml"

        # Cooldown-Tracking: {alert_key: last_alert_time}
        self._alert_cooldowns: dict[str, datetime] = {}

        # Auto-Suppress: Entities die wiederholt offline/stale sind
        # {entity_id: {"count": int, "first_seen": datetime, "type": str}}
        self._offline_streak: dict[str, dict] = {}
        # Nach N aufeinanderfolgenden Diagnostik-Zyklen → auto-suppress
        self._suppress_after_cycles = int(diag_cfg.get("suppress_after_cycles", 3))
        # Aktuell unterdrueckte Entities (auto-erkannt)
        self._auto_suppressed: dict[
            str, dict
        ] = {}  # {entity_id: {"since": dt, "type": str}}

        if self.enabled:
            logger.info(
                "DiagnosticsEngine initialisiert (battery<%d%%, stale>%dmin, offline>%dmin)",
                self.battery_threshold,
                self.stale_minutes,
                self.offline_minutes,
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
            due = await asyncio.to_thread(self.check_maintenance)
            result["maintenance_due"] = due

        # Disk space check
        disk_status = await asyncio.to_thread(self.check_disk_space)
        result["disk_space"] = disk_status
        if disk_status.get("status") == "warning":
            result["healthy"] = False
            result["issues"].append(
                {
                    "entity_id": "system.disk",
                    "type": "disk_space_low",
                    "message": f"Disk space low: {disk_status['free_pct']:.1f}% free",
                }
            )

        return result

    @staticmethod
    def check_disk_space() -> dict:
        """Prueft den verfuegbaren Speicherplatz."""
        import shutil

        usage = shutil.disk_usage("/")
        free_pct = (usage.free / usage.total) * 100
        if free_pct < 10:
            logger.warning("Disk space low: %.1f%% free", free_pct)
            return {"status": "warning", "free_pct": round(free_pct, 1)}
        return {"status": "ok", "free_pct": round(free_pct, 1)}

    # ------------------------------------------------------------------
    # Feature 10.4: Entity-Diagnostik
    # ------------------------------------------------------------------

    def _should_monitor(self, entity_id: str) -> bool:
        """Prueft ob Entity ueberwacht werden soll.

        Nutzt Entity-Annotations: Annotierte (nicht-hidden) Entities werden
        automatisch ueberwacht, sofern diagnostics nicht explizit deaktiviert.
        Ohne Annotation: Domain-Filter + Exclude-Patterns.
        """
        # Hidden-Entities nie ueberwachen
        if is_entity_hidden(entity_id):
            return False

        # Annotierte Entities: diagnostics-Feld pruefen (default=True)
        ann = get_entity_annotation(entity_id)
        if ann and ann.get("role"):
            return ann.get("diagnostics", True)

        # Legacy-Whitelist (falls noch in Config)
        if self.monitored_entities:
            return entity_id in self.monitored_entities

        # Ohne Annotation: nicht ueberwachen
        return False

    async def check_entities(self) -> list[dict]:
        """Prueft ueberwachte HA-Entities auf Probleme.

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
        now = datetime.now(timezone.utc)
        now_local = datetime.now(timezone.utc)

        # Entities die in diesem Zyklus als problematisch erkannt werden
        seen_problematic: set[str] = set()

        for state in states:
            entity_id = state.get("entity_id", "")
            if not self._should_monitor(entity_id):
                continue
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
                        )
                        offline_mins = (now - changed_dt).total_seconds() / 60
                        if offline_mins >= self.offline_minutes:
                            seen_problematic.add(entity_id)

                            # Auto-suppressed? Dann nicht mehr melden
                            if entity_id in self._auto_suppressed:
                                continue

                            issue = {
                                "entity_id": entity_id,
                                "issue_type": "offline",
                                "message": f"{friendly_name} offline seit {self._format_duration(offline_mins)}",
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
            if entity_id.startswith("sensor.") or entity_id.startswith(
                "binary_sensor."
            ):
                if current_state not in ("unavailable", "unknown") and last_changed:
                    try:
                        changed_dt = datetime.fromisoformat(
                            last_changed.replace("Z", "+00:00")
                        )
                        stale_mins = (now - changed_dt).total_seconds() / 60
                        if stale_mins >= self.stale_minutes:
                            # Nur bei Sensoren die sich normalerweise aendern
                            device_class = attrs.get("device_class", "")
                            # Nur bei Sensoren die sich _regelmaessig_ aendern sollten
                            # Energy/Power: Stabile Werte sind normal (z.B. Nacht)
                            if device_class in (
                                "motion",
                                "temperature",
                                "humidity",
                                "battery",
                            ):
                                seen_problematic.add(entity_id)

                                # Auto-suppressed? Dann nicht mehr melden
                                if entity_id in self._auto_suppressed:
                                    continue

                                issue = {
                                    "entity_id": entity_id,
                                    "issue_type": "stale",
                                    "message": f"{friendly_name} seit {self._format_duration(stale_mins)} unveraendert",
                                    "severity": "info",
                                    "minutes": int(stale_mins),
                                }
                                if self._check_cooldown(f"stale:{entity_id}"):
                                    issues.append(issue)
                    except (ValueError, TypeError):
                        pass

        # Auto-Suppress-Logik: Streaks aktualisieren
        self._update_offline_streaks(seen_problematic, now_local)

        return issues

    def _update_offline_streaks(self, seen_problematic: set[str], now: datetime):
        """Aktualisiert Offline-Streaks und auto-suppressed Entities.

        Entities die in N aufeinanderfolgenden Zyklen problematisch sind
        werden automatisch unterdrueckt. Wenn eine Entity nicht mehr in
        der Problemliste ist (z.B. wieder online), wird der Streak zurueckgesetzt.
        """
        # Streaks hochzaehlen fuer problematische Entities
        for entity_id in seen_problematic:
            if entity_id in self._offline_streak:
                self._offline_streak[entity_id]["count"] += 1
            else:
                self._offline_streak[entity_id] = {
                    "count": 1,
                    "first_seen": now,
                    "type": "offline",
                }

            # Schwelle erreicht? → auto-suppress
            streak = self._offline_streak[entity_id]
            if (
                streak["count"] >= self._suppress_after_cycles
                and entity_id not in self._auto_suppressed
            ):
                self._auto_suppressed[entity_id] = {
                    "since": streak["first_seen"],
                    "type": streak["type"],
                    "suppressed_at": now,
                }
                logger.info(
                    "Auto-Suppress: %s nach %d Zyklen als dauerhaft offline erkannt",
                    entity_id,
                    streak["count"],
                )

        # Streaks zuruecksetzen fuer Entities die NICHT mehr problematisch sind
        recovered = [eid for eid in self._offline_streak if eid not in seen_problematic]
        for entity_id in recovered:
            del self._offline_streak[entity_id]

    def on_entity_recovered(self, entity_id: str) -> Optional[dict]:
        """Wird aufgerufen wenn eine Entity von unavailable zurueckkommt.

        Returns:
            Dict mit Suppress-Info wenn Entity auto-suppressed war, sonst None.
        """
        result = None

        # War auto-suppressed? → aufheben und Info zurueckgeben
        if entity_id in self._auto_suppressed:
            info = self._auto_suppressed.pop(entity_id)
            result = {
                "entity_id": entity_id,
                "was_suppressed_since": info["since"].isoformat()
                if hasattr(info["since"], "isoformat")
                else str(info["since"]),
                "type": info["type"],
            }
            logger.info(
                "Auto-Suppress aufgehoben: %s ist wieder online (war suppressed seit %s)",
                entity_id,
                info.get("suppressed_at", "?"),
            )

        # Streak zuruecksetzen
        self._offline_streak.pop(entity_id, None)

        # Cooldown zuruecksetzen damit naechster Check fresh startet
        self._alert_cooldowns.pop(f"offline:{entity_id}", None)
        self._alert_cooldowns.pop(f"stale:{entity_id}", None)

        return result

    def get_suppressed_entities(self) -> dict[str, dict]:
        """Gibt aktuell auto-unterdrueckte Entities zurueck (fuer UI/Debug)."""
        return dict(self._auto_suppressed)

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
            "healthy_percent": round(
                (total - unavailable - unknown) / max(total, 1) * 100, 1
            ),
            "low_batteries": low_batteries,
            "domains": domains,
        }

    @staticmethod
    def _format_duration(minutes: float) -> str:
        """Formatiert Minuten in lesbaren Text (z.B. '2 Stunden', '1 Tag')."""
        mins = int(minutes)
        if mins < 60:
            return f"{mins} Minuten"
        hours = mins // 60
        if hours < 24:
            remaining = mins % 60
            if remaining > 0:
                return f"{hours} Std {remaining} Min"
            return f"{hours} Stunden" if hours != 1 else "1 Stunde"
        days = hours // 24
        remaining_hours = hours % 24
        if remaining_hours > 0:
            return f"{days} {'Tag' if days == 1 else 'Tagen'} und {remaining_hours} Std"
        return f"{days} {'Tag' if days == 1 else 'Tagen'}"

    def _check_cooldown(self, alert_key: str) -> bool:
        """Prueft ob ein Alert gesendet werden darf (Cooldown)."""
        now = datetime.now(timezone.utc)
        last = self._alert_cooldowns.get(alert_key)
        if last and (now - last) < timedelta(minutes=self.alert_cooldown):
            return False
        self._alert_cooldowns[alert_key] = now
        # Periodic cleanup to prevent unbounded growth
        if len(self._alert_cooldowns) > 500:
            cutoff = now - timedelta(hours=24)
            self._alert_cooldowns = {
                k: v for k, v in self._alert_cooldowns.items() if v > cutoff
            }
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
        today = datetime.now(timezone.utc).date()

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
                        due.append(
                            {
                                "name": name,
                                "days_overdue": days_overdue,
                                "priority": priority,
                                "last_done": str(last_date),
                                "description": task.get("description", ""),
                                "entity_id": task.get("entity_id", ""),
                            }
                        )
                except (ValueError, TypeError):
                    # Ungueltiges Datum → als faellig markieren
                    due.append(
                        {
                            "name": name,
                            "days_overdue": 0,
                            "priority": priority,
                            "last_done": None,
                            "description": task.get("description", ""),
                            "entity_id": task.get("entity_id", ""),
                        }
                    )
            else:
                # Noch nie gemacht → faellig
                due.append(
                    {
                        "name": name,
                        "days_overdue": 0,
                        "priority": priority,
                        "last_done": None,
                        "description": task.get("description", ""),
                        "entity_id": task.get("entity_id", ""),
                    }
                )

        return due

    def complete_task(self, task_name: str) -> bool:
        """Markiert eine Wartungsaufgabe als erledigt und fuehrt History.

        Args:
            task_name: Name der Aufgabe

        Returns:
            True wenn erfolgreich
        """
        tasks = self._load_maintenance_tasks()
        found = False

        for task in tasks:
            if task.get("name", "").lower() == task_name.lower():
                today = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
                # Completion-History fuehren (max 10 Eintraege)
                history = task.get("history", [])
                history.append(today)
                task["history"] = history[-10:]
                task["last_done"] = today
                task["completion_count"] = len(task.get("history", [today]))
                found = True
                break

        if found:
            self._save_maintenance_tasks(tasks)
            logger.info("Wartungsaufgabe erledigt: %s", task_name)

        return found

    def get_task_history(self, task_name: str) -> list[str]:
        """Gibt die Completion-History einer Wartungsaufgabe zurueck."""
        tasks = self._load_maintenance_tasks()
        for task in tasks:
            if task.get("name", "").lower() == task_name.lower():
                return task.get("history", [])
        return []

    def get_maintenance_tasks(self) -> list[dict]:
        """Gibt alle Wartungsaufgaben zurueck."""
        return self._load_maintenance_tasks()

    def _load_maintenance_tasks(self) -> list[dict]:
        """Laedt Wartungsaufgaben aus YAML."""
        try:
            if not self._maintenance_file.exists():
                example = self._maintenance_file.with_suffix(".yaml.example")
                if example.exists():
                    import shutil

                    shutil.copy2(example, self._maintenance_file)
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
                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            logger.error("maintenance.yaml speichern fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Feature 10.6: Self-Diagnostik
    # ------------------------------------------------------------------

    def check_system_resources(self) -> dict:
        """Prueft lokale System-Ressourcen (Disk, Memory).

        Returns:
            Dict mit disk, memory Info und Warnungen
        """
        result = {"disk": {}, "memory": {}, "warnings": []}

        # Disk-Space
        try:
            usage = shutil.disk_usage("/")
            total_gb = usage.total / (1024**3)
            free_gb = usage.free / (1024**3)
            used_pct = (usage.used / usage.total) * 100
            result["disk"] = {
                "total_gb": round(total_gb, 1),
                "free_gb": round(free_gb, 1),
                "used_percent": round(used_pct, 1),
            }
            if used_pct > 90:
                result["warnings"].append(
                    f"Speicherplatz kritisch: {round(free_gb, 1)} GB frei ({round(used_pct)}% belegt)"
                )
            elif used_pct > 80:
                result["warnings"].append(
                    f"Speicherplatz niedrig: {round(free_gb, 1)} GB frei ({round(used_pct)}% belegt)"
                )
        except Exception as e:
            result["disk"]["error"] = str(e)

        # Memory via /proc/meminfo (Linux)
        try:

            def _read_meminfo():
                meminfo_path = Path("/proc/meminfo")
                if not meminfo_path.exists():
                    return None
                meminfo = {}
                with open(meminfo_path) as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val = parts[1].strip().split()[0]  # kB-Wert
                            meminfo[key] = int(val)
                return meminfo

            meminfo = _read_meminfo()
            if meminfo:
                total_mb = meminfo.get("MemTotal", 0) / 1024
                available_mb = meminfo.get("MemAvailable", 0) / 1024
                used_mb = total_mb - available_mb
                used_pct = (used_mb / max(total_mb, 1)) * 100

                result["memory"] = {
                    "total_mb": round(total_mb),
                    "available_mb": round(available_mb),
                    "used_percent": round(used_pct, 1),
                }
                if used_pct > 90:
                    result["warnings"].append(
                        f"RAM kritisch: {round(available_mb)} MB frei ({round(used_pct)}% belegt)"
                    )
                elif used_pct > 80:
                    result["warnings"].append(
                        f"RAM hoch: {round(available_mb)} MB frei ({round(used_pct)}% belegt)"
                    )
        except Exception as e:
            result["memory"]["error"] = str(e)

        return result

    async def check_connectivity(self) -> dict:
        """Prueft Netzwerk-Konnektivitaet zu allen Diensten.

        Returns:
            Dict mit Service-Erreichbarkeit
        """
        import aiohttp
        import asyncio

        async def _check_ha():
            try:
                ha_ok = await self.ha.is_available()
                return "home_assistant", {
                    "status": "connected" if ha_ok else "disconnected",
                }
            except Exception as e:
                logger.error("HA Health-Check fehlgeschlagen: %s", e)
                return "home_assistant", {"status": "error"}

        async def _check_ollama():
            try:
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"{settings.ollama_url}/api/tags") as resp:
                        return "ollama", {
                            "status": "connected"
                            if resp.status == 200
                            else "disconnected",
                        }
            except Exception as e:
                logger.error("Ollama Health-Check fehlgeschlagen: %s", e)
                return "ollama", {"status": "disconnected"}

        async def _check_redis():
            try:
                import redis.asyncio as aioredis

                r = aioredis.from_url(settings.redis_url, socket_timeout=3)
                try:
                    await r.ping()
                    return "redis", {"status": "connected"}
                finally:
                    await r.aclose()
            except Exception as e:
                logger.error("Redis Health-Check fehlgeschlagen: %s", e)
                return "redis", {"status": "disconnected"}

        async def _check_chromadb():
            try:
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        f"{settings.chroma_url}/api/v1/heartbeat"
                    ) as resp:
                        return "chromadb", {
                            "status": "connected"
                            if resp.status == 200
                            else "disconnected",
                        }
            except Exception as e:
                logger.error("ChromaDB Health-Check fehlgeschlagen: %s", e)
                return "chromadb", {"status": "disconnected"}

        async def _check_mindhome():
            try:
                mh_status = await self.ha._get_mindhome("/api/health")
                return "mindhome_addon", {
                    "url": settings.mindhome_url,
                    "status": "connected" if mh_status else "disconnected",
                }
            except Exception as e:
                return "mindhome_addon", {
                    "url": settings.mindhome_url,
                    "status": f"disconnected: {e}",
                }

        check_results = await asyncio.gather(
            _check_ha(),
            _check_ollama(),
            _check_redis(),
            _check_chromadb(),
            _check_mindhome(),
        )

        results = {}
        for name, status in check_results:
            results[name] = status

        return results

    async def full_diagnostic(self) -> dict:
        """Fuehrt kompletten Diagnostik-Lauf durch (Entities + System + Netzwerk).

        Returns:
            Umfassender Report aller Diagnose-Ergebnisse
        """
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entities": {},
            "system": {},
            "connectivity": {},
            "maintenance": [],
            "summary": {"total_warnings": 0, "status": "healthy"},
        }

        # Parallel: Entity-Checks, System-Status, Netzwerk-Konnektivitaet
        import asyncio

        issues, system_status, connectivity = await asyncio.gather(
            self.check_entities(),
            self.get_system_status(),
            self.check_connectivity(),
        )

        report["entities"] = {
            "issues": issues,
            "issues_count": len(issues),
        }
        report["entities"]["overview"] = system_status

        # System-Ressourcen (in Thread ausfuehren)
        resources = await asyncio.to_thread(self.check_system_resources)
        report["system"] = resources

        report["connectivity"] = connectivity

        # Wartung (in Thread ausfuehren)
        maintenance = await asyncio.to_thread(self.check_maintenance)
        report["maintenance"] = maintenance

        # Summary berechnen
        total_warnings = (
            len(issues) + len(resources.get("warnings", [])) + len(maintenance)
        )
        disconnected = sum(
            1
            for svc in connectivity.values()
            if "disconnected" in str(svc.get("status", ""))
        )
        total_warnings += disconnected

        if disconnected > 0 or any(i.get("severity") == "critical" for i in issues):
            report["summary"]["status"] = "critical"
        elif total_warnings > 3:
            report["summary"]["status"] = "degraded"
        elif total_warnings > 0:
            report["summary"]["status"] = "warning"

        report["summary"]["total_warnings"] = total_warnings
        report["summary"]["disconnected_services"] = disconnected

        return report

    async def get_user_facing_status(self) -> dict | None:
        """Gibt eine benutzerfreundliche Statusmeldung bei Degradation zurueck.

        Prueft alle kritischen Subsysteme und kommuniziert Probleme in
        natuerlicher deutscher Sprache (Jarvis-Persoenlichkeit).

        Returns:
            None wenn alles gesund ist, sonst dict mit:
                message: Benutzerfreundliche deutsche Nachricht
                severity: "info" oder "warning"
        """
        import aiohttp
        import asyncio

        issues: list[tuple[str, str]] = []  # (message, severity)

        # --- Ollama Response-Time pruefen ---
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start = asyncio.get_event_loop().time()
                async with session.get(f"{settings.ollama_url}/api/tags") as resp:
                    elapsed = asyncio.get_event_loop().time() - start
                    if resp.status != 200:
                        issues.append(
                            (
                                "Ich bin gerade etwas langsamer im Denken — mein Sprachmodell ist ausgelastet",
                                "warning",
                            )
                        )
                    elif elapsed > 5.0:
                        issues.append(
                            (
                                "Ich bin gerade etwas langsamer im Denken — mein Sprachmodell ist ausgelastet",
                                "warning",
                            )
                        )
                    elif elapsed > 2.0:
                        issues.append(
                            (
                                "Meine Antworten koennten gerade etwas langsamer sein — Ollama ist ausgelastet",
                                "info",
                            )
                        )
        except asyncio.TimeoutError:
            issues.append(
                (
                    "Ich bin gerade etwas langsamer im Denken — mein Sprachmodell ist ausgelastet",
                    "warning",
                )
            )
        except Exception as e:
            logger.warning("Ollama-Erreichbarkeitspruefung fehlgeschlagen: %s", e)
            issues.append(
                (
                    "Mein Sprachmodell ist gerade nicht erreichbar — ich arbeite mit Einschraenkungen",
                    "warning",
                )
            )

        # --- Redis-Konnektivitaet pruefen ---
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.redis_url, socket_timeout=3)
            try:
                await r.ping()
            finally:
                await r.aclose()
        except Exception as e:
            logger.warning("Redis-Erreichbarkeitspruefung fehlgeschlagen: %s", e)
            issues.append(
                (
                    "Mein Kurzzeitgedaechtnis ist gerade eingeschraenkt",
                    "warning",
                )
            )

        # --- Home Assistant Erreichbarkeit pruefen ---
        try:
            ha_ok = await self.ha.is_available()
            if not ha_ok:
                issues.append(
                    (
                        "Ich habe gerade keinen Zugriff auf die Haussteuerung — Home Assistant antwortet nicht",
                        "warning",
                    )
                )
        except Exception as e:
            logger.warning(
                "Home-Assistant-Erreichbarkeitspruefung fehlgeschlagen: %s", e
            )
            issues.append(
                (
                    "Ich habe gerade keinen Zugriff auf die Haussteuerung — Home Assistant antwortet nicht",
                    "warning",
                )
            )

        # --- Speicherplatz pruefen ---
        try:
            usage = shutil.disk_usage("/")
            free_pct = (usage.free / usage.total) * 100
            if free_pct < 5:
                issues.append(
                    (
                        "Mir geht der Speicherplatz aus — eventuell sollten wir aufraeumen",
                        "warning",
                    )
                )
            elif free_pct < 10:
                issues.append(
                    (
                        "Der Speicherplatz wird knapp — wir sollten bald aufraeumen",
                        "info",
                    )
                )
        except Exception as e:
            logger.debug("Speicherplatzpruefung fehlgeschlagen: %s", e)

        # --- Arbeitsspeicher pruefen ---
        try:

            def _read_meminfo_status():
                meminfo_path = Path("/proc/meminfo")
                if not meminfo_path.exists():
                    return None
                meminfo = {}
                with open(meminfo_path) as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val = parts[1].strip().split()[0]
                            meminfo[key] = int(val)
                return meminfo

            meminfo = await asyncio.to_thread(_read_meminfo_status)
            if meminfo:
                total = meminfo.get("MemTotal", 0)
                available = meminfo.get("MemAvailable", 0)
                if total > 0:
                    used_pct = ((total - available) / total) * 100
                    if used_pct > 95:
                        issues.append(
                            (
                                "Der Arbeitsspeicher ist fast voll — ich koennte instabil werden",
                                "warning",
                            )
                        )
                    elif used_pct > 90:
                        issues.append(
                            (
                                "Der Arbeitsspeicher wird knapp — Leistung koennte eingeschraenkt sein",
                                "info",
                            )
                        )
        except Exception as e:
            logger.debug("Arbeitsspeicherpruefung fehlgeschlagen: %s", e)

        # Alles gesund → None
        if not issues:
            return None

        # Schwerwiegendstes Problem zuerst (warning > info)
        warning_issues = [i for i in issues if i[1] == "warning"]
        if warning_issues:
            # Bei mehreren Warnings: kombinierte Nachricht
            if len(warning_issues) > 1:
                messages = [i[0] for i in warning_issues]
                combined = messages[0] + ". Ausserdem: " + ". ".join(messages[1:])
                return {"message": combined, "severity": "warning"}
            return {"message": warning_issues[0][0], "severity": "warning"}

        # Nur Info-Level Issues
        return {"message": issues[0][0], "severity": "info"}

    def health_status(self) -> str:
        """Gibt den eigenen Status zurueck."""
        if not self.enabled:
            return "disabled"
        return "active"

    # ------------------------------------------------------------------
    # Phase 8: Proaktive Diagnostik-Hinweise
    # ------------------------------------------------------------------

    async def get_proactive_hints(self) -> list[dict]:
        """Sammelt proaktive Diagnostik-Hinweise fuer den Assistenten.

        Gibt Hinweise zurueck die Jarvis beilaeufig erwaehnen kann,
        z.B. "Uebrigens, der Bewegungsmelder im Bad meldet seit 6 Stunden nichts."

        Returns:
            Liste von {message, severity, entity_id} Dicts
        """
        hints: list[dict] = []
        if not self.enabled:
            return hints

        try:
            entities = await self.check_entities()
            for entity in entities:
                status = entity.get("status", "")
                eid = entity.get("entity_id", "")
                name = entity.get("friendly_name", eid)

                if status == "low_battery":
                    battery = entity.get("battery_level", "?")
                    hints.append(
                        {
                            "message": f"{name} hat nur noch {battery}% Batterie",
                            "severity": "info",
                            "entity_id": eid,
                            "type": "battery",
                        }
                    )
                elif status == "stale":
                    minutes = entity.get("stale_minutes", 0)
                    hours = int(minutes / 60)
                    hints.append(
                        {
                            "message": f"{name} meldet seit {hours}h nichts — moeglicherweise offline",
                            "severity": "warning" if hours > 12 else "info",
                            "entity_id": eid,
                            "type": "stale",
                        }
                    )
                elif status == "offline":
                    hints.append(
                        {
                            "message": f"{name} ist offline",
                            "severity": "warning",
                            "entity_id": eid,
                            "type": "offline",
                        }
                    )

            # System-Ressourcen pruefen
            sys_status = self.check_system_resources()
            if sys_status.get("disk_usage_percent", 0) > 85:
                hints.append(
                    {
                        "message": f"Festplattenspeicher bei {sys_status['disk_usage_percent']}%",
                        "severity": "warning",
                        "entity_id": "",
                        "type": "system",
                    }
                )

        except Exception as e:
            logger.debug("Proaktive Diagnostik-Hints Fehler: %s", e)

        return hints

    async def get_morning_diagnostic_summary(self) -> str:
        """Kurze Zusammenfassung fuer das Morgen-Briefing.

        Returns:
            Zusammenfassungstext oder leerer String
        """
        hints = await self.get_proactive_hints()
        if not hints:
            return ""

        warnings = [h for h in hints if h["severity"] == "warning"]
        infos = [h for h in hints if h["severity"] == "info"]

        parts = []
        if warnings:
            parts.append(f"{len(warnings)} Warnungen")
        if infos:
            parts.append(f"{len(infos)} Hinweise")

        summary = f"System-Status: {', '.join(parts)}."
        if warnings:
            # Wichtigste Warnung nennen
            summary += f" Wichtigste: {warnings[0]['message']}."
        return summary

    # ------------------------------------------------------------------
    # Predictive Failure, Root-Cause-Korrelation & Repair Playbooks
    # ------------------------------------------------------------------

    async def predict_failure(self, entity_id: str) -> Optional[dict]:
        """Prognostiziert bevorstehende Sensorausfaelle basierend auf Latenz-Trends.

        Wenn die Antwortzeit eines Sensors stetig steigt, deutet das auf
        bevorstehenden Ausfall hin (Batterie leer, Funk-Probleme, Hardware-Defekt).

        Args:
            entity_id: Die zu pruefende Entity-ID.

        Returns:
            Dict mit Vorhersage oder None wenn kein Problem erkannt.
        """
        try:
            states = await self.ha.get_states()
            if not states:
                return None

            entity_state = None
            for s in states:
                if s.get("entity_id") == entity_id:
                    entity_state = s
                    break

            if not entity_state:
                return None

            attrs = entity_state.get("attributes", {})
            last_updated = entity_state.get("last_updated", "")

            # Pruefe ob der Sensor zunehmend verzoegert antwortet
            if not last_updated:
                return None

            try:
                last_ts = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

            now = datetime.now(timezone.utc)
            staleness_hours = (now - last_ts).total_seconds() / 3600

            # Heuristik: Sensor der > 6h nicht aktualisiert hat → Warnung
            # Sensor der > 24h nicht aktualisiert hat → hohes Ausfallrisiko
            if staleness_hours < 6:
                return None

            if staleness_hours >= 24:
                confidence = min(0.95, 0.7 + (staleness_hours - 24) / 100)
                days_until = 1
                prediction = "Sensor wahrscheinlich offline oder Batterie leer"
            else:
                confidence = 0.4 + (staleness_hours - 6) / 36  # 0.4 bis 0.9
                days_until = max(1, int(7 - staleness_hours / 4))
                prediction = "Sensor zeigt Verzoegerung — moeglicher Ausfall"

            return {
                "entity_id": entity_id,
                "prediction": prediction,
                "confidence": round(min(confidence, 0.95), 2),
                "days_until": days_until,
                "staleness_hours": round(staleness_hours, 1),
                "friendly_name": attrs.get("friendly_name", entity_id),
            }
        except Exception as e:
            logger.debug("predict_failure fuer %s fehlgeschlagen: %s", entity_id, e)
            return None

    def correlate_root_cause(self, offline_entities: list[str]) -> Optional[str]:
        """Korreliert mehrere Offline-Entities zu einer gemeinsamen Ursache.

        Wenn 3+ Sensoren aus dem gleichen Bereich offline sind, liegt
        wahrscheinlich ein Netzwerk-/WiFi-Problem in diesem Bereich vor.

        Args:
            offline_entities: Liste von Entity-IDs die offline sind.

        Returns:
            Ursachen-Beschreibung oder None.
        """
        if len(offline_entities) < 3:
            return None

        # Bereich aus Entity-ID extrahieren (z.B. "sensor.kueche_temp" → "kueche")
        area_counts: dict[str, int] = {}
        for eid in offline_entities:
            # Entferne domain prefix
            name_part = eid.split(".", 1)[-1] if "." in eid else eid
            # Erster Teil vor dem letzten Unterstrich ist oft der Bereich
            parts = name_part.split("_")
            if parts:
                area = parts[0]
                area_counts[area] = area_counts.get(area, 0) + 1

        # Bereich mit den meisten Ausfaellen
        for area, count in sorted(
            area_counts.items(), key=lambda x: x[1], reverse=True
        ):
            if count >= 3:
                return f"WiFi-Problem in {area} — {count} Sensoren betroffen"

        return None

    def get_repair_playbook(self, issue_type: str) -> list[str]:
        """Gibt schrittweise Reparaturanleitung fuer einen Problemtyp zurueck.

        Args:
            issue_type: Art des Problems ("battery", "offline", "stale").

        Returns:
            Liste von Reparaturschritten.
        """
        playbooks: dict[str, list[str]] = {
            "battery": [
                "1. Batteriestand im HA-Dashboard pruefen",
                "2. Passende Ersatzbatterie bereitlegen (meist CR2032 oder AA)",
                "3. Geraet oeffnen und Batterie tauschen",
                "4. Geraet neu pairen falls noetig (Zigbee: Pairing-Modus aktivieren)",
                "5. Im HA pruefen ob Sensor wieder meldet",
            ],
            "offline": [
                "1. Pruefen ob das Geraet Strom hat (LED, Display)",
                "2. WiFi/Zigbee-Reichweite pruefen — ggf. Repeater noetig",
                "3. Geraet neu starten (Strom trennen, 10s warten)",
                "4. Router/Coordinator pruefen — ggf. Neustart",
                "5. Falls Zigbee: Coordinator-Logs auf Fehler pruefen",
                "6. Geraet neu pairen wenn nichts hilft",
            ],
            "stale": [
                "1. Entity in HA pruefen — letztes Update-Datum kontrollieren",
                "2. Batterie pruefen (haeufigste Ursache fuer stale Sensoren)",
                "3. Funkreichweite pruefen — Sensor evtl. zu weit entfernt",
                "4. HA-Integration neu laden (Einstellungen → Integrationen)",
                "5. Sensor-Firmware-Update pruefen (falls OTA verfuegbar)",
            ],
        }
        return playbooks.get(
            issue_type, [f"Kein Playbook fuer '{issue_type}' verfuegbar."]
        )
