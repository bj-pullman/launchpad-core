const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(
  path.join(__dirname, '../apps/staff_status/static/staff_status.js'),
  'utf8'
);

function themeHarness({stored = null, dark = false} = {}) {
  const storage = new Map();
  if (stored !== null) storage.set('staff_status_public_theme', stored);
  let mediaListener;
  const media = {
    matches: dark,
    addEventListener(type, listener) {
      if (type === 'change') mediaListener = listener;
    }
  };
  const buttons = ['light', 'dark', 'system'].map((preference) => ({
    dataset: {publicThemeChoice: preference},
    attributes: {},
    listeners: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(type, listener) { this.listeners[type] = listener; }
  }));
  const root = {dataset: {}};
  const document = {
    documentElement: root,
    body: {dataset: {}},
    addEventListener() {},
    querySelectorAll(selector) {
      if (selector === '[data-public-theme-control]') return [{}];
      if (selector === '[data-public-theme-choice]') return buttons;
      return [];
    }
  };
  const localStorage = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, value); }
  };
  const window = {matchMedia: () => media, localStorage};
  const context = {document, window, console, setInterval() { return 1; }, FormData};
  vm.runInNewContext(source, context);
  const api = window.StaffStatusPublicTheme;
  api.initPublicThemeControl();
  return {
    api,
    buttons,
    root,
    storage,
    mediaChange(matches) {
      media.matches = matches;
      mediaListener({matches});
    }
  };
}

test('missing and invalid preferences default to System', () => {
  for (const stored of [null, 'invalid']) {
    const harness = themeHarness({stored, dark: true});
    assert.equal(harness.root.dataset.themePreference, 'system');
    assert.equal(harness.root.dataset.theme, 'dark');
  }
});

test('stored Light and Dark preferences resolve explicitly', () => {
  const light = themeHarness({stored: 'light', dark: true});
  assert.equal(light.root.dataset.theme, 'light');
  assert.equal(light.buttons[0].attributes['aria-pressed'], 'true');

  const dark = themeHarness({stored: 'dark', dark: false});
  assert.equal(dark.root.dataset.theme, 'dark');
  assert.equal(dark.buttons[1].attributes['aria-pressed'], 'true');
});

test('theme changes apply immediately and persist locally', () => {
  const harness = themeHarness();
  harness.buttons[1].listeners.click();
  assert.equal(harness.storage.get('staff_status_public_theme'), 'dark');
  assert.equal(harness.root.dataset.theme, 'dark');
  assert.equal(harness.root.dataset.themePreference, 'dark');
});

test('System reacts to OS changes while explicit preferences ignore them', () => {
  const system = themeHarness({stored: 'system', dark: false});
  system.mediaChange(true);
  assert.equal(system.root.dataset.theme, 'dark');
  system.mediaChange(false);
  assert.equal(system.root.dataset.theme, 'light');

  for (const preference of ['light', 'dark']) {
    const explicit = themeHarness({stored: preference, dark: preference !== 'dark'});
    explicit.mediaChange(preference === 'light');
    assert.equal(explicit.root.dataset.theme, preference);
  }
});
