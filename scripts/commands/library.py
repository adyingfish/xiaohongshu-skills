"""注册个人笔记、收藏与内容库检索命令。"""

from __future__ import annotations

from xhs.library import list_library, search_library


def register(subparsers, connect, output):
    def listing(args):
        browser, page = connect(args)
        try:
            result = list_library(
                page, args.library_scope, limit=args.limit,
                max_pages=args.max_pages, keyword=getattr(args, "keyword", ""),
            )
        finally:
            browser.close()
        output(result)

    def search(args):
        browser, page = connect(args)
        try:
            result = search_library(
                page, args.keyword, scope=args.scope, limit=args.limit, max_pages=args.max_pages,
            )
        finally:
            browser.close()
        output(result)

    def bounds(command):
        command.add_argument("--limit", type=int, default=50, help="每个范围最多读取条数，1–500")
        command.add_argument("--max-pages", type=int, default=3, help="最多读取轮数，1–20")

    for name, scope, help_text in [
        ("list-my-notes", "notes", "读取自己主页的笔记列表，不含草稿或审核状态"),
        ("list-favorites", "favorites", "读取自己收藏的笔记列表"),
        ("list-collections", "collections", "读取网页专辑，不代表 App 全部收藏夹"),
    ]:
        command = subparsers.add_parser(name, help=help_text)
        bounds(command)
        if scope != "collections":
            command.add_argument("--keyword", default="", help="按列表标题和作者筛选")
        command.set_defaults(func=listing, library_scope=scope)
    command = subparsers.add_parser("search-library", help="在自己的笔记和收藏中检索标题、作者")
    bounds(command)
    command.add_argument("--keyword", required=True)
    command.add_argument("--scope", choices=["notes", "favorites", "all"], default="all")
    command.set_defaults(func=search)
