# Finance

The Finance application tracks financial records, vendors, categories, renewals, attachments, and notification workflows.

## Core concepts

- Records store finance items such as purchases, renewals, and subscriptions.
- Vendors may be created manually or during imports.
- Categories help organize spending.
- Attachments store supporting documents.
- Renewal notifications depend on Email Integration.

## Budget access

Budget features should be tightly guarded with a separate permission from normal Finance access.

Recommended model:

- Finance app access requires role and department scope.
- Budget access is separate and must be assigned explicitly.

## Renewal notifications

Finance renewal emails require:

- Email Integration configured
- Notification sender configured
- Recipient behavior configured
- Template settings configured

## Import behavior

Finance imports should report created vendors, skipped records, and errors. Upload routes should handle missing attachments gracefully.
