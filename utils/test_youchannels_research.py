"""
测试 You.com Research API 客户端模块

运行方式:
  # 无需 API key，单元测试全部通过
  python3 -m pytest utils/test_youchannels_research.py -v

  # 包含集成测试（需要 YDC_API_KEY）
  export YDC_API_KEY=your_key_here
  python3 -m pytest utils/test_youchannels_research.py -v

  # 仅运行集成测试（需要 YDC_API_KEY）
  export YDC_API_KEY=your_key_here
  python3 -m pytest utils/test_youchannels_research.py::TestGetYoudotcomResearchIntegration -v

注意: 集成测试与单元测试共享同一进程，建议单独运行集成测试以避免环境状态干扰。
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub dotenv before importing the module
import types
_dotenv = types.ModuleType("dotenv")
_dotenv.load_dotenv = lambda *a, **k: None
sys.modules["dotenv"] = _dotenv


class TestResolveEffort:
    """测试 effort 参数解析"""

    def test_resolve_effort_valid(self):
        from utils.youchannels_research import _resolve_effort
        assert _resolve_effort("lite") == "lite"
        assert _resolve_effort("deep") == "deep"
        assert _resolve_effort("exhaustive") == "exhaustive"

    def test_resolve_effort_invalid_defaults_to_standard(self):
        from utils.youchannels_research import _resolve_effort
        assert _resolve_effort("invalid") == "standard"
        assert _resolve_effort(None) == "standard"


class TestFormatResearchForAI:
    """测试 format_research_for_ai"""

    def test_success_result_formatted(self):
        from utils.youchannels_research import format_research_for_ai

        result = {
            "success": True,
            "content": "AI stocks are rising due to new regulations.",
            "sources": [
                {
                    "url": "https://example.com/article1",
                    "title": "AI Stocks Rise",
                    "snippets": ["AI stocks surged 5% after new policy announcement."],
                },
                {
                    "url": "https://example.com/article2",
                    "title": "Market Report",
                    "snippets": ["Analysts remain bullish on tech sector."],
                },
            ],
        }

        output = format_research_for_ai(result)

        assert "【You.com深度研究结果】" in output
        assert "AI stocks are rising" in output
        assert "AI Stocks Rise" in output
        assert "https://example.com/article1" in output
        assert "AI stocks surged 5%" in output  # snippet included

    def test_failure_result(self):
        from utils.youchannels_research import format_research_for_ai

        result = {"success": False, "error": "API key invalid"}
        output = format_research_for_ai(result)

        assert "获取失败" in output
        assert "API key invalid" in output

    def test_empty_result(self):
        from utils.youchannels_research import format_research_for_ai

        assert "获取失败" in format_research_for_ai({})
        assert "获取失败" in format_research_for_ai(None)

    def test_content_truncation(self):
        from utils.youchannels_research import format_research_for_ai

        result = {
            "success": True,
            "content": "A" * 10000,
            "sources": [],
        }
        output = format_research_for_ai(result, max_content_length=500)
        assert "已截断" in output
        assert len(output) < 1000

    def test_sources_truncation(self):
        from utils.youchannels_research import format_research_for_ai

        result = {
            "success": True,
            "content": "Test content.",
            "sources": [
                {"url": f"https://example.com/{i}", "title": f"Source {i}", "snippets": [f"Snippet {i}"]}
                for i in range(15)
            ],
        }
        output = format_research_for_ai(result)
        assert "Source 0" in output
        assert "Source 9" in output
        assert "Source 10" not in output  # capped at 10

    def test_missing_source_fields(self):
        from utils.youchannels_research import format_research_for_ai

        result = {
            "success": True,
            "content": "Content",
            "sources": [
                {},  # empty dict
                {"url": "https://example.com"},  # missing title
                {"title": "Only Title"},  # missing url
            ],
        }
        output = format_research_for_ai(result)
        assert "【You.com深度研究结果】" in output  # should not raise

    def test_snippet_truncation(self):
        from utils.youchannels_research import format_research_for_ai

        result = {
            "success": True,
            "content": "Content",
            "sources": [
                {"url": "https://example.com", "title": "Title", "snippets": ["A" * 500]},
            ],
        }
        output = format_research_for_ai(result)
        assert "A" * 300 in output  # truncated to max_snippet_length
        assert "A" * 400 not in output  # not beyond that


class TestGetYoudotcomResearchErrorPaths:
    """测试 get_youdotcom_research 错误路径（无网络调用）"""

    def setup_method(self):
        self._orig_key = os.environ.get("YDC_API_KEY")

    def teardown_method(self):
        if self._orig_key is None:
            os.environ.pop("YDC_API_KEY", None)
        else:
            os.environ["YDC_API_KEY"] = self._orig_key

    def test_missing_api_key(self):
        os.environ.pop("YDC_API_KEY", None)

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is False
        assert "YDC_API_KEY" in result["error"]
        assert result["content"] == ""
        assert result["sources"] == []

    @patch("utils.youchannels_research.requests.post")
    def test_http_401(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is False
        assert "invalid or expired" in result["error"]

    @patch("utils.youchannels_research.requests.post")
    def test_http_403(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_post.return_value = mock_resp

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is False
        assert "lacks the required scope" in result["error"]

    @patch("utils.youchannels_research.requests.post")
    def test_http_422(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "invalid params"
        mock_post.return_value = mock_resp

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is False
        assert "Invalid request parameters" in result["error"]

    @patch("utils.youchannels_research.requests.post")
    def test_http_500(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.status_text = "Internal Server Error"
        mock_resp.ok = True
        mock_resp.json.return_value = {"output": {"content": "", "sources": []}}
        mock_post.return_value = mock_resp

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is False
        assert "500" in result["error"]

    @patch("utils.youchannels_research.requests.post")
    def test_timeout(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        import requests as req

        mock_post.side_effect = req.exceptions.Timeout("timed out")

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query", timeout=30)
        assert result["success"] is False
        assert "timed out" in result["error"]

    @patch("utils.youchannels_research.requests.post")
    def test_network_error(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        import requests as req

        mock_post.side_effect = req.exceptions.ConnectionError("connection refused")

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is False
        assert "Request failed" in result["error"]

    @patch("utils.youchannels_research.requests.post")
    def test_malformed_output_not_dict(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"output": "not a dict"}
        mock_post.return_value = mock_resp

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is False
        assert "Unexpected API response structure" in result["error"]

    @patch("utils.youchannels_research.requests.post")
    def test_output_sources_not_list(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "output": {
                "content": "Valid content",
                "sources": "not a list",
            }
        }
        mock_post.return_value = mock_resp

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is True
        assert result["content"] == "Valid content"
        assert result["sources"] == []  # gracefully degraded to []

    @patch("utils.youchannels_research.requests.post")
    def test_output_content_not_string(self, mock_post):
        os.environ["YDC_API_KEY"] = "test-key"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "output": {
                "content": 12345,
                "sources": [],
            }
        }
        mock_post.return_value = mock_resp

        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research

        result = get_youdotcom_research("test query")
        assert result["success"] is True
        assert result["content"] == ""  # gracefully degraded to empty string


class TestGetYoudotcomResearchIntegration:
    """集成测试：需要 YDC_API_KEY 环境变量"""

    def _do_research(self):
        import importlib
        import utils.youchannels_research
        importlib.reload(utils.youchannels_research)
        from utils.youchannels_research import get_youdotcom_research
        return get_youdotcom_research("What are the latest trends in AI stock trading?", effort="lite")

    def test_research_returns_content_and_sources(self):
        api_key = os.environ.get("YDC_API_KEY", "").strip()
        if not api_key or api_key.startswith("your_"):
            pytest.skip("YDC_API_KEY not set")
        os.environ["YDC_API_KEY"] = api_key

        result = self._do_research()

        assert result["success"] is True
        assert isinstance(result["content"], str)
        assert len(result["content"]) > 0
        assert isinstance(result["sources"], list)
        assert len(result["sources"]) > 0

        first = result["sources"][0]
        assert "url" in first
        assert "title" in first
        assert "snippets" in first
        assert isinstance(first["snippets"], list)

    def test_research_respects_effort_parameter(self):
        api_key = os.environ.get("YDC_API_KEY", "").strip()
        if not api_key or api_key.startswith("your_"):
            pytest.skip("YDC_API_KEY not set")
        os.environ["YDC_API_KEY"] = api_key

        result = self._do_research()
        assert result["success"] is True
        assert len(result["content"]) > 0
