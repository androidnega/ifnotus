# PHASE 38B — Customer cron never runs as root / worker

## Fix

`EnvironmentCronService` hard-fails when:

- `unix_username` is missing
- the Unix user is not present on the host (`pwd.getpwnam`)
- neither `runuser` nor `sudo -n -u` is available
- environment status is not `active`

There is **no** bare `bash -lc` fallback as the worker identity.

## Manual live check

On a disposable ACTIVE env with a real `ifn_*` (or entitled unix) user:

```text
whoami > cron-user.txt
```

Expect file contents = tenant username, never `root`.

## Note

`ifnotus-worker` may still run as root for provisioning. That is separate from
customer cron argv construction (fail-closed here).
