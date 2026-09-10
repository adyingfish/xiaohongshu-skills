"""通知分页边界、加载失败和关注单次提交/刷新核验的回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from xhs import notifications, relationships

UID = "a" * 24


def item(id_, kind="comments", timestamp=1):
    return {"id": id_, "kind": kind, "time": timestamp}


def notice(items=None, *, more=False, cursor="0"):
    return {"ready": True, "selected": True, "items": items or [],
            "has_more": more, "cursor": cursor}


def test_notification_error_not_empty_success():
    page = Mock()
    page.evaluate.return_value = {"error": "网页通知加载失败"}
    with pytest.raises(notifications.NotificationError, match="加载失败"):
        notifications.get_notifications(page)


def test_notification_missing_state_timeout(monkeypatch):
    page = Mock()
    page.evaluate.return_value = {"ready": False}
    ticks = iter([0, 100])
    monkeypatch.setattr(notifications.time, "monotonic", lambda: next(ticks))
    with pytest.raises(notifications.NotificationError, match="未加载完成"):
        notifications._wait_ready(page, "mentions")


def test_notification_verified_empty(monkeypatch):
    monkeypatch.setattr(notifications, "_run", lambda *a, **kw: notice())
    result = notifications.get_notifications(Mock(), "comments")
    assert result["count"] == 0 and result["complete"]
    assert result["read_may_mark_seen"]


def test_notification_pagination_deduplicates_and_filters(monkeypatch):
    states = iter([
        notice([item("a"), item("m", "mentions")], more=True, cursor="1"),
        notice([item("a"), item("b", timestamp=5)], cursor="2"),
    ])
    calls = []

    def run(page, action, **kwargs):
        calls.append(action)
        return next(states) if action == "read" else {"selected": True}

    monkeypatch.setattr(notifications, "_run", run)
    result = notifications.get_notifications(Mock(), "comments")
    assert [i["id"] for i in result["items"]] == ["b", "a"]
    assert result["complete"] and calls.count("more") == 1


def test_notification_page_bound_is_not_complete(monkeypatch):
    monkeypatch.setattr(notifications, "_run", lambda *a, **kw: notice(
        [item("a")], more=True, cursor="1"))
    result = notifications.get_notifications(Mock(), "comments", max_pages=1)
    assert result["count"] == 1 and not result["complete"] and result["has_more"]
    assert result["sources"][0]["stop_reason"] == "max_pages"


def test_notification_no_progress_stops_without_claiming_complete(monkeypatch):
    monkeypatch.setattr(notifications, "_run", lambda *a, **kw: notice(
        [item("a")], more=True, cursor="1"))
    ticks = iter(range(0, 1000, 10))
    monkeypatch.setattr(notifications.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(notifications.time, "sleep", lambda _: None)
    result = notifications.get_notifications(Mock(), "comments")
    assert not result["complete"] and result["sources"][0]["stop_reason"] == "no_progress"


def test_notification_limit_and_unknown_types_not_complete(monkeypatch):
    monkeypatch.setattr(notifications, "_run", lambda *a, **kw: notice(
        [item("a"), item("b"), item("x", "unknown")]))
    result = notifications.get_notifications(Mock(), "comments", limit=1)
    assert result["count"] == 1 and not result["complete"]
    assert result["has_more"] and result["unclassified_count"] == 1


def test_notification_actor_loss_does_not_hide_behind_pagination_complete(monkeypatch):
    broken = {**item("a", "follows"), "user_details_complete": False}
    monkeypatch.setattr(notifications, "_run", lambda *a, **kw: notice([broken]))
    result = notifications.get_notifications(Mock(), "follows")
    assert result["pagination_complete"] is True
    assert result["complete"] is False
    assert result["user_details_complete"] is False
    assert result["incomplete_user_count"] == 1


def test_notification_all_visits_each_web_group(monkeypatch):
    groups = []

    def run(page, action, **kwargs):
        if action == "select":
            groups.append(kwargs["source"])
        return notice([item(kwargs["source"], kwargs["source"])])

    monkeypatch.setattr(notifications, "_run", run)
    result = notifications.get_notifications(Mock())
    assert groups == ["mentions", "likes", "follows"] and result["count"] == 3


@pytest.mark.parametrize("limit,max_pages", [(0, 1), (501, 1), (20, 0), (20, 21)])
def test_notification_invalid_bounds_before_navigation(limit, max_pages):
    page = Mock()
    with pytest.raises(notifications.NotificationError):
        notifications.get_notifications(page, limit=limit, max_pages=max_pages)
    page.navigate.assert_not_called()


def test_follow_preview_never_clicks(monkeypatch):
    runner = Mock(return_value={"ready": True, "state": "not-followed"})
    monkeypatch.setattr(relationships, "_run", runner)
    result = relationships.set_follow(Mock(), UID, "测试用户", "followed")
    assert result["status"] == "preview" and result["would_change"]
    assert all(call.args[1] == "read" for call in runner.call_args_list)


def test_follow_already_target_never_clicks(monkeypatch):
    runner = Mock(return_value={"ready": True, "state": "followed"})
    monkeypatch.setattr(relationships, "_run", runner)
    result = relationships.set_follow(Mock(), UID, "测试用户", "followed", confirmed=True)
    assert result["status"] == "unchanged" and runner.call_count == 1


def test_follow_single_click_and_reload_verification(monkeypatch):
    runner = Mock(side_effect=[
        {"ready": True, "state": "not-followed"}, {"clicked": True},
        {"ready": True, "state": "followed"}, {"ready": True, "state": "followed"},
    ])
    monkeypatch.setattr(relationships, "_run", runner)
    page = Mock()
    result = relationships.set_follow(page, UID, "测试用户", "followed", confirmed=True)
    assert result["success"] and result["verification"] == "reloaded_page"
    assert page.navigate.call_count == 2
    assert sum(c.args[1] == "set" for c in runner.call_args_list) == 1


def test_follow_optimistic_ui_rolled_back_is_unknown(monkeypatch):
    runner = Mock(side_effect=[
        {"ready": True, "state": "not-followed"}, {"clicked": True},
        {"ready": True, "state": "followed"}, {"ready": True, "state": "not-followed"},
    ])
    monkeypatch.setattr(relationships, "_run", runner)
    result = relationships.set_follow(Mock(), UID, "测试用户", "followed", confirmed=True)
    assert result["status"] == "unknown" and not result["success"]


def test_follow_click_connection_error_no_retry(monkeypatch):
    runner = Mock(side_effect=[
        {"ready": True, "state": "not-followed"}, RuntimeError("connection lost"),
    ])
    monkeypatch.setattr(relationships, "_run", runner)
    result = relationships.set_follow(Mock(), UID, "测试用户", "followed", confirmed=True)
    assert result["status"] == "unknown" and runner.call_count == 2


def test_follow_timeout_no_second_click(monkeypatch):
    def run(page, action, **kwargs):
        return {"clicked": True} if action == "set" else {"ready": True, "state": "not-followed"}

    runner = Mock(side_effect=run)
    monkeypatch.setattr(relationships, "_run", runner)
    result = relationships.set_follow(Mock(), UID, "测试用户", "followed",
                                      confirmed=True, timeout=0)
    assert result["status"] == "unknown"
    assert sum(c.args[1] == "set" for c in runner.call_args_list) == 1


@pytest.mark.parametrize("uid,name", [("bad", "name"), (UID, " ")])
def test_follow_invalid_identity_before_navigation(uid, name):
    page = Mock()
    with pytest.raises(relationships.RelationshipError):
        relationships.set_follow(page, uid, name, "followed")
    page.navigate.assert_not_called()
