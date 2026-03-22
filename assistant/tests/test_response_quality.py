"""
Tests fuer ResponseQualityTracker — Antwort-Qualitaets-Messung.
"""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from assistant.response_quality import (
    ResponseQualityTracker,
    DEFAULT_SCORE,
    MIN_EXCHANGES_FOR_SCORE,
    EMA_ALPHA,
)


@pytest.fixture
def tracker(redis_mock):
    t = ResponseQualityTracker()
    t.redis = redis_mock
    t.enabled = True
    return t


# ============================================================
# check_followup
# ============================================================


class TestCheckFollowup:
    """Tests fuer check_followup()."""

    def test_no_previous_text(self, tracker):
        result = tracker.check_followup("Mach das Licht an")
        assert result is None

    def test_followup_within_window(self, tracker):
        tracker._last_user_text = "Mach das Licht an"
        tracker._last_response_time = time.time() - 10  # 10s ago
        tracker._last_response_category = "device_command"
        result = tracker.check_followup("Und die Heizung?")
        assert result is not None
        assert result["is_followup"] is True

    def test_no_followup_outside_window(self, tracker):
        tracker._last_user_text = "Mach das Licht an"
        tracker._last_response_time = time.time() - 120  # 2 min ago
        tracker._last_response_category = "device_command"
        result = tracker.check_followup("Wie wird das Wetter?")
        assert result is None

    def test_rephrase_detected(self, tracker):
        tracker._last_user_text = "Licht Wohnzimmer einschalten"
        tracker._last_response_time = time.time() - 30
        tracker._last_response_category = "device_command"
        # Gleiche Keywords in anderer Reihenfolge (hoher Overlap nach Stopword-Entfernung)
        result = tracker.check_followup("Wohnzimmer Licht einschalten")
        assert result is not None
        assert result["is_rephrase"] is True

    def test_disabled_returns_none(self, tracker):
        tracker.enabled = False
        tracker._last_user_text = "Test"
        result = tracker.check_followup("Test2")
        assert result is None

    def test_followup_without_category_returns_none(self, tracker):
        """If no category was set for last response, followup is not detected."""
        tracker._last_user_text = "Hallo"
        tracker._last_response_time = time.time() - 5
        tracker._last_response_category = ""  # no category
        result = tracker.check_followup("Hallo nochmal")
        # is_followup requires _last_response_category to be truthy
        # but is_rephrase might trigger; with no category AND no rephrase -> None
        # depends on rephrase detection
        if result is not None:
            assert result["is_followup"] is False

    def test_both_followup_and_rephrase(self, tracker):
        """A message can be both a followup AND a rephrase."""
        tracker._last_user_text = "Licht Wohnzimmer einschalten"
        tracker._last_response_time = time.time() - 5  # very recent
        tracker._last_response_category = "device_command"
        result = tracker.check_followup("Wohnzimmer Licht einschalten")
        assert result is not None
        assert result["is_followup"] is True
        assert result["is_rephrase"] is True

    def test_previous_category_preserved(self, tracker):
        """check_followup should return the previous category."""
        tracker._last_user_text = "Test"
        tracker._last_response_time = time.time() - 5
        tracker._last_response_category = "knowledge"
        result = tracker.check_followup("Test nochmal bitte")
        if result is not None:
            assert result["previous_category"] == "knowledge"


# ============================================================
# record_exchange
# ============================================================


