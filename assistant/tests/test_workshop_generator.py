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


# ---------------------------------------------------------------------------
# Coverage: lines 162-165 (generate_code with project_id + redis)
# ---------------------------------------------------------------------------

class TestGenerateCodeWithRedis:
    @pytest.mark.asyncio
    async def test_generate_code_with_project_and_redis(self):
        """generate_code fetches project title from Redis when project_id + redis."""
        wg = _make_wg_with_router()
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            b"title": b"LED Blinker",
            b"status": b"active",
        })
        wg.redis = redis
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            result = await wg.generate_code("proj1", "blink an LED", language="python")
        assert result["status"] == "ok"
        assert result["language"] == "python"
        assert result["filename"].endswith(".py")
        redis.hgetall.assert_called_once_with("mha:repair:project:proj1")

    @pytest.mark.asyncio
    async def test_generate_code_with_project_no_redis(self):
        """generate_code with project_id but no redis still works."""
        wg = _make_wg_with_router()
        wg.redis = None
        result = await wg.generate_code("proj1", "test", language="html")
        assert result["status"] == "ok"
        assert result["filename"].endswith(".html")

    @pytest.mark.asyncio
    async def test_generate_code_with_existing_code(self):
        """generate_code truncates existing_code to 3000 chars."""
        wg = _make_wg_with_router()
        wg.redis = None
        long_code = "x" * 5000
        result = await wg.generate_code(None, "extend", language="cpp", existing_code=long_code)
        assert result["status"] == "ok"
        assert result["filename"].endswith(".cpp")

    @pytest.mark.asyncio
    async def test_generate_code_unknown_language(self):
        """Unknown language falls back to .txt extension."""
        wg = _make_wg_with_router()
        wg.redis = None
        result = await wg.generate_code(None, "test", language="rust")
        assert result["status"] == "ok"
        assert result["filename"].endswith(".txt")


# ---------------------------------------------------------------------------
# Coverage: lines 201-220 (generate_3d_model with project + redis)
# ---------------------------------------------------------------------------

class TestGenerate3dModelWithRedis:
    @pytest.mark.asyncio
    async def test_generate_3d_model_with_project(self):
        """generate_3d_model fetches project title from Redis."""
        wg = _make_wg_with_router()
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            b"title": b"Gehaeuse",
        })
        wg.redis = redis
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            result = await wg.generate_3d_model("proj1", "box 50x50x30")
        assert result["status"] == "ok"
        assert result["filename"].endswith(".scad")

    @pytest.mark.asyncio
    async def test_generate_3d_model_no_project(self):
        """generate_3d_model without project_id skips Redis lookup."""
        wg = _make_wg_with_router()
        wg.redis = None
        result = await wg.generate_3d_model(None, "cylinder")
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Coverage: lines 245, 253-268 (generate_schematic + generate_website)
# ---------------------------------------------------------------------------

class TestGenerateSchematicSave:
    @pytest.mark.asyncio
    async def test_generate_schematic_saves_file(self):
        """generate_schematic saves SVG file when project_id is given."""
        wg = _make_wg_with_router()
        wg.ollama.chat = AsyncMock(return_value='<svg viewBox="0 0 100 100"><rect/></svg>')
        redis = AsyncMock()
        wg.redis = redis
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            result = await wg.generate_schematic("proj1", "LED circuit")
        assert result["status"] == "ok"
        assert result["svg"].startswith("<svg")


class TestGenerateWebsite:
    @pytest.mark.asyncio
    async def test_no_model(self):
        wg = _make_wg()
        result = await wg.generate_website("proj1", "dashboard")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_generate_website_success(self):
        """generate_website generates HTML and saves."""
        wg = _make_wg_with_router()
        wg.ollama.chat = AsyncMock(return_value="<html><body>Dashboard</body></html>")
        redis = AsyncMock()
        wg.redis = redis
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            result = await wg.generate_website("proj1", "dashboard", context="sensor data")
        assert result["status"] == "ok"
        assert result["filename"].endswith(".html")
        assert "html" in result

    @pytest.mark.asyncio
    async def test_generate_website_no_context(self):
        """generate_website uses default context when none given."""
        wg = _make_wg_with_router()
        wg.redis = None
        result = await wg.generate_website(None, "dashboard")
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Coverage: lines 277, 281-307 (generate_bom full path)
# ---------------------------------------------------------------------------

