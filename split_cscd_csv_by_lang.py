#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将年度总表 CSV 按题名语言拆分为 *-zh.csv 与 *-en.csv。

规则：
- 仅检查「题名」字段
- 若题名包含中文字符 -> zh
- 否则 -> en
- 题名为空或缺失 -> zh
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

_CJK_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")


def detect_language_by_title(title: str) -> str:
    if not (title or "").strip():
        return "zh"
    return "zh" if _CJK_RE.search(title) else "en"


def split_one_csv(input_csv: Path, out_dir: Path) -> tuple[int, int, int]:
    with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if not fieldnames:
            raise ValueError(f"CSV 无表头或为空：{input_csv}")
        if "题名" not in fieldnames:
            raise ValueError(f"CSV 缺少字段「题名」：{input_csv}")
        rows = list(reader)

    stem = input_csv.stem
    zh_path = out_dir / f"{stem}-zh.csv"
    en_path = out_dir / f"{stem}-en.csv"

    total_count = 0
    zh_count = 0
    en_count = 0

    with zh_path.open("w", encoding="utf-8-sig", newline="") as f_zh, en_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f_en:
        zh_writer = csv.DictWriter(f_zh, fieldnames=fieldnames, extrasaction="ignore")
        en_writer = csv.DictWriter(f_en, fieldnames=fieldnames, extrasaction="ignore")
        zh_writer.writeheader()
        en_writer.writeheader()

        for row in rows:
            total_count += 1
            lang = detect_language_by_title(row.get("题名", ""))
            normalized = {k: (row.get(k) or "") for k in fieldnames}
            if lang == "zh":
                zh_writer.writerow(normalized)
                zh_count += 1
            else:
                en_writer.writerow(normalized)
                en_count += 1

    if zh_count + en_count != total_count:
        raise RuntimeError(
            f"数量校验失败：{input_csv} total={total_count} zh={zh_count} en={en_count}"
        )

    return total_count, zh_count, en_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将一个或多个年度 CSV 拆分为 -zh/-en 两个文件（按题名判定）"
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        type=Path,
        help="输入 CSV 路径，可传多个，如：--inputs 2019.csv 2020.csv",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出目录（默认：脚本所在目录）",
    )
    args = parser.parse_args()

    out_dir = args.out or Path(__file__).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)

    for p in args.inputs:
        if not p.exists():
            print(f"输入文件不存在：{p}", file=sys.stderr)
            return 1
        if p.suffix.lower() != ".csv":
            print(f"输入文件不是 CSV：{p}", file=sys.stderr)
            return 1

    overall_total = 0
    overall_zh = 0
    overall_en = 0

    try:
        for input_csv in args.inputs:
            total, zh, en = split_one_csv(input_csv, out_dir)
            overall_total += total
            overall_zh += zh
            overall_en += en
            print(f"[{input_csv.name}] total={total} zh={zh} en={en}")
    except Exception as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 1

    print(
        f"[ALL] total={overall_total} zh={overall_zh} en={overall_en} "
        f"check={overall_total == (overall_zh + overall_en)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
