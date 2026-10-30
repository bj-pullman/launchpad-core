const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../apps/snipeops/media_catalog/static/js/media_catalog.js'), 'utf8');

function fixture() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set(['hidden']);
      elements.set(id, {value: '', textContent: '', innerHTML: '', disabled: false, min: '',
        focus() {}, addEventListener() {}, reportValidity: () => true, querySelectorAll: () => [],
        classList: {add: c => classes.add(c), remove: c => classes.delete(c),
          contains: c => classes.has(c), toggle(c, yes) { if (yes) classes.add(c); else classes.delete(c); }}
      });
    }
    return elements.get(id);
  }
  const context = vm.createContext({document: {
    addEventListener() {}, getElementById: element,
    querySelector: () => ({content: 'csrf-test'})
  }, window: {MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS: true}, console, Intl});
  vm.runInContext(source, context);
  const checkout = {id: 9, status: 'active', return_by_date: '2026-08-14',
    extension_min_date: '2026-08-15', extension_default_date: '2026-08-17',
    device_asset_tag: '<Device>', student_name: 'Student'};
  return {context, element, checkout};
}

test('Extension action is shown only for unreturned checkouts with management permission', () => {
  const {context, element, checkout} = fixture();
  context.renderStudentCheckouts([checkout]);
  assert.match(element('studentCheckoutsBody').innerHTML, /Extend Due Date/);
  context.renderStudentCheckouts([{...checkout, status: 'returned'}]);
  assert.doesNotMatch(element('studentCheckoutsBody').innerHTML, /Extend Due Date/);
  context.window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS = false;
  context.renderStudentCheckouts([checkout]);
  assert.doesNotMatch(element('studentCheckoutsBody').innerHTML, /Extend Due Date/);
});

test('Dashboard Needs Attention opens the extension dialog for the selected overdue checkout', async () => {
  const {context, element, checkout} = fixture();
  let click;
  const trigger = {dataset: {dashboardExtendCheckoutId: '9'}, addEventListener: (name, handler) => { click = handler; }};
  element('dashboardAttention').querySelectorAll = selector => selector === '[data-dashboard-extend-checkout-id]' ? [trigger] : [];
  const data = {summary: {overdue_checkout_count: 1}, scope_mode: 'management', attention: {overdue_checkouts: [checkout]}};
  context.renderDashboardAttention(data);
  assert.match(element('dashboardAttention').innerHTML, /Extend Due Date/);
  assert.match(element('dashboardAttention').innerHTML, /&lt;Device&gt;/);
  click();
  assert.equal(element('extendStudentCheckoutModal').classList.contains('hidden'), false);
  assert.equal(element('extendStudentCheckoutReturnBy').value, checkout.extension_default_date);
  let refreshed = 0;
  context.refreshStudentCheckoutDependentViews = async () => { refreshed++; };
  context.apiPost = async (url, body) => {
    assert.equal(url, '/api/student-checkouts/9/extend');
    assert.equal(body.expected_return_by_date, checkout.return_by_date);
    return {message: 'Due date extended.'};
  };
  await context.confirmExtendStudentCheckout();
  assert.equal(refreshed, 1);
  assert.equal(element('confirmExtendStudentCheckoutBtn').textContent, 'Extend Due Date');
  context.window.MEDIA_CATALOG_CAN_MANAGE_STUDENT_CHECKOUTS = false;
  context.renderDashboardAttention(data);
  assert.doesNotMatch(element('dashboardAttention').innerHTML, /Extend Due Date/);
});

test('Extension dialog displays escaped device context and server-provided dates', () => {
  const {context, element, checkout} = fixture();
  context.openExtendStudentCheckoutModal(checkout);
  assert.equal(element('extendStudentCheckoutReturnBy').min, '2026-08-15');
  assert.equal(element('extendStudentCheckoutReturnBy').value, '2026-08-17');
  assert.match(element('extendStudentCheckoutBody').innerHTML, /&lt;Device&gt;/);
  assert.equal(element('extendStudentCheckoutModal').classList.contains('hidden'), false);
});

test('Saving posts the new date and previous date, prevents duplicate submissions, and refreshes views', async () => {
  const {context, element, checkout} = fixture();
  let calls = 0, resolve, refreshed = 0;
  context.apiPost = (url, body) => {
    calls++;
    assert.equal(url, '/api/student-checkouts/9/extend');
    assert.equal(body.return_by_date, '2026-08-17');
    assert.equal(body.expected_return_by_date, '2026-08-14');
    return new Promise(done => { resolve = done; });
  };
  context.refreshStudentCheckoutDependentViews = async () => { refreshed++; };
  context.openExtendStudentCheckoutModal(checkout);
  const saving = context.confirmExtendStudentCheckout();
  await context.confirmExtendStudentCheckout();
  context.closeExtendStudentCheckoutModal();
  assert.equal(calls, 1);
  assert.equal(element('extendStudentCheckoutModal').classList.contains('hidden'), false);
  resolve({message: 'Checkout extended.'});
  await saving;
  assert.equal(refreshed, 1);
  assert.equal(element('extendStudentCheckoutModal').classList.contains('hidden'), true);
  assert.equal(element('confirmExtendStudentCheckoutBtn').disabled, false);
});

test('Validation and server errors retain the dialog and entered date', async () => {
  const {context, element, checkout} = fixture();
  let calls = 0;
  context.apiPost = async () => { calls++; throw new Error('The due date changed.'); };
  context.openExtendStudentCheckoutModal(checkout);
  element('extendStudentCheckoutReturnBy').value = '2026-08-14';
  await context.confirmExtendStudentCheckout();
  assert.equal(calls, 0);
  element('extendStudentCheckoutReturnBy').value = '2026-08-20';
  await context.confirmExtendStudentCheckout();
  assert.equal(element('extendStudentCheckoutStatus').textContent, 'The due date changed.');
  assert.equal(element('extendStudentCheckoutReturnBy').value, '2026-08-20');
  assert.equal(element('extendStudentCheckoutModal').classList.contains('hidden'), false);
});

test('JSON API calls include the existing CSRF token', async () => {
  const {context} = fixture();
  context.fetch = async (url, options) => {
    assert.equal(options.headers['X-CSRF-Token'], 'csrf-test');
    return {ok: true, text: async () => '{"ok":true}'};
  };
  await context.apiPost('/api/student-checkouts/9/extend', {}, 'Failed');
});
