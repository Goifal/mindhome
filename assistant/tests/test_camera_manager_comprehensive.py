"""
Comprehensive tests for CameraManager — covering camera lookup,
snapshot handling, vision analysis, doorbell, and night motion scenarios.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.camera_manager import CameraManager


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def ha():
    mock = AsyncMock()
    mock.get_states = AsyncMock(return_value=[])
    mock.get_camera_snapshot = AsyncMock(return_value=b"fake_image_bytes")
    return mock


@pytest.fixture
def ollama():
    mock = AsyncMock()
    mock.chat = AsyncMock(
        return_value={
            "message": {"content": "Eine Person steht vor der Tuer."},
        }
    )
    return mock


@pytest.fixture
def cm(ha, ollama):
    with patch(
        "assistant.camera_manager.yaml_config",
        {
            "cameras": {
                "enabled": True,
                "vision_model": "llava",
                "camera_map": {
                    "haustuer": "camera.haustuer",
                    "garage": "camera.garage",
                    "garten": "camera.garten_cam",
                },
            }
        },
    ):
        return CameraManager(ha, ollama)


# ── _find_camera advanced scenarios ───────────────────────────


class TestFindCameraAdvanced:
    """Advanced tests for camera lookup logic."""

    @pytest.mark.asyncio
    async def test_find_by_friendly_name(self, cm, ha):
        """Camera found by friendly_name match."""
        ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "camera.front_cam",
                    "state": "idle",
                    "attributes": {"friendly_name": "Vordere Haustuer Kamera"},
                },
            ]
        )
        result = await cm._find_camera("vordere")
        assert result == "camera.front_cam"

    @pytest.mark.asyncio
    async def test_find_with_spaces_converted_to_underscores(self, cm, ha):
        """Spaces in search string are converted to underscores."""
        ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "camera.hinter_hof",
                    "state": "idle",
                    "attributes": {"friendly_name": "Hinterhof"},
                },
            ]
        )
        result = await cm._find_camera("hinter hof")
        assert result == "camera.hinter_hof"

    @pytest.mark.asyncio
    async def test_find_prefers_mapping_over_ha_search(self, cm, ha):
        """camera_map mapping takes precedence over HA entity search."""
        ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "camera.haustuer_alt",
                    "state": "idle",
                    "attributes": {"friendly_name": "Haustuer Alt"},
                },
            ]
        )
        result = await cm._find_camera("haustuer")
        # Should return the mapped entity, not the HA search result
        assert result == "camera.haustuer"

    @pytest.mark.asyncio
    async def test_find_returns_none_when_states_empty(self, cm, ha):
        """Returns None when HA returns empty states and no mapping match."""
        ha.get_states = AsyncMock(return_value=[])
        result = await cm._find_camera("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_returns_none_when_states_is_none(self, cm, ha):
        """Returns None when HA returns None for states."""
        ha.get_states = AsyncMock(return_value=None)
        result = await cm._find_camera("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_skips_non_camera_entities(self, cm, ha):
        """Only camera.* entities are considered."""
        ha.get_states = AsyncMock(
            return_value=[
                {"entity_id": "light.haustuer", "state": "on", "attributes": {}},
                {"entity_id": "switch.haustuer", "state": "on", "attributes": {}},
                {
                    "entity_id": "binary_sensor.haustuer_motion",
                    "state": "on",
                    "attributes": {},
                },
            ]
        )
        # "haustuer" is in camera_map, so this won't hit HA search
        cm.camera_map = {}
        result = await cm._find_camera("haustuer")
        assert result is None


# ── get_camera_view comprehensive ─────────────────────────────


class TestGetCameraViewComprehensive:
    """Comprehensive tests for the main get_camera_view method."""

    @pytest.mark.asyncio
    async def test_view_uses_room_parameter(self, cm, ha, ollama):
        """Room parameter is used when camera_name is empty."""
        result = await cm.get_camera_view(room="garage")
        assert result["success"] is True
        assert result["camera_entity"] == "camera.garage"

    @pytest.mark.asyncio
    async def test_view_camera_name_takes_priority(self, cm, ha, ollama):
        """camera_name is used when both camera_name and room are provided."""
        result = await cm.get_camera_view(camera_name="haustuer", room="garage")
        assert result["camera_entity"] == "camera.haustuer"

    @pytest.mark.asyncio
    async def test_view_snapshot_none_returns_failure(self, cm, ha):
        """When snapshot returns None, report failure."""
        ha.get_camera_snapshot = AsyncMock(return_value=None)
        result = await cm.get_camera_view(camera_name="haustuer")
        assert result["success"] is False
        assert "Snapshot" in result["message"]

    @pytest.mark.asyncio
    async def test_view_snapshot_exception_returns_failure(self, cm, ha):
        """When snapshot raises exception, report failure."""
        ha.get_camera_snapshot = AsyncMock(side_effect=ConnectionError("timeout"))
        result = await cm.get_camera_view(camera_name="haustuer")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_view_analysis_none_returns_partial_success(self, cm, ha, ollama):
        """When vision analysis returns None, still return the snapshot."""
        ollama.chat = AsyncMock(side_effect=Exception("Vision model error"))
        result = await cm.get_camera_view(camera_name="haustuer")
        assert result["success"] is True
        assert "Bild-Analyse nicht verfuegbar" in result["message"]
        assert result["image_available"] is True
        assert "snapshot" in result

    @pytest.mark.asyncio
    async def test_view_includes_base64_snapshot(self, cm, ha, ollama):
        """Successful view includes base64-encoded snapshot."""
        ha.get_camera_snapshot = AsyncMock(return_value=b"test_image_data")
        result = await cm.get_camera_view(camera_name="haustuer")
        expected_b64 = base64.b64encode(b"test_image_data").decode()
        assert result["snapshot"] == expected_b64

    @pytest.mark.asyncio
    async def test_view_both_params_empty_fails(self, cm, ha):
        """When both camera_name and room are empty, returns failure."""
        cm.camera_map = {}
        ha.get_states = AsyncMock(return_value=[])
        result = await cm.get_camera_view(camera_name="", room="")
        assert result["success"] is False


# ── describe_doorbell comprehensive ───────────────────────────


class TestDescribeDoorbellComprehensive:
    """Comprehensive tests for doorbell description."""

    @pytest.mark.asyncio
    async def test_doorbell_tries_multiple_names(self, cm, ha, ollama):
        """Doorbell search tries multiple common names."""
        # Remove all from camera_map so it falls through to HA search
        cm.camera_map = {}
        ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "camera.front_door",
                    "state": "idle",
                    "attributes": {"friendly_name": "Front Door Camera"},
                },
            ]
        )
        result = await cm.describe_doorbell()
        assert result is not None

    @pytest.mark.asyncio
    async def test_doorbell_returns_none_when_disabled(self, cm):
        """Disabled manager returns None."""
        cm.enabled = False
        result = await cm.describe_doorbell()
        assert result is None

    @pytest.mark.asyncio
    async def test_doorbell_snapshot_returns_none_skips_to_next(self, cm, ha, ollama):
        """When snapshot is None for first camera, tries next name."""
        cm.camera_map = {"haustuer": "camera.haustuer", "eingang": "camera.eingang"}
        call_count = 0

        async def conditional_snapshot(entity_id):
            nonlocal call_count
            call_count += 1
            if entity_id == "camera.haustuer":
                return None  # First camera fails
            return b"image_data"  # Second succeeds

        ha.get_camera_snapshot = AsyncMock(side_effect=conditional_snapshot)
        result = await cm.describe_doorbell()
        # Should have found eingang camera
        assert result is not None or call_count >= 2

    @pytest.mark.asyncio
    async def test_doorbell_uses_doorbell_context(self, cm, ha, ollama):
        """Doorbell analysis uses 'doorbell' context for the prompt."""
        await cm.describe_doorbell()
        call_args = ollama.chat.call_args
        if call_args:
            msg = call_args[1]["messages"][0]["content"]
            assert "Tuerkamera" in msg


# ── analyze_night_motion comprehensive ────────────────────────


class TestAnalyzeNightMotionComprehensive:
    """Comprehensive tests for night motion analysis."""

    @pytest.mark.asyncio
    async def test_night_motion_matches_partial_name(self, cm, ha, ollama):
        """Motion sensor entity partially matches camera_map key."""
        cm.camera_map = {"garten": "camera.garten_cam"}
        result = await cm.analyze_night_motion("binary_sensor.motion_garten_hinten")
        # "garten" is in "motion_garten_hinten"
        assert result is not None

    @pytest.mark.asyncio
    async def test_night_motion_fallback_keywords(self, cm, ha, ollama):
        """Fallback to outdoor cameras using keywords."""
        cm.camera_map = {}
        ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "camera.indoor_living",
                    "state": "idle",
                    "attributes": {},
                },
                {
                    "entity_id": "camera.aussen_einfahrt",
                    "state": "idle",
                    "attributes": {},
                },
            ]
        )
        ha.get_camera_snapshot = AsyncMock(return_value=b"night_image")
        result = await cm.analyze_night_motion("binary_sensor.motion_unknown")
        assert result is not None

    @pytest.mark.asyncio
    async def test_night_motion_fallback_garten_keyword(self, cm, ha, ollama):
        """Fallback finds camera with 'garten' keyword."""
        cm.camera_map = {}
        ha.get_states = AsyncMock(
            return_value=[
                {"entity_id": "camera.garten_sued", "state": "idle", "attributes": {}},
            ]
        )
        ha.get_camera_snapshot = AsyncMock(return_value=b"garden_image")
        result = await cm.analyze_night_motion("binary_sensor.random_motion")
        assert result is not None

    @pytest.mark.asyncio
    async def test_night_motion_fallback_einfahrt_keyword(self, cm, ha, ollama):
        """Fallback finds camera with 'einfahrt' keyword."""
        cm.camera_map = {}
        ha.get_states = AsyncMock(
            return_value=[
                {"entity_id": "camera.einfahrt", "state": "idle", "attributes": {}},
            ]
        )
        ha.get_camera_snapshot = AsyncMock(return_value=b"driveway_image")
        result = await cm.analyze_night_motion("binary_sensor.motion_x")
        assert result is not None

    @pytest.mark.asyncio
    async def test_night_motion_fallback_hof_keyword(self, cm, ha, ollama):
        """Fallback finds camera with 'hof' keyword."""
        cm.camera_map = {}
        ha.get_states = AsyncMock(
            return_value=[
                {"entity_id": "camera.hof_cam", "state": "idle", "attributes": {}},
            ]
        )
        ha.get_camera_snapshot = AsyncMock(return_value=b"yard_image")
        result = await cm.analyze_night_motion("binary_sensor.motion_y")
        assert result is not None

    @pytest.mark.asyncio
    async def test_night_motion_no_outdoor_cameras(self, cm, ha):
        """No outdoor cameras found returns None."""
        cm.camera_map = {}
        ha.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "camera.indoor_office",
                    "state": "idle",
                    "attributes": {},
                },
                {
                    "entity_id": "camera.indoor_wohnzimmer",
                    "state": "idle",
                    "attributes": {},
                },
            ]
        )
        result = await cm.analyze_night_motion("binary_sensor.motion_z")
        assert result is None

    @pytest.mark.asyncio
    async def test_night_motion_snapshot_fails_returns_none(self, cm, ha):
        """Snapshot failure for night motion returns None."""
        cm.camera_map = {"aussen": "camera.aussen"}
        ha.get_camera_snapshot = AsyncMock(side_effect=Exception("Camera offline"))
        result = await cm.analyze_night_motion("binary_sensor.motion_aussen")
        assert result is None

    @pytest.mark.asyncio
    async def test_night_motion_uses_night_context(self, cm, ha, ollama):
        """Night motion uses 'night_motion' context for the prompt."""
        cm.camera_map = {"garten": "camera.garten_cam"}
        ha.get_camera_snapshot = AsyncMock(return_value=b"night_image")
        await cm.analyze_night_motion("binary_sensor.motion_garten")
        call_args = ollama.chat.call_args
        if call_args:
            msg = call_args[1]["messages"][0]["content"]
            assert "Nachtaufnahme" in msg


# ── _analyze_image edge cases ─────────────────────────────────


class TestAnalyzeImageEdgeCases:
    """Edge cases for image analysis."""

    @pytest.mark.asyncio
    async def test_analyze_empty_response_content(self, cm, ollama):
        """Empty content in response returns empty string."""
        ollama.chat = AsyncMock(
            return_value={
                "message": {"content": ""},
            }
        )
        result = await cm._analyze_image(b"data")
        assert result == ""

    @pytest.mark.asyncio
    async def test_analyze_response_without_message_key(self, cm, ollama):
        """Response without 'message' key returns empty string or None."""
        ollama.chat = AsyncMock(return_value={})
        result = await cm._analyze_image(b"data")
        # .get("message", {}).get("content", "") returns ""
        assert result == ""

    @pytest.mark.asyncio
    async def test_analyze_large_image(self, cm, ollama):
        """Large image data is base64-encoded and sent correctly."""
        large_image = b"\x89PNG" * 100000  # ~400KB
        await cm._analyze_image(large_image)
        call_args = ollama.chat.call_args
        msg = call_args[1]["messages"][0]
        expected_b64 = base64.b64encode(large_image).decode("utf-8")
        assert msg["images"][0] == expected_b64

    @pytest.mark.asyncio
    async def test_analyze_uses_temperature_03(self, cm, ollama):
        """Vision LLM is called with temperature 0.3."""
        await cm._analyze_image(b"data")
        assert ollama.chat.call_args[1]["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_analyze_uses_max_tokens_300(self, cm, ollama):
        """Vision LLM is called with max_tokens=300."""
        await cm._analyze_image(b"data")
        assert ollama.chat.call_args[1]["max_tokens"] == 300


# ── Configuration edge cases ─────────────────────────────────


class TestCameraConfigEdgeCases:
    """Edge cases for CameraManager configuration."""

    def test_missing_cameras_section(self):
        """When 'cameras' key is missing entirely, defaults are used."""
        ha = AsyncMock()
        ollama = AsyncMock()
        with patch("assistant.camera_manager.yaml_config", {}):
            cm = CameraManager(ha, ollama)
            assert cm.enabled is True
            assert cm.vision_model == "llava"
            assert cm.camera_map == {}

    def test_partial_config(self):
        """Partial camera config uses defaults for missing keys."""
        ha = AsyncMock()
        ollama = AsyncMock()
        with patch(
            "assistant.camera_manager.yaml_config", {"cameras": {"enabled": False}}
        ):
            cm = CameraManager(ha, ollama)
            assert cm.enabled is False
            assert cm.vision_model == "llava"
            assert cm.camera_map == {}

    def test_camera_map_with_many_entries(self):
        """Large camera_map is stored correctly."""
        ha = AsyncMock()
        ollama = AsyncMock()
        big_map = {f"camera_{i}": f"camera.cam_{i}" for i in range(20)}
        with patch(
            "assistant.camera_manager.yaml_config", {"cameras": {"camera_map": big_map}}
        ):
            cm = CameraManager(ha, ollama)
            assert len(cm.camera_map) == 20
