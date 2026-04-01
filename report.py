from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class BatchReport:
    batch_index: int
    start_page: int
    end_page: int
    selected_pages: int
    selected_records: int
    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    download_file: str = ""
    status: str = "running"
    error: str = ""

    def done(self, download_file: str) -> None:
        self.finished_at = now_iso()
        self.download_file = download_file
        self.status = "success"

    def fail(self, err: Exception) -> None:
        self.finished_at = now_iso()
        self.status = "failed"
        self.error = str(err)


@dataclass
class RunReport:
    year: int
    limit: int
    total_results_reported_by_site: int
    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    status: str = "running"
    batches: list[BatchReport] = field(default_factory=list)
    downloaded_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def complete(self) -> None:
        self.finished_at = now_iso()
        self.status = "success"

    def fail(self, err: Exception) -> None:
        self.finished_at = now_iso()
        self.status = "failed"
        self.notes.append(str(err))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_report(report: RunReport, output_file: Path) -> None:
    output_file.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