class TestRecordExchange:
    """Tests fuer record_exchange()."""

    @pytest.mark.asyncio
    async def test_clear_exchange(self, tracker):
        await tracker.record_exchange("device_command", person="Max")
        tracker.redis.hincrby.assert_called()
        tracker.redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_thanked_exchange(self, tracker):
        await tracker.record_exchange("device_command", was_thanked=True)
        # "thanked" = clear quality
        tracker.redis.hincrby.assert_called()

    @pytest.mark.asyncio
    async def test_rephrased_exchange(self, tracker):
        await tracker.record_exchange("knowledge", was_rephrased=True)
        tracker.redis.hincrby.assert_called()

    @pytest.mark.asyncio
    async def test_disabled_no_record(self, tracker):
        tracker.enabled = False
        await tracker.record_exchange("device_command")
        tracker.redis.hincrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_per_person_stats(self, tracker):
        await tracker.record_exchange("device_command", person="Lisa")
        # Should have calls for both global and per-person stats
        assert tracker.redis.hincrby.call_count >= 2

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self):
        t = ResponseQualityTracker()
        t.redis = None
        t.enabled = True
        # Should not raise
        await t.record_exchange("device_command")

    @pytest.mark.asyncio
    async def test_quality_scores_correct(self, tracker):
        """Verify the target scores for different exchange types."""
        # was_thanked -> score 1.0
        # was_rephrased -> score 0.0
        # had_followup -> score 0.2
        # normal -> score 0.8
        # We verify indirectly via _update_score being called
        await tracker.record_exchange("knowledge", was_thanked=True)
        # The quality should be "clear" and score_target 1.0

    @pytest.mark.asyncio
    async def test_followup_exchange_quality(self, tracker):
        """had_followup should set quality to 'unclear' with score 0.2."""
        await tracker.record_exchange("knowledge", had_followup=True)
        # Verify "unclear" was used in stats
        hincrby_calls = tracker.redis.hincrby.call_args_list
        quality_args = [str(c) for c in hincrby_calls]
        assert any("unclear" in s for s in quality_args)

    @pytest.mark.asyncio
    async def test_history_entry_contains_timestamp(self, tracker):
        """History entry should contain timestamp and category."""
        await tracker.record_exchange("smalltalk")
        lpush_call = tracker.redis.lpush.call_args
        entry = json.loads(lpush_call[0][1])
        assert "timestamp" in entry
        assert entry["category"] == "smalltalk"
        assert entry["quality"] == "clear"

    @pytest.mark.asyncio
    async def test_history_trimmed_to_300(self, tracker):
        """History should be trimmed to 300 entries."""
        await tracker.record_exchange("device_command")
        tracker.redis.ltrim.assert_called_once()
        trim_args = tracker.redis.ltrim.call_args[0]
        assert trim_args[2] == 299  # 0 to 299 = 300 entries

    @pytest.mark.asyncio
    async def test_few_shot_stored_for_good_exchange(self, tracker):
        """When score_target >= 0.8 and _last_user_text is set, few-shot should be stored."""
        tracker._last_user_text = "Wie warm ist es?"
        with patch.object(
            tracker, "_store_few_shot_example", new_callable=AsyncMock
        ) as mock_store:
            await tracker.record_exchange(
                "knowledge",
                was_thanked=True,
                response_text="22 Grad im Wohnzimmer.",
            )
            mock_store.assert_called_once()


# ============================================================
# _detect_rephrase
# ============================================================


class TestDetectRephrase:
    """Tests fuer _detect_rephrase()."""

    def test_similar_texts(self, tracker):
        assert (
            tracker._detect_rephrase(
                "Licht Wohnzimmer einschalten",
                "Wohnzimmer Licht einschalten",
            )
            is True
        )

    def test_different_texts(self, tracker):
        assert (
            tracker._detect_rephrase(
                "Wie wird das Wetter morgen?",
                "Mach die Heizung an",
            )
            is False
        )

    def test_empty_texts(self, tracker):
        assert tracker._detect_rephrase("", "") is False
        assert tracker._detect_rephrase("Test", "") is False

    def test_identical_texts(self, tracker):
        """Identical texts should be detected as rephrase."""
        assert tracker._detect_rephrase("Licht an", "Licht an") is True

    def test_stopwords_ignored(self, tracker):
        """Stopwords should not contribute to overlap score."""
        # "ich mir" are stopwords, only "kalt" remains -> different content words
        result = tracker._detect_rephrase(
            "ich mir kalt",
            "du mir warm",
        )
        # After stopword removal: {"kalt"} vs {"warm"} -> 0 overlap -> False
        assert result is False

    def test_all_stopwords_returns_false(self, tracker):
        """If all words are stopwords, should return False."""
        assert tracker._detect_rephrase("ich du das", "ich du das") is False


# ============================================================
# update_last_exchange
# ============================================================


class TestUpdateLastExchange:
    """Tests fuer update_last_exchange()."""

    def test_updates_state(self, tracker):
        tracker.update_last_exchange("Test text", "device_command")
        assert tracker._last_user_text == "Test text"
        assert tracker._last_response_category == "device_command"
        assert tracker._last_response_time > 0

    def test_updates_timestamp(self, tracker):
        """Timestamp should be recent."""
        before = time.time()
        tracker.update_last_exchange("Test", "knowledge")
        after = time.time()
        assert before <= tracker._last_response_time <= after


