import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from iro_agent.knowledge.scanners.java_spring import JavaSpringScanner
from iro_agent.knowledge.scanners.mybatis import MyBatisScanner
from iro_agent.knowledge.code_graph import CodeRelationshipGraph
from iro_agent.knowledge.synthesizer import KnowledgeSynthesizer
from iro_agent.knowledge.validator import BlueprintValidator
from iro_agent.knowledge.tree_scanner import TreeScanResult
from iro_agent.knowledge.schema_scanner import SchemaScanResult, TableMetadata
from iro_agent.knowledge.code_scanner import CodeScanResult
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge
from iro_agent.cli import init_agent_engine
from iro_agent.config import IROConfig


def test_java_spring_scanner_symbol_resolution_and_scope():
    """测试符号解析器避免断链，以及方法作用域避免伪造调用边"""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src_dir = root / "src" / "main" / "java" / "com" / "example"
        ctrl_dir = src_dir / "controller"
        svc_dir = src_dir / "service"
        mapper_dir = src_dir / "mapper"
        resources_dir = root / "src" / "main" / "resources" / "mapper"
        
        ctrl_dir.mkdir(parents=True)
        svc_dir.mkdir(parents=True)
        mapper_dir.mkdir(parents=True)
        resources_dir.mkdir(parents=True)

        # 1. Service 类
        (svc_dir / "OrderService.java").write_text(
            """package com.example.service;

import org.springframework.stereotype.Service;

@Service
public class OrderService {
    public void create() {
        // do create
    }
}
""",
            encoding="utf-8",
        )

        # 2. Mapper XML
        (resources_dir / "DockTaskMapper.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<mapper namespace="com.example.mapper.DockTaskMapper">
    <insert id="insertTask">
        INSERT INTO sys_dock_task (id, task_no) VALUES (#{id}, #{taskNo})
    </insert>
</mapper>
""",
            encoding="utf-8",
        )

        # 3. Controller 类 (包含 1 个 API 方法调用 orderService.create()，1 个普通无调用方法，1 个私有非 API 辅助方法)
        (ctrl_dir / "OrderController.java").write_text(
            """package com.example.controller;

import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.beans.factory.annotation.Autowired;
import com.example.service.OrderService;
import com.example.mapper.DockTaskMapper;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    @Autowired
    private OrderService orderService;

    @Autowired
    private DockTaskMapper dockTaskMapper;

    @PostMapping("/create")
    public String createOrder() {
        orderService.create();
        dockTaskMapper.insertTask();
        return "created";
    }

    @GetMapping("/info")
    public String getOrder() {
        return "order_info";
    }

    private String buildHelperMessage() {
        return "internal_helper";
    }
}
""",
            encoding="utf-8",
        )

        # 执行 Java 扫描
        java_scanner = JavaSpringScanner(project_root=root)
        result = java_scanner.scan()

        entities = {e.entity_id: e for e in result.entities}
        edges = result.relationships

        # 验证 P0-1 符号解析：目标 ID 必须是全限定名而非短类名
        calls_edges = [
            edge for edge in edges
            if edge.relationship_type in ("CALLS_SERVICE", "CALLS_MAPPER", "CALLS")
        ]
        target_ids = {e.target_entity_id for e in calls_edges}
        assert "com.example.service.OrderService" in target_ids
        assert "com.example.mapper.DockTaskMapper" in target_ids
        # 确保没有短类名的孤立目标
        assert "OrderService" not in target_ids
        assert "DockTaskMapper" not in target_ids

        # 验证 P0-2 方法级调用范围：只有 createOrder 有调用边，getOrder 和 buildHelperMessage 绝没有调用边
        create_method_id = "com.example.controller.OrderController.createOrder"
        get_method_id = "com.example.controller.OrderController.getOrder"
        helper_method_id = "com.example.controller.OrderController.buildHelperMessage"

        create_out_calls = [
            e for e in calls_edges if e.source_entity_id == create_method_id
        ]
        get_out_calls = [
            e for e in calls_edges if e.source_entity_id == get_method_id
        ]
        helper_out_calls = [
            e for e in calls_edges if e.source_entity_id == helper_method_id
        ]

        assert len(create_out_calls) == 2  # 调了 orderService 和 dockTaskMapper
        assert len(get_out_calls) == 0      # 绝无伪造调用
        assert len(helper_out_calls) == 0   # 绝无伪造调用

        # 验证 P0-3 控制器无注解方法绝不伪造 API
        api_entities = [e for e in result.entities if e.entity_type == "api"]
        api_paths = [e.metadata.get("path") for e in api_entities]
        assert "/api/orders/create" in api_paths
        assert "/api/orders/info" in api_paths
        # buildHelperMessage 无注解，绝不能变成 API
        assert "/api/orders/buildHelperMessage" not in api_paths
        assert not any("buildHelperMessage" in p for p in api_paths)


def test_code_graph_trace_api_to_table():
    """测试完整端到端链路追溯 (API -> Controller -> Service -> Mapper -> Table)"""
    graph = CodeRelationshipGraph()
    # 构造节点
    graph.add_entity(CodeEntityNode(entity_id="api:POST:/api/orders/create", entity_type="api", name="POST /api/orders/create"))
    graph.add_entity(CodeEntityNode(entity_id="com.example.controller.OrderController", entity_type="controller", name="OrderController"))
    graph.add_entity(CodeEntityNode(entity_id="com.example.controller.OrderController.createOrder", entity_type="controller", name="createOrder"))
    graph.add_entity(CodeEntityNode(entity_id="com.example.service.OrderService", entity_type="service", name="OrderService"))
    graph.add_entity(CodeEntityNode(entity_id="com.example.mapper.DockTaskMapper", entity_type="mapper", name="DockTaskMapper"))
    graph.add_entity(CodeEntityNode(entity_id="com.example.mapper.DockTaskMapper.insertTask", entity_type="sql_statement", name="insertTask"))
    graph.add_entity(CodeEntityNode(entity_id="table:sys_dock_task", entity_type="table", name="sys_dock_task"))

    # 构造边 (包括部分短类名引用，检验 resolve_entity_id 鲁棒性)
    graph.add_relationship(CodeRelationshipEdge(source_entity_id="com.example.controller.OrderController.createOrder", relationship_type="EXPOSES_API", target_entity_id="api:POST:/api/orders/create"))
    graph.add_relationship(CodeRelationshipEdge(source_entity_id="com.example.controller.OrderController.createOrder", relationship_type="CALLS_MAPPER", target_entity_id="DockTaskMapper"))
    graph.add_relationship(CodeRelationshipEdge(source_entity_id="com.example.mapper.DockTaskMapper", relationship_type="CALLS", target_entity_id="com.example.mapper.DockTaskMapper.insertTask"))
    graph.add_relationship(CodeRelationshipEdge(source_entity_id="com.example.mapper.DockTaskMapper.insertTask", relationship_type="WRITES_TABLE", target_entity_id="table:sys_dock_task"))

    traces = graph.trace_api_to_table("/api/orders/create")
    assert len(traces) >= 1
    assert traces[0]["target_table"] == "sys_dock_task"


def test_synthesizer_generic_and_unbiased():
    """验证知识提炼器完全剥离业务特定硬编码，且推断置信度规范化"""
    synthesizer = KnowledgeSynthesizer()
    tree_res = TreeScanResult(project_root=".", primary_language="java", top_level_modules=["order-service"])
    schema_res = SchemaScanResult(
        connected=False,
        tables=[
            TableMetadata(table_name="ordersys_dock_task", columns=[], primary_key="id"),
            TableMetadata(table_name="ordersys_dispatch_callback_receipt", columns=[], primary_key="id"),
        ]
    )
    code_res = CodeScanResult()

    blueprint = synthesizer._synthesize_deterministic(tree_res, schema_res, code_res)

    all_concepts = [c.name for c in blueprint.business_concepts]
    all_aliases = [a for c in blueprint.business_concepts for a in c.aliases]

    # 严禁出现 TASK-013 专属业务词
    assert "最新一托" not in all_aliases
    assert "当前一托" not in all_aliases
    assert "当前11号月台正在处理什么" not in all_aliases
    assert "调度完成回执" not in all_concepts

    # 命名推断置信度不得为 confirmed
    for c in blueprint.business_concepts:
        assert c.confidence in ("strongly_inferred", "inferred")

    for r in blueprint.source_of_truth_rules:
        assert r.confidence in ("strongly_inferred", "inferred")


def test_validator_dangling_edge_pruning():
    """验证 Validator 对代码调用图悬空边的过滤与告警"""
    validator = BlueprintValidator()
    synthesizer = KnowledgeSynthesizer()
    tree_res = TreeScanResult(project_root=".", primary_language="java", top_level_modules=["app"])
    schema_res = SchemaScanResult(connected=False, tables=[])
    code_res = CodeScanResult()

    blueprint = synthesizer._synthesize_deterministic(tree_res, schema_res, code_res)

    # 构造包含有效边和悬空边的图
    graph = CodeRelationshipGraph()
    graph.add_entity(CodeEntityNode(entity_id="A", entity_type="controller", name="A"))
    graph.add_entity(CodeEntityNode(entity_id="B", entity_type="service", name="B"))
    # 有有效边
    graph.add_relationship(CodeRelationshipEdge(source_entity_id="A", relationship_type="CALLS", target_entity_id="B"))
    # 悬空边 (目标不存在)
    graph.add_relationship(CodeRelationshipEdge(source_entity_id="A", relationship_type="CALLS", target_entity_id="NonExistentC"))
    # 悬空边 (源不存在)
    graph.add_relationship(CodeRelationshipEdge(source_entity_id="NonExistentD", relationship_type="CALLS", target_entity_id="B"))

    code_res.code_graph = graph.to_dict()

    cleaned_bp, warnings = validator.validate(blueprint, schema_res, code_res)

    assert any("过滤" in w or "缺失" in w for w in warnings)
    cleaned_graph_dict = cleaned_bp.metadata.get("code_graph")
    assert len(cleaned_graph_dict["edges"]) == 1
    assert cleaned_graph_dict["edges"][0]["source_entity_id"] == "A"
    assert cleaned_graph_dict["edges"][0]["target_entity_id"] == "B"


def test_agent_engine_registers_code_graph_tools():
    """验证 Agent 引擎正确注册了代码关系图工具 Schema 与 Handler"""
    config = IROConfig()
    client = init_agent_engine(config)

    assert "code_trace_api_to_table" in client.tool_handlers
    assert "code_find_table_usage" in client.tool_handlers

    schemas = client._build_tools_schema()
    tool_names = [t["function"]["name"] for t in schemas]
    assert "code_trace_api_to_table" in tool_names
    assert "code_find_table_usage" in tool_names
