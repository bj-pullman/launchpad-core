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
    section.querySelector('[data-renewal-toggle]').addEventListener('change', e => { fields.hidden = !e.target.checked; });
    const picker = section.querySelector('[data-renewal-picker]');
    const query = section.querySelector('[data-renewal-query]');
    const select = section.querySelector('[data-renewal-results]');
    let controller;
    const load = delay(async () => {
      controller?.abort(); controller = new AbortController();
      select.replaceChildren(new Option('Choose a Renewal', ''));
      section.querySelector('[name=renewal_cycle_id]').value = '';
      section.querySelector('[name=renewal_id]').value = '';
      try {
        const rows = await search(section.dataset.searchUrl, query.value, controller.signal);
        rows.forEach(r => select.add(new Option(`${r.renewal_name} · ${r.vendor_name} · ${r.department_name} · ${r.fiscal_year_label || 'Create initial cycle'} · $${r.expected_cost || '0.00'}`, `${r.renewal_id}:${r.cycle_id || ''}`)));
        section.querySelector('[data-renewal-message]').textContent = rows.length ? '' : 'No matching Renewals.';
      } catch (error) { if (error.name !== 'AbortError') section.querySelector('[data-renewal-message]').textContent = error.message; }
    });
    section.querySelector('[data-renewal-mode]').addEventListener('change', e => { picker.hidden = e.target.value !== 'link'; if (!picker.hidden) load(); });
    query.addEventListener('input', load);
    select.addEventListener('change', () => {
      const [renewal, cycle] = select.value.split(':');
      section.querySelector('[name=renewal_id]').value = renewal || '';
      section.querySelector('[name=renewal_cycle_id]').value = cycle || '';
    });
  });
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
