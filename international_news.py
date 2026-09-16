#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""International finance news adapter for the A-share mainline analyzer.

NewsAPI is the active international-news provider. The legacy GDELT adapter is
kept for compatibility, but the combined fetch path does not call it unless
the caller explicitly opts in.

Provider failures are returned as structured status data instead of aborting the
whole market analysis.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover - production requirements include requests
    requests = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - production requirements include python-dotenv
    pass

logger = logging.getLogger(__name__)


DEFAULT_INTERNATIONAL_QUERY = (
    "(China OR Chinese OR Beijing OR Shanghai OR Asia) AND "
    "(agriculture OR farming OR metals OR mining OR copper OR aluminium OR "
    "oil OR gas OR energy OR technology OR chip OR semiconductor OR "
    "memory OR storage OR artificial intelligence OR commodities OR "
    "trade OR policy OR tariff)"
)

NEWSAPI_FALLBACK_QUERY = (
    "agriculture OR farming OR metals OR mining OR copper OR aluminium OR "
    "oil OR gas OR energy OR technology OR chip OR semiconductor OR memory "
    "OR storage OR artificial intelligence OR commodities"
)


class InternationalNewsFetcher:
    """Fetch, normalize and de-duplicate international news articles."""

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: Optional[float] = None,
        gdelt_url: Optional[str] = None,
        newsapi_url: Optional[str] = None,
        newsapi_key: Optional[str] = None,
    ):
        if session is not None:
            self.session = session
        elif requests is not None:
            self.session = requests.Session()
        else:
            raise RuntimeError(
                "requests is required for live international news fetching; "
                "install project requirements first"
            )
        self.timeout = float(timeout or os.getenv("INTERNATIONAL_NEWS_TIMEOUT", "15"))
        self.gdelt_url = gdelt_url or os.getenv(
            "GDELT_DOC_API_URL", "https://api.gdeltproject.org/api/v2/doc/doc"
        )
        self.newsapi_url = newsapi_url or os.getenv(
            "NEWSAPI_BASE_URL", "https://newsapi.org/v2/everything"
        )
        self.newsapi_key = (
            newsapi_key if newsapi_key is not None else os.getenv("NEWSAPI_API_KEY", "")
        ).strip()

    def fetch(
        self,
        query: Optional[str] = None,
        days: int = 7,
        max_records: int = 50,
        include_newsapi: bool = True,
        include_gdelt: bool = False,
        language: str = "en",
    ) -> Dict[str, Any]:
        """Fetch international news, using NewsAPI unless GDELT is opted in."""
        query = (query or os.getenv("INTERNATIONAL_NEWS_QUERY") or DEFAULT_INTERNATIONAL_QUERY).strip()
        days = max(1, min(int(days), 30))
        max_records = max(1, min(int(max_records), 100))

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        source_results: List[Dict[str, Any]] = []

        if include_gdelt:
            source_results.append(
                self.fetch_gdelt(
                    query=query,
                    start=start,
                    end=end,
                    max_records=max_records,
                )
            )
        else:
            source_results.append(
                {
                    "source": "gdelt",
                    "enabled": False,
                    "success": False,
                    "count": 0,
                    "articles": [],
                    "error": "disabled",
                }
            )
        if include_newsapi:
            newsapi_result = self.fetch_newsapi(
                query=query,
                start=start,
                end=end,
                max_records=max_records,
                language=language,
            )
            # The China/Asia condition is useful for precision, but can be too
            # restrictive for international commodity and technology coverage.
            if newsapi_result.get("success") and not newsapi_result.get("count"):
                fallback_result = self.fetch_newsapi(
                    query=NEWSAPI_FALLBACK_QUERY,
                    start=start,
                    end=end,
                    max_records=max_records,
                    language=language,
                )
                if fallback_result.get("count", 0):
                    fallback_result["fallback_query"] = NEWSAPI_FALLBACK_QUERY
                    newsapi_result = fallback_result
                elif not fallback_result.get("success"):
                    newsapi_result["fallback_error"] = fallback_result.get(
                        "error", "fallback request failed"
                    )
            source_results.append(newsapi_result)
            logger.info(
                "NewsAPI fetched %s articles (query=%s)",
                newsapi_result.get("count", 0),
                newsapi_result.get("query", query)[:180],
            )
            if newsapi_result.get("error"):
                logger.warning(
                    "NewsAPI request failed: %s", newsapi_result["error"]
                )
            elif newsapi_result.get("fallback_error"):
                logger.warning(
                    "NewsAPI fallback request failed: %s",
                    newsapi_result["fallback_error"],
                )
        else:
            source_results.append(
                {
                    "source": "newsapi",
                    "enabled": False,
                    "success": False,
                    "articles": [],
                "error": "disabled",
            }
            )

        articles = self._deduplicate(
            article
            for result in source_results
            for article in result.get("articles", [])
        )
        return {
            "success": bool(articles),
            "query": query,
            "days": days,
            "count": len(articles),
            "articles": articles[:max_records * 2],
            "sources": source_results,
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    def fetch_gdelt(
        self,
        query: str,
        start: datetime,
        end: datetime,
        max_records: int = 50,
    ) -> Dict[str, Any]:
        """Fetch articles from the public GDELT DOC endpoint."""
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": max_records,
            "sort": "HybridRel",
            "startdatetime": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
        }
        try:
            response = self.session.get(self.gdelt_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("articles", []) if isinstance(payload, dict) else []
            articles = [
                self._normalize_article(row, provider="gdelt")
                for row in rows
                if isinstance(row, dict)
            ]
            return {
                "source": "gdelt",
                "enabled": True,
                "success": True,
                "count": len(articles),
                "articles": articles,
            }
        except Exception as exc:
            logger.warning("GDELT fetch failed: %s", exc)
            return {
                "source": "gdelt",
                "enabled": True,
                "success": False,
                "count": 0,
                "articles": [],
                "error": str(exc),
            }

    def fetch_newsapi(
        self,
        query: str,
        start: datetime,
        end: datetime,
        max_records: int = 50,
        language: str = "en",
    ) -> Dict[str, Any]:
        """Fetch articles from NewsAPI when an API key is available."""
        if not self.newsapi_key:
            return {
                "source": "newsapi",
                "enabled": False,
                "success": False,
                "count": 0,
                "articles": [],
                "query": query,
                "error": "NEWSAPI_API_KEY is not configured",
            }

        params = {
            "q": query,
            "from": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": max_records,
        }
        # AkShare applies a global requests patch in this project. Override its
        # browser-oriented headers for NewsAPI so the API receives JSON
        # negotiation headers and never requests Brotli unless explicitly
        # supported by the runtime.
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "aiagents-stock-news-client/1.0",
            "X-Api-Key": self.newsapi_key,
        }
        try:
            response = self.session.get(
                self.newsapi_url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            http_status = getattr(response, "status_code", None)
            content_type = str(
                getattr(response, "headers", {}).get("Content-Type", "")
            )
            try:
                payload = response.json()
            except ValueError as exc:
                body_preview = self._response_preview(
                    response, secret=self.newsapi_key
                )
                raise RuntimeError(
                    "NewsAPI returned non-JSON response"
                    f" (HTTP {http_status}, Content-Type: {content_type or 'unknown'}, "
                    f"body: {body_preview})"
                ) from exc

            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"NewsAPI returned unexpected JSON payload "
                    f"(HTTP {http_status}, type: {type(payload).__name__})"
                )

            if http_status is not None and http_status >= 400:
                raise RuntimeError(
                    f"NewsAPI HTTP {http_status}: "
                    f"{payload.get('code', 'unknown')} - "
                    f"{payload.get('message', 'request failed')}"
                )
            if payload.get("status") != "ok":
                raise RuntimeError(
                    f"NewsAPI {payload.get('code', 'error')}: "
                    f"{payload.get('message', 'request failed')}"
                )
            rows = payload.get("articles", [])
            articles = [
                self._normalize_article(row, provider="newsapi")
                for row in rows
                if isinstance(row, dict)
            ]
            return {
                "source": "newsapi",
                "enabled": True,
                "success": True,
                "count": len(articles),
                "articles": articles,
                "query": query,
                "http_status": http_status,
            }
        except Exception as exc:
            logger.warning("NewsAPI fetch failed: %s", exc)
            return {
                "source": "newsapi",
                "enabled": True,
                "success": False,
                "count": 0,
                "articles": [],
                "query": query,
                "error": str(exc),
            }

    @staticmethod
    def _response_preview(
        response: Any, limit: int = 240, secret: str = ""
    ) -> str:
        """Return a safe, short response preview for diagnostics."""
        try:
            text = str(getattr(response, "text", "") or "")
        except Exception:
            text = ""
        text = re.sub(r"\s+", " ", text).strip()
        if secret:
            text = text.replace(secret, "[REDACTED]")
        if not text:
            return "<empty body>"
        return text[:limit]

    def _normalize_article(self, row: Dict[str, Any], provider: str) -> Dict[str, Any]:
        if provider == "newsapi":
            source = row.get("source") or {}
            title = row.get("title", "")
            url = row.get("url", "")
            published_at = row.get("publishedAt", "")
            description = row.get("description", "")
            source_name = source.get("name", "") if isinstance(source, dict) else str(source)
            language = "en"
            domain = self._domain(url)
        else:
            title = row.get("title", "")
            url = row.get("url", "")
            published_at = row.get("seendate", "")
            description = row.get("snippet", "") or row.get("content", "")
            source_name = row.get("domain", "") or row.get("sourcecountry", "")
            language = row.get("language", "")
            domain = row.get("domain", "") or self._domain(url)

        text = " ".join(
            part.strip()
            for part in (str(title or ""), str(description or ""))
            if part and str(part).strip()
        )
        return {
            "id": self._article_id(url, title),
            "provider": provider,
            "source": source_name,
            "domain": domain,
            "title": str(title or "").strip(),
            "description": str(description or "").strip(),
            "url": str(url or "").strip(),
            "published_at": str(published_at or "").strip(),
            "language": str(language or "").strip(),
            "text": text,
            "topic_tags": self._topic_tags(text),
        }

    @staticmethod
    def _article_id(url: str, title: str) -> str:
        value = (url or title or "").strip().lower()
        value = re.sub(r"\s+", " ", value)
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _domain(url: str) -> str:
        match = re.search(r"https?://([^/]+)", str(url or ""))
        return match.group(1).lower() if match else ""

    @staticmethod
    def _topic_tags(text: str) -> List[str]:
        checks = {
            "中国宏观": ("china", "chinese", "beijing", "policy", "economy"),
            "科技与AI": ("artificial intelligence", " ai ", "semiconductor", "chip", "robot"),
            "利率与流动性": ("fed", "interest rate", "yield", "liquidity", "inflation"),
            "贸易与地缘": ("tariff", "trade", "sanction", "geopolit", "export control"),
            "能源与资源": ("oil", "gas", "copper", "gold", "commodity", "energy"),
        }
        normalized = f" {text.lower()} "
        return [
            tag
            for tag, keywords in checks.items()
            if any(keyword in normalized for keyword in keywords)
        ]

    @staticmethod
    def _deduplicate(articles: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        result = []
        for article in articles:
            key = article.get("url") or article.get("id") or article.get("title")
            key = str(key).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(article)
        return result
