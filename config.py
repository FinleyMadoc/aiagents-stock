import os
from dotenv import load_dotenv

# Keep a key injected by Docker or the hosting platform ahead of a possibly
# stale/empty value in the mounted .env file.
_runtime_newsapi_key = os.getenv("NEWSAPI_API_KEY", "").strip()
_runtime_iwencai_cookie = os.getenv("IWENCAI_COOKIE", "").strip()
load_dotenv(override=True)
if _runtime_newsapi_key:
    os.environ["NEWSAPI_API_KEY"] = _runtime_newsapi_key
if _runtime_iwencai_cookie:
    os.environ["IWENCAI_COOKIE"] = _runtime_iwencai_cookie

# DeepSeek API配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

# You.com API配置
YDC_API_KEY = os.getenv("YDC_API_KEY", "")

# 默认AI模型名称（支持任何OpenAI兼容的模型）
DEFAULT_MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "deepseek-chat")
MAINLINE_THINKING_MODE = os.getenv(
    "MAINLINE_THINKING_MODE", "false"
).strip().lower() == "true"
MAINLINE_REASONING_EFFORT = os.getenv(
    "MAINLINE_REASONING_EFFORT", "high"
).strip().lower()
if MAINLINE_REASONING_EFFORT not in {"low", "high", "max"}:
    MAINLINE_REASONING_EFFORT = "high"
MAINLINE_HISTORY_DIR = os.getenv(
    "MAINLINE_HISTORY_DIR", "data/mainline/history"
).strip() or "data/mainline/history"
try:
    MAINLINE_HISTORY_LIMIT = max(
        int(os.getenv("MAINLINE_HISTORY_LIMIT", "100")), 1
    )
except ValueError:
    MAINLINE_HISTORY_LIMIT = 100

# 其他配置
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
UZI_SKILL_ROOT = os.getenv("UZI_SKILL_ROOT", "")
UZI_REPORT_ROOT = os.getenv("UZI_REPORT_ROOT", "data/uzi-reports")
UZI_DEFAULT_DEPTH = os.getenv("UZI_DEFAULT_DEPTH", "medium")
UZI_DEFAULT_SCHOOL = os.getenv("UZI_DEFAULT_SCHOOL", "")

# International finance news used by the A-share mainline analyzer.
NEWSAPI_API_KEY = os.getenv("NEWSAPI_API_KEY", "")
IWENCAI_COOKIE = os.getenv("IWENCAI_COOKIE", "").strip()
NEWSAPI_BASE_URL = os.getenv(
    "NEWSAPI_BASE_URL", "https://newsapi.org/v2/everything"
)
GDELT_DOC_API_URL = os.getenv(
    "GDELT_DOC_API_URL", "https://api.gdeltproject.org/api/v2/doc/doc"
)
INTERNATIONAL_NEWS_TIMEOUT = float(
    os.getenv("INTERNATIONAL_NEWS_TIMEOUT", "15")
)
INTERNATIONAL_NEWS_QUERY = os.getenv("INTERNATIONAL_NEWS_QUERY", "")

# 股票数据源配置
DEFAULT_PERIOD = "1y"  # 默认获取1年数据
DEFAULT_INTERVAL = "1d"  # 默认日线数据

# MiniQMT量化交易配置
MINIQMT_CONFIG = {
    'enabled': os.getenv("MINIQMT_ENABLED", "false").lower() == "true",
    'account_id': os.getenv("MINIQMT_ACCOUNT_ID", ""),
    'host': os.getenv("MINIQMT_HOST", "127.0.0.1"),
    'port': int(os.getenv("MINIQMT_PORT", "58610")),
}

# TDX股票数据API配置项目地址github.com/oficcejo/tdx-api
TDX_CONFIG = {
    'enabled': os.getenv("TDX_ENABLED", "false").lower() == "true",
    'base_url': os.getenv("TDX_BASE_URL", "http://192.168.1.222:8181"),
}
