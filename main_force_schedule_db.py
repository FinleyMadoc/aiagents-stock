#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力选股定时任务数据库
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None


class MainForceScheduleDatabase:
    """主力选股定时任务和执行结果存储"""

    DEFAULT_DB_PATH = os.path.join("data", "main_force_scheduler", "main_force_scheduler.db")
    DEFAULT_REPORT_DIR = os.path.join("data", "main_force_scheduler", "reports")
    DEFAULT_TIMES = ["09:15", "09:45", "13:30"]

    def __init__(self, db_path: str = None, report_dir: str = None):
        self.db_path = db_path or os.getenv("MAIN_FORCE_SCHEDULER_DB", self.DEFAULT_DB_PATH)
        self.report_dir = report_dir or os.getenv("MAIN_FORCE_SCHEDULER_REPORT_DIR", self.DEFAULT_REPORT_DIR)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        os.makedirs(self.report_dir, exist_ok=True)
        self._init_database()
        self.ensure_default_tasks()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_settings (
                config_key TEXT PRIMARY KEY,
                config_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL UNIQUE,
                schedule_time TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                params_json TEXT NOT NULL,
                last_run_at TEXT,
                last_status TEXT,
                last_message TEXT,
                last_result_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL,
                schedule_time TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration REAL DEFAULT 0,
                total_stocks INTEGER DEFAULT 0,
                filtered_stocks INTEGER DEFAULT 0,
                recommendation_count INTEGER DEFAULT 0,
                recommendations_json TEXT,
                result_json TEXT,
                report_path TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_main_force_run_created_at
            ON run_history(created_at DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_main_force_run_task
            ON run_history(task_key, created_at DESC)
        """)

        conn.commit()
        conn.close()

    def _default_params(self) -> Dict:
        return {
            "start_date": None,
            "days_ago": 90,
            "final_n": 5,
            "max_range_change": 30.0,
            "min_market_cap": 50.0,
            "max_market_cap": 5000.0,
            "main_board_only": True,
        }

    def ensure_default_tasks(self):
        """首次初始化时写入 09:15、09:45、13:30 三个默认任务。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM scheduled_tasks")
        task_count = cursor.fetchone()[0]

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            INSERT OR IGNORE INTO scheduler_settings (config_key, config_value, updated_at)
            VALUES ('scheduler_enabled', 'false', ?)
            """,
            (now,),
        )

        if task_count == 0:
            for schedule_time in self.DEFAULT_TIMES:
                task_key = self._task_key_for_time(schedule_time)
                cursor.execute(
                    """
                    INSERT INTO scheduled_tasks
                    (task_key, schedule_time, enabled, params_json, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?, ?)
                    """,
                    (
                        task_key,
                        schedule_time,
                        json.dumps(self._default_params(), ensure_ascii=False),
                        now,
                        now,
                    ),
                )

        conn.commit()
        conn.close()

    def _task_key_for_time(self, schedule_time: str) -> str:
        return f"main_force_{schedule_time.replace(':', '')}"

    def _clean_value(self, value):
        if value is None:
            return None
        if pd is not None and isinstance(value, pd.DataFrame):
            return value.head(200).to_dict("records")
        if pd is not None and isinstance(value, pd.Series):
            return value.to_dict()
        if isinstance(value, dict):
            return {str(k): self._clean_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean_value(v) for v in value]
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def is_scheduler_enabled(self) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT config_value FROM scheduler_settings WHERE config_key = 'scheduler_enabled'"
        )
        row = cursor.fetchone()
        conn.close()
        return bool(row and row["config_value"].lower() == "true")

    def set_scheduler_enabled(self, enabled: bool):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO scheduler_settings (config_key, config_value, updated_at)
            VALUES ('scheduler_enabled', ?, ?)
            ON CONFLICT(config_key) DO UPDATE SET
                config_value = excluded.config_value,
                updated_at = excluded.updated_at
            """,
            ("true" if enabled else "false", now),
        )
        conn.commit()
        conn.close()

    def get_tasks(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM scheduled_tasks
            ORDER BY schedule_time ASC
            """
        )
        rows = cursor.fetchall()
        conn.close()

        tasks = []
        for row in rows:
            try:
                params = json.loads(row["params_json"] or "{}")
            except Exception:
                params = self._default_params()
            tasks.append({
                "id": row["id"],
                "task_key": row["task_key"],
                "schedule_time": row["schedule_time"],
                "enabled": bool(row["enabled"]),
                "params": params,
                "last_run_at": row["last_run_at"],
                "last_status": row["last_status"],
                "last_message": row["last_message"],
                "last_result_id": row["last_result_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        return tasks

    def add_task(self, schedule_time: str, enabled: bool = True, params: Dict = None) -> int:
        self._validate_time(schedule_time)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO scheduled_tasks
            (task_key, schedule_time, enabled, params_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._task_key_for_time(schedule_time),
                schedule_time,
                1 if enabled else 0,
                json.dumps(params or self._default_params(), ensure_ascii=False),
                now,
                now,
            ),
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def update_task(self, task_id: int, schedule_time: str, enabled: bool, params: Dict = None):
        self._validate_time(schedule_time)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE scheduled_tasks
            SET task_key = ?, schedule_time = ?, enabled = ?, params_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                self._task_key_for_time(schedule_time),
                schedule_time,
                1 if enabled else 0,
                json.dumps(params or self._default_params(), ensure_ascii=False),
                now,
                task_id,
            ),
        )
        conn.commit()
        conn.close()

    def delete_task(self, task_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def save_run_history(
        self,
        task_key: str,
        schedule_time: str,
        status: str,
        message: str,
        start_time: datetime,
        end_time: datetime,
        result: Dict = None,
        report_path: str = None,
    ) -> int:
        result = result or {}
        recommendations = result.get("final_recommendations", []) or []
        total_stocks = int(result.get("total_stocks") or result.get("total_fetched") or 0)
        filtered_stocks = int(result.get("filtered_stocks") or result.get("filtered_count") or 0)
        duration = (end_time - start_time).total_seconds() if end_time else 0
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cleaned_result = self._clean_value(result)
        cleaned_recommendations = self._clean_value(recommendations)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO run_history
            (task_key, schedule_time, status, message, start_time, end_time, duration,
             total_stocks, filtered_stocks, recommendation_count, recommendations_json,
             result_json, report_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_key,
                schedule_time,
                status,
                message,
                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_time.strftime("%Y-%m-%d %H:%M:%S") if end_time else None,
                duration,
                total_stocks,
                filtered_stocks,
                len(recommendations),
                json.dumps(cleaned_recommendations, ensure_ascii=False, default=str),
                json.dumps(cleaned_result, ensure_ascii=False, default=str),
                report_path,
                created_at,
            ),
        )
        run_id = cursor.lastrowid

        cursor.execute(
            """
            UPDATE scheduled_tasks
            SET last_run_at = ?, last_status = ?, last_message = ?, last_result_id = ?, updated_at = ?
            WHERE task_key = ?
            """,
            (created_at, status, message, run_id, created_at, task_key),
        )

        conn.commit()
        conn.close()
        return run_id

    def get_run_history(self, limit: int = 50, task_key: str = None) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if task_key:
            cursor.execute(
                """
                SELECT *
                FROM run_history
                WHERE task_key = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (task_key, limit),
            )
        else:
            cursor.execute(
                """
                SELECT *
                FROM run_history
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_history(row) for row in rows]

    def get_run_by_id(self, run_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM run_history WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_history(row) if row else None

    def _row_to_history(self, row) -> Dict:
        def loads(value, default):
            try:
                return json.loads(value) if value else default
            except Exception:
                return default

        return {
            "id": row["id"],
            "task_key": row["task_key"],
            "schedule_time": row["schedule_time"],
            "status": row["status"],
            "message": row["message"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "duration": row["duration"],
            "total_stocks": row["total_stocks"],
            "filtered_stocks": row["filtered_stocks"],
            "recommendation_count": row["recommendation_count"],
            "recommendations": loads(row["recommendations_json"], []),
            "result": loads(row["result_json"], {}),
            "report_path": row["report_path"],
            "created_at": row["created_at"],
        }

    def save_markdown_report(self, content: str, run_time: datetime, task_key: str) -> str:
        filename = f"{run_time.strftime('%Y%m%d_%H%M%S')}_{task_key}.md"
        report_path = os.path.join(self.report_dir, filename)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
        return report_path

    def _validate_time(self, schedule_time: str):
        datetime.strptime(schedule_time, "%H:%M")


main_force_schedule_db = MainForceScheduleDatabase()
