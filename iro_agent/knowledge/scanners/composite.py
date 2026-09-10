from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from iro_agent.knowledge.scanners.base import BaseCodeScannerAdapter, ScannerResult
from iro_agent.knowledge.scanners.java_spring import JavaSpringScanner
from iro_agent.knowledge.scanners.mybatis import MyBatisScanner
from iro_agent.knowledge.scanners.vue import VueFrontendScanner
from iro_agent.knowledge.scanners.python import PythonScanner
from iro_agent.knowledge.code_graph import CodeRelationshipGraph
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge


class CompositeCodeScanner:
    """综合多语言与框架代码扫描协调器"""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.adapters: List[BaseCodeScannerAdapter] = [
            JavaSpringScanner(self.project_root),
            MyBatisScanner(self.project_root),
            VueFrontendScanner(self.project_root),
            PythonScanner(self.project_root),
        ]

    def scan(self) -> Tuple[ScannerResult, CodeRelationshipGraph]:
        all_entities: List[CodeEntityNode] = []
        all_edges: List[CodeRelationshipEdge] = []
        graph = CodeRelationshipGraph()
        detected_adapters = []

        for adapter in self.adapters:
            if adapter.detect():
                detected_adapters.append(adapter.__class__.__name__)
                res = adapter.scan()
                for ent in res.entities:
                    all_entities.append(ent)
                    graph.add_entity(ent)
                for edge in res.relationships:
                    all_edges.append(edge)
                    graph.add_relationship(edge)

        result = ScannerResult(
            entities=all_entities,
            relationships=all_edges,
            metadata={"detected_adapters": detected_adapters},
        )
        return result, graph
