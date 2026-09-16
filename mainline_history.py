#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent JSON history for A-share mainline analyses."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_HISTORY_DIR = Path("data/mainline/history")
DEFAULT_HISTORY_LIMIT = 100


class MainlineHistoryStore:
    """Store and load complete mainline result JSON files."""

    def __init__(
        self,
        directory: Optional[str | Path] = None,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self.directory = Path(directory or DEFAULT_HISTORY_DIR)
        self.limit = max(int(limit), 1)

    def save(self, result: Dict[str, Any]) -> Dict[str, str]:
        """Save one result and return its stable history metadata."""
        self.directory.mkdir(parents=True, exist_ok=True)
        generated_at = str(result.get("generated_at", "") or "")
        stamp = self._timestamp(generated_at)
        filename = f"mainline_{stamp}_{datetime.now().strftime('%f')}.json"
        path = self.directory / filename
        history = {
            "id": path.stem,
            "path": str(path),
            "generated_at": generated_at,
        }
        result["history"] = history
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self._prune()
        return history

    def list_records(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return lightweight metadata ordered newest first."""
        records: List[Dict[str, Any]] = []
        files = sorted(
            self.directory.glob("mainline_*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ) if self.directory.exists() else []
        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            summary = payload.get("mainline_summary", {}) or {}
            weekly = summary.get("weekly", []) or []
            monthly = summary.get("monthly", []) or []
            records.append(
                {
                    "id": path.stem,
                    "path": str(path),
                    "generated_at": payload.get("generated_at", ""),
                    "ai_used": bool(payload.get("ai_used", False)),
                    "thinking_mode": bool(payload.get("thinking_mode", False)),
                    "weekly_top": self._top_sector(weekly),
                    "monthly_top": self._top_sector(monthly),
                    "weekly_count": len(weekly),
                    "monthly_count": len(monthly),
                }
            )
        return records[: max(1, int(limit or self.limit))]

    def load(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Load a history result by stem id, rejecting paths outside the store."""
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", str(record_id or ""))
        if not safe_id or safe_id != str(record_id):
            return None
        path = (self.directory / f"{safe_id}.json").resolve()
        try:
            path.relative_to(self.directory.resolve())
        except ValueError:
            return None
        if not path.exists() or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def _prune(self) -> None:
        files = sorted(
            self.directory.glob("mainline_*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in files[self.limit :]:
            try:
                path.unlink()
            except OSError:
                pass

    @staticmethod
    def _top_sector(groups: List[Dict[str, Any]]) -> str:
        if not groups or not isinstance(groups[0], dict):
            return "暂无"
        return str(groups[0].get("sector", "暂无") or "暂无")

    @staticmethod
    def _timestamp(value: str) -> str:
        parsed = value.replace("Z", "+00:00") if value else ""
        try:
            return datetime.fromisoformat(parsed).strftime("%Y%m%d_%H%M%S")
        except ValueError:
            return datetime.now().strftime("%Y%m%d_%H%M%S")
