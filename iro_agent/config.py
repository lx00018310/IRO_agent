import json
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "ordersys"
    connect_timeout: int = 5


class GlmConfig(BaseModel):
    api_key: str = ""
    api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-5.3-flash"
    timeout: int = 60


class WeChatConfig(BaseModel):
    enabled: bool = False
    listen_host: str = "0.0.0.0"
    listen_port: int = 8080
    webhook_url: str = ""
    token: str = ""
    aes_key: str = ""


class StorageConfig(BaseModel):
    audit_db_path: str = "iro_agent_audit.db"
    memory_db_path: str = "iro_agent_memory.db"


class IROConfig(BaseModel):
    project_name: str = "TASK-013"
    project_root: str = "D:/当前工作/维力智能设备/TASK-013_武汉自动上车显示屏"
    wrelease_dir: str = "D:/当前工作/维力智能设备/TASK-013_武汉自动上车显示屏/deployment_control/native/delivery"
    log_dirs: List[str] = Field(
        default_factory=lambda: [
            "D:/当前工作/维力智能设备/TASK-013_武汉自动上车显示屏/deployment_control",
            "D:/当前工作/维力智能设备/TASK-013_武汉自动上车显示屏/cache/260829日志",
        ]
    )
    allowed_paths: List[str] = Field(default_factory=list)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    glm: GlmConfig = Field(default_factory=GlmConfig)
    wechat: WeChatConfig = Field(default_factory=WeChatConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    def get_effective_allowed_paths(self) -> List[str]:
        """返回规范化后的允许访问只读目录列表"""
        paths = set()
        if self.project_root and os.path.exists(self.project_root):
            paths.add(os.path.abspath(self.project_root))
        if self.wrelease_dir and os.path.exists(self.wrelease_dir):
            paths.add(os.path.abspath(self.wrelease_dir))
        for ld in self.log_dirs:
            if ld and os.path.exists(ld):
                paths.add(os.path.abspath(ld))
        for ap in self.allowed_paths:
            if ap and os.path.exists(ap):
                paths.add(os.path.abspath(ap))
        return sorted(list(paths))


_CONFIG_INSTANCE: Optional[IROConfig] = None


def load_config(config_path: Optional[str] = None) -> IROConfig:
    """加载单一配置文件。优先顺序：显式参数 -> 环境变量 IRO_CONFIG_PATH -> 本地 config.json -> 本地 config.example.json -> 默认配置"""
    global _CONFIG_INSTANCE
    target_path: Optional[Path] = None

    if config_path:
        target_path = Path(config_path)
    elif os.environ.get("IRO_CONFIG_PATH"):
        target_path = Path(os.environ["IRO_CONFIG_PATH"])
    elif Path("config.json").exists():
        target_path = Path("config.json")
    elif Path("config.example.json").exists():
        target_path = Path("config.example.json")

    if target_path and target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _CONFIG_INSTANCE = IROConfig(**data)
    else:
        _CONFIG_INSTANCE = IROConfig()

    return _CONFIG_INSTANCE


def get_config() -> IROConfig:
    """获取当前全局配置单例"""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE
