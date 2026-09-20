"""Run locally installed Iwencai SkillHub skills from Python."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


logger = logging.getLogger(__name__)


class IwencaiSkillHubError(RuntimeError):
    """Raised when a SkillHub skill cannot be executed successfully."""


class IwencaiSkillHubClient:
    """Thin subprocess adapter for the three official Iwencai skills."""

    NEWS_SKILL = "news-search"
    SECTOR_SKILL = "hithink-sector-selector"
    STOCK_SKILL = "hithink-astock-selector"

    def __init__(
        self,
        skills_dir: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        project_root = Path(__file__).resolve().parents[1]
        try:
            from dotenv import load_dotenv

            load_dotenv(project_root / ".env", override=False)
        except Exception:
            self._load_env_file(project_root / ".env")

        configured_dir = skills_dir or os.getenv("IWENCAI_SKILLS_DIR", "skills")
        path = Path(configured_dir).expanduser()
        self.skills_dir = path if path.is_absolute() else project_root / path
        self.api_key = str(api_key or os.getenv("IWENCAI_API_KEY", "")).strip()
        self.base_url = str(
            base_url
            or os.getenv("IWENCAI_BASE_URL", "https://openapi.iwencai.com")
        ).rstrip("/")
        raw_timeout = timeout or os.getenv("IWENCAI_SKILL_TIMEOUT", "45")
        try:
            self.timeout = max(int(raw_timeout), 5)
        except (TypeError, ValueError):
            self.timeout = 45

    @staticmethod
    def _load_env_file(path: Path) -> None:
        """Load simple KEY=VALUE entries when python-dotenv is unavailable."""
        if not path.is_file():
            return
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[7:].strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            os.environ[key] = value

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def installed(self, slug: str) -> bool:
        return self._script_path(slug).is_file()

    def installation_status(self) -> Dict[str, bool]:
        return {
            slug: self.installed(slug)
            for slug in (self.NEWS_SKILL, self.SECTOR_SKILL, self.STOCK_SKILL)
        }

    def news_search(self, query: str, size: int = 20) -> Dict[str, Any]:
        requested_size = max(1, min(int(size), 100))
        logger.info(
            "[SkillHub] 开始调用 API: skill=%s query=%s size=%d base_url=%s",
            self.NEWS_SKILL,
            query,
            requested_size,
            self.base_url,
        )
        payload = self._run(
            self.NEWS_SKILL,
            [
                str(query),
                "--size",
                str(requested_size),
                "--base-url",
                self.base_url,
                "--timeout",
                str(self.timeout),
            ],
        )
        result = {
            "raw": payload,
            "articles": self.normalize_news(payload),
        }
        logger.info(
            "[SkillHub] API调用结果: skill=%s status=success count=%d trace_id=%s",
            self.NEWS_SKILL,
            len(result["articles"]),
            self._trace_id(payload),
        )
        return result

    def select_sectors(
        self, query: str, page: int = 1, limit: int = 20
    ) -> Dict[str, Any]:
        requested_page = max(int(page), 1)
        requested_limit = max(1, min(int(limit), 100))
        logger.info(
            "[SkillHub] 开始调用 API: skill=%s query=%s page=%d limit=%d base_url=%s",
            self.SECTOR_SKILL,
            query,
            requested_page,
            requested_limit,
            self.base_url,
        )
        payload = self._run(
            self.SECTOR_SKILL,
            [
                "--query",
                str(query),
                "--page",
                str(requested_page),
                "--limit",
                str(requested_limit),
                "--timeout",
                str(self.timeout),
            ],
        )
        logger.info(
            "[SkillHub] API调用结果: skill=%s status=success count=%d "
            "code_count=%s trace_id=%s",
            self.SECTOR_SKILL,
            self._data_count(payload),
            payload.get("code_count", self._data_count(payload)),
            self._trace_id(payload),
        )
        return payload

    def select_stocks(
        self, query: str, page: int = 1, limit: int = 100
    ) -> Dict[str, Any]:
        requested_page = max(int(page), 1)
        requested_limit = max(1, min(int(limit), 100))
        logger.info(
            "[SkillHub] 开始调用 API: skill=%s query=%s page=%d limit=%d base_url=%s",
            self.STOCK_SKILL,
            query,
            requested_page,
            requested_limit,
            self.base_url,
        )
        payload = self._run(
            self.STOCK_SKILL,
            [
                "--query",
                str(query),
                "--page",
                str(requested_page),
                "--limit",
                str(requested_limit),
                "--timeout",
                str(self.timeout),
            ],
        )
        logger.info(
            "[SkillHub] API调用结果: skill=%s status=success count=%d "
            "code_count=%s trace_id=%s",
            self.STOCK_SKILL,
            self._data_count(payload),
            payload.get("code_count", self._data_count(payload)),
            self._trace_id(payload),
        )
        return payload

    def _script_path(self, slug: str) -> Path:
        filename = "news_search.py" if slug == self.NEWS_SKILL else "cli.py"
        return self.skills_dir / slug / "scripts" / filename

    def _run(self, slug: str, arguments: List[str]) -> Dict[str, Any]:
        if not self.api_key:
            raise IwencaiSkillHubError("IWENCAI_API_KEY is not configured")
        script = self._script_path(slug)
        if not script.is_file():
            raise IwencaiSkillHubError(
                f"Skill {slug} is not installed at {script.parent.parent}"
            )

        environment = os.environ.copy()
        environment["IWENCAI_API_KEY"] = self.api_key
        environment["IWENCAI_BASE_URL"] = self.base_url
        started_at = time.monotonic()
        logger.info(
            "[SkillHub] 启动技能进程: skill=%s script=%s timeout=%ss",
            slug,
            script,
            self.timeout,
        )
        try:
            completed = subprocess.run(
                [sys.executable, str(script), *arguments],
                cwd=str(script.parent.parent),
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.timeout + 5,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error(
                "[SkillHub] API调用失败: skill=%s error=timeout duration=%.2fs",
                slug,
                time.monotonic() - started_at,
            )
            raise IwencaiSkillHubError(
                f"Skill {slug} timed out after {self.timeout} seconds"
            ) from exc

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if not stdout:
            logger.error(
                "[SkillHub] API调用失败: skill=%s return_code=%d duration=%.2fs error=%s",
                slug,
                completed.returncode,
                time.monotonic() - started_at,
                stderr or "empty response",
            )
            raise IwencaiSkillHubError(
                stderr or f"Skill {slug} returned an empty response"
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            logger.error(
                "[SkillHub] API调用失败: skill=%s return_code=%d duration=%.2fs "
                "error=invalid_json response_preview=%s",
                slug,
                completed.returncode,
                time.monotonic() - started_at,
                stdout[:300],
            )
            raise IwencaiSkillHubError(
                f"Skill {slug} returned invalid JSON: {stdout[:300]}"
            ) from exc
        if completed.returncode != 0:
            message = self._error_message(payload) or stderr
            logger.error(
                "[SkillHub] API调用失败: skill=%s return_code=%d duration=%.2fs error=%s",
                slug,
                completed.returncode,
                time.monotonic() - started_at,
                message or "unknown error",
            )
            raise IwencaiSkillHubError(
                message or f"Skill {slug} exited with code {completed.returncode}"
            )
        if not isinstance(payload, dict):
            payload = {"data": payload}
        logger.info(
            "[SkillHub] 技能进程完成: skill=%s return_code=%d duration=%.2fs "
            "response_keys=%s stdout_bytes=%d",
            slug,
            completed.returncode,
            time.monotonic() - started_at,
            list(payload.keys()),
            len(completed.stdout.encode("utf-8")),
        )
        return payload

    @staticmethod
    def _data_count(payload: Dict[str, Any]) -> int:
        rows = payload.get("datas", []) if isinstance(payload, dict) else []
        return len(rows) if isinstance(rows, list) else 0

    @staticmethod
    def _trace_id(payload: Dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        trace_id = payload.get("trace_id")
        if trace_id:
            return str(trace_id)
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("trace_id", ""))
        return ""

    @staticmethod
    def _error_message(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("error", "message", "msg", "text_response"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def normalize_news(cls, payload: Any) -> List[Dict[str, Any]]:
        """Extract common article fields without depending on one response envelope."""
        articles: List[Dict[str, Any]] = []
        seen = set()
        for item in cls._walk_dicts(payload):
            title = cls._first_text(item, ("title", "标题", "新闻标题", "name"))
            if not title:
                continue
            url = cls._first_text(item, ("url", "link", "链接", "新闻链接"))
            summary = cls._first_text(
                item, ("summary", "snippet", "description", "content", "摘要", "正文")
            )
            published_at = cls._first_text(
                item, ("published_at", "publishedAt", "publish_time", "time", "日期", "发布时间")
            )
            source = item.get("source", item.get("来源", item.get("media", "")))
            if isinstance(source, dict):
                source = cls._first_text(source, ("name", "title"))
            key = (title, url)
            if key in seen:
                continue
            seen.add(key)
            articles.append(
                {
                    "title": title,
                    "url": url,
                    "summary": summary[:500],
                    "description": summary[:500],
                    "published_at": published_at,
                    "source": str(source or "同花顺问财"),
                    "provider": "iwencai-skillhub",
                }
            )
        return articles

    @classmethod
    def _walk_dicts(cls, value: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from cls._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_dicts(child)

    @staticmethod
    def _first_text(item: Dict[str, Any], keys: Iterable[str]) -> str:
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
