from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpiderConfig:
    base_url: str = "http://sciencechina.cn/simple"
    page_size: int = 20
    max_export_per_batch: int = 1000
    max_pages_per_batch: int = 50
    action_delay_ms: int = 300
    default_timeout_ms: int = 20_000
    search_settle_ms: int = 3_000
    navigation_timeout_ms: int = 45_000
    download_timeout_ms: int = 180_000
    click_retry_times: int = 3
    click_retry_wait_ms: int = 800
    logs_dirname: str = "logs"
    reports_dirname: str = "reports"
    downloads_dirname: str = "downloads"


def ensure_runtime_dirs(project_root: Path) -> tuple[Path, Path, Path]:
    logs_dir = project_root / SpiderConfig.logs_dirname
    reports_dir = project_root / SpiderConfig.reports_dirname
    downloads_dir = project_root / SpiderConfig.downloads_dirname
    logs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir, reports_dir, downloads_dir
