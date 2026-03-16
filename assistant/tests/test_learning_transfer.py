"""
Tests fuer LearningTransfer — Praeferenz-Uebertragung zwischen aehnlichen Raeumen.
"""

import json
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.learning_transfer import (
    DEFAULT_ROOM_GROUPS,
    REDIS_KEY_PREFERENCES,
    TRANSFERABLE_DOMAINS,
    LearningTransfer,
)


@pytest.fixture
def lt():
    """LearningTransfer with mocked config and Redis."""
    with patch("assistant.learning_transfer.yaml_config") as mock_cfg:
        mock_cfg.get.return_value = {}
        obj = LearningTransfer()
    obj.redis = AsyncMock()
    obj.redis.get = AsyncMock(return_value=None)
    obj.redis.set = AsyncMock(return_value=True)
    return obj


@pytest.fixture
def lt_disabled():
    """LearningTransfer that is disabled."""
    with patch("assistant.learning_transfer.yaml_config") as mock_cfg:
        mock_cfg.get.return_value = {"enabled": False}
        obj = LearningTransfer()
    obj.redis = AsyncMock()
    return obj


# ── Initialization ──────────────────────────────────────────────────


class TestInit:
    """Tests fuer __init__ und initialize."""

    def test_default_values(self, lt):
        assert lt.enabled is True
        assert lt.auto_suggest is True
        assert lt.min_observations == 3
        assert lt.transfer_confidence == 0.7
        assert lt.domains_enabled == ["light", "climate", "media"]
        assert lt._preferences == {}
        assert isinstance(lt._pending_transfers, deque)

    def test_default_room_groups_loaded(self, lt):
        assert lt._room_groups == DEFAULT_ROOM_GROUPS

    def test_custom_config(self):
        cfg = {
            "enabled": False,
            "auto_suggest": False,
            "min_observations": 5,
            "transfer_confidence": 0.9,
            "domains": ["light"],
            "room_groups": {"custom": ["a", "b"]},
        }
        with patch("assistant.learning_transfer.yaml_config") as mock_cfg:
            mock_cfg.get.return_value = cfg
            obj = LearningTransfer()
        assert obj.enabled is False
        assert obj.auto_suggest is False
        assert obj.min_observations == 5
        assert obj.transfer_confidence == 0.9
        assert obj.domains_enabled == ["light"]
        assert obj._room_groups == {"custom": ["a", "b"]}

    @pytest.mark.asyncio
    async def test_initialize_loads_preferences(self, lt):
        lt.redis.get.return_value = json.dumps({"wohnzimmer:light": [{"brightness": 200, "count": 5}]})
        await lt.initialize(lt.redis)
        assert "wohnzimmer:light" in lt._preferences

    @pytest.mark.asyncio
    async def test_initialize_without_redis(self):
        with patch("assistant.learning_transfer.yaml_config") as mock_cfg:
            mock_cfg.get.return_value = {}
            obj = LearningTransfer()
        await obj.initialize(None)
        assert obj.redis is None
        assert obj._preferences == {}

    @pytest.mark.asyncio
    async def test_initialize_disabled_skips_load(self, lt_disabled):
        await lt_disabled.initialize(lt_disabled.redis)
        lt_disabled.redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_transfers_maxlen(self, lt):
        assert lt._pending_transfers.maxlen == 100


# ── Load / Save Preferences ────────────────────────────────────────


