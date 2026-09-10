from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xhs import library
from xhs.errors import NotLoggedInError

ACCOUNT = "0123456789abcdef01234567"
OTHER = "abcdef0123456789abcdef01"
NOTE_A = "aaaaaaaaaaaaaaaaaaaaaaaa"
NOTE_B = "bbbbbbbbbbbbbbbbbbbbbbbb"


def record(note_id=NOTE_A, title="测试笔记", author="作者"):
    return {"id": note_id, "displayTitle": title, "xsecToken": "token+a",
            "user": {"userId": ACCOUNT, "nickname": author}}


def snapshot(items, *, more=False, cursor="", page=1, scope="notes"):
    return {"ready": True, "records": items, "account_id": ACCOUNT, "nickname": "自己",
            "scope": scope, "cursor": cursor, "page": page, "has_more": more,
            "record_format": "note_metadata"}


def test_pagination_deduplicates_updates_and_marks_exhaustion(monkeypatch):
    first = snapshot([record()], more=True, cursor="a")
    second = snapshot([record(title="更新标题"), record(NOTE_B)], cursor="b", page=2)
    monkeypatch.setattr(library, "_open_own", Mock(return_value=first))
    run = Mock(side_effect=[{"scrolled": True}, second])
    monkeypatch.setattr(library, "_run", run)
    result = library.list_library(Mock(), "notes")
    assert result["count"] == 2
    assert result["items"][0]["displayTitle"] == "更新标题"
    assert result["complete"] is True
    assert result["pages_requested"] == 2
    assert "xsec_token=token%2Ba" in result["items"][0]["shareUrl"]


def test_limit_and_page_bound_do_not_claim_full_coverage(monkeypatch):
    monkeypatch.setattr(library, "_open_own", Mock(return_value=snapshot(
        [record(), record(NOTE_B)], more=False,
    )))
    limited = library.list_library(Mock(), "notes", limit=1)
    assert limited["count"] == 1 and limited["complete"] is False
    assert limited["has_more"] is False and limited["stopped_reason"] == "limit"
    monkeypatch.setattr(library, "_open_own", Mock(return_value=snapshot([record()], more=True)))
    bounded = library.list_library(Mock(), "notes", max_pages=1)
    assert bounded["complete"] is False and bounded["stopped_reason"] == "max_pages"


def test_stalled_page_returns_partial_data(monkeypatch):
    state = snapshot([record()], more=True)
    monkeypatch.setattr(library, "_open_own", Mock(return_value=state))
    monkeypatch.setattr(library, "_run", Mock(side_effect=[{"scrolled": True}, state]))
    result = library.list_library(Mock(), "favorites", timeout=0)
    assert result["complete"] is False and result["stopped_reason"] == "stalled"
    assert result["count"] == 1


def test_keyword_search_is_title_or_author_only(monkeypatch):
    monkeypatch.setattr(library, "_open_own", Mock(return_value=snapshot([
        record(title="隐藏正文", author="旅行作者"), record(NOTE_B, title="旅行攻略"),
    ])))
    result = library.list_library(Mock(), "notes", keyword="旅行")
    assert result["count"] == 2
    assert result["search_fields"] == ["displayTitle", "user.nickname"]
    empty = library.list_library(Mock(), "notes", keyword="不存在的正文")
    assert empty["count"] == 0 and empty["scanned_count"] == 2


def test_search_deduplicates_note_present_in_two_scopes(monkeypatch):
    def listing(page, scope, **kwargs):
        return {"account_id": ACCOUNT, "scope": scope, "items": [record()], "complete": True,
                "has_more": False, "stopped_reason": "end", "scanned_count": 1,
                "pages_requested": 1}

    monkeypatch.setattr(library, "list_library", listing)
    result = library.search_library(Mock(), "测试")
    assert result["count"] == 1
    assert result["items"][0]["scopes"] == ["notes", "favorites"]


def test_account_switch_during_search_is_rejected(monkeypatch):
    monkeypatch.setattr(library, "list_library", Mock(side_effect=[
        {"account_id": ACCOUNT}, {"account_id": OTHER},
    ]))
    with pytest.raises(library.LibraryError, match="账号发生变化"):
        library.search_library(Mock(), "测试")


