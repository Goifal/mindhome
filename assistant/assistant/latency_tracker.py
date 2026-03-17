"""
Latency Tracker — End-to-End Latenz-Monitoring fuer den MindHome Assistant.

Misst die Dauer jeder Phase im Request-Lifecycle:
  STT → Pre-Classify → Context-Gather → LLM-First-Token → LLM-Complete → TTS-First-Audio

Berechnet Percentile (p50, p95, p99) aus einem Ring-Buffer der letzten N Requests.
Ergebnisse werden periodisch in Redis geschrieben (mha:latency:stats).
"""

import asyncio
import bisect
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Phasen im Request-Lifecycle (Reihenfolge = typischer Ablauf)
PHASES = (
    "pre_classify",
    "context_gather",
    "llm_first_token",
    "llm_complete",
    "tts_first_audio",
    "total",
)

_MAX_HISTORY = 200  # Ring-Buffer Groesse


@dataclass
class RequestTrace:
    """Einzelner Request-Trace mit Phase-Timestamps."""

    request_id: str
    start: float = field(default_factory=time.monotonic)
    marks: dict = field(default_factory=dict)
    _phase_durations: dict = field(default_factory=dict)

    def mark(self, phase: str) -> None:
        """Setzt einen Zeitstempel fuer eine Phase."""
        self.marks[phase] = time.monotonic()

    def finish(self) -> dict:
        """Berechnet Dauer pro Phase in Millisekunden. Gibt Dict zurueck."""
        durations = {}
        prev = self.start
        for phase in PHASES[:-1]:  # Alles ausser "total"
            ts = self.marks.get(phase)
            if ts is not None:
                durations[phase] = round((ts - prev) * 1000, 1)
                prev = ts
        durations["total"] = round((time.monotonic() - self.start) * 1000, 1)
        self._phase_durations = durations
        return durations


class LatencyTracker:
    """Sammelt Request-Traces und berechnet Latenz-Percentile."""

    def __init__(self, max_history: int = _MAX_HISTORY):
        self._max_history = max_history
        # Pro Phase: sortierte Liste fuer schnelle Percentil-Berechnung
        self._phase_values: dict[str, deque] = {p: deque(maxlen=max_history) for p in PHASES}
        # Sortierte Kopien fuer Percentil-Berechnung (lazy, invalidiert bei neuen Werten)
        self._sorted_cache: dict[str, list] = {}
        self._dirty = True
        self._trace_count: int = 0
        self._redis = None

    def set_redis(self, redis_client) -> None:
        """Setzt den Redis-Client fuer periodisches Stats-Schreiben."""
        self._redis = redis_client

    def begin(self, request_id: str = "") -> RequestTrace:
        """Startet einen neuen Request-Trace."""
        if not request_id:
            self._trace_count += 1
            request_id = f"req-{self._trace_count}"
        return RequestTrace(request_id=request_id)

    def record(self, trace: RequestTrace) -> dict:
        """Schliesst einen Trace ab und fuegt ihn in den Ring-Buffer ein."""
        durations = trace.finish()
        for phase, ms in durations.items():
            if phase in self._phase_values:
                self._phase_values[phase].append(ms)
        self._dirty = True

        logger.info(
            "Latency [%s]: %s",
            trace.request_id,
            " | ".join(f"{k}={v:.0f}ms" for k, v in durations.items()),
        )
        return durations

    def _ensure_sorted(self) -> None:
        """Baut sortierte Listen fuer Percentil-Berechnung (nur wenn dirty)."""
        if not self._dirty:
            return
        for phase in PHASES:
            vals = list(self._phase_values[phase])
            vals.sort()
            self._sorted_cache[phase] = vals
        self._dirty = False

    def percentile(self, phase: str, p: float) -> Optional[float]:
        """Berechnet das p-te Percentil (0-100) fuer eine Phase.

        Returns None wenn keine Daten vorhanden.
        """
        self._ensure_sorted()
        vals = self._sorted_cache.get(phase, [])
        if not vals:
            return None
        if p <= 0:
            return vals[0]
        if p >= 100:
            return vals[-1]
        idx = (p / 100) * (len(vals) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(vals) - 1)
        frac = idx - lower
        return round(vals[lower] + frac * (vals[upper] - vals[lower]), 1)

    def get_stats(self) -> dict:
        """Gibt aktuelle Latenz-Statistiken zurueck (p50, p95, p99 pro Phase)."""
        stats = {}
        for phase in PHASES:
            vals = list(self._phase_values[phase])
            if not vals:
                continue
            stats[phase] = {
                "p50": self.percentile(phase, 50),
                "p95": self.percentile(phase, 95),
                "p99": self.percentile(phase, 99),
                "count": len(vals),
                "min": round(min(vals), 1),
                "max": round(max(vals), 1),
            }
        return stats

    async def flush_to_redis(self) -> None:
        """Schreibt aktuelle Stats nach Redis (fuer Dashboard/Monitoring)."""
        if not self._redis:
            return
        try:
            import json
            stats = self.get_stats()
            if stats:
                await self._redis.set(
                    "mha:latency:stats",
                    json.dumps(stats),
                    ex=600,  # 10 Min TTL
                )
        except Exception as e:
            logger.debug("Latency flush_to_redis fehlgeschlagen: %s", e)

    def get_summary_text(self) -> str:
        """Gibt eine menschenlesbare Zusammenfassung zurueck."""
        stats = self.get_stats()
        if not stats:
            return "Keine Latenz-Daten vorhanden."
        lines = ["Latenz-Statistik (letzte Requests):"]
        for phase in PHASES:
            s = stats.get(phase)
            if not s:
                continue
            lines.append(
                f"  {phase:20s}  p50={s['p50']:>7.0f}ms  "
                f"p95={s['p95']:>7.0f}ms  p99={s['p99']:>7.0f}ms  "
                f"(n={s['count']}, min={s['min']:.0f}, max={s['max']:.0f})"
            )
        return "\n".join(lines)


# Modul-Level Singleton
latency_tracker = LatencyTracker()
