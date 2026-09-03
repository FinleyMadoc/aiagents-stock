#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力选股定时调度器
"""

import os
import schedule
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

from main_force_analysis import MainForceAnalyzer
from main_force_pdf_generator import generate_main_force_markdown_report
from main_force_schedule_db import main_force_schedule_db


class MainForceScheduler:
    """主力选股定时任务调度器"""

    def __init__(self):
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.analysis_lock = threading.Lock()
        self.db = main_force_schedule_db
        self.last_run_time = None
        self.last_result = None
        self.last_error = None
        self._ensure_default_jobs()

    def _ensure_default_jobs(self):
        """确保数据库里有默认任务配置"""
        self.db.ensure_default_tasks()

    def get_tasks(self) -> List[Dict]:
        return self.db.get_tasks()

    def set_task_enabled(self, task_id: int, enabled: bool):
        tasks = self.get_tasks()
        task = next((item for item in tasks if item["id"] == task_id), None)
        if not task:
            return
        self.db.update_task(task_id, task["schedule_time"], enabled, task.get("params"))
        if self.running:
            self._reschedule()

    def set_task_time(self, task_id: int, schedule_time: str):
        tasks = self.get_tasks()
        task = next((item for item in tasks if item["id"] == task_id), None)
        if not task:
            return
        self.db.update_task(task_id, schedule_time, task["enabled"], task.get("params"))
        if self.running:
            self._reschedule()

    def update_task_params(self, task_id: int, params: Dict):
        tasks = self.get_tasks()
        task = next((item for item in tasks if item["id"] == task_id), None)
        if not task:
            return
        self.db.update_task(task_id, task["schedule_time"], task["enabled"], params)
        if self.running:
            self._reschedule()

    def add_task(self, schedule_time: str, enabled: bool = True, params: Dict = None) -> bool:
        try:
            self.db.add_task(schedule_time, enabled=enabled, params=params)
            if self.running:
                self._reschedule()
            return True
        except Exception:
            return False

    def delete_task(self, task_id: int) -> bool:
        deleted = self.db.delete_task(task_id)
        if deleted and self.running:
            self._reschedule()
        return deleted

    def set_scheduler_enabled(self, enabled: bool):
        self.db.set_scheduler_enabled(enabled)

    def is_scheduler_enabled(self) -> bool:
        return self.db.is_scheduler_enabled()

    def start(self) -> bool:
        if self.running:
            return True

        self._reschedule()
        self.running = True
        self.set_scheduler_enabled(True)
        self.thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self) -> bool:
        if not self.running:
            self.set_scheduler_enabled(False)
            return True

        self.running = False
        self.set_scheduler_enabled(False)
        self._clear_jobs()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None
        return True

    def _schedule_loop(self):
        while self.running:
            try:
                schedule.run_pending()
            except Exception as exc:
                self.last_error = str(exc)
            time.sleep(20)

    def _clear_jobs(self):
        jobs_to_remove = [job for job in schedule.jobs if "main_force_scheduler" in job.tags]
        for job in jobs_to_remove:
            schedule.cancel_job(job)

    def _reschedule(self):
        with self.lock:
            self._clear_jobs()
            for task in self.get_tasks():
                if not task.get("enabled", True):
                    continue
                job = schedule.every().day.at(task["schedule_time"]).do(self._run_task_safe, task["id"])
                job.tag("main_force_scheduler", task["task_key"])

    def _run_task_safe(self, task_id: int):
        if not self.analysis_lock.acquire(blocking=False):
            task = self._get_task(task_id)
            if task:
                self._save_run(task, "skipped", "上一次任务尚未完成，跳过本次执行", None, None, None)
            return

        try:
            task = self._get_task(task_id)
            if not task:
                return
            self._run_task(task)
        finally:
            self.analysis_lock.release()

    def _get_task(self, task_id: int) -> Optional[Dict]:
        return next((item for item in self.get_tasks() if item["id"] == task_id), None)

    def _run_task(self, task: Dict):
        start_time = datetime.now()
        self.last_run_time = start_time
        self.last_error = None

        params = task.get("params") or {}
        try:
            analyzer = MainForceAnalyzer()
            result = analyzer.run_full_analysis(
                start_date=params.get("start_date"),
                days_ago=params.get("days_ago"),
                final_n=params.get("final_n", 5),
                max_range_change=params.get("max_range_change", 30.0),
                min_market_cap=params.get("min_market_cap", 50.0),
                max_market_cap=params.get("max_market_cap", 5000.0),
            )

            report_path = None
            if result.get("success"):
                try:
                    markdown = generate_main_force_markdown_report(analyzer, result)
                    report_path = self.db.save_markdown_report(markdown, start_time, task["task_key"])
                except Exception as report_error:
                    self.last_error = f"报告生成失败: {report_error}"

            status = "success" if result.get("success") else "failed"
            message = result.get("error") if not result.get("success") else "执行完成"
            run_id = self._save_run(task, status, message, start_time, datetime.now(), result, report_path)

            self.last_result = {
                "run_id": run_id,
                "task": task,
                "result": result,
                "report_path": report_path,
            }
        except Exception as exc:
            self.last_error = str(exc)
            self._save_run(task, "error", str(exc), start_time, datetime.now(), {"error": str(exc)}, None)

    def _save_run(
        self,
        task: Dict,
        status: str,
        message: str,
        start_time: datetime,
        end_time: Optional[datetime],
        result: Dict,
        report_path: str = None,
    ) -> int:
        end_time = end_time or datetime.now()
        return self.db.save_run_history(
            task_key=task["task_key"],
            schedule_time=task["schedule_time"],
            status=status,
            message=message,
            start_time=start_time,
            end_time=end_time,
            result=result,
            report_path=report_path,
        )

    def run_now(self, task_id: int = None) -> bool:
        tasks = self.get_tasks()
        if not tasks:
            return False

        if task_id is not None:
            task = self._get_task(task_id)
            if not task:
                return False
            self._run_task_safe(task["id"])
            return True

        enabled_tasks = [task for task in tasks if task.get("enabled", True)]
        if not enabled_tasks:
            return False

        self._run_task_safe(enabled_tasks[0]["id"])
        return True

    def get_next_run_time(self) -> Optional[str]:
        jobs = [job for job in schedule.jobs if "main_force_scheduler" in job.tags and getattr(job, "next_run", None)]
        if not jobs:
            return None
        next_job = min(jobs, key=lambda job: job.next_run)
        return next_job.next_run.strftime("%Y-%m-%d %H:%M:%S")

    def get_status(self) -> Dict:
        tasks = self.get_tasks()
        running_jobs = [job for job in schedule.jobs if "main_force_scheduler" in job.tags]
        enabled_count = sum(1 for task in tasks if task.get("enabled", True))
        return {
            "running": self.running,
            "scheduler_enabled": self.is_scheduler_enabled(),
            "task_count": len(tasks),
            "enabled_count": enabled_count,
            "next_run_time": self.get_next_run_time(),
            "last_run_time": self.last_run_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_run_time else None,
            "last_error": self.last_error,
            "job_count": len(running_jobs),
            "db_path": self.db.db_path,
            "report_dir": self.db.report_dir,
        }


main_force_scheduler = MainForceScheduler()

if main_force_scheduler.is_scheduler_enabled():
    main_force_scheduler.start()
