'use strict';
// Real-browser tests for the shipped ui/ (index.html, styles.css, module.js).
// !!! SIMULATED: the Cluster Admin core bridge ($root events, apiUrl, token) and the
// !!! NS8 task backend are fixtures written in this file. No real NS8 host is contacted.
//
// Run:  node tests/ui-browser.cjs
// Env:  PLAYWRIGHT_MODULE  path/name of the playwright module (default: "playwright")
//       CHROME_EXECUTABLE  chromium binary (default: Playwright's own browser)
//       NS8_CORE_CSS       REQUIRED path to the real Cluster Admin core.css
//       UI_DIR             directory of the shipped UI (default: ../ui)
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const EXPECTED_TESTS = 20;
const UI_DIR = path.resolve(process.env.UI_DIR || path.join(__dirname, '..', 'ui'));
const ORIGIN = 'http://ns8.test';
const APP = '/cluster-admin/apps/no-s81c2/';
const TOKEN = 'SIMULATED-TOKEN-0123456789';

const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

// NS8_CORE_CSS is REQUIRED: the real Cluster Admin core.css (no fallback stub).
const CORE_CSS = process.env.NS8_CORE_CSS;
if (!CORE_CSS || !fs.existsSync(CORE_CSS) || fs.statSync(CORE_CSS).size < 100000) {
  console.error('NS8_CORE_CSS must point to the real Cluster Admin core.css (e.g. extracted from the pinned core image)');
  process.exit(2);
}

const OK_STATUS = {
  ok: true, changed: false, disabled: false, enabled: true,
  files: {
    'index.html': { state: 'patched', remote: 0, local: 2, detail: '' },
    'js/app.js': { state: 'patched', remote: 0, local: 1, detail: '' },
  },
  fonts: { owned: 8 }, errors: [],
};
const ok = (extra) => Object.assign({}, OK_STATUS, extra || {});

const PARENT_HTML = (opts) => `<!doctype html><meta charset="utf-8"><title>SIMULATED core</title>
<body><h1>SIMULATED Cluster Admin core bridge (test fixture, not a real NS8)</h1>
<iframe id="app" src="${opts.src}" style="width:900px;height:700px"></iframe>
<script>
(function(){
  var L = {};
  var core = { $root: {
    apiUrl: ${JSON.stringify(opts.apiUrl)},
    ${opts.locale ? `$i18n: { locale: ${JSON.stringify(opts.locale)} },` : ''}
    $on: function(n, f){ (L[n] = L[n] || []).push(f); },
    $off: function(n, f){ if (!L[n]) return; L[n] = L[n].filter(function(x){ return x !== f && x.fn !== f; }); if (!L[n].length) delete L[n]; },
    $once: function(n, f){ var s = this; function w(){ s.$off(n, w); f.apply(null, arguments); } w.fn = f; this.$on(n, w); },
    $emit: function(n){ var a = [].slice.call(arguments, 1); (L[n] || []).slice().forEach(function(f){ f.apply(null, a); }); },
    $count: function(){ return Object.keys(L).reduce(function(s, k){ return s + L[k].length; }, 0); }
  } };
  window.core = core;
  ${opts.token === false ? '' : `localStorage.setItem('loginInfo', JSON.stringify({ token: ${JSON.stringify(TOKEN)} }));`}
})();
</script>`;

