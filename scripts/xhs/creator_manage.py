"""创作后台笔记状态和浏览器本地草稿；不删除、不保存、不发布。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .errors import XHSError

_SCRIPT = Path(__file__).with_suffix(".js").read_text(encoding="utf-8")
MANAGER_URL = "https://creator.xiaohongshu.com/new/note-manager"
DRAFT_URL = "https://creator.xiaohongshu.com/publish/publish"
KINDS = ("image", "video", "long", "audio")
STATUSES = ("all", "published", "reviewing", "rejected")


class CreatorManageError(XHSError):
    """无法安全读取或定位创作后台内容。"""


def _run(page: Any, action: str, **params: Any) -> dict:
    result = page.evaluate(f"({_SCRIPT})({json.dumps({'action': action, **params})})")
    if not isinstance(result, dict):
        raise CreatorManageError("创作后台没有返回可识别的数据")
    if result.get("error") or result.get("__xhs_error"):
        raise CreatorManageError(result.get("error") or result["__xhs_error"])
    if params.get("account_id") and result.get("ready") is not False:
        _account(result, params["account_id"])
    return result


def _account(result: dict, expected: str = "") -> str:
    account_id = str(result.get("account_id", ""))
    if not re.fullmatch(r"[0-9a-fA-F]{24}", account_id):
        raise CreatorManageError("无法确认当前创作账号身份，未继续读取或打开草稿")
    if expected and account_id != expected:
        raise CreatorManageError("创作账号发生变化，已停止，避免混合账号数据")
    return account_id


def _wait(page: Any, action: str, **params: Any) -> dict:
    deadline = time.monotonic() + 15.0
    while True:
        result = _run(page, action, **params)
        if result.get("ready"):
            return result
        if time.monotonic() >= deadline:
            raise CreatorManageError("页面仍未就绪或结构不受支持；未将加载失败当成空列表")
        time.sleep(0.3)


def _prepare(page: Any, url: str, *, reuse_publish: bool = False) -> None:
    guard = _run(page, "guard")
    if not guard.get("safe_to_navigate"):
        raise CreatorManageError("当前编辑器已有内容，请先保存或处理，未导航或覆盖")
    if not (reuse_publish and guard.get("on_publish")):
        page.navigate(url)
        page.wait_for_load()


def _bounds(limit: int, max_pages: int) -> None:
    if not 1 <= limit <= 500 or not 1 <= max_pages <= 20:
        raise CreatorManageError("limit 必须为 1–500，max-pages 必须为 1–20")


def _collect(page: Any, prefix: str, id_key: str, max_pages: int, **params: Any) -> dict:
    selected = _wait(page, f"{prefix}-select", **params)
    account_id = _account(selected, params.get("account_id", ""))
    params = {**params, "account_id": account_id}
    state = _wait(page, f"{prefix}-read", **params)
    items: dict[str, dict] = {}
    pages = 1
    stop = "end"
    complete = False
    while True:
        _account(state, account_id)
        for item in state["items"]:
            items[item[id_key]] = item
        total = state.get("total")
        complete = bool(state.get("complete")) or (isinstance(total, int) and len(items) >= total)
        if complete:
            break
        if pages >= max_pages:
            stop = "max_pages"
            break
        before = set(items)
        _run(page, f"{prefix}-more", **params)
        deadline = time.monotonic() + 5.0
        while True:
            state = _wait(page, f"{prefix}-read", **params)
            _account(state, account_id)
            if state.get("complete") or any(i[id_key] not in before for i in state["items"]):
                pages += 1
                break
            if time.monotonic() >= deadline:
                stop = "no_progress"
                break
            time.sleep(0.3)
        if stop == "no_progress":
            break
    return {"account_id": account_id, "account_name": state.get("account_name", ""),
            "items": list(items.values()), "complete": complete,
            "total": state.get("total"), "pages": pages, "stop_reason": stop}


def list_managed_notes(
    page: Any, *, status: str = "all", keyword: str = "", limit: int = 100, max_pages: int = 3,
) -> dict:
    _bounds(limit, max_pages)
    if status not in STATUSES:
        raise CreatorManageError("不支持的笔记状态")
    _prepare(page, MANAGER_URL)
    # 读取全部页再筛选已确认的状态，保留未识别状态，避免猜测后台数字枚举。
    result = _collect(page, "notes", "note_id", max_pages, status="all")
    unknown = sum(i["status"] == "unknown" for i in result["items"])
    selected = [i for i in result["items"] if (status == "all" or i["status"] == status)
                and (not keyword or keyword.casefold() in i["title"].casefold())]
    return {**result, "success": True, "scope": "creator_note_manager", "status": status,
            "items": selected[:limit], "count": min(len(selected), limit),
            "total_loaded": len(result["items"]), "unclassified_count": unknown,
            "complete": result["complete"] and len(selected) <= limit
            and (status == "all" or unknown == 0),
            "metrics_scope": "note_manager_snapshot"}


def get_note_status(page: Any, note_id: str, *, max_pages: int = 3) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{24}", note_id):
        raise CreatorManageError("笔记 ID 必须为 24 位十六进制 ID")
    result = list_managed_notes(page, limit=500, max_pages=max_pages)
    note = next((i for i in result["items"] if i["note_id"] == note_id), None)
    return {"account_id": result["account_id"], "account_name": result.get("account_name", ""),
            "success": note is not None, "found": note is not None,
            "note": note, "search_complete": result["complete"],
            "scope": "creator_note_manager",
            "message": "已找到笔记" if note else "已读范围内未找到；不据此判断笔记已删除"}


def list_drafts(
    page: Any, *, kind: str = "all", keyword: str = "", limit: int = 100, max_pages: int = 3,
) -> dict:
    _bounds(limit, max_pages)
    if kind not in (*KINDS, "all"):
        raise CreatorManageError("不支持的草稿类型")
    _prepare(page, DRAFT_URL, reuse_publish=True)
    drawer = _wait(page, "draft-drawer")
    account_id = _account(drawer)
    results = [{**_collect(page, "draft", "draft_id", max_pages, kind=k, account_id=account_id),
                "kind": k}
               for k in (KINDS if kind == "all" else (kind,))]
    items = [i for result in results for i in result["items"]]
    selected = [i for i in items if not keyword or keyword.casefold() in i["title"].casefold()]
    return {"account_id": account_id, "account_name": drawer.get("account_name", ""),
            "success": True, "scope": "current_browser_local_drafts", "kind": kind,
            "items": selected[:limit], "count": min(len(selected), limit),
            "total_loaded": len(items),
            "complete": all(r["complete"] for r in results) and len(selected) <= limit,
            "groups": [{k: v for k, v in r.items() if k != "items"} for r in results]}


def open_draft(
    page: Any, draft_id: str, expected_title: str, kind: str, *, open_editor: bool = False,
    max_pages: int = 3,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", draft_id) or not expected_title.strip():
        raise CreatorManageError("必须提供稳定的草稿 ID 和完整显示标题")
    if kind not in KINDS:
        raise CreatorManageError("打开草稿时必须指定具体类型")
    result = list_drafts(page, kind=kind, limit=500, max_pages=max_pages)
    matches = [i for i in result["items"] if i["draft_id"] == draft_id]
    if len(matches) != 1 or matches[0]["title"] != expected_title:
        raise CreatorManageError("已读取的草稿中 ID 和标题未同时匹配，未打开")
    account_id = _account(result)
    base = {"account_id": account_id, "account_name": result.get("account_name", ""),
            "draft": matches[0], "saved": False, "published": False}
    if not open_editor:
        return {**base, "success": True, "status": "preview", "opened": False}
    # ID、标题与已有编辑内容检查在同一次页面操作中完成。
    try:
        clicked = _run(page, "draft-open", kind=kind, draft_id=draft_id,
                       expected_title=expected_title, account_id=account_id)
        if not clicked.get("clicked"):
            raise CreatorManageError("未确认草稿编辑按钮已点击")
        state = _wait(page, "editor", account_id=account_id)
        _account(state, account_id)
        wanted = expected_title if matches[0].get("has_title") else ""
        if wanted not in state.get("titles", []):
            raise CreatorManageError("打开后的编辑器标题与草稿不一致")
        return {**base, "success": True, "status": "editor_open", "opened": True}
    except Exception:
        return {**base, "success": False, "status": "unknown", "opened": None,
                "error": "未能确认编辑器已打开目标草稿，请检查当前页面；未保存或发布"}
