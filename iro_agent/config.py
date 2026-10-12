import json
import os
import hashlib
import re
from pathlib import Path
from typing import List, Optional, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, field_validator, model_validator


class DatabaseConfig(BaseModel):
    type: Literal["postgresql", "mysql"] = "postgresql"
    host: str = ""
    port: int = 5432
    user: str = ""
    password: str = ""
    database: str = ""
    connect_timeout: int = 5
    query_timeout: int = Field(default=10, ge=1, le=60)

    @model_validator(mode="before")
    @classmethod
    def default_port(cls, data):
        if isinstance(data, dict) and data.get("type") == "mysql" and "port" not in data:
            return {**data, "port": 3306}
        return data


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


class InvestigationConfig(BaseModel):
    max_iterations: int = 10
    max_tool_calls: int = 12
    max_no_gain_rounds: int = 2
    physical_escalation_enabled: bool = True


class BootstrapConfig(BaseModel):
    max_rounds: int = 12
    min_coverage_gain: float = 0.03
    max_no_gain_rounds: int = 2


class EvaluationConfig(BaseModel):
    save_trajectory: bool = True
    repeat_count: int = 1


class SourceConfig(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    description: str = Field(min_length=1)


class DirectorySourceConfig(SourceConfig):
    path: str = Field(min_length=1)


def validate_env_name(value: str) -> str:
    if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("环境变量名只能包含字母、数字和下划线，不能以数字开头")
    return value


class DatabaseSourceConfig(DatabaseConfig, SourceConfig):
    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = Field(min_length=1)
    database: str = Field(min_length=1)
    connect_timeout: int = Field(default=5, ge=1, le=60)
    password_env: str = ""

    _env_name = field_validator("password_env")(validate_env_name)

    def connection_config(self) -> DatabaseConfig:
        data = self.model_dump(include=set(DatabaseConfig.model_fields))
        if self.password_env:
            if not os.environ.get(self.password_env):
                raise ValueError(f"缺少数据库凭据环境变量 {self.password_env}")
            data["password"] = os.environ[self.password_env]
        return DatabaseConfig(**data)


class OtherSourceConfig(SourceConfig):
    """任意本地只读资料：API/接口文档、数据字典、说明文件、导出的 JSON/CSV 等。"""
    path: str = Field(min_length=1)  # Directory (recursive) or a single file.

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("其他来源必须是绝对路径（目录或单个文件）")
        return value


class HttpSourceConfig(SourceConfig):
    url: str
    headers_env: dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=15, ge=1, le=60)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username or parts.password or parts.fragment
                or any(c.isspace() for c in value)):
            raise ValueError("接口必须是完整 HTTP/HTTPS URL，不能包含账号、密码、片段或空白")
        # Accessing .port also rejects malformed or out-of-range ports.
        _ = parts.port
        from urllib.parse import parse_qsl
        if any(re.search(r"password|secret|token|api[_-]?key", k, re.I) for k, _ in parse_qsl(parts.query)):
            raise ValueError("接口凭据请使用请求头环境变量，不要放在 URL 中")
        return value

    @field_validator("headers_env")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for header, env_name in value.items():
            if (not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", header)
                    or header.lower() in {"host", "content-length", "transfer-encoding", "connection"}
                    or "method" in header.lower() or "override" in header.lower()):
                raise ValueError("不允许该请求头名称")
            if not env_name:
                raise ValueError("请求头必须引用非空的环境变量名")
            validate_env_name(env_name)
        return value


