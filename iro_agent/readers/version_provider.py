from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from iro_agent.config import get_config, IROConfig
from iro_agent.security.audit import AuditLogger
from iro_agent.readers.git_reader import GitReader
from iro_agent.readers.wrelease_reader import WReleaseReader


class VersionReader(ABC):
    """统一版本读取器抽象基类：对上层掩盖 GitReader 与 WReleaseReader 的实现细节"""

    @abstractmethod
    def is_available(self) -> bool:
        """检测当前版本源在现场是否真实可用"""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """返回当前提供者名称，如 'GitReader' 或 'WReleaseReader'"""
        pass

    @abstractmethod
    def get_current_version(self) -> Optional[Dict[str, Any]]:
        """获取当前已确认的生产运行版本，未检测到时必须标为 UNKNOWN，严禁冒充"""
        pass

    @abstractmethod
    def get_recent_versions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的版本或提交列表"""
        pass

    @abstractmethod
    def get_version_events(
        self, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """提取归一化时间戳的版本变动事件，供 Incident Timeline 消费"""
        pass

    @abstractmethod
    def compare_versions(self, ver_a: str, ver_b: str) -> Dict[str, Any]:
        """比对两个版本之间的代码 diff 或交付物模块变动"""
        pass

    @abstractmethod
    def get_version_details(self, version_id: str) -> Optional[Dict[str, Any]]:
        """获取指定版本的详细信息"""
        pass


class GitReaderAdapter(VersionReader):
    """GitReader 统一适配器"""

    def __init__(self, git_reader: Optional[GitReader] = None, audit_logger: Optional[AuditLogger] = None):
        self.reader = git_reader or GitReader(audit_logger=audit_logger)

    def is_available(self) -> bool:
        try:
            repo_path = Path(self.reader.repo_dir)
            if not (repo_path.is_dir() and (repo_path / ".git").exists()):
                return False
            # 验证 git 命令能够正常工作
            self.reader.get_status()
            return True
        except Exception:
            return False

    def get_provider_name(self) -> str:
        return "GitReader"

    def get_current_version(self) -> Optional[Dict[str, Any]]:
        try:
            commits = self.reader.get_recent_commits(limit=1)
            if commits:
                latest = commits[0]
                return {
                    "version": latest["commit"][:8],
                    "commit_hash": latest["commit"],
                    "summary": latest["summary"],
                    "date": latest["date"],
                    "author": latest["author"],
                    "version_type": "source_code_version",
                    "is_running_detected": False,
                    "pointer_source": "Git HEAD (仅代表源码工作区版本)",
                    "note": "Git HEAD 仅能证实本地源码仓库状态，不能作为工控机现场已确认运行版本",
                }
        except Exception:
            pass
        return {
            "version": "UNKNOWN",
            "version_type": "source_code_version",
            "is_running_detected": False,
            "pointer_source": "unknown",
        }

    def get_recent_versions(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.reader.get_recent_commits(limit=limit)

    def get_version_events(
        self, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        commits = self.reader.get_recent_commits(limit=30)
        events = []
        for c in commits:
            ts = c["date"][:19]
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            events.append({
                "event_type": "version_change",
                "source_type": "git",
                "timestamp": ts,
                "version_id": c["commit"][:8],
                "description": c["summary"],
                "author": c["author"],
                "evidence_level": "CONFIRMED",
            })
        return events

    def compare_versions(self, ver_a: str, ver_b: str) -> Dict[str, Any]:
        diff_text = self.reader.get_diff(ver_a, ver_b)
        return {
            "from_release": ver_a,
            "to_release": ver_b,
            "has_changes": bool(diff_text.strip()),
            "diff_text": diff_text[:2000],
            "changed_modules": [],
        }

    def get_version_details(self, version_id: str) -> Optional[Dict[str, Any]]:
        try:
            raw = self.reader.show_commit(version_id)
            return {"version_id": version_id, "details": raw}
        except Exception:
            return None


class WReleaseReaderAdapter(VersionReader):
    """WReleaseReader 统一适配器：解除对 Git 的依赖，专注于 WRelease 独立事实"""

    def __init__(self, wrelease_reader: Optional[WReleaseReader] = None, audit_logger: Optional[AuditLogger] = None):
        self.reader = wrelease_reader or WReleaseReader(audit_logger=audit_logger)

    def is_available(self) -> bool:
        try:
            p = Path(self.reader.delivery_dir)
            if not p.is_dir():
                return False
            releases = self.reader.list_available_releases(limit=1)
            return len(releases) > 0
        except Exception:
            return False

    def get_provider_name(self) -> str:
        return "WReleaseReader"

    def get_current_version(self) -> Optional[Dict[str, Any]]:
        res = self.reader.get_running_release()
        if res:
            res["version_type"] = "running_release"
        return res

    def get_recent_versions(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.reader.list_available_releases(limit=limit)

    def get_version_events(
        self, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        releases = self.reader.list_available_releases(limit=30)
        events = []
        for r in releases:
            ts = r.get("created_at") or ""
            ts_clean = ts[:19]
            if not ts_clean:
                continue
            if start_time and ts_clean < start_time:
                continue
            if end_time and ts_clean > end_time:
                continue
            events.append({
                "event_type": "wrelease_update",
                "source_type": "wrelease",
                "timestamp": ts_clean,
                "version_id": r["version"],
                "description": f"发布交付包 {r['version']} (包含模块: {', '.join(r.get('modules_summary', []))})",
                "modules": r.get("modules_summary", []),
                "evidence_level": "CONFIRMED",
            })
        return events

    def compare_versions(self, ver_a: str, ver_b: str) -> Dict[str, Any]:
        return self.reader.compare_releases(ver_a, ver_b)

    def get_version_details(self, version_id: str) -> Optional[Dict[str, Any]]:
        return self.reader.get_release_info(version_id)


class VersionReaderResolver:
    """版本提供者解析器：严格遵循 Git First, WRelease Fallback, 单工程互斥生效原则"""

    @classmethod
    def resolve(
        cls,
        config: Optional[IROConfig] = None,
        audit_logger: Optional[AuditLogger] = None,
        prefer_provider: Optional[str] = None,
    ) -> Tuple[Optional[VersionReader], str]:
        """
        按优先级选择活跃的版本提供者：
        1. 若显式指定或有效 Git 存在 -> GitReader
        2. 若 Git 不存在/无效，但有效 WRelease 存在 -> WReleaseReader
        3. 均不可用 -> (None, "None")
        """
        cfg = config or get_config()
        audit = audit_logger or AuditLogger()

        git_adapter = GitReaderAdapter(audit_logger=audit)
        wrelease_adapter = WReleaseReaderAdapter(audit_logger=audit)

        if prefer_provider == "wrelease":
            if wrelease_adapter.is_available():
                return wrelease_adapter, "WReleaseReader"
            if git_adapter.is_available():
                return git_adapter, "GitReader"
            return None, "None"

        # 默认规则：Git 优先
        if git_adapter.is_available():
            return git_adapter, "GitReader"

        # 回退：WRelease 兜底
        if wrelease_adapter.is_available():
            return wrelease_adapter, "WReleaseReader"

        return None, "None"
