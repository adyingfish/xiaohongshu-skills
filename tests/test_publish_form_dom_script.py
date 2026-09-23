"""用最小 DOM 模型执行真实页面快照脚本，核对话题节点判定。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from xhs.publish_form import _SNAPSHOT_JS


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 不可用")
def test_dom_script_distinguishes_bound_topic_from_plain_hashtag():
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const expression = fs.readFileSync(0, 'utf8');
function run(bound) {
  const marker = {
    textContent: '#旅行',
    getAttribute: key => key === 'data-topic-id' ? 'topic-1' : null,
  };
  function block(text, hasMarker) {
    return {
      innerText: text,
      matches: () => true,
      querySelectorAll: () => hasMarker ? [marker] : [],
      cloneNode: () => {
        const copy = {textContent: text};
        copy.querySelectorAll = () => hasMarker ? [{remove: () => {copy.textContent = '';}}] : [];
        return copy;
      },
    };
  }
  const editor = {
    getClientRects: () => [1],
    innerText: '正文\n#旅行',
    children: [block('正文', false), block('#旅行', bound)],
    querySelectorAll: () => bound ? [marker] : [],
  };
  const title = {getClientRects: () => [1], value: '标题'};
  const document = {
    querySelectorAll: selector => {
      if (selector === 'div.d-input input') return [title];
      if (selector === 'div.ql-editor') return [editor];
      if (selector === '[role="textbox"][contenteditable="true"]') return [];
      if (selector === '.img-preview-area .pr') return [{}, {}];
      return [];
    },
    querySelector: selector => selector === '.img-preview-area' ? {} : null,
  };
  return vm.runInNewContext(expression, {
    document,
    location: {href: 'https://creator.xiaohongshu.com/publish/publish'},
    getComputedStyle: () => ({visibility: 'visible'}),
  });
}
process.stdout.write(JSON.stringify([run(false), run(true)]));
"""
    result = subprocess.run(
        ["node", "-e", script],
        input=_SNAPSHOT_JS,
        text=True,
        capture_output=True,
        check=True,
    )
    plain, bound = json.loads(result.stdout)
    assert plain["topic_state"] == "none"
    assert plain["body_plain"] == "正文\n#旅行"
    assert bound["topic_state"] == "bound"
    assert bound["topics"] == ["旅行"]
    assert bound["body_plain"] == "正文"
    assert bound["topic_block_index"] == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 不可用")
def test_restore_script_stops_before_write_when_title_changes():
    from xhs.errors import PublishError

    class CapturePage:
        def __init__(self):
            self.expression = None

        def evaluate_existing_creator(self, expression, tab_id=None):
            if self.expression is None:
                self.expression = expression
                return {
                    "url": "https://creator.xiaohongshu.com/publish/publish",
                    "tab_id": 11,
                    "title_count": 1,
                    "editor_count": 1,
                    "image_area": True,
                    "title": "标题",
                    "body": "第一行",
                    "body_plain": "第一行",
                    "images": 2,
                    "topics": [],
                    "topic_state": "none",
                    "topic_block_index": None,
                }
            self.expression = expression
            return False

    from xhs.publish_form import restore_publish_body

    page = CapturePage()
    with pytest.raises(PublishError, match="页面状态已变化"):
        restore_publish_body(page, "标题", "第一行\n第二行", 2)
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const expression = fs.readFileSync(0, 'utf8');
const editor = {
  getClientRects: () => [1], innerText: '第一行',
  querySelectorAll: () => [], children: [],
};
const title = {getClientRects: () => [1], value: '别的标题'};
let writes = 0;
const document = {
  querySelectorAll: selector => {
    if (selector === 'div.d-input input') return [title];
    if (selector === 'div.ql-editor') return [editor];
    if (selector === '[role="textbox"][contenteditable="true"]') return [];
    if (selector === '.img-preview-area .pr') return [{}, {}];
    return [];
  },
  querySelector: selector => selector === '.img-preview-area' ? {} : null,
  execCommand: () => {writes++; return true;},
};
const result = vm.runInNewContext(expression, {
  document,
  location: {href: 'https://creator.xiaohongshu.com/publish/publish'},
  getComputedStyle: () => ({visibility: 'visible'}),
});
process.stdout.write(JSON.stringify({result, writes}));
"""
    run = subprocess.run(
        ["node", "-e", script],
        input=page.expression,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(run.stdout) == {"result": False, "writes": 0}
