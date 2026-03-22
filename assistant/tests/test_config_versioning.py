"""Tests for assistant.config_versioning module."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock
from pathlib import Path

from assistant.config_versioning import ConfigVersioning


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    pipe = MagicMock()
    pipe.lpush = MagicMock(return_value=pipe)
    pipe.ltrim = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    r.pipeline = MagicMock(return_value=pipe)
    r.lrange = AsyncMock(return_value=[])
    r.llen = AsyncMock(return_value=0)
    r.rpop = AsyncMock(return_value=None)
    return r


@pytest.fixture
def cv():
    with patch(
        "assistant.config_versioning.yaml_config",
        {
            "self_optimization": {
                "rollback": {
                    "enabled": True,
                    "max_snapshots": 5,
                    "snapshot_on_every_edit": True,
                    "max_disk_mb": 50,
                }
            }
        },
    ):
        return ConfigVersioning()


# ------------------------------------------------------------------
# Basic / is_enabled
# ------------------------------------------------------------------


def test_is_enabled_true(cv, mock_redis):
    cv._redis = mock_redis
    assert cv.is_enabled() is True


def test_is_enabled_no_redis(cv):
    assert cv.is_enabled() is False


def test_is_enabled_disabled(cv, mock_redis):
    cv._enabled = False
    cv._redis = mock_redis
    assert cv.is_enabled() is False


@pytest.mark.asyncio
async def test_initialize(cv, mock_redis):
    with patch("assistant.config_versioning._SNAPSHOT_DIR") as mock_dir:
        mock_dir.mkdir = MagicMock()
        await cv.initialize(mock_redis)
    assert cv._redis is mock_redis


# ------------------------------------------------------------------
# create_snapshot
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_snapshot_success(cv, mock_redis, tmp_path):
    cv._redis = mock_redis
    mock_redis.llen.return_value = 0

    config_file = tmp_path / "test.yaml"
    config_file.write_text("key: value")

    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path / "snapshots"):
        (tmp_path / "snapshots").mkdir()
        snap_id = await cv.create_snapshot("test", config_file, reason="manual")

    assert snap_id is not None
    assert snap_id.startswith("test_")
    mock_redis.pipeline.assert_called_once()


@pytest.mark.asyncio
async def test_create_snapshot_disabled(cv, mock_redis):
    cv._enabled = False
    cv._redis = mock_redis
    result = await cv.create_snapshot("test", Path("/nonexistent"))
    assert result is None


@pytest.mark.asyncio
async def test_create_snapshot_file_missing(cv, mock_redis):
    cv._redis = mock_redis
    result = await cv.create_snapshot("test", Path("/nonexistent/file.yaml"))
    assert result is None


# ------------------------------------------------------------------
# list_snapshots
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots(cv, mock_redis):
    cv._redis = mock_redis
    snap = {
        "id": "test_20250101_120000",
        "config_file": "test",
        "timestamp": "2025-01-01T12:00:00",
    }
    mock_redis.lrange.return_value = [json.dumps(snap)]
    result = await cv.list_snapshots("test")
    assert len(result) == 1
    assert result[0]["id"] == "test_20250101_120000"


@pytest.mark.asyncio
async def test_list_snapshots_no_redis(cv):
    cv._redis = None
    result = await cv.list_snapshots("test")
    assert result == []


@pytest.mark.asyncio
async def test_list_snapshots_invalid_json(cv, mock_redis):
    cv._redis = mock_redis
    mock_redis.lrange.return_value = ["not-json", json.dumps({"id": "ok"})]
    result = await cv.list_snapshots("test")
    assert len(result) == 1


# ------------------------------------------------------------------
# list_all_snapshots
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_snapshots(cv, mock_redis):
    cv._redis = mock_redis
    snap1 = json.dumps({"id": "s1", "timestamp": "2025-01-02"})
    snap2 = json.dumps({"id": "s2", "timestamp": "2025-01-01"})
    mock_redis.lrange.side_effect = [[snap1], [snap2], [], []]
    result = await cv.list_all_snapshots()
    assert len(result) == 2
    assert result[0]["id"] == "s1"  # sorted by timestamp desc


# ------------------------------------------------------------------
# rollback
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_no_redis(cv):
    cv._redis = None
    result = await cv.rollback("test_20250101_120000")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_rollback_snapshot_not_found(cv, mock_redis):
    cv._redis = mock_redis
    mock_redis.lrange.return_value = []
    result = await cv.rollback("test_20250101_120000")
    assert result["success"] is False
    assert "nicht gefunden" in result["message"]


@pytest.mark.asyncio
async def test_rollback_success(cv, mock_redis, tmp_path):
    cv._redis = mock_redis
    mock_redis.llen.return_value = 0

    original = tmp_path / "test.yaml"
    original.write_text("old: value")
    snapshot_file = tmp_path / "test_20250101_120000.yaml"
    snapshot_file.write_text("key: restored")

    snap = json.dumps(
        {
            "id": "test_20250101_120000",
            "config_file": "test",
            "original_path": str(original),
            "snapshot_path": str(snapshot_file),
            "timestamp": "2025-01-01T12:00:00",
        }
    )
    mock_redis.lrange.return_value = [snap]

    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path):
        result = await cv.rollback("test_20250101_120000")

    assert result["success"] is True
    assert original.read_text() == "key: restored"


@pytest.mark.asyncio
async def test_rollback_snapshot_file_missing(cv, mock_redis):
    cv._redis = mock_redis
    snap = json.dumps(
        {
            "id": "test_20250101_120000",
            "config_file": "test",
            "original_path": "/tmp/orig.yaml",
            "snapshot_path": "/tmp/nonexistent_snap.yaml",
            "timestamp": "2025-01-01T12:00:00",
        }
    )
    mock_redis.lrange.return_value = [snap]
    result = await cv.rollback("test_20250101_120000")
    assert result["success"] is False
    assert "fehlt" in result["message"]


# ------------------------------------------------------------------
# reload_config
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_config_success(cv, mock_redis, tmp_path):
    cv._redis = mock_redis
    mock_redis.llen.return_value = 0
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("key: value")

    with (
        patch("assistant.config_versioning._CONFIG_DIR", tmp_path),
        patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path / "snapshots"),
        patch(
            "assistant.config_versioning.load_yaml_config",
            return_value={"new_key": "new_val"},
        ),
        patch("assistant.config_versioning.yaml_config", {"old_key": "old_val"}),
    ):
        (tmp_path / "snapshots").mkdir(exist_ok=True)
        result = await cv.reload_config()

    assert result["success"] is True
    assert "changed_keys" in result


@pytest.mark.asyncio
async def test_reload_config_no_file(cv, mock_redis, tmp_path):
    cv._redis = mock_redis
    with patch("assistant.config_versioning._CONFIG_DIR", tmp_path):
        result = await cv.reload_config()
    assert result["success"] is False


# ------------------------------------------------------------------
# health_status
# ------------------------------------------------------------------


def test_health_status(cv, tmp_path):
    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path):
        (tmp_path / "snap1.yaml").write_text("x")
        (tmp_path / "snap2.yaml").write_text("y")
        status = cv.health_status()
    assert status["enabled"] is True
    assert status["current_snapshots"] == 2
    assert status["max_snapshots"] == 5


def test_health_status_no_dir(cv):
    with patch(
        "assistant.config_versioning._SNAPSHOT_DIR", Path("/nonexistent_path_xyz")
    ):
        status = cv.health_status()
    assert status["current_snapshots"] == 0


# ------------------------------------------------------------------
# _cleanup_old_snapshots
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_old_snapshots_removes_excess(cv, mock_redis, tmp_path):
    cv._redis = mock_redis
    mock_redis.llen.return_value = 7  # > max_snapshots=5

    old_snap = json.dumps({"snapshot_path": str(tmp_path / "old.yaml")})
    mock_redis.rpop.side_effect = [old_snap, old_snap, None]
    (tmp_path / "old.yaml").write_text("x")

    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path):
        await cv._cleanup_old_snapshots("test")
    # rpop should be called to_remove=2 times
    assert mock_redis.rpop.call_count == 2


# ------------------------------------------------------------------
# NEW: create_snapshot exception handling — Lines 100-102
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_snapshot_exception(cv, mock_redis, tmp_path):
    """Exception during snapshot returns None (lines 100-102)."""
    cv._redis = mock_redis
    config_file = tmp_path / "test.yaml"
    config_file.write_text("key: value")

    # Make pipeline.execute raise to trigger the except block
    pipe = mock_redis.pipeline()
    pipe.execute = AsyncMock(side_effect=Exception("Redis down"))

    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path / "snapshots"):
        (tmp_path / "snapshots").mkdir()
        result = await cv.create_snapshot("test", config_file, reason="test")
    assert result is None


# ------------------------------------------------------------------
# NEW: rollback exception — Lines 174-176
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_exception(cv, mock_redis, tmp_path):
    """Exception during rollback returns failure (lines 174-176)."""
    cv._redis = mock_redis
    mock_redis.llen.return_value = 0

    original = tmp_path / "test.yaml"
    original.write_text("old: value")
    snapshot_file = tmp_path / "test_20250101_120000.yaml"
    snapshot_file.write_text("key: restored")

    snap = json.dumps(
        {
            "id": "test_20250101_120000",
            "config_file": "test",
            "original_path": str(original),
            "snapshot_path": str(snapshot_file),
            "timestamp": "2025-01-01T12:00:00",
        }
    )
    mock_redis.lrange.return_value = [snap]

    # Make shutil.copy2 fail to trigger except block
    with (
        patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path),
        patch(
            "assistant.config_versioning.shutil.copy2",
            side_effect=Exception("disk full"),
        ),
    ):
        result = await cv.rollback("test_20250101_120000")
    assert result["success"] is False
    assert "Rollback-Fehler" in result["message"]


# ------------------------------------------------------------------
# NEW: _cleanup decode/key errors — Lines 209-210
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_decode_error(cv, mock_redis, tmp_path):
    """Handles JSONDecodeError during cleanup (lines 209-210)."""
    cv._redis = mock_redis
    mock_redis.llen.return_value = 7  # > max_snapshots=5

    # Return invalid JSON for rpop
    mock_redis.rpop.side_effect = ["not-valid-json", None]

    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path):
        await cv._cleanup_old_snapshots("test")
    # Should not raise, rpop called for to_remove=2 items


@pytest.mark.asyncio
async def test_cleanup_key_error(cv, mock_redis, tmp_path):
    """Handles KeyError during cleanup (lines 209-210)."""
    cv._redis = mock_redis
    mock_redis.llen.return_value = 6  # > max_snapshots=5

    # JSON without "snapshot_path" key
    mock_redis.rpop.side_effect = [json.dumps({"other_key": "value"})]

    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path):
        await cv._cleanup_old_snapshots("test")
    # Should not raise


# ------------------------------------------------------------------
# NEW: _enforce_disk_quota file deletion — Lines 224-232
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_disk_quota_deletes_oldest(cv, tmp_path):
    """Deletes oldest snapshots when disk quota exceeded (lines 224-232)."""
    cv._redis = AsyncMock()
    cv._redis.llen = AsyncMock(return_value=2)
    cv._cfg = {"max_disk_mb": 0}  # 0 MB quota = always over

    # Create files with different timestamps
    import time

    f1 = tmp_path / "old.yaml"
    f1.write_text("a" * 100)
    time.sleep(0.05)
    f2 = tmp_path / "new.yaml"
    f2.write_text("b" * 100)

    with patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path):
        await cv._enforce_disk_quota()
    # At least one file should have been deleted
    remaining = list(tmp_path.glob("*.yaml"))
    assert len(remaining) < 2


# ------------------------------------------------------------------
# NEW: _enforce_disk_quota exception — Lines 236-237
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_disk_quota_exception(cv):
    """Handles exception in disk quota check (lines 236-237)."""
    cv._redis = AsyncMock()
    cv._cfg = {"max_disk_mb": 50}

    with patch("assistant.config_versioning._SNAPSHOT_DIR") as mock_dir:
        mock_dir.iterdir.side_effect = OSError("permission denied")
        # Should not raise
        await cv._enforce_disk_quota()


# ------------------------------------------------------------------
# NEW: reload_config update exception/rollback — Lines 271-275
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_config_update_exception_rollback(cv, mock_redis, tmp_path):
    """Config rollback on update exception (lines 271-275)."""
    cv._redis = mock_redis
    mock_redis.llen.return_value = 0
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("key: value")

    original_config = {"old_key": "old_val"}

    class FailingDict(dict):
        """Dict that fails on the second update() call."""

        _call_count = 0

        def update(self, other):
            self._call_count += 1
            if self._call_count >= 1:
                raise RuntimeError("update failed")
            super().update(other)

    failing_config = FailingDict(original_config)

    with (
        patch("assistant.config_versioning._CONFIG_DIR", tmp_path),
        patch("assistant.config_versioning._SNAPSHOT_DIR", tmp_path / "snapshots"),
        patch(
            "assistant.config_versioning.load_yaml_config",
            return_value={"new_key": "new_val"},
        ),
        patch("assistant.config_versioning.yaml_config", failing_config),
    ):
        (tmp_path / "snapshots").mkdir(exist_ok=True)
        result = await cv.reload_config()

    assert result["success"] is False


# ------------------------------------------------------------------
# NEW: reload_config general exception — Lines 280-282
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_config_general_exception(cv, mock_redis, tmp_path):
    """General exception during reload returns failure (lines 280-282)."""
    cv._redis = mock_redis

    with (
        patch("assistant.config_versioning._CONFIG_DIR", tmp_path),
        patch(
            "assistant.config_versioning.load_yaml_config",
            side_effect=Exception("YAML broken"),
        ),
    ):
        config_file = tmp_path / "settings.yaml"
        config_file.write_text("key: value")
        result = await cv.reload_config()

    assert result["success"] is False
    assert "YAML broken" in result["message"]
