import json
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import requests
from iro_agent.config import get_config, GlmConfig
from iro_agent.security.redactor import redact_secrets
from iro_agent.security.audit import AuditLogger


SYSTEM_PROMPT = """你是工业现场只读智能诊断助手 IRO_agent。

【核心原则：极端精简，拒绝任何废话，直切要害】
1. 【事实查询（查目录/版本/配置/位置/状态）】：
   - 仅用 1 句话直接回答事实本身（例如：“TASK-013 项目目录位于：D:\\当前工作\\维力智能设备\\TASK-013_武汉自动上车显示屏”）。
   - 严禁套用故障诊断格式，严禁输出任何“核心结论/关键依据/排查建议/业务影响”等标题。

2. 【故障排查（为什么报错/卡顿/掉线/异常）】：
   - 严格限定为以下极简结构，总字数严控在 100 字以内：
**核心结论**：一句话讲清直接根因与现状。
**关键依据**：
- 依据1（仅列1~2条最核心事实或日志关键报错，严禁大段贴日志）
**排查建议**：（若有明确物理/配置排查动作则写1条，无必要则不写）
- 建议1

3. 【工具调用与时序分析指引】：
   - 涉及发布记录、版本变更与日志异常时序比对（如“在发布之前还是之后发生”）时，优先调用 diagnostic_pipeline 一键获取完整时间线与时序判定。
   - 核心完整性准则：时序上的先后承接关系并不等同于直接因果关系，客观陈述时间先后即可，严禁无据断言因果。
   - 严禁盲目发起过多无用轮次，用最少且确凿的工具调用直接推导出答案。

4. 【禁止事项】：
   - 严禁任何客套铺垫（如“根据您提供的信息”、“经过调阅分析...”）。
   - 严禁列出系统各模块完好度清单（严禁逐项列出“PLC正常、发货正常...”）。
   - 严禁长篇大论，回答必须短小精悍、一针见血。
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
                    "name": "version_current",
                    "description": "查询当前项目的版本状态（若底层为 Git 则返回当前源码版本；若底层为 WRelease 则返回现场已确认运行版本或 UNKNOWN）",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "version_recent",
                    "description": "查询当前项目最近的版本发布或提交记录列表",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "返回数量，默认 10"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "version_compare",
                    "description": "比对当前项目中两个版本之间的代码 diff 或交付模块变动",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ver_a": {"type": "string", "description": "源版本号或提交哈希"},
                            "ver_b": {"type": "string", "description": "目标版本号或提交哈希"},
                        },
                        "required": ["ver_a", "ver_b"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "version_events",
                    "description": "获取归一化时间戳的版本变动事件列表，供时序比对与分析",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_time": {"type": "string", "description": "可选起始时间 ISO 格式"},
                            "end_time": {"type": "string", "description": "可选结束时间 ISO 格式"},
                        },
                    },
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
            {
                "type": "function",
                "function": {
                    "name": "db_query",
                    "description": "安全只读执行数据库 SELECT 查询（自动拦截写操作与多语句，返回数据行字典列表）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "只读 SQL SELECT 语句"},
                            "max_rows": {"type": "integer", "description": "最多返回行数，默认 20"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "diagnostic_pipeline",
                    "description": "执行端到端自动化诊断流水线：自动串联聚合发布与日志时序(Timeline)、分析故障域(FaultDomain)、评估业务受损级别(P0~P3)与历史相似故障统计",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symptom": {"type": "string", "description": "故障现象或疑问描述"},
                            "log_keyword": {"type": "string", "description": "可选的错误日志检索关键词"},
                        },
                        "required": ["symptom"],
                    },
                },
            },
        ]

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        image_path: Optional[str] = None,
        max_tool_rounds: int = 8,
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
                ext = Path(image_path).suffix.lower()
                mime_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                    ".bmp": "image/bmp",
                }
                mime = mime_map.get(ext, "image/jpeg")
                img_content = [
                    {"type": "text", "text": formatted_messages[-1]["content"]},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
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
            "Connection": "close",
        }

        for round_idx in range(max_tool_rounds):
            is_last = (round_idx >= max_tool_rounds - 1)
            payload = {
                "model": self.glm_cfg.model,
                "messages": formatted_messages,
                "max_tokens": 800,
            }
            if not is_last:
                payload["tools"] = self.tools_schema
                payload["tool_choice"] = "auto"
            else:
                formatted_messages.append({"role": "user", "content": "请基于当前已获得的事实数据，立即输出最终简明回答。"})
            import time
            data = None
            last_err = None
            for attempt in range(3):
                try:
                    resp = requests.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=self.glm_cfg.timeout,
                    )
                    if resp.status_code in (401, 403):
                        last_err = requests.exceptions.HTTPError(f"认证失败 ({resp.status_code}): {resp.text}", response=resp)
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(1.0 * (attempt + 1))

            if data is None:
                self.audit.record(tool_name="GlmClient", operation="api_call", result_summary=f"请求失败: {last_err}", status="ERROR")
                raise RuntimeError(f"GLM-5.3-Flash API 请求失败: {last_err}")

            choice = data["choices"][0]
            message = choice["message"]
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                # 最终回答
                final_text = (message.get("content") or "").strip()
                if final_text:
                    return redact_secrets(final_text)
                # 若无工具调用且内容为空，强制注入催促提示
                formatted_messages.append({"role": "user", "content": "请基于以上查询结果，直接给出最终的简短结论。"})
                continue

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

                tool_res_str = json.dumps(tool_res, ensure_ascii=False)
                if len(tool_res_str) > 1200:
                    tool_res_str = tool_res_str[:1200] + "...[已截断过长事实数据]"

                formatted_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": redact_secrets(tool_res_str),
                })

        try:
            resp = requests.post(
                url,
                headers=headers,
                json={
                    "model": self.glm_cfg.model,
                    "messages": formatted_messages + [{"role": "user", "content": "请依据以上所有检索事实，直接回答用户最初的问题。"}],
                    "max_tokens": 800,
                },
                timeout=self.glm_cfg.timeout,
            )
            ans = resp.json()["choices"][0]["message"].get("content", "").strip()
            if ans:
                return redact_secrets(ans)
        except Exception:
            pass

        return "诊断轮次达到上限，请缩小问题范围或指定排查维度。"
