import time
from pathlib import Path
from typing import Optional, Dict, Any
from iro_agent.config import IROConfig, get_config
from iro_agent.knowledge.tree_scanner import TreeScanner
from iro_agent.knowledge.schema_scanner import SchemaScanner
from iro_agent.knowledge.code_scanner import TargetedCodeScanner
from iro_agent.knowledge.synthesizer import KnowledgeSynthesizer
from iro_agent.knowledge.validator import BlueprintValidator
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.knowledge.models import ProjectBlueprint


class ProjectKnowledgeBootstrapper:
    """项目认知初始化流水线执行器 (Project Knowledge Bootstrapper)"""

    def __init__(self, config: Optional[IROConfig] = None):
        self.config = config or get_config()
        self.project_root = Path(self.config.project_root)
        self.store = ProjectKnowledgeStore(base_dir=self.project_root if self.project_root.exists() else Path.cwd())

    def run_bootstrap(self, refresh: bool = False, use_llm: bool = True) -> ProjectBlueprint:
        """执行全自动扫描、提炼、校验与持久化流程"""
        print("==================================================")
        print("  IRO_agent 项目认知引导构建 (Project Bootstrap)")
        print(f"  目标工程: {self.config.project_name}")
        print(f"  工程路径: {self.config.project_root}")
        print("==================================================")

        # 检查是否已存在
        if self.store.exists() and not refresh:
            print("[信息] 已存在项目认知蓝图。如需重新构建，请使用 --refresh 参数。")
            return self.store.load_blueprint()

        t0 = time.time()

        # 1. 扫描目录结构与技术栈
        print("\n[Stage 1/5] 扫描目录结构与技术栈...")
        tree_scanner = TreeScanner(self.project_root)
        tree_res = tree_scanner.scan()
        print(f"  ├─ 识别顶级模块: {', '.join(tree_res.top_level_modules) or '无'}")
        print(f"  ├─ 主要语言: {tree_res.primary_language}")
        print(f"  └─ 技术栈框架: {', '.join(tree_res.frameworks) or '通用'}")

        # 2. 只读扫描数据库 Schema
        print("\n[Stage 2/5] 探查数据库元数据 (只读连接)...")
        schema_scanner = SchemaScanner(db_config=self.config.database)
        schema_res = schema_scanner.scan()
        if schema_res.connected:
            print(f"  ├─ 成功连接数据库: {schema_res.database_name}")
            print(f"  └─ 发现用户业务表数量: {len(schema_res.tables)} 张")
        else:
            print(f"  └─ 数据库元数据未直接连通: {schema_res.error or '未配置'}")

        # 3. 定向扫描数据模型与代码实体
        print("\n[Stage 3/5] 定向扫描数据模型 (ORM) 与关键实体...")
        code_scanner = TargetedCodeScanner(self.project_root)
        code_res = code_scanner.scan()
        print(f"  ├─ 扫描组件数: {code_res.scanned_files_count}")
        print(f"  ├─ 识别模型/实体类: {code_res.detected_models_count} 个")
        print(f"  ├─ 识别状态枚举类: {len(code_res.enums)} 个")
        if code_res.code_graph:
            g_nodes = len(code_res.code_graph.get("entities", []))
            g_edges = len(code_res.code_graph.get("edges", []))
            print(f"  └─ 构建代码拓扑图: 实体节点 {g_nodes} 个, 关系边 {g_edges} 条")

        # 4. 结构化知识合成
        print("\n[Stage 4/5] 提纯业务概念与核心事实源规则 (Source of Truth)...")
        synthesizer = KnowledgeSynthesizer(glm_cfg=self.config.glm)
        blueprint = synthesizer.synthesize(tree_res, schema_res, code_res, use_llm=use_llm)

        # 5. 蓝图校验与持久化
        print("\n[Stage 5/5] 蓝图合法性与敏感信息交叉核验...")
        validator = BlueprintValidator()
        sanitized_bp, warnings = validator.validate(blueprint, schema_res, code_res)
        for w in warnings:
            print(f"  [校验提示] {w}")

        self.store.save_blueprint(sanitized_bp, export_markdown=True)
        cost_time = time.time() - t0

        print("\n==================================================")
        print(f"  项目认知构建完成！耗时: {cost_time:.2f}s")
        print(f"  持久化主文件: {self.store.blueprint_path}")
        print(f"  可读蓝图文档: {self.store.markdown_path}")
        print("  核心业务概念数:", len(sanitized_bp.business_concepts))
        print("  事实源权威规则数:", len(sanitized_bp.source_of_truth_rules))
        print("  核心数据表数量:", len(sanitized_bp.database_tables))
        print("==================================================")

        return sanitized_bp