async function newEnv(browser, o = {}) {
  const ctx = await browser.newContext({ locale: o.navLocale || 'en-US' });
  const env = { ctx, requests: [], pageErrors: [], external: [], coreFonts: 0, script: o.script || (() => ({})), lang: o.lang };
  await ctx.route('**/*', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.origin !== ORIGIN) {
      // real core.css still references IBM's CDN fonts (what this module patches): tolerated, recorded separately
      if (url.hostname === '1.www.s81c.com' && /\/IBM-Plex-(Sans|Mono)\//.test(url.pathname)) env.coreFonts++;
      else env.external.push(req.url());
      return route.abort();
    }
    const p = url.pathname;
    if (req.method() === 'POST' && /^\/cluster-admin\/api\/module\/[^/]+\/tasks$/.test(p)) {
      const body = JSON.parse(req.postData());
      const rec = { path: p, body, auth: req.headers()['authorization'], ct: req.headers()['content-type'] };
      env.requests.push(rec);
      const d = await env.script(body.action, body.data, env.requests.length, body) || {};
      if (d.delay) await new Promise((r) => setTimeout(r, d.delay));
      await route.fulfill({ status: d.http || 200, contentType: 'application/json', body: JSON.stringify(d.http >= 400 ? { error: 'x' } : { data: { id: 'task-1' } }) });
      if (d.http >= 400) return;
      const n = (type) => `${body.action}-${type}-${body.extra.eventId}`;
      for (const ev of d.events || []) try {
        await env.page.evaluate(([name, args]) => core.$root.$emit(name, ...args), [n(ev.type), ev.type === 'completed'
          ? [{ action: body.action }, { output: ev.output }]
          : ev.type === 'aborted' ? [{ output: ev.output || 'boom', status: 'aborted' }, { action: body.action }]
            : [ev.output, { action: body.action }]]);
      } catch (e) { /* page closed */ }
      return;
    }
    if (p === '/cluster-admin/') {
      return route.fulfill({ status: 200, contentType: 'text/html', body: PARENT_HTML({ src: o.src || APP, apiUrl: o.apiUrl || ORIGIN + '/cluster-admin/api', locale: o.hostLocale, token: o.token }) });
    }
    if (p === '/cluster-admin/css/core.css') {
      return route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(CORE_CSS) });
    }
    if (p === '/cluster-admin/other/') return route.fulfill({ status: 200, contentType: 'text/html', body: '<p>other page</p>' });
    const m = p.match(/^\/cluster-admin\/apps\/no-s81c[1-9][0-9]*\/(.*)$/);
    if (m) {
      const f = m[1] || 'index.html';
      const fp = path.join(UI_DIR, f);
      if (fp.startsWith(UI_DIR) && fs.existsSync(fp) && fs.statSync(fp).isFile()) {
        const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' };
        return route.fulfill({ status: 200, contentType: types[path.extname(fp)] || 'application/octet-stream', body: fs.readFileSync(fp) });
      }
    }
    return route.fulfill({ status: 404, body: 'nf' });
  });
  env.page = await ctx.newPage();
  env.page.on('pageerror', (e) => env.pageErrors.push(String(e)));
  env.page.on('dialog', (d) => d.dismiss());
  return env;
}

async function openApp(env, { standalone = false } = {}) {
  if (standalone) { await env.page.goto(ORIGIN + APP); return env.page; }
  await env.page.goto(ORIGIN + '/cluster-admin/');
  const handle = await env.page.waitForSelector('#app');
  const frame = await handle.contentFrame();
  env.frame = frame;
  await frame.waitForLoadState('load');
  return frame;
}

async function until(fn, what, ms = 4000) {
  const t0 = Date.now();
  let last;
  while (Date.now() - t0 < ms) {
    try { const v = await fn(); if (v) return v; } catch (e) { last = e; }
    await new Promise((r) => setTimeout(r, 25));
  }
  throw new Error('timeout waiting for ' + what + (last ? ': ' + last.message : ''));
}
const txt = (f, sel) => f.locator(sel).first().innerText();
const settle = (ms = 250) => new Promise((r) => setTimeout(r, ms));
const done = (output) => ({ events: [{ type: 'completed', output }] });

