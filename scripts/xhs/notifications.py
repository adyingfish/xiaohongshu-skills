"""读取网页通知，受控加载更多，并明确区分空列表、失败与未读完。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .errors import NotLoggedInError, XHSError

NOTIFICATIONS_URL = "https://www.xiaohongshu.com/notification"
_SCRIPT = Path(__file__).with_suffix(".js").read_text(encoding="utf-8")
KINDS = ("comments", "mentions", "likes", "follows", "all")


class NotificationError(XHSError):
    """通知页未就绪或数据结构不受支持。"""


def _run(page: Any, action: str, **params: Any) -> dict:
    value = page.evaluate(f"({_SCRIPT})({json.dumps({'action': action, **params})})")
    if not isinstance(value, dict):
        raise NotificationError("通知页面返回了无法识别的数据")
    if value.get("not_logged_in"):
        raise NotLoggedInError()
    if value.get("error") or value.get("__xhs_error"):
        raise NotificationError(value.get("error") or value["__xhs_error"])
    return value


def _wait_ready(page: Any, source: str, *, timeout: float = 12.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        result = _run(page, "read", source=source)
        if result.get("ready"):
            return result
        if time.monotonic() >= deadline:
            raise NotificationError("通知仍未加载完成；未把未就绪或加载失败当成空列表")
        time.sleep(0.3)


def _key(item: dict) -> str:
    return str(item.get("id") or json.dumps(item, sort_keys=True, ensure_ascii=False))


def _read_source(page: Any, source: str, max_pages: int, limit: int) -> dict:
    deadline = time.monotonic() + 12.0
    while not _run(page, "select", source=source).get("selected"):
        if time.monotonic() >= deadline:
            raise NotificationError("通知标签未加载，无法切换到所需分组")
        time.sleep(0.3)
    state = _wait_ready(page, source)
    items: dict[str, dict] = {}
    pages = 1
    stop = "end"
    while True:
        for item in state["items"]:
            items[_key(item)] = item
        if state.get("has_more") is False:
            break
        if len(items) >= limit:
            stop = "limit"
            break
        if pages >= max_pages:
            stop = "max_pages"
            break
        before = (state.get("cursor"), len(items))
        _run(page, "more", source=source)
        deadline = time.monotonic() + 6.0
        while True:
            next_state = _wait_ready(page, source)
            next_keys = {_key(item) for item in next_state["items"]}
            changed = next_state.get("cursor") != before[0] or bool(next_keys - items.keys())
            if changed or next_state.get("has_more") is False:
                state = next_state
                pages += 1
                break
            if time.monotonic() >= deadline:
                state = next_state
                stop = "no_progress"
                break
            time.sleep(0.3)
        if stop == "no_progress":
            break
    return {
        "source": source,
        "items": list(items.values()),
        "has_more": state.get("has_more"),
        "cursor": state.get("cursor", ""),
        "pages": pages,
        "stop_reason": stop,
        "complete": stop == "end" and state.get("has_more") is False,
    }


def get_notifications(
    page: Any, kind: str = "all", *, limit: int = 100, max_pages: int = 3,
) -> dict:
    """读取网页当前账号通知；打开通知页可能由网站自动标记已读。"""
    if kind not in KINDS:
        raise NotificationError("不支持的通知类型")
    if not 1 <= limit <= 500 or not 1 <= max_pages <= 20:
        raise NotificationError("limit 必须为 1–500，max-pages 必须为 1–20")
    page.navigate(NOTIFICATIONS_URL)
    page.wait_for_load()
    sources = ["mentions", "likes", "follows"] if kind == "all" else [
        "mentions" if kind == "comments" else kind
    ]
    results = [_read_source(page, source, max_pages, 500) for source in sources]
    items: dict[str, dict] = {}
    unknown = 0
    for result in results:
        for item in result["items"]:
            unknown += item.get("kind") == "unknown"
            if kind == "all" or item.get("kind") == kind:
                items[f"{result['source']}:{_key(item)}"] = item
    ordered = sorted(items.values(), key=lambda item: item.get("time", 0), reverse=True)
    incomplete_users = sum(item.get("user_details_complete") is False for item in ordered)
    pagination_complete = all(r["complete"] for r in results) and len(ordered) <= limit
    return {
        "success": True,
        "kind": kind,
        "items": ordered[:limit],
        "count": min(len(ordered), limit),
        "total_loaded_matches": len(ordered),
        "complete": pagination_complete and not incomplete_users and (not unknown or kind == "all"),
        "pagination_complete": pagination_complete,
        "user_details_complete": not incomplete_users,
        "incomplete_user_count": incomplete_users,
        "has_more": any(r["has_more"] is not False for r in results) or len(ordered) > limit,
        "unclassified_count": unknown,
        "sources": [{k: v for k, v in r.items() if k != "items"} for r in results],
        "scope": "web_notifications",
        "read_may_mark_seen": True,
    }
