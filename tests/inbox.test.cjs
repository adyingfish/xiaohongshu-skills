const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const source = readFileSync(join(__dirname, '../scripts/xhs/inbox.js'), 'utf8');
const peer = 'bbbbbbbbbbbbbbbbbbbbbbbb';
const account = 'aaaaaaaaaaaaaaaaaaaaaaaa';

function element(text = '', attrs = {}, selectors = {}, classes = []) {
    return {
        textContent: text, children: [], events: [], scrollTop: 0, scrollHeight: 100,
        classList: {contains: name => classes.includes(name)},
        getBoundingClientRect: () => ({width: 100, height: 100}),
        getAttribute: name => attrs[name] ?? null,
        querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
        querySelectorAll: selector => selectors[selector] || [],
        cloneNode: () => element(text),
        dispatchEvent(event) { this.events.push(event.type); },
    };
}

function fixture() {
    const list = element();
    const active = element('', {'data-conv-id': peer}, {
        '.xhs-im-conv-item__name': [element('朋友')],
    });
    const nodes = {
        '.xhs-im-view': [element()],
        '.xhs-im-conv-list__scroll': [element()],
        '.xhs-im-msg-list': [list],
        '.xhs-im-conv-item--active[data-conv-kind="c2c"]': [active],
        '.xhs-im-chat-window__header-name': [element('朋友')],
        '.xhs-im-chat-window .xhs-im-input-bar-editor': [], // 被禁发也仍允许读取历史。
    };
    const context = {
        window: {__INITIAL_STATE__: {user: {userInfo: {value: {userId: account}}, loggedIn: true}}},
        location: {origin: 'https://www.xiaohongshu.com', pathname: `/chat/${peer}`},
        document: {
            querySelectorAll: selector => nodes[selector] || [],
            querySelector: selector => nodes[selector]?.[0] || null,
        },
        getComputedStyle: () => ({visibility: 'visible'}),
        Event: class {constructor(type) {this.type = type;}},
    };
    const execute = params => JSON.parse(JSON.stringify(runInNewContext(
        `(${source})(${JSON.stringify({user_id: peer, expected_name: '朋友', ...params})})`, context)));
    return {list, nodes, execute, context};
}

function message(id, text, own = false, image = false) {
    const body = element(text);
    const picture = Object.assign(element('', {src: 'https://example.org/picture.png'}), {alt: '图片'});
    const bubble = element('', {}, {img: image ? [picture] : []});
    return element('', {'data-message-id': id, 'data-store-id': id, 'data-content-type': image ? '2' : '1'}, {
        '.chat-item__bubble': [bubble],
        [own ? '.chat-item__bubble--me' : '.chat-item__bubble--other']: [bubble],
        '.xhs-im-bubble__text': image ? [] : [body],
    }, ['chat-item']);
}

function propsTree(f, components) {
    f.nodes['#app'] = [{__vue_app__: {_container: {_vnode: {
        children: Object.entries(components).map(([name, props]) => ({
            component: {type: {name}, props, subTree: null},
        })),
    }}}}];
}

function rawMessage(id, content, outgoing = false, contentType = 1) {
    return {messageId: id, storeId: Number(id), chatId: peer,
        senderId: outgoing ? account : peer, receiverId: outgoing ? peer : account,
        createTime: 1788948450000 + Number(id), contentType, isLocalMsg: false,
        content: JSON.stringify({content, content_type: contentType}),
    };
}

test('读取真实 DOM 字段、方向、时间标签，不要求输入框可用', () => {
    const f = fixture();
    f.list.children = [element('昨天 18:07', {}, {}, ['xhs-im-msg-list__time-divider']),
        message('1', '对方来信'), message('2', '我的回复', true)];
    const state = f.execute({action: 'snapshot'});
    assert.equal(state.conversation_ready, true);
    const result = f.execute({action: 'messages'});
    assert.equal(result.account_id, account);
    assert.deepEqual(result.messages.map(m => m.direction), ['incoming', 'outgoing']);
    assert.equal(result.messages[0].time_label, '昨天 18:07');
    assert.equal(result.messages[0].timestamp_ms, null);
    assert.equal(result.complete, false);
});

test('图片来信保留方向和媒体地址；系统欢迎语不误判待回复', () => {
    const f = fixture();
    f.list.children = [message('1', '', false, true),
        message('2', '我们已相互关注，开始聊天吧[偷笑R]')];
    const result = f.execute({action: 'messages'});
    assert.equal(result.messages[0].kind, 'image');
    assert.equal(result.messages[0].direction, 'incoming');
    assert.equal(result.messages[0].images.length, 1);
    assert.equal(result.messages[1].direction, 'unknown');
    assert.equal(result.messages[1].kind, 'system_candidate');
});

test('读取和翻页均核对会话；无发送及输入事件', () => {
    const f = fixture();
    assert.match(f.execute({action: 'messages', expected_name: '不匹配'}).error, /昵称/);
    assert.match(f.execute({action: 'scroll', target: 'messages', user_id: account}).error, /会话/);
    assert.equal(f.list.events.length, 0);
    assert.equal(f.execute({action: 'scroll', target: 'messages'}).scrolled, true);
    assert.deepEqual(f.list.events, ['scroll']);
});

test('错误站点或缺失页面结构不能返回空列表成功', () => {
    const f = fixture();
    f.context.location.origin = 'https://example.org';
    assert.match(f.execute({action: 'list'}).error, /未就绪/);
    f.context.location.origin = 'https://www.xiaohongshu.com';
    f.nodes['.xhs-im-view'] = [];
    assert.match(f.execute({action: 'messages'}).error, /未就绪/);
});