// default simulated backend
function backend(state) {
  return (action, data) => {
    if (action === 'get-configuration') return done({ enabled: state.enabled });
    if (action === 'get-font-status') return done(ok({ enabled: state.enabled, disabled: !state.enabled }));
    if (action === 'configure-module') { state.enabled = data.enabled; return done({ enabled: state.enabled }); }
    if (action === 'refresh-fonts') return done(ok({ changed: true, enabled: state.enabled }));
    return { http: 400 };
  };
}
async function loaded(f, env, n = 2) {
  await until(() => env.requests.length >= n, `${n} requests`);
  await until(async () => (await f.locator('#aggregate').getAttribute('data-state')) !== 'loading', 'load finished');
}

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test('initialization fetches get-configuration then get-font-status and renders native controls', async (b) => {
  const env = await newEnv(b, { script: backend({ enabled: true }) });
  const f = await openApp(env);
  await loaded(f, env);
  assert.deepStrictEqual(env.requests.map((r) => r.body.action), ['get-configuration', 'get-font-status']);
  const r = env.requests[0];
  assert.strictEqual(r.path, '/cluster-admin/api/module/no-s81c2/tasks');
  assert.strictEqual(r.auth, 'Bearer ' + TOKEN);
  assert.deepStrictEqual(Object.keys(r.body).sort(), ['action', 'extra']);
  assert.deepStrictEqual(Object.keys(r.body.extra).sort(), ['eventId', 'isNotificationHidden', 'title']);
  assert.strictEqual(r.body.extra.isNotificationHidden, true);
  assert.ok(/^[0-9a-f-]{36}$/.test(r.body.extra.eventId));
  assert.notStrictEqual(r.body.extra.eventId, env.requests[1].body.extra.eventId);
  assert.strictEqual(await f.locator('#enabled').isChecked(), true);
  assert.strictEqual(await f.locator('#enabled').getAttribute('type'), 'checkbox');
  assert.ok(await f.locator('label[for=enabled]').innerText().then((t) => /Enable local fonts/.test(t)));
  assert.strictEqual(await f.locator('#aggregate').getAttribute('data-state'), 'ok');
  assert.strictEqual(await txt(f, '#font-count'), '8');
  assert.strictEqual(await txt(f, '#patched-count'), '2');
  assert.strictEqual(await txt(f, '#remote-count'), '0');
  for (const id of ['save', 'refresh', 'reload']) assert.strictEqual(await f.locator('#' + id).getAttribute('type'), 'button');
  assert.ok(await f.locator('link[href="/cluster-admin/css/core.css"]').count() === 1);
  assert.ok(await f.locator('.bx--btn').count() >= 2, 'native bx-- buttons');
  assert.strictEqual(await f.locator('#aggregate').evaluate((e) => getComputedStyle(e).display !== 'none'), true);
  assert.deepStrictEqual(env.external, []);
  assert.deepStrictEqual(env.pageErrors, []);
  assert.strictEqual(await env.page.evaluate(() => core.$root.$count()), 0, 'listeners cleaned up');
  await env.ctx.close();
});

test('German UI by navigator language with explicit label', async (b) => {
  const env = await newEnv(b, { navLocale: 'de-DE', script: backend({ enabled: true }) });
  const f = await openApp(env);
  await loaded(f, env);
  assert.ok(/Lokale Schriftarten aktivieren/.test(await f.locator('label[for=enabled]').innerText()));
  assert.ok(/Jetzt prüfen/.test(await txt(f, '#refresh')));
  assert.strictEqual(await f.locator('html').getAttribute('lang'), 'de');
  await env.ctx.close();
});

test('disabled configuration shows explicit state and unchecked box', async (b) => {
  const env = await newEnv(b, { script: backend({ enabled: false }) });
  const f = await openApp(env);
  await loaded(f, env);
  assert.strictEqual(await f.locator('#enabled').isChecked(), false);
  assert.ok(/disabled/i.test(await txt(f, '#configured')));
  await env.ctx.close();
});

for (const target of [false, true]) {
  test(`save sends exactly {enabled:${target}} then reloads`, async (b) => {
    const st = { enabled: !target };
    const env = await newEnv(b, { script: backend(st) });
    const f = await openApp(env);
    await loaded(f, env);
    assert.strictEqual(await f.locator('#save').isDisabled(), true, 'save disabled while clean');
    if (target !== await f.locator('#enabled').isChecked()) await f.locator('label[for=enabled]').click();
    assert.strictEqual(await f.locator('#save').isDisabled(), false);
    await f.locator('#save').click();
    await until(() => env.requests.length >= 4, '4 requests');
    const w = env.requests[2];
    assert.strictEqual(w.body.action, 'configure-module');
    assert.deepStrictEqual(w.body.data, { enabled: target });
    assert.strictEqual(env.requests[3].body.action, 'get-configuration');
    await until(() => env.requests.length >= 5, '5 requests');
    assert.strictEqual(env.requests[4].body.action, 'get-font-status');
    await until(async () => (await f.locator('#aggregate').getAttribute('data-state')) !== 'loading', 'done');
    assert.strictEqual(await f.locator('#enabled').isChecked(), target);
    assert.ok(new RegExp(target ? 'enabled' : 'disabled', 'i').test(await txt(f, '#configured')));
    assert.strictEqual(await env.page.evaluate(() => core.$root.$count()), 0);
    await env.ctx.close();
  });
}

