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

# 结果列表排序目标（与站点下拉文案一致）
SORT_TITLE_ASC_LABEL = "题名：升序"


def _normalize_sort_label(s: str | None) -> str:
    if not s:
        return ""
    t = s.strip().replace("：", ":")
    return re.sub(r"\s+", "", t)


class CscdSpider:
    def __init__(
        self,
        *,
        year: int,
        limit: int | None,
        start_page: int,
        download_dir: Path,
        config: SpiderConfig,
        logger,
        headless: bool = False,
    ) -> None:
        self.year = year
        self.limit = limit
        self.start_page = max(1, start_page)
        self.download_dir = download_dir
        self.config = config
        self.logger = logger
        self.headless = headless
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        # 整页恢复过程中禁止「遮罩双超时→再次刷新」嵌套
        self._inside_hard_recover: bool = False

    async def run(self) -> RunReport:
        await self._start_browser()
        try:
            await self._open_homepage()
            await self._apply_year_filter(self.year)
            total_results = await self._read_total_results()
            self.logger.info("站点检索结果总数: %s", total_results)
            effective_limit = self.limit if self.limit is not None else total_results
            if effective_limit <= 0:
                raise RuntimeError("无法识别站点检索总数，且未显式提供 --limit。")
            report = RunReport(
                year=self.year,
                limit=effective_limit,
                total_results_reported_by_site=total_results,
            )
            # 先每页条数再排序（改条数会整表刷新，可能打回默认排序）
            await self._prepare_results_view()
            await self._verify_sort_alignment(context="prepare完成后", auto_fix=True)
            await self._verify_page_alignment(
                expected_page=1,
                context="prepare完成后",
                auto_fix=True,
            )
            await self._goto_start_page_if_needed()
            await self._verify_sort_alignment(context="起始页就绪后", auto_fix=True)
            await self._run_batches(report, effective_limit)
            report.complete()
            return report
        except Exception as err:
            self.logger.exception("执行失败: %s", err)
            failed_report = RunReport(
                year=self.year,
                limit=self.limit or 0,
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
                headless=self.headless,
                channel="chrome",
                slow_mo=self.config.action_delay_ms,
            )
        except PlaywrightError:
            # 本机未安装可识别 Chrome 时，回退到 Playwright 自带 Chromium。
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
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

    async def _run_batches(self, report: RunReport, limit: int) -> None:
        assert self.page is not None
        remaining = limit
        current_page = self.start_page
        batch_index = 1

        while remaining > 0:
            await self._verify_page_alignment(
                expected_page=current_page,
                context=f"批次{batch_index}开始前",
                auto_fix=True,
            )
            await self._verify_sort_alignment(
                context=f"批次{batch_index}开始前",
                auto_fix=True,
            )
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
                actual_pages = await self._select_pages_for_current_batch(
                    pages_to_select=pages_to_select,
                    expected_start_page=current_page,
                )
                if actual_pages <= 0:
                    report.notes.append("无法继续翻页，提前结束。")
                    break
                selected_records = min(batch_records, actual_pages * self.config.page_size)

                batch.selected_pages = actual_pages
                batch.selected_records = selected_records
                batch.end_page = current_page + actual_pages - 1

                try:
                    downloaded_file = await self._export_selected(
                        start_page=batch.start_page,
                        end_page=batch.end_page,
                    )
                except Exception as export_err:
                    self.logger.warning(
                        "批次 %s 导出失败，整页恢复后从第 %s 页重勾本批: %s",
                        batch_index,
                        batch.start_page,
                        export_err,
                    )
                    await self._hard_recover_state(batch.start_page)
                    actual_pages = await self._select_pages_for_current_batch(
                        pages_to_select=pages_to_select,
                        expected_start_page=batch.start_page,
                    )
                    if actual_pages <= 0:
                        raise RuntimeError("整页恢复后仍无法完成本批页勾选。") from export_err
                    selected_records = min(batch_records, actual_pages * self.config.page_size)
                    batch.selected_pages = actual_pages
                    batch.selected_records = selected_records
                    batch.end_page = batch.start_page + actual_pages - 1
                    downloaded_file = await self._export_selected(
                        start_page=batch.start_page,
                        end_page=batch.end_page,
                    )
                batch.done(downloaded_file)
                report.downloaded_files.append(downloaded_file)
                report.batches.append(batch)

                remaining -= selected_records
                current_page = batch.end_page + 1
                batch_index += 1

                if remaining <= 0:
                    break

                await self._clear_all_record_selection()
                if not await self._go_next_page(expected_after=current_page):
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
        assert self.page is not None
        self.logger.info("从第 %s 页恢复，使用分页输入框直接跳转。", self.start_page)
        page_input = await self._first_visible_locator(ui.PAGINATION_PAGE_INPUT_SELECTORS)
        await page_input.click()
        await page_input.fill(str(self.start_page))
        await page_input.press("Enter")
        await self.page.wait_for_timeout(1500)

        jumped_ok = await self._is_current_page(self.start_page)
        if not jumped_ok:
            raise RuntimeError(f"分页输入框跳转失败，目标页: {self.start_page}")
        await self._verify_page_alignment(
            expected_page=self.start_page,
            context="start-page跳转后",
            auto_fix=False,
        )

    async def _is_current_page(self, expected_page: int) -> bool:
        assert self.page is not None
        active_item = self.page.locator("li.ant-pagination-item-active")
        if await active_item.count() > 0:
            text = (await active_item.first.inner_text()).strip()
            if text.isdigit():
                return int(text) == expected_page

        try:
            page_input = await self._first_visible_locator(ui.PAGINATION_PAGE_INPUT_SELECTORS)
            input_value = (await page_input.input_value()).strip()
            if input_value.isdigit():
                return int(input_value) == expected_page
        except Exception:
            return False
        return False

    async def _prepare_results_view(self) -> None:
        """
        检索有结果后的视图准备：先 20条/页，再「题名：升序」。
        切换每页条数会整表刷新，可能把排序打回默认，故排序必须在改条数之后。
        """
        await self._set_page_size_to_20()
        await self._ensure_sort_title_asc()

    async def _read_current_sort_title(self) -> str | None:
        """读取结果区当前排序展示（span.ant-select-selection-item 的 title 或文本）。"""
        assert self.page is not None
        try:
            trigger = await self._sort_trigger_locator()
        except RuntimeError:
            return None
        item = trigger.locator("span.ant-select-selection-item").first
        if await item.count() == 0:
            return None
        title = await item.get_attribute("title")
        if title and title.strip():
            return title.strip()
        text = (await item.text_content() or "").strip()
        return text or None

    async def _sort_trigger_locator(self) -> Locator:
        """结果列表排序用的 ant-select 触发器（排除分页区「每页条数」）。"""
        assert self.page is not None
        for sel in ui.SORT_TRIGGER_SELECTORS:
            loc = self.page.locator(sel).first
            if await loc.count() == 0:
                continue
            try:
                await loc.wait_for(state="visible", timeout=4_000)
                return loc
            except PlaywrightTimeoutError:
                continue

        all_sel = self.page.locator("div.ant-select-selector")
        n = await all_sel.count()
        for i in range(n):
            node = all_sel.nth(i)
            try:
                if not await node.is_visible():
                    continue
            except Exception:
                continue
            in_pag = node.locator("xpath=ancestor::*[contains(@class,'ant-pagination')][1]")
            if await in_pag.count() > 0:
                continue
            item = node.locator("span.ant-select-selection-item").first
            if await item.count() == 0:
                continue
            title = (await item.get_attribute("title")) or ""
            text = (await item.text_content()) or ""
            if "条/页" in title or "条/页" in text:
                continue
            return node
        raise RuntimeError("未找到结果区排序下拉框（ant-select-selector）。")

    async def _ensure_sort_title_asc(self) -> None:
        assert self.page is not None
        await self._wait_loading_overlay_hidden(timeout_ms=8_000)
        cur = await self._read_current_sort_title()
        if _normalize_sort_label(cur) == _normalize_sort_label(SORT_TITLE_ASC_LABEL):
            self.logger.info("排序已为「%s」。", SORT_TITLE_ASC_LABEL)
            return

        await self._wait_loading_overlay_hidden(timeout_ms=8_000)
        trigger = await self._sort_trigger_locator()
        await trigger.click()
        await self._wait_for_retry()
        await self._safe_click(ui.SORT_TITLE_ASC_OPTIONS, "选择题名：升序")
        await self._wait_loading_overlay_hidden(timeout_ms=15_000)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=12_000)
        except PlaywrightTimeoutError:
            await self.page.wait_for_load_state("domcontentloaded")
        await self.page.wait_for_timeout(self.config.search_settle_ms)

    async def _verify_sort_alignment(self, *, context: str, auto_fix: bool) -> None:
        cur = await self._read_current_sort_title()
        ok = _normalize_sort_label(cur) == _normalize_sort_label(SORT_TITLE_ASC_LABEL)
        if ok:
            self.logger.info("[%s] 排序校验通过: %s", context, cur or "(空)")
            return
        msg = (
            f"[{context}] 排序校验失败: 期望「{SORT_TITLE_ASC_LABEL}」，"
            f"当前「{cur!r}」"
        )
        if not auto_fix:
            raise RuntimeError(msg)
        self.logger.warning("%s，尝试重新设为题名升序。", msg)
        await self._ensure_sort_title_asc()
        cur2 = await self._read_current_sort_title()
        if _normalize_sort_label(cur2) != _normalize_sort_label(SORT_TITLE_ASC_LABEL):
            raise RuntimeError(f"{msg}；纠偏后仍为「{cur2!r}」。")
        self.logger.info("[%s] 排序已纠偏为「%s」", context, cur2)

    async def _results_page_likely_ready(self) -> bool:
        assert self.page is not None
        if await self.page.locator("li.ant-pagination-simple-pager").count() > 0:
            return True
        body = await self.page.inner_text("body")
        return bool(re.search(r"篇文献|检索结果", body))

    async def _hard_recover_state(self, expected_page: int) -> None:
        """
        整页刷新后恢复：检索条件、20条/页、题名升序、跳到目标页并校验。
        刷新会清空所有勾选，调用方需重新跑本批勾选循环。
        """
        assert self.page is not None
        self._inside_hard_recover = True
        try:
            self.logger.warning("执行整页恢复，目标起始页=%s", expected_page)
            await self.page.reload(wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
            await self._wait_loading_overlay_hidden(timeout_ms=15_000)
            await self.page.wait_for_timeout(self.config.search_settle_ms)

            if not await self._results_page_likely_ready():
                await self._apply_year_filter(self.year)
                _ = await self._read_total_results()

            await self._prepare_results_view()
            await self._verify_sort_alignment(context="整页恢复后", auto_fix=True)
            await self._verify_page_alignment(
                expected_page=expected_page,
                context="整页恢复后",
                auto_fix=True,
            )
        finally:
            self._inside_hard_recover = False

    async def _read_current_page_for_recover(self) -> int:
        """分页器可读时返回当前页，否则 1（用于遮罩双超时后未传入期望页时的兜底）。"""
        p = await self._read_pagination_progress()
        if p:
            return p[0]
        return 1

    async def _page_size_trigger_locator(self) -> Locator:
        """
        每页条数下拉：优先分页区域；兜底为「展示文案/title 含 条/页」且不含排序语义的 ant-select。
        （站点可能把 selector 放在 ant-pagination-options，或文案只在 title 上，:has-text 会失效）
        """
        assert self.page is not None
        for sel in (
            ".ant-pagination .ant-select-selector",
            "li.ant-pagination-options .ant-select-selector",
            ".ant-pagination-options .ant-select-selector",
        ):
            loc = self.page.locator(sel).first
            if await loc.count() == 0:
                continue
            try:
                await loc.wait_for(state="visible", timeout=4_000)
                return loc
            except PlaywrightTimeoutError:
                continue

        all_sel = self.page.locator("div.ant-select-selector")
        n = await all_sel.count()
        for i in range(n):
            node = all_sel.nth(i)
            try:
                if not await node.is_visible():
                    continue
            except Exception:
                continue
            item = node.locator("span.ant-select-selection-item").first
            if await item.count() == 0:
                continue
            title = (await item.get_attribute("title")) or ""
            text = (await item.text_content()) or ""
            if "条/页" not in title and "条/页" not in text:
                continue
            if "题名" in title or "排序" in title or "默认排序" in title:
                continue
            return node
        raise RuntimeError(
            "未找到每页条数下拉框（分页区 ant-select 或含「条/页」的 selection-item）。"
        )

    async def _set_page_size_to_20(self) -> None:
        assert self.page is not None
        try:
            trigger = await self._page_size_trigger_locator()
            item = trigger.locator("span.ant-select-selection-item").first
            if await item.count() > 0:
                title = (await item.get_attribute("title")) or ""
                text = (await item.text_content()) or ""
                blob = (title + text).replace(" ", "")
                if "20条/页" in blob or ("20" in blob and "条" in blob and "/页" in blob):
                    return
        except RuntimeError:
            pass

        await self._wait_loading_overlay_hidden(timeout_ms=8_000)
        trigger = await self._page_size_trigger_locator()
        await trigger.click()
        await self._wait_for_retry()
        await self._safe_click(ui.PAGE_SIZE_20_OPTIONS, "选择20条/页")
        await self.page.wait_for_timeout(1200)

    async def _select_pages_for_current_batch(self, pages_to_select: int, expected_start_page: int) -> int:
        selected_pages = 0
        for i in range(pages_to_select):
            expected_page = expected_start_page + i
            await self._verify_page_alignment(
                expected_page=expected_page,
                context=f"批次内第{i + 1}/{pages_to_select}次勾选前",
                auto_fix=True,
            )
            await self._verify_sort_alignment(
                context=f"批次内第{i + 1}/{pages_to_select}次勾选前",
                auto_fix=True,
            )
            await self._ensure_checkbox_checked(ui.CURRENT_PAGE_CHECKBOX_SELECTORS, "本页勾选")
            await self._verify_page_alignment(
                expected_page=expected_page,
                context=f"批次内第{i + 1}/{pages_to_select}次勾选后",
                auto_fix=True,
            )
            selected_pages += 1
            if i == pages_to_select - 1:
                break
            moved = await self._go_next_page(expected_after=expected_page + 1)
            if not moved:
                break
        return selected_pages

    async def _go_next_page(self, expected_after: int | None = None) -> bool:
        assert self.page is not None
        if await self.page.locator("li.ant-pagination-next.ant-pagination-disabled").count() > 0:
            return False
        try:
            await self._safe_click(ui.NEXT_PAGE_BUTTON_SELECTORS, "点击下一页按钮")
            await self.page.wait_for_load_state("domcontentloaded")
            await self.page.wait_for_timeout(1000)
            if expected_after is not None:
                await self._verify_page_alignment(
                    expected_page=expected_after,
                    context="点击下一页后",
                    auto_fix=True,
                )
                await self._verify_sort_alignment(
                    context="点击下一页后",
                    auto_fix=True,
                )
            return True
        except Exception:
            return False

    async def _export_selected(self, start_page: int, end_page: int) -> str:
        assert self.page is not None
        await self._safe_click_export_menu()
        await self._safe_click(ui.EXPORT_DOWNLOAD_MENUITEM_SELECTORS, "选择下载导出")
        await self._ensure_checkbox_checked(ui.EXPORT_PANEL_SELECT_ALL_CHECKBOX_SELECTORS, "导出面板全选")

        export_button = await self._first_visible_locator(ui.EXPORT_SUBMIT_BUTTON_SELECTORS)
        async with self.page.expect_download(timeout=self.config.download_timeout_ms) as download_info:
            await export_button.click()
        download = await download_info.value

        suggested_name = download.suggested_filename or f"p{start_page}-{end_page}.xlsx"
        output_name = f"batch_p{start_page}-{end_page}_{suggested_name}"
        output_path = self.download_dir / output_name
        await download.save_as(str(output_path))
        self.logger.info("下载完成: %s", output_path)
        return str(output_path)

    async def _read_pagination_progress(self) -> tuple[int, int] | None:
        """
        读取分页条中的“当前页/总页数”，优先解析 li.ant-pagination-simple-pager 的 title，如“1/23777”。
        返回 (current_page, total_pages)；读不到返回 None。
        """
        assert self.page is not None
        pager = self.page.locator("li.ant-pagination-simple-pager").first
        if await pager.count() == 0:
            return None

        title = (await pager.get_attribute("title") or "").strip()
        if title:
            m = re.search(r"(\d+)\s*/\s*(\d+)", title)
            if m:
                return int(m.group(1)), int(m.group(2))

        try:
            page_input = await self._first_visible_locator(ui.PAGINATION_PAGE_INPUT_SELECTORS)
            current_text = (await page_input.input_value()).strip()
            slash_text = (await pager.inner_text()).strip()
            m2 = re.search(r"/\s*(\d+)", slash_text)
            if current_text.isdigit() and m2:
                return int(current_text), int(m2.group(1))
        except Exception:
            return None
        return None

    async def _jump_to_page(self, target_page: int) -> None:
        assert self.page is not None
        page_input = await self._first_visible_locator(ui.PAGINATION_PAGE_INPUT_SELECTORS)
        await page_input.click()
        await page_input.fill(str(target_page))
        await page_input.press("Enter")
        await self.page.wait_for_timeout(1200)

    async def _verify_page_alignment(
        self,
        *,
        expected_page: int,
        context: str,
        auto_fix: bool,
    ) -> None:
        """
        校验“内部期望页码”与分页条输入框/标题一致；不一致时可自动纠偏跳转。
        """
        progress = await self._read_pagination_progress()
        if progress is None:
            self.logger.warning("[%s] 未读取到分页进度，跳过页码校验。", context)
            return
        ui_current, ui_total = progress
        if ui_current == expected_page:
            self.logger.info("[%s] 页码校验通过: %s/%s", context, ui_current, ui_total)
            return

        msg = (
            f"[{context}] 页码校验失败: 期望第 {expected_page} 页，"
            f"分页条显示 {ui_current}/{ui_total}"
        )
        if not auto_fix:
            raise RuntimeError(msg)

        self.logger.warning("%s，尝试分页输入框纠偏跳转。", msg)
        await self._jump_to_page(expected_page)
        progress2 = await self._read_pagination_progress()
        if progress2 is None:
            raise RuntimeError(f"{msg}；纠偏后仍无法读取分页条。")
        ui_current2, ui_total2 = progress2
        if ui_current2 != expected_page:
            raise RuntimeError(
                f"{msg}；纠偏后仍不一致：{ui_current2}/{ui_total2}"
            )
        self.logger.info(
            "[%s] 页码已纠偏到 %s/%s", context, ui_current2, ui_total2
        )

    async def _clear_all_record_selection(self) -> None:
        await self._click_checkbox_toggle(ui.ALL_RECORDS_CHECKBOX_SELECTORS, "所有记录取消(1/2)")
        await self._click_checkbox_toggle(ui.ALL_RECORDS_CHECKBOX_SELECTORS, "所有记录取消(2/2)")

    async def _wait_loading_overlay_hidden(
        self,
        timeout_ms: int | None = None,
        *,
        expected_page: int | None = None,
    ) -> None:
        """
        等待全屏 loading 遮罩消失，避免点击被 useLoading/ant-spin 拦截。

        同一轮调用中，若前两个遮罩（useLoading 全屏层、ant-spin-fullscreen）**均**等待超时，
        则视为遮罩卡死，执行一次 `page.reload` 并走 `_hard_recover_state`（20条/页、题名升序、
        页码与排序校验）。`expected_page` 可传入期望页码；未传则从分页器读取当前页。
        在 `_hard_recover_state` 内部不会再次触发本逻辑（防嵌套刷新）。
        """
        assert self.page is not None
        t = timeout_ms or self.config.default_timeout_ms
        timeout_idx0 = False
        timeout_idx1 = False
        for i, selector in enumerate(ui.LOADING_OVERLAY_SELECTORS):
            loc = self.page.locator(selector)
            try:
                await loc.first.wait_for(state="hidden", timeout=t)
            except PlaywrightTimeoutError:
                self.logger.warning("等待遮罩消失超时: %s", selector)
                if i == 0:
                    timeout_idx0 = True
                if i == 1:
                    timeout_idx1 = True
            except Exception:
                continue

        if (
            timeout_idx0
            and timeout_idx1
            and not self._inside_hard_recover
        ):
            ep = expected_page if expected_page is not None else await self._read_current_page_for_recover()
            self.logger.warning(
                "同一轮内前两处全屏遮罩均等待超时，执行整页刷新并恢复状态（目标页=%s）。",
                ep,
            )
            await self._hard_recover_state(ep)
            self.logger.warning(
                "整页恢复后勾选已全部清空；若正处于多页批次中途，此前已勾页可能丢失，"
                "本批导出条数可能不足。导出失败时会自动从批次首页整批重勾。"
            )

    async def _safe_click_export_menu(self) -> None:
        """
        导出菜单专用点击：点击前后都等待遮罩消失；失败时再等待并重试。
        """
        assert self.page is not None
        last_err: Exception | None = None
        for _ in range(self.config.click_retry_times):
            try:
                await self._wait_loading_overlay_hidden(timeout_ms=10_000)
                locator = await self._first_visible_locator(ui.EXPORT_MENU_BUTTON_SELECTORS)
                await locator.click()
                await self._wait_for_retry()
                await self._wait_loading_overlay_hidden(timeout_ms=10_000)
                self.logger.info("点击导出方式菜单 成功。")
                return
            except Exception as err:  # noqa: PERF203
                last_err = err
                await self._wait_loading_overlay_hidden(timeout_ms=8_000)
                await self._wait_for_retry()
        raise RuntimeError(f"点击导出方式菜单 失败: {last_err}")

    async def _click_checkbox_toggle(self, selectors: Iterable[str], action_name: str) -> None:
        await self._wait_loading_overlay_hidden(timeout_ms=8_000)
        locator = await self._first_visible_locator(selectors)
        await locator.click()
        await self._wait_for_retry()
        self.logger.info("%s 完成。", action_name)

    async def _ensure_checkbox_checked(self, selectors: Iterable[str], action_name: str) -> None:
        await self._wait_loading_overlay_hidden(timeout_ms=8_000)
        locator = await self._first_visible_locator(selectors)
        checked = False
        try:
            checked = await locator.is_checked()
        except PlaywrightError:
            checked = False

        if checked:
            self.logger.info("%s 完成（已勾选）。", action_name)
            return

        # 站点上的 ant-checkbox-input 经常可见但 click 不稳定，优先使用 check(force=True)。
        try:
            await locator.check(force=True, timeout=self.config.default_timeout_ms)
            await self._wait_for_retry()
        except Exception:
            # 兜底：点所属 label（或内部方框）再校验。
            try:
                label = locator.locator("xpath=ancestor::label[1]").first
                if await label.count() > 0:
                    await label.click(force=True, timeout=self.config.default_timeout_ms)
                    await self._wait_for_retry()
            except Exception:
                pass

        try:
            if not await locator.is_checked():
                inner = locator.locator("xpath=following-sibling::span[contains(@class,'ant-checkbox-inner')][1]")
                if await inner.count() > 0:
                    await inner.click(force=True, timeout=self.config.default_timeout_ms)
                    await self._wait_for_retry()
        except Exception:
            pass

        try:
            final_checked = await locator.is_checked()
        except PlaywrightError:
            final_checked = False
        if not final_checked:
            raise RuntimeError(f"{action_name} 失败：checkbox 未进入 checked 状态。")
        self.logger.info("%s 完成。", action_name)

    async def _fill_first(self, selectors: Iterable[str], value: str) -> None:
        locator = await self._first_visible_locator(selectors)
        await locator.fill(value)
        await self._wait_for_retry()

    async def _safe_click(self, selectors: Iterable[str], action_name: str) -> None:
        last_err: Exception | None = None
        for _ in range(self.config.click_retry_times):
            try:
                await self._wait_loading_overlay_hidden(timeout_ms=8_000)
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
