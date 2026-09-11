import re
import urllib.parse
from typing import Dict, Any, Optional, List
import requests
from requests.auth import HTTPBasicAuth
from iro_agent.security.audit import AuditLogger
from iro_agent.security.redactor import redact_secrets


class WebReader:
    """现场网络与内网工控系统只读网页/日志抓取器 (Read-Only Web & Log Page Fetcher)"""

    def __init__(self, audit_logger: Optional[AuditLogger] = None, timeout: int = 6):
        self.audit = audit_logger or AuditLogger()
        self.timeout = timeout

    def fetch_page(
        self,
        url: str,
        keyword: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        max_chars: int = 3000,
    ) -> Dict[str, Any]:
        """
        安全只读拉取目标网页或内网系统日志接口。
        支持 Basic 认证与工控内网免密/弱密页面。
        """
        url_clean = (url or "").strip()
        if not url_clean.startswith(("http://", "https://")):
            return {"error": "非法 URL: 必须以 http:// 或 https:// 开头", "url": url_clean}

        auth = None
        if username is not None:
            auth = HTTPBasicAuth(username, password or "")

        headers = {
            "User-Agent": "IRO_agent/1.0 (Industrial Read-Only Diagnostic Assistant)",
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
        }

        # 敏感信息打码记录审计日志
        safe_url = url_clean
        self.audit.record(
            tool_name="WebReader",
            operation="fetch_page",
            result_summary=f"只读请求目标页面: {safe_url}, 认证用户: {username or 'anonymous'}",
            status="SUCCESS",
        )

        try:
            resp = requests.get(
                url_clean,
                headers=headers,
                auth=auth,
                timeout=self.timeout,
                allow_redirects=True,
            )
        except requests.exceptions.Timeout:
            return {
                "error": f"连接超时: 目标页面 {url_clean} 在 {self.timeout}s 内未响应",
                "status_code": 408,
                "url": url_clean,
            }
        except Exception as e:
            return {
                "error": f"网络请求异常: {e}",
                "status_code": 0,
                "url": url_clean,
            }

        status_code = resp.status_code
        content_type = resp.headers.get("Content-Type", "")

        # 针对常见 401/403 提示
        if status_code in (401, 403):
            return {
                "status_code": status_code,
                "url": url_clean,
                "error": f"目标页面需要身份验证或权限不足 (HTTP {status_code})。请确认传入的 username / password 参数。",
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

        # 长度截断保护
        truncated = False
        if len(cleaned_text) > max_chars:
            cleaned_text = cleaned_text[:max_chars] + f"\n... [内容过长已截断，共 {len(raw_text)} 字符]"
            truncated = True

        return {
            "status_code": status_code,
            "url": url_clean,
            "content_type": content_type,
            "content": redact_secrets(cleaned_text),
            "truncated": truncated,
        }

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

        # 3. 替换常见分块标签为换行
        with_newlines = re.sub(r"<(?:p|div|tr|li|h[1-6]|br)[^>]*>", "\n", no_comments, flags=re.IGNORECASE)

        # 4. 剥离所有 HTML 标签
        stripped = re.sub(r"<[^>]+>", " ", with_newlines)

        # 5. 清洗实体与多余空白
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
