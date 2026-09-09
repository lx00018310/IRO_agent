import json
from unittest.mock import MagicMock, patch
import pytest
from iro_agent.config import get_config, IROConfig
from iro_agent.cli import init_agent_engine
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.gateway.wechat import WeChatGatewayServer


def test_missing_api_key_raises():
    """验证未配置 API Key 时坚决拒绝执行并报错，不再进行任何假降级"""
    config = IROConfig(glm={"api_key": ""})
    engine = init_agent_engine(config)

    with pytest.raises(ValueError, match="未配置有效的 GLM API Key"):
        engine.chat_completion([{"role": "user", "content": "系统怎么了"}])


def test_scenario_a_glm_tool_calling_flow():
    """验证 GLM 在线 Tool Calling 调度流程"""
    config = get_config()
    config.glm.api_key = "test_valid_api_key_12345"
    engine = init_agent_engine(config)

    # 模拟第 1 轮：模型请求调用 wrelease_compare 工具
    mock_resp_round1 = MagicMock()
    mock_resp_round1.status_code = 200
    mock_resp_round1.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "wrelease_list",
                        "arguments": "{}",
                    },
                }],
            }
        }]
    }

    # 模拟第 2 轮：模型获得工具结果后给出最终业务语言诊断
    mock_resp_round2 = MagicMock()
    mock_resp_round2.status_code = 200
    mock_resp_round2.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": (
                    "### 1. 诊断结论\n"
                    "通过调阅 WRelease 发现今天存在模块更新，工位网络偶发掉线，核心装车流程正常。\n\n"
                    "### 2. 业务影响分析 (级别: P2)\n"
                    "仅看板监控刷新延迟。\n\n"
                    "### 7. 诊断置信度\nHigh"
                ),
            }
        }]
    }

    with patch("requests.post", side_effect=[mock_resp_round1, mock_resp_round2]):
        reply = engine.chat_completion([{"role": "user", "content": "今天升级导致卡死了吗？"}])
        assert "诊断结论" in reply
        assert "业务影响分析" in reply
        assert "置信度" in reply


def test_scenario_c_historical_similar():
    """验证历史相似事故统计"""
    store = IncidentStore()
    store.record_incident({
        "symptom": "WebSocket 掉线，订单看板无法实时刷新",
        "user_question": "以前发生过类似情况吗？",
        "fault_domain": "Network",
        "root_cause": "局域网 TCP 连接重置",
        "severity": "P2",
    })

    stats = store.get_similar_incident_stats("WebSocket", days=90)
    assert stats["total_similar_count"] >= 1
    assert "Network" in stats["domain_breakdown"]


def test_scenario_wechat_gateway_with_glm():
    """验证微信网关调用 GLM 回送结果"""
    config = get_config()
    config.glm.api_key = "test_valid_api_key_12345"
    engine = init_agent_engine(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "### 1. 诊断结论\n经 GLM 诊断分析，当前系统网络稳定，无破坏性异常。",
            }
        }]
    }

    with patch("requests.post", return_value=mock_resp):
        server = WeChatGatewayServer(host="127.0.0.1", port=18089, glm_client=engine)
        server.start(block=False)

        import urllib.request
        try:
            req_data = json.dumps({
                "from_user": "user_01",
                "session_id": "sess_01",
                "content": "@IRO_agent 检查现场状态",
            }).encode("utf-8")

            req = urllib.request.Request(
                "http://127.0.0.1:18089",
                data=req_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
                res = json.loads(resp.read().decode("utf-8"))
                assert "诊断结论" in res["reply"]
        finally:
            server.stop()
