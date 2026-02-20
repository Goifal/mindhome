"""
Ollama API Client - Kommunikation mit dem lokalen LLM

Qwen 3 Kompatibilitaet:
- Stripped automatisch <think>...</think> Bloecke aus Antworten
- Thinking Mode wird fuer Fast-Tier deaktiviert (spart Latenz)
"""

import logging
import re
from typing import Optional

import aiohttp

from .config import settings

logger = logging.getLogger(__name__)

# Regex zum Entfernen von Qwen 3 Think-Bloecken
_THINK_PATTERN = re.compile(r"<think>[\s\S]*?</think>\s*", re.DOTALL)

# Startwoerter die typisch fuer LLM-Reasoning sind
_REASONING_STARTERS = re.compile(
    r"^(?:Okay|Ok|Alright|So,?\s|Let me|I need|First|The user|I should"
    r"|I'll|I can|Here|Now|Wait|Hmm|This|Right|Well|Looking|My|In the"
    r"|The original|The key|Possible|Maybe|But)",
    re.IGNORECASE,
)


def strip_think_tags(text: str) -> str:
    """Entfernt <think>...</think> Bloecke aus Qwen 3 Antworten."""
    if not text or "<think>" not in text:
        return text
    cleaned = _THINK_PATTERN.sub("", text).strip()
    return cleaned if cleaned else text


def _is_reasoning_leak(text: str) -> bool:
    """Erkennt ob ein Text ein LLM-Reasoning-Leak ist statt einer echten Antwort.

    Heuristik: Wenn der Text mit englischem Reasoning beginnt UND
    entweder zu lang ist oder ueberwiegend Englisch ist, ist es ein Leak.
    """
    if not text or len(text) < 40:
        return False

    # Beginnt mit typischem Reasoning-Starter?
    if not _REASONING_STARTERS.match(text.strip()):
        return False

    # Anteil englischer Woerter pruefen (Jarvis-Meldungen sind Deutsch)
    eng_markers = [
        "let me", "i need", "the user", "i should", "first,",
        "original", "translate", "rephrase", "thinking", "analyze",
        "however", "therefore", "because", "which means", "so the",
        "probably", "maybe", "perhaps", "possible", "want to",
        "looking at", "understand", "check", "consider", "notice",
    ]
    text_lower = text.lower()
    eng_hits = sum(1 for m in eng_markers if m in text_lower)

    # >=3 englische Marker → definitiv Reasoning-Leak
    if eng_hits >= 3:
        return True

    # Text > 200 Zeichen + beginnt mit Reasoning-Starter → wahrscheinlich Leak
    if len(text) > 200 and eng_hits >= 1:
        return True

    return False


def strip_reasoning_leak(text: str) -> str:
    """Entfernt ungetaggtes LLM-Reasoning und gibt leeren String bei komplettem Leak.

    Manche Modelle (Qwen 3) geben gelegentlich ihren Denkprozess aus,
    ohne ihn in <think>-Tags zu wrappen. Diese Funktion:
    1. Entfernt <think>-Tags
    2. Entfernt englisches Reasoning-Prefix wenn deutsche Antwort folgt
    3. Gibt leeren String zurueck wenn der GESAMTE Text ein Leak ist
       (Caller faellt dann auf raw_message zurueck)
    """
    if not text:
        return text

    # Think-Tags zuerst
    text = strip_think_tags(text)

    # Komplett-Leak erkennen (gesamter Output ist Reasoning, keine Antwort)
    if _is_reasoning_leak(text):
        logger.warning(
            "Reasoning-Leak erkannt (%d Zeichen, Anfang: '%.60s...')",
            len(text), text,
        )
        # Versuchen: Letzte Zeile(n) koennten die eigentliche Antwort sein
        # (z.B. 'Sir, Phase C zieht etwas viel. Ich behalte das im Auge.')
        lines = text.strip().split("\n")
        for candidate in reversed(lines):
            candidate = candidate.strip().strip('"').strip("'").strip()
            if not candidate:
                continue
            # Kandidat ist kurz, auf Deutsch, und kein Reasoning
            if (
                10 < len(candidate) < 200
                and not _REASONING_STARTERS.match(candidate)
                and not any(w in candidate.lower() for w in ["let me", "i need", "the user", "i should"])
            ):
                logger.info("Reasoning-Leak: Letzte Zeile als Antwort: '%s'", candidate)
                return candidate
        # Kein brauchbarer Kandidat → leerer String (Caller nutzt Fallback)
        return ""

    return text


class OllamaClient:
    """Asynchroner Client fuer die Ollama REST API."""

    def __init__(self):
        self.base_url = settings.ollama_url

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
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
            },
        }

        if tools:
            payload["tools"] = tools

        # Qwen 3 Thinking Mode steuern
        # Bei Tools: Think aus (stoert Function Calling)
        # Bei Fast-Model: Think aus (spart Latenz)
        # Bei Deep-Model ohne Tools: Think an (besseres Reasoning)
        if think is not None:
            payload["think"] = think
        elif tools:
            payload["think"] = False
        elif model == settings.model_fast:
            payload["think"] = False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        logger.error("Ollama Fehler %d: %s", resp.status, error)
                        return {"error": error}
                    result = await resp.json()

                    # Think-Tags aus der Antwort strippen (Sicherheitsnetz)
                    msg = result.get("message", {})
                    content = msg.get("content", "")
                    if content and "<think>" in content:
                        cleaned = strip_think_tags(content)
                        logger.debug("Think-Tags entfernt (%d → %d Zeichen)",
                                     len(content), len(cleaned))
                        msg["content"] = cleaned

                    return result
        except aiohttp.ClientError as e:
            logger.error("Ollama nicht erreichbar: %s", e)
            return {"error": str(e)}

    async def stream_chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
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
        model = model or settings.model_smart

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if think is not None:
            payload["think"] = think
        elif model == settings.model_fast:
            payload["think"] = False

        in_think_block = False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        logger.error("Ollama Stream Fehler %d: %s", resp.status, error)
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
                        if not content:
                            if data.get("done"):
                                break
                            continue

                        # Think-Tags im Stream filtern
                        if "<think>" in content:
                            in_think_block = True
                            continue
                        if "</think>" in content:
                            in_think_block = False
                            continue
                        if in_think_block:
                            continue

                        yield content

                        if data.get("done"):
                            break

        except aiohttp.ClientError as e:
            logger.error("Ollama Stream nicht erreichbar: %s", e)

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
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
        model = model or settings.model_smart

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        logger.error("Ollama Generate Fehler %d: %s", resp.status, error)
                        return ""
                    result = await resp.json()
                    text = result.get("response", "")
                    return strip_think_tags(text)
        except aiohttp.ClientError as e:
            logger.error("Ollama Generate nicht erreichbar: %s", e)
            return ""

    async def is_available(self) -> bool:
        """Prueft ob Ollama erreichbar ist."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except aiohttp.ClientError:
            return False

    async def list_models(self) -> list[str]:
        """Listet alle verfuegbaren Modelle."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags") as resp:
                    data = await resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except aiohttp.ClientError:
            return []
