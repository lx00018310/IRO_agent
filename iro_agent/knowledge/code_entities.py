from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class CodeEvidence(BaseModel):
    """代码证据来源模型"""
    file_path: str
    start_line: int = 1
    end_line: int = 1
    evidence_type: str = "ast_or_regex"
    snippet: str = ""


class CodeEntityNode(BaseModel):
    """通用代码实体节点"""
    entity_id: str  # 唯一ID，如 "com.example.controller.DockController.getTask" 或 "ordersys_dock_task"
    entity_type: str  # module, controller, service, repository, mapper, entity, enum, api, sql_statement, table
    name: str
    qualified_name: str = ""
    file_path: str = ""
    start_line: int = 1
    end_line: int = 1
    framework: str = "generic"  # spring, mybatis, django, vue, etc.
    annotations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    confidence: str = "inferred"  # confirmed, strongly_inferred, inferred


class CodeRelationshipEdge(BaseModel):
    """通用代码调用与数据关系边"""
    source_entity_id: str
    relationship_type: str  # CALLS, USES, MAPS_TO_TABLE, READS_TABLE, WRITES_TABLE, EXPOSES_API, USES_ENUM
    target_entity_id: str
    evidence: Optional[CodeEvidence] = None
    confidence: str = "inferred"
    metadata: Dict[str, Any] = Field(default_factory=dict)
