"""
Circuit Breaker - Strukturierte Fehlerbehandlung fuer externe Dienste.

Schuetzt vor kaskadierten Fehlern wenn externe Dienste (Ollama, HA, Redis)
nicht erreichbar sind. Implementiert das Circuit-Breaker-Pattern:

  CLOSED  → Normalbetrieb, Fehler werden gezaehlt
  OPEN    → Dienst als kaputt angenommen, Calls werden sofort abgelehnt
  HALF_OPEN → Test-Call, bei Erfolg → CLOSED, bei Fehler → OPEN

Zusaetzlich: Retry-Logik mit exponentiellem Backoff.
"""

import asyncio
import logging
import threading
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit Breaker fuer einen einzelnen externen Dienst."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    def _check_recovery(self) -> None:
        """Prueft ob der Recovery-Timeout abgelaufen ist und wechselt ggf. zu HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("Circuit %s: OPEN -> HALF_OPEN", self.name)

    @property
    def state(self) -> CircuitState:
        return self._state

    def check_state(self) -> CircuitState:
        """Prueft und aktualisiert den State (inkl. Recovery-Check) und gibt ihn zurueck."""
        self._check_recovery()
        return self._state

    @property
    def is_available(self) -> bool:
        """Prueft ob der Dienst voraussichtlich erreichbar ist (read-only)."""
        self._check_recovery()
        s = self._state
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False

    def try_acquire(self) -> bool:
        """Reserviert einen Call-Slot. Im HALF_OPEN: inkrementiert Zaehler."""
        with self._lock:
            self._check_recovery()
            s = self._state
            if s == CircuitState.CLOSED:
                return True
            if s == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                logger.debug("Circuit %s HALF_OPEN max calls reached", self.name)
                return False
            # S7: OPEN-State nicht stumm
            logger.debug("Circuit %s OPEN — rejecting call", self.name)
            return False

    def record_success(self) -> None:
        """Meldet einen erfolgreichen Call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Circuit %s: HALF_OPEN -> CLOSED", self.name)
            else:
                self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """Meldet einen fehlgeschlagenen Call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("Circuit %s: HALF_OPEN -> OPEN (Test-Call fehlgeschlagen)", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit %s: CLOSED -> OPEN (%d Fehler)",
                    self.name, self._failure_count,
                )

    def reset(self) -> None:
        """Setzt den Circuit Breaker zurueck."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0

    def status(self) -> dict:
        """Status fuer Diagnostik/Metrics."""
        return {
            "name": self.name,
            "state": self.check_state().value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


class CircuitBreakerRegistry:
    """Zentrale Registry fuer alle Circuit Breaker im System."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def register(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> CircuitBreaker:
        """Registriert einen neuen Circuit Breaker."""
        cb = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
        self._breakers[name] = cb
        return cb

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Holt einen Circuit Breaker by name."""
        return self._breakers.get(name)

    def all_status(self) -> list[dict]:
        """Status aller registrierten Breaker."""
        return [cb.status() for cb in self._breakers.values()]

    def all_available(self) -> dict[str, bool]:
        """Verfuegbarkeit aller Dienste."""
        return {name: cb.is_available for name, cb in self._breakers.items()}

    # ------------------------------------------------------------------
    # Phase 8C: Graduated Degradation, Error-Kategorisierung, Cascade
    # ------------------------------------------------------------------

    _STATES = ["CLOSED", "WARNING", "REDUCED", "OPEN"]
    _GRADUATED_STATES = _STATES  # Alias fuer Rueckwaertskompatibilitaet

    _CASCADE_MAP: dict[str, list[str]] = {
        "ollama": ["response_cache"],
        "redis": ["memory", "anticipation", "feedback"],
        "chromadb": ["semantic_memory", "rag"],
        "home_assistant": ["device_health", "diagnostics"],
    }

    def get_graduated_state(self, service: str) -> str:
        """Gibt den abgestuften Zustand eines Service zurueck.

        CLOSED (0-2 Fehler) → WARNING (3-5) → REDUCED (6-9) → OPEN (10+).
        """
        cb = self._breakers.get(service)
        if not cb:
            return "CLOSED"
        count = cb._failure_count
        if count <= 2:
            return "CLOSED"
        if count <= 5:
            return "WARNING"
        if count <= 9:
            return "REDUCED"
        return "OPEN"

    @staticmethod
    def categorize_error(error: Exception) -> str:
        """Kategorisiert einen Fehler nach Typ.

        Returns:
            "timeout", "server_error", "client_error", "connection_error"
        """
        error_str = str(type(error).__name__).lower()
        error_msg = str(error).lower()

        if "timeout" in error_str or "timeout" in error_msg:
            return "timeout"
        if "connection" in error_str or "connect" in error_msg:
            return "connection_error"
        if any(c in error_msg for c in ("500", "502", "503", "504")):
            return "server_error"
        if any(c in error_msg for c in ("400", "401", "403", "404", "422")):
            return "client_error"
        return "server_error"

    def check_cascade(self, failed_service: str) -> list[str]:
        """Prueft welche abhaengigen Services ebenfalls degradiert werden sollten.

        Args:
            failed_service: Name des ausgefallenen Service.

        Returns:
            Liste der betroffenen abhaengigen Services.
        """
        return list(self._CASCADE_MAP.get(failed_service, []))


# Globale Registry
registry = CircuitBreakerRegistry()

# Standard-Breaker fuer die Hauptdienste registrieren
ollama_breaker = registry.register("ollama", failure_threshold=5, recovery_timeout=15)
ha_breaker = registry.register("home_assistant", failure_threshold=5, recovery_timeout=20)
mindhome_breaker = registry.register("mindhome", failure_threshold=5, recovery_timeout=20)
redis_breaker = registry.register("redis", failure_threshold=5, recovery_timeout=10)
chromadb_breaker = registry.register("chromadb", failure_threshold=5, recovery_timeout=15)
web_search_breaker = registry.register("web_search", failure_threshold=3, recovery_timeout=120)
