"""
Ollama API Client - Kommunikation mit dem lokalen LLM

Qwen 3 Kompatibilitaet:
- Stripped automatisch <think>...</think> Bloecke aus Antworten
- Thinking Mode wird fuer Fast-Tier deaktiviert (spart Latenz)
"""

import asyncio
import logging
import re
from typing import Optional

import aiohttp

from .circuit_breaker import ollama_breaker
from .config import settings
from .constants import (
    LLM_DEFAULT_MAX_TOKENS,
    LLM_DEFAULT_TEMPERATURE,
    LLM_TIMEOUT_AVAILABILITY,
    LLM_TIMEOUT_DEEP,
    LLM_TIMEOUT_FAST,
    LLM_TIMEOUT_SMART,
    LLM_TIMEOUT_STREAM,
)

logger = logging.getLogger(__name__)

# Regex zum Entfernen von Qwen 3 Think-Bloecken
_THINK_PATTERN = re.compile(r"<think>[\s\S]*?</think>\s*", re.DOTALL)

# Woerter die auf Meta-Kommentar / Reasoning hindeuten (nicht in echter Meldung)
_META_MARKERS = [
    # Englisches Reasoning
    "let me", "i need to", "the user", "i should", "i'll ", "i can ",
    "original:", "original message", "translate", "rephrase", "reformulate",
    "thinking", "analyze", "however", "therefore", "which means",
    "looking at", "understand", "consider", "examples given",
    "in jarvis", "jarvis's style", "jarvis style", "the example",
    "low urgency", "medium urgency", "high urgency",
    "short,", "concise", "1-2 sentence", "1-3 sentence",
    "british butler", "dry humor", "matter-of-fact",
    # Prompt-Echo
    "formuliere diese", "meldung im jarvis", "dringlichkeit:",
]

# Haeufige deutsche Woerter (muessen in einer echten deutschen Meldung vorkommen)
_GERMAN_MARKERS = [
    "sir", "ma'am", "der", "die", "das", "ist", "ein", "und", "nicht",
    "ich", "hab", "mal", "aus", "auf", "mit", "bei", "zur",
    "noch", "nur", "etwas", "gerade", "bitte", "danke",
    "grad", "uhr", "haus", "licht", "heiz",
    # Verben (haeufig in Notifications)
    "wurde", "wird", "hat", "sind", "kann", "soll",
    "sollte", "darf", "liegt", "steht", "scheint",
    # Smart-Home Begriffe
    "temperatur", "fenster", "wasser", "luft",
    "befeuchter", "humidor", "sensor", "batterie",
    # Allgemein
    "bereits", "aktuell", "guten", "herr", "frau",
]


def strip_think_tags(text: str) -> str:
    """Entfernt <think>...</think> Bloecke aus Qwen 3 Antworten."""
    if not text or "<think>" not in text:
        return text
    cleaned = _THINK_PATTERN.sub("", text).strip()
    return cleaned if cleaned else text


def validate_notification(text: str) -> str:
    """Validiert LLM-Output als Jarvis-Meldung. Gibt leeren String bei Leak.

    Eine gueltige Jarvis-Meldung ist:
    - Kurz (< 250 Zeichen)
    - Auf Deutsch (enthaelt deutsche Woerter)
    - Kein Meta-Kommentar ueber die Aufgabe selbst
    - Kein englisches Reasoning

    Gibt den bereinigten Text oder leeren String zurueck (Caller nutzt Fallback).
    """
    if not text:
        return text

    # Think-Tags entfernen
    text = strip_think_tags(text)
    if not text:
        return ""

    text = text.strip()

    # --- Check 1: Meta-Kommentar / Reasoning erkannt ---
    text_lower = text.lower()
    meta_hits = sum(1 for m in _META_MARKERS if m in text_lower)
    if meta_hits >= 2:
        logger.warning(
            "Notification verworfen (Meta-Kommentar, %d Treffer): '%.80s...'",
            meta_hits, text,
        )
        # Versuche letzte Zeile als Antwort zu extrahieren
        extracted = _extract_final_answer(text)
        if extracted:
            return extracted
        return ""

    # --- Check 2: Zu lang fuer eine Notification ---
    if len(text) > 300:
        # Vielleicht ist die eigentliche Meldung in den ersten 1-2 Saetzen?
        first_part = text.split("\n")[0].strip()
        if 10 < len(first_part) < 250 and _looks_german(first_part):
            logger.info("Notification gekuerzt auf erste Zeile: '%s'", first_part)
            return first_part
        logger.warning("Notification verworfen (zu lang: %d Zeichen)", len(text))
        return ""

    # --- Check 3: Nicht Deutsch ---
    if not _looks_german(text) and len(text) > 50:
        logger.warning("Notification verworfen (nicht Deutsch): '%.80s...'", text)
        return ""

    return text


