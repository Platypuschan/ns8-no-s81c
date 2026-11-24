/* SPDX-License-Identifier: GPL-3.0-or-later
 * Native NS8 module settings for local fonts. Vanilla JS, no external resources.
 * Talks to the Cluster Admin core exactly like regular NS8 modules: task POST + $root events. */
'use strict';
(function () {
  var TASK_TIMEOUT_MS = 30000;
  var MAX_ERRORS = 8, MAX_FILES = 8, MAX_TEXT = 240;

  var I18N = {
    en: {
      title: 'Local fonts', intro: 'Replaces external IBM Plex font references of the Cluster Admin UI with local files.',
      settings: 'Settings', enable: 'Enable local fonts', configured: 'Configured:', enabledV: 'enabled', disabledV: 'disabled',
      save: 'Save', status: 'Status', overall: 'Overall status:', ok: 'OK', error: 'Error', unknown: 'Unknown', loading: 'Loading…',
      fonts: 'Local fonts', patched: 'Patched files', remote: 'Remaining remote references',
      problems: 'Files needing attention', errors: 'Errors', refresh: 'Check now', reload: 'Read status',
      more: 'and {n} more', blockedTitle: 'Not available here',
      blockedHost: 'Open this page inside Cluster Admin (Applications → this module) to change settings and see live status.',
      blockedAuth: 'No valid Cluster Admin session was found. Open this page inside Cluster Admin and log in.',
      eTimeout: 'The operation timed out. Status is unknown.', eHttp: 'The task could not be created. Status is unknown.',
      eAborted: 'The operation failed. Status is unknown.', eValidation: 'The settings were rejected. Status is unknown.',
      eInvalid: 'Unexpected response from the module. Status is unknown.', eBusy: 'Another operation is running.'
    },
    de: {
      title: 'Lokale Schriftarten', intro: 'Ersetzt externe IBM-Plex-Schriftverweise der Cluster-Admin-Oberfläche durch lokale Dateien.',
      settings: 'Einstellungen', enable: 'Lokale Schriftarten aktivieren', configured: 'Konfiguriert:', enabledV: 'aktiviert', disabledV: 'deaktiviert',
      save: 'Speichern', status: 'Status', overall: 'Gesamtstatus:', ok: 'In Ordnung', error: 'Fehler', unknown: 'Unbekannt', loading: 'Wird geladen…',
      fonts: 'Lokale Schriftarten', patched: 'Angepasste Dateien', remote: 'Verbleibende externe Verweise',
      problems: 'Dateien mit Handlungsbedarf', errors: 'Fehler', refresh: 'Jetzt prüfen', reload: 'Status lesen',
      more: 'und {n} weitere', blockedTitle: 'Hier nicht verfügbar',
      blockedHost: 'Diese Seite bitte in Cluster Admin öffnen (Anwendungen → dieses Modul), um Einstellungen zu ändern und den Live-Status zu sehen.',
      blockedAuth: 'Keine gültige Cluster-Admin-Sitzung gefunden. Bitte die Seite in Cluster Admin öffnen und anmelden.',
      eTimeout: 'Zeitüberschreitung. Der Status ist unbekannt.', eHttp: 'Die Aufgabe konnte nicht erstellt werden. Der Status ist unbekannt.',
      eAborted: 'Der Vorgang ist fehlgeschlagen. Der Status ist unbekannt.', eValidation: 'Die Einstellungen wurden abgelehnt. Der Status ist unbekannt.',
      eInvalid: 'Unerwartete Antwort des Moduls. Der Status ist unbekannt.', eBusy: 'Ein anderer Vorgang läuft.'
    }
  };

  var $ = function (id) { return document.getElementById(id); };
  var lang = 'en';
  var state = { config: null, status: null, busy: false, dirty: false, tag: 'loading', error: '', blocked: '' };
  var active = []; // in-flight task handles (for teardown)
  var tornDown = false;

  function pickLang() {
    var l = '';
    try { var h = window.parent.core.$root.$i18n.locale; if (typeof h === 'string') l = h; } catch (e) { /* none */ }
    if (!l) l = (navigator.languages && navigator.languages[0]) || navigator.language || 'en';
    return /^de/i.test(l) ? 'de' : 'en';
  }
  function t(k, n) { var s = I18N[lang][k] || I18N.en[k] || k; return n === undefined ? s : s.replace('{n}', n); }
  function clean(s, max) {
    s = String(s === undefined || s === null ? '' : s).replace(/[\u0000-\u001f\u007f]+/g, ' ').trim();
    return s.length > max ? s.slice(0, max - 1) + '…' : s;
  }

  // ---- host context ------------------------------------------------------
  function hostContext() {
    var m = location.pathname.match(/\/cluster-admin\/apps\/(no-s81c[1-9][0-9]*)\/?/);
    if (!m) return { err: 'blockedHost' };
    var root;
    try {
      if (window.parent === window) return { err: 'blockedHost' };
      root = window.parent.core.$root;
      void window.parent.location.origin; // throws when cross-origin
      if (!root || typeof root.apiUrl !== 'string' || typeof root.$on !== 'function' || typeof root.$off !== 'function') return { err: 'blockedHost' };
      var api = new URL(root.apiUrl, location.href);
      if (api.origin !== location.origin) return { err: 'blockedHost' };
    } catch (e) { return { err: 'blockedHost' }; }
    if (!token()) return { err: 'blockedAuth' };
    return { moduleId: m[1], root: root, apiUrl: root.apiUrl.replace(/\/+$/, '') };
  }
  function token() {
    try {
      var li = JSON.parse(window.localStorage.getItem('loginInfo'));
      return li && typeof li.token === 'string' && li.token ? li.token : '';
    } catch (e) { return ''; }
  }
  function uuid() {
    if (window.crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    var b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    var h = Array.prototype.map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
    return [h.slice(0, 8), h.slice(8, 12), h.slice(12, 16), h.slice(16, 20), h.slice(20)].join('-');
  }

  // ---- task bridge ---------------------------------------------------------
  function runTask(ctx, action, data) {
    return new Promise(function (resolve, reject) {
      var eventId = uuid();
      var names = ['completed', 'aborted', 'validation-failed'].map(function (k) { return action + '-' + k + '-' + eventId; });
      var done = false, timer = null, ac = new AbortController(), handlers = [];
      var handle = { cancel: function () { finish(reject, 'torn'); } };
      function finish(fn, v) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        for (var i = 0; i < names.length; i++) { try { ctx.root.$off(names[i], handlers[i]); } catch (e) { /* ignore */ } }
        var ix = active.indexOf(handle); if (ix >= 0) active.splice(ix, 1);
        if (fn === reject) ac.abort();
        fn(v);
      }
      handlers[0] = function (context, result) {
        var out = result && typeof result === 'object' ? result.output : undefined;
        finish(resolve, out);
      };
      handlers[1] = function () { finish(reject, 'eAborted'); };
      handlers[2] = function () { finish(reject, 'eValidation'); };
      for (var i = 0; i < names.length; i++) ctx.root.$on(names[i], handlers[i]);
      active.push(handle);
      timer = setTimeout(function () { finish(reject, 'eTimeout'); }, TASK_TIMEOUT_MS);
      var body = { action: action, extra: { eventId: eventId, title: action, isNotificationHidden: true } };
      if (data !== undefined) body.data = data;
      var tk = token();
      if (!tk) { finish(reject, 'blockedAuth'); return; }
      fetch(ctx.apiUrl + '/module/' + encodeURIComponent(ctx.moduleId) + '/tasks', {
        method: 'POST', credentials: 'same-origin', signal: ac.signal,
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tk },
        body: JSON.stringify(body)
      }).then(function (r) { if (!r.ok) finish(reject, 'eHttp'); }, function () { finish(reject, 'eHttp'); });
    });
  }

  // ---- result validation -----------------------------------------------------
  function validStatus(s) {
    return s && typeof s === 'object' && !Array.isArray(s) && s.files && typeof s.files === 'object' && !Array.isArray(s.files) &&
      Array.isArray(s.errors) && s.fonts && typeof s.fonts === 'object';
  }
  function num(v) { return Array.isArray(v) ? v.length : (typeof v === 'number' && isFinite(v) && v >= 0 ? Math.floor(v) : 0); }
  function aggregate(s) {
    if (!s) return 'unknown';
    if (s.errors.length || s.ok === false) return 'error';
    if (s.ok === true) return 'ok';
    return 'unknown';
  }

  // ---- rendering -------------------------------------------------------------
  function setText(id, v) { $(id).textContent = v; }
  function render() {
    var blocked = !!state.blocked;
    var s = state.status;
    var tag = blocked ? 'unknown' : (state.busy && !s && !state.error ? 'loading' : aggregate(s));
    if (state.loadingFirst) tag = 'loading';
    var agg = $('aggregate');
    agg.setAttribute('data-state', tag);
    agg.textContent = t(tag);
    $('blocked').hidden = !blocked;
    if (blocked) setText('blocked-text', t(state.blocked));
    $('message').hidden = !state.error;
    setText('message-text', state.error ? t(state.error) : '');
    var cfg = state.config;
    setText('configured', cfg === null ? '–' : t(cfg ? 'enabledV' : 'disabledV'));
    var cb = $('enabled');
    cb.disabled = blocked || state.busy || cfg === null;
    $('save').disabled = blocked || state.busy || cfg === null || !state.dirty;
    $('refresh').disabled = blocked || state.busy;
    $('reload').disabled = blocked || state.busy;
    var fc = '–', pc = '–', rc = '–', problems = [], errs = [];
    if (s) {
      fc = String(num(s.fonts.owned));
      var p = 0, r = 0;
      Object.keys(s.files).forEach(function (rel) {
        var f = s.files[rel] || {};
        if (f.state === 'patched') p++;
        r += num(f.remote);
        if (f.state !== 'patched') problems.push(clean(rel, 80) + ': ' + clean(f.state, 30) + (num(f.remote) ? ' (' + num(f.remote) + ')' : '') + (f.detail ? ' – ' + clean(f.detail, MAX_TEXT) : ''));
      });
      pc = String(p); rc = String(r);
      errs = s.errors.map(function (e) { return clean(e, MAX_TEXT); });
    }
    setText('font-count', fc); setText('patched-count', pc); setText('remote-count', rc);
    fillList('problems', 'problems-wrap', problems, MAX_FILES);
    fillList('errors', 'errors-wrap', errs, MAX_ERRORS);
  }
  function fillList(id, wrapId, items, max) {
    var ul = $(id);
    while (ul.firstChild) ul.removeChild(ul.firstChild);
    items.slice(0, max).forEach(function (x) { var li = document.createElement('li'); li.textContent = x; ul.appendChild(li); });
    if (items.length > max) { var li = document.createElement('li'); li.textContent = t('more', items.length - max); ul.appendChild(li); }
    $(wrapId).hidden = items.length === 0;
  }
  function applyI18n() {
    document.documentElement.setAttribute('lang', lang);
    document.title = t('title');
    Array.prototype.forEach.call(document.querySelectorAll('[data-i18n]'), function (el) {
      var span = el.querySelector('.bx--checkbox-label-text');
      (span || el).textContent = t(el.getAttribute('data-i18n'));
    });
    $('enabled').setAttribute('aria-label', t('enable'));
  }
  // checkbox label span carries data-i18n itself; avoid double handling
  function fail(e) {
    state.config = null; state.dirty = false;
    state.status = null;
    state.error = typeof e === 'string' && I18N.en[e] ? e : 'eInvalid';
    if (e === 'torn') state.error = '';
  }

  // ---- operations --------------------------------------------------------------
  var ctx = null;
  function begin() {
    if (state.busy || tornDown || state.blocked) return false;
    state.busy = true; state.error = ''; render();
    return true;
  }
  function end() { state.busy = false; state.loadingFirst = false; if (!tornDown) render(); }

  async function readAll() {
    var cfg = await runTask(ctx, 'get-configuration');
    if (!cfg || typeof cfg.enabled !== 'boolean') throw 'eInvalid';
    var st = await runTask(ctx, 'get-font-status');
    if (!validStatus(st)) throw 'eInvalid';
    state.config = cfg.enabled; state.status = st; state.dirty = false;
    $('enabled').checked = cfg.enabled;
  }
  async function doReload() {
    if (!begin()) return;
    state.status = null;
    try { await readAll(); } catch (e) { fail(e); }
    end();
  }
  async function doSave() {
    if (!begin()) return;
    var want = $('enabled').checked;
    try {
      var out = await runTask(ctx, 'configure-module', { enabled: want });
      if (!out || typeof out.enabled !== 'boolean') throw 'eInvalid';
      state.status = null;
      await readAll();
    } catch (e) { fail(e); }
    end();
  }
  async function doRefresh() {
    if (!begin()) return;
    try {
      var st = await runTask(ctx, 'refresh-fonts');
      if (!validStatus(st)) throw 'eInvalid';
      state.status = st;
      if (typeof st.enabled === 'boolean') { state.config = st.enabled; if (!state.dirty) $('enabled').checked = st.enabled; }
    } catch (e) { fail(e); }
    end();
  }

  function teardown() {
    if (tornDown) return;
    tornDown = true;
    active.slice().forEach(function (h) { h.cancel(); });
  }

  function init() {
    lang = pickLang();
    applyI18n();
    var h = hostContext();
    if (h.err) { state.blocked = h.err; render(); return; }
    ctx = h;
    $('enabled').addEventListener('change', function () { state.dirty = state.config !== null && $('enabled').checked !== state.config; render(); });
    $('save').addEventListener('click', doSave);
    $('refresh').addEventListener('click', doRefresh);
    $('reload').addEventListener('click', doReload);
    window.addEventListener('pagehide', teardown);
    window.addEventListener('beforeunload', teardown);
    window.addEventListener('unload', teardown);
    state.loadingFirst = true;
    doReload();
  }
  init();
})();
