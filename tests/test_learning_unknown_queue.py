import pytest
from iro_agent.knowledge.unknowns import KnowledgeUnknown, UnknownQueue


def test_unknown_priority_calculation():
    unk1 = KnowledgeUnknown(
        unknown_id="unk_1",
        topic="Database SoT",
        description="Verify task table role",
        importance=5,
        resolvability=4,
        business_impact=0.9,
        diagnostic_relevance=0.8,
        confidence_gap=1.0,
        reading_cost=1.0,
    )
    # priority = 0.9 * 0.8 * 4 * 1.0 / 1.0 = 2.88
    assert unk1.calculate_priority() == pytest.approx(2.88, abs=0.01)

    # UNRESOLVABLE_DIGITALLY should have 0 priority
    unk_unres = KnowledgeUnknown(
        unknown_id="unk_2",
        topic="Hardware physical cable",
        description="Cable broken",
        resolvability=0,
        status="OPEN",
    )
    assert unk_unres.calculate_priority() == 0.0

    # RESOLVED should have 0 priority
    unk1.status = "RESOLVED"
    assert unk1.calculate_priority() == 0.0


def test_unknown_queue_selection_order():
    q = UnknownQueue()
    u_low = KnowledgeUnknown(
        unknown_id="u_low",
        topic="Low value topic",
        description="Low",
        resolvability=2,
        business_impact=0.2,
        diagnostic_relevance=0.2,
        reading_cost=2.0,
    )
    u_high = KnowledgeUnknown(
        unknown_id="u_high",
        topic="High value topic",
        description="High",
        resolvability=5,
        business_impact=1.0,
        diagnostic_relevance=1.0,
        reading_cost=1.0,
    )
    u_unres = KnowledgeUnknown(
        unknown_id="u_unres",
        topic="Physical cable",
        description="Unresolvable",
        resolvability=0,
    )

    q.add(u_low)
    q.add(u_high)
    q.add(u_unres)

    # First pop must be highest priority (u_high)
    top1 = q.pop_highest_priority()
    assert top1 is not None
    assert top1.unknown_id == "u_high"

    # Resolving u_high
    q.resolve("u_high", notes="resolved from code", round_no=1)
    assert top1.status == "RESOLVED"

    # Next pop must be u_low (since u_unres is resolvability 0)
    top2 = q.pop_highest_priority()
    assert top2 is not None
    assert top2.unknown_id == "u_low"


def test_unknown_queue_status_transitions():
    q = UnknownQueue()
    u = KnowledgeUnknown(
        unknown_id="u1",
        topic="PLC handshake",
        description="Handshake spec",
        resolvability=3,
    )
    q.add(u)
    assert not q.all_digitally_unresolvable_or_resolved()

    q.mark_attempted("u1", "gateway/plc.py")
    assert "gateway/plc.py" in q.get("u1").attempted_sources

    q.mark_partially_resolved("u1", gap_remaining=0.4, notes="Found partial ACK logic")
    assert q.get("u1").status == "PARTIALLY_RESOLVED"
    assert q.get("u1").confidence_gap == pytest.approx(0.4)

    q.mark_unresolvable("u1", notes="Requires physical oscilloscope")
    assert q.get("u1").status == "UNRESOLVABLE_DIGITALLY"
    assert q.all_digitally_unresolvable_or_resolved()
