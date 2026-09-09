import os
from pathlib import Path
from typing import Optional
from iro_agent.config import IROConfig, get_config


class SecurityPolicyError(PermissionError):
    """违反安全只读策略时抛出的异常"""
    pass


FORBIDDEN_OPERATIONS = {
    "write", "create", "update", "delete", "rm", "drop", "alter",
    "truncate", "insert", "commit", "push", "checkout", "rebase",
    "merge", "pull", "chmod", "chown", "exec", "execute", "spawn",
}


def assert_read_only_operation(operation: str) -> None:
    """校验操作名称，确保严禁任何写或执行行为"""
    op_lower = operation.lower().strip()
    for forbidden in FORBIDDEN_OPERATIONS:
        if forbidden in op_lower:
            raise SecurityPolicyError(f"安全策略拦截：禁止执行修改类操作 '{operation}'")


def validate_read_path(raw_path: str | Path, config: Optional[IROConfig] = None) -> Path:
    """验证路径是否在只读白名单范围内，严防路径穿越与非法探测"""
    cfg = config or get_config()
    allowed_dirs = cfg.get_effective_allowed_paths()

    if not allowed_dirs:
        raise SecurityPolicyError("安全策略拦截：未配置任何允许访问的有效只读目录白名单")

    target = Path(raw_path).resolve()

    # 检查是否为已知白名单目录或其子目录/文件
    is_allowed = False
    for allowed in allowed_dirs:
        allowed_path = Path(allowed).resolve()
        try:
            target.relative_to(allowed_path)
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        raise SecurityPolicyError(
            f"安全策略拦截：目标路径 '{target}' 不在配置的只读白名单中。允许范围: {allowed_dirs}"
        )

    return target
