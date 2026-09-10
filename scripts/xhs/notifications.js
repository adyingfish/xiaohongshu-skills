(params) => {
    const unwrap = v => v && typeof v === 'object' && 'value' in v ? v.value :
        v && typeof v === 'object' && '_value' in v ? v._value : v;
    const visible = el => !!el && el.getBoundingClientRect().width > 0 &&
        el.getBoundingClientRect().height > 0 && getComputedStyle(el).visibility !== 'hidden' &&
        Number(getComputedStyle(el).opacity || 1) > 0.1;
    if (visible(document.querySelector('.login-container'))) return {not_logged_in: true};
    if (location.origin !== 'https://www.xiaohongshu.com' ||
        !/^\/notification\/?$/.test(location.pathname)) return {error: '当前不是通知页面'};
    const root = unwrap(window.__INITIAL_STATE__?.notification);
    const map = unwrap(root?.notificationMap);
    if (!map) return {ready: false};
    const labels = {mentions: ['评论和@', '评论和 @', '评论与@'],
        likes: ['赞和收藏'], follows: ['新增关注']};
    if (!labels[params.source]) return {error: '不支持的网页通知分组'};
    const tabs = [...document.querySelectorAll('[role="tab"], .reds-tab-item, .tab-item')]
        .filter(visible);
    const tab = tabs.find(el => labels[params.source].includes(
        (el.querySelector('.badge-container span') || el).textContent.trim()));
    if (!tab) return {ready: false};
    if (params.action === 'select') {
        tab.click();
        return {selected: true};
    }
    // 分组存在但尚未取回数据，与已成功加载的空列表分开处理。
    const sourceKey = params.source === 'follows' ? 'connections' : params.source;
    const sourceIndex = {mentions: 0, likes: 1, follows: 2}[params.source];
    if (Number(unwrap(root.activeTabKey)) !== sourceIndex || unwrap(root.isFetching)) {
        return {ready: false};
    }
    const group = unwrap(map[sourceKey]);
    if (!group || !Array.isArray(unwrap(group.messageList))) return {ready: false};
    if (group.error || group.loadError || group.isError) return {error: '网页通知加载失败'};
    if (group.loading || group.isLoading) return {ready: false};
    const container = document.querySelector('.notification-container') ||
        document.querySelector('.notification-page') || document.body;
    const error = [...container.querySelectorAll('.error, .error-msg, .error-message')]
        .filter(visible).map(el => el.textContent.trim()).find(Boolean);
    if (error) return {error: `通知页面错误：${error}`};
    if (params.action === 'more') {
        const scrollables = [container, ...container.querySelectorAll('*')]
            .filter(el => visible(el) && el.scrollHeight > el.clientHeight + 8 &&
                /auto|scroll/.test(getComputedStyle(el).overflowY));
        const scroller = scrollables.at(-1) || document.scrollingElement;
        if (!scroller) return {error: '未找到通知列表的滚动区域'};
        scroller.scrollTo({top: scroller.scrollHeight, behavior: 'instant'});
        scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
        return {scrolled: true};
    }
    const list = unwrap(group.messageList);
    const emptyShown = [...container.querySelectorAll('.empty, .empty-state, .empty-container, .nothing')]
        .some(el => visible(el) && /暂无|没有|还没有/.test(el.textContent));
    const emptyLoaded = group.hasMore === false && String(group.cursor ?? '') !== '';
    if (!list.length && !emptyShown && !emptyLoaded) return {ready: false};
    const items = list.map(m => {
        const type = String(m.type || '');
        const title = String(m.title || '');
        // connections 的操作者位于 user，赞藏/评论使用 userInfo（真实网页两种结构）。
        const actor = m.userInfo || m.user || {};
        const target = m.itemInfo || {};
        const attachedTarget = target.attachItemInfo || {};
        const note = target.type === 'note_info' ? target :
            attachedTarget.type === 'note_info' ? attachedTarget : {};
        const normalizeTarget = item => ({type: String(item.type || 'unknown'),
            id: String(item.id || ''), title: String(item.content || ''),
            xsec_token: String(item.xsecToken || '')});
        const kind = params.source === 'likes' ? 'likes' : params.source === 'follows' ? 'follows' :
            /^(at|mention)\//i.test(type) ? 'mentions' : /^comment\//i.test(type) ? 'comments' :
            /提到|@了/.test(title) ? 'mentions' : /评论了|回复了/.test(title) ? 'comments' : 'unknown';
        const user = {user_id: String(actor.userid || actor.userId || ''),
            nickname: String(actor.nickname || ''), xsec_token: String(actor.xsecToken || '')};
        return {
            id: String(m.id || ''), type, kind, action: title,
            time: Number(m.time || 0),
            user, user_details_complete: !!user.user_id && !!user.nickname,
            target: target.id ? normalizeTarget(target) : null,
            attached_target: attachedTarget.id ? normalizeTarget(attachedTarget) : null,
            comment_id: String(m.commentInfo?.id || ''),
            content: String(m.commentInfo?.content || ''),
            quoted_comment: String(m.commentInfo?.targetComment?.content || ''),
            note_id: String(note.id || ''),
            note_title: String(note.content || ''),
            note_xsec_token: String(note.xsecToken || '')
        };
    });
    return JSON.parse(JSON.stringify({ready: true, items, total_loaded: list.length,
        has_more: typeof group.hasMore === 'boolean' ? group.hasMore : null,
        cursor: String(group.cursor || '')}));
}