test('会话列表读取预览、显示时间；未证实未读字段不虚构数值', () => {
    const f = fixture();
    f.nodes['.xhs-im-conv-item[data-conv-kind="c2c"]'] = [element('', {'data-conv-id': peer}, {
        '.xhs-im-conv-item__name': [element('朋友')],
        '.xhs-im-conv-item__summary-text': [element('还需要处理吗？')],
        '.xhs-im-conv-item__time': [element('昨天')],
    })];
    const result = f.execute({action: 'list'});
    assert.equal(result.conversations[0].preview, '还需要处理吗？');
    assert.equal(result.conversations[0].time_label, '昨天');
    assert.equal(result.conversations[0].unread_count, null);
});

test('读取真实会话 props 中的未读、时间与草稿，不能把 peerUserId 当成会话对象', () => {
    const f = fixture();
    propsTree(f, {IMView: {currentUserId: account}, ConversationList: {
        isLoading: false, isUnreadInitialized: true, totalUnread: 5,
        convList: [{id: peer, peerUserId: account, kind: 'c2c', name: '朋友',
            lastMessage: '请回复', lastMessageAt: 1788948450000, unreadCount: 5, hasDraft: true}],
    }});
    const result = f.execute({action: 'list'});
    assert.equal(result.source, 'vue_component_props');
    assert.equal(result.conversations[0].user_id, peer);
    assert.equal(result.conversations[0].unread_count, 5);
    assert.equal(result.conversations[0].timestamp_ms, 1788948450000);
    assert.equal(result.conversations[0].has_draft, true);
    assert.equal(result.total_unread, 5);
    assert.equal(result.complete, false); // 没有会话总数/结束字段。
});

test('消息 props 补齐收发者、毫秒时间、历史结束和隐藏控制消息', () => {
    const f = fixture();
    f.list.children = [message('2', '普通来信'), message('3', '我的回复', true)];
    propsTree(f, {IMView: {currentUserId: account}, ChatWindow: {
        conv: {id: peer}, hasMoreHistory: false, isLoadingMessages: false,
        messages: [rawMessage('1', '', true, 0), rawMessage('2', '普通来信'),
            rawMessage('3', '我的回复', true)],
    }});
    const result = f.execute({action: 'messages'});
    assert.equal(result.complete, true);
    assert.equal(result.messages.length, 3);
    assert.equal(result.messages[0].kind, 'system');
    assert.equal(result.messages[1].direction, 'incoming');
    assert.equal(result.messages[1].sender_id, peer);
    assert.equal(result.messages[1].timestamp_ms, 1788948450002);
    assert.equal(result.messages[2].direction, 'outgoing');
});

test('加载中不可误报空列表或历史已完整', () => {
    const f = fixture();
    propsTree(f, {ChatWindow: {conv: {id: peer}, hasMoreHistory: false,
        isLoadingMessages: true, messages: []}});
    assert.equal(f.execute({action: 'snapshot'}).conversation_ready, false);
    const messages = f.execute({action: 'messages'});
    assert.equal(messages.loading, true);
    assert.equal(messages.complete, false);
    propsTree(f, {ConversationList: {isLoading: true, convList: []}});
    assert.equal(f.execute({action: 'snapshot'}).ready, false);
    assert.equal(f.execute({action: 'list'}).loading, true);
});

test('组件账号不一致停止；未知消息保留内容，未落库发送不算已回复', () => {
    const f = fixture();
    propsTree(f, {IMView: {currentUserId: peer}});
    assert.match(f.execute({action: 'snapshot'}).error, /账号/);
    propsTree(f, {ChatWindow: {conv: {id: peer}, hasMoreHistory: true,
        messages: [rawMessage('1', {card_title: '未知卡片'}, false, 999),
            {...rawMessage('2', '本地发送中', true), storeId: 0, isLocalMsg: true}],
    }});
    const result = f.execute({action: 'messages'});
    const unknown = result.messages.find(m => m.message_id === '1');
    assert.equal(unknown.kind, 'unknown');
    assert.equal(unknown.content.content.card_title, '未知卡片');
    assert.equal(result.messages.find(m => m.message_id === '2').pending, true);
    assert.equal(result.complete, false);
});

test('组件目标正确但残留另一个会话消息时拒绝读取，不误判本会话已回复', () => {
    const f = fixture();
    const other = 'cccccccccccccccccccccccc';
    propsTree(f, {ChatWindow: {conv: {id: peer}, hasMoreHistory: false,
        messages: [{...rawMessage('1', '发往另一会话', true), chatId: other, receiverId: other}],
    }});
    assert.match(f.execute({action: 'messages'}).error, /会话归属/);
});

test('发送者为自己但接收者不是目标时，不认作已回复', () => {
    const f = fixture();
    propsTree(f, {ChatWindow: {conv: {id: peer}, hasMoreHistory: false,
        messages: [{...rawMessage('1', '错误接收者', true), receiverId: 'c'.repeat(24)}],
    }});
    assert.equal(f.execute({action: 'messages'}).messages[0].direction, 'unknown');
});

test('缺失组件及空 DOM 不可作为成功空列表，明确加载完的空历史才可返回', () => {
    const f = fixture();
    assert.match(f.execute({action: 'messages'}).error, /加载失败/);
    assert.match(f.execute({action: 'list'}).error, /加载失败/);
    propsTree(f, {ChatWindow: {conv: {id: peer}, hasMoreHistory: false, messages: []}});
    assert.match(f.execute({action: 'messages'}).error, /加载状态/);
    propsTree(f, {ChatWindow: {conv: {id: peer}, hasMoreHistory: false,
        isLoadingMessages: false, messages: []}});
    const empty = f.execute({action: 'messages'});
    assert.equal(empty.complete, true);
    assert.deepEqual(empty.messages, []);
});
