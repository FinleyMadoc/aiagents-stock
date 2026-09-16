#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone NewsAPI connectivity and configuration diagnostic."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from international_news import InternationalNewsFetcher


def main() -> int:
    key = os.getenv("NEWSAPI_API_KEY", "").strip()
    print(f"NEWSAPI_API_KEY: {'configured' if key else 'missing'}")
    print(
        "NEWSAPI_BASE_URL: "
        + os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2/everything")
    )
    if not key:
        print("诊断结束：容器环境没有读取到 NEWSAPI_API_KEY。")
        return 2

    now = datetime.now(timezone.utc)
    result = InternationalNewsFetcher(newsapi_key=key).fetch_newsapi(
        query='"China" AND (economy OR finance OR technology)',
        start=now - timedelta(days=3),
        end=now,
        max_records=5,
        language="en",
    )
    print(f"status: {'ok' if result.get('success') else 'error'}")
    print(f"count: {result.get('count', 0)}")
    if result.get("error"):
        print(f"error: {result['error']}")
        return 1
    for article in result.get("articles", [])[:5]:
        print(f"- {article.get('published_at')} | {article.get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
