import json
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config
from iro_agent.security.policy import validate_read_path
from iro_agent.security.audit import AuditLogger


class LogReader:
    """TASK-013 工业日志阅读器：支持 Pino JSON 结构化日志与文本日志的高效窗口查询"""

    # 常见级别映射
    PINO_LEVEL_MAP = {
        10: "TRACE",
        20: "DEBUG",
        30: "INFO",
        40: "WARN",
        50: "ERROR",
        60: "FATAL",
    }

    TIME_REGEX = re.compile(r"(\d{4}[-_]?\d{2}[-_]?\d{2}[ T_]?\d{2}[:_]?\d{2}[:_]?\d{2})")

    def __init__(self, log_dirs: Optional[List[str | Path]] = None, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        raw_dirs = log_dirs or self.config.log_dirs
        self.log_dirs = [validate_read_path(d, self.config) for d in raw_dirs if Path(d).exists()]
        self.audit = audit_logger or AuditLogger()

    def discover_log_files(self) -> List[Path]:
        """扫描所有配置日志目录下的 .log 文件"""
        log_files = []
        for ldir in self.log_dirs:
            for root, _, files in os.walk(ldir):
                for f in files:
                    if f.endswith(".log") or f.endswith(".txt"):
                        log_files.append(Path(root) / f)
        return log_files

    def _parse_log_line(self, line: str, line_no: int, file_path: Path) -> Dict[str, Any]:
        """解析单行日志，兼容 Pino JSON 与普通文本"""
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
                level_num = data.get("level", 30)
                level_name = self.PINO_LEVEL_MAP.get(level_num, str(level_num))
                # 工业现场外呼业务异常兼容：remoteCode == ERROR 或 businessAccepted == False 提级为 ERROR
                if str(data.get("remoteCode", "")).upper() == "ERROR" or data.get("businessAccepted") is False:
                    level_name = "ERROR"
                time_str = str(data.get("time", ""))
                msg = data.get("msg", "")
                remote_msg = str(data.get("remoteMessage") or "")
                op_name = str(data.get("operation", "")).lower()
                if "material" in op_name and remote_msg:
                    msg = f"{msg} | 物料呼叫响应异常/拒收: {remote_msg}"
                elif remote_msg:
                    msg = f"{msg} | {remote_msg}"
                err = data.get("err", {})
                return {
                    "file": file_path.name,
                    "line_no": line_no,
                    "is_json": True,
                    "time": time_str,
                    "level": level_name,
                    "message": msg,
                    "error": err,
                    "raw": stripped,
                }
            except Exception:
                pass

        # 普通文本日志 fallback
        time_match = self.TIME_REGEX.search(stripped)
        extracted_time = time_match.group(1) if time_match else ""
        level = "INFO"
        upper = stripped.upper()
        if "ERROR" in upper or "FATAL" in upper or "EXCEPTION" in upper:
            level = "ERROR"
        elif "WARN" in upper:
            level = "WARN"

        return {
            "file": file_path.name,
            "line_no": line_no,
            "is_json": False,
            "time": extracted_time,
            "level": level,
            "message": stripped[:300],
            "error": {},
            "raw": stripped,
        }

    def search_logs(
        self,
        keyword: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_results: int = 100,
        file_name_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """在所有日志中执行带时间窗口、错误级别和关键字的组合过滤"""
        files = self.discover_log_files()
        if file_name_filter:
            files = [f for f in files if file_name_filter.lower() in f.name.lower()]

        results = []
        target_levels = set()
        if level:
            lvl_upper = level.upper()
            if lvl_upper == "ERROR":
                target_levels = {"ERROR", "FATAL", "50", "60"}
            elif lvl_upper == "WARN":
                target_levels = {"WARN", "40"}
            else:
                target_levels = {lvl_upper}

        kw_lower = keyword.lower() if keyword else None

        for file_path in files:
            validate_read_path(file_path, self.config)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, start=1):
                        parsed = self._parse_log_line(line, line_no, file_path)

                        # 等级过滤
                        if target_levels and parsed["level"] not in target_levels:
                            continue

                        # 关键字过滤
                        if kw_lower:
                            raw_l = parsed["raw"].lower()
                            if kw_lower in raw_l:
                                pass
                            elif ("拒收" in kw_lower or "物料" in kw_lower) and ("materialcall" in raw_l or "物料" in raw_l or "拒收" in raw_l):
                                pass
                            elif all(p in raw_l for p in kw_lower.split()):
                                pass
                            else:
                                continue

                        # 时间窗口过滤
                        if parsed["time"]:
                            if start_time and parsed["time"] < start_time:
                                continue
                            if end_time and parsed["time"] > end_time:
                                continue

                        results.append(parsed)
                        if len(results) >= max_results:
                            break
            except Exception:
                continue

            if len(results) >= max_results:
                break

        self.audit.record(
            tool_name="LogReader",
            operation="search_logs",
            target=f"kw={keyword}, level={level}, files_scanned={len(files)}",
            result_summary=f"匹配到 {len(results)} 条日志",
            status="SUCCESS",
        )
        return results

    def get_log_context(self, file_name: str, target_line_no: int, window: int = 5) -> List[Dict[str, Any]]:
        """提取指定文件某行附近的上下文行"""
        files = [f for f in self.discover_log_files() if f.name == file_name]
        if not files:
            raise FileNotFoundError(f"未找到日志文件: {file_name}")

        target_file = files[0]
        validate_read_path(target_file, self.config)

        start_line = max(1, target_line_no - window)
        end_line = target_line_no + window

        context_lines = []
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, start=1):
                if start_line <= line_no <= end_line:
                    parsed = self._parse_log_line(line, line_no, target_file)
                    parsed["is_target"] = (line_no == target_line_no)
                    context_lines.append(parsed)
                elif line_no > end_line:
                    break

        return context_lines