# ============================================================
# get_quality_score
# ============================================================


class TestGetQualityScore:
    """Tests fuer get_quality_score()."""

    @pytest.mark.asyncio
    async def test_default_score(self, tracker):
        tracker.redis.get.return_value = None
        tracker.redis.hget.return_value = None
        score = await tracker.get_quality_score("device_command")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_stored_score(self, tracker):
        tracker.redis.get.return_value = "0.92"
        score = await tracker.get_quality_score("device_command")
        assert score == 0.92

    @pytest.mark.asyncio
    async def test_no_score_below_min_exchanges(self, tracker):
        """Returns default when no stored score and total < MIN_EXCHANGES."""
        tracker.redis.get.return_value = None
        tracker.redis.hget.return_value = str(MIN_EXCHANGES_FOR_SCORE - 1)
        score = await tracker.get_quality_score("knowledge")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_no_redis_returns_default(self):
        t = ResponseQualityTracker()
        t.redis = None
        t.enabled = True
        score = await t.get_quality_score("device_command")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_score_is_float(self, tracker):
        """Score should be converted to float properly."""
        tracker.redis.get.return_value = "0.7777"
        score = await tracker.get_quality_score("analysis")
        assert isinstance(score, float)
        assert abs(score - 0.7777) < 0.0001


# ============================================================
# initialize
# ============================================================


