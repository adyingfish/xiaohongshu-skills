(params) => {
    const unwrap = value => {
        for (let i = 0; i < 4 && value && typeof value === 'object'; i++) {
            if (value.value !== undefined) value = value.value;
            else if (value._value !== undefined) value = value._value;
            else break;
        }
        return value;
    };
    const list = value => {
        value = unwrap(value);
        if (Array.isArray(value)) return value;
        if (value && typeof value === 'object' && Object.keys(value).every(k => /^\d+$/.test(k))) {
            return Object.keys(value).sort((a, b) => Number(a) - Number(b)).map(k => value[k]);
        }
        return null;
    };
    const visible = el => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < innerWidth &&
            getComputedStyle(el).visibility !== 'hidden' &&
            getComputedStyle(el).display !== 'none' && Number(getComputedStyle(el).opacity || 1) > .1;
    };
    const done = value => JSON.stringify(value);
    const user = window.__INITIAL_STATE__?.user;
    const info = unwrap(user?.userInfo) || {};
    const logged = unwrap(user?.loggedIn);
    if (logged === false || info.guest === true || visible(document.querySelector('.login-container'))) {
        return done({not_logged_in: true});
    }
    const accountId = String(info.userId || '');
    if (!/^[0-9a-fA-F]{24}$/.test(accountId)) return done({ready: false});
    if (params.action === 'account') {
        return done({ready: true, account_id: accountId, nickname: String(info.nickname || '')});
    }
    const profileId = location.pathname.match(/^\/user\/profile\/([0-9a-fA-F]{24})\/?$/)?.[1];
    if (location.origin !== 'https://www.xiaohongshu.com' || profileId !== accountId ||
        (params.account_id && params.account_id !== accountId)) {
        return done({error: '当前页面或登录账号与个人内容库目标不一致'});
    }
    if (!['notes', 'favorites', 'collections'].includes(params.scope)) {
        return done({error: '未知个人内容库范围'});
    }
    const topQuery = params.scope === 'notes' ? 'note' : 'fav';
    const subQuery = params.scope === 'collections' ? 'board' : 'note';
    const active = unwrap(user.activeTab) || {};
    const sub = unwrap(user.activeSubTab) || {};
    if (params.action === 'select') {
        if (active.query !== topQuery) {
            const label = topQuery === 'note' ? '笔记' : '收藏';
            const tabs = [...document.querySelectorAll('.reds-tab-item.sub-tab-list')]
                .filter(el => visible(el) && el.textContent.trim() === label);
            if (tabs.length !== 1) return done({error: '未找到唯一的个人主页标签'});
            tabs[0].click();
            return done({selected: false, clicked: true});
        }
        if (topQuery === 'fav' && sub.query !== subQuery) {
            const label = subQuery === 'board' ? '专辑' : '笔记';
            const tabs = [...document.querySelectorAll('.tab-content-item .sub-tab-list .reds-tab-item')]
                .filter(el => visible(el) && el.textContent.trim().split(/[・·]/)[0] === label);
            if (tabs.length !== 1) return done({error: '未找到唯一的收藏子标签'});
            tabs[0].click();
            return done({selected: false, clicked: true});
        }
        return done({selected: true});
    }
    if (active.query !== topQuery || (topQuery === 'fav' && sub.query !== subQuery)) {
        return done({ready: false});
    }
    const index = params.scope === 'notes' ? active.index : sub.index;
    if (!Number.isInteger(index) || index < 0) return done({error: '网页未提供列表索引'});
    const queries = unwrap(user.noteQueries);
    const query = unwrap(queries?.[index]);
    const allNotes = unwrap(user.notes);
    const records = list(allNotes?.[index]);
    const fetching = unwrap(unwrap(user.isFetchingNotes)?.[index]);
    const status = unwrap(unwrap(user.userNoteFetchingStatus)?.[index]);
    if (['rejected', 'error', 'failed'].includes(status)) {
        return done({error: '网页加载个人列表失败，请稍后重试'});
    }
    if (query?.userId && query.userId !== accountId) return done({error: '列表归属账号不一致'});
    if (records === null || !query || typeof query.hasMore !== 'boolean') {
        return done({ready: false});
    }
    const root = document.querySelectorAll('.tab-content-item')[active.index];
    if (params.action === 'scroll') {
        if (!root) return done({error: '未找到当前列表滚动容器'});
        const cards = root.querySelectorAll('.note-item, .board-container');
        const last = cards[cards.length - 1];
        if (last?.scrollIntoView) last.scrollIntoView({block: 'end', behavior: 'instant'});
        let scroller = root;
        while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 8 &&
            /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement;
        scroller = scroller || document.scrollingElement;
        if (!scroller) return done({error: '网页没有可用滚动区域'});
        scroller.scrollTo({top: scroller.scrollHeight, behavior: 'instant'});
        return done({scrolled: true});
    }
    const emptyText = [...(root?.querySelectorAll('.empty-text') || [])]
        .filter(visible).map(el => el.textContent.trim()).join(' ');
    const settledEmpty = records.length === 0 && !query.hasMore &&
        (status === 'resolved' || /(?:没有|暂无)/.test(emptyText));
    if (fetching === true || (records.length === 0 && !settledEmpty)) return done({ready: false});
    const meta = {ready: true, account_id: accountId, nickname: String(info.nickname || ''),
        scope: params.scope, has_more: query.hasMore, cursor: String(query.cursor || ''),
        page: Number(query.page || 1), empty_text: emptyText};
    if (params.scope === 'collections') {
        // 当前网页专辑由 notes[sub.index] 提供；保留实际记录，不猜测 App 收藏夹结构。
        return done({...meta, records, record_format: 'web_collection_raw'});
    }
    const items = records.map(raw => {
        const card = raw.noteCard || {};
        return {id: String(raw.id || card.noteId || ''),
            xsecToken: String(raw.xsecToken || card.xsecToken || ''),
            displayTitle: String(card.displayTitle || ''), type: String(card.type || ''),
            user: {userId: String(card.user?.userId || ''),
                nickname: String(card.user?.nickname || card.user?.nickName || '')},
            interactInfo: card.interactInfo || {}, time: card.time || null,
            cover: card.cover?.urlDefault || card.cover?.url || ''};
    });
    if (items.some(item => !/^[0-9a-fA-F]{24}$/.test(item.id))) {
        return done({error: '列表包含无法识别的笔记数据，未将其当作空列表'});
    }
    return done({...meta, records: items, record_format: 'note_metadata'});
}
