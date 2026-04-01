from __future__ import annotations

import asyncio
import math
import re
from pathlib import Path
from typing import Iterable

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from config import SpiderConfig
from report import BatchReport, RunReport
import selectors as ui


class CscdSpider:
    def __init__(
        self,
        *,
        year: int,
        limit: int,
        start_page: int,
        download_dir: Path,
        config: SpiderConfig,
        logger,
    ) -> None:
        self.year = year
        self.limit = limit
        self.start_page = max(1, start_page)
        self.download_dir = download_dir
        self.config = config
        self.logger = logger
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def run(self) -> RunReport:
        await self._start_browser()
        try:
            await self._open_homepage()
            await self._apply_year_filter(self.year)
            total_results = await self._read_total_results()
            self.logger.info("站点检索结果总数: %s", total_results)
            report = RunReport(
                year=self.year,
                limit=self.limit,
                total_results_reported_by_site=total_results,
            )
            await self._goto_start_page_if_needed()
            await self._set_page_size_to_20()
            await self._run_batches(report)
            report.complete()
            return report
        except Exception as err:
            self.logger.exception("执行失败: %s", err)
            failed_report = RunReport(
                year=self.year,
                limit=self.limit,
                total_results_reported_by_site=0,
            )
            failed_report.fail(err)
            return failed_report
        finally:
            await self._close_browser()

    async def _start_browser(self) -> None:
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                channel="chrome",
                slow_mo=self.config.action_delay_ms,
            )
        except PlaywrightError:
            # 本机未安装可识别 Chrome 时，回退到 Playwright 自带 Chromium。
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                slow_mo=self.config.action_delay_ms,
            )
        self.context = await self.browser.new_context(accept_downloads=True)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.config.default_timeout_ms)

    async def _close_browser(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _open_homepage(self) -> None:
        assert self.page is not None
        await self.page.goto(
            self.config.base_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms
        )
        await self.page.wait_for_timeout(self.config.search_settle_ms)
        if "/simple" not in self.page.url:
            await self._safe_click(ui.ENTER_SIMPLE_SEARCH_BUTTONS, "点击进入检索")
            await self.page.wait_for_url("**/simple", timeout=self.config.navigation_timeout_ms)
            await self.page.wait_for_timeout(self.config.search_settle_ms)

    async def _run_batches(self, report: RunReport) -> None:
        assert self.page is not None
        remaining = self.limit
        current_page = self.start_page
        batch_index = 1

        while remaining > 0:
            batch_records = min(remaining, self.config.max_export_per_batch)
            pages_to_select = min(
                self.config.max_pages_per_batch,
                math.ceil(batch_records / self.config.page_size),
            )
            batch = BatchReport(
                batch_index=batch_index,
                start_page=current_page,
                end_page=current_page + pages_to_select - 1,
                selected_pages=0,
                selected_records=0,
            )

            try:
                actual_pages = await self._select_pages_for_current_batch(pages_to_select)
                if actual_pages <= 0:
                    report.notes.append("无法继续翻页，提前结束。")
                    break
                selected_records = min(batch_records, actual_pages * self.config.page_size)

                batch.selected_pages = actual_pages
                batch.selected_records = selected_records
                batch.end_page = current_page + actual_pages - 1

                downloaded_file = await self._export_selected(batch_index)
                batch.done(downloaded_file)
                report.downloaded_files.append(downloaded_file)
                report.batches.append(batch)

                remaining -= selected_records
                current_page = batch.end_page + 1
                batch_index += 1

                if remaining <= 0:
                    break

                await self._clear_all_record_selection()
                if not await self._go_next_page():
                    report.notes.append("批次结束后无法翻到下一页，提前结束。")
                    break
            except Exception as err:
                batch.fail(err)
                report.batches.append(batch)
                raise

    async def _apply_year_filter(self, year: int) -> None:
        assert self.page is not None
        await self._safe_click(ui.ADD_DATE_RANGE_BUTTONS, "点击添加论文发表日期范围")
        await self._fill_first(ui.DATE_RANGE_START_INPUTS, str(year))
        await self._fill_first(ui.DATE_RANGE_END_INPUTS, str(year))
        await self._safe_click(ui.SEARCH_BUTTONS, "点击检索按钮")
        await self.page.wait_for_timeout(self.config.search_settle_ms)

    async def _read_total_results(self) -> int:
        assert self.page is not None
        body_text = await self.page.inner_text("body")
        for pattern in ui.RESULT_COUNT_TEXT_PATTERNS:
            found = re.search(pattern, body_text)
            if not found:
                continue
            number = int(found.group(1).replace(",", ""))
            if number > 0:
                return number
        self.logger.warning("未能稳定识别检索总数，默认按 limit 执行。")
        return self.limit

    async def _goto_start_page_if_needed(self) -> None:
        if self.start_page <= 1:
            return
        self.logger.info("从第 %s 页恢复，开始逐页跳转。", self.start_page)
        for _ in range(1, self.start_page):
            moved = await self._go_next_page()
            if not moved:
                raise RuntimeError(f"无法跳转到 start_page={self.start_page}，提前到达末页。")

    async def _set_page_size_to_20(self) -> None:
        assert self.page is not None
        current = await self.page.locator("span.ant-select-selection-item").first.text_content()
        if current and "20条/页" in current:
            return

        await self._safe_click(ui.PAGE_SIZE_TRIGGER_SELECTORS, "点击页大小下拉框")
        await self._safe_click(ui.PAGE_SIZE_20_OPTIONS, "选择20条/页")
        await self.page.wait_for_timeout(1200)

    async def _select_pages_for_current_batch(self, pages_to_select: int) -> int:
        selected_pages = 0
        for i in range(pages_to_select):
            await self._ensure_checkbox_checked(ui.CURRENT_PAGE_CHECKBOX_SELECTORS, "本页勾选")
            selected_pages += 1
            if i == pages_to_select - 1:
                break
            moved = await self._go_next_page()
            if not moved:
                break
        return selected_pages

    async def _go_next_page(self) -> bool:
        assert self.page is not None
        if await self.page.locator("li.ant-pagination-next.ant-pagination-disabled").count() > 0:
            return False
        try:
            await self._safe_click(ui.NEXT_PAGE_BUTTON_SELECTORS, "点击下一页按钮")
            await self.page.wait_for_load_state("domcontentloaded")
            await self.page.wait_for_timeout(1000)
            return True
        except Exception:
            return False

    async def _export_selected(self, batch_index: int) -> str:
        assert self.page is not None
        await self._safe_click(ui.EXPORT_MENU_BUTTON_SELECTORS, "点击导出方式菜单")
        await self._safe_click(ui.EXPORT_DOWNLOAD_MENUITEM_SELECTORS, "选择下载导出")
        await self._ensure_checkbox_checked(ui.EXPORT_PANEL_SELECT_ALL_CHECKBOX_SELECTORS, "导出面板全选")

        export_button = await self._first_visible_locator(ui.EXPORT_SUBMIT_BUTTON_SELECTORS)
        async with self.page.expect_download(timeout=self.config.download_timeout_ms) as download_info:
            await export_button.click()
        download = await download_info.value

        suggested_name = download.suggested_filename or f"batch_{batch_index}.xlsx"
        output_name = f"batch_{batch_index:03d}_{suggested_name}"
        output_path = self.download_dir / output_name
        await download.save_as(str(output_path))
        self.logger.info("批次 %s 下载完成: %s", batch_index, output_path)
        return str(output_path)

    async def _clear_all_record_selection(self) -> None:
        await self._click_checkbox_toggle(ui.ALL_RECORDS_CHECKBOX_SELECTORS, "所有记录取消(1/2)")
        await self._click_checkbox_toggle(ui.ALL_RECORDS_CHECKBOX_SELECTORS, "所有记录取消(2/2)")

    async def _click_checkbox_toggle(self, selectors: Iterable[str], action_name: str) -> None:
        locator = await self._first_visible_locator(selectors)
        await locator.click()
        await self._wait_for_retry()
        self.logger.info("%s 完成。", action_name)

    async def _ensure_checkbox_checked(self, selectors: Iterable[str], action_name: str) -> None:
        locator = await self._first_visible_locator(selectors)
        try:
            is_checked = await locator.is_checked()
        except PlaywrightError:
            is_checked = False
        if not is_checked:
            await locator.click()
            await self._wait_for_retry()
        self.logger.info("%s 完成。", action_name)

    async def _fill_first(self, selectors: Iterable[str], value: str) -> None:
        locator = await self._first_visible_locator(selectors)
        await locator.fill(value)
        await self._wait_for_retry()

    async def _safe_click(self, selectors: Iterable[str], action_name: str) -> None:
        last_err: Exception | None = None
        for _ in range(self.config.click_retry_times):
            try:
                locator = await self._first_visible_locator(selectors)
                await locator.click()
                await self._wait_for_retry()
                self.logger.info("%s 成功。", action_name)
                return
            except Exception as err:  # noqa: PERF203
                last_err = err
                await self._wait_for_retry()
        raise RuntimeError(f"{action_name} 失败: {last_err}")

    async def _first_visible_locator(self, selectors: Iterable[str]) -> Locator:
        assert self.page is not None
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=4_000)
                return locator
            except PlaywrightTimeoutError:
                continue
        raise RuntimeError(f"无法找到可见元素: {list(selectors)}")

    async def _wait_for_retry(self) -> None:
        await asyncio.sleep(self.config.click_retry_wait_ms / 1000)
