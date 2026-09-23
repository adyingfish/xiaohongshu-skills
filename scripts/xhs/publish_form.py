"""图文创作页的只读快照、分项回读和保守的正文末尾恢复。"""

from __future__ import annotations

import json
from string import Template
from urllib.parse import urlparse

from .errors import PublishError
from .publish import _extract_hashtags_from_content
from .selectors import CONTENT_EDITOR, IMAGE_PREVIEW, TITLE_INPUT

# 只有带稳定话题标识的节点才算已绑定；纯文本 #话题 从不算绑定。
_TOPIC_SELECTOR = '[data-topic-id],.mention[data-id][data-denotation-char="#"]'
_SNAPSHOT_JS = (
    """(() => {
    const visible = el => !!el.getClientRects().length &&
        getComputedStyle(el).visibility !== 'hidden';
    const titles = [...document.querySelectorAll(TITLE)].filter(visible);
    const editors = [...new Set([
        ...document.querySelectorAll(EDITOR),
        ...document.querySelectorAll('[role="textbox"][contenteditable="true"]')
    ])].filter(visible);
    const el = editors.length === 1 ? editors[0] : null;
    const result = {
        url: location.href,
        title_count: titles.length,
        editor_count: editors.length,
        image_area: !!document.querySelector('.img-preview-area'),
        title: titles.length === 1 ? titles[0].value : null,
        body: el ? el.innerText : null,
        body_plain: el ? el.innerText : null,
        images: document.querySelectorAll(IMAGES).length,
        topics: [],
        topic_state: 'none',
        topic_block_index: null
    };
    if (!el) return result;
    const markers = [...el.querySelectorAll(TOPICS)];
    if (!markers.length) return result;
    const blocks = [...el.children];
    const bodyBlocks = [];
    const topics = [];
    let firstTopic = null;
    let valid = blocks.length > 0;
    for (let i = 0; i < blocks.length; i++) {
        const block = blocks[i];
        if (!block.matches('p,div')) { valid = false; break; }
        const found = [...block.querySelectorAll(TOPICS)];
        if (!found.length) {
            if (firstTopic !== null && block.innerText.trim()) valid = false;
            if (firstTopic === null) bodyBlocks.push(block.innerText);
            continue;
        }
        if (firstTopic === null) firstTopic = i;
        const copy = block.cloneNode(true);
        copy.querySelectorAll(TOPICS).forEach(node => node.remove());
        if (copy.textContent.trim()) valid = false;
        for (const node of found) {
            const id = node.getAttribute('data-topic-id') || node.getAttribute('data-id');
            const name = (node.getAttribute('data-value') || node.textContent || '')
                .trim().replace(/^#/, '').trim();
            if (!id || !name) valid = false;
            topics.push(name);
        }
    }
    if (valid && topics.length === markers.length && firstTopic > 0 &&
        bodyBlocks[bodyBlocks.length - 1].trim()) {
        result.body_plain = bodyBlocks.join('\\n');
        result.topics = topics;
        result.topic_state = 'bound';
        result.topic_block_index = firstTopic;
    } else {
        result.body_plain = null;
        result.topic_state = 'unknown';
    }
    return result;
})()""".replace("TITLE", json.dumps(TITLE_INPUT))
    .replace("EDITOR", json.dumps(CONTENT_EDITOR))
    .replace("IMAGES", json.dumps(IMAGE_PREVIEW))
    .replace("TOPICS", json.dumps(_TOPIC_SELECTOR))
)


