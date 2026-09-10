"""链接及导出命令注册；由 CLI 注入连接与输出函数。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from xhs.export import validate_output_path, write_export
from xhs.links import make_share_url, resolve_link, validate_feed_id


def register(subparsers, connect, output) -> None:
    def share(args):
        output({
            "feedId": args.feed_id,
            "shareUrl": make_share_url(args.feed_id, args.xsec_token),
            "hasToken": bool(args.xsec_token),
            "accessVerified": False,
        })

    def resolve(args):
        output(resolve_link(args.link))

    def export_content(args):
        path = validate_output_path(args.output, overwrite=args.overwrite)
        input_path = Path(args.input).expanduser()
        if not input_path.is_absolute():
            raise ValueError("输入文件必须是绝对路径")
        if input_path.resolve() == path.resolve():
            raise ValueError("输入和导出路径不能相同")
        data = json.loads(input_path.read_text(encoding="utf-8-sig"))
        output(write_export(data, path, format=args.format, overwrite=args.overwrite))

    def export_note(args):
        from xhs.feed_detail import get_feed_detail

        path = validate_output_path(args.output, overwrite=args.overwrite)
        if args.link:
            if args.xsec_token is not None:
                raise ValueError("--link 与 --xsec-token 不能同时使用")
            resolved = resolve_link(args.link)
            feed_id, token = resolved["feedId"], resolved["xsecToken"]
        else:
            feed_id = validate_feed_id(args.feed_id)
            token = args.xsec_token or ""
        if not token:
            raise ValueError("导出笔记需要 xsec_token；请从搜索结果或完整分享链接获取")
        browser, page = connect(args)
        try:
            # 现有 make_feed_detail_url 直接插入令牌；先编码，防止 &/+/? 改写查询参数。
            detail = get_feed_detail(page, feed_id, quote(token, safe=""))
            if detail.note.note_id != feed_id:
                raise ValueError("实际读取的笔记 ID 与目标不一致，未生成导出文件")
            data = detail.to_dict()
            data.update(
                sourceUrl=make_share_url(feed_id, token),
                exportedAt=datetime.now(UTC).isoformat(),
                coverage={
                    "comments": "loaded_only",
                    "commentsComplete": False,
                    "hasMoreComments": detail.comments.has_more,
                    "mediaDownloaded": False,
                },
            )
            result = write_export(data, path, format=args.format, overwrite=args.overwrite)
            result.update(feedId=feed_id, coverage=data["coverage"])
        finally:
            browser.close()
        output(result)

    command = subparsers.add_parser("get-share-url", help="生成笔记分享地址（不验证访问权限）")
    command.add_argument("--feed-id", required=True)
    command.add_argument("--xsec-token", default="")
    command.set_defaults(func=share)

    command = subparsers.add_parser("resolve-link", help="解析笔记长链接或 xhslink 短链接")
    command.add_argument("--link", required=True, help="单条链接或包含一条链接的分享文案")
    command.set_defaults(func=resolve)

    def export_options(command: argparse.ArgumentParser):
        command.add_argument("--output", required=True, help="导出文件的绝对路径")
        command.add_argument("--format", choices=["json", "markdown"], default="json")
        command.add_argument("--overwrite", action="store_true", help="允许替换已有普通文件")

    command = subparsers.add_parser(
        "export-content", help="将本地 JSON 内容导出为 JSON 或 Markdown",
    )
    command.add_argument("--input", required=True, help="已有 JSON 文件的绝对路径")
    export_options(command)
    command.set_defaults(func=export_content)

    command = subparsers.add_parser(
        "export-note", help="读取笔记并导出正文和已加载评论，不下载媒体",
    )
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--link", help="笔记链接或分享文案")
    source.add_argument("--feed-id", help="笔记 ID")
    command.add_argument("--xsec-token", help="与 --feed-id 搭配使用")
    export_options(command)
    command.set_defaults(func=export_note)
