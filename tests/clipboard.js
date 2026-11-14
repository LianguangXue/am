// Run with: node tests/clipboard.js. No browser or third-party packages needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../bin/am'), 'utf8');
const start = source.indexOf('async function copy(text){');
const end = source.indexOf('\nfunction matches(', start);
assert(start >= 0 && end > start, 'dashboard copy handler must be present');
const handler = source.slice(start, end);

function fixture(clipboard, legacyResult = true) {
  const messages = [], prompts = [];
  const state = {attached:false, selected:false, removed:false, restored:false, legacyCalls:0};
  const field = {
    style: {}, value:'',
    select() { state.selected = true; },
    setSelectionRange(a, b) { assert.equal(a, 0); assert.equal(b, field.value.length); },
    remove() { state.removed = true; state.attached = false; },
  };
  const context = vm.createContext({
    navigator: {clipboard},
    toast: text => messages.push(text),
    window: {prompt: (title, text) => prompts.push(text)},
    document: {
      activeElement: {focus() { state.restored = true; }},
      createElement(tag) { assert.equal(tag, 'textarea'); return field; },
      body: {append(element) { assert.equal(element, field); state.attached = true; }},
      execCommand(command) {
        state.legacyCalls++;
        assert.equal(command, 'copy');
        assert(state.attached && state.selected);
        if (legacyResult instanceof Error) throw legacyResult;
        return legacyResult;
      },
    },
  });
  vm.runInContext(handler, context);
  return {copy:context.copy, messages, prompts, state, field};
}

(async () => {
  const text = 'am adopt 中文-session\nsecond line';
  // Reproduce the old HTTP behavior: success toast despite no clipboard write.
  const original = fixture(undefined);
  const oldContext = vm.createContext({navigator:{}, toast: t => original.messages.push(t)});
  vm.runInContext("function oldCopy(text){ if(navigator.clipboard) navigator.clipboard.writeText(text); toast('已复制 ' + text); }",
    oldContext);
  oldContext.oldCopy(text);
  assert.deepEqual(original.messages, ['已复制 ' + text]);
  assert.equal(original.state.legacyCalls, 0, 'old HTTP handler falsely reports success');

  let release;
  const written = [];
  const modern = fixture({writeText: value => {
    written.push(value); return new Promise(resolve => { release = resolve; });
  }});
  const pending = modern.copy(text);
  assert.equal(modern.messages.length, 0, 'success must await clipboard completion');
  release(); await pending;
  assert.deepEqual(written, [text]);
  assert.deepEqual(modern.messages, ['已复制 ' + text]);
  assert.equal(modern.state.legacyCalls, 0);

  for (const clipboard of [undefined, {}, {writeText: async () => { throw Error('denied'); }}]) {
    const fallback = fixture(clipboard);
    await fallback.copy(text);
    assert.equal(fallback.field.value, text);
    assert.equal(fallback.state.legacyCalls, 1);
    assert(fallback.state.removed && fallback.state.restored);
    assert.deepEqual(fallback.messages, ['已复制 ' + text]);
    assert.deepEqual(fallback.prompts, []);
  }
  for (const result of [false, Error('disabled')]) {
    const failure = fixture(undefined, result);
    await failure.copy(text);
    assert.deepEqual(failure.messages, ['自动复制失败，请手动复制']);
    assert.deepEqual(failure.prompts, [text]);
    assert(failure.state.removed && failure.state.restored);
  }
  console.log('PASS: clipboard completion, HTTP fallback, denied permission, failure, cleanup, exact text');
})().catch(error => { console.error(error); process.exitCode = 1; });