test('double click on save sends a single write and controls lock while busy', async (b) => {
  const st = { enabled: true };
  const inner = backend(st);
  const env = await newEnv(b, { script: (a, d, n) => (a === 'configure-module' ? { delay: 300, ...inner(a, d) } : inner(a, d)) });
  const f = await openApp(env);
  await loaded(f, env);
  await f.locator('label[for=enabled]').click();
  await f.locator('#save').dblclick();
  await f.locator('#save').click({ force: true }).catch(() => {});
  await f.locator('#refresh').click({ force: true }).catch(() => {});
  assert.strictEqual(await f.locator('#save').isDisabled(), true);
  assert.strictEqual(await f.locator('#refresh').isDisabled(), true);
  await until(() => env.requests.length >= 5, 'reload');
  await settle();
  assert.strictEqual(env.requests.filter((r) => r.body.action === 'configure-module').length, 1);
  assert.strictEqual(env.requests.filter((r) => r.body.action === 'refresh-fonts').length, 0);
  await env.ctx.close();
});

test('Jetzt prüfen invokes refresh-fonts and renders its result without extra requests', async (b) => {
  const env = await newEnv(b, { navLocale: 'de-DE', script: (a, d) => (a === 'refresh-fonts' ? done(ok({ changed: true, fonts: { owned: 12 } })) : backend({ enabled: true })(a, d)) });
  const f = await openApp(env);
  await loaded(f, env);
  await f.locator('#refresh').click();
  await until(async () => (await txt(f, '#font-count')) === '12', 'refreshed count');
  assert.strictEqual(env.requests.length, 3);
  assert.strictEqual(env.requests[2].body.action, 'refresh-fonts');
  assert.ok(!('data' in env.requests[2].body) || env.requests[2].body.data == null);
  await env.ctx.close();
});

test('Status lesen re-reads configuration and status', async (b) => {
  const env = await newEnv(b, { script: backend({ enabled: true }) });
  const f = await openApp(env);
  await loaded(f, env);
  await f.locator('#reload').click();
  await until(() => env.requests.length >= 4, '4 requests');
  assert.deepStrictEqual(env.requests.slice(2).map((r) => r.body.action), ['get-configuration', 'get-font-status']);
  await env.ctx.close();
});

test('error status: aggregate error, remote refs, bounded readable error list', async (b) => {
  const errors = Array.from({ length: 12 }, (_, i) => 'Fehler ' + i + ' ' + 'x'.repeat(i === 0 ? 2000 : 5));
  errors.push('<img src=x onerror=window.__pwn=1>');
  const st = ok({ ok: false, files: { 'a.js': { state: 'pending', remote: 3, local: 0, detail: '' }, 'b.js': { state: 'patched', remote: 0, local: 1 } }, errors });
  const env = await newEnv(b, { script: (a, d) => (a === 'get-font-status' ? done(st) : backend({ enabled: true })(a, d)) });
  const f = await openApp(env);
  await loaded(f, env);
  assert.strictEqual(await f.locator('#aggregate').getAttribute('data-state'), 'error');
  assert.strictEqual(await txt(f, '#remote-count'), '3');
  assert.strictEqual(await txt(f, '#patched-count'), '1');
  const n = await f.locator('#errors li').count();
  assert.ok(n >= 1 && n <= 11, 'bounded list, got ' + n);
  const all = await txt(f, '#errors');
  assert.ok(all.length < 2500);
  assert.ok(/Error 0|Fehler 0/.test(all));
  assert.strictEqual(await f.evaluate(() => window.__pwn), undefined);
  assert.strictEqual(await f.locator('#errors img').count(), 0);
  await env.ctx.close();
});

test('status with ok missing is unknown, never green', async (b) => {
  const env = await newEnv(b, { script: (a, d) => (a === 'get-font-status' ? done({ enabled: true, files: {}, fonts: { owned: 0 }, errors: [] }) : backend({ enabled: true })(a, d)) });
  const f = await openApp(env);
  await loaded(f, env);
  assert.strictEqual(await f.locator('#aggregate').getAttribute('data-state'), 'unknown');
  await env.ctx.close();
});

