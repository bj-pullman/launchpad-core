# Authentication and Sign-In

Launchpad authentication controls how users sign in and which users are allowed access.

## Supported sign-in concepts

Launchpad may support:

- Local accounts
- Google OIDC
- Microsoft OIDC
- SAML
- Break-glass local administrator access

## Local accounts

Local accounts are stored in Launchpad and authenticate with Launchpad-managed credentials.

Local accounts are useful for:

- Break-glass access
- Service administrators
- Environments without SSO
- Initial setup

## SSO-only accounts

SSO-only accounts exist in Launchpad but do not have a local password. They authenticate through an external identity provider.

## Require existing local user for SSO

Recommended behavior is to require a user record to already exist in Launchpad before SSO login is permitted. This gives administrators control over who can access Launchpad even if they exist in the external identity provider.

## Access denied messaging

Access denied messages should remain generic and should not disclose the exact rule that failed.

Recommended message:

```text
Your account is not permitted to sign in.
```

## Break-glass accounts

Maintain at least one local administrator account that is not dependent on SSO. Store credentials securely according to district policy.
