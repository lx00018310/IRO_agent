from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge


class ScannerResult(BaseModel):
    """扫描器标准化产出物"""
    entities: List[CodeEntityNode] = Field(default_factory=list)
    relationships: List[CodeRelationshipEdge] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseCodeScannerAdapter(ABC):
    """通用代码扫描器适配器抽象基类"""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()

    @abstractmethod
    def detect(self) -> bool:
        """探测当前项目是否包含适配的技术栈特征"""
        pass

    @abstractmethod
    def scan(self) -> ScannerResult:
        """执行结构化静态扫描并返回实体与关系"""
        pass
