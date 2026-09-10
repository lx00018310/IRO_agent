import re
from typing import List, Tuple

# 敏感词匹配正则规则
SECRET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 私钥证书
    (re.compile(r'-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----', re.IGNORECASE), '[REDACTED_PRIVATE_KEY]'),
    # 连接串中的密码：postgres://user:password@host
    (re.compile(r'(postgres(?:ql)?|mysql|redis|mongodb)://([^:]+):([^@/]+)@', re.IGNORECASE), r'\1://\2:[REDACTED_DB_PASSWORD]@'),
    # API Key / Token / Secret 赋值
    (re.compile(r'((?:api[_-]?key|bearer|access[_-]?token|auth[_-]?token|secret[_-]?key|jwt|app[_-]?secret|feishu[_-]?secret)\s*[:=：]\s*["\']?)([a-zA-Z0-9_\-\.]{8,})(["\']?)', re.IGNORECASE), r'\1[REDACTED_SECRET]\3'),
    # 中英文密码赋值
    (re.compile(r'((?:password|passwd|pwd|口令|密码)\s*[:=：是为]\s*["\']?)([^\s,"\'};{]+)(["\']?)', re.IGNORECASE), r'\1[REDACTED_PASSWORD]\3'),
]


def redact_secrets(text: str) -> str:
    """对即将发送给大模型或存入日志、网关回送的文本进行敏感信息脱敏"""
    if not text:
        return ""
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)

    # 动态匹配全局生效配置中的敏感凭据明文进行保底抹除
    try:
        from iro_agent.config import get_config
        cfg = get_config()
        secrets_to_mask = [
            cfg.glm.api_key,
            cfg.feishu.app_secret,
            cfg.database.password,
        ]
        for s in secrets_to_mask:
            if s and len(s) >= 6 and s not in ("YOUR_GLM_API_KEY", "YOUR_FEISHU_APP_SECRET"):
                result = result.replace(s, "[REDACTED_SECRET]")
    except Exception:
        pass

    return result


class SecretRedactor:
    """敏感信息脱敏器封装"""

    @staticmethod
    def redact(text: str) -> str:
        return redact_secrets(text)

