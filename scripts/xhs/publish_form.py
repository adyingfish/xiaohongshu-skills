"""图文编辑页快照、填写回读和保守的正文末尾恢复。"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from .errors import PublishError
from .publish import _extract_hashtags_from_content
from .selectors import CONTENT_EDITOR, IMAGE_PREVIEW, TITLE_INPUT

_SNAPSHOT_JS = (
    """(() => {
    const visible = el => !!el.getClientRects().length &&
        getComputedStyle(el).visibility !== 'hidden';
    const title = [...document.querySelectorAll(TITLE)].filter(visible);
    const editors = [...new Set([
        ...document.querySelectorAll(EDITOR),
        ...document.querySelectorAll('[role="textbox"][contenteditable="true"]')
    ])].filter(visible);
    return {
        url: location.href,
        title_count: title.length,
        editor_count: editors.length,
        image_area: !!document.querySelector('.img-preview-area'),
        title: title.length === 1 ? title[0].value : null,
        body: editors.length === 1 ? editors[0].innerText : null,
        images: document.querySelectorAll(IMAGES).length
    };
})()""".replace("TITLE", json.dumps(TITLE_INPUT))
    .replace("EDITOR", json.dumps(CONTENT_EDITOR))
    .replace("IMAGES", json.dumps(IMAGE_PREVIEW))
)


def _lines(value: str) -> list[str]:
    """规范化编辑器换行，保留正文内部的空行。"""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return [line.strip() for line in lines]


def _validate_snapshot(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise PublishError("无法读取图文编辑页快照；未发布")
    url = str(raw.get("url", ""))
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "creator.xiaohongshu.com"
        or parsed.path != "/publish/publish"
    ):
        raise PublishError("当前页面不是小红书图文创作页；未发布")
    if (
        raw.get("title_count") != 1
        or raw.get("editor_count") != 1
        or raw.get("image_area") is not True
    ):
        raise PublishError("图文编辑页的标题、正文编辑器或图片区域缺失或不唯一；未发布")
    if not isinstance(raw.get("title"), str) or not isinstance(raw.get("body"), str):
        raise PublishError("图文编辑页字段不可读；未发布")
    images = raw.get("images")
    if type(images) is not int or images < 0:
        raise PublishError("无法读取图片预览数量；未发布")
    return {"url": url, "title": raw["title"], "body": raw["body"], "images": images}


def _evaluate_creator(page, expression: str):
    evaluate = getattr(page, "evaluate_existing_creator", page.evaluate)
    return evaluate(expression)


def inspect_publish_form(page) -> dict:
    """只读取当前图文编辑页的稿件字段。"""
    return _validate_snapshot(_evaluate_creator(page, _SNAPSHOT_JS))


def _expected_parts(content: str, tags: list[str]) -> tuple[list[str], list[str]]:
    body, topics = _extract_hashtags_from_content(content, tags)
    return _lines(body), topics


def _body_matches(actual: str, expected: list[str], topics: list[str]) -> bool:
    lines = _lines(actual)
    if not topics:
        return lines == expected
    if lines[: len(expected)] != expected:
        return False
    tail = " ".join(lines[len(expected) :]).strip()
    # 话题选择器可能将多个话题放在同一段，顺序应与输入一致。
    return tail.split() == [f"#{tag}" for tag in topics]


def verify_publish_form(
    snapshot: dict, title: str, content: str, images: int, tags: list[str] | None = None
) -> dict:
    expected_body, topics = _expected_parts(content, tags or [])
    checks = {
        "title": snapshot["title"] == title,
        "images": snapshot["images"] == images,
        "body": _body_matches(snapshot["body"], expected_body, topics),
    }
    result = {
        "verified": all(checks.values()),
        "checks": checks,
        "actual_images": snapshot["images"],
        "expected_images": images,
        "actual_body_lines": len(_lines(snapshot["body"])),
        "expected_body_lines": len(expected_body),
        "topics": topics,
    }
    if not result["verified"]:
        failed = "、".join(k for k, ok in checks.items() if not ok)
        raise PublishError(f"图文表单回读不匹配（{failed}）；未发布。核对结果: {result}")
    return result


def _missing_suffix(actual: str, expected: list[str]) -> list[str]:
    actual_lines = _lines(actual)
    if actual_lines == expected:
        return []
    if not actual_lines or len(actual_lines) >= len(expected):
        raise PublishError("正文并非无歧义的末尾缺失；未修改草稿")
    if actual_lines != expected[: len(actual_lines)]:
        raise PublishError("正文存在中间缺失、重复或顺序差异；未修改草稿")
    suffix = expected[len(actual_lines) :]
    if len(set(line for line in expected if line)) != len([line for line in expected if line]):
        raise PublishError("正文含重复行，末尾缺失存在歧义；未修改草稿")
    if any(not line for line in suffix):
        raise PublishError("缺失片段含空行，需人工核对；未修改草稿")
    return suffix


def restore_publish_body(page, title: str, content: str, images: int) -> dict:
    """只在标题、图数、正文前缀完全匹配时补齐连续缺失的末尾。"""
    if images < 1:
        raise PublishError("恢复正文须提供正数图片数量；未修改草稿")
    expected, topics = _expected_parts(content, [])
    if topics:
        raise PublishError("正文含由话题选择器处理的末尾话题；未修改草稿")
    before = inspect_publish_form(page)
    if before["title"] != title or before["images"] != images:
        raise PublishError("当前稿件标题或图片预览数不匹配；未修改草稿")
    missing = _missing_suffix(before["body"], expected)
    if not missing:
        return {"restored": [], "verified": True, "images": images}
    # 写入前在同一次页面调用中重验身份与原正文，避免两次读取间切换页面。
    payload = json.dumps(
        {
            "url": before["url"],
            "title": title,
            "body": before["body"],
            "images": images,
            "suffix": missing,
        },
        ensure_ascii=False,
    )
    expression = (
        """(() => {
        const wanted = PAYLOAD;
        const visible = el => !!el.getClientRects().length &&
            getComputedStyle(el).visibility !== 'hidden';
        const titles = [...document.querySelectorAll(TITLE)].filter(visible);
        const editors = [...new Set([
            ...document.querySelectorAll(EDITOR),
            ...document.querySelectorAll('[role="textbox"][contenteditable="true"]')
        ])].filter(visible);
        if (location.href !== wanted.url || titles.length !== 1 ||
            titles[0].value !== wanted.title || editors.length !== 1 ||
            !document.querySelector('.img-preview-area') ||
            document.querySelectorAll(IMAGES).length !== wanted.images ||
            editors[0].innerText !== wanted.body) return false;
        const el = editors[0];
        el.focus();
        const range = document.createRange();
        range.selectNodeContents(el);
        range.collapse(false);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        for (const line of wanted.suffix) {
            if (!document.execCommand('insertParagraph', false, null)) return false;
            if (!document.execCommand('insertText', false, line)) return false;
        }
        return true;
    })()""".replace("PAYLOAD", payload)
        .replace("TITLE", json.dumps(TITLE_INPUT))
        .replace("EDITOR", json.dumps(CONTENT_EDITOR))
        .replace("IMAGES", json.dumps(IMAGE_PREVIEW))
    )
    if _evaluate_creator(page, expression) is not True:
        raise PublishError("页面在恢复前发生变化或编辑器拒绝输入；请重新检查草稿，未发布")
    after = inspect_publish_form(page)
    verify_publish_form(after, title, content, images)
    return {"restored": missing, "verified": True, "images": images}
