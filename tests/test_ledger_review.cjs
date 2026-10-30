const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../apps/finance/static/finance/ledger_review.js'), 'utf8');

function harness(recordCount = 1) {
  const events = {}, modalEvents = {}, requests = [], timers = new Map();
  let timerId = 0, submitted = 0;
  class Option { constructor(text, value) { this.text = text; this.value = String(value); } }
  const feedback = {textContent: ''};
  const select = {
    options: [], value: '',
    replaceChildren(...options) { this.options = options; this.value = ''; },
    append(fragment) { this.options.push(...fragment.options); },
    add(option) { this.options.push(option); }
  };
  const query = {value: '', focus() {}, matches: s => s === '[data-review-record-query]', closest: () => form};
  const message = {textContent: ''}, link = {disabled: true};
  const fields = new Map([['ledger_id', '42'], ['row_version', 'version'], ['csrf_token', 'token'], ['action', 'link']]);
  const elements = {
    '[data-review-record-select]': select, '[data-review-record-query]': query,
    '[data-review-picker-message]': message, '[data-review-link-button]': link
  };
  const form = {
    isConnected: true, dataset: {searchUrl: '/finance/Technology/records/search?all=1'},
    elements: Object.fromEntries(Array.from(fields, ([key, value]) => [key, {value}])),
    matches: s => ['[data-review-action]', '[data-review-link-form]'].includes(s),
    querySelector: s => elements[s], querySelectorAll: () => [link]
  };
  select.matches = s => s === '[data-review-record-select]';
  select.closest = () => form;
  const modalNodes = Object.fromEntries(['#ledger-record-title', '[data-ledger-modal-subtitle]',
    '[data-ledger-modal-description]', '[data-ledger-modal-context]', '[data-ledger-match]',
    '[data-ledger-picker]', '[data-ledger-create-help]', '[data-ledger-modal-message]', '.finance-modal-dialog']
    .map(key => [key, {textContent: '', focus() {}}]));
  const modal = {hidden: true, querySelector: s => s === 'form' ? form : (modalNodes[s] || elements[s]),
    addEventListener: (name, fn) => { modalEvents[name] = fn; }};
  const oldResults = {dataset: {currentUrl: '/finance/Technology/ledger/review?page=2&per_page=10&vendor_q=Adobe'}};
  const root = {
    dataset: {},
    querySelector: s => ({
      '[data-review-message]': feedback,
      '[data-review-results]': oldResults,
      '[data-review-filters]': {requestSubmit() { submitted++; }},
      '[data-review-initial-records]': {
        content: {cloneNode: () => ({options: Array.from({length: recordCount}, (_, i) => new Option(`Existing record ${i}`, i + 7))})}
      }
    })[s],
    addEventListener: (name, fn) => { events[name] = fn; },
    setAttribute() {}, removeAttribute() {}
  };
  class FormData {
    constructor() {
      this.fields = new Map(Object.entries(form.elements).map(([key, item]) => [key, String(item.value)]));
      if (!select.disabled) this.fields.set('record_id', select.value);
    }
    set(key, value) { this.fields.set(key, value); }
    get(key) { return this.fields.get(key); }
  }
  vm.runInNewContext(source, {
    document: {querySelector: s => s === '[data-ledger-modal]' ? modal : root,
      body: {append() {}, classList: {add() {}, remove() {}}}}, Option, URL, AbortController, FormData,
    location: {origin: 'https://example.test'},
    setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    fetch(url, options) {
      return new Promise((resolve, reject) => requests.push({url: String(url), options, resolve, reject}));
    }
  });
  const settle = () => new Promise(resolve => setImmediate(resolve));
  async function respond(index, data, status = 200) {
    requests[index].resolve({ok: status < 400, redirected: false, status,
      headers: {get: () => 'application/json'}, json: async () => data});
    await settle();
  }
  function type(text) { query.value = text; modalEvents.input({target: query}); }
  function tick() { for (const [id, fn] of timers) { timers.delete(id); fn(); } }
  function open(mode = 'link') {
    const button = {dataset: {ledgerOpen: mode, transaction: JSON.stringify({id: 42, version: 'version',
      vendor: 'Vendor', label: 'Description', po: '123', date: '08/01/2026'})}};
    events.click({target: {closest: s => s === '[data-ledger-open]' ? button : null}});
  }
  function submit(action = 'link') {
    return events.submit({target: form, preventDefault() {}, submitter: {name: 'action', value: action}});
  }
  return {events, modalEvents, modal, root, requests, feedback, select, query, message, link, form,
    open, type, tick, respond, settle, submit, get submitted() { return submitted; }};
}

