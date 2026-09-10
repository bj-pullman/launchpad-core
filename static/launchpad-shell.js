(() => {
  const meta = name => document.querySelector(`meta[name="${name}"]`)?.content;
  const root = document.documentElement;
  const media = matchMedia('(prefers-color-scheme: dark)');
  function applyTheme(preference) {
    root.dataset.themePreference = preference;
    const resolved = preference === 'dark' || (preference === 'system' && media.matches) ? 'dark' : 'light';
    root.dataset.theme = resolved;
    // Keep legacy app selectors synchronized while :root remains authoritative.
    if (document.body) document.body.dataset.theme = resolved;
    document.querySelectorAll('[data-theme-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === preference));
      button.classList.toggle('active', button.dataset.themeChoice === preference);
    });
  }
  applyTheme(root.dataset.themePreference);
  media.addEventListener('change', () => applyTheme(root.dataset.themePreference));
  let themePending = false;
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-theme-choice]');
    if (!button || themePending) return;
    themePending = true;
    const messages = document.querySelectorAll('[data-theme-message]');
    try {
      const response = await fetch(meta('launchpad-theme-url'), {
        method: 'POST', headers: {'X-CSRF-Token': meta('launchpad-csrf'), 'X-Requested-With': 'XMLHttpRequest'},
        body: new URLSearchParams({theme_preference: button.dataset.themeChoice})
      });
      if (!response.ok || response.redirected) throw new Error('Theme was not saved. Reload or sign in again.');
      applyTheme(button.dataset.themeChoice);
      messages.forEach(message => { message.textContent = ''; });
    } catch (error) { messages.forEach(message => { message.textContent = error.message; }); }
    finally { themePending = false; }
  });

  // A request caused by polling is not human activity. Never advance activity
  // merely because a timer, fetch or heartbeat completed.
  let lastInteraction = Date.now();
  const recent = () => !document.hidden && Date.now() - lastInteraction < 60000;
  ['pointerdown', 'pointermove', 'keydown', 'touchstart', 'wheel'].forEach(name => {
    document.addEventListener(name, event => { if (event.isTrusted && !document.hidden) lastInteraction = Date.now(); }, {passive: true});
  });
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if (url.origin === location.origin) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      if (!headers.has('X-Launchpad-Background')) headers.set('X-Launchpad-Background', recent() ? '0' : '1');
      init = {...init, headers};
    }
    return originalFetch(input, init);
  };
  if (meta('launchpad-keep-active') === 'true') {
    let pending = false;
    const timer = setInterval(async () => {
      if (!recent() || pending) return;
      pending = true;
      try {
        const response = await originalFetch(meta('launchpad-activity-url'), {
          method: 'POST', headers: {'X-CSRF-Token': meta('launchpad-csrf'), 'X-Launchpad-Background': '1'}
        });
        if (response.status === 401 || response.status === 403) clearInterval(timer);
      } catch (_) { /* A later interaction may retry after a transient network error. */ }
      finally { pending = false; }
    }, 30000);
  }
})();
