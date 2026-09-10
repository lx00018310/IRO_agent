import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.knowledge.models import ConfigItem, ConfigPriorityRule
from iro_agent.security.redactor import SecretRedactor


class ConfigCatalogScanner:
    """配置全目录深度扫描器：全面遍历多格式配置文件，解析配置项并落实敏感信息脱敏"""

    SUPPORTED_EXTENSIONS = {".json", ".yml", ".yaml", ".properties", ".env", ".ini", ".conf", ".xml"}
    IGNORE_DIRS = {".git", ".venv", "node_modules", "target", "build", "dist", "__pycache__", ".idea", ".vscode"}

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)

    def scan(self, max_files: int = 200, max_items_per_file: int = 100) -> tuple[List[ConfigItem], List[ConfigPriorityRule]]:
        """全量遍历扫描配置目录与配置项"""
        catalog: List[ConfigItem] = []
        if not self.root_dir.exists():
            return catalog, []

        config_files: List[Path] = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith(".")]
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in self.SUPPORTED_EXTENSIONS or f in (".env", "config.json"):
                    config_files.append(Path(root) / f)
                    if len(config_files) >= max_files:
                        break
            if len(config_files) >= max_files:
                break

        for file_path in config_files:
            try:
                items = self._parse_config_file(file_path, max_items_per_file)
                catalog.extend(items)
            except Exception:
                continue

        priority_rules = self._detect_priority_rules(catalog)
        return catalog, priority_rules

    def _parse_config_file(self, file_path: Path, max_items: int) -> List[ConfigItem]:
        items: List[ConfigItem] = []
        try:
            rel_path = file_path.relative_to(self.root_dir).as_posix()
        except ValueError:
            rel_path = file_path.name

        ext = file_path.suffix.lower()

        try:
            raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        if ext == ".json":
            items.extend(self._parse_json(raw_text, file_path, rel_path, max_items))
        elif ext in (".yml", ".yaml"):
            items.extend(self._parse_yaml_lines(raw_text, file_path, rel_path, max_items))
        elif ext in (".properties", ".env", ".ini", ".conf"):
            items.extend(self._parse_key_value_lines(raw_text, file_path, rel_path, max_items))
        elif ext == ".xml":
            items.extend(self._parse_xml_tags(raw_text, file_path, rel_path, max_items))

        return items

    @staticmethod
    def _mask_value(key: str, val: Any) -> str:
        val_str = str(val) if val is not None else ""
        k_lower = key.lower()
        sensitive_keys = {"password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "private_key", "aes_key"}
        if any(sk in k_lower for sk in sensitive_keys):
            return "[REDACTED_SECRET]"
        combined = f"{key}: {val_str}"
        redacted = SecretRedactor.redact(combined)
        if redacted != combined and ":" in redacted:
            return redacted.split(":", 1)[1].strip()
        return SecretRedactor.redact(val_str)

    def _parse_json(self, text: str, file_path: Path, rel_path: str, max_items: int) -> List[ConfigItem]:
        items = []
        try:
            data = json.loads(text)
        except Exception:
            return items

        def _flatten(obj: Any, prefix: str = ""):
            if len(items) >= max_items:
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    full_k = f"{prefix}.{k}" if prefix else str(k)
                    _flatten(v, full_k)
            else:
                redacted_val = self._mask_value(prefix, obj)
                unit, meaning = self._infer_semantics(prefix)
                items.append(
                    ConfigItem(
                        config_id=f"CFG-{len(items)+1:04d}-{file_path.stem}",
                        file_path=str(file_path.resolve()),
                        relative_path=rel_path,
                        key=prefix,
                        value_type=type(obj).__name__ if obj is not None else "null",
                        default_value=redacted_val,
                        business_meaning=meaning,
                        unit=unit,
                        read_by=[file_path.stem],
                        confidence="confirmed",
                    )
                )

        _flatten(data)
        return items


    def _parse_yaml_lines(self, text: str, file_path: Path, rel_path: str, max_items: int) -> List[ConfigItem]:
        items = []
        for line in text.splitlines():
            if len(items) >= max_items:
                break
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" in stripped:
                parts = stripped.split(":", 1)
                k = parts[0].strip()
                v = parts[1].strip()
                if k and not v.startswith("{") and not v.startswith("["):
                    unit, meaning = self._infer_semantics(k)
                    items.append(
                        ConfigItem(
                            config_id=f"CFG-{len(items)+1:04d}-{file_path.stem}",
                            file_path=str(file_path.resolve()),
                            relative_path=rel_path,
                            key=k,
                            value_type="string",
                            default_value=self._mask_value(k, v),
                            business_meaning=meaning,
                            unit=unit,
                            confidence="confirmed",
                        )
                    )
        return items

    def _parse_key_value_lines(self, text: str, file_path: Path, rel_path: str, max_items: int) -> List[ConfigItem]:
        items = []
        for line in text.splitlines():
            if len(items) >= max_items:
                break
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            sep = "=" if "=" in line else (":" if ":" in line else None)
            if sep:
                parts = line.split(sep, 1)
                k = parts[0].strip()
                v = parts[1].strip().strip('"\'')
                unit, meaning = self._infer_semantics(k)
                items.append(
                    ConfigItem(
                        config_id=f"CFG-{len(items)+1:04d}-{file_path.stem}",
                        file_path=str(file_path.resolve()),
                        relative_path=rel_path,
                        key=k,
                        value_type="string",
                        default_value=self._mask_value(k, v),
                        business_meaning=meaning,
                        unit=unit,
                        confidence="confirmed",
                    )
                )
        return items

    def _parse_xml_tags(self, text: str, file_path: Path, rel_path: str, max_items: int) -> List[ConfigItem]:
        items = []
        tag_pattern = re.compile(r"<([a-zA-Z0-9_\-\.]+)>([^<]+)</\1>")
        for m in tag_pattern.finditer(text):
            if len(items) >= max_items:
                break
            k = m.group(1).strip()
            v = m.group(2).strip()
            unit, meaning = self._infer_semantics(k)
            items.append(
                ConfigItem(
                    config_id=f"CFG-{len(items)+1:04d}-{file_path.stem}",
                    file_path=str(file_path.resolve()),
                    relative_path=rel_path,
                    key=k,
                    value_type="string",
                    default_value=self._mask_value(k, v),
                    business_meaning=meaning,
                    unit=unit,
                    confidence="confirmed",
                )
            )
        return items


    def _infer_semantics(self, key: str) -> tuple[str, str]:
        k_lower = key.lower()
        unit = ""
        meanings = []

        if "second" in k_lower or "sec" in k_lower:
            unit = "秒 (s)"
        elif "millis" in k_lower or "ms" in k_lower:
            unit = "毫秒 (ms)"
        elif "minute" in k_lower:
            unit = "分钟 (min)"
        elif "hour" in k_lower:
            unit = "小时 (h)"
        elif "port" in k_lower:
            unit = "网络端口"

        if any(w in k_lower for w in ["poll", "polling", "interval"]):
            meanings.append("轮询扫描周期/时间间隔")
        if any(w in k_lower for w in ["timeout"]):
            meanings.append("超时时间设置")
        if any(w in k_lower for w in ["material", "call", "pallet", "dock"]):
            meanings.append("叫料/装车任务作业参数")
        if any(w in k_lower for w in ["db", "database", "datasource", "sql"]):
            meanings.append("数据库连接设置")
        if any(w in k_lower for w in ["host", "ip", "address"]):
            meanings.append("目标主机或服务IP网络地址")
        if any(w in k_lower for w in ["port"]):
            meanings.append("服务监听或通信端口")

        meaning_str = "；".join(meanings) if meanings else "业务系统运行参数"
        return unit, meaning_str

    def _detect_priority_rules(self, catalog: List[ConfigItem]) -> List[ConfigPriorityRule]:
        rules = []
        rules.append(
            ConfigPriorityRule(
                rule_name="标准工业三级覆盖规则",
                description="运行时环境变量 > 外部部署工作目录配置 > 源码内部打包默认配置",
                precedence_order=[
                    "环境变量 (Environment Variables)",
                    "外部持久化配置目录 (如 delivery / deployment_control / ProgramData)",
                    "代码包静态内置配置 (src / resources)",
                    "程序代码硬编码缺省值 (Hardcoded Default)"
                ],
                evidence="基于项目目录结构与典型工控部署模式综合决议"
            )
        )
        return rules


def search_config_catalog(catalog: List[ConfigItem], query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """依据自然语言或配置关键字在 ConfigCatalog 中执行语义与全名检索"""
    q = (query or "").strip().lower()
    if not q:
        return []

    tokens = [t for t in re.split(r"[\s,，、_；;?!？！。]+", q) if len(t) >= 1]
    bigrams = set()
    if len(q) >= 2:
        for i in range(len(q) - 1):
            bigrams.add(q[i:i+2])

    scored = []
    for item in catalog:
        score = 0
        k_lower = item.key.lower()
        f_lower = item.relative_path.lower()
        m_lower = (item.business_meaning or "").lower()

        # 1. 精确 key 包含或匹配
        if item.key.lower() in q:
            score += 120
        for tok in tokens:
            if len(tok) >= 2 and tok in k_lower:
                score += 35
            elif len(tok) >= 2 and tok in f_lower:
                score += 25
            elif len(tok) >= 2 and tok in m_lower:
                score += 15

        for bg in bigrams:
            if bg in k_lower or bg in m_lower or bg in f_lower:
                score += 5

        # 领域关键词加权
        if any(term in q for term in ["轮询", "叫料", "时间", "周期", "interval", "poll"]) and ("poll" in k_lower or "interval" in k_lower or "material" in k_lower):
            score += 40

        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, item in scored[:limit]:
        results.append({
            "key": item.key,
            "relative_path": item.relative_path,
            "file_path": item.file_path,
            "default_value": item.default_value,
            "value_type": item.value_type,
            "business_meaning": item.business_meaning,
            "unit": item.unit,
            "confidence": item.confidence,
            "match_score": score,
        })
    return results