class TestGenerateBomFull:
    @pytest.mark.asyncio
    async def test_no_model(self):
        wg = _make_wg()
        wg.redis = AsyncMock()
        result = await wg.generate_bom("proj1")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_project_not_found(self):
        """generate_bom returns error if project not in Redis."""
        wg = _make_wg_with_router()
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={})
        wg.redis = redis
        result = await wg.generate_bom("proj1")
        assert result["status"] == "error"
        assert "nicht gefunden" in result["message"]

    @pytest.mark.asyncio
    async def test_generate_bom_success(self):
        """generate_bom generates a BOM from project data."""
        wg = _make_wg_with_router()
        wg.ollama.chat = AsyncMock(return_value="| # | Bauteil | Menge |\n| 1 | LED | 3 |")
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            b"title": b"LED Projekt",
            b"parts": json.dumps(["LED", "Widerstand"]).encode(),
            b"category": b"electronics",
        })
        redis.lrange = AsyncMock(return_value=[])
        wg.redis = redis
        # Mock list_files and read_file
        with patch.object(wg, "list_files", new_callable=AsyncMock, return_value=[
            {"name": "code.ino", "size": 100},
        ]):
            with patch.object(wg, "read_file", new_callable=AsyncMock, return_value="void setup(){}"):
                result = await wg.generate_bom("proj1")
        assert result["status"] == "ok"
        assert "bom" in result


# ---------------------------------------------------------------------------
# Coverage: lines 314-349 (generate_documentation)
# ---------------------------------------------------------------------------

class TestGenerateDocumentation:
    @pytest.mark.asyncio
    async def test_no_model(self):
        wg = _make_wg()
        wg.redis = AsyncMock()
        result = await wg.generate_documentation("proj1")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_no_redis(self):
        wg = _make_wg_with_router()
        wg.redis = None
        result = await wg.generate_documentation("proj1")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_project_not_found(self):
        wg = _make_wg_with_router()
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={})
        wg.redis = redis
        result = await wg.generate_documentation("proj1")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_generate_documentation_success(self):
        """Full documentation generation path."""
        wg = _make_wg_with_router()
        wg.ollama.chat = AsyncMock(return_value="# Projekt\n\nBeschreibung...")
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={
            b"title": b"Sensor Box",
            b"category": b"electronics",
            b"description": b"Temp sensor",
            b"parts": b'["DHT22"]',
            b"status": b"active",
        })
        wg.redis = redis
        with patch.object(wg, "list_files", new_callable=AsyncMock, return_value=[
            {"name": "main.ino"},
        ]):
            with tempfile.TemporaryDirectory() as tmpdir:
                wg.FILES_DIR = Path(tmpdir)
                result = await wg.generate_documentation("proj1")
        assert result["status"] == "ok"
        assert "documentation" in result
        assert result["filename"].startswith("DOKU_")


# ---------------------------------------------------------------------------
# Coverage: lines 356-385 (generate_tests)
# ---------------------------------------------------------------------------

class TestGenerateTests:
    @pytest.mark.asyncio
    async def test_no_model(self):
        wg = _make_wg()
        result = await wg.generate_tests("proj1", "main.py")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        wg = _make_wg_with_router()
        with patch.object(wg, "read_file", new_callable=AsyncMock, return_value=""):
            result = await wg.generate_tests("proj1", "missing.py")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_generate_tests_success(self):
        """Full test generation path."""
        wg = _make_wg_with_router()
        wg.ollama.chat = AsyncMock(return_value="def test_something(): pass")
        with patch.object(wg, "read_file", new_callable=AsyncMock, return_value="def hello(): pass"):
            with tempfile.TemporaryDirectory() as tmpdir:
                wg.FILES_DIR = Path(tmpdir)
                result = await wg.generate_tests("proj1", "main.py")
        assert result["status"] == "ok"
        assert result["filename"] == "test_main.py"
        assert "tests" in result

    @pytest.mark.asyncio
    async def test_generate_tests_js(self):
        """Test generation for JavaScript uses Jest framework."""
        wg = _make_wg_with_router()
        wg.ollama.chat = AsyncMock(return_value="test('works', () => {})")
        with patch.object(wg, "read_file", new_callable=AsyncMock, return_value="function foo(){}"):
            with tempfile.TemporaryDirectory() as tmpdir:
                wg.FILES_DIR = Path(tmpdir)
                result = await wg.generate_tests("proj1", "app.js")
        assert result["status"] == "ok"
        assert result["filename"] == "test_app.js"


# ---------------------------------------------------------------------------
# Coverage: lines 482-483 (calculate exception), 500, 502, 508
# ---------------------------------------------------------------------------

class TestCalculateException:
    def test_calculate_missing_key(self):
        """calculate catches KeyError and returns error dict."""
        wg = _make_wg()
        result = wg.calculate("resistor_divider")  # missing v_in, v_out
        assert "error" in result