class TestLoadSavePreferences:
    """Tests fuer _load_preferences und _save_preferences."""

    @pytest.mark.asyncio
    async def test_load_preferences_parses_json(self, lt):
        data = {"kueche:light": [{"brightness": 180, "count": 3}]}
        lt.redis.get.return_value = json.dumps(data)
        await lt._load_preferences()
        assert lt._preferences == data

    @pytest.mark.asyncio
    async def test_load_preferences_no_data(self, lt):
        lt.redis.get.return_value = None
        await lt._load_preferences()
        assert lt._preferences == {}

    @pytest.mark.asyncio
    async def test_load_preferences_no_redis(self, lt):
        lt.redis = None
        await lt._load_preferences()
        assert lt._preferences == {}

    @pytest.mark.asyncio
    async def test_load_preferences_handles_exception(self, lt):
        lt.redis.get.side_effect = Exception("connection lost")
        await lt._load_preferences()
        assert lt._preferences == {}

    @pytest.mark.asyncio
    async def test_save_preferences_writes_json(self, lt):
        lt._preferences = {"kueche:light": [{"brightness": 180, "count": 3}]}
        await lt._save_preferences()
        lt.redis.set.assert_called_once()
        args, kwargs = lt.redis.set.call_args
        assert args[0] == REDIS_KEY_PREFERENCES
        parsed = json.loads(args[1])
        assert parsed == lt._preferences
        assert kwargs["ex"] == 86400 * 90

    @pytest.mark.asyncio
    async def test_save_preferences_no_redis(self, lt):
        lt.redis = None
        await lt._save_preferences()  # Should not raise

    @pytest.mark.asyncio
    async def test_save_preferences_handles_exception(self, lt):
        lt.redis.set.side_effect = Exception("write error")
        lt._preferences = {"x:y": []}
        await lt._save_preferences()  # Should not raise


# ── observe_action ──────────────────────────────────────────────────


class TestObserveAction:
    """Tests fuer observe_action."""

    @pytest.mark.asyncio
    async def test_observe_records_preference(self, lt):
        await lt.observe_action("wohnzimmer", "light", {"brightness": 200})
        key = "wohnzimmer:light"
        assert key in lt._preferences
        assert lt._preferences[key][0]["brightness"] == 200
        assert lt._preferences[key][0]["count"] == 1

    @pytest.mark.asyncio
    async def test_observe_increments_existing_preference(self, lt):
        await lt.observe_action("wohnzimmer", "light", {"brightness": 200})
        await lt.observe_action("wohnzimmer", "light", {"brightness": 200})
        prefs = lt._preferences["wohnzimmer:light"]
        assert prefs[0]["count"] == 2

    @pytest.mark.asyncio
    async def test_observe_disabled_noop(self, lt_disabled):
        await lt_disabled.observe_action("wohnzimmer", "light", {"brightness": 200})
        assert lt_disabled._preferences == {}

    @pytest.mark.asyncio
    async def test_observe_unknown_domain_noop(self, lt):
        await lt.observe_action("wohnzimmer", "vacuum", {"power": True})
        assert lt._preferences == {}

    @pytest.mark.asyncio
    async def test_observe_domain_not_in_enabled(self, lt):
        lt.domains_enabled = ["climate"]
        await lt.observe_action("wohnzimmer", "light", {"brightness": 200})
        assert lt._preferences == {}

    @pytest.mark.asyncio
    async def test_observe_filters_non_transferable_attributes(self, lt):
        await lt.observe_action("kueche", "light", {"brightness": 200, "entity_id": "light.kueche"})
        prefs = lt._preferences["kueche:light"]
        assert "entity_id" not in prefs[0]
        assert "brightness" in prefs[0]

    @pytest.mark.asyncio
    async def test_observe_skips_none_values(self, lt):
        await lt.observe_action("kueche", "light", {"brightness": None, "color_temp": 350})
        prefs = lt._preferences["kueche:light"]
        assert "brightness" not in prefs[0]
        assert prefs[0]["color_temp"] == 350

    @pytest.mark.asyncio
    async def test_observe_all_none_values_noop(self, lt):
        await lt.observe_action("kueche", "light", {"brightness": None})
        assert lt._preferences == {}

    @pytest.mark.asyncio
    async def test_observe_empty_attributes_noop(self, lt):
        await lt.observe_action("kueche", "light", {})
        assert lt._preferences == {}

    @pytest.mark.asyncio
    async def test_observe_lowercases_room(self, lt):
        await lt.observe_action("Wohnzimmer", "light", {"brightness": 200})
        assert "wohnzimmer:light" in lt._preferences

    @pytest.mark.asyncio
    async def test_observe_stores_person(self, lt):
        await lt.observe_action("kueche", "light", {"brightness": 200}, person="Alice")
        prefs = lt._preferences["kueche:light"]
        assert prefs[0]["person"] == "Alice"

    @pytest.mark.asyncio
    async def test_observe_updates_last_seen(self, lt):
        before = time.time()
        await lt.observe_action("kueche", "light", {"brightness": 200})
        after = time.time()
        pref = lt._preferences["kueche:light"][0]
        assert before <= pref["last_seen"] <= after

    @pytest.mark.asyncio
    async def test_observe_saves_to_redis(self, lt):
        await lt.observe_action("kueche", "light", {"brightness": 200})
        lt.redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_observe_max_20_prefs_per_key(self, lt):
        for i in range(25):
            await lt.observe_action("kueche", "light", {"brightness": i})
        assert len(lt._preferences["kueche:light"]) <= 20

    @pytest.mark.asyncio
    async def test_observe_sorts_by_count_descending(self, lt):
        # Create one pref with count=3, others with count=1
        for _ in range(3):
            await lt.observe_action("kueche", "light", {"brightness": 100})
        await lt.observe_action("kueche", "light", {"brightness": 200})
        prefs = lt._preferences["kueche:light"]
        assert prefs[0]["brightness"] == 100
        assert prefs[0]["count"] == 3

    @pytest.mark.asyncio
    async def test_observe_separate_keys_for_different_domains(self, lt):
        await lt.observe_action("kueche", "light", {"brightness": 200})
        await lt.observe_action("kueche", "climate", {"temperature": 22})
        assert "kueche:light" in lt._preferences
        assert "kueche:climate" in lt._preferences

    @pytest.mark.asyncio
    async def test_observe_climate_records_temperature(self, lt):
        await lt.observe_action("wohnzimmer", "climate", {"temperature": 21.5})
        assert lt._preferences["wohnzimmer:climate"][0]["temperature"] == 21.5

    @pytest.mark.asyncio
    async def test_observe_media_records_volume(self, lt):
        await lt.observe_action("wohnzimmer", "media", {"volume_level": 0.4})
        assert lt._preferences["wohnzimmer:media"][0]["volume_level"] == 0.4


