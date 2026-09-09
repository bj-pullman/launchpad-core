(() => {
  const delay = (fn) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), 250); }; };
  async function search(url, q, signal) {
    const target = new URL(url, location.origin); target.searchParams.set('q', q);
    const response = await fetch(target, {signal, headers: {'X-Requested-With': 'XMLHttpRequest'}});
    if (!response.ok) throw new Error('Search unavailable. Reload or sign in again.');
    return response.json();
  }
  document.querySelectorAll('[data-record-picker]').forEach(form => {
    let controller;
    form.querySelector('[data-record-query]').addEventListener('input', delay(async e => {
      controller?.abort(); controller = new AbortController();
      const select = form.querySelector('select[name=record_id]');
      select.replaceChildren(new Option('Choose a Record', ''));
      try {
        const rows = await search(form.dataset.searchUrl, e.target.value, controller.signal);
        rows.forEach(r => select.add(new Option(`${r.display_name} · ${r.vendor_name || ''} · PO ${r.po_number || '—'}`, r.id)));
        form.querySelector('[data-picker-message]').textContent = rows.length ? '' : 'No matching Records.';
      } catch (error) { if (error.name !== 'AbortError') form.querySelector('[data-picker-message]').textContent = error.message; }
    }));
  });
  document.querySelectorAll('[data-renewal-workflow]').forEach(section => {
    const fields = section.querySelector('[data-renewal-fields]');
    const picker = section.querySelector('[data-renewal-picker]');
    const query = section.querySelector('[data-renewal-query]');
    const select = section.querySelector('[data-renewal-results]');
    const mode = section.querySelector('[name=renewal_mode]');
    const year = section.querySelector('[data-renewal-year]');
    const yearSelect = year.querySelector('select');
    const submit = section.querySelector('[data-renewal-submit]');
    const message = section.querySelector('[data-renewal-message]');
    let controller, generation = 0;
    function clearSelection() {
      select.replaceChildren(new Option('Choose a Renewal', ''));
      section.querySelector('[name=renewal_cycle_id]').value = '';
      section.querySelector('[name=renewal_id]').value = '';
      if (submit) submit.disabled = mode.value === 'link';
    }
    function showYear(show) {
      year.hidden = !show;
      yearSelect.disabled = !show;
      if (!show) yearSelect.value = '';
    }
    const load = delay(async (version) => {
      if (version !== generation || mode.value !== 'link') return;
      controller = new AbortController();
      try {
        const rows = await search(section.dataset.searchUrl, query.value, controller.signal);
        if (version !== generation) return;
        rows.forEach(r => select.add(new Option(
          [r.renewal_name, r.vendor_name, r.fiscal_year_label || 'Create initial cycle'].filter(Boolean).join(' · '),
          `${r.renewal_id}:${r.cycle_id || ''}`)));
        message.textContent = rows.length ? '' : 'No matching Renewals.';
      } catch (error) {
        if (error.name !== 'AbortError' && version === generation) message.textContent = error.message;
      }
    });
    function refresh() {
      controller?.abort();
      clearSelection();
      showYear(false);
      message.textContent = 'Searching…';
      load(++generation);
    }
    function setMode(value) {
      controller?.abort(); ++generation;
      mode.value = value;
      section.querySelector('[name=is_renewal]').value = value ? 'on' : '';
      fields.hidden = !value;
      picker.hidden = value !== 'link';
      select.required = value === 'link';
      select.disabled = value !== 'link';
      section.querySelector('[data-renewal-create]').hidden = value !== 'create';
      section.querySelectorAll('[data-renewal-action]').forEach(button =>
        button.setAttribute('aria-expanded', String(button.dataset.renewalAction === value)));
      clearSelection();
      showYear(value === 'create');
      message.textContent = '';
      if (submit) {
        submit.textContent = value === 'create' ? 'Create Renewal' : 'Link Renewal';
        submit.disabled = value === 'link';
      }
      if (value === 'link') { refresh(); query.focus(); }
    }
    section.querySelectorAll('[data-renewal-action]').forEach(button =>
      button.addEventListener('click', () => setMode(button.dataset.renewalAction)));
    section.querySelector('[data-renewal-cancel]').addEventListener('click', () => {
      setMode('');
      if (section.querySelector('[name=replace_link]')) section.closest('form').hidden = true;
      (document.querySelector('[data-renewal-change]') || section.querySelector('[data-renewal-action]')).focus();
    });
    document.querySelector('[data-renewal-change]')?.addEventListener('click', () => {
      section.closest('form').hidden = false;
      setMode('link');
    });
    query.addEventListener('input', refresh);
    select.addEventListener('change', () => {
      const [renewal, cycle] = select.value.split(':');
      section.querySelector('[name=renewal_id]').value = renewal || '';
      section.querySelector('[name=renewal_cycle_id]').value = cycle || '';
      showYear(Boolean(renewal && !cycle));
      if (submit) submit.disabled = !renewal;
    });
    setMode('');
  });
  const form = document.querySelector('[data-dirty-form]');
  if (form) {
    const snapshot = () => JSON.stringify(Array.from(new FormData(form), ([key, value]) =>
      [key, value instanceof File ? (value.name ? [value.name, value.size, value.lastModified] : null) : value])
      .filter(([key]) => key !== 'csrf_token'));
    let initial = snapshot(), submitting = false, destination = null, leaveTrigger = null;
    const dirty = () => !submitting && snapshot() !== initial;
    // Finance initializes derived dates/status on DOMContentLoaded; baseline afterward.
    document.addEventListener('DOMContentLoaded', () => { initial = snapshot(); }, {once: true});
    form.addEventListener('submit', event => {
      if (!event.defaultPrevented) submitting = true;
    });
    window.addEventListener('pageshow', () => { submitting = false; });
    window.addEventListener('beforeunload', event => {
      if (!dirty()) return;
      event.preventDefault();
      event.returnValue = '';
    });
    document.addEventListener('click', event => {
      const link = event.target.closest('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey ||
          event.shiftKey || event.altKey || link.target === '_blank' || link.hasAttribute('download')) return;
      const url = new URL(link.href, location.href);
      if (!['http:', 'https:'].includes(url.protocol) ||
          (url.pathname === location.pathname && url.search === location.search && url.hash)) return;
      if (!dirty()) return;
      event.preventDefault();
      destination = link.href;
      leaveTrigger = link;
      document.getElementById('record-exit-trigger').click();
    });
    document.getElementById('record-exit-confirm').addEventListener('click', () => {
      if (!destination) return;
      submitting = true;
      location.assign(destination);
    });
    document.getElementById('record-exit-modal').addEventListener('click', event => {
      if (event.target.closest('[data-modal-close]')) {
        window.requestAnimationFrame(() => leaveTrigger?.focus());
      }
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && leaveTrigger &&
          !document.getElementById('record-exit-modal').hidden) {
        window.requestAnimationFrame(() => leaveTrigger.focus());
      }
    });
  }
  const preview = document.querySelector('[data-po-preview]');
  const po = document.querySelector('[name=po_number]');
  if (preview && po) {
    let controller;
    const load = delay(async () => {
      controller?.abort(); controller = new AbortController();
      preview.replaceChildren(); if (!po.value.trim()) return;
      const url = new URL(preview.dataset.poPreview, location.origin);
      url.searchParams.set('po', po.value); if (preview.dataset.recordId) url.searchParams.set('exclude', preview.dataset.recordId);
      try {
        const response = await fetch(url, {signal: controller.signal, headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok) throw new Error('PO preview unavailable.');
        const data = await response.json();
        data.duplicates.forEach(r => {
          const p = document.createElement('p'); p.textContent = `Possible duplicate Record: another active Record uses PO ${data.po}. `;
          const link = document.createElement('a'); link.href = `/finance/records/${r.id}`; link.textContent = `Open ${r.name}`;
          p.append(link); preview.append(p);
        });
        data.years.forEach(y => {
          const p = document.createElement('p'); p.textContent = `Ledger activity found: ${y.fiscal_year} · ${y.transactions} transactions · $${y.paid} paid · $${y.open_encumbrance} remaining.`; preview.append(p);
        });
        if (data.transactions) { const p = document.createElement('p'); p.textContent = 'Qualifying unlinked transactions will be reconciled when you save. Ambiguous matches remain for review.'; preview.append(p); }
      } catch (error) { if (error.name !== 'AbortError') preview.textContent = error.message; }
    });
    po.addEventListener('input', load); load();
  }
})();
