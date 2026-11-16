/* TV Remote phone app. Plain ES5 on purpose so it runs on older Android browsers.
 *
 * Two ways to reach the laptop:
 *  - LocalTransport: HTTP to the laptop itself (page opened as http://<laptop>:8080/?t=TOKEN)
 *  - RelayTransport: through the internet via a ntfy server (page hosted on GitHub Pages,
 *    opened as https://.../#k=SECRET). Same protocol as server/relay.py.
 */
(function () {
  'use strict';

  var KEYS = { token: 'tvremote.token', secret: 'tvremote.secret', server: 'tvremote.server', state: 'tvremote.state',
               group: 'tvremote.group' };
  var DEFAULT_RELAY = 'https://ntfy.sh';
  // Channel groups = languages; one tab each. Swipe left/right to change.
  var GROUP_ORDER = ['PT', 'EN', 'DE'];
  var GROUP_NAMES = { PT: 'Português', EN: 'English', DE: 'Deutsch' };
  var transport = null;
  var channels = [];
  var current = null;
  var lastSync = 0;
  var activeGroup = null;

  var $ = function (id) { return document.getElementById(id); };
  var grid = $('grid'), editor = $('editor'), rows = $('rows'), controls = $('controls');

  function store(k, v) {
    try {
      if (v === undefined) return localStorage.getItem(k);
      localStorage.setItem(k, v);
    } catch (e) {}
    return null;
  }

  // Values come from the link (after # or ?) the first time, then from this phone's storage.
  function param(name) {
    var m = new RegExp('[#?&]' + name + '=([^&#]+)').exec(location.hash + '&' + location.search);
    return m ? decodeURIComponent(m[1]) : null;
  }

  // ------------------------------------------------------------------ local transport
  function LocalTransport(token) {
    var routes = {
      channels: ['GET', '/api/channels'], save: ['PUT', '/api/channels'], play: ['POST', '/api/play'],
      stop: ['POST', '/api/stop'], volume: ['POST', '/api/volume'], shutdown: ['POST', '/api/shutdown']
    };
    this.mode = 'local';
    this.request = function (cmd, args) {
      var r = routes[cmd];
      var opts = { method: r[0], headers: { 'X-Token': token } };
      if (r[0] !== 'GET') {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(args || {});
      }
      return fetch(r[1], opts).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) {
            var msg = data.error || ('Erro ' + res.status);
            if (res.status === 401) msg = 'Token inválido: leia de novo o QR code (./show-qr.sh no portátil)';
            throw new Error(msg);
          }
          return data;
        });
      }, function () { throw new Error('Sem ligação ao portátil'); });
    };
    this.send = this.request;
  }

  // ------------------------------------------------------------------ relay transport
  var enc = window.TextEncoder ? new TextEncoder() : null;
  var CHUNK = 3000;

  function hex(buf) {
    var b = new Uint8Array(buf), s = '';
    for (var i = 0; i < b.length; i++) s += ('0' + b[i].toString(16)).slice(-2);
    return s;
  }
  function hexBytes(h) {
    var out = new Uint8Array(h.length / 2);
    for (var i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
    return out;
  }
  function randomHex(n) { return hex(crypto.getRandomValues(new Uint8Array(n))); }
  function hmacKey(raw) {
    return crypto.subtle.importKey('raw', raw, { name: 'HMAC', hash: { name: 'SHA-256' } }, false, ['sign']);
  }
  function hmacHex(key, text) { return crypto.subtle.sign('HMAC', key, enc.encode(text)).then(hex); }
  // JSON with non-ASCII escaped (like Python's json.dumps), so 1 char = 1 byte on the wire.
  function asciiJSON(obj) {
    return JSON.stringify(obj).replace(/[\u007f-￿]/g, function (c) {
      return '\\u' + ('000' + c.charCodeAt(0).toString(16)).slice(-4);
    });
  }

  function derive(secret) {
    return hmacKey(enc.encode(secret)).then(function (k) {
      return Promise.all([hmacHex(k, 'topic:cmd'), hmacHex(k, 'topic:state'), hmacHex(k, 'sign')]);
    }).then(function (h) {
      return hmacKey(hexBytes(h[2])).then(function (signKey) {
        return { cmdTopic: 'tvr' + h[0].slice(0, 29), stateTopic: 'tvr' + h[1].slice(0, 29), signKey: signKey };
      });
    });
  }

  function RelayTransport(secret, server) {
    var self = this, keys = null, pending = {}, groups = {};
    self.mode = 'relay';

    var ready = derive(secret).then(function (d) {
      keys = d;
      return new Promise(function (resolve) {
        var es = new EventSource(server + '/' + d.stateTopic + '/sse');
        es.onopen = function () { resolve(); };
        es.onmessage = function (ev) { onEvent(ev.data); };
        setTimeout(resolve, 5000); // don't wait forever; requests will time out instead
      });
    });

    function onEvent(data) {
      var m, w;
      try { m = JSON.parse(data); w = JSON.parse(m.message); } catch (e) { return; }
      if (m.event && m.event !== 'message') return;
      var g = groups[w.g] || (groups[w.g] = { parts: {}, count: 0 });
      if (!(w.i in g.parts)) { g.parts[w.i] = w.d; g.count++; }
      if (g.count < w.n) return;
      delete groups[w.g];
      var text = '';
      for (var i = 0; i < w.n; i++) text += g.parts[i];
      hmacHex(keys.signKey, text).then(function (sig) {
        if (sig !== w.s) return; // not from our laptop
        var msg = JSON.parse(text);
        if (pending[msg.re]) pending[msg.re].done(msg);
      });
    }

    function post(body) {
      return fetch(server + '/' + keys.cmdTopic, { method: 'POST', body: body }).then(function (r) {
        if (r.status === 429) throw new Error('Limite diário de mensagens do ntfy.sh atingido. Tente mais tarde.');
        if (!r.ok) throw new Error('Erro do servidor de mensagens (' + r.status + ')');
      }, function () { throw new Error('Sem ligação à internet'); });
    }

    function publish(cmd, args, wait) {
      return ready.then(function () {
        var id = randomHex(8);
        var payload = { id: id, ts: Math.floor(Date.now() / 1000), cmd: cmd, args: args || {} };
        var reply = null;
        if (wait) {
          reply = new Promise(function (resolve, reject) {
            var timer = setTimeout(function () {
              delete pending[id];
              reject(new Error('O portátil não respondeu. Está ligado e com internet?'));
            }, 15000);
            pending[id] = {
              timer: timer,
              done: function (msg) {
                clearTimeout(timer);
                delete pending[id];
                if (msg.ok) resolve(msg.data);
                else reject(new Error(msg.error === 'clock' ? 'A hora do telemóvel está errada: acerte o relógio.' : msg.error));
              }
            };
          });
        }
        var text = asciiJSON(payload);
        return hmacHex(keys.signKey, text).then(function (sig) {
          var gid = randomHex(6), parts = [];
          for (var i = 0; i < text.length; i += CHUNK) parts.push(text.slice(i, i + CHUNK));
          return parts.reduce(function (p, part, i) {
            return p.then(function () {
              return post(JSON.stringify({ g: gid, i: i, n: parts.length, d: part, s: sig }));
            });
          }, Promise.resolve());
        }).then(function () { return reply; }, function (e) {
          if (pending[id]) { clearTimeout(pending[id].timer); delete pending[id]; }
          throw e;
        });
      });
    }

    self.request = function (cmd, args) { return publish(cmd, args, true); };
    self.send = function (cmd, args) { return publish(cmd, args, false); };
  }

  function initTransport() {
    var secret = param('k'), token = param('t'), server = param('s');
    if (secret) { store(KEYS.secret, secret); store(KEYS.server, server || DEFAULT_RELAY); }
    if (token) store(KEYS.token, token);
    secret = secret || store(KEYS.secret);
    token = token || store(KEYS.token);
    if (secret && enc && window.crypto && crypto.subtle && window.EventSource) {
      return new RelayTransport(secret, server || store(KEYS.server) || DEFAULT_RELAY);
    }
    if (token && location.protocol === 'http:') return new LocalTransport(token);
    return null;
  }

  // ------------------------------------------------------------------ UI helpers
  var toastTimer;
  function toast(msg, isError) {
    var t = $('toast');
    t.textContent = msg;
    t.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = 'toast'; }, isError ? 4500 : 1800);
  }
  function setStatus(kind, text) {
    var s = $('status');
    s.className = 'status ' + kind;
    s.textContent = text;
  }
  function fail(err) {
    if (transport && transport.mode === 'relay') setStatus('bad', 'sem resposta');
    toast(err.message || 'Sem ligação ao portátil', true);
  }
  function ok() { if (transport && transport.mode === 'relay') setStatus('good', 'ligado'); }

  function remember(data) {
    if (data.channels) channels = data.channels;
    if ('current' in data) current = data.current;
    store(KEYS.state, JSON.stringify({ channels: channels, current: current }));
  }

  // ------------------------------------------------------------------ grid
  var PALETTE = ['#1f5fbf', '#2e7d4f', '#b3541e', '#7b3fa8', '#b02a4a', '#0f7c86',
                 '#8a6d1a', '#4a5bb0', '#6b8e23', '#a23b8f', '#c0392b', '#2c6e8f'];
  function colorFor(index) { return PALETTE[index % PALETTE.length]; }

  function groupOf(ch) { return ch.group || 'PT'; }

  // Known languages always get a tab (even if empty, so channels can be added
  // there); other groups from the file follow in order of appearance.
  function groups() {
    var list = GROUP_ORDER.slice();
    channels.forEach(function (ch) { if (list.indexOf(groupOf(ch)) === -1) list.push(groupOf(ch)); });
    return list;
  }

  function inGroup(g) { return channels.filter(function (ch) { return groupOf(ch) === g; }); }

  // Categories = sections inside a language tab, in order of first appearance;
  // channels without a category go last, under "Outros".
  function sections(list) {
    var out = [], index = {}, rest = [];
    list.forEach(function (ch) {
      var c = (ch.category || '').trim();
      if (!c) { rest.push(ch); return; }
      var key = c.toLowerCase();
      if (!(key in index)) { index[key] = out.length; out.push({ name: c, items: [] }); }
      out[index[key]].items.push(ch);
    });
    if (rest.length) out.push({ name: out.length ? 'Outros' : '', items: rest });
    return out;
  }

  function renderTabs() {
    var tabs = $('tabs');
    tabs.innerHTML = '';
    if (!transport) { tabs.className = 'tabs hidden'; return; }
    tabs.className = 'tabs';
    groups().forEach(function (g) {
      var b = document.createElement('button');
      b.className = g === activeGroup ? 'active' : '';
      b.setAttribute('role', 'tab');
      b.innerHTML = (GROUP_NAMES[g] || g) + '<span class="count">' + inGroup(g).length + '</span>';
      b.onclick = function () { showGroup(g); };
      tabs.appendChild(b);
    });
  }

  function renderGrid() {
    grid.innerHTML = '';
    var list = inGroup(activeGroup);
    if (!list.length) {
      grid.innerHTML = '<div class="empty">' + (transport ? 'Sem canais em ' + (GROUP_NAMES[activeGroup] || activeGroup) +
        '. Toque em Editar para adicionar.' : 'Leia o QR code mostrado no portátil (./show-qr.sh) para ligar este telemóvel.') + '</div>';
      return;
    }
    var i = 0;
    sections(list).forEach(function (sec) {
      if (sec.name) {
        var h = document.createElement('h2');
        h.className = 'section';
        h.textContent = sec.name;
        grid.appendChild(h);
      }
      sec.items.forEach(function (ch) {
        var b = document.createElement('button');
        b.className = 'tile' + (ch.id === current ? ' current' : '');
        b.style.background = colorFor(i++);
        b.textContent = ch.name;
        b.onclick = function () { play(ch, b); };
        grid.appendChild(b);
      });
    });
  }

  function render() {
    if (groups().indexOf(activeGroup) === -1) activeGroup = 'PT';
    renderTabs();
    renderGrid();
  }

  // Change language tab; `dir` > 0 slides the new grid in from the right.
  function showGroup(g, dir) {
    if (g === activeGroup) return;
    var all = groups();
    if (dir === undefined) dir = all.indexOf(g) - all.indexOf(activeGroup);
    activeGroup = g;
    store(KEYS.group, g);
    render();
    grid.className = 'grid ' + (dir > 0 ? 'from-right' : 'from-left');
    setTimeout(function () { grid.className = 'grid'; }, 260);
  }

  function step(delta) {
    var all = groups(), i = all.indexOf(activeGroup) + delta;
    if (i >= 0 && i < all.length) showGroup(all[i], delta);
  }

  // Swipe left/right anywhere on the channel area to change language.
  (function () {
    var x0 = null, y0 = 0, t0 = 0;
    $('pager').addEventListener('touchstart', function (e) {
      if (editor.className.indexOf('hidden') === -1 || e.touches.length !== 1) { x0 = null; return; }
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; t0 = Date.now();
    }, { passive: true });
    $('pager').addEventListener('touchend', function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy) && Date.now() - t0 < 800) step(dx < 0 ? 1 : -1);
    }, { passive: true });
  })();

  function play(ch, el) {
    el.className += ' busy';
    transport.request('play', { id: ch.id }).then(function (res) {
      remember(res); ok(); renderGrid();
      toast('▶ ' + ch.name);
    }).catch(function (e) { renderGrid(); fail(e); });
  }

  function load() {
    if (!transport) { render(); return; }
    lastSync = Date.now();
    if (transport.mode === 'relay') setStatus('wait', 'a ligar…');
    return transport.request('channels').then(function (res) {
      remember(res); ok(); render();
    }).catch(fail);
  }

  // ------------------------------------------------------------------ controls
  Array.prototype.forEach.call(document.querySelectorAll('[data-vol]'), function (b) {
    b.onclick = function () {
      if (transport) transport.send('volume', { action: b.getAttribute('data-vol') }).catch(fail);
    };
  });

  $('stopBtn').onclick = function () {
    if (!transport) return;
    transport.request('stop').then(function (res) {
      remember(res); ok(); renderGrid(); toast('Parado');
    }).catch(fail);
  };

  $('powerBtn').onclick = function () {
    if (!transport || !confirm('Desligar o portátil?')) return;
    transport.request('shutdown').then(function () { toast('A desligar…'); }).catch(fail);
  };

  // ------------------------------------------------------------------ editor
  function addRow(name, url, category) {
    var row = document.createElement('div');
    row.className = 'row';
    row.innerHTML =
      '<input class="name" placeholder="Nome (ex: RTP 1)">' +
      '<input class="url" type="url" placeholder="https://…" autocapitalize="off" autocorrect="off">' +
      '<input class="category" list="categoryList" placeholder="Categoria (ex: Notícias)">' +
      '<div class="row-actions">' +
      '<button data-a="up">↑</button><button data-a="down">↓</button>' +
      '<button data-a="del" class="danger">Apagar</button></div>';
    row.querySelector('.name').value = name || '';
    row.querySelector('.url').value = url || '';
    row.querySelector('.category').value = category || '';
    row.querySelector('.row-actions').onclick = function (ev) {
      var a = ev.target.getAttribute('data-a');
      if (a === 'del') rows.removeChild(row);
      else if (a === 'up' && row.previousElementSibling) rows.insertBefore(row, row.previousElementSibling);
      else if (a === 'down' && row.nextElementSibling) rows.insertBefore(row.nextElementSibling, row);
    };
    rows.appendChild(row);
    return row;
  }

  function setEditing(on) {
    editor.className = 'editor' + (on ? '' : ' hidden');
    grid.className = 'grid' + (on ? ' hidden' : '');
    controls.className = on ? 'hidden' : '';
    $('tabs').className = on ? 'tabs hidden' : 'tabs';
    $('editBtn').className = on ? 'ghost hidden' : 'ghost';
    $('toast').className = 'toast';
    window.scrollTo(0, 0);
    if (on) {  // edit the channels of the open language tab only
      $('editGroup').textContent = GROUP_NAMES[activeGroup] || activeGroup;
      rows.innerHTML = '';
      var secs = sections(inGroup(activeGroup)), opts = $('categoryList');
      opts.innerHTML = '';
      secs.forEach(function (sec) {
        if (sec.name && sec.name !== 'Outros') {
          var o = document.createElement('option');
          o.value = sec.name;
          opts.appendChild(o);
        }
        // Rows in the order shown on the grid (grouped by category).
        sec.items.forEach(function (ch) { addRow(ch.name, ch.url, ch.category); });
      });
    }
  }

  $('editBtn').onclick = function () { if (transport) setEditing(true); };
  $('cancelBtn').onclick = function () { setEditing(false); };
  $('addBtn').onclick = function () {
    var last = rows.lastElementChild;
    addRow('', 'https://', last ? last.querySelector('.category').value : '').querySelector('.name').focus();
  };
  $('saveBtn').onclick = function () {
    // The other languages are sent back unchanged; this tab's rows replace its channels.
    var list = channels.filter(function (ch) { return groupOf(ch) !== activeGroup; }).map(function (ch) {
      return { name: ch.name, url: ch.url, group: groupOf(ch), category: ch.category || '' };
    });
    var mine = [];
    Array.prototype.forEach.call(rows.children, function (row) {
      var name = row.querySelector('.name').value.trim();
      var url = row.querySelector('.url').value.trim();
      var category = row.querySelector('.category').value.trim();
      if (name || (url && url !== 'https://')) mine.push({ name: name, url: url, group: activeGroup, category: category });
    });
    // Saved grouped by category, so the file reads like the grid.
    sections(mine).forEach(function (sec) { list = list.concat(sec.items); });
    transport.request('save', { channels: list }).then(function (res) {
      remember(res); ok();
      setEditing(false);
      render();
      toast('Guardado');
    }).catch(fail);
  };

  // ------------------------------------------------------------------ start
  transport = initTransport();
  activeGroup = store(KEYS.group) || 'PT';
  if (transport && transport.mode === 'relay') {
    // Show the last known channels at once; refresh them from the laptop.
    try { remember(JSON.parse(store(KEYS.state) || '{}')); } catch (e) {}
    render();
  }
  load();
  // Refresh when the app comes back to the foreground (at most once a minute
  // through the internet: ntfy.sh allows 250 messages a day).
  document.addEventListener('visibilitychange', function () {
    if (document.hidden || editor.className.indexOf('hidden') === -1) return;
    if (transport && transport.mode === 'relay' && Date.now() - lastSync < 60000) return;
    load();
  });

  if ('serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('sw.js').catch(function () {});
  }
})();
