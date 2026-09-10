import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from iro_agent.config import IROConfig, FeishuConfig, GatewayConfig
from iro_agent.gateway.base import GatewayMessage
from iro_agent.gateway.dedup import EventDeduplicator
from iro_agent.gateway.feishu import FeishuGateway, clean_mention_text
from iro_agent.gateway.http_adapter import HttpGatewayAdapter, HttpGatewayHandler


@pytest.fixture
def mock_glm_client():
    client = MagicMock()
    client.chat_completion.return_value = "**核心结论**：系统运行正常，未见异常报错。"
    return client


@pytest.fixture
def sample_config():
    cfg = IROConfig()
    cfg.feishu.app_id = "cli_mock_app_12345"
    cfg.feishu.app_secret = "mock_secret_abcdef123456"
    cfg.feishu.receive_group_at = True
    cfg.feishu.receive_private = True
    return cfg


def test_01_gateway_startup_and_health(sample_config):
    """Test 1: 网关初始化与健康检查"""
    gw = FeishuGateway(config=sample_config)
    health = gw.health()
    assert health["gateway_type"] == "feishu"
    assert health["app_id_configured"] is True
    assert health["app_secret_configured"] is True

    # 测试凭证缺失时拒绝启动
    no_cred_cfg = IROConfig()
    no_cred_cfg.feishu.app_id = ""
    no_cred_cfg.feishu.app_secret = ""
    bad_gw = FeishuGateway(config=no_cred_cfg)
    with pytest.raises(ValueError, match="未配置有效"):
        bad_gw.start(block=False)


def test_02_private_text_message(sample_config, mock_glm_client, tmp_path):
    """Test 2: 私聊文本解析与回复"""
    dedup_db = str(tmp_path / "test_dedup.db")
    gw = FeishuGateway(config=sample_config, glm_client=mock_glm_client, dedup_db_path=dedup_db)
    gw.send_message = MagicMock(return_value=True)

    fake_event = {
        "header": {"event_id": "evt_priv_001"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_test_01"}},
            "message": {
                "message_id": "om_msg_001",
                "chat_id": "oc_p2p_chat_01",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": "TASK-013今天有什么异常？"}),
                "create_time": "1725920000",
            },
        },
    }

    gw._on_message_receive(fake_event)

    # 验证 GLM 被正常调用且参数正确
    assert mock_glm_client.chat_completion.called
    history = mock_glm_client.chat_completion.call_args[0][0]
    user_prompts = [m["content"] for m in history if m["role"] == "user"]
    assert user_prompts[-1] == "TASK-013今天有什么异常？"

    # 验证向私聊回送了消息
    gw.send_message.assert_called_once()
    call_kwargs = gw.send_message.call_args[1] or {}
    chat_id = call_kwargs.get("chat_id") or gw.send_message.call_args[0][0]
    assert chat_id == "oc_p2p_chat_01"


def test_03_group_without_at_or_at_others_ignored(sample_config, mock_glm_client, tmp_path):
    """Test 3: 群聊无 @ 或 @他人 (如 @张三) 必须严格静默忽略 (P0)"""
    dedup_db = str(tmp_path / "test_dedup.db")
    gw = FeishuGateway(config=sample_config, glm_client=mock_glm_client, dedup_db_path=dedup_db)
    gw.send_message = MagicMock()

    # 情况 A: 完全无 @
    fake_event_no_at = {
        "header": {"event_id": "evt_grp_no_at"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_test_02"}},
            "message": {
                "message_id": "om_msg_002",
                "chat_id": "oc_group_chat_01",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": "大家今天去哪里吃午饭？"}),
                "mentions": [],
                "create_time": "1725920100",
            },
        },
    }
    gw._on_message_receive(fake_event_no_at)
    assert not mock_glm_client.chat_completion.called
    assert not gw.send_message.called

    # 情况 B: @他人 (例如 @张三，非本机器人)
    fake_event_at_other = {
        "header": {"event_id": "evt_grp_at_other"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_test_02"}},
            "message": {
                "message_id": "om_msg_002_other",
                "chat_id": "oc_group_chat_01",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": "@_user_99 张三今天订单怎么了？"}),
                "mentions": [{"key": "@_user_99", "name": "张三"}],
                "create_time": "1725920150",
            },
        },
    }
    gw._on_message_receive(fake_event_at_other)
    # 验证依然坚决不调用模型，不回送消息
    assert not mock_glm_client.chat_completion.called
    assert not gw.send_message.called


