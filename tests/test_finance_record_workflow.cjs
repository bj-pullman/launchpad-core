const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../apps/finance/static/finance/record_workflow.js'), 'utf8');

function editor() {
  const documentEvents = {}, windowEvents = {}, formEvents = {};
  let opened = 0, destination;
  const fields = new Map([['title', 'Original'], ['status', 'active'], ['csrf_token', 'token']]);
  const form = {addEventListener: (name, fn) => {formEvents[name] = fn;}};
  const buttons = {
    'record-exit-trigger': {click: () => {opened++;}},
    'record-exit-confirm': {addEventListener: (_, fn) => {buttons.exit = fn;}},
    'record-exit-modal': {addEventListener() {}}
  };
  class File {
    constructor(name = '', size = 0, lastModified = Math.random()) {
      Object.assign(this, {name, size, lastModified});
    }
  }
  class FormData {
    *[Symbol.iterator]() {
      yield* fields;
      yield ['attachment_files', new File()];
    }
  }
  const document = {
    querySelectorAll: () => [],
    querySelector: selector => selector === '[data-dirty-form]' ? form : null,
    getElementById: id => buttons[id],
    addEventListener: (name, fn) => {documentEvents[name] = fn;}
  };
  const window = {addEventListener: (name, fn) => {windowEvents[name] = fn;}, requestAnimationFrame: fn => fn()};
  const location = {href:'https://example.test/finance/records/1/edit', pathname:'/finance/records/1/edit', search:'',
    assign: href => {destination = href;}};
  vm.runInNewContext(source, {document, window, location, URL, FormData, File, setTimeout, clearTimeout});
  documentEvents.DOMContentLoaded();
  function click(extra = {}) {
    let prevented = false;
    const link = {href:'https://example.test/finance/records/1', target:'', hasAttribute:() => false};
    documentEvents.click({target:{closest:() => link}, button:0, preventDefault:() => {prevented = true;}, ...extra});
    return prevented;
  }
  function unload() {
    let prevented = false;
    windowEvents.beforeunload({preventDefault:() => {prevented = true;}});
    return prevented;
  }
  return {fields, formEvents, windowEvents, click, unload, exit:() => buttons.exit(),
    opened:() => opened, destination:() => destination};
}

test('Untouched form and restored values do not warn, including empty file inputs', () => {
  const e = editor();
  assert.equal(e.click(), false);
  assert.equal(e.unload(), false);
  e.fields.set('title', 'Changed');
  assert.equal(e.unload(), true);
  e.fields.set('title', 'Original');
  assert.equal(e.click(), false);
  e.fields.set('csrf_token', 'refreshed');
  assert.equal(e.unload(), false);
});

test('External status changes trigger custom exit modal and native unload protection', () => {
  const e = editor();
  e.fields.set('status', 'cancelled');
  assert.equal(e.click(), true);
  assert.equal(e.opened(), 1);
  assert.equal(e.destination(), undefined);
  assert.equal(e.unload(), true);
  e.exit();
  assert.equal(e.destination(), 'https://example.test/finance/records/1');
  assert.equal(e.unload(), false);
});

test('Save permits redirect; cancelled submit and history restoration retain protection', () => {
  const e = editor();
  e.fields.set('title', 'Changed');
  e.formEvents.submit({defaultPrevented:true});
  assert.equal(e.unload(), true);
  e.formEvents.submit({defaultPrevented:false});
  assert.equal(e.unload(), false);
  e.windowEvents.pageshow();
  assert.equal(e.unload(), true);
});

test('Opening links in another tab does not interrupt editing', () => {
  const e = editor();
  e.fields.set('title', 'Changed');
  assert.equal(e.click({ctrlKey:true}), false);
  assert.equal(e.opened(), 0);
});
