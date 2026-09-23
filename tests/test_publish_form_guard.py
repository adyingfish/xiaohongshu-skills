from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cli
from xhs import publish_form
from xhs.errors import PublishError

URL = "https://creator.xiaohongshu.com/publish/publish?source=official"


def snapshot(body="第一行\n第二行", title="标题", images=2, **changes):
    return {
        "url": URL,
        "tab_id": 11,
        "title_count": 1,
        "editor_count": 1,
        "image_area": True,
        "title": title,
        "body": body,
        "body_plain": body,
        "images": images,
        "topics": [],
        "topic_state": "none",
        "topic_block_index": None,
        **changes,
    }


class DraftPage:
    def __init__(self, body="第一行", **changes):
        self.state = snapshot(body=body, **changes)
        self.writes = 0
        self.calls = []

    def evaluate_existing_creator(self, expression, tab_id=None):
        self.calls.append((expression, tab_id))
        if "const wanted =" in expression:
            self.writes += 1
            self.state["body_plain"] = "第一行\n第二行"
            self.state["body"] = "第一行\n第二行" + (
                "\n#旅行" if self.state["topic_state"] == "bound" else ""
            )
            return True
        return self.state.copy()


def test_inspection_scopes_fields_and_pins_tab():
    page = DraftPage()
    inspected = publish_form.inspect_publish_form(page, tab_id=11)
    assert inspected["tab_id"] == 11
    assert inspected["body_plain"] == "第一行"
    assert len(page.calls) == 1
    assert page.calls[0][1] == 11
    assert "document.body.innerText" not in page.calls[0][0]
    page.state["url"] = "https://example.com/publish/publish"
    with pytest.raises(PublishError, match="不是小红书图文创作页"):
        publish_form.inspect_publish_form(page)
    assert page.writes == 0


@pytest.mark.parametrize(
    "change",
    [
        {"title_count": 0},
        {"title_count": 2},
        {"editor_count": 2},
        {"image_area": False},
        {"images": None},
        {"topic_state": "invalid"},
    ],
)
def test_inspection_rejects_incomplete_or_ambiguous_page(change):
    page = DraftPage()
    page.state.update(change)
    with pytest.raises(PublishError):
        publish_form.inspect_publish_form(page)
    assert page.writes == 0


@pytest.mark.parametrize(
    "actual,expected,ok",
    [
        ("正文\n", "正文", True),
        ("正文\r\n第二行", "正文\n第二行", True),
        ("正文\n\n第二行", "正文\n第二行", False),
        ("正文第二行", "正文\n第二行", False),
        ("  缩进", "缩进", False),
        ("行尾 ", "行尾", False),
    ],
)
def test_body_verification_preserves_meaningful_whitespace(actual, expected, ok):
    result = publish_form.verify_publish_form(
        publish_form._validate_snapshot(snapshot(body=actual)), "标题", expected, 2
    )
    assert result["checks"]["body"] is ok


def test_plain_hashtag_is_not_verified_as_bound_topic():
    actual = publish_form._validate_snapshot(snapshot(body="正文\n#旅行"))
    result = publish_form.verify_publish_form(actual, "标题", "正文\n#旅行", 2)
    assert result["verified"] is False
    assert result["status"] == "unverified"
    assert result["checks"]["topics"] is None


def test_structurally_bound_topics_have_separate_verification():
    actual = publish_form._validate_snapshot(
        snapshot(
            body="正文\n#旅行",
            body_plain="正文",
            topics=["旅行"],
            topic_state="bound",
            topic_block_index=1,
        )
    )
    result = publish_form.verify_publish_form(actual, "标题", "正文\n#旅行", 2)
    assert result["verified"] is True
    assert result["checks"]["topics"] is True
    unknown = dict(actual, body_plain=None, topics=[], topic_state="unknown")
    result = publish_form.verify_publish_form(unknown, "标题", "正文\n#旅行", 2)
    assert result["status"] == "unverified"
    assert result["checks"]["topics"] is None


def test_verification_reports_each_mismatched_key():
    for change, key in [
        ({"title": "别的标题"}, "title"),
        ({"images": 1}, "images"),
        ({"body_plain": "第一行"}, "body"),
    ]:
        actual = publish_form._validate_snapshot(snapshot(**change))
        result = publish_form.verify_publish_form(actual, "标题", "第一行\n第二行", 2)
        assert result["status"] == "mismatch"
        assert result["checks"][key] is False


