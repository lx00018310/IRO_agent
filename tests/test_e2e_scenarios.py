import json
import pytest
from pathlib import Path
from iro_agent.config import get_config
from iro_agent.cli import init_agent_engine
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.gateway.wechat import WeChatGatewayServer, WeChatGatewayHandler


def test_scenario_a_why_broken_today():
    """Scenario A: 昨天好好的，今天为什么不行了？"""
    config = get_config()
    engine = init_agent_engine(config)

    question = "昨天系统运行正常，今天早上突然订单看板卡死，怎么回事？"
    history = [{"role": "user", "content": question}]
    reply = engine.chat_completion(history)

    assert "诊断结论" in reply
    assert "业务影响分析" in reply
    assert "关键事实与研判证据" in reply
    assert "置信度" in reply
    # 确保没有泄露密钥
    assert "SuperSecret" not in reply
    assert "YOUR_GLM_API_KEY" not in reply


def test_scenario_b_upgrade_correlation():
    """Scenario B: 今天的升级导致了这个问题吗？"""
    config = get_config()
    engine = init_agent_engine(config)

    question = "今天部署的最新 WRelease 发布包和这次卡死有关系吗？"
    history = [{"role": "user", "content": question}]
    reply = engine.chat_completion(history)

    assert "诊断结论" in reply
    assert "WRelease" in reply or "发布" in reply or "交付" in reply


def test_scenario_c_historical_similar():
    """Scenario C: 以前发生过类似情况吗？"""
    # 预置一条测试历史记录
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


def test_scenario_d_fault_domain_and_e_impact_scope():
    """Scenario D & E: 到底是哪部分坏了？还能不能继续用？"""
    config = get_config()
    engine = init_agent_engine(config)

    question = "目前到底是前端、后端还是PLC坏了？现场自动装车还能继续跑吗？"
    history = [{"role": "user", "content": question}]
    reply = engine.chat_completion(history)

    assert "业务影响分析" in reply
    assert "建议现场排查步骤" in reply


def test_scenario_wechat_gateway_mock():
    """验证微信网关通信与端到端脱敏响应"""
    config = get_config()
    engine = init_agent_engine(config)
    server = WeChatGatewayServer(host="127.0.0.1", port=18088, glm_client=engine)
    server.start(block=False)

    import urllib.request
    try:
        # 1. 验证 GET 健康检查
        with urllib.request.urlopen("http://127.0.0.1:18088", timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"

        # 2. 验证 POST 微信问答
        req_data = json.dumps({
            "from_user": "field_engineer_zhang",
            "session_id": "group_task013_on_site",
            "content": "@IRO_agent 现场装车屏幕网络掉线了，帮看下是哪里问题？",
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://127.0.0.1:18088",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            res = json.loads(resp.read().decode("utf-8"))
            assert "reply" in res
            assert "诊断结论" in res["reply"]
            # 验证密钥绝不返回
            assert "api_key" not in res["reply"]
            assert "password" not in res["reply"]
    finally:
        server.stop()
