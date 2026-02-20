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

# Muster fuer ungetaggtes LLM-Reasoning (englisch) vor der eigentlichen Antwort
_REASONING_LEAK_PATTERN = re.compile(
    r"^(?:"
    r"(?:Okay|Ok|Alright|So|Let me|I need to|First|The user|I should|I'll|Here)"
    r"[^\n]*\n)+"       # Englische Reasoning-Zeilen am Anfang
    r"[\s]*",            # Whitespace danach
    re.IGNORECASE,
)


def strip_think_tags(text: str) -> str:
    """Entfernt <think>...</think> Bloecke aus Qwen 3 Antworten."""
    if not text or "<think>" not in text:
        return text
    cleaned = _THINK_PATTERN.sub("", text).strip()
    return cleaned if cleaned else text


def strip_reasoning_leak(text: str) -> str:
    """Entfernt ungetaggtes englisches Reasoning das vor der Antwort steht.

    Manche Modelle (Qwen 3) geben gelegentlich ihren Denkprozess aus,
    ohne ihn in <think>-Tags zu wrappen. Diese Funktion erkennt typische
    Muster (englische Saetze wie 'Okay, let me...', 'First, I need to...')
    und entfernt sie, wenn die eigentliche Antwort (Deutsch) danach folgt.
    """
    if not text:
        return text

    # Think-Tags zuerst
    text = strip_think_tags(text)

    # Pruefen ob Text mit typischem englischen Reasoning beginnt
    # und ob danach noch deutscher Content kommt
    cleaned = _REASONING_LEAK_PATTERN.sub("", text).strip()
    if cleaned and cleaned != text.strip():
        logger.debug("Reasoning-Leak entfernt (%d → %d Zeichen)", len(text), len(cleaned))
        return cleaned

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
