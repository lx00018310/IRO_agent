from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from iro_agent.knowledge.tree_scanner import TreeScanResult
from iro_agent.knowledge.schema_scanner import SchemaScanResult
from iro_agent.knowledge.code_scanner import CodeScanResult
from iro_agent.knowledge.models import ConfigItem, ConfigPriorityRule


class BootstrapEvidenceBundle(BaseModel):
    """Stage 0: 静态证据归集包 (Static Evidence Collection Bundle)"""
    project_name: str
    project_root: str
    top_level_modules: List[str] = Field(default_factory=list)
    primary_language: str = "java"
    frameworks: List[str] = Field(default_factory=list)
    startup_scripts: List[str] = Field(default_factory=list)
    deployment_scripts: List[str] = Field(default_factory=list)
    key_directories: List[str] = Field(default_factory=list)
    
    # 代码图谱要素
    code_graph: Dict[str, Any] = Field(default_factory=dict)
    controllers: List[Dict[str, Any]] = Field(default_factory=list)
    services: List[Dict[str, Any]] = Field(default_factory=list)
    mappers: List[Dict[str, Any]] = Field(default_factory=list)
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    enums: List[Dict[str, Any]] = Field(default_factory=list)
    
    # 数据库与表
    database_connected: bool = False
    database_tables: List[Dict[str, Any]] = Field(default_factory=list)
    
    # 配置
    config_items: List[ConfigItem] = Field(default_factory=list)
    config_rules: List[ConfigPriorityRule] = Field(default_factory=list)
    
    # 外部与通信端点
    external_endpoints: List[str] = Field(default_factory=list)
    known_unknowns: List[str] = Field(default_factory=list)

    @classmethod
    def assemble(
        cls,
        project_name: str,
        tree_res: TreeScanResult,
        schema_res: SchemaScanResult,
        code_res: CodeScanResult,
        config_items: List[ConfigItem],
        config_rules: List[ConfigPriorityRule],
    ) -> "BootstrapEvidenceBundle":
        controllers = []
        services = []
        mappers = []
        entities = []
        external_endpoints = []

        for ent in code_res.entities:
            ent_dict = ent.model_dump()
            ent_type = ent.entity_type.lower()
            if "controller" in ent_type:
                controllers.append(ent_dict)
            elif "service" in ent_type:
                services.append(ent_dict)
            elif "mapper" in ent_type or "repository" in ent_type:
                mappers.append(ent_dict)
            else:
                entities.append(ent_dict)

        db_tables = [t.model_dump() for t in schema_res.tables]

        return cls(
            project_name=project_name,
            project_root=str(tree_res.project_root),
            top_level_modules=list(tree_res.top_level_modules),
            primary_language=tree_res.primary_language,
            frameworks=list(tree_res.frameworks),
            startup_scripts=list(tree_res.startup_scripts),
            deployment_scripts=list(tree_res.deployment_scripts),
            key_directories=list(tree_res.key_directories),
            code_graph=code_res.code_graph or {},
            controllers=controllers,
            services=services,
            mappers=mappers,
            entities=entities,
            enums=list(code_res.enums),
            database_connected=schema_res.connected,
            database_tables=db_tables,
            config_items=config_items,
            config_rules=config_rules,
            external_endpoints=external_endpoints,
            known_unknowns=[],
        )