test('Opening the picker immediately displays all database-provided options beyond 50', () => {
  const h = harness(126); h.open();
  assert.equal(h.select.options.length, 127);
  assert.equal(h.select.options[1].value, '7');
  assert.equal(h.requests.length, 0);
  assert.equal(h.select.options[126].value, '132');
  assert.match(h.message.textContent, /126 available Records/);
  assert.equal(h.link.disabled, true);
  h.select.value = '7'; h.modalEvents.change({target: h.select});
  assert.equal(h.link.disabled, false);
});

test('Typing clears a stale selection immediately and rejects out-of-order search responses', async () => {
  const h = harness(); h.open(); h.select.value = '7';
  h.type('old'); h.tick();
  h.type('new');
  assert.equal(h.select.value, '');
  assert.equal(h.link.disabled, true);
  assert.equal(h.requests[0].options.signal.aborted, true);
  h.tick();
  await h.respond(1, {rows: [{id: 9, label: 'New match'}], page: 1, has_more: false});
  await h.respond(0, {rows: [{id: 8, label: 'Old match'}], page: 1, has_more: false});
  assert.deepEqual(h.select.options.map(o => o.value), ['', '9']);
  assert.match(h.requests[1].url, /q=new/);
});

test('Search requests and displays every matching record without a page limit', async () => {
  const h = harness(); h.open(); h.type('match'); h.tick();
  assert.match(h.requests[0].url, /all=1/);
  const rows = Array.from({length: 125}, (_, i) => ({id: i + 1, label: `Match ${i}`}));
  await h.respond(0, {rows, page: 1, has_more: false});
  assert.equal(h.select.options.length, 126);
  assert.equal(h.select.options[125].value, '125');
  assert.match(h.message.textContent, /125 matching Records/);
});

test('Review submissions carry CSRF, transaction version, selected ID and filtered page', async () => {
  const h = harness(); h.open(); h.select.value = '7';
  const pending = h.submit();
  const request = h.requests[0];
  assert.match(request.url, /page=2&per_page=10&vendor_q=Adobe/);
  assert.equal(request.options.method, 'POST');
  for (const [key, value] of [['csrf_token','token'], ['ledger_id','42'], ['row_version','version'], ['record_id','7'], ['action','link']]) {
    assert.equal(request.options.body.get(key), value);
  }
  await h.respond(0, {ok: false, message: 'The transaction changed.'}, 409);
  await pending;
  assert.equal(h.feedback.textContent, 'The transaction changed.');
  assert.equal(h.select.value, '7');
  assert.equal(h.link.disabled, false);
});

test('Unknown save outcomes block repeated actions until the review is refreshed', async () => {
  const h = harness(); h.open();
  const pending = h.submit('ignore');
  h.requests[0].reject(new Error('Network lost'));
  await pending;
  assert.match(h.feedback.textContent, /may have succeeded/);
  await h.submit('ignore');
  assert.equal(h.requests.length, 1);
  assert.match(h.feedback.textContent, /Refresh the Ledger/);
});

test('Create Record mode does not require selecting an existing record', async () => {
  const h = harness(); h.open('create');
  assert.equal(h.modal.hidden, false);
  assert.equal(h.select.required, false);
  assert.equal(h.select.disabled, true);
  assert.equal(h.link.disabled, false);
  const pending = h.submit('create');
  assert.equal(h.requests[0].options.body.get('action'), 'create');
  assert.equal(h.requests[0].options.body.get('record_id'), undefined);
  await h.respond(0, {ok: false, message: 'A Record already uses this PO.'}, 409);
  await pending;
  assert.equal(h.modal.hidden, false);
  assert.equal(h.link.disabled, false);
});

test('Normal Ledger uses the shared Record action endpoint', async () => {
  const h = harness(); h.root.dataset.actionUrl = '/finance/Technology/ledger/record-action';
  h.open(); h.select.value = '7';
  const pending = h.submit();
  assert.equal(h.requests[0].url, h.root.dataset.actionUrl);
  await h.respond(0, {ok: false, message: 'Stale transaction'}, 409);
  await pending;
});

test('Opening another transaction aborts pending searches and resets the selection', async () => {
  const h = harness(); h.open(); h.type('old'); h.tick();
  h.open('create');
  assert.equal(h.requests[0].options.signal.aborted, true);
  await h.respond(0, {rows: [{id: 99, label: 'Old result'}], page: 1, has_more: false});
  assert.deepEqual(h.select.options.map(o => o.value), ['', '7']);
  assert.equal(h.link.disabled, false);
});

test('Page-size changes submit the server-side filter form', () => {
  const h = harness();
  h.events.change({target: {matches: s => s === '[data-review-page-size]'}});
  assert.equal(h.submitted, 1);
});
