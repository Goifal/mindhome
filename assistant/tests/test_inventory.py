"""
Tests fuer InventoryManager — Vorrats-Tracking mit Redis und Ablaufdaten.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.inventory import InventoryManager


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ha_mock():
    """AsyncMock Home Assistant Client."""
    mock = AsyncMock()
    mock.call_service = AsyncMock(return_value={"success": True})
    return mock


@pytest.fixture
def redis_mock():
    """AsyncMock Redis Client."""
    mock = AsyncMock()
    mock.hset = AsyncMock()
    mock.hgetall = AsyncMock(return_value={})
    mock.sadd = AsyncMock()
    mock.srem = AsyncMock()
    mock.smembers = AsyncMock(return_value=set())
    mock.delete = AsyncMock()
    return mock


@pytest.fixture
def manager(ha_mock, redis_mock):
    """InventoryManager mit gemockten Clients."""
    mgr = InventoryManager(ha_mock)
    mgr.redis = redis_mock
    return mgr


@pytest.fixture
def manager_no_redis(ha_mock):
    """InventoryManager ohne Redis (redis=None)."""
    mgr = InventoryManager(ha_mock)
    mgr.redis = None
    return mgr


# =====================================================================
# _days_until (static method)
# =====================================================================


class TestDaysUntil:
    """Tests fuer die statische Methode _days_until."""

    def test_future_date(self):
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        result = InventoryManager._days_until(future)
        assert result == 5

    def test_past_date(self):
        past = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        result = InventoryManager._days_until(past)
        assert result == -3

    def test_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        assert InventoryManager._days_until(today) == 0

    def test_invalid_format(self):
        assert InventoryManager._days_until("not-a-date") is None

    def test_empty_string(self):
        assert InventoryManager._days_until("") is None

    @pytest.mark.parametrize("bad_input", [None, 123, []])
    def test_non_string_input(self, bad_input):
        assert InventoryManager._days_until(bad_input) is None


# =====================================================================
# add_item
# =====================================================================


class TestAddItem:
    """Tests fuer add_item."""

    @pytest.mark.asyncio
    async def test_add_item_success(self, manager, redis_mock):
        result = await manager.add_item("Milch", quantity=2, expiry_date="2026-04-01", category="kuehlschrank")
        assert result["success"] is True
        assert "Milch" in result["message"]
        redis_mock.hset.assert_called_once()
        assert redis_mock.sadd.call_count == 2  # all + category set

    @pytest.mark.asyncio
    async def test_add_item_no_redis(self, manager_no_redis):
        result = await manager_no_redis.add_item("Milch")
        assert result["success"] is False
        assert "Redis" in result["message"]

    @pytest.mark.asyncio
    async def test_add_item_defaults(self, manager, redis_mock):
        result = await manager.add_item("Brot")
        assert result["success"] is True
        call_kwargs = redis_mock.hset.call_args
        mapping = call_kwargs[1]["mapping"] if "mapping" in call_kwargs[1] else call_kwargs[0][1]
        assert mapping["quantity"] == "1"
        assert mapping["category"] == "sonstiges"

    @pytest.mark.asyncio
    async def test_add_item_redis_error(self, manager, redis_mock):
        redis_mock.hset.side_effect = Exception("connection lost")
        result = await manager.add_item("Milch")
        assert result["success"] is False


# =====================================================================
# remove_item
# =====================================================================


class TestRemoveItem:
    """Tests fuer remove_item."""

    @pytest.mark.asyncio
    async def test_remove_item_found(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_milch_abc12345"}
        redis_mock.hgetall.return_value = {
            "id": "inv_milch_abc12345",
            "name": "Milch",
            "category": "kuehlschrank",
        }
        result = await manager.remove_item("Milch")
        assert result["success"] is True
        redis_mock.delete.assert_called_once()
        assert redis_mock.srem.call_count == 2

    @pytest.mark.asyncio
    async def test_remove_item_not_found(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_brot_abc12345"}
        redis_mock.hgetall.return_value = {"name": "Brot", "category": "vorrat"}
        result = await manager.remove_item("Milch")
        assert result["success"] is False
        assert "nicht" in result["message"]

    @pytest.mark.asyncio
    async def test_remove_item_no_redis(self, manager_no_redis):
        result = await manager_no_redis.remove_item("Milch")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_remove_item_case_insensitive(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_milch_abc12345"}
        redis_mock.hgetall.return_value = {"name": "Milch", "category": "kuehlschrank"}
        result = await manager.remove_item("milch")
        assert result["success"] is True


# =====================================================================
# update_quantity
# =====================================================================


class TestUpdateQuantity:
    """Tests fuer update_quantity."""

    @pytest.mark.asyncio
    async def test_update_quantity_positive(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {"name": "Milch", "category": "kuehlschrank"}
        result = await manager.update_quantity("Milch", 5)
        assert result["success"] is True
        assert "5" in result["message"]
        redis_mock.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_quantity_zero_removes(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {"name": "Milch", "category": "kuehlschrank"}
        result = await manager.update_quantity("Milch", 0)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_quantity_negative_removes(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {"name": "Milch", "category": "kuehlschrank"}
        result = await manager.update_quantity("Milch", -1)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_quantity_not_found(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_brot_abc"}
        redis_mock.hgetall.return_value = {"name": "Brot", "category": "vorrat"}
        result = await manager.update_quantity("Milch", 3)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_update_quantity_no_redis(self, manager_no_redis):
        result = await manager_no_redis.update_quantity("Milch", 3)
        assert result["success"] is False


# =====================================================================
# list_items
# =====================================================================


class TestListItems:
    """Tests fuer list_items."""

    @pytest.mark.asyncio
    async def test_list_items_empty(self, manager, redis_mock):
        redis_mock.smembers.return_value = set()
        result = await manager.list_items()
        assert result["success"] is True
        assert "leer" in result["message"]

    @pytest.mark.asyncio
    async def test_list_items_with_data(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {
            "name": "Milch",
            "quantity": "2",
            "expiry_date": "2099-12-31",
            "category": "kuehlschrank",
        }
        result = await manager.list_items()
        assert result["success"] is True
        assert "Milch" in result["message"]
        assert "x2" in result["message"]

    @pytest.mark.asyncio
    async def test_list_items_by_category(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {
            "name": "Milch",
            "quantity": "1",
            "expiry_date": "",
            "category": "kuehlschrank",
        }
        result = await manager.list_items(category="kuehlschrank")
        assert result["success"] is True
        redis_mock.smembers.assert_called_with("mha:inventory:cat:kuehlschrank")

    @pytest.mark.asyncio
    async def test_list_items_expired_shows_warning(self, manager, redis_mock):
        past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {
            "name": "Milch",
            "quantity": "1",
            "expiry_date": past,
            "category": "sonstiges",
        }
        result = await manager.list_items()
        assert "ABGELAUFEN" in result["message"]

    @pytest.mark.asyncio
    async def test_list_items_expiring_today(self, manager, redis_mock):
        today = datetime.now().strftime("%Y-%m-%d")
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {
            "name": "Milch",
            "quantity": "1",
            "expiry_date": today,
            "category": "sonstiges",
        }
        result = await manager.list_items()
        assert "HEUTE" in result["message"]

    @pytest.mark.asyncio
    async def test_list_items_no_redis(self, manager_no_redis):
        result = await manager_no_redis.list_items()
        assert result["success"] is False


# =====================================================================
# check_expiring
# =====================================================================


class TestCheckExpiring:
    """Tests fuer check_expiring."""

    @pytest.mark.asyncio
    async def test_check_expiring_finds_items(self, manager, redis_mock):
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {
            "name": "Milch",
            "quantity": "1",
            "expiry_date": tomorrow,
            "category": "kuehlschrank",
        }
        result = await manager.check_expiring(days_ahead=3)
        assert len(result) == 1
        assert result[0]["name"] == "Milch"
        assert result[0]["days_left"] == 1

    @pytest.mark.asyncio
    async def test_check_expiring_ignores_far_future(self, manager, redis_mock):
        far = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        redis_mock.smembers.return_value = {"inv_milch_abc"}
        redis_mock.hgetall.return_value = {
            "name": "Milch",
            "quantity": "1",
            "expiry_date": far,
            "category": "kuehlschrank",
        }
        result = await manager.check_expiring(days_ahead=3)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_check_expiring_no_expiry_date(self, manager, redis_mock):
        redis_mock.smembers.return_value = {"inv_salz_abc"}
        redis_mock.hgetall.return_value = {
            "name": "Salz",
            "quantity": "1",
            "expiry_date": "",
            "category": "vorrat",
        }
        result = await manager.check_expiring()
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_check_expiring_no_redis(self, manager_no_redis):
        result = await manager_no_redis.check_expiring()
        assert result == []

    @pytest.mark.asyncio
    async def test_check_expiring_sorted_by_days_left(self, manager, redis_mock):
        d1 = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        d2 = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        redis_mock.smembers.return_value = {"inv_a_abc", "inv_b_abc"}
        redis_mock.hgetall.side_effect = [
            {"name": "A", "quantity": "1", "expiry_date": d1, "category": "x"},
            {"name": "B", "quantity": "1", "expiry_date": d2, "category": "x"},
        ]
        result = await manager.check_expiring(days_ahead=5)
        assert result[0]["name"] == "B"
        assert result[1]["name"] == "A"


# =====================================================================
# auto_add_to_shopping_list
# =====================================================================


class TestAutoAddToShoppingList:
    """Tests fuer auto_add_to_shopping_list."""

    @pytest.mark.asyncio
    async def test_auto_add_success(self, manager, ha_mock):
        ha_mock.call_service.return_value = True
        result = await manager.auto_add_to_shopping_list("Milch")
        assert result is True
        ha_mock.call_service.assert_called_once_with(
            "shopping_list", "add_item", {"name": "Milch"}
        )

    @pytest.mark.asyncio
    async def test_auto_add_ha_error(self, manager, ha_mock):
        ha_mock.call_service.side_effect = Exception("HA down")
        result = await manager.auto_add_to_shopping_list("Milch")
        assert result is False


# =====================================================================
# Edge cases / initialization
# =====================================================================


class TestInitialization:
    """Tests fuer Initialisierung und Callback."""

    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, ha_mock):
        mgr = InventoryManager(ha_mock)
        mock_redis = AsyncMock()
        await mgr.initialize(mock_redis)
        assert mgr.redis is mock_redis

    def test_set_notify_callback(self, manager):
        cb = MagicMock()
        manager.set_notify_callback(cb)
        assert manager._notify_callback is cb

    @pytest.mark.asyncio
    async def test_remove_item_handles_bytes(self, manager, redis_mock):
        """Redis kann bytes zurueckgeben statt strings."""
        redis_mock.smembers.return_value = {b"inv_milch_abc"}
        redis_mock.hgetall.return_value = {
            b"name": b"Milch",
            b"category": b"kuehlschrank",
        }
        result = await manager.remove_item("Milch")
        assert result["success"] is True
