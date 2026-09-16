#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-share weekly/monthly mainline analysis.

This module combines:
- pywencai through ``main_force_selector`` for stock-level main-force flow;
- AkShare through ``SectorStrategyDataFetcher`` for sectors and market breadth;
- domestic 7x24 finance news through AkShare;
- NewsAPI through ``InternationalNewsFetcher`` for international news.

The returned object is JSON-serializable and can be used by Streamlit, a
scheduler, or the command line. AI is an enhancement, not a hard dependency:
without a DeepSeek key the deterministic baseline still returns a useful
structure and candidate pool.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from international_news import InternationalNewsFetcher

logger = logging.getLogger(__name__)


MAINLINE_SYSTEM_PROMPT = """你是一名中国A股顶级市场结构研究员，拥有15年以上市场交易与盘面分析经验，深度理解以下体系：

A股题材炒作与主线演化逻辑
游资、机构、量化资金的典型行为特征
涨停板、连板梯队、趋势中军、补涨股之间的联动关系
情绪周期的冰点、修复、主升、高位震荡、退潮等阶段特征
资金抱团、分歧转一致、一致转分歧、强趋势与弱轮动的盘口差异
政策驱动、产业催化、事件刺激、海外映射对A股主线形成的影响

你的任务是：基于提供的市场数据、资金流、板块表现、国内新闻和国际新闻，识别当前A股真正的交易主线，并输出具备交易指导意义的结构化结论。

严格要求：
1. 先判断市场环境，再判断主线；不能只根据新闻热度下结论。
2. 区分真正主线、次级热点、脉冲题材和跟风分支。
3. 区分情绪龙头、趋势中军、补涨标的和跟风后排。
4. 判断情绪周期并给出数据依据；数据缺失时明确写“数据不足”。
5. 主线持续性必须从产业逻辑、事件催化、资金合力三方面评估。
6. 新闻只能作为催化证据，不能替代资金承接和板块扩散。
7. 板块优先关注农业、金属、矿产、油气、科技、芯片半导体和存储等方向，
   同时区分行业板块和概念题材，只有二者交叉确认时才提高信心。
8. 主力资金是第一证据，板块行情和概念题材是确认，国内/国际新闻只是催化，
   新闻热度不能替代资金承接。
9. 所有股票推荐只能来自输入股票池，且只能选择6或3开头的股票代码。
10. 必须严格分开本周和本月结论；没有明确主线时，必须写
    “主线不清、轮动为主、降低预期”。
11. 输出必须是纯JSON，不要Markdown代码围栏。
"""


SECTOR_ALIASES = {
    "农业": (
        "农业", "种植", "林业", "畜牧", "养殖", "农产品", "饲料", "农药",
        "化肥", "农业服务", "farming", "agriculture",
    ),
    "矿产": (
        "矿产", "采掘", "矿业", "煤炭", "锂矿", "磷矿", "钴矿", "锰矿",
        "矿石", "mining", "mineral", "coal",
    ),
    "金属": (
        "金属", "有色", "钢铁", "铜", "铝", "锌", "铅", "镍", "钴",
        "稀土", "黄金", "白银", "metal", "copper", "aluminium", "gold",
        "silver",
    ),
    "油气": (
        "石油", "石化", "油气", "天然气", "燃气", "原油", "炼化", "oil",
        "gas", "petroleum",
    ),
    "存储": (
        "存储", "memory", "storage", "nand", "dram", "hbm", "固态硬盘",
        "硬盘",
    ),
    "半导体": (
        "半导体", "芯片", "集成电路", "光刻机", "semiconductor", "chip",
        "foundry", "wafer",
    ),
    "芯片半导体": (
        "半导体", "芯片", "集成电路", "光刻", "封测", "晶圆", "硅片",
        "芯片设计", "先进封装", "semiconductor", "chip",
    ),
    "人工智能": (
        "人工智能", "ai", "artificial intelligence", "大模型", "算力",
        "machine learning", "data center",
    ),
    "科技": (
        "科技", "软件", "计算机", "通信", "电子", "人工智能", "算力",
        "云计算", "数据中心", "机器人", "智能", "互联网", "信息技术",
        "technology", "software", "robot",
    ),
    "机器人": ("机器人", "人形机器人", "robot", "automation", "humanoid"),
    "低空经济": ("低空经济", "无人机", "eVTOL", "drone", "urban air mobility"),
    "新能源": (
        "新能源", "锂电", "电池", "光伏", "储能", "solar", "battery",
        "energy storage",
    ),
    "军工": ("军工", "航空航天", "航天", "defense", "aerospace"),
    "贵金属": ("黄金", "白银", "贵金属", "gold", "silver", "precious metal"),
    "有色金属": ("有色", "铜", "铝", "锂", "copper", "aluminium", "mining"),
    "医药": ("医药", "创新药", "医疗", "pharma", "biotech", "drug"),
    "消费": ("消费", "零售", "白酒", "消费电子", "consumer", "retail"),
    "金融": ("银行", "证券", "保险", "金融", "bank", "broker", "insurance"),
    "房地产": ("房地产", "地产", "property", "real estate"),
}

FOCUS_THEME_ORDER = (
    "农业",
    "矿产",
    "油气",
    "存储",
    "芯片半导体",
    "金属",
    "科技",
)


