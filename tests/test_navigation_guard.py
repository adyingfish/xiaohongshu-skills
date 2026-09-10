import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xhs.errors import XHSError
from xhs.navigation import _GUARD, GuardedPage


@pytest.mark.parametrize("state", [None, {}, {"safe": False, "reason": "现有草稿"}])
def test_unknown_or_dirty_editor_never_navigates(state):
    page = Mock()
    page.evaluate.return_value = state
    with pytest.raises(XHSError):
        GuardedPage(page).navigate("https://www.xiaohongshu.com/notification")
    page.navigate.assert_not_called()


def test_safe_navigation_and_other_operations_are_forwarded():
    page = Mock()
    page.evaluate.return_value = {"safe": True}
    guard = GuardedPage(page)
    guard.navigate("https://www.xiaohongshu.com/notification")
    page.navigate.assert_called_once_with("https://www.xiaohongshu.com/notification")
    guard.wait_for_load()
    page.wait_for_load.assert_called_once()


# Run the actual shipped JavaScript instead of pre-deciding the guard result in a mock.
# The restored-image selector is the one used by the existing publishing code.
_NODE = shutil.which("node")
_DRIVER = r"""
const fs = require('fs');
const vm = require('vm');
const {source, mode} = JSON.parse(fs.readFileSync(0, 'utf8'));
const inDraft = mode === 'draft_preview';
const hidden = mode === 'selected_hidden_file';
const mediaTags = {image: 'IMG', video: 'VIDEO', audio: 'AUDIO'};
const media = {tagName: mediaTags[mode.split('_').at(-1)] || 'IMG'};
const drawer = {contains: el => el.inDraft, querySelector: s => s === '.draft-list' ? {} : null,
    getBoundingClientRect: () => ({width: 600, height: 500})};
const box = {
    inDraft, tagName: 'DIV', value: '', textContent: mode === 'text' ? '未保存正文' : '',
    files: hidden ? [{}] : [],
    getBoundingClientRect: () => ({width: hidden ? 0 : 200, height: hidden ? 0 : 100}),
    getAttribute: s => s === 'contenteditable' ? 'true' : null,
    closest: () => inDraft ? drawer : null,
    querySelector: s => mode.startsWith('rich_text_') &&
        s.split(',').includes(media.tagName.toLowerCase()) ? media : null,
};
const controls = mode.startsWith('rich_text_') || mode === 'text' ? [box] : [];
const document = {
    querySelectorAll(selector) {
        if (selector.includes('contenteditable')) return controls;
        if (selector === 'input[type="file"]') return hidden ? [box] : [];
        if (selector === '.d-drawer') return inDraft ? [drawer] : [];
        if (selector === '.draft-list') return [];
        if (selector.split(',').some(s => s.trim() === '.img-preview-area .pr')) {
            return mode === 'restored_image' || inDraft ? [box] : [];
        }
        return [];
    }
};
const result = vm.runInNewContext(source, {document,
    location: {hostname: 'creator.xiaohongshu.com', origin: 'https://creator.xiaohongshu.com',
        pathname: '/publish/publish'},
    getComputedStyle: () => ({display: 'block', visibility: 'visible', opacity: '1'})});
process.stdout.write(JSON.stringify(result));
"""


@pytest.mark.skipif(not _NODE, reason="执行网页 JavaScript 回归测试需要 Node.js")
@pytest.mark.parametrize("guard", ["navigation", "creator"])
@pytest.mark.parametrize("mode,safe", [
    ("restored_image", False),
    ("rich_text_image", False),
    ("rich_text_video", False),
    ("rich_text_audio", False),
    ("selected_hidden_file", False),
    ("text", False),
    ("draft_preview", True),
    ("empty", True),
])
def test_actual_page_guard_preserves_editor_media(guard, mode, safe):
    if guard == "navigation":
        source = _GUARD
        key = "safe"
    else:
        script = (Path(__file__).resolve().parents[1] / "scripts/xhs/creator_manage.js").read_text()
        source = "(" + script + ")({action: 'guard'})"
        key = "safe_to_navigate"
    result = subprocess.run(
        [_NODE, "-e", _DRIVER],
        input=json.dumps({"source": source, "mode": mode}),
        text=True, capture_output=True, check=True, timeout=10,
    )
    assert json.loads(result.stdout)[key] is safe
