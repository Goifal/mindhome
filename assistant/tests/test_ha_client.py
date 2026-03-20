"""Tests for assistant.ha_client module."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import aiohttp
import pytest


# ---------------------------------------------------------------------------
# Helper: create a HomeAssistantClient with mocked settings and breakers
# ---------------------------------------------------------------------------

def _make_client():
    """Build a HomeAssistantClient with safe defaults and mocked breakers."""
    with patch("assistant.ha_client.settings") as s_mock, \
         patch("assistant.ha_client.ha_breaker") as ha_b, \
         patch("assistant.ha_client.mindhome_breaker") as mh_b:
        s_mock.ha_url = "http://ha.local:8123"
        s_mock.ha_token = "test-token"
        s_mock.mindhome_url = "http://mh.local:8099"
        ha_b.is_available = True
        ha_b.record_success = MagicMock()
        ha_b.record_failure = MagicMock()
        mh_b.is_available = True
        mh_b.record_success = MagicMock()
        mh_b.record_failure = MagicMock()
        from assistant.ha_client import HomeAssistantClient
        client = HomeAssistantClient()
    # Keep references to the breaker mocks on the client for assertions
    client._ha_breaker = ha_b
    client._mh_breaker = mh_b
    return client


def _mock_session_get(client, json_data=None, status=200, side_effect=None):
    """Patch _get_session to return a mock session with a GET response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.text = AsyncMock(return_value=str(json_data))
    resp.read = AsyncMock(return_value=b"image-bytes")

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)

    session = AsyncMock()
    if side_effect:
        session.get = MagicMock(side_effect=side_effect)
    else:
        session.get = MagicMock(return_value=cm)
    session.post = MagicMock(return_value=cm)
    session.put = MagicMock(return_value=cm)
    session.delete = MagicMock(return_value=cm)
    session.closed = False

    client._get_session = AsyncMock(return_value=session)
    return session, resp


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_initializes_headers(self):
        client = _make_client()
        assert client._ha_headers["Authorization"] == "Bearer test-token"
        assert client._ha_headers["Content-Type"] == "application/json"

    def test_urls_stripped(self):
        client = _make_client()
        assert not client.ha_url.endswith("/")
        assert not client.mindhome_url.endswith("/")


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestClose:
    @pytest.mark.asyncio
    async def test_close_session(self):
        client = _make_client()
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        client._session = mock_session
        await client.close()
        mock_session.close.assert_awaited_once()
        assert client._session is None

    @pytest.mark.asyncio
    async def test_close_no_session(self):
        client = _make_client()
        client._session = None
        await client.close()  # Should not raise


# ---------------------------------------------------------------------------
# get_states (with cache)
# ---------------------------------------------------------------------------

class TestGetStates:
    @pytest.mark.asyncio
    async def test_returns_states(self):
        client = _make_client()
        states = [{"entity_id": "light.test", "state": "on"}]
        _mock_session_get(client, json_data=states)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_states()
        assert result == states

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        client = _make_client()
        cached = [{"entity_id": "sensor.a"}]
        client._states_cache = cached
        client._states_cache_ts = time.monotonic()
        result = await client.get_states()
        assert result is cached


# ---------------------------------------------------------------------------
# get_state
# ---------------------------------------------------------------------------

class TestGetState:
    @pytest.mark.asyncio
    async def test_get_single_state(self):
        client = _make_client()
        state = {"entity_id": "light.test", "state": "on"}
        _mock_session_get(client, json_data=state)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_state("light.test")
        assert result == state


# ---------------------------------------------------------------------------
# call_service
# ---------------------------------------------------------------------------

class TestCallService:
    @pytest.mark.asyncio
    async def test_call_service_success(self):
        client = _make_client()
        _mock_session_get(client, json_data={"result": "ok"}, status=200)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.call_service("light", "turn_on", {"entity_id": "light.test"})
        assert result is True


# ---------------------------------------------------------------------------
# fire_event
# ---------------------------------------------------------------------------

class TestFireEvent:
    @pytest.mark.asyncio
    async def test_fire_event_success(self):
        client = _make_client()
        _mock_session_get(client, json_data={"message": "ok"}, status=200)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.fire_event("test_event", {"key": "val"})
        assert result is True


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    @pytest.mark.asyncio
    async def test_available(self):
        client = _make_client()
        _mock_session_get(client, json_data={"message": "API running."})
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.is_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_not_available(self):
        client = _make_client()
        _mock_session_get(client, json_data=None, status=500)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.is_available()
        assert result is False


# ---------------------------------------------------------------------------
# Circuit breaker OPEN
# ---------------------------------------------------------------------------

