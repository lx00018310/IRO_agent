from typing import List, Dict, Any, Optional, Set
from collections import defaultdict
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge, CodeEvidence


class CodeRelationshipGraph:
    """本地轻量级代码实体关系图 (拓扑查询与链路追踪)"""

    def __init__(self):
        self.entities: Dict[str, CodeEntityNode] = {}
        self.edges: List[CodeRelationshipEdge] = []
        self._outgoing_edges: Dict[str, List[CodeRelationshipEdge]] = defaultdict(list)
        self._incoming_edges: Dict[str, List[CodeRelationshipEdge]] = defaultdict(list)

    def add_entity(self, entity: CodeEntityNode) -> None:
        self.entities[entity.entity_id] = entity

    def add_relationship(self, edge: CodeRelationshipEdge) -> None:
        self.edges.append(edge)
        self._outgoing_edges[edge.source_entity_id].append(edge)
        self._incoming_edges[edge.target_entity_id].append(edge)

    def get_entity(self, entity_id: str) -> Optional[CodeEntityNode]:
        return self.entities.get(entity_id)

    def find_callers(self, entity_id: str) -> List[CodeRelationshipEdge]:
        """获取调用/依赖该实体的上游关系"""
        return self._incoming_edges.get(entity_id, [])

    def find_callees(self, entity_id: str) -> List[CodeRelationshipEdge]:
        """获取该实体发起调用/依赖的下游关系"""
        return self._outgoing_edges.get(entity_id, [])

    def trace_api_to_table(self, api_path: str) -> List[Dict[str, Any]]:
        """链路追溯: API -> Controller -> Service -> Mapper/Repo -> SQL/Table"""
        matched_chains: List[Dict[str, Any]] = []
        api_path_clean = api_path.strip().lower()

        # 1. 定位 API 节点或暴露 API 的 Controller 方法
        entry_nodes: List[CodeEntityNode] = []
        for ent_id, ent in self.entities.items():
            if ent.entity_type == "api":
                if api_path_clean in ent.name.lower() or ent.name.lower() in api_path_clean:
                    # 寻找暴露该 API 的 Controller
                    controller_callers = [
                        edge.source_entity_id for edge in self.find_callers(ent.entity_id)
                        if edge.relationship_type == "EXPOSES_API"
                    ]
                    for c_id in controller_callers:
                        c_ent = self.get_entity(c_id)
                        if c_ent and c_ent not in entry_nodes:
                            entry_nodes.append(c_ent)
                    if not controller_callers:
                        entry_nodes.append(ent)
            elif ent.entity_type == "controller":
                p = ent.metadata.get("path", "")
                if p and (api_path_clean in p.lower() or p.lower() in api_path_clean):
                    if ent not in entry_nodes:
                        entry_nodes.append(ent)

        visited: Set[str] = set()

        ALLOWED_RELS = {
            "CALLS", "CALLS_SERVICE", "CALLS_MAPPER", "CALLS_REPOSITORY",
            "USES", "MAPS_TO_TABLE", "READS_TABLE", "WRITES_TABLE", "EXPOSES_API"
        }

        def dfs(current_id: str, current_path: List[Dict[str, Any]]):
            curr_ent = self.get_entity(current_id)
            node_desc = {
                "entity_id": current_id,
                "entity_type": curr_ent.entity_type if curr_ent else "unknown",
                "name": curr_ent.name if curr_ent else current_id,
                "file_path": curr_ent.file_path if curr_ent else "",
                "start_line": curr_ent.start_line if curr_ent else 1,
            }
            new_path = current_path + [node_desc]

            if curr_ent and curr_ent.entity_type in ("table", "database_table"):
                matched_chains.append({
                    "target_table": curr_ent.name,
                    "chain": new_path,
                })
                return

            out_edges = self.find_callees(current_id)
            for edge in out_edges:
                target_id = edge.target_entity_id
                if edge.relationship_type in ALLOWED_RELS:
                    edge_key = f"{current_id}->{target_id}"
                    if edge_key not in visited and len(new_path) < 12:
                        visited.add(edge_key)
                        dfs(target_id, new_path)
                        visited.remove(edge_key)

        for start_ent in entry_nodes:
            dfs(start_ent.entity_id, [])

        return matched_chains

    def find_table_usage(self, table_name: str) -> Dict[str, Any]:
        """查询某张数据表被哪些代码读取、写入或映射"""
        tbl_clean = table_name.strip().lower()
        res = {
            "table_name": table_name,
            "read_by": [],
            "written_by": [],
            "mapped_by": [],
        }

        for edge in self.edges:
            target_ent = self.get_entity(edge.target_entity_id)
            target_name = target_ent.name.lower() if target_ent else edge.target_entity_id.lower()

            if tbl_clean == target_name or tbl_clean in target_name:
                source_ent = self.get_entity(edge.source_entity_id)
                evidence_info = edge.evidence.model_dump() if edge.evidence else {
                    "file_path": source_ent.file_path if source_ent else "",
                    "start_line": source_ent.start_line if source_ent else 1,
                }
                item = {
                    "caller_id": edge.source_entity_id,
                    "caller_name": source_ent.name if source_ent else edge.source_entity_id,
                    "caller_type": source_ent.entity_type if source_ent else "unknown",
                    "evidence": evidence_info,
                }
                if edge.relationship_type == "READS_TABLE":
                    res["read_by"].append(item)
                elif edge.relationship_type == "WRITES_TABLE":
                    res["written_by"].append(item)
                elif edge.relationship_type == "MAPS_TO_TABLE":
                    res["mapped_by"].append(item)

        return res

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.model_dump() for e in self.entities.values()],
            "edges": [e.model_dump() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeRelationshipGraph":
        graph = cls()
        for e_data in data.get("entities", []):
            graph.add_entity(CodeEntityNode.model_validate(e_data))
        for r_data in data.get("edges", []):
            graph.add_relationship(CodeRelationshipEdge.model_validate(r_data))
        return graph
