// 仅读取网页已加载的私信状态；滚动由网页自己的事件处理加载，不调用消息 API。
(params) => {
    const unwrap = value => value?.value ?? value?._value ?? value;
    const user = window.__INITIAL_STATE__?.user;
    const userInfo = unwrap(user?.userInfo) || {};
    const accountId = userInfo.userId || userInfo.user_id || '';
    const visible = el => !!el && el.getBoundingClientRect().width > 0 &&
        el.getBoundingClientRect().height > 0 && getComputedStyle(el).visibility !== 'hidden';
    const one = selector => {
        const nodes = [...document.querySelectorAll(selector)].filter(visible);
        return nodes.length === 1 ? nodes[0] : null;
    };
    const text = el => {
        if (!el) return '';
        const copy = el.cloneNode(true);
        copy.querySelectorAll('img').forEach(img => img.replaceWith(img.alt || '\uFFFC'));
        copy.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
        copy.querySelectorAll('div,p').forEach(block => block.prepend('\n'));
        return copy.textContent.replace(/\r\n/g, '\n').trim();
    };
    const onChat = location.origin === 'https://www.xiaohongshu.com' &&
        /^\/chat(?:\/|$)/.test(location.pathname);
    const pathId = location.pathname.match(/^\/chat\/([0-9a-fA-F]{24})\/?$/)?.[1] || '';
    const active = one('.xhs-im-conv-item--active[data-conv-kind="c2c"]');
    const header = one('.xhs-im-chat-window__header-name');
    const editor = one('.xhs-im-chat-window .xhs-im-input-bar-editor');
    const list = one('.xhs-im-msg-list');
    const root = one('.xhs-im-view');
    // IM 使用独立 Vue 组件状态，__INITIAL_STATE__.messageData 并不是这里的消息源。
    // 只遍历当前渲染树并读取 props，不调用组件方法或私有消息接口。
    const components = new Map();
    const seen = new Set();
    const walk = (node, depth = 0) => {
        if (!node || typeof node !== 'object' || seen.has(node) || depth > 55) return;
        seen.add(node);
        if (node.component) {
            const component = node.component;
            const name = component.type?.name || component.type?.__name || '';
            if (['IMView', 'ConversationList', 'ChatWindow', 'MessageList'].includes(name)) {
                const found = components.get(name) || [];
                found.push(component.props || {});
                components.set(name, found);
            }
            walk(component.subTree, depth + 1);
        }
        if (Array.isArray(node.children)) node.children.forEach(child => walk(child, depth + 1));
        if (node.suspense?.activeBranch) walk(node.suspense.activeBranch, depth + 1);
    };
    walk(document.querySelector('#app')?.__vue_app__?._container?._vnode);
    const component = (name, predicate = () => true) => {
        const matches = (components.get(name) || []).filter(predicate);
        return matches.length === 1 ? matches[0] : null;
    };
    const im = component('IMView');
    const conversationsState = component('ConversationList');
    const chat = component('ChatWindow', props => props.conv?.id === pathId);
    const history = component('MessageList', props => props.conv?.id === pathId);
    const messageLoading = !!(chat?.isLoadingMessages || chat?.isPreloadingMessages ||
        chat?.isLoadingHistory || history?.initialLoading || history?.preloading || history?.loadingMore);
    const identityError = (im?.currentUserId && im.currentUserId !== accountId) ||
        (chat?.myUid && chat.myUid !== accountId) || (history?.myUid && history.myUid !== accountId);
    const pageReady = onChat && /^[0-9a-fA-F]{24}$/.test(accountId) &&
        !!root && !!one('.xhs-im-conv-list__scroll');
    const conversationMatches = !!list && !!header && !!active &&
        active.getAttribute('data-conv-id') === pathId;
    const state = {
        on_chat_page: onChat,
        ready: pageReady && !conversationsState?.isLoading,
        conversation_ready: conversationMatches && !messageLoading,
        account_id: accountId,
        user_id: pathId,
        recipient: text(header),
        draft: text(editor),
        not_logged_in: unwrap(user?.loggedIn) === false || visible(document.querySelector('.login-container')),
    };
    if (identityError) return {error: '登录账号与当前私信组件账号不一致，已停止'};
    if (params.action === 'snapshot') return state;
    if (!pageReady) return {error: '私信页面未就绪，无法确认列表是否为空'};
    if (['messages', 'latest'].includes(params.action) ||
        (params.action === 'scroll' && params.target === 'messages')) {
        if (!conversationMatches || pathId !== params.user_id || text(header) !== params.expected_name ||
            text(active?.querySelector('.xhs-im-conv-item__name')) !== params.expected_name) {
            return {error: '会话 ID、完整昵称和当前页面未同时匹配，停止读取'};
        }
    }
    if (params.action === 'latest') {
        list.scrollTop = list.scrollHeight;
        list.dispatchEvent(new Event('scroll', {bubbles: true}));
        return {scrolled: true};
    }
    if (params.action === 'scroll') {
        const target = params.target === 'messages' ? list : one('.xhs-im-conv-list__scroll');
        if (!target) return {scrolled: false};
        target.scrollTop = params.target === 'messages' ? 0 : target.scrollHeight;
        target.dispatchEvent(new Event('scroll', {bubbles: true}));
        return {scrolled: true};
    }
    if (params.action === 'list') {
        if (conversationsState?.isLoading) {
            return {account_id: accountId, conversations: [], loading: true, complete: false};
        }
        let conversations = [...document.querySelectorAll('.xhs-im-conv-item[data-conv-kind="c2c"]')]
            .map(el => ({
                user_id: el.getAttribute('data-conv-id') || '',
                nickname: text(el.querySelector('.xhs-im-conv-item__name')),
                preview: text(el.querySelector('.xhs-im-conv-item__summary-text')),
                time_label: text(el.querySelector('.xhs-im-conv-item__time')),
                unread_count: null,
                unread_hint: text(el.querySelector('.xhs-im-conv-item__bottom-right')),
            }));
        if (conversationsState && !Array.isArray(conversationsState.convList)) {
            return {error: '私信会话组件数据结构发生变化'};
        }
        if (conversationsState) {
            const dom = new Map(conversations.map(conv => [conv.user_id, conv]));
            conversations = conversationsState.convList.filter(conv => conv.kind === 'c2c')
                .map(conv => ({
                    user_id: conv.id, // 实际 conv.peerUserId 指向自己，不能用作会话对象！
                    nickname: conv.name || '',
                    preview: conv.lastMessage || '',
                    time_label: dom.get(conv.id)?.time_label || '',
                    timestamp_ms: Number(conv.lastMessageAt) || null,
                    unread_count: conversationsState.isUnreadInitialized &&
                        Number.isFinite(conv.unreadCount) ? conv.unreadCount : null,
                    unread_hint: dom.get(conv.id)?.unread_hint || '',
                    has_draft: !!conv.hasDraft,
                    is_muted: !!conv.isMuted,
                    is_pinned: !!conv.isPinned,
                    is_blocked: !!conv.isBlocked,
                }));
        }
        if (!conversationsState && conversations.length === 0) {
            return {error: '未捕获会话组件或会话记录，无法区分空收件箱与加载失败'};
        }
        return {account_id: accountId, conversations, complete: false,
            completeness_note: '已读取普通文件夹中加载的单人会话；不包含陌生人文件夹，网页没有提供会话总数或结束标记。',
            total_unread: conversationsState?.isUnreadInitialized ? conversationsState.totalUnread : null,
            source: conversationsState ? 'vue_component_props' : 'dom'};
    }
    if (params.action === 'messages') {
        let timeLabel = '';
        const messages = [];
        for (const child of list.children) {
            if (child.classList.contains('xhs-im-msg-list__time-divider')) {
                timeLabel = text(child);
                continue;
            }
            if (!child.classList.contains('chat-item')) continue;
            const bubble = child.querySelector('.chat-item__bubble');
            const body = child.querySelector('.xhs-im-bubble__text');
            const content = text(body);
            const direction = child.querySelector('.chat-item__bubble--me') ? 'outgoing' :
                child.querySelector('.chat-item__bubble--other') ? 'incoming' : 'unknown';
            const images = [...(bubble?.querySelectorAll('img') || [])]
                .filter(img => !img.classList.contains('xhs-im-inline-emoji'))
                .map(img => ({url: img.currentSrc || img.getAttribute('src') || '', alt: img.alt || ''}));
            const media = [...(bubble?.querySelectorAll('video,audio') || [])]
                .map(el => ({kind: el.tagName.toLowerCase(), url: el.currentSrc || el.getAttribute('src') || ''}));
            // 网页会把相互关注欢迎语渲染为 incoming text；仅凭文字无法证明是人工消息。
            const systemCandidate = /^我们已相互关注，开始聊天吧/.test(content);
            messages.push({
                message_id: child.getAttribute('data-message-id') || '',
                store_id: child.getAttribute('data-store-id') || '',
                content_type: child.getAttribute('data-content-type') || '',
                direction: systemCandidate ? 'unknown' : direction,
                kind: systemCandidate ? 'system_candidate' : body ? 'text' :
                    media.length ? media[0].kind : images.length ? 'image' : 'unknown',
                text: content || (bubble ? text(bubble) : text(child)),
                time_label: timeLabel,
                timestamp_ms: null,
                images, media,
                failed: !!child.querySelector('.chat-item__status-btn--failed'),
                pending: !!child.querySelector('.chat-item__status-loading') ||
                    (direction === 'outgoing' && !/^[1-9]\d*$/.test(child.getAttribute('data-store-id') || '')),
            });
        }
        const rawMessages = chat?.messages || history?.messages;
        if ((chat || history) && !Array.isArray(rawMessages)) {
            return {error: '私信历史组件数据结构发生变化'};
        }
        if (messageLoading) return {account_id: accountId, messages: [], complete: false, loading: true};
        if (Array.isArray(rawMessages)) {
            if (rawMessages.some(raw => raw.chatId && raw.chatId !== pathId)) {
                return {error: '历史消息会话归属与当前目标不一致，已停止读取'};
            }
            if (!rawMessages.length && typeof chat?.isLoadingMessages !== 'boolean' &&
                typeof history?.initialLoading !== 'boolean') {
                return {error: '空历史缺少明确加载状态，无法确认会话是否为空'};
            }
            const rendered = new Map(messages.map(message => [message.message_id, message]));
            const normalized = rawMessages.map(raw => {
                const dom = rendered.get(raw.messageId);
                let decoded;
                try { decoded = typeof raw.content === 'string' ? JSON.parse(raw.content) : raw.content; }
                catch { decoded = {content: raw.content}; }
                const body = decoded?.content;
                const content = typeof body === 'string' ? body : dom?.text || '';
                const direction = raw.senderId === accountId && raw.receiverId === pathId ? 'outgoing' :
                    raw.senderId === pathId && raw.receiverId === accountId ? 'incoming' : 'unknown';
                const systemCandidate = /^我们已相互关注，开始聊天吧/.test(content);
                // 当前网页不渲染 contentType=0、空正文的控制记录，但保留在历史数据中。
                const control = raw.contentType === 0 && !content && !dom;
                const kind = control ? 'system' : systemCandidate ? 'system_candidate' :
                    raw.contentType === 1 ? 'text' : dom?.kind || 'unknown';
                return {
                    message_id: raw.messageId || '',
                    store_id: String(raw.storeId ?? ''),
                    content_type: String(raw.contentType ?? ''),
                    sender_id: raw.senderId || '', receiver_id: raw.receiverId || '',
                    direction: systemCandidate ? 'unknown' : direction,
                    kind, text: content, time_label: dom?.time_label || raw.formatTime || '',
                    timestamp_ms: Number(raw.createTime) || null,
                    images: dom?.images || [], media: dom?.media || [],
                    ...(kind === 'unknown' ? {content: decoded} : {}),
                    failed: dom?.failed || false,
                    pending: dom?.pending || (direction === 'outgoing' &&
                        (!!raw.isLocalMsg || !/^[1-9]\d*$/.test(String(raw.storeId ?? '')))),
                };
            });
            return {account_id: accountId, messages: normalized,
                complete: chat ? chat.hasMoreHistory === false : history.hasMore === false,
                loading: false, source: 'vue_component_props'};
        }
        if (!messages.length) {
            return {error: '未捕获消息组件或消息记录，无法区分空会话与加载失败'};
        }
        return {account_id: accountId, messages, complete: false, source: 'dom'};
    }
    return {error: '未知私信读取操作'};
}
