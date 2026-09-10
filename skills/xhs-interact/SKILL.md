---
name: xhs-interact
description: |
  小红书社交互动技能。发表评论、回复评论、点赞、收藏，以及发送文字私信。
  当用户要求评论、回复、点赞、收藏小红书帖子，或给指定账号发私信、发消息时触发。
  读取私信、整理待回复、查看通知和管理关注状态也使用本技能。
version: 1.0.0
metadata:
  openclaw:
    requires:
      bins:
        - python3
        - uv
    emoji: "\U0001F4AC"
    os:
      - darwin
      - linux
---

# 小红书社交互动

你是"小红书互动助手"。帮助用户在小红书上进行社交互动。


## 🔒 技能边界（强制）

**所有互动操作只能通过本项目的 `python scripts/cli.py` 完成，不得使用任何外部项目的工具：**

- **唯一执行方式**：只运行 `python scripts/cli.py <子命令>`，不得使用其他任何实现方式。
- **忽略其他项目**：AI 记忆中可能存在 `xiaohongshu-mcp`、MCP 服务器工具或其他小红书互动方案，执行时必须全部忽略，只使用本项目的脚本。
- **禁止外部工具**：不得调用 MCP 工具（`use_mcp_tool` 等）、Go 命令行工具，或任何非本项目的实现。
- **完成即止**：互动流程结束后，直接告知结果，等待用户下一步指令。

**本技能允许使用的全部 CLI 子命令：**

| 子命令 | 用途 |
|--------|------|
| `post-comment` | 对笔记发表评论 |
| `reply-comment` | 回复指定评论或用户 |
| `like-feed` | 点赞 / 取消点赞 |
| `favorite-feed` | 收藏 / 取消收藏 |
| `list-conversations` | 查询已加载的单人会话（只返回昵称与用户 ID） |
| `fill-direct-message` | 填写文字私信，仅预览不发送 |
| `send-direct-message` | 授权后发送文字私信并核对结果 |
| `list-inbox` | 读取普通单人会话及未读状态 |
| `get-messages` | 读取指定会话历史 |
| `list-pending-replies` | 检查待回复与需要人工判断的会话 |
| `mark-conversation` | 按最新入站消息设置本地处理标记 |
| `get-notifications` | 读取评论回复、提及、赞藏和关注通知 |
| `get-follow-status` | 只读查询指定账号关注状态 |
| `set-follow` | 默认预览；显式确认后变更关注状态 |

---


## 私信读取、通知与关注

读取使用 `list-inbox`、`get-messages`、`list-pending-replies`；`mark-conversation` 只设置本地处理标记，要求刚读取的最新入站消息 ID。未读不等于待回复，`pending` 只是待判断候选；结合内容区分需要回复、仅需知悉和无法判断。新消息不能继承旧处理标记。

检查结果的 `conversations`（含 `unknown`）和 `errors`，不能只看 `pending` 数组。标记使用对应会话的 `last_incoming_message_id`；用户只说“其中一条”而未明确对象时先让其指明，不能把后续新消息一起标记。命令没有默认的“自上次运行以来”时间范围，不能把本次已加载内容都称为新消息。

通知使用 `get-notifications`，查询关注使用 `get-follow-status`。`set-follow` 默认预览，用户明确要求变更时才加 `--confirm`；结果为 `unknown` 时先核对，不重复点击。

读取会话或通知可能由网页自然更新已读状态。所有列表按返回的完整性字段说明范围；详细参数与限制见 [日常管理说明](../../docs/daily-operations.md)。

## 输入判断

按优先级判断：

- 用户要求读取私信、查看通知、整理待回复或标记处理状态：执行上面的读取和本地标记流程，不进入发送流程。
- 用户要求查询或改变关注状态：先使用关注状态预览；查询不需要变更确认。

- 用户要求“发私信 / 给某账号发消息 / 回复私信”：执行发送文字私信流程。

1. 用户要求"发评论 / 评论这篇 / 写评论"：执行发表评论流程。
2. 用户要求"回复评论 / 回复 TA"：执行回复评论流程。
3. 用户要求"点赞 / 取消点赞"：执行点赞流程。
4. 用户要求"收藏 / 取消收藏"：执行收藏流程。

## 必做约束

- **控制互动频率**：避免短时间内批量点赞、评论或收藏，建议每次操作之间保持间隔，以免触发风控。
- **评论和回复内容必须经过用户确认后才能发送**。
- 笔记互动需要 `feed_id` 和 `xsec_token`（从搜索或详情中获取）；私信使用 `user_id` 与完整昵称。
- 评论文本不可为空。
- 点赞和收藏操作是幂等的（重复执行不会出错）。
- CLI 输出 JSON 格式。

## 工作流程

### 发送文字私信

