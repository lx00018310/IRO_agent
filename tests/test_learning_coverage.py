import pytest
from iro_agent.knowledge.unknowns import KnowledgeUnknown, UnknownQueue
from iro_agent.knowledge.learning_state import LearningState, DEFAULT_COVERAGE_DIMENSIONS
from iro_agent.knowledge.learning_loop import evaluate_learning_stop_conditions


def test_coverage_dimensions_and_overall():
    state = LearningState()
    assert len(state.coverage) == 10
    for dim in DEFAULT_COVERAGE_DIMENSIONS:
        assert dim in state.coverage

    assert state.overall_coverage() == 0.0

    state.update_coverage_dimension("architecture", 0.8)
    state.update_coverage_dimension("modules", 0.6)
    # average = (0.8 + 0.6) / 10 = 0.14
    assert state.overall_coverage() == pytest.approx(0.14)


def test_coverage_gain_tracking():
    state = LearningState()
    # Round 0
    state.record_round_coverage()  # 0.0
    # Round 1
    state.update_coverage_dimension("architecture", 0.5)  # overall 0.05
    state.record_round_coverage()
    # Round 2
    state.update_coverage_dimension("modules", 0.5)  # overall 0.10
    state.record_round_coverage()

    gains = state.recent_coverage_gains(window=2)
    assert len(gains) == 2
    assert gains[0] == pytest.approx(0.05)
    assert gains[1] == pytest.approx(0.05)


def test_stop_condition_convergence_plateau():
    state = LearningState(max_rounds=12)
    queue = UnknownQueue()
    queue.add(KnowledgeUnknown("u1", "T1", "D1", resolvability=3))
    state.sync_unknown_queue(queue)

    state.round_no = 2
    state.coverage_history = [0.50, 0.51, 0.52]  # gains: +0.01, +0.01 (both < 0.03)

    reason = evaluate_learning_stop_conditions(state)
    assert reason == "STOP_B_CONVERGENCE_PLATEAU"


def test_stop_condition_max_rounds():
    state = LearningState(max_rounds=5)
    state.round_no = 5
    reason = evaluate_learning_stop_conditions(state)
    assert reason == "STOP_D_MAX_ROUNDS_REACHED"


def test_stop_condition_all_unresolvable():
    state = LearningState(max_rounds=10)
    queue = UnknownQueue()
    queue.add(KnowledgeUnknown("u_phys", "Wire broken", "Phys", resolvability=0, status="OPEN"))
    state.sync_unknown_queue(queue)

    state.round_no = 1
    state.coverage_history = [0.2, 0.3]
    reason = evaluate_learning_stop_conditions(state)
    assert reason == "STOP_C_ALL_DIGITALLY_UNRESOLVABLE"
