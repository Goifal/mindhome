"""
MindHome Workshop-Generator — Code/3D/SVG/Website/BOM/Doku/Tests/Berechnungen.

Generiert Artefakte fuer Werkstatt-Projekte:
- Code-Generation (Arduino, Python, C++, HTML, JS, YAML, MicroPython)
- OpenSCAD 3D-Modelle
- SVG-Schaltplaene
- Responsive Websites
- BOM (Bill of Materials)
- Projekt-Dokumentation
- Test-Generation
- Deterministische Berechnungen (Ohm, LED, Widerstand, Draht, etc.)
- File-Management mit Versionierung
- Projekt-Export als ZIP
"""

import json
import logging
import math
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================
# Physik-Referenz-Datenbanken (kein LLM noetig)
# ============================================================

RESISTOR_E24 = [
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0,
    2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3,
    4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
]

WIRE_GAUGE_MM2 = {
    0.5: 3, 0.75: 5, 1.0: 7.5, 1.5: 10,
    2.5: 16, 4.0: 25, 6.0: 32, 10.0: 50,
}

SCREW_TORQUES_NM = {
    "M3": 1.2, "M4": 2.5, "M5": 5.0, "M6": 8.5,
    "M8": 22, "M10": 44, "M12": 77,
}

MATERIAL_PROPERTIES = {
    "pla": {"temp_max": 60, "strength_mpa": 50, "density_g_cm3": 1.24},
    "petg": {"temp_max": 80, "strength_mpa": 55, "density_g_cm3": 1.27},
    "abs": {"temp_max": 100, "strength_mpa": 40, "density_g_cm3": 1.04},
    "tpu": {"temp_max": 80, "strength_mpa": 30, "density_g_cm3": 1.21},
    "asa": {"temp_max": 95, "strength_mpa": 55, "density_g_cm3": 1.07},
}

ESP32_PINOUT = {
    "adc": [32, 33, 34, 35, 36, 39],
    "dac": [25, 26],
    "i2c_sda": 21, "i2c_scl": 22,
    "spi_mosi": 23, "spi_miso": 19, "spi_clk": 18,
    "pwm": list(range(2, 34)),
    "touch": [4, 2, 15, 13, 12, 14, 27, 33, 32],
}

UNIT_CONVERSIONS = {
    ("mm", "inch"): lambda x: x / 25.4,
    ("inch", "mm"): lambda x: x * 25.4,
    ("celsius", "fahrenheit"): lambda x: x * 9 / 5 + 32,
    ("fahrenheit", "celsius"): lambda x: (x - 32) * 5 / 9,
    ("bar", "psi"): lambda x: x * 14.5038,
    ("psi", "bar"): lambda x: x / 14.5038,
    ("kg", "lbs"): lambda x: x * 2.20462,
    ("lbs", "kg"): lambda x: x / 2.20462,
}


# ============================================================
# LLM-Prompts
# ============================================================

CODE_GEN_PROMPT = """Du bist ein erfahrener Embedded-/Software-Entwickler.
Generiere VOLLSTAENDIGEN, KOMPILIERBAREN Code. Keine Platzhalter. Keine "...".
Sprache: {language}
Projekt: {project_title}
Bestehender Code: {existing_code}
Anforderung: {requirement}

REGELN:
- Vollstaendig: Alle Imports, alle Funktionen, main() wenn noetig
- Kommentare auf Deutsch
- Bei Arduino/ESP32: setup() + loop() + alle Variablen
- Bei Python: if __name__ == "__main__" wenn standalone
- Bei HTML: Vollstaendiges Dokument mit DOCTYPE"""

OPENSCAD_PROMPT = """Du bist ein CAD-Ingenieur. Generiere VOLLSTAENDIGEN OpenSCAD Code.
Masse in mm. Verwende Module fuer Wiederholungen.
Projekt: {project_title}
Anforderung: {requirement}

REGELN:
- Immer $fn=60 fuer runde Formen
- Toleranzen: Steckverbindungen +0.2mm, Pressfit -0.1mm
- Wandstaerke min. 1.2mm fuer FDM-Druck
- Kommentare auf Deutsch"""

