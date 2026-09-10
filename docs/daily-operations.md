# 日常使用与运营管理

本次扩展围绕六项需求提供可独立调用的命令。所有命令均从 `python scripts/cli.py` 运行；离线生成链接、解析长链接、导出已有 JSON 不连接浏览器。页面读取沿用 XHS Bridge。

## 1. 私信读取与待回复管理

目标：知道谁发了什么、哪些会话可能需要回复，以及哪些已由自己处理。

```bash
python scripts/cli.py list-inbox --limit 100 --max-scrolls 3
python scripts/cli.py get-messages --user-id USER_ID --expected-name '完整昵称' --limit 100
python scripts/cli.py list-pending-replies --limit 20 --message-limit 100 --max-scrolls 3
python scripts/cli.py mark-conversation --user-id USER_ID --expected-name '完整昵称' \
  --message-id LAST_INCOMING_MESSAGE_ID --status handled
```

- 读取单人会话、未读数、最后消息时间和历史消息，保留收发方向及图片等内容信息。群聊和陌生人文件夹不在本次范围。
- “未读”是网页状态；“待回复”依据已读取的有效消息和本地处理标记判断。不能把二者等同。`pending` 是候选，是否需要回复仍要结合内容判断；如一句“谢谢”可能只需知悉。
- `list-pending-replies` 的 `pending` 是候选子集，`conversations` 保留已检查会话及 `pending/replied/handled/empty/unknown` 状态，`errors` 记录失败。不要丢弃未知项；处理标记使用会话中的 `last_incoming_message_id`。
- 没有默认的“上次运行以来”增量边界。用户说“其中一条已处理”时，先明确具体会话及处理到哪条消息，不将其后新消息一并标记。
- 本地处理标记绑定当前账号、会话及最新入站消息 ID；新消息到来后不继承旧的“已处理”。使用 `--status pending` 可恢复待处理标记。
- 状态库只保存处理标记，不保存消息正文。需要改变位置时传绝对路径 `--state-file`。
- 网页未提供会话列表的完整结束标志，所以会话清单明确是已加载范围。单个会话历史能取得 `hasMoreHistory` 时据此判断是否完整。
- 疑似“相互关注，开始聊天”的欢迎文字保留不确定标记；无法确定发送者或内容性质时，不自动认定需要回复。
- 打开会话可能由网页自然标记已读；命令不会额外发送已读请求、回复或清空草稿。发送仍使用已有的独立私信命令及授权流程。

## 2. 评论、回复、提及及其他通知

目标：集中读取账号收到的互动，保留通知对应的用户、评论和目标内容。

```bash
python scripts/cli.py get-notifications --kind all --limit 100 --max-pages 3
python scripts/cli.py get-notifications --kind comments
python scripts/cli.py get-notifications --kind mentions
```

- 分类：`comments` 包含评论和回复，`mentions` 为提及，另有 `likes`（赞和收藏）、`follows`（新增关注）、`all`。
- 网页把评论和提及放在同一分组，命令读取后按实际类型区分；不认识的类型保留为未知，不根据标题强猜。
- 保留专辑与附属笔记的类型关系，不把专辑编号误当成笔记编号。
- 返回分页完整性、用户字段完整性、未知类型数量和停止原因。加载失败不能返回“成功且零条”。
- 打开通知页可能自然改变网页未读状态。本命令只读取，不自动回复、点赞或关注。

## 3. 自己的笔记与草稿管理

目标：查自己发布的内容及状态，找到浏览器已有草稿并定位恢复编辑入口。

```bash
python scripts/cli.py list-my-notes --keyword '标题关键词'
python scripts/cli.py list-managed-notes --status all --limit 100 --max-pages 3
python scripts/cli.py get-note-status --note-id NOTE_ID
python scripts/cli.py list-drafts --kind all
python scripts/cli.py open-draft --draft-id DRAFT_ID --expected-title '完整草稿标题' --kind image
# 明确要继续编辑时，追加 --open；不会保存或发布。
```

