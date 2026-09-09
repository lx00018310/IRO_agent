import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config
from iro_agent.security.policy import validate_read_path, SecurityPolicyError
from iro_agent.security.audit import AuditLogger


class GitReader:
    """严格只读 Git 阅读器，严禁任何写或变更操作"""

    ALLOWED_SUBCOMMANDS = {"log", "show", "diff", "blame", "status", "branch", "rev-parse"}

    def __init__(self, repo_dir: Optional[str | Path] = None, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        raw_repo = repo_dir or self.config.project_root
        self.repo_dir = validate_read_path(raw_repo, self.config)
        self.audit = audit_logger or AuditLogger()

    def _run_git_readonly(self, args: List[str]) -> str:
        if not args:
            raise SecurityPolicyError("未提供 Git 子命令")
        subcmd = args[0].lower()
        if subcmd not in self.ALLOWED_SUBCOMMANDS:
            self.audit.record(
                tool_name="GitReader",
                operation=f"git_{subcmd}",
                target=str(self.repo_dir),
                result_summary="非只读 Git 命令被拦截",
                status="REJECTED",
            )
            raise SecurityPolicyError(f"GitReader 仅允许执行只读查询操作，禁止调用 '{subcmd}'")

        cmd = ["git"] + args
        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.repo_dir),
                capture_output=True,
                check=False,
            )
            # 兼容 Windows GBK / UTF-8
            stdout = res.stdout.decode("utf-8", errors="replace")
            stderr = res.stderr.decode("utf-8", errors="replace")

            status = "SUCCESS" if res.returncode == 0 else "ERROR"
            self.audit.record(
                tool_name="GitReader",
                operation=f"git {subcmd}",
                target=str(self.repo_dir),
                result_summary=f"退出码 {res.returncode}",
                status=status,
                details=f"Cmd: {' '.join(cmd)}\nStderr: {stderr[:200]}",
            )
            if res.returncode != 0:
                raise RuntimeError(f"Git 命令执行失败: {stderr.strip()}")
            return stdout
        except Exception as e:
            if not isinstance(e, SecurityPolicyError):
                self.audit.record(
                    tool_name="GitReader",
                    operation=f"git {subcmd}",
                    target=str(self.repo_dir),
                    result_summary=str(e),
                    status="ERROR",
                )
            raise

    def get_recent_commits(self, limit: int = 20, path: Optional[str] = None) -> List[Dict[str, str]]:
        """获取最近提交列表，支持按特定文件路径过滤"""
        args = ["log", f"-n{limit}", "--pretty=format:%H%x09%an%x09%ad%x09%s", "--date=iso"]
        if path:
            args.extend(["--", path])
        raw = self._run_git_readonly(args)
        commits = []
        for line in raw.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 4:
                commits.append({
                    "commit": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "summary": parts[3],
                })
        return commits

    def show_commit(self, commit_hash: str) -> str:
        """查看指定提交的完整详情与 diff"""
        safe_hash = commit_hash.strip().replace(";", "").replace("&", "")
        return self._run_git_readonly(["show", safe_hash])

    def get_diff(self, commit_a: str, commit_b: str = "HEAD") -> str:
        """查看两个 commit 之间的差异"""
        return self._run_git_readonly(["diff", commit_a.strip(), commit_b.strip()])

    def get_blame(self, file_path: str, start_line: int = 1, end_line: int = 50) -> str:
        """查看指定代码片段的作者与提交溯源"""
        validate_read_path(Path(self.repo_dir) / file_path, self.config)
        return self._run_git_readonly(["blame", f"-L{start_line},{end_line}", "--", file_path])

    def get_status(self) -> str:
        """查看仓库状态与当前所在分支/HEAD"""
        return self._run_git_readonly(["status", "-sb"])
