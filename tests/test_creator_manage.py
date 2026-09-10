"""验证后台数据范围、稳定草稿身份和已有编辑内容保护。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from xhs import creator_manage as creator

ACCOUNT = "f" * 24


def identity(result):
    return {"account_id": ACCOUNT, "account_name": "测试账号", **result}


def test_dirty_editor_blocks_navigation(monkeypatch):
    monkeypatch.setattr(creator, "_run", lambda *a, **k: {"safe_to_navigate": False})
    page = Mock()
    with pytest.raises(creator.CreatorManageError, match="已有内容"):
        creator.list_managed_notes(page)
    page.navigate.assert_not_called()


def test_existing_empty_publish_page_is_reused(monkeypatch):
    monkeypatch.setattr(creator, "_run", lambda *a, **k: {
        "safe_to_navigate": True, "on_publish": True})
    page = Mock()
    creator._prepare(page, creator.DRAFT_URL, reuse_publish=True)
    page.navigate.assert_not_called()


def test_missing_data_is_error_not_empty():
    page = Mock()
    page.evaluate.return_value = {"error": "未读取到数据"}
    with pytest.raises(creator.CreatorManageError, match="未读取到"):
        creator.list_drafts(page)


def test_collect_deduplicates_and_completes_accumulated_pages(monkeypatch):
    states = iter([
        {"ready": True},
        {"items": [{"note_id": "1"}], "total": 2, "complete": False},
        {"items": [{"note_id": "1"}, {"note_id": "2"}], "total": 2, "complete": False},
    ])
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: identity(next(states)))
    monkeypatch.setattr(creator, "_run", lambda *a, **k: {})
    result = creator._collect(Mock(), "notes", "note_id", 3)
    assert len(result["items"]) == 2 and result["complete"]


def test_collect_page_bound_is_incomplete(monkeypatch):
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: identity({
        "items": [{"note_id": "1"}], "total": 4, "complete": False}))
    result = creator._collect(Mock(), "notes", "note_id", 1)
    assert not result["complete"] and result["stop_reason"] == "max_pages"


def test_unknown_status_does_not_disappear_as_complete(monkeypatch):
    monkeypatch.setattr(creator, "_prepare", lambda *a, **k: None)
    monkeypatch.setattr(creator, "_collect", lambda *a, **k: {"complete": True, "items": [
        {"note_id": "1", "status": "published", "title": "A"},
        {"note_id": "2", "status": "unknown", "title": "B"}]})
    result = creator.list_managed_notes(Mock(), status="reviewing")
    assert result["count"] == 0 and not result["complete"] and result["unclassified_count"] == 1


def test_note_absence_does_not_claim_deleted(monkeypatch):
    monkeypatch.setattr(creator, "list_managed_notes", lambda *a, **k: identity({
        "items": [], "complete": False}))
    result = creator.get_note_status(Mock(), "a" * 24)
    assert not result["found"] and not result["search_complete"] and "删除" in result["message"]


def test_drafts_all_types_and_local_scope(monkeypatch):
    kinds = []
    monkeypatch.setattr(creator, "_prepare", lambda *a, **k: None)
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: identity({}))

    def collect(*a, **kwargs):
        kinds.append(kwargs["kind"])
        return identity({"items": [], "complete": True, "total": 0})

    monkeypatch.setattr(creator, "_collect", collect)
    result = creator.list_drafts(Mock())
    assert kinds == ["image", "video", "long", "audio"]
    assert result["scope"] == "current_browser_local_drafts" and result["complete"]


def draft_result():
    return identity({"items": [{"draft_id": "d1", "title": "测试稿", "has_title": True}]})


def test_open_draft_preview_never_clicks(monkeypatch):
    monkeypatch.setattr(creator, "list_drafts", lambda *a, **k: draft_result())
    run = Mock()
    monkeypatch.setattr(creator, "_run", run)
    result = creator.open_draft(Mock(), "d1", "测试稿", "image")
    assert result["status"] == "preview" and not result["opened"]
    run.assert_not_called()


def test_open_draft_checks_exact_title(monkeypatch):
    monkeypatch.setattr(creator, "list_drafts", lambda *a, **k: draft_result())
    with pytest.raises(creator.CreatorManageError, match="未同时匹配"):
        creator.open_draft(Mock(), "d1", "其他稿", "image", open_editor=True)


def test_open_draft_verifies_editor_title_never_saves(monkeypatch):
    monkeypatch.setattr(creator, "list_drafts", lambda *a, **k: draft_result())
    run = Mock(return_value={"clicked": True})
    monkeypatch.setattr(creator, "_run", run)
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: identity({"titles": ["测试稿"]}))
    result = creator.open_draft(Mock(), "d1", "测试稿", "image", open_editor=True)
    assert result["opened"] and not result["saved"] and not result["published"]
    assert run.call_count == 1 and run.call_args.args[1] == "draft-open"
    assert run.call_args.kwargs["account_id"] == ACCOUNT


def test_open_draft_wrong_editor_is_unknown(monkeypatch):
    monkeypatch.setattr(creator, "list_drafts", lambda *a, **k: draft_result())
    monkeypatch.setattr(creator, "_run", lambda *a, **k: {"clicked": True})
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: identity({"titles": ["其他稿"]}))
    result = creator.open_draft(Mock(), "d1", "测试稿", "image", open_editor=True)
    assert result["status"] == "unknown" and not result["success"]


@pytest.mark.parametrize("limit,pages", [(0, 3), (501, 3), (1, 0), (1, 21)])
def test_invalid_bounds_before_browser(limit, pages):
    page = Mock()
    with pytest.raises(creator.CreatorManageError):
        creator.list_drafts(page, limit=limit, max_pages=pages)
    page.navigate.assert_not_called()


def test_account_switch_between_selection_and_first_page_stops(monkeypatch):
    states = iter([
        identity({"ready": True}),
        identity({"account_id": "b" * 24, "items": [], "complete": True, "total": 0}),
    ])
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: next(states))
    with pytest.raises(creator.CreatorManageError, match="账号发生变化"):
        creator._collect(Mock(), "notes", "note_id", 3)


def test_account_switch_during_pagination_stops_without_mixed_records(monkeypatch):
    states = iter([
        identity({"ready": True}),
        identity({"items": [{"note_id": "1"}], "complete": False, "total": 2}),
        identity({"account_id": "b" * 24, "items": [{"note_id": "2"}],
                  "complete": True, "total": 1}),
    ])
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: next(states))
    monkeypatch.setattr(creator, "_run", lambda *a, **k: identity({}))
    with pytest.raises(creator.CreatorManageError, match="账号发生变化"):
        creator._collect(Mock(), "notes", "note_id", 3)


def test_draft_group_uses_original_account_id(monkeypatch):
    monkeypatch.setattr(creator, "_prepare", lambda *a, **k: None)
    monkeypatch.setattr(creator, "_wait", lambda *a, **k: identity({}))
    groups = []

    def collect(*a, **kwargs):
        groups.append(kwargs["account_id"])
        return identity({"items": [], "complete": True, "total": 0})

    monkeypatch.setattr(creator, "_collect", collect)
    result = creator.list_drafts(Mock())
    assert groups == [ACCOUNT] * 4
    assert result["account_id"] == ACCOUNT


def test_run_rejects_identity_change_even_with_valid_data():
    page = Mock()
    page.evaluate.return_value = {"ready": True, "account_id": "b" * 24, "items": []}
    with pytest.raises(creator.CreatorManageError, match="账号发生变化"):
        creator._run(page, "notes-read", account_id=ACCOUNT)
