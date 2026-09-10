import os
import json
import time
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from iro_agent.config import get_config
from iro_agent.knowledge.models import (
    ProjectBlueprint,
    BusinessConcept,
    TableKnowledge,
    SourceOfTruthRule,
    ModuleKnowledge,
)


class ProjectKnowledgeStore:
    """项目认知蓝图存储与检索管理器 (分离于 IncidentStore 与对话记忆)"""

    def __init__(self, base_dir: Optional[Path] = None):
        self.config = get_config()
        # 优先以项目根目录或运行根目录下的 .iro_agent 为存储目录
        root = base_dir or Path(self.config.project_root) if Path(self.config.project_root).exists() else Path.cwd()
        self.store_dir = root / ".iro_agent"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.blueprint_path = self.store_dir / "project_blueprint.json"
        self.markdown_path = self.store_dir / "project_blueprint.md"
        self.override_path = self.store_dir / "project_knowledge_override.json"
        self.history_dir = self.store_dir / "project_blueprint.history"
        self._cached_blueprint: Optional[ProjectBlueprint] = None

    def exists(self) -> bool:
        return self.blueprint_path.exists()

    def load_blueprint(self, reload: bool = False) -> Optional[ProjectBlueprint]:
        """加载已持久化的项目蓝图，并自动合并手动覆盖规则"""
        if self._cached_blueprint and not reload:
            return self._cached_blueprint

        if not self.blueprint_path.exists():
            return None

        try:
            with open(self.blueprint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            blueprint = ProjectBlueprint.model_validate(data)
            # 应用手工规则覆盖
            blueprint = self.apply_manual_overrides(blueprint)
            self._cached_blueprint = blueprint
            return blueprint
        except Exception as e:
            # 记录异常或回退
            return None

    def backup_blueprint(self) -> Optional[Path]:
        """在更新前将当前蓝图备份到历史目录"""
        if not self.blueprint_path.exists():
            return None
        self.history_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_file = self.history_dir / f"project_blueprint_{timestamp}.json"
        shutil.copy2(self.blueprint_path, backup_file)
        return backup_file

    def save_blueprint(self, blueprint: ProjectBlueprint, export_markdown: bool = True) -> None:
        """持久化项目蓝图为 JSON 并可读导出为 Markdown"""
        self.backup_blueprint()
        self.store_dir.mkdir(parents=True, exist_ok=True)

        # 保存 JSON
        with open(self.blueprint_path, "w", encoding="utf-8") as f:
            json.dump(blueprint.model_dump(), f, ensure_ascii=False, indent=2)

        self._cached_blueprint = blueprint

        # 导出人类可读 Markdown
        if export_markdown:
            self._export_markdown(blueprint)

    def apply_manual_overrides(self, blueprint: ProjectBlueprint) -> ProjectBlueprint:
        """如果存在人工覆盖文件，执行最高优先级覆盖"""
        if not self.override_path.exists():
            return blueprint

        try:
            with open(self.override_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)

            # 覆盖 Source of Truth 规则
            if "source_of_truth_rules" in overrides:
                override_rules = [SourceOfTruthRule.model_validate(r) for r in overrides["source_of_truth_rules"]]
                # 按 fact 覆盖已有的或插入
                override_facts = {r.fact: r for r in override_rules}
                new_rules = []
                for r in blueprint.source_of_truth_rules:
                    if r.fact in override_facts:
                        new_rules.append(override_facts.pop(r.fact))
                    else:
                        new_rules.append(r)
                new_rules.extend(override_facts.values())
                blueprint.source_of_truth_rules = new_rules

            # 覆盖 Business Concepts
            if "business_concepts" in overrides:
                override_concepts = [BusinessConcept.model_validate(c) for c in overrides["business_concepts"]]
                override_names = {c.name: c for c in override_concepts}
                new_concepts = []
                for c in blueprint.business_concepts:
                    if c.name in override_names:
                        new_concepts.append(override_names.pop(c.name))
                    else:
                        new_concepts.append(c)
                new_concepts.extend(override_names.values())
                blueprint.business_concepts = new_concepts

        except Exception:
            pass

        return blueprint

    def _export_markdown(self, bp: ProjectBlueprint) -> None:
        """生成结构化可读 Markdown 蓝图"""
        lines = [
            f"# 项目架构与业务知识蓝图 — {bp.project.project_name}",
            f"- **项目标识**: `{bp.project.project_id}`",
            f"- **生成时间**: `{bp.project.generated_at}`",
            f"- **版本**: `{bp.project.blueprint_version}`",
            f"- **源码根路径**: `{bp.project.source_root}`",
            "",
            "## 1. 核心事实源规则 (Source of Truth Rules)",
            "| 业务事实 | 权威数据源 (Canonical) | 备选源 | 严禁作为主源 (Invalid Primary) | 依据说明 |",
            "|---|---|---|---|---|",
        ]
        for r in bp.source_of_truth_rules:
            sec = ", ".join(r.secondary_sources) or "无"
            inv = ", ".join(r.invalid_primary_sources) or "无"
            lines.append(f"| {r.fact} | `{r.canonical_source}` | {sec} | **{inv}** | {r.reason} |")

        lines.extend([
            "",
            "## 2. 核心业务概念定义 (Business Concepts)",
        ])
        for c in bp.business_concepts:
            aliases = " / ".join(c.aliases) if c.aliases else "无"
            lines.append(f"### {c.name} (别名: {aliases})")
            lines.append(f"- **描述**: {c.description}")
            lines.append(f"- **权威数据源**: `{json.dumps(c.canonical_source, ensure_ascii=False)}`")
            if c.do_not_use_as_primary:
                lines.append(f"- **严禁作为主源**: {', '.join(c.do_not_use_as_primary)}")
            if c.query_guidance:
                lines.append(f"- **查询指引**: {c.query_guidance}")
            lines.append("")

        lines.extend([
            "## 3. 核心业务数据表 (Database Tables)",
            "| 表名 | 业务角色 | 表类型 | 主键 | 核心状态/标识字段 | 时间字段 |",
            "|---|---|---|---|---|---|",
        ])
        for t in bp.database_tables:
            status = ", ".join(t.status_fields) or "无"
            time_f = ", ".join(t.time_fields) or "无"
            lines.append(f"| `{t.table_name}` | {t.business_role} | `{t.table_type}` | `{t.primary_key}` | {status} | {time_f} |")

        lines.extend([
            "",
            "## 4. 关键系统模块 (Modules)",
            "| 模块名 | 业务定位 | 技术类型 | 主要路径 |",
            "|---|---|---|---|",
        ])
        for m in bp.modules:
            paths = "<br>".join(m.main_paths)
            lines.append(f"| {m.name} | {m.business_role} | `{m.technical_type}` | `{paths}` |")

        with open(self.markdown_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def get_concept(self, query: str) -> Optional[BusinessConcept]:
        bp = self.load_blueprint()
        if not bp:
            return None
        q = query.lower()
        for c in bp.business_concepts:
            if c.name.lower() in q or any(alias.lower() in q for alias in c.aliases):
                return c
        return None

    def get_table(self, table_name: str) -> Optional[TableKnowledge]:
        bp = self.load_blueprint()
        if not bp:
            return None
        for t in bp.database_tables:
            if t.table_name.lower() == table_name.lower():
                return t
        return None
