# cscdspider

基于 Playwright 的 CSCD 导出自动化脚本，针对 `http://sciencechina.cn/simple` 的实际交互流程实现：

- 先进入检索页（处理首页跳转）
- 添加论文发表日期范围（起止同年）
- 统计检索结果总数
- 按 `20条/页 * 50页 = 1000条` 分批勾选导出
- 每批导出后双击“所有记录”取消勾选，再进入下一批

## 1. 安装

```bash
cd cscdspider
pip install -r requirements.txt
playwright install
```

## 2. 运行

### 按年份抓取前 2000 条（你的测试需求）

```bash
python run.py --year 2019 --limit 2000
```

### 从指定页恢复（例如从第 51 页继续）

```bash
python run.py --year 2019 --limit 1000 --start-page 51
```

### 指定下载目录

```bash
python run.py --year 2019 --limit 1000 --download-dir "D:\\data\\cscd"
```

## 3. 输出目录

- 下载文件：`cscdspider/downloads/`
- 运行日志：`cscdspider/logs/run.log`
- 批次报告：`cscdspider/reports/report_*.json`

报告包含：

- 站点返回的检索总数
- 每批开始/结束页（如 1-50、51-100）
- 每批条数（最多 1000）
- 导出文件路径与状态

## 4. 重要约束

- 强制非无头模式。传 `--headless` 会直接报错。
- 运行方式为 `python run.py ...`，不使用 `python -m ...`。

## 5. 常见问题

- **无法点击“添加论文发表日期范围”**  
  站点可能先落在首页，脚本已自动点击“进入检索”；若页面结构变化，请更新 `selectors.py`。

- **导出失败/下载慢**  
  通常是站点响应波动。重跑同样命令即可；必要时减小 `--limit` 分段执行。

- **中断后如何继续**  
  记录中断时页码，用 `--start-page` 从下一页恢复；例如第 50 页导出完成后，从 51 开始。
# cscdspider

Automation for [Science China](http://sciencechina.cn/simple) CSCD exports: start from the **simple search** page, restrict by **publication year range** (same start/end year), then select per-page checkboxes and export in batches of up to 1000 records.

## Quick start

1. Install dependencies:

```bash
cd cscdspider
pip install -r requirements.txt
python -m playwright install chrome
```

在 **`cscdspider` 目录** 下直接运行（无需 `-m`）：

```powershell
cd D:\课程\计算社会科学\玄学研究\cscdspider
python run.py --years 2019 --max-records 2000
```

填完年份后**默认不额外 sleep**，`fill`/`click` 由 Playwright 顺序执行即可。若你机器上需缓冲，可设 `--after-fill-sleep 2` 或 `CSCD_AFTER_YEAR_FILL_SLEEP_SEC`。

脚本**只使用 [简单检索页](http://sciencechina.cn/simple)** 内的发表年条件 + 主「检索」；**不会**在结果页用侧栏「出版年」分面、精炼等旧式筛年。

或双击 / 运行：`run_spider.bat --years 2019 --max-records 2000`

从上一级目录也可：`python cscdspider\run.py --years 2019 ...`（在 `玄学研究` 下）。

2. **不要加 `--headless`**，以便观察浏览器操作。首次请在有界面模式下运行，并在浏览器中完成机构认证（如「北京大学用户」登录）。

- 默认入口为 **简单检索**：`http://sciencechina.cn/simple`（写死在 [`config.py`](config.py) 的 `SIMPLE_SEARCH_URL`；可用环境变量 `CSCD_TARGET_URL` 或 `--target-url` 覆盖调试）。
- 脚本会点击「添加论文发表日期范围」，在「从 / 到」输入**同一年**（如 2019），再点「检索」，然后按分页勾选并导出。

仅当脚本已稳定、无需观察界面时，才使用 `--headless` 做后台跑批。

3. **每页条数**：进入检索结果后，脚本会自动打开分页区的 `ant-select`，将 **「10条/页」改为「20条/页」**，再按「本页」+「下一页」循环（每批最多 50 页 × 20 条 = 1000 条）并导出。批次页数仍由 `build_batch_plan` 按每页 20 条计算。

4. Outputs:

- Downloads: `cscdspider/data/downloads/`
- Run log: `cscdspider/data/run_log.jsonl`
- Resume state: `cscdspider/data/export_state.json`

## Environment variables

| Variable | Meaning |
|----------|---------|
| `CSCD_TARGET_URL` | 入口 URL（默认 `http://sciencechina.cn/simple`） |
| `CSCD_USER_DATA_DIR` | Persistent browser profile directory |
| `CSCD_DOWNLOAD_DIR` | Export download directory |
| `CSCD_RUN_LOG` | JSONL log path |
| `CSCD_STATE_PATH` | Resume state JSON path |
| `CSCD_BATCH_SIZE` | Max records per export (default 1000) |
| `CSCD_PAGE_SIZE` | Default records per page if auto-detect fails (default 20) |
| `CSCD_MAX_RECORDS` | Cap total exported records (0 = no cap) |
| `CSCD_AFTER_YEAR_FILL_SLEEP_SEC` | Extra seconds after filling year before 检索 (default 0) |
| `CSCD_HEADLESS` | `true` / `false` |
| `CSCD_MAX_RETRIES` | Retries per export batch |
| `CSCD_ACTION_TIMEOUT_MS` | Default action timeout |
| `CSCD_NAV_TIMEOUT_MS` | Navigation / download timeout |
| `CSCD_INTER_BATCH_SLEEP_SEC` | Pause between batches |
| `CSCD_BROWSER_EXECUTABLE` | Optional Chrome path |

## Notes

- Site UI may change; run with a visible browser first to verify selectors.
- Full export of large year sets can take a long time; use `--max-records` for smoke tests.
