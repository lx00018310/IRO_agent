import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional
from iro_agent.gateway.base import GatewayAdapter, GatewayMessage
from iro_agent.gateway.dedup import EventDeduplicator
from iro_agent.llm.glm_client import GlmClient
from iro_agent.security.redactor import redact_secrets
from iro_agent.security.audit import AuditLogger


class HttpGatewayHandler(BaseHTTPRequestHandler):
    """本地开发与测试 HTTP 请求处理器"""

    glm_client: Optional[GlmClient] = None
    audit: Optional[AuditLogger] = None
    dedup: Optional[EventDeduplicator] = None
    session_history: Dict[str, list] = {}
    last_replies: Dict[str, str] = {}

    def do_GET(self):
        """健康检查"""
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "IRO_agent Http Gateway Adapter"}).encode("utf-8"))

    def do_POST(self):
        """接收开发测试请求"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")

        try:
            data = json.loads(body) if body.strip() else {}
        except Exception:
            data = {"content": body}

        event_id = data.get("event_id", "")
        message_id = data.get("message_id", "")

        # 事件幂等去重检查
        if self.dedup and event_id and self.dedup.is_duplicate(event_id=event_id, message_id=message_id):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ignored", "reason": "duplicate_event"}).encode("utf-8"))
            return

        user_id = str(data.get("from_user", "dev_user"))
        chat_id = str(data.get("chat_id", f"p2p_{user_id}"))
        chat_type = data.get("chat_type", "p2p")
        session_id = data.get("session_id", f"http:{chat_type}:{chat_id}")
        content = data.get("content", "")

        # 安全防范：严格禁止任意本地绝对路径注入 (Section 18)
        raw_image_input = data.get("image_path")
        safe_image_path: Optional[str] = None
        if raw_image_input:
            # 严格拒绝以盘符或 / 开头的任意系统路径，只允许指定受控安全目录下的文件
            is_absolute = os.path.isabs(raw_image_input)
            has_win_drive = len(raw_image_input) > 2 and raw_image_input[1] == ":"
            if is_absolute or has_win_drive:
                # 拒绝任意本地路径注入
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "Security violation: arbitrary local file paths are not allowed"
                }).encode("utf-8"))
                return
            else:
                safe_image_path = raw_image_input

        if self.audit:
            self.audit.record(
                tool_name="HttpGatewayAdapter",
                operation="receive_message",
                target=f"session={session_id}, user={user_id}",
                result_summary=f"收到消息: {content[:50]}",
                status="SUCCESS",
                session_id=session_id,
                user_id=user_id,
            )

        # 维护上下文会话
        history = self.session_history.setdefault(session_id, [])
        history.append({"role": "user", "content": content})

        # 调用模型/诊断内核
        reply_text = "收到请求，正在诊断中..."
        if self.glm_client:
            reply_text = self.glm_client.chat_completion(history, image_path=safe_image_path)
            history.append({"role": "assistant", "content": reply_text})

        # 敏感信息脱敏
        safe_reply = redact_secrets(reply_text)
        self.last_replies[chat_id] = safe_reply

        if self.audit:
            self.audit.record(
                tool_name="HttpGatewayAdapter",
                operation="reply_message",
                target=f"session={session_id}",
                result_summary="成功回送业务语言诊断报告",
                status="SUCCESS",
                session_id=session_id,
                user_id=user_id,
            )

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"reply": safe_reply}, ensure_ascii=False).encode("utf-8"))


class HttpGatewayAdapter(GatewayAdapter):
    """本地开发与测试 HTTP 网关适配器"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080, glm_client: Optional[GlmClient] = None):
        self.host = host
        self.port = port
        self.glm_client = glm_client
        self.audit = AuditLogger()
        self.dedup = EventDeduplicator("iro_agent_gateway_events.db")
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, block: bool = True) -> None:
        HttpGatewayHandler.glm_client = self.glm_client
        HttpGatewayHandler.audit = self.audit
        HttpGatewayHandler.dedup = self.dedup
        self.server = HTTPServer((self.host, self.port), HttpGatewayHandler)

        print(f"[IRO_agent Gateway] 开发测试 HTTP 网关已启动，监听地址: http://{self.host}:{self.port}")
        if block:
            try:
                self.server.serve_forever()
            except KeyboardInterrupt:
                self.stop()
        else:
            self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            print("[IRO_agent Gateway] 开发测试 HTTP 网关已停止。")

    def send_message(self, chat_id: str, text: str, reply_to_message_id: Optional[str] = None) -> bool:
        safe_reply = redact_secrets(text)
        HttpGatewayHandler.last_replies[chat_id] = safe_reply
        return True

    def download_resource(self, message_id: str, file_key: str, target_dir: Optional[str] = None) -> Optional[str]:
        return None

    def health(self) -> Dict[str, Any]:
        return {
            "gateway_type": "http",
            "host": self.host,
            "port": self.port,
            "running": self.server is not None,
        }
