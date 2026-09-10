from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from commands.links_export import register
from xhs import links
from xhs.export import to_markdown, write_export
from xhs.types import CommentList, FeedDetail, FeedDetailResponse

NOTE_ID = "0123456789abcdef01234567"
NOTE_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}"


def parser(connect=None, output=None):
    result = argparse.ArgumentParser()
    register(result.add_subparsers(required=True), connect or Mock(), output or Mock())
    return result


def test_share_url_preserves_token_without_query_injection():
    token = "abc+def/中文=&xsec_source=evil?%"
    result = links.resolve_link(links.make_share_url(NOTE_ID, token))
    assert result["feedId"] == NOTE_ID
    assert result["xsecToken"] == token
    assert result["accessVerified"] is False
    assert parse_qs(urlsplit(result["shareUrl"]).query)["xsec_source"] == ["pc_search"]


@pytest.mark.parametrize("path", [
    f"/explore/{NOTE_ID}", f"/discovery/item/{NOTE_ID}/",
    f"/user/profile/aaaaaaaaaaaaaaaaaaaaaaaa/{NOTE_ID}",
])
def test_pasted_share_text_resolves_locally_without_token(path, monkeypatch):
    fetch = Mock(side_effect=AssertionError("不得发出请求"))
    monkeypatch.setattr(links, "_redirect_location", fetch)
    result = links.resolve_link(f"一条分享文案 https://www.xiaohongshu.com{path}，复制打开！")
    assert result["hasToken"] is False
    assert result["redirects"] == 0
    fetch.assert_not_called()


@pytest.mark.parametrize("url", [
    f"https://www.xiaohongshu.com.evil.test/explore/{NOTE_ID}",
    f"https://www.xiaohongshu.com@127.0.0.1/explore/{NOTE_ID}",
    f"https://user@www.xiaohongshu.com/explore/{NOTE_ID}",
    f"https://www.xiaohongshu.com:9999/explore/{NOTE_ID}",
    f"https://www.xiaohongshu.com\\@example.com/explore/{NOTE_ID}",
    "file:///etc/passwd",
    "http://127.0.0.1/",
    "http://[::1]/",
    "https://www.xiaohongshu.com/user/profile/0123456789abcdef01234567",
])
def test_untrusted_or_non_note_links_rejected(url):
    with pytest.raises(ValueError):
        links.resolve_link(url)


def test_ambiguous_links_and_tokens_rejected():
    with pytest.raises(ValueError, match="仅包含一条"):
        links.resolve_link(NOTE_URL + " https://xhslink.com/a/xyz")
    with pytest.raises(ValueError, match="多个 xsec_token"):
        links.resolve_link(NOTE_URL + "?xsec_token=a&xsec_token=b")


def test_short_link_follows_relative_redirect_and_returns_verified_shape(monkeypatch):
    fetch = Mock(side_effect=["/o/second", NOTE_URL + "?xsec_token=a%2Bb"])
    monkeypatch.setattr(links, "_redirect_location", fetch)
    result = links.resolve_link("http://xhslink.com/a/first")
    assert result["xsecToken"] == "a+b"
    assert result["redirects"] == 2
    assert fetch.call_args_list[1].args[0] == "http://xhslink.com/o/second"


@pytest.mark.parametrize("redirect", [
    "http://127.0.0.1/secret", "http://169.254.169.254/", "https://evil.test/",
    "file:///etc/passwd", "//example.com/path", "https://xhslink.com:9999/path",
])
def test_short_link_never_requests_untrusted_redirect_target(redirect, monkeypatch):
    fetch = Mock(return_value=redirect)
    monkeypatch.setattr(links, "_redirect_location", fetch)
    with pytest.raises(ValueError):
        links.resolve_link("https://xhslink.com/a/first")
    assert fetch.call_count == 1


def test_short_link_loop_and_limit_are_bounded(monkeypatch):
    monkeypatch.setattr(links, "_redirect_location", Mock(return_value="/a/first"))
    with pytest.raises(ValueError, match="循环"):
        links.resolve_link("https://xhslink.com/a/first")
    monkeypatch.setattr(links, "_redirect_location", Mock(side_effect=["/a/2", "/a/3"]))
    with pytest.raises(ValueError, match="次数"):
        links.resolve_link("https://xhslink.com/a/first", max_redirects=2)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"])
