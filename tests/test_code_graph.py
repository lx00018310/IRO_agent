from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge, CodeEvidence
from iro_agent.knowledge.code_graph import CodeRelationshipGraph


def test_code_graph_api_to_table_tracing():
    graph = CodeRelationshipGraph()

    # 1. 注册节点: API -> Controller -> Service -> Mapper -> Table
    api_node = CodeEntityNode(
        entity_id="api:POST:/ordersys/dock/create",
        entity_type="api",
        name="POST /ordersys/dock/create",
        metadata={"path": "/ordersys/dock/create"},
    )
    ctrl_node = CodeEntityNode(
        entity_id="com.example.controller.DockController.createTask",
        entity_type="controller",
        name="createTask",
    )
    svc_node = CodeEntityNode(
        entity_id="com.example.service.DockTaskService.assignTask",
        entity_type="service",
        name="assignTask",
    )
    mapper_node = CodeEntityNode(
        entity_id="com.example.mapper.DockTaskMapper.insertTask",
        entity_type="mapper",
        name="insertTask",
    )
    table_node = CodeEntityNode(
        entity_id="table:ordersys_dock_task",
        entity_type="table",
        name="ordersys_dock_task",
    )

    for n in [api_node, ctrl_node, svc_node, mapper_node, table_node]:
        graph.add_entity(n)

    # 2. 注册关系边
    graph.add_relationship(
        CodeRelationshipEdge(
            source_entity_id=ctrl_node.entity_id,
            relationship_type="EXPOSES_API",
            target_entity_id=api_node.entity_id,
        )
    )
    graph.add_relationship(
        CodeRelationshipEdge(
            source_entity_id=ctrl_node.entity_id,
            relationship_type="CALLS_SERVICE",
            target_entity_id=svc_node.entity_id,
        )
    )
    graph.add_relationship(
        CodeRelationshipEdge(
            source_entity_id=svc_node.entity_id,
            relationship_type="CALLS_MAPPER",
            target_entity_id=mapper_node.entity_id,
        )
    )
    graph.add_relationship(
        CodeRelationshipEdge(
            source_entity_id=mapper_node.entity_id,
            relationship_type="WRITES_TABLE",
            target_entity_id=table_node.entity_id,
        )
    )

    # 3. 测试从 Controller / API 追溯到 Table
    traces = graph.trace_api_to_table("/ordersys/dock/create")
    assert len(traces) >= 1
    assert traces[0]["target_table"] == "ordersys_dock_task"

    # 4. 测试表使用追溯 find_table_usage
    usage = graph.find_table_usage("ordersys_dock_task")
    assert len(usage["written_by"]) >= 1
    assert usage["written_by"][0]["caller_name"] == "insertTask"
