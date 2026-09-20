"""
pywencai 安全调用辅助模块

解决 iwencai.com 服务器被屏蔽/返回 403 时
pywencai.get() 内部抛出 NoneType 异常的问题。

工作流程：
1. 先用 pywencai 直接调用（快速路径）
2. 失败后通过 Playwright 获取浏览器 cookies 重试（绕过 TLS 指纹限制）

💡 如遇选股失败，请在浏览器中登录 https://www.iwencai.com/screener
"""

import os
import logging
from importlib import import_module

logger = logging.getLogger(__name__)
_last_error = ""
_COOKIE_ENV_NAMES = (
    "IWENCAI_COOKIE",
    "IWENCAI_SESSION_COOKIE",
    "IWENCAI_COOKIES",
    "PYWENCAI_COOKIE",
    "WENCAI_COOKIE",
)


def get_last_error():
    """Return the latest redacted pywencai failure reason for diagnostics."""
    return _last_error


def safe_get(query, loop=True, cookie=None, **kwargs):
    """
    安全调用 pywencai.get，捕获内部 NoneType 异常。
    
    自动降级：常规调用失败后，尝试用浏览器 cookies 重试。
    
    Args:
        query: 问财查询语句
        loop: 是否翻页获取全部数据
        cookie: 可选的问财 Cookie；未提供时读取环境变量
        **kwargs: 传递给 pywencai.get 的其它参数
        
    Returns:
        正常时返回 pywencai 结果，失败时返回 None
    """
    global _last_error
    _last_error = ""

    configured_cookie = _normalize_cookie(cookie) or _get_configured_cookie()
    if configured_cookie:
        kwargs["cookie"] = configured_cookie

    # 尝试1: 直接调用（快速路径）
    result = _try_call(query, loop, **kwargs)
    if result is not None:
        _last_error = ""
        return result

    if configured_cookie:
        _last_error = (
            f"问财返回空响应；已传入Cookie长度={len(configured_cookie)}，"
            "请检查Cookie有效期、服务器出口IP和请求环境"
        )
        print(f"[pywencai] ❌ Cookie调用失败，暂不使用未登录浏览器重试")
        return None

    print(f"[pywencai] ⚠️ 直接调用失败，尝试浏览器会话...")

    # 尝试2: 用浏览器 cookies 重试（绕过 TLS 指纹验证）  
    try:
        from utils.iwencai_browser import get_browser_cookies
        cookie_str = get_browser_cookies()
        if cookie_str:
            kwargs_with_cookie = dict(kwargs)
            kwargs_with_cookie['cookie'] = cookie_str
            result = _try_call(query, loop, **kwargs_with_cookie)
            if result is not None:
                _last_error = ""
                print(f"[pywencai] ✅ 浏览器会话成功，共获取 {len(result) if hasattr(result,'__len__') else '?'} 条数据")
                return result
            else:
                cookie_hint = (
                    f"；已传入Cookie长度={len(cookie_str)}，但问财仍返回空响应，"
                    "通常是Cookie失效、复制不完整、账号退出登录或服务器IP被拦截"
                )
                if _last_error:
                    _last_error += cookie_hint
                else:
                    _last_error = "Cookie会话请求失败" + cookie_hint
                print(f"[pywencai] ❌ 浏览器会话也失败，选股功能暂时不可用")
                print(f"[pywencai] 💡 请用浏览器打开 https://www.iwencai.com/screener 并登录")
        else:
            _last_error = "未获取到 iwencai Cookie"
    except Exception as e:
        _last_error = _redact_error(e)
        logger.debug(f"浏览器 cookies 方案也失败: {e}")

    return None


def _normalize_cookie(cookie):
    """Normalize a manually copied Cookie request-header value."""
    value = str(cookie or "").strip()
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    return value


def _get_configured_cookie():
    """Read a Cookie from the environment for direct CLI usage."""
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except Exception:
        pass

    for name in _COOKIE_ENV_NAMES:
        value = _normalize_cookie(os.getenv(name, ""))
        if value:
            return value
    return ""


def _try_call(query, loop=True, **kwargs):
    """内部调用 pywencai.get，捕获异常"""
    global _last_error
    import pywencai
    try:
        _ensure_browser_headers()
        result = pywencai.get(query=query, loop=loop, **kwargs)
        return result
    except AttributeError as e:
        _last_error = _redact_error(e)
        logger.debug(f"pywencai 内部异常: {e}")
        return None
    except Exception as e:
        _last_error = _redact_error(e)
        logger.debug(f"pywencai 调用异常: {type(e).__name__}: {e}")
        return None


def _ensure_browser_headers():
    """Extend pywencai's generated headers with browser origin metadata."""
    try:
        wencai_module = import_module("pywencai.wencai")
        current_headers = wencai_module.headers
        if getattr(current_headers, "_iwencai_browser_headers", False):
            return

        def browser_headers(cookie=None, user_agent=None):
            request_headers = current_headers(cookie, user_agent)
            request_headers.update({
                "Referer": "https://www.iwencai.com/",
                "Origin": "https://www.iwencai.com",
            })
            return request_headers

        browser_headers._iwencai_browser_headers = True
        wencai_module.headers = browser_headers
    except (AttributeError, ImportError):
        logger.debug("当前 pywencai 版本不支持扩展内部请求头")


def _redact_error(error):
    """Keep diagnostics useful while avoiding accidental Cookie leakage."""
    message = f"{type(error).__name__}: {error}"
    for key in (
        "IWENCAI_COOKIE",
        "IWENCAI_SESSION_COOKIE",
        "IWENCAI_COOKIES",
        "PYWENCAI_COOKIE",
        "WENCAI_COOKIE",
    ):
        value = os.getenv(key, "").strip()
        if value:
            message = message.replace(value, "[REDACTED]")
    return message[:500]
