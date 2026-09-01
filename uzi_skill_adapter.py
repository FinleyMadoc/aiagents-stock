"""UZI 个股深度分析适配器。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UZIResult:
    success: bool
    ticker: str
    repo_root: str
    output_dir: str
    report_path: str = ""
    report_meta: dict | None = None
    stdout: str = ""
    stderr: str = ""
    command: list[str] | None = None
    error: str = ""


class UZISkillAdapter:
    """调用外部 UZI-Skill 仓库生成个股深度分析报告。"""

    def __init__(self, repo_root: str | None = None, output_root: str | None = None) -> None:
        self.repo_root = self._resolve_repo_root(repo_root)
        self.output_root = self._resolve_output_root(output_root)

    @staticmethod
    def _candidate_paths() -> list[Path]:
        here = Path(__file__).resolve().parent
        env_root = os.getenv("UZI_SKILL_ROOT", "").strip()
        return [
            Path(env_root).expanduser() if env_root else None,
            here / "UZI-Skill-main",
            here.parent / "UZI-Skill-main",
            Path("/app/UZI-Skill-main"),
            Path("/data/UZI-Skill-main"),
        ]

    def _resolve_repo_root(self, repo_root: str | None) -> Path:
        candidates = [Path(repo_root).expanduser() if repo_root else None] + self._candidate_paths()
        for candidate in candidates:
            if candidate and self._is_valid_repo(candidate):
                return candidate.resolve()
        raise FileNotFoundError(
            "未找到 UZI-Skill 仓库。请设置 UZI_SKILL_ROOT，或把仓库挂载到容器可见位置。"
        )

    @staticmethod
    def _resolve_output_root(output_root: str | None) -> Path:
        root = Path(output_root or os.getenv("UZI_REPORT_ROOT", "data/uzi-reports")).expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    @staticmethod
    def _is_valid_repo(path: Path) -> bool:
        return path.exists() and path.is_dir() and (path / "run.py").exists()

    @staticmethod
    def _safe_name(ticker: str) -> str:
        return "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in ticker.strip()) or "ticker"

    def run(
        self,
        ticker: str,
        *,
        depth: str | None = None,
        school: str | None = None,
        no_resume: bool = False,
    ) -> UZIResult:
        safe_ticker = self._safe_name(ticker)
        out_dir = self.output_root / f"{safe_ticker}_{time.strftime('%Y%m%d_%H%M%S')}"
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            "run.py",
            ticker,
            "--no-browser",
            "--output-dir",
            str(out_dir),
        ]
        if depth:
            cmd.extend(["--depth", depth])
        if school:
            cmd.extend(["--school", school])
        if no_resume:
            cmd.append("--no-resume")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("UZI_NO_AUTO_OPEN", "1")

        proc = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )

        report_path = out_dir / "index.html"
        meta_path = out_dir / "report.meta.json"
        report_meta = None
        if meta_path.exists():
            try:
                report_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                report_meta = None

        success = proc.returncode == 0 and report_path.exists()
        return UZIResult(
            success=success,
            ticker=ticker,
            repo_root=str(self.repo_root),
            output_dir=str(out_dir),
            report_path=str(report_path) if report_path.exists() else "",
            report_meta=report_meta,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            command=cmd,
            error="" if success else (proc.stderr.strip() or proc.stdout.strip() or f"UZI 运行失败，退出码 {proc.returncode}"),
        )
