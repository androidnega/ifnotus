# PHASE 38C — Billing suspend / restore / terminate lifecycle

## Fix

`SubscriptionBillingService` no longer flips environment flags in isolation. Suspend,
restore, and terminate paths delegate to `EnvironmentLifecycleService`, which disables
nginx, FTP/SFTP, Unix identity, mail, and containers according to existing lifecycle
design.

Billing still sends subscription-level customer notifications (grace ended, hosting
terminated). Per-environment lifecycle notifications are suppressed on billing paths
(`notify_customer=False`).

## Live check

After a subscription enters grace and is suspended by the hourly billing tick:

- Environment nginx vhost disabled (site unreachable or suspension behavior)
- Tenant Unix user locked (`usermod -L` / equivalent)
- FTP/SFTP disabled for the environment
- Container stopped if present

After manual renewal from suspended/grace:

- Lifecycle restore re-enables nginx, FTP, SFTP, and Unix unlock

After terminate-after-non-renewal:

- Full lifecycle terminate runs (not DB flags only)
