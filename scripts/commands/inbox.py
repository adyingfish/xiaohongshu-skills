"""私信读取和本地待办命令；主 CLI 注入连接与输出函数。"""

from __future__ import annotations

from xhs import inbox


def register(subparsers, connect, output) -> None:
    def execute(args):
        browser, page = connect(args)
        try:
            if args.command == "list-inbox":
                result = inbox.list_inbox(page, limit=args.limit, max_scrolls=args.max_scrolls)
            elif args.command == "get-messages":
                result = inbox.get_messages(
                    page,
                    args.user_id,
                    args.expected_name,
                    limit=args.limit,
                    max_scrolls=args.max_scrolls,
                )
            elif args.command == "list-pending-replies":
                result = inbox.list_pending_replies(
                    page,
                    limit=args.limit,
                    max_scrolls=args.max_scrolls,
                    message_limit=args.message_limit,
                    state_file=args.state_file,
                )
            else:
                result = inbox.mark_conversation(
                    page,
                    args.user_id,
                    args.expected_name,
                    message_id=args.message_id,
                    status=args.status,
                    state_file=args.state_file,
                )
            output(result, exit_code=0 if result.get("success") else 2)
        finally:
            browser.close()

    for command, help_text in (
        ("list-inbox", "读取普通文件夹中已加载私信、预览和未读状态（不含群聊/陌生人）"),
        ("get-messages", "读取指定会话历史；打开会话可能自然变为已读"),
        ("list-pending-replies", "逐会话检查最新有效消息，整理待回复清单"),
        ("mark-conversation", "仅对最后有效消息为对方来信的会话设置本地处理标记"),
    ):
        sub = subparsers.add_parser(command, help=help_text)
        if command != "mark-conversation":
            sub.add_argument(
                "--limit",
                type=int,
                default=20 if command == "list-pending-replies" else 100,
                help="最多返回记录数；待回复命令中指最多检查会话数（1–1000）",
            )
            sub.add_argument(
                "--max-scrolls",
                type=int,
                default=3,
                help="最多滚动加载次数（0–50）；未确认到达结尾时 complete=false",
            )
        if command in {"get-messages", "mark-conversation"}:
            sub.add_argument("--user-id", required=True, help="对方 24 位用户 ID")
            sub.add_argument("--expected-name", required=True, help="对方完整昵称，用于交叉核对")
        if command in {"list-pending-replies", "mark-conversation"}:
            sub.add_argument("--state-file", help="本地处理状态 SQLite 文件（不保存消息正文）")
        if command == "list-pending-replies":
            sub.add_argument(
                "--message-limit", type=int, default=100, help="每个会话最多读取消息数（1–1000）"
            )
        if command == "mark-conversation":
            sub.add_argument(
                "--message-id", required=True, help="刚读取的最新入站消息 ID；变化后拒绝标记"
            )
            sub.add_argument("--status", choices=["handled", "pending"], required=True)
        sub.set_defaults(func=execute)
