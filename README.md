# cscdspider

基于 Playwright 的 CSCD 导出自动化脚本，按 `http://sciencechina.cn/simple` 的交互流程实现：

- 点击“添加论文发表日期范围”
- 起始/结束年份输入同一年（如 2019）
- 点击“检索”并读取结果总数
- **先切换 `20条/页`，再将排序设为「题名：升序」**（改每页条数会刷新列表，可能打回默认排序，故排序在条数之后）
- 分页器页码与当前排序会在批次内多次校验；不一致时会尝试自动纠偏
- 按 `20 条/页 * 50 页 = 1000 条` 分批勾选与导出（**最后一批不足 50 页时，以实际剩余页数为一批**）
- 每批导出后点击两次“所有记录”清空，再继续下一批
- 若导出阶段因全屏遮罩等失败，会 **整页刷新** 并从 **本批起始页** 重新勾选整批后重试导出一次（刷新会清空所有勾选）
- **同一轮遮罩等待**中，若 `useLoading` 全屏层与 `ant-spin-fullscreen` **两处均超时**，也会 **整页刷新**，并重新执行检索（如需）、`20条/页`、`题名：升序` 与 **页码/排序校验**；勾选会清空，多页批次中途触发时可能影响本批条数，导出失败时另有自动整批重勾

## 安装

```bash
cd cscdspider
pip install -r requirements.txt
playwright install
```

## 运行

### 1) 常规有头运行（默认，全量）

```bash
python run.py --year 2019
```

### 2) 无头运行（新增支持）

```bash
python run.py --year 2019 --limit 2000 --headless
```

### 3) 断点续跑（从指定页开始）

```bash
python run.py --year 2019 --limit 1000 --start-page 51
```

> `--start-page` 现在为“**输入框直跳**”模式：会在分页输入框（如 `1/85802` 左侧输入框）中直接填入页码并回车，而不是逐页点击“下一页”。
>
> 执行顺序为：先切换到 `20条/页`，再执行 `--start-page` 跳转。
>
> 新增页码一致性校验：脚本会维护内部期望页码，并与分页器 `li.ant-pagination-simple-pager` 的 `title`/输入框值（如 `1/23777`）逐步比对；若不一致会先尝试输入框纠偏跳转，仍不一致则报错终止，避免抓错页内容。

### 4) 自定义下载目录

```bash
python run.py --year 2019 --limit 1000 --download-dir "D:\\data\\cscd"
```

## 参数说明

- `--year`：检索年份（必填）
- `--limit`：目标条数（可选；不传时按检索结果总数全量抓取）
- `--start-page`：从指定页开始（默认 `1`，输入框直跳）
- `--download-dir`：自定义下载目录
- `--headless`：启用无头模式（默认不启用，保持有界面）

## 输出目录

- 下载文件：`cscdspider/downloads/`
- 运行日志：`cscdspider/logs/run.log`
- 批次报告：`cscdspider/reports/report_*.json`

下载文件命名：

- `batch_p{起始页}-{结束页}_{站点原文件名}`
- 示例：`batch_p351-400_xxx.txt`（每批对应一段连续页码；末批为剩余页，如 `batch_p9901-9920_xxx.txt`）

报告包含：

- 站点返回总数
- 每批页范围（如 `1-50`、`51-100`）
- 每批条数与状态
- 导出文件路径

## 将下载的 txt 合并为年度 CSV

各年目录（如 `2019/`、`2020/`）下所有 `batch_*.txt` 可合并为对应年份 CSV（UTF-8 BOM，便于 Excel 打开）：

```bash
cd cscdspider
python parse_cscd_txts_to_csv.py
# 指定年份（新增）
python parse_cscd_txts_to_csv.py --years 2019 2020 2021
# 或指定根目录与输出目录
python parse_cscd_txts_to_csv.py --base "D:\路径\cscdspider" --out "D:\路径\cscdspider" --years 2019 2020 2021
```

解析规则：以行首「文献收藏号：」切分篇目；每行「字段名：值」采用全角冒号；常见列为 文献收藏号、题名、作者、机构、实验室（可无）、关键词、来源、基金、文摘、被引频次，并附加 `source_file` 便于溯源。

参数说明补充：

- `--years`：要解析的年份列表（默认 `2019 2020`）

## 按中英文拆分年度 CSV

可将年度总表（如 `2019.csv`、`2020.csv`）按语言拆分为 `YYYY-zh.csv` 与 `YYYY-en.csv`：

```bash
cd cscdspider
python split_cscd_csv_by_lang.py --inputs 2019.csv 2020.csv
# 或指定输入与输出目录
python split_cscd_csv_by_lang.py --inputs "D:\路径\2019.csv" --out "D:\路径\输出"
```

拆分规则：

- 仅根据 `题名` 字段判定
- `题名` 含中文字符 -> 写入 `*-zh.csv`
- `题名` 不含中文字符 -> 写入 `*-en.csv`
- `题名` 为空时默认写入 `*-zh.csv`

脚本会对每个输入文件打印 `total / zh / en`，并校验 `zh + en == total`；若不相等则报错退出。

## 说明

- 运行入口固定使用 `python run.py ...`，不需要 `python -m`。
- 如页面结构变化，请更新 `selectors.py` 中的选择器。
- 若未传 `--limit`，脚本会使用页面识别到的“篇文献”总数作为抓取上限。
