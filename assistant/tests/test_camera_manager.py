"""
Tests fuer CameraManager — Kamera-Integration und Vision-LLM-Analyse.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.camera_manager import CameraManager


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def ha_mock():
    """Home Assistant Client Mock."""
    mock = AsyncMock()
    mock.get_states = AsyncMock(return_value=[])
    mock.get_camera_snapshot = AsyncMock(return_value=b"fake_image_bytes")
    return mock


@pytest.fixture
def ollama_mock():
    """Ollama Client Mock."""
    mock = AsyncMock()
    mock.chat = AsyncMock(return_value={
        "message": {"content": "Person mit Paket vor der Tuer."},
    })
    return mock


@pytest.fixture
def cm(ha_mock, ollama_mock):
    """CameraManager Instanz."""
    with patch("assistant.camera_manager.yaml_config", {
        "cameras": {
            "enabled": True,
            "vision_model": "llava",
            "camera_map": {"haustuer": "camera.haustuer", "garage": "camera.garage"},
        }
    }):
        return CameraManager(ha_mock, ollama_mock)


# =====================================================================
# find_camera
# =====================================================================


class TestFindCamera:
    """Tests fuer _find_camera()."""

    @pytest.mark.asyncio
    async def test_find_by_mapping(self, cm):
        """Kamera wird per camera_map gefunden."""
        result = await cm._find_camera("haustuer")
        assert result == "camera.haustuer"

    @pytest.mark.asyncio
    async def test_find_by_mapping_case_insensitive(self, cm):
        result = await cm._find_camera("Haustuer")
        assert result == "camera.haustuer"

    @pytest.mark.asyncio
    async def test_find_by_ha_entity(self, cm, ha_mock):
        """Kamera wird per HA-Entity-Suche gefunden."""
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "camera.garten_cam", "state": "idle",
             "attributes": {"friendly_name": "Garten Kamera"}},
        ])
        result = await cm._find_camera("garten")
        assert result == "camera.garten_cam"

    @pytest.mark.asyncio
    async def test_find_not_found(self, cm, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await cm._find_camera("unbekannt")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_empty_search(self, cm):
        result = await cm._find_camera("")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_ignores_non_camera_entities(self, cm, ha_mock):
        ha_mock.get_states = AsyncMock(return_value=[
            {"entity_id": "light.garten", "state": "on", "attributes": {}},
        ])
        result = await cm._find_camera("garten")
        assert result is None


# =====================================================================
# get_snapshot
# =====================================================================


class TestGetSnapshot:
    """Tests fuer _get_snapshot()."""

    @pytest.mark.asyncio
    async def test_snapshot_success(self, cm, ha_mock):
        ha_mock.get_camera_snapshot = AsyncMock(return_value=b"image_data")
        result = await cm._get_snapshot("camera.haustuer")
        assert result == b"image_data"

    @pytest.mark.asyncio
    async def test_snapshot_failure(self, cm, ha_mock):
        ha_mock.get_camera_snapshot = AsyncMock(side_effect=Exception("Camera offline"))
        result = await cm._get_snapshot("camera.haustuer")
        assert result is None


# =====================================================================
# analyze_image
# =====================================================================


class TestAnalyzeImage:
    """Tests fuer _analyze_image()."""

    @pytest.mark.asyncio
    async def test_analyze_doorbell_context(self, cm, ollama_mock):
        result = await cm._analyze_image(b"fake_data", context="doorbell")
        assert result == "Person mit Paket vor der Tuer."
        # Pruefen dass doorbell-spezifischer Prompt verwendet wird
        call_args = ollama_mock.chat.call_args
        msg = call_args[1]["messages"][0]["content"]
        assert "Tuerkamera" in msg

    @pytest.mark.asyncio
    async def test_analyze_night_motion_context(self, cm, ollama_mock):
        await cm._analyze_image(b"fake_data", context="night_motion")
        msg = ollama_mock.chat.call_args[1]["messages"][0]["content"]
        assert "Nachtaufnahme" in msg

    @pytest.mark.asyncio
    async def test_analyze_general_context(self, cm, ollama_mock):
        await cm._analyze_image(b"fake_data", context="general")
        msg = ollama_mock.chat.call_args[1]["messages"][0]["content"]
        assert "Kamera-Bild" in msg

    @pytest.mark.asyncio
    async def test_analyze_sends_base64_image(self, cm, ollama_mock):
        image = b"test_image_data"
        await cm._analyze_image(image)
        call_args = ollama_mock.chat.call_args
        msg = call_args[1]["messages"][0]
        expected_b64 = base64.b64encode(image).decode("utf-8")
        assert msg["images"][0] == expected_b64

    @pytest.mark.asyncio
    async def test_analyze_uses_vision_model(self, cm, ollama_mock):
        await cm._analyze_image(b"data")
        assert ollama_mock.chat.call_args[1]["model"] == "llava"

    @pytest.mark.asyncio
    async def test_analyze_error_returns_none(self, cm, ollama_mock):
        ollama_mock.chat = AsyncMock(side_effect=Exception("Model error"))
        result = await cm._analyze_image(b"data")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_error_response(self, cm, ollama_mock):
        ollama_mock.chat = AsyncMock(return_value={"error": "Model not loaded"})
        result = await cm._analyze_image(b"data")
        assert result is None or result == ""


# =====================================================================
# describe_doorbell
# =====================================================================


class TestDescribeDoorbell:
    """Tests fuer describe_doorbell()."""

    @pytest.mark.asyncio
    async def test_doorbell_success(self, cm, ha_mock, ollama_mock):
        """Tuerkamera wird gefunden und beschrieben."""
        result = await cm.describe_doorbell()
        assert result == "Person mit Paket vor der Tuer."

    @pytest.mark.asyncio
    async def test_doorbell_no_camera(self, cm, ha_mock, ollama_mock):
        """Keine Tuerkamera gefunden."""
        cm.camera_map = {}
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await cm.describe_doorbell()
        assert result is None

    @pytest.mark.asyncio
    async def test_doorbell_snapshot_fails(self, cm, ha_mock):
        """Snapshot fehlgeschlagen."""
        ha_mock.get_camera_snapshot = AsyncMock(return_value=None)
        result = await cm.describe_doorbell()
        assert result is None


# =====================================================================
# get_camera_view
# =====================================================================


class TestGetCameraView:
    """Tests fuer get_camera_view()."""

    @pytest.mark.asyncio
    async def test_view_success(self, cm, ha_mock, ollama_mock):
        result = await cm.get_camera_view(camera_name="haustuer")
        assert result["success"] is True
        assert "Person" in result["message"]
        assert result["image_available"] is True

    @pytest.mark.asyncio
    async def test_view_disabled(self, cm):
        cm.enabled = False
        result = await cm.get_camera_view(camera_name="haustuer")
        assert result["success"] is False
        assert "deaktiviert" in result["message"]

    @pytest.mark.asyncio
    async def test_view_camera_not_found(self, cm, ha_mock):
        cm.camera_map = {}
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await cm.get_camera_view(camera_name="unbekannt")
        assert result["success"] is False


# =====================================================================
# analyze_night_motion
# =====================================================================


class TestAnalyzeNightMotion:
    """Tests fuer analyze_night_motion()."""

    @pytest.mark.asyncio
    async def test_night_motion_disabled(self, cm):
        cm.enabled = False
        result = await cm.analyze_night_motion("binary_sensor.motion_aussen")
        assert result is None

    @pytest.mark.asyncio
    async def test_night_motion_with_mapped_camera(self, cm, ha_mock, ollama_mock):
        """Motion-Sensor matched zu Kamera im camera_map."""
        cm.camera_map = {"aussen": "camera.aussen_cam"}
        result = await cm.analyze_night_motion("binary_sensor.motion_aussen")
        assert result is not None

    @pytest.mark.asyncio
    async def test_night_motion_no_camera(self, cm, ha_mock):
        """Keine passende Kamera gefunden."""
        cm.camera_map = {}
        ha_mock.get_states = AsyncMock(return_value=[])
        result = await cm.analyze_night_motion("binary_sensor.motion_keller")
        assert result is None


# =====================================================================
# Config
# =====================================================================


class TestConfig:
    """Tests fuer Konfiguration."""

    def test_default_config(self):
        ha = AsyncMock()
        ollama = AsyncMock()
        with patch("assistant.camera_manager.yaml_config", {}):
            cm = CameraManager(ha, ollama)
            assert cm.enabled is True
            assert cm.vision_model == "llava"
            assert cm.camera_map == {}

    def test_custom_config(self):
        ha = AsyncMock()
        ollama = AsyncMock()
        with patch("assistant.camera_manager.yaml_config", {
            "cameras": {
                "enabled": False,
                "vision_model": "custom_vision",
                "camera_map": {"vorne": "camera.front"},
            }
        }):
            cm = CameraManager(ha, ollama)
            assert cm.enabled is False
            assert cm.vision_model == "custom_vision"
            assert cm.camera_map == {"vorne": "camera.front"}
