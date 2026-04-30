# -*- coding: utf-8 -*-
"""
将 CSCD 导出的 .txt 批量解析为 2019.csv / 2020.csv。

文本规则（基于样例）：
- 每篇以「文献收藏号：」起头，篇与篇之间可有空行，分割不明显，故以该标记切分记录。
- 行格式一般为「字段名：值」；全角「：」为字段与正文分界；值里可出现半角「:」等（如机构）。
- 常见字段：文献收藏号、题名、作者、机构、实验室(可选)、关键词、来源、基金(可选)、文摘、被引频次。
- 若遇未见过的「xxx：」行，会作为新列写入；文摘换行续写会合并到该字段。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# 长名优先，避免 实验室/机构 等歧义
_KNOWN_FIELD_PREFIXES: tuple[str, ...] = (
    "文献收藏号",
    "被引频次",
    "实验室",
    "关键词",
    "机构",
    "题名",
    "作者",
    "基金",
    "来源",
    "文摘",
)


def _line_field_split(line: str) -> tuple[str, str] | None:
    """匹配「标准字段名 + 全角/半角冒号 + 本行余下内容」。"""
    for name in _KNOWN_FIELD_PREFIXES:
        for sep in ("：", ":"):
            prefix = name + sep
            if line.startswith(prefix):
                return name, line[len(prefix) :]
    m = re.match(r"^([^：:\n]{1,40})[：:](.*)$", line)
    if m:
        k, v = m.group(1).strip(), m.group(2)
        if k and re.match(r"^[\d\s]+P?$", k) is None:  # 避免误把纯数字当字段名
            return k, v
    return None


def _split_records(text: str) -> list[str]:
    t = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    parts = re.split(r"(?m)(?=^文献收藏号[：:])", t)
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        if s.startswith("文献收藏号：") or s.startswith("文献收藏号:"):
            out.append(s)
    return out


def _parse_one_record(block: str) -> dict[str, str]:
    d: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal current_key, buf
        if current_key is not None:
            d[current_key] = "\n".join(buf).strip() if buf else ""
        current_key, buf = None, []

    for line in block.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        got = _line_field_split(line)
        if got:
            k, first = got
            flush()
            current_key, buf = k, [first]
        elif current_key is not None:
            buf.append(line)
    flush()
    return d


def _discover_and_parse(txt_paths: list[Path]) -> tuple[list[dict[str, str]], list[str]]:
    all_keys: set[str] = set()
    rows: list[dict[str, str]] = []
    for p in sorted(txt_paths):
        text = p.read_text(encoding="utf-8", errors="replace")
        for block in _split_records(text):
            rec = _parse_one_record(block)
            if not rec or not (rec.get("文献收藏号") or "").strip():
                continue
            rec["source_file"] = p.name
            for k in rec:
                all_keys.add(k)
            rows.append(rec)
    priority = [
        "文献收藏号",
        "题名",
        "作者",
        "机构",
        "实验室",
        "关键词",
        "来源",
        "基金",
        "文摘",
        "被引频次",
        "source_file",
    ]
    rest = sorted(x for x in all_keys if x not in priority)
    fieldnames = [c for c in priority if c in all_keys] + rest
    return rows, fieldnames


def main() -> int:
    ap = argparse.ArgumentParser(
        description="将 2019、2020 目录下 batch_*.txt 解析合并为 2019.csv、2020.csv"
    )
    ap.add_argument(
        "--base",
        type=Path,
        default=None,
        help="含 2019/与 2020/ 子目录的路径（默认：脚本所在 cscdspider 目录）",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出目录（默认同 --base）",
    )
    args = ap.parse_args()
    base = args.base or Path(__file__).resolve().parent
    out_dir = args.out or base

    for year, sub in (("2019", "2019"), ("2020", "2020")):
        folder = base / sub
        if not folder.is_dir():
            print(f"跳过：目录不存在 {folder}", file=sys.stderr)
            continue
        txts = sorted(folder.glob("batch_*.txt"))
        if not txts:
            print(f"跳过：{folder} 下无 batch_*.txt", file=sys.stderr)
            continue
        rows, fieldnames = _discover_and_parse(txts)
        out_path = out_dir / f"{year}.csv"
        with out_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: (r.get(k) or "") for k in fieldnames})
        print(
            f"写入 {out_path} 共 {len(rows)} 条，{len(fieldnames)} 列。"
            f" 列：{', '.join(fieldnames)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
