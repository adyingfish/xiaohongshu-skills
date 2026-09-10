"""将已读取内容导出为本地 JSON/Markdown；默认不覆盖文件，不下载媒体。"""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def _text(value) -> str:
    # 网页正文作为普通文字展示，不让 HTML 或 Markdown 变成可执行内容/远程图片。
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(str(value), quote=False))


def _safe_url(value) -> str | None:
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return value.replace("<", "%3C").replace(">", "%3E")


def _json_block(data) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    longest = max((len(match) for match in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}json\n{text}\n{fence}\n"


def to_markdown(data: dict | list) -> str:
    """笔记使用可阅读版式；其他结构完整放入 JSON 代码块，避免字段丢失。"""
    if not isinstance(data, dict) or not isinstance(data.get("note"), dict):
        return "# 小红书内容导出\n\n" + _json_block(data)
    note = data["note"]
    user = note.get("user") or {}
    lines = [f"# {_text(note.get('title') or '无标题笔记')}", ""]
    lines.append(f"作者：{_text(user.get('nickname', ''))}")
    lines.append(f"笔记 ID：{_text(note.get('noteId', ''))}")
    url = _safe_url(data.get("sourceUrl"))
    if url:
        lines.append(f"来源：<{url}>")
    lines.extend(["", _text(note.get("body") or note.get("desc") or ""), ""])
    tags = note.get("tags") or []
    if tags:
        lines.extend(["话题：" + "、".join(_text(tag) for tag in tags), ""])
    images = note.get("imageList") or []
    if images:
        lines.extend(["## 图片地址", "", "仅记录地址，未下载图片。", ""])
        for index, item in enumerate(images, 1):
            url = _safe_url(item.get("urlDefault") or item.get("urlPre"))
            if url:
                lines.append(f"{index}. <{url}>")
        lines.append("")
    comments = data.get("comments") or []
    if isinstance(comments, dict):
        comments = comments.get("list") or []
    lines.extend(["## 已读取评论", "", "仅包含本次读取的数据，不保证评论及回复齐全。", ""])

    def append_comments(items, depth=0):
        for item in items:
            author = (item.get("user") or item.get("userInfo") or {}).get("nickname", "")
            content = _text(item.get("content", "")).replace("\n", "\n" + "  " * (depth + 1))
            lines.append("  " * depth + f"- {_text(author)}：{content}")
            if item.get("subComments"):
                append_comments(item["subComments"], depth + 1)

    append_comments(comments)
    # 保留互动统计、时间和未知新增字段，Markdown 不以可读摘要替代原始记录。
    lines.extend(["", "## 完整数据", "", _json_block(data)])
    return "\n".join(lines)


def validate_output_path(output_path: str | Path, *, overwrite: bool = False) -> Path:
    path = Path(output_path).expanduser()
    if not path.is_absolute():
        raise ValueError("导出路径必须是绝对路径")
    # 不 resolve 文件本身，防止覆盖选项沿符号链接修改其他文件。
    if path.is_symlink():
        raise ValueError("导出目标不能是符号链接")
    if path.exists():
        if not path.is_file():
            raise ValueError("导出目标不是普通文件")
        if not overwrite:
            raise FileExistsError("导出文件已存在；请换路径或显式指定 --overwrite")
    if not path.parent.is_dir():
        raise ValueError("导出文件的父目录不存在")
    return path


def write_export(
    data: dict | list,
    output_path: str | Path,
    *,
    format: str = "json",
    overwrite: bool = False,
) -> dict:
    if not isinstance(data, dict | list):
        raise ValueError("导出内容必须是 JSON 对象或数组")
    if format not in {"json", "markdown"}:
        raise ValueError("导出格式必须为 json 或 markdown")
    path = validate_output_path(output_path, overwrite=overwrite)
    text = (
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if format == "json" else to_markdown(data)
    )
    # 同目录临时文件完整写入后再发布，避免中断留下半份导出。
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if overwrite:
            validate_output_path(path, overwrite=True)
            os.replace(temporary, path)
        else:
            # link 的独占创建保证其他进程同时生成同名文件时不会被覆盖。
            os.link(temporary, path)
        return {
            "success": True,
            "outputPath": str(path),
            "format": format,
            "bytes": len(text.encode("utf-8")),
            "mediaDownloaded": False,
        }
    finally:
        Path(temporary).unlink(missing_ok=True)
