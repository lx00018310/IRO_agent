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


class GatewayConfig(BaseModel):
    type: str = "feishu"  # "feishu" | "http"
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080


class FeishuConfig(BaseModel):
    enabled: bool = True
    app_id: str = ""
    app_secret: str = ""
    bot_name: str = "IRO_agent"
    receive_group_at: bool = True
    receive_private: bool = True


class ProjectMappingConfig(BaseModel):
    feishu: dict[str, dict[str, str]] = Field(default_factory=dict)


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
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    project_mapping: ProjectMappingConfig = Field(default_factory=ProjectMappingConfig)
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
    """加载单一配置文件。绝对不覆盖用户文件，严格只读读取。"""
    global _CONFIG_INSTANCE
    base_dir = Path(__file__).resolve().parent.parent
    target_path: Optional[Path] = None

    if config_path:
        target_path = Path(config_path).resolve()
    elif os.environ.get("IRO_CONFIG_PATH"):
        target_path = Path(os.environ["IRO_CONFIG_PATH"]).resolve()
    elif (base_dir / "config.json").is_file():
        target_path = base_dir / "config.json"
    elif Path("config.json").is_file():
        target_path = Path("config.json").resolve()
    elif (base_dir / "config.example.json").is_file():
        target_path = base_dir / "config.example.json"

    if target_path and target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _CONFIG_INSTANCE = IROConfig(**data)
    else:
        _CONFIG_INSTANCE = IROConfig()

    # 环境变量覆盖（安全优先级高于文件明文）
    if os.environ.get("IRO_GLM_API_KEY"):
        _CONFIG_INSTANCE.glm.api_key = os.environ["IRO_GLM_API_KEY"]
    if os.environ.get("IRO_DB_PASSWORD"):
        _CONFIG_INSTANCE.database.password = os.environ["IRO_DB_PASSWORD"]
    if os.environ.get("IRO_DB_HOST"):
        _CONFIG_INSTANCE.database.host = os.environ["IRO_DB_HOST"]
    if os.environ.get("IRO_DB_USER"):
        _CONFIG_INSTANCE.database.user = os.environ["IRO_DB_USER"]

    # 飞书凭据与网关环境变量支持
    feishu_app_id = os.environ.get("FEISHU_APP_ID") or os.environ.get("IRO_FEISHU_APP_ID")
    if feishu_app_id:
        _CONFIG_INSTANCE.feishu.app_id = feishu_app_id

    feishu_app_secret = os.environ.get("FEISHU_APP_SECRET") or os.environ.get("IRO_FEISHU_APP_SECRET")
    if feishu_app_secret:
        _CONFIG_INSTANCE.feishu.app_secret = feishu_app_secret

    feishu_bot_name = os.environ.get("FEISHU_BOT_NAME") or os.environ.get("IRO_FEISHU_BOT_NAME")
    if feishu_bot_name:
        _CONFIG_INSTANCE.feishu.bot_name = feishu_bot_name

    if os.environ.get("IRO_GATEWAY_TYPE"):
        _CONFIG_INSTANCE.gateway.type = os.environ["IRO_GATEWAY_TYPE"]

    return _CONFIG_INSTANCE


def get_config() -> IROConfig:
    """获取当前全局配置单例"""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE
