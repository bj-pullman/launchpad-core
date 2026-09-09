# Coordinated Launchpad update

Implemented in the local working tree. No commit, push, deployment, production database migration, or outbound notification was performed. Tests used disposable databases; notification delivery was mocked in the Record-form test.

## Behavior

Settings → Security now manages idle timeout, absolute lifetime, Remember Me duration, activity-aware keepalive, required sign-in, and Secure/HttpOnly/SameSite cookie policy. A single database snapshot supplies each request's policy, so saved policy applies on subsequent requests across workers without changing shared per-process configuration.

Zero means Never for idle and absolute limits. Zero Remember Me days disables persistent sign-in. Remember Me retains the cookie across browser restarts, but does not bypass idle or absolute limits. Its expiration is anchored to authentication time. Existing cookie names and signing keys are preserved.

The shared browser script records trusted pointer, keyboard, wheel and touch interactions. Heartbeats run every 30 seconds only while a visible tab has interacted within the last minute. Background fetches are marked separately and do not renew idle activity. Existing tabs need a navigation/reload to pick up a newly enabled keepalive setting; disabling it is enforced immediately on the server.

Finance Records have optional user-maintained friendly names. A shared `record_name` template filter and `record_display_name` Python helper fall back to the unchanged source title. Searches retain both names. Vendor names use a separate `vendor_friendly_name` alias to avoid confusing vendor and Record metadata.

Vendors remain global. Ledger imports keep their existing code-first/name-fallback reuse behavior. Imports preserve vendor metadata, Record friendly names, source titles, notes, selected categories, Renewal links, manual Ledger links, and ignored/reviewed decisions. The legacy Record importer updates accounting cost on an existing Record without rewriting curated metadata.

Light, Dark and System use the existing user preference and account endpoint. System resolves through `prefers-color-scheme` and responds to OS changes. The shared head initializes the resolved theme before the body is painted. Common surfaces and controls use shared tokens across Launchpad, Settings, Finance, Staff Status, SnipeOps and its sub-apps, including Media Catalog. Application accents are retained.

## Ledger → Record → Renewal

1. An import performs the existing accounting updates and safe Record matching. PO normalization is shared on both sides. Multiple active Records with the same base PO remain unresolved; the importer does not pick the newest or create a third Record.
2. Import completion opens a department-scoped summary with linked, possible-match, needs-review and reviewed/ignored counts, followed by Review Unlinked Transactions. These counts reflect current persisted state for that run, not a separate historical snapshot.
3. Review shows the vendor, description, PO, accounting amounts, account, fiscal year, suggested Record, confidence and reason. Users can search both Record names and source titles, Link, Create Record, Ignore or Mark Reviewed. Manual links cannot cross the current department. Direct creation from review avoids an existing same-PO Record; intentional duplicate Records can still be created through Add Record.
4. Record create/edit previews PO activity separately by fiscal year and warns about another active Record with the same base PO. Saving immediately reconciles qualifying unlinked Ledger rows using the accounting matcher. Reviewed, ignored and already linked rows stay untouched.
5. The Record form/detail Renewal section can create a Renewal from the Record or search existing Renewals and cycles. Search includes related Record titles/friendly names, PO, vendor, category and department. A new-cycle fiscal year can be selected explicitly or inferred from the Record/current year.
6. Creation copies the preferred Record name, vendor, category, department, expected cost, dates, notification settings, notes and PO context into the existing Renewal/Cycle architecture. Creation and linkage commit atomically; a failed link rolls back the new Renewal and cycle.
7. Record Relationships links to its Ledger activity, Purchase Orders and Renewal with fiscal-year context. Ledger filters also expose linked, unlinked, ignored and reviewed states.

## Schema and configuration