def _looks_german(text: str) -> bool:
    """Prueft ob ein Text deutsch aussieht."""
    text_lower = text.lower()
    hits = sum(1 for w in _GERMAN_MARKERS if w in text_lower)
    # Mindestens 2 deutsche Marker oder Umlaute vorhanden
    return hits >= 2 or any(c in text for c in "äöüÄÖÜß")


def _extract_final_answer(text: str) -> str:
    """Versucht die eigentliche Antwort aus einem Reasoning-Block zu fischen.

    Manche Modelle schreiben die Antwort als letzte Zeile, oft in Anfuehrungszeichen.
    """
    lines = text.strip().split("\n")
    for line in reversed(lines):
        candidate = line.strip().strip('"').strip("'").strip('"').strip('"').strip()
        if not candidate or len(candidate) < 8 or len(candidate) > 250:
            continue
        if _looks_german(candidate):
            meta_in_candidate = sum(1 for m in _META_MARKERS if m in candidate.lower())
            if meta_in_candidate == 0:
                logger.info("Antwort aus Reasoning extrahiert: '%s'", candidate)
                return candidate
    return ""


# Legacy-Alias fuer bestehende Aufrufe
strip_reasoning_leak = validate_notification


class OllamaClient:
    """Asynchroner Client fuer die Ollama REST API mit per-Model Timeouts und Connection Pooling."""

    # Kontextfenster-Groesse (num_ctx) begrenzen.
    # Ollama allokiert KV-Cache fuer das volle Kontextfenster im VRAM,
    # auch wenn der Prompt kurz ist. Bei 8GB GPUs (RTX 3070) fuehrt der
    # Default (32768+) zu VRAM-Ueberlauf. 4096 reicht fuer Smart-Home.
    _DEFAULT_NUM_CTX = 4096

    def __init__(self):
        self.base_url = settings.ollama_url
        # Shared Session (wird lazy initialisiert) — spart TCP-Handshake pro Request
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock: asyncio.Lock = asyncio.Lock()

    @property
    def num_ctx(self) -> int:
        """Liest num_ctx live aus yaml_config (aendert sich bei Settings-Update)."""
        from .config import yaml_config
        return int((yaml_config.get("ollama") or {}).get("num_ctx", self._DEFAULT_NUM_CTX))

    async def _get_session(self) -> aiohttp.ClientSession:
        """Gibt die shared aiohttp Session zurueck (thread-safe lazy init)."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            return self._session

    async def close(self) -> None:
        """Schliesst die HTTP Session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _get_timeout(self, model: str) -> int:
        """Berechnet den passenden Timeout je nach Modell-Tier."""
        if model == settings.model_fast:
            return LLM_TIMEOUT_FAST
        elif model == settings.model_deep:
            return LLM_TIMEOUT_DEEP
        else:
            return LLM_TIMEOUT_SMART

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        tools: Optional[list] = None,
        temperature: float = LLM_DEFAULT_TEMPERATURE,
        max_tokens: int = LLM_DEFAULT_MAX_TOKENS,
        think: Optional[bool] = None,
    ) -> dict:
        """
        Sendet eine Chat-Anfrage an Ollama.

        Args:
            messages: Liste von {"role": "...", "content": "..."} Nachrichten
            model: Modellname (default: smart model)
            tools: Function-Calling Tools (optional)
            temperature: Kreativitaet (0.0 - 1.0)
            max_tokens: Maximale Antwort-Laenge
            think: Qwen 3 Thinking Mode (True/False/None=auto)

        Returns:
            Ollama API Response dict
        """
        model = model or settings.model_smart

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }

        if tools:
            payload["tools"] = tools

        # Qwen 3 Thinking Mode steuern
        # Bei Tools: Think aus (stoert Function Calling)
        # Bei Fast-Model: Think aus (spart Latenz)
        # Bei Smart == Deep (gleiches Modell): Think aus (kein VRAM-Overhead)
        # Bei Deep-Model ohne Tools: Think an (besseres Reasoning)
        if think is not None:
            payload["think"] = think
        elif tools:
            payload["think"] = False
        elif model == settings.model_fast:
            payload["think"] = False
        elif model == settings.model_deep and settings.model_deep == settings.model_smart:
            # Smart und Deep sind das gleiche Modell — Think bringt keinen Vorteil,
            # verbraucht aber deutlich mehr VRAM und Zeit
            payload["think"] = False

        # Circuit Breaker Check
        if not ollama_breaker.is_available:
            logger.warning("Ollama Circuit OPEN — ueberspringe Call")
            return {"error": "Ollama nicht verfuegbar (Circuit Breaker offen)"}

        timeout = self._get_timeout(model)

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error("Ollama Fehler %d: %s", resp.status, error)
                    ollama_breaker.record_failure()
                    return {"error": error}
                result = await resp.json()
                ollama_breaker.record_success()

                # Think-Tags aus der Antwort strippen (Sicherheitsnetz)
                msg = result.get("message", {})
                content = msg.get("content", "")
                if content and "<think>" in content:
                    cleaned = strip_think_tags(content)
                    logger.debug("Think-Tags entfernt (%d → %d Zeichen)",
                                 len(content), len(cleaned))
                    msg["content"] = cleaned

                return result
        except asyncio.TimeoutError:
            logger.error("Ollama Timeout nach %ds fuer Modell %s", timeout, model)
            ollama_breaker.record_failure()
            return {"error": f"Timeout nach {timeout}s"}
        except aiohttp.ClientError as e:
            logger.error("Ollama nicht erreichbar: %s", e)
            ollama_breaker.record_failure()
            return {"error": str(e)}

    async def stream_chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = LLM_DEFAULT_TEMPERATURE,
        max_tokens: int = LLM_DEFAULT_MAX_TOKENS,
        think: Optional[bool] = None,
    ):
        """
        Streaming Chat — gibt Token-fuer-Token zurueck (async generator).

        Yields:
            str: Einzelne Text-Chunks sobald sie vom LLM kommen.

        Usage:
            async for chunk in ollama.stream_chat(messages, model):
                print(chunk, end="", flush=True)
        """
        if not ollama_breaker.is_available:
            logger.warning("Ollama Circuit OPEN — Stream abgebrochen")
            return

        model = model or settings.model_smart

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }

        if think is not None:
            payload["think"] = think
        elif model == settings.model_fast:
            payload["think"] = False
        elif model == settings.model_deep and settings.model_deep == settings.model_smart:
            payload["think"] = False

        # F-024: Buffer-basiertes Think-Tag-Filtering (verhindert Content-Verlust)
        _think_buffer = ""
        in_think_block = False

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT_STREAM),
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error("Ollama Stream Fehler %d: %s", resp.status, error)
                    ollama_breaker.record_failure()
                    yield "[STREAM_ERROR]"
                    return

                import json as _json

                async for line in resp.content:
                    if not line:
                        continue
                    try:
                        data = _json.loads(line)
                    except (ValueError, _json.JSONDecodeError):
                        continue

                    content = data.get("message", {}).get("content", "")
                    is_done = data.get("done", False)
                    if not content and not is_done:
                        continue

                    # F-024: Buffer-Ansatz — Chunks mit Tags im Buffer sammeln
                    _think_buffer += content

                    # Wenn wir im Think-Block sind, weiter buffern bis </think>
                    if in_think_block:
                        if "</think>" in _think_buffer:
                            # Think-Block beenden, Rest nach </think> behalten
                            _, _, after = _think_buffer.partition("</think>")
                            _think_buffer = after.lstrip()
                            in_think_block = False
                        else:
                            if is_done:
                                break
                            continue

                    # Pruefe ob ein neuer Think-Block beginnt
                    if "<think>" in _think_buffer:
                        before, _, after = _think_buffer.partition("<think>")
                        # Content VOR <think> ausgeben
                        if before.strip():
                            yield before
                        # Alles nach <think> buffern
                        _think_buffer = after
                        in_think_block = True
                        # Sofort pruefen ob </think> auch schon im Buffer
                        if "</think>" in _think_buffer:
                            _, _, after = _think_buffer.partition("</think>")
                            _think_buffer = after.lstrip()
                            in_think_block = False
                        if is_done:
                            break
                        continue

                    # Kein Think-Tag — Buffer ausgeben
                    if _think_buffer:
                        yield _think_buffer
                        _think_buffer = ""

                    if is_done:
                        break

                # Rest im Buffer ausgeben (falls kein offener Think-Block)
                if _think_buffer and not in_think_block:
                    yield _think_buffer

        except asyncio.TimeoutError:
            logger.error("Ollama Stream Timeout nach %ds", LLM_TIMEOUT_STREAM)
            ollama_breaker.record_failure()
            yield "[STREAM_TIMEOUT]"
        except aiohttp.ClientError as e:
            logger.error("Ollama Stream nicht erreichbar: %s", e)
            ollama_breaker.record_failure()
            yield "[STREAM_ERROR]"

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = LLM_DEFAULT_TEMPERATURE,
        max_tokens: int = LLM_DEFAULT_MAX_TOKENS,
    ) -> str:
        """
        Sendet eine Generate-Anfrage an Ollama (/api/generate).

        Im Gegensatz zu chat() nimmt generate() einen einzelnen Prompt-String
        statt einer Message-Liste. Wird u.a. von SelfOptimization genutzt.

        Args:
            prompt: Der Prompt-Text
            model: Modellname (default: smart model)
            temperature: Kreativitaet (0.0 - 1.0)
            max_tokens: Maximale Antwort-Laenge

        Returns:
            Generierter Text als String
        """
        if not ollama_breaker.is_available:
            logger.warning("Ollama Circuit OPEN — generate() uebersprungen")
            return ""

        model = model or settings.model_smart
        timeout = self._get_timeout(model)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error("Ollama Generate Fehler %d: %s", resp.status, error)
                    return ""
                result = await resp.json()
                ollama_breaker.record_success()
                text = result.get("response", "")
                return strip_think_tags(text)
        except asyncio.TimeoutError:
            logger.error("Ollama Generate Timeout nach %ds fuer Modell %s", timeout, model)
            ollama_breaker.record_failure()
            return ""
        except aiohttp.ClientError as e:
            logger.error("Ollama Generate nicht erreichbar: %s", e)
            ollama_breaker.record_failure()
            return ""

    async def is_available(self) -> bool:
        """Prueft ob Ollama erreichbar ist (mit Circuit Breaker Feedback)."""
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT_AVAILABILITY),
            ) as resp:
                available = resp.status == 200
                if available:
                    ollama_breaker.record_success()
                return available
        except aiohttp.ClientError:
            ollama_breaker.record_failure()
            return False

    async def list_models(self) -> list[str]:
        """Listet alle verfuegbaren Modelle."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/tags") as resp:
                data = await resp.json()
                return [m["name"] for m in data.get("models", [])]
        except aiohttp.ClientError:
            return []
