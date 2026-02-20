"""
Web Search - Optionale Web-Recherche fuer den Jarvis-Assistenten.

Features:
- SearXNG (self-hosted, Privacy-freundlich) — empfohlen
- DuckDuckGo HTML API als Fallback
- Ergebnisse als Kontext an LLM (RAG-Pattern)
- Config-Flag: web_search.enabled (default off)
- Privacy-First: Kein Tracking, kein Google

WICHTIG: Standardmaessig DEAKTIVIERT (lokales Prinzip bleibt erhalten).
Muss explizit in settings.yaml aktiviert werden.
"""

import logging
from typing import Optional
from urllib.parse import quote_plus

import aiohttp

from .config import yaml_config

logger = logging.getLogger(__name__)


class WebSearch:
    """Optionale Web-Recherche fuer Wissensfragen."""

    def __init__(self):
        # Konfiguration
        ws_cfg = yaml_config.get("web_search", {})
        self.enabled = ws_cfg.get("enabled", False)
        self.engine = ws_cfg.get("engine", "searxng")  # searxng oder duckduckgo
        self.searxng_url = ws_cfg.get("searxng_url", "http://localhost:8888")
        self.max_results = ws_cfg.get("max_results", 5)
        self.timeout = ws_cfg.get("timeout_seconds", 10)

    async def search(self, query: str) -> dict:
        """Fuehrt eine Web-Suche durch.

        Args:
            query: Suchanfrage

        Returns:
            Dict mit success, message (formatierte Ergebnisse), raw_results
        """
        if not self.enabled:
            return {
                "success": False,
                "message": "Web-Recherche ist deaktiviert. Aktiviere sie in der Konfiguration unter web_search.enabled.",
            }

        if not query or len(query.strip()) < 3:
            return {"success": False, "message": "Suchanfrage zu kurz."}

        try:
            if self.engine == "searxng":
                results = await self._search_searxng(query)
            else:
                results = await self._search_duckduckgo(query)

            if not results:
                return {"success": True, "message": f"Keine Ergebnisse fuer '{query}' gefunden."}

            # Ergebnisse formatieren
            lines = [f"Suchergebnisse fuer '{query}':"]
            for i, r in enumerate(results[:self.max_results], 1):
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                url = r.get("url", "")
                lines.append(f"{i}. {title}")
                if snippet:
                    lines.append(f"   {snippet}")

            return {
                "success": True,
                "message": "\n".join(lines),
                "raw_results": results[:self.max_results],
            }

        except Exception as e:
            logger.error("Web-Suche fehlgeschlagen: %s", e)
            return {"success": False, "message": f"Suche fehlgeschlagen: {e}"}

    async def _search_searxng(self, query: str) -> list[dict]:
        """Suche via SearXNG (self-hosted)."""
        url = f"{self.searxng_url}/search"
        params = {
            "q": query,
            "format": "json",
            "language": "de",
            "categories": "general",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                if resp.status != 200:
                    logger.warning("SearXNG returned %d", resp.status)
                    return []
                data = await resp.json()
                results = []
                for r in data.get("results", [])[:self.max_results]:
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("content", ""),
                        "url": r.get("url", ""),
                    })
                return results

    async def _search_duckduckgo(self, query: str) -> list[dict]:
        """Suche via DuckDuckGo Instant Answer API."""
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

                results = []

                # Abstract (Hauptergebnis)
                abstract = data.get("AbstractText", "")
                if abstract:
                    results.append({
                        "title": data.get("Heading", query),
                        "snippet": abstract,
                        "url": data.get("AbstractURL", ""),
                    })

                # Related Topics
                for topic in data.get("RelatedTopics", [])[:self.max_results - 1]:
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append({
                            "title": topic.get("Text", "")[:80],
                            "snippet": topic.get("Text", ""),
                            "url": topic.get("FirstURL", ""),
                        })

                return results
