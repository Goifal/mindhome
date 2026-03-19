"""
Tests fuer Smart Shopping - Verbrauchsprognose und Einkaufslisten-Logik.
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from assistant.smart_shopping import SmartShopping


# ============================================================
# Fixtures
# ============================================================

SHOPPING_CONFIG = {
    "smart_shopping": {
        "enabled": True,
        "min_purchases": 2,
        "reminder_days_before": 1,
        "reminder_cooldown_hours": 24,
    },
}

DISABLED_CONFIG = {
    "smart_shopping": {"enabled": False},
}


@pytest.fixture
def shop(ha_mock, redis_mock):
    """SmartShopping instance with mocked config, HA, and Redis."""
    with patch("assistant.smart_shopping.yaml_config", SHOPPING_CONFIG):
        s = SmartShopping(ha_mock)
    s.redis = redis_mock
    return s


@pytest.fixture
def shop_disabled(ha_mock, redis_mock):
    """SmartShopping instance that is disabled."""
    with patch("assistant.smart_shopping.yaml_config", DISABLED_CONFIG):
        s = SmartShopping(ha_mock)
    s.redis = redis_mock
    return s


def _make_purchase_entries(dates):
    """Create Redis-style purchase entries from a list of datetime objects."""
    return [
        json.dumps({"date": d.isoformat(), "quantity": 1}).encode()
        for d in dates
    ]


# ============================================================
# record_purchase Tests
# ============================================================

class TestRecordPurchase:
    @pytest.mark.asyncio
    async def test_successful_purchase(self, shop, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[])
        result = await shop.record_purchase("Milch", 2)
        assert result["success"] is True
        assert "Milch" in result["message"]
        redis_mock.rpush.assert_called_once()
        redis_mock.ltrim.assert_called_once()
        redis_mock.expire.assert_called()

    @pytest.mark.asyncio
    async def test_records_weekday_pattern(self, shop, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[])
        redis_mock.hincrby = AsyncMock()
        await shop.record_purchase("Brot")
        redis_mock.hincrby.assert_called_once()

    @pytest.mark.asyncio
    async def test_disabled_returns_failure(self, shop_disabled, redis_mock):
        result = await shop_disabled.record_purchase("Milch")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_no_redis_returns_failure(self, ha_mock):
        with patch("assistant.smart_shopping.yaml_config", SHOPPING_CONFIG):
            s = SmartShopping(ha_mock)
        s.redis = None
        result = await s.record_purchase("Milch")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_item_name_normalized(self, shop, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[])
        await shop.record_purchase("Gouda Kaese")
        key_arg = redis_mock.rpush.call_args[0][0]
        assert "gouda_kaese" in key_arg


# ============================================================
# _calculate_prediction Tests
# ============================================================

class TestCalculatePrediction:
    @pytest.mark.asyncio
    async def test_not_enough_purchases_returns_none(self, shop, redis_mock):
        redis_mock.lrange = AsyncMock(return_value=[
            json.dumps({"date": "2025-01-01T10:00:00", "quantity": 1}).encode()
        ])
        result = await shop._calculate_prediction("Milch")
        assert result is None

    @pytest.mark.asyncio
    async def test_same_day_purchases_ignored(self, shop, redis_mock):
        """Purchases on the same day (bulk buy) produce no intervals."""
        now = datetime(2025, 6, 1, 10, 0)
        entries = _make_purchase_entries([now, now])
        redis_mock.lrange = AsyncMock(return_value=entries)
        result = await shop._calculate_prediction("Milch")
        assert result is None

    @pytest.mark.asyncio
    async def test_correct_avg_days(self, shop, redis_mock):
        dates = [
            datetime(2025, 1, 1),
            datetime(2025, 1, 8),   # 7 days
            datetime(2025, 1, 15),  # 7 days
        ]
        entries = _make_purchase_entries(dates)
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await shop._calculate_prediction("Milch")
        assert result is not None
        assert result["avg_days"] == 7.0
        assert result["data_points"] == 2

    @pytest.mark.asyncio
    async def test_confidence_capped_at_1(self, shop, redis_mock):
        # 12 purchases -> 11 intervals -> confidence = min(1.0, 11/10) = 1.0
        dates = [datetime(2025, 1, 1) + timedelta(days=i * 5) for i in range(12)]
        entries = _make_purchase_entries(dates)
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await shop._calculate_prediction("Milch")
        assert result is not None
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self, ha_mock):
        with patch("assistant.smart_shopping.yaml_config", SHOPPING_CONFIG):
            s = SmartShopping(ha_mock)
        s.redis = None
        result = await s._calculate_prediction("Milch")
        assert result is None

    @pytest.mark.asyncio
    async def test_next_expected_calculation(self, shop, redis_mock):
        dates = [
            datetime(2025, 3, 1),
            datetime(2025, 3, 11),  # 10 days
        ]
        entries = _make_purchase_entries(dates)
        redis_mock.lrange = AsyncMock(return_value=entries)

        result = await shop._calculate_prediction("Eier")
        assert result is not None
        expected_next = datetime(2025, 3, 21).date()
        actual_next = datetime.fromisoformat(result["next_expected"]).date()
        assert actual_next == expected_next


# ============================================================
# get_predictions Tests
# ============================================================

class TestGetPredictions:
    @pytest.mark.asyncio
    async def test_returns_sorted_predictions(self, shop, redis_mock):
        pred_a = json.dumps({"item": "Milch", "next_expected": "2025-04-01"})
        pred_b = json.dumps({"item": "Brot", "next_expected": "2025-03-15"})
        redis_mock.hgetall = AsyncMock(return_value={
            b"milch": pred_a.encode(),
            b"brot": pred_b.encode(),
        })

        result = await shop.get_predictions()
        assert len(result) == 2
        assert result[0]["item"] == "Brot"  # earlier date first
        assert result[1]["item"] == "Milch"

    @pytest.mark.asyncio
    async def test_empty_when_disabled(self, shop_disabled):
        result = await shop_disabled.get_predictions()
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_when_no_redis(self, ha_mock):
        with patch("assistant.smart_shopping.yaml_config", SHOPPING_CONFIG):
            s = SmartShopping(ha_mock)
        s.redis = None
        result = await s.get_predictions()
        assert result == []


# ============================================================
# get_items_running_low Tests
# ============================================================

class TestGetItemsRunningLow:
    @pytest.mark.asyncio
    async def test_item_within_threshold(self, shop, redis_mock):
        tomorrow = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        pred = json.dumps({
            "item": "Milch",
            "next_expected": tomorrow,
            "confidence": 0.5,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"milch": pred.encode()})

        result = await shop.get_items_running_low()
        assert len(result) == 1
        assert result[0]["item"] == "Milch"

    @pytest.mark.asyncio
    async def test_item_past_due_is_high_urgency(self, shop, redis_mock):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        pred = json.dumps({
            "item": "Eier",
            "next_expected": yesterday,
            "confidence": 0.8,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"eier": pred.encode()})

        result = await shop.get_items_running_low()
        assert len(result) == 1
        assert result[0]["urgency"] == "high"

    @pytest.mark.asyncio
    async def test_low_confidence_excluded(self, shop, redis_mock):
        tomorrow = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        pred = json.dumps({
            "item": "Milch",
            "next_expected": tomorrow,
            "confidence": 0.1,  # below 0.3 threshold
        })
        redis_mock.hgetall = AsyncMock(return_value={b"milch": pred.encode()})

        result = await shop.get_items_running_low()
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_far_future_item_excluded(self, shop, redis_mock):
        far_future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        pred = json.dumps({
            "item": "Salz",
            "next_expected": far_future,
            "confidence": 0.9,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"salz": pred.encode()})

        result = await shop.get_items_running_low()
        assert len(result) == 0


# ============================================================
# add_missing_ingredients Tests
# ============================================================

class TestAddMissingIngredients:
    @pytest.mark.asyncio
    async def test_adds_missing_items(self, shop, ha_mock):
        ha_mock.api_get = AsyncMock(return_value=[
            {"name": "Butter", "complete": False},
        ])

        result = await shop.add_missing_ingredients(["Butter", "Mehl", "Eier"])
        assert "Butter" in result["already_on_list"]
        assert "Mehl" in result["added"]
        assert "Eier" in result["added"]

    @pytest.mark.asyncio
    async def test_empty_ingredients(self, shop):
        result = await shop.add_missing_ingredients([])
        assert result["added"] == []
        assert result["already_on_list"] == []

    @pytest.mark.asyncio
    async def test_completed_items_not_on_list(self, shop, ha_mock):
        ha_mock.api_get = AsyncMock(return_value=[
            {"name": "Butter", "complete": True},
        ])
        result = await shop.add_missing_ingredients(["Butter"])
        assert "Butter" in result["added"]

    @pytest.mark.asyncio
    async def test_api_error_handled(self, shop, ha_mock):
        ha_mock.api_get = AsyncMock(side_effect=Exception("API down"))
        result = await shop.add_missing_ingredients(["Milch"])
        assert "Milch" in result["added"]

    @pytest.mark.asyncio
    async def test_blank_ingredients_skipped(self, shop, ha_mock):
        ha_mock.api_get = AsyncMock(return_value=[])
        result = await shop.add_missing_ingredients(["Milch", "  ", ""])
        assert result["added"] == ["Milch"]


# ============================================================
# get_shopping_day_pattern Tests
# ============================================================

class TestGetShoppingDayPattern:
    @pytest.mark.asyncio
    async def test_returns_preferred_day(self, shop, redis_mock):
        redis_mock.hgetall = AsyncMock(return_value={
            b"0": b"2",    # Monday
            b"5": b"10",   # Saturday
            b"6": b"3",    # Sunday
        })

        result = await shop.get_shopping_day_pattern()
        assert result is not None
        assert result["preferred_day"] == "Samstag"
        assert result["total_trips"] == 15

    @pytest.mark.asyncio
    async def test_no_data_returns_none(self, shop, redis_mock):
        redis_mock.hgetall = AsyncMock(return_value={})
        result = await shop.get_shopping_day_pattern()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self, ha_mock):
        with patch("assistant.smart_shopping.yaml_config", SHOPPING_CONFIG):
            s = SmartShopping(ha_mock)
        s.redis = None
        result = await s.get_shopping_day_pattern()
        assert result is None


# ============================================================
# get_shopping_context Tests
# ============================================================

class TestGetShoppingContext:
    @pytest.mark.asyncio
    async def test_includes_open_items(self, shop, ha_mock, redis_mock):
        ha_mock.api_get = AsyncMock(return_value=[
            {"name": "Milch", "complete": False},
            {"name": "Brot", "complete": False},
            {"name": "Done", "complete": True},
        ])
        redis_mock.hgetall = AsyncMock(return_value={})

        context = await shop.get_shopping_context()
        assert "Einkaufsliste (2)" in context
        assert "Milch" in context

    @pytest.mark.asyncio
    async def test_empty_context_when_nothing(self, shop, ha_mock, redis_mock):
        ha_mock.api_get = AsyncMock(return_value=[])
        redis_mock.hgetall = AsyncMock(return_value={})

        context = await shop.get_shopping_context()
        assert context == ""

    @pytest.mark.asyncio
    async def test_includes_shopping_day_pattern(self, shop, ha_mock, redis_mock):
        ha_mock.api_get = AsyncMock(return_value=[])

        # First hgetall call is for get_predictions (via get_items_running_low)
        # Second hgetall call is for get_shopping_day_pattern
        redis_mock.hgetall = AsyncMock(side_effect=[
            {},  # predictions
            {b"5": b"8"},  # shopping days (Saturday)
        ])

        context = await shop.get_shopping_context()
        assert "Samstag" in context


# ============================================================
# set_notify_callback Tests
# ============================================================

class TestSetNotifyCallback:
    def test_sets_callback(self, shop):
        cb = AsyncMock()
        shop.set_notify_callback(cb)
        assert shop._notify_callback is cb


# ============================================================
# initialize Tests
# ============================================================

class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_sets_redis(self, shop, redis_mock):
        shop.redis = None
        await shop.initialize(redis_mock)
        assert shop.redis is redis_mock

    @pytest.mark.asyncio
    async def test_initialize_with_none(self, shop):
        await shop.initialize(None)
        assert shop.redis is None


# ============================================================
# check_and_notify Tests
# ============================================================

class TestCheckAndNotify:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, shop_disabled):
        result = await shop_disabled.check_and_notify()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_callback_returns_empty(self, shop):
        shop._notify_callback = None
        result = await shop.check_and_notify()
        assert result == []

    @pytest.mark.asyncio
    async def test_notifies_running_low_items(self, shop, redis_mock):
        from datetime import datetime, timedelta, timezone
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        pred = json.dumps({
            "item": "Milch",
            "next_expected": yesterday,
            "confidence": 0.8,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"milch": pred.encode()})
        redis_mock.exists = AsyncMock(return_value=0)  # no cooldown

        cb = AsyncMock()
        shop._notify_callback = cb

        result = await shop.check_and_notify()
        assert "Milch" in result
        cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_cooldown_prevents_notification(self, shop, redis_mock):
        from datetime import datetime, timedelta, timezone
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        pred = json.dumps({
            "item": "Milch",
            "next_expected": yesterday,
            "confidence": 0.8,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"milch": pred.encode()})
        redis_mock.exists = AsyncMock(return_value=1)  # cooldown active

        cb = AsyncMock()
        shop._notify_callback = cb

        result = await shop.check_and_notify()
        assert result == []
        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_callback_exception_handled(self, shop, redis_mock):
        from datetime import datetime, timedelta, timezone
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        pred = json.dumps({
            "item": "Butter",
            "next_expected": yesterday,
            "confidence": 0.8,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"butter": pred.encode()})
        redis_mock.exists = AsyncMock(return_value=0)

        cb = AsyncMock(side_effect=RuntimeError("notify failed"))
        shop._notify_callback = cb

        result = await shop.check_and_notify()
        assert result == []  # notification failed, not added

    @pytest.mark.asyncio
    async def test_notifies_item_soon_to_expire(self, shop, redis_mock):
        from datetime import datetime, timedelta, timezone
        tomorrow = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        pred = json.dumps({
            "item": "Eier",
            "next_expected": tomorrow,
            "confidence": 0.5,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"eier": pred.encode()})
        redis_mock.exists = AsyncMock(return_value=0)

        cb = AsyncMock()
        shop._notify_callback = cb

        result = await shop.check_and_notify()
        assert "Eier" in result


# ============================================================
# _check_reminder_cooldown Tests
# ============================================================

class TestCheckReminderCooldown:
    @pytest.mark.asyncio
    async def test_no_redis_returns_false(self, ha_mock):
        with patch("assistant.smart_shopping.yaml_config", SHOPPING_CONFIG):
            s = SmartShopping(ha_mock)
        s.redis = None
        result = await s._check_reminder_cooldown("Milch")
        assert result is False

    @pytest.mark.asyncio
    async def test_cooldown_active(self, shop, redis_mock):
        redis_mock.exists = AsyncMock(return_value=1)
        result = await shop._check_reminder_cooldown("Milch")
        assert result is True

    @pytest.mark.asyncio
    async def test_no_cooldown(self, shop, redis_mock):
        redis_mock.exists = AsyncMock(return_value=0)
        result = await shop._check_reminder_cooldown("Milch")
        assert result is False


# ============================================================
# _set_reminder_cooldown Tests
# ============================================================

class TestSetReminderCooldown:
    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self, ha_mock):
        with patch("assistant.smart_shopping.yaml_config", SHOPPING_CONFIG):
            s = SmartShopping(ha_mock)
        s.redis = None
        await s._set_reminder_cooldown("Milch")
        # No exception

    @pytest.mark.asyncio
    async def test_sets_cooldown(self, shop, redis_mock):
        await shop._set_reminder_cooldown("Milch")
        redis_mock.setex.assert_called_once()
        key_arg = redis_mock.setex.call_args[0][0]
        assert "milch" in key_arg

    @pytest.mark.asyncio
    async def test_cooldown_key_normalized(self, shop, redis_mock):
        await shop._set_reminder_cooldown("Gouda Kaese")
        key_arg = redis_mock.setex.call_args[0][0]
        assert "gouda_kaese" in key_arg


# ============================================================
# record_purchase prediction path Tests
# ============================================================

class TestRecordPurchasePrediction:
    @pytest.mark.asyncio
    async def test_purchase_stores_prediction(self, shop, redis_mock):
        """When prediction is calculated, it's stored in Redis."""
        dates = [
            datetime(2025, 1, 1),
            datetime(2025, 1, 8),
        ]
        entries = _make_purchase_entries(dates)
        redis_mock.lrange = AsyncMock(return_value=entries)
        redis_mock.hincrby = AsyncMock()

        result = await shop.record_purchase("Milch")
        assert result["success"] is True
        redis_mock.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_purchase_exception(self, shop, redis_mock):
        """Redis exception during purchase recording."""
        redis_mock.rpush = AsyncMock(side_effect=RuntimeError("Redis down"))
        result = await shop.record_purchase("Milch")
        assert result["success"] is False


