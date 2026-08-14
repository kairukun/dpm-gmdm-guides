(function () {
  var search = document.getElementById('guide-search');
  var empty = document.getElementById('empty-state');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var groups = Array.prototype.slice.call(document.querySelectorAll('.group'));
  var sections = Array.prototype.slice.call(document.querySelectorAll('.section'));

  function apply(term) {
    if (!search) return;
    var q = term.trim().toLowerCase();
    var visible = 0;

    cards.forEach(function (card) {
      var hit =
        !q ||
        (card.dataset.name || '').indexOf(q) !== -1 ||
        (card.dataset.desc || '').indexOf(q) !== -1;
      card.hidden = !hit;
      if (hit) visible++;
    });

    groups.forEach(function (group) {
      var any = group.querySelector('.card:not([hidden])');
      group.hidden = !any;
    });

    sections.forEach(function (section) {
      var any = section.querySelector('.card:not([hidden])');
      section.hidden = !any;
    });

    if (empty) empty.hidden = visible !== 0;
  }

  if (search) {
    search.addEventListener('input', function () {
      apply(search.value);
    });
  }

  function rootPrefix() {
    return location.pathname.indexOf('/guides/') !== -1 ? '../' : '';
  }

  var SESSION_KEY = 'dpmEditorSession';
  var staticMode = false;

  function renderAuth(me) {
    var prefix = rootPrefix();
    document.querySelectorAll('[data-auth-slot]').forEach(function (slot) {
      slot.hidden = false;
      if (!me.authenticated) {
        slot.innerHTML = '<a class="nav-link" href="' + prefix + 'login.html">Editor sign in</a>';
        return;
      }
      var slug = slot.getAttribute('data-edit-slug');
      var bits = [];
      if (slug) {
        bits.push('<a class="btn btn-edit" href="' + prefix + 'edit.html?guide=' + encodeURIComponent(slug) + '">Edit guide</a>');
      }
      bits.push('<span class="editor-user">' + (me.user.email || 'Editor') + '</span>');
      bits.push('<button type="button" class="nav-link" data-logout>Sign out</button>');
      slot.innerHTML = bits.join('');
    });

    document.querySelectorAll('.auth-only').forEach(function (el) {
      el.hidden = !me.authenticated;
    });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-logout]');
    if (!btn) return;
    e.preventDefault();
    if (staticMode) {
      try { sessionStorage.removeItem(SESSION_KEY); } catch (err) {}
      location.reload();
      return;
    }
    fetch('/api/logout', { method: 'POST' }).then(function () {
      location.reload();
    }).catch(function () {
      location.href = rootPrefix() + 'login.html';
    });
  });

  // On the published copy there is no API; editing is unlocked with an access code.
  function renderStaticAuth() {
    staticMode = true;
    document.body.setAttribute('data-static-site', 'true');
    var unlocked = false;
    try { unlocked = !!sessionStorage.getItem(SESSION_KEY); } catch (err) {}
    if (unlocked) {
      renderAuth({ authenticated: true, user: { email: 'Signed in with access code' } });
      return;
    }
    fetch(rootPrefix() + 'assets/editor-key.json', { cache: 'no-store' })
      .then(function (r) {
        if (r.ok) renderAuth({ authenticated: false });
      })
      .catch(function () {});
  }

  fetch('/api/me')
    .then(function (r) {
      var type = r.headers.get('content-type') || '';
      if (!r.ok || type.indexOf('application/json') === -1) throw new Error('no api');
      return r.json();
    })
    .then(renderAuth)
    .catch(renderStaticAuth);
})();
