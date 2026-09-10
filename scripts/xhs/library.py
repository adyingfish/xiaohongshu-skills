"""自己的主页笔记、收藏笔记与网页专辑读取；明确范围与分页完整性。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .errors import NotLoggedInError, XHSError
from .links import make_share_url

_SCRIPT = Path(__file__).with_suffix(".js").read_text(encoding="utf-8")


class LibraryError(XHSError):
    """个人列表页面或数据校验失败。"""


def _run(page, action: str, **params) -> dict:
    value = page.evaluate(f"({_SCRIPT})({json.dumps({'action': action, **params})})")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise LibraryError("个人内容库返回了无法识别的数据")
    if value.get("not_logged_in"):
        raise NotLoggedInError()
    if value.get("error") or value.get("__xhs_error"):
        raise LibraryError(value.get("error") or value["__xhs_error"])
    return value


def _wait(page, action: str, field: str, *, timeout: float, **params) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        value = _run(page, action, **params)
        if value.get(field):
            return value
        if time.monotonic() >= deadline:
            raise LibraryError("个人内容库页面未就绪；未将加载失败当作空列表")
        time.sleep(0.25)


def _open_own(page, scope: str, timeout: float) -> dict:
    account = _run(page, "account")
    if not account.get("ready"):
        page.navigate("https://www.xiaohongshu.com/explore")
        page.wait_for_load()
        account = _wait(page, "account", "ready", timeout=timeout)
    page.navigate(f"https://www.xiaohongshu.com/user/profile/{account['account_id']}")
    page.wait_for_load()
    params = {"scope": scope, "account_id": account["account_id"]}
    _wait(page, "select", "selected", timeout=timeout, **params)
    return _wait(page, "read", "ready", timeout=timeout, **params)


def _record_key(record: dict, scope: str) -> str:
    if scope != "collections":
        return record["id"]
    # 网页专辑非空结构尚未现场验证：完整记录去重，不虚构专辑 ID 或标题字段。
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def list_library(
    page, scope: str, *, limit: int = 50, max_pages: int = 3,
    keyword: str = "", timeout: float = 12,
) -> dict:
    if scope not in {"notes", "favorites", "collections"}:
        raise ValueError("范围必须为 notes、favorites 或 collections")
    if not 1 <= limit <= 500 or not 1 <= max_pages <= 20:
        raise ValueError("limit 应为 1–500，max-pages 应为 1–20")
    if not 0 <= timeout <= 60:
        raise ValueError("timeout 应为 0–60 秒")
    if scope == "collections" and keyword:
        raise ValueError("网页专辑暂不支持关键词检索")
    state = _open_own(page, scope, timeout)
    account_id = state["account_id"]
    records: dict[str, dict] = {}
    rounds = 1
    stopped = "end"
    while True:
        for record in state["records"]:
            if not isinstance(record, dict):
                raise LibraryError("个人列表中存在无法识别的记录")
            records[_record_key(record, scope)] = record
        if len(records) >= limit:
            stopped = "limit" if len(records) > limit or state["has_more"] else "end"
            break
        if not state["has_more"]:
            break
        if rounds >= max_pages:
            stopped = "max_pages"
            break
        before = (len(records), state["cursor"], state["page"])
        _run(page, "scroll", scope=scope, account_id=account_id)
        rounds += 1
        deadline = time.monotonic() + timeout
        while True:
            candidate = _run(page, "read", scope=scope, account_id=account_id)
            if candidate.get("ready"):
                candidate_keys = {_record_key(record, scope) for record in candidate["records"]}
                after = (len(set(records) | candidate_keys), candidate["cursor"], candidate["page"])
                if after != before or not candidate["has_more"]:
                    state = candidate
                    break
            if time.monotonic() >= deadline:
                stopped = "stalled"
                break
            time.sleep(0.25)
        if stopped == "stalled":
            break
    scanned = list(records.values())[:limit]
    if scope != "collections":
        for record in scanned:
            record["shareUrl"] = make_share_url(record["id"], record.get("xsecToken", ""))
        key = keyword.strip().casefold()
        items = [record for record in scanned if not key or key in (
            record.get("displayTitle", "") + "\n" + record.get("user", {}).get("nickname", "")
        ).casefold()]
    else:
        items = scanned
    result = {
        "success": True, "scope": scope, "account_id": account_id,
        "items": items, "count": len(items), "scanned_count": len(scanned),
        "pages_requested": rounds, "has_more": state["has_more"],
        "complete": stopped == "end", "stopped_reason": stopped,
        "keyword": keyword, "search_fields": ["displayTitle", "user.nickname"]
        if scope != "collections" else [],
        "source": "personal_web_profile", "record_format": state["record_format"],
    }
    if scope == "collections":
        result["limitation"] = "仅网页专辑；不代表 App 全部收藏夹，非空记录保留网页原始结构"
    else:
        result["limitation"] = "仅列表标题及作者，不含正文检索或创作后台发布审核状态"
    return result


def search_library(
    page, keyword: str, *, scope: str = "all", limit: int = 50, max_pages: int = 3,
) -> dict:
    if not keyword.strip():
        raise ValueError("检索关键词不能为空")
    if scope not in {"all", "notes", "favorites"}:
        raise ValueError("检索范围必须为 all、notes 或 favorites")
    scopes = ["notes", "favorites"] if scope == "all" else [scope]
    results = [list_library(page, selected, keyword=keyword, limit=limit, max_pages=max_pages)
               for selected in scopes]
    if len({result["account_id"] for result in results}) != 1:
        raise LibraryError("检索过程中登录账号发生变化，已停止")
    items = {}
    for result in results:
        for record in result["items"]:
            if record["id"] not in items:
                items[record["id"]] = {**record, "scopes": []}
            items[record["id"]]["scopes"].append(result["scope"])
    return {
        "success": True, "keyword": keyword, "scope": scope,
        "account_id": results[0]["account_id"], "items": list(items.values()),
        "count": len(items), "complete": all(result["complete"] for result in results),
        "coverage": [{key: result[key] for key in (
            "scope", "scanned_count", "complete", "has_more", "stopped_reason", "pages_requested",
        )} for result in results],
        "search_fields": ["displayTitle", "user.nickname"],
        "limitation": "在各范围最多读取 limit 条，匹配标题和作者，不是全文检索",
    }
