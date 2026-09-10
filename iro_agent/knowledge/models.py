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


class ProjectBlueprint(BaseModel):
    """工业软件项目认知完整蓝图数据模型"""
    project: ProjectMetadata
    modules: List[ModuleKnowledge] = Field(default_factory=list)
    business_concepts: List[BusinessConcept] = Field(default_factory=list)
    data_sources: List[Dict[str, Any]] = Field(default_factory=list)
    database_tables: List[TableKnowledge] = Field(default_factory=list)
    states: List[StateEnumKnowledge] = Field(default_factory=list)
    apis: List[ApiKnowledge] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    source_of_truth_rules: List[SourceOfTruthRule] = Field(default_factory=list)
    code_locations: List[CodeLocation] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
