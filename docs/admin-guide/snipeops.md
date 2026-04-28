# SnipeOps

SnipeOps extends Snipe-IT workflows inside Launchpad.

## Planned and supported concepts

SnipeOps may include:

- Import by Scan
- Device audit workflows
- Snipe-IT API integration
- Intune sync
- Mosyle sync
- Staff rostering into Snipe-IT
- Reporting

## Snipe-IT integration

SnipeOps requires Snipe-IT base URL and API token configuration.

## Import by Scan

Import by Scan supports asset intake workflows. Future improvements may include:

- Configurable recent-record load count
- Print Label directly from Import by Scan

## Device Audit

Device Audit should support mobile-friendly auditing using serial number as the primary key and asset tag as secondary identifier.

Audit updates may include:

- Location
- Assigned user or assigned asset
- Room number
- Condition notes
- Issue notes

## Dual logging

Audit actions should write to both SnipeOps audit history and Snipe-IT audit logs when possible.
