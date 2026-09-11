"""验证 6 个工业排查现场关键场景端到端真实行为"""
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import DecisionAction, HypothesisStatus
from iro_agent.llm.glm_client import GlmClient


def test_scenario_1_normal_robot_fault():
    """场景 1: 正常机器人动作受阻，排查日志与状态并收敛"""
    mock_glm = MagicMock()
    mock_glm.chat_completion.side_effect = [
        # 假设生成
        """```json
[
  {"hypothesis_id": "H1", "description": "AGV急停信号触发", "related_flow_step": "急停回路", "required_evidence": ["log_search"]}
]
```""",
        # Round 1 Planner
        """```json
{
  "thought": "检查急停相关日志",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "log_search",
  "tool_arguments": {"keyword": "EMERGENCY_STOP", "limit": 10},
  "reason": "查急停日志"
}
```""",
        # Round 2 Planner
        """```json
{
  "thought": "日志捕获明确急停信号，申请收敛",
  "hypothesis_updates": [
    {
      "action": "SUPPORT",
      "hypothesis_id": "H1",
      "confidence": 0.95,
      "evidence_ids": ["EV_step_1"],
      "reason": "急停被拍下"
    }
  ],
  "decision": "CONVERGE",
  "reason": "确认急停"
}
```"""
    ]
    tools = {
        "log_search": MagicMock(return_value={"logs": ["[FATAL] Hardware emergency stop button depressed on AGV_02"]}),
    }
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm, tool_handlers=tools)
    report = harness.investigate("AGV在产线上突然停机")
    assert report.final_status == "CONVERGED"
    assert "急停" in report.primary_root_cause


def test_scenario_2_db_query_fault():
    """场景 2: 数据库事务锁等待故障，使用 db_query 契约参数 sql 成功执行并收敛"""
    mock_glm = MagicMock()
    mock_glm.chat_completion.side_effect = [
        """```json
[{"hypothesis_id": "H1", "description": "出库单据被死锁挂起", "related_flow_step": "出库", "required_evidence": ["db_query"]}]
```""",
        """```json
{
  "thought": "查询单据表状态",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "db_query",
  "tool_arguments": {"sql": "SELECT id, status FROM wms_outbound_task WHERE status='LOCKED'"},
  "reason": "查锁定任务"
}
```""",
        """```json
{
  "thought": "查到死锁记录，申请收敛",
  "hypothesis_updates": [
    {
      "action": "SUPPORT",
      "hypothesis_id": "H1",
      "confidence": 0.98,
      "evidence_ids": ["EV_step_1"],
      "reason": "单据处于死锁状态"
    }
  ],
  "decision": "CONVERGE",
  "reason": "确认单据锁死"
}
```"""
    ]
    tools = {
        "db_query": MagicMock(return_value=[{"id": 888, "status": "LOCKED"}]),
    }
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm, tool_handlers=tools)
    report = harness.investigate("出库单一直卡在处理中")
    assert report.final_status == "CONVERGED"
    assert "死锁" in report.primary_root_cause


def test_scenario_3_log_search_fault():
    """场景 3: log_search 契约参数 limit 映射成功执行"""
    mock_glm = MagicMock()
    mock_glm.chat_completion.side_effect = [
        """```json
[{"hypothesis_id": "H1", "description": "微服务连接超时", "related_flow_step": "网关通信", "required_evidence": ["log_search"]}]
```""",
        """```json
{
  "thought": "搜索超时日志",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "log_search",
  "tool_arguments": {"keyword": "Connection reset by peer", "limit": 25},
  "reason": "检索网络错误"
}
```""",
        """```json
{
  "thought": "捕获连接重置日志，申请收敛",
  "hypothesis_updates": [
    {
      "action": "SUPPORT",
      "hypothesis_id": "H1",
      "confidence": 0.9,
      "evidence_ids": ["EV_step_1"],
      "reason": "对端重置网络连接"
    }
  ],
  "decision": "CONVERGE",
  "reason": "网关重置连接"
}
```"""
    ]
    tools = {
        "log_search": MagicMock(return_value={"logs": ["[ERROR] Connection reset by peer: port 9092 unreachable"]}),
    }
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm, tool_handlers=tools)
    report = harness.investigate("上游接口响应频繁报错")
    assert report.final_status == "CONVERGED"
    assert "超时" in report.primary_root_cause or "连接" in report.primary_root_cause


def test_scenario_4_planner_error_fail_closed():
    """场景 4: Planner 发生通信或解析严重异常，Fail Closed 终止"""
    mock_glm = MagicMock(spec=GlmClient)
    mock_glm.complete_structured.side_effect = [
        """```json
[{"hypothesis_id": "H1", "description": "调度阻塞", "related_flow_step": "调度", "required_evidence": ["log_search"]}]
```""",
        RuntimeError("网络断开，大模型无法访问"),
    ]
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)
    report = harness.investigate("自动化立库不动作")
    assert report.final_status == "PLANNER_ERROR"
    assert "PLANNER_ERROR" in report.stop_reason


def test_scenario_5_hypothesis_generation_error_fail_closed():
    """场景 5: 动态假设推演失败，严禁 fallback 模板，立即 Fail Closed 终止"""
    mock_glm = MagicMock(spec=GlmClient)
    mock_glm.chat_completion.side_effect = RuntimeError("GLM 服务 503 Service Unavailable")
    mock_glm.complete_structured.side_effect = RuntimeError("GLM 服务 503 Service Unavailable")

    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)
    report = harness.investigate("自动化立库不动作")
    assert report.final_status == "PLANNER_ERROR"
    assert report.stop_reason == "HYPOTHESIS_GENERATION_ERROR"
    assert len(report.hypotheses) == 0


def test_scenario_6_insufficient_evidence_converge_rejected():
    """场景 6: 证据不足但 LLM 尝试 CONVERGE，被 Guardrail 拦截，最终以 INSUFFICIENT_EVIDENCE 结案"""
    mock_glm = MagicMock(spec=GlmClient)
    mock_glm.complete_structured.side_effect = [
        """```json
[{"hypothesis_id": "H1", "description": "电机烧毁", "related_flow_step": "动力", "required_evidence": ["log_search"]}]
```""",
        """{
            "thought": "不需要任何证据，直接下定论",
            "decision": "CONVERGE",
            "reason": "主观臆断"
        }""",
        """{
            "thought": "再次直接下定论",
            "decision": "CONVERGE",
            "reason": "依旧主观臆断"
        }""",
    ]
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)
    report = harness.investigate("堆垛机无法前进")
    assert report.final_status == "INSUFFICIENT_EVIDENCE"
    assert "INSUFFICIENT_EVIDENCE" in report.stop_reason or "安全防护" in report.stop_reason