- `finance_records.friendly_name TEXT NULL` is added with the existing guarded `_ensure_column` migration. Existing titles and other values are not rewritten or backfilled.
- Finance initialization now ensures the existing Ledger schema is available before Record-save reconciliation, including on a fresh database. No parallel Vendor, Renewal, Settings or theme tables were introduced.
- Existing `users.theme_preference` is already unconstrained text. Validation now accepts `system`, `light` and `dark`; no table rebuild is needed. Existing users and the `light` default remain unchanged.
- Existing session settings are reused: `security.session_idle_timeout_minutes`, `security.session_absolute_timeout_hours`, `security.session_remember_me_days` and `security.require_login_for_launchpad`.
- `security.session_keep_active` is new and defaults to false when absent. Existing `security.cookie_secure`, `security.cookie_httponly` and `security.cookie_samesite` are exposed and read live. SameSite None requires Secure.
- Defaults apply to missing settings without overwriting saved policy; saving Security persists a complete validated policy in one transaction.
- `security.cookie_name` remains the existing bootstrap cookie identity loaded at startup. Changing it would require coordinated cookie replacement/sign-in, so it is not a live policy control.
- `SECRET_KEY` remains deployment configuration. No secrets were moved into the database. Existing integration-secret storage was not redesigned.
- Obsolete session/cookie examples were removed from `.env.example`; they were already ignored by the database-backed implementation.
- `.gitignore` now permits the supplied workflow, JavaScript, Media Catalog and preview tests to be reviewed and versioned.

## Session-expiration investigation

Confirmed code defects addressed:

- Zero was compared as a zero-length timeout, expiring sessions immediately instead of implementing Never.
- `start_user_session` changed `current_app.permanent_session_lifetime` for a remembered login, affecting other users on that worker and making behavior depend on worker history.
- Flask also used the application-wide permanent lifetime when accepting signed cookies, including non-permanent cookies. That implicit limit could conflict with explicit policy. The existing signed-cookie interface is extended to enforce authenticated session age explicitly; anonymous/OAuth bootstrap state retains Flask's signature-age limit.
- Timezone-naive legacy timestamps could trigger subtraction errors against timezone-aware UTC. A broad exception handler then silently reset the session. UTC-naive legacy values are now normalized; missing, malformed and implausibly future values produce explicit termination reasons.
- Policy loaded only at startup could differ from the settings an administrator believed were active. Policy is now read on each request.
- Merely working within a loaded page did not necessarily contact the server. Activity-gated keepalive can now account for that work without keeping unattended tabs alive.
- App-specific static assets now remain exempt from required-login redirects, and dynamic session responses are marked no-store.

All explicit authenticated-session clears use reason logging, including timeout, malformed timestamp, invalid authentication state, reauthentication and logout. Rejected cookie signatures are logged without the cookie. Logs contain reason, endpoint and method, not credentials, cookies, CSRF values or session payloads.

The repository's IIS reverse-proxy forwarding and ProxyFix configuration were inspected. No evidence in the checked-in proxy configuration establishes a separate short timeout. Workers must still share a stable `SECRET_KEY` and consistent database configuration. No production cookies, runtime settings or incident traces were collected. Therefore the exact trigger of the reported less-than-30-minute logout is not proven; the new termination logs should identify future occurrences. A cookie discarded by the browser never reaches the server and cannot be diagnosed solely by application timeout logging.

## Validation

- Full Python suite: `python -m unittest discover -s tests -v` — 54 passed.
- Browser-script behavior: `node --test tests/test_launchpad_shell.cjs` — 5 passed.
- JavaScript syntax: `node --check apps/finance/static/finance/record_workflow.js` — passed.
- Python compile checks and Jinja compilation/route rendering — passed.
- Tests cover actual Ledger import execution, manual-link/review preservation, vendor reuse and metadata, both Record-name searches, delayed reconciliation, ambiguous PO handling, Renewal creation/link rollback, permissions, Security saves, signed-cookie age, malformed timestamps, policy updates and all theme values.
- One pre-existing local Media Catalog test depended on today's date despite creating an August 2026 checkout. Its clock is now fixed to the scenario date; application behavior was not changed for that test.
- Self-contained preview HTML can be exported with `python -m unittest discover -s tests -p launchpad_visual_preview.py`. These use disposable data and are not screenshot validation.

## Remaining verification and limits

Visual verification remains outstanding: the in-app browser execution tool was unavailable, and local headless Edge/Chrome exited without screenshots. Template rendering, route behavior and JavaScript logic passed, but desktop/mobile layout and theme contrast should still be checked in the development browser, including app modals and SSO redirects under the chosen cookie policy.

The existing client-side signed-session architecture remains. Logout clears the browser's cookie; this change does not introduce centralized token revocation or a server-side session store. Concurrent responses can still carry older signed session snapshots. A persistent server-side session system would be a separate architectural decision.