SVG_PROMPT = """Du bist ein Elektrotechnik-Ingenieur. Generiere einen SVG-Schaltplan.
REGELN:
- Sauberes SVG mit viewBox
- Bauteile als Symbole (Rechteck=Widerstand, Kreis mit Pfeil=LED, etc.)
- Verbindungslinien als <line> oder <path>
- Beschriftungen mit <text>
- Farbschema: Hintergrund=#1a1a2e, Linien=#00d4ff, Text=#e0e0e0
Anforderung: {requirement}"""

WEBSITE_PROMPT = """Du bist ein Fullstack-Webentwickler. Generiere eine VOLLSTAENDIGE,
FUNKTIONALE Single-Page HTML/CSS/JS Datei.
DESIGN: Modern, responsive, CSS Grid/Flexbox. Dunkles Theme (#040810, #00d4ff).
Anforderung: {requirement}
Kontext: {context}
REGELN: Alles in EINER Datei. Kein Framework noetig. Vanilla JS."""


# ============================================================
# Hauptklasse
# ============================================================

class WorkshopGenerator:
    """Code-/3D-/Schaltplan-Generator fuer die Werkstatt."""

    FILES_DIR = Path("/app/data/workshop/files")

    def __init__(self, ollama_client):
        self.ollama = ollama_client
        self.redis = None
        self.model_router = None

    async def initialize(self, redis_client):
        """Initialisiert mit Redis und erstellt Verzeichnisse."""
        self.redis = redis_client
        self.FILES_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("WorkshopGenerator initialisiert (FILES_DIR=%s)", self.FILES_DIR)

    def set_model_router(self, router):
        """Setzt den ModelRouter."""
        self.model_router = router

    # ── Code-Generation ──────────────────────────────────────

    async def generate_code(self, project_id, requirement,
                            language="arduino", existing_code="",
                            model=None) -> dict:
        """Generiert Code in der angegebenen Sprache."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return {"status": "error", "message": "Kein LLM-Modell verfuegbar"}

        project_title = ""
        if project_id and self.redis:
            proj = await self.redis.hgetall(
                f"mha:repair:project:{project_id}")
            project_title = proj.get("title", "")

        prompt = CODE_GEN_PROMPT.format(
            language=language, project_title=project_title or "Unbenannt",
            existing_code=(existing_code[:3000]
                           if existing_code else "Kein bestehender Code"),
            requirement=requirement,
        )
        messages = [{"role": "system", "content": prompt}]
        code = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.2, max_tokens=4096)

        # Datei speichern
        ext = {
            "arduino": ".ino", "python": ".py", "cpp": ".cpp",
            "html": ".html", "javascript": ".js", "yaml": ".yaml",
            "micropython": ".py",
        }.get(language, ".txt")
        filename = f"code_{language}_{datetime.now().strftime('%H%M%S')}{ext}"
        if project_id:
            await self._save_file(project_id, filename, code)

        return {"status": "ok", "code": code,
                "filename": filename, "language": language}

    # ── 3D-Modell (OpenSCAD) ─────────────────────────────────

    async def generate_3d_model(self, project_id, requirement,
                                model=None) -> dict:
        """Generiert ein OpenSCAD 3D-Modell."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return {"status": "error", "message": "Kein LLM-Modell verfuegbar"}

        project_title = ""
        if project_id and self.redis:
            proj = await self.redis.hgetall(
                f"mha:repair:project:{project_id}")
            project_title = proj.get("title", "")

        prompt = OPENSCAD_PROMPT.format(
            project_title=project_title or "Unbenannt",
            requirement=requirement,
        )
        messages = [{"role": "system", "content": prompt}]
        scad_code = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.2, max_tokens=4096)

        filename = f"model_{datetime.now().strftime('%H%M%S')}.scad"
        if project_id:
            await self._save_file(project_id, filename, scad_code)
        return {"status": "ok", "code": scad_code, "filename": filename}

    # ── SVG-Schaltplan ───────────────────────────────────────

    async def generate_schematic(self, project_id, requirement,
                                 model=None) -> dict:
        """Generiert einen SVG-Schaltplan."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return {"status": "error", "message": "Kein LLM-Modell verfuegbar"}

        prompt = SVG_PROMPT.format(requirement=requirement)
        messages = [{"role": "system", "content": prompt}]
        svg = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.2, max_tokens=4096)

        # SVG extrahieren (falls in Markdown-Block)
        svg_match = re.search(r'<svg[\s\S]*?</svg>', svg)
        if svg_match:
            svg = svg_match.group(0)

        filename = f"schematic_{datetime.now().strftime('%H%M%S')}.svg"
        if project_id:
            await self._save_file(project_id, filename, svg)
        return {"status": "ok", "svg": svg, "filename": filename}

    # ── Website-Generation ───────────────────────────────────

    async def generate_website(self, project_id, requirement,
                               context="", model=None) -> dict:
        """Generiert eine Single-Page Website."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return {"status": "error", "message": "Kein LLM-Modell verfuegbar"}

        prompt = WEBSITE_PROMPT.format(
            requirement=requirement, context=context or "Werkstatt-Projekt")
        messages = [{"role": "system", "content": prompt}]
        html = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.3, max_tokens=8192)

        filename = f"site_{datetime.now().strftime('%H%M%S')}.html"
        if project_id:
            await self._save_file(project_id, filename, html)
        return {"status": "ok", "html": html, "filename": filename}

    # ── BOM-Generator ────────────────────────────────────────

    async def generate_bom(self, project_id, model=None) -> dict:
        """Generiert eine Bill of Materials."""
        model = model or (self.model_router.model_smart
                          if self.model_router else None)
        if not model:
            return {"status": "error", "message": "Kein LLM-Modell verfuegbar"}
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfuegbar"}

        project = await self.redis.hgetall(
            f"mha:repair:project:{project_id}")
        if not project:
            return {"status": "error", "message": "Projekt nicht gefunden"}

        parts = json.loads(project.get("parts", "[]"))
        files = await self.list_files(project_id)
        file_contents = {}
        for f in files[:5]:
            content = await self.read_file(project_id, f["name"])
            if content:
                file_contents[f["name"]] = content[:1500]

        prompt = f"""Erstelle eine vollstaendige BOM (Bill of Materials) fuer dieses Projekt.
Projekt: {project.get('title', '')}
Bekannte Teile: {json.dumps(parts, ensure_ascii=False)}
Projekt-Dateien: {json.dumps(file_contents, ensure_ascii=False)}

Format als Markdown-Tabelle:
| # | Bauteil | Menge | Spezifikation | Geschaetzter Preis | Bezugsquelle |
Ergaenze fehlende Teile die aus dem Code/Schaltplan ersichtlich sind."""
        messages = [{"role": "system", "content": prompt}]
        bom = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.3, max_tokens=2048)
        return {"status": "ok", "bom": bom}

    # ── Dokumentation ────────────────────────────────────────

    async def generate_documentation(self, project_id,
                                     model=None) -> dict:
        """Generiert Projekt-Dokumentation."""
        model = model or (self.model_router.model_smart
                          if self.model_router else None)
        if not model:
            return {"status": "error", "message": "Kein LLM-Modell verfuegbar"}
        if not self.redis:
            return {"status": "error", "message": "Redis nicht verfuegbar"}

        project = await self.redis.hgetall(
            f"mha:repair:project:{project_id}")
        if not project:
            return {"status": "error", "message": "Projekt nicht gefunden"}

        files = await self.list_files(project_id)

        prompt = f"""Erstelle eine Projekt-Dokumentation (Markdown).
Projekt: {project.get('title', '')} ({project.get('category', '')})
Beschreibung: {project.get('description', '')}
Teile: {project.get('parts', '[]')}
Dateien: {[f['name'] for f in files]}
Status: {project.get('status', '')}

Struktur: Uebersicht, Materialien, Schaltung/Aufbau, Software, Montage, Tests, Fazit."""
        messages = [{"role": "system", "content": prompt}]
        doc = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.4, max_tokens=4096)

        title_slug = project.get("title", "projekt").replace(" ", "_")
        filename = f"DOKU_{title_slug}.md"
        await self._save_file(project_id, filename, doc)
        return {"status": "ok", "documentation": doc, "filename": filename}

    # ── Test-Generation ──────────────────────────────────────

    async def generate_tests(self, project_id, filename,
                             model=None) -> dict:
        """Generiert Tests fuer eine Projekt-Datei."""
        model = model or (self.model_router.model_deep
                          if self.model_router else None)
        if not model:
            return {"status": "error", "message": "Kein LLM-Modell verfuegbar"}

        code = await self.read_file(project_id, filename)
        if not code:
            return {"status": "error", "message": "Datei nicht gefunden"}

        ext = Path(filename).suffix
        test_frameworks = {
            ".py": "pytest", ".ino": "Arduino Serial Test",
            ".js": "Jest", ".cpp": "Google Test",
            ".html": "Browser Console Test",
        }
        framework = test_frameworks.get(ext, "generic")

        prompt = f"""Generiere Tests fuer diesen Code.
Framework: {framework}
Code:
{code[:4000]}
REGELN: Vollstaendige, ausfuehrbare Tests. Edge Cases abdecken."""
        messages = [{"role": "system", "content": prompt}]
        tests = await self.ollama.chat(
            model=model, messages=messages,
            temperature=0.2, max_tokens=4096)

        test_filename = f"test_{filename}"
        await self._save_file(project_id, test_filename, tests)
        return {"status": "ok", "tests": tests, "filename": test_filename}

    # ── Berechnungen (KEIN LLM) ──────────────────────────────

    def calculate(self, calc_type, **params) -> dict:
        """Deterministische Berechnungen ohne LLM."""
        try:
            if calc_type == "resistor_divider":
                v_in = params["v_in"]
                v_out = params["v_out"]
                r2 = params.get("r2", 10000)
                r1 = r2 * (v_in / v_out - 1)
                r1_e24 = self._nearest_e24(r1)
                v_out_real = v_in * r2 / (r1_e24 + r2)
                return {
                    "r1": r1_e24, "r2": r2,
                    "v_out_real": round(v_out_real, 3),
                    "error_pct": round(
                        abs(v_out - v_out_real) / v_out * 100, 2),
                }

            elif calc_type == "led_resistor":
                v_supply = params["v_supply"]
                v_led = params.get("v_led", 2.0)
                i_ma = params.get("i_ma", 20)
                r = (v_supply - v_led) / (i_ma / 1000)
                r_e24 = self._nearest_e24(r)
                power_mw = (v_supply - v_led) ** 2 / r_e24 * 1000
                return {"resistor_ohm": r_e24,
                        "power_mw": round(power_mw, 1)}

            elif calc_type == "wire_gauge":
                current_a = params["current_a"]
                for mm2, max_a in sorted(WIRE_GAUGE_MM2.items()):
                    if max_a >= current_a:
                        return {"recommended_mm2": mm2,
                                "max_current_a": max_a}
                return {"error": "Strom zu hoch fuer Standard-Kabelquerschnitte"}

            elif calc_type == "ohms_law":
                v = params.get("v")
                i = params.get("i")
                r = params.get("r")
                if v and i:
                    return {"r": round(v / i, 3), "p": round(v * i, 3)}
                if v and r:
                    return {"i": round(v / r, 6), "p": round(v ** 2 / r, 3)}
                if i and r:
                    return {"v": round(i * r, 3), "p": round(i ** 2 * r, 3)}
                return {"error": "Mindestens 2 von 3 Werten (v, i, r) noetig"}

            elif calc_type == "3d_print_weight":
                volume_cm3 = params["volume_cm3"]
                material = params.get("material", "pla")
                infill = params.get("infill_pct", 20) / 100
                props = MATERIAL_PROPERTIES.get(
                    material, MATERIAL_PROPERTIES["pla"])
                weight = volume_cm3 * props["density_g_cm3"] * infill
                return {"weight_g": round(weight, 1),
                        "material": material,
                        "infill_pct": infill * 100}

            elif calc_type == "screw_torque":
                screw = params["screw_size"].upper()
                torque = SCREW_TORQUES_NM.get(screw)
                if torque is None:
                    return {"error": f"Schraubengroesse '{screw}' nicht bekannt. "
                            f"Verfuegbar: {', '.join(SCREW_TORQUES_NM.keys())}"}
                return {"torque_nm": torque}

            elif calc_type == "convert":
                value = params["value"]
                from_unit = params["from_unit"].lower()
                to_unit = params["to_unit"].lower()
                converter = UNIT_CONVERSIONS.get((from_unit, to_unit))
                if converter:
                    return {"result": round(converter(value), 4),
                            "from": from_unit, "to": to_unit}
                return {"error": f"Konvertierung {from_unit} -> {to_unit} "
                        "nicht unterstuetzt"}

            elif calc_type == "power_supply":
                components = params.get("components", [])
                total_ma = sum(
                    c.get("current_ma", 0) * c.get("quantity", 1)
                    for c in components)
                safety_factor = 1.25
                recommended_ma = total_ma * safety_factor
                voltage = params.get("voltage", 5)
                return {
                    "total_ma": total_ma,
                    "recommended_ma": round(recommended_ma),
                    "recommended_w": round(
                        voltage * recommended_ma / 1000, 1),
                }

            return {"error": f"Unbekannter Berechnungstyp: {calc_type}"}
        except Exception as e:
            return {"error": str(e)}

    def _nearest_e24(self, value) -> float:
        """Findet den naechsten E24-Widerstandswert."""
        if value <= 0:
            return RESISTOR_E24[0]
        decade = 10 ** int(math.log10(value))
        normalized = value / decade
        closest = min(RESISTOR_E24, key=lambda x: abs(x - normalized))
        return closest * decade

    # ── File-Management ──────────────────────────────────────

    async def _save_file(self, project_id, filename, content) -> dict:
        """Speichert Datei auf Disk + Referenz in Redis."""
        project_dir = self.FILES_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        filepath = project_dir / filename
        filepath.write_text(content, encoding="utf-8")

        # Redis: Datei-Liste und Versionierung
        if self.redis:
            await self.redis.rpush(
                f"mha:repair:files:{project_id}", filename)
            await self.redis.rpush(
                f"mha:repair:versions:{project_id}:{filename}",
                json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "size": len(content),
                }))

        # WebSocket Event
        try:
            from .websocket import emit_workshop
            await emit_workshop("file_created", {
                "project_id": project_id, "filename": filename,
            })
        except Exception:
            pass

        return {"status": "ok", "path": str(filepath)}

    async def read_file(self, project_id, filename) -> str:
        """Liest eine Projekt-Datei."""
        filepath = self.FILES_DIR / project_id / filename
        if (filepath.exists()
                and filepath.resolve().is_relative_to(
                    self.FILES_DIR.resolve())):
            return filepath.read_text(encoding="utf-8")
        return ""

    async def list_files(self, project_id) -> list:
        """Listet Dateien eines Projekts."""
        if not self.redis:
            return []
        filenames = await self.redis.lrange(
            f"mha:repair:files:{project_id}", 0, -1)
        result = []
        for fn in filenames:
            filepath = self.FILES_DIR / project_id / fn
            if filepath.exists():
                result.append({
                    "name": fn,
                    "size": filepath.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        filepath.stat().st_mtime).isoformat(),
                })
        return result

    async def delete_file(self, project_id, filename) -> dict:
        """Loescht eine Projekt-Datei."""
        filepath = self.FILES_DIR / project_id / filename
        if (filepath.exists()
                and filepath.resolve().is_relative_to(
                    self.FILES_DIR.resolve())):
            filepath.unlink()
            if self.redis:
                await self.redis.lrem(
                    f"mha:repair:files:{project_id}", 0, filename)
            return {"status": "ok"}
        return {"status": "error", "message": "Datei nicht gefunden"}

    async def export_project(self, project_id) -> str:
        """Exportiert alle Projekt-Dateien als ZIP."""
        project_dir = self.FILES_DIR / project_id
        if not project_dir.exists():
            return ""
        zip_path = self.FILES_DIR / f"{project_id}_export.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in project_dir.iterdir():
                if f.is_file():
                    zf.write(f, f.name)
        return str(zip_path)
