"""
Camera Manager - Kamera-Integration fuer visuelle Sicherheit.

Features:
- Snapshot von HA-Kameras abrufen
- Bild an Vision-LLM senden fuer Beschreibung
- "Wer ist an der Tuer?" -> Tuerkamera -> Vision-LLM -> Beschreibung
- Proaktive Integration bei Tuerklingel-Events
- Datenschutz: Bilder werden NICHT gespeichert

Nutzt die bestehende HA camera-Domain und das Vision-LLM aus ocr.py.
"""

import base64
import logging
from typing import Optional

from .config import yaml_config
from .ha_client import HomeAssistantClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class CameraManager:
    """Verwaltet Kamera-Zugriff und Bild-Analyse."""

    def __init__(self, ha_client: HomeAssistantClient, ollama: OllamaClient):
        self.ha = ha_client
        self.ollama = ollama

        # Konfiguration
        cam_cfg = yaml_config.get("cameras", {})
        self.enabled = cam_cfg.get("enabled", True)
        self.vision_model = cam_cfg.get("vision_model", "llava")
        # Mapping: Raum/Name -> camera entity_id
        self.camera_map: dict[str, str] = cam_cfg.get("camera_map", {})

    async def get_camera_view(self, camera_name: str = "", room: str = "") -> dict:
        """Holt einen Snapshot von einer Kamera und beschreibt ihn.

        Args:
            camera_name: Name der Kamera (z.B. "haustuer", "garage")
            room: Raum-Name als Alternative

        Returns:
            Dict mit success, message (Beschreibung), image_available
        """
        if not self.enabled:
            return {"success": False, "message": "Kamera-Integration ist deaktiviert."}

        # Kamera-Entity finden
        entity_id = await self._find_camera(camera_name or room)
        if not entity_id:
            return {"success": False, "message": f"Keine Kamera fuer '{camera_name or room}' gefunden."}

        # Snapshot holen
        image_data = await self._get_snapshot(entity_id)
        if not image_data:
            return {"success": False, "message": "Kamera-Snapshot konnte nicht abgerufen werden."}

        # Bild an Vision-LLM senden
        description = await self._analyze_image(image_data)
        if not description:
            return {
                "success": True,
                "message": "Snapshot abgerufen, aber Bild-Analyse nicht verfuegbar.",
                "image_available": True,
            }

        return {
            "success": True,
            "message": description,
            "image_available": True,
            "camera_entity": entity_id,
        }

    async def describe_doorbell(self) -> Optional[str]:
        """Holt und beschreibt das Bild der Tuerkamera bei Klingel-Event.

        Returns:
            Beschreibung oder None wenn nicht moeglich.
        """
        # Tuerkamera finden
        door_cameras = ["haustuer", "eingang", "front_door", "doorbell", "tuerklingel"]
        for name in door_cameras:
            entity_id = await self._find_camera(name)
            if entity_id:
                image_data = await self._get_snapshot(entity_id)
                if image_data:
                    return await self._analyze_image(image_data, context="doorbell")
        return None

    async def _find_camera(self, search: str) -> Optional[str]:
        """Findet eine Kamera-Entity."""
        if not search:
            return None

        search_lower = search.lower().replace(" ", "_")

        # 1. Konfiguriertes Mapping
        for name, entity_id in self.camera_map.items():
            if name.lower() == search_lower:
                return entity_id

        # 2. HA-Entity Suche
        states = await self.ha.get_states()
        if not states:
            return None

        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("camera."):
                continue
            name = entity_id.split(".", 1)[1]
            friendly = state.get("attributes", {}).get("friendly_name", "")

            if search_lower in name.lower() or search_lower in friendly.lower():
                return entity_id

        return None

    async def _get_snapshot(self, entity_id: str) -> Optional[bytes]:
        """Holt einen Snapshot von einer Kamera via HA API."""
        try:
            image_bytes = await self.ha.get_camera_snapshot(entity_id)
            return image_bytes
        except Exception as e:
            logger.error("Kamera-Snapshot fehlgeschlagen fuer %s: %s", entity_id, e)
            return None

    async def _analyze_image(self, image_data: bytes, context: str = "general") -> Optional[str]:
        """Analysiert ein Bild mit dem Vision-LLM."""
        try:
            image_b64 = base64.b64encode(image_data).decode("utf-8")

            if context == "doorbell":
                prompt = (
                    "Beschreibe kurz auf Deutsch was du auf diesem Tuerkamera-Bild siehst. "
                    "Fokussiere auf: Wer steht vor der Tuer? Pakete? Fahrzeuge? "
                    "Maximal 2 Saetze."
                )
            else:
                prompt = (
                    "Beschreibe kurz auf Deutsch was du auf diesem Kamera-Bild siehst. "
                    "Fokussiere auf Personen, Fahrzeuge, auffaellige Objekte. "
                    "Maximal 2 Saetze."
                )

            response = await self.ollama.chat(
                messages=[{"role": "user", "content": prompt, "images": [image_b64]}],
                model=self.vision_model,
                temperature=0.3,
                max_tokens=150,
            )

            if "error" not in response:
                return response.get("message", {}).get("content", "")

        except Exception as e:
            logger.error("Vision-LLM Analyse fehlgeschlagen: %s", e)

        return None
