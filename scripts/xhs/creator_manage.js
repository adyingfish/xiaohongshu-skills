(params) => {
    const visible = el => !!el && el.getBoundingClientRect().width > 0 &&
        el.getBoundingClientRect().height > 0 && getComputedStyle(el).visibility !== 'hidden' &&
        Number(getComputedStyle(el).opacity || 1) > 0.1;
    const all = (selector, root = document) => [...root.querySelectorAll(selector)].filter(visible);
    const text = el => el?.textContent.trim() || '';
    const plain = v => JSON.parse(JSON.stringify(v));
    const creator = location.origin === 'https://creator.xiaohongshu.com';
    const onPublish = creator && /^\/publish\//.test(location.pathname);
    const drawer = all('.d-drawer').find(el => el.querySelector('.draft-list')) ||
        all('.draft-list')[0]?.closest('.d-drawer-container') || all('.draft-list')[0]?.parentElement;
    const outsideDraftList = el => !drawer?.contains(el) &&
        !el.closest('.draft-drawer, .draft-list, .draft-item');
    const controls = all('input:not([type="file"]), textarea, [contenteditable="true"]')
        .filter(outsideDraftList);
    const titles = controls.filter(el => el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')
        .map(el => String(el.value || '').trim());
    const editors = controls.filter(el => el.getAttribute('contenteditable') === 'true');
    const dirty = onPublish && (controls.some(el =>
        String(el.value || el.textContent || '').trim() || el.querySelector('img,video,audio')) ||
        all('.img-preview-area .pr, .video-preview, video[src], audio[src]').some(outsideDraftList) ||
        [...document.querySelectorAll('input[type="file"]')]
            .some(el => outsideDraftList(el) && el.files?.length));
    if (params.action === 'guard') return {safe_to_navigate: !dirty, on_publish: onPublish};
    if (!creator) return {error: '当前不是小红书创作服务平台'};
    if (all('.login-container, .login-page').length) return {error: '创作服务平台尚未登录'};
    const app = document.querySelector('#app')?.__vue_app__;
    const unwrap = value => value && typeof value === 'object' && 'value' in value ? value.value :
        value && typeof value === 'object' && '_value' in value ? value._value : value;
    const user = unwrap(app?.config?.globalProperties?.$store?.state?.Auth?.userInfo);
    const account = {account_id: String(user?.userId || user?.user_id || ''),
        account_name: String(user?.userName || user?.nickname || '')};
    if (!/^[0-9a-fA-F]{24}$/.test(account.account_id)) return {ready: false};
    if (params.account_id && params.account_id !== account.account_id) {
        return {...account, error: '创作账号发生变化，已停止，避免混合账号数据或打开错误草稿'};
    }
    const result = (() => {
    if (params.action === 'editor') return {ready: onPublish && !drawer &&
        (editors.length > 0 || all('.img-preview-area .pr, .video-preview').length > 0), titles};
    if (params.action.startsWith('draft')) {
        if (!onPublish) return {error: '当前不是发布页面'};
        if (params.action === 'draft-drawer') {
            if (drawer) return {ready: true};
            if (dirty) return {error: '编辑器已有内容，请先保存或处理，避免覆盖'};
            const entries = all('.draft-title').filter(el => /^草稿箱/.test(text(el)));
            if (entries.length !== 1) return {ready: false};
            entries[0].click();
            return {ready: false};
        }
        if (!drawer) return {ready: false};
        const labels = {image: '图文笔记', video: '视频笔记', long: '长文笔记', audio: '播客笔记'};
        const tab = all('.tab-item', drawer).find(el => text(el).startsWith(labels[params.kind]));
        if (!tab) return {error: '草稿箱没有请求的类型标签'};
        if (params.action === 'draft-select') {
            if (!tab.classList.contains('active')) tab.click();
            return {ready: true};
        }
        if (!tab.classList.contains('active')) return {ready: false};
        const count = Number(text(tab).match(/[（(](\d+)[）)]/)?.[1] ?? NaN);
        const cards = all('.draft-item[data-draft-id]', drawer);
        const items = cards.map(el => ({draft_id: el.getAttribute('data-draft-id'),
            kind: params.kind, raw_type: el.getAttribute('data-draft-type'),
            title: text(el.querySelector('.draft-title-text')),
            saved_at: text(el.querySelector('.draft-time')),
            has_title: el.querySelector('.draft-title-text')?.classList.contains('has-title') || false}));
        if (params.action === 'draft-open') {
            if (dirty) return {error: '编辑器已有内容，未覆盖'};
            const matches = cards.filter(el => el.getAttribute('data-draft-id') === params.draft_id);
            if (matches.length !== 1 || text(matches[0].querySelector('.draft-title-text')) !== params.expected_title) {
                return {error: '草稿 ID 和标题未同时匹配，未打开'};
            }
            const buttons = all('.draft-actions .btn', matches[0]).filter(el => text(el) === '编辑');
            if (buttons.length !== 1) return {error: '未找到唯一的草稿编辑按钮'};
            buttons[0].click();
            return {clicked: true};
        }
        if (params.action === 'draft-more') {
            const list = drawer.querySelector('.draft-list');
            list.scrollTo({top: list.scrollHeight, behavior: 'instant'});
            list.dispatchEvent(new Event('scroll', {bubbles: true}));
            return {scrolled: true};
        }
        const empty = all('.empty-state', drawer).some(el => /暂无草稿/.test(text(el)));
        if (!items.length && !(count === 0 && empty)) return {ready: false};
        return plain({ready: true, items, total: Number.isFinite(count) ? count : null,
            complete: Number.isFinite(count) && items.length >= count});
    }
    if (location.pathname !== '/new/note-manager') return {error: '当前不是笔记管理页面'};
    const container = document.querySelector('.notes-container');
    if (!container) return {ready: false};
    const tabs = all('.tab-list .tab-item', container);
    const labels = {all: '全部', published: '已发布', reviewing: '审核中', rejected: '未通过'};
    const tab = tabs.find(el => text(el).startsWith(labels[params.status]));
    if (!tab) return {ready: false};
    if (params.action === 'notes-select') {
        if (!tab.classList.contains('tab-item--active')) tab.click();
        return {ready: true};
    }
    if (!tab.classList.contains('tab-item--active')) return {ready: false};
    if (all('.d-loading, .loading', container).length) return {ready: false};
    const errors = all('.error-message, .load-error', container).map(text).filter(Boolean);
    if (errors.length) return {error: errors.join('；')};
    if (params.action === 'notes-more') {
        const next = all('button, [role="button"]', container).find(el =>
            el.getAttribute('aria-label') === '下一页' || text(el) === '下一页');
        if (next && !next.disabled && next.getAttribute('aria-disabled') !== 'true') next.click();
        else {
            const scrollables = [container, ...container.querySelectorAll('*')].filter(el =>
                visible(el) && el.scrollHeight > el.clientHeight + 8 &&
                /auto|scroll/.test(getComputedStyle(el).overflowY));
            const scroller = scrollables.at(-1) || document.scrollingElement;
            scroller.scrollTo({top: scroller.scrollHeight, behavior: 'instant'});
            scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
        }
        return {scrolled: true};
    }
    const props = new Map();
    const seen = new Set();
    function walk(v, depth = 0) {
        if (!v || typeof v !== 'object' || seen.has(v) || depth > 70) return;
        seen.add(v);
        if (v.component) {
            const c = v.component;
            const note = c.props?.note;
            if (note?.id) props.set(String(note.id), note);
            walk(c.subTree, depth + 1);
        }
        if (Array.isArray(v.children)) v.children.forEach(x => walk(x, depth + 1));
    }
    walk(document.querySelector('#app')?.__vue_app__?._container?._vnode);
    const cards = all('.note-card', container);
    const items = [];
    for (const card of cards) {
        let id;
        try {id = JSON.parse(card.dataset.impression || '{}').noteTarget?.value?.noteId;} catch (_) {}
        if (!id) return {error: '笔记卡片缺少稳定 ID，未输出可能错配的记录'};
        const note = props.get(id);
        const title = text(card.querySelector('.note-card__title'));
        if (note && String(note.display_title) !== title) return {ready: false};
        items.push({note_id: id, title, time: note?.time || text(card.querySelector('.note-card__time')),
            status: note?.tab_status === 1 ? 'published' :
                all('.note-card__status, .note-card__tag', card).some(el => text(el) === '审核中') ? 'reviewing' :
                all('.note-card__status, .note-card__tag', card).some(el => text(el) === '未通过') ? 'rejected' : 'unknown',
            raw_status: note?.tab_status ?? null, type: note?.type || 'unknown',
            xsec_token: note?.xsec_token || '', stats: note ? {views: note.view_count ?? null,
                likes: note.likes ?? null, comments: note.comments_count ?? null,
                collections: note.collected_count ?? null, shares: note.shared_count ?? null} : null});
    }
    const totalText = text(tabs.find(el => text(el).startsWith('全部')));
    const allTotal = Number(totalText.match(/全部\s*[（(]?\s*(\d+)/)?.[1] ?? NaN);
    const empty = all('.empty-state, .d-result, .empty', container).some(el => /暂无|没有.*笔记/.test(text(el)));
    if (!items.length && !empty && allTotal !== 0) return {ready: false};
    const complete = (Number.isFinite(allTotal) && items.length >= allTotal) || empty;
    return plain({ready: true, items, total: Number.isFinite(allTotal) ? allTotal : null,
        complete, status: params.status});
    })();
    return plain({...result, ...account});
}
