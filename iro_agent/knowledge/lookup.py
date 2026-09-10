import re
from typing import Dict, Any, List, Optional
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.knowledge.models import BusinessConcept, TableKnowledge, SourceOfTruthRule


class ProjectLookupEngine:
    """项目认知检索与业务对齐引擎 (Project Lookup Engine)"""

    def __init__(self, store: Optional[ProjectKnowledgeStore] = None):
        self.store = store or ProjectKnowledgeStore()

    def lookup(self, query: str) -> Dict[str, Any]:
        """依据自然语言业务提问，提取权威事实源与对应表结构指引，严控在 5~15 条高价值事实"""
        blueprint = self.store.load_blueprint()
        if not blueprint:
            return {
                "status": "NOT_BOOTSTRAPPED",
                "message": "尚未建立当前项目的持久化业务蓝图，请先运行 iro init 初始化。",
                "concepts": [],
                "rules": [],
                "tables": [],
                "warnings": [],
            }

        q_raw = query.strip()
        tokens = [t.lower() for t in re.split(r"[\s,，、_；;]+", q_raw) if len(t) >= 1]

        matched_concepts: List[Dict[str, Any]] = []
        matched_rules: List[Dict[str, Any]] = []
        matched_tables: List[Dict[str, Any]] = []
        warnings: List[str] = []

        # 提取用于中文匹配的 2-gram 词元
        bigrams = set()
        if len(q_raw) >= 2:
            for i in range(len(q_raw) - 1):
                bigrams.add(q_raw[i:i+2].lower())

        # 1. 匹配业务概念 (Business Concepts) - 支持精确匹配与消歧打分
        scored_concepts = []
        for c in blueprint.business_concepts:
            all_names = [c.name.lower()] + [a.lower() for a in c.aliases]
            score = 0
            # 完整别名或全名在提问中直接出现 -> 最高分
            for name in all_names:
                if name in q_raw.lower():
                    score = max(score, 100 + len(name))
            # 若无完整匹配，检查核心关键词是否出现
            if score == 0:
                # 概念的核心特征词需满足至少 3 字或多个 bigram 命中
                matched_bg = [bg for bg in bigrams if bg in c.name.lower() or any(bg in a.lower() for a in c.aliases)]
                # 排除像"调度"这类系统级超宽泛词导致的单点误触发
                meaningful_bg = [bg for bg in matched_bg if bg not in ("系统", "查询", "信息", "调度")]
                if meaningful_bg:
                    score = len(meaningful_bg) * 10

            if score > 0:
                scored_concepts.append((score, c))

        # 按匹配度从高到低排序
        scored_concepts.sort(key=lambda x: x[0], reverse=True)

        # 收集最高置信度概念明确禁用的表（例如当前托盘禁用 ordersys_dispatch_callback_receipt）
        forbidden_tables = set()
        if scored_concepts:
            top_concept = scored_concepts[0][1]
            for bad_tbl in top_concept.do_not_use_as_primary:
                forbidden_tables.add(bad_tbl.lower())

        matched_concept_objs = []
        for score, c in scored_concepts:
            cs = c.canonical_source
            c_tbl = cs.get("table", "").lower() if isinstance(cs, dict) else ""
            # 若该概念依赖的表被最高优先级概念明确禁用，且当前概念不是绝对显式命中（score < 100），则果断消歧过滤
            if c_tbl and c_tbl in forbidden_tables and score < 100:
                continue

            matched_concept_objs.append(c)
            matched_concepts.append({
                "concept": c.name,
                "canonical_source": c.canonical_source,
                "description": c.description,
                "query_guidance": c.query_guidance,
                "confidence": c.confidence,
            })
            if c.do_not_use_as_primary:
                for bad in c.do_not_use_as_primary:
                    warn_msg = f"【严禁误用】'{c.name}' 的主数据源非 '{bad}'！严禁将其作为主要状态依据。"
                    if warn_msg not in warnings:
                        warnings.append(warn_msg)

        # 收集概念命中的权威表名
        concept_tables = set()
        for c in matched_concept_objs:
            if isinstance(c.canonical_source, dict) and "table" in c.canonical_source:
                concept_tables.add(c.canonical_source["table"].lower())

        # 2. 匹配权威事实规则 (Source of Truth Rules)
        for r in blueprint.source_of_truth_rules:
            fact_lower = r.fact.lower()
            canon_lower = r.canonical_source.lower()
            # 条件A: 事实描述包含搜索子词或直接包含提问关键词
            text_hit = any(term in fact_lower for term in bigrams if len(term) >= 2) or fact_lower in q_raw.lower()
            # 条件B: 规则涉及已命中概念的权威表
            table_hit = any(tbl in canon_lower for tbl in concept_tables)

            if text_hit or table_hit:
                matched_rules.append({
                    "fact": r.fact,
                    "canonical_source": r.canonical_source,
                    "secondary_sources": r.secondary_sources,
                    "invalid_primary_sources": r.invalid_primary_sources,
                    "reason": r.reason,
                })
                for inv in r.invalid_primary_sources:
                    w = f"【排查避坑】事实 '{r.fact}' 严禁以 '{inv}' 为准，原因为: {r.reason}"
                    if w not in warnings:
                        warnings.append(w)

        # 3. 匹配核心业务表 (Database Tables)
        # 优先加入 matched_concepts 和 matched_rules 中涉及的表
        involved_table_names = set()
        for c in matched_concepts:
            cs = c.get("canonical_source")
            if isinstance(cs, dict) and "table" in cs:
                involved_table_names.add(cs["table"])
        for r in matched_rules:
            c_src = r.get("canonical_source", "")
            table_name = c_src.split(".")[0]
            if table_name:
                involved_table_names.add(table_name)

        for t in blueprint.database_tables:
            t_name = t.table_name.lower()
            t_role = t.business_role.lower()
            is_hit = (
                t.table_name in involved_table_names
                or t_name in q_raw.lower()
                or any(tok in t_role for tok in tokens if len(tok) >= 2)
            )
            if is_hit:
                matched_tables.append({
                    "table_name": t.table_name,
                    "business_role": t.business_role,
                    "table_type": t.table_type,
                    "primary_key": t.primary_key,
                    "status_fields": t.status_fields,
                    "time_fields": t.time_fields,
                    "important_fields": t.important_fields,
                    "not_for": t.not_for,
                })
                if t.not_for:
                    for nf in t.not_for:
                        w = f"【表适用性】表 '{t.table_name}' 不适用于: {nf}"
                        if w not in warnings:
                            warnings.append(w)

        return {
            "status": "SUCCESS",
            "project_id": blueprint.project.project_id,
            "concepts": matched_concepts[:5],
            "rules": matched_rules[:5],
            "tables": matched_tables[:5],
            "warnings": warnings[:5],
        }
