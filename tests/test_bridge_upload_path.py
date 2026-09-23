from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from xhs.bridge import BridgePage, browser_upload_path


def test_local_mode_keeps_execution_path_and_order(tmp_path, monkeypatch):
    files = [tmp_path / "a.png", tmp_path / "b.mp4"]
    for path in files:
        path.touch()
    monkeypatch.delenv("XHS_BROWSER_PATH_STYLE", raising=False)
    page = BridgePage()
    page._call = Mock()
    page.set_file_input("input[type=file]", [str(path) for path in files])
    page._call.assert_called_once_with(
        "set_file_input", {"selector": "input[type=file]", "files": [str(path) for path in files]}
    )


def test_windows_mode_converts_wsl_mount_before_bridge_call(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_PATH_STYLE", "windows")
    monkeypatch.setattr("xhs.bridge.os.path.isfile", lambda _: True)
    monkeypatch.setattr("xhs.bridge.os.access", lambda *_: True)
    page = BridgePage()
    page._call = Mock()
    page.set_file_input("image-input", ["/mnt/c/a b/图片.png", "/mnt/d/视频.mp4"])
    page._call.assert_called_once_with(
        "set_file_input", {"selector": "image-input", "files": [r"C:\a b\图片.png", r"D:\视频.mp4"]}
    )


@pytest.mark.parametrize("path", ["", "relative.png", "/home/user/image.png", "/mnt/c/no-file.png"])
def test_invalid_windows_upload_fails_before_extension(path, tmp_path, monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_PATH_STYLE", "windows")
    page = BridgePage()
    page._call = Mock()
    with pytest.raises(ValueError):
        page.set_file_input("image-input", [path])
    page._call.assert_not_called()


def test_unsupported_style_fails(tmp_path, monkeypatch):
    file = tmp_path / "image.png"
    file.touch()
    monkeypatch.setenv("XHS_BROWSER_PATH_STYLE", "guess")
    with pytest.raises(ValueError, match="仅支持"):
        browser_upload_path(str(file))


def test_existing_creator_evaluation_uses_dedicated_extension_command():
    page = BridgePage()
    page._call = Mock(return_value={"title": "标题"})
    assert page.evaluate_existing_creator("1 + 1") == {"title": "标题"}
    page._call.assert_called_once_with("evaluate_existing_creator", {"expression": "1 + 1"})


def test_native_windows_absolute_path_is_preserved(monkeypatch):
    from types import SimpleNamespace

    import xhs.bridge as bridge

    fake_os = SimpleNamespace(
        name="nt",
        path=SimpleNamespace(isfile=lambda _: True),
        access=lambda *_: True,
        R_OK=4,
    )
    monkeypatch.setattr(bridge, "os", fake_os)
    assert bridge.browser_upload_path(r"C:\图片\示例.png", "windows") == r"C:\图片\示例.png"


def test_existing_relative_video_path_is_resolved_in_local_mode(tmp_path, monkeypatch):
    video = tmp_path / "视频.mp4"
    video.touch()
    monkeypatch.chdir(tmp_path)
    assert browser_upload_path("视频.mp4", "local") == str(video)
    page = BridgePage()
    page._call = Mock()
    page.set_file_input("video-input", ["视频.mp4"])
    page._call.assert_called_once_with(
        "set_file_input", {"selector": "video-input", "files": [str(video)]}
    )


def test_relative_path_must_resolve_to_wsl_mount_for_windows_mode(monkeypatch):
    import xhs.bridge as bridge

    monkeypatch.setattr(bridge.os.path, "abspath", lambda _: "/mnt/c/素材/视频.mp4")
    monkeypatch.setattr(bridge.os.path, "isfile", lambda _: True)
    monkeypatch.setattr(bridge.os.path, "realpath", lambda path: path)
    monkeypatch.setattr(bridge.os, "access", lambda *_: True)
    assert bridge.browser_upload_path("视频.mp4", "windows") == r"C:\素材\视频.mp4"


def test_creator_evaluation_can_pin_tab_and_current_tab_is_separate():
    page = BridgePage()
    page._call = Mock(side_effect=[{"tab_id": 11}, {"page_type": "home"}])
    assert page.evaluate_existing_creator("1 + 1", tab_id=11) == {"tab_id": 11}
    assert page.inspect_current_xhs_tab() == {"page_type": "home"}
    assert page._call.call_args_list[0].args == (
        "evaluate_existing_creator",
        {"expression": "1 + 1", "tabId": 11},
    )
    assert page._call.call_args_list[1].args == ("inspect_current_xhs_tab",)


def test_existing_relative_linux_file_is_rejected_for_windows_browser(tmp_path, monkeypatch):
    file = tmp_path / "视频.mp4"
    file.touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XHS_BROWSER_PATH_STYLE", "windows")
    page = BridgePage()
    page._call = Mock()
    with pytest.raises(ValueError, match="Windows 浏览器无法访问"):
        page.set_file_input("video-input", ["视频.mp4"])
    page._call.assert_not_called()