def test_04_group_with_at_cleaned(sample_config, mock_glm_client, tmp_path):
    """Test 4: 群聊 @ 消息正确剥离 mention 并响应"""
    dedup_db = str(tmp_path / "test_dedup.db")
    gw = FeishuGateway(config=sample_config, glm_client=mock_glm_client, dedup_db_path=dedup_db)
    gw.send_message = MagicMock(return_value=True)

    fake_event = {
        "header": {"event_id": "evt_grp_with_at"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_test_03"}},
            "message": {
                "message_id": "om_msg_003",
                "chat_id": "oc_group_chat_02",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": "@_user_1 TASK-013今天有什么异常？"}),
                "mentions": [{"key": "@_user_1", "name": "IRO_agent"}],
                "create_time": "1725920200",
            },
        },
    }

    gw._on_message_receive(fake_event)

    # 验证 @ 占位符被清洗
    assert mock_glm_client.chat_completion.called
    history = mock_glm_client.chat_completion.call_args[0][0]
    user_prompts = [m["content"] for m in history if m["role"] == "user"]
    assert user_prompts[-1] == "TASK-013今天有什么异常？"

    # 验证回复发送到同一个群
    gw.send_message.assert_called_once()
    call_kwargs = gw.send_message.call_args[1] or {}
    chat_id = call_kwargs.get("chat_id") or gw.send_message.call_args[0][0]
    assert chat_id == "oc_group_chat_02"
    assert call_kwargs.get("reply_to_message_id") == "om_msg_003"


def test_05_followup_multiturn_session(sample_config, mock_glm_client, tmp_path):
    """Test 5: 多轮对话上下文保持"""
    dedup_db = str(tmp_path / "test_dedup.db")
    gw = FeishuGateway(config=sample_config, glm_client=mock_glm_client, dedup_db_path=dedup_db)
    gw.send_message = MagicMock(return_value=True)

    # 轮次 1
    evt1 = {
        "header": {"event_id": "evt_turn_1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_04"}},
            "message": {
                "message_id": "om_msg_10",
                "chat_id": "oc_group_session",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": "@IRO_agent 今天订单为什么卡住？"}),
                "mentions": [{"key": "@_user_1", "name": "IRO_agent"}],
            },
        },
    }
    gw._on_message_receive(evt1)

    # 轮次 2: 追问
    evt2 = {
        "header": {"event_id": "evt_turn_2"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_04"}},
            "message": {
                "message_id": "om_msg_11",
                "chat_id": "oc_group_session",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": "@IRO_agent 那这个问题以前发生过吗？"}),
                "mentions": [{"key": "@_user_1", "name": "IRO_agent"}],
            },
        },
    }
    gw._on_message_receive(evt2)

    # 验证 session_id 相同且累计了 4 条消息 (user, assistant, user, assistant)
    session_id = "feishu:group:oc_group_session"
    assert session_id in gw.session_history
    history = gw.session_history[session_id]
    assert len(history) == 4
    assert history[0]["content"] == "今天订单为什么卡住？"
    assert history[2]["content"] == "那这个问题以前发生过吗？"


def test_06_image_two_phase_association_and_cleanup(sample_config, mock_glm_client, tmp_path):
    """Test 6: 现场图片两阶段交互（先在群发图暂存、随后文字提问关联消费）及即用即删生命周期 (P1)"""
    dedup_db = str(tmp_path / "test_dedup.db")
    gw = FeishuGateway(config=sample_config, glm_client=mock_glm_client, dedup_db_path=dedup_db)
    gw.send_message = MagicMock(return_value=True)

    dummy_img = tmp_path / "test_two_phase.png"
    dummy_img.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")
    gw.download_resource = MagicMock(return_value=str(dummy_img))

    # 阶段 1: 用户在群聊中先发了一张现场截图，但并未 @ 机器人
    evt_img_only = {
        "header": {"event_id": "evt_img_phase1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_05"}},
            "message": {
                "message_id": "om_msg_img_1",
                "chat_id": "oc_group_two_phase",
                "chat_type": "group",
                "message_type": "image",
                "content": json.dumps({"image_key": "img_phase1_key"}),
                "mentions": [],
            },
        },
    }
    gw._on_message_receive(evt_img_only)

    # 验证阶段 1: 静默暂存，不惊扰群聊
    assert not mock_glm_client.chat_completion.called
    assert not gw.send_message.called
    session_id = "feishu:group:oc_group_two_phase"
    assert session_id in gw.session_recent_images
    assert gw.session_recent_images[session_id]["image_path"] == str(dummy_img)
    assert os.path.exists(str(dummy_img))  # 此时文件必须依然保留

    # 阶段 2: 隔了几秒，用户在群里 @IRO_agent 提问
    evt_text_ask = {
        "header": {"event_id": "evt_text_phase2"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_05"}},
            "message": {
                "message_id": "om_msg_text_2",
                "chat_id": "oc_group_two_phase",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": "@_user_1 这个报错是什么意思？"}),
                "mentions": [{"key": "@_user_1", "name": "IRO_agent"}],
            },
        },
    }
    gw._on_message_receive(evt_text_ask)

    # 验证阶段 2: 成功将先前暂存的截图关联送入 GLM，并回送诊断
    assert mock_glm_client.chat_completion.called
    call_kwargs = mock_glm_client.chat_completion.call_args[1]
    assert call_kwargs["image_path"] == str(dummy_img)
    assert gw.send_message.called

    # 验证消费完成后，图片从近期缓存中移除且本地临时文件被物理删除
    assert session_id not in gw.session_recent_images
    assert not os.path.exists(str(dummy_img))


