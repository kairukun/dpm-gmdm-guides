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
        bits.push('<a class="btn btn-edit" href="' + prefix + 'edit/' + encodeURIComponent(slug) + '">Edit guide</a>');
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
    fetch('/api/logout', { method: 'POST' }).then(function () {
      location.reload();
    }).catch(function () {
      location.href = rootPrefix() + 'login.html';
    });
  });

  // The published copy is static, so sign-in stays hidden unless the API answers.
  fetch('/api/me')
    .then(function (r) {
      var type = r.headers.get('content-type') || '';
      if (!r.ok || type.indexOf('application/json') === -1) throw new Error('no api');
      return r.json();
    })
    .then(renderAuth)
    .catch(function () {
      document.body.setAttribute('data-static-site', 'true');
    });
})();