# ============================================================
# get_predictions exception Tests
# ============================================================

class TestGetPredictionsException:
    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, shop, redis_mock):
        redis_mock.hgetall = AsyncMock(side_effect=RuntimeError("Redis down"))
        result = await shop.get_predictions()
        assert result == []


# ============================================================
# get_items_running_low edge cases
# ============================================================

class TestGetItemsRunningLowEdgeCases:
    @pytest.mark.asyncio
    async def test_invalid_date_skipped(self, shop, redis_mock):
        pred = json.dumps({
            "item": "Bad",
            "next_expected": "not-a-date",
            "confidence": 0.8,
        })
        redis_mock.hgetall = AsyncMock(return_value={b"bad": pred.encode()})
        result = await shop.get_items_running_low()
        assert len(result) == 0


# ============================================================
# get_shopping_context edge cases
# ============================================================

class TestGetShoppingContextEdgeCases:
    @pytest.mark.asyncio
    async def test_api_exception_handled(self, shop, ha_mock, redis_mock):
        ha_mock.api_get = AsyncMock(side_effect=RuntimeError("API down"))
        redis_mock.hgetall = AsyncMock(return_value={})
        context = await shop.get_shopping_context()
        # Should not crash, just return whatever other parts provide
        assert isinstance(context, str)

    @pytest.mark.asyncio
    async def test_includes_running_low_items(self, shop, ha_mock, redis_mock):
        ha_mock.api_get = AsyncMock(return_value=[])
        from datetime import datetime, timedelta, timezone
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        pred = json.dumps({
            "item": "Milch",
            "next_expected": yesterday,
            "confidence": 0.8,
            "days_until": -1,
        })
        redis_mock.hgetall = AsyncMock(side_effect=[
            {b"milch": pred.encode()},  # predictions
            {},  # shopping day pattern
        ])
        context = await shop.get_shopping_context()
        assert "Milch" in context

    @pytest.mark.asyncio
    async def test_get_shopping_day_pattern_exception(self, shop, redis_mock):
        redis_mock.hgetall = AsyncMock(side_effect=RuntimeError("fail"))
        result = await shop.get_shopping_day_pattern()
        assert result is None


# ============================================================
# add_missing_ingredients edge cases
# ============================================================

class TestAddMissingIngredientsEdgeCases:
    @pytest.mark.asyncio
    async def test_call_service_exception(self, shop, ha_mock):
        ha_mock.api_get = AsyncMock(return_value=[])
        ha_mock.call_service = AsyncMock(side_effect=RuntimeError("HA error"))
        result = await shop.add_missing_ingredients(["Mehl"])
        assert result["added"] == []
        assert result["already_on_list"] == []

    @pytest.mark.asyncio
    async def test_no_added_no_already(self, shop, ha_mock):
        ha_mock.api_get = AsyncMock(return_value=[])
        result = await shop.add_missing_ingredients(["", "  "])
        assert "Keine Zutaten" in result["message"]
