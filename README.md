# cscdspider

基于 Playwright 的 CSCD 导出自动化脚本，按 `http://sciencechina.cn/simple` 的交互流程实现：

- 点击“添加论文发表日期范围”
- 起始/结束年份输入同一年（如 2019）
- 点击“检索”并读取结果总数
- 按 `20 条/页 * 50 页 = 1000 条` 分批勾选与导出
- 每批导出后点击两次“所有记录”清空，再继续下一批

## 安装

```bash
cd cscdspider
pip install -r requirements.txt
playwright install
```

## 运行

### 1) 常规有头运行（默认）

```bash
python run.py --year 2019 --limit 2000
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

### 4) 自定义下载目录

```bash
python run.py --year 2019 --limit 1000 --download-dir "D:\\data\\cscd"
```

## 参数说明

- `--year`：检索年份（必填）
- `--limit`：目标条数（默认 `2000`）
- `--start-page`：从指定页开始（默认 `1`，输入框直跳）
- `--download-dir`：自定义下载目录
- `--headless`：启用无头模式（默认不启用，保持有界面）

## 输出目录

- 下载文件：`cscdspider/downloads/`
- 运行日志：`cscdspider/logs/run.log`
- 批次报告：`cscdspider/reports/report_*.json`

报告包含：

- 站点返回总数
- 每批页范围（如 `1-50`、`51-100`）
- 每批条数与状态
- 导出文件路径

## 说明

- 运行入口固定使用 `python run.py ...`，不需要 `python -m`。
- 如页面结构变化，请更新 `selectors.py` 中的选择器。
