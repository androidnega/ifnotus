"""Pluggable off-site backup storage (DR). Local disk alone is not disaster recovery."""

from __future__ import annotations

import hashlib
import hmac
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class BackupPutResult:
    ok: bool
    provider: str
    key: str
    skipped: bool = False
    error: str | None = None
    bytes: int | None = None


class BackupProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    def put(self, local_path: Path, key: str) -> BackupPutResult: ...

    def fetch(self, key: str, dest: Path) -> BackupPutResult: ...

    def delete(self, key: str) -> BackupPutResult: ...


class NullOffsiteProvider:
    """Configured offsite absent — backups remain same-VPS only (not DR)."""

    name = "none"

    def configured(self) -> bool:
        return False

    def put(self, local_path: Path, key: str) -> BackupPutResult:
        return BackupPutResult(
            ok=False,
            provider=self.name,
            key=key,
            skipped=True,
            error="BACKUP_OFFSITE_PROVIDER not configured — archive stays on this VPS only.",
        )

    def fetch(self, key: str, dest: Path) -> BackupPutResult:
        return BackupPutResult(ok=False, provider=self.name, key=key, skipped=True, error="no_offsite")

    def delete(self, key: str) -> BackupPutResult:
        return BackupPutResult(ok=True, provider=self.name, key=key, skipped=True)


