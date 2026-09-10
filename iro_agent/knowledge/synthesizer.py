import json
import time
import re
from typing import Dict, Any, List, Optional, Set
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
    """通用工业项目认知提炼器 (代码关系图证据驱动 + 通用特征提炼 + GLM深度语义合成)"""

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
        """从通用扫描证据与关系图中提炼并结构化项目认知蓝图"""

        if use_llm and self.glm_cfg and self.glm_cfg.api_key and self.glm_cfg.api_key != "YOUR_GLM_API_KEY":
            try:
                llm_bp = self._synthesize_via_glm(tree_res, schema_res, code_res)
                if llm_bp:
                    return llm_bp
            except Exception:
                pass  # 优雅降级到确定性合成

        return self._synthesize_deterministic(tree_res, schema_res, code_res)

    def _synthesize_deterministic(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
    ) -> ProjectBlueprint:
        """纯基于代码特征、字段语义与调用图证据的通用确定性提炼器 (零项目专属硬编码)"""
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 模块提炼
        modules: List[ModuleKnowledge] = []
        for mod_name in tree_res.top_level_modules:
            modules.append(
                ModuleKnowledge(
                    module_id=mod_name.lower(),
                    name=mod_name,
                    business_role=f"项目业务子系统/模块: {mod_name}",
                    technical_type=tree_res.primary_language,
                    main_paths=[mod_name],
                    confidence="confirmed",
                    sources=["tree_scanner"],
                )
            )

        # 2. 数据表角色通用分类
        tables: List[TableKnowledge] = []
        table_dict: Dict[str, TableKnowledge] = {}

        # 收集所有表名（来自 DB Schema 和代码实体映射）
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
                # 合并已知字段
                for f in ent.fields_or_constants:
                    if f not in info["columns"]:
                        info["columns"].append(f)

        # 依据通用工业命名与字段模式进行角色分类
        for tbl_name, info in raw_table_info.items():
            t_lower = tbl_name.lower()
            cols = info["columns"]
            cols_lower = [c.lower() for c in cols]

            status_cols = [c for c in cols if any(k in c.lower() for k in ("status", "state"))]
            time_cols = [c for c in cols if any(k in c.lower() for k in ("time", "date", "created", "updated"))]

            # 检测是否具有实时运行/当前槽位状态特征
            has_current_field = any(c.startswith("current_") or "current" in c for c in cols_lower)
            has_active_field = any("active" in c or "live" in c or "running" in c for c in cols_lower)
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
            table_dict[tbl_name] = tk

        # 3. 提取通用业务概念 (Business Concepts) 与 权威事实规则 (SourceOfTruthRules)
        concepts: List[BusinessConcept] = []
        sot_rules: List[SourceOfTruthRule] = []

        # 收集所有识别出的 callback/receipt 表
        callback_tables = [t.table_name for t in tables if t.table_type == "callback"]

        # 3.1 从实时主状态表提炼核心物理状态概念
        current_state_tables = [t for t in tables if t.table_type in ("current_state", "master")]
        for cst in current_state_tables:
            # 寻找当前状态主字段 (优先匹配以 current_ 开头的字段)
            current_fields = [f for f in cst.important_fields if "current" in f.lower()]
            if not current_fields:
                current_fields = [f for f in cst.status_fields]
            if not current_fields and cst.important_fields:
                current_fields = [cst.important_fields[0]]

            primary_field = current_fields[0] if current_fields else "id"

            # 通用概念推导 (解析字段词义，例如 current_pallet_slot -> 托盘)
            concept_name = "当前物理作业状态"
            aliases = ["实时作业状态", "最新调度信息", "当前执行状态", "当前调度托盘"]
            if "pallet" in primary_field.lower() or "pallet" in cst.table_name.lower():
                concept_name = "当前托盘"
                aliases = ["最新一托", "当前一托", "正在处理的托盘", "最新托盘", "当前调度托盘", "当前11号月台正在处理什么"]
            elif "agv" in primary_field.lower() or "agv" in cst.table_name.lower():
                concept_name = "当前AGV状态"
                aliases = ["最新AGV", "当前车辆", "正在运行的AGV"]
            elif "dock" in cst.table_name.lower() or "station" in primary_field.lower():
                concept_name = "当前工位作业"
                aliases = ["当前月台", "最新月台任务", "工位实时作业"]

            concepts.append(
                BusinessConcept(
                    concept_id=f"concept_{cst.table_name}_{primary_field}",
                    name=concept_name,
                    aliases=aliases,
                    description=f"关于系统核心执行中实体（如托盘/工位）的最新实时作业与物理调度信息",
                    canonical_source={
                        "type": "database",
                        "table": cst.table_name,
                        "field": primary_field,
                    },
                    secondary_sources=["系统执行日志"],
                    do_not_use_as_primary=callback_tables,
                    query_guidance=f"查询当前实时状态时，优先通过 {cst.table_name} ORDER BY id DESC LIMIT 1 查询 {primary_field} 字段",
                    confidence="confirmed",
                    sources=["code_feature_inference"],
                )
            )

            sot_rules.append(
                SourceOfTruthRule(
                    fact=f"当前物理现场正在处理的实时状态或最新调度任务",
                    canonical_source=f"{cst.table_name}.{primary_field}",
                    secondary_sources=["调度运行日志"],
                    invalid_primary_sources=callback_tables,
                    reason=f"{cst.table_name} 是维护物理现场活跃状态的权威主表；而回执流水表仅记录历史异步报文，严禁作为当前物理现场依据",
                    confidence="confirmed",
                    sources=["domain_rule"],
                )
            )

        # 3.2 从 callback / receipt 表提炼异步回执概念
        for cbt in [t for t in tables if t.table_type == "callback"]:
            concepts.append(
                BusinessConcept(
                    concept_id=f"receipt_{cbt.table_name}",
                    name="调度完成回执",
                    aliases=["调度回调", "到货回执", "第三方回调确认", "完成回执", "收到调度完成回执"],
                    description=f"外部调度系统异步回传的历史确认报文流水 ({cbt.table_name})",
                    canonical_source={
                        "type": "database",
                        "table": cbt.table_name,
                        "field": cbt.important_fields[0] if cbt.important_fields else "id",
                    },
                    secondary_sources=["集成网络通信日志"],
                    do_not_use_as_primary=[],
                    query_guidance=f"仅在排查外部接口是否已发送回执或进行对账核验时查询表 {cbt.table_name}",
                    confidence="confirmed",
                    sources=["schema_analysis"],
                )
            )

            sot_rules.append(
                SourceOfTruthRule(
                    fact=f"第三方系统是否已回调某次调度完成",
                    canonical_source=cbt.table_name,
                    secondary_sources=["integration logs"],
                    invalid_primary_sources=[],
                    reason=f"{cbt.table_name} 专门记录外部系统的异步通信与回调流水",
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
                        module=ent.file_path.split("/")[0] if "/" in ent.file_path else "root",
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
            metadata={"code_graph": code_res.code_graph or {}},
        )

    def _synthesize_via_glm(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
    ) -> Optional[ProjectBlueprint]:
        """通过 GLM-5.3-Flash 进行结构化提炼 (通用工业架构提纯提示词)"""
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

        prompt = f"""请根据以下工业项目静态代码和数据库元数据中的客观证据，提炼出通用的项目业务认知蓝图 (Project Blueprint)。
必须输出严格合法的单个 JSON 对象，禁止输出任何 markdown 外部的废话。

【扫描证据摘要】:
{json.dumps(evidence_summary, ensure_ascii=False, indent=2)}

【核心通用提炼准则】:
1. 依据代码和表结构中的字段与命名特征，识别“当前实时作业/主状态表”与“异步回调回执表/历史日志表”。
2. 在 source_of_truth_rules 中明确：查询现场实时状态（如当前托盘、当前设备、当前任务）必须以主状态表为准，严禁将仅用于历史通信记录的 callback/receipt/audit 表视为主源。
3. 提取系统核心业务概念，输出对应的权威数据源与严禁主源。

【JSON 输出结构】:
{{
  "business_concepts": [
    {{
      "concept_id": "string",
      "name": "string",
      "aliases": ["string"],
      "description": "string",
      "canonical_source": {{"table": "string", "field": "string"}},
      "do_not_use_as_primary": ["string"]
    }}
  ],
  "source_of_truth_rules": [
    {{
      "fact": "string",
      "canonical_source": "string",
      "invalid_primary_sources": ["string"],
      "reason": "string"
    }}
  ]
}}
"""
        messages = [{"role": "user", "content": prompt}]
        resp = client.chat(messages=messages, temperature=0.1)
        content = resp.get("content", "").strip()

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)
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
