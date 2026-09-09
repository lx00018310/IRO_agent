import json
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config
from iro_agent.security.policy import validate_read_path
from iro_agent.security.audit import AuditLogger


class WReleaseReader:
    """WRelease 发布包阅读器：专门负责解析、比对、审计工业现场的 .wrelease 发布交付件"""

    def __init__(self, delivery_dir: Optional[str | Path] = None, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        raw_dir = delivery_dir or self.config.wrelease_dir
        self.delivery_dir = validate_read_path(raw_dir, self.config)
        self.audit = audit_logger or AuditLogger()

    def list_available_releases(self, limit: int = 10) -> List[Dict[str, Any]]:
        """扫描交付目录下的所有 .wrelease 发布包，按创建时间排序，返回精简元数据"""
        if not self.delivery_dir.exists():
            return []

        releases = []
        for file in self.delivery_dir.glob("*.wrelease"):
            info = self.get_release_info(file.name)
            if info:
                releases.append({
                    "file_name": info["file_name"],
                    "version": info["version"],
                    "created_at": info.get("created_at"),
                    "modules_summary": list(info.get("modules", {}).keys()),
                })

        releases.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return releases[:limit]

    def get_release_info(self, file_name_or_version: str) -> Optional[Dict[str, Any]]:
        """安全读取单个 .wrelease 包中的 manifest.json 元数据"""
        target_file = None
        if file_name_or_version.endswith(".wrelease"):
            target_file = self.delivery_dir / file_name_or_version
        else:
            # 尝试通过版本号匹配文件名
            for file in self.delivery_dir.glob(f"*{file_name_or_version}*.wrelease"):
                target_file = file
                break

        if not target_file or not target_file.exists():
            return None

        validate_read_path(target_file, self.config)

        try:
            with zipfile.ZipFile(target_file, "r") as z:
                if "manifest.json" not in z.namelist():
                    return None
                raw_manifest = z.read("manifest.json").decode("utf-8")
                manifest = json.loads(raw_manifest)

            version = manifest.get("version") or target_file.stem
            created_at = manifest.get("createdAt")
            modules = {}
            for mod_name in ["backend", "frontend", "faceIsup"]:
                if mod_name in manifest:
                    modules[mod_name] = manifest[mod_name]

            res = {
                "file_name": target_file.name,
                "file_path": str(target_file),
                "version": version,
                "created_at": created_at,
                "schema_version": manifest.get("schemaVersion"),
                "modules": modules,
                "raw_manifest": manifest,
            }
            self.audit.record(
                tool_name="WReleaseReader",
                operation="get_release_info",
                target=target_file.name,
                result_summary=f"解析版本 {version}",
                status="SUCCESS",
            )
            return res
        except Exception as e:
            self.audit.record(
                tool_name="WReleaseReader",
                operation="get_release_info",
                target=str(target_file),
                result_summary=f"解析失败: {e}",
                status="ERROR",
            )
            return None

    def compare_releases(self, ver_a: str, ver_b: str) -> Dict[str, Any]:
        """比对两个发布包的模块版本差异与 SHA256 变动"""
        info_a = self.get_release_info(ver_a)
        info_b = self.get_release_info(ver_b)

        if not info_a:
            raise ValueError(f"未能读取发布包: {ver_a}")
        if not info_b:
            raise ValueError(f"未能读取发布包: {ver_b}")

        mods_a = info_a.get("modules", {})
        mods_b = info_b.get("modules", {})

        all_mod_names = set(mods_a.keys()) | set(mods_b.keys())
        changed_modules = []
        unchanged_modules = []

        for mod in sorted(list(all_mod_names)):
            sha_a = mods_a.get(mod, {}).get("sha256")
            sha_b = mods_b.get(mod, {}).get("sha256")
            if sha_a != sha_b:
                changed_modules.append({
                    "module": mod,
                    "sha256_a": sha_a,
                    "sha256_b": sha_b,
                    "status": "CHANGED" if (sha_a and sha_b) else ("ADDED" if sha_b else "REMOVED"),
                })
            else:
                unchanged_modules.append({
                    "module": mod,
                    "sha256": sha_a,
                    "status": "SAME",
                })

        return {
            "from_release": info_a["version"],
            "to_release": info_b["version"],
            "from_time": info_a.get("created_at"),
            "to_time": info_b.get("created_at"),
            "changed_modules": changed_modules,
            "unchanged_modules": unchanged_modules,
            "has_changes": len(changed_modules) > 0,
        }

    def get_latest_release(self) -> Optional[Dict[str, Any]]:
        """获取最新生成的交付包"""
        releases = self.list_available_releases()
        return releases[0] if releases else None

    def get_running_release(self) -> Optional[Dict[str, Any]]:
        """探测现场当前正在运行的 WRelease 版本"""
        import os
        candidates = []
        env_file = os.environ.get("TASK013_BACKEND_VERSION_FILE")
        if env_file:
            candidates.append(Path(env_file))

        # 工控机标准路径 %ProgramData%\WLZN\TASK013\backend\current-version.json
        prog_data = os.environ.get("ProgramData", "C:\\ProgramData")
        candidates.append(Path(prog_data) / "WLZN" / "TASK013" / "backend" / "current-version.json")

        # 项目本地路径
        candidates.append(Path(self.config.project_root) / "deployment_control" / "native" / "current-version.json")
        candidates.append(self.delivery_dir.parent / "current-version.json")

        running_version = None
        pointer_source = None
        for cand in candidates:
            if cand.is_file():
                try:
                    with open(cand, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                        if "version" in data and data["version"]:
                            running_version = data["version"].strip()
                            pointer_source = str(cand)
                            break
                except Exception:
                    pass

        if running_version:
            info = self.get_release_info(running_version)
            if info:
                info["is_running_detected"] = True
                info["pointer_source"] = pointer_source
                return info

        # 未检测到生产指针时，降级为最新生成交付包并明确标注
        latest = self.get_latest_release()
        if latest:
            latest["is_running_detected"] = False
            latest["pointer_source"] = "未检测到生产运行指针 (降级为最新交付包)"
        return latest

    def map_release_to_git_commit(self, file_name_or_version: str) -> Optional[Dict[str, Any]]:
        """将 WRelease 版本映射关联到 Git Commit"""
        info = self.get_release_info(file_name_or_version)
        if not info:
            return None

        version = info.get("version", "")
        created_at = info.get("created_at")

        from iro_agent.readers.git_reader import GitReader
        try:
            gr = GitReader(audit_logger=self.audit)
            commits = gr.get_recent_commits(limit=50)

            # 策略1: 在 commit 提交说明中精确匹配版本号 (如 v8.13.6 或 8.13.6)
            ver_clean = version.lstrip("v")
            for c in commits:
                if version.lower() in c["summary"].lower() or ver_clean in c["summary"]:
                    return {
                        "version": version,
                        "matched_by": "summary",
                        "commit": c["commit"],
                        "author": c["author"],
                        "date": c["date"],
                        "summary": c["summary"],
                    }

            # 策略2: 按发布时间比对最相近的提交 (提交时间早于或相近于 created_at)
            if created_at and commits:
                from datetime import datetime
                try:
                    rel_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    for c in commits:
                        c_dt = datetime.fromisoformat(c["date"].replace("Z", "+00:00"))
                        if c_dt <= rel_dt:
                            return {
                                "version": version,
                                "matched_by": "timestamp_closest",
                                "commit": c["commit"],
                                "author": c["author"],
                                "date": c["date"],
                                "summary": c["summary"],
                            }
                except Exception:
                    pass

            # 策略3: 降级返回最新提交
            if commits:
                c = commits[0]
                return {
                    "version": version,
                    "matched_by": "latest_fallback",
                    "commit": c["commit"],
                    "author": c["author"],
                    "date": c["date"],
                    "summary": c["summary"],
                }
        except Exception as e:
            self.audit.record(
                tool_name="WReleaseReader",
                operation="map_release_to_git_commit",
                target=version,
                result_summary=f"映射异常: {e}",
                status="ERROR",
            )
        return None
