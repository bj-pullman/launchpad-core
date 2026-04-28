# First-Time Setup Wizard

The Setup Wizard helps administrators stand up Launchpad in a clean and predictable order. It is primarily a first-run experience, but administrators may return to the setup area later to review skipped or incomplete items.

## Setup philosophy

The wizard should help administrators understand what each setup step enables, what happens if they skip it, and where they can configure it later. The goal is to avoid noisy warnings throughout the app while still making important dependencies clear.

## Required step: Local Admin

Local administrator setup cannot be skipped.

### What this step does

Creates the initial Launchpad administrator account. This account is required to access settings, configure integrations, manage users, and recover access if an external sign-in provider is unavailable.

### Why it matters

The local administrator is the break-glass account for Launchpad. Even if Google, Microsoft, SAML, or another identity provider is misconfigured, the local admin should still be able to sign in and repair the system.

### Skip behavior

This step cannot be skipped.

## Organization Basics

### What this step does

Configures organization-wide settings such as organization name, public base URL, timezone, date format, and time format.

### Why it matters

These settings control how Launchpad displays dates and times and how it generates public-facing links such as Staff Status kiosk URLs, board URLs, and password setup links.

### If skipped

Launchpad will still work, but generated links and displayed times may be incorrect until these settings are configured.

### Configure later

Settings -> General

## Email Integration

### What this step does

Configures the SMTP relay Launchpad uses to send system email.

### Why it matters

Email is used for account setup links, password reset links, Finance renewal reminders, and future notification workflows.

### If skipped

Launchpad will still work, but email-based features will not be available. Local user imports may still create accounts, but users will not receive setup links.

### Configure later

Settings -> Integrations -> Email

## Authentication

### What this step does

Configures sign-in methods and access rules. Launchpad may support local login, Google OIDC, Microsoft OIDC, SAML, or other identity providers depending on configuration.

### Why it matters

Authentication determines how users sign in and whether external users are allowed into Launchpad. Access rules also help prevent unauthorized sign-ins.

### If skipped

Users will only be able to sign in using whatever default local authentication behavior is enabled. External sign-in providers will remain unavailable until configured.

### Configure later

Settings -> Authentication

## Users

### What this step does

Guides administrators through user creation, import requirements, account type choices, and invite behavior.

### Why it matters

Users must exist in Launchpad before they can sign in through SSO or use applications that depend on staff identity, such as Staff Status.

### If skipped

Users must be created manually later before they can sign in or appear in Launchpad applications.

### Configure later

Settings -> Users

## Applications

### What this step does

Reviews readiness for built-in applications such as Staff Status, Finance, and SnipeOps.

### Why it matters

Some applications require additional settings or integrations before they are fully useful.

### If skipped

Applications may remain hidden, incomplete, or unavailable until their required settings are configured.

### Configure later

Settings -> Staff Status, Settings -> Finance, Settings -> Integrations

## Recommended skip confirmation modal content

Each skippable step should show a confirmation modal before skipping.

Example for Email Integration:

> Skip Email Setup?
>
> If you skip this step, Launchpad cannot send account setup links, password reset emails, Finance renewal reminders, or other system notifications.
>
> You can configure this later in Settings -> Integrations -> Email.

Buttons:

- Go Back
- Skip Email Setup

## Suggested setup state keys

These values can be stored in Launchpad settings:

```text
setup.completed
setup.completed_at
setup.completed_by_user_id
setup.current_step
setup.local_admin_completed
setup.organization_completed
setup.organization_skipped
setup.email_completed
setup.email_skipped
setup.authentication_completed
setup.authentication_skipped
setup.users_completed
setup.users_skipped
setup.apps_completed
setup.apps_skipped
```
