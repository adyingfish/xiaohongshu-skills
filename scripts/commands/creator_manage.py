"""创作后台笔记与本地草稿命令注册。"""

from __future__ import annotations


def register(subparsers, connect, output) -> None:
    def run(args):
        from xhs import creator_manage as creator

        browser, page = connect(args)
        try:
            if args.command == "get-note-status":
                result = creator.get_note_status(page, args.note_id, max_pages=args.max_pages)
            elif args.command == "open-draft":
                result = creator.open_draft(page, args.draft_id, args.expected_title, args.kind,
                                            open_editor=args.open, max_pages=args.max_pages)
            else:
                kwargs = {"keyword": args.keyword, "limit": args.limit,
                          "max_pages": args.max_pages}
                if args.command == "list-managed-notes":
                    result = creator.list_managed_notes(page, status=args.status, **kwargs)
                else:
                    result = creator.list_drafts(page, kind=args.kind, **kwargs)
            output(result, exit_code=0 if result.get("success") else 2)
        finally:
            browser.close()

    for command, help_ in [("list-managed-notes", "读取自己的后台笔记与状态"),
                           ("list-drafts", "读取当前浏览器本地草稿列表")]:
        sub = subparsers.add_parser(command, help=help_)
        sub.add_argument("--keyword", default="")
        sub.add_argument("--limit", type=int, default=100)
        sub.add_argument("--max-pages", type=int, default=3)
        if command == "list-managed-notes":
            sub.add_argument("--status", choices=["all", "published", "reviewing", "rejected"],
                             default="all")
        else:
            sub.add_argument("--kind", choices=["all", "image", "video", "long", "audio"],
                             default="all")
        sub.set_defaults(func=run)

    sub = subparsers.add_parser("get-note-status", help="查询自己的指定笔记状态")
    sub.add_argument("--note-id", required=True)
    sub.add_argument("--max-pages", type=int, default=3)
    sub.set_defaults(func=run)

    sub = subparsers.add_parser("open-draft", help="预览指定草稿；--open 才打开编辑，不保存或发布")
    sub.add_argument("--draft-id", required=True)
    sub.add_argument("--expected-title", required=True)
    sub.add_argument("--kind", choices=["image", "video", "long", "audio"], required=True)
    sub.add_argument("--open", action="store_true")
    sub.add_argument("--max-pages", type=int, default=3)
    sub.set_defaults(func=run)
