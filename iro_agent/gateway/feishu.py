import os
import json
import re
import tempfile
import threading
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    GetMessageResourceRequest,
)

from iro_agent.config import get_config, IROConfig
from iro_agent.gateway.base import GatewayAdapter, GatewayMessage
from iro_agent.gateway.dedup import EventDeduplicator
from iro_agent.llm.glm_client import GlmClient
from iro_agent.security.redactor import redact_secrets
from iro_agent.security.audit import AuditLogger

logger = logging.getLogger(__name__)


def clean_mention_text(raw_text: str, mentions: Optional[List[Any]] = None) -> str:
    """清洗群聊消息中对机器人的 @mention 占位符，返回干净的用户提问"""
    cleaned = raw_text
    if mentions:
        for m in mentions:
            key = getattr(m, "key", None)
            name = getattr(m, "name", None)
            if key:
                cleaned = cleaned.replace(key, " ")
            if name:
                cleaned = cleaned.replace(f"@{name}", " ").replace(name, " ")

    # 通用正则剥离 @_user_1、@IRO_agent、@机器人 等占位符
    cleaned = re.sub(r"@_user_\d+", " ", cleaned)
    cleaned = re.sub(r"@\S+", " ", cleaned)
    return cleaned.strip()


class FeishuGateway(GatewayAdapter):
    """飞书企业自建应用 Bot 生产网关（基于 WebSocket 长连接）"""

    def __init__(
        self,
        config: Optional[IROConfig] = None,
        glm_client: Optional[GlmClient] = None,
        dedup_db_path: str = "iro_agent_gateway_events.db",
    ):
        self.config = config or get_config()
        self.glm_client = glm_client
        self.app_id = self.config.feishu.app_id
        self.app_secret = self.config.feishu.app_secret
        self.audit = AuditLogger()
        self.dedup = EventDeduplicator(dedup_db_path)
        self.session_history: Dict[str, list] = {}
        self._ws_client: Optional[lark.ws.Client] = None
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

        # 初始化飞书 OpenAPI 客户端
        if self.app_id and self.app_secret:
            self.client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .log_level(lark.LogLevel.WARNING)
                .build()
            )
        else:
            self.client = None

    def start(self, block: bool = True) -> None:
        """启动飞书 WebSocket 长连接监听"""
        if not self.app_id or not self.app_secret:
            raise ValueError("启动飞书网关失败: 未配置有效的 FEISHU_APP_ID 或 FEISHU_APP_SECRET")

        dispatcher_builder = lark.EventDispatcherHandler.builder("", "")
        dispatcher_builder.register_p2_im_message_receive_v1(self._on_message_receive)
        dispatcher = dispatcher_builder.build()

        self._ws_client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            log_level=lark.LogLevel.INFO,
            event_handler=dispatcher,
        )

        self._running = True
        print(f"[IRO_agent Gateway] 飞书 WebSocket 网关已启动 (App ID: {self.app_id[:6]}***)")

        if block:
            try:
                self._ws_client.start()
            except (KeyboardInterrupt, SystemExit):
                self.stop()
        else:
            self._thread = threading.Thread(target=self._ws_client.start, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """停止网关"""
        self._running = False
        print("[IRO_agent Gateway] 飞书 WebSocket 网关已停止。")

    def normalize_event(self, event_data: Any) -> Optional[GatewayMessage]:
        """将飞书原始事件规范化为 GatewayMessage"""
        try:
            event_id = ""
            if hasattr(event_data, "header") and hasattr(event_data.header, "event_id"):
                event_id = event_data.header.event_id
            elif isinstance(event_data, dict):
                event_id = event_data.get("header", {}).get("event_id", "")

            # 提取 event 主体
            event = getattr(event_data, "event", None)
            if event is None and isinstance(event_data, dict):
                event = event_data.get("event", {})

            # 提取 sender
            user_id = ""
            sender = getattr(event, "sender", None) if hasattr(event, "sender") else (event.get("sender") if isinstance(event, dict) else None)
            if sender:
                sender_id = getattr(sender, "sender_id", None) if hasattr(sender, "sender_id") else (sender.get("sender_id") if isinstance(sender, dict) else None)
                if sender_id:
                    user_id = getattr(sender_id, "open_id", "") if hasattr(sender_id, "open_id") else sender_id.get("open_id", "")
                    if not user_id:
                        user_id = getattr(sender_id, "user_id", "") if hasattr(sender_id, "user_id") else sender_id.get("user_id", "")

            # 提取 message
            message = getattr(event, "message", None) if hasattr(event, "message") else (event.get("message") if isinstance(event, dict) else None)
            if not message:
                return None

            message_id = getattr(message, "message_id", "") if hasattr(message, "message_id") else message.get("message_id", "")
            chat_id = getattr(message, "chat_id", "") if hasattr(message, "chat_id") else message.get("chat_id", "")
            chat_type = getattr(message, "chat_type", "p2p") if hasattr(message, "chat_type") else message.get("chat_type", "p2p")
            message_type = getattr(message, "message_type", "text") if hasattr(message, "message_type") else message.get("message_type", "text")
            raw_content = getattr(message, "content", "") if hasattr(message, "content") else message.get("content", "")
            create_time = getattr(message, "create_time", "") if hasattr(message, "create_time") else str(message.get("create_time", ""))

            # 提取 mentions
            mentions = getattr(message, "mentions", []) if hasattr(message, "mentions") else message.get("mentions", [])

            # 解析 content 中的文字
            parsed_text = ""
            image_refs = []
            if raw_content:
                try:
                    c_dict = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                    if message_type == "text":
                        parsed_text = c_dict.get("text", "")
                    elif message_type == "image":
                        img_key = c_dict.get("image_key", "")
                        if img_key:
                            image_refs.append(img_key)
                except Exception:
                    parsed_text = str(raw_content)

            return GatewayMessage(
                gateway="feishu",
                event_id=event_id,
                message_id=message_id,
                chat_id=chat_id,
                chat_type=chat_type,
                user_id=user_id,
                timestamp=create_time,
                message_type=message_type,
                text=parsed_text,
                image_refs=image_refs,
                raw_metadata={"mentions": mentions},
            )
        except Exception as e:
            logger.warning(f"飞书事件规范化失败: {e}")
            return None

    def _on_message_receive(self, event_data: Any) -> None:
        """飞书消息接收回调"""
        msg = self.normalize_event(event_data)
        if not msg:
            return

        # 1. 事件去重
        if self.dedup.is_duplicate(event_id=msg.event_id, message_id=msg.message_id):
            logger.info(f"忽略重复飞书事件: event_id={msg.event_id}")
            return

        # 2. 群聊与私聊路由过滤 (Section 9)
        clean_text = msg.text
        if msg.chat_type == "group":
            if not self.config.feishu.receive_group_at:
                return
            # 群聊必须且仅响应 @ 机器人
            mentions = msg.raw_metadata.get("mentions") or []
            if not mentions and "@" not in msg.text:
                # 未 @ 机器人，静默忽略无关群聊
                return
            clean_text = clean_mention_text(msg.text, mentions)
        elif msg.chat_type == "p2p":
            if not self.config.feishu.receive_private:
                return
            clean_text = msg.text.strip()

        # 3. 会话与项目映射 (Section 10, 11)
        session_id = f"feishu:{msg.chat_type}:{msg.chat_id}"
        target_project = (
            self.config.project_mapping.feishu.get(msg.chat_id, {}).get("project", self.config.project_name)
        )

        self.audit.record(
            tool_name="FeishuGateway",
            operation="receive_message",
            target=f"session={session_id}, user={msg.user_id}, project={target_project}",
            result_summary=f"收到消息: {clean_text[:50]}",
            status="SUCCESS",
            session_id=session_id,
            user_id=msg.user_id,
        )

        # 4. 图片消息安全下载与临时文件生命周期 (Section 13)
        tmp_image_path = None
        if msg.message_type == "image" and msg.image_refs:
            image_key = msg.image_refs[0]
            tmp_image_path = self.download_resource(message_id=msg.message_id, file_key=image_key)

        try:
            # 维护上下文会话
            history = self.session_history.setdefault(session_id, [])
            prompt_content = clean_text or ("请结合此现场图片分析故障原因并给出诊断建议。" if tmp_image_path else "")
            if not prompt_content and not tmp_image_path:
                return

            history.append({"role": "user", "content": prompt_content})

            reply_text = "收到请求，正在诊断中..."
            if self.glm_client:
                reply_text = self.glm_client.chat_completion(history, image_path=tmp_image_path)
                history.append({"role": "assistant", "content": reply_text})

            # 5. 敏感凭据脱敏回送
            safe_reply = redact_secrets(reply_text)
            self.send_message(chat_id=msg.chat_id, text=safe_reply, reply_to_message_id=msg.message_id)

            self.audit.record(
                tool_name="FeishuGateway",
                operation="reply_message",
                target=f"chat_id={msg.chat_id}, message_id={msg.message_id}",
                result_summary="成功回送业务语言诊断报告",
                status="SUCCESS",
                session_id=session_id,
                user_id=msg.user_id,
            )
        finally:
            # 临时图片严格即用即删
            if tmp_image_path and os.path.exists(tmp_image_path):
                try:
                    os.remove(tmp_image_path)
                except Exception as ex:
                    logger.warning(f"清理临时图片失败: {ex}")

    def send_message(self, chat_id: str, text: str, reply_to_message_id: Optional[str] = None) -> bool:
        """调用飞书 OpenAPI 回复/发送文本消息"""
        if not self.client:
            logger.error("飞书客户端未就绪，无法发送消息")
            return False

        safe_text = redact_secrets(text)
        content_json = json.dumps({"text": safe_text}, ensure_ascii=False)

        # 优先使用原消息引用回复 (Thread/Reply)
        if reply_to_message_id:
            try:
                request = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to_message_id)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(content_json)
                        .msg_type("text")
                        .build()
                    )
                    .build()
                )
                response = self.client.im.v1.message.reply(request)
                if response.success():
                    return True
                logger.warning(f"引用回复失败 ({response.code}: {response.msg})，降级为常规发送")
            except Exception as e:
                logger.warning(f"引用回复异常: {e}，降级为常规发送")

        # 降级：以 chat_id 发送到目标会话
        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(content_json)
                    .build()
                )
                .build()
            )
            response = self.client.im.v1.message.create(request)
            if not response.success():
                logger.error(f"飞书消息发送失败: code={response.code}, msg={response.msg}")
                return False
            return True
        except Exception as e:
            logger.error(f"飞书消息发送异常: {e}")
            return False

    def download_resource(self, message_id: str, file_key: str, target_dir: Optional[str] = None) -> Optional[str]:
        """下载现场图片资源到受控安全临时目录，校验格式并返回本地路径"""
        if not self.client:
            return None

        # 受控临时目录
        base_tmp = target_dir or os.path.join(tempfile.gettempdir(), "iro_agent_feishu_tmp")
        os.makedirs(base_tmp, exist_ok=True)
        safe_filename = f"feishu_img_{file_key[:16]}_{int(datetime.now(timezone.utc).timestamp())}.png"
        target_path = os.path.join(base_tmp, safe_filename)

        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type("image")
                .build()
            )
            response = self.client.im.v1.message_resource.get(request)
            if not response.success():
                logger.error(f"飞书图片下载失败: code={response.code}, msg={response.msg}")
                return None

            # 写入受控本地文件
            with open(target_path, "wb") as f:
                f.write(response.file.read())

            # 校验文件大小 (< 15MB)
            if os.path.getsize(target_path) > 15 * 1024 * 1024:
                os.remove(target_path)
                logger.warning("飞书图片超出 15MB 限制，已被拒绝")
                return None

            return os.path.abspath(target_path)
        except Exception as e:
            logger.error(f"飞书资源下载异常: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return None

    def health(self) -> Dict[str, Any]:
        """网关健康检查状态"""
        return {
            "gateway_type": "feishu",
            "app_id_configured": bool(self.app_id),
            "app_secret_configured": bool(self.app_secret),
            "websocket_client_ready": self._ws_client is not None,
            "running": self._running,
        }
