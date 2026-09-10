import os
import re
from pathlib import Path
from typing import List, Dict, Any, Set, Optional
from pydantic import BaseModel, Field
from iro_agent.security.redactor import redact_secrets


class CodeEntity(BaseModel):
    name: str
    file_path: str
    entity_type: str  # model, service, controller, enum
    mapped_table: Optional[str] = None
    fields_or_constants: List[str] = Field(default_factory=list)
    docstring_or_comment: str = ""


class CodeScanResult(BaseModel):
    entities: List[CodeEntity] = Field(default_factory=list)
    enums: List[Dict[str, Any]] = Field(default_factory=list)
    detected_models_count: int = 0
    scanned_files_count: int = 0


class TargetedCodeScanner:
    """针对性业务代码与数据模型扫描器 (严格脱敏过滤与黑名单修剪)"""

    CLASS_DEF_PATTERN = re.compile(r"class\s+([A-Za-z0-9_]+)(?:\([^\)]*\))?:")
    TABLE_NAME_PATTERN = re.compile(r"db_table\s*=\s*['\"]([a-zA-Z0-9_]+)['\"]|__tablename__\s*=\s*['\"]([a-zA-Z0-9_]+)['\"]")
    ENUM_CLASS_PATTERN = re.compile(r"class\s+([A-Za-z0-9_]+)\s*\((?:.*Enum|.*Choices|TextChoices|IntegerChoices)[^\)]*\):")

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()

    def scan(self, max_files: int = 200) -> CodeScanResult:
        if not self.project_root.exists() or not self.project_root.is_dir():
            return CodeScanResult()

        entities: List[CodeEntity] = []
        enums: List[Dict[str, Any]] = []
        scanned_count = 0

        # 针对性寻找可能包含数据模型与枚举的路径
        candidate_files: List[Path] = []
        for root_str, dirs, files in os.walk(self.project_root):
            # 修剪黑名单目录
            dirs[:] = [
                d for d in dirs
                if d.lower() not in {
                    ".git", "node_modules", "dist", "build", "target", "logs",
                    "runtime", "__pycache__", ".venv", "venv", ".idea", ".vscode"
                }
            ]
            for f in files:
                suffix = Path(f).suffix.lower()
                if suffix in (".py", ".java"):
                    p = Path(root_str) / f
                    fname_lower = f.lower()
                    if any(k in fname_lower for k in ("model", "entity", "schema", "enum", "constant", "dao", "mapper", "service")):
                        candidate_files.append(p)
                    elif len(candidate_files) < max_files:
                        # 兜底收录核心源码
                        candidate_files.append(p)

        for file_path in candidate_files[:max_files]:
            scanned_count += 1
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                # 强制脱敏
                content = redact_secrets(content)
                rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")

                lines = content.splitlines()
                current_entity: Optional[CodeEntity] = None

                for line in lines:
                    line_strip = line.strip()

                    # 1. 优先匹配类声明
                    c_match = self.CLASS_DEF_PATTERN.search(line_strip)
                    if c_match:
                        class_name = c_match.group(1)
                        if class_name.lower() == "meta" and current_entity and current_entity.entity_type == "model":
                            # Django 内部 class Meta，不作为独立实体，保留外层模型上下文
                            pass
                        else:
                            is_enum = bool(self.ENUM_CLASS_PATTERN.search(line_strip))
                            current_entity = CodeEntity(
                                name=class_name,
                                file_path=rel_path,
                                entity_type="enum" if is_enum else "model",
                            )
                            entities.append(current_entity)

                    # 2. 提取映射表名 db_table 或 __tablename__
                    if current_entity:
                        t_match = self.TABLE_NAME_PATTERN.search(line_strip)
                        if t_match:
                            table_name = t_match.group(1) or t_match.group(2)
                            current_entity.mapped_table = table_name
                            current_entity.entity_type = "model"

                    # 3. 提取关键字段或枚举项（以赋值开头的行）
                    if current_entity and "=" in line_strip and not line_strip.startswith(("#", "//", "def ", "class ", "return ")):
                        key_part = line_strip.split("=")[0].strip()
                        if re.match(r"^[A-Za-z0-9_]+$", key_part) and key_part not in ("class", "def"):
                            if len(current_entity.fields_or_constants) < 25:
                                current_entity.fields_or_constants.append(key_part)

            except Exception:
                continue

        models_count = sum(1 for e in entities if e.entity_type == "model")
        return CodeScanResult(
            entities=entities,
            enums=[e.model_dump() for e in entities if e.entity_type == "enum"],
            detected_models_count=models_count,
            scanned_files_count=scanned_count,
        )
