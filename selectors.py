from __future__ import annotations

# 关键操作使用“多选择器兜底”，优先文本和语义，避免仅依赖动态 class。

ENTER_SIMPLE_SEARCH_BUTTONS = [
    "div.page_gradientBtn__xop1d:has-text('进入检索')",
]

ADD_DATE_RANGE_BUTTONS = [
    "button.styles_card-add2__5n8Dd",
    "button:has-text('添加论文发表日期范围')",
]

DATE_RANGE_START_INPUTS = [
    "input[date-range='start']",
    "input[placeholder*='论文发表从']",
]

DATE_RANGE_END_INPUTS = [
    "input[date-range='end']",
    "input[placeholder*='到（例：']",
]

SEARCH_BUTTONS = [
    "button.styles_card-submit__B3evQ",
    "button:has-text('检索')",
]

RESULT_COUNT_TEXT_PATTERNS = [
    r"共\s*([0-9,]+)\s*条",
    r"([0-9,]+)\s*篇文献",
    r"检索结果\s*([0-9,]+)",
    r"([0-9,]+)\s*条/页",
]

PAGE_SIZE_TRIGGER_SELECTORS = [
    "div.ant-select-selector:has-text('10条/页')",
    "div.ant-select-selector:has-text('20条/页')",
]

PAGE_SIZE_20_OPTIONS = [
    "div.ant-select-item-option-content:has-text('20条/页')",
    "div[title='20条/页']",
]

CURRENT_PAGE_CHECKBOX_SELECTORS = [
    "label.ant-checkbox-wrapper:has(span:has-text('本页')) input.ant-checkbox-input",
    "label:has-text('本页') input.ant-checkbox-input",
    "table thead input.ant-checkbox-input",
]

ALL_RECORDS_CHECKBOX_SELECTORS = [
    "text=所有记录",
    "label:has-text('所有记录') input.ant-checkbox-input",
]

NEXT_PAGE_BUTTON_SELECTORS = [
    "button.ant-pagination-item-link:has(span[aria-label='right'])",
    "li.ant-pagination-next button",
]

PAGINATION_PAGE_INPUT_SELECTORS = [
    "li.ant-pagination-simple-pager input",
    "li[title*='/'] input",
]

EXPORT_MENU_BUTTON_SELECTORS = [
    "button:has-text('导出方式')",
]

EXPORT_DOWNLOAD_MENUITEM_SELECTORS = [
    "li[role='menuitem']:has-text('下载')",
]

EXPORT_PANEL_SELECT_ALL_CHECKBOX_SELECTORS = [
    "label:has-text('全选') input.ant-checkbox-input",
    "div:has-text('全选') input.ant-checkbox-input",
]

EXPORT_SUBMIT_BUTTON_SELECTORS = [
    "button.primary-btn.Export_btn__hVJKw:has-text('导出')",
    ".ant-modal-content button:has-text('导出')",
]

LOADING_OVERLAY_SELECTORS = [
    "div.useLoading_loading-overlay__MIFyx",
    "div.ant-spin-fullscreen.ant-spin-fullscreen-show",
    "span.ant-spin-dot.ant-spin-dot-spin",
]
