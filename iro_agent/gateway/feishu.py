import os
import json
import re
import time
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


def clean_mention_text(raw_text: str, mentions: Optional[List[Any]] = None, bot_name: str = "IRO_agent") -> str:
    """清洗群聊消息中对机器人的 @mention 占位符，返回干净的用户提问"""
    cleaned = raw_text
    bot_names = {bot_name.lower(), "iro_agent", "iro-agent", "iroagent"}
    if mentions:
        for m in mentions:
            key = getattr(m, "key", None) if hasattr(m, "key") else (m.get("key") if isinstance(m, dict) else None)
            name = getattr(m, "name", None) if hasattr(m, "name") else (m.get("name") if isinstance(m, dict) else None)
            # 仅当 mention 匹配机器人时才剥离，避免误伤其他 @提及
            is_bot = (name and (name.lower() in bot_names or "iro" in name.lower())) or (key and re.match(r"@_user_\d+", key))
            if is_bot:
                if key:
                    cleaned = cleaned.replace(key, " ")
                if name:
                    cleaned = cleaned.replace(f"@{name}", " ").replace(name, " ")

    cleaned = re.sub(r"@_user_\d+", " ", cleaned)
    cleaned = re.sub(r"@IRO_agent\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"@iro-agent\b", " ", cleaned, flags=re.IGNORECASE)
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
        self.bot_name = self.config.feishu.bot_name or "IRO_agent"
        self.bot_open_id: Optional[str] = None
        self.audit = AuditLogger()
        self.dedup = EventDeduplicator(dedup_db_path)
        self.session_history: Dict[str, list] = {}
        # 会话级最近现场图片短时缓存: session_id -> {"image_path": str, "timestamp": float}
        self.session_recent_images: Dict[str, dict] = {}
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
        print(f"[IRO_agent Gateway] 飞书 WebSocket 网关已启动 (App ID: {self.app_id[:6]}***, 机器人名称: {self.bot_name})")

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
        self._cleanup_expired_images(max_age=0)  # 退出时清理全部残留临时图片
        print("[IRO_agent Gateway] 飞书 WebSocket 网关已停止。")

    def _cleanup_expired_images(self, max_age: int = 300) -> None:
        """清理超过有效期的未消费临时图片文件"""
        now = time.time()
        expired_sessions = []
        for sess_id, img_info in list(self.session_recent_images.items()):
            if now - img_info.get("timestamp", 0) > max_age:
                expired_sessions.append(sess_id)
                path = img_info.get("image_path")
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
        for sess_id in expired_sessions:
            self.session_recent_images.pop(sess_id, None)

    def _is_mention_bot(self, mentions: List[Any]) -> bool:
        """严格判定 mentions 列表中是否包含指向机器人自身的条目 (P0 过滤 @张三 等误触发)"""
        if not mentions:
            return False

        bot_names = {self.bot_name.lower(), "iro_agent", "iro-agent", "iroagent"}
        for m in mentions:
            m_name = getattr(m, "name", None) if hasattr(m, "name") else (m.get("name") if isinstance(m, dict) else None)
            m_id = getattr(m, "id", None) if hasattr(m, "id") else (m.get("id") if isinstance(m, dict) else None)
            open_id = getattr(m_id, "open_id", None) if hasattr(m_id, "open_id") else (m_id.get("open_id") if isinstance(m_id, dict) else None)

            # 1. 若获取到了机器人 open_id 进行精确比对
            if self.bot_open_id and open_id and open_id == self.bot_open_id:
                return True
            # 2. 匹配名称
            if m_name and m_name.lower() in bot_names:
                return True
            # 3. 匹配名称中包含 iro
            if m_name and ("iro" in m_name.lower() or "诊断" in m_name):
                return True
        return False

    def normalize_event(self, event_data: Any) -> Optional[GatewayMessage]:
        """将飞书原始事件规范化为 GatewayMessage"""
        try:
            event_id = ""
            if hasattr(event_data, "header") and hasattr(event_data.header, "event_id"):
                event_id = event_data.header.event_id
            elif isinstance(event_data, dict):
                event_id = event_data.get("header", {}).get("event_id", "")

            event = getattr(event_data, "event", None)
            if event is None and isinstance(event_data, dict):
                event = event_data.get("event", {})

            user_id = ""
            sender = getattr(event, "sender", None) if hasattr(event, "sender") else (event.get("sender") if isinstance(event, dict) else None)
            if sender:
                sender_id = getattr(sender, "sender_id", None) if hasattr(sender, "sender_id") else (sender.get("sender_id") if isinstance(sender, dict) else None)
                if sender_id:
                    user_id = getattr(sender_id, "open_id", "") if hasattr(sender_id, "open_id") else sender_id.get("open_id", "")
                    if not user_id:
                        user_id = getattr(sender_id, "user_id", "") if hasattr(sender_id, "user_id") else sender_id.get("user_id", "")

            message = getattr(event, "message", None) if hasattr(event, "message") else (event.get("message") if isinstance(event, dict) else None)
            if not message:
                return None

            message_id = getattr(message, "message_id", "") if hasattr(message, "message_id") else message.get("message_id", "")
            chat_id = getattr(message, "chat_id", "") if hasattr(message, "chat_id") else message.get("chat_id", "")
            chat_type = getattr(message, "chat_type", "p2p") if hasattr(message, "chat_type") else message.get("chat_type", "p2p")
            message_type = getattr(message, "message_type", "text") if hasattr(message, "message_type") else message.get("message_type", "text")
            raw_content = getattr(message, "content", "") if hasattr(message, "content") else message.get("content", "")
            create_time = getattr(message, "create_time", "") if hasattr(message, "create_time") else str(message.get("create_time", ""))

            mentions = getattr(message, "mentions", []) if hasattr(message, "mentions") else message.get("mentions", [])

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
        """飞书消息接收核心处理"""
        self._cleanup_expired_images()

        msg = self.normalize_event(event_data)
        if not msg:
            return

        session_id = f"feishu:{msg.chat_type}:{msg.chat_id}"
        target_project = (
            self.config.project_mapping.feishu.get(msg.chat_id, {}).get("project", self.config.project_name)
        )

        mentions = msg.raw_metadata.get("mentions") or []
        is_at_bot = self._is_mention_bot(mentions)

        # 1. 群聊与私聊严格路由 (P0)
        clean_text = msg.text
        if msg.chat_type == "group":
            if not self.config.feishu.receive_group_at:
                return

            # 如果是纯图片消息但没有 @ 机器人：暂存到 session 缓存，静默等待紧随的文字提问 (P1)
            if msg.message_type == "image" and not is_at_bot:
                if msg.image_refs:
                    tmp_img = self.download_resource(message_id=msg.message_id, file_key=msg.image_refs[0])
                    if tmp_img:
                        self.session_recent_images[session_id] = {"image_path": tmp_img, "timestamp": time.time()}
                        self.dedup.mark_completed(msg.event_id, msg.message_id)
                        logger.info(f"已缓存群聊待关联图片: session={session_id}, path={tmp_img}")
                return

            # 如果群聊消息未 @ 机器人本身（比如 @张三），坚决静默忽略！
            if not is_at_bot:
                return

            clean_text = clean_mention_text(msg.text, mentions, bot_name=self.bot_name)

        elif msg.chat_type == "p2p":
            if not self.config.feishu.receive_private:
                return
            clean_text = msg.text.strip()

        # 2. 状态化去重防重锁 (P0)
        if not self.dedup.acquire_lock(event_id=msg.event_id, message_id=msg.message_id):
            logger.info(f"忽略重复或处理中的飞书事件: event_id={msg.event_id}")
            return

        # 3. 现场图片关联与提取 (P1)
        tmp_image_to_use: Optional[str] = None
        should_cleanup_img: bool = False

        if msg.message_type == "image" and msg.image_refs:
            tmp_image_to_use = self.download_resource(message_id=msg.message_id, file_key=msg.image_refs[0])
            should_cleanup_img = True
        elif msg.message_type == "text":
            # 检查会话近期是否有未过期的关联图片
            cached_img = self.session_recent_images.get(session_id)
            if cached_img and (time.time() - cached_img.get("timestamp", 0) <= 300):
                cached_path = cached_img.get("image_path")
                if cached_path and os.path.exists(cached_path):
                    tmp_image_to_use = cached_path
                    should_cleanup_img = True
                    self.session_recent_images.pop(session_id, None)
                    logger.info(f"成功将近期上传的截图关联至当前提问: {cached_path}")

        prompt_content = clean_text or ("请结合此现场图片分析故障原因并给出诊断建议。" if tmp_image_to_use else "")
        if not prompt_content and not tmp_image_to_use:
            self.dedup.mark_completed(msg.event_id, msg.message_id)
            return

        self.audit.record(
            tool_name="FeishuGateway",
            operation="receive_message",
            target=f"session={session_id}, user={msg.user_id}, project={target_project}",
            result_summary=f"收到消息: {prompt_content[:50]}",
            status="SUCCESS",
            session_id=session_id,
            user_id=msg.user_id,
        )

        try:
            # 维护上下文会话
            history = self.session_history.setdefault(session_id, [])
            history.append({"role": "user", "content": prompt_content})

            reply_text = "收到请求，正在诊断中..."
            if self.glm_client:
                reply_text = self.glm_client.chat_completion(history, image_path=tmp_image_to_use)
                history.append({"role": "assistant", "content": reply_text})

            # 4. 敏感凭据脱敏与回送
            safe_reply = redact_secrets(reply_text)
            send_ok = self.send_message(chat_id=msg.chat_id, text=safe_reply, reply_to_message_id=msg.message_id)

            if send_ok:
                self.dedup.mark_completed(event_id=msg.event_id, message_id=msg.message_id)
            else:
                self.dedup.mark_failed(event_id=msg.event_id, message_id=msg.message_id, error="send_message failed")

            self.audit.record(
                tool_name="FeishuGateway",
                operation="reply_message",
                target=f"chat_id={msg.chat_id}, message_id={msg.message_id}",
                result_summary="成功回送业务语言诊断报告",
                status="SUCCESS" if send_ok else "ERROR",
                session_id=session_id,
                user_id=msg.user_id,
            )

        except Exception as e:
            # 异常时释放锁为 FAILED，允许飞书重试时重新消费
            self.dedup.mark_failed(event_id=msg.event_id, message_id=msg.message_id, error=str(e))
            logger.error(f"处理飞书消息发生异常: {e}", exc_info=True)
            raise

        finally:
            # 仅在图片被作为诊断输入消费后，才真正物理销毁临时文件
            if should_cleanup_img and tmp_image_to_use and os.path.exists(tmp_image_to_use):
                try:
                    os.remove(tmp_image_to_use)
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

            with open(target_path, "wb") as f:
                f.write(response.file.read())

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
            "bot_name": self.bot_name,
            "app_id_configured": bool(self.app_id),
            "app_secret_configured": bool(self.app_secret),
            "websocket_client_ready": self._ws_client is not None,
            "running": self._running,
        }
