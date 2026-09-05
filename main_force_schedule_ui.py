#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力选股定时任务UI
"""

import os
from datetime import datetime, time as dt_time

import pandas as pd
import streamlit as st

from main_force_scheduler import main_force_scheduler


def display_main_force_schedule_page():
    """显示主力选股定时任务页面"""

    st.markdown("## ⏰ 主力选股定时任务")
    st.caption("仅在周一到周五按设定时间自动执行主力选股，并把结果保存到本地数据库与报告目录。")

    status = main_force_scheduler.get_status()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("任务数", status.get("task_count", 0))
    with col2:
        st.metric("启用数", status.get("enabled_count", 0))
    with col3:
        st.metric("运行状态", "运行中" if status.get("running") else "已停止")
    with col4:
        st.metric("调度开关", "开启" if status.get("scheduler_enabled") else "关闭")

    col5, col6 = st.columns(2)
    with col5:
        st.info(f"数据库: {status.get('db_path', '')}")
    with col6:
        st.info(f"报告目录: {status.get('report_dir', '')}")

    if status.get("next_run_time"):
        st.success(f"下一次运行: {status['next_run_time']}")
    if status.get("last_run_time"):
        st.caption(f"上次运行: {status['last_run_time']}")
    if status.get("last_error"):
        st.warning(f"最近错误: {status['last_error']}")

    st.markdown("---")

    tab1, tab2 = st.tabs(["任务配置", "执行历史"])

    with tab1:
        display_task_config_section()

    with tab2:
        display_run_history_section()


def display_task_config_section():
    tasks = main_force_scheduler.get_tasks()

    st.markdown("### 任务列表")

    if not tasks:
        st.info("暂无任务")
    else:
        for task in tasks:
            with st.container(border=True):
                col_a, col_b, col_c, col_d = st.columns([1.4, 1.1, 1, 1])
                with col_a:
                    current_time = datetime.strptime(task["schedule_time"], "%H:%M").time()
                    new_time = st.time_input(
                        "运行时间",
                        value=current_time,
                        key=f"task_time_{task['id']}",
                        format="24h",
                    )
                with col_b:
                    enabled = st.checkbox(
                        "启用",
                        value=task.get("enabled", True),
                        key=f"task_enabled_{task['id']}",
                    )
                with col_c:
                    if st.button("保存", key=f"save_task_{task['id']}", type="primary"):
                        try:
                            main_force_scheduler.update_task_params(task["id"], task.get("params", {}))
                            main_force_scheduler.set_task_time(task["id"], new_time.strftime("%H:%M"))
                            main_force_scheduler.set_task_enabled(task["id"], enabled)
                            st.success("已保存")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"保存失败: {exc}")
                with col_d:
                    if st.button("删除", key=f"delete_task_{task['id']}"):
                        if len(tasks) <= 1:
                            st.warning("至少保留一个任务")
                        else:
                            if main_force_scheduler.delete_task(task["id"]):
                                st.success("已删除")
                                st.rerun()
                            else:
                                st.error("删除失败")

                params = task.get("params", {})
                col_p1, col_p2, col_p3, col_p4, col_p5 = st.columns(5)
                with col_p1:
                    st.caption(f"days_ago: {params.get('days_ago', 90)}")
                with col_p2:
                    st.caption(f"final_n: {params.get('final_n', 5)}")
                with col_p3:
                    st.caption(f"最大涨跌幅: {params.get('max_range_change', 30.0)}%")
                with col_p4:
                    st.caption(f"最小市值: {params.get('min_market_cap', 50.0)}亿")
                with col_p5:
                    st.caption(f"最大市值: {params.get('max_market_cap', 5000.0)}亿")
                st.caption(f"仅保留主板(6/0开头): {params.get('main_board_only', True)}")

    st.markdown("---")

    st.markdown("### 批量参数")
    st.caption("这里修改的是所有任务共同使用的主力选股参数。")

    first_params = tasks[0].get("params", {}) if tasks else {}
    with st.form("main_force_global_params"):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            days_ago = st.number_input(
                "回看天数",
                min_value=7,
                max_value=730,
                value=int(first_params.get("days_ago", 90)),
                step=1,
            )
        with col_b:
            final_n = st.number_input(
                "最终精选数量",
                min_value=1,
                max_value=20,
                value=int(first_params.get("final_n", 5)),
                step=1,
            )
        with col_c:
            max_range_change = st.number_input(
                "最大涨跌幅(%)",
                min_value=1.0,
                max_value=300.0,
                value=float(first_params.get("max_range_change", 30.0)),
                step=1.0,
            )

        col_d, col_e, col_f = st.columns(3)
        with col_d:
            min_market_cap = st.number_input(
                "最小市值(亿)",
                min_value=1.0,
                max_value=10000.0,
                value=float(first_params.get("min_market_cap", 50.0)),
                step=1.0,
            )
        with col_e:
            max_market_cap = st.number_input(
                "最大市值(亿)",
                min_value=10.0,
                max_value=100000.0,
                value=float(first_params.get("max_market_cap", 5000.0)),
                step=10.0,
            )
        with col_f:
            main_board_only = st.checkbox(
                "仅保留主板股票(6/0开头)",
                value=bool(first_params.get("main_board_only", True)),
                help="勾选后会过滤掉创业板、科创板、北交所等非6/0开头股票",
            )

        if st.form_submit_button("应用到全部任务", type="primary"):
            params = {
                "start_date": None,
                "days_ago": int(days_ago),
                "final_n": int(final_n),
                "max_range_change": float(max_range_change),
                "min_market_cap": float(min_market_cap),
                "max_market_cap": float(max_market_cap),
                "main_board_only": bool(main_board_only),
            }
            for task in tasks:
                main_force_scheduler.update_task_params(task["id"], params)
            st.success("已应用到全部任务")
            st.rerun()

    st.markdown("---")

    st.markdown("### 新增任务")
    col_new_1, col_new_2, col_new_3 = st.columns(3)
    with col_new_1:
        new_time = st.time_input("新增时间", value=dt_time(9, 15), key="new_task_time", format="24h")
    with col_new_2:
        new_enabled = st.checkbox("新增后启用", value=True, key="new_task_enabled")
    with col_new_3:
        st.write("")
        st.write("")
        if st.button("添加任务", type="primary"):
            if main_force_scheduler.add_task(new_time.strftime("%H:%M"), enabled=new_enabled):
                st.success("任务已添加")
                st.rerun()
            else:
                st.error("添加失败，时间可能已存在")

    st.markdown("---")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if status := main_force_scheduler.get_status():
            if status.get("running"):
                if st.button("停止调度器", type="secondary"):
                    main_force_scheduler.stop()
                    st.success("调度器已停止")
                    st.rerun()
            else:
                if st.button("启动调度器", type="primary"):
                    main_force_scheduler.start()
                    st.success("调度器已启动")
                    st.rerun()
    with col_b:
        if st.button("立即执行一次", type="primary"):
            with st.spinner("正在执行主力选股..."):
                main_force_scheduler.run_now()
            st.success("已触发执行")
            st.rerun()
    with col_c:
        if st.button("恢复默认 3 个时间点"):
            current_tasks = main_force_scheduler.get_tasks()
            for task in current_tasks:
                main_force_scheduler.delete_task(task["id"])
            for schedule_time in ["09:15", "09:45", "13:30"]:
                main_force_scheduler.add_task(schedule_time, enabled=True)
            st.success("已恢复默认时间点")
            st.rerun()


def display_run_history_section():
    st.markdown("### 执行历史")
    history = main_force_scheduler.db.get_run_history(limit=50)

    if not history:
        st.info("暂无执行历史")
        return

    history_df = pd.DataFrame(
        [
            {
                "ID": item["id"],
                "任务": item["schedule_time"],
                "状态": item["status"],
                "开始时间": item["start_time"],
                "耗时(秒)": round(item["duration"] or 0, 1),
                "总股票": item["total_stocks"],
                "筛选后": item["filtered_stocks"],
                "推荐数": item["recommendation_count"],
            }
            for item in history
        ]
    )
    st.dataframe(history_df, width="stretch", hide_index=True)

    st.markdown("---")

    for item in history:
        title = f"{item['start_time']} | {item['schedule_time']} | {item['status']} | 推荐 {item['recommendation_count']} 只"
        with st.expander(title, expanded=False):
            st.write(f"**消息**: {item.get('message') or '无'}")
            st.write(f"**开始**: {item.get('start_time')}")
            st.write(f"**结束**: {item.get('end_time')}")
            st.write(f"**耗时**: {round(item.get('duration') or 0, 2)} 秒")
            st.write(f"**报告文件**: {item.get('report_path') or '未生成'}")

            if item.get("recommendations"):
                rec_df = pd.DataFrame(
                    [
                        {
                            "排名": rec.get("rank"),
                            "代码": rec.get("symbol"),
                            "名称": rec.get("name"),
                            "仓位": rec.get("position"),
                            "周期": rec.get("investment_period"),
                        }
                        for rec in item["recommendations"]
                    ]
                )
                st.dataframe(rec_df, width="stretch", hide_index=True)

            if item.get("report_path") and os.path.exists(item["report_path"]):
                with open(item["report_path"], "r", encoding="utf-8") as f:
                    report_text = f.read()
                st.download_button(
                    "下载报告",
                    data=report_text,
                    file_name=os.path.basename(item["report_path"]),
                    mime="text/markdown",
                    key=f"download_report_{item['id']}",
                )
                st.text_area(
                    "报告预览",
                    value=report_text[:4000],
                    height=240,
                    key=f"preview_report_{item['id']}",
                )
