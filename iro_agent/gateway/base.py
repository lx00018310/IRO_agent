from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class GatewayMessage(BaseModel):
    """网关消息统一归一化数据载荷"""
    gateway: str = "feishu"  # "feishu" | "http"
    event_id: str = ""
    message_id: str = ""
    chat_id: str = ""
    chat_type: str = "p2p"  # "p2p" | "group"
    user_id: str = ""
    timestamp: str = ""
    message_type: str = "text"  # "text" | "image"
    text: str = ""
    image_refs: List[str] = Field(default_factory=list)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


class GatewayAdapter(ABC):
    """网关适配器抽象接口规范"""

    @abstractmethod
    def start(self, block: bool = True) -> None:
        """启动网关服务"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """停止网关服务"""
        pass

    @abstractmethod
    def send_message(self, chat_id: str, text: str, reply_to_message_id: Optional[str] = None) -> bool:
        """回送消息"""
        pass

    @abstractmethod
    def download_resource(self, message_id: str, file_key: str, target_dir: Optional[str] = None) -> Optional[str]:
        """下载媒体资源（如现场截图），保存至受控临时目录并返回绝对路径"""
        pass

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """健康检查"""
        pass
