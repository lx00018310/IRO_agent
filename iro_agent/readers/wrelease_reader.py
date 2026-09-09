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

    def list_available_releases(self) -> List[Dict[str, Any]]:
        """扫描交付目录下的所有 .wrelease 发布包，按创建时间排序"""
        if not self.delivery_dir.exists():
            return []

        releases = []
        for file in self.delivery_dir.glob("*.wrelease"):
            info = self.get_release_info(file.name)
            if info:
                releases.append(info)

        # 优先按 manifest 中的 createdAt 排序，若无则按文件修改时间排序
        releases.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return releases

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
