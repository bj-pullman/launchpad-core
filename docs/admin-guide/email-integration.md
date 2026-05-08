# Email Integration

Launchpad uses the configured SMTP integration to send system email.

## What email enables

Email may be used for:

- Local account setup links
- Password reset links
- User import invite emails
- Finance renewal reminders
- Future alerts and notifications

## Required settings

Typical SMTP settings include:

- SMTP host
- SMTP port
- Username
- Password or relay credential
- TLS/SSL setting
- From address
- From display name

## Test email

After configuring SMTP, send a test email from the Email settings page. Do not rely on the settings being valid until a test message succeeds.

## If email is not configured

Launchpad should continue functioning without email, but email-based workflows will be unavailable.

For example:

- User import can still create accounts.
- Local users will not receive password setup links.
- Finance renewal reminders will not send.

## User import behavior

When importing local users, Launchpad should use email to send password setup links rather than sending plain temporary passwords.

Recommended behavior:

1. Create the local user account.
2. Generate a one-time password setup token.
3. Email the user a setup link.
4. Require the user to set their own password.

Never send plain passwords by email.