test('reload failure clears previous green status', async (b) => {
  let fail = false;
  const inner = backend({ enabled: true });
  const env = await newEnv(b, { script: (a, d) => (fail && a === 'get-font-status' ? { events: [{ type: 'aborted' }] } : inner(a, d)) });
  const f = await openApp(env);
  await loaded(f, env);
  assert.strictEqual(await f.locator('#aggregate').getAttribute('data-state'), 'ok');
  fail = true;
  await f.locator('#reload').click();
  await until(async () => (await f.locator('#aggregate').getAttribute('data-state')) === 'unknown', 'unknown after failure');
  assert.strictEqual(await txt(f, '#font-count'), '–');
  assert.ok((await txt(f, '#message')).length > 0);
  assert.strictEqual(await f.locator('#reload').isDisabled(), false);
  await env.ctx.close();
});

test('HTTP task creation error is shown and nothing leaks', async (b) => {
  const env = await newEnv(b, { script: () => ({ http: 500 }) });
  const f = await openApp(env);
  await until(async () => (await txt(f, '#message')).length > 0, 'message');
  assert.strictEqual(env.requests.length, 1, 'no follow-up requests');
  assert.ok(!(await f.locator('body').innerText()).includes(TOKEN));
  assert.strictEqual(await f.locator('#aggregate').getAttribute('data-state'), 'unknown');
  assert.strictEqual(await f.locator('#save').isDisabled(), true);
  assert.strictEqual(await env.page.evaluate(() => core.$root.$count()), 0);
  await env.ctx.close();
});

test('aborted task shows error, keeps checkbox and does not expose output', async (b) => {
  const inner = backend({ enabled: true });
  const env = await newEnv(b, { script: (a, d) => (a === 'configure-module' ? { events: [{ type: 'aborted', output: 'SECRET-LOG ' + TOKEN }] } : inner(a, d)) });
  const f = await openApp(env);
  await loaded(f, env);
  await f.locator('label[for=enabled]').click();
  await f.locator('#save').click();
  await until(async () => (await txt(f, '#message')).length > 0, 'message');
  const body = await f.locator('body').innerText();
  assert.ok(!body.includes('SECRET-LOG') && !body.includes(TOKEN));
  assert.strictEqual(await f.locator('#enabled').isChecked(), false);
  assert.strictEqual(env.requests.length, 3);
  assert.strictEqual(await env.page.evaluate(() => core.$root.$count()), 0);
  await env.ctx.close();
});

test('validation-failed event is treated as failure and cleans all listeners', async (b) => {
  const inner = backend({ enabled: true });
  const env = await newEnv(b, { script: (a, d) => (a === 'configure-module' ? { events: [{ type: 'validation-failed', output: [{ parameter: 'enabled', error: 'bad' }] }] } : inner(a, d)) });
  const f = await openApp(env);
  await loaded(f, env);
  await f.locator('label[for=enabled]').click();
  await f.locator('#save').click();
  await until(async () => (await txt(f, '#message')).length > 0, 'message');
  assert.strictEqual(env.requests.length, 3);
  assert.strictEqual(await env.page.evaluate(() => core.$root.$count()), 0);
  await env.ctx.close();
});

test('timeout is bounded, reported, and a late result is ignored', async (b) => {
  const env = await newEnv(b, { script: () => ({}) });
  await env.page.clock.install();
  const f = await openApp(env);
  await until(() => env.requests.length === 1, 'first request');
  await env.page.clock.fastForward(10 * 60 * 1000);
  await until(async () => (await txt(f, '#message')).length > 0, 'timeout message');
  assert.ok(/time|Zeit/i.test(await txt(f, '#message')));
  assert.strictEqual(await env.page.evaluate(() => core.$root.$count()), 0);
  const id = env.requests[0].body.extra.eventId;
  await env.page.evaluate((i) => core.$root.$emit('get-configuration-completed-' + i, {}, { output: { enabled: true } }), id);
  await settle();
  assert.strictEqual(env.requests.length, 1);
  assert.strictEqual(await f.locator('#aggregate').getAttribute('data-state'), 'unknown');
  await env.ctx.close();
});

