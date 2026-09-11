import re
import urllib.parse
from html.parser import HTMLParser
from typing import Dict, Any, Optional, List, Union
import requests
from requests.auth import HTTPBasicAuth
from iro_agent.security.audit import AuditLogger
from iro_agent.security.redactor import redact_secrets


class _TableHTMLParser(HTMLParser):
    """纯标准库 HTML 表格解析器，实现零外部依赖表格提取"""

    def __init__(self):
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self.current_table: Optional[List[List[str]]] = None
        self.current_row: Optional[List[str]] = None
        self.current_cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        t = tag.lower()
        if t == "table":
            self.current_table = []
        elif t == "tr" and self.current_table is not None:
            self.current_row = []
        elif t in ("th", "td") and self.current_row is not None:
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("th", "td") and self.current_cell is not None:
            self.current_row.append("".join(self.current_cell).strip())
            self.current_cell = None
        elif t == "tr" and self.current_row is not None:
            if self.current_row:
                self.current_table.append(self.current_row)
            self.current_row = None
        elif t == "table" and self.current_table is not None:
            if self.current_table:
                self.tables.append(self.current_table)
            self.current_table = None


class WebReader:
    """现场网络与异构工控/管理系统通用自适应网页抓取器 (Universal Adaptive Web Reader)"""

    def __init__(self, audit_logger: Optional[AuditLogger] = None, timeout: int = 15):
        self.audit = audit_logger or AuditLogger()
        self.timeout = timeout

    @staticmethod
    def parse_cookies(cookies: Optional[Union[str, Dict[str, str]]]) -> Dict[str, str]:
        """将 Cookie 字符串 (如 'ASP.NET_SessionId=xxx; token=yyy') 或字典归一化为字典"""
        if not cookies:
            return {}
        if isinstance(cookies, dict):
            return {k.strip(): str(v).strip() for k, v in cookies.items() if k.strip()}
        cookie_dict = {}
        for item in str(cookies).split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                if k.strip():
                    cookie_dict[k.strip()] = v.strip()
        return cookie_dict

    @staticmethod
    def html_to_markdown_tables(html: str) -> str:
        """从 HTML 中解析提取 <table> 标签并转换为标准的 Markdown 表格 (纯标准库零依赖)"""
        if not html or "<table" not in html.lower():
            return ""
        try:
            parser = _TableHTMLParser()
            parser.feed(html)
            if not parser.tables:
                return ""
            md_tables = []
            for table in parser.tables:
                if not table:
                    continue
                max_cols = max(len(r) for r in table)
                if max_cols == 0:
                    continue
                norm_grid = [r + [""] * (max_cols - len(r)) for r in table]
                header = norm_grid[0]
                sep = ["---"] * max_cols
                lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
                for r in norm_grid[1:]:
                    lines.append("| " + " | ".join(r) + " |")
                md_tables.append("\n".join(lines))
            return "\n\n".join(md_tables)
        except Exception:
            return ""

    def fetch_page(
        self,
        url: str,
        keyword: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cookies: Optional[Union[str, Dict[str, str]]] = None,
        headers: Optional[Dict[str, str]] = None,
        mode: str = "auto",  # "auto", "browser", "http"
        wait_until: str = "networkidle",  # "networkidle", "domcontentloaded", "load"
        timeout: Optional[int] = None,
        max_chars: int = 4000,
    ) -> Dict[str, Any]:
        """
        安全只读拉取目标网页或系统日志。
        支持:
        - HTTP Fast 探针 (API、静态日志、Prometheus)
        - Headless Browser 探针 (DevExpress XAF、Vue、React、ASP.NET WebForms)
        - Cookie 会话注入 (ASP.NET_SessionId 等)
        - 表单自动识别与登录
        - 结构化表格自动转 Markdown
        - 网络响应流量监听 (捕获后台 JSON 数据)
        """
        url_clean = (url or "").strip()
        if not url_clean.startswith(("http://", "https://", "data:")):
            return {"error": "非法 URL: 必须以 http://, https:// 或 data: 开头", "url": url_clean}

        effective_timeout = timeout or self.timeout
        parsed_cookies = self.parse_cookies(cookies)

        # 敏感信息打码记录审计日志
        safe_url = redact_secrets(url_clean)
        self.audit.record(
            tool_name="WebReader",
            operation="fetch_page",
            result_summary=f"只读抓取网页: {safe_url}, 模式: {mode}, 用户: {username or 'anonymous'}",
            status="SUCCESS",
        )

        # 1. 显式浏览器模式或 data: URI
        if mode == "browser" or url_clean.startswith("data:"):
            return self._fetch_via_browser(
                url=url_clean,
                keyword=keyword,
                username=username,
                password=password,
                cookies=parsed_cookies,
                headers=headers,
                wait_until=wait_until,
                timeout=effective_timeout,
                max_chars=max_chars,
            )

        # 2. 显式 HTTP 模式
        if mode == "http":
            return self._fetch_via_http(
                url=url_clean,
                keyword=keyword,
                username=username,
                password=password,
                cookies=parsed_cookies,
                headers=headers,
                timeout=effective_timeout,
                max_chars=max_chars,
            )

        # 3. 智能自适应模式 (auto)
        # 先快速 HTTP 探测，若遇到动态框架/错误拦截则平滑升级为无头浏览器内核渲染
        http_res = self._fetch_via_http(
            url=url_clean,
            keyword=keyword,
            username=username,
            password=password,
            cookies=parsed_cookies,
            headers=headers,
            timeout=min(6, effective_timeout),
            max_chars=max_chars,
        )

        # 判断是否需要升级到浏览器内核渲染
        need_browser_upgrade = False
        content = http_res.get("content", "")
        raw_text = http_res.get("raw_text", "")

        # 特征 1: 遇到典型的无会话拦截与报错 (如 Application Error / Session Expired)
        if "application error" in content.lower() or "session expired" in content.lower():
            need_browser_upgrade = True
        # 特征 2: SPA 骨架或 DevExpress/Vue/React 前端特征
        elif any(marker in raw_text.lower() for marker in ["<div id=\"app\">", "<div id=\"root\">", "dx.all.js", "aspxwebcontrol", "__viewstate"]):
            need_browser_upgrade = True
        # 特征 3: 提取出的可见文本极少但原始 HTML 较大 (说明数据全靠 JS 异步加载)
        elif len(content) < 200 and len(raw_text) > 1500:
            need_browser_upgrade = True

        if need_browser_upgrade:
            try:
                browser_res = self._fetch_via_browser(
                    url=url_clean,
                    keyword=keyword,
                    username=username,
                    password=password,
                    cookies=parsed_cookies,
                    headers=headers,
                    wait_until=wait_until,
                    timeout=effective_timeout,
                    max_chars=max_chars,
                )
                if "error" not in browser_res or browser_res.get("status_code", 0) == 200:
                    return browser_res
            except Exception:
                pass  # 浏览器降级失败时保留 HTTP 探测结果

        return http_res

    def _fetch_via_http(
        self,
        url: str,
        keyword: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
        max_chars: int = 4000,
    ) -> Dict[str, Any]:
        """Tier 1: 极速 HTTP 探针"""
        auth = None
        if username is not None:
            auth = HTTPBasicAuth(username, password or "")

        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
        }
        if headers:
            req_headers.update(headers)

        try:
            resp = requests.get(
                url,
                headers=req_headers,
                auth=auth,
                cookies=cookies if cookies else None,
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.exceptions.Timeout:
            return {
                "error": f"连接超时: 目标页面 {url} 在 {timeout}s 内未响应",
                "status_code": 408,
                "url": url,
                "engine": "http",
            }
        except Exception as e:
            return {
                "error": f"网络请求异常: {e}",
                "status_code": 0,
                "url": url,
                "engine": "http",
            }

        status_code = resp.status_code
        content_type = resp.headers.get("Content-Type", "")

        if status_code in (401, 403):
            return {
                "status_code": status_code,
                "url": url,
                "engine": "http",
                "error": f"目标页面需要身份验证或权限不足 (HTTP {status_code})。支持传入 cookies 维持会话。",
            }

        raw_text = resp.text or ""
        cleaned_text = self._clean_content(raw_text, content_type)

        # 关键词提取过滤
        if keyword:
            filtered_text = self._filter_by_keyword(cleaned_text, keyword)
            if filtered_text:
                cleaned_text = filtered_text
            else:
                cleaned_text = f"【提示】：页面已成功拉取，但未搜索到包含关键词 '{keyword}' 的日志段落。\n以下为前述部分正文：\n" + cleaned_text[:800]

        truncated = False
        if len(cleaned_text) > max_chars:
            cleaned_text = cleaned_text[:max_chars] + f"\n... [内容过长已截断，共 {len(raw_text)} 字符]"
            truncated = True

        return {
            "status_code": status_code,
            "url": url,
            "engine": "http",
            "content_type": content_type,
            "content": redact_secrets(cleaned_text),
            "raw_text": raw_text,
            "truncated": truncated,
        }

    def _fetch_via_browser(
        self,
        url: str,
        keyword: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        wait_until: str = "networkidle",
        timeout: int = 15,
        max_chars: int = 4000,
    ) -> Dict[str, Any]:
        """Tier 2: 无头 Chromium 渲染探针 (支持 DOM 动态渲染、Cookie 注入、表单自动登录与网络嗅探)"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {
                "error": "未安装 Playwright 库，无法启动无头浏览器探针。请使用 http 模式。",
                "url": url,
                "engine": "browser",
            }

        intercepted_apis: List[str] = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers=headers or {},
                )

                # 注入 Cookie 会话
                if cookies and not url.startswith("data:"):
                    pw_cookies = []
                    for k, v in cookies.items():
                        pw_cookies.append({
                            "name": k,
                            "value": v,
                            "url": url,
                        })
                    try:
                        context.add_cookies(pw_cookies)
                    except Exception:
                        pass

                page = context.new_page()

                # 流量嗅探: 监听后台 XHR/Fetch 异步接口数据
                def _on_response(response):
                    try:
                        ct = (response.headers.get("content-type") or "").lower()
                        resp_url = response.url
                        if ("json" in ct or "text" in ct) and any(kw in resp_url.lower() for kw in ["api", "task", "log", "list", "query", "wes", "data"]):
                            text = response.text()
                            if text and 10 < len(text) < 3000 and ("{" in text or "[" in text):
                                intercepted_apis.append(f"接口 [{resp_url}] 响应: {text[:600]}")
                    except Exception:
                        pass

                page.on("response", _on_response)

                # 导航页面
                try:
                    # 首先尝试 networkidle，若超时自动平滑退回 domcontentloaded
                    page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
                except Exception:
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=3000)
                    except Exception:
                        pass

                # 表单自动感知登录尝试
                if username is not None and not cookies:
                    self._try_auto_login(page, username, password)

                # 获取渲染后的标题、文本和 HTML 内容
                page_title = page.title() or ""
                body_text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
                html_content = page.content() or ""

                browser.close()
        except Exception as e:
            return {
                "error": f"无头浏览器渲染失败: {e}",
                "status_code": 0,
                "url": url,
                "engine": "browser",
            }

        # 结构化表格转换
        md_tables = self.html_to_markdown_tables(html_content)

        # 组装正文
        parts = []
        if page_title:
            parts.append(f"【网页标题】: {page_title}")
        if body_text.strip():
            # 简单清洗连续换行
            cleaned_body = re.sub(r"\n{3,}", "\n\n", body_text.strip())
            parts.append(cleaned_body)
        if md_tables:
            parts.append(f"【提取到的结构化数据表格】:\n{md_tables}")
        if intercepted_apis:
            parts.append("【嗅探到的后台接口数据】:\n" + "\n".join(intercepted_apis[:3]))

        full_content = "\n\n".join(parts)

        # 关键词提取过滤
        if keyword:
            filtered_text = self._filter_by_keyword(full_content, keyword)
            if filtered_text:
                full_content = filtered_text
            else:
                full_content = f"【提示】：页面已成功渲染，但未搜索到包含关键词 '{keyword}' 的日志段落。\n以下为前述部分正文：\n" + full_content[:800]

        truncated = False
        if len(full_content) > max_chars:
            full_content = full_content[:max_chars] + f"\n... [渲染内容过长已截断，共 {len(body_text)} 字符]"
            truncated = True

        return {
            "status_code": 200,
            "url": url,
            "engine": "browser",
            "title": page_title,
            "content": redact_secrets(full_content),
            "has_tables": bool(md_tables),
            "truncated": truncated,
        }

    def _try_auto_login(self, page: Any, username: str, password: Optional[str] = None) -> None:
        """尝试在无头浏览器中自动识别登录输入框并点击提交"""
        try:
            pwd_input = page.query_selector('input[type="password"]')
            if pwd_input and pwd_input.is_visible():
                user_input = page.query_selector(
                    'input[type="text"], input[name*="user" i], input[name*="login" i], input[id*="user" i], input[id*="login" i]'
                )
                if user_input:
                    user_input.fill(username)
                pwd_input.fill(password or "")

                submit_btn = page.query_selector(
                    'button[type="submit"], input[type="submit"], button:has-text("登录"), button:has-text("Log in"), button:has-text("Sign in")'
                )
                if submit_btn and submit_btn.is_visible():
                    submit_btn.click()
                else:
                    pwd_input.press("Enter")
                page.wait_for_timeout(2000)
        except Exception:
            pass

    def _clean_content(self, text: str, content_type: str) -> str:
        """HTML 结构清洗提纯"""
        if "html" not in content_type.lower() and not text.strip().startswith("<"):
            return text.strip()

        # 1. 提取网页标题并从正文中移除 title 标签避免重复
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        no_title = re.sub(r"<title[^>]*>.*?</title>", " ", text, flags=re.IGNORECASE | re.DOTALL)

        # 2. 剥离 scripts, styles, svg 等
        no_script = re.sub(r"<script[^>]*>.*?</script>", " ", no_title, flags=re.IGNORECASE | re.DOTALL)
        no_style = re.sub(r"<style[^>]*>.*?</style>", " ", no_script, flags=re.IGNORECASE | re.DOTALL)
        no_svg = re.sub(r"<svg[^>]*>.*?</svg>", " ", no_style, flags=re.IGNORECASE | re.DOTALL)
        no_comments = re.sub(r"<!--.*?-->", " ", no_svg, flags=re.DOTALL)

        # 3. 提取结构化表格 Markdown (如有)
        md_tables = self.html_to_markdown_tables(text)

        # 4. 替换常见分块标签为换行
        with_newlines = re.sub(r"<(?:p|div|tr|li|h[1-6]|br)[^>]*>", "\n", no_comments, flags=re.IGNORECASE)

        # 5. 剥离所有 HTML 标签
        stripped = re.sub(r"<[^>]+>", " ", with_newlines)

        # 6. 清洗实体与多余空白
        unescaped = (
            stripped.replace("&nbsp;", " ")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
        )
        lines = []
        for line in unescaped.splitlines():
            line_clean = re.sub(r"[ \t]+", " ", line).strip()
            if line_clean:
                lines.append(line_clean)

        result = "\n".join(lines)
        if md_tables:
            result += f"\n\n【提取到的结构化数据表格】:\n{md_tables}"

        if title:
            return f"【网页标题】: {title}\n" + result
        return result

    def _filter_by_keyword(self, text: str, keyword: str, context_lines: int = 3) -> Optional[str]:
        """提取命中关键词的前后上下文行"""
        lines = text.splitlines()
        kw = keyword.lower()
        matched_indices = [i for i, line in enumerate(lines) if kw in line.lower()]

        if not matched_indices:
            return None

        selected_lines_set = set()
        for idx in matched_indices:
            start = max(0, idx - context_lines)
            end = min(len(lines), idx + context_lines + 1)
            for j in range(start, end):
                selected_lines_set.add(j)

        sorted_indices = sorted(list(selected_lines_set))
        output_chunks = []
        last_idx = None
        for i in sorted_indices:
            if last_idx is not None and i > last_idx + 1:
                output_chunks.append("--- [省略中间不相关日志] ---")
            output_chunks.append(lines[i])
            last_idx = i

        return f"【包含关键词 '{keyword}' 的日志与正文段落】:\n" + "\n".join(output_chunks)
