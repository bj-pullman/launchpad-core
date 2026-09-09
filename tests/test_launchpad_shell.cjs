const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/launchpad-shell.js'), 'utf8');

function shell({preference='system', dark=true, keepActive=true}={}) {
  let now=0, timer, mediaListener;
  const listeners={}, calls=[];
  const root={dataset:{themePreference:preference}};
  const media={matches:dark, addEventListener:(type, fn)=>{mediaListener=fn;}};
  const metadata={'launchpad-csrf':'csrf','launchpad-keep-active':String(keepActive),
    'launchpad-theme-url':'/account/theme','launchpad-activity-url':'/auth/session/activity'};
  const document={hidden:false,documentElement:root,body:{removeAttribute(){}},
    querySelector:selector=>({content:metadata[selector.match(/name="([^"]+)"/)[1]]}),
    querySelectorAll:()=>[],addEventListener:(type,fn)=>{listeners[type]=fn;}};
  const window={fetch:async (url,init)=>{calls.push({url,init});return {ok:true,status:204};}};
  const context={document,window,matchMedia:()=>media,Date:{now:()=>now},
    URL,URLSearchParams,Headers,Request,location:{origin:'https://example.test',href:'https://example.test/page'},
    setInterval:fn=>{timer=fn;return 1;},clearInterval:()=>{timer=undefined;}};
  Object.defineProperty(context,'fetch',{get:()=>window.fetch});
  vm.runInNewContext(source,context);
  return {root,media,document,calls,listeners,window,advance:n=>{now+=n;},tick:()=>timer?.(),
    mediaChange:dark=>{media.matches=dark;mediaListener();},hasTimer:()=>!!timer};
}

test('System follows OS changes; explicit themes override OS',()=>{
  const system=shell();assert.equal(system.root.dataset.theme,'dark');
  system.mediaChange(false);assert.equal(system.root.dataset.theme,'light');
  for(const preference of ['light','dark']) {
    const explicit=shell({preference});explicit.mediaChange(preference==='light');
    assert.equal(explicit.root.dataset.theme,preference);
  }
});
test('Idle, hidden and synthetic activity never heartbeat',async()=>{
  const s=shell();s.advance(61000);await s.tick();assert.equal(s.calls.length,0);
  s.listeners.pointermove({isTrusted:false});await s.tick();assert.equal(s.calls.length,0);
  s.listeners.keydown({isTrusted:true});s.document.hidden=true;await s.tick();assert.equal(s.calls.length,0);
  s.document.hidden=false;await s.tick();assert.equal(s.calls.length,1);
  assert.equal(s.calls[0].url,'/auth/session/activity');
  s.advance(61000);await s.tick();assert.equal(s.calls.length,1);
});
test('Disabled keepalive installs no heartbeat',()=>assert.equal(shell({keepActive:false}).hasTimer(),false));
test('Polling requests are marked background without refreshing client activity',async()=>{
  const s=shell();s.advance(61000);
  await s.window.fetch('/poll');assert.equal(s.calls[0].init.headers.get('X-Launchpad-Background'),'1');
  await s.tick();assert.equal(s.calls.length,1);
  s.listeners.keydown({isTrusted:true});await s.window.fetch('/search');
  assert.equal(s.calls[1].init.headers.get('X-Launchpad-Background'),'0');
});
test('Theme persists through the existing endpoint before applying selection',async()=>{
  const s=shell({preference:'light'});
  await s.listeners.click({target:{closest:()=>({dataset:{themeChoice:'system'}})}});
  assert.equal(s.calls[0].url,'/account/theme');
  assert.equal(s.calls[0].init.body.get('theme_preference'),'system');
  assert.equal(s.root.dataset.themePreference,'system');
});
