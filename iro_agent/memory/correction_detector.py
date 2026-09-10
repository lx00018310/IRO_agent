import re
from typing import Optional, Dict, Any


class CorrectionDetector:
    """纠错与显式记忆指示检测器：准确识别用户对 Agent 的指正、事实源修正及运维原则交代"""

    # 典型纠错与指导短语前缀或关键词
    CORRECTION_PATTERNS = [
        r"(?:^|[\s,，、;；!！。])(?:请?记住|记好了|记下)[：:\s]*(.+)$",
        r"(?:^|[\s,，、;；!！。])(?:以后(?:应该|要|必须|严禁|不能)|正确做法是)[：:\s]*(.+)$",
        r"(?:^|[\s,，、;；!！。])(?:不是这[个张份]|你查错了|查错了)[,，\s]*(?:应该|是|正确的是|实际是)?[：:\s]*(.+)$",
        r"(?:^|[\s,，、;；!！。])(?:这里|此项|数据)?(?:要|必须)?以[：:\s]*(.+)为准",
        r"(?:^|[\s,，、;；!！。])这个表不是用来[：:\s]*(.+)(?:的)?",
        r"(?:^|[\s,，、;；!！。])(?:正确的是|事实是|实际上是)[：:\s]*(.+)$",
        r"(?:^|[\s,，、;；!！。])这个配置在[：:\s]*(.+)$",
    ]

    # 排除纯提问模式（如“记住密码怎么设置？”、“你是不是查错了？”）
    QUESTION_EXCLUSIONS = [
        r"\?$",
        r"？$",
        r"^(?:是不是|能否|怎么|如何|为什么|为啥|凭什么)",
    ]

    @classmethod
    def detect(cls, text: str) -> Optional[Dict[str, Any]]:
        """检测输入文本是否包含纠错或需持久化记住的业务/排查原则。若命中则提取结构化数据，否则返回 None"""
        cleaned = text.strip()
        if not cleaned:
            return None

        # 检查是否为疑问句
        for eq in cls.QUESTION_EXCLUSIONS:
            if re.search(eq, cleaned):
                # 如果包含“记住：”则优先视作记忆指令，除非通篇是疑问
                if not re.search(r"^(?:请?记住|记好了)[：:]", cleaned):
                    return None

        matched_rule_text: Optional[str] = None
        detected_pattern_type = "operation_rule"

        # 逐一正则匹配
        for pattern in cls.CORRECTION_PATTERNS:
            m = re.search(pattern, cleaned, re.IGNORECASE)
            if m:
                extracted = m.group(1).strip()
                if len(extracted) >= 3:
                    matched_rule_text = extracted
                    break

        if not matched_rule_text:
            return None

        # 剥离末尾标点
        matched_rule_text = re.sub(r"[。！!]+$", "", matched_rule_text).strip()

        # 根据关键词判定 rule_type 与 topic
        rule_type = "operation_rule"
        topic = "general"

        lower_raw = cleaned.lower()
        if any(k in lower_raw for k in ["配置", "config", "settings", "json", "yml", "yaml", "properties", "grep", "目录"]):
            rule_type = "configuration_rule"
            topic = "configuration_lookup"
        elif any(k in lower_raw for k in ["以...为准", "为准", "主源", "主表", "权威", "真实状态"]):
            rule_type = "source_of_truth_correction"
            topic = "source_of_truth"
        elif any(k in lower_raw for k in ["表不是", "这张表", "查表", "数据库"]):
            rule_type = "business_semantic_correction"
            topic = "database_semantics"
        elif any(k in lower_raw for k in ["grep", "工具", "查询应该", "排查应该", "遍历"]):
            rule_type = "tool_usage_rule"
            topic = "investigation_operation"

        return {
            "rule_type": rule_type,
            "topic": topic,
            "rule_text": matched_rule_text,
            "reason": f"操作员修正交互: {cleaned}",
            "source_type": "user_correction",
            "confidence": "confirmed",
            "status": "active",
        }

    @classmethod
    def format_honesty_response(
        cls,
        rule_id: Optional[str],
        rule_text: str,
        error: Optional[str] = None,
    ) -> str:
        """落实记忆诚实原则 (Memory Honesty Rule)：持久化成功方可说明已记住，失败时明确据实告知"""
        if rule_id and not error:
            return (
                f"**学习记忆已持久化记住该原则**\n"
                f"- 规则编号: `{rule_id}`\n"
                f"- 规则内容: {rule_text}\n"
                f"- 生效状态: 已成功写入本地学习记忆库并在未来相关排查中自动生效（跨会话与进程重启不丢失）。"
            )
        else:
            err_msg = error or "未知存储异常"
            return (
                f"**学习记忆持久化失败**\n"
                f"- 规则内容: {rule_text}\n"
                f"- 失败原因: {err_msg}\n"
                f"- 提示: 该原则尚未成功写入磁盘，无法保证跨会话持久化。"
            )