def _lines(value: str) -> list[str]:
    """只规范化换行和不换行空格；保留正文每行的缩进与尾随空格。"""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


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
        raise PublishError("当前活动页不是小红书图文创作页；未发布")
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
    state = raw.get("topic_state")
    if state not in {"none", "bound", "unknown"}:
        raise PublishError("话题结构状态不可读；未发布")
    plain = raw.get("body_plain")
    topics = raw.get("topics")
    if state != "unknown" and not isinstance(plain, str):
        raise PublishError("普通正文不可读；未发布")
    if not isinstance(topics, list) or not all(isinstance(x, str) for x in topics):
        raise PublishError("话题结构不可读；未发布")
    topic_index = raw.get("topic_block_index")
    if state == "bound" and (not topics or type(topic_index) is not int or topic_index < 1):
        raise PublishError("话题段落位置不可读；未发布")
    if state == "none" and (topics or topic_index is not None):
        raise PublishError("话题状态不一致；未发布")
    tab_id = raw.get("tab_id")
    if tab_id is not None and (type(tab_id) is not int or tab_id < 0):
        raise PublishError("创作页标签 ID 不可读；未发布")
    return {
        "url": url,
        "tab_id": tab_id,
        "title": raw["title"],
        "body": raw["body"],
        "body_plain": plain,
        "images": images,
        "topics": topics,
        "topic_state": state,
        "topic_block_index": raw.get("topic_block_index"),
    }


def _evaluate_creator(page, expression: str, tab_id: int | None = None):
    if hasattr(page, "evaluate_existing_creator"):
        return page.evaluate_existing_creator(expression, tab_id)
    return page.evaluate(expression)


def inspect_publish_form(page, tab_id: int | None = None) -> dict:
    """只读取活动或显式指定的图文编辑页。"""
    snapshot = _validate_snapshot(_evaluate_creator(page, _SNAPSHOT_JS, tab_id))
    if tab_id is not None and snapshot["tab_id"] != tab_id:
        raise PublishError("读取结果不属于指定创作页标签；未发布")
    return snapshot


def _expected_parts(content: str, tags: list[str]) -> tuple[list[str], list[str]]:
    body, topics = _extract_hashtags_from_content(content, tags)
    return _lines(body), topics


def verify_publish_form(
    snapshot: dict, title: str, content: str, images: int, tags: list[str] | None = None
) -> dict:
    """区分文本一致、话题绑定和未知状态，不把 #文本当成已选话题。"""
    expected_body, expected_topics = _expected_parts(content, tags or [])
    body = snapshot.get("body_plain")
    topic_state = snapshot["topic_state"]
    if topic_state == "unknown" or (expected_topics and topic_state == "none"):
        # 未识别的 #文本可能是普通正文，也可能是另一种话题节点；不能判为核对通过。
        body_verified = None
        topics_verified = None
    else:
        body_verified = _lines(body) == expected_body if isinstance(body, str) else None
        topics_verified = (
            snapshot["topics"] == expected_topics if topic_state == "bound" else not expected_topics
        )
    checks = {
        "title": snapshot["title"] == title,
        "images": snapshot["images"] == images,
        "body": body_verified,
        "topics": topics_verified,
    }
    status = (
        "mismatch"
        if False in checks.values()
        else "unverified"
        if None in checks.values()
        else "verified"
    )
    return {
        "status": status,
        "verified": status == "verified",
        "checks": checks,
        "actual_images": snapshot["images"],
        "expected_images": images,
        "actual_body_lines": len(_lines(body)) if isinstance(body, str) else None,
        "expected_body_lines": len(expected_body),
        "expected_topics": expected_topics,
        "observed_topics": snapshot["topics"],
        "topic_state": snapshot["topic_state"],
    }


def _missing_suffix(actual: str, expected: list[str]) -> list[str]:
    actual_lines = _lines(actual)
    if actual_lines == expected:
        return []
    if not actual_lines or len(actual_lines) >= len(expected):
        raise PublishError("正文并非无歧义的末尾缺失；未修改草稿")
    if actual_lines != expected[: len(actual_lines)]:
        raise PublishError("正文存在中间缺失、重复、空白或顺序差异；未修改草稿")
    suffix = expected[len(actual_lines) :]
    nonempty = [line for line in expected if line]
    if len(set(nonempty)) != len(nonempty):
        raise PublishError("正文含重复行，末尾缺失存在歧义；未修改草稿")
    if any(not line for line in suffix):
        raise PublishError("缺失片段含空行，需人工核对；未修改草稿")
    return suffix


