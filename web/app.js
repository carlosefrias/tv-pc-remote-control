/* TV Remote phone app. Plain ES5 on purpose so it runs on older Android browsers. */
(function () {
  'use strict';

  var TOKEN_KEY = 'tvremote.token';
  var token = '';
  var channels = [];
  var current = null;

  var $ = function (id) { return document.getElementById(id); };
  var grid = $('grid'), editor = $('editor'), rows = $('rows'), controls = $('controls');

  // ---- token: taken from ?t=... once, then remembered on this phone ----
  function initToken() {
    var m = /[?&]t=([^&]+)/.exec(location.search);
    if (m) {
      token = decodeURIComponent(m[1]);
      try { localStorage.setItem(TOKEN_KEY, token); } catch (e) {}
      // Keep the token in the URL so "Add to Home screen" also carries it.
    } else {
      try { token = localStorage.getItem(TOKEN_KEY) || ''; } catch (e) {}
    }
  }

  // ---- API ----
  function api(method, path, body) {
    var opts = { method: method, headers: { 'X-Token': token } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var msg = data.error || ('Erro ' + r.status);
          if (r.status === 401) msg = 'Token inválido – abra o link com ?t=TOKEN mostrado no portátil';
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  var toastTimer;
  function toast(msg, isError) {
    var t = $('toast');
    t.textContent = msg;
    t.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = 'toast'; }, isError ? 4000 : 1800);
  }
  function fail(err) { toast(err.message || 'Sem ligação ao portátil', true); }

  // ---- grid ----
  var PALETTE = ['#1f5fbf', '#2e7d4f', '#b3541e', '#7b3fa8', '#b02a4a', '#0f7c86',
                 '#8a6d1a', '#4a5bb0', '#6b8e23', '#a23b8f', '#c0392b', '#2c6e8f'];
  function colorFor(index) { return PALETTE[index % PALETTE.length]; }

  function renderGrid() {
    grid.innerHTML = '';
    if (!channels.length) {
      grid.innerHTML = '<div class="empty">Sem canais. Toque em Editar para adicionar.</div>';
      return;
    }
    channels.forEach(function (ch, i) {
      var b = document.createElement('button');
      b.className = 'tile' + (ch.id === current ? ' current' : '');
      b.style.background = colorFor(i);
      b.textContent = ch.name;
      b.onclick = function () { play(ch, b); };
      grid.appendChild(b);
    });
  }

  function play(ch, el) {
    el.className += ' busy';
    api('POST', '/api/play', { id: ch.id }).then(function (res) {
      current = res.current;
      renderGrid();
      toast('▶ ' + ch.name);
    }).catch(function (e) { renderGrid(); fail(e); });
  }

  function load() {
    return api('GET', '/api/channels').then(function (res) {
      channels = res.channels;
      current = res.current;
      renderGrid();
    }).catch(fail);
  }

  // ---- controls ----
  Array.prototype.forEach.call(document.querySelectorAll('[data-vol]'), function (b) {
    b.onclick = function () {
      api('POST', '/api/volume', { action: b.getAttribute('data-vol') }).catch(fail);
    };
  });

  $('stopBtn').onclick = function () {
    api('POST', '/api/stop').then(function () {
      current = null; renderGrid(); toast('Parado');
    }).catch(fail);
  };

  $('powerBtn').onclick = function () {
    if (!confirm('Desligar o portátil?')) return;
    api('POST', '/api/shutdown').then(function () { toast('A desligar…'); }).catch(fail);
  };

  // ---- editor ----
  function addRow(name, url) {
    var row = document.createElement('div');
    row.className = 'row';
    row.innerHTML =
      '<input class="name" placeholder="Nome (ex: RTP 1)">' +
      '<input class="url" type="url" placeholder="https://…" autocapitalize="off" autocorrect="off">' +
      '<div class="row-actions">' +
      '<button data-a="up">↑</button><button data-a="down">↓</button>' +
      '<button data-a="del" class="danger">Apagar</button></div>';
    row.querySelector('.name').value = name || '';
    row.querySelector('.url').value = url || '';
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
    $('editBtn').className = on ? 'ghost hidden' : 'ghost';
    $('toast').className = 'toast';
    window.scrollTo(0, 0);
    if (on) {
      rows.innerHTML = '';
      channels.forEach(function (ch) { addRow(ch.name, ch.url); });
    }
  }

  $('editBtn').onclick = function () { setEditing(true); };
  $('cancelBtn').onclick = function () { setEditing(false); };
  $('addBtn').onclick = function () { addRow('', 'https://').querySelector('.name').focus(); };
  $('saveBtn').onclick = function () {
    var list = [];
    Array.prototype.forEach.call(rows.children, function (row) {
      var name = row.querySelector('.name').value.trim();
      var url = row.querySelector('.url').value.trim();
      if (name || (url && url !== 'https://')) list.push({ name: name, url: url });
    });
    api('PUT', '/api/channels', { channels: list }).then(function (res) {
      channels = res.channels;
      current = res.current;
      setEditing(false);
      renderGrid();
      toast('Guardado');
    }).catch(fail);
  };

  initToken();
  load();
  // Refresh when the app comes back to the foreground (e.g. channel changed elsewhere).
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && editor.className.indexOf('hidden') !== -1) load();
  });
})();
