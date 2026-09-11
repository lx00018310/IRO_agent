import pytest
from pathlib import Path
from iro_agent.knowledge.unknowns import KnowledgeUnknown, UnknownQueue
from iro_agent.knowledge.learning_state import LearningState
from iro_agent.knowledge.learning_loop import BootstrapLearningLoop


def test_learning_replan_dynamic_selection(tmp_path):
    # Setup mock files
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "order_service.py").write_text("class OrderService:\n    pass\n", encoding="utf-8")
    (src_dir / "plc_gateway.py").write_text("class PLCGateway:\n    pass\n", encoding="utf-8")

    loop = BootstrapLearningLoop(project_root=tmp_path, max_rounds=5)
    state = LearningState(max_rounds=5)
    queue = UnknownQueue()

    # Add 2 unknowns
    u_order = KnowledgeUnknown(
        unknown_id="unk_order",
        topic="Order Service Flow",
        description="Check order dispatch",
        resolvability=4,
        suggested_sources=["src/order_service.py"],
        business_impact=0.9,
        diagnostic_relevance=0.9,
    )
    u_plc = KnowledgeUnknown(
        unknown_id="unk_plc",
        topic="PLC Gateway Protocol",
        description="Check PLC protocol",
        resolvability=3,
        suggested_sources=["src/plc_gateway.py"],
        business_impact=0.7,
        diagnostic_relevance=0.7,
    )
    queue.add(u_plc)
    queue.add(u_order)
    state.sync_unknown_queue(queue)
    state.record_round_coverage()

    # First selection must be unk_order (higher score)
    top1 = state.get_unknown_queue().pop_highest_priority()
    assert top1.unknown_id == "unk_order"

    # Simulate dynamic discovery during learning: new critical DB unknown discovered!
    u_db_emergency = KnowledgeUnknown(
        unknown_id="unk_db_critical",
        topic="Critical Task Lock Table",
        description="Urgent lock table schema",
        resolvability=5,
        suggested_sources=["src/order_service.py"],
        business_impact=1.0,
        diagnostic_relevance=1.0,
        reading_cost=0.5,  # Very high priority!
    )
    q = state.get_unknown_queue()
    q.resolve("unk_order", notes="Read order_service.py", round_no=1)
    q.add(u_db_emergency)
    state.sync_unknown_queue(q)

    # Next pop should adaptively pick the newly discovered high-priority unk_db_critical, NOT unk_plc
    top2 = state.get_unknown_queue().pop_highest_priority()
    assert top2.unknown_id == "unk_db_critical"


def test_learning_loop_execution(tmp_path):
    code_dir = tmp_path / "service"
    code_dir.mkdir()
    (code_dir / "dispatch.py").write_text("def dispatch_task(): pass", encoding="utf-8")

    loop = BootstrapLearningLoop(project_root=tmp_path, max_rounds=3)
    initial_state = loop.build_initial_state()

    final_state = loop.run_loop(initial_state)

    assert final_state.round_no > 0
    assert final_state.stop_reason is not None
    assert len(final_state.completed_reads) > 0 or len(final_state.failed_reads) > 0
    assert final_state.overall_coverage() > 0.0
