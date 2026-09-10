import json
import re
from typing import List, Tuple, Optional
from iro_agent.knowledge.models import ProjectBlueprint
from iro_agent.knowledge.schema_scanner import SchemaScanResult
from iro_agent.knowledge.code_scanner import CodeScanResult
from iro_agent.knowledge.code_graph import CodeRelationshipGraph


class BlueprintValidator:
    """项目认知蓝图合法性、证据链与安全性交叉校验器"""

    SENSITIVE_PATTERNS = [
        re.compile(r"password\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
        re.compile(r"api_key\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
        re.compile(r"secret\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    ]

    def validate(
        self,
        blueprint: ProjectBlueprint,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
    ) -> Tuple[ProjectBlueprint, List[str]]:
        """执行全要素交叉校验并返回修正后的蓝图与告警列表"""
        warnings: List[str] = []

        valid_tables = {t.table_name.lower() for t in schema_res.tables}
        for ent in code_res.entities:
            if ent.mapped_table:
                valid_tables.add(ent.mapped_table.lower())

        # 从代码关系图中提取所有引用的表
        graph = CodeRelationshipGraph.from_dict(code_res.code_graph) if code_res.code_graph else None
        if graph:
            for ent in graph.entities.values():
                if ent.entity_type == "table":
                    valid_tables.add(ent.name.lower())

        # 1. 校验 Source of Truth Rules
        sanitized_rules = []
        for r in blueprint.source_of_truth_rules:
            canon_tbl = r.canonical_source.split(".")[0].lower()
            if valid_tables and canon_tbl not in valid_tables:
                warnings.append(f"SoT 规则中的主表 '{canon_tbl}' 在已知 Schema 或代码实体中未发现，降级为 inferred")
                r.confidence = "inferred"

            # 校验 invalid_primary_sources
            if r.canonical_source in r.invalid_primary_sources:
                warnings.append(f"SoT 规则冲突: 权威源 '{r.canonical_source}' 包含在禁止主源列表中，已从禁止项移除")
                r.invalid_primary_sources = [s for s in r.invalid_primary_sources if s != r.canonical_source]

            sanitized_rules.append(r)
        blueprint.source_of_truth_rules = sanitized_rules

        # 2. 校验 Business Concepts
        for c in blueprint.business_concepts:
            cs = c.canonical_source
            if isinstance(cs, dict) and "table" in cs:
                tbl = cs["table"].lower()
                if valid_tables and tbl not in valid_tables:
                    warnings.append(f"概念 '{c.name}' 绑定的表 '{tbl}' 在已知环境中未直接探知")
                    c.confidence = "inferred"

        # 3. 敏感数据安全巡检
        raw_json = json.dumps(blueprint.model_dump(), ensure_ascii=False)
        for pat in self.SENSITIVE_PATTERNS:
            if pat.search(raw_json):
                warnings.append("检测到蓝图中可能存在未脱敏的凭据字符串，已触发安全关注")

        return blueprint, warnings