def _to_number(value: Any) -> Optional[float]:
    """Convert common Chinese finance strings to a number."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "").replace("，", "")
    if not text or text in {"-", "--", "N/A", "nan", "None", "无"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    if "亿" in text:
        number *= 100000000
    elif "万" in text:
        number *= 10000
    elif "千" in text:
        number *= 1000
    return number


def _first_column(columns: Iterable[Any], patterns: Sequence[str]) -> Optional[str]:
    columns = [str(column) for column in columns]
    for pattern in patterns:
        for column in columns:
            if pattern == column or pattern in column:
                return column
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _records(value: Any, limit: int = 200) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        return [_json_safe(row) for row in value.head(limit).to_dict("records")]
    if isinstance(value, list):
        return [_json_safe(row) if isinstance(row, dict) else {"value": _json_safe(row)} for row in value[:limit]]
    if isinstance(value, dict):
        return [_json_safe(value)]
    return []


class MainlineAnalyzer:
    """Collect market evidence and produce the eight-section mainline report."""

    def __init__(
        self,
        selector: Any = None,
        sector_fetcher: Any = None,
        international_fetcher: Optional[InternationalNewsFetcher] = None,
        model: Optional[str] = None,
    ):
        self.selector = selector
        self.sector_fetcher = sector_fetcher
        if international_fetcher is not None:
            self.international_fetcher = international_fetcher
        else:
            try:
                import config

                self.international_fetcher = InternationalNewsFetcher(
                    timeout=config.INTERNATIONAL_NEWS_TIMEOUT,
                    gdelt_url=config.GDELT_DOC_API_URL,
                    newsapi_url=config.NEWSAPI_BASE_URL,
                    newsapi_key=config.NEWSAPI_API_KEY,
                )
            except Exception:
                self.international_fetcher = InternationalNewsFetcher()
        self._newsapi_only = False
        self.model = model

    def collect_snapshot(
        self,
        international_days: int = 7,
        min_market_cap: float = 50,
        max_market_cap: float = 5000,
        international_query: Optional[str] = None,
        include_newsapi: bool = True,
    ) -> Dict[str, Any]:
        """Collect all evidence. Individual source failures are isolated."""
        now = datetime.now()
        weekly_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - pd.Timedelta(days=now.weekday())
        monthly_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        weekly = self._fetch_main_force(
            start_date=weekly_start.strftime("%Y年%m月%d日"),
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
        )
        monthly = self._fetch_main_force(
            start_date=monthly_start.strftime("%Y年%m月%d日"),
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
        )
        domestic = self._fetch_domestic_market_data(domestic_news_days=7)
        international = self.international_fetcher.fetch(
            query=international_query,
            days=max(int(international_days), 1),
            max_records=50,
            include_newsapi=include_newsapi,
        )

        return {
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "windows": {
                "weekly_start": weekly_start.strftime("%Y-%m-%d"),
                "monthly_start": monthly_start.strftime("%Y-%m-%d"),
                "domestic_news_days": 7,
                "international_days": international_days,
            },
            "main_force": {
                "weekly": weekly,
                "monthly": monthly,
            },
            "domestic_market": domestic,
            "international_news": international,
            "source_status": {
                "pywencai_weekly": weekly.get("success", False),
                "pywencai_monthly": monthly.get("success", False),
                "akshare_market": domestic.get("success", False),
                "gdelt": self._provider_status(international, "gdelt"),
                "newsapi": self._provider_status(international, "newsapi"),
            },
            "source_diagnostics": {
                "pywencai_weekly": {
                    "status": "ok" if weekly.get("success") else "error",
                    "message": weekly.get("message", ""),
                    "count": weekly.get("count", 0),
                },
                "pywencai_monthly": {
                    "status": "ok" if monthly.get("success") else "error",
                    "message": monthly.get("message", ""),
                    "count": monthly.get("count", 0),
                },
                "akshare": domestic.get("diagnostics", {}),
                "gdelt": self._international_diagnostic(international, "gdelt"),
                "newsapi": self._international_diagnostic(international, "newsapi"),
            },
        }

    def analyze_snapshot(
        self,
        snapshot: Dict[str, Any],
        top_n: int = 10,
        include_ai: bool = True,
        thinking_mode: bool = False,
        reasoning_effort: str = "high",
    ) -> Dict[str, Any]:
        """Turn a collected snapshot into structured analysis and a stock pool."""
        themes = self._build_theme_scores(snapshot)
        sector_stock_picks = self._build_sector_stock_picks(
            snapshot, themes, sector_limit=5, per_sector=10
        )
        recommendations = self._flatten_sector_picks(
            sector_stock_picks, limit=max(1, top_n)
        )
        fallback = self._build_fallback_analysis(snapshot, themes, recommendations)

        analysis = fallback
        ai_used = False
        if include_ai:
            ai_analysis = self._run_llm_analysis(
                snapshot=snapshot,
                themes=themes,
                recommendations=recommendations,
                fallback=fallback,
                thinking_mode=thinking_mode,
                reasoning_effort=reasoning_effort,
            )
            if ai_analysis:
                analysis = self._merge_analysis(fallback, ai_analysis)
                ai_used = True

        return {
            "success": True,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ai_used": ai_used,
            "thinking_mode": bool(thinking_mode and ai_used),
            "reasoning_effort": reasoning_effort if thinking_mode and ai_used else None,
            "analysis": analysis,
            "themes": themes,
            "recommendations": recommendations,
            "sector_stock_picks": sector_stock_picks,
            "mainline_summary": self._build_mainline_summary(sector_stock_picks),
            "report": self.format_report(analysis, recommendations),
            "snapshot": _json_safe(snapshot),
        }

    def run(
        self,
        international_days: int = 7,
        min_market_cap: float = 50,
        max_market_cap: float = 5000,
        top_n: int = 10,
        include_ai: bool = True,
        include_newsapi: bool = True,
        thinking_mode: bool = False,
        reasoning_effort: str = "high",
        international_query: Optional[str] = None,
        output_path: Optional[str] = None,
        save_history: bool = True,
        history_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        snapshot = self.collect_snapshot(
            international_days=international_days,
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
            international_query=international_query,
            include_newsapi=include_newsapi,
        )
        result = self.analyze_snapshot(
            snapshot,
            top_n=top_n,
            include_ai=include_ai,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
        )
        if save_history:
            try:
                from mainline_history import MainlineHistoryStore

                history_store = MainlineHistoryStore(
                    directory=history_dir or getattr(
                        config, "MAINLINE_HISTORY_DIR", "data/mainline/history"
                    ),
                    limit=getattr(config, "MAINLINE_HISTORY_LIMIT", 100),
                )
                history_store.save(result)
            except Exception as exc:
                logger.warning("mainline history save failed: %s", exc)
        if output_path:
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(_json_safe(result), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return result

    def _fetch_main_force(
        self,
        start_date: Optional[str],
        min_market_cap: float,
        max_market_cap: float,
    ) -> Dict[str, Any]:
        try:
            if self.selector is None:
                from main_force_selector import main_force_selector

                self.selector = main_force_selector
            success, data, message = self.selector.get_main_force_stocks(
                start_date=start_date,
                min_market_cap=min_market_cap,
                max_market_cap=max_market_cap,
            )
            return {
                "success": bool(success and data is not None and not data.empty),
                "message": message,
                "count": int(len(data)) if isinstance(data, pd.DataFrame) else 0,
                "records": _records(data),
            }
        except Exception as exc:
            logger.warning("pywencai main-force fetch failed (%s): %s", start_date, exc)
            return {
                "success": False,
                "message": str(exc),
                "count": 0,
                "records": [],
            }

    def _fetch_domestic_market_data(self, domestic_news_days: int = 7) -> Dict[str, Any]:
        """Reuse the existing AkShare sector fetcher without triggering its AI research."""
        try:
            if self.sector_fetcher is None:
                from sector_strategy_data import SectorStrategyDataFetcher

                self.sector_fetcher = SectorStrategyDataFetcher()

            fetcher = self.sector_fetcher
            diagnostics: Dict[str, Any] = {}
            data = {}
            for key, method_name, default in (
                ("sectors", "_get_sector_performance", {}),
                ("concepts", "_get_concept_performance", {}),
                ("sector_fund_flow", "_get_sector_fund_flow", {}),
                ("market_overview", "_get_market_overview", {}),
            ):
                value, diagnostic = self._call_domestic_method(
                    fetcher, method_name, default
                )
                data[key] = value
                diagnostics[key] = diagnostic

            news, news_diagnostic = self._fetch_domestic_news_with_diagnostic(
                fetcher, days=domestic_news_days
            )
            data["news"] = news
            diagnostics["news"] = news_diagnostic
            return {
                "success": any(bool(value) for value in data.values()),
                "diagnostics": diagnostics,
                **_json_safe(data),
            }
        except Exception as exc:
            logger.warning("AkShare domestic market fetch failed: %s", exc)
            return {
                "success": False,
                "error": str(exc),
                "sectors": {},
                "concepts": {},
                "sector_fund_flow": {},
                "market_overview": {},
                "news": [],
                "diagnostics": {
                    "collector": {"status": "error", "message": str(exc)}
                },
            }

    @staticmethod
    def _call_domestic_method(
        fetcher: Any, name: str, default: Any
    ) -> Tuple[Any, Dict[str, Any]]:
        try:
            method = getattr(fetcher, name)
            value = method()
            return value, {
                "status": "ok" if value else "empty",
                "count": MainlineAnalyzer._value_count(value),
            }
        except Exception as exc:
            logger.warning("%s failed: %s", name, exc)
            return default, {"status": "error", "message": str(exc), "count": 0}

    @staticmethod
    def _value_count(value: Any) -> int:
        if isinstance(value, dict):
            if isinstance(value.get("today"), list):
                return len(value["today"])
            return len(value)
        if isinstance(value, (list, tuple, set)):
            return len(value)
        try:
            return int(len(value))
        except (TypeError, AttributeError):
            return 1 if value else 0

    def _fetch_domestic_news(self, fetcher: Any) -> List[Dict[str, Any]]:
        """Combine the existing AkShare global finance news and CLS 7x24 feed."""
        news, _ = self._fetch_domestic_news_with_diagnostic(fetcher)
        return news

    def _fetch_domestic_news_with_diagnostic(
        self, fetcher: Any, days: int = 7
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        diagnostics: Dict[str, Any] = {}
        news: List[Dict[str, Any]] = []
        existing, existing_diagnostic = self._call_domestic_method(
            fetcher, "_get_financial_news", []
        )
        diagnostics["eastmoney_finance_news"] = existing_diagnostic
        news.extend(_records(existing, limit=150))

        try:
            import akshare as ak

            cls_df = ak.stock_info_global_cls()
            diagnostics["cls_7x24"] = {
                "status": "ok" if cls_df is not None and not cls_df.empty else "empty",
                "count": int(len(cls_df)) if cls_df is not None else 0,
            }
            if cls_df is not None and not cls_df.empty:
                for row in cls_df.head(150).to_dict("records"):
                    news.append(
                        {
                            "title": row.get("标题", row.get("title", "")),
                            "content": row.get("内容", row.get("content", "")),
                            "publish_time": row.get("发布时间", row.get("time", "")),
                            "source": "财联社7x24",
                            "url": row.get("链接", row.get("url", "")),
                        }
                    )
        except Exception as exc:
            logger.warning("CLS 7x24 news fetch failed: %s", exc)
            diagnostics["cls_7x24"] = {
                "status": "error",
                "message": str(exc),
                "count": 0,
            }

        seen = set()
        result = []
        for item in news:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", item.get("新闻标题", "")) or "").strip()
            url = str(item.get("url", item.get("新闻链接", "")) or "").strip()
            key = (url or title).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "title": title,
                    "content": str(item.get("content", item.get("新闻内容", "")) or "").strip(),
                    "publish_time": str(
                        item.get("publish_time", item.get("发布时间", "")) or ""
                    ),
                    "source": str(item.get("source", item.get("文章来源", "AkShare")) or "AkShare"),
                    "url": url,
                }
            )
        recent_news = self._filter_recent_news(result, days=days)
        diagnostics["combined"] = {
            "status": "ok" if recent_news else "empty",
            "count": len(recent_news),
            "window_days": max(int(days), 1),
            "raw_count": len(result),
        }
        return recent_news[:200], diagnostics

    @staticmethod
    def _filter_recent_news(
        news: List[Dict[str, Any]], days: int = 7
    ) -> List[Dict[str, Any]]:
        """Keep recent domestic news; retain undated rows with source provenance."""
        cutoff = pd.Timestamp.now(tz=None) - pd.Timedelta(days=max(int(days), 1))
        result = []
        for item in news or []:
            if not isinstance(item, dict):
                continue
            published = item.get("publish_time", item.get("published_at", ""))
            parsed = pd.to_datetime(published, errors="coerce")
            if pd.isna(parsed):
                result.append(item)
                continue
            if getattr(parsed, "tzinfo", None) is not None:
                parsed = parsed.tz_localize(None)
            if parsed >= cutoff:
                result.append(item)
        return result

    @staticmethod
    def _provider_status(international: Dict[str, Any], provider: str) -> bool:
        return any(
            item.get("source") == provider and item.get("success")
            for item in international.get("sources", [])
        )

    @staticmethod
    def _international_diagnostic(
        international: Dict[str, Any], provider: str
    ) -> Dict[str, Any]:
        for item in international.get("sources", []):
            if item.get("source") != provider:
                continue
            if item.get("success") and item.get("count", 0):
                status = "ok"
            elif item.get("success"):
                status = "no_data"
            elif not item.get("enabled", True):
                status = "not_configured"
            else:
                status = "error"
            return {
                "status": status,
                "count": item.get("count", 0),
                "message": item.get("error", ""),
            }
        return {"status": "unknown", "count": 0, "message": "source result missing"}

    def _build_theme_scores(self, snapshot: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        weekly = self._aggregate_force(snapshot["main_force"].get("weekly", {}).get("records", []))
        monthly = self._aggregate_force(snapshot["main_force"].get("monthly", {}).get("records", []))
        return {
            "weekly": self._score_themes(
                aggregate=weekly,
                snapshot=snapshot,
                window="weekly",
            ),
            "monthly": self._score_themes(
                aggregate=monthly,
                snapshot=snapshot,
                window="monthly",
            ),
        }

    def _aggregate_force(self, records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        if not records:
            return {}
        df = pd.DataFrame(records)
        industry_col = _first_column(
            df.columns,
            ("所属同花顺行业", "所属行业", "行业", "板块", "概念"),
        )
        fund_col = _first_column(
            df.columns,
            (
                "区间主力资金流向",
                "区间主力资金净流入",
                "主力资金流向",
                "主力资金净流入",
                "主力净流入",
            ),
        )
        change_col = _first_column(
            df.columns,
            ("区间涨跌幅", "涨跌幅:前复权", "涨跌幅(%)", "涨跌幅"),
        )
        code_col = _first_column(df.columns, ("股票代码", "证券代码", "代码"))
        name_col = _first_column(df.columns, ("股票简称", "股票名称", "名称"))
        if not industry_col:
            return {}

        grouped: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "sector": "",
                "count": 0,
                "fund_inflow": 0.0,
                "avg_change": 0.0,
                "stocks": [],
            }
        )
        for _, row in df.iterrows():
            raw_sector = str(row.get(industry_col, "") or "").strip()
            if not raw_sector or raw_sector in {"nan", "None", "-"}:
                continue
            sector = self._theme_name(raw_sector)
            item = grouped[sector]
            item["sector"] = sector
            item["count"] += 1
            fund = _to_number(row.get(fund_col)) if fund_col else None
            change = _to_number(row.get(change_col)) if change_col else None
            item["fund_inflow"] += fund or 0
            item["avg_change"] += change or 0
            if len(item["stocks"]) < 10:
                item["stocks"].append(
                    {
                        "symbol": str(row.get(code_col, "") or "") if code_col else "",
                        "name": str(row.get(name_col, "") or "") if name_col else "",
                    }
                )
        for item in grouped.values():
            if item["count"]:
                item["avg_change"] /= item["count"]
        return dict(grouped)

    def _score_themes(
        self,
        aggregate: Dict[str, Dict[str, Any]],
        snapshot: Dict[str, Any],
        window: str,
    ) -> List[Dict[str, Any]]:
        sector_data = snapshot.get("domestic_market", {})
        sector_performance = sector_data.get("sectors", {}) or {}
        concept_performance = sector_data.get("concepts", {}) or {}
        flow_rows = (sector_data.get("sector_fund_flow", {}) or {}).get("today", [])
        domestic_news = sector_data.get("news", []) or []
        international_news = (snapshot.get("international_news", {}) or {}).get("articles", [])

        rows = []
        for sector, item in aggregate.items():
            aliases = self._aliases_for_sector(sector)
            matching_sector = self._find_sector_record(sector, sector_performance)
            concept_matches = self._find_concept_records(sector, concept_performance)
            matching_flow = self._find_flow_record(sector, flow_rows)
            domestic_hits, domestic_evidence = self._news_evidence(
                domestic_news, aliases
            )
            international_hits, international_evidence = self._news_evidence(
                international_news, aliases
            )
            concept_change, concept_up, concept_down = self._concept_metrics(
                concept_matches
            )
            latest_fund_inflow = self._value_from_record(
                matching_flow, ("main_net_inflow", "今日主力净流入-净额")
            )
            sector_change_pct = self._value_from_record(
                matching_sector, ("change_pct", "涨跌幅")
            )
            performance_change_pct = (
                (float(item["avg_change"]) + sector_change_pct) / 2
                if matching_sector
                else float(item["avg_change"])
            )
            concept_evidence = [
                {
                    "name": name,
                    "change_pct": self._value_from_record(
                        record, ("change_pct", "涨跌幅")
                    ),
                    "up_count": self._value_from_record(
                        record, ("up_count", "上涨家数")
                    ),
                    "down_count": self._value_from_record(
                        record, ("down_count", "下跌家数")
                    ),
                }
                for name, record in concept_matches[:5]
            ]
            rows.append(
                {
                    "name": sector,
                    "window": window,
                    "stock_count": item["count"],
                    "main_fund_inflow": round(item["fund_inflow"], 2),
                    "avg_stock_change_pct": round(item["avg_change"], 2),
                    "sector_change_pct": sector_change_pct,
                    "performance_change_pct": round(performance_change_pct, 2),
                    "sector_fund_inflow": self._value_from_record(
                        matching_flow, ("main_net_inflow", "今日主力净流入-净额")
                    ),
                    "latest_fund_inflow": latest_fund_inflow,
                    "fund_signal": self._fund_signal(
                        item["fund_inflow"], latest_fund_inflow, bool(matching_flow)
                    ),
                    "concept_count": len(concept_matches),
                    "concept_change_pct": concept_change,
                    "concept_up_count": concept_up,
                    "concept_down_count": concept_down,
                    "domestic_news_hits": domestic_hits,
                    "international_news_hits": international_hits,
                    "news_hits": domestic_hits + international_hits,
                    "evidence": {
                        "stocks": item["stocks"][:5],
                        "matched_aliases": aliases[:8],
                        "concepts": concept_evidence,
                        "domestic_news": domestic_evidence,
                        "international_news": international_evidence,
                    },
                }
            )

        def scale(values: List[float], value: float) -> float:
            if not values or max(values) == min(values):
                return 50.0 if value else 0.0
            return (value - min(values)) / (max(values) - min(values)) * 100

        fund_values = [max(float(row["main_fund_inflow"] or 0), 0) for row in rows]
        latest_fund_values = [
            max(float(row["latest_fund_inflow"] or 0), 0) for row in rows
        ]
        breadth_values = [float(row["stock_count"] or 0) for row in rows]
        change_values = [float(row["performance_change_pct"] or 0) for row in rows]
        concept_values = [
            self._concept_confirmation_value(row) for row in rows
        ]
        domestic_values = [float(row["domestic_news_hits"] or 0) for row in rows]
        intl_values = [float(row["international_news_hits"] or 0) for row in rows]
        for row in rows:
            row["score"] = round(
                scale(fund_values, max(float(row["main_fund_inflow"] or 0), 0)) * 0.45
                + scale(
                    latest_fund_values,
                    max(float(row["latest_fund_inflow"] or 0), 0),
                )
                * 0.10
                + scale(breadth_values, float(row["stock_count"] or 0)) * 0.10
                + scale(change_values, float(row["performance_change_pct"] or 0)) * 0.10
                + scale(concept_values, self._concept_confirmation_value(row)) * 0.10
                + scale(domestic_values, float(row["domestic_news_hits"] or 0)) * 0.075
                + scale(intl_values, float(row["international_news_hits"] or 0)) * 0.075,
                2,
            )
            row["sustainability_hint"] = self._sustainability_hint(row)
            row["evidence_summary"] = self._evidence_summary(row)
            row["reason"] = row["evidence_summary"]
        return sorted(rows, key=lambda row: row["score"], reverse=True)[:15]

    @classmethod
    def _find_concept_records(
        cls, sector: str, records: Dict[str, Any]
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Return concept rows mapped to the same canonical theme."""
        if not isinstance(records, dict):
            return []
        matches = []
        for name, value in records.items():
            if not isinstance(value, dict):
                continue
            if cls._theme_name(str(name)) == sector:
                matches.append((str(name), value))
        matches.sort(
            key=lambda item: cls._value_from_record(
                item[1], ("change_pct", "涨跌幅")
            ),
            reverse=True,
        )
        return matches

    @staticmethod
    def _concept_metrics(
        concept_matches: List[Tuple[str, Dict[str, Any]]]
    ) -> Tuple[float, float, float]:
        if not concept_matches:
            return 0.0, 0.0, 0.0
        changes = [
            _to_number(record.get("change_pct", record.get("涨跌幅")))
            for _, record in concept_matches
        ]
        changes = [value for value in changes if value is not None]
        up_count = sum(
            _to_number(record.get("up_count", record.get("上涨家数"))) or 0
            for _, record in concept_matches
        )
        down_count = sum(
            _to_number(record.get("down_count", record.get("下跌家数"))) or 0
            for _, record in concept_matches
        )
        return (
            round(sum(changes) / len(changes), 2) if changes else 0.0,
            round(up_count, 2),
            round(down_count, 2),
        )

    @staticmethod
    def _concept_confirmation_value(row: Dict[str, Any]) -> float:
        """Reward positive concept breadth and performance, not just concept count."""
        count = float(row.get("concept_count") or 0)
        change = float(row.get("concept_change_pct") or 0)
        up_count = float(row.get("concept_up_count") or 0)
        down_count = float(row.get("concept_down_count") or 0)
        breadth = (up_count - down_count) / max(up_count + down_count, 1)
        return max(count, 0) + max(change, 0) * 2 + max(breadth, 0) * 10

    @staticmethod
    def _news_evidence(
        articles: List[Dict[str, Any]], aliases: Sequence[str]
    ) -> Tuple[int, List[Dict[str, str]]]:
        hits = 0
        evidence = []
        for article in articles:
            if not isinstance(article, dict):
                continue
            text = " ".join(
                str(article.get(key, "") or "")
                for key in ("title", "content", "description", "text")
            ).lower()
            if not any(alias.lower() in text for alias in aliases):
                continue
            hits += 1
            if len(evidence) < 5:
                evidence.append(
                    {
                        "title": str(article.get("title", "") or "")[:160],
                        "source": str(
                            article.get("source", article.get("provider", ""))
                            or ""
                        )[:80],
                    }
                )
        return hits, evidence

    @staticmethod
    def _evidence_summary(row: Dict[str, Any]) -> str:
        return (
            f"窗口主力资金 {float(row.get('main_fund_inflow', 0) or 0):+.2f}，"
            f"今日板块资金 {float(row.get('latest_fund_inflow', 0) or 0):+.2f}，"
            f"判断 {row.get('fund_signal', '数据不足')}；"
            f"行业覆盖 {int(row.get('stock_count', 0) or 0)} 只；"
            f"概念交叉 {int(row.get('concept_count', 0) or 0)} 个，"
            f"概念平均涨幅 {float(row.get('concept_change_pct', 0) or 0):+.2f}%；"
            f"国内新闻 {int(row.get('domestic_news_hits', 0) or 0)} 条，"
            f"国际新闻 {int(row.get('international_news_hits', 0) or 0)} 条"
        )

    @staticmethod
    def _fund_signal(
        window_inflow: float, latest_inflow: float, latest_available: bool
    ) -> str:
        """Summarize whether current flow confirms the longer window."""
        window_positive = float(window_inflow or 0) > 0
        latest_positive = float(latest_inflow or 0) > 0
        if not latest_available:
            return "窗口偏看好，最新资金数据不足" if window_positive else "数据不足"
        if latest_positive and window_positive:
            return "最新偏看好，且与窗口趋势一致"
        if latest_positive:
            return "最新偏看好，但窗口累计仍待确认"
        if window_positive and float(latest_inflow or 0) < 0:
            return "窗口偏看好，但最新出现分歧"
        if window_positive:
            return "窗口偏看好，最新暂未放量"
        return "最新偏弱"

    @staticmethod
    def _aliases_for_sector(sector: str) -> Tuple[str, ...]:
        if sector in SECTOR_ALIASES:
            return tuple(dict.fromkeys((sector, *SECTOR_ALIASES[sector])))
        for key, aliases in SECTOR_ALIASES.items():
            if key in sector or sector in key:
                return tuple(dict.fromkeys((sector, *aliases)))
        return (sector,)

    @staticmethod
    def _theme_name(sector: str) -> str:
        """Map a raw pywencai industry label to a compact report direction."""
        value = str(sector or "").strip().lower().replace(" ", "")
        if not value or value in {"nan", "none", "-"}:
            return ""
        for theme in FOCUS_THEME_ORDER:
            aliases = SECTOR_ALIASES.get(theme, (theme,))
            if any(
                alias.lower().replace(" ", "") in value
                or value in alias.lower().replace(" ", "")
                for alias in (theme, *aliases)
            ):
                return theme
        return str(sector).strip()

    @staticmethod
    def _find_sector_record(sector: str, records: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(records, dict):
            return {}
        aliases = MainlineAnalyzer._aliases_for_sector(sector)
        for name, value in records.items():
            name_text = str(name or "").lower()
            if any(
                alias.lower() in name_text or name_text in alias.lower()
                for alias in aliases
            ):
                return value if isinstance(value, dict) else {}
        return {}

    @staticmethod
    def _find_flow_record(sector: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        aliases = MainlineAnalyzer._aliases_for_sector(sector)
        for record in records or []:
            name = str(record.get("sector", record.get("名称", "")) or "")
            name_text = name.lower()
            if any(
                alias.lower() in name_text or name_text in alias.lower()
                for alias in aliases
            ):
                return record
        return {}

    @staticmethod
    def _value_from_record(record: Dict[str, Any], keys: Sequence[str]) -> float:
        for key in keys:
            if key in record:
                return round(_to_number(record.get(key)) or 0, 2)
        return 0.0

    @staticmethod
    def _sustainability_hint(row: Dict[str, Any]) -> str:
        score = float(row.get("score", 0))
        if score >= 70 and row.get("stock_count", 0) >= 3:
            return "较强"
        if score >= 45:
            return "一般"
        return "弱"

    def _build_recommendations(
        self,
        snapshot: Dict[str, Any],
        themes: Dict[str, List[Dict[str, Any]]],
        top_n: int,
    ) -> List[Dict[str, Any]]:
        sector_stock_picks = self._build_sector_stock_picks(
            snapshot, themes, sector_limit=5, per_sector=10
        )
        return self._flatten_sector_picks(sector_stock_picks, limit=top_n)

    def _build_sector_stock_picks(
        self,
        snapshot: Dict[str, Any],
        themes: Dict[str, List[Dict[str, Any]]],
        sector_limit: int = 5,
        per_sector: int = 10,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Rank up to ten 6/3-prefix stocks separately for each main sector."""
        picks: Dict[str, List[Dict[str, Any]]] = {"weekly": [], "monthly": []}
        for window in ("weekly", "monthly"):
            records = (
                snapshot.get("main_force", {})
                .get(window, {})
                .get("records", [])
            )
            for theme in themes.get(window, []):
                sector = str(theme.get("name", "") or "").strip()
                stocks = self._rank_sector_stocks(
                    records, sector, per_sector=per_sector
                )
                # The UI promises a sector-specific 6/3 stock pool. Skip a
                # strong sector only when pywencai has no eligible code for it.
                if not stocks:
                    continue
                picks[window].append(
                    {
                        "sector": sector,
                        "score": theme.get("score", 0),
                        "fund_inflow": theme.get("main_fund_inflow", 0),
                        "latest_fund_inflow": theme.get("latest_fund_inflow", 0),
                        "fund_signal": theme.get("fund_signal", "数据不足"),
                        "stock_count": theme.get("stock_count", 0),
                        "performance_change_pct": theme.get(
                            "performance_change_pct", 0
                        ),
                        "news_hits": theme.get("news_hits", 0),
                        "domestic_news_hits": theme.get("domestic_news_hits", 0),
                        "international_news_hits": theme.get(
                            "international_news_hits", 0
                        ),
                        "concept_count": theme.get("concept_count", 0),
                        "concept_change_pct": theme.get("concept_change_pct", 0),
                        "evidence": theme.get("evidence", {}),
                        "evidence_summary": theme.get("evidence_summary", ""),
                        "sustainability_hint": theme.get(
                            "sustainability_hint", "弱"
                        ),
                        "reason": theme.get("reason", ""),
                        "stocks": stocks,
                    }
                )
                if len(picks[window]) >= sector_limit:
                    break
        return picks

    def _rank_sector_stocks(
        self,
        records: List[Dict[str, Any]],
        sector: str,
        per_sector: int = 10,
    ) -> List[Dict[str, Any]]:
        """Create a fund-flow-first ranking for one canonical sector."""
        records = [row for row in (records or []) if isinstance(row, dict)]
        if not records:
            return []
        df = pd.DataFrame(records).drop_duplicates()
        industry_col = _first_column(
            df.columns, ("所属同花顺行业", "所属行业", "行业", "板块", "概念")
        )
        fund_col = _first_column(
            df.columns,
            (
                "区间主力资金流向",
                "区间主力资金净流入",
                "主力资金流向",
                "主力资金净流入",
                "主力净流入",
            ),
        )
        change_col = _first_column(
            df.columns, ("区间涨跌幅", "涨跌幅:前复权", "涨跌幅(%)", "涨跌幅")
        )
        code_col = _first_column(df.columns, ("股票代码", "证券代码", "代码"))
        name_col = _first_column(df.columns, ("股票简称", "股票名称", "名称"))
        cap_col = _first_column(df.columns, ("总市值", "市值"))
        candidates: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            symbol = self._clean_symbol(row.get(code_col, "") if code_col else "")
            name = str(row.get(name_col, "") or "") if name_col else ""
            raw_industry = (
                str(row.get(industry_col, "") or "") if industry_col else ""
            )
            if (
                not symbol
                or not name
                or not symbol.startswith(("6", "3"))
                or self._theme_name(raw_industry) != sector
            ):
                continue
            candidate = {
                "symbol": symbol,
                "name": name,
                "industry": raw_industry,
                "theme": sector,
                "main_fund_inflow": round(
                    (_to_number(row.get(fund_col)) if fund_col else 0) or 0, 2
                ),
                "range_change_pct": round(
                    (_to_number(row.get(change_col)) if change_col else 0) or 0, 2
                ),
                "market_cap": round(
                    (_to_number(row.get(cap_col)) if cap_col else 0) or 0, 2
                ),
                "mainline_alignment": 1,
                "raw_data": _json_safe(row.to_dict()),
            }
            previous = candidates.get(symbol)
            if previous is None or (
                candidate["main_fund_inflow"] > previous["main_fund_inflow"]
            ):
                candidates[symbol] = candidate

        scored = list(candidates.values())
        if not scored:
            return []
        positive_scored = [
            item
            for item in scored
            if float(item["main_fund_inflow"] or 0) > 0
        ]
        if not positive_scored:
            return []
        scored = positive_scored
        max_fund = max(
            max(float(item["main_fund_inflow"] or 0), 0) for item in scored
        ) or 1
        for item in scored:
            fund = float(item["main_fund_inflow"] or 0)
            change = float(item["range_change_pct"] or 0)
            flow_score = max(fund, 0) / max_fund * 75
            change_score = min(max(change, 0), 20) / 20 * 15
            positive_bonus = 10 if fund > 0 else 0
            item["score"] = round(
                flow_score + change_score + positive_bonus, 2
            )
            item["basis"] = [
                f"{sector}方向主力资金 {item['main_fund_inflow']:+.2f}",
                f"区间涨跌幅 {item['range_change_pct']:+.2f}%",
            ]
            item["risk"] = (
                "需结合次日板块承接和个股开盘强弱复核，不构成买卖指令。"
            )
        scored.sort(
            key=lambda item: (
                float(item["main_fund_inflow"] or 0) > 0,
                item["score"],
                item["main_fund_inflow"],
            ),
            reverse=True,
        )
        return scored[: max(1, min(per_sector, 10))]

    @staticmethod
    def _flatten_sector_picks(
        sector_stock_picks: Dict[str, List[Dict[str, Any]]],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Flatten weekly/monthly picks for existing report/LLM consumers."""
        result: List[Dict[str, Any]] = []
        seen = set()
        groups = [
            *sector_stock_picks.get("weekly", []),
            *sector_stock_picks.get("monthly", []),
        ]
        groups.sort(
            key=lambda item: float(item.get("score", 0) or 0), reverse=True
        )
        for group in groups:
            for item in group.get("stocks", []):
                symbol = item.get("symbol", "")
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                result.append(item)
                if len(result) >= max(1, limit):
                    return result
        return result

    @staticmethod
    def _build_mainline_summary(
        sector_stock_picks: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        return {
            "weekly": sector_stock_picks.get("weekly", []),
            "monthly": sector_stock_picks.get("monthly", []),
            "strongest_weekly": sector_stock_picks.get("weekly", [])[:1],
            "strongest_monthly": sector_stock_picks.get("monthly", [])[:1],
        }

    @staticmethod
    def _clean_symbol(value: Any) -> str:
        match = re.search(r"(\d{6})", str(value or ""))
        return match.group(1) if match else ""

    def _build_fallback_analysis(
        self,
        snapshot: Dict[str, Any],
        themes: Dict[str, List[Dict[str, Any]]],
        recommendations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        weekly = themes.get("weekly", [])
        monthly = themes.get("monthly", [])
        market = snapshot.get("domestic_market", {}).get("market_overview", {}) or {}
        market_environment, environment_basis = self._market_environment(market)
        weekly_mainline = self._theme_descriptions(weekly[:3])
        monthly_mainline = self._theme_descriptions(monthly[:3])
        clear_mainline = bool(weekly and weekly[0].get("score", 0) >= 45)

        return {
            "market_environment": {
                "conclusion": market_environment,
                "basis": environment_basis,
                "action": self._action_for_environment(market_environment),
            },
            "current_mainline": {
                "weekly": weekly_mainline if clear_mainline else "主线不清、轮动为主、降低预期",
                "monthly": monthly_mainline if monthly else "数据不足，无法确认本月主线",
                "basis": self._theme_basis(weekly[:3], monthly[:3]),
            },
            "secondary_hotspots": self._theme_descriptions(weekly[3:7]) or "暂未形成清晰次级热点",
            "core_anchors": recommendations[:5] or "当前没有足够的候选股票数据",
            "emotion_cycle": self._emotion_cycle(market),
            "mainline_sustainability": self._sustainability(weekly[:5], monthly[:5]),
            "next_day_focus": self._next_day_focus(weekly[:3], recommendations, market),
            "one_line_conclusion": self._one_line_conclusion(
                market_environment, weekly, recommendations
            ),
        }

    @staticmethod
    def _market_environment(market: Dict[str, Any]) -> Tuple[str, List[str]]:
        up_ratio = _to_number(market.get("up_ratio"))
        limit_up = _to_number(market.get("limit_up"))
        limit_down = _to_number(market.get("limit_down"))
        basis = []
        if up_ratio is not None:
            basis.append(f"上涨家数占比 {up_ratio:.1f}%")
        if limit_up is not None:
            basis.append(f"涨停 {limit_up:.0f} 家")
        if limit_down is not None:
            basis.append(f"跌停 {limit_down:.0f} 家")
        if up_ratio is None:
            return "数据不足", basis or ["缺少市场涨跌家数和涨跌停统计"]
        if up_ratio >= 65 and (limit_up or 0) >= 40 and (limit_down or 0) <= 15:
            return "强势/主动进攻", basis
        if up_ratio <= 35 and (limit_down or 0) >= 20:
            return "弱势/退潮", basis
        if up_ratio <= 45:
            return "震荡偏弱/控制仓位", basis
        return "震荡/精选参与", basis

    @staticmethod
    def _action_for_environment(environment: str) -> str:
        if "强势" in environment:
            return "主动进攻，但只做主线核心，回避后排追高"
        if "弱势" in environment or "退潮" in environment:
            return "控制仓位，优先观察，不做情绪接力"
        if "数据不足" in environment:
            return "等待关键数据补齐，避免依据单一新闻交易"
        return "精选参与，等待主线分歧后的承接确认"

    @staticmethod
    def _theme_descriptions(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "name": row.get("name", ""),
                "score": row.get("score", 0),
                "fund_inflow": row.get("main_fund_inflow", 0),
                "latest_fund_inflow": row.get("latest_fund_inflow", 0),
                "fund_signal": row.get("fund_signal", "数据不足"),
                "stock_count": row.get("stock_count", 0),
                "performance_change_pct": row.get("performance_change_pct", 0),
                "news_hits": row.get("news_hits", 0),
                "domestic_news_hits": row.get("domestic_news_hits", 0),
                "international_news_hits": row.get("international_news_hits", 0),
                "concept_count": row.get("concept_count", 0),
                "concept_change_pct": row.get("concept_change_pct", 0),
                "sustainability_hint": row.get("sustainability_hint", "弱"),
                "reason": (
                    f"窗口主力资金 {row.get('main_fund_inflow', 0):.2f}，"
                    f"最新资金判断 {row.get('fund_signal', '数据不足')}，"
                    f"概念交叉 {row.get('concept_count', 0)} 个，"
                    f"国内/国际新闻 {row.get('domestic_news_hits', 0)}/"
                    f"{row.get('international_news_hits', 0)} 条，"
                    f"资金候选 {row.get('stock_count', 0)} 只"
                ),
            }
            for row in rows
        ]

    @staticmethod
    def _theme_basis(weekly: List[Dict[str, Any]], monthly: List[Dict[str, Any]]) -> List[str]:
        basis = []
        if weekly:
            basis.append("本周资金聚集: " + "、".join(row["name"] for row in weekly))
        if monthly:
            basis.append("本月资金聚集: " + "、".join(row["name"] for row in monthly))
        if not basis:
            basis.append("缺少有效的问财主力资金数据")
        return basis

    @staticmethod
    def _emotion_cycle(market: Dict[str, Any]) -> Dict[str, Any]:
        up_ratio = _to_number(market.get("up_ratio"))
        limit_up = _to_number(market.get("limit_up"))
        limit_down = _to_number(market.get("limit_down"))
        if up_ratio is None:
            return {"stage": "数据不足", "basis": ["缺少涨跌家数、涨跌停和连板数据"]}
        if up_ratio >= 65 and (limit_up or 0) >= 40:
            stage = "主升"
        elif up_ratio <= 35 and (limit_down or 0) >= 20:
            stage = "退潮"
        elif up_ratio <= 45:
            stage = "冰点/弱修复"
        else:
            stage = "震荡分化"
        return {
            "stage": stage,
            "basis": [
                f"上涨家数占比 {up_ratio:.1f}%",
                f"涨停 {limit_up or 0:.0f} 家 / 跌停 {limit_down or 0:.0f} 家",
                "当前数据未覆盖连板高度和炸板率，结论需要次日盘面验证",
            ],
        }

    @staticmethod
    def _sustainability(
        weekly: List[Dict[str, Any]], monthly: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        names = []
        for row in weekly:
            name = row.get("name", "")
            monthly_row = next((item for item in monthly if item.get("name") == name), None)
            overlap = bool(monthly_row)
            level = row.get("sustainability_hint", "弱")
            if overlap and level == "一般":
                level = "较强"
            names.append(
                {
                    "theme": name,
                    "level": level,
                    "产业逻辑": "需要结合公司公告和产业数据核验",
                    "事件催化": "有新闻命中，但需观察是否持续扩散",
                    "资金合力": "本周/月窗口是否重叠: " + ("是" if overlap else "否"),
                    "end_trigger": "核心股失去承接、板块涨停扩散收缩或催化兑现后资金流出",
                }
            )
        return names or [{"theme": "未识别", "level": "弱", "end_trigger": "数据不足"}]

    @staticmethod
    def _next_day_focus(
        weekly: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
        market: Dict[str, Any],
    ) -> List[str]:
        focus = []
        if weekly:
            focus.append(f"观察 {weekly[0]['name']} 核心股能否弱转强，并确认板块是否继续扩散")
        if recommendations:
            focus.append(f"观察 {recommendations[0]['name']} 开盘承接，而不是只看竞价涨幅")
        focus.append("观察主线分歧后是否有回流，以及后排是否出现大面积掉队")
        if not market.get("up_ratio"):
            focus.append("补齐涨跌家数、涨停/跌停和成交额数据后再提高仓位")
        return focus

    @staticmethod
    def _one_line_conclusion(
        environment: str,
        weekly: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
    ) -> str:
        if not weekly:
            return "主线不清、轮动为主、降低预期；等待资金和板块扩散同时确认。"
        if "退潮" in environment or "弱势" in environment:
            return f"{environment}，只观察 {weekly[0]['name']} 核心锚点，不追后排。"
        stock = recommendations[0]["name"] if recommendations else "核心股"
        return f"围绕 {weekly[0]['name']} 做强弱判断，优先观察 {stock} 的承接与板块扩散。"

    def _run_llm_analysis(
        self,
        snapshot: Dict[str, Any],
        themes: Dict[str, List[Dict[str, Any]]],
        recommendations: List[Dict[str, Any]],
        fallback: Dict[str, Any],
        thinking_mode: bool = False,
        reasoning_effort: str = "high",
    ) -> Optional[Dict[str, Any]]:
        try:
            import config

            if not str(getattr(config, "DEEPSEEK_API_KEY", "") or "").strip():
                return None
            from deepseek_client import DeepSeekClient

            client = DeepSeekClient(model=self.model)
            sector_stock_picks = self._build_sector_stock_picks(
                snapshot, themes, sector_limit=5, per_sector=10
            )
            context = {
                "windows": snapshot.get("windows"),
                "source_status": snapshot.get("source_status"),
                "market": snapshot.get("domestic_market", {}).get("market_overview", {}),
                "themes": themes,
                "sector_stock_picks": sector_stock_picks,
                "recommendations": recommendations,
                "domestic_news": snapshot.get("domestic_market", {}).get("news", [])[:40],
                "international_news": snapshot.get("international_news", {}).get("articles", [])[:40],
            }
            prompt = f"""请严格基于以下 JSON 数据分析本周和本月A股主线。
不要补写输入中不存在的价格、涨停高度、成交额、新闻事实或股票代码。
如果数据没有连板高度、炸板率或成交额，请在依据中明确写数据不足。

时间口径：
- weekly：本周一以来的问财主力资金和个股表现；新闻是近7日催化证据。
- monthly：本月1日以来的问财主力资金和个股表现；新闻仍是近7日最新催化，
  不能声称已经覆盖完整自然月新闻。

判断口径：
- 主力资金是第一证据；板块行情和概念题材用于交叉确认。
- 国内新闻和国际新闻必须分开引用，新闻只能解释催化，不能替代资金承接。
- 行业板块与概念题材要分开描述；概念证据不足时不要提高置信度。
- weekly 与 monthly 必须分别给出主线、次级热点和股票池，不得混写。

数据：
{json.dumps(_json_safe(context), ensure_ascii=False, indent=2)[:50000]}

请只输出 JSON，结构必须为：
{{
  "market_environment": {{"conclusion": "", "basis": [], "action": ""}},
  "current_mainline": {{"weekly": [], "monthly": [], "basis": []}},
  "secondary_hotspots": [],
  "core_anchors": [],
  "emotion_cycle": {{"stage": "", "basis": []}},
  "mainline_sustainability": [],
  "next_day_focus": [],
  "one_line_conclusion": ""
}}

其中 core_anchors 只能从 sector_stock_picks 中选择；
每个股票代码只能是6或3开头，不能自行生成代码；
每个板块的 stocks 最多10只，且 weekly/monthly 必须保持各自周期；
每个主线项目要给出资金、行业/概念和国内/国际新闻依据（如果缺失要写数据不足）。
"""
            response = client.call_api(
                [
                    {"role": "system", "content": MAINLINE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                max_tokens=8000 if thinking_mode else 5000,
                thinking=thinking_mode,
                reasoning_effort=reasoning_effort,
                # Reasoning content is never shown or persisted by the mainline UI.
                include_reasoning=False,
                response_format={"type": "json_object"},
            )
            parsed = self._parse_json_response(response)
            if not isinstance(parsed, dict):
                return None
            return self._constrain_ai_analysis(parsed, sector_stock_picks)
        except Exception as exc:
            logger.warning("LLM mainline analysis failed, using baseline: %s", exc)
            return None

    @classmethod
    def _constrain_ai_analysis(
        cls,
        analysis: Dict[str, Any],
        sector_stock_picks: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Drop model-selected stocks that are outside the deterministic pool."""
        allowed: Dict[str, Dict[str, Any]] = {}
        for groups in sector_stock_picks.values():
            for group in groups or []:
                for stock in group.get("stocks", []) or []:
                    symbol = cls._clean_symbol(stock.get("symbol", ""))
                    if symbol.startswith(("6", "3")):
                        allowed[symbol] = stock

        constrained = dict(analysis)
        anchors = analysis.get("core_anchors")
        if not isinstance(anchors, list):
            return constrained
        safe_anchors = []
        for item in anchors:
            if isinstance(item, dict):
                symbol = cls._clean_symbol(item.get("symbol", ""))
                if symbol in allowed:
                    safe_anchors.append(item)
                continue
            text = str(item or "")
            symbols = re.findall(r"(?<!\d)(?:6|3)\d{5}(?!\d)", text)
            if symbols and symbols[0] in allowed:
                safe_anchors.append(text)
        constrained["core_anchors"] = safe_anchors
        return constrained

    @staticmethod
    def _parse_json_response(response: Any) -> Optional[Dict[str, Any]]:
        text = str(response or "").strip()
        text = re.sub(r"【推理过程】.*?\n\n", "", text, flags=re.DOTALL)
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        candidate = fenced.group(1) if fenced else text
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(candidate[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _merge_analysis(fallback: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(fallback)
        for key in result:
            value = ai.get(key)
            if value not in (None, "", [], {}):
                result[key] = value
        return result

    @staticmethod
    def format_report(
        analysis: Dict[str, Any],
        recommendations: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Render the fixed eight-section report requested by the user."""
        recommendations = recommendations or []
        environment = analysis.get("market_environment", {})
        mainline = analysis.get("current_mainline", {})
        emotion = analysis.get("emotion_cycle", {})
        sustainability = analysis.get("mainline_sustainability", [])
        anchors = analysis.get("core_anchors", recommendations)

        def render(value: Any) -> str:
            if isinstance(value, str):
                return value
            return json.dumps(_json_safe(value), ensure_ascii=False, indent=2)

        lines = [
            "【1.市场环境】",
            render(environment),
            "",
            "【2.当前主线】",
            render(mainline),
            "",
            "【3.次级热点】",
            render(analysis.get("secondary_hotspots", [])),
            "",
            "【4.核心锚点个股】",
            render(anchors),
            "",
            "【5.情绪周期】",
            render(emotion),
            "",
            "【6.主线持续性评估】",
            render(sustainability),
            "",
            "【7.明日观察重点】",
            render(analysis.get("next_day_focus", [])),
            "",
            "【8.一句话交易结论】",
            render(analysis.get("one_line_conclusion", "")),
            "",
            "风险提示：以上内容是基于当前数据窗口的研究结果，不构成投资建议；A股市场变化可能导致结论失效。",
        ]
        return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="A股本周/本月主线分析")
    parser.add_argument("--international-days", type=int, default=7)
    parser.add_argument("--min-market-cap", type=float, default=50)
    parser.add_argument("--max-market-cap", type=float, default=5000)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--no-ai", action="store_true", help="只运行确定性分析，不调用DeepSeek")
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="启用DeepSeek思考模式（需要DeepSeek API Key）",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "high", "max"),
        default="high",
        help="思考强度：low/high/max",
    )
    parser.add_argument("--no-newsapi", action="store_true", help="不请求NewsAPI")
    parser.add_argument("--query", default=None, help="覆盖国际新闻查询语句")
    parser.add_argument("--output", default=None, help="保存完整JSON结果")
    parser.add_argument(
        "--no-history", action="store_true", help="不保存主线分析历史"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = MainlineAnalyzer().run(
        international_days=args.international_days,
        min_market_cap=args.min_market_cap,
        max_market_cap=args.max_market_cap,
        top_n=args.top_n,
        include_ai=not args.no_ai,
        include_newsapi=not args.no_newsapi,
        thinking_mode=args.thinking,
        reasoning_effort=args.reasoning_effort,
        international_query=args.query,
        output_path=args.output,
        save_history=not args.no_history,
    )
    print(result["report"])
    if args.output:
        print(f"\n完整JSON已保存: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