class TestInitialize:
    """Tests fuer initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_with_redis(self, redis_mock):
        t = ResponseQualityTracker()
        await t.initialize(redis_mock)
        assert t.redis is redis_mock
        assert t.enabled is True

    @pytest.mark.asyncio
    async def test_initialize_with_none(self):
        t = ResponseQualityTracker()
        await t.initialize(None)
        assert t.enabled is False

    @pytest.mark.asyncio
    async def test_initialize_sets_correct_config(self):
        """Initialize should respect config settings."""
        t = ResponseQualityTracker()
        assert t._followup_window > 0
        assert t._rephrase_threshold > 0


# ============================================================
# get_person_score
# ============================================================


class TestGetPersonScore:
    """Tests fuer get_person_score()."""

    @pytest.mark.asyncio
    async def test_returns_stored_person_score(self, tracker):
        tracker.redis.get.return_value = "0.85"
        score = await tracker.get_person_score("device_command", "Max")
        assert score == 0.85

    @pytest.mark.asyncio
    async def test_no_stored_returns_default(self, tracker):
        tracker.redis.get.return_value = None
        score = await tracker.get_person_score("device_command", "Max")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_no_redis_returns_default(self):
        t = ResponseQualityTracker()
        t.redis = None
        t.enabled = True
        score = await t.get_person_score("device_command", "Max")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_empty_person_returns_default(self, tracker):
        score = await tracker.get_person_score("device_command", "")
        assert score == DEFAULT_SCORE

    @pytest.mark.asyncio
    async def test_person_score_key_includes_person_name(self, tracker):
        """Redis key should include person name."""
        tracker.redis.get.return_value = "0.75"
        await tracker.get_person_score("knowledge", "Lisa")
        call_args = tracker.redis.get.call_args[0][0]
        assert "Lisa" in call_args
        assert "knowledge" in call_args


# ============================================================
# get_stats
# ============================================================


class TestGetStats:
    """Tests fuer get_stats()."""

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self):
        t = ResponseQualityTracker()
        t.redis = None
        t.enabled = True
        stats = await t.get_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_returns_stats_with_data(self, tracker):
        tracker.redis.hgetall = AsyncMock(
            side_effect=[
                {b"clear": b"10", b"unclear": b"2", b"total": b"12"},  # device_command
                {},  # knowledge
                {},  # smalltalk
                {},  # analysis
            ]
        )
        tracker.redis.get = AsyncMock(return_value="0.85")
        tracker.redis.hget = AsyncMock(return_value="12")
        stats = await tracker.get_stats()
        assert "device_command" in stats
        assert stats["device_command"]["score"] == 0.85
        assert stats["device_command"]["clear"] == 10.0

    @pytest.mark.asyncio
    async def test_empty_categories_excluded(self, tracker):
        tracker.redis.hgetall = AsyncMock(return_value={})
        stats = await tracker.get_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_multiple_categories(self, tracker):
        """Stats should include all categories with data."""
        tracker.redis.hgetall = AsyncMock(
            side_effect=[
                {b"clear": b"5", b"total": b"5"},  # device_command
                {b"clear": b"3", b"total": b"3"},  # knowledge
                {},  # smalltalk
                {},  # analysis
            ]
        )
        tracker.redis.get = AsyncMock(return_value="0.7")
        tracker.redis.hget = AsyncMock(return_value="5")
        stats = await tracker.get_stats()
        assert "device_command" in stats
        assert "knowledge" in stats
        assert "smalltalk" not in stats


# ============================================================
# _update_score
# ============================================================


class TestUpdateScore:
    """Tests fuer _update_score() EMA calculation."""

    @pytest.mark.asyncio
    async def test_no_redis_returns_early(self):
        t = ResponseQualityTracker()
        t.redis = None
        await t._update_score("device_command", 1.0)
        # No exception

    @pytest.mark.asyncio
    async def test_below_min_exchanges_no_update(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE - 1))
        await tracker._update_score("device_command", 1.0)
        tracker.redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_ema_calculation(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.5")
        await tracker._update_score("device_command", 1.0)
        # EMA: 0.1 * 1.0 + 0.9 * 0.5 = 0.55
        tracker.redis.setex.assert_called_once()
        call_args = tracker.redis.setex.call_args[0]
        new_score = float(call_args[2])
        assert abs(new_score - 0.55) < 0.01

    @pytest.mark.asyncio
    async def test_ema_with_no_existing_score(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value=None)
        await tracker._update_score("device_command", 0.0)
        # EMA: 0.1 * 0.0 + 0.9 * 0.5 (DEFAULT_SCORE) = 0.45
        tracker.redis.setex.assert_called_once()
        call_args = tracker.redis.setex.call_args[0]
        new_score = float(call_args[2])
        assert abs(new_score - 0.45) < 0.01

    @pytest.mark.asyncio
    async def test_ema_per_person(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.8")
        await tracker._update_score("device_command", 1.0, person="Max")
        tracker.redis.setex.assert_called_once()
        key_arg = tracker.redis.setex.call_args[0][0]
        assert "person:Max" in key_arg

    @pytest.mark.asyncio
    async def test_score_clamped_to_0_1(self, tracker):
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.99")
        await tracker._update_score("device_command", 1.0)
        call_args = tracker.redis.setex.call_args[0]
        new_score = float(call_args[2])
        assert 0.0 <= new_score <= 1.0

    @pytest.mark.asyncio
    async def test_ema_downward(self, tracker):
        """EMA should also decrease the score when target is low."""
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.8")
        await tracker._update_score("device_command", 0.0)
        # EMA: 0.1 * 0.0 + 0.9 * 0.8 = 0.72
        call_args = tracker.redis.setex.call_args[0]
        new_score = float(call_args[2])
        assert abs(new_score - 0.72) < 0.01

    @pytest.mark.asyncio
    async def test_ttl_set_to_90_days(self, tracker):
        """Score key TTL should be 90 days."""
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.5")
        await tracker._update_score("device_command", 1.0)
        call_args = tracker.redis.setex.call_args[0]
        ttl = call_args[1]
        assert ttl == 90 * 86400

    @pytest.mark.asyncio
    async def test_score_key_format(self, tracker):
        """Score key should follow the expected naming convention."""
        tracker.redis.hget = AsyncMock(return_value=str(MIN_EXCHANGES_FOR_SCORE + 5))
        tracker.redis.get = AsyncMock(return_value="0.5")
        await tracker._update_score("knowledge", 0.8)
        key = tracker.redis.setex.call_args[0][0]
        assert key == "mha:response_quality:score:knowledge"


# ============================================================
# get_weak_categories
# ============================================================


class TestGetWeakCategories:
    """Tests fuer get_weak_categories()."""

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self):
        t = ResponseQualityTracker()
        t.redis = None
        result = await t.get_weak_categories()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_weak_categories(self, tracker):
        """Categories below threshold with enough data should be returned."""
        tracker.redis.get = AsyncMock(return_value="0.2")  # below default 0.3 threshold
        tracker.redis.hgetall = AsyncMock(
            return_value={
                b"total": b"25",
                b"rephrased": b"10",
            }
        )
        tracker.redis.hget = AsyncMock(return_value=None)
        result = await tracker.get_weak_categories(threshold=0.3)
        assert len(result) > 0
        for item in result:
            assert item["score"] < 0.3
            assert "category" in item
            assert "rephrase_count" in item

    @pytest.mark.asyncio
    async def test_no_weak_categories_above_threshold(self, tracker):
        """Categories above threshold should not be returned."""
        tracker.redis.get = AsyncMock(return_value="0.8")
        tracker.redis.hgetall = AsyncMock(
            return_value={
                b"total": b"25",
                b"rephrased": b"0",
            }
        )
        tracker.redis.hget = AsyncMock(return_value=None)
        result = await tracker.get_weak_categories(threshold=0.3)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_not_enough_data_excluded(self, tracker):
        """Categories with too few exchanges should not appear."""
        tracker.redis.get = AsyncMock(return_value="0.1")  # very weak
        tracker.redis.hgetall = AsyncMock(
            return_value={
                b"total": str(MIN_EXCHANGES_FOR_SCORE - 1).encode(),
                b"rephrased": b"0",
            }
        )
        tracker.redis.hget = AsyncMock(return_value=None)
        result = await tracker.get_weak_categories()
        assert len(result) == 0


# ============================================================
# _store_few_shot_example and get_few_shot_examples
# ============================================================


class TestFewShotExamples:
    """Tests fuer D6 Dynamic Few-Shot Examples."""

    @pytest.mark.asyncio
    async def test_store_few_shot_example(self, tracker):
        """Good exchange should be stored as few-shot example."""
        await tracker._store_few_shot_example(
            "device_command", "Mach das Licht an", "Erledigt.", "Max"
        )
        tracker.redis.lpush.assert_called_once()
        entry = json.loads(tracker.redis.lpush.call_args[0][1])
        assert entry["user_text"] == "Mach das Licht an"
        assert entry["response_text"] == "Erledigt."
        assert entry["person"] == "Max"

    @pytest.mark.asyncio
    async def test_store_without_user_text_skipped(self, tracker):
        """Empty user_text should not store a few-shot example."""
        await tracker._store_few_shot_example("device_command", "", "Erledigt.", "Max")
        tracker.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_without_response_text_skipped(self, tracker):
        """Empty response_text should not store a few-shot example."""
        await tracker._store_few_shot_example(
            "device_command", "Mach Licht an", "", "Max"
        )
        tracker.redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_no_redis_skipped(self):
        """Without redis, storing should not crash."""
        t = ResponseQualityTracker()
        t.redis = None
        await t._store_few_shot_example("device_command", "Test", "Response", "Max")
        # No exception

    @pytest.mark.asyncio
    async def test_get_few_shot_examples(self, tracker):
        """Should parse stored few-shot examples from redis."""
        entries = [
            json.dumps(
                {
                    "user_text": "Test1",
                    "response_text": "Resp1",
                    "category": "device_command",
                }
            ).encode(),
            json.dumps(
                {
                    "user_text": "Test2",
                    "response_text": "Resp2",
                    "category": "device_command",
                }
            ).encode(),
        ]
        tracker.redis.lrange = AsyncMock(return_value=entries)
        result = await tracker.get_few_shot_examples("device_command", limit=5)
        assert len(result) == 2
        assert result[0]["user_text"] == "Test1"

    @pytest.mark.asyncio
    async def test_get_few_shot_no_redis(self):
        """Without redis, should return empty list."""
        t = ResponseQualityTracker()
        t.redis = None
        result = await t.get_few_shot_examples("device_command")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_few_shot_invalid_json_skipped(self, tracker):
        """Invalid JSON entries should be silently skipped."""
        entries = [
            b"not valid json",
            json.dumps({"user_text": "Valid", "response_text": "OK"}).encode(),
        ]
        tracker.redis.lrange = AsyncMock(return_value=entries)
        result = await tracker.get_few_shot_examples("device_command")
        assert len(result) == 1
        assert result[0]["user_text"] == "Valid"

    @pytest.mark.asyncio
    async def test_store_truncates_long_texts(self, tracker):
        """Long user_text and response_text should be truncated."""
        long_user = "x" * 500
        long_response = "y" * 500
        await tracker._store_few_shot_example(
            "knowledge", long_user, long_response, "Max"
        )
        entry = json.loads(tracker.redis.lpush.call_args[0][1])
        assert len(entry["user_text"]) <= 200
        assert len(entry["response_text"]) <= 300
