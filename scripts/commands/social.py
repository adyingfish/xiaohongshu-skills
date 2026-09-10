"""通知和关注关系命令注册。"""

from __future__ import annotations


def register(subparsers, connect, output) -> None:
    def notifications(args):
        from xhs.notifications import get_notifications

        browser, page = connect(args)
        try:
            output(get_notifications(page, args.kind, limit=args.limit, max_pages=args.max_pages))
        finally:
            browser.close()

    def follow(args):
        from xhs.relationships import set_follow

        browser, page = connect(args)
        try:
            result = set_follow(page, args.user_id, args.expected_name,
                                getattr(args, "state", "followed"),
                                xsec_token=args.xsec_token,
                                confirmed=getattr(args, "confirm", False))
            if args.command == "get-follow-status":
                result = {"success": True, "user_id": result["user_id"],
                          "nickname": result["nickname"], "state": result["current_state"]}
            output(result, exit_code=0 if result.get("success") else 2)
        finally:
            browser.close()

    sub = subparsers.add_parser("get-notifications", help="读取评论、回复、提及、赞藏和关注通知")
    sub.add_argument("--kind", choices=["comments", "mentions", "likes", "follows", "all"],
                     default="all")
    sub.add_argument("--limit", type=int, default=100, help="最多输出条数，1–500")
    sub.add_argument("--max-pages", type=int, default=3, help="每组最多加载批数，1–20")
    sub.set_defaults(func=notifications)

    sub = subparsers.add_parser("set-follow", help="预览关注状态；加 --confirm 才执行一次变更")
    sub.add_argument("--user-id", required=True)
    sub.add_argument("--expected-name", required=True, help="目标用户的完整昵称")
    sub.add_argument("--state", choices=["followed", "not-followed"], required=True)
    sub.add_argument("--xsec-token", default="")
    sub.add_argument("--confirm", action="store_true")
    sub.set_defaults(func=follow)

    sub = subparsers.add_parser("get-follow-status", help="只读查询指定用户的关注状态")
    sub.add_argument("--user-id", required=True)
    sub.add_argument("--expected-name", required=True, help="目标用户的完整昵称")
    sub.add_argument("--xsec-token", default="")
    sub.set_defaults(func=follow)
