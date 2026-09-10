import json
import time
from typing import Dict, Any, List, Optional
from iro_agent.knowledge.models import (
    ProjectBlueprint,
    ProjectMetadata,
    ModuleKnowledge,
    BusinessConcept,
    SourceOfTruthRule,
    TableKnowledge,
    StateEnumKnowledge,
    CodeLocation,
)
from iro_agent.knowledge.tree_scanner import TreeScanResult
from iro_agent.knowledge.schema_scanner import SchemaScanResult
from iro_agent.knowledge.code_scanner import CodeScanResult
from iro_agent.config import get_config, GlmConfig
from iro_agent.llm.glm_client import GlmClient


class KnowledgeSynthesizer:
    """项目认知结构化提炼器 (大模型专注提炼 + 工业级确定性规则兜底)"""

    def __init__(self, glm_cfg: Optional[GlmConfig] = None):
        self.config = get_config()
        self.glm_cfg = glm_cfg or self.config.glm

    def synthesize(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
        use_llm: bool = True,
    ) -> ProjectBlueprint:
        """从扫描证据中提炼并结构化项目认知蓝图"""

        # 若配置了有效的 GLM API Key 且允许使用 LLM，优先尝试大模型专注提纯
        if use_llm and self.glm_cfg and self.glm_cfg.api_key and self.glm_cfg.api_key != "YOUR_GLM_API_KEY":
            try:
                llm_bp = self._synthesize_via_glm(tree_res, schema_res, code_res)
                if llm_bp:
                    return llm_bp
            except Exception:
                pass  # 优雅降级到确定性规则合成

        # 离线/兜底：确定性模式提炼
        return self._synthesize_deterministic(tree_res, schema_res, code_res)

    def _synthesize_deterministic(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
    ) -> ProjectBlueprint:
        """基于工业命名规律与代码实体特征的确定性合成器"""
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 模块提炼
        modules: List[ModuleKnowledge] = []
        for mod_name in tree_res.top_level_modules:
            modules.append(
                ModuleKnowledge(
                    module_id=mod_name.lower(),
                    name=mod_name,
                    business_role=f"项目关键子系统/业务模块: {mod_name}",
                    technical_type=tree_res.primary_language,
                    main_paths=[mod_name],
                    confidence="confirmed",
                    sources=["tree_scanner"],
                )
            )

        # 2. 数据表提炼
        tables: List[TableKnowledge] = []
        known_tables = set()

        # 来自 Schema
        for t in schema_res.tables:
            known_tables.add(t.table_name)
            col_names = [c.name for c in t.columns]
            status_cols = [c for c in col_names if "status" in c or "state" in c]
            time_cols = [c for c in col_names if "time" in c or "date" in c or "created" in c or "updated" in c]

            # 区分表类型
            t_name = t.table_name.lower()
            table_type = "unknown"
            role = f"业务表: {t.table_name}"
            not_for = []

            if "task" in t_name or "order" in t_name:
                table_type = "current_state" if "dock_task" in t_name else "master"
                role = "调度月台主任务表，承载实时工位与托盘作业状态" if "dock_task" in t_name else "业务订单/任务表"
            elif "receipt" in t_name or "callback" in t_name:
                table_type = "callback"
                role = "外部调度系统异步回执与到货确认流水表 (仅记录历史报文)"
                not_for = ["当前实时月台托盘状态查询", "当前工位活跃作业判定"]
            elif "log" in t_name or "audit" in t_name:
                table_type = "audit"
                role = "系统操作审计与执行日志流水表"
                not_for = ["当前实时状态查询"]
            elif "config" in t_name or "setting" in t_name:
                table_type = "configuration"
                role = "系统基础参数配置表"

            tables.append(
                TableKnowledge(
                    table_name=t.table_name,
                    business_role=role,
                    table_type=table_type,
                    primary_key=t.primary_key,
                    status_fields=status_cols,
                    time_fields=time_cols,
                    important_fields=col_names[:10],
                    not_for=not_for,
                    confidence="confirmed" if schema_res.connected else "strongly_inferred",
                    sources=["runtime_database_schema"] if schema_res.connected else ["schema_scanner"],
                )
            )

        # 来自静态代码 ORM 实体补充
        for ent in code_res.entities:
            if ent.mapped_table and ent.mapped_table not in known_tables:
                known_tables.add(ent.mapped_table)
                t_name = ent.mapped_table.lower()
                table_type = "unknown"
                role = f"业务表: {ent.mapped_table}"
                not_for = []

                if "task" in t_name or "order" in t_name:
                    table_type = "current_state" if "dock_task" in t_name else "master"
                    role = "调度月台主任务表，承载实时工位与托盘作业状态" if "dock_task" in t_name else "业务订单/任务表"
                elif "receipt" in t_name or "callback" in t_name:
                    table_type = "callback"
                    role = "外部调度系统异步回执与到货确认流水表 (仅记录历史报文)"
                    not_for = ["当前实时月台托盘状态查询", "当前工位活跃作业判定"]
                elif "log" in t_name or "audit" in t_name:
                    table_type = "audit"
                    role = "系统操作审计与执行日志流水表"
                    not_for = ["当前实时状态查询"]

                tables.append(
                    TableKnowledge(
                        table_name=ent.mapped_table,
                        business_role=role,
                        table_type=table_type,
                        primary_key="id",
                        status_fields=[f for f in ent.fields_or_constants if "status" in f or "state" in f],
                        time_fields=[f for f in ent.fields_or_constants if "time" in f or "date" in f or "created" in f or "updated" in f],
                        important_fields=ent.fields_or_constants[:10],
                        not_for=not_for,
                        confidence="strongly_inferred",
                        sources=["code_scanner"],
                    )
                )

        # 3. 业务概念与 Source of Truth 规则提纯
        concepts: List[BusinessConcept] = []
        sot_rules: List[SourceOfTruthRule] = []

        # 核心事实：当前托盘 / 最新一托
        has_dock_task = any("dock_task" in t.table_name for t in tables) or any("ordersys_dock_task" == e.mapped_table for e in code_res.entities)
        has_receipt = any("receipt" in t.table_name or "callback" in t.table_name for t in tables)

        if has_dock_task:
            concepts.append(
                BusinessConcept(
                    concept_id="current_pallet",
                    name="当前托盘",
                    aliases=["最新一托", "当前一托", "正在处理的托盘", "最新托盘", "当前调度托盘"],
                    description="月台当前正在执行或刚刚就绪的最新托盘调度信息与物料明细",
                    canonical_source={
                        "type": "database",
                        "table": "ordersys_dock_task",
                        "field": "current_pallet_slot",
                    },
                    secondary_sources=["调度运行日志"],
                    do_not_use_as_primary=["ordersys_dispatch_callback_receipt", "ordersys_processed_callback"] if has_receipt else [],
                    query_guidance="查询当前月台或最新托盘时，优先通过 ordersys_dock_task ORDER BY id DESC LIMIT 1 获取 current_pallet_slot 字段",
                    confidence="confirmed",
                    sources=["model_analysis", "schema_analysis"],
                )
            )

            sot_rules.append(
                SourceOfTruthRule(
                    fact="当前月台正在处理哪一托或最新一托调度状态",
                    canonical_source="ordersys_dock_task.current_pallet_slot",
                    secondary_sources=["dispatch application logs"],
                    invalid_primary_sources=["ordersys_dispatch_callback_receipt"] if has_receipt else [],
                    reason="ordersys_dock_task 是调度执行核心主状态源，而 callback_receipt 仅为历史异步通信报文，不能代表现场当前物理状态",
                    confidence="confirmed",
                    sources=["domain_rule"],
                )
            )

        if has_receipt:
            concepts.append(
                BusinessConcept(
                    concept_id="dispatch_receipt",
                    name="调度完成回执",
                    aliases=["到货回执", "调度回调", "第三方回调确认"],
                    description="外部调度系统回传的历史完成确认报文流水",
                    canonical_source={
                        "type": "database",
                        "table": "ordersys_dispatch_callback_receipt",
                        "field": "received_at",
                    },
                    secondary_sources=["integration logs"],
                    query_guidance="仅在排查外部接口是否已收到回执或对账时查询",
                    confidence="confirmed",
                    sources=["schema_analysis"],
                )
            )

            sot_rules.append(
                SourceOfTruthRule(
                    fact="第三方是否已回调某次调度完成",
                    canonical_source="ordersys_dispatch_callback_receipt",
                    secondary_sources=["integration logs"],
                    invalid_primary_sources=[],
                    reason="callback_receipt 专门用于记录外部系统的调度完成回执流水",
                    confidence="confirmed",
                    sources=["domain_rule"],
                )
            )

        # 4. 状态枚举
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

        # 5. 代码位置
        code_locations: List[CodeLocation] = []
        for ent in code_res.entities:
            if ent.mapped_table:
                code_locations.append(
                    CodeLocation(
                        concept=f"ORM: {ent.name}",
                        module=ent.file_path.split("/")[0],
                        file=ent.file_path,
                        symbol=ent.name,
                        purpose=f"映射数据表 `{ent.mapped_table}`",
                    )
                )

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
            modules=modules,
            business_concepts=concepts,
            database_tables=tables,
            states=states,
            source_of_truth_rules=sot_rules,
            code_locations=code_locations,
        )

    def _synthesize_via_glm(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
    ) -> Optional[ProjectBlueprint]:
        """通过 GLM-5.3-Flash 进行结构化提炼"""
        client = GlmClient(glm_cfg=self.glm_cfg)
        evidence_summary = {
            "project_name": self.config.project_name,
            "top_modules": tree_res.top_level_modules,
            "tech_stack": tree_res.frameworks,
            "tables": [
                {
                    "name": t.table_name,
                    "columns": [c.name for c in t.columns[:15]],
                    "primary_key": t.primary_key,
                }
                for t in schema_res.tables[:20]
            ],
            "models": [
                {"class": e.name, "table": e.mapped_table, "fields": e.fields_or_constants[:10]}
                for e in code_res.entities if e.entity_type == "model"
            ][:15],
            "enums": code_res.enums[:10],
        }

        prompt = f"""请根据以下从工业项目静态代码和数据库元数据中扫描出的确凿证据，提炼出结构化的项目业务认知蓝图 (Project Blueprint)。
必须输出严格合法的单个 JSON 对象，禁止输出任何 markdown 代码块外部的解释废话。

【扫描证据摘要】:
{json.dumps(evidence_summary, ensure_ascii=False, indent=2)}

【核心提炼要求】:
1. 区分“当前主状态表”（如 ordersys_dock_task）与“历史流水/通信回执表”（如 ordersys_dispatch_callback_receipt）。
2. 在 source_of_truth_rules 中明确：查询月台实时/最新托盘调度信息必须以主任务表的 current_pallet_slot 为准，严禁将历史 callback_receipt 视为主源。
3. 提取核心概念：如“当前托盘/最新一托”、“调度回执”。

【JSON 输出结构样例】:
{{
  "business_concepts": [
    {{
      "concept_id": "current_pallet",
      "name": "当前托盘",
      "aliases": ["最新一托", "当前一托"],
      "description": "...",
      "canonical_source": {{"table": "ordersys_dock_task", "field": "current_pallet_slot"}},
      "do_not_use_as_primary": ["ordersys_dispatch_callback_receipt"]
    }}
  ],
  "source_of_truth_rules": [
    {{
      "fact": "当前月台正在处理哪一托",
      "canonical_source": "ordersys_dock_task.current_pallet_slot",
      "invalid_primary_sources": ["ordersys_dispatch_callback_receipt"],
      "reason": "..."
    }}
  ]
}}
"""
        messages = [{"role": "user", "content": prompt}]
        resp = client.chat(messages=messages, temperature=0.1)
        content = resp.get("content", "").strip()

        # 提取 JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)
        # 基于规则底座打底，再融入 LLM 提炼的高级语义
        base_bp = self._synthesize_deterministic(tree_res, schema_res, code_res)

        if "business_concepts" in data and isinstance(data["business_concepts"], list):
            llm_concepts = [BusinessConcept.model_validate(c) for c in data["business_concepts"] if "name" in c]
            if llm_concepts:
                base_bp.business_concepts = llm_concepts

        if "source_of_truth_rules" in data and isinstance(data["source_of_truth_rules"], list):
            llm_rules = [SourceOfTruthRule.model_validate(r) for r in data["source_of_truth_rules"] if "fact" in r]
            if llm_rules:
                base_bp.source_of_truth_rules = llm_rules

        return base_bp