def test_restore_only_once_after_exact_prefix_match_and_pins_tab():
    page = DraftPage()
    result = publish_form.restore_publish_body(page, "标题", "第一行\n第二行", 2)
    assert result["restored"] == ["第二行"]
    assert result["verification"]["verified"] is True
    assert page.calls[1][1] == 11
    assert page.calls[2][1] == 11
    again = publish_form.restore_publish_body(page, "标题", "第一行\n第二行", 2)
    assert again["restored"] == []
    assert page.writes == 1


@pytest.mark.parametrize(
    "content,tags",
    [
        ("第一行\n第二行", ["旅行"]),
        ("第一行\n第二行\n#旅行", []),
    ],
)
def test_restore_ordinary_suffix_before_bound_topic(content, tags):
    page = DraftPage(
        body="第一行\n#旅行",
        body_plain="第一行",
        topics=["旅行"],
        topic_state="bound",
        topic_block_index=1,
    )
    result = publish_form.restore_publish_body(page, "标题", content, 2, tags)
    assert result["restored"] == ["第二行"]
    assert result["verification"]["checks"]["topics"] is True
    assert page.writes == 1
    again = publish_form.restore_publish_body(page, "标题", content, 2, tags)
    assert again["restored"] == []
    assert page.writes == 1


@pytest.mark.parametrize(
    "body,title,images,content",
    [
        ("其他", "标题", 2, "第一行\n第二行"),
        ("第一行\n第三行", "标题", 2, "第一行\n第二行\n第三行"),
        ("第一行", "别的标题", 2, "第一行\n第二行"),
        ("第一行", "标题", 1, "第一行\n第二行"),
        ("", "标题", 2, "第一行\n第二行"),
        ("第一行", "标题", 2, "第一行\n\n第二行"),
    ],
)
def test_restore_rejects_unsafe_prose_without_write(body, title, images, content):
    page = DraftPage(body=body, body_plain=body, title=title, images=images)
    with pytest.raises(PublishError, match="未修改草稿"):
        publish_form.restore_publish_body(page, "标题", content, 2)
    assert page.writes == 0


def test_restore_rejects_unknown_or_plain_topic_without_write():
    for changes in [
        {"body": "第一行\n#旅行", "body_plain": "第一行\n#旅行"},
        {"body": "第一行\n#旅行", "body_plain": None, "topic_state": "unknown"},
    ]:
        page = DraftPage(**changes)
        with pytest.raises(PublishError, match="未修改草稿"):
            publish_form.restore_publish_body(page, "标题", "第一行\n第二行\n#旅行", 2)
        assert page.writes == 0


def test_duplicate_lines_are_not_restored_automatically():
    page = DraftPage(body="重复", body_plain="重复")
    with pytest.raises(PublishError, match="重复行"):
        publish_form.restore_publish_body(page, "标题", "重复\n重复", 2)
    assert page.writes == 0


def test_inspect_cli_needs_no_files_or_browser_start(monkeypatch):
    args = cli.build_parser().parse_args(["inspect-publish-form", "--tab-id", "11"])
    page = DraftPage()
    browser = Mock()
    monkeypatch.setattr(cli, "_connect_readonly", lambda _: (browser, page))
    output = Mock()
    monkeypatch.setattr(cli, "_output", output)
    args.func(args)
    assert output.call_args.args[0]["preview"]["title"] == "标题"
    assert page.calls[0][1] == 11
    assert page.writes == 0
    browser.close.assert_called_once()


def test_current_tab_cli_uses_minimal_bridge_command(monkeypatch):
    args = cli.build_parser().parse_args(["inspect-current-xhs-tab"])
    page = Mock()
    page.inspect_current_xhs_tab.return_value = {"tab_id": 4, "page_type": "home"}
    browser = Mock()
    monkeypatch.setattr(cli, "_connect_readonly", lambda _: (browser, page))
    output = Mock()
    monkeypatch.setattr(cli, "_output", output)
    args.func(args)
    assert output.call_args.args[0]["tab"]["page_type"] == "home"
    page.inspect_current_xhs_tab.assert_called_once()
    browser.close.assert_called_once()


