"""
Config Versioning - Snapshot & Rollback fuer Jarvis-Konfigurationsdateien.

Phase 13.4: Sichert Config-Dateien vor jeder Aenderung.
- Snapshot vor jedem edit_config() (Phase 13.1)
- Snapshot vor jeder Selbstoptimierung (Phase 13.4)
- Rollback auf beliebigen Snapshot
- Maximale Snapshot-Anzahl konfigurierbar
- Redis-basierte Metadaten + Datei-Backups
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .config import yaml_config, load_yaml_config

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_SNAPSHOT_DIR = _CONFIG_DIR / "snapshots"


class ConfigVersioning:
    """Verwaltet Snapshots, Rollbacks und Hot-Reload fuer Konfigurationsdateien."""

    def __init__(self):
        self._cfg = yaml_config.get("self_optimization", {}).get("rollback", {})
        self._enabled = self._cfg.get("enabled", True)
        self._max_snapshots = int(self._cfg.get("max_snapshots", 20))
        self._snapshot_on_edit = self._cfg.get("snapshot_on_every_edit", True)
        self._redis = None

    async def initialize(self, redis_client=None) -> None:
        """Initialisiert mit Redis-Client fuer Metadaten."""
        self._redis = redis_client
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "ConfigVersioning initialisiert (enabled=%s, max=%d)",
            self._enabled, self._max_snapshots,
        )

    def is_enabled(self) -> bool:
        return self._enabled and self._redis is not None

    async def create_snapshot(
        self,
        config_file: str,
        yaml_path: Path,
        reason: str = "manual",
        changed_by: str = "jarvis",
    ) -> Optional[str]:
        """Erstellt einen Snapshot einer Config-Datei vor Aenderung.

        Returns: snapshot_id oder None bei Fehler.
        """
        if not self.is_enabled():
            return None

        if not yaml_path.exists():
            return None

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_id = f"{config_file}_{timestamp}"
            snapshot_path = _SNAPSHOT_DIR / f"{snapshot_id}.yaml"

            shutil.copy2(yaml_path, snapshot_path)

            metadata = {
                "id": snapshot_id,
                "config_file": config_file,
                "original_path": str(yaml_path),
                "snapshot_path": str(snapshot_path),
                "reason": reason,
                "changed_by": changed_by,
                "timestamp": datetime.now().isoformat(),
            }

            key = f"mha:config_snapshots:{config_file}"
            await self._redis.lpush(key, json.dumps(metadata))
            # 90 Tage TTL als Sicherheitsnetz (Cleanup passiert auch aktiv)
            await self._redis.expire(key, 90 * 86400)

            await self._cleanup_old_snapshots(config_file)

            logger.info("Snapshot erstellt: %s (Grund: %s)", snapshot_id, reason)
            return snapshot_id

        except Exception as e:
            logger.error("Snapshot fehlgeschlagen: %s", e)
            return None

    async def list_snapshots(self, config_file: str) -> list[dict]:
        """Listet alle Snapshots einer Config-Datei (neueste zuerst)."""
        if not self._redis:
            return []

        raw = await self._redis.lrange(f"mha:config_snapshots:{config_file}", 0, -1)
        snapshots = []
        for item in raw:
            try:
                snapshots.append(json.loads(item))
            except json.JSONDecodeError:
                continue
        return snapshots

    async def list_all_snapshots(self) -> list[dict]:
        """Listet alle Snapshots aller Config-Dateien."""
        all_snapshots = []
        for config_name in ["easter_eggs", "opinion_rules", "room_profiles", "settings"]:
            snapshots = await self.list_snapshots(config_name)
            all_snapshots.extend(snapshots)
        all_snapshots.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        return all_snapshots

    async def rollback(self, snapshot_id: str) -> dict:
        """Stellt eine Config-Datei aus einem Snapshot wieder her.

        Returns: {"success": bool, "message": str}
        """
        if not self._redis:
            return {"success": False, "message": "Redis nicht verfuegbar"}

        config_file = snapshot_id.rsplit("_", 2)[0]
        snapshots = await self.list_snapshots(config_file)

        target = None
        for snap in snapshots:
            if snap["id"] == snapshot_id:
                target = snap
                break

        if not target:
            return {"success": False, "message": f"Snapshot '{snapshot_id}' nicht gefunden"}

        snapshot_path = Path(target["snapshot_path"])
        original_path = Path(target["original_path"])

        if not snapshot_path.exists():
            return {"success": False, "message": f"Snapshot-Datei fehlt: {snapshot_path}"}

        try:
            await self.create_snapshot(
                config_file, original_path,
                reason=f"pre_rollback_to_{snapshot_id}",
                changed_by="user",
            )

            shutil.copy2(snapshot_path, original_path)

            logger.info("Rollback ausgefuehrt: %s -> %s", snapshot_id, original_path)
            return {
                "success": True,
                "message": f"Config '{config_file}' auf Stand {target['timestamp']} zurueckgesetzt",
                "restored_from": target["timestamp"],
            }

        except Exception as e:
            logger.error("Rollback fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Rollback-Fehler: {e}"}

    async def _cleanup_old_snapshots(self, config_file: str):
        """Entfernt aelteste Snapshots wenn max_snapshots ueberschritten."""
        key = f"mha:config_snapshots:{config_file}"
        count = await self._redis.llen(key)

        if count <= self._max_snapshots:
            return

        to_remove = count - self._max_snapshots
        for _ in range(to_remove):
            raw = await self._redis.rpop(key)
            if raw:
                try:
                    meta = json.loads(raw)
                    old_path = Path(meta["snapshot_path"])
                    if old_path.exists():
                        old_path.unlink()
                        logger.debug("Alter Snapshot geloescht: %s", old_path)
                except (json.JSONDecodeError, KeyError, OSError):
                    pass

    async def reload_config(self) -> dict:
        """Hot-Reload: Laedt settings.yaml neu ohne Neustart.

        Aktualisiert das globale yaml_config dict mit den neuen Werten.
        Nicht-kritische Settings werden sofort wirksam.

        Returns: {"success": bool, "changed_keys": list}
        """
        try:
            config_path = _CONFIG_DIR / "settings.yaml"
            if not config_path.exists():
                return {"success": False, "message": "settings.yaml nicht gefunden"}

            # Snapshot vor Reload
            await self.create_snapshot("settings", config_path, reason="pre_reload")

            # Neu laden
            new_config = load_yaml_config()

            # Aenderungen erkennen
            changed = []
            for key in set(list(yaml_config.keys()) + list(new_config.keys())):
                old_val = yaml_config.get(key)
                new_val = new_config.get(key)
                if old_val != new_val:
                    changed.append(key)

            # Globales yaml_config aktualisieren
            yaml_config.clear()
            yaml_config.update(new_config)

            logger.info("Config Hot-Reload: %d Keys geaendert: %s", len(changed), changed)
            return {"success": True, "changed_keys": changed}

        except Exception as e:
            logger.error("Config Hot-Reload fehlgeschlagen: %s", e)
            return {"success": False, "message": str(e)}

    def health_status(self) -> dict:
        """Status fuer Diagnostik."""
        snapshot_count = len(list(_SNAPSHOT_DIR.glob("*.yaml"))) if _SNAPSHOT_DIR.exists() else 0
        return {
            "enabled": self._enabled,
            "max_snapshots": self._max_snapshots,
            "current_snapshots": snapshot_count,
            "snapshot_on_edit": self._snapshot_on_edit,
        }
