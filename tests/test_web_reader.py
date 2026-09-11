from unittest.mock import patch, MagicMock
import pytest
from iro_agent.readers.web_reader import WebReader


def test_invalid_url():
    """验证非 http/https URL 直接被拒绝拦截"""
    reader = WebReader()
    res = reader.fetch_page("ftp://10.100.139.170/log")
    assert "error" in res
    assert "非法 URL" in res["error"]


def test_html_cleaning_and_title_extraction():
    """验证 HTML 页面杂质清洗、标题保留与换行排版"""
    reader = WebReader()

    mock_html = """
    <html>
      <head>
        <title>调度系统实时运行日志</title>
        <script>function evil() { console.log('bad'); }</script>
        <style>.hide { display: none; }</style>
      </head>
      <body>
        <h1>月台作业调度中心</h1>
        <!-- 注释文字不应展示 -->
        <p>当前11号月台状态: <span class="badge">NORMAL</span></p>
        <div>
          <p>小车 AGV-02 正常运行中</p>
        </div>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.text = mock_html

    with patch("requests.get", return_value=mock_resp):
        res = reader.fetch_page("http://10.100.139.170/status")

        assert res["status_code"] == 200
        content = res["content"]
        assert "【网页标题】: 调度系统实时运行日志" in content
        assert "月台作业调度中心" in content
        assert "当前11号月台状态: NORMAL" in content
        assert "小车 AGV-02 正常运行中" in content
        assert "console.log" not in content
        assert "display: none" not in content
        assert "注释文字不应展示" not in content


def test_keyword_filtering():
    """验证按关键词提取日志段落与上下文"""
    reader = WebReader()

    log_content = "\n".join([
        "2026-09-11 09:00:01 INFO [Dispatch] 系统启动正常",
        "2026-09-11 09:00:02 INFO [Dispatch] 初始化月台任务",
        "2026-09-11 09:00:03 INFO [Dispatch] 发送PLC信号",
        "2026-09-11 09:00:04 ERROR [Dispatch] Robot connection timeout at port 8080",
        "2026-09-11 09:00:05 WARN [Dispatch] 正在尝试重连小车",
        "2026-09-11 09:00:06 INFO [Dispatch] 心跳包发送完毕",
        "2026-09-11 09:00:07 INFO [Dispatch] 无任务空闲",
    ])

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/plain"}
    mock_resp.text = log_content

    with patch("requests.get", return_value=mock_resp):
        res = reader.fetch_page("http://10.100.139.170/logs/today", keyword="timeout")
        assert "Robot connection timeout" in res["content"]
        assert "正在尝试重连小车" in res["content"]


def test_basic_auth_and_session_handling():
    """验证 Basic Auth 用户名和密码参数传递"""
    reader = WebReader()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/plain"}
    mock_resp.text = "调度日志登录成功: admin"

    with patch("requests.get", return_value=mock_resp) as mock_get:
        res = reader.fetch_page(
            url="http://10.100.139.170",
            username="admin",
            password="",
        )
        assert res["status_code"] == 200
        assert mock_get.called
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["auth"] is not None
        assert call_kwargs["auth"].username == "admin"
        assert call_kwargs["auth"].password == ""


def test_timeout_interception():
    """验证连接超时保护与清晰友好提示"""
    reader = WebReader(timeout=2)

    import requests
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        res = reader.fetch_page("http://10.100.139.170/slow")
        assert res["status_code"] == 408
        assert "连接超时" in res["error"]


def test_cookie_parsing():
    """验证 Cookie 字符串与字典的归一化解析"""
    cookie_str = "ASP.NET_SessionId=abcdef123456; token=jwt_test_token; theme=dark"
    parsed = WebReader.parse_cookies(cookie_str)
    assert parsed["ASP.NET_SessionId"] == "abcdef123456"
    assert parsed["token"] == "jwt_test_token"
    assert parsed["theme"] == "dark"

    # 字典输入直通
    d = {"ASP.NET_SessionId": "123"}
    assert WebReader.parse_cookies(d) == d


def test_table_to_markdown_conversion():
    """验证 HTML 复杂表格提取并转换为 Markdown 规范表格"""
    html = """
    <div>
      <h2>任务状态列表</h2>
      <table border="1">
        <tr><th>Oid</th><th>任务状态</th><th>目标月台</th></tr>
        <tr><td>101</td><td>EXECUTING</td><td>11号月台</td></tr>
        <tr><td>102</td><td>DONE</td><td>12号月台</td></tr>
      </table>
    </div>
    """
    md = WebReader.html_to_markdown_tables(html)
    assert "| Oid | 任务状态 | 目标月台 |" in md
    assert "| --- | --- | --- |" in md
    assert "| 101 | EXECUTING | 11号月台 |" in md
    assert "| 102 | DONE | 12号月台 |" in md


def test_playwright_headless_browser_render():
    """验证无头浏览器原生渲染、DOM 文本提取与表格格式化 (基于 Data URI 离线验证)"""
    reader = WebReader()
    data_html = """data:text/html;charset=utf-8,<html>
      <head><title>自动装车调度管理系统(WES)</title></head>
      <body>
        <h1>配送任务</h1>
        <div id="dynamic-content">动态JS加载内容就绪</div>
        <table>
          <tr><th>Oid</th><th>任务状态</th></tr>
          <tr><td>888</td><td>已派发</td></tr>
        </table>
      </body>
    </html>"""

    res = reader.fetch_page(url=data_html, mode="browser", keyword="动态JS")
    assert res["status_code"] == 200
    assert res["engine"] == "browser"
    assert "动态JS加载内容就绪" in res["content"]
    assert res["has_tables"] is True
    assert res["title"] == "自动装车调度管理系统(WES)"


def test_auto_upgrade_on_application_error():
    """验证在 auto 模式下，若 HTTP 结果包含 Application Error，自动尝试浏览器内核渲染"""
    reader = WebReader()

    # Mock HTTP 返回 Application Error
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.headers = {"Content-Type": "text/html"}
    mock_http_resp.text = "<html><head><title>WES</title></head><body>Application Error: Session Expired</body></html>"

    # Mock 浏览器渲染返回正常数据
    mock_browser_result = {
        "status_code": 200,
        "url": "http://10.100.139.170/BOAgvTask_ListView",
        "engine": "browser",
        "title": "自动装车调度管理系统(WES)",
        "content": "【网页标题】: 自动装车调度管理系统(WES)\n\n配送任务列表\n| Oid | 状态 |\n| 1 | 就绪 |",
        "has_tables": True,
    }

    with patch("requests.get", return_value=mock_http_resp):
        with patch.object(reader, "_fetch_via_browser", return_value=mock_browser_result) as mock_browser:
            res = reader.fetch_page("http://10.100.139.170/BOAgvTask_ListView", mode="auto")
            assert mock_browser.called
            assert res["engine"] == "browser"
            assert "配送任务列表" in res["content"]