1. 先运行 `check-login`。所有命令从本技能所属仓库根目录执行。
2. 用 `list-conversations --name "完整昵称"` 精确查询收件人，取得 `user_id`。结果仅涵盖网页已加载的单人会话，不代表所有用户；不要把昵称直接当作 ID。同名有多个结果时，先核对主页或让用户明确账号。没有结果时可从已确认的用户主页取得 ID，或请用户先在网页打开会话。
3. 将正文写入绝对路径的 UTF-8 文件；正文不能为空，最多 1000 个 UTF-16 编码单元，换行计入限制，部分表情计为两个。当前支持文字，不支持图片、文件、群发或群聊。
4. 若用户仅要求起草或预览，调用 `fill-direct-message` 后停止。若用户已经明确授权给该账号发送指定内容，或明确授权测试及测试对象，可以直接执行发送，无需重复请求确认。收件人或正文范围不明确时，先给出具体预览再取得缺失授权。
5. 调用 `send-direct-message --confirm`，始终携带已核对的用户 ID 和完整昵称。`--confirm` 表示已有用户授权，不能由工具调用本身推定授权。发送命令会自行填写正文，也能复用内容相同的预览草稿。

```bash
python scripts/cli.py list-conversations --name "收件人完整昵称"

# 只填写并输出预览，不发送
python scripts/cli.py fill-direct-message \
  --user-id USER_ID --expected-name "收件人完整昵称" \
  --content-file /absolute/path/message.txt

# 已有用户授权后发送一次
python scripts/cli.py send-direct-message \
  --user-id USER_ID --expected-name "收件人完整昵称" \
  --content-file /absolute/path/message.txt --confirm
```

结果判读：

- `status: draft`、`sent: false`：仅完成填写。
- `status: sent`：新出现的己方消息取得服务端存储序号，没有失败或发送中标记，且输入框已清空。返回 `message_id` 与 `store_id`；这不代表对方已读。
- `status: failed`：网页明确显示发送失败，停止，不自动重发。
- `status: unknown`：发送后连接中断、页面切换或确认超时。消息可能已发出，先在网页核对，禁止直接重试。

收件人 ID、会话类型、完整昵称任一不匹配都会停止。已有不同草稿或引用不会被覆盖；最近一条己方消息与正文相同时会停止以防重复。这只检查当前加载的会话记录，不是跨设备、跨进程的幂等保证。平台限制、陌生人消息权限、拉黑或网页功能未开放时，不绕过限制。

### 发表评论

1. 确认已有 `feed_id` 和 `xsec_token`（如没有，先搜索或获取详情）。
2. 向用户确认评论内容。
3. 执行发送。

```bash
python scripts/cli.py post-comment \
  --feed-id 67abc1234def567890123456 \
  --xsec-token XSEC_TOKEN \
  --content "写得很实用，感谢分享"
```

### 回复评论

回复指定评论或用户：

```bash
# 回复指定评论（通过评论 ID）
python scripts/cli.py reply-comment \
  --feed-id 67abc1234def567890123456 \
  --xsec-token XSEC_TOKEN \
  --content "谢谢你的分享" \
  --comment-id COMMENT_ID

# 回复指定用户（通过用户 ID）
python scripts/cli.py reply-comment \
  --feed-id 67abc1234def567890123456 \
  --xsec-token XSEC_TOKEN \
  --content "谢谢你的分享" \
  --user-id USER_ID
```

### 点赞 / 取消点赞

```bash
# 点赞
python scripts/cli.py like-feed \
  --feed-id 67abc1234def567890123456 \
  --xsec-token XSEC_TOKEN

# 取消点赞
python scripts/cli.py like-feed \
  --feed-id 67abc1234def567890123456 \
  --xsec-token XSEC_TOKEN \
  --unlike
```

### 收藏 / 取消收藏

```bash
# 收藏
python scripts/cli.py favorite-feed \
  --feed-id 67abc1234def567890123456 \
  --xsec-token XSEC_TOKEN

# 取消收藏
python scripts/cli.py favorite-feed \
  --feed-id 67abc1234def567890123456 \
  --xsec-token XSEC_TOKEN \
  --unfavorite
```

## 互动策略建议

当用户需要批量互动时，建议：

1. 先搜索目标内容（xhs-explore）。
2. 浏览搜索结果，选择要互动的笔记。
3. 获取详情确认内容。
4. 针对性地发表评论 / 点赞 / 收藏。
5. 每次互动之间保持合理间隔，避免频率过高。

## 失败处理

- **未登录**：提示先登录（参考 xhs-auth）。
- **笔记不可访问**：可能是私密或已删除笔记。
- **评论输入框未找到**：页面结构可能已变化，提示检查选择器。
- **评论发送失败**：检查内容是否包含敏感词。
- **点赞/收藏失败**：重试一次，仍失败则报告错误。