class CommandOffsiteProvider:
    """Shell command offsite (rsync, rclone, aws s3 cp, scp, …).

    Put placeholders: {path} local file, {key} object key, {dir} parent dir, {basename}.
    Fetch/delete use BACKUP_OFFSITE_FETCH_CMD / BACKUP_OFFSITE_DELETE_CMD with the same
    placeholders ({path} = destination for fetch).
    """

    name = "command"

    def __init__(
        self,
        cmd_template: str,
        *,
        fetch_cmd: str = "",
        delete_cmd: str = "",
    ) -> None:
        self._cmd = (cmd_template or "").strip()
        self._fetch = (fetch_cmd or "").strip()
        self._delete = (delete_cmd or "").strip()

    def configured(self) -> bool:
        return bool(self._cmd)

    def put(self, local_path: Path, key: str) -> BackupPutResult:
        if not self._cmd:
            return BackupPutResult(ok=False, provider=self.name, key=key, skipped=True, error="empty_cmd")
        cmd = self._render(self._cmd, path=local_path, key=key)
        return self._run(cmd, key, local_path.stat().st_size if local_path.exists() else None)

    def fetch(self, key: str, dest: Path) -> BackupPutResult:
        if not self._fetch:
            # Best-effort for flat cp mirrors: copy basename beside a known put target is not
            # recoverable without fetch_cmd — fail clearly (PHASE 38K).
            return BackupPutResult(
                ok=False,
                provider=self.name,
                key=key,
                skipped=True,
                error="BACKUP_OFFSITE_FETCH_CMD not set — cannot restore from offsite command mirror",
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._render(self._fetch, path=dest, key=key)
        return self._run(cmd, key, None)

    def delete(self, key: str) -> BackupPutResult:
        if not self._delete:
            return BackupPutResult(ok=True, provider=self.name, key=key, skipped=True)
        cmd = self._render(self._delete, path=Path("/dev/null"), key=key)
        return self._run(cmd, key, None)

    @staticmethod
    def _render(template: str, *, path: Path, key: str) -> str:
        basename = Path(key).name
        return (
            template.replace("{path}", str(path))
            .replace("{key}", key)
            .replace("{dir}", str(path.parent))
            .replace("{basename}", basename)
        )

    def _run(self, cmd: str, key: str, size: int | None) -> BackupPutResult:
        try:
            proc = subprocess.run(
                ["bash", "-lc", cmd],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("backup_offsite_cmd_failed", error=str(exc))
            return BackupPutResult(ok=False, provider=self.name, key=key, error=str(exc))
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-500:]
            logger.warning("backup_offsite_cmd_failed", error=err, cmd=shlex.quote(cmd[:160]))
            return BackupPutResult(ok=False, provider=self.name, key=key, error=err or "cmd_failed")
        logger.info("backup_offsite_cmd_ok", key=key)
        return BackupPutResult(ok=True, provider=self.name, key=key, bytes=size)


class S3CompatibleBackupProvider:
    """S3-compatible object storage (AWS, R2, B2, Contabo Object Storage, MinIO)."""

    name = "s3"

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "auto",
        prefix: str = "ifnotus/",
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region or "auto"
        self._prefix = prefix.lstrip("/")

    def configured(self) -> bool:
        return bool(self._endpoint and self._bucket and self._access_key and self._secret_key)

    def put(self, local_path: Path, key: str) -> BackupPutResult:
        object_key = self._full_key(key)
        body = local_path.read_bytes()
        try:
            self._request("PUT", object_key, body=body, content_type="application/gzip")
        except Exception as exc:  # noqa: BLE001
            logger.warning("backup_s3_put_failed", error=str(exc), key=object_key)
            return BackupPutResult(ok=False, provider=self.name, key=object_key, error=str(exc))
        return BackupPutResult(ok=True, provider=self.name, key=object_key, bytes=len(body))

    def fetch(self, key: str, dest: Path) -> BackupPutResult:
        object_key = self._full_key(key) if not key.startswith(self._prefix) else key
        try:
            data = self._request("GET", object_key)
        except Exception as exc:  # noqa: BLE001
            return BackupPutResult(ok=False, provider=self.name, key=object_key, error=str(exc))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return BackupPutResult(ok=True, provider=self.name, key=object_key, bytes=len(data))

    def delete(self, key: str) -> BackupPutResult:
        object_key = self._full_key(key) if not key.startswith(self._prefix) else key
        try:
            self._request("DELETE", object_key)
        except Exception as exc:  # noqa: BLE001
            return BackupPutResult(ok=False, provider=self.name, key=object_key, error=str(exc))
        return BackupPutResult(ok=True, provider=self.name, key=object_key)

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        if self._prefix and not key.startswith(self._prefix):
            return f"{self._prefix}{key}"
        return key

    def _request(self, method: str, object_key: str, *, body: bytes = b"", content_type: str = "") -> bytes:
        # Path-style: https://endpoint/bucket/key
        path = f"/{self._bucket}/{quote(object_key, safe='/')}"
        url = f"{self._endpoint}{path}"
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        host = self._endpoint.split("://", 1)[-1]
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type and method == "PUT":
            headers["content-type"] = content_type
        canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
        signed_headers = ";".join(sorted(headers))
        canonical_request = "\n".join(
            [
                method,
                path,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self._region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                algorithm,
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signing_key = self._signing_key(date_stamp)
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"{algorithm} Credential={self._access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        with httpx.Client(timeout=120.0) as client:
            resp = client.request(method, url, content=body if body else None, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"s3_{method}_{resp.status_code}: {resp.text[:300]}")
            return resp.content

    def _signing_key(self, date_stamp: str) -> bytes:
        def _sign(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode(), hashlib.sha256).digest()

        k_date = _sign(("AWS4" + self._secret_key).encode(), date_stamp)
        k_region = _sign(k_date, self._region)
        k_service = _sign(k_region, "s3")
        return _sign(k_service, "aws4_request")


class ResticBackupProvider:
    """Encrypted offsite backup provider using Restic (deduplicated & authenticated).

    Supports remote object storage (S3, B2, Azure, GCS, SFTP, REST server).
    """

    name = "restic"

    def __init__(
        self,
        repository: str,
        password: str,
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        self._repo = (repository or "").strip()
        self._password = (password or "").strip()
        self._extra_env = env or {}

    def configured(self) -> bool:
        return bool(self._repo and self._password)

    def _build_env(self) -> dict[str, str]:
        import os
        env = os.environ.copy()
        env["RESTIC_REPOSITORY"] = self._repo
        env["RESTIC_PASSWORD"] = self._password
        env.update(self._extra_env)
        return env

    def put(self, local_path: Path, key: str) -> BackupPutResult:
        if not self.configured():
            return BackupPutResult(
                ok=False, provider=self.name, key=key, skipped=True, error="restic_not_configured"
            )
        try:
            cmd = ["restic", "backup", "--tag", key, str(local_path)]
            res = subprocess.run(cmd, env=self._build_env(), capture_output=True, text=True, check=False)
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "").strip()
                logger.warning("restic_backup_failed", error=err, key=key)
                return BackupPutResult(ok=False, provider=self.name, key=key, error=err[:300])
            size = local_path.stat().st_size if local_path.exists() else None
            return BackupPutResult(ok=True, provider=self.name, key=key, bytes=size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("restic_backup_exception", error=str(exc), key=key)
            return BackupPutResult(ok=False, provider=self.name, key=key, error=str(exc))

    def fetch(self, key: str, dest: Path) -> BackupPutResult:
        if not self.configured():
            return BackupPutResult(
                ok=False, provider=self.name, key=key, skipped=True, error="restic_not_configured"
            )
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["restic", "restore", "latest", "--tag", key, "--target", str(dest.parent)]
            res = subprocess.run(cmd, env=self._build_env(), capture_output=True, text=True, check=False)
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "").strip()
                return BackupPutResult(ok=False, provider=self.name, key=key, error=err[:300])
            return BackupPutResult(ok=True, provider=self.name, key=key)
        except Exception as exc:  # noqa: BLE001
            return BackupPutResult(ok=False, provider=self.name, key=key, error=str(exc))

    def delete(self, key: str) -> BackupPutResult:
        if not self.configured():
            return BackupPutResult(ok=True, provider=self.name, key=key, skipped=True)
        try:
            cmd = ["restic", "forget", "--tag", key, "--prune"]
            subprocess.run(cmd, env=self._build_env(), capture_output=True, text=True, check=False)
            return BackupPutResult(ok=True, provider=self.name, key=key)
        except Exception as exc:  # noqa: BLE001
            return BackupPutResult(ok=False, provider=self.name, key=key, error=str(exc))


def resolve_backup_provider(settings: Settings) -> BackupProvider:
    kind = (getattr(settings, "backup_offsite_provider", None) or "none").strip().lower()
    fetch_cmd = getattr(settings, "backup_offsite_fetch_cmd", "") or ""
    delete_cmd = getattr(settings, "backup_offsite_delete_cmd", "") or ""
    if kind in {"", "none", "local", "off"}:
        # Fall back to legacy platform cmd for environment archives when set
        legacy = (getattr(settings, "platform_backup_offsite_cmd", None) or "").strip()
        env_cmd = (getattr(settings, "backup_offsite_cmd", None) or "").strip()
        cmd = env_cmd or legacy
        if cmd:
            return CommandOffsiteProvider(cmd, fetch_cmd=fetch_cmd, delete_cmd=delete_cmd)
        return NullOffsiteProvider()
    if kind == "command":
        return CommandOffsiteProvider(
            getattr(settings, "backup_offsite_cmd", "") or "",
            fetch_cmd=fetch_cmd,
            delete_cmd=delete_cmd,
        )
    if kind == "s3":
        return S3CompatibleBackupProvider(
            endpoint=getattr(settings, "backup_s3_endpoint", "") or "",
            bucket=getattr(settings, "backup_s3_bucket", "") or "",
            access_key=getattr(settings, "backup_s3_access_key", "") or "",
            secret_key=getattr(settings, "backup_s3_secret_key", "") or "",
            region=getattr(settings, "backup_s3_region", "auto") or "auto",
            prefix=getattr(settings, "backup_s3_prefix", "ifnotus/") or "ifnotus/",
        )
    if kind == "restic":
        s3_env = {}
        if getattr(settings, "backup_s3_access_key", None):
            s3_env["AWS_ACCESS_KEY_ID"] = getattr(settings, "backup_s3_access_key")
        if getattr(settings, "backup_s3_secret_key", None):
            s3_env["AWS_SECRET_ACCESS_KEY"] = getattr(settings, "backup_s3_secret_key")
        return ResticBackupProvider(
            repository=getattr(settings, "backup_restic_repository", "") or "",
            password=getattr(settings, "backup_restic_password", "") or "",
            env=s3_env,
        )
    logger.warning("backup_provider_unknown", kind=kind)
    return NullOffsiteProvider()


def storage_key_for(customer_id: str, environment_id: str, filename: str) -> str:
    base = Path(filename).name
    return f"customers/{customer_id}/{environment_id}/{base}"
