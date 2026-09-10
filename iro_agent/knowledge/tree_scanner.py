import os
from pathlib import Path
from typing import Dict, List, Any, Set
from pydantic import BaseModel, Field


class TreeScanResult(BaseModel):
    project_root: str
    total_files: int = 0
    extension_counts: Dict[str, int] = Field(default_factory=dict)
    primary_language: str = "unknown"
    frameworks: List[str] = Field(default_factory=list)
    top_level_modules: List[str] = Field(default_factory=list)
    key_directories: List[str] = Field(default_factory=list)
    startup_scripts: List[str] = Field(default_factory=list)
    deployment_scripts: List[str] = Field(default_factory=list)
    entry_points: List[str] = Field(default_factory=list)


class TreeScanner:
    """项目目录树与技术栈扫描探测器 (严格只读，黑名单安全过滤)"""

    EXCLUDED_DIRS: Set[str] = {
        ".git", ".svn", ".hg", "node_modules", "dist", "build", "target",
        "cache", "logs", "runtime", "__pycache__", ".venv", "venv",
        ".idea", ".vscode", "tmp", "temp", ".iro_agent"
    }

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()

    def scan(self, max_depth: int = 4) -> TreeScanResult:
        if not self.project_root.exists() or not self.project_root.is_dir():
            return TreeScanResult(project_root=str(self.project_root))

        ext_counts: Dict[str, int] = {}
        top_modules: List[str] = []
        key_dirs: List[str] = []
        startup_scripts: List[str] = []
        deployment_scripts: List[str] = []
        entry_points: List[str] = []
        frameworks: Set[str] = set()
        total_files = 0

        # 1. 扫描顶层子目录识别顶级模块
        try:
            for item in self.project_root.iterdir():
                if item.name.lower() in self.EXCLUDED_DIRS or item.name.startswith("."):
                    continue
                if item.is_dir():
                    top_modules.append(item.name)
        except Exception:
            pass

        # 2. 递归遍历目录与技术栈特征文件
        for root_str, dirs, files in os.walk(self.project_root):
            # 原地修剪黑名单目录
            dirs[:] = [d for d in dirs if d.lower() not in self.EXCLUDED_DIRS and not d.startswith(".")]

            rel_path = Path(root_str).relative_to(self.project_root)
            depth = len(rel_path.parts)
            if depth > max_depth:
                dirs[:] = []
                continue

            if str(rel_path) != ".":
                key_dirs.append(str(rel_path).replace("\\", "/"))

            for file_name in files:
                total_files += 1
                suffix = Path(file_name).suffix.lower()
                if suffix:
                    ext_counts[suffix] = ext_counts.get(suffix, 0) + 1

                fname_lower = file_name.lower()
                rel_f_str = (rel_path / file_name).as_posix() if str(rel_path) != "." else file_name

                # 识别启动与部署脚本
                if fname_lower.endswith((".bat", ".cmd", ".sh", ".ps1")):
                    if any(k in fname_lower for k in ["start", "run", "launch", "boot", "server"]):
                        startup_scripts.append(rel_f_str)
                    elif any(k in fname_lower for k in ["deploy", "install", "build", "release"]):
                        deployment_scripts.append(rel_f_str)
                elif "dockerfile" in fname_lower or "docker-compose" in fname_lower:
                    deployment_scripts.append(rel_f_str)

                # 技术栈特征识别与入口识别
                if fname_lower == "pom.xml":
                    frameworks.add("Maven / Spring Boot")
                elif fname_lower == "build.gradle":
                    frameworks.add("Gradle")
                elif fname_lower == "manage.py":
                    frameworks.add("Django")
                    entry_points.append(rel_f_str)
                elif fname_lower == "main.py" or fname_lower == "app.py":
                    entry_points.append(rel_f_str)
                elif "application.java" in fname_lower:
                    entry_points.append(rel_f_str)
                elif fname_lower == "package.json":
                    frameworks.add("Node.js / Web")
                elif fname_lower in ("requirements.txt", "pyproject.toml"):
                    frameworks.add("Python")
                elif "vue" in fname_lower:
                    frameworks.add("Vue.js")

        # 3. 推断主语言
        primary_lang = "unknown"
        py_count = ext_counts.get(".py", 0)
        java_count = ext_counts.get(".java", 0)
        js_count = ext_counts.get(".js", 0) + ext_counts.get(".ts", 0) + ext_counts.get(".vue", 0)

        counts = [("Python", py_count), ("Java", java_count), ("JavaScript/TypeScript", js_count)]
        counts.sort(key=lambda x: x[1], reverse=True)
        if counts[0][1] > 0:
            primary_lang = counts[0][0]

        return TreeScanResult(
            project_root=str(self.project_root),
            total_files=total_files,
            extension_counts=ext_counts,
            primary_language=primary_lang,
            frameworks=sorted(list(frameworks)),
            top_level_modules=sorted(top_modules),
            key_directories=sorted(key_dirs)[:30],
            startup_scripts=sorted(startup_scripts),
            deployment_scripts=sorted(deployment_scripts),
            entry_points=sorted(entry_points),
        )

