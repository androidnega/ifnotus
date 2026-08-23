# PHASE 38D — Deploy and prove real SFTP

## Fix

1. Install `/etc/ssh/sshd_config.d/ifnotus-sftp.conf` only after `sshd -t` passes.
2. Create group `ifnotus-sftp`.
3. Match `Group ifnotus-sftp,!ifnotus-ssh` with `ChrootDirectory %h` and
   `ForceCommand internal-sftp -d /public` (no duplicate `Subsystem sftp`).
4. Tenant Unix home = environment chroot root; writable site files in `public/`.
5. New provisioning creates `.../<hostname>/public` as document root.
6. `ensure_account` migrates flat docroots into `public/` and syncs nginx `root`.

## Install on host

```bash
sudo bash scripts/install-ifnotus-sftp-sshd.sh
```

## Manual live check

Disposable env after panel “Create SFTP login”:

```text
sftp USER@serverlabsttu.space
pwd          # expect /public
ls
put /tmp/x.txt
get x.txt
cd /etc      # must fail
```

Interactive SSH for SFTP-only users must fail (nologin + ForceCommand).