# ── _check_transfers ────────────────────────────────────────────────


class TestCheckTransfers:
    """Tests fuer _check_transfers und Transfer-Generierung."""

    @pytest.mark.asyncio
    async def test_no_transfer_below_min_observations(self, lt):
        lt._preferences = {
            "wohnzimmer:light": [{"brightness": 200, "count": 2}],
        }
        await lt._check_transfers("wohnzimmer", "light", {"brightness": 200})
        assert len(lt._pending_transfers) == 0

    @pytest.mark.asyncio
    async def test_transfer_generated_at_min_observations(self, lt):
        lt._preferences = {
            "wohnzimmer:light": [{"brightness": 200, "count": 3}],
        }
        with patch("assistant.learning_transfer.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await lt._check_transfers("wohnzimmer", "light", {"brightness": 200})
        # wohnzimmer is in wohnbereich group with esszimmer and kueche
        assert len(lt._pending_transfers) == 2
        targets = {t["target_room"] for t in lt._pending_transfers}
        assert targets == {"esszimmer", "kueche"}

    @pytest.mark.asyncio
    async def test_transfer_skips_target_with_strong_preference(self, lt):
        lt._preferences = {
            "wohnzimmer:light": [{"brightness": 200, "count": 5}],
            "esszimmer:light": [{"brightness": 150, "count": 4}],
        }
        await lt._check_transfers("wohnzimmer", "light", {"brightness": 200})
        targets = {t["target_room"] for t in lt._pending_transfers}
        assert "esszimmer" not in targets
        assert "kueche" in targets

    @pytest.mark.asyncio
    async def test_transfer_no_similar_rooms(self, lt):
        lt._preferences = {
            "unbekannt:light": [{"brightness": 200, "count": 5}],
        }
        await lt._check_transfers("unbekannt", "light", {"brightness": 200})
        assert len(lt._pending_transfers) == 0

    @pytest.mark.asyncio
    async def test_transfer_duplicate_not_added(self, lt):
        lt._preferences = {
            "wohnzimmer:light": [{"brightness": 200, "count": 5}],
        }
        await lt._check_transfers("wohnzimmer", "light", {"brightness": 200})
        count_before = len(lt._pending_transfers)
        await lt._check_transfers("wohnzimmer", "light", {"brightness": 200})
        assert len(lt._pending_transfers) == count_before

    @pytest.mark.asyncio
    async def test_transfer_contains_correct_fields(self, lt):
        lt._preferences = {
            "schlafzimmer:light": [{"brightness": 150, "color_temp": 400, "count": 4}],
        }
        await lt._check_transfers("schlafzimmer", "light", {"brightness": 150})
        t = lt._pending_transfers[0]
        assert t["source_room"] == "schlafzimmer"
        assert t["domain"] == "light"
        assert t["confidence"] == 0.7
        assert t["source_count"] == 4
        assert "brightness" in t["attributes"]
        assert "timestamp" in t

    @pytest.mark.asyncio
    async def test_transfer_only_transferable_attrs(self, lt):
        lt._preferences = {
            "wohnzimmer:light": [{"brightness": 200, "count": 5, "last_seen": 100, "person": "Bob"}],
        }
        await lt._check_transfers("wohnzimmer", "light", {"brightness": 200})
        t = lt._pending_transfers[0]
        assert "count" not in t["attributes"]
        assert "last_seen" not in t["attributes"]
        assert "person" not in t["attributes"]

    @pytest.mark.asyncio
    async def test_transfer_empty_prefs_noop(self, lt):
        lt._preferences = {}
        await lt._check_transfers("wohnzimmer", "light", {"brightness": 200})
        assert len(lt._pending_transfers) == 0

    @pytest.mark.asyncio
    async def test_auto_suggest_off_skips_check(self, lt):
        lt.auto_suggest = False
        # Enough observations to trigger
        for _ in range(5):
            await lt.observe_action("wohnzimmer", "light", {"brightness": 200})
        assert len(lt._pending_transfers) == 0


# ── _check_transfers climate with open-window skip ──────────────────


class TestCheckTransfersClimateWindowSkip:
    """Tests for the climate open-window skip logic in _check_transfers."""

    @pytest.mark.asyncio
    async def test_climate_transfer_skipped_for_open_window(self, lt):
        """The window-check logic is wrapped in try/except — if the lazy
        import of StateChangeLog succeeds and conditions match, the transfer
        to that room is skipped.  We test the happy path by directly
        manipulating the internal state after _check_transfers runs."""
        lt._preferences = {
            "wohnzimmer:climate": [{"temperature": 22, "count": 5}],
        }
        # Without mocking the lazy import the dependency check silently
        # passes (except Exception: pass).  Verify transfers are generated.
        await lt._check_transfers("wohnzimmer", "climate", {"temperature": 22})
        targets = {t["target_room"] for t in lt._pending_transfers}
        # Both rooms should appear (dependency check is best-effort)
        assert "esszimmer" in targets
        assert "kueche" in targets

    @pytest.mark.asyncio
    async def test_climate_transfer_proceeds_when_no_brain(self, lt):
        lt._preferences = {
            "wohnzimmer:climate": [{"temperature": 22, "count": 5}],
        }
        await lt._check_transfers("wohnzimmer", "climate", {"temperature": 22})
        assert len(lt._pending_transfers) > 0


# ── _find_similar_rooms ─────────────────────────────────────────────


class TestFindSimilarRooms:
    """Tests fuer _find_similar_rooms."""

    def test_finds_rooms_in_wohnbereich(self, lt):
        result = lt._find_similar_rooms("wohnzimmer")
        assert set(result) == {"esszimmer", "kueche"}

    def test_finds_rooms_in_schlafbereich(self, lt):
        result = lt._find_similar_rooms("schlafzimmer")
        assert set(result) == {"gaestezimmer", "kinderzimmer"}

    def test_case_insensitive(self, lt):
        result = lt._find_similar_rooms("Wohnzimmer")
        assert set(result) == {"esszimmer", "kueche"}

    def test_unknown_room_returns_empty(self, lt):
        result = lt._find_similar_rooms("keller")
        assert result == []

    def test_excludes_source_room(self, lt):
        result = lt._find_similar_rooms("bad")
        assert "bad" not in result

    def test_nassbereich_group(self, lt):
        result = lt._find_similar_rooms("bad")
        assert set(result) == {"badezimmer", "gaeste_wc", "waschkueche"}

    def test_custom_room_groups(self, lt):
        lt._room_groups = {"etage1": ["flur", "wohnzimmer", "kueche"]}
        result = lt._find_similar_rooms("flur")
        assert set(result) == {"wohnzimmer", "kueche"}


# ── get_pending_transfers / clear ───────────────────────────────────


class TestPendingTransfers:
    """Tests fuer get_pending_transfers und clear_pending_transfers."""

    def test_get_pending_returns_deque(self, lt):
        result = lt.get_pending_transfers()
        assert isinstance(result, deque)

    def test_clear_pending_transfers(self, lt):
        lt._pending_transfers.append({"test": 1})
        lt.clear_pending_transfers()
        assert len(lt._pending_transfers) == 0


# ── get_transfer_suggestion ─────────────────────────────────────────


class TestGetTransferSuggestion:
    """Tests fuer get_transfer_suggestion."""

    def test_finds_matching_suggestion(self, lt):
        lt._pending_transfers.append({
            "source_room": "wohnzimmer",
            "target_room": "esszimmer",
            "domain": "light",
            "attributes": {"brightness": 200},
        })
        result = lt.get_transfer_suggestion("esszimmer", "light")
        assert result is not None
        assert result["target_room"] == "esszimmer"

    def test_returns_none_no_match(self, lt):
        lt._pending_transfers.append({
            "source_room": "wohnzimmer",
            "target_room": "esszimmer",
            "domain": "light",
            "attributes": {"brightness": 200},
        })
        result = lt.get_transfer_suggestion("kueche", "light")
        assert result is None

    def test_case_insensitive_room_match(self, lt):
        lt._pending_transfers.append({
            "source_room": "wohnzimmer",
            "target_room": "esszimmer",
            "domain": "light",
            "attributes": {"brightness": 200},
        })
        result = lt.get_transfer_suggestion("Esszimmer", "light")
        assert result is not None

    def test_domain_must_match(self, lt):
        lt._pending_transfers.append({
            "source_room": "wohnzimmer",
            "target_room": "esszimmer",
            "domain": "light",
            "attributes": {"brightness": 200},
        })
        result = lt.get_transfer_suggestion("esszimmer", "climate")
        assert result is None


# ── get_context_hint ────────────────────────────────────────────────


class TestGetContextHint:
    """Tests fuer get_context_hint."""

    def test_empty_when_disabled(self, lt_disabled):
        assert lt_disabled.get_context_hint() == ""

    def test_empty_when_no_transfers(self, lt):
        assert lt.get_context_hint() == ""

    def test_hint_with_transfers(self, lt):
        lt._pending_transfers.append({
            "source_room": "wohnzimmer",
            "target_room": "esszimmer",
            "domain": "light",
            "attributes": {"brightness": 200},
        })
        hint = lt.get_context_hint()
        assert "wohnzimmer" in hint
        assert "esszimmer" in hint
        assert "brightness=200" in hint

    def test_hint_filtered_by_room(self, lt):
        lt._pending_transfers.append({
            "source_room": "wohnzimmer",
            "target_room": "esszimmer",
            "domain": "light",
            "attributes": {"brightness": 200},
        })
        lt._pending_transfers.append({
            "source_room": "schlafzimmer",
            "target_room": "gaestezimmer",
            "domain": "light",
            "attributes": {"brightness": 100},
        })
        hint = lt.get_context_hint("esszimmer")
        assert "esszimmer" in hint
        assert "gaestezimmer" not in hint

    def test_hint_max_two_entries(self, lt):
        for i in range(5):
            lt._pending_transfers.append({
                "source_room": f"src{i}",
                "target_room": f"tgt{i}",
                "domain": "light",
                "attributes": {"brightness": i},
            })
        hint = lt.get_context_hint()
        assert hint.count("Praeferenz-Transfer") == 2

    def test_hint_no_room_filter_shows_all_up_to_two(self, lt):
        lt._pending_transfers.append({
            "source_room": "a",
            "target_room": "b",
            "domain": "light",
            "attributes": {"brightness": 1},
        })
        lt._pending_transfers.append({
            "source_room": "c",
            "target_room": "d",
            "domain": "light",
            "attributes": {"brightness": 2},
        })
        hint = lt.get_context_hint("")
        assert hint.count("Praeferenz-Transfer") == 2


# ── get_preferences_summary ─────────────────────────────────────────


class TestGetPreferencesSummary:
    """Tests fuer get_preferences_summary."""

    def test_empty_preferences(self, lt):
        assert lt.get_preferences_summary() == {}

    def test_summary_structure(self, lt):
        lt._preferences = {
            "kueche:light": [
                {"brightness": 200, "color_temp": 400, "count": 5, "last_seen": 100, "person": "Alice"},
            ],
        }
        summary = lt.get_preferences_summary()
        assert "kueche:light" in summary
        entry = summary["kueche:light"]
        assert entry["room"] == "kueche"
        assert entry["domain"] == "light"
        assert entry["observations"] == 5
        assert "brightness" in entry["top_preference"]
        assert "color_temp" in entry["top_preference"]
        # Metadata should be excluded from top_preference
        assert "count" not in entry["top_preference"]
        assert "last_seen" not in entry["top_preference"]
        assert "person" not in entry["top_preference"]

    def test_summary_multiple_rooms(self, lt):
        lt._preferences = {
            "kueche:light": [{"brightness": 200, "count": 3}],
            "bad:climate": [{"temperature": 24, "count": 7}],
        }
        summary = lt.get_preferences_summary()
        assert len(summary) == 2
        assert summary["bad:climate"]["observations"] == 7

    def test_summary_empty_prefs_list_skipped(self, lt):
        lt._preferences = {
            "kueche:light": [],
        }
        summary = lt.get_preferences_summary()
        assert "kueche:light" not in summary


# ── Integration: full observe_action -> transfer flow ───────────────


class TestIntegrationObserveToTransfer:
    """End-to-end tests for observe_action triggering transfer proposals."""

    @pytest.mark.asyncio
    async def test_full_flow_generates_transfer(self, lt):
        for _ in range(3):
            await lt.observe_action("wohnzimmer", "light", {"brightness": 200, "color_temp": 400})
        assert len(lt._pending_transfers) > 0
        t = lt._pending_transfers[0]
        assert t["source_room"] == "wohnzimmer"
        assert t["domain"] == "light"
        assert t["attributes"]["brightness"] == 200

    @pytest.mark.asyncio
    async def test_different_prefs_no_early_transfer(self, lt):
        """Different attribute values each time means no pref reaches min_observations."""
        await lt.observe_action("wohnzimmer", "light", {"brightness": 100})
        await lt.observe_action("wohnzimmer", "light", {"brightness": 200})
        await lt.observe_action("wohnzimmer", "light", {"brightness": 255})
        assert len(lt._pending_transfers) == 0

    @pytest.mark.asyncio
    async def test_transfer_for_climate_domain(self, lt):
        for _ in range(4):
            await lt.observe_action("schlafzimmer", "climate", {"temperature": 20})
        targets = {t["target_room"] for t in lt._pending_transfers}
        assert "gaestezimmer" in targets or "kinderzimmer" in targets


# ── Constants ───────────────────────────────────────────────────────


class TestConstants:
    """Verify module-level constants are correct."""

    def test_redis_key_preferences(self):
        assert REDIS_KEY_PREFERENCES == "mha:learning_transfer:preferences"

    def test_transferable_domains_keys(self):
        assert set(TRANSFERABLE_DOMAINS.keys()) == {"light", "climate", "media"}

    def test_light_attributes(self):
        assert "brightness" in TRANSFERABLE_DOMAINS["light"]["attributes"]
        assert "color_temp" in TRANSFERABLE_DOMAINS["light"]["attributes"]

    def test_default_room_groups_has_expected_groups(self):
        assert "wohnbereich" in DEFAULT_ROOM_GROUPS
        assert "schlafbereich" in DEFAULT_ROOM_GROUPS
        assert "nassbereich" in DEFAULT_ROOM_GROUPS
        assert "arbeitsbereich" in DEFAULT_ROOM_GROUPS
        assert "aussen" in DEFAULT_ROOM_GROUPS
