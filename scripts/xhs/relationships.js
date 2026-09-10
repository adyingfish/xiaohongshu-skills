(params) => {
    const visible = el => !!el && el.getBoundingClientRect().width > 0 &&
        el.getBoundingClientRect().height > 0 && getComputedStyle(el).visibility !== 'hidden' &&
        Number(getComputedStyle(el).opacity || 1) > 0.1;
    if (visible(document.querySelector('.login-container'))) return {not_logged_in: true};
    const id = location.pathname.match(/^\/user\/profile\/([0-9a-fA-F]{24})\/?$/)?.[1];
    if (location.origin !== 'https://www.xiaohongshu.com' || id !== params.user_id) {
        return {error: '用户主页 ID 与目标不一致，已停止'};
    }
    const root = document.querySelector('.user-page > .user') || document.querySelector('.user-page .user-info');
    if (!root) return {ready: false};
    const names = [...root.querySelectorAll('.user-name')].filter(visible);
    if (names.length !== 1) return {ready: false};
    const nickname = names[0].textContent.trim();
    if (nickname !== params.expected_name) return {error: '用户主页昵称与预期不一致，已停止'};
    const norm = text => text.replace(/\s+/g, '');
    const toState = text => ['已关注', '互相关注', '相互关注'].includes(norm(text)) ? 'followed' :
        ['关注', '+关注', '回关'].includes(norm(text)) ? 'not-followed' : null;
    const buttons = [...root.querySelectorAll('button, [role="button"], .reds-button-new')]
        .filter(el => visible(el) && toState(el.textContent) !== null);
    const unique = buttons.filter(el => !buttons.some(other => other !== el && el.contains(other)));
    if (unique.length !== 1) return {ready: false};
    const button = unique[0];
    const state = toState(button.textContent);
    if (params.action === 'read') return {ready: true, user_id: id, nickname, state,
        label: button.textContent.trim()};
    if (params.action !== 'set') return {error: '未知关注操作'};
    if (state === params.desired_state) return {unchanged: true};
    if (!['followed', 'not-followed'].includes(params.desired_state) || state !== params.expected_state) {
        return {error: '点击前关注状态发生变化，已停止'};
    }
    if (button.disabled || button.getAttribute('aria-disabled') === 'true') {
        return {error: '关注按钮不可用，已停止'};
    }
    button.click();
    return {clicked: true};
}