PO matching remains department-scoped and follows the existing cross-fiscal-year Record architecture. A reused PO with multiple active Records is deliberately left for review. Large departments may benefit from indexed normalized Record PO storage if profiling shows the current matching scan to be expensive.

Archived/deleted Records are not automatically matched. Reviewed/ignored rows do not auto-reconcile. Existing Renewal links must be managed through the established Renewal workflow before reassignment. If Record save succeeds but optional Renewal validation fails, the UI reports that the Record was saved and the Renewal needs attention; new Renewal/Cycle/link creation itself is atomic.

## Files changed

The exact working-tree paths are listed below.

- `.env.example`
- `.gitignore`
- `apps/finance/blueprint.py`
- `apps/finance/db.py`
- `apps/finance/ledger_accounting_service.py`
- `apps/finance/ledger_import_service.py`
- `apps/finance/ledger_query_service.py`
- `apps/finance/ledger_routes.py`
- `apps/finance/ledger_service.py`
- `apps/finance/ledger_validation_service.py`
- `apps/finance/page_total_service.py`
- `apps/finance/record_names.py`
- `apps/finance/record_renewal_service.py`
- `apps/finance/record_workflow_routes.py`
- `apps/finance/record_workflow_service.py`
- `apps/finance/renewal_service.py`
- `apps/finance/routes.py`
- `apps/finance/service.py`
- `apps/finance/setup_guard_routes.py`
- `apps/finance/static/finance/finance.css`
- `apps/finance/static/finance/record_workflow.js`
- `apps/finance/templates/finance/_record_renewal_form.html`
- `apps/finance/templates/finance/ledger.html`
- `apps/finance/templates/finance/ledger_detail.html`
- `apps/finance/templates/finance/ledger_review.html`
- `apps/finance/templates/finance/record_detail.html`
- `apps/finance/templates/finance/record_form.html`
- `apps/finance/templates/finance/records.html`
- `apps/finance/templates/finance/records_archived.html`
- `apps/finance/templates/finance/records_deleted.html`
- `apps/finance/templates/finance/renewal_activity.html`
- `apps/finance/templates/finance/renewal_detail.html`
- `apps/finance/templates/finance/vendor_detail.html`
- `apps/launchpad_ui/routes.py`
- `apps/launchpad_ui/static/launchpad_ui/launchpad.css`
- `apps/launchpad_ui/static/launchpad_ui/login.css`
- `apps/launchpad_ui/static/launchpad_ui/settings.css`
- `apps/launchpad_ui/static/launchpad_ui/setup/setup.css`
- `apps/launchpad_ui/templates/launchpad_ui/base.html`
- `apps/launchpad_ui/templates/launchpad_ui/settings/groups.html`
- `apps/launchpad_ui/templates/launchpad_ui/settings/security.html`
- `apps/launchpad_ui/templates/launchpad_ui/settings/users.html`
- `apps/snipeops/checkout_assets/static/css/checkout_assets.css`
- `apps/snipeops/import_by_scan/static/css/import_by_scan.css`
- `apps/snipeops/media_catalog/static/css/media_catalog.css`
- `apps/snipeops/secure_user_rostering/static/css/secure_user_rostering.css`
- `apps/snipeops/snipe_catalog/static/css/snipe_catalog.css`
- `apps/snipeops/static/snipeops/css/snipeops.css`
- `apps/snipeops/templates/snipeops/base.html`
- `apps/staff_status/static/staff_status.css`
- `apps/staff_status/templates/staff_status/board_public.html`
- `apps/staff_status/templates/staff_status/kiosk.html`
- `docs/launchpad-coordinated-update.md`
- `modules/core/app_factory.py`
- `modules/core/auth/routes.py`
- `modules/core/auth/session_policy.py`
- `modules/core/identity/user_service.py`
- `static/launchpad-shell.js`
- `static/launchpad-theme.css`
- `templates/layouts/_theme_head.html`
- `templates/layouts/_theme_picker.html`
- `templates/layouts/base_public.html`
- `tests/launchpad_visual_preview.py`
- `tests/test_launchpad_shell.cjs`
- `tests/test_launchpad_workflows.py`
- `tests/test_media_catalog_student_checkouts.py`
