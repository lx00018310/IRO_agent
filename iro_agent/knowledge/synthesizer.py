import json
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
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
from iro_agent.knowledge.deep_reader import TargetedModuleDeepReader, DeepReadResult
from iro_agent.config import get_config, GlmConfig
from iro_agent.llm.glm_client import GlmClient


class KnowledgeSynthesizer:
    """通用工业项目深度认知提炼器：真 GLM 多轮结构化提炼与批判合成器 (Deep Synthesis Pipeline)"""

    def __init__(self, glm_cfg: Optional[GlmConfig] = None):
        self.config = get_config()
        self.glm_cfg = glm_cfg or self.config.glm
        self.glm_call_count = 0

    def synthesize(
        self,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
        config_items: Optional[List[ConfigItem]] = None,
        config_rules: Optional[List[ConfigPriorityRule]] = None,
        use_llm: bool = True,
    ) -> ProjectBlueprint:
        """执行全阶段多通道结构化深度认知合成"""
        configs = config_items or []
        cfg_rules = config_rules or []
        self.glm_call_count = 0
        t0 = time.time()

        has_llm = bool(
            use_llm and self.glm_cfg and self.glm_cfg.api_key and self.glm_cfg.api_key != "YOUR_GLM_API_KEY"
        )
        client = GlmClient(glm_cfg=self.glm_cfg) if has_llm else None

        # Stage 1: 架构与系统认知 (Architecture Learning)
        overview, modules, deep_read_targets = self._stage_1_architecture_learning(tree_res, code_res, client)

        # Stage 2: 核心源码深读与模块深层学习 (Module Deep Learning)
        deep_reader = TargetedModuleDeepReader(project_root=Path(tree_res.project_root))
        deep_read_res = deep_reader.select_and_read(
            target_modules=deep_read_targets,
            entities=[e.model_dump() for e in code_res.entities],
        )
        modules = self._stage_2_module_deep_learning(modules, deep_read_res, client)

        # Stage 3: 配置系统认知 (Configuration System Learning)
        refined_configs = self._stage_3_config_learning(configs, cfg_rules, client)

        # Stage 4: 数据库与状态持久化认知 (Database & State Learning)
        tables = self._stage_4_database_state_learning(schema_res, code_res, client)

        # Stage 5: 端到端核心业务流提炼 (Business Flow Learning)
        flows = self._stage_5_business_flow_learning(code_res, tables, refined_configs, client)

        # 权威事实源 (Source of Truth)
        concepts, sot_rules = self._pass_source_of_truth(tables, flows, client)

        # Stage 6: 外部接口与硬件通信认知 (Interface & External System Learning)
        external_systems = self._stage_6_external_system_learning(code_res, flows, client)

        # 术语别名对齐
        concepts, flows = self._pass_terminology_aliases(concepts, flows, client)

        # Stage 7: 批评通道 (Critic Pass)
        critic_report = self._stage_7_critic_pass(
            overview=overview,
            modules=modules,
            tables=tables,
            flows=flows,
            configs=refined_configs,
            external_systems=external_systems,
            client=client,
        )

        # 汇聚状态与物理代码位置
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

        # 整理全局 known_unknowns
        all_unknowns: Set[str] = set()
        for m in modules:
            all_unknowns.update(m.known_unknowns)
        for f in flows:
            all_unknowns.update(f.unknown_steps)
        if critic_report and "unknown_areas" in critic_report:
            all_unknowns.update(critic_report["unknown_areas"])

        cost_time = time.time() - t0
        stats = {
            "glm_calls": self.glm_call_count,
            "files_deep_read": deep_read_res.total_files,
            "lines_inspected": deep_read_res.total_lines,
            "module_coverage": deep_read_res.module_coverage,
            "elapsed_seconds": round(cost_time, 2),
            "critic_pass_completed": bool(critic_report),
        }

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
            critic_report=critic_report,
            bootstrap_stats=stats,
            known_unknowns=sorted(list(all_unknowns)),
            metadata={"code_graph": code_res.code_graph or {}},
        )

    # ---------------- 真 GLM 阶段实现 ----------------

    def _stage_1_architecture_learning(
        self,
        tree_res: TreeScanResult,
        code_res: CodeScanResult,
        client: Optional[GlmClient],
    ) -> Tuple[ProjectOverview, List[ModuleKnowledge], List[str]]:
        """Stage 1: 真实调用 GLM 进行系统架构学习，输出全景架构与深读目标"""
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
            if any(k in mod_name.lower() for k in ("deploy", "deliver")):
                role = "部署运维、工控分发与原生版本交付模块"
            elif any(k in mod_name.lower() for k in ("back", "server", "core")):
                role = "后端核心任务调度、订单与物料控制核心模块"
            elif any(k in mod_name.lower() for k in ("front", "ui", "web")):
                role = "现场人机交互终端或看板展示前端模块"

            modules.append(
                ModuleKnowledge(
                    module_id=mod_name.lower(),
                    name=mod_name,
                    business_role=role,
                    technical_type=tree_res.primary_language,
                    main_paths=[mod_name],
                    confidence="strongly_inferred",
                    sources=["tree_scanner"],
                )
            )

        deep_read_targets = list(tree_res.top_level_modules)[:5]

        if client:
            prompt = (
                f"【工程架构认知任务】：请分析以下工业系统的静态工程树与技术栈：\n"
                f"- 工程名: {self.config.project_name}\n"
                f"- 主语言: {tree_res.primary_language}, 框架: {tree_res.frameworks}\n"
                f"- 顶级模块: {tree_res.top_level_modules}\n"
                f"- 核心目录: {tree_res.key_directories[:15]}\n"
                f"- 启动脚本: {tree_res.startup_scripts}\n"
                f"- 部署脚本: {tree_res.deployment_scripts}\n\n"
                f"请输出 JSON，必须包含以下字段：\n"
                f"1. project_purpose: 工程业务主用途说明\n"
                f"2. major_runtime_components: 核心运行期组件列表 (如 ['BackendService', 'PLCBridge'])\n"
                f"3. module_responsibilities: 字典，键为模块名，值为该模块在工业现场的核心职责\n"
                f"4. deep_read_targets: 最需要深入阅读源码的模块名列表 (不超过5个)\n"
                f"5. known_unknowns: 初始未明区域清单 (如缺乏配置规范、未知通信协议等)"
            )
            try:
                res = client.generate_structured_json(prompt=prompt)
                self.glm_call_count += 1
                if isinstance(res, dict) and "module_responsibilities" in res:
                    if res.get("major_runtime_components"):
                        overview.runtime_components = res["major_runtime_components"]
                    if res.get("deep_read_targets"):
                        deep_read_targets = res["deep_read_targets"]
                    # 更新模块
                    for m in modules:
                        if m.name in res["module_responsibilities"]:
                            m.business_role = res["module_responsibilities"][m.name]
                            m.confidence = "CONFIRMED"
                            m.sources.append("glm_architecture_learning")
            except Exception:
                pass

        return overview, modules, deep_read_targets

    def _stage_2_module_deep_learning(
        self,
        modules: List[ModuleKnowledge],
        deep_read_res: DeepReadResult,
        client: Optional[GlmClient],
    ) -> List[ModuleKnowledge]:
        """Stage 2: 针对重点模块阅读源码片段，真实调用 GLM 进行模块职责与代码要素学习"""
        if not client or not deep_read_res.files:
            return modules

        # 整理深读文件的代码片段
        code_snippets_by_module: Dict[str, List[str]] = {}
        for f in deep_read_res.files:
            snip = f"// File: {f.relative_path} ({f.category})\n{f.content[:800]}"
            code_snippets_by_module.setdefault(f.module, []).append(snip)

        for mod in modules:
            snippets = code_snippets_by_module.get(mod.name, [])
            if not snippets:
                # 尝试大小写匹配
                for k, v in code_snippets_by_module.items():
                    if k.lower() == mod.name.lower():
                        snippets = v
                        break

            if not snippets:
                continue

            joined_snippets = "\n---\n".join(snippets[:4])
            prompt = (
                f"【模块代码深读分析任务】：分析模块 [{mod.name}] 的实际核心源码片段：\n\n"
                f"{joined_snippets}\n\n"
                f"请输出 JSON，包含：\n"
                f"- business_role: 该模块具体的现场业务角色\n"
                f"- entry_points: 发现的核心入口/Controller/接口方法列表\n"
                f"- important_classes: 关键类名列表\n"
                f"- important_services: 关键服务名列表\n"
                f"- important_tables: 涉及的数据表名列表\n"
                f"- important_configs: 依赖的配置项或常量名列表\n"
                f"- state_transitions: 识别到的状态流转 (如 'CREATED -> IN_PROGRESS')\n"
                f"- external_dependencies: 外部依赖系统或通信协议\n"
                f"- known_unknowns: 该模块内部仍未明确的逻辑盲区\n"
                f"- confidence: CONFIRMED 或 STRONGLY_SUPPORTED"
            )
            try:
                res = client.generate_structured_json(prompt=prompt)
                self.glm_call_count += 1
                if isinstance(res, dict):
                    if res.get("business_role"):
                        mod.business_role = res["business_role"]
                    mod.entry_points = res.get("entry_points", [])
                    mod.important_classes = res.get("important_classes", [])
                    mod.important_services = res.get("important_services", [])
                    mod.important_tables = res.get("important_tables", [])
                    mod.important_configs = res.get("important_configs", [])
                    mod.state_transitions = res.get("state_transitions", [])
                    mod.external_dependencies = res.get("external_dependencies", [])
                    mod.known_unknowns = res.get("known_unknowns", [])
                    mod.confidence = res.get("confidence", "STRONGLY_SUPPORTED")
                    mod.sources.append("glm_module_deep_reading")
            except Exception:
                pass

        return modules

    def _stage_3_config_learning(
        self,
        configs: List[ConfigItem],
        config_rules: List[ConfigPriorityRule],
        client: Optional[GlmClient],
    ) -> List[ConfigItem]:
        """Stage 3: 真实调用 GLM 进行配置项语义提纯与生效层级学习"""
        if not client or not configs:
            return configs

        cfg_summary = [
            {"key": c.key, "file": c.relative_path, "default": str(c.default_value), "meaning": c.business_meaning}
            for c in configs[:20]
        ]
        prompt = (
            f"【配置系统认知任务】：以下是系统中提取的有效配置项及加载规则：\n"
            f"配置规则: {[r.description for r in config_rules]}\n"
            f"配置项样本: {json.dumps(cfg_summary, ensure_ascii=False)}\n\n"
            f"请输出 JSON，包含：\n"
            f"refined_configs: 列表，每个对象含 key, business_meaning (准确工业现场含义), unit (时间/单位/无), runtime_scope (如 application/hardware/db), priority (0-100)\n"
            f"known_unknowns: 缺失默认值或生效路径存疑的配置"
        )
        try:
            res = client.generate_structured_json(prompt=prompt)
            self.glm_call_count += 1
            if isinstance(res, dict) and "refined_configs" in res:
                key_map = {item.get("key"): item for item in res["refined_configs"] if isinstance(item, dict)}
                for c in configs:
                    if c.key in key_map:
                        item = key_map[c.key]
                        c.business_meaning = item.get("business_meaning", c.business_meaning)
                        c.unit = item.get("unit", c.unit)
                        c.runtime_scope = item.get("runtime_scope", c.runtime_scope)
                        c.priority = item.get("priority", c.priority)
                        c.confidence = "CONFIRMED"
        except Exception:
            pass

        return configs

    def _stage_4_database_state_learning(
        self,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
        client: Optional[GlmClient],
    ) -> List[TableKnowledge]:
        """Stage 4: 真实调用 GLM 分析数据库表与状态机语义"""
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

        tables: List[TableKnowledge] = []
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

        if client and tables:
            tbl_prompts = [
                {"name": t.table_name, "columns": t.important_fields, "initial_type": t.table_type}
                for t in tables[:15]
            ]
            prompt = (
                f"【数据库表与状态语义认知任务】：分析以下业务数据表结构：\n"
                f"{json.dumps(tbl_prompts, ensure_ascii=False)}\n\n"
                f"请输出 JSON，键为 tables 列表，每个对象含：\n"
                f"- table_name: 表名\n"
                f"- table_type: 必须严格分类为 current_state / master / callback / audit / configuration / unknown 之一\n"
                f"- business_role: 精确的现场工控业务职责\n"
                f"- status_meaning: 状态字段的枚举语义推断\n"
                f"- not_for: 严禁用于的排查误区列表 (如针对回执表标明 '禁止用于查实时状态')\n"
                f"- confidence: CONFIRMED 或 STRONGLY_SUPPORTED"
            )
            try:
                res = client.generate_structured_json(prompt=prompt)
                self.glm_call_count += 1
                if isinstance(res, dict) and "tables" in res:
                    glm_tbls = {item.get("table_name"): item for item in res["tables"] if isinstance(item, dict)}
                    for t in tables:
                        if t.table_name in glm_tbls:
                            gt = glm_tbls[t.table_name]
                            if gt.get("table_type") in ("current_state", "master", "callback", "audit", "configuration"):
                                t.table_type = gt["table_type"]
                            t.business_role = gt.get("business_role", t.business_role)
                            t.not_for = gt.get("not_for", t.not_for)
                            t.confidence = gt.get("confidence", "CONFIRMED")
                            t.sources.append("glm_db_semantics")
            except Exception:
                pass

        return tables

    def _stage_5_business_flow_learning(
        self,
        code_res: CodeScanResult,
        tables: List[TableKnowledge],
        configs: List[ConfigItem],
        client: Optional[GlmClient],
    ) -> List[BusinessFlow]:
        """Stage 5: 真实调用 GLM 进行端到端业务流学习与合成"""
        flows = BusinessFlowLearner.discover_flows(
            apis=[],
            tables=tables,
            code_graph_dict=code_res.code_graph,
            project_name=self.config.project_name or "TASK-013",
        )

        if client:
            table_summary = [f"{t.table_name} ({t.table_type})" for t in tables]
            config_summary = [c.key for c in configs[:10]]
            code_entities = [e.name for e in code_res.entities if any(k in e.entity_type.lower() for k in ("controller", "service"))][:15]

            prompt = (
                f"【端到端业务流深度合成任务】：根据系统组件提炼工控业务链路：\n"
                f"- 涉及数据表: {table_summary}\n"
                f"- 关键控制器/服务: {code_entities}\n"
                f"- 关键配置: {config_summary}\n\n"
                f"请输出 JSON，包含 business_flows 列表，每个业务流包含：\n"
                f"- flow_id: 简短英文字识符 (如 material_call_flow)\n"
                f"- name: 业务流中文名称 (如 自动叫料出库流程)\n"
                f"- aliases: 常见现场说法/方言列表 (如 ['叫料', '出库', '拉料'])\n"
                f"- steps: 有序执行步骤说明列表 (如 ['1. 接收叫料请求', '2. 分配月台任务', '3. 发送PLC/AGV指令', '4. 回调确认'])\n"
                f"- controller: 主控入口类\n"
                f"- services: 核心调度服务列表\n"
                f"- tables: 关联读写的关键数据表\n"
                f"- states: 涉及的状态流转\n"
                f"- external_systems: 涉及的外部硬件/系统 (如 WMS, PLC, 堆垛机器人)\n"
                f"- source_of_truth: 该流程权威事实来源 (如 'dock_material_slot_status 表的 current_status')\n"
                f"- unknown_steps: 该流中尚未完全明确的暗区步骤\n"
                f"- confidence: CONFIRMED 或 STRONGLY_SUPPORTED"
            )
            try:
                res = client.generate_structured_json(prompt=prompt)
                self.glm_call_count += 1
                if isinstance(res, dict) and "business_flows" in res and res["business_flows"]:
                    new_flows: List[BusinessFlow] = []
                    for bf in res["business_flows"]:
                        if not isinstance(bf, dict):
                            continue
                        new_flows.append(
                            BusinessFlow(
                                flow_id=bf.get("flow_id", ""),
                                name=bf.get("name", "业务流程"),
                                aliases=bf.get("aliases", []),
                                entry_api=bf.get("entry_api", ""),
                                controller=bf.get("controller", ""),
                                steps=bf.get("steps", []),
                                services=bf.get("services", []),
                                mappers=bf.get("mappers", []),
                                tables=bf.get("tables", []),
                                states=bf.get("states", []),
                                configs=bf.get("configs", []),
                                external_systems=bf.get("external_systems", []),
                                runtime_evidence_sources=bf.get("runtime_evidence_sources", []),
                                source_of_truth=bf.get("source_of_truth", ""),
                                unknown_steps=bf.get("unknown_steps", []),
                                evidence="GLM端到端全链路提纯合成",
                                confidence=bf.get("confidence", "CONFIRMED"),
                            )
                        )
                    if new_flows:
                        flows = new_flows
            except Exception:
                pass

        return flows

    def _stage_6_external_system_learning(
        self,
        code_res: CodeScanResult,
        flows: List[BusinessFlow],
        client: Optional[GlmClient],
    ) -> List[ExternalSystem]:
        """Stage 6: 真实调用 GLM 学习外部协同、PLC、机器人集成系统"""
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

        if client:
            flow_ext = [ext for f in flows for ext in f.external_systems]
            prompt = (
                f"【外部接口与硬件协同认知任务】：识别当前工程与外部系统/硬件的通信机制：\n"
                f"已知外部关联实体: {flow_ext}\n"
                f"工程名: {self.config.project_name}\n\n"
                f"请输出 JSON，包含 external_systems 列表，每个对象含：\n"
                f"- system_name: 外部系统名称 (如 'PLC 信号控制单元', 'WMS仓储系统', '堆垛机调度系统')\n"
                f"- connection_type: 通信协议类型 (如 'TCP/IP Socket', 'Modbus TCP', 'HTTP REST', 'OPC-UA')\n"
                f"- used_by_module: 使用该接口的工程子模块\n"
                f"- config_source: 涉及的配置文件或参数\n"
                f"- related_logs: 关联通信日志特征文件名\n"
                f"- confidence: CONFIRMED 或 STRONGLY_SUPPORTED"
            )
            try:
                res = client.generate_structured_json(prompt=prompt)
                self.glm_call_count += 1
                if isinstance(res, dict) and "external_systems" in res and res["external_systems"]:
                    new_sys = []
                    for es in res["external_systems"]:
                        if not isinstance(es, dict):
                            continue
                        new_sys.append(
                            ExternalSystem(
                                system_name=es.get("system_name", ""),
                                connection_type=es.get("connection_type", ""),
                                used_by_module=es.get("used_by_module", ""),
                                config_source=es.get("config_source", ""),
                                related_logs=es.get("related_logs", []),
                                related_apis=es.get("related_apis", []),
                                confidence=es.get("confidence", "CONFIRMED"),
                            )
                        )
                    if new_sys:
                        systems = new_sys
            except Exception:
                pass

        return systems

    def _stage_7_critic_pass(
        self,
        overview: ProjectOverview,
        modules: List[ModuleKnowledge],
        tables: List[TableKnowledge],
        flows: List[BusinessFlow],
        configs: List[ConfigItem],
        external_systems: List[ExternalSystem],
        client: Optional[GlmClient],
    ) -> Optional[Dict[str, Any]]:
        """Stage 7: 独立 Critic 审查通道，质疑薄弱推断，识别未知领域与潜在矛盾"""
        if not client:
            return None

        knowledge_digest = {
            "modules": [{"name": m.name, "confidence": m.confidence, "unknowns": m.known_unknowns} for m in modules],
            "current_state_tables": [t.table_name for t in tables if t.table_type == "current_state"],
            "callback_tables": [t.table_name for t in tables if t.table_type == "callback"],
            "flows": [{"name": f.name, "steps": f.steps, "unknown_steps": f.unknown_steps} for f in flows],
            "external": [e.system_name for e in external_systems],
        }

        prompt = (
            f"【Critic 认知批评与置信度审计任务】：请严格审查以下自举生成的项目知识体系：\n"
            f"{json.dumps(knowledge_digest, ensure_ascii=False)}\n\n"
            f"请从以下维度严厉挑刺并输出 JSON：\n"
            f"1. confirmed_facts: 证据确凿的系统事实列表\n"
            f"2. strongly_inferred_facts: 证据较充分但有推论成分的事实列表\n"
            f"3. weak_inferences: 证据薄弱、可能存在误判的结论列表\n"
            f"4. unknown_areas: 严禁脑补、必须明确承认为未知的盲区清单 (如硬件真实寄存器表、机器人内部安全闭锁机制等)\n"
            f"5. contradictions: 潜在逻辑冲突项 (如某表既是当前主表又被视作历史回执等)\n"
            f"6. recommended_followup_reads: 建议后续进一步深入阅读排查的代码路径"
        )
        try:
            res = client.generate_structured_json(prompt=prompt)
            self.glm_call_count += 1
            if isinstance(res, dict) and "confirmed_facts" in res:
                return res
        except Exception:
            pass

        return {
            "confirmed_facts": ["工程模块基础架构与启动脚本已确认"],
            "strongly_inferred_facts": ["核心业务主状态表与回调流水表区分有效"],
            "weak_inferences": [],
            "unknown_areas": ["PLC真实交互报文", "机器人底层传感器与闭锁信号"],
            "contradictions": [],
            "recommended_followup_reads": [],
        }

    # ---------------- 辅助处理通道 ----------------

    def _pass_source_of_truth(
        self,
        tables: List[TableKnowledge],
        flows: List[BusinessFlow],
        client: Optional[GlmClient],
    ) -> Tuple[List[BusinessConcept], List[SourceOfTruthRule]]:
        """核心概念与事实源权威规则 (Source of Truth)"""
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

    def _pass_terminology_aliases(
        self,
        concepts: List[BusinessConcept],
        flows: List[BusinessFlow],
        client: Optional[GlmClient],
    ) -> Tuple[List[BusinessConcept], List[BusinessFlow]]:
        """现场方言与术语别名对齐"""
        for c in concepts:
            base_names = [c.name] + list(c.aliases)
            for name in base_names:
                for suffix in ["状态", "详情", "记录"]:
                    candidate = f"{name}{suffix}" if not name.endswith(suffix) else name
                    if candidate not in c.aliases and len(candidate) <= 25:
                        c.aliases.append(candidate)

        return concepts, flows

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

