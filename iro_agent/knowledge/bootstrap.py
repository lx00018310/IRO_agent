import time
from pathlib import Path
from typing import Optional, Dict, Any
from iro_agent.config import IROConfig, get_config
from iro_agent.knowledge.tree_scanner import TreeScanner
from iro_agent.knowledge.schema_scanner import SchemaScanner
from iro_agent.knowledge.code_scanner import TargetedCodeScanner
from iro_agent.knowledge.config_catalog import ConfigCatalogScanner
from iro_agent.knowledge.evidence_bundle import BootstrapEvidenceBundle
from iro_agent.knowledge.synthesizer import KnowledgeSynthesizer
from iro_agent.knowledge.validator import BlueprintValidator
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.knowledge.bootstrap_report import BootstrapReportGenerator
from iro_agent.knowledge.models import ProjectBlueprint


class ProjectKnowledgeBootstrapper:
    """深度项目认知初始化流水线执行器 (True Deep Project Knowledge Bootstrapper)"""

    def __init__(self, config: Optional[IROConfig] = None):
        self.config = config or get_config()
        self.project_root = Path(self.config.project_root)
        self.store = ProjectKnowledgeStore(base_dir=self.project_root if self.project_root.exists() else Path.cwd())

    def run_bootstrap(
        self,
        refresh: bool = False,
        use_llm: bool = True,
        static_only: bool = False,
    ) -> ProjectBlueprint:
        """执行全阶段真实 GLM 深度自举流水线"""
        print("==================================================")
        print("  IRO_agent 深度项目自举构建 (Deep Project Bootstrap)")
        print(f"  目标工程: {self.config.project_name}")
        print(f"  工程路径: {self.config.project_root}")
        mode_str = "纯静态基线 (Static-Only)" if static_only else "真 GLM-5.3-Flash 深度学习模式"
        print(f"  自举模式: {mode_str}")
        print("==================================================")

        # 检查是否已存在
        if self.store.exists() and not refresh:
            print("[信息] 已存在项目认知蓝图。如需重新构建，请使用 --refresh 参数。")
            return self.store.load_blueprint()

        # 校验模型配置 (非 static_only 模式下严禁静默假成功)
        effective_use_llm = use_llm and not static_only
        if not static_only:
            has_api_key = bool(
                self.config.glm.api_key and self.config.glm.api_key != "YOUR_GLM_API_KEY"
            )
            if not has_api_key and use_llm:
                raise ValueError(
                    "未配置有效的 GLM API Key！默认自举模式必须执行真实深度 GLM 认知与源码精读。\n"
                    "请在 config.json 中配置 glm.api_key，或显式附加 --static-only 参数以使用纯静态基线。"
                )

        t0 = time.time()

        # Stage 0: 静态证据归集 (Static Evidence Collection)
        print("\n[Bootstrap 0/9] 静态证据多维归集 (Static Evidence Collection)...")
        tree_scanner = TreeScanner(self.project_root)
        tree_res = tree_scanner.scan()
        print(f"  ├─ 识别顶级模块: {', '.join(tree_res.top_level_modules) or '无'}")
        print(f"  ├─ 主力语言: {tree_res.primary_language}，技术框架: {', '.join(tree_res.frameworks) or '通用'}")
        print(f"  └─ 发现启动脚本: {len(tree_res.startup_scripts)} 个，部署脚本: {len(tree_res.deployment_scripts)} 个")

        cfg_scanner = ConfigCatalogScanner(self.project_root)
        config_items, config_rules = cfg_scanner.scan()
        print(f"  ├─ 提取有效配置项: {len(config_items)} 项 (已全面脱敏)，规则: {len(config_rules)} 条")

        schema_scanner = SchemaScanner(db_config=self.config.database)
        schema_res = schema_scanner.scan()
        if schema_res.connected:
            print(f"  ├─ 探得数据库业务表: {len(schema_res.tables)} 张")
        else:
            print(f"  ├─ 数据库离线或未直连，采用代码实体静态反推")

        code_scanner = TargetedCodeScanner(self.project_root)
        code_res = code_scanner.scan()
        g_nodes = len(code_res.code_graph.get("entities", [])) if code_res.code_graph else 0
        g_edges = len(code_res.code_graph.get("edges", [])) if code_res.code_graph else 0
        print(f"  └─ 代码实体与拓扑图: {code_res.detected_models_count} 模型 / {g_nodes} 节点 / {g_edges} 关系边")

        evidence_bundle = BootstrapEvidenceBundle.assemble(
            project_name=self.config.project_name or "TASK-013",
            tree_res=tree_res,
            schema_res=schema_res,
            code_res=code_res,
            config_items=config_items,
            config_rules=config_rules,
        )

        # Stage 1 ~ Stage 7: 真实深度多轮学习与 Critic Pass
        print("\n[Bootstrap 1/9] GLM 系统全景架构深度学习 (System Architecture Learning)...")
        print("[Bootstrap 2/9] 核心模块源码针对性精读与职责萃取 (Module Deep Learning)...")
        print("[Bootstrap 3/9] 配置项现场业务语义与生效层级学习 (Config System Learning)...")
        print("[Bootstrap 4/9] 数据库业务表角色与状态流转学习 (DB & State Learning)...")
        print("[Bootstrap 5/9] 端到端核心业务链路提炼 (Business Flow Learning)...")
        print("[Bootstrap 6/9] 外部协同、PLC与机器人集成映射 (External System Learning)...")
        print("[Bootstrap 7/9] 批判性推论审计与未知暗区审查 (Critic Pass)...")

        synthesizer = KnowledgeSynthesizer(glm_cfg=self.config.glm)
        blueprint = synthesizer.synthesize(
            tree_res=tree_res,
            schema_res=schema_res,
            code_res=code_res,
            config_items=config_items,
            config_rules=config_rules,
            use_llm=effective_use_llm,
        )

        # Stage 8: 真实要素核验与置信度校准 (Validation)
        print("\n[Bootstrap 8/9] 真实要素程序化核验与置信度校准 (Validation)...")
        validator = BlueprintValidator()
        sanitized_bp, warnings = validator.validate(blueprint, schema_res, code_res)
        for w in warnings:
            print(f"  [校验提示] {w}")

        # Stage 9: 持久化与生成自举报告 (Persist + Bootstrap Report)
        print("\n[Bootstrap 9/9] 持久化项目认知全景蓝图与质量报告 (Persist & Report)...")
        self.store.save_blueprint(sanitized_bp, export_markdown=True)

        report_md = BootstrapReportGenerator.generate(sanitized_bp)
        report_path = self.store.store_dir / "bootstrap_report.md"
        with open(report_path, "w", encoding="utf-8") as rf:
            rf.write(report_md)

        cost_time = time.time() - t0
        stats = sanitized_bp.bootstrap_stats or {}

        print("\n==================================================")
        print(f"[Deep Bootstrap 完成] 总耗时: {cost_time:.2f}s")
        print(f"  ├─ 真实 GLM 调用轮次: {stats.get('glm_calls', 0)} 次")
        print(f"  ├─ 深入精读源码文件: {stats.get('files_deep_read', 0)} 个 ({stats.get('lines_inspected', 0)} 行)")
        print(f"  ├─ 核心模块建立认知: {len(sanitized_bp.modules)} 个")
        print(f"  ├─ 核心业务端到端流: {len(sanitized_bp.business_flows)} 条")
        print(f"  ├─ 识别已知未知暗区: {len(sanitized_bp.known_unknowns)} 项")
        print(f"  ├─ 认知蓝图文件: {self.store.blueprint_path}")
        print(f"  └─ 深度自举报告: {report_path}")
        print("==================================================")

        return sanitized_bp