def restore_publish_body(
    page,
    title: str,
    content: str,
    images: int,
    tags: list[str] | None = None,
    tab_id: int | None = None,
) -> dict:
    """锁定目标页，仅补齐已核对的普通正文末尾，保留已绑定话题。"""
    if images < 1:
        raise PublishError("恢复正文须提供正数图片数量；未修改草稿")
    expected_body, expected_topics = _expected_parts(content, tags or [])
    before = inspect_publish_form(page, tab_id)
    if hasattr(page, "evaluate_existing_creator") and before["tab_id"] is None:
        raise PublishError("无法锁定创作页标签；未修改草稿")
    if before["title"] != title or before["images"] != images:
        raise PublishError("当前稿件标题或图片预览数不匹配；未修改草稿")
    if expected_topics:
        if before["topic_state"] != "bound" or before["topics"] != expected_topics:
            raise PublishError("预期话题未能按顺序确认为已绑定节点；未修改草稿")
    elif before["topic_state"] != "none":
        raise PublishError("页面存在未预期或不可识别的话题节点；未修改草稿")
    plain = before["body_plain"]
    if not isinstance(plain, str):
        raise PublishError("无法区分普通正文与话题；未修改草稿")
    missing = _missing_suffix(plain, expected_body)
    if not missing:
        result = verify_publish_form(before, title, content, images, tags)
        if not result["verified"]:
            raise PublishError("当前稿件未通过回读；未修改草稿")
        return {"restored": [], "verification": result, "images": images}
    payload = json.dumps(
        {
            "url": before["url"],
            "title": title,
            "body": before["body"],
            "body_plain": plain,
            "images": images,
            "topics": before["topics"],
            "topic_state": before["topic_state"],
            "topic_block_index": before["topic_block_index"],
            "suffix": missing,
        },
        ensure_ascii=False,
    )
    expression = Template(
        """(() => {
        const wanted = $PAYLOAD;
        const current = $SNAPSHOT;
        if (current.url !== wanted.url || current.title !== wanted.title ||
            current.body !== wanted.body || current.body_plain !== wanted.body_plain ||
            current.images !== wanted.images ||
            current.topic_state !== wanted.topic_state ||
            current.topic_block_index !== wanted.topic_block_index ||
            JSON.stringify(current.topics) !== JSON.stringify(wanted.topics)) return false;
        const el = [...new Set([
            ...document.querySelectorAll($EDITOR),
            ...document.querySelectorAll('[role="textbox"][contenteditable="true"]')
        ])].filter(node => !!node.getClientRects().length &&
            getComputedStyle(node).visibility !== 'hidden')[0];
        if (!el) return false;
        let target = el;
        if (wanted.topic_state === 'bound') {
            const index = wanted.topic_block_index;
            if (!Number.isInteger(index) || index < 1) return false;
            target = el.children[index - 1];
            if (!target || !target.matches('p,div')) return false;
        }
        target.focus?.();
        el.focus();
        const range = document.createRange();
        range.selectNodeContents(target);
        range.collapse(false);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        for (const line of wanted.suffix) {
            if (!document.execCommand('insertParagraph', false, null)) return false;
            if (!document.execCommand('insertText', false, line)) return false;
        }
        return true;
    })()"""
    ).substitute(
        PAYLOAD=payload,
        SNAPSHOT=_SNAPSHOT_JS,
        EDITOR=json.dumps(CONTENT_EDITOR),
    )
    try:
        write_result = _evaluate_creator(page, expression, before["tab_id"])
    except Exception as error:
        raise PublishError(
            "正文恢复结果未知，可能已部分写入；先只读检查草稿，勿自动重试，未发布"
        ) from error
    if write_result is not True:
        raise PublishError("页面状态已变化或编辑器拒绝输入，可能已部分写入；先只读检查草稿，未发布")
    try:
        after = inspect_publish_form(page, before["tab_id"])
    except Exception as error:
        raise PublishError(
            "正文已尝试恢复但回读失败；先只读检查草稿，勿自动重试，未发布"
        ) from error
    result = verify_publish_form(after, title, content, images, tags)
    if not result["verified"]:
        raise PublishError("正文恢复后回读未通过；请只读检查草稿，勿自动重填或重试，未发布")
    return {"restored": missing, "verification": result, "images": images}
