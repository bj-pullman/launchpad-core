# Users and Groups

Users and Groups control who can access Launchpad and what they can do.

## Users page

The Users page allows administrators to:

- Create users
- Edit users
- Activate or disable users
- Delete users
- Filter users
- Perform bulk actions
- Assign groups and direct permissions

## Account types

### Local account

A local account has a Launchpad password and can sign in through local authentication.

### SSO-only account

An SSO-only account does not have a local password and must sign in through a configured external provider.

## Required import fields

Recommended required CSV fields:

```csv
email,username,first_name,last_name,display_name,account_type,department
```

## Optional import fields

Optional CSV fields may include:

```csv
job_title,office_location,company_name,employee_id,preferred_language,business_phone,mobile_phone,manager_email,manager_display_name,groups
```

## User import recommendations

For local accounts, do not email temporary passwords. Instead, send a password setup link using the Email Integration.

For SSO-only accounts, no password setup link is required.

## Groups

Groups are reusable permission bundles. Prefer groups for standard access patterns and direct permissions only for exceptions.

## Direct permissions

Direct permissions should be used sparingly. They are useful for one-off access needs but can become difficult to audit if overused.

## Bulk actions

Users can be bulk activated, disabled, or deleted. Bulk edit may later support assigning groups, removing groups, and updating shared profile fields.
