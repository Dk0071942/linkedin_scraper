"""Tiny Jinja-friendly i18n.

Picked over Babel/gettext to avoid adding a dependency and an extraction step
for a tool with two languages and a few hundred strings. Each language is just
a flat dict; lookups fall back to English if a key is missing in the target.

Wire-up: app._ctx() reads the `mvp_lang` cookie, exposes `t(key)` and `lang`
in every template context, plus `languages` for the picker.
"""

from typing import Any


LANGUAGES: list[dict[str, str]] = [
    {"code": "en", "name": "English"},
    {"code": "zh", "name": "中文"},
]
SUPPORTED_CODES: set[str] = {lang["code"] for lang in LANGUAGES}
DEFAULT_LANG: str = "en"


_EN: dict[str, str] = {
    # Brand + nav
    "brand": "LinkedIn Scraper",
    "nav.jobs": "Jobs",
    "nav.discarded": "Discarded",
    "nav.map": "Map",
    "nav.config": "Config",
    "nav.run": "Run",
    "footer.tagline": "mvp · run via",

    # Status pill in header
    "status.idle": "idle",

    # Common
    "common.save": "Save",
    "common.saved": "Saved ✓",
    "common.error": "Error",
    "common.back": "Back",
    "common.untitled": "(untitled)",
    "common.none_dash": "-",
    "common.loading": "loading…",

    # Jobs / Discarded list pages
    "jobs.heading.kept": "Kept jobs",
    "jobs.heading.discarded": "Discarded jobs",
    "jobs.counts": "{kept} kept · {disc} discarded",
    "jobs.search_placeholder": "Filter by title, company, or location…",
    "jobs.empty.no_match": "No jobs match",
    "jobs.empty.kept": "No kept jobs yet.",
    "jobs.empty.discarded": "No discarded jobs yet.",
    "jobs.empty.cta_prefix": "Configure your",
    "jobs.empty.cta_searches": "searches",
    "jobs.empty.cta_and_start": "and start a",
    "jobs.empty.cta_run": "run",
    "jobs.col.title": "Title",
    "jobs.col.company": "Company",
    "jobs.col.location": "Location",
    "jobs.col.workplace": "Workplace",
    "jobs.col.posted": "Posted",
    "jobs.col.status": "Status",
    "jobs.posted.days_ago": "{n}d ago",

    # Job detail
    "detail.back_to_jobs": "← Back to jobs",
    "detail.back_to_discarded": "← Back to discarded",
    "detail.open_linkedin": "Open on LinkedIn ↗",
    "detail.posted_label": "Posted:",
    "detail.discarded_badge": "Discarded",
    "detail.restore": "Restore to kept jobs",
    "detail.discard": "Move to discarded",
    "detail.copy_for_llm": "Copy for LLM",
    "detail.copy_for_llm.copied": "Copied!",
    "detail.copy_for_llm.failed": "Copy failed",
    "detail.description": "Job description",
    "detail.no_description": "No description scraped.",
    "detail.llm_prompt": (
        "Please draft a tailored motivation letter for the following job. "
        "Match my CV to the role, highlight relevant experience, and keep "
        "the tone professional but warm. Ask me for my CV if you do not "
        "have it."
    ),

    # Application card
    "app.heading": "Application",
    "app.field.status": "Status",
    "app.field.applied_at": "Applied at",
    "app.field.rejected_at": "Rejected at",
    "app.field.accepted_at": "Accepted at",
    "app.field.cv_version": "CV version",
    "app.field.cv_version.placeholder": "e.g. cv-2026-04-data.pdf",
    "app.field.motivation_letter": "Motivation letter",
    "app.field.motivation_letter.placeholder": "Drafted motivation letter…",
    "app.field.notes": "Notes",
    "app.add_event_summary": "Add history event",
    "app.add_event.placeholder": "e.g. submitted via easy apply",
    "app.add_event.notes_placeholder": "optional notes",
    "app.history": "History",
    "app.save": "Save application",
    "app.status.not_applied": "not applied",
    "app.status.drafted": "drafted",
    "app.status.applied": "applied",
    "app.status.interviewing": "interviewing",
    "app.status.accepted": "accepted",
    "app.status.rejected": "rejected",
    "app.status.withdrawn": "withdrawn",

    # Config page
    "config.heading": "Config",
    "config.searches.heading": "Searches",
    "config.searches.add": "+ Add search",
    "config.searches.help": (
        "Each row is a LinkedIn-side search query. Use multiple broad rows "
        "to maximize recall; the per-field filter below narrows results."
    ),
    "config.searches.kw_placeholder": "keywords (e.g. engineer)",
    "config.searches.loc_placeholder": "location (e.g. Germany)",
    "config.filters.heading": "Filters",
    "config.filters.help": (
        "One keyword per line. Across fields = AND. Within a field, "
        "include is OR. Leave a textarea empty to skip that field."
    ),
    "config.filters.field.job_title": "Job title",
    "config.filters.field.location": "Location",
    "config.filters.field.job_description": "Job description",
    "config.filters.field.workplace_type": "Workplace type (must be one of)",
    "config.filters.field.employment_type": "Employment type (must be one of)",
    "config.filters.field.posted_within_days": "Posted within (days)",
    "config.filters.field.posted_within_days.placeholder": "leave empty to skip date filter",
    "config.filters.field.case_sensitive": "Case-sensitive matching",
    "config.filters.include": "Include (any match)",
    "config.filters.exclude": "Exclude (none may match)",
    "config.scrape.heading": "Scrape settings",
    "config.scrape.delay": "Delay between job pages (seconds)",
    "config.scrape.randomize": "Randomize 100%–300% of base delay",
    "config.scrape.session_file": "Session file",
    "config.scrape.data_dir": "Data directory",
    "config.save": "Save config",
    "config.backup_note": "A backup is written to mvp/config.yaml.bak on every save.",
    "config.error.no_searches": "Add at least one search row.",

    # Run page
    "run.controls": "Controls",
    "run.start": "▶ Start scrape",
    "run.rescrape": "↻ Rescrape (wipe data/)",
    "run.rescrape_confirm": "Wipe data/ and re-scrape from scratch?",
    "run.login": "🔑 Log in to LinkedIn",
    "run.stop": "■ Stop",
    "run.status.heading": "Status",
    "run.status.state": "State",
    "run.status.started": "Started",
    "run.status.finished": "Finished",
    "run.summary.searches": "Searches",
    "run.summary.urls_found": "URLs found",
    "run.summary.scraped": "Scraped",
    "run.summary.matched": "Matched",
    "run.summary.failed": "Failed",
    "run.live_log": "Live log",
    "run.clear": "clear",
    "run.run_finished": "--- run finished ---",

    # Map
    "map.heading": "Job locations",
    "map.legend.kept_onsite": "Kept · On-site",
    "map.legend.kept_hybrid": "Kept · Hybrid",
    "map.legend.discarded": "Discarded",
    "map.note": (
        "Geocoding via OpenStreetMap Nominatim · Remote-only jobs hidden · "
        "Toggle layers via the control on the top right of the map."
    ),
    "map.layer.kept": "Kept",
    "map.layer.discarded": "Discarded",
    "map.failed": "Failed to load map data",
    "map.popup.discarded": "(discarded)",
}


