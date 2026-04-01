from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from config import SpiderConfig, ensure_runtime_dirs
from report import write_report
from spider import CscdSpider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CSCD 下载导出自动化脚本")
    parser.add_argument("--year", type=int, required=True, help="检索年份，例如 2019")
    parser.add_argument("--limit", type=int, default=2000, help="目标抓取条数，例如 2000")
    parser.add_argument("--start-page", type=int, default=1, help="从第几页开始继续执行")
    parser.add_argument("--download-dir", type=str, default="", help="自定义下载目录")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="禁止使用。该项目强制非无头模式，传入将直接报错。",
    )
    return parser


def setup_logger(logs_dir: Path) -> logging.Logger:
    logger = logging.getLogger("cscdspider")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(logs_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


async def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.headless:
        raise ValueError("该脚本不支持无头模式，请去掉 --headless。")
    if args.limit <= 0:
        raise ValueError("--limit 必须大于 0。")

    project_root = Path(__file__).resolve().parent
    config = SpiderConfig()
    logs_dir, reports_dir, default_download_dir = ensure_runtime_dirs(project_root)
    download_dir = Path(args.download_dir).resolve() if args.download_dir else default_download_dir
    download_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logger(logs_dir)
    logger.info("开始执行: year=%s, limit=%s, start_page=%s", args.year, args.limit, args.start_page)
    logger.info("下载目录: %s", download_dir)

    spider = CscdSpider(
        year=args.year,
        limit=args.limit,
        start_page=args.start_page,
        download_dir=download_dir,
        config=config,
        logger=logger,
    )
    report = await spider.run()

    report_file = reports_dir / f"report_{args.year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    write_report(report, report_file)
    logger.info("执行状态: %s", report.status)
    logger.info("站点检索总数: %s", report.total_results_reported_by_site)
    logger.info("批次数量: %s", len(report.batches))
    logger.info("报告文件: %s", report_file)

    if report.status != "success":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
