import json
from unittest.mock import MagicMock, patch
import pytest
from iro_agent.config import get_config, IROConfig
from iro_agent.cli import init_agent_engine
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.gateway.http_adapter import HttpGatewayAdapter


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
                    "**核心结论**：今天升级未导致主装车流程卡死，核心调度正常。\n\n"
                    "**关键依据**：\n"
                    "- 模块更新主要涉及前端静态与非阻断接口\n"
                    "- 日志未见主流程数据库死锁或崩溃"
                ),
            }
        }]
    }

    with patch("requests.post", side_effect=[mock_resp_round1, mock_resp_round2]):
        reply = engine.chat_completion([{"role": "user", "content": "今天升级导致卡死了吗？"}])
        assert "**核心结论**" in reply
        assert "核心调度正常" in reply


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


def test_scenario_http_gateway_adapter_with_glm():
    """验证开发测试 HTTP 网关适配器调用 GLM 回送结果"""
    config = get_config()
    config.glm.api_key = "test_valid_api_key_12345"
    engine = init_agent_engine(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "**核心结论**：经 GLM 诊断分析，当前系统网络稳定，无破坏性异常。",
            }
        }]
    }

    with patch("requests.post", return_value=mock_resp):
        server = HttpGatewayAdapter(host="127.0.0.1", port=18089, glm_client=engine)
        server.start(block=False)

        import urllib.request
        try:
            req_data = json.dumps({
                "from_user": "user_01",
                "session_id": "sess_01",
                "content": "检查现场状态",
            }).encode("utf-8")

            req = urllib.request.Request(
                "http://127.0.0.1:18089",
                data=req_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
                res = json.loads(resp.read().decode("utf-8"))
                assert "**核心结论**" in res["reply"]
        finally:
            server.stop()


def test_extract_image_path_and_multimodal_flow(tmp_path):
    """验证图片路径自动识别与 GLM 多模态图文调用"""
    from iro_agent.cli import extract_image_path

    # 创建一个临时测试图片
    img_file = tmp_path / "mock_fault.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0mock_image_bytes")

    # 1. 测试无引号路径提取
    raw_input_1 = f"{img_file} 告诉我怎么会这样？"
    extracted_path, clean_text = extract_image_path(raw_input_1)
    assert extracted_path == str(img_file.resolve())
    assert clean_text == "告诉我怎么会这样？"

    # 2. 测试带双引号路径提取（如 Windows 拖入带空格的路径）
    raw_input_2 = f'"{img_file}" 屏幕红字报错排查'
    extracted_path_2, clean_text_2 = extract_image_path(raw_input_2)
    assert extracted_path_2 == str(img_file.resolve())
    assert clean_text_2 == "屏幕红字报错排查"

    # 3. 验证多模态调用传递给 GLM 的 payload
    config = get_config()
    config.glm.api_key = "test_key_valid"
    engine = init_agent_engine(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "**核心结论**：系统拦截了非本车物料。",
            }
        }]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        reply = engine.chat_completion(
            messages=[{"role": "user", "content": clean_text}],
            image_path=extracted_path,
        )
        assert "**核心结论**" in reply

        # 检查 payload 是否包含图片 base64
        called_payload = mock_post.call_args[1]["json"]
        last_msg = called_payload["messages"][-1]
        assert isinstance(last_msg["content"], list)
        assert last_msg["content"][1]["type"] == "image_url"
        assert "data:image/jpeg;base64," in last_msg["content"][1]["image_url"]["url"]
