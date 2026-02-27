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
import time
import traceback
from typing import Any, Optional
from urllib.parse import quote, urlencode

import aiohttp

from .circuit_breaker import ha_breaker
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
        # F-034: Lock im __init__ erstellen statt lazy (Race Condition bei gleichzeitigem Zugriff)
        self._session_lock: asyncio.Lock = asyncio.Lock()
        # States-Cache: vermeidet N+1 Queries innerhalb kurzer Zeitfenster
        self._states_cache: Optional[list[dict]] = None
        self._states_cache_ts: float = 0.0
        self._STATES_CACHE_TTL = 5.0  # Sekunden (von 2s erhoeht — HA-States aendern sich selten innerhalb 5s)

    def _get_lock(self) -> asyncio.Lock:
        """Gibt den Session-Lock zurueck."""
        return self._session_lock

    async def _get_session(self) -> aiohttp.ClientSession:
        """Gibt die shared aiohttp Session zurueck (thread-safe lazy init)."""
        async with self._get_lock():
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=20)
                self._session = aiohttp.ClientSession(timeout=timeout)
            return self._session

    async def close(self) -> None:
        """Schliesst die HTTP Session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ----- Home Assistant API -----

    async def get_states(self) -> list[dict]:
        """Alle Entity-States von HA holen (mit kurzem Cache gegen N+1 Queries)."""
        now = time.monotonic()
        if self._states_cache is not None and (now - self._states_cache_ts) < self._STATES_CACHE_TTL:
            return self._states_cache
        result = await self._get_ha("/api/states") or []
        if result:  # Nur nicht-leere Ergebnisse cachen
            self._states_cache = result
            self._states_cache_ts = now
        return result

    async def get_state(self, entity_id: str) -> Optional[dict]:
        """State einer einzelnen Entity."""
        return await self._get_ha(f"/api/states/{entity_id}")

    async def api_get(self, path: str) -> Any:
        """Generischer GET auf die HA REST API (z.B. /api/shopping_list)."""
        return await self._get_ha(path)

    async def get_camera_snapshot(self, entity_id: str) -> Optional[bytes]:
        """Holt einen Kamera-Snapshot als Bild-Bytes.

        Args:
            entity_id: Kamera-Entity (z.B. camera.haustuer)

        Returns:
            Bild-Bytes (JPEG) oder None
        """
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.ha_url}/api/camera_proxy/{entity_id}",
                headers=self._ha_headers,
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.warning("Camera Snapshot %s -> %d", entity_id, resp.status)
        except Exception as e:
            logger.error("Camera Snapshot Fehler: %s", e)
        return None

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
        # Audit-Log fuer Licht-Aktionen
        if domain == "light":
            logger.debug(
                "LIGHT AUDIT: %s.%s data=%s",
                domain, service, data,
            )

        result = await self._post_ha(
            f"/api/services/{domain}/{service}", data or {}
        )
        return result is not None

    async def call_service_with_response(
        self, domain: str, service: str, data: Optional[dict] = None
    ) -> Any:
        """HA Service aufrufen und Response-Body zurueckgeben.

        Manche HA-Services (z.B. weather.get_forecasts, calendar.get_events)
        geben Daten zurueck. Nutzt ?return_response (ab HA 2024.x erforderlich).
        """
        return await self._post_ha(
            f"/api/services/{domain}/{service}?return_response", data or {}
        )

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

    async def search_devices(self, domain: str = "", room: str = "") -> Optional[list]:
        """Geraete ueber MindHome Device-DB suchen (schneller als alle HA-States laden)."""
        params = {}
        if domain:
            params["domain"] = domain
        if room:
            params["room"] = room
        qs = urlencode(params) if params else ""
        return await self._get_mindhome(f"/api/devices/search?{qs}")

    async def mindhome_get(self, path: str) -> Any:
        """Oeffentlicher GET auf die MindHome Add-on API (z.B. /api/covers/configs)."""
        return await self._get_mindhome(path)

    async def mindhome_post(self, path: str, data: dict, retries: int = 0) -> Any:
        """POST auf die MindHome Add-on API."""
        last_err = None
        for attempt in range(1 + retries):
            session = await self._get_session()
            try:
                async with session.post(
                    f"{self.mindhome_url}{path}",
                    json=data,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    body = await resp.text()
                    logger.warning("MindHome POST %s -> %d: %s", path, resp.status, body[:300])
                    last_err = f"HTTP {resp.status}"
                    if 400 <= resp.status < 500:
                        break  # Client-Error: nicht retrybar
            except Exception as e:
                logger.warning("MindHome POST %s fehlgeschlagen (Versuch %d): %s", path, attempt + 1, e)
                last_err = str(e)
            if attempt < retries:
                await asyncio.sleep(1.5)
        if last_err:
            logger.warning("MindHome POST %s endgueltig fehlgeschlagen: %s", path, last_err)
        return None

    async def log_actions(self, actions: list, user_text: str = "", response_text: str = "") -> None:
        """Jarvis-Aktionen an MindHome Add-on ActionLog melden."""
        if not actions:
            return
        # Actions JSON-sicher machen (result kann komplexe Objekte enthalten)
        safe_actions = []
        for a in actions:
            safe = {
                "function": str(a.get("function", "unknown")),
                "args": a.get("args") or a.get("arguments") or {},
            }
            result = a.get("result", {})
            if isinstance(result, dict):
                safe["result"] = {
                    "success": bool(result.get("success", False)),
                    "message": str(result.get("message", "")),
                }
            else:
                safe["result"] = {"success": False, "message": str(result)}
            safe_actions.append(safe)

        payload = {
            "actions": safe_actions,
            "user_text": str(user_text or ""),
            "response": str(response_text or ""),
        }
        logger.info("log_actions: %d Aktionen melden (%s)",
                     len(safe_actions),
                     [a["function"] for a in safe_actions])
        result = await self.mindhome_post("/api/action-log", payload, retries=1)
        if result is None:
            logger.warning("log_actions: POST /api/action-log fehlgeschlagen (result=None)")
        else:
            logger.info("log_actions: Erfolgreich %d Aktionen geloggt", len(safe_actions))

    async def mindhome_put(self, path: str, data: dict) -> Any:
        """PUT auf die MindHome Add-on API (z.B. Cover-Config setzen)."""
        session = await self._get_session()
        try:
            async with session.put(
                f"{self.mindhome_url}{path}",
                json=data,
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("MindHome PUT %s -> %d", path, resp.status)
                return None
        except Exception as e:
            logger.warning("MindHome PUT %s fehlgeschlagen: %s", path, e)
            return None

    # ----- Interne HTTP Methoden mit Retry -----

    async def _get_ha(self, path: str) -> Any:
        """GET-Request an Home Assistant mit Retry und Circuit Breaker."""
        # F-025: Circuit Breaker pruefen
        if not ha_breaker.is_available:
            logger.debug("HA Circuit Breaker OPEN — GET %s uebersprungen", path)
            return None

        session = await self._get_session()
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    f"{self.ha_url}{path}",
                    headers=self._ha_headers,
                ) as resp:
                    if resp.status == 200:
                        ha_breaker.record_success()
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

        # F-025: Fehler im Circuit Breaker registrieren
        ha_breaker.record_failure()
        logger.error("HA GET %s endgueltig fehlgeschlagen: %s", path, last_error)
        return None

    async def _post_ha(self, path: str, data: dict) -> Any:
        """POST-Request an Home Assistant mit Retry und Circuit Breaker."""
        # F-025: Circuit Breaker pruefen
        if not ha_breaker.is_available:
            logger.debug("HA Circuit Breaker OPEN — POST %s uebersprungen", path)
            return None

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

    async def _put_ha(self, path: str, data: dict) -> Any:
        """PUT-Request an Home Assistant mit Retry."""
        session = await self._get_session()
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.put(
                    f"{self.ha_url}{path}",
                    headers=self._ha_headers,
                    json=data,
                ) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
                    if 400 <= resp.status < 500:
                        body = await resp.text()
                        logger.warning(
                            "HA PUT %s -> %d (Client-Fehler): %s",
                            path, resp.status, body[:200],
                        )
                        return None
                    body = await resp.text()
                    logger.warning(
                        "HA PUT %s -> %d (Versuch %d/%d): %s",
                        path, resp.status, attempt + 1, MAX_RETRIES, body[:200],
                    )
                    last_error = f"HTTP {resp.status}"
            except aiohttp.ClientError as e:
                last_error = str(e)
                logger.warning(
                    "HA PUT %s fehlgeschlagen (Versuch %d/%d): %s",
                    path, attempt + 1, MAX_RETRIES, e,
                )
            except asyncio.TimeoutError:
                last_error = "Timeout"
                logger.warning(
                    "HA PUT %s Timeout (Versuch %d/%d)",
                    path, attempt + 1, MAX_RETRIES,
                )

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE * (attempt + 1)
                await asyncio.sleep(wait)

        logger.error("HA PUT %s endgueltig fehlgeschlagen: %s", path, last_error)
        return None

    async def _delete_ha(self, path: str) -> bool:
        """DELETE-Request an Home Assistant mit Retry."""
        session = await self._get_session()
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.delete(
                    f"{self.ha_url}{path}",
                    headers=self._ha_headers,
                ) as resp:
                    if resp.status in (200, 204):
                        return True
                    if 400 <= resp.status < 500:
                        body = await resp.text()
                        logger.warning(
                            "HA DELETE %s -> %d (Client-Fehler): %s",
                            path, resp.status, body[:200],
                        )
                        return False
                    body = await resp.text()
                    logger.warning(
                        "HA DELETE %s -> %d (Versuch %d/%d): %s",
                        path, resp.status, attempt + 1, MAX_RETRIES, body[:200],
                    )
                    last_error = f"HTTP {resp.status}"
            except aiohttp.ClientError as e:
                last_error = str(e)
                logger.warning(
                    "HA DELETE %s fehlgeschlagen (Versuch %d/%d): %s",
                    path, attempt + 1, MAX_RETRIES, e,
                )
            except asyncio.TimeoutError:
                last_error = "Timeout"
                logger.warning(
                    "HA DELETE %s Timeout (Versuch %d/%d)",
                    path, attempt + 1, MAX_RETRIES,
                )

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE * (attempt + 1)
                await asyncio.sleep(wait)

        logger.error("HA DELETE %s endgueltig fehlgeschlagen: %s", path, last_error)
        return False

    # --- Oeffentliche Config-Methoden (fuer Automation, Script, etc.) ---

    async def put_config(self, config_type: str, config_id: str, data: dict) -> bool:
        """Erstellt/aktualisiert eine HA-Config (Automation, Script, etc.).

        Args:
            config_type: z.B. "automation", "script", "scene"
            config_id: Eindeutige ID
            data: Config-Daten

        Returns:
            True bei Erfolg
        """
        result = await self._put_ha(
            f"/api/config/{config_type}/config/{config_id}", data
        )
        return result is not None

    async def delete_config(self, config_type: str, config_id: str) -> bool:
        """Loescht eine HA-Config (Automation, Script, etc.).

        Args:
            config_type: z.B. "automation", "script", "scene"
            config_id: Eindeutige ID

        Returns:
            True bei Erfolg
        """
        return await self._delete_ha(
            f"/api/config/{config_type}/config/{config_id}"
        )

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
