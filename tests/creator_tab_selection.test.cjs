const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const background = fs.readFileSync(path.join(__dirname, '..', 'extension', 'background.js'), 'utf8');
const start = background.indexOf('async function getExistingCreatorTab(');
const end = background.indexOf('async function getOrOpenXhsTab()', start);
assert.ok(start >= 0 && end > start);
const source = background.slice(start, end);

function selector(activeTab, byId = {}) {
  const chrome = {
    tabs: {
      query: async () => [activeTab],
      get: async id => byId[id],
    },
  };
  return Function('chrome', `${source}\nreturn getExistingCreatorTab;`)(chrome);
}

test('active home does not silently select a background creator draft', async () => {
  const pick = selector({id: 1, url: 'https://www.xiaohongshu.com/explore'}, {
    2: {id: 2, url: 'https://creator.xiaohongshu.com/publish/publish'},
  });
  await assert.rejects(() => pick(), /不是图文创作页/);
  assert.equal((await pick(2)).id, 2);
});

test('active creator is selected; wrong explicit id is rejected', async () => {
  const creator = {id: 8, url: 'https://creator.xiaohongshu.com/publish/publish?source=official'};
  const pick = selector(creator, {9: {id: 9, url: 'https://www.xiaohongshu.com/'}});
  assert.equal((await pick()).id, 8);
  await assert.rejects(() => pick(9), /不是图文创作页/);
  await assert.rejects(() => pick(-1), /无效/);
});

test('current-tab status reads active home, never a background draft', async () => {
  const calls = [];
  const chrome = {
    tabs: {query: async options => {
      calls.push(options);
      return [{id: 3, url: 'https://www.xiaohongshu.com/explore'}];
    }},
    scripting: {executeScript: async options => {
      calls.push(options);
      return [{result: {url: 'https://www.xiaohongshu.com/explore', page_type: 'home',
        visible_editor_count: 0, title: null, images: null}}];
    }},
  };
  const inspect = Function('chrome', `${source}\nreturn cmdInspectCurrentXhsTab;`)(chrome);
  const result = await inspect();
  assert.equal(result.page_type, 'home');
  assert.equal(result.tab_id, 3);
  assert.equal(calls[1].target.tabId, 3);
  assert.deepEqual(calls[0], {active: true, lastFocusedWindow: true});
});

test('current-tab status omits URL and DOM read on other sites', async () => {
  let scriptCalls = 0;
  const chrome = {
    tabs: {query: async () => [{id: 7, url: 'https://example.com/private'}]},
    scripting: {executeScript: async () => {scriptCalls++;}},
  };
  const inspect = Function('chrome', `${source}\nreturn cmdInspectCurrentXhsTab;`)(chrome);
  assert.deepEqual(await inspect(), {tab_id: 7, active: true, page_type: 'other', url: null});
  assert.equal(scriptCalls, 0);
});

test('multiple creator drafts require the active tab or an explicit id', async () => {
  const first = {id: 10, url: 'https://creator.xiaohongshu.com/publish/publish?draft=one'};
  const second = {id: 11, url: 'https://creator.xiaohongshu.com/publish/publish?draft=two'};
  const pick = selector(first, {11: second});
  assert.equal((await pick()).id, 10);
  assert.equal((await pick(11)).id, 11);
});
