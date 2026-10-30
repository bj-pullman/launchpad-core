(() => {
  'use strict';
  const root = document.querySelector('[data-ledger-review]');
  if (!root) return;
  const feedback = root.querySelector('[data-review-message]');
  const modal = document.querySelector('[data-ledger-modal]');
  const modalForm = modal?.querySelector('form');
  let opener = null;
  // Keep fixed positioning outside ancestors with transforms/stacking contexts.
  if (modal) document.body.append(modal);
  const pickerStates = new WeakMap();
  let busy = false, uncertainSave = false;
  const announce = message => {
    feedback.textContent = message;
    if (modal && !modal.hidden) modal.querySelector('[data-ledger-modal-message]').textContent = message;
  };
  const currentUrl = () => root.querySelector('[data-review-results]').dataset.currentUrl;

  function stateFor(form) {
    let state = pickerStates.get(form);
    if (!state) {
      state = {initialized: false, generation: 0, controller: null, timer: null, loading: false};
      pickerStates.set(form, state);
    }
    return state;
  }
  function pickerMessage(form, message) {
    form.querySelector('[data-review-picker-message]').textContent = message;
  }
  function updatePickerButtons(form) {
    const state = stateFor(form);
    form.querySelector('[data-review-link-button]').disabled =
      busy || uncertainSave || (form.elements.action.value === 'link' &&
        (state.loading || !form.querySelector('[data-review-record-select]').value));
  }
  function initializePicker(form) {
    const state = stateFor(form);
    if (state.initialized) return;
    state.initialized = true;
    const seed = root.querySelector('[data-review-initial-records]');
    const select = form.querySelector('[data-review-record-select]');
    select.replaceChildren(new Option('Choose a Record', ''));
    if (seed) {
      select.append(seed.content.cloneNode(true));
    }
    pickerMessage(form, select.options.length > 1
      ? `${select.options.length - 1} available Records. Search to narrow the list.`
      : 'No available Finance Records in this department.');
    updatePickerButtons(form);
  }
  function resetPicker() {
    const state = stateFor(modalForm);
    state.controller?.abort();
    clearTimeout(state.timer);
    state.generation += 1;
    state.initialized = false;
    state.loading = false;
  }
  function closeModal() {
    if (!modal || modal.hidden || busy) return;
    resetPicker();
    modal.hidden = true;
    document.body.classList.remove('finance-modal-open');
    (opener?.isConnected ? opener : root.querySelector('[data-review-refresh]'))?.focus({preventScroll: true});
  }
  function openModal(button) {
    if (!modal || busy) return;
    if (uncertainSave) { announce('Refresh the Ledger before submitting another action.'); return; }
    const transaction = JSON.parse(button.dataset.transaction);
    const mode = button.dataset.ledgerOpen;
    resetPicker();
    opener = button;
    modalForm.elements.ledger_id.value = transaction.id;
    modalForm.elements.row_version.value = transaction.version;
    modalForm.elements.action.value = mode;
    modal.querySelector('#ledger-record-title').textContent = mode === 'create' ? 'Create Record' : 'Link Record';
    modal.querySelector('[data-ledger-modal-subtitle]').textContent = mode === 'create'
      ? 'Promote this Ledger transaction to a Finance Record.' : 'Choose an existing Finance Record for this transaction.';
    modal.querySelector('[data-ledger-modal-description]').textContent = transaction.vendor + ' — ' + transaction.label;
    modal.querySelector('[data-ledger-modal-context]').textContent = 'PO ' + transaction.po + ' · ' + transaction.date;
    modal.querySelector('[data-ledger-match]').textContent = transaction.suggested
      ? 'Suggested: ' + transaction.suggested + (transaction.reason ? ' · ' + transaction.reason : '') : '';
    modal.querySelector('[data-ledger-picker]').hidden = mode !== 'link';
    modal.querySelector('[data-ledger-create-help]').hidden = mode !== 'create';
    const select = modalForm.querySelector('[data-review-record-select]');
    select.disabled = mode !== 'link';
    select.required = mode === 'link';
    modalForm.querySelector('[data-review-record-query]').value = '';
    modal.querySelector('[data-ledger-modal-message]').textContent = '';
    modalForm.querySelector('[data-review-link-button]').textContent = mode === 'create' ? 'Create and Link Record' : 'Link Record';
    initializePicker(modalForm);
    modal.hidden = false;
    document.body.classList.add('finance-modal-open');
    (mode === 'link' ? modal.querySelector('[data-review-record-query]') : modal.querySelector('.finance-modal-dialog')).focus();
  }
  async function loadRecords(form, generation) {
    const state = stateFor(form);
    if (generation !== state.generation || !form.isConnected) return;
    state.controller = new AbortController();
    state.loading = true;
    updatePickerButtons(form);
    pickerMessage(form, 'Loading Records…');
    const url = new URL(form.dataset.searchUrl, location.origin);
    url.searchParams.set('q', form.querySelector('[data-review-record-query]').value);
    try {
      const response = await fetch(url, {
        signal: state.controller.signal, credentials: 'same-origin', cache: 'no-store',
        headers: {'X-Requested-With': 'XMLHttpRequest'}
      });
      if (response.redirected || !response.ok) throw new Error('Record search is unavailable. Refresh or sign in again.');
      const data = await response.json();
      if (!Array.isArray(data.rows)) throw new Error('Record search returned an unexpected response.');
      if (generation !== state.generation || !form.isConnected) return;
      const select = form.querySelector('[data-review-record-select]');
      select.replaceChildren(new Option('Choose a Record', ''));
      const existing = new Set(Array.from(select.options, option => option.value));
      for (const record of data.rows) {
        const value = String(record.id);
        if (!existing.has(value)) {
          select.add(new Option(record.label, value));
          existing.add(value);
        }
      }
      pickerMessage(form, select.options.length > 1
        ? `${select.options.length - 1} matching Records.` : 'No matching Finance Records.');
    } catch (error) {
      if (error.name !== 'AbortError' && generation === state.generation && form.isConnected) pickerMessage(form, error.message);
    } finally {
      if (generation === state.generation && form.isConnected) {
        state.loading = false;
        updatePickerButtons(form);
      }
    }
  }
  function refreshRecordSearch(form) {
    const state = stateFor(form);
    state.controller?.abort();
    clearTimeout(state.timer);
    state.generation += 1;
    state.loading = true;
    form.querySelector('[data-review-record-select]').replaceChildren(new Option('Choose a Record', ''));
    pickerMessage(form, 'Searching…');
    updatePickerButtons(form);
    const generation = state.generation;
    state.timer = setTimeout(() => loadRecords(form, generation), 250);
  }
  async function requestReview(url, options = {}) {
    const response = await fetch(url, {
      ...options, credentials: 'same-origin', cache: 'no-store',
      headers: {'X-Ledger-Review': '1', 'X-Requested-With': 'XMLHttpRequest'}
    });
    if (response.redirected || !(response.headers.get('Content-Type') || '').includes('application/json')) {
      throw new Error('The server response could not be confirmed.');
    }
    const data = await response.json();
    if (!response.ok || !data.ok) {
      const error = new Error(data.message || 'The operation failed.');
      error.confirmedFailure = data.ok === false;
      throw error;
    }
    return data;
  }
  function replaceResults(data) {
    if (typeof data.html !== 'string' || typeof data.url !== 'string') throw new Error('The server returned an incomplete Ledger response.');
    const oldResults = root.querySelector('[data-review-results]');
    const template = document.createElement('template');
    template.innerHTML = data.html;
    const newResults = template.content.querySelector('[data-review-results]');
    if (!newResults) throw new Error('The refreshed review could not be displayed.');
    const tableScroll = oldResults.querySelector('.table-wrap')?.scrollLeft || 0;
    const scrollX = window.scrollX, scrollY = window.scrollY;
    oldResults.replaceWith(newResults);
    const wrap = newResults.querySelector('.table-wrap');
    if (wrap) wrap.scrollLeft = tableScroll;
    const count = root.querySelector('[data-unresolved-count]');
    if (count && Number.isInteger(data.unresolved_count)) count.textContent = String(data.unresolved_count);
    history.replaceState(history.state, '', data.url);
    window.scrollTo(scrollX, scrollY);
  }
  async function refreshReview() {
    if (busy) return;
    busy = true;
    root.setAttribute('aria-busy', 'true');
    announce('Refreshing review…');
    try {
      const data = await requestReview(currentUrl());
      replaceResults(data);
      uncertainSave = false;
      announce('Review refreshed.');
    } catch (error) {
      announce('Unable to refresh. Reload the page or sign in again.');
    } finally {
      busy = false;
      root.removeAttribute('aria-busy');
      if (!uncertainSave) closeModal();
    }
  }
  modal?.addEventListener('input', event => {
    if (busy) return;
    if (event.target.matches('[data-review-record-query]')) refreshRecordSearch(event.target.closest('[data-review-link-form]'));
  });
  modal?.addEventListener('change', event => {
    if (event.target.matches('[data-review-record-select]')) updatePickerButtons(modalForm);
  });
  root.addEventListener('change', event => {
    if (event.target.matches('[data-review-page-size]') && !busy) root.querySelector('[data-review-filters]').requestSubmit();
  });
  root.addEventListener('click', event => {
    if (busy && event.target.closest('a')) {
      event.preventDefault(); announce('Please wait for the current operation to finish.'); return;
    }
    if (event.target.closest('[data-review-refresh]')) { refreshReview(); return; }
    const button = event.target.closest('[data-ledger-open]');
    if (button) openModal(button);
  });
  modal?.addEventListener('click', event => {
    if (busy) return;
    if (event.target.closest('[data-ledger-close]')) { closeModal(); return; }
  });
  modal?.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeModal(); }
    if (event.key !== 'Tab') return;
    const controls = Array.from(modal.querySelectorAll('button, input, select, [tabindex]'))
      .filter(element => !element.disabled && element.tabIndex >= 0 && element.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !controls.includes(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
  async function submitAction(event) {
    const form = event.target;
    if (!form.matches('[data-review-action]')) {
      if (busy) { event.preventDefault(); announce('Please wait for the current operation to finish.'); }
      return;
    }
    event.preventDefault();
    if (busy) { announce('Please wait for the current operation to finish.'); return; }
    if (uncertainSave) { announce('Refresh the Ledger before submitting another action.'); return; }
    const body = new FormData(form), submitter = event.submitter;
    if (submitter?.name) body.set(submitter.name, submitter.value);
    if (body.get('action') === 'link' && !body.get('record_id')) { announce('Choose a Finance Record first.'); return; }
    const controls = Array.from(form.querySelectorAll('button, input, select'));
    const disabledStates = controls.map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    busy = true; root.setAttribute('aria-busy', 'true'); announce('Saving review…');
    let saved = false;
    try {
      const data = await requestReview(root.dataset.actionUrl || currentUrl(), {method: 'POST', body});
      saved = true;
      replaceResults(data.html ? data : await requestReview(currentUrl()));
      announce(data.message || 'Ledger review saved.');
    } catch (error) {
      if (error.confirmedFailure) announce(error.message);
      else {
        uncertainSave = true;
        announce(saved ? 'Saved successfully, but the table could not refresh. Close this dialog and refresh the Ledger before another action.'
          : 'The save result could not be confirmed. It may have succeeded. Close this dialog and refresh the Ledger before trying another action.');
      }
    } finally {
      controls.forEach((control, index) => { control.disabled = disabledStates[index]; });
      busy = false; root.removeAttribute('aria-busy');
      if (form.isConnected && form.matches('[data-review-link-form]')) updatePickerButtons(form);
      if (saved && !uncertainSave) closeModal();
    }
  }
  root.addEventListener('submit', submitAction);
  modal?.addEventListener('submit', submitAction);
})();
