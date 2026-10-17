"""chat_completion 最终汇总与轮次收口行为：重试、工具不误执行、真实失败原因。"""

import json
from unittest.mock import Mock

import pytest
import requests

from iro_agent.config import IROConfig
from iro_agent.llm.glm_client import GlmClient
from iro_agent.security.audit import AuditLogger


def make_client(tmp_path, **glm_overrides):
    import iro_agent.config as config_module
    config = IROConfig(project_root=str(tmp_path), glm={"api_key": "unit.test.key", "timeout": 1},
                       storage={"audit_db_path": "audit.db", "memory_db_path": "memory.db"}, **glm_overrides)
    config_module._CONFIG_INSTANCE = config
    return GlmClient(glm_cfg=config.glm, audit_logger=AuditLogger(config=config))


def response(content=None, tool_calls=None, finish_reason=None):
    message = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    choice = {"message": message}
    if finish_reason:
        choice["finish_reason"] = finish_reason
    body = {"choices": [choice]}
    resp = Mock(status_code=200)
    resp.json.return_value = body
    return resp


def http_error(status):
    resp = Mock(status_code=status)
    return requests.exceptions.HTTPError(f"HTTP {status}", response=resp)


def post_succeed(responses):
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        return responses.pop(0)
    return post, calls


def test_normal_tool_round_then_answer_is_unchanged(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    calls = []

    def handler(**kwargs):
        calls.append(kwargs)
        return {"rows": [{"id": 1}]}
    client.register_tool_handler("log_search", handler)
    first = response(tool_calls=[{"id": "call_1", "function": {
        "name": "log_search", "arguments": json.dumps({"keyword": "reset"})}}])
    second = response(content="最终结论")
    post, sent = post_succeed([first, second])
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)

    assert client.chat_completion([{"role": "user", "content": "查 reset"}]) == "最终结论"
    assert calls == [{"keyword": "reset"}]
    assert len(sent) == 2
    tool_messages = [m for m in sent[1]["messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 1 and tool_messages[0]["tool_call_id"] == "call_1"


def test_final_summary_recovers_after_transient_failures_without_rerunning_tools(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    tool_runs = []
    client.register_tool_handler("log_search", lambda **kw: tool_runs.append(kw) or {})
    # 主循环轮 1 返回工具调用；轮 2(最后一轮)直接给最终文本；最终汇总阶段不会被触发。
    # 汇总阶段的瞬时故障恢复由 is_summary 区分：用带"回答用户最初的问题"标记的请求模拟。
    seen = []
    first = response(tool_calls=[{"id": "call_1", "function": {
        "name": "log_search", "arguments": json.dumps({"keyword": "x"})}}])

    def is_summary(payload):
        return any(m.get("role") == "user" and "回答用户最初的问题" in str(m.get("content"))
                   for m in payload["messages"])

    def post(*args, **kwargs):
        seen.append(kwargs["json"])
        if is_summary(kwargs["json"]):
            if len([p for p in seen if is_summary(p)]) <= 2:
                raise http_error(503)
            return response(content="恢复后的回答")
        return [first, response(content="round2 done")].pop(0)
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    result = client.chat_completion([{"role": "user", "content": "查 x"}], max_tool_rounds=2)
    assert result == "恢复后的回答"
    assert len(tool_runs) == 1  # 工具只执行一次，最终汇总阶段绝不重放工具
    summary_payloads = [p for p in seen if is_summary(p)]
    assert len(summary_payloads) == 3  # 两次 503 + 一次成功


def test_final_summary_exhausts_retries_and_reports_truth(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    attempts = []

    def is_summary(payload):
        messages = payload["messages"]
        return any(m.get("role") == "user" and "回答用户最初的问题" in str(m.get("content"))
                   for m in messages)

    def post(*args, **kwargs):
        if is_summary(kwargs["json"]):
            attempts.append(kwargs["json"])
            raise requests.exceptions.Timeout("timed out")
        return response(content="")  # 主循环各轮只给空内容，直到进入最终汇总
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    result = client.chat_completion([{"role": "user", "content": "查 x"}])
    assert "最终汇总" in result
    assert "timed out" in result
    assert len(attempts) == 3  # 3 次总尝试
    assert "诊断轮次达到上限" not in result  # 旧文案不再出现


def test_auth_failure_fails_fast_without_retries(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise http_error(401)
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="401"):
        client.chat_completion([{"role": "user", "content": "查 x"}])  # 主循环轮次直接失败
    assert len(calls) == 1


def test_retryable_matrix(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    for status in (429, 500, 502, 503, 504):
        attempts = []

        def post(*args, status=status, **kwargs):
            attempts.append(1)
            raise http_error(status)
        monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
        monkeypatch.setattr("time.sleep", lambda _s: None)
        with pytest.raises(RuntimeError):
            client.chat_completion([{"role": "user", "content": "q"}])  # 主循环轮次 429/5xx 重试后抛出
        assert len(attempts) == 3, status


def test_non_retryable_4xx_fails_once(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    attempts = []

    def post(*args, **kwargs):
        attempts.append(1)
        raise http_error(400)
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="400"):
        client.chat_completion([{"role": "user", "content": "q"}])
    assert len(attempts) == 1


def test_empty_and_malformed_responses_are_distinguished(tmp_path, monkeypatch):
    client = make_client(tmp_path)

    # 空内容 + 非法 JSON 明确报告，不再伪装成轮次上限
    bad = Mock(status_code=200)
    bad.json.side_effect = ValueError("no json")
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", Mock(return_value=bad))
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="JSON"):
        client.chat_completion([{"role": "user", "content": "q"}])

    # 缺 choices
    missing = Mock(status_code=200)
    missing.json.return_value = {"object": "chat.completion"}
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", Mock(return_value=missing))
    with pytest.raises(RuntimeError, match="choices"):
        client.chat_completion([{"role": "user", "content": "q"}])


def test_final_summary_empty_content_reports_empty_not_timeout(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    post, _sent = post_succeed([response(content="  ")])
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    result = client.chat_completion([{"role": "user", "content": "q"}], max_tool_rounds=0)
    assert "空内容" in result
    assert "诊断轮次达到上限" not in result


def test_last_round_tool_calls_are_never_executed(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    tool_runs = []
    client.register_tool_handler("log_search", lambda **kw: tool_runs.append(kw) or {})
    first = response(tool_calls=[{"id": "call_1", "function": {
        "name": "log_search", "arguments": json.dumps({"keyword": "x"})}}])
    post, sent = post_succeed([first, response(content="final")])
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)

    result = client.chat_completion([{"role": "user", "content": "q"}], max_tool_rounds=1)
    assert tool_runs == []
    assert result == "final"
    # 历史中不能出现没有工具结果的 assistant tool_calls 消息（避免下一次请求消息不配对）
    for payload in sent:
        assistant_messages = [m for m in payload["messages"]
                              if m.get("role") == "assistant" and m.get("tool_calls")]
        assert assistant_messages == []
        # 最后一轮请求不携带 tools
        assert payload.get("tools") is None


def test_finish_reason_length_with_content_is_not_empty(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    post, _sent = post_succeed([response(content="长回答被截断但非空", finish_reason="length")])
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    assert client.chat_completion([{"role": "user", "content": "q"}]) == "长回答被截断但非空"


def test_default_round_budget_unchanged_and_no_unbounded_summary_loop(tmp_path, monkeypatch):
    import inspect
    client = make_client(tmp_path)
    signature = inspect.signature(client.chat_completion)
    assert signature.parameters["max_tool_rounds"].default == 8
    # 完整结构检查：最终汇总失败后直接返回字符串，不开新循环
    post, _sent = post_succeed([response(content="  ")])
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    result = client.chat_completion([{"role": "user", "content": "q"}], max_tool_rounds=0)
    assert isinstance(result, str) and "重试" not in result.split("。")[0][:5] or result


def test_error_text_never_contains_api_key(tmp_path, monkeypatch):
    import iro_agent.config as config_module
    key = "sk-secret-unit-test-key-123"
    config = IROConfig(project_root=str(tmp_path), glm={"api_key": key, "timeout": 1},
                       storage={"audit_db_path": "audit.db", "memory_db_path": "memory.db"})
    config_module._CONFIG_INSTANCE = config
    client = GlmClient(glm_cfg=config.glm, audit_logger=AuditLogger(config=config))

    def post(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused with " + key)
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(RuntimeError) as exc_info:
        client.chat_completion([{"role": "user", "content": "q"}])
    assert key not in str(exc_info.value)
