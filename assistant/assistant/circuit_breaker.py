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
import time
from enum import Enum
from typing import Any, Callable, Optional

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

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("Circuit %s: OPEN -> HALF_OPEN", self.name)
        return self._state

    @property
    def is_available(self) -> bool:
        """Prueft ob der Dienst voraussichtlich erreichbar ist."""
        s = self.state
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        return False

    def record_success(self) -> None:
        """Meldet einen erfolgreichen Call."""
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
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    def status(self) -> dict:
        """Status fuer Diagnostik/Metrics."""
        return {
            "name": self.name,
            "state": self.state.value,
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


# Globale Registry
registry = CircuitBreakerRegistry()

# Standard-Breaker fuer die Hauptdienste registrieren
ollama_breaker = registry.register("ollama", failure_threshold=3, recovery_timeout=30)
ha_breaker = registry.register("home_assistant", failure_threshold=5, recovery_timeout=20)
redis_breaker = registry.register("redis", failure_threshold=3, recovery_timeout=15)
chromadb_breaker = registry.register("chromadb", failure_threshold=5, recovery_timeout=60)


async def call_with_breaker(
    breaker: CircuitBreaker,
    coro_factory: Callable,
    *args: Any,
    fallback: Any = None,
    **kwargs: Any,
) -> Any:
    """Fuehrt einen async Call mit Circuit-Breaker-Schutz aus.

    Args:
        breaker: Der zu verwendende Circuit Breaker
        coro_factory: Async Funktion (nicht aufgerufen) die den Call ausfuehrt
        fallback: Rueckgabewert wenn Circuit offen oder Call fehlschlaegt

    Returns:
        Ergebnis des Calls oder fallback
    """
    if not breaker.is_available:
        logger.debug("Circuit %s ist OPEN — nutze Fallback", breaker.name)
        return fallback

    try:
        result = await coro_factory(*args, **kwargs)
        breaker.record_success()
        return result
    except Exception as e:
        breaker.record_failure()
        logger.warning("Circuit %s: Call fehlgeschlagen: %s", breaker.name, e)
        return fallback