_ZH: dict[str, str] = {
    # Brand + nav
    "brand": "LinkedIn 抓取器",
    "nav.jobs": "职位",
    "nav.discarded": "已丢弃",
    "nav.map": "地图",
    "nav.config": "配置",
    "nav.run": "运行",
    "footer.tagline": "mvp · 启动方式",

    # Status pill in header
    "status.idle": "空闲",

    # Common
    "common.save": "保存",
    "common.saved": "已保存 ✓",
    "common.error": "错误",
    "common.back": "返回",
    "common.untitled": "(无标题)",
    "common.none_dash": "-",
    "common.loading": "加载中…",

    # Jobs / Discarded list pages
    "jobs.heading.kept": "保留的职位",
    "jobs.heading.discarded": "已丢弃的职位",
    "jobs.counts": "{kept} 保留 · {disc} 已丢弃",
    "jobs.search_placeholder": "按标题、公司或地点过滤…",
    "jobs.empty.no_match": "没有匹配的职位",
    "jobs.empty.kept": "暂无保留的职位。",
    "jobs.empty.discarded": "暂无已丢弃的职位。",
    "jobs.empty.cta_prefix": "请先配置",
    "jobs.empty.cta_searches": "搜索条件",
    "jobs.empty.cta_and_start": "并开始一次",
    "jobs.empty.cta_run": "运行",
    "jobs.col.title": "标题",
    "jobs.col.company": "公司",
    "jobs.col.location": "地点",
    "jobs.col.workplace": "工作方式",
    "jobs.col.posted": "发布时间",
    "jobs.col.status": "状态",
    "jobs.posted.days_ago": "{n} 天前",

    # Job detail
    "detail.back_to_jobs": "← 返回职位列表",
    "detail.back_to_discarded": "← 返回已丢弃列表",
    "detail.open_linkedin": "在 LinkedIn 打开 ↗",
    "detail.posted_label": "发布时间:",
    "detail.discarded_badge": "已丢弃",
    "detail.restore": "恢复为保留职位",
    "detail.discard": "移至已丢弃",
    "detail.copy_for_llm": "复制给 LLM",
    "detail.copy_for_llm.copied": "已复制!",
    "detail.copy_for_llm.failed": "复制失败",
    "detail.description": "职位描述",
    "detail.no_description": "未抓取到描述。",
    "detail.llm_prompt": (
        "请根据以下职位草拟一封量身定制的求职信。结合我的简历突出相关经验,"
        "语气保持专业且友好。如果你没有我的简历,请向我索取。"
    ),

    # Application card
    "app.heading": "申请",
    "app.field.status": "状态",
    "app.field.applied_at": "申请日期",
    "app.field.rejected_at": "被拒日期",
    "app.field.accepted_at": "录用日期",
    "app.field.cv_version": "简历版本",
    "app.field.cv_version.placeholder": "例如 cv-2026-04-data.pdf",
    "app.field.motivation_letter": "求职信",
    "app.field.motivation_letter.placeholder": "起草的求职信…",
    "app.field.notes": "备注",
    "app.add_event_summary": "添加历史事件",
    "app.add_event.placeholder": "例如:通过 Easy Apply 提交",
    "app.add_event.notes_placeholder": "可选备注",
    "app.history": "历史",
    "app.save": "保存申请",
    "app.status.not_applied": "未申请",
    "app.status.drafted": "已起草",
    "app.status.applied": "已申请",
    "app.status.interviewing": "面试中",
    "app.status.accepted": "已录用",
    "app.status.rejected": "已拒绝",
    "app.status.withdrawn": "已撤回",

    # Config page
    "config.heading": "配置",
    "config.searches.heading": "搜索条件",
    "config.searches.add": "+ 添加搜索",
    "config.searches.help": (
        "每一行是一个 LinkedIn 端的搜索查询。使用多条宽泛的搜索可以"
        "提高召回率,下方的逐字段过滤再做精确筛选。"
    ),
    "config.searches.kw_placeholder": "关键词 (如 engineer)",
    "config.searches.loc_placeholder": "地点 (如 Germany)",
    "config.filters.heading": "过滤条件",
    "config.filters.help": (
        "每行一个关键词。跨字段为 AND。同一字段内,include 为 OR。"
        "留空则跳过该字段。"
    ),
    "config.filters.field.job_title": "职位标题",
    "config.filters.field.location": "地点",
    "config.filters.field.job_description": "职位描述",
    "config.filters.field.workplace_type": "工作方式 (必须为以下之一)",
    "config.filters.field.employment_type": "雇佣类型 (必须为以下之一)",
    "config.filters.field.posted_within_days": "发布于 (天内)",
    "config.filters.field.posted_within_days.placeholder": "留空则不限日期",
    "config.filters.field.case_sensitive": "区分大小写",
    "config.filters.include": "包含 (任一匹配)",
    "config.filters.exclude": "排除 (任一出现即排除)",
    "config.scrape.heading": "抓取设置",
    "config.scrape.delay": "每个职位页之间的延迟 (秒)",
    "config.scrape.randomize": "在基础延迟的 100%–300% 范围内随机",
    "config.scrape.session_file": "会话文件",
    "config.scrape.data_dir": "数据目录",
    "config.save": "保存配置",
    "config.backup_note": "每次保存都会写入备份至 mvp/config.yaml.bak。",
    "config.error.no_searches": "至少需要一行搜索条件。",

    # Run page
    "run.controls": "控制",
    "run.start": "▶ 开始抓取",
    "run.rescrape": "↻ 重新抓取 (清空 data/)",
    "run.rescrape_confirm": "清空 data/ 并从头重新抓取?",
    "run.login": "🔑 登录 LinkedIn",
    "run.stop": "■ 停止",
    "run.status.heading": "状态",
    "run.status.state": "状态",
    "run.status.started": "开始时间",
    "run.status.finished": "结束时间",
    "run.summary.searches": "搜索次数",
    "run.summary.urls_found": "找到的 URL",
    "run.summary.scraped": "已抓取",
    "run.summary.matched": "匹配",
    "run.summary.failed": "失败",
    "run.live_log": "实时日志",
    "run.clear": "清空",
    "run.run_finished": "--- 运行结束 ---",

    # Map
    "map.heading": "职位地点",
    "map.legend.kept_onsite": "保留 · 现场",
    "map.legend.kept_hybrid": "保留 · 混合",
    "map.legend.discarded": "已丢弃",
    "map.note": (
        "通过 OpenStreetMap Nominatim 进行地理编码 · 仅远程职位隐藏 · "
        "通过地图右上角的控件切换图层。"
    ),
    "map.layer.kept": "保留",
    "map.layer.discarded": "已丢弃",
    "map.failed": "加载地图数据失败",
    "map.popup.discarded": "(已丢弃)",
}


TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": _EN,
    "zh": _ZH,
}


def normalize(code: str) -> str:
    """Normalize a language code; fall back to default if unsupported."""
    if not code:
        return DEFAULT_LANG
    return code if code in SUPPORTED_CODES else DEFAULT_LANG


def translate(key: str, lang: str = DEFAULT_LANG, **fmt: Any) -> str:
    """Translate `key` to `lang`. Falls back to English; falls back to the
    raw key if even English is missing. `fmt` provides {param} substitutions.
    """
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANG]
    text = table.get(key) or TRANSLATIONS[DEFAULT_LANG].get(key, key)
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text
