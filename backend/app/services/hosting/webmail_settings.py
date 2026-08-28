"""Persist webmail (Roundcube) panel settings and apply branding on disk."""

from __future__ import annotations

import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.schemas.operations import OperationResult
from app.schemas.webmail_settings import WebmailSettingsResponse, WebmailSettingsUpdateRequest
from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

logger = get_logger(__name__)

# Throttle nginx inject during inventory polling.
_last_ensure_mono: float = 0.0
_ENSURE_TTL_SECONDS = 120.0


def whatsapp_chat_url(phone: str) -> str:
    """Build https://wa.me/<digits> from a phone number (with or without +)."""
    digits = re.sub(r"\D+", "", phone or "")
    if not digits:
        raise AppException("WhatsApp number is required.", code="webmail_whatsapp_empty")
    return f"https://wa.me/{digits}"


class WebmailSettingsStore:
    """File-backed webmail settings + live Roundcube config/branding sync."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = Path(settings.webmail_settings_path).resolve()
        self._rc_config = Path(settings.roundcube_config_path)
        self._rc_public = Path(settings.roundcube_public_html)
        self._brand_src = Path(settings.webmail_brand_assets_dir).resolve()
        self._provisioner = DomainNginxProvisioner(settings)

    def _read_raw(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            import json

            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_raw(self, data: dict) -> None:
        import json

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def get_whatsapp(self) -> str:
        raw = self._read_raw()
        value = str(raw.get("support_whatsapp") or self._settings.webmail_support_whatsapp or "").strip()
        return value or "+233541069241"

    def get_product_name(self) -> str:
        raw = self._read_raw()
        return str(raw.get("product_name") or "IFNOTUS Webmail").strip() or "IFNOTUS Webmail"

    def status(self) -> WebmailSettingsResponse:
        raw = self._read_raw()
        phone = self.get_whatsapp()
        return WebmailSettingsResponse(
            support_whatsapp=phone,
            support_url=whatsapp_chat_url(phone),
            product_name=self.get_product_name(),
            auto_detect_domains=bool(raw.get("auto_detect_domains", True)),
            updated_at=raw.get("updated_at"),
        )

    def update(self, body: WebmailSettingsUpdateRequest) -> WebmailSettingsResponse:
        raw = self._read_raw()
        if body.support_whatsapp is not None:
            phone = body.support_whatsapp.strip()
            if not phone:
                raise AppException("WhatsApp number cannot be empty.", code="webmail_whatsapp_empty")
            # Validate by building URL
            whatsapp_chat_url(phone)
            raw["support_whatsapp"] = phone
        if body.product_name is not None:
            name = body.product_name.strip()
            if name:
                raw["product_name"] = name
        if body.auto_detect_domains is not None:
            raw["auto_detect_domains"] = bool(body.auto_detect_domains)
        raw["updated_at"] = datetime.now(UTC).isoformat()
        self._write_raw(raw)
        self.apply_roundcube_config()
        self.apply_branding_assets()
        return self.status()

    def apply_roundcube_config(self) -> None:
        """Rewrite support_url / product_name / logos in Roundcube config.inc.php."""
        phone = self.get_whatsapp()
        support = whatsapp_chat_url(phone)
        product = self.get_product_name()
        paths: list[Path] = []
        for candidate in (
            self._rc_config,
            Path("/etc/roundcube/config.inc.php"),
            Path("/var/lib/roundcube/config/config.inc.php"),
        ):
            if candidate.exists() and candidate not in paths:
                paths.append(candidate)
        if not paths:
            logger.warning("roundcube_config_missing")
            return

        logo_block = (
            "$config['skin_logo'] = [\n"
            "  'elastic:*' => 'images/ifnotus-webmail-logo.png',\n"
            "  '[favicon]' => 'images/ifnotus-webmail-favicon.ico',\n"
            "  'elastic:[favicon]' => 'images/ifnotus-webmail-favicon.ico',\n"
            "];"
        )

        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("roundcube_config_read_failed", path=str(path), error=str(exc))
                continue

            text = self._set_php_string(text, "support_url", support)
            text = self._set_php_string(text, "product_name", product)
            if "trusted_host_patterns" not in text:
                text = text.rstrip() + "\n$config['trusted_host_patterns'] = ['.+'];\n"
            text = self._apply_host_isolation(text)
            if re.search(r"\$config\['skin_logo'\]\s*=", text):
                text = re.sub(
                    r"\$config\['skin_logo'\]\s*=\s*.*?;",
                    logo_block,
                    text,
                    count=1,
                    flags=re.DOTALL,
                )
            else:
                text = text.rstrip() + "\n" + logo_block + "\n"

            try:
                path.write_text(text, encoding="utf-8")
                logger.info("roundcube_config_updated", path=str(path), support_url=support)
            except OSError as exc:
                logger.warning("roundcube_config_write_failed", path=str(path), error=str(exc))

    @staticmethod
    def _apply_host_isolation(text: str) -> str:
        """Scope the webmail session cookie to the requested host.

        One Roundcube instance serves every hosted domain. Without a per-host
        cookie name every domain shares `roundcube_sessid`, so an open session
        on one domain can surface while browsing another domain's /mail.
        """
        begin = "// >>> IFNOTUS host isolation (managed) >>>"
        end = "// <<< IFNOTUS host isolation (managed) <<<"
        block = "\n".join(
            [
                begin,
                "$ifnotus_webmail_host = strtolower((string) ($_SERVER['HTTP_HOST'] ?? ''));",
                "$ifnotus_webmail_host = preg_replace('/:\\d+$/', '', $ifnotus_webmail_host);",
                "$ifnotus_webmail_host = preg_replace('/[^a-z0-9.\\-]/', '', $ifnotus_webmail_host);",
                "if ($ifnotus_webmail_host === '') { $ifnotus_webmail_host = 'default'; }",
                "$config['session_name'] = 'ifnotus_webmail_' . substr(sha1($ifnotus_webmail_host), 0, 16);",
                "$config['session_path'] = '/';",
                "$config['session_domain'] = '';",
                "$config['session_samesite'] = 'Lax';",
                end,
            ]
        )
        pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
        if pattern.search(text):
            return pattern.sub(lambda _match: block, text, count=1)
        return text.rstrip() + "\n\n" + block + "\n"

    @staticmethod
    def _set_php_string(text: str, key: str, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        pattern = rf"(\$config\['{re.escape(key)}'\]\s*=\s*)'[^']*';"
        replacement = rf"\1'{escaped}';"
        if re.search(pattern, text):
            return re.sub(pattern, replacement, text, count=1)
        return text.rstrip() + f"\n$config['{key}'] = '{escaped}';\n"

    def apply_branding_assets(self) -> None:
        """Copy transparent logo/favicon into Roundcube public images + elastic skin."""
        if not self._rc_public.is_dir():
            return
        images = self._rc_public / "images"
        elastic = self._rc_public / "skins" / "elastic" / "images"
        images.mkdir(parents=True, exist_ok=True)

        mapping = {
            "logo.png": [
                images / "ifnotus-webmail-logo.png",
                elastic / "logo.png",
            ],
            "logo-192.png": [images / "ifnotus-webmail-logo-192.png"],
            "favicon.ico": [
                images / "ifnotus-webmail-favicon.ico",
                elastic / "favicon.ico",
            ],
            "favicon-32.png": [images / "ifnotus-webmail-favicon-32.png"],
        }

        # Prefer packaged assets next to deploy; fall back to repo assets path.
        sources: list[Path] = []
        if self._brand_src.is_dir():
            sources.append(self._brand_src)
        for extra in (
            Path("/srv/apps/ifnotus/assets/webmail"),
            Path(__file__).resolve().parents[3] / "assets" / "webmail",
        ):
            if extra.is_dir() and extra not in sources:
                sources.append(extra)

        for name, destinations in mapping.items():
            src_file: Path | None = None
            for folder in sources:
                candidate = folder / name
                if candidate.is_file():
                    src_file = candidate
                    break
            if src_file is None:
                continue
            for dest in destinations:
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dest)
                except OSError as exc:
                    logger.warning("webmail_brand_copy_failed", dest=str(dest), error=str(exc))

        # Also replace default SVG logo used by elastic login template when png configured.
        svg_logo = elastic / "logo.svg"
        png_logo = elastic / "logo.png"
        if png_logo.is_file() and svg_logo.is_file():
            # Keep a backup once; elastic may still reference svg via template default.
            bak = elastic / "logo.svg.bak-ifnotus"
            try:
                if not bak.exists():
                    shutil.copy2(svg_logo, bak)
            except OSError:
                pass

    async def ensure_webmail_for_domains(self, *, force: bool = False) -> OperationResult:
        """Inject /mail on nginx sites for newly discovered domains (throttled)."""
        global _last_ensure_mono
        raw = self._read_raw()
        if not bool(raw.get("auto_detect_domains", True)) and not force:
            return OperationResult(success=True, message="Webmail auto-detect disabled.", details={})
        now = time.monotonic()
        if not force and (now - _last_ensure_mono) < _ENSURE_TTL_SECONDS:
            return OperationResult(
                success=True,
                message="Webmail domain sync skipped (recently ran).",
                details={"throttled": True},
            )
        _last_ensure_mono = now
        # Ensure branding + support URL stay applied
        self.apply_branding_assets()
        self.apply_roundcube_config()
        result = await self._provisioner.ensure_webmail_on_all_sites()
        logger.info(
            "webmail_domain_sync",
            success=result.success,
            message=result.message,
            details=result.details,
        )
        return result
