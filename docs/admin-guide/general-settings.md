# General Settings

General Settings control organization-wide Launchpad behavior.

## Organization name

The organization name appears in the interface and may be used in emails, page titles, or future templates.

## Public base URL

The public base URL is the fully qualified URL users use to reach Launchpad.

Example:

```text
https://launchpad.sheridanschools.org
```

## Why public base URL matters

Launchpad uses this value when generating links for:

- Staff Status kiosk URLs
- Staff Status public board URLs
- Password setup links
- Password reset links
- Future email links

If this value is missing or incorrect, generated links may point to localhost, an internal IP, or the wrong hostname.

## Timezone

Timezone controls how Launchpad displays system times such as last login and Staff Status board timestamps.

Recommended value for Sheridan School District:

```text
America/Chicago
```

## Date and time format

Administrators can configure how dates and times appear throughout Launchpad.

Recommended default:

```text
MM/DD/YYYY
12-hour time
```
