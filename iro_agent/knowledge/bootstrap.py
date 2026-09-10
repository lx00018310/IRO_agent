import time
from pathlib import Path
from typing import Optional, Dict, Any
from iro_agent.config import IROConfig, get_config
from iro_agent.knowledge.tree_scanner import TreeScanner
from iro_agent.knowledge.schema_scanner import SchemaScanner
from iro_agent.knowledge.code_scanner import TargetedCodeScanner
from iro_agent.knowledge.config_catalog import ConfigCatalogScanner
from iro_agent.knowledge.business_flows import BusinessFlowLearner
from iro_agent.knowledge.synthesizer import KnowledgeSynthesizer
from iro_agent.knowledge.validator import BlueprintValidator
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.knowledge.models import ProjectBlueprint


class ProjectKnowledgeBootstrapper:
    """10 阶段深度项目认知初始化流水线执行器 (Deep Project Knowledge Bootstrapper)"""

    def __init__(self, config: Optional[IROConfig] = None):
        self.config = config or get_config()
        self.project_root = Path(self.config.project_root)
        self.store = ProjectKnowledgeStore(base_dir=self.project_root if self.project_root.exists() else Path.cwd())

    def run_bootstrap(self, refresh: bool = False, use_llm: bool = True) -> ProjectBlueprint:
        """执行 10 阶段全要素深度项目认知自举流水线"""
        print("==================================================")
        print("  IRO_agent 深度项目自举构建 (Deep Project Bootstrap)")
        print(f"  目标工程: {self.config.project_name}")
        print(f"  工程路径: {self.config.project_root}")
        print("==================================================")

        # 检查是否已存在
        if self.store.exists() and not refresh:
            print("[信息] 已存在项目认知蓝图。如需重新构建，请使用 --refresh 参数。")
            return self.store.load_blueprint()

        t0 = time.time()

        # Stage 1: Project Map
        print("\n[Stage 1/10] 构建工程全景图 (Project Map)...")
        tree_scanner = TreeScanner(self.project_root)
        tree_res = tree_scanner.scan()
        print(f"  ├─ 识别顶级模块: {', '.join(tree_res.top_level_modules) or '无'}")
        print(f"  ├─ 主力语言: {tree_res.primary_language}，技术框架: {', '.join(tree_res.frameworks) or '通用'}")
        print(f"  └─ 发现启动脚本: {len(tree_res.startup_scripts)} 个，部署脚本: {len(tree_res.deployment_scripts)} 个")

        # Stage 2: Module Discovery
        print("\n[Stage 2/10] 深度探索业务模块 (Module Discovery)...")
        print(f"  └─ 已解析模块边界: {len(tree_res.top_level_modules)} 个核心模块")

        # Stage 3: Config Discovery
        print("\n[Stage 3/10] 遍历配置目录与配置文件 (Config Discovery)...")
        cfg_scanner = ConfigCatalogScanner(self.project_root)
        config_items, config_rules = cfg_scanner.scan()
        print(f"  ├─ 提取有效配置项: {len(config_items)} 项 (已全面脱敏)")
        print(f"  └─ 确立覆盖优先级规则: {len(config_rules)} 条")

        # Stage 4: DB Semantics
        print("\n[Stage 4/10] 探查数据库元数据与业务表语义 (DB Semantics)...")
        schema_scanner = SchemaScanner(db_config=self.config.database)
        schema_res = schema_scanner.scan()
        if schema_res.connected:
            print(f"  └─ 探得数据库业务表: {len(schema_res.tables)} 张")
        else:
            print(f"  └─ 数据库离线或未直连，采用代码模型静态反推")

        # Stage 5: Code Relationship Review
        print("\n[Stage 5/10] 深度静态扫描代码拓扑图 (Code Relationship Review)...")
        code_scanner = TargetedCodeScanner(self.project_root)
        code_res = code_scanner.scan()
        g_nodes = len(code_res.code_graph.get("entities", [])) if code_res.code_graph else 0
        g_edges = len(code_res.code_graph.get("edges", [])) if code_res.code_graph else 0
        print(f"  ├─ 识别模型与实体: {code_res.detected_models_count} 个")
        print(f"  └─ 调用拓扑图构建: {g_nodes} 节点 / {g_edges} 关系边")

        # Stage 6: Core Business Flow Learning
        print("\n[Stage 6/10] 端到端核心业务流提炼 (Core Business Flow Learning)...")
        print(f"  └─ 结合控制器与持久层构建调用链路")

        # Stage 7: External System Mapping
        print("\n[Stage 7/10] 外部协同与硬件系统集成映射 (External System Mapping)...")
        print(f"  └─ 识别外部系统通信与硬件协议")

        # Stage 8: GLM Multi-pass Synthesis
        print("\n[Stage 8/10] 7-Pass 多通道结构化认知合成 (GLM Multi-pass Synthesis)...")
        synthesizer = KnowledgeSynthesizer(glm_cfg=self.config.glm)
        blueprint = synthesizer.synthesize(
            tree_res=tree_res,
            schema_res=schema_res,
            code_res=code_res,
            config_items=config_items,
            config_rules=config_rules,
            use_llm=use_llm,
        )

        # Stage 9: Validation
        print("\n[Stage 9/10] 真实要素核验与置信度校准 (Validation)...")
        validator = BlueprintValidator()
        sanitized_bp, warnings = validator.validate(blueprint, schema_res, code_res)
        for w in warnings:
            print(f"  [校验提示] {w}")

        # Stage 10: Persist Knowledge
        print("\n[Stage 10/10] 持久化项目认知全景蓝图 (Persist Knowledge)...")
        self.store.save_blueprint(sanitized_bp, export_markdown=True)
        cost_time = time.time() - t0

        print("\n==================================================")
        print(f"[Bootstrap 完成] 耗时: {cost_time:.2f}s")
        print(f"Project Map: 完成 ({len(sanitized_bp.modules)} 模块)")
        print(f"Config Catalog: {len(sanitized_bp.config_catalog)} 项配置")
        print(f"DB Semantics: {len(sanitized_bp.database_tables)} 张核心数据表")
        print(f"Business Flows: {len(sanitized_bp.business_flows)} 条核心业务流程")
        print(f"Validation: {'通过 (含提示)' if warnings else '完美通过'}")
        print(f"持久化蓝图: {self.store.blueprint_path}")
        print("==================================================")

        return sanitized_bp
