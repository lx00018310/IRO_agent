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
1. 【事实查询（查目录/版本/配置/位置/状态/最新业务事实）】：
   - 仅用 1 句话直接回答事实本身（例如：“TASK-013 项目目录位于：D:\\当前工作\\维力智能设备\\TASK-013_武汉自动上车显示屏”）。
   - 严禁套用故障诊断格式，严禁输出任何“核心结论/关键依据/排查建议/业务影响”等标题。

2. 【故障排查（为什么报错/卡顿/掉线/异常）】：
   - 严格限定为以下极简结构，总字数严控在 100 字以内：
**核心结论**：一句话讲清直接根因与现状。
**关键依据**：
- 依据1（仅列1~2条最核心事实或日志关键报错，严禁大段贴日志）
**排查建议**：（若有明确物理/配置排查动作则写1条，无必要则不写）
- 建议1

3. 【业务概念与权威数据源原则 (Source of Truth)】：
   - 涉及工控业务事实（如“最新一托”、“调度信息”、“当前月台”、“回执确认”）查询时，**必须优先调用 project_lookup(query)** 获取项目的权威数据源（Source of Truth）和防踩坑告警。
   - 依据 project_lookup 的指导确定权威主表，严禁将历史通信流水（如 callback_receipt）误用为当前月台实时物理状态的主源。
   - 对表字段不确定时，可调用 db_describe_table(table_name) 探查字段类型，再发起精准的 db_query。

4. 【时序分析与数据新鲜度裁决】：
   - 工业诊断必须以“当前最新时刻”为基准。
   - 查询“最新”数据时，必须根据时间字段或自增主键使用 ORDER BY ... DESC LIMIT N（如 ORDER BY id DESC）。
   - 若主状态表存在近期的有效状态，严禁将数天前的历史异步日志与当前状态混为一谈。
   - 时序先后关系不等同于直接因果关系，客观陈述事实即可，严禁无据断言。

5. 【禁止事项】：
   - 严禁任何客套铺垫，严禁逐项列出完好度清单。
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
                    "name": "project_lookup",
                    "description": "检索当前项目的业务知识蓝图与权威事实源 (Source of Truth)。涉及业务概念（如最新一托、调度回执、月台任务等）或数据库查询前，优先调用此工具获取权威表和避坑告警",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "业务关键词或概念（如 '最新一托', '调度信息', '11号月台'）"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "db_list_tables",
                    "description": "只读列出当前数据库中所有可用的业务表名称",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "db_describe_table",
                    "description": "只读查看指定数据表的列名、数据类型、主键与结构定义",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "需要探查的数据表名"},
                        },
                        "required": ["table_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "db_query",
                    "description": "安全只读执行数据库 SELECT 查询（自动拦截写操作与多语句，返回数据行字典列表）。在执行查询前，请先调用 project_lookup 明确权威主表",
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
                    "name": "investigation_pipeline",
                    "description": "执行假设驱动与动态优先级故障排查套件 (Investigation Harness)：针对现场异常（PLC/机器人/配置/网络/应用崩溃）制定竞争假设与证据规划，快速收敛根因，数字证据耗尽时生成现场硬件物理排查清单",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symptom": {"type": "string", "description": "现场故障现象或疑问描述"},
                        },
                        "required": ["symptom"],
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
            {
                "type": "function",
                "function": {
                    "name": "code_trace_api_to_table",
                    "description": "基于代码拓扑调用图，从 API 路由全链路追踪到底层数据表 (API -> Controller -> Service -> Mapper -> SQL/Table)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "api_path": {"type": "string", "description": "接口路由或 URL 路径片段（如 /api/orders, /callback）"},
                        },
                        "required": ["api_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "code_find_table_usage",
                    "description": "基于代码拓扑关系图，反向查询指定数据表在代码中的读写、映射与调用方",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "需要追溯的数据表名"},
                        },
                        "required": ["table_name"],
                    },
                },
            },
        ]

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        image_path: Optional[str] = None,
        max_tool_rounds: int = 8,
        verbose: bool = False,
    ) -> str:
        """执行多轮对话与工具调用循环"""
        # 脱敏所有用户输入并动态注入系统时间锚点
        import time
        current_time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        sys_content = f"{SYSTEM_PROMPT}\n【工控机当前时间锚点】: {current_time_str}\n"
        formatted_messages = [{"role": "system", "content": sys_content}]
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
            if verbose:
                msg_thought = (message.get("content") or "").strip()
                if msg_thought:
                    print(f"\n[模型思考/意图说明]:\n{msg_thought}")

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                if verbose:
                    print(f"\n[工具调用 (Round {round_idx + 1})] -> {func_name}")
                    print(f"  ├─ 入参: {json.dumps(args, ensure_ascii=False)}")

                handler = self.tool_handlers.get(func_name)
                if handler:
                    try:
                        tool_res = handler(**args)
                    except Exception as err:
                        tool_res = {"error": str(err)}
                else:
                    tool_res = {"error": f"工具 {func_name} 未实现"}

                tool_res_str = json.dumps(tool_res, ensure_ascii=False, default=str)
                if verbose:
                    preview = tool_res_str if len(tool_res_str) <= 1000 else tool_res_str[:1000] + f"... [已截断，共 {len(tool_res_str)} 字符]"
                    print(f"  └─ 返回: {preview}")

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

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1500) -> str:
        """纯文本直接调用大模型 (用于无工具调用的分析与提纯)"""
        if not self.glm_cfg.api_key or self.glm_cfg.api_key == "YOUR_GLM_API_KEY":
            raise ValueError("未配置有效的 GLM API Key。请在 config.json 中配置 glm.api_key。")

        url = f"{self.glm_cfg.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.glm_cfg.api_key}",
            "Content-Type": "application/json",
            "Connection": "close",
        }
        sys_msg = system_prompt or "你是一个严谨客观的工业系统代码架构分析专家。直接回答问题，输出准确真实结论。"
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": self.glm_cfg.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=self.glm_cfg.timeout)
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["choices"][0]["message"].get("content", "").strip()
        return redact_secrets(raw_text)

    def generate_structured_json(
        self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 2000
    ) -> Dict[str, Any]:
        """要求大模型严格输出符合 JSON 规范的结构化字典"""
        sys_msg = (system_prompt or "") + "\n【重要指令】：必须仅输出合法的 JSON 对象，严禁包裹 markdown 代码块外的解释废话。直接以 { 开头。"
        raw_output = self.generate_text(prompt=prompt, system_prompt=sys_msg, max_tokens=max_tokens)

        # 尝试提取 json 内容
        clean = raw_output.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        # 查找首个 { 到最后一个 }
        start_idx = clean.find("{")
        end_idx = clean.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            clean = clean[start_idx : end_idx + 1]

        try:
            return json.loads(clean)
        except Exception as e:
            self.audit.record(tool_name="GlmClient", operation="parse_json", result_summary=f"JSON解析异常: {e}, 原文: {raw_output[:200]}", status="WARN")
            return {"raw_response": raw_output, "error": f"JSON parse error: {e}"}