class SourcesConfig(BaseModel):
    code: list[DirectorySourceConfig] = Field(default_factory=list)
    logs: list[DirectorySourceConfig] = Field(default_factory=list)
    databases: list[DatabaseSourceConfig] = Field(default_factory=list)
    http: list[HttpSourceConfig] = Field(default_factory=list)
    other: list[OtherSourceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_sources(self):
        ids, locations = set(), set()
        for kind in ("code", "logs", "databases", "http", "other"):
            for source in getattr(self, kind):
                if source.id.lower() in ids:
                    raise ValueError(f"来源 ID 重复: {source.id}")
                ids.add(source.id.lower())
                if kind in ("code", "logs"):
                    location = (kind, os.path.normcase(str(Path(source.path).resolve())))
                elif kind == "other":
                    location = (kind, os.path.normcase(str(Path(source.path).resolve())))
                elif kind == "http":
                    location = (kind, source.url)
                else:
                    location = (kind, source.type, source.host.lower(), source.port, source.database, source.user)
                if location in locations:
                    raise ValueError(f"重复的数据来源: {source.id}")
                locations.add(location)
        return self


class SetupState(BaseModel):
    version: int = 0
    completed_at: str = ""
    fingerprint: str = ""


class IROConfig(BaseModel):
    project_name: str = ""
    project_root: str = ""
    wrelease_dir: str = ""
    log_dirs: List[str] = Field(default_factory=list)
    allowed_paths: List[str] = Field(default_factory=list)
    sources: Optional[SourcesConfig] = None  # None denotes the old single-source schema.
    setup: SetupState = Field(default_factory=SetupState)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    glm: GlmConfig = Field(default_factory=GlmConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    project_mapping: ProjectMappingConfig = Field(default_factory=ProjectMappingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    investigation: InvestigationConfig = Field(default_factory=InvestigationConfig)
    bootstrap: BootstrapConfig = Field(default_factory=BootstrapConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    @property
    def primary_code_root(self) -> str:
        if self.sources is not None:
            return self.sources.code[0].path if self.sources.code else ""
        return self.project_root

    def setup_fingerprint(self) -> str:
        sources = self.sources.model_dump() if self.sources is not None else None
        if sources:
            for db in sources["databases"]:
                db.pop("password", None)
        payload = {
            "project_name": self.project_name, "project_root": self.project_root,
            "wrelease_dir": self.wrelease_dir, "allowed_paths": self.allowed_paths,
            "sources": sources,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def is_setup_complete(self) -> bool:
        return bool(self.project_name.strip() and self.project_root and self.sources is not None
                    and any(getattr(self.sources, kind) for kind in ("code", "logs", "databases", "http", "other"))
                    and self.setup.version == 1 and self.setup.completed_at
                    and self.setup.fingerprint == self.setup_fingerprint())

    def get_effective_allowed_paths(self) -> List[str]:
        """返回规范化后的允许访问只读目录列表"""
        paths = set()
        if self.project_root and os.path.exists(self.project_root):
            paths.add(os.path.abspath(self.project_root))
        if self.wrelease_dir and os.path.exists(self.wrelease_dir):
            paths.add(os.path.abspath(self.wrelease_dir))
        source_paths = []
        if self.sources is not None:
            source_paths = [s.path for s in self.sources.code + self.sources.logs + self.sources.other]
        for ld in (self.log_dirs if self.sources is None else source_paths):
            if ld and os.path.exists(ld):
                paths.add(os.path.abspath(ld))
        for ap in self.allowed_paths:
            if ap and os.path.exists(ap):
                paths.add(os.path.abspath(ap))
        return sorted(list(paths))


_CONFIG_INSTANCE: Optional[IROConfig] = None
_CONFIG_PATH: Optional[Path] = None


def resolve_config_path(config_path: Optional[str] = None) -> Path:
    return Path(config_path or os.environ.get("IRO_CONFIG_PATH") or "config.json").expanduser().resolve()


def read_config_data(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置 JSON 不合法（第 {exc.lineno} 行，第 {exc.colno} 列）；Windows 路径请使用 / 或双反斜杠") from None
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是 JSON 对象")
    return data


def load_config(config_path: Optional[str] = None) -> IROConfig:
    """加载单一配置文件。绝对不覆盖用户文件，严格只读读取。"""
    global _CONFIG_INSTANCE, _CONFIG_PATH
    target_path = resolve_config_path(config_path)
    if not target_path.is_file() and (config_path or os.environ.get("IRO_CONFIG_PATH")):
        raise FileNotFoundError(f"未找到指定配置文件: {target_path}；请先执行 setup")
    _CONFIG_INSTANCE = IROConfig(**read_config_data(target_path)) if target_path.is_file() else IROConfig()
    _CONFIG_PATH = target_path

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
