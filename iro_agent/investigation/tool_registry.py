import re
from typing import Dict, Any, Optional, Callable, List, Tuple
from pydantic import BaseModel, Field
from iro_agent.investigation.models import EvidenceTier


class ToolSpec(BaseModel):
    """排查工具规范定义"""
    name: str
    description: str
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "READ_ONLY"
    tier: EvidenceTier = EvidenceTier.TIER_1A_RUNTIME_DIGITAL
    handler: Optional[Callable] = None


class ToolRegistry:
    """
    工业排查只读安全工具注册表 (Read-Only Tool Registry)
    硬防御核心机制：严格白名单机制，零写权限，任何非白名单或含有写意图的调用均被直接拦截拒决。
    """

    DANGEROUS_SQL_PATTERNS = [
        r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke)\b",
        r";\s*(insert|update|delete|drop|alter)",
    ]

    def __init__(self, register_defaults: bool = True, include_legacy_pipelines: bool = False):
        self._tools: Dict[str, ToolSpec] = {}
        if register_defaults:
            self._register_default_tools(include_legacy_pipelines=include_legacy_pipelines)

    def unregister(self, name: str) -> None:
        """从注册表中注销工具"""
        self._tools.pop(name, None)

    def register(self, spec: ToolSpec) -> None:
        """注册工具（强制校验风险级别必须为 READ_ONLY）"""
        if spec.risk_level != "READ_ONLY":
            raise PermissionError(f"安全违规拦截：只读安全环境禁止注册非只读工具 '{spec.name}' (risk_level={spec.risk_level})")
        self._tools[spec.name] = spec

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def validate_call(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        严密校验工具调用请求：
        1. 必须在只读白名单中；
        2. 参数必须合法；
        3. 数据库查询必须为纯只读 SELECT，严禁任何写操作；
        4. 严禁任何设备控制/写操作。
        """
        if not tool_name:
            return False, "tool_name 不能为空"

        if tool_name not in self._tools:
            return False, f"安全违规拦截：工具 '{tool_name}' 不在只读工具白名单中！当前允许的只读工具: {self.list_tool_names()}"

        spec = self._tools[tool_name]
        args = arguments or {}

        # 1. 针对 db_query 的安全防线：强制只能 SELECT
        if tool_name == "db_query":
            sql = args.get("sql", args.get("query", ""))
            if not sql or not isinstance(sql, str):
                return False, "db_query 必须提供非空的 'sql' 参数"
            sql_clean = sql.strip().lower()
            if not (sql_clean.startswith("select") or sql_clean.startswith("show") or sql_clean.startswith("desc") or sql_clean.startswith("explain")):
                return False, f"安全违规拦截：db_query 仅允许只读查询操作 (SELECT/SHOW/DESC)，检测到非法语句: '{sql[:50]}'"
            for pattern in self.DANGEROUS_SQL_PATTERNS:
                if re.search(pattern, sql_clean):
                    return False, f"安全违规拦截：检测到数据库写/结构变更关键字，已硬阻断: '{sql[:50]}'"

        # 2. 针对 log_search 的参数校验
        if tool_name == "log_search":
            if not any(k in args for k in ("keyword", "query", "keywords")):
                return False, "log_search 必须提供 'keyword' 检索参数"

        # 3. 针对 config_lookup 的参数校验
        if tool_name == "config_lookup":
            if not any(k in args for k in ("query", "key", "keyword")):
                return False, "config_lookup 必须提供 'query' 参数"

        # 4. 针对 plc_read 的只读防线
        if tool_name == "plc_read":
            if not any(k in args for k in ("register", "address", "tag", "point")):
                return False, "plc_read 必须提供目标寄存器或点位参数 ('register' 或 'address')"
            # 绝不允许包含 write_value
            if "value" in args or "write_value" in args or "write" in args:
                return False, "安全违规拦截：plc_read 属于只读点位采集，禁止传入写入值"

        # 5. 针对 robot_query 的只读防线
        if tool_name == "robot_query":
            # 绝不允许包含 move, exec, action 指令
            if any(k in args for k in ("action", "command", "move_to", "speed", "reset_alarm")):
                return False, "安全违规拦截：robot_query 仅允许查询状态，禁止发送任何运动或复位控制指令"

        return True, None

    def get_prompt_description(self) -> str:
        """生成供 LLM Planner 提示词使用的工具能力清单 Markdown 格式"""
        lines = []
        for name, spec in sorted(self._tools.items()):
            lines.append(f"- `{name}`: {spec.description}")
            if spec.parameters_schema:
                param_strs = [f"{p}: {t}" for p, t in spec.parameters_schema.items()]
                lines.append(f"  参数: {{{', '.join(param_strs)}}}")
        return "\n".join(lines)

    def _register_default_tools(self, include_legacy_pipelines: bool = False) -> None:
        """注册工业现场标准只读安全工具"""
        self.register(ToolSpec(
            name="log_search",
            description="检索应用服务和系统运行日志，支持按关键词、异常码、时间范围过滤",
            parameters_schema={"keyword": "str, 必填", "limit": "int, 选填, 默认20"},
            tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        ))
        self.register(ToolSpec(
            name="db_query",
            description="只读查询业务核心数据库 (MySQL/PostgreSQL)，仅允许 SELECT/SHOW",
            parameters_schema={"sql": "str, 必填, 仅允许只读 SELECT 语句"},
            tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        ))
        self.register(ToolSpec(
            name="config_lookup",
            description="查阅生效中的配置文件、环境变量与参数项",
            parameters_schema={"query": "str, 必填, 配置键或模块名"},
            tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        ))
        self.register(ToolSpec(
            name="version_current",
            description="获取当前部署版本、Git Commit 以及发版时间",
            parameters_schema={},
            tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        ))
        self.register(ToolSpec(
            name="project_lookup",
            description="检索项目蓝图知识库（业务流定义、状态机、设备拓扑架构）",
            parameters_schema={"query": "str, 必填, 检索概念或实体"},
            tier=EvidenceTier.TIER_1B_STATIC_FACTS,
        ))
        self.register(ToolSpec(
            name="plc_read",
            description="只读读取 PLC 寄存器/点位状态（如通信心跳、握手信号、光电传感器），严格只读",
            parameters_schema={"address": "str, 必填, 寄存器或点位地址"},
            tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
        ))
        self.register(ToolSpec(
            name="robot_query",
            description="只读查询机械臂/AGV/移动机器人运行状态、通信端口、当前报警码",
            parameters_schema={"query_type": "str, 选填, 如 status/alarm/pose"},
            tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
        ))
        self.register(ToolSpec(
            name="web_fetch",
            description="只读获取内部微服务或硬件设备 HTTP 只读接口",
            parameters_schema={"url": "str, 必填, 必须为只读 GET 请求"},
            tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
        ))
        if include_legacy_pipelines:
            self.register(ToolSpec(
                name="diagnostic_pipeline",
                description="运行内建多维只读日志关联分析流水线",
                parameters_schema={"symptom": "str, 必填, 故障症状描述"},
                tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
            ))
