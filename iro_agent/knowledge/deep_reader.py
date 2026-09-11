import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class DeepReadFile(BaseModel):
    """单文件深度阅读记录"""
    relative_path: str
    module: str
    category: str
    line_count: int
    content: str


class DeepReadResult(BaseModel):
    """深度阅读汇总结果"""
    files: List[DeepReadFile] = Field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    module_coverage: Dict[str, int] = Field(default_factory=dict)


class TargetedModuleDeepReader:
    """针对性模块源码深度阅读器 (Stage 2 File Selection & Deep Reading)"""

    def __init__(
        self,
        project_root: Path,
        max_modules: int = 5,
        max_files_per_module: int = 8,
        max_lines_per_file: int = 300,
        max_total_deep_read_lines: int = 3000,
    ):
        self.project_root = Path(project_root)
        self.max_modules = max_modules
        self.max_files_per_module = max_files_per_module
        self.max_lines_per_file = max_lines_per_file
        self.max_total_deep_read_lines = max_total_deep_read_lines

    def select_and_read(
        self,
        target_modules: List[str],
        entities: List[Dict[str, Any]],
    ) -> DeepReadResult:
        """根据模块与实体分类，优先抓取高业务价值代码并读取内容"""
        result = DeepReadResult()
        curr_total_lines = 0

        # 若目标模块为空，退化为顶级目录
        active_modules = target_modules[: self.max_modules] if target_modules else ["src", "app"]

        # 按模块归类已知实体文件
        module_file_candidates: Dict[str, List[Dict[str, Any]]] = {m: [] for m in active_modules}

        for ent in entities:
            f_path = ent.get("file_path", "")
            if not f_path:
                continue
            # 排除测试、生成代码、DTO、静态文件
            f_lower = f_path.lower()
            if any(p in f_lower for p in ["test", "dto", "vo", "generated", "target", "build", "node_modules"]):
                continue

            matched_mod = None
            for m in active_modules:
                if m.lower() in f_path.lower():
                    matched_mod = m
                    break
            if not matched_mod and active_modules:
                matched_mod = active_modules[0]

            if matched_mod:
                module_file_candidates[matched_mod].append({
                    "file_path": f_path,
                    "entity_name": ent.get("name", ""),
                    "entity_type": ent.get("entity_type", "class"),
                    "priority": self._calc_priority(f_path, ent.get("entity_type", "")),
                })

        # 遍历每个模块读取源码
        for mod, candidates in module_file_candidates.items():
            # 排序：高优先级靠前
            sorted_candidates = sorted(candidates, key=lambda x: x["priority"], reverse=True)
            seen_files = set()
            mod_count = 0

            for cand in sorted_candidates:
                if mod_count >= self.max_files_per_module:
                    break
                rel_path = cand["file_path"]
                if rel_path in seen_files:
                    continue
                seen_files.add(rel_path)

                full_path = self.project_root / rel_path
                if not full_path.exists() or not full_path.is_file():
                    continue

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                except Exception:
                    continue

                line_count = len(lines)
                if line_count == 0:
                    continue

                # 截取在行数配额内的关键代码
                take_lines = lines[: self.max_lines_per_file]
                if curr_total_lines + len(take_lines) > self.max_total_deep_read_lines:
                    take_count = max(0, self.max_total_deep_read_lines - curr_total_lines)
                    take_lines = take_lines[:take_count]

                if not take_lines:
                    break

                read_content = "".join(take_lines)
                curr_total_lines += len(take_lines)

                deep_file = DeepReadFile(
                    relative_path=rel_path,
                    module=mod,
                    category=cand["entity_type"],
                    line_count=len(take_lines),
                    content=read_content,
                )
                result.files.append(deep_file)
                mod_count += 1
                result.module_coverage[mod] = result.module_coverage.get(mod, 0) + 1

                if curr_total_lines >= self.max_total_deep_read_lines:
                    break

            if curr_total_lines >= self.max_total_deep_read_lines:
                break

        result.total_files = len(result.files)
        result.total_lines = curr_total_lines
        return result

    def _calc_priority(self, path: str, entity_type: str) -> int:
        p_lower = path.lower()
        t_lower = entity_type.lower()
        score = 10

        # 控制器与入口
        if "controller" in p_lower or "controller" in t_lower:
            score += 50
        elif "service" in p_lower or "service" in t_lower:
            score += 40
        elif "mapper" in p_lower or "repository" in p_lower:
            score += 35
        elif "state" in p_lower or "machine" in p_lower:
            score += 45
        elif "plc" in p_lower or "robot" in p_lower or "device" in p_lower:
            score += 48
        elif "config" in p_lower or "setting" in p_lower:
            score += 30

        return score