def test_missing_data_and_login_are_not_empty_success():
    page = Mock()
    page.evaluate.return_value = json.dumps({"ready": False})
    with pytest.raises(library.LibraryError, match="未将加载失败"):
        library._wait(page, "read", "ready", timeout=0)
    page.evaluate.return_value = json.dumps({"not_logged_in": True})
    with pytest.raises(NotLoggedInError):
        library._run(page, "read")


def test_collection_records_preserved_without_guessing_app_fields(monkeypatch):
    raw = {"unknownNewField": {"title": "真实结构原样保留"}}
    monkeypatch.setattr(
        library, "_open_own", Mock(return_value=snapshot([raw], scope="collections")),
    )
    result = library.list_library(Mock(), "collections")
    assert result["items"] == [raw]
    assert "不代表 App" in result["limitation"]


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 501}, {"max_pages": 0},
                                   {"max_pages": 21}, {"timeout": -1}])
def test_invalid_bounds_rejected_before_page_access(kwargs):
    page = Mock()
    with pytest.raises(ValueError):
        library.list_library(page, "notes", **kwargs)
    page.evaluate.assert_not_called()


_NODE_RUNNER = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = {querySelectorAll: () => []};
const context = {window: {__INITIAL_STATE__: {user: input.user}},
    location: {origin: 'https://www.xiaohongshu.com', pathname: '/user/profile/' + input.profile},
    document: {querySelector: () => null, querySelectorAll: () => [root, root, root]},
    innerWidth: 1440, getComputedStyle: () => ({})};
const result = vm.runInNewContext('(' + input.script + ')', context)(input.params);
process.stdout.write(result);
"""


def run_js(user, scope="notes", profile=ACCOUNT):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node.js unavailable")
    result = subprocess.run(
        [executable, "-e", _NODE_RUNNER],
        input=json.dumps({"script": library._SCRIPT, "user": user, "profile": profile,
                          "params": {"action": "read", "scope": scope, "account_id": ACCOUNT}}),
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def state_user():
    def raw(note_id):
        return {"id": note_id, "noteCard": {"displayTitle": "示例", "user": {}}}

    return {
        "loggedIn": {"_value": True}, "userInfo": {"_value": {"userId": ACCOUNT}},
        "activeTab": {"query": "note", "index": 0},
        "activeSubTab": {"query": "note", "index": 1, "key": 0},
        "notes": {"0": {"0": raw(NOTE_A)}, "1": {"0": raw(NOTE_B)}, "3": {}},
        "noteQueries": {str(index): {"hasMore": False, "userId": ACCOUNT}
                        for index in [0, 1, 3]},
        "isFetchingNotes": {"0": False, "1": False, "3": False},
        "userNoteFetchingStatus": {"0": "resolved", "1": "pending", "3": "resolved"},
    }


def test_actual_javascript_selects_only_correct_numeric_dictionary_bucket():
    user = state_user()
    own = run_js(user)
    assert [item["id"] for item in own["records"]] == [NOTE_A]
    user["activeTab"] = {"query": "fav", "index": 1}
    favorites = run_js(user, "favorites")
    assert [item["id"] for item in favorites["records"]] == [NOTE_B]
    # 真实页面收藏 pending 未复位，但已有记录、hasMore=false 且 fetching=false。
    assert favorites["ready"] is True


def test_actual_javascript_uses_subtab_index_instead_of_key():
    user = state_user()
    user["activeTab"] = {"query": "fav", "index": 1}
    user["activeSubTab"] = {"query": "board", "index": 3, "key": 1}
    boards = run_js(user, "collections")
    assert boards["records"] == [] and boards["has_more"] is False
    assert boards["record_format"] == "web_collection_raw"


def test_actual_javascript_rejects_wrong_account_and_fetch_failure():
    user = state_user()
    assert "不一致" in run_js(user, profile=OTHER)["error"]
    user["userNoteFetchingStatus"]["0"] = "rejected"
    assert "失败" in run_js(user)["error"]


def test_actual_javascript_empty_loading_is_not_success():
    user = state_user()
    user["notes"]["0"] = {}
    user["userNoteFetchingStatus"]["0"] = "pending"
    user["noteQueries"]["0"]["hasMore"] = True
    assert run_js(user) == {"ready": False}
