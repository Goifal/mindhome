"""Tests for assistant.workshop_generator module."""

import json
import math
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.workshop_generator import (
    ESP32_PINOUT,
    MATERIAL_PROPERTIES,
    RESISTOR_E24,
    SCREW_TORQUES_NM,
    UNIT_CONVERSIONS,
    WIRE_GAUGE_MM2,
    WorkshopGenerator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wg(ollama_mock=None):
    ollama = ollama_mock or AsyncMock()
    wg = WorkshopGenerator(ollama)
    return wg


def _make_wg_with_router(model_name="test-model"):
    ollama = AsyncMock()
    ollama.chat = AsyncMock(return_value="generated code")
    wg = WorkshopGenerator(ollama)
    router = MagicMock()
    router.model_deep = model_name
    router.model_smart = model_name
    wg.set_model_router(router)
    return wg


# ---------------------------------------------------------------------------
# calculate: resistor_divider
# ---------------------------------------------------------------------------

class TestCalcResistorDivider:
    def test_basic_divider(self):
        wg = _make_wg()
        result = wg.calculate("resistor_divider", v_in=5.0, v_out=3.3)
        assert "r1" in result
        assert "r2" in result
        assert "v_out_real" in result
        assert "error_pct" in result
        assert result["v_out_real"] > 0

    def test_custom_r2(self):
        wg = _make_wg()
        result = wg.calculate("resistor_divider", v_in=12.0, v_out=5.0, r2=4700)
        assert result["r2"] == 4700


# ---------------------------------------------------------------------------
# calculate: led_resistor
# ---------------------------------------------------------------------------

class TestCalcLedResistor:
    def test_basic_led(self):
        wg = _make_wg()
        result = wg.calculate("led_resistor", v_supply=5.0, v_led=2.0, i_ma=20)
        assert "resistor_ohm" in result
        assert "power_mw" in result
        assert result["resistor_ohm"] > 0

    def test_default_values(self):
        wg = _make_wg()
        result = wg.calculate("led_resistor", v_supply=3.3)
        assert "resistor_ohm" in result


# ---------------------------------------------------------------------------
# calculate: wire_gauge
# ---------------------------------------------------------------------------

class TestCalcWireGauge:
    def test_low_current(self):
        wg = _make_wg()
        result = wg.calculate("wire_gauge", current_a=2)
        assert result["recommended_mm2"] == 0.5

    def test_high_current(self):
        wg = _make_wg()
        result = wg.calculate("wire_gauge", current_a=40)
        assert result["recommended_mm2"] == 10.0

    def test_excessive_current(self):
        wg = _make_wg()
        result = wg.calculate("wire_gauge", current_a=100)
        assert "error" in result


# ---------------------------------------------------------------------------
# calculate: ohms_law
# ---------------------------------------------------------------------------

class TestCalcOhmsLaw:
    def test_v_and_i(self):
        wg = _make_wg()
        result = wg.calculate("ohms_law", v=12, i=0.5)
        assert result["r"] == 24.0
        assert result["p"] == 6.0

    def test_v_and_r(self):
        wg = _make_wg()
        result = wg.calculate("ohms_law", v=12, r=100)
        assert "i" in result
        assert "p" in result

    def test_i_and_r(self):
        wg = _make_wg()
        result = wg.calculate("ohms_law", i=0.1, r=100)
        assert result["v"] == 10.0

    def test_missing_params(self):
        wg = _make_wg()
        result = wg.calculate("ohms_law")
        assert "error" in result


# ---------------------------------------------------------------------------
# calculate: 3d_print_weight
# ---------------------------------------------------------------------------

class TestCalc3dPrintWeight:
    def test_pla_default(self):
        wg = _make_wg()
        result = wg.calculate("3d_print_weight", volume_cm3=10)
        assert result["material"] == "pla"
        assert result["weight_g"] > 0

    def test_petg(self):
        wg = _make_wg()
        result = wg.calculate("3d_print_weight", volume_cm3=10, material="petg", infill_pct=50)
        assert result["material"] == "petg"
        assert result["infill_pct"] == 50


# ---------------------------------------------------------------------------
# calculate: screw_torque
# ---------------------------------------------------------------------------

class TestCalcScrewTorque:
    def test_m6(self):
        wg = _make_wg()
        result = wg.calculate("screw_torque", screw_size="M6")
        assert result["torque_nm"] == 8.5

    def test_lowercase(self):
        wg = _make_wg()
        result = wg.calculate("screw_torque", screw_size="m8")
        assert result["torque_nm"] == 22

    def test_unknown_size(self):
        wg = _make_wg()
        result = wg.calculate("screw_torque", screw_size="M99")
        assert "error" in result


# ---------------------------------------------------------------------------
# calculate: convert
# ---------------------------------------------------------------------------

class TestCalcConvert:
    def test_mm_to_inch(self):
        wg = _make_wg()
        result = wg.calculate("convert", value=25.4, from_unit="mm", to_unit="inch")
        assert abs(result["result"] - 1.0) < 0.01

    def test_celsius_to_fahrenheit(self):
        wg = _make_wg()
        result = wg.calculate("convert", value=100, from_unit="celsius", to_unit="fahrenheit")
        assert abs(result["result"] - 212.0) < 0.01

    def test_unsupported_conversion(self):
        wg = _make_wg()
        result = wg.calculate("convert", value=1, from_unit="kg", to_unit="celsius")
        assert "error" in result


# ---------------------------------------------------------------------------
# calculate: power_supply
# ---------------------------------------------------------------------------

class TestCalcPowerSupply:
    def test_single_component(self):
        wg = _make_wg()
        result = wg.calculate("power_supply", voltage=5, components=[
            {"current_ma": 200, "quantity": 2},
        ])
        assert result["total_ma"] == 400
        assert result["recommended_ma"] == 500  # 400 * 1.25

    def test_empty_components(self):
        wg = _make_wg()
        result = wg.calculate("power_supply", voltage=5, components=[])
        assert result["total_ma"] == 0


# ---------------------------------------------------------------------------
# calculate: unknown type
# ---------------------------------------------------------------------------

class TestCalcUnknown:
    def test_unknown_type(self):
        wg = _make_wg()
        result = wg.calculate("nonexistent_calc")
        assert "error" in result


# ---------------------------------------------------------------------------
# _nearest_e24
# ---------------------------------------------------------------------------

class TestNearestE24:
    def test_exact_value(self):
        wg = _make_wg()
        assert wg._nearest_e24(100) == 100.0

    def test_rounded_value(self):
        wg = _make_wg()
        result = wg._nearest_e24(155)
        assert result == 150.0

    def test_zero_or_negative(self):
        wg = _make_wg()
        assert wg._nearest_e24(0) == RESISTOR_E24[0]
        assert wg._nearest_e24(-5) == RESISTOR_E24[0]


# ---------------------------------------------------------------------------
# Async: generate_code - no model
# ---------------------------------------------------------------------------

class TestGenerateCode:
    @pytest.mark.asyncio
    async def test_no_model_returns_error(self):
        wg = _make_wg()
        wg.model_router = None
        result = await wg.generate_code("proj1", "blink LED")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_generate_code_success(self):
        wg = _make_wg_with_router()
        wg.redis = None  # no redis
        result = await wg.generate_code("proj1", "blink LED", language="arduino")
        assert result["status"] == "ok"
        assert result["language"] == "arduino"
        assert result["filename"].endswith(".ino")


# ---------------------------------------------------------------------------
# Async: generate_3d_model
# ---------------------------------------------------------------------------

class TestGenerate3dModel:
    @pytest.mark.asyncio
    async def test_no_model(self):
        wg = _make_wg()
        result = await wg.generate_3d_model("proj1", "box")
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Async: generate_schematic
# ---------------------------------------------------------------------------

class TestGenerateSchematic:
    @pytest.mark.asyncio
    async def test_no_model(self):
        wg = _make_wg()
        result = await wg.generate_schematic("proj1", "LED circuit")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_svg_extraction(self):
        ollama = AsyncMock()
        ollama.chat = AsyncMock(return_value='Some text\n<svg viewBox="0 0 100 100"><circle/></svg>\nMore text')
        wg = _make_wg(ollama)
        wg.model_router = MagicMock()
        wg.model_router.model_deep = "m"
        result = await wg.generate_schematic(None, "test")
        assert result["status"] == "ok"
        assert result["svg"].startswith("<svg")


# ---------------------------------------------------------------------------
# Async: generate_bom
# ---------------------------------------------------------------------------

class TestGenerateBom:
    @pytest.mark.asyncio
    async def test_no_redis(self):
        wg = _make_wg_with_router()
        wg.redis = None
        result = await wg.generate_bom("proj1")
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Async: read_file / path traversal protection
# ---------------------------------------------------------------------------

class TestReadFile:
    @pytest.mark.asyncio
    async def test_invalid_project_id(self):
        wg = _make_wg()
        result = await wg.read_file("../etc", "passwd")
        assert result == ""

    @pytest.mark.asyncio
    async def test_invalid_filename(self):
        wg = _make_wg()
        result = await wg.read_file("valid_proj", "../../etc/passwd")
        assert result == ""


# ---------------------------------------------------------------------------
# Async: list_files
# ---------------------------------------------------------------------------

class TestListFiles:
    @pytest.mark.asyncio
    async def test_no_redis(self):
        wg = _make_wg()
        wg.redis = None
        result = await wg.list_files("proj1")
        assert result == []


# ---------------------------------------------------------------------------
# Async: export_project
# ---------------------------------------------------------------------------

class TestExportProject:
    @pytest.mark.asyncio
    async def test_nonexistent_project_dir(self):
        wg = _make_wg()
        wg.FILES_DIR = Path("/tmp/nonexistent_workshop_test_dir")
        result = await wg.export_project("proj1")
        assert result == ""


# ---------------------------------------------------------------------------
# set_model_router
# ---------------------------------------------------------------------------

class TestSetModelRouter:
    def test_set_router(self):
        wg = _make_wg()
        router = MagicMock()
        wg.set_model_router(router)
        assert wg.model_router is router


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_dir(self):
        wg = _make_wg()
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir) / "workshop"
            redis = AsyncMock()
            await wg.initialize(redis)
            assert wg.redis is redis
            assert wg.FILES_DIR.exists()
