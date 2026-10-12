"""Interactive project onboarding. This writes only the agent's own config file."""

import getpass
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from iro_agent.config import (
    DatabaseSourceConfig, DirectorySourceConfig, HttpSourceConfig, IROConfig,
    SetupState, SourcesConfig, read_config_data,
)


class SetupRequiredError(ValueError):
    pass


class SetupCancelled(Exception):
    pass


def validation_message(exc: ValidationError) -> str:
    # Pydantic's default string includes raw input, which may contain credentials.
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False))


def configuration_errors(config: IROConfig) -> list[str]:
    errors = []
    if not config.project_name.strip():
        errors.append("项目名称为空")
    if not config.project_root or not Path(config.project_root).is_dir():
        errors.append("项目工作目录不存在")
    if config.wrelease_dir and not Path(config.wrelease_dir).is_dir():
        errors.append("WRelease 目录不存在")
    if config.sources is None or not any(getattr(config.sources, k) for k in ("code", "logs", "databases", "http")):
        errors.append("至少需要一个数据来源")
    elif config.sources is not None:
        for source in config.sources.code + config.sources.logs:
            if not Path(source.path).is_absolute() or not Path(source.path).is_dir():
                errors.append(f"来源 {source.id} 必须是存在的绝对目录路径")
    return errors


def require_setup(config: IROConfig):
    if not config.is_setup_complete():
        raise SetupRequiredError("尚未完成本项目配置引导，或项目/来源配置已改变。请先执行 python -m iro_agent.cli setup")
    # Transient source outages are reported by readers, not disguised as incomplete onboarding.
    if not config.project_name.strip() or not config.project_root or config.sources is None:
        raise SetupRequiredError("项目配置不完整，请重新执行 setup")
    if not Path(config.project_root).is_dir():
        raise SetupRequiredError("项目工作目录不可用，请恢复目录或重新执行 setup；不能改用其他目录的项目缓存")