def test_07_stateful_dedup_and_failure_retry(sample_config, mock_glm_client, tmp_path):
    """Test 7: 状态化去重与失败重试机制 (P0: 失败不丢消息，成功后幂等防重)"""
    dedup_db = str(tmp_path / "test_dedup.db")
    gw = FeishuGateway(config=sample_config, glm_client=mock_glm_client, dedup_db_path=dedup_db)

    # 1. 模拟首次投递，但发送失败（如飞书网络抖动）
    gw.send_message = MagicMock(return_value=False)
    evt = {
        "header": {"event_id": "evt_fail_then_retry"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_retry"}},
            "message": {
                "message_id": "om_msg_retry_1",
                "chat_id": "oc_retry",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": "测试失败重发"}),
            },
        },
    }

    gw._on_message_receive(evt)
    assert gw.send_message.call_count == 1
    # 状态应为 FAILED
    assert gw.dedup.get_status("evt_fail_then_retry") == "FAILED"

    # 2. 飞书长连接重试投递该事件，此时网络恢复（send_message 成功）
    gw.send_message = MagicMock(return_value=True)
    gw._on_message_receive(evt)
    # 允许重新接管处理，状态更新为 COMPLETED
    assert gw.send_message.call_count == 1
    assert gw.dedup.get_status("evt_fail_then_retry") == "COMPLETED"

    # 3. 第三次重复投递已被 COMPLETED 的事件，严格拦截
    gw._on_message_receive(evt)
    # send_message 调用次数依然为 1，未重复发送
    assert gw.send_message.call_count == 1


def test_08_secret_leakage_protection(sample_config, mock_glm_client, tmp_path):
    """Test 8: 凭据隔离与敏感信息绝不外泄"""
    dedup_db = str(tmp_path / "test_dedup.db")
    gw = FeishuGateway(config=sample_config, glm_client=mock_glm_client, dedup_db_path=dedup_db)
    gw.send_message = MagicMock(return_value=True)

    # 模拟模型输出意外包含了 secret
    mock_glm_client.chat_completion.return_value = (
        f"诊断完毕。当前配置密码是 mock_secret_abcdef123456，请注意保护。"
    )

    evt = {
        "header": {"event_id": "evt_sec_01"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_sec"}},
            "message": {
                "message_id": "om_msg_sec",
                "chat_id": "oc_sec",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": "泄密测试"}),
            },
        },
    }

    gw._on_message_receive(evt)

    # 验证最终发送的消息中脱敏
    call_kwargs = gw.send_message.call_args[1] or {}
    sent_text = call_kwargs.get("text") or (gw.send_message.call_args[0][1] if len(gw.send_message.call_args[0]) > 1 else "")
    assert "mock_secret_abcdef123456" not in sent_text
    assert "REDACTED" in sent_text or "******" in sent_text


def test_09_http_gateway_arbitrary_path_rejection():
    """Section 18: 开发测试 HTTP 网关严格拒绝外部任意绝对路径注入"""
    import urllib.request
    from iro_agent.gateway.http_adapter import HttpGatewayAdapter

    adapter = HttpGatewayAdapter(host="127.0.0.1", port=18088)
    adapter.start(block=False)

    try:
        url = "http://127.0.0.1:18088"

        # 尝试注入系统绝对路径
        payload = json.dumps({
            "content": "测试注入",
            "image_path": "C:\\Windows\\System32\\calc.exe",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)

        assert exc_info.value.code == 400
    finally:
        adapter.stop()
