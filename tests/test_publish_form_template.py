"""正文恢复脚本中的合法稿件文字不得被当作模板占位词。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from xhs.errors import PublishError
from xhs.publish_form import restore_publish_body


class CapturePage:
    def __init__(self, title: str, body: str):
        self.title = title
        self.body = body
        self.expression = ""

    def evaluate_existing_creator(self, expression: str, tab_id: int | None = None):
        if not self.expression:
            self.expression = expression
            return {
                "url": "https://creator.xiaohongshu.com/publish/publish",
                "tab_id": 11,
                "title_count": 1,
                "editor_count": 1,
                "image_area": True,
                "title": self.title,
                "body": self.body,
                "body_plain": self.body,
                "images": 1,
                "topics": [],
                "topic_state": "none",
                "topic_block_index": None,
            }
        self.expression = expression
        return False


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 不可用")
@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("SNAPSHOT", "正文"),
        ("EDITOR", "正文"),
        ("标题", "SNAPSHOT"),
        ("标题", "EDITOR"),
        ("SNAPSHOT EDITOR", "正文包含 SNAPSHOT 和 EDITOR"),
        ("$SNAPSHOT", "正文包含 $EDITOR"),
        ("普通标题", "普通正文"),
    ],
)
def test_payload_words_do_not_rewrite_restoration_script(title: str, body: str):
    page = CapturePage(title, body)
    with pytest.raises(PublishError, match="页面状态已变化"):
        restore_publish_body(page, title, body + "\n补充声明", 1)
    result = subprocess.run(
        ["node", "--check", "-"],
        input=page.expression,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert f'"title": {json.dumps(title, ensure_ascii=False)}' in page.expression
    assert f'"body": {json.dumps(body, ensure_ascii=False)}' in page.expression
