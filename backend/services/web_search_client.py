import asyncio
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class WebSearchError(Exception):
    pass


class WebSearchClient:
    """
    Lightweight async web search wrapper.
    Tries (in order):
      - SerpAPI (if SERPAPI_KEY set)
      - Bing Web Search API (if BING_API_KEY set)
      - DuckDuckGo HTML scraping fallback (no API key)
    Methods:
      - search(query, limit=10) -> List[Dict[str, Any]]
      - fetch_snippet(url) -> str (basic html fetch + text extraction)
    """

    def __init__(
        self,
        serpapi_key: Optional[str] = None,
        bing_key: Optional[str] = None,
        timeout: float = 15.0,
        max_retries: int = 2,
        backoff: float = 0.5,
    ) -> None:
        self.serpapi_key = serpapi_key
        self.bing_key = bing_key
        self._client = httpx.AsyncClient(timeout=timeout)
        self.max_retries = max_retries
        self.backoff = backoff

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                sleep = self.backoff * (2 ** attempt)
                logger.debug("web_search_client request failed, retrying in %.2fs (%d): %s", sleep, attempt + 1, exc)
                await asyncio.sleep(sleep)
        raise WebSearchError(f"Request failed for {url}") from last_exc

    async def _serpapi_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        # SerpAPI JSON endpoint (Google engine)
        params = {"engine": "google", "q": query, "num": limit, "api_key": self.serpapi_key}
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
        resp = await self._request("GET", url)
        j = resp.json()
        results = []
        for item in j.get("organic_results", [])[:limit]:
            results.append(
                {
                    "title": item.get("title"),
                    "link": item.get("link") or item.get("url"),
                    "snippet": item.get("snippet") or item.get("snippet_highlighted"),
                    "source": "serpapi",
                }
            )
        return results

    async def _bing_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        # Bing Web Search API (Azure) - subscription key in header
        params = {"q": query, "count": limit}
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.bing_key}
        resp = await self._request("GET", url, params=params, headers=headers)
        j = resp.json()
        results = []
        web_pages = j.get("webPages", {}).get("value", [])
        for item in web_pages[:limit]:
            results.append({"title": item.get("name"), "link": item.get("url"), "snippet": item.get("snippet"), "source": "bing"})
        return results

    async def _duckduckgo_scrape(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        # Simple DuckDuckGo HTML fallback parsing. Best-effort; fragile.
        q = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/html/?q={q}"
        resp = await self._request("GET", url, headers={"User-Agent": "iba-bot/1.0"})
        html = resp.text
        results: List[Dict[str, Any]] = []
        # crude regex to extract titles/links/snippets from DuckDuckGo "result" blocks
        # matches <a rel="noopener" class="result__a" href="...">Title</a>
        links = re.findall(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S)
        snippets = re.findall(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>.*?</a>\s*<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, flags=re.I | re.S)
        # fallback simpler snippet extraction
        if not snippets:
            snippets = re.findall(r'<div class="result__snippet">(.*?)</div>', html, flags=re.I | re.S)
        # build combined results
        for i, (link, title_html) in enumerate(links[:limit]):
            title = re.sub("<.*?>", "", title_html).strip()
            snippet = re.sub("<.*?>", "", snippets[i].strip()) if i < len(snippets) else ""
            results.append({"title": title, "link": urllib.parse.unquote(link), "snippet": snippet, "source": "duckduckgo"})
        return results

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Perform a search and return list of {title, link, snippet, source}.
        """
        if not query:
            return []

        # prefer SerpAPI
        if self.serpapi_key:
            try:
                return await self._serpapi_search(query, limit=limit)
            except Exception as e:
                logger.warning("SerpAPI search failed, falling back: %s", e)

        # try Bing
        if self.bing_key:
            try:
                return await self._bing_search(query, limit=limit)
            except Exception as e:
                logger.warning("Bing search failed, falling back: %s", e)

        # final fallback: DuckDuckGo scrape
        try:
            return await self._duckduckgo_scrape(query, limit=limit)
        except Exception as e:
            logger.exception("DuckDuckGo scrape failed: %s", e)
            raise WebSearchError("All search providers failed") from e

    async def fetch_snippet(self, url: str, max_chars: int = 2000) -> str:
        """
        Fetch URL and return a best-effort textual snippet (stripped HTML).
        """
        try:
            resp = await self._request("GET", url, headers={"User-Agent": "iba-bot/1.0"})
            text = resp.text
            # strip tags (naive)
            snippet = re.sub(r"<script.*?</script>", "", text, flags=re.S | re.I)
            snippet = re.sub(r"<style.*?</style>", "", snippet, flags=re.S | re.I)
            snippet = re.sub(r"<[^>]+>", " ", snippet)
            snippet = re.sub(r"\s+", " ", snippet).strip()
            return snippet[:max_chars]
        except Exception as e:
            logger.debug("fetch_snippet failed for %s: %s", url, e)
            return ""


# module-level default client using env/config
_default_client: Optional[WebSearchClient] = None


def _get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        from ..core import config as core_config  # type: ignore
        return getattr(core_config.settings, name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


def _ensure_default_client() -> WebSearchClient:
    global _default_client
    if _default_client is None:
        serp = _get_setting("SERPAPI_KEY")
        bing = _get_setting("BING_API_KEY")
        _default_client = WebSearchClient(serpapi_key=serp, bing_key=bing)
    return _default_client


# convenience wrappers
async def search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    client = _ensure_default_client()
    return await client.search(query=query, limit=limit)


async def fetch_snippet(url: str, max_chars: int = 2000) -> str:
    client = _ensure_default_client()
    return await client.fetch_snippet(url=url, max_chars=max_chars)