test('duplicate completion events trigger no extra requests', async (b) => {
  const inner = backend({ enabled: true });
  const env = await newEnv(b, { script: (a, d) => { const r = inner(a, d); return { events: [r.events[0], r.events[0]] }; } });
  const f = await openApp(env);
  await loaded(f, env);
  await settle();
  assert.strictEqual(env.requests.length, 2);
  const id = env.requests[1].body.extra.eventId;
  await env.page.evaluate(([i, st]) => core.$root.$emit('get-font-status-completed-' + i, {}, { output: st }), [id, OK_STATUS]);
  await settle();
  assert.strictEqual(env.requests.length, 2);
  await env.ctx.close();
});

test('navigation away tears down listeners; late events trigger nothing', async (b) => {
  const env = await newEnv(b, { script: () => ({}) });
  const f = await openApp(env);
  await until(() => env.requests.length === 1, 'first request');
  assert.ok(await env.page.evaluate(() => core.$root.$count()) > 0);
  const id = env.requests[0].body.extra.eventId;
  await env.page.evaluate(() => { document.getElementById('app').contentWindow.location.href = '/cluster-admin/other/'; });
  await until(async () => (await env.page.evaluate(() => core.$root.$count())) === 0, 'listeners removed');
  await env.page.evaluate((i) => core.$root.$emit('get-configuration-completed-' + i, {}, { output: { enabled: true } }), id);
  await settle();
  assert.strictEqual(env.requests.length, 1);
  assert.deepStrictEqual(env.pageErrors, []);
  await env.ctx.close();
});

test('no host command prose; controls instead of shell instructions', async (b) => {
  const env = await newEnv(b, { navLocale: 'de-DE', script: backend({ enabled: true }) });
  const f = await openApp(env);
  await loaded(f, env);
  const body = await f.locator('body').innerText();
  assert.ok(!/runagent|journalctl|python3|<\/?pre|Strg\+Umschalt/.test(body + await f.content().then((h) => h.replace(/<script[\s\S]*?<\/script>/g, ''))), 'no CLI text');
  assert.strictEqual(await f.locator('pre').count(), 0);
  await env.ctx.close();
});

test('standalone visit is blocked: clear hint, disabled controls, no requests, no fake status', async (b) => {
  const env = await newEnv(b, { script: backend({ enabled: true }) });
  const f = await openApp(env, { standalone: true });
  await until(async () => /Cluster Admin/.test(await txt(f, '#blocked')), 'blocked hint');
  assert.ok(await f.locator('#blocked').isVisible());
  for (const id of ['enabled', 'save', 'refresh', 'reload']) assert.strictEqual(await f.locator('#' + id).isDisabled(), true, id);
  assert.notStrictEqual(await f.locator('#aggregate').getAttribute('data-state'), 'ok');
  assert.strictEqual(env.requests.length, 0);
  await env.ctx.close();
});

test('missing token or cross-origin apiUrl blocks without sending anything', async (b) => {
  for (const o of [{ token: false }, { apiUrl: 'https://evil.example/api' }]) {
    const env = await newEnv(b, { script: backend({ enabled: true }), ...o });
    const f = await openApp(env);
    await until(async () => (await txt(f, '#blocked')).length > 0, 'blocked');
    assert.strictEqual(await f.locator('#save').isDisabled(), true);
    assert.strictEqual(env.requests.length, 0);
    assert.deepStrictEqual(env.external, []);
    await env.ctx.close();
  }
});

(async () => {
  assert.strictEqual(tests.length, EXPECTED_TESTS, 'fixture count drifted: ' + tests.length);
  console.log(`SIMULATED NS8 core bridge + task backend (fixture); core.css: ${CORE_CSS}`);
  const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE || undefined, args: ['--no-sandbox'] });
  let failed = 0;
  for (const t of tests) {
    try { await t.fn(browser); console.log('ok   - ' + t.name); }
    catch (e) { failed++; console.log('FAIL - ' + t.name + '\n       ' + String(e.message).split('\n').slice(0, 14).join('\n       ')); }
  }
  await browser.close();
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
