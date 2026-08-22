# PHASE 28 — Email product

Complete customer-facing email management in the Hosting Panel **Email** tab. Staff `/admin/mail` remains the operator console; customers get parity for day-to-day mailbox work.

## Package controls

| Field | Meaning |
|-------|---------|
| `mail_enabled` | Gates the Email tab and all mail APIs |
| `mailboxes` | Max mailboxes per site |
| `mail_storage_mb` | Total quota budget across mailboxes (sum of `quota_mb`) |

Example (Club Connect): `mailboxes=5`, `mail_storage_mb=2048`.

Low-cost plans keep tight limits — no unlimited mail on Starter/Personal.

## Customer API

| Method | Path | Action |
|--------|------|--------|
| GET | `.../mail` | Domain, mailboxes, aliases, webmail + IMAP/SMTP hints |
| POST | `.../mail/mailboxes` | Create mailbox |
| PATCH | `.../mail/mailboxes/{id}` | Quota, suspend, display name |
| POST | `.../mail/mailboxes/{id}/reset-password` | Rotate password |
| DELETE | `.../mail/mailboxes/{id}` | Delete mailbox + vmail tree |
| POST | `.../mail/aliases` | Create forwarder |
| PATCH | `.../mail/aliases/{id}` | Update forwarder |
| DELETE | `.../mail/aliases/{id}` | Remove forwarder |

## Abuse / safety

- Reserved local parts (`postmaster`, `abuse`, `admin`, …) blocked on create
- Forwarder count capped at `mailboxes × 3`
- Storage cap enforced when setting quotas
- Suspended mailboxes excluded from Postfix auth maps (existing)
- Environment **suspend** → all mailboxes suspended
- Environment **terminate** → mailboxes/aliases/vmail purged for hosting domain

## Domain changes

When `env.domain` changes, the next mail access rebinds `hosting_domain_id` to the matching `Domain` row. Mailboxes on the previous domain remain until removed manually.

## Hosting Panel

**Email** tab: create/delete mailboxes, reset password, suspend, forwarders, Roundcube link, IMAP/SMTP settings. Hidden when `capabilities.on.mail` is false.
