"""
You.com Research API 客户端模块
用于获取带有多步推理和引用来源的研究级答案

API文档: https://you.com/specs/openapi_research.yaml
"""

import os
import requests
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

# API 配置
RESEARCH_API_URL = "https://api.you.com/v1/research"
DEFAULT_TIMEOUT = 60  # 研究API响应较慢，适当延长超时时间

# 可通过环境变量配置搜索深度
_RESEARCH_EFFORT = os.getenv("YDC_RESEARCH_EFFORT", "standard").strip()
_VALID_EFFORTS = {"lite", "standard", "deep", "exhaustive"}


def _resolve_effort(effort: str | None) -> str:
    """解析effort参数，超出范围时回退到standard"""
    if effort and effort in _VALID_EFFORTS:
        return effort
    if _RESEARCH_EFFORT in _VALID_EFFORTS:
        return _RESEARCH_EFFORT
    return "standard"


def get_youdotcom_research(
    query: str,
    effort: Literal["lite", "standard", "deep", "exhaustive"] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    调用 You.com Research API，获取研究级答案。

    Args:
        query: 研究问题或复杂查询（最长40000字符）
        effort: 搜索深度。
            - lite: 快速返回，适合简单问题
            - standard: 平衡速度和深度（默认）
            - deep: 更深入的交叉验证
            - exhaustive: 最全面，适合复杂研究任务
            如果为 None，优先读取环境变量 YDC_RESEARCH_EFFORT，
            均无则使用 "standard"。
        timeout: 请求超时时间（秒）

    Returns:
        {
            "content": str,      # Markdown格式的答案，含编号引用
            "sources": [         # 使用的网络来源列表
                {
                    "url": str,
                    "title": str,
                    "snippets": [str, ...]  # 关键摘录，评估来源相关性
                },
                ...
            ],
            "success": bool,
            "error": str | None
        }
    """
    api_key = os.getenv("YDC_API_KEY", "").strip()
    if not api_key:
        return _error_result(
            "YDC_API_KEY environment variable is not set. "
            "Please configure your You.com API key in the .env file."
        )

    resolved_effort = _resolve_effort(effort)

    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "input": query,
        "research_effort": resolved_effort,
    }

    try:
        response = requests.post(
            RESEARCH_API_URL,
            json=payload,
            headers=headers,
            timeout=timeout,
        )

        if response.status_code == 401:
            return _error_result("You.com API key is invalid or expired.")
        elif response.status_code == 403:
            return _error_result(
                "You.com API key lacks the required scope for the Research endpoint."
            )
        elif response.status_code == 422:
            return _error_result(f"Invalid request parameters: {response.text}")
        elif not response.ok or response.status_code >= 400:
            return _error_result(
                f"You.com Research API error: {response.status_code} {response.status_text}"
            )

        data = response.json()

        # 防御性解析：output 可能是 dict、list 或其他类型
        output = data.get("output")
        if not isinstance(output, dict):
            # output 结构不符合预期，返回原始数据供调试
            return {
                "content": str(output) if output else "",
                "sources": [],
                "success": False,
                "error": f"Unexpected API response structure: {type(output).__name__}",
            }

        # 安全提取各字段
        raw_content = output.get("content")
        content = raw_content if isinstance(raw_content, str) else ""

        raw_sources = output.get("sources")
        sources = (
            [s for s in raw_sources if isinstance(s, dict)]
            if isinstance(raw_sources, list)
            else []
        )

        return {
            "content": content,
            "sources": [
                {
                    "url": str(s.get("url", "")),
                    "title": str(s.get("title", "N/A")),
                    "snippets": [
                        str(sn) for sn in s.get("snippets", [])
                        if sn is not None
                    ],
                }
                for s in sources
            ],
            "success": True,
            "error": None,
        }

    except requests.exceptions.Timeout:
        return _error_result(f"Request timed out after {timeout} seconds.")
    except requests.exceptions.RequestException as e:
        return _error_result(f"Request failed: {str(e)}")
    except Exception as e:
        return _error_result(f"Unexpected error: {str(e)}")


def _error_result(message: str) -> dict:
    return {
        "content": "",
        "sources": [],
        "success": False,
        "error": message,
    }


def format_research_for_ai(
    research_result: dict,
    max_content_length: int = 8000,
    max_snippet_length: int = 300,
) -> str:
    """
    将研究结果格式化为适合AI分析师阅读的文本。

    Args:
        research_result: get_youdotcom_research() 的返回结果
        max_content_length: 内容最大长度（字符），超出部分截断
        max_snippet_length: 每个来源摘录的最大长度（字符）

    Returns:
        格式化后的字符串，供AI智能体使用
    """
    if not research_result:
        return "【You.com研究结果】\n获取失败: 返回结果为空\n"

    if not research_result.get("success"):
        error = research_result.get("error", "Unknown error")
        return f"【You.com研究结果】\n获取失败: {error}\n"

    content = research_result.get("content", "") or ""

    # 截断过长内容
    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n...(内容过长，已截断)"

    sources = research_result.get("sources") or []
    if not isinstance(sources, list):
        sources = []

    parts = ["【You.com深度研究结果】\n"]
    parts.append(content)

    if sources:
        parts.append("\n【参考来源】")
        for i, src in enumerate(sources[:10], 1):
            title = src.get("title", "N/A") or "N/A"
            url = src.get("url", "") or ""
            snippets = src.get("snippets") or []
            if not isinstance(snippets, list):
                snippets = []

            parts.append(f"\n{i}. {title}")
            if url:
                parts.append(f"   {url}")

            # 包含关键摘录，帮助智能体评估来源相关性
            if snippets:
                top_snippet = snippets[0]
                if isinstance(top_snippet, str) and top_snippet:
                    snippet_text = (
                        top_snippet[:max_snippet_length]
                        + "..."
                        if len(top_snippet) > max_snippet_length
                        else top_snippet
                    )
                    parts.append(f"   摘录: {snippet_text}")

    return "\n".join(parts)
