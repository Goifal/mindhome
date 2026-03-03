"""
Ollama API Client - Kommunikation mit dem lokalen LLM

Qwen 3 / 3.5 Kompatibilitaet:
- Stripped automatisch <think>...</think> Bloecke aus Antworten
- Thinking Mode wird fuer Fast-Tier deaktiviert (spart Latenz)
- Qwen 3.5: Modell-optimierte Parameter (top_k, top_p, min_p)
- Qwen 3.5: Thinking + Tool Calling gleichzeitig moeglich
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


def _is_qwen35(model: str) -> bool:
    """Prueft ob ein Modell zur Qwen 3.5 Familie gehoert."""
    return "qwen3.5" in model.lower()


def _is_qwen3(model: str) -> bool:
    """Prueft ob ein Modell zur Qwen 3.x Familie gehoert (inkl. 3.5)."""
    return "qwen3" in model.lower()


def _model_options(model: str, temperature: float, max_tokens: int, num_ctx: int,
                   think_enabled: bool = False) -> dict:
    """Erzeugt modell-optimierte Ollama Options.

    Qwen 3.5 empfohlene Parameter (laut Alibaba):
    - Thinking Mode: temp=0.6, top_p=0.95, top_k=20, min_p=0
    - Non-Thinking:  temp=0.7, top_p=0.8,  top_k=20, min_p=0

    Qwen 3.5 MoE-Modelle sind VRAM-effizient (35B nutzt nur 3B aktive Parameter),
    daher koennen wir num_ctx groesser waehlen als bei Dense-Modellen.
    """
    opts = {
        "temperature": temperature,
        "num_predict": max_tokens,
        "num_ctx": num_ctx,
    }

    if _is_qwen35(model):
        opts["top_k"] = 20
        opts["min_p"] = 0.0
        opts["repeat_penalty"] = 1.1
        if think_enabled:
            opts["temperature"] = min(temperature, 0.6)
            opts["top_p"] = 0.95
        else:
            opts["top_p"] = 0.8
    elif _is_qwen3(model):
        # Qwen 3: gleiche Empfehlungen wie 3.5
        opts["top_k"] = 20
        opts["min_p"] = 0.0
        if think_enabled:
            opts["temperature"] = min(temperature, 0.6)
            opts["top_p"] = 0.95
        else:
            opts["top_p"] = 0.8

    return opts


class OllamaClient:
    """Asynchroner Client fuer die Ollama REST API mit per-Model Timeouts und Connection Pooling."""

    # Kontextfenster-Groesse (num_ctx) begrenzen.
    # Ollama allokiert KV-Cache fuer das volle Kontextfenster im VRAM,
    # auch wenn der Prompt kurz ist. Bei 8GB GPUs fuehrt der
    # Default (32768+) zu VRAM-Ueberlauf.
    # Qwen 3.5 MoE-Modelle sind effizienter, daher num_ctx angepasst.
    _DEFAULT_NUM_CTX = 4096
    _DEFAULT_NUM_CTX_FAST = 2048
    _DEFAULT_NUM_CTX_DEEP = 8192

    # Standard keep_alive: Modell nach 120s Idle aus VRAM entladen (spart ~10W GPU)
    _DEFAULT_KEEP_ALIVE = "120s"

    def __init__(self):
        self.base_url = settings.ollama_url
        # Shared Session (wird lazy initialisiert) — spart TCP-Handshake pro Request
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock: asyncio.Lock = asyncio.Lock()

    def num_ctx_for(self, model: str) -> int:
        """Liest num_ctx pro Modell-Tier aus yaml_config.

        Konfigurierbar in settings.yaml:
          ollama:
            num_ctx_fast: 2048
            num_ctx_smart: 4096
            num_ctx_deep: 8192
        """
        from .config import yaml_config
        ollama_cfg = yaml_config.get("ollama") or {}

        if model == settings.model_fast:
            return int(ollama_cfg.get("num_ctx_fast", self._DEFAULT_NUM_CTX_FAST))
        elif model == settings.model_deep:
            return int(ollama_cfg.get("num_ctx_deep", self._DEFAULT_NUM_CTX_DEEP))
        else:
            return int(ollama_cfg.get("num_ctx_smart", ollama_cfg.get("num_ctx", self._DEFAULT_NUM_CTX)))

    @property
    def num_ctx(self) -> int:
        """Liest num_ctx (Smart-Tier) aus yaml_config — Rueckwaertskompatibel."""
        from .config import yaml_config
        ollama_cfg = yaml_config.get("ollama") or {}
        return int(ollama_cfg.get("num_ctx_smart", ollama_cfg.get("num_ctx", self._DEFAULT_NUM_CTX)))

    @property
    def keep_alive(self) -> str:
        """Liest keep_alive aus yaml_config.

        Steuert wie lange Ollama ein Modell nach dem letzten Request im VRAM haelt.
        Kuerzere Werte sparen GPU-Strom im Idle (~10W bei RTX 3070).
        Konfigurierbar in settings.yaml unter ollama.keep_alive (z.B. '120s', '5m', '0').
        """
        from .config import yaml_config
        ollama_cfg = yaml_config.get("ollama") or {}
        return str(ollama_cfg.get("keep_alive", self._DEFAULT_KEEP_ALIVE))

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

        # Thinking Mode bestimmen
        # Qwen 3.5: Kann Thinking + Tools gleichzeitig
        # Qwen 3:   Tools stoeren Thinking → deaktivieren
        if think is not None:
            think_enabled = think
        elif model == settings.model_fast:
            think_enabled = False
        elif tools and not _is_qwen35(model):
            # Aeltere Modelle: Tools und Think vertragen sich nicht
            think_enabled = False
        elif model == settings.model_deep and settings.model_deep == settings.model_smart:
            think_enabled = False
        else:
            # Qwen 3.5 + Tools: Think bleibt an (native Unterstuetzung)
            # Deep ohne Tools: Think an
            think_enabled = None  # Ollama/Modell entscheidet

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": _model_options(
                model, temperature, max_tokens, self.num_ctx_for(model),
                think_enabled=bool(think_enabled),
            ),
        }

        if tools:
            payload["tools"] = tools

        if think_enabled is not None:
            payload["think"] = think_enabled

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

        # Thinking Mode (gleiche Logik wie chat())
        if think is not None:
            think_enabled = think
        elif model == settings.model_fast:
            think_enabled = False
        elif model == settings.model_deep and settings.model_deep == settings.model_smart:
            think_enabled = False
        else:
            think_enabled = None

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": _model_options(
                model, temperature, max_tokens, self.num_ctx_for(model),
                think_enabled=bool(think_enabled) if think_enabled is not None else False,
            ),
        }

        if think_enabled is not None:
            payload["think"] = think_enabled

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
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx_for(model),
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