def masked_config(value):
    if isinstance(value, dict):
        return {k: ("********" if v and (k.lower() in {"password", "api_key", "token", "app_secret", "secret", "private_key"}
                                      or "secret" in k.lower() and not k.endswith("_env")) else masked_config(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [masked_config(v) for v in value]
    return value


def atomic_save(path: Path, data: dict, expected_content: bytes | None):
    current = path.read_bytes() if path.exists() else None
    if current != expected_content:
        raise ValueError("配置文件在向导运行期间被其他程序修改；未覆盖，请重新运行 setup")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".iro-setup-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


class SetupWizard:
    def __init__(self, path: Path, input_fn=None, secret_fn=None, print_fn=print):
        self.path = path.resolve()
        self.input = input_fn or input
        self.secret = secret_fn or getpass.getpass
        self.print = print_fn

    def ask(self, prompt, default="", required=False):
        while True:
            value = self.input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
            if value.lower() in ("q", "quit", "exit"):
                raise SetupCancelled()
            value = "" if value == "-" else value or str(default)
            if required and not value:
                self.print("此项不能为空。")
                continue
            return value

    def yes(self, prompt, default=False):
        while True:
            value = self.ask(prompt + " (y/n)", "y" if default else "n").lower()
            if value in ("y", "yes", "是"):
                return True
            if value in ("n", "no", "否"):
                return False
            self.print("请输入 y 或 n。")

    def directory(self, prompt, default="", required=True):
        while True:
            raw = self.ask(prompt, default, required).strip('"\'')
            if not raw and not required:
                return ""
            path = Path(raw).expanduser().resolve()
            if path.is_dir():
                return path.as_posix()
            self.print("目录不存在，请重新输入；可粘贴带引号的 Windows 路径。")

    def secret_value(self, prompt, current=""):
        value = self.secret(prompt + ("（回车保留，- 清空）: " if current else "（不回显，回车跳过）: "))
        if value.lower() in ("q", "quit", "exit"):
            raise SetupCancelled()
        return "" if value == "-" else value or current

    @staticmethod
    def import_legacy(config):
        sources = {kind: [] for kind in ("code", "logs", "databases", "http")}
        if config.project_root:
            sources["code"].append({"id": "code-1", "description": "原项目代码", "path": config.project_root})
        for index, path in enumerate(dict.fromkeys(config.log_dirs), 1):
            if path:
                sources["logs"].append({"id": f"logs-{index}", "description": f"原日志目录 {index}", "path": path})
        if config.database.host and config.database.database and config.database.user:
            sources["databases"].append({**config.database.model_dump(), "id": "db-1", "description": "原业务数据库"})
        return SourcesConfig(**sources)

    def add_source(self, sources, kind):
        all_ids = {s.id.lower() for k in ("code", "logs", "databases", "http") for s in getattr(sources, k)}
        index = 1
        prefix = {"code": "code", "logs": "logs", "databases": "db", "http": "http"}[kind]
        while f"{prefix}-{index}" in all_ids:
            index += 1
        data = {"id": self.ask("来源 ID（字母开头，字母/数字/-/_）", f"{prefix}-{index}", True),
                "description": self.ask("来源用途（帮助查询时选对来源）", required=True)}
        if kind in ("code", "logs"):
            data["path"] = self.directory("目录路径")
            model = DirectorySourceConfig
        elif kind == "databases":
            self.print("当前支持 PostgreSQL，请使用只读数据库账号。")
            data.update(host=self.ask("数据库地址", required=True), port=self.ask("端口", "5432"),
                        database=self.ask("数据库名", required=True), user=self.ask("只读账号", required=True),
                        password_env=self.ask("密码环境变量名（留空则输入密码）"))
            if not data["password_env"]:
                data["password"] = self.secret_value("数据库密码")
            model = DatabaseSourceConfig
        else:
            self.print("登记完整的只读 GET 端点；只允许这个精确 URL，不跟随重定向。")
            data["url"] = self.ask("完整 HTTP/HTTPS URL", required=True)
            data["headers_env"] = {}
            while self.yes("是否添加鉴权请求头环境变量"):
                header = self.ask("请求头名称", "Authorization", True)
                data["headers_env"][header] = self.ask("环境变量名（其值为完整请求头内容）", required=True)
            model = HttpSourceConfig
        source = model(**data)
        updated = sources.model_dump()
        updated[kind].append(source.model_dump())
        return SourcesConfig(**updated)

    def manage_sources(self, sources):
        while True:
            self.print("\n来源管理：1 添加代码目录；2 添加数据库；3 添加日志目录；4 添加 HTTP 接口；5 删除来源；6 查看；0 下一步")
            self.print("当前来源：" + ", ".join(s.id for k in ("code", "databases", "logs", "http") for s in getattr(sources, k)))
            choice = self.ask("选择", "0")
            if choice == "0":
                if not any(getattr(sources, k) for k in ("code", "logs", "databases", "http")):
                    self.print("至少添加一个来源后才能继续。")
                    continue
                return sources
            try:
                if choice in ("1", "2", "3", "4"):
                    sources = self.add_source(sources, {"1": "code", "2": "databases", "3": "logs", "4": "http"}[choice])
                elif choice == "5":
                    source_id = self.ask("要删除的来源 ID", required=True)
                    updated = sources.model_dump()
                    found = any(s["id"] == source_id for items in updated.values() for s in items)
                    sources = SourcesConfig(**{k: [s for s in items if s["id"] != source_id] for k, items in updated.items()})
                    self.print("已删除。" if found else "未找到该来源。")
                elif choice == "6":
                    self.print(json.dumps(masked_config(sources.model_dump()), indent=2, ensure_ascii=False))
                else:
                    self.print("请输入菜单中的编号。")
            except ValidationError as exc:
                self.print("来源未添加：" + validation_message(exc))

    def run(self):
        self.print("IRO_agent 项目配置向导：一个实例只管理一个项目。输入 q 或 Ctrl+C 取消；- 清空可选项。")
        self.print(f"配置文件：{self.path}")
        original = self.path.read_bytes() if self.path.is_file() else None
        raw = read_config_data(self.path) if original is not None else {}
        config = IROConfig(**raw)
        if not raw:
            config.storage.audit_db_path = (self.path.parent / "iro_agent_audit.db").as_posix()
            config.storage.memory_db_path = (self.path.parent / "iro_agent_memory.db").as_posix()
        sources = config.sources if config.sources is not None else self.import_legacy(config)
        self.print("\n[1/4] 项目与工作目录")
        config.project_name = self.ask("项目名称", config.project_name, True)
        config.project_root = self.directory("项目工作目录（存放 .iro_agent 认知缓存）", config.project_root or str(self.path.parent))
        config.wrelease_dir = self.directory("WRelease 交付目录（可跳过）", config.wrelease_dir, False)

        self.print("\n[2/4] 添加同一个项目的多个来源；不需要的类型可以跳过。")
        while True:
            config.sources = self.manage_sources(sources)
            errors = configuration_errors(config)
            if not errors:
                break
            self.print("\n".join(errors))
            self.print("请删除或重新添加无效的来源。")
            sources = config.sources

        self.print("\n[3/4] 模型与可选网关")
        config.glm.api_base = self.ask("模型 API 地址", config.glm.api_base, True)
        config.glm.model = self.ask("模型名称", config.glm.model, True)
        self.print("模型 Key 可用环境变量 IRO_GLM_API_KEY；留空仍可执行静态认知初始化。")
        if self.yes("是否输入/更新模型 API Key", not bool(config.glm.api_key or os.environ.get("IRO_GLM_API_KEY"))):
            config.glm.api_key = self.secret_value("模型 API Key", config.glm.api_key)
        has_feishu = bool(config.feishu.app_id and config.feishu.app_id != "YOUR_FEISHU_APP_ID")
        config.feishu.enabled = self.yes("是否配置飞书机器人网关", has_feishu)
        if config.feishu.enabled:
            self.print("也可设置 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量。")
            config.feishu.app_id = self.ask("飞书 App ID", config.feishu.app_id)
            if not os.environ.get("FEISHU_APP_SECRET") and not os.environ.get("IRO_FEISHU_APP_SECRET"):
                config.feishu.app_secret = self.secret_value("飞书 App Secret", config.feishu.app_secret)

        self.print("\n[4/4] 校验与保存")
        from iro_agent.readers.sources import SourceReaders
        if self.yes("是否执行来源连通性检查（数据库 SELECT 1 / HTTP GET）", True):
            checks = SourceReaders(config).check()
            self.print(json.dumps(checks, ensure_ascii=False, indent=2))
            if any(c["status"] != "OK" for c in checks) and not self.yes("存在不可用来源，是否明确保留这些来源并完成配置"):
                raise SetupCancelled()
        else:
            self.print("未执行数据库/HTTP 连通性测试；运行时会明确报告不可用来源。")
        self.print(json.dumps(masked_config(config.model_dump(exclude={"setup"})), indent=2, ensure_ascii=False))
        if not self.yes("确认保存并完成本项目配置流程", True):
            raise SetupCancelled()
        config.setup = SetupState(version=1, completed_at=datetime.now(timezone.utc).isoformat(),
                                  fingerprint=config.setup_fingerprint())
        # Preserve unrelated existing top-level settings; never persist environment overrides.
        atomic_save(self.path, {**raw, **config.model_dump()}, original)
        self.print(f"配置流程已完成：{self.path}\n可执行 init --static-only、chat、investigate 或 gateway start。")
        self.print(f'后续命令使用同一配置文件：python -m iro_agent.cli --config "{self.path.as_posix()}" chat')
        return config
