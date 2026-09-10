"""只读私信收件箱，以及按账号、会话和入站消息隔离的本地处理标记。"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .direct_message import CHAT_URL, DirectMessageError
from .errors import NotLoggedInError

_SCRIPT = Path(__file__).with_name("inbox.js").read_text(encoding="utf-8")
READ_NOTICE = "打开网页会话可能由小红书自动标记已读；本命令不调用标记已读或发送接口。"


def _run(page: Any, action: str, **params: Any) -> dict:
    value = page.evaluate(f"({_SCRIPT})({json.dumps({'action': action, **params})})")
    if not isinstance(value, dict):
        raise DirectMessageError("私信页面返回了无法识别的数据")
    if value.get("not_logged_in"):
        raise NotLoggedInError()
    if value.get("error") or value.get("__xhs_error"):
        raise DirectMessageError(value.get("error") or value["__xhs_error"])
    return value


def _id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{24}", value):
        raise DirectMessageError("用户 ID 必须是 24 位十六进制 ID")
    return value.lower()


def _bounds(limit: int, max_scrolls: int) -> None:
    if not 1 <= limit <= 1000 or not 0 <= max_scrolls <= 50:
        raise DirectMessageError("limit 必须为 1–1000，max-scrolls 必须为 0–50")


def _ready(page: Any, user_id: str = "", expected_name: str = "", timeout: float = 20) -> dict:
    stop = time.monotonic() + timeout
    while True:
        state = _run(page, "snapshot", user_id=user_id, expected_name=expected_name)
        if state.get("ready") and (not user_id or state.get("conversation_ready")):
            if user_id and (
                state.get("user_id") != user_id or state.get("recipient") != expected_name
            ):
                raise DirectMessageError("会话 ID 或完整昵称不匹配")
            return state
        if time.monotonic() >= stop:
            raise DirectMessageError("私信页面未就绪，无法把加载失败当作空列表")
        time.sleep(0.4)


def _open(page: Any, user_id: str = "", expected_name: str = "") -> dict:
    if user_id:
        user_id = _id(user_id)
        if not expected_name.strip():
            raise DirectMessageError("读取会话必须提供对方完整昵称以交叉核对")
    state = _run(page, "snapshot")
    needs_navigation = not state.get("on_chat_page") or (
        user_id and state.get("user_id") != user_id
    )
    if needs_navigation:
        if state.get("draft"):
            raise DirectMessageError("当前私信会话存在草稿，停止切换以免丢失")
        page.navigate(f"{CHAT_URL}/{user_id}" if user_id else CHAT_URL)
        page.wait_for_load()
    return _ready(page, user_id, expected_name)


def merge_messages(older: list[dict], newer: list[dict]) -> list[dict]:
    """按网页旧到新顺序合并，重叠消息保留更新状态；有完整序号时按序号校正。"""
    result: list[dict] = []
    indices: dict[str, int] = {}
    for message in [*older, *newer]:
        key = str(message.get("message_id") or "")
        if key and key in indices:
            result[indices[key]] = message
        else:
            if key:
                indices[key] = len(result)
            result.append(message)
    if result and all(
        str(m.get("store_id", "")).isdigit() and int(m["store_id"]) > 0 for m in result
    ):
        result.sort(key=lambda m: int(m["store_id"]))
    elif result and all(
        isinstance(m.get("timestamp_ms"), (int, float)) and m["timestamp_ms"] > 0 for m in result
    ):
        result.sort(key=lambda m: m["timestamp_ms"])
    return result


def _collect(page: Any, action: str, key: str, limit: int, max_scrolls: int, **params: Any) -> dict:
    state = _run(page, action, **params)
    account_id = _id(state.get("account_id", ""))
    initial_deadline = time.monotonic() + 20
    while state.get("loading"):
        if time.monotonic() >= initial_deadline:
            raise DirectMessageError("等待私信数据加载超时，无法确认列表是否为空")
        time.sleep(0.3)
        state = _run(page, action, **params)
        if state.get("account_id", "").lower() != account_id:
            raise DirectMessageError("读取期间登录账号发生变化，已停止")
    items = state.get(key)
    if not isinstance(items, list):
        raise DirectMessageError("网页数据结构变化，无法读取私信列表")
    collected = (
        merge_messages([], items)
        if key == "messages"
        else list({item["user_id"]: item for item in items}.values())
    )
    scrolls = 0
    stopped = "limit" if len(collected) >= limit else "max_scrolls"
    for _ in range(max_scrolls):
        if len(collected) >= limit or state.get("complete"):
            break
        before = {
            str(item.get("message_id" if key == "messages" else "user_id")) for item in collected
        }
        moved = _run(page, "scroll", target=key, **params)
        if not moved.get("scrolled"):
            stopped = "no_scroll_container"
            break
        scrolls += 1
        # 网页滚动触发自己的加载逻辑，不直接调用私有历史接口。
        deadline = time.monotonic() + 3
        while True:
            time.sleep(0.3)
            state = _run(page, action, **params)
            if state.get("account_id", "").lower() != account_id:
                raise DirectMessageError("读取期间登录账号发生变化，已停止")
            if state.get("loading"):
                if time.monotonic() >= deadline:
                    raise DirectMessageError("私信翻页加载超时，未将加载中误报为空列表")
                continue
            current = state.get(key)
            if not isinstance(current, list):
                raise DirectMessageError("翻页后无法读取私信数据")
            current_ids = {
                str(item.get("message_id" if key == "messages" else "user_id")) for item in current
            }
            if current_ids - before or state.get("complete") or time.monotonic() >= deadline:
                break
        if key == "messages":
            collected = merge_messages(current, collected)
            # 已加载消息的发送状态可更新，旧缓存不可覆盖当前状态。
            latest = {m.get("message_id"): m for m in current if m.get("message_id")}
            collected = [latest.get(m.get("message_id"), m) for m in collected]
        else:
            combined = {item["user_id"]: item for item in collected}
            combined.update({item["user_id"]: item for item in current})
            collected = list(combined.values())
        if not current_ids - before:
            stopped = "stalled"
            break
    complete = bool(state.get("complete")) and len(collected) <= limit
    if complete:
        stopped = "end"
    elif len(collected) >= limit:
        stopped = "limit"
    return {
        "success": True,
        "account_id": account_id,
        key: collected[-limit:] if key == "messages" else collected[:limit],
        "loaded_count": len(collected),
        "complete": complete,
        "scope": "web_loaded_records",
        "stop_reason": stopped,
        "scrolls": scrolls,
        **{name: state[name] for name in ("source", "completeness_note", "total_unread")
           if name in state},
    }


def list_inbox(page: Any, *, limit: int = 100, max_scrolls: int = 3) -> dict:
    _bounds(limit, max_scrolls)
    _open(page)
    result = _collect(page, "list", "conversations", limit, max_scrolls)
    result["conversation_kind"] = "c2c"
    result["note"] = "未读数仅反映网页状态，不等于待回复；不包含群聊或陌生人文件夹。"
    return result


def get_messages(
    page: Any, user_id: str, expected_name: str, *, limit: int = 100, max_scrolls: int = 3
) -> dict:
    _bounds(limit, max_scrolls)
    user_id = _id(user_id)
    _open(page, user_id, expected_name)
    _run(page, "latest", user_id=user_id, expected_name=expected_name)
    result = _collect(
        page,
        "messages",
        "messages",
        limit,
        max_scrolls,
        user_id=user_id,
        expected_name=expected_name,
    )
    result.update(
        user_id=user_id, recipient=expected_name, order="oldest_first", notice=READ_NOTICE
    )
    return result


def reply_state(messages: list[dict], *, complete: bool = False, mark: dict | None = None) -> dict:
    """最后一条有效消息来自对方才待回复；系统消息、失败或待确认的发送不算回复。"""
    effective = [
        m
        for m in messages
        if m.get("kind") != "system" and not m.get("failed") and not m.get("pending")
    ]
    incoming = [m for m in effective if m.get("direction") == "incoming"]
    last_incoming = incoming[-1] if incoming else None
    result = {
        "last_incoming_message_id": (last_incoming or {}).get("message_id", ""),
        "last_message": effective[-1] if effective else None,
    }
    if not effective:
        return {**result, "status": "empty" if complete else "unknown"}
    last = effective[-1]
    if last.get("direction") == "outgoing":
        return {**result, "status": "replied"}
    if last.get("direction") != "incoming" or not last.get("message_id"):
        return {**result, "status": "unknown"}
    if mark and mark.get("message_id") == last["message_id"] and mark.get("status") == "handled":
        return {**result, "status": "handled", "local_mark": mark}
    return {**result, "status": "pending"}


class ReplyMarks:
    """仅保存本地处理状态及标识，不持久化消息正文或昵称。"""

    def __init__(self, path: str | Path | None = None):
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self.path = Path(path) if path else base / "xiaohongshu-skills" / "reply-marks.sqlite3"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 首次创建即限制权限，避免短暂暴露；现存文件沿用更严格权限。
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS marks (account TEXT, peer TEXT, message TEXT, "
                    "status TEXT, updated TEXT, PRIMARY KEY (account, peer))"
                )
                yield conn
        finally:
            conn.close()

    def get(self, account_id: str, user_id: str) -> dict | None:
        account_id, user_id = _id(account_id), _id(user_id)
        if not self.path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT message, status, updated FROM marks WHERE account=? AND peer=?",
                (account_id, user_id),
            ).fetchone()
        return dict(zip(("message_id", "status", "updated_at"), row, strict=True)) if row else None

    def put(self, account_id: str, user_id: str, message_id: str, status: str) -> dict:
        account_id, user_id = _id(account_id), _id(user_id)
        if status not in {"pending", "handled"} or not message_id:
            raise DirectMessageError("处理状态或入站消息 ID 无效")
        updated = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO marks VALUES (?, ?, ?, ?, ?) ON CONFLICT(account, peer) "
                "DO UPDATE SET message=excluded.message, status=excluded.status, "
                "updated=excluded.updated",
                (account_id, user_id, message_id, status, updated),
            )
        return {"message_id": message_id, "status": status, "updated_at": updated}


def list_pending_replies(
    page: Any,
    *,
    limit: int = 20,
    max_scrolls: int = 2,
    message_limit: int = 100,
    state_file: str | None = None,
) -> dict:
    _bounds(message_limit, max_scrolls)
    inbox = list_inbox(page, limit=limit, max_scrolls=max_scrolls)
    account_id = _id(inbox.get("account_id", ""))
    marks = ReplyMarks(state_file)
    results, errors = [], []
    for conversation in inbox["conversations"]:
        user_id = conversation["user_id"]
        try:
            history = get_messages(
                page,
                user_id,
                conversation["nickname"],
                limit=message_limit,
                max_scrolls=max_scrolls,
            )
            if history.get("account_id") != account_id:
                raise DirectMessageError("读取期间登录账号发生变化，已停止")
            state = reply_state(
                history["messages"],
                complete=history["complete"],
                mark=marks.get(account_id, user_id),
            )
            results.append({**conversation, **state, "history_complete": history["complete"]})
        except DirectMessageError as exc:
            errors.append({"user_id": user_id, "error": str(exc)})
            if "账号" in str(exc) or "草稿" in str(exc):
                break
    return {
        "success": not errors,
        "account_id": account_id,
        "pending": [item for item in results if item["status"] == "pending"],
        "conversations": results,
        "errors": errors,
        "checked_count": len(results),
        "complete": inbox["complete"]
        and not errors
        and all(item["status"] != "unknown" for item in results),
        "scope": "checked_loaded_conversations",
        "notice": READ_NOTICE,
    }


def mark_conversation(
    page: Any,
    user_id: str,
    expected_name: str,
    *,
    message_id: str,
    status: str,
    state_file: str | None = None,
) -> dict:
    history = get_messages(page, user_id, expected_name, limit=100, max_scrolls=0)
    state = reply_state(history["messages"], complete=history["complete"])
    if state["status"] != "pending":
        raise DirectMessageError(
            "仅能标记最新有效消息确认为对方来信的会话；已回复、系统候选或未知方向请先重新核对"
        )
    if not message_id or state["last_incoming_message_id"] != message_id:
        raise DirectMessageError("最新入站消息与 --message-id 不一致，请重新读取后再标记")
    mark = ReplyMarks(state_file).put(history["account_id"], user_id, message_id, status)
    return {
        "success": True,
        "account_id": history["account_id"],
        "user_id": user_id,
        "local_only": True,
        "mark": mark,
        "notice": READ_NOTICE,
    }
