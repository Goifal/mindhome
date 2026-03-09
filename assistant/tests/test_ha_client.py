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
