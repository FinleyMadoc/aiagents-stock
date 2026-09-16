"""Compact Streamlit page for the A-share mainline result."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import config
from mainline_history import MainlineHistoryStore
from mainline_analysis import MainlineAnalyzer


DISPLAY_SECTOR_COUNT = 5
DEFAULT_MAINLINE_THINKING_MODE = bool(
    getattr(config, "MAINLINE_THINKING_MODE", False)
)
DEFAULT_MAINLINE_REASONING_EFFORT = str(
    getattr(config, "MAINLINE_REASONING_EFFORT", "high") or "high"
).lower()
if DEFAULT_MAINLINE_REASONING_EFFORT not in {"low", "high", "max"}:
    DEFAULT_MAINLINE_REASONING_EFFORT = "high"


def _render_sector_group(title: str, groups: list[dict]) -> None:
    st.subheader(title)
    if not groups:
        st.info("暂无足够的主力资金数据。")
        return

    for rank, group in enumerate(groups[:DISPLAY_SECTOR_COUNT], 1):
        sector = group.get("sector", "未命名板块")
        concepts = [
            str(item.get("name", "")).strip()
            for item in (group.get("evidence", {}) or {}).get("concepts", [])[:3]
            if str(item.get("name", "")).strip()
        ]
        concept_text = "、".join(concepts) if concepts else "暂无"
        st.markdown(
            f"**{rank}. {sector}**　"
            f"综合分 {float(group.get('score', 0) or 0):.1f}　"
            f"主力资金 {float(group.get('fund_inflow', 0) or 0):+.2f}"
        )

        st.caption(
            f"主力判断：{group.get('fund_signal', '数据不足')}　"
            f"概念：{concept_text}　"
            f"板块涨幅 {float(group.get('performance_change_pct', 0) or 0):+.2f}%　"
            f"国内/国际新闻 "
            f"{int(group.get('domestic_news_hits', 0) or 0)}/"
            f"{int(group.get('international_news_hits', 0) or 0)} 条　"
            f"　持续性：{group.get('sustainability_hint', '弱')}"
        )

        stocks = group.get("stocks", [])[:10]
        if not stocks:
            st.warning(f"{sector} 暂无符合条件的 6/3 开头股票。")
            continue

        rows = [
            {
                "代码": item.get("symbol"),
                "名称": item.get("name"),
                "原行业": item.get("industry"),
                "主力资金": item.get("main_fund_inflow"),
                "区间涨跌": item.get("range_change_pct"),
                "个股评分": item.get("score"),
            }
            for item in stocks
        ]
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
        )


def _history_store() -> MainlineHistoryStore:
    return MainlineHistoryStore(
        directory=getattr(config, "MAINLINE_HISTORY_DIR", "data/mainline/history"),
        limit=getattr(config, "MAINLINE_HISTORY_LIMIT", 100),
    )


def _display_history_controls() -> None:
    """Offer persistent result loading without making history a separate page."""
    store = _history_store()
    records = store.list_records()
    with st.expander(f"历史记录（{len(records)} 条）", expanded=False):
        st.caption(f"历史文件目录：{store.directory}")
        if not records:
            st.info("暂无历史记录。点击开始分析后会自动保存。")
            return

        labels = {}
        for record in records:
            generated_at = str(record.get("generated_at", "") or "")
            label = (
                f"{generated_at or record.get('id', '')} | "
                f"周：{record.get('weekly_top', '暂无')} | "
                f"月：{record.get('monthly_top', '暂无')} | "
                f"记录：{record.get('id', '')}"
            )
            if record.get("thinking_mode"):
                label += " | 思考模式"
            labels[label] = record["id"]

        selected_label = st.selectbox(
            "选择历史分析",
            options=list(labels),
            key="mainline_history_selection",
        )
        selected_id = labels[selected_label]
        if st.button("查看此记录", key="mainline_load_history"):
            historical_result = store.load(selected_id)
            if historical_result:
                st.session_state.mainline_result = historical_result
                st.session_state.mainline_history_loaded_id = selected_id
                st.success("已加载历史主线分析。")
            else:
                st.error("历史文件不存在或格式无效。")

        selected_result = st.session_state.get("mainline_result")
        if selected_result and selected_result.get("history", {}).get("id") == selected_id:
            st.download_button(
                "下载此历史 JSON",
                data=json.dumps(selected_result, ensure_ascii=False, indent=2),
                file_name=f"{selected_id}.json",
                mime="application/json",
                key="mainline_download_history",
            )


def display_mainline_analysis() -> None:
    st.title("A股主力板块")
    st.caption(
        "本周=周一以来资金，本月=当月1日起资金；国内/国际新闻均取近 7 日，"
        "国际新闻仅使用 NewsAPI；股票仅保留 6 和 3 开头。"
    )

    option_col, effort_col = st.columns([1, 1])
    with option_col:
        thinking_mode = st.checkbox(
            "启用 DeepSeek 思考模式",
            value=st.session_state.get(
                "mainline_thinking_mode", DEFAULT_MAINLINE_THINKING_MODE
            ),
            disabled=not bool(config.DEEPSEEK_API_KEY.strip()),
            help="提高主线判断的多步推理能力，也会增加耗时和 Token 消耗；页面只显示最终结论。",
        )
        st.session_state.mainline_thinking_mode = thinking_mode
    with effort_col:
        reasoning_effort = st.selectbox(
            "思考强度",
            options=("low", "high", "max"),
            index=("low", "high", "max").index(
                st.session_state.get(
                    "mainline_reasoning_effort",
                    DEFAULT_MAINLINE_REASONING_EFFORT,
                )
            ),
            disabled=not thinking_mode or not bool(config.DEEPSEEK_API_KEY.strip()),
            help="high 是默认平衡选项，max 更慢且成本更高。",
        )
        st.session_state.mainline_reasoning_effort = reasoning_effort

    if st.button("开始分析", type="primary", width="stretch"):
        with st.spinner(
            "正在使用思考模式分析..." if thinking_mode
            else "正在分析本周、本月资金和近 7 日新闻..."
        ):
            result = MainlineAnalyzer(model=config.DEFAULT_MODEL_NAME).run(
                international_days=7,
                min_market_cap=50.0,
                max_market_cap=5000.0,
                top_n=10,
                include_ai=bool(config.DEEPSEEK_API_KEY.strip()),
                include_newsapi=bool(config.NEWSAPI_API_KEY.strip()),
                thinking_mode=thinking_mode,
                reasoning_effort=reasoning_effort,
                history_dir=getattr(
                    config, "MAINLINE_HISTORY_DIR", "data/mainline/history"
                ),
            )
        st.session_state.mainline_result = result

    _display_history_controls()

    result = st.session_state.get("mainline_result")
    if not result:
        st.info("点击“开始分析”获取本周、本月主力板块和股票池。")
        return

    summary = result.get("mainline_summary", {})
    weekly = summary.get("weekly", [])
    monthly = summary.get("monthly", [])

    if weekly:
        st.success(f"本周最强板块：{weekly[0].get('sector', '暂无')}")
    if monthly:
        st.info(f"本月最强板块：{monthly[0].get('sector', '暂无')}")
    if result.get("thinking_mode"):
        st.caption(f"本次使用 DeepSeek 思考模式（{result.get('reasoning_effort', 'high')}）")

    _render_sector_group("本周主力板块", weekly)
    st.divider()
    _render_sector_group("本月主力板块", monthly)

    st.caption(
        "评分逻辑：窗口个股资金 45% + 最新板块资金 10% + 板块覆盖/涨幅 20% + "
        "概念交叉 10% + 国内/国际新闻各 7.5%。"
        "股票推荐仅为研究候选，不构成投资建议。"
    )
