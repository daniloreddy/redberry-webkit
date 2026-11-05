/* redberry-webkit-ui — shared behaviour of the page chrome. Served at /ui/_assets/app.js and loaded
   at the end of <body> by every webkit (Go, Java, Python), so it runs after the DOM it touches.
   The anti-flash theme boot script is NOT here: it must stay inline in <head> to run before paint. */

(function () {
  // Dark/light toggle: persisted in localStorage ("dark_mode"), applied via <html data-theme>.
  var b = document.getElementById('wk-theme-toggle');
  if (!b) return;
  b.addEventListener('click', function () {
    var d = document.documentElement.getAttribute('data-theme') !== 'dark';
    document.documentElement.setAttribute('data-theme', d ? 'dark' : 'light');
    try { localStorage.setItem('dark_mode', String(d)); } catch (e) {}
  });
})();

(function () {
  // Relocate a project's auto-refresh status line into the shared footer. An
  // auto-refreshing page renders <label class="refresh-lbl"> at the tail of
  // #live ("Aggiornato: HH:MM:SS · auto-refresh Ns"); we copy its text into
  // #wk-live-status on the app-name row and keep it in sync on every HTMX swap.
  var slot = document.getElementById('wk-live-status');
  if (!slot) return;
  function sync() {
    // Clear (not bail) when the label is gone: a fragment swap can bring in a
    // template without #live .refresh-lbl, and a stale timestamp frozen in the
    // footer would never update again.
    var src = document.querySelector('#live .refresh-lbl');
    slot.textContent = src ? src.textContent : '';
    if (src) document.documentElement.classList.add('wk-has-live-status');
  }
  document.addEventListener('htmx:afterSwap', sync);
  sync();
})();

(function () {
  // Request tables: upgrade an error status badge from its native title=
  // tooltip to a click-to-open popover holding the full, selectable message.
  // Progressive enhancement — with no JS the title tooltip still works.
  var pop = null;
  function close() { if (pop) { pop.remove(); pop = null; } }
  document.addEventListener('click', function (e) {
    var badge = e.target.closest ? e.target.closest('.wk-status.err[data-error]') : null;
    if (!badge) { close(); return; }
    e.preventDefault();
    if (pop && pop._for === badge) { close(); return; }
    close();
    pop = document.createElement('div');
    pop.className = 'wk-status-pop';
    pop.textContent = badge.getAttribute('data-error');
    pop._for = badge;
    document.body.appendChild(pop);
    var r = badge.getBoundingClientRect();
    pop.style.top = Math.max(8, Math.min(r.bottom + 6, window.innerHeight - pop.offsetHeight - 8)) + 'px';
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + 'px';
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  document.addEventListener('htmx:beforeSwap', close);
})();
