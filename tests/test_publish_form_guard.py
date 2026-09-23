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


def snapshot(body="第一行\n第二行", title="标题", images=2, url=URL):
    return {
        "url": url,
        "title_count": 1,
        "editor_count": 1,
        "image_area": True,
        "title": title,
        "body": body,
        "images": images,
    }


class DraftPage:
    def __init__(self, body="第一行", **changes):
        self.state = snapshot(body=body, **changes)
        self.writes = 0
        self.calls = []

    def evaluate(self, expression):
        self.calls.append(expression)
        if "const wanted =" in expression:
            self.writes += 1
            self.state["body"] = "第一行\n第二行"
            return True
        return self.state.copy()


def test_inspection_reads_only_scoped_fields_and_rejects_other_page():
    page = DraftPage()
    assert publish_form.inspect_publish_form(page) == {
        "url": URL,
        "title": "标题",
        "body": "第一行",
        "images": 2,
    }
    assert len(page.calls) == 1
    assert "document.body.innerText" not in page.calls[0]
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
    ],
)
def test_inspection_requires_unique_editor_and_valid_image_area(change):
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
        ("正文\n#旅行", "正文\n#旅行", True),
    ],
)
def test_fill_body_verification_handles_newlines_and_topics(actual, expected, ok):
    result = publish_form._body_matches(actual, *publish_form._expected_parts(expected, []))
    assert result is ok


def test_fill_verification_fails_on_each_key_field():
    for change in ({"title": "别的标题"}, {"images": 1}, {"body": "第一行"}):
        state = {"title": "标题", "images": 2, "body": "第一行\n第二行", **change}
        with pytest.raises(PublishError, match="未发布"):
            publish_form.verify_publish_form(state, "标题", "第一行\n第二行", 2)


def test_restore_only_once_after_exact_prefix_match():
    page = DraftPage()
    result = publish_form.restore_publish_body(page, "标题", "第一行\n第二行", 2)
    assert result["restored"] == ["第二行"]
    assert page.writes == 1
    again = publish_form.restore_publish_body(page, "标题", "第一行\n第二行", 2)
    assert again["restored"] == []
    assert page.writes == 1


@pytest.mark.parametrize(
    "body,title,images,content",
    [
        ("其他", "标题", 2, "第一行\n第二行"),
        ("第一行\n第三行", "标题", 2, "第一行\n第二行\n第三行"),
        ("第一行", "别的标题", 2, "第一行\n第二行"),
        ("第一行", "标题", 1, "第一行\n第二行"),
        ("第一行", "标题", 2, "第一行\n第二行\n#旅行"),
    ],
)
def test_restore_rejects_unsafe_state_without_write(body, title, images, content):
    page = DraftPage(body=body, title=title, images=images)
    with pytest.raises(PublishError, match="未修改草稿"):
        publish_form.restore_publish_body(page, "标题", content, 2)
    assert page.writes == 0


def test_inspect_cli_needs_no_files_and_never_fills(monkeypatch):
    args = cli.build_parser().parse_args(["inspect-publish-form"])
    page = DraftPage()
    browser = Mock()
    monkeypatch.setattr(cli, "_connect_existing", lambda _: (browser, page))
    output = Mock()
    monkeypatch.setattr(cli, "_output", output)
    args.func(args)
    assert output.call_args.args[0]["preview"]["title"] == "标题"
    assert page.writes == 0
    browser.close.assert_called_once()


def test_duplicate_lines_are_not_restored_automatically():
    page = DraftPage(body="重复")
    with pytest.raises(PublishError, match="重复行"):
        publish_form.restore_publish_body(page, "标题", "重复\n重复", 2)
    assert page.writes == 0


def test_fill_cli_verifies_snapshot_before_reporting_success(tmp_path, monkeypatch):
    import image_downloader
    from xhs import publish

    title_file = tmp_path / "title.txt"
    content_file = tmp_path / "content.txt"
    image_file = tmp_path / "image.png"
    title_file.write_text("标题", encoding="utf-8")
    content_file.write_text("第一行\n第二行", encoding="utf-8")
    image_file.touch()
    args = cli.build_parser().parse_args(
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
    page = DraftPage(body="第一行\n第二行", images=1)
    browser = Mock()
    fill = Mock()
    output = Mock()
    monkeypatch.setattr(cli, "_connect", lambda _: (browser, page))
    monkeypatch.setattr(cli, "_output", output)
    monkeypatch.setattr(image_downloader, "process_images", lambda paths: paths)
    monkeypatch.setattr(publish, "fill_publish_form", fill)
    args.func(args)
    fill.assert_called_once()
    assert output.call_args.args[0]["verification"]["verified"] is True
    browser.close.assert_called_once()


def test_fill_cli_fails_on_missing_body_without_publishing(tmp_path, monkeypatch):
    import image_downloader
    from xhs import publish

    title_file = tmp_path / "title.txt"
    content_file = tmp_path / "content.txt"
    image_file = tmp_path / "image.png"
    title_file.write_text("标题", encoding="utf-8")
    content_file.write_text("第一行\n第二行", encoding="utf-8")
    image_file.touch()
    args = cli.build_parser().parse_args(
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
    page = DraftPage(body="第一行", images=1)
    browser = Mock()
    monkeypatch.setattr(cli, "_connect", lambda _: (browser, page))
    monkeypatch.setattr(image_downloader, "process_images", lambda paths: paths)
    monkeypatch.setattr(publish, "fill_publish_form", Mock())
    with pytest.raises(PublishError, match="body"):
        args.func(args)
    browser.close.assert_called_once()
    assert page.writes == 0
