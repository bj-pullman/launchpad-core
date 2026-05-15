# FAQ

## Is the Setup Wizard required?

The local admin step is required. Other steps can be skipped, but skipped steps may limit features until configured later.

## Why can't local admin setup be skipped?

Launchpad needs at least one administrative account that is not dependent on external sign-in providers. This account is used for initial setup and recovery.

## Should passwords be emailed to local users?

No. Launchpad should send a password setup link instead of sending plain temporary passwords.

## What happens if Email Integration is skipped?

Launchpad will still work, but it cannot send account setup links, password reset links, Finance renewal reminders, or other system emails.

## What is the Public Base URL used for?

It is used to generate external links such as kiosk URLs, board URLs, and password setup links.

## What is the difference between Local and SSO-only users?

Local users authenticate with a Launchpad password. SSO-only users authenticate through an external provider and do not have a local password.

## Should I use groups or direct permissions?

Use groups for standard access. Use direct permissions only for exceptions.

## Why require users to exist before SSO login?

This gives administrators explicit control over who can access Launchpad even if they exist in the external identity provider.

## Can Staff Status kiosk update multiple users?

Yes. The kiosk can select one or more staff members and apply selected locations to all of them.

## Can I reorder Staff Status locations?

Yes. Locations can be reordered with drag and drop by administrators with department operation access.