def _fill_args(tmp_path):
    title_file = tmp_path / "title.txt"
    content_file = tmp_path / "content.txt"
    image_file = tmp_path / "image.png"
    title_file.write_text("标题", encoding="utf-8")
    content_file.write_text("第一行\n第二行", encoding="utf-8")
    image_file.touch()
    return cli.build_parser().parse_args(
        [
            "fill-publish",
            "--title-file",
            str(title_file),
            "--content-file",
            str(content_file),
            "--images",
            str(image_file),
        ]
    )


def test_fill_cli_reports_verified_state(tmp_path, monkeypatch):
    import image_downloader
    from xhs import publish

    args = _fill_args(tmp_path)
    page = DraftPage(body="第一行\n第二行", body_plain="第一行\n第二行", images=1)
    browser = Mock()
    output = Mock()
    monkeypatch.setattr(cli, "_connect", lambda _: (browser, page))
    monkeypatch.setattr(cli, "_output", output)
    monkeypatch.setattr(image_downloader, "process_images", lambda paths: paths)
    monkeypatch.setattr(publish, "fill_publish_form", Mock())
    args.func(args)
    data = output.call_args.args[0]
    assert data["form_state"] == "filled"
    assert data["published"] is False
    assert data["verification"]["verified"] is True
    browser.close.assert_called_once()


def test_fill_cli_mismatch_does_not_invite_refill(tmp_path, monkeypatch):
    import image_downloader
    from xhs import publish

    args = _fill_args(tmp_path)
    page = DraftPage(body="第一行", body_plain="第一行", images=1)
    browser = Mock()
    output = Mock()
    monkeypatch.setattr(cli, "_connect", lambda _: (browser, page))
    monkeypatch.setattr(cli, "_output", output)
    monkeypatch.setattr(image_downloader, "process_images", lambda paths: paths)
    monkeypatch.setattr(publish, "fill_publish_form", Mock())
    args.func(args)
    data = output.call_args.args[0]
    assert data["form_state"] == "filled"
    assert data["verification"]["status"] == "mismatch"
    assert "勿自动重填" in data["next_step"]
    assert output.call_args.kwargs["exit_code"] == 2
    browser.close.assert_called_once()


def test_restore_cli_reads_separate_topic_file(tmp_path, monkeypatch):
    title_file = tmp_path / "title.txt"
    content_file = tmp_path / "content.txt"
    tags_file = tmp_path / "tags.txt"
    title_file.write_text("标题", encoding="utf-8")
    content_file.write_text("第一行\n第二行", encoding="utf-8")
    tags_file.write_text("旅行\n摄影\n", encoding="utf-8")
    args = cli.build_parser().parse_args(
        [
            "restore-publish-body",
            "--title-file",
            str(title_file),
            "--content-file",
            str(content_file),
            "--image-count",
            "2",
            "--tags-file",
            str(tags_file),
            "--tab-id",
            "11",
        ]
    )
    page = Mock()
    browser = Mock()
    monkeypatch.setattr(cli, "_connect_readonly", lambda _: (browser, page))
    output = Mock()
    monkeypatch.setattr(cli, "_output", output)
    restore = Mock(return_value={"restored": []})
    monkeypatch.setattr(publish_form, "restore_publish_body", restore)
    args.func(args)
    restore.assert_called_once_with(page, "标题", "第一行\n第二行", 2, ["旅行", "摄影"], 11)


def test_restore_cli_preserves_body_indentation(tmp_path, monkeypatch):
    title_file = tmp_path / "title.txt"
    content_file = tmp_path / "content.txt"
    title_file.write_text("标题", encoding="utf-8")
    content_file.write_text("  缩进正文  \n", encoding="utf-8")
    args = cli.build_parser().parse_args(
        [
            "restore-publish-body",
            "--title-file",
            str(title_file),
            "--content-file",
            str(content_file),
            "--image-count",
            "1",
        ]
    )
    page = Mock()
    monkeypatch.setattr(cli, "_connect_readonly", lambda _: (Mock(), page))
    monkeypatch.setattr(cli, "_output", Mock())
    restore = Mock(return_value={"restored": []})
    monkeypatch.setattr(publish_form, "restore_publish_body", restore)
    args.func(args)
    assert restore.call_args.args[2] == "  缩进正文  "