- `list-my-notes` 读取个人主页的笔记元数据，不提供后台审核状态。
- `list-managed-notes` 读取创作平台，状态筛选为 `all/published/reviewing/rejected`；未确认的状态代码保留未知，不假定为已发布。附带数据仅是管理列表快照，不等同完整分析后台。
- `list-drafts` 支持 `image/video/long/audio/all`。这些草稿存储于当前浏览器本地，不是账号在所有设备上的全部草稿。
- `open-draft` 默认只预览目标。只有加 `--open` 才点击对应草稿的编辑入口，并核对 UUID、分类和完整标题。
- 本次不提供删除、修改已发布笔记或自动保存草稿。已有 `fill-publish`、`save-draft`、`click-publish` 继续负责原发布流程，调用前仍须遵守其内容及确认约束。

## 4. 关注关系管理

目标：查询指定用户的关注状态，在有明确授权时准确切换一次。

```bash
python scripts/cli.py get-follow-status --user-id USER_ID --expected-name '完整昵称'
python scripts/cli.py set-follow --user-id USER_ID --expected-name '完整昵称' --state followed
# 确认要执行时追加 --confirm；取消关注使用 --state not-followed。
```

- 默认预览，核对路径中的用户 ID 和主页完整昵称；“互相关注”识别为已关注。
- 已达到目标状态时不点击。确认变更后最多点击一次，并重新读取页面核验；超时或结果不明返回 `unknown`，不能自动再点一次。
- 当前实测网页版主页没有打开关注／粉丝完整列表的入口，因此本次不提供全量关注列表管理。新增关注通知也不能代替完整粉丝列表。

## 5. 收藏、网页专辑与个人检索

目标：找到自己存过的内容，并明确检索覆盖范围。

```bash
python scripts/cli.py list-favorites --limit 100 --max-pages 3
python scripts/cli.py list-collections
python scripts/cli.py search-library --scope all --keyword '关键词' --limit 100 --max-pages 3
```

- `search-library` 范围为 `notes/favorites/all`，当前检索列表中的标题、作者，不宣称全文检索。
- 笔记和收藏共用分页、去重及身份核对机制，按网页正确的数据分组读取。
- `list-collections` 对应网页“专辑”，非空记录保留其原始结构；不等于 App 的所有收藏夹。
- 本次不提供专辑创建、改名、删除或内容移动，也没有未经证实的专辑详情入口。

## 6. 链接与内容导出

上游 PR #66 提供分享地址生成和搜索结果 `shareUrl`。本次沿用其能力范围，增加正确的 URL 参数编码、链接解析和本地导出；不是把 #66 当成完整导出功能。

```bash
python scripts/cli.py get-share-url --feed-id NOTE_ID --xsec-token TOKEN
python scripts/cli.py resolve-link --link '完整链接或含链接的分享文案'
python scripts/cli.py export-note --link '笔记链接' --output /绝对路径/note.md --format markdown
python scripts/cli.py export-content --input /绝对路径/已读取.json \
  --output /绝对路径/归档.json --format json
```

- 支持主站笔记长链接、个人主页下的笔记链接，以及通过 HTTP 重定向跳转的 `xhslink.com` 短链接。每一跳验证域名和网络目标；依赖网页脚本的短链会明确报出限制。
- 生成或解析链接不代表已验证笔记可访问，也不延长访问令牌有效期。
- 搜索、主页等笔记序列化结果附带 `shareUrl`；缺令牌或有效笔记编号时返回空地址。
- `export-note` 读取笔记详情并校验实际笔记编号；只导出已读取的评论，不假称全部评论完整。
- JSON 保留结构化数据；Markdown 提供可读正文、图片地址、评论及完整数据。媒体默认只记录地址，不下载图片或视频。
- 输出必须是绝对路径，父目录需已存在，默认不覆盖文件；明确覆盖时加 `--overwrite`。导出包含账号可见的个人内容，应由用户选择保存和分享位置。

## 完整性与验收

- 返回 `complete=false` 时，结合 `has_more`、`stop_reason` 或 `stopped_reason` 判断是条数限制、页数限制、未证实结束、未知类型还是加载停滞；不可汇报为“已读完”。
- 限制参数约束一次命令的读取量，不是持续定时监控。需要持续运行时另行设计调度、增量保存和任务恢复。
- 新管理命令在跨页前保护当前私信草稿和创作编辑内容；存在未处理内容时停止导航，不擅自保存、覆盖或清空。
- 验证分三层：实际脚本和原始结构的离线测试、已登录网页的只读读取、写操作的授权后实测。本次开发只进行了前两层；关注变更、草稿打开编辑等写入或编辑路径使用模拟验证，不冒称已在真实账号执行。
