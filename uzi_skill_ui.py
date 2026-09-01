"""UZI 个股深度分析 Streamlit 页面。"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import config
from uzi_skill_adapter import UZISkillAdapter


def _read_html(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def display_new_skill_uzi() -> None:
    st.markdown(
        """
        <div class="top-nav">
            <h1 class="nav-title">🧠 new-skill-uzi</h1>
            <p class="nav-subtitle">UZI 个股深度分析引擎 | 外部 skill 接入当前项目</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")

    col1, col2 = st.columns([2, 1])
    with col1:
        ticker = st.text_input(
            "股票代码或名称",
            value=st.session_state.get("uzi_ticker", ""),
            placeholder="例如: 600519 / 贵州茅台 / AAPL / 00700.HK",
            key="uzi_ticker",
        )
    with col2:
        default_depth = getattr(config, "UZI_DEFAULT_DEPTH", "medium")
        depth = st.selectbox(
            "分析深度",
            ["lite", "medium", "deep"],
            index=["lite", "medium", "deep"].index(default_depth) if default_depth in ["lite", "medium", "deep"] else 1,
        )

    col3, col4 = st.columns([1, 1])
    with col3:
        default_school = getattr(config, "UZI_DEFAULT_SCHOOL", "")
        school = st.selectbox(
            "流派视角",
            ["", "A", "B", "C", "D", "E", "F", "G", "H", "I"],
            index=["", "A", "B", "C", "D", "E", "F", "G", "H", "I"].index(default_school)
            if default_school in ["", "A", "B", "C", "D", "E", "F", "G", "H", "I"]
            else 0,
            format_func=lambda x: "默认（全评委）" if x == "" else x,
        )
    with col4:
        no_resume = st.checkbox("强制重抓", value=False, help="等同于 UZI 的 --no-resume")

    output_root = st.text_input(
        "输出目录",
        value=getattr(config, "UZI_REPORT_ROOT", "data/uzi-reports"),
        help="UZI 生成的 HTML 报告会导出到这里",
    )

    if st.button("🚀 运行 new-skill-uzi", type="primary", width="stretch"):
        if not ticker.strip():
            st.error("请输入股票代码或名称")
            return

        try:
            adapter = UZISkillAdapter(
                repo_root=getattr(config, "UZI_SKILL_ROOT", "") or None,
                output_root=output_root,
            )
        except Exception as e:
            st.error(f"UZI 仓库不可用: {e}")
            st.info("请把 UZI-Skill-main 放到容器可见位置，或设置 `UZI_SKILL_ROOT`。")
            return

        with st.spinner("UZI 正在运行深度分析，请稍候..."):
            result = adapter.run(
                ticker.strip(),
                depth=depth,
                school=school or None,
                no_resume=no_resume,
            )

        st.session_state.uzi_last_result = result

    result = st.session_state.get("uzi_last_result")
    if not result:
        st.caption("运行后会在这里显示报告。")
        return

    st.markdown("---")

    if not result.success:
        st.error(f"分析失败: {result.error}")
        with st.expander("运行日志"):
            if result.stdout:
                st.text_area("stdout", result.stdout, height=180)
            if result.stderr:
                st.text_area("stderr", result.stderr, height=180)
        return

    meta = result.report_meta or {}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("输出目录", Path(result.output_dir).name)
    with col2:
        st.metric("报告文件", "index.html")
    with col3:
        st.metric("仓库", Path(result.repo_root).name)

    if meta.get("one_liner"):
        st.info(meta["one_liner"])

    if result.report_path and Path(result.report_path).exists():
        html_content = _read_html(result.report_path)
        st.download_button(
            "下载 HTML 报告",
            data=html_content.encode("utf-8"),
            file_name=f"{Path(result.output_dir).name}.html",
            mime="text/html",
            width="stretch",
        )
        with st.expander("预览报告", expanded=True):
            components.html(html_content, height=900, scrolling=True)
    else:
        st.warning("UZI 已运行成功，但没有找到 index.html。")

    with st.expander("运行信息"):
        st.code(" ".join(result.command or []))
        if result.stdout:
            st.text_area("stdout", result.stdout, height=180)
        if result.stderr:
            st.text_area("stderr", result.stderr, height=180)
