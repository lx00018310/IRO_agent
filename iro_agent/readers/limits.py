"""Small, shared limits for local diagnostic reads (no background workers)."""

import os
from pathlib import Path

MAX_FILE_BYTES = 5_000_000
MAX_SCAN_BYTES = 20_000_000
MAX_SCAN_FILES = 500
MAX_SCAN_ENTRIES = 5000
MAX_RESULTS = 2000
MAX_READ_LINES = 500
MAX_OUTPUT_CHARS = 50_000


class ReadLimitError(ValueError):
    pass


def bounded_int(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} 必须是 1 到 {maximum} 的整数")
    return value


class ReadBudget:
    def __init__(self):
        self.bytes_read = 0

    def read_text(self, path: Path) -> str:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES or self.bytes_read + size > MAX_SCAN_BYTES:
            raise ReadLimitError("observability_gap: 文件或本次扫描超过读取大小上限，请缩小来源范围")
        with path.open("rb") as stream:
            data = stream.read(min(MAX_FILE_BYTES, MAX_SCAN_BYTES - self.bytes_read) + 1)
        self.bytes_read += len(data)
        if len(data) > MAX_FILE_BYTES or self.bytes_read > MAX_SCAN_BYTES:
            raise ReadLimitError("observability_gap: 文件增长导致读取大小超过上限")
        return data.decode("utf-8-sig", errors="replace")


def iter_source_files(root: Path, skip_dirs=()):
    """Bound enumeration itself, rather than slicing an already unbounded rglob list."""
    pending = [root]
    entries = files = 0
    while pending:
        with os.scandir(pending.pop()) as directory:
            for entry in directory:
                entries += 1
                if entries > MAX_SCAN_ENTRIES:
                    raise ReadLimitError("observability_gap: 目录扫描条目超过上限，请缩小来源范围")
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if (entry.name not in skip_dirs and not entry.name.startswith(".")
                            and not getattr(path, "is_junction", lambda: False)()):
                        pending.append(path)
                elif entry.is_file():
                    files += 1
                    if files > MAX_SCAN_FILES:
                        raise ReadLimitError("observability_gap: 文件扫描数量超过上限，请缩小来源范围")
                    yield path