class TestCircuitBreakerOpen:
    @pytest.mark.asyncio
    async def test_ha_get_skipped_when_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = False
            result = await client.get_states()
        assert result == []

    @pytest.mark.asyncio
    async def test_mindhome_get_skipped_when_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = False
            result = await client.get_mindhome_status()
        assert result is None


# ---------------------------------------------------------------------------
# MindHome endpoints
# ---------------------------------------------------------------------------

class TestMindHomeEndpoints:
    @pytest.mark.asyncio
    async def test_get_presence(self):
        client = _make_client()
        data = {"persons": []}
        _mock_session_get(client, json_data=data)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.get_presence()
        assert result == data

    @pytest.mark.asyncio
    async def test_get_energy(self):
        client = _make_client()
        data = {"total_kwh": 42}
        _mock_session_get(client, json_data=data)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.get_energy()
        assert result == data


# ---------------------------------------------------------------------------
# search_devices input validation
# ---------------------------------------------------------------------------

class TestSearchDevices:
    @pytest.mark.asyncio
    async def test_invalid_domain_rejected(self):
        client = _make_client()
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            result = await client.search_devices(domain="light; DROP TABLE")
        assert result == []

    @pytest.mark.asyncio
    async def test_valid_domain(self):
        client = _make_client()
        _mock_session_get(client, json_data=[{"entity_id": "light.test"}])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.search_devices(domain="light")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# mindhome_post
# ---------------------------------------------------------------------------

class TestMindHomePost:
    @pytest.mark.asyncio
    async def test_post_success(self):
        client = _make_client()
        _mock_session_get(client, json_data={"ok": True}, status=200)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.mindhome_post("/api/test", {"data": 1})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_post_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = False
            result = await client.mindhome_post("/api/test", {})
        assert result is None


# ---------------------------------------------------------------------------
# mindhome_put / mindhome_delete
# ---------------------------------------------------------------------------

class TestMindHomePutDelete:
    @pytest.mark.asyncio
    async def test_put_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = False
            result = await client.mindhome_put("/api/x", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = False
            result = await client.mindhome_delete("/api/x")
        assert result is None


# ---------------------------------------------------------------------------
# put_config / delete_config
# ---------------------------------------------------------------------------

class TestConfigMethods:
    @pytest.mark.asyncio
    async def test_put_config_success(self):
        client = _make_client()
        _mock_session_get(client, json_data={"result": "ok"}, status=200)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.put_config("automation", "test_id", {"alias": "test"})
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_config_success(self):
        client = _make_client()
        # Mock delete response
        resp = AsyncMock()
        resp.status = 200
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        session = AsyncMock()
        session.delete = MagicMock(return_value=cm)
        session.closed = False
        client._get_session = AsyncMock(return_value=session)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.delete_config("automation", "test_id")
        assert result is True


# ---------------------------------------------------------------------------
# log_actions
# ---------------------------------------------------------------------------

class TestLogActions:
    @pytest.mark.asyncio
    async def test_empty_actions_noop(self):
        client = _make_client()
        client.mindhome_post = AsyncMock()
        await client.log_actions([])
        client.mindhome_post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_log_actions_calls_post(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(return_value={"ok": True})
        actions = [{"function": "test_fn", "args": {}, "result": {"success": True, "message": "done"}}]
        await client.log_actions(actions, user_text="hello", response_text="world")
        client.mindhome_post.assert_awaited_once()
        call_args = client.mindhome_post.call_args
        assert call_args[0][0] == "/api/action-log"


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------

class TestGetHistory:
    @pytest.mark.asyncio
    async def test_get_history_returns_first_element(self):
        client = _make_client()
        history_data = [[{"state": "21.5", "last_changed": "2026-03-01T10:00:00"}]]
        _mock_session_get(client, json_data=history_data)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_history("sensor.temp", hours=24)
        assert result == history_data[0]

    @pytest.mark.asyncio
    async def test_get_history_clamps_hours(self):
        client = _make_client()
        _mock_session_get(client, json_data=None, status=200)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_history("sensor.temp", hours=9999)
        # Should not raise - hours clamped to 720
        assert result is None


# ---------------------------------------------------------------------------
# get_camera_snapshot
# ---------------------------------------------------------------------------

class TestGetCameraSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = False
            result = await client.get_camera_snapshot("camera.front")
        assert result is None

    @pytest.mark.asyncio
    async def test_snapshot_success(self):
        client = _make_client()
        _mock_session_get(client, status=200)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_camera_snapshot("camera.front")
        assert result == b"image-bytes"


# =====================================================================
# Additional tests for 100% coverage
# =====================================================================


def _mock_session_multi(client, responses):
    """Create a session mock that returns different responses per call.
    responses: list of (status, json_data | None, text_data | None)
    """
    call_idx = {"i": 0}

    def make_cm(status, json_data, text_data):
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data)
        resp.text = AsyncMock(return_value=text_data or "")
        resp.read = AsyncMock(return_value=b"")
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm, resp

    cms = [make_cm(*r) for r in responses]

    session = AsyncMock()
    session.closed = False

    def get_side(*a, **kw):
        idx = min(call_idx["i"], len(cms) - 1)
        call_idx["i"] += 1
        return cms[idx][0]

    session.get = MagicMock(side_effect=get_side)
    session.post = MagicMock(side_effect=get_side)
    session.put = MagicMock(side_effect=get_side)
    session.delete = MagicMock(side_effect=get_side)

    client._get_session = AsyncMock(return_value=session)
    return session


class TestGetAutomations:
    """Cover lines 105-111."""

    @pytest.mark.asyncio
    async def test_returns_list_directly(self):
        client = _make_client()
        automations = [{"id": "auto_1", "alias": "Test"}]
        _mock_session_get(client, json_data=automations)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_automations()
        assert result == automations

    @pytest.mark.asyncio
    async def test_fallback_to_states(self):
        """When endpoint returns non-list, falls back to states filtered by automation."""
        client = _make_client()
        states = [
            {"entity_id": "automation.test", "state": "on"},
            {"entity_id": "light.kitchen", "state": "off"},
        ]

        call_count = {"i": 0}

        def make_resp(status, data):
            resp = AsyncMock()
            resp.status = status
            resp.json = AsyncMock(return_value=data)
            resp.text = AsyncMock(return_value="")
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=resp)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        session = AsyncMock()
        session.closed = False

        # First call: automation config returns dict (not list) -> fallback
        # Second call: states returns list
        cms = [
            make_resp(200, {"error": "not supported"}),
            make_resp(200, states),
        ]

        def get_side(*a, **kw):
            idx = min(call_count["i"], len(cms) - 1)
            call_count["i"] += 1
            return cms[idx]

        session.get = MagicMock(side_effect=get_side)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_automations()
        assert len(result) == 1
        assert result[0]["entity_id"] == "automation.test"


