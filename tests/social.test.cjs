// Execute the shipping page scripts against isolated DOM/state fixtures.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = name => fs.readFileSync(path.join(__dirname, '../scripts/xhs', `${name}.js`), 'utf8');
function node(text = '') {
    return {textContent: text, getBoundingClientRect: () => ({width: 100, height: 40}),
        querySelector: () => null, querySelectorAll: () => [], getAttribute: () => null,
        contains: () => false, click() {this.clicks = (this.clicks || 0) + 1;}};
}
function fixture(name, params, doc, state, pathname) {
    return vm.runInNewContext(`(${source(name)})(params)`, {
        params, document: doc, window: {__INITIAL_STATE__: state},
        location: {origin: 'https://www.xiaohongshu.com', pathname},
        getComputedStyle: () => ({visibility: 'visible', opacity: '1', overflowY: 'auto'}),
        Event: class Event {},
    });
}
function notifications(overrides = {}) {
    const tabs = ['评论和@', '赞和收藏', '新增关注'].map(node);
    const container = node();
    const group = {messageList: [], hasMore: false, cursor: '0', ...overrides.group};
    const root = {activeTabKey: 0, isFetching: false,
        notificationMap: {mentions: group, connections: group, likes: group}, ...overrides.root};
    const doc = {querySelector: selector => selector === '.notification-page' ? container : null,
        querySelectorAll: () => tabs};
    const run = (params = {}) => fixture('notifications', {action: 'read', source: 'mentions', ...params},
        doc, {notification: root}, '/notification');
    return {run, group, root, tabs};
}
test('notifications: a successful empty response differs from untouched group', () => {
    assert.equal(notifications().run().ready, true);
    assert.equal(notifications({group: {cursor: '', hasMore: true}}).run().ready, false);
});
test('notifications: fetching or wrong active tab cannot read stale data', () => {
    assert.equal(notifications({root: {isFetching: true}}).run().ready, false);
    assert.equal(notifications({root: {activeTabKey: 1}}).run().ready, false);
});
test('notifications: explicit page load error remains an error', () => {
    assert.match(notifications({group: {error: true}}).run().error, /加载失败/);
});
test('notifications: missing store does not become empty success', () => {
    assert.equal(notifications({root: {notificationMap: null}}).run().ready, false);
});
test('notifications: comments/replies/mentions remain distinguishable', () => {
    const messages = [
        {id: '1', type: 'comment/item', title: '评论了你的笔记', commentInfo: {content: '正文'}},
        {id: '2', type: 'comment/comment', title: '回复了你的评论',
            commentInfo: {targetComment: {content: '引用'}}},
        {id: '3', type: 'at/item', title: '在笔记中提到了你'},
        {id: '4', type: 'future/new'},
    ];
    const result = notifications({group: {messageList: messages}}).run();
    assert.deepEqual(Array.from(result.items, item => item.kind),
        ['comments', 'comments', 'mentions', 'unknown']);
    assert.equal(result.items[1].quoted_comment, '引用');
});
test('notifications: follows resolves the actual connections state key', () => {
    const f = notifications({root: {activeTabKey: 2}});
    delete f.root.notificationMap.follows;
    assert.equal(f.run({source: 'follows'}).ready, true);
});
test('notifications: real follow/you schema keeps user rather than expecting userInfo', () => {
    // 2026-09-10 实际新增关注记录结构；所有身份和令牌替换为合成值。
    const f = notifications({root: {activeTabKey: 2}, group: {messageList: [{
        id: '7683475088344472000', type: 'follow/you', title: '开始关注你了',
        user: {userid: 'a'.repeat(24), nickname: '关注者', fstatus: 'both', xsecToken: 'token'},
    }]}});
    const item = f.run({source: 'follows'}).items[0];
    assert.equal(item.user.user_id, 'a'.repeat(24));
    assert.equal(item.user.nickname, '关注者');
    assert.equal(item.user_details_complete, true);
    assert.equal(item.target, null);
});
test('notifications: real faved/item board wrapper keeps attached note and target types', () => {
    // 真实通知把收藏者的专辑作为 itemInfo，原笔记作为 attachItemInfo。
    const f = notifications({root: {activeTabKey: 1}, group: {messageList: [{
        id: '7682789430921907000', type: 'faved/item', title: '收藏了你的笔记',
        userInfo: {userid: 'a'.repeat(24), nickname: '收藏者'},
        itemInfo: {type: 'board_info', id: 'b'.repeat(24), content: '默认专辑',
            extraInfo: {desc: '隐私专辑', status: 1}, xsecToken: 'board-token',
            attachItemInfo: {type: 'note_info', id: 'c'.repeat(24), content: '原笔记',
                xsecToken: 'note-token'}},
    }]}});
    const item = f.run({source: 'likes'}).items[0];
    assert.equal(item.target.type, 'board_info');
    assert.equal(item.target.id, 'b'.repeat(24));
    assert.equal(item.attached_target.type, 'note_info');
    assert.equal(item.note_id, 'c'.repeat(24));
    assert.equal(item.note_title, '原笔记');
    assert.equal(item.note_xsec_token, 'note-token');
});
test('notifications: unknown targets do not become note IDs; missing actor is explicit', () => {
    const item = notifications({group: {messageList: [{id: '1', type: 'future/item',
        itemInfo: {type: 'future_info', id: 'b'.repeat(24)}}]}}).run().items[0];
    assert.equal(item.target.type, 'future_info');
    assert.equal(item.note_id, '');
    assert.equal(item.user_details_complete, false);
});
test('notifications: known machine type takes precedence over wording in title', () => {
    const item = notifications({group: {messageList: [{id: '1', type: 'comment/comment',
        title: '回复了提到你的评论'}]}}).run().items[0];
    assert.equal(item.kind, 'comments');
});
test('notifications: only the requested tab gets clicked', () => {
    const f = notifications();
    assert.equal(f.run({action: 'select', source: 'likes'}).selected, true);
    assert.equal(f.tabs[1].clicks, 1);
    assert.equal(f.tabs[0].clicks, undefined);
});
function relationships(label = '关注', opts = {}) {
    const username = node(opts.name || '测试用户');
    const button = node(label);
    const root = node();
    root.querySelectorAll = selector => selector === '.user-name' ? [username] : [button];
    const doc = {querySelector: selector => selector === '.user-page > .user' ? root : null};
    const run = (params = {}) => fixture('relationships', {action: 'read',
        user_id: 'a'.repeat(24), expected_name: '测试用户', ...params}, doc, {},
        '/user/profile/' + (opts.id || 'a'.repeat(24)));
    return {run, button};
}
test('relationships: mutual following counts as followed', () => {
    assert.equal(relationships('互相关注').run().state, 'followed');
    assert.equal(relationships('已关注').run().state, 'followed');
    assert.equal(relationships('回关').run().state, 'not-followed');
});
test('relationships: preview does not click', () => {
    const f = relationships();
    assert.equal(f.run().state, 'not-followed');
    assert.equal(f.button.clicks, undefined);
});
test('relationships: identity mismatch stops before mutation', () => {
    assert.match(relationships('关注', {name: '别的用户'}).run({action: 'set'}).error, /昵称/);
    assert.match(relationships('关注', {id: 'b'.repeat(24)}).run({action: 'set'}).error, /ID/);
});
test('relationships: current state race must not invert a following', () => {
    const f = relationships('已关注');
    assert.match(f.run({action: 'set', expected_state: 'not-followed',
        desired_state: 'not-followed'}).error, /发生变化/);
    assert.equal(f.button.clicks, undefined);
});
test('relationships: idempotent target never clicks', () => {
    const f = relationships('互相关注');
    assert.equal(f.run({action: 'set', desired_state: 'followed'}).unchanged, true);
    assert.equal(f.button.clicks, undefined);
});
test('relationships: valid change only clicks once', () => {
    const f = relationships();
    assert.equal(f.run({action: 'set', expected_state: 'not-followed',
        desired_state: 'followed'}).clicked, true);
    assert.equal(f.button.clicks, 1);
});
test('relationships: disabled control does not click', () => {
    const f = relationships();
    f.button.disabled = true;
    assert.match(f.run({action: 'set', expected_state: 'not-followed',
        desired_state: 'followed'}).error, /不可用/);
    assert.equal(f.button.clicks, undefined);
});