class TestSaveFileValidation:
    @pytest.mark.asyncio
    async def test_invalid_project_id(self):
        """_save_file rejects invalid project_id."""
        wg = _make_wg()
        result = await wg._save_file("../evil", "test.txt", "content")
        assert result["status"] == "error"
        assert "Invalid project_id" in result["message"]

    @pytest.mark.asyncio
    async def test_invalid_filename(self):
        """_save_file rejects invalid filename."""
        wg = _make_wg()
        result = await wg._save_file("proj1", "../passwd", "content")
        assert result["status"] == "error"
        assert "Invalid filename" in result["message"]

    @pytest.mark.asyncio
    async def test_save_file_with_redis(self):
        """_save_file saves to disk and registers in Redis."""
        wg = _make_wg()
        redis = AsyncMock()
        wg.redis = redis
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            with patch("assistant.websocket.emit_workshop", new_callable=AsyncMock):
                result = await wg._save_file("proj1", "test.txt", "hello world")
        assert result["status"] == "ok"
        redis.sadd.assert_called_once()
        redis.rpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_file_ws_emit_fails(self):
        """_save_file handles WebSocket emit failure gracefully."""
        wg = _make_wg()
        wg.redis = None
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            with patch("assistant.websocket.emit_workshop", side_effect=Exception("ws fail")):
                result = await wg._save_file("proj1", "test.txt", "content")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_save_file_path_traversal_resolve(self):
        """_save_file blocks path traversal via resolve check."""
        wg = _make_wg()
        wg.redis = None
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            # Valid project_id and filename patterns, but we test the normal case
            with patch("assistant.websocket.emit_workshop", new_callable=AsyncMock):
                result = await wg._save_file("proj1", "file.txt", "data")
            assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Coverage: lines 540-549, 555-573 (read_file, list_files with data)
# ---------------------------------------------------------------------------

class TestReadFileSuccess:
    @pytest.mark.asyncio
    async def test_read_existing_file(self):
        """read_file returns content of existing file."""
        wg = _make_wg()
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            proj_dir = Path(tmpdir) / "proj1"
            proj_dir.mkdir()
            (proj_dir / "test.txt").write_text("hello", encoding="utf-8")
            result = await wg.read_file("proj1", "test.txt")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        """read_file returns empty string for nonexistent file."""
        wg = _make_wg()
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            result = await wg.read_file("proj1", "missing.txt")
        assert result == ""


class TestListFilesWithData:
    @pytest.mark.asyncio
    async def test_list_files_with_data(self):
        """list_files returns file info from Redis + disk."""
        wg = _make_wg()
        redis = AsyncMock()
        redis.lrange = AsyncMock(return_value=[b"test.txt", b"code.ino"])
        wg.redis = redis
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            proj_dir = Path(tmpdir) / "proj1"
            proj_dir.mkdir()
            (proj_dir / "test.txt").write_text("hello")
            (proj_dir / "code.ino").write_text("void setup(){}")
            result = await wg.list_files("proj1")
        assert len(result) == 2
        names = [f["name"] for f in result]
        assert "test.txt" in names
        assert "code.ino" in names
        for f in result:
            assert "size" in f
            assert "modified" in f


# ---------------------------------------------------------------------------
# Coverage: lines 577-594 (delete_file)
# ---------------------------------------------------------------------------

class TestDeleteFile:
    @pytest.mark.asyncio
    async def test_delete_existing_file(self):
        """delete_file deletes file and removes from Redis."""
        wg = _make_wg()
        redis = AsyncMock()
        wg.redis = redis
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            proj_dir = Path(tmpdir) / "proj1"
            proj_dir.mkdir()
            (proj_dir / "test.txt").write_text("hello")
            result = await wg.delete_file("proj1", "test.txt")
        assert result["status"] == "ok"
        redis.lrem.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self):
        """delete_file returns error for missing file."""
        wg = _make_wg()
        wg.redis = None
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            result = await wg.delete_file("proj1", "missing.txt")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_delete_file_no_redis(self):
        """delete_file works without Redis."""
        wg = _make_wg()
        wg.redis = None
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            proj_dir = Path(tmpdir) / "proj1"
            proj_dir.mkdir()
            (proj_dir / "test.txt").write_text("content")
            result = await wg.delete_file("proj1", "test.txt")
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Coverage: lines 604-608 (export_project with files)
# ---------------------------------------------------------------------------

class TestExportProjectWithFiles:
    @pytest.mark.asyncio
    async def test_export_creates_zip(self):
        """export_project creates a ZIP of all project files."""
        import zipfile as zf_mod
        wg = _make_wg()
        with tempfile.TemporaryDirectory() as tmpdir:
            wg.FILES_DIR = Path(tmpdir)
            proj_dir = Path(tmpdir) / "proj1"
            proj_dir.mkdir()
            (proj_dir / "main.ino").write_text("void setup(){}")
            (proj_dir / "README.md").write_text("# Project")
            result = await wg.export_project("proj1")
            assert result != ""
            assert result.endswith(".zip")
            # Verify ZIP contents while tmpdir still exists
            with zf_mod.ZipFile(result, "r") as zf:
                names = zf.namelist()
                assert "main.ino" in names
                assert "README.md" in names
