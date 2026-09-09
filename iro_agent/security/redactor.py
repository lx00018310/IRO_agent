import re
from typing import List, Tuple

# 敏感词匹配正则规则
SECRET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 私钥证书
    (re.compile(r'-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----', re.IGNORECASE), '[REDACTED_PRIVATE_KEY]'),
    # 连接串中的密码：postgres://user:password@host
    (re.compile(r'(postgres(?:ql)?|mysql|redis|mongodb)://([^:]+):([^@/]+)@', re.IGNORECASE), r'\1://\2:[REDACTED_DB_PASSWORD]@'),
    # API Key / Token 赋值
    (re.compile(r'((?:api[_-]?key|bearer|access[_-]?token|auth[_-]?token|secret[_-]?key|jwt)\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{8,})(["\']?)', re.IGNORECASE), r'\1[REDACTED_SECRET]\3'),
    # 中英文密码赋值
    (re.compile(r'((?:password|passwd|pwd|口令|密码)\s*[:=：]\s*["\']?)([^\s,"\'};{]+)(["\']?)', re.IGNORECASE), r'\1[REDACTED_PASSWORD]\3'),
]


def redact_secrets(text: str) -> str:
    """对即将发送给大模型或存入日志的文本进行敏感信息脱敏"""
    if not text:
        return ""
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result
