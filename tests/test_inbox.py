from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xhs import inbox

ACCOUNT = "aaaaaaaaaaaaaaaaaaaaaaaa"
PEER = "bbbbbbbbbbbbbbbbbbbbbbbb"
NAME = "测试会话"


def message(key, direction="incoming", kind="text", **kwargs):
    return {"message_id": key, "direction": direction, "kind": kind, **kwargs}


def test_pending_requires_last_effective_incoming():
    incoming = message("1", text="收到请回复")
    outgoing = message("2", "outgoing", text="已收到")
    assert inbox.reply_state([incoming])["status"] == "pending"
    assert inbox.reply_state([incoming, outgoing])["status"] == "replied"
    assert inbox.reply_state([outgoing, incoming])["status"] == "pending"


@pytest.mark.parametrize(
    "suffix",
    [
        message("2", "outgoing", pending=True),
        message("2", "outgoing", failed=True),
        message("2", "unknown", "system"),
    ],
)
def test_system_pending_and_failed_sends_do_not_count_as_reply(suffix):
    assert inbox.reply_state([message("1"), suffix])["status"] == "pending"


def test_image_message_counts_and_unknown_direction_remains_unknown():
    assert inbox.reply_state([message("1", kind="image")])["status"] == "pending"
    assert inbox.reply_state([message("1"), message("2", "unknown")])["status"] == "unknown"
    assert inbox.reply_state([message("")])["status"] == "unknown"
    assert inbox.reply_state([])["status"] == "unknown"
    assert inbox.reply_state([], complete=True)["status"] == "empty"


def test_new_message_invalidates_handled_mark(tmp_path):
    marks = inbox.ReplyMarks(tmp_path / "marks.sqlite3")
    mark = marks.put(ACCOUNT, PEER, "old", "handled")
    assert inbox.reply_state([message("old")], mark=mark)["status"] == "handled"
    assert inbox.reply_state([message("old"), message("new")], mark=mark)["status"] == "pending"
    reopened = marks.put(ACCOUNT, PEER, "old", "pending")
    assert inbox.reply_state([message("old")], mark=reopened)["status"] == "pending"


def test_marks_are_persistent_and_account_isolated(tmp_path):
    path = tmp_path / "private" / "marks.sqlite3"
    inbox.ReplyMarks(path).put(ACCOUNT, PEER, "msg-1", "handled")
    marks = inbox.ReplyMarks(path)
    assert marks.get(ACCOUNT, PEER)["message_id"] == "msg-1"
    assert marks.get("cccccccccccccccccccccccc", PEER) is None
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(inbox.DirectMessageError):
        marks.put("", PEER, "msg-1", "handled")


def test_merge_repeated_pages_and_numeric_store_order():
    first = [message("b", store_id="20"), message("c", store_id="30")]
    next_page = [message("b", store_id="20"), message("a", store_id="2")]
    assert [m["message_id"] for m in inbox.merge_messages(next_page, first)] == ["a", "b", "c"]


def test_merge_timestamp_order_when_no_sequence_and_preserve_dom_when_unknown():
    assert [
        m["message_id"]
        for m in inbox.merge_messages(
            [message("b", timestamp_ms=2000)], [message("a", timestamp_ms=1000)]
        )
    ] == ["a", "b"]
    assert [
        m["message_id"]
        for m in inbox.merge_messages(
            [message("old"), message("overlap")], [message("overlap"), message("new")]
        )
    ] == ["old", "overlap", "new"]


class FakePage:
    def __init__(self, pages=None):
        self.navigate = Mock()
        self.wait_for_load = Mock()
        self.page = 0
        self.pages = pages or [{"messages": [message("incoming")], "complete": False}]
        self.actions = []
        self.state = {
            "on_chat_page": True,
            "ready": True,
            "conversation_ready": True,
            "user_id": PEER,
            "recipient": NAME,
            "draft": "",
            "account_id": ACCOUNT,
        }

    def evaluate(self, expression):
        params = json.loads(expression.removeprefix(f"({inbox._SCRIPT})(")[:-1])
        self.actions.append(params["action"])
        if params["action"] == "snapshot":
            return self.state.copy()
        if params["action"] == "latest":
            return {"scrolled": True}
        if params["action"] == "scroll":
            self.page = min(self.page + 1, len(self.pages) - 1)
            return {"scrolled": True}
        if params["action"] == "messages":
            return {"account_id": ACCOUNT, **self.pages[self.page]}
        if params["action"] == "list":
            return {
                "account_id": ACCOUNT,
                "conversations": [{"user_id": PEER, "nickname": NAME, "unread_count": 0}],
                "complete": False,
            }
        raise AssertionError(params)


def test_history_pages_are_deduplicated_and_limit_is_latest(monkeypatch):
    monkeypatch.setattr(inbox.time, "sleep", lambda _: None)
    page = FakePage(
        [
            {"messages": [message("b"), message("c")], "complete": False},
            {"messages": [message("a"), message("b")], "complete": True},
        ]
    )
    result = inbox.get_messages(page, PEER, NAME, limit=3, max_scrolls=2)
    assert [m["message_id"] for m in result["messages"]] == ["a", "b", "c"]
    assert result["complete"] is True
    result = inbox.get_messages(
        FakePage([{"messages": [message("a"), message("b"), message("c")], "complete": True}]),
        PEER,
        NAME,
        limit=2,
        max_scrolls=0,
    )
    assert [m["message_id"] for m in result["messages"]] == ["b", "c"]
    assert result["complete"] is False


