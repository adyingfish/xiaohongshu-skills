const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../scripts/xhs/creator_manage.js'), 'utf8');
function el(text = '', classes = []) {
    return {textContent: text, tagName: 'DIV', value: '', dataset: {}, files: [],
        classList: {contains: name => classes.includes(name)},
        getBoundingClientRect: () => ({width: 100, height: 50}),
        querySelector: () => null, querySelectorAll: () => [], getAttribute: () => null,
        contains: () => false, closest: () => null,
        click() {this.clicks = (this.clicks || 0) + 1;}};
}
function run(params, document, pathname) {
    return vm.runInNewContext(`(${script})(params)`, {params, document,
        location: {origin: 'https://creator.xiaohongshu.com', pathname},
        getComputedStyle: () => ({visibility: 'visible', opacity: '1', overflowY: 'auto'}),
        Event: class Event {}});
}
function noteFixture(note = {id: 'a'.repeat(24), display_title: '测试笔记', tab_status: 1, likes: 3}) {
    const title = el(note.display_title);
    const card = el();
    card.dataset.impression = JSON.stringify({noteTarget: {value: {noteId: note.id}}});
    card.querySelector = selector => selector === '.note-card__title' ? title : null;
    const tab = el('全部 1', ['tab-item--active']);
    const container = el();
    container.querySelectorAll = selector => selector === '.tab-list .tab-item' ? [tab] :
        selector === '.note-card' ? [card] : [];
    const auth = {userId: 'f'.repeat(24), userName: '测试账号'};
    const app = {config: {globalProperties: {$store: {state: {Auth: {userInfo: auth}}}}},
        _container: {_vnode: {component: {props: {note}}}}};
    const document = {querySelectorAll: () => [], querySelector: selector =>
        selector === '.notes-container' ? container : selector === '#app' ? {__vue_app__: app} : null};
    return {card, title, auth, read: (params = {}) => run({action: 'notes-read', status: 'all', ...params}, document,
        '/new/note-manager')};
}
test('managed notes: stable DOM id associates real component note props', () => {
    const result = noteFixture().read();
    assert.equal(result.items[0].note_id, 'a'.repeat(24));
    assert.equal(result.items[0].status, 'published');
    assert.equal(result.items[0].stats.likes, 3);
    assert.equal(result.complete, true);
});
test('managed notes: missing stable id is an error', () => {
    const f = noteFixture();
    f.card.dataset.impression = '{}';
    assert.match(f.read().error, /稳定 ID/);
});
test('managed notes: stale title must not be joined to a different note', () => {
    const f = noteFixture();
    f.title.textContent = '其他标题';
    assert.equal(f.read().ready, false);
});
test('managed notes: unknown numeric status is retained without guessing', () => {
    const result = noteFixture({id: 'a'.repeat(24), display_title: '审核中只是标题', tab_status: 88}).read();
    assert.equal(result.items[0].status, 'unknown');
    assert.equal(result.items[0].raw_status, 88);
});
function draftFixture() {
    const edit = el('编辑');
    const remove = el('删除');
    const title = el('测试草稿', ['has-title']);
    const card = el();
    card.getAttribute = name => ({'data-draft-id': 'draft-uuid', 'data-draft-type': 'image'}[name] || null);
    card.querySelector = selector => selector === '.draft-title-text' ? title : null;
    card.querySelectorAll = selector => selector === '.draft-actions .btn' ? [edit, remove] : [];
    const tab = el('图文笔记(1)', ['active']);
    const list = el();
    const drawer = el();
    drawer.querySelector = selector => selector === '.draft-list' ? list : null;
    drawer.querySelectorAll = selector => selector === '.tab-item' ? [tab] :
        selector === '.draft-item[data-draft-id]' ? [card] : [];
    const controls = [];
    const auth = {userId: 'f'.repeat(24), userName: '测试账号'};
    const app = {config: {globalProperties: {$store: {state: {Auth: {userInfo: auth}}}}}};
    const document = {querySelector: s => s === '#app' ? {__vue_app__: app} : null,
        querySelectorAll: selector => selector === '.d-drawer' ? [drawer] :
            selector.startsWith('input:not') ? controls : []};
    const invoke = params => run({kind: 'image', ...params}, document, '/publish/publish');
    return {invoke, edit, remove, controls, tab, drawer, card, auth};
}
test('drafts: list reads real UUID and title, not only tab count', () => {
    const result = draftFixture().invoke({action: 'draft-read'});
    assert.equal(result.items[0].draft_id, 'draft-uuid');
    assert.equal(result.items[0].title, '测试草稿');
    assert.equal(result.complete, true);
});
test('drafts: count without actual rows is not a successful list', () => {
    const f = draftFixture();
    f.drawer.querySelectorAll = selector => selector === '.tab-item' ? [f.tab] : [];
    assert.equal(f.invoke({action: 'draft-read'}).ready, false);
});
test('drafts: exact identity mismatch never clicks edit or delete', () => {
    const f = draftFixture();
    assert.match(f.invoke({action: 'draft-open', draft_id: 'other',
        expected_title: '测试草稿'}).error, /未同时匹配/);
    assert.equal(f.edit.clicks, undefined);
    assert.equal(f.remove.clicks, undefined);
});
test('drafts: only matching edit button is clicked', () => {
    const f = draftFixture();
    assert.equal(f.invoke({action: 'draft-open', draft_id: 'draft-uuid',
        expected_title: '测试草稿'}).clicked, true);
    assert.equal(f.edit.clicks, 1);
    assert.equal(f.remove.clicks, undefined);
});
test('drafts: existing editor text blocks navigation and opening', () => {
    const f = draftFixture();
    const input = el();
    input.tagName = 'INPUT'; input.value = '未保存正文'; f.controls.push(input);
    assert.equal(f.invoke({action: 'guard'}).safe_to_navigate, false);
    assert.match(f.invoke({action: 'draft-open', draft_id: 'draft-uuid',
        expected_title: '测试草稿'}).error, /已有内容/);
    assert.equal(f.edit.clicks, undefined);
});

test('creator identity: only account id and name are included in the response', () => {
    const f = noteFixture();
    f.auth.phone = 'private-test-value';
    const result = f.read();
    assert.equal(result.account_id, 'f'.repeat(24));
    assert.equal(result.account_name, '测试账号');
    assert.equal(JSON.stringify(result).includes('private-test-value'), false);
});
test('creator identity: changed account is rejected before returning records', () => {
    const f = noteFixture();
    f.auth.userId = 'b'.repeat(24);
    assert.match(f.read({account_id: 'f'.repeat(24)}).error, /账号发生变化/);
});
test('creator identity: missing account cannot become own-note success', () => {
    const f = noteFixture();
    delete f.auth.userId;
    assert.equal(f.read().ready, false);
});
test('creator identity: draft account change never clicks the editor', () => {
    const f = draftFixture();
    f.auth.userId = 'b'.repeat(24);
    assert.match(f.invoke({action: 'draft-open', draft_id: 'draft-uuid',
        expected_title: '测试草稿', account_id: 'f'.repeat(24)}).error, /账号发生变化/);
    assert.equal(f.edit.clicks, undefined);
});
