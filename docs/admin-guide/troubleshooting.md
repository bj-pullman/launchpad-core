# Troubleshooting

## Generated URLs point to localhost

Check Settings -> General -> Public Base URL.

Expected value:

```text
https://launchpad.sheridanschools.org
```

Also verify reverse proxy headers and ProxyFix configuration.

## User cannot sign in through SSO

Check:

- User exists in Launchpad.
- User is active.
- Hosted domain or tenant setting is correct.
- Required groups or domains are configured correctly.
- Access denied message is intentionally generic.

## Local user shows as SSO-only

Local account type should be determined by whether the local auth account has a password hash. If a local user appears as SSO-only, verify the local auth query includes password/account type detection.

## Staff Status kiosk or board URLs do not work

Check:

- Department has generated kiosk/board token.
- Public base URL is configured.
- Department is enabled.
- Token has not been regenerated without updating the saved link.

## Staff Status location order does not save

Check:

- Reorder route exists.
- User has department operate permission.
- JavaScript loaded successfully.
- SortableJS loaded successfully.

## Email test fails

Check:

- SMTP host and port
- TLS/SSL setting
- Credentials or relay permission
- From address policy
- Firewall or network rules
