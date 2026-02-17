"""
Home Assistant API Client - Kommunikation mit HA und MindHome

Features:
  - Retry-Logik mit exponentiellem Backoff (3 Versuche)
  - Detailliertes Error-Logging mit Status-Codes und Response-Body
  - Connection Pooling via shared aiohttp.ClientSession
  - Konfigurierbare Timeouts

API-Endpoints an die tatsaechlichen MindHome Add-on Routes angepasst:
  /api/system/health  -> /api/health
  /api/presence        -> /api/persons
  /api/energy/current  -> /api/energy/summary
  /api/comfort/status  -> /api/health/comfort
  /api/security/status -> /api/security/dashboard
"""

import asyncio
import logging
from typing import Any, Optional

import aiohttp

from .config import settings

logger = logging.getLogger(__name__)

# Retry-Konfiguration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # Sekunden: 1.5, 3.0, 4.5


class HomeAssistantClient:
    """Client fuer Home Assistant + MindHome REST API mit Retry und Connection Pooling."""

    def __init__(self):
        self.ha_url = settings.ha_url.rstrip("/")
        self.ha_token = settings.ha_token
        self.mindhome_url = settings.mindhome_url.rstrip("/")
        self._ha_headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }
        # Shared Session (wird lazy initialisiert)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Gibt die shared aiohttp Session zurueck (lazy init)."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        """Schliesst die HTTP Session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ----- Home Assistant API -----

    async def get_states(self) -> list[dict]:
        """Alle Entity-States von HA holen."""
        return await self._get_ha("/api/states") or []

    async def get_state(self, entity_id: str) -> Optional[dict]:
        """State einer einzelnen Entity."""
        return await self._get_ha(f"/api/states/{entity_id}")

    async def call_service(
        self, domain: str, service: str, data: Optional[dict] = None
    ) -> bool:
        """
        HA Service aufrufen (z.B. light.turn_off).

        Args:
            domain: z.B. "light", "climate", "scene"
            service: z.B. "turn_on", "turn_off", "activate"
            data: Service-Daten (entity_id, brightness, etc.)

        Returns:
            True bei Erfolg
        """
        result = await self._post_ha(
            f"/api/services/{domain}/{service}", data or {}
        )
        return result is not None

    async def fire_event(
        self, event_type: str, event_data: Optional[dict] = None
    ) -> bool:
        """
        HA Event ueber REST API feuern.

        Args:
            event_type: z.B. "mindhome_presence_mode"
            event_data: Event-Daten

        Returns:
            True bei Erfolg
        """
        result = await self._post_ha(
            f"/api/events/{event_type}", event_data or {}
        )
        return result is not None

    async def is_available(self) -> bool:
        """Prueft ob HA erreichbar ist."""
        try:
            result = await self._get_ha("/api/")
            return result is not None and "message" in (result or {})
        except Exception:
            return False

    # ----- MindHome API -----

    async def get_mindhome_status(self) -> Optional[dict]:
        """MindHome System-Status."""
        return await self._get_mindhome("/api/health")

    async def get_presence(self) -> Optional[dict]:
        """Anwesenheitsdaten von MindHome."""
        return await self._get_mindhome("/api/persons")

    async def get_energy(self) -> Optional[dict]:
        """Energie-Daten von MindHome."""
        return await self._get_mindhome("/api/energy/summary")

    async def get_comfort(self) -> Optional[dict]:
        """Komfort-Daten von MindHome."""
        return await self._get_mindhome("/api/health/comfort")

    async def get_security(self) -> Optional[dict]:
        """Sicherheits-Status von MindHome."""
        return await self._get_mindhome("/api/security/dashboard")

    async def get_patterns(self) -> Optional[dict]:
        """Erkannte Muster von MindHome."""
        return await self._get_mindhome("/api/patterns")

    async def get_health_dashboard(self) -> Optional[dict]:
        """Gesundheits-Dashboard von MindHome."""
        return await self._get_mindhome("/api/health/dashboard")

    async def get_day_phases(self) -> Optional[dict]:
        """Tagesphasen von MindHome."""
        return await self._get_mindhome("/api/day-phases")

    # ----- Interne HTTP Methoden mit Retry -----

    async def _get_ha(self, path: str) -> Any:
        """GET-Request an Home Assistant mit Retry."""
        session = await self._get_session()
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    f"{self.ha_url}{path}",
                    headers=self._ha_headers,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    # Client-Fehler: nicht retrien
                    if 400 <= resp.status < 500:
                        body = await resp.text()
                        logger.warning(
                            "HA GET %s -> %d (Client-Fehler): %s",
                            path, resp.status, body[:200],
                        )
                        return None
                    # Server-Fehler: retrien
                    body = await resp.text()
                    logger.warning(
                        "HA GET %s -> %d (Versuch %d/%d): %s",
                        path, resp.status, attempt + 1, MAX_RETRIES, body[:200],
                    )
                    last_error = f"HTTP {resp.status}"
            except aiohttp.ClientError as e:
                last_error = str(e)
                logger.warning(
                    "HA GET %s fehlgeschlagen (Versuch %d/%d): %s",
                    path, attempt + 1, MAX_RETRIES, e,
                )
            except asyncio.TimeoutError:
                last_error = "Timeout"
                logger.warning(
                    "HA GET %s Timeout (Versuch %d/%d)",
                    path, attempt + 1, MAX_RETRIES,
                )

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE * (attempt + 1)
                await asyncio.sleep(wait)

        logger.error("HA GET %s endgueltig fehlgeschlagen: %s", path, last_error)
        return None

    async def _post_ha(self, path: str, data: dict) -> Any:
        """POST-Request an Home Assistant mit Retry."""
        session = await self._get_session()
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.post(
                    f"{self.ha_url}{path}",
                    headers=self._ha_headers,
                    json=data,
                ) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
                    if 400 <= resp.status < 500:
                        body = await resp.text()
                        logger.warning(
                            "HA POST %s -> %d (Client-Fehler): %s",
                            path, resp.status, body[:200],
                        )
                        return None
                    body = await resp.text()
                    logger.warning(
                        "HA POST %s -> %d (Versuch %d/%d): %s",
                        path, resp.status, attempt + 1, MAX_RETRIES, body[:200],
                    )
                    last_error = f"HTTP {resp.status}"
            except aiohttp.ClientError as e:
                last_error = str(e)
                logger.warning(
                    "HA POST %s fehlgeschlagen (Versuch %d/%d): %s",
                    path, attempt + 1, MAX_RETRIES, e,
                )
            except asyncio.TimeoutError:
                last_error = "Timeout"
                logger.warning(
                    "HA POST %s Timeout (Versuch %d/%d)",
                    path, attempt + 1, MAX_RETRIES,
                )

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE * (attempt + 1)
                await asyncio.sleep(wait)

        logger.error("HA POST %s endgueltig fehlgeschlagen: %s", path, last_error)
        return None

    async def _get_mindhome(self, path: str) -> Any:
        """GET-Request an MindHome Add-on mit Retry und Logging."""
        session = await self._get_session()
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    f"{self.mindhome_url}{path}",
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if 400 <= resp.status < 500:
                        body = await resp.text()
                        logger.warning(
                            "MindHome GET %s -> %d (Client-Fehler): %s",
                            path, resp.status, body[:200],
                        )
                        return None
                    body = await resp.text()
                    logger.warning(
                        "MindHome GET %s -> %d (Versuch %d/%d): %s",
                        path, resp.status, attempt + 1, MAX_RETRIES, body[:200],
                    )
                    last_error = f"HTTP {resp.status}"
            except aiohttp.ClientError as e:
                last_error = str(e)
                logger.warning(
                    "MindHome GET %s fehlgeschlagen (Versuch %d/%d): %s",
                    path, attempt + 1, MAX_RETRIES, e,
                )
            except asyncio.TimeoutError:
                last_error = "Timeout"
                logger.warning(
                    "MindHome GET %s Timeout (Versuch %d/%d)",
                    path, attempt + 1, MAX_RETRIES,
                )

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE * (attempt + 1)
                await asyncio.sleep(wait)

        logger.error(
            "MindHome GET %s endgueltig fehlgeschlagen nach %d Versuchen: %s",
            path, MAX_RETRIES, last_error,
        )
        return None
