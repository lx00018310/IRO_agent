import json
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import requests
from iro_agent.config import get_config, GlmConfig
from iro_agent.security.redactor import redact_secrets
from iro_agent.security.audit import AuditLogger


SYSTEM_PROMPT = """你是由 DeepMind / 工业技术团队指导构建的工业软件只读智能诊断助手：IRO_agent (Industrial Read-Only Agent)。
你的核心原则是：
1. 【严格只读】你只有只读查询工具，绝不能修改生产代码、配置、数据库或发布包。
2. 【业务语言优先】向非技术用户、项目经理与现场工程师汇报时，必须使用通俗易懂的工业业务语言，禁止直接倾倒底层代码、长堆栈或技术黑话。
3. 【证据链驱动】每个诊断推断必须有确凿事实凭证（Log 错误、WRelease 变更指纹、Git 提交等）。证据不足时直接承认“证据不足”，严禁幻觉推断。
4. 【标准输出结构】
   - 诊断结论
   - 业务影响分析 (P0~P3级别)
   - 关键事实与研判证据
   - 历史相似案例统计
   - 建议现场排查步骤
   - 诊断置信度 (High / Medium / Low / Insufficient evidence)
"""


class GlmClient:
    """GLM-5.3-Flash 大模型调用客户端：集成工具调用 (Tool Calling)、图文多模态诊断与敏感信息脱敏"""

    def __init__(self, glm_cfg: Optional[GlmConfig] = None, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        self.glm_cfg = glm_cfg or self.config.glm
        self.audit = audit_logger or AuditLogger()
        self.tools_schema = self._build_tools_schema()
        self.tool_handlers: Dict[str, Callable] = {}

    def register_tool_handler(self, name: str, handler: Callable) -> None:
        self.tool_handlers[name] = handler

    def _build_tools_schema(self) -> List[Dict[str, Any]]:
        """构建 OpenAI / GLM 兼容的只读工具定义清单"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "wrelease_compare",
                    "description": "比对两个 WRelease 交付版本的模块 SHA256 变动情况",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ver_a": {"type": "string", "description": "源版本号或文件名"},
                            "ver_b": {"type": "string", "description": "目标版本号或文件名"},
                        },
                        "required": ["ver_a", "ver_b"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "wrelease_list",
                    "description": "列出所有可用的 WRelease 历史版本包",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "log_search",
                    "description": "在工控机运行日志中组合检索错误、关键词与时间窗口",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "关键词"},
                            "level": {"type": "string", "description": "日志级别 (ERROR/WARN)"},
                            "max_results": {"type": "integer", "description": "最大条数"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_recent_commits",
                    "description": "查询源代码仓库最近的提交记录",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "返回数量"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "code_search",
                    "description": "在源代码中检索类、函数或配置常量",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "检索关键字"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_similar_stats",
                    "description": "查询过去 90 天内相似历史故障的发生频次与归因分布",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "故障现象关键词"},
                        },
                        "required": ["keyword"],
                    },
                },
            },
        ]

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        image_path: Optional[str] = None,
        max_tool_rounds: int = 5,
    ) -> str:
        """执行多轮对话与工具调用循环"""
        # 脱敏所有用户输入
        formatted_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                content = redact_secrets(content)
            formatted_messages.append({"role": m["role"], "content": content})

        # 多模态图片支持
        if image_path:
            with open(image_path, "rb") as img_file:
                b64 = base64.b64encode(img_file.read()).decode("utf-8")
                img_content = [
                    {"type": "text", "text": formatted_messages[-1]["content"]},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]
                formatted_messages[-1]["content"] = img_content

        # 检查是否配置有效 API Key
        if not self.glm_cfg.api_key or self.glm_cfg.api_key == "YOUR_GLM_API_KEY":
            raise ValueError("未配置有效的 GLM API Key。请在 config.json 中配置 glm.api_key 后再使用诊断功能。")

        # 发起 GLM API 调用
        url = f"{self.glm_cfg.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.glm_cfg.api_key}",
            "Content-Type": "application/json",
        }

        for _ in range(max_tool_rounds):
            payload = {
                "model": self.glm_cfg.model,
                "messages": formatted_messages,
                "tools": self.tools_schema,
                "tool_choice": "auto",
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.glm_cfg.timeout)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.audit.record(tool_name="GlmClient", operation="api_call", result_summary=f"请求失败: {e}", status="ERROR")
                raise RuntimeError(f"GLM-5.3-Flash API 请求失败: {e}")

            choice = data["choices"][0]
            message = choice["message"]
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                # 最终回答
                final_text = message.get("content", "")
                return redact_secrets(final_text)

            # 执行模型请求的只读工具
            formatted_messages.append(message)
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                handler = self.tool_handlers.get(func_name)
                if handler:
                    try:
                        tool_res = handler(**args)
                    except Exception as err:
                        tool_res = {"error": str(err)}
                else:
                    tool_res = {"error": f"工具 {func_name} 未实现"}

                formatted_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": redact_secrets(json.dumps(tool_res, ensure_ascii=False)),
                })

        return "诊断轮次达到上限，请缩小问题范围或指定排查维度。"
