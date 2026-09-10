from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ProjectMetadata(BaseModel):
    project_id: str
    project_name: str
    generated_at: str
    last_verified_at: Optional[str] = None
    blueprint_version: str = "0.2.0"
    source_root: str
    active_version_provider: str = "none"
    database_type: str = "postgresql"
    source_fingerprint: Optional[str] = None


class ModuleKnowledge(BaseModel):
    module_id: str
    name: str
    business_role: str
    technical_type: str = ""
    main_paths: List[str] = Field(default_factory=list)
    related_tables: List[str] = Field(default_factory=list)
    related_apis: List[str] = Field(default_factory=list)
    confidence: str = "inferred"
    sources: List[str] = Field(default_factory=list)


class BusinessConcept(BaseModel):
    concept_id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    description: str = ""
    canonical_source: Dict[str, Any] = Field(default_factory=dict)
    secondary_sources: List[str] = Field(default_factory=list)
    do_not_use_as_primary: List[str] = Field(default_factory=list)
    related_fields: List[str] = Field(default_factory=list)
    related_modules: List[str] = Field(default_factory=list)
    query_guidance: str = ""
    confidence: str = "inferred"
    sources: List[str] = Field(default_factory=list)
    last_verified: Optional[str] = None


class SourceOfTruthRule(BaseModel):
    fact: str
    canonical_source: str
    secondary_sources: List[str] = Field(default_factory=list)
    invalid_primary_sources: List[str] = Field(default_factory=list)
    reason: str = ""
    confidence: str = "confirmed"
    sources: List[str] = Field(default_factory=list)


class TableKnowledge(BaseModel):
    table_name: str
    business_role: str
    table_type: str = "unknown"  # current_state, master, transaction, history, callback, audit, configuration, mapping, unknown
    important_fields: List[str] = Field(default_factory=list)
    time_fields: List[str] = Field(default_factory=list)
    primary_key: str = "id"
    status_fields: List[str] = Field(default_factory=list)
    relationships: List[str] = Field(default_factory=list)
    recommended_queries: List[str] = Field(default_factory=list)
    not_for: List[str] = Field(default_factory=list)
    confidence: str = "inferred"
    sources: List[str] = Field(default_factory=list)


class StateEnumKnowledge(BaseModel):
    name: str
    value: str
    business_meaning: str
    source_location: str = ""
    related_table: str = ""
    related_field: str = ""
    confidence: str = "inferred"


class ApiKnowledge(BaseModel):
    method: str
    path: str
    business_role: str
    controller: str = ""
    service: str = ""
    related_tables: List[str] = Field(default_factory=list)
    request_fields: List[str] = Field(default_factory=list)
    response_fields: List[str] = Field(default_factory=list)
    confidence: str = "inferred"
    sources: List[str] = Field(default_factory=list)


class CodeLocation(BaseModel):
    concept: str
    module: str = ""
    file: str
    symbol: str = ""
    purpose: str = ""


class ProjectOverview(BaseModel):
    """工程全景认知模型"""
    modules: List[str] = Field(default_factory=list)
    runtime_components: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    entry_points: List[str] = Field(default_factory=list)
    important_directories: List[str] = Field(default_factory=list)
    startup_scripts: List[str] = Field(default_factory=list)
    deployment_scripts: List[str] = Field(default_factory=list)


class ConfigItem(BaseModel):
    """配置项认知数据模型"""
    config_id: str
    file_path: str
    relative_path: str
    key: str
    value_type: str = "string"
    default_value: Optional[str] = None
    business_meaning: str = ""
    unit: str = ""
    read_by: List[str] = Field(default_factory=list)
    priority: int = 0
    runtime_scope: str = "application"
    confidence: str = "inferred"
    last_verified: Optional[str] = None


class ConfigPriorityRule(BaseModel):
    """配置优先级规则模型"""
    rule_name: str
    description: str
    precedence_order: List[str] = Field(default_factory=list)
    evidence: str = ""


class BusinessFlow(BaseModel):
    """核心业务流程端到端链路模型"""
    name: str
    aliases: List[str] = Field(default_factory=list)
    entry_api: str = ""
    controller: str = ""
    services: List[str] = Field(default_factory=list)
    mappers: List[str] = Field(default_factory=list)
    tables: List[str] = Field(default_factory=list)
    states: List[str] = Field(default_factory=list)
    configs: List[str] = Field(default_factory=list)
    external_systems: List[str] = Field(default_factory=list)
    source_of_truth: str = ""
    evidence: str = ""
    confidence: str = "inferred"


class ExternalSystem(BaseModel):
    """外部依赖与集成系统模型"""
    system_name: str
    connection_type: str = ""
    used_by_module: str = ""
    config_source: str = ""
    related_logs: List[str] = Field(default_factory=list)
    related_apis: List[str] = Field(default_factory=list)
    confidence: str = "inferred"


class ProjectBlueprint(BaseModel):
    """工业软件项目认知完整蓝图数据模型"""
    project: ProjectMetadata
    project_overview: Optional[ProjectOverview] = None
    modules: List[ModuleKnowledge] = Field(default_factory=list)
    business_concepts: List[BusinessConcept] = Field(default_factory=list)
    business_flows: List[BusinessFlow] = Field(default_factory=list)
    config_catalog: List[ConfigItem] = Field(default_factory=list)
    config_priority_rules: List[ConfigPriorityRule] = Field(default_factory=list)
    external_systems: List[ExternalSystem] = Field(default_factory=list)
    data_sources: List[Dict[str, Any]] = Field(default_factory=list)
    database_tables: List[TableKnowledge] = Field(default_factory=list)
    states: List[StateEnumKnowledge] = Field(default_factory=list)
    apis: List[ApiKnowledge] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    source_of_truth_rules: List[SourceOfTruthRule] = Field(default_factory=list)
    code_locations: List[CodeLocation] = Field(default_factory=list)
    operational_rules: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

