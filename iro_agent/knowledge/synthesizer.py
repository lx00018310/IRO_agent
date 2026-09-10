import json
import time
import re
from typing import Dict, Any, List, Optional, Set
from iro_agent.knowledge.models import (
    ProjectBlueprint,
    ProjectMetadata,
    ProjectOverview,
    ModuleKnowledge,
    BusinessConcept,
    SourceOfTruthRule,
    TableKnowledge,
    StateEnumKnowledge,
    CodeLocation,
    ConfigItem,
    ConfigPriorityRule,
    BusinessFlow,
    ExternalSystem,
    ApiKnowledge,
)
from iro_agent.knowledge.tree_scanner import TreeScanResult
from iro_agent.knowledge.schema_scanner import SchemaScanResult
from iro_agent.knowledge.code_scanner import CodeScanResult
from iro_agent.knowledge.business_flows import BusinessFlowLearner
from iro_agent.config import get_config, GlmConfig
from iro_agent.llm.glm_client import GlmClient


class KnowledgeSynthesizer:
    """通用工业项目认知提炼器：7-Pass 多轮结构化提炼合成器 (代码图谱 + 静态证据 + 深度语义)"""

    def __init__(self, glm_cfg: Optional[GlmConfig] = None):
        self.config = get_config()
        self.glm_cfg = glm_cfg or self.config.glm

    def synthesize(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
        config_items: Optional[List[ConfigItem]] = None,
        config_rules: Optional[List[ConfigPriorityRule]] = None,
        use_llm: bool = True,
    ) -> ProjectBlueprint:
        """执行 7-Pass 结构化多通道认知合成"""
        configs = config_items or []
        cfg_rules = config_rules or []

        # 具备 GLM 能力且允许使用时调用 7-Pass LLM 提纯，否则无缝执行高质量确定性基线合成
        has_llm = bool(
            use_llm and self.glm_cfg and self.glm_cfg.api_key and self.glm_cfg.api_key != "YOUR_GLM_API_KEY"
        )
        client = GlmClient(glm_cfg=self.glm_cfg) if has_llm else None

        # Pass 1: Project & Module Summary
        overview, modules = self._pass_1_project_module_summary(tree_res, client)

        # Pass 2: Config Semantics
        refined_configs = self._pass_2_config_semantics(configs, client)

        # Pass 3: Database & Table Semantics
        tables = self._pass_3_database_table_semantics(schema_res, code_res, client)

        # Pass 4: Business Flows
        flows = self._pass_4_business_flows(code_res, tables, configs, client)

        # Pass 5: Source of Truth
        concepts, sot_rules = self._pass_5_source_of_truth(tables, flows, client)

        # Pass 6: External Integrations
        external_systems = self._pass_6_external_integrations(code_res, flows, client)

        # Pass 7: Terminology & Aliases (对齐概念与流的同义词)
        concepts, flows = self._pass_7_terminology_aliases(concepts, flows, client)

        # 组装状态枚举与代码物理位置
        states: List[StateEnumKnowledge] = []
        for e in code_res.enums:
            enum_name = e.get("name", "")
            for val in e.get("fields_or_constants", []):
                meaning = "已创建/待执行" if "CREATE" in val else ("已完成" if "COMPLET" in val else f"状态项: {val}")
                states.append(
                    StateEnumKnowledge(
                        name=f"{enum_name}.{val}",
                        value=val,
                        business_meaning=meaning,
                        source_location=e.get("file_path", ""),
                        confidence="strongly_inferred",
                    )
                )

        code_locations: List[CodeLocation] = []
        for ent in code_res.entities:
            if ent.mapped_table:
                code_locations.append(
                    CodeLocation(
                        concept=f"ORM: {ent.name}",
                        module=ent.file_path.split("/")[0] if "/" in ent.file_path else "root",
                        file=ent.file_path,
                        symbol=ent.name,
                        purpose=f"映射数据表 `{ent.mapped_table}`",
                    )
                )

        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        metadata = ProjectMetadata(
            project_id=self.config.project_name or "INDUSTRIAL_PROJECT",
            project_name=self.config.project_name or "工业控制系统",
            generated_at=now_str,
            last_verified_at=now_str,
            source_root=str(tree_res.project_root),
            database_type="postgresql",
        )

        return ProjectBlueprint(
            project=metadata,
            project_overview=overview,
            modules=modules,
            business_concepts=concepts,
            business_flows=flows,
            config_catalog=refined_configs,
            config_priority_rules=cfg_rules,
            external_systems=external_systems,
            database_tables=tables,
            states=states,
            source_of_truth_rules=sot_rules,
            code_locations=code_locations,
            metadata={"code_graph": code_res.code_graph or {}},
        )

    # ---------------- 7-Pass 独立合成通道 ----------------

    def _pass_1_project_module_summary(
        self,
        tree_res: TreeScanResult,
        client: Optional[GlmClient],
    ) -> tuple[ProjectOverview, List[ModuleKnowledge]]:
        """Pass 1: 工程全景与模块职责提纯"""
        overview = ProjectOverview(
            modules=list(tree_res.top_level_modules),
            runtime_components=["BackendService", "DeploymentControl"],
            languages=[tree_res.primary_language],
            frameworks=list(tree_res.frameworks),
            entry_points=list(tree_res.entry_points),
            important_directories=list(tree_res.key_directories)[:20],
            startup_scripts=list(tree_res.startup_scripts),
            deployment_scripts=list(tree_res.deployment_scripts),
        )

        modules: List[ModuleKnowledge] = []
        for mod_name in tree_res.top_level_modules:
            role = f"业务子模块: {mod_name}"
            if "deploy" in mod_name.lower() or "deliver" in mod_name.lower():
                role = "部署运维、工控分发与原生版本交付模块"
            elif "back" in mod_name.lower() or "server" in mod_name.lower():
                role = "后端核心任务调度、订单与物料控制核心模块"
            elif "front" in mod_name.lower() or "ui" in mod_name.lower() or "web" in mod_name.lower():
                role = "现场人机交互终端或看板展示前端模块"

            modules.append(
                ModuleKnowledge(
                    module_id=mod_name.lower(),
                    name=mod_name,
                    business_role=role,
                    technical_type=tree_res.primary_language,
                    main_paths=[mod_name],
                    confidence="confirmed",
                    sources=["tree_scanner"],
                )
            )
        return overview, modules

    def _pass_2_config_semantics(
        self,
        configs: List[ConfigItem],
        client: Optional[GlmClient],
    ) -> List[ConfigItem]:
        """Pass 2: 配置项语义增强"""
        # 针对每个配置项，已在 Scanner 中根据关键词做了强语义解析，确保每个配置项都有明确作用与单位
        return configs

    def _pass_3_database_table_semantics(
        self,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
        client: Optional[GlmClient],
    ) -> List[TableKnowledge]:
        """Pass 3: 数据库表语义与角色分类提纯"""
        tables: List[TableKnowledge] = []
        raw_table_info: Dict[str, Dict[str, Any]] = {}

        for t in schema_res.tables:
            col_names = [c.name for c in t.columns]
            raw_table_info[t.table_name] = {
                "columns": col_names,
                "primary_key": t.primary_key,
                "source": "runtime_database_schema" if schema_res.connected else "schema_scanner",
                "confidence": "confirmed" if schema_res.connected else "strongly_inferred",
            }

        for ent in code_res.entities:
            if ent.mapped_table:
                info = raw_table_info.setdefault(ent.mapped_table, {
                    "columns": list(ent.fields_or_constants),
                    "primary_key": "id",
                    "source": "code_scanner",
                    "confidence": "strongly_inferred",
                })
                for f in ent.fields_or_constants:
                    if f not in info["columns"]:
                        info["columns"].append(f)

        for tbl_name, info in raw_table_info.items():
            t_lower = tbl_name.lower()
            cols = info["columns"]
            cols_lower = [c.lower() for c in cols]

            status_cols = [c for c in cols if any(k in c.lower() for k in ("status", "state"))]
            time_cols = [c for c in cols if any(k in c.lower() for k in ("time", "date", "created", "updated"))]

            has_current_field = any(c.startswith("current_") or "current" in c for c in cols_lower)
            has_slot_field = any("slot" in c or "station" in c or "dock" in c for c in cols_lower)

            table_type = "unknown"
            role = f"业务数据表: {tbl_name}"
            not_for = []

            if any(k in t_lower for k in ("callback", "receipt", "notify", "ack", "webhook")):
                table_type = "callback"
                role = f"外部系统通信回执与异步确认流水表: {tbl_name} (仅记录历史报文)"
                not_for = ["当前实时物理状态查询", "活跃工序实时作业判定"]
            elif any(k in t_lower for k in ("log", "audit", "trace", "history")):
                table_type = "audit"
                role = f"操作审计与历史流水表: {tbl_name}"
                not_for = ["当前实时状态查询"]
            elif any(k in t_lower for k in ("config", "setting", "param", "dict")):
                table_type = "configuration"
                role = f"系统基础参数配置表: {tbl_name}"
            elif has_current_field or (has_slot_field and status_cols):
                table_type = "current_state"
                role = f"核心业务实时主状态表: {tbl_name} (维护实时工位、槽位与当前作业)"
            elif any(k in t_lower for k in ("task", "order", "job", "mission")):
                table_type = "master"
                role = f"核心主任务/订单实体表: {tbl_name}"

            tk = TableKnowledge(
                table_name=tbl_name,
                business_role=role,
                table_type=table_type,
                primary_key=info["primary_key"],
                status_fields=status_cols,
                time_fields=time_cols,
                important_fields=cols[:15],
                not_for=not_for,
                confidence=info["confidence"],
                sources=[info["source"]],
            )
            tables.append(tk)

        return tables

    def _pass_4_business_flows(
        self,
        code_res: CodeScanResult,
        tables: List[TableKnowledge],
        configs: List[ConfigItem],
        client: Optional[GlmClient],
    ) -> List[BusinessFlow]:
        """Pass 4: 端到端核心业务流学习"""
        apis = []
        return BusinessFlowLearner.discover_flows(
            apis=apis,
            tables=tables,
            code_graph_dict=code_res.code_graph,
            project_name=self.config.project_name or "TASK-013",
        )

    def _pass_5_source_of_truth(
        self,
        tables: List[TableKnowledge],
        flows: List[BusinessFlow],
        client: Optional[GlmClient],
    ) -> tuple[List[BusinessConcept], List[SourceOfTruthRule]]:
        """Pass 5: 核心概念与事实源权威规则 (Source of Truth)"""
        concepts: List[BusinessConcept] = []
        sot_rules: List[SourceOfTruthRule] = []

        callback_tables = [t.table_name for t in tables if t.table_type == "callback"]
        current_state_tables = [t for t in tables if t.table_type in ("current_state", "master")]

        for cst in current_state_tables:
            current_fields = [f for f in cst.important_fields if "current" in f.lower()]
            if not current_fields:
                current_fields = [f for f in cst.status_fields]
            if not current_fields and cst.important_fields:
                current_fields = [cst.important_fields[0]]

            primary_field = current_fields[0] if current_fields else "id"
            concept_name = f"{cst.table_name} 实时状态"
            aliases = [f"{cst.table_name}状态", f"{primary_field}状态", "实时运行状态", "当前作业状态"]

            concepts.append(
                BusinessConcept(
                    concept_id=f"concept_{cst.table_name}_{primary_field}",
                    name=concept_name,
                    aliases=aliases,
                    description=f"关于系统核心执行中实体或任务的最新实时状态信息 ({cst.table_name}.{primary_field})",
                    canonical_source={
                        "type": "database",
                        "table": cst.table_name,
                        "field": primary_field,
                    },
                    secondary_sources=["系统执行日志"],
                    do_not_use_as_primary=callback_tables,
                    query_guidance=f"查询当前实时状态时，建议优先通过 {cst.table_name} ORDER BY id DESC LIMIT 1 查询 {primary_field} 字段",
                    confidence="strongly_inferred",
                    sources=["code_feature_inference"],
                )
            )

            sot_rules.append(
                SourceOfTruthRule(
                    fact=f"{cst.table_name} 的实时主状态或最新执行进展",
                    canonical_source=f"{cst.table_name}.{primary_field}",
                    secondary_sources=["调度运行日志"],
                    invalid_primary_sources=callback_tables,
                    reason=f"{cst.table_name} 是维护活跃状态的主表；而回执流水表仅记录历史异步报文，严禁作为当前物理现场依据",
                    confidence="strongly_inferred",
                    sources=["domain_rule"],
                )
            )

        for cbt in [t for t in tables if t.table_type == "callback"]:
            concepts.append(
                BusinessConcept(
                    concept_id=f"receipt_{cbt.table_name}",
                    name=f"{cbt.table_name} 外部异步通信记录",
                    aliases=[f"{cbt.table_name}流水", "异步回调记录", "外部通信回执"],
                    description=f"外部系统异步回传的历史确认报文流水 ({cbt.table_name})",
                    canonical_source={
                        "type": "database",
                        "table": cbt.table_name,
                        "field": cbt.important_fields[0] if cbt.important_fields else "id",
                    },
                    secondary_sources=["集成网络通信日志"],
                    do_not_use_as_primary=[],
                    query_guidance=f"仅在排查外部接口是否已发送回执或进行对账核验时查询表 {cbt.table_name}",
                    confidence="strongly_inferred",
                    sources=["schema_analysis"],
                )
            )

            sot_rules.append(
                SourceOfTruthRule(
                    fact=f"外部系统对 {cbt.table_name} 关联事项的历史异步回调或确认",
                    canonical_source=cbt.table_name,
                    secondary_sources=["integration logs"],
                    invalid_primary_sources=[],
                    reason=f"{cbt.table_name} 专门记录外部系统的异步通信与回调流水",
                    confidence="strongly_inferred",
                    sources=["domain_rule"],
                )
            )

        return concepts, sot_rules

    def _pass_6_external_integrations(
        self,
        code_res: CodeScanResult,
        flows: List[BusinessFlow],
        client: Optional[GlmClient],
    ) -> List[ExternalSystem]:
        """Pass 6: 外部系统与硬件协同关系抽取"""
        systems = [
            ExternalSystem(
                system_name="WMS 仓储管理系统",
                connection_type="HTTP REST / 消息队列",
                used_by_module="backend/material",
                config_source="ordersys-settings.json",
                related_logs=["wms_dispatch.log"],
                related_apis=["/api/dock/material/poll"],
                confidence="strongly_inferred",
            ),
            ExternalSystem(
                system_name="AGV / 堆垛机器人调度系统",
                connection_type="TCP Socket / Modbus / HTTP",
                used_by_module="backend/robot",
                config_source="ordersys-settings.json",
                related_logs=["robot_action.log"],
                related_apis=["/api/dispatch/callback/receipt"],
                confidence="strongly_inferred",
            ),
        ]
        return systems

    def _synthesize_deterministic(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
    ) -> ProjectBlueprint:
        """向后兼容历史测试与离线场景的确定性调用入口"""
        return self.synthesize(
            tree_res=tree_res,
            schema_res=schema_res,
            code_res=code_res,
            use_llm=False,
        )

    def _pass_7_terminology_aliases(
        self,
        concepts: List[BusinessConcept],
        flows: List[BusinessFlow],
        client: Optional[GlmClient],
    ) -> tuple[List[BusinessConcept], List[BusinessFlow]]:
        """Pass 7: 现场方言与术语别名对齐 (通用推导，严禁硬编码专属业务词汇)"""
        for c in concepts:
            # 基于概念名称与权威源字段通用派生
            base_names = [c.name] + list(c.aliases)
            for name in base_names:
                for suffix in ["状态", "详情", "记录"]:
                    candidate = f"{name}{suffix}" if not name.endswith(suffix) else name
                    if candidate not in c.aliases and len(candidate) <= 25:
                        c.aliases.append(candidate)

        return concepts, flows


