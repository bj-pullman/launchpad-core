# System Maintenance

This page covers operational maintenance for Launchpad.

## Deployment model

Launchpad may be hosted as a Python/Flask application behind Waitress and IIS, with IIS acting as the reverse proxy.

Typical flow:

```text
Client Browser -> DNS -> IIS HTTPS -> 127.0.0.1:5000 -> Waitress -> Flask
```

## Git workflow

Recommended branch flow:

- `dev` for active development and testing
- `main` for stable production code

Common commands:

```bash
git status
git add .
git commit -m "Describe change"
git push origin dev
```

## Backups

Before migrations or major updates, back up:

- SQLite databases in `instance/`
- `.env` file
- uploaded files and attachments
- service configuration

## Updating production

Before pulling new code into production:

1. Confirm current branch.
2. Confirm no uncommitted local changes.
3. Back up databases.
4. Pull the desired branch.
5. Install requirements if changed.
6. Restart the service.
7. Validate login and critical apps.

## Troubleshooting deployment

If generated URLs point to localhost or 127.0.0.1, verify:

- Public base URL in General Settings
- ProxyFix configuration
- IIS reverse proxy headers
- Hostname and DNS