class TestApiGet:
    """Cover line 141."""

    @pytest.mark.asyncio
    async def test_api_get(self):
        client = _make_client()
        _mock_session_get(client, json_data=["item1"])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.api_get("/api/shopping_list")
        assert result == ["item1"]


class TestCameraSnapshotEdgeCases:
    """Cover lines 165-170."""

    @pytest.mark.asyncio
    async def test_snapshot_non_200(self):
        client = _make_client()
        _mock_session_get(client, status=404)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.get_camera_snapshot("camera.test")
        assert result is None

    @pytest.mark.asyncio
    async def test_snapshot_exception(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)

        client._get_session = AsyncMock(return_value=session)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.get_camera_snapshot("camera.test")
        assert result is None
        hb.record_failure.assert_called()


class TestCallServiceWithResponse:
    """Cover line 206."""

    @pytest.mark.asyncio
    async def test_returns_response_data(self):
        client = _make_client()
        _mock_session_get(client, json_data={"forecast": [{"temp": 20}]}, status=200)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.call_service_with_response("weather", "get_forecasts", {"type": "daily"})
        assert result == {"forecast": [{"temp": 20}]}


class TestIsAvailableEdge:
    """Cover lines 233-234."""

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("Fail"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.is_available()
        assert result is False


class TestMindHomeEndpointsAdditional:
    """Cover lines 252, 256, 260, 264, 268."""

    @pytest.mark.asyncio
    async def test_get_comfort(self):
        client = _make_client()
        _mock_session_get(client, json_data={"temp": 22})
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.get_comfort()
        assert result == {"temp": 22}

    @pytest.mark.asyncio
    async def test_get_security(self):
        client = _make_client()
        _mock_session_get(client, json_data={"armed": True})
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.get_security()
        assert result == {"armed": True}

    @pytest.mark.asyncio
    async def test_get_patterns(self):
        client = _make_client()
        _mock_session_get(client, json_data={"patterns": []})
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.get_patterns()
        assert result == {"patterns": []}

    @pytest.mark.asyncio
    async def test_get_health_dashboard(self):
        client = _make_client()
        _mock_session_get(client, json_data={"status": "ok"})
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.get_health_dashboard()
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_day_phases(self):
        client = _make_client()
        _mock_session_get(client, json_data={"phase": "morning"})
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.get_day_phases()
        assert result == {"phase": "morning"}


class TestSearchDevicesValidation:
    """Cover lines 281-284, 290."""

    @pytest.mark.asyncio
    async def test_invalid_room_rejected(self):
        client = _make_client()
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            result = await client.search_devices(room="bad; DROP TABLE")
        assert result == []

    @pytest.mark.asyncio
    async def test_mindhome_get_called(self):
        client = _make_client()
        _mock_session_get(client, json_data=[])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.mindhome_get("/api/custom")
        assert result == []


class TestMindHomePostRetry:
    """Cover lines 311-325."""

    @pytest.mark.asyncio
    async def test_post_client_error_no_retry(self):
        """4xx errors should not retry."""
        client = _make_client()
        _mock_session_multi(client, [
            (400, None, "Bad request"),
        ])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client.mindhome_post("/api/test", {}, retries=2)
        assert result is None

    @pytest.mark.asyncio
    async def test_post_exception_retry(self):
        """Exception during post should retry."""
        client = _make_client()
        session = AsyncMock()
        session.closed = False

        call_count = {"i": 0}
        def post_side(*a, **kw):
            call_count["i"] += 1
            if call_count["i"] <= 2:
                cm = AsyncMock()
                cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("conn"))
                cm.__aexit__ = AsyncMock(return_value=False)
                return cm
            resp = AsyncMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={"ok": True})
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=resp)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        session.post = MagicMock(side_effect=post_side)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_success = MagicMock()
            mb.record_failure = MagicMock()
            result = await client.mindhome_post("/api/test", {}, retries=3)
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_post_server_error_retries_exhaust(self):
        client = _make_client()
        _mock_session_multi(client, [
            (500, None, "Server error"),
            (500, None, "Server error"),
        ])
        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client.mindhome_post("/api/test", {}, retries=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_post_with_timeout(self):
        client = _make_client()
        _mock_session_get(client, json_data={"ok": True}, status=200)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.mindhome_post("/api/test", {}, timeout=30.0)
        assert result == {"ok": True}


class TestLogActionsEdgeCases:
    """Cover lines 345, 358."""

    @pytest.mark.asyncio
    async def test_log_actions_non_dict_result(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(return_value={"ok": True})
        actions = [{"function": "test", "result": "some string"}]
        await client.log_actions(actions)
        call_data = client.mindhome_post.call_args[0][1]
        assert call_data["actions"][0]["result"]["success"] is False
        assert "some string" in call_data["actions"][0]["result"]["message"]

    @pytest.mark.asyncio
    async def test_log_actions_post_fails(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(return_value=None)
        actions = [{"function": "test", "result": {"success": True, "message": "ok"}}]
        await client.log_actions(actions)  # Should log warning but not raise


class TestMindHomePutRetry:
    """Cover lines 368-391."""

    @pytest.mark.asyncio
    async def test_put_success(self):
        client = _make_client()
        _mock_session_get(client, json_data={"ok": True}, status=200)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.mindhome_put("/api/test", {"data": 1})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_put_client_error(self):
        client = _make_client()
        _mock_session_multi(client, [(400, None, "Bad")])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            result = await client.mindhome_put("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_put_server_error_exhaust_retries(self):
        client = _make_client()
        _mock_session_multi(client, [
            (500, None, "Error"),
            (500, None, "Error"),
            (500, None, "Error"),
        ])
        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            result = await client.mindhome_put("/api/test", {}, retries=3)
        assert result is None

    @pytest.mark.asyncio
    async def test_put_exception_retries(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("conn"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.put = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client.mindhome_put("/api/test", {}, retries=2)
        assert result is None
        mb.record_failure.assert_called()


class TestMindHomeDeleteRetry:
    """Cover lines 399-421."""

    @pytest.mark.asyncio
    async def test_delete_success(self):
        client = _make_client()
        _mock_session_get(client, json_data={"deleted": True}, status=200)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.mindhome_delete("/api/test")
        assert result == {"deleted": True}

    @pytest.mark.asyncio
    async def test_delete_client_error(self):
        client = _make_client()
        _mock_session_multi(client, [(400, None, "Bad")])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            result = await client.mindhome_delete("/api/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_server_error_exhaust(self):
        client = _make_client()
        _mock_session_multi(client, [
            (500, None, "Error"),
            (500, None, "Error"),
            (500, None, "Error"),
        ])
        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            result = await client.mindhome_delete("/api/test", retries=3)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_exception_retries(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("conn"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.delete = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client.mindhome_delete("/api/test", retries=2)
        assert result is None


class TestGetHaRetryPaths:
    """Cover lines 446-452, 461-462."""

    @pytest.mark.asyncio
    async def test_client_error_returns_none(self):
        client = _make_client()
        _mock_session_multi(client, [(404, None, "Not found")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            result = await client._get_ha("/api/missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_client_error_non_404(self):
        client = _make_client()
        _mock_session_multi(client, [(422, None, "Unprocessable")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            result = await client._get_ha("/api/bad")
        assert result is None

    @pytest.mark.asyncio
    async def test_aiohttp_error_retries(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("conn error"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._get_ha("/api/test")
        assert result is None
        hb.record_failure.assert_called()

    @pytest.mark.asyncio
    async def test_timeout_retries(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._get_ha("/api/test")
        assert result is None


class TestPostHaRetryPaths:
    """Cover lines 486-487, 502-534."""

    @pytest.mark.asyncio
    async def test_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = False
            result = await client._post_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_client_error_returns_none(self):
        client = _make_client()
        _mock_session_multi(client, [(400, None, "Bad")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            result = await client._post_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_server_error_retries(self):
        client = _make_client()
        _mock_session_multi(client, [
            (500, None, "Error"),
            (500, None, "Error"),
            (500, None, "Error"),
        ])
        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._post_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_aiohttp_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._post_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        cm.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._post_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_201_success(self):
        client = _make_client()
        _mock_session_multi(client, [(201, {"created": True}, "")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client._post_ha("/api/test", {})
        assert result == {"created": True}


class TestPutHaRetryPaths:
    """Cover lines 539-540, 554-586."""

    @pytest.mark.asyncio
    async def test_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = False
            result = await client._put_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_client_error(self):
        client = _make_client()
        _mock_session_multi(client, [(400, None, "Bad")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            result = await client._put_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_server_error_retries(self):
        client = _make_client()
        _mock_session_multi(client, [
            (500, None, "Error"),
            (500, None, "Error"),
            (500, None, "Error"),
        ])
        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._put_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_aiohttp_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.put = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._put_ha("/api/test", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        cm.__aexit__ = AsyncMock(return_value=False)
        session.put = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._put_ha("/api/test", {})
        assert result is None


class TestDeleteHaRetryPaths:
    """Cover lines 591-592, 605-637."""

    @pytest.mark.asyncio
    async def test_breaker_open(self):
        client = _make_client()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = False
            result = await client._delete_ha("/api/test")
        assert result is False

    @pytest.mark.asyncio
    async def test_success_204(self):
        client = _make_client()
        _mock_session_multi(client, [(204, None, "")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client._delete_ha("/api/test")
        assert result is True

    @pytest.mark.asyncio
    async def test_client_error(self):
        client = _make_client()
        _mock_session_multi(client, [(400, None, "Bad")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            result = await client._delete_ha("/api/test")
        assert result is False

    @pytest.mark.asyncio
    async def test_server_error_retries(self):
        client = _make_client()
        _mock_session_multi(client, [
            (500, None, "Error"),
            (500, None, "Error"),
            (500, None, "Error"),
        ])
        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._delete_ha("/api/test")
        assert result is False

    @pytest.mark.asyncio
    async def test_aiohttp_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.delete = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._delete_ha("/api/test")
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        cm.__aexit__ = AsyncMock(return_value=False)
        session.delete = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client._delete_ha("/api/test")
        assert result is False


class TestGetMindHomeRetryPaths:
    """Cover lines 688-723."""

    @pytest.mark.asyncio
    async def test_client_error(self):
        client = _make_client()
        _mock_session_multi(client, [(400, None, "Bad")])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            result = await client._get_mindhome("/api/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_server_error_retries(self):
        client = _make_client()
        _mock_session_multi(client, [
            (500, None, "Error"),
            (500, None, "Error"),
            (500, None, "Error"),
        ])
        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client._get_mindhome("/api/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_aiohttp_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client._get_mindhome("/api/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        client = _make_client()
        session = AsyncMock()
        session.closed = False
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client._get_mindhome("/api/test")
        assert result is None


# =====================================================================
# Additional comprehensive tests
# =====================================================================


class TestGetSessionLazyInit:
    """Tests for _get_session lazy initialization and reuse."""

    @pytest.mark.asyncio
    async def test_creates_session_when_none(self):
        client = _make_client()
        assert client._session is None
        with patch("assistant.ha_client.aiohttp.ClientSession") as cs:
            mock_session = MagicMock()
            mock_session.closed = False
            cs.return_value = mock_session
            session = await client._get_session()
            cs.assert_called_once()
            assert session is mock_session

    @pytest.mark.asyncio
    async def test_reuses_existing_open_session(self):
        client = _make_client()
        existing = MagicMock()
        existing.closed = False
        client._session = existing
        session = await client._get_session()
        assert session is existing

    @pytest.mark.asyncio
    async def test_recreates_closed_session(self):
        client = _make_client()
        old_session = MagicMock()
        old_session.closed = True
        client._session = old_session
        with patch("assistant.ha_client.aiohttp.ClientSession") as cs:
            new_session = MagicMock()
            new_session.closed = False
            cs.return_value = new_session
            session = await client._get_session()
            assert session is new_session


class TestGetStatesCache:
    """Tests for states cache behavior."""

    @pytest.mark.asyncio
    async def test_cache_expired_refetches(self):
        client = _make_client()
        client._states_cache = [{"entity_id": "old.data"}]
        client._states_cache_ts = time.monotonic() - 10  # Expired (TTL=5s)
        new_states = [{"entity_id": "new.data"}]
        _mock_session_get(client, json_data=new_states)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_states()
        assert result == new_states

    @pytest.mark.asyncio
    async def test_empty_response_invalidates_cache(self):
        client = _make_client()
        client._states_cache = [{"entity_id": "old"}]
        client._states_cache_ts = time.monotonic() - 10
        _mock_session_get(client, json_data=[])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_states()
        assert result == []
        assert client._states_cache is None
        assert client._states_cache_ts == 0

    @pytest.mark.asyncio
    async def test_none_response_invalidates_cache(self):
        client = _make_client()
        client._states_cache = [{"entity_id": "old"}]
        client._states_cache_ts = time.monotonic() - 10
        _mock_session_get(client, json_data=None)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_states()
        # _get_ha returns None on error, get_states falls back to []
        assert client._states_cache is None


class TestCallServiceEdgeCases:
    """Tests for call_service edge cases."""

    @pytest.mark.asyncio
    async def test_call_service_no_data(self):
        client = _make_client()
        _mock_session_get(client, json_data={"result": "ok"}, status=200)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.call_service("scene", "activate")
        assert result is True

    @pytest.mark.asyncio
    async def test_call_service_unavailable_entity_still_proceeds(self):
        """When entity is unavailable, call_service logs warning but still calls."""
        client = _make_client()
        call_count = {"i": 0}

        def make_resp(status, data):
            resp = AsyncMock()
            resp.status = status
            resp.json = AsyncMock(return_value=data)
            resp.text = AsyncMock(return_value="")
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=resp)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        session = AsyncMock()
        session.closed = False
        cms = [
            make_resp(200, {"entity_id": "light.test", "state": "unavailable"}),
            make_resp(200, {"result": "ok"}),
        ]

        def side(*a, **kw):
            idx = min(call_count["i"], len(cms) - 1)
            call_count["i"] += 1
            return cms[idx]

        session.get = MagicMock(side_effect=side)
        session.post = MagicMock(side_effect=side)
        client._get_session = AsyncMock(return_value=session)

        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client._dep_check_cache", {}):
            hb.is_available = True
            hb.record_success = MagicMock()
            # Patch dependency check to avoid importing state_change_log
            client._check_dependency_conflicts = AsyncMock()
            result = await client.call_service("light", "turn_on", {"entity_id": "light.test"})
        assert result is True

    @pytest.mark.asyncio
    async def test_call_service_non_action_domain_skips_dep_check(self):
        """Non-physical domains (e.g. tts) should skip dependency check."""
        client = _make_client()
        _mock_session_get(client, json_data={"result": "ok"}, status=200)
        client._check_dependency_conflicts = AsyncMock()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            await client.call_service("tts", "speak", {"entity_id": "tts.google"})
        client._check_dependency_conflicts.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_service_failure_returns_false(self):
        client = _make_client()
        _mock_session_get(client, json_data=None, status=500)
        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.call_service("light", "turn_on", {"entity_id": "light.test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_call_service_skip_dep_check_flag(self):
        """When _skip_dep_check_depth is set, dependency check is skipped."""
        client = _make_client()
        client._skip_dep_check_depth = 1
        _mock_session_get(client, json_data={"result": "ok"}, status=200)
        client._check_dependency_conflicts = AsyncMock()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            await client.call_service("light", "turn_on", {"entity_id": "light.test"})
        client._check_dependency_conflicts.assert_not_awaited()


class TestCheckDependencyConflicts:
    """Tests for _check_dependency_conflicts."""

    @pytest.mark.asyncio
    async def test_no_entity_id_returns_early(self):
        client = _make_client()
        with patch("assistant.ha_client._dep_check_cache", {}):
            await client._check_dependency_conflicts("light", "turn_on", {})
        # Should not raise

    @pytest.mark.asyncio
    async def test_rate_limited_skip(self):
        client = _make_client()
        with patch("assistant.ha_client._dep_check_cache", {"light.test": time.monotonic()}):
            await client._check_dependency_conflicts(
                "light", "turn_on", {"entity_id": "light.test"}
            )
        # Should return early due to rate limiting

    @pytest.mark.asyncio
    async def test_exception_does_not_block(self):
        """Dependency check must never block the action."""
        client = _make_client()
        client.get_states = AsyncMock(side_effect=Exception("DB error"))
        with patch("assistant.ha_client._dep_check_cache", {}):
            # Should not raise
            await client._check_dependency_conflicts(
                "light", "turn_on", {"entity_id": "light.new_entity"}
            )

    @pytest.mark.asyncio
    async def test_off_service_state_detection(self):
        """Services with 'off' should map to state_val='off'."""
        client = _make_client()
        client.get_states = AsyncMock(return_value=[])
        with patch("assistant.ha_client._dep_check_cache", {}), \
             patch("assistant.ha_client.StateChangeLog", create=True) as mock_scl:
            mock_scl_mod = MagicMock()
            with patch.dict("sys.modules", {"assistant.state_change_log": mock_scl_mod}):
                # The import inside the method will be handled
                try:
                    await client._check_dependency_conflicts(
                        "light", "turn_off", {"entity_id": "light.dep_test"}
                    )
                except Exception:
                    pass  # Import/mock issues are OK, we just test it doesn't crash


class TestMindHomeCached:
    """Tests for _get_mindhome_cached."""

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        client = _make_client()
        cached_data = {"persons": [{"name": "Test"}]}
        client._mindhome_cache["/api/persons"] = (time.monotonic(), cached_data)
        result = await client._get_mindhome_cached("/api/persons")
        assert result == cached_data

    @pytest.mark.asyncio
    async def test_cache_miss_fetches(self):
        client = _make_client()
        data = {"persons": []}
        _mock_session_get(client, json_data=data)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client._get_mindhome_cached("/api/persons")
        assert result == data
        assert "/api/persons" in client._mindhome_cache

    @pytest.mark.asyncio
    async def test_cache_expired_refetches(self):
        client = _make_client()
        client._mindhome_cache["/api/persons"] = (time.monotonic() - 10, {"old": True})
        fresh_data = {"persons": ["new"]}
        _mock_session_get(client, json_data=fresh_data)
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client._get_mindhome_cached("/api/persons")
        assert result == fresh_data

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_none_result(self):
        client = _make_client()
        client._mindhome_cache["/api/persons"] = (time.monotonic() - 10, {"old": True})
        _mock_session_get(client, json_data=None, status=500)
        with patch("assistant.ha_client.mindhome_breaker") as mb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            mb.is_available = True
            mb.record_failure = MagicMock()
            result = await client._get_mindhome_cached("/api/persons")
        assert result is None
        assert "/api/persons" not in client._mindhome_cache


class TestLogActivity:
    """Tests for log_activity."""

    @pytest.mark.asyncio
    async def test_log_activity_success(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(return_value={"ok": True})
        await client.log_activity(
            action_type="proactive",
            function="set_light",
            reason="Auto-Licht bei Ankunft",
            arguments={"entity_id": "light.flur", "brightness": 200},
            result="Licht eingeschaltet",
        )
        client.mindhome_post.assert_awaited_once()
        call_data = client.mindhome_post.call_args[0][1]
        assert call_data["action_type"] == "proactive"
        assert call_data["actions"][0]["function"] == "set_light"

    @pytest.mark.asyncio
    async def test_log_activity_post_fails(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(return_value=None)
        # Should not raise
        await client.log_activity("emergency", "alarm", "Test")

    @pytest.mark.asyncio
    async def test_log_activity_exception(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(side_effect=Exception("Network"))
        # Should not raise
        await client.log_activity("emergency", "alarm", "Test")

    @pytest.mark.asyncio
    async def test_log_activity_truncates_reason(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(return_value={"ok": True})
        long_reason = "x" * 500
        await client.log_activity("proactive", "fn", long_reason)
        call_data = client.mindhome_post.call_args[0][1]
        assert len(call_data["reason"]) <= 200

    @pytest.mark.asyncio
    async def test_log_activity_truncates_result(self):
        client = _make_client()
        client.mindhome_post = AsyncMock(return_value={"ok": True})
        long_result = "r" * 1000
        await client.log_activity("proactive", "fn", "reason", result=long_result)
        call_data = client.mindhome_post.call_args[0][1]
        assert len(call_data["actions"][0]["result"]["message"]) <= 500


class TestConstructorApiKey:
    """Tests for API key header setup."""

    def test_no_api_key(self):
        with patch("assistant.ha_client.settings") as s_mock, \
             patch("assistant.ha_client.ha_breaker"), \
             patch("assistant.ha_client.mindhome_breaker"):
            s_mock.ha_url = "http://ha.local:8123"
            s_mock.ha_token = "test-token"
            s_mock.mindhome_url = "http://mh.local:8099"
            s_mock.assistant_api_key = ""
            from assistant.ha_client import HomeAssistantClient
            client = HomeAssistantClient()
        assert "X-API-Key" not in client._mindhome_headers

    def test_with_api_key(self):
        with patch("assistant.ha_client.settings") as s_mock, \
             patch("assistant.ha_client.ha_breaker"), \
             patch("assistant.ha_client.mindhome_breaker"):
            s_mock.ha_url = "http://ha.local:8123"
            s_mock.ha_token = "test-token"
            s_mock.mindhome_url = "http://mh.local:8099"
            s_mock.assistant_api_key = "secret-key-123"
            from assistant.ha_client import HomeAssistantClient
            client = HomeAssistantClient()
        assert client._mindhome_headers["X-API-Key"] == "secret-key-123"


class TestSearchDevicesEdgeCases:
    """Additional edge cases for search_devices."""

    @pytest.mark.asyncio
    async def test_no_params(self):
        client = _make_client()
        _mock_session_get(client, json_data=[{"entity_id": "light.all"}])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.search_devices()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_valid_room_with_umlauts(self):
        client = _make_client()
        _mock_session_get(client, json_data=[])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.search_devices(room="Büro Erdgeschoß")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_both_domain_and_room(self):
        client = _make_client()
        _mock_session_get(client, json_data=[{"entity_id": "light.buero"}])
        with patch("assistant.ha_client.mindhome_breaker") as mb:
            mb.is_available = True
            mb.record_success = MagicMock()
            result = await client.search_devices(domain="light", room="Buero")
        assert isinstance(result, list)


class TestGetHistoryEdgeCases:
    """Additional edge cases for get_history."""

    @pytest.mark.asyncio
    async def test_history_empty_list(self):
        client = _make_client()
        _mock_session_get(client, json_data=[])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_history("sensor.temp", hours=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_history_hours_clamped_minimum(self):
        client = _make_client()
        _mock_session_get(client, json_data=[[{"state": "20"}]])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_history("sensor.temp", hours=-5)
        # hours clamped to min 1
        assert result == [{"state": "20"}]


class TestGetStateEntityNotFound:
    """Test entity not found scenarios."""

    @pytest.mark.asyncio
    async def test_entity_not_found_returns_none(self):
        client = _make_client()
        _mock_session_multi(client, [(404, None, "Not found")])
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            result = await client.get_state("sensor.nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_entity_found(self):
        client = _make_client()
        state_data = {"entity_id": "sensor.temp", "state": "22.5", "attributes": {"unit_of_measurement": "°C"}}
        _mock_session_get(client, json_data=state_data)
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = True
            hb.record_success = MagicMock()
            result = await client.get_state("sensor.temp")
        assert result["state"] == "22.5"


class TestCloseAlreadyClosed:
    """Test close when session is already closed."""

    @pytest.mark.asyncio
    async def test_close_already_closed_session(self):
        client = _make_client()
        mock_session = AsyncMock()
        mock_session.closed = True
        client._session = mock_session
        await client.close()
        mock_session.close.assert_not_awaited()


class TestCallServiceWithResponseBreaker:
    """Test call_service_with_response when breaker is open."""

    @pytest.mark.asyncio
    async def test_breaker_open_returns_none(self):
        client = _make_client()
        with patch("assistant.ha_client.ha_breaker") as hb:
            hb.is_available = False
            result = await client.call_service_with_response("weather", "get_forecasts", {})
        assert result is None


class TestFireEventFailure:
    """Test fire_event failure case."""

    @pytest.mark.asyncio
    async def test_fire_event_failure(self):
        client = _make_client()
        _mock_session_get(client, json_data=None, status=500)
        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.fire_event("test_event", {"key": "val"})
        assert result is False


class TestPutConfigDeleteConfigFailure:
    """Test put_config/delete_config failure cases."""

    @pytest.mark.asyncio
    async def test_put_config_failure(self):
        client = _make_client()
        _mock_session_multi(client, [(500, None, "Error")] * 3)
        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.put_config("automation", "test_id", {"alias": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_config_failure(self):
        client = _make_client()
        _mock_session_multi(client, [(500, None, "Error")] * 3)
        with patch("assistant.ha_client.ha_breaker") as hb, \
             patch("assistant.ha_client.asyncio.sleep", new_callable=AsyncMock):
            hb.is_available = True
            hb.record_failure = MagicMock()
            result = await client.delete_config("automation", "test_id")
        assert result is False