def test_current_loading_error_is_not_empty_success():
    page = FakePage([{"error": "历史消息加载失败"}])
    with pytest.raises(inbox.DirectMessageError, match="加载失败"):
        inbox.get_messages(page, PEER, NAME, max_scrolls=0)


def test_initial_loading_is_waited_and_timeout_not_reported_as_empty(monkeypatch):
    monkeypatch.setattr(inbox.time, "sleep", lambda _: None)
    ticks = iter(range(100))
    monkeypatch.setattr(inbox.time, "monotonic", lambda: next(ticks))
    page = FakePage([{"messages": [], "loading": True}])
    with pytest.raises(inbox.DirectMessageError, match="加载超时"):
        inbox.get_messages(page, PEER, NAME, max_scrolls=0)


def test_initial_loading_then_messages_succeeds(monkeypatch):
    monkeypatch.setattr(inbox.time, "sleep", lambda _: None)
    page = FakePage()
    original = page.evaluate

    def delayed(expression):
        state = original(expression)
        if page.actions[-1] == "messages" and page.actions.count("messages") == 1:
            return {"account_id": ACCOUNT, "messages": [], "loading": True}
        return state

    page.evaluate = delayed
    result = inbox.get_messages(page, PEER, NAME, max_scrolls=0)
    assert len(result["messages"]) == 1
    assert page.actions.count("messages") == 2


def test_repeated_page_stops_without_claiming_complete(monkeypatch):
    ticks = iter(range(100))
    monkeypatch.setattr(inbox.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(inbox.time, "sleep", lambda _: None)
    page = FakePage()
    result = inbox.get_messages(page, PEER, NAME, max_scrolls=10)
    assert result["scrolls"] == 1
    assert result["complete"] is False
    assert result["stop_reason"] == "stalled"
    assert len(result["messages"]) == 1


def test_account_change_during_pagination_is_rejected(monkeypatch):
    monkeypatch.setattr(inbox.time, "sleep", lambda _: None)
    page = FakePage()
    original = page.evaluate

    def changed_account(expression):
        state = original(expression)
        if page.actions.count("messages") > 1:
            state["account_id"] = "cccccccccccccccccccccccc"
        return state

    page.evaluate = changed_account
    with pytest.raises(inbox.DirectMessageError, match="账号发生变化"):
        inbox.get_messages(page, PEER, NAME, max_scrolls=1)


def test_name_mismatch_and_draft_prevent_navigation():
    page = FakePage()
    with pytest.raises(inbox.DirectMessageError, match="昵称"):
        inbox.get_messages(page, PEER, "另一个人")
    page.state.update(user_id="cccccccccccccccccccccccc", draft="不能丢失的草稿")
    with pytest.raises(inbox.DirectMessageError, match="草稿"):
        inbox.get_messages(page, PEER, NAME)
    page.navigate.assert_not_called()


def test_pending_is_independent_of_unread_and_applies_local_status(tmp_path):
    path = str(tmp_path / "marks.sqlite3")
    result = inbox.list_pending_replies(FakePage(), max_scrolls=0, state_file=path)
    assert len(result["pending"]) == 1
    assert result["pending"][0]["unread_count"] == 0
    assert result["complete"] is False
    inbox.mark_conversation(
        FakePage(), PEER, NAME, message_id="incoming", status="handled", state_file=path
    )
    result = inbox.list_pending_replies(FakePage(), max_scrolls=0, state_file=path)
    assert result["pending"] == []
    assert result["conversations"][0]["status"] == "handled"


def test_stale_message_mark_does_not_write_state(tmp_path):
    path = tmp_path / "marks.sqlite3"
    with pytest.raises(inbox.DirectMessageError, match="不一致"):
        inbox.mark_conversation(
            FakePage(), PEER, NAME, message_id="stale", status="handled", state_file=str(path)
        )
    assert not path.exists()


def test_limit_validation_precedes_browser_access():
    page = FakePage()
    with pytest.raises(inbox.DirectMessageError):
        inbox.get_messages(page, PEER, NAME, limit=0)
    assert page.actions == []


def test_system_candidate_does_not_become_a_pending_reply_or_silently_disappear():
    candidate = message("welcome", "unknown", "system_candidate")
    assert inbox.reply_state([candidate], complete=True)["status"] == "unknown"
    state = inbox.reply_state([message("old"), candidate])
    assert state["status"] == "unknown"
    assert state["last_message"] == candidate


@pytest.mark.parametrize("tail", [
    message("reply", "outgoing"), message("welcome", "unknown", "system_candidate"),
    message("unknown", "unknown"),
])
def test_cannot_mark_old_incoming_when_latest_effective_message_is_not_incoming(tmp_path, tail):
    path = tmp_path / "marks.sqlite3"
    page = FakePage([{"messages": [message("old"), tail], "complete": True}])
    with pytest.raises(inbox.DirectMessageError, match="最新有效消息"):
        inbox.mark_conversation(
            page, PEER, NAME, message_id="old", status="handled", state_file=str(path),
        )
    assert not path.exists()
