import pytest
from iro_agent.knowledge.unknowns import KnowledgeUnknown, UnknownQueue
from iro_agent.knowledge.learning_state import LearningState
from iro_agent.knowledge.learning_loop import evaluate_learning_stop_conditions


def test_stop_condition_stop_a_all_resolved():
    state = LearningState(max_rounds=12)
    queue = UnknownQueue()
    u1 = KnowledgeUnknown("u1", "T1", "D1", resolvability=3, status="RESOLVED")
    u2 = KnowledgeUnknown("u2", "T2", "D2", resolvability=4, status="RESOLVED")
    queue.add(u1)
    queue.add(u2)
    state.sync_unknown_queue(queue)

    state.round_no = 3
    state.coverage_history = [0.1, 0.4, 0.7]

    reason = evaluate_learning_stop_conditions(state)
    assert reason == "STOP_A_NO_HIGH_VALUE_UNKNOWNS"


def test_stop_condition_stop_b_plateau():
    state = LearningState(max_rounds=12)
    queue = UnknownQueue()
    # 还有待解决项
    queue.add(KnowledgeUnknown("u1", "T1", "D1", resolvability=3, status="OPEN"))
    state.sync_unknown_queue(queue)

    state.round_no = 4
    # 最近两次增量均为 0.01 (< 0.03)
    state.coverage_history = [0.20, 0.35, 0.36, 0.37]

    reason = evaluate_learning_stop_conditions(state)
    assert reason == "STOP_B_CONVERGENCE_PLATEAU"


def test_stop_condition_stop_c_only_physical_unresolvable():
    state = LearningState(max_rounds=12)
    queue = UnknownQueue()
    # 一个已解决，一个物理不可解
    queue.add(KnowledgeUnknown("u1", "Code logic", "Resolved", resolvability=3, status="RESOLVED"))
    queue.add(KnowledgeUnknown("u2", "Physical wire", "Broken", resolvability=0, status="OPEN"))
    state.sync_unknown_queue(queue)

    state.round_no = 2
    state.coverage_history = [0.30, 0.50]

    reason = evaluate_learning_stop_conditions(state)
    assert reason == "STOP_C_ALL_DIGITALLY_UNRESOLVABLE"


def test_stop_condition_stop_d_max_rounds():
    state = LearningState(max_rounds=6)
    queue = UnknownQueue()
    queue.add(KnowledgeUnknown("u1", "Large backlog", "Desc", resolvability=4, status="OPEN"))
    state.sync_unknown_queue(queue)

    state.round_no = 6
    state.coverage_history = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]

    reason = evaluate_learning_stop_conditions(state)
    assert reason == "STOP_D_MAX_ROUNDS_REACHED"
