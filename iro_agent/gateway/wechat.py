import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional
from iro_agent.config import get_config
from iro_agent.llm.glm_client import GlmClient
from iro_agent.security.redactor import redact_secrets
from iro_agent.security.audit import AuditLogger


class WeChatGatewayHandler(BaseHTTPRequestHandler):
    """微信回调 HTTP 处理器"""

    glm_client: Optional[GlmClient] = None
    audit: Optional[AuditLogger] = None
    session_history: Dict[str, list] = {}

    def do_GET(self):
        """健康检查或微信服务端配置验证"""
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "IRO_agent WeChat Gateway"}).encode("utf-8"))

    def do_POST(self):
        """接收微信消息 (群聊@或私信)"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")

        try:
            data = json.loads(body) if body.strip() else {}
        except Exception:
            data = {"content": body}

        user_id = data.get("from_user", "wechat_user")
        session_id = data.get("session_id", f"session_{user_id}")
        content = data.get("content", "")
        image_path = data.get("image_path")

        if self.audit:
            self.audit.record(
                tool_name="WeChatGateway",
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
            reply_text = self.glm_client.chat_completion(history, image_path=image_path)
            history.append({"role": "assistant", "content": reply_text})

        # 敏感信息脱敏
        safe_reply = redact_secrets(reply_text)

        if self.audit:
            self.audit.record(
                tool_name="WeChatGateway",
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


class WeChatGatewayServer:
    """微信网关后台服务管理器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, glm_client: Optional[GlmClient] = None):
        self.host = host
        self.port = port
        self.glm_client = glm_client
        self.audit = AuditLogger()
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, block: bool = True) -> None:
        WeChatGatewayHandler.glm_client = self.glm_client
        WeChatGatewayHandler.audit = self.audit
        self.server = HTTPServer((self.host, self.port), WeChatGatewayHandler)

        print(f"[IRO_agent Gateway] 微信网关已启动，监听地址: http://{self.host}:{self.port}")
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
            print("[IRO_agent Gateway] 微信网关已停止。")