def test_short_host_resolving_to_private_address_rejected(ip, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", Mock(return_value=[(0, 0, 0, "", (ip, 443))]))
    with pytest.raises(ValueError, match="非公开"):
        links._public_address("xhslink.com", 443)


def test_pinned_https_connection_uses_checked_ip_and_original_tls_hostname(monkeypatch):
    connect = Mock(return_value=Mock())
    context = Mock()
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(links.ssl, "create_default_context", Mock(return_value=context))
    connection = links._PinnedHTTPSConnection("xhslink.com", "1.1.1.1", 443, 10)
    connection.connect()
    connect.assert_called_once_with(("1.1.1.1", 443), 10)
    context.wrap_socket.assert_called_once_with(connect.return_value, server_hostname="xhslink.com")


def test_json_export_is_lossless_and_refuses_overwrite(tmp_path):
    path = tmp_path / "note.json"
    data = {"note": {"title": "中文 😀"}, "unknownField": [{"value": 123}]}
    result = write_export(data, path)
    assert json.loads(path.read_text()) == data
    assert result["mediaDownloaded"] is False
    with pytest.raises(FileExistsError):
        write_export({"new": True}, path)
    assert json.loads(path.read_text()) == data
    write_export({"new": True}, path, overwrite=True)
    assert json.loads(path.read_text()) == {"new": True}
    assert list(tmp_path.glob(".note.json.*")) == []


def test_export_refuses_relative_and_symlink_targets(tmp_path):
    with pytest.raises(ValueError, match="绝对"):
        write_export({}, "relative.json")
    target = tmp_path / "original.json"
    target.write_text("original")
    link = tmp_path / "linked.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="符号链接"):
        write_export({}, link, overwrite=True)
    assert target.read_text() == "original"


def test_markdown_contains_text_nested_comments_and_unknown_fields_without_remote_images(tmp_path):
    data = {
        "note": {
            "title": "<script>alert(1)</script>", "noteId": NOTE_ID,
            "body": "正文\n![追踪图片](https://evil.test/image)",
            "user": {"nickname": "作者"},
            "imageList": [{"urlDefault": "https://example.com/media.jpg"}],
            "interactInfo": {"likedCount": "9"},
        },
        "sourceUrl": NOTE_URL,
        "comments": [{"content": "评论", "user": {"nickname": "甲"},
                      "subComments": [{"content": "回复", "user": {"nickname": "乙"}}]}],
        "unknownField": "保留",
    }
    path = tmp_path / "note.md"
    write_export(data, path, format="markdown")
    text = path.read_text()
    # 摘要内不直接嵌入 HTML 或远程图片；原始数据保存在 fenced JSON 中。
    summary = text.split("## 完整数据")[0]
    assert "<script>" not in summary
    assert "![追踪图片]" not in summary
    assert "<https://example.com/media.jpg>" in summary
    assert "甲：评论" in text and "乙：回复" in text
    assert '"unknownField": "保留"' in text
    assert "不保证评论及回复齐全" in text


def test_generic_markdown_cannot_break_out_of_json_fence():
    result = to_markdown([{"message": "````\n<script>bad</script>"}])
    assert "`````json\n" in result
    assert result.endswith("`````\n")


def test_local_commands_never_connect_browser(tmp_path):
    connect = Mock(side_effect=AssertionError("不得连接浏览器"))
    output = Mock()
    cli = parser(connect, output)
    for argv in [
        ["get-share-url", "--feed-id", NOTE_ID, "--xsec-token", "a+b"],
        ["resolve-link", "--link", NOTE_URL],
    ]:
        args = cli.parse_args(argv)
        args.func(args)
    source = tmp_path / "input.json"
    source.write_text('{"items": []}')
    args = cli.parse_args([
        "export-content", "--input", str(source), "--output", str(tmp_path / "out.md"),
        "--format", "markdown",
    ])
    args.func(args)
    connect.assert_not_called()


def test_export_note_validates_token_and_output_before_browser(tmp_path):
    connect = Mock()
    cli = parser(connect)
    args = cli.parse_args([
        "export-note", "--link", NOTE_URL, "--output", str(tmp_path / "out.json"),
    ])
    with pytest.raises(ValueError, match="需要 xsec_token"):
        args.func(args)
    connect.assert_not_called()


def test_export_note_keeps_comment_coverage_and_encoded_token(tmp_path, monkeypatch):
    browser, page = Mock(), Mock()
    output = Mock()
    detail = FeedDetailResponse(
        note=FeedDetail(note_id=NOTE_ID, title="笔记"),
        comments=CommentList(has_more=True),
    )
    fetch = Mock(return_value=detail)
    monkeypatch.setattr("xhs.feed_detail.get_feed_detail", fetch)
    cli = parser(Mock(return_value=(browser, page)), output)
    path = tmp_path / "note.json"
    args = cli.parse_args([
        "export-note", "--feed-id", NOTE_ID, "--xsec-token", "a+b&x=1",
        "--output", str(path),
    ])
    args.func(args)
    fetch.assert_called_once_with(page, NOTE_ID, "a%2Bb%26x%3D1")
    data = json.loads(path.read_text())
    assert data["coverage"]["commentsComplete"] is False
    assert data["coverage"]["hasMoreComments"] is True
    browser.close.assert_called_once()


def test_export_note_mismatched_identity_does_not_write(tmp_path, monkeypatch):
    browser, page = Mock(), Mock()
    monkeypatch.setattr("xhs.feed_detail.get_feed_detail", Mock(return_value=FeedDetailResponse()))
    cli = parser(Mock(return_value=(browser, page)))
    path = tmp_path / "wrong.json"
    args = cli.parse_args([
        "export-note", "--feed-id", NOTE_ID, "--xsec-token", "token", "--output", str(path),
    ])
    with pytest.raises(ValueError, match="不一致"):
        args.func(args)
    assert not path.exists()
    browser.close.assert_called_once()


def test_feed_serialization_adds_encoded_share_url_without_breaking_empty_cards():
    from urllib.parse import parse_qs, urlsplit

    from xhs.types import Feed

    item = Feed(id="0123456789abcdef01234567", xsec_token="a+b&c=").to_dict()
    assert parse_qs(urlsplit(item["shareUrl"]).query)["xsec_token"] == ["a+b&c="]
    assert Feed().to_dict()["shareUrl"] == ""
    assert Feed(id="not-a-note", xsec_token="token").to_dict()["shareUrl"] == ""
