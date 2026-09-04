"""Customer Git Version Control — cPanel-style clone / create / pull under the site home."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppException, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.platform import CustomerEnvironment
from app.services.applications.git_util import run_git
from app.services.monitoring.subprocess_util import run_command
from app.services.platform.application_runtime import site_home_from_document_root
from app.services.platform.fs_ownership import fix_web_ownership

logger = get_logger(__name__)

_FORBIDDEN_PATH = re.compile(r"""[\\*|\"'<>&@`$(){}\[\]?;:=%#]""")
_CLONE_URL_OK = re.compile(
    r"^(https?://|ssh://|git://|file://|git@)",
    re.IGNORECASE,
)


def _slug_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip("-._")
    return cleaned[:80] or "repository"


class EnvironmentGitService:
    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._session = session

    def _customers_root(self) -> Path:
        return Path(self._settings.customer_environments_root).resolve()

    def _site_home(self, env: CustomerEnvironment) -> Path:
        if not env.document_root:
            raise ValidationError("This site has no folder yet.")
        home = site_home_from_document_root(Path(env.document_root).resolve())
        base = self._customers_root()
        if base.exists() and not str(home).startswith(str(base)):
            raise AppException("Site folder is outside the customer area.")
        return home

    def _account_home(self, env: CustomerEnvironment) -> Path:
        """cPanel-style account home: customers/<storage_slug>/ (may hold many domains)."""
        base = self._customers_root()
        site = self._site_home(env)
        try:
            rel = site.resolve().relative_to(base)
        except ValueError:
            return site
        if not rel.parts:
            return site
        return (base / rel.parts[0]).resolve()

    def _root(self, env: CustomerEnvironment) -> Path:
        """Document root — kept for older single-repo clone/pull."""
        if not env.document_root:
            raise ValidationError("This site has no folder yet.")
        root = Path(env.document_root).resolve()
        base = self._customers_root()
        if base.exists() and not str(root).startswith(str(base)):
            raise AppException("Site folder is outside the customer area.")
        return root

    def _home_label(self, env: CustomerEnvironment) -> str:
        return (getattr(env, "hosting_name", None) or env.unix_username or "user").strip() or "user"

    def _home_display(self, env: CustomerEnvironment) -> str:
        return f"/home3/{self._home_label(env)}"

    def _display_path(self, env: CustomerEnvironment, real: Path) -> str:
        home = self._account_home(env)
        try:
            rel = real.resolve().relative_to(home)
            rel_s = rel.as_posix()
            return f"{self._home_display(env)}/{rel_s}" if rel_s != "." else self._home_display(env)
        except ValueError:
            return str(real)

    def _registry_path(self, env: CustomerEnvironment) -> Path:
        return self._account_home(env) / ".ifnotus" / "git-repos.json"

    def _load_registry(self, env: CustomerEnvironment) -> list[dict]:
        path = self._registry_path(env)
        legacy = self._site_home(env) / ".ifnotus" / "git-repos.json"
        for candidate in (path, legacy):
            if not candidate.is_file():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = data.get("repositories") if isinstance(data, dict) else data
            return list(rows) if isinstance(rows, list) else []
        return []

    def _save_registry(self, env: CustomerEnvironment, rows: list[dict]) -> None:
        path = self._registry_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"repositories": rows}, indent=2), encoding="utf-8")
        fix_web_ownership(path.parent, user=self._settings.web_run_user)

    async def _plan_cap(self, env: CustomerEnvironment) -> int | None:
        from app.models.platform import HostingPlan, Subscription
        from app.services.platform.plan_matrix import feature_included, features_for, pack_denied_message

        sub = await self._session.get(Subscription, env.subscription_id)
        plan = await self._session.get(HostingPlan, sub.plan_id) if sub else None
        if not feature_included(plan, "git"):
            raise ValidationError(pack_denied_message("Git"))
        cap = features_for(plan).get("repos")
        if cap == 0:
            raise ValidationError(pack_denied_message("Git"))
        return int(cap) if cap not in (None, "unlimited") else None

    def resolve_requested_path(self, env: CustomerEnvironment, requested: str | None) -> tuple[Path, str]:
        home = self._account_home(env)
        label = self._home_label(env)
        raw = (requested or "").strip() or str(home)
        # Allow UI copy like (/home3/user)/try
        if raw.startswith("(") and ")/" in raw:
            raw = raw.replace("(", "", 1).replace(")/", "/", 1)
        if any(ch.isspace() for ch in raw):
            raise ValidationError("The path cannot contain whitespace.")
        if "./" in raw or "../" in raw or raw.endswith("/..") or raw == "..":
            raise ValidationError("The path cannot contain ./ or ../ directory references.")
        if _FORBIDDEN_PATH.search(raw):
            raise ValidationError(
                r'The path cannot contain \ * | " \' < > & @ ` $ { } [ ] ( ) ; ? : = % #'
            )
        cleaned = raw.rstrip("/")
        prefixes = (
            f"/home3/{label}/",
            f"/home3/{label}",
            f"/home/{label}/",
            f"/home/{label}",
        )
        rel = cleaned
        matched = False
        for prefix in prefixes:
            bare = prefix.rstrip("/")
            if cleaned == bare:
                rel = ""
                matched = True
                break
            if cleaned.startswith(bare + "/"):
                rel = cleaned[len(bare) + 1 :]
                matched = True
                break
        if not matched:
            # Soft-accept mangled display prefixes like /home3t/try → try
            parts = Path(cleaned).parts if cleaned.startswith("/") else ()
            if len(parts) >= 2 and str(parts[1]).startswith("home"):
                rel = Path(*parts[2:]).as_posix() if len(parts) > 2 else ""
                matched = True
            elif cleaned.startswith("/"):
                try:
                    candidate = Path(cleaned).resolve()
                    candidate.relative_to(home)
                    rel = str(candidate.relative_to(home))
                    matched = True
                except ValueError as exc:
                    raise ValidationError("Repository path must stay inside your hosting home.") from exc
            else:
                rel = cleaned.lstrip("/")
                matched = True
        rel_path = Path(rel) if rel and rel != "." else Path()
        if ".." in rel_path.parts:
            raise ValidationError("The path cannot contain ./ or ../ directory references.")
        real = (home / rel_path).resolve()
        try:
            real.relative_to(home)
            real.relative_to(self._customers_root())
        except ValueError as exc:
            raise ValidationError("Repository path must stay inside your hosting home.") from exc
        return real, self._display_path(env, real)

    @staticmethod
    def detect_web_root(repo: Path) -> Path:
        """Choose the folder nginx should serve for a Git/app tree."""
        from app.services.hosting.nginx_provisioner import DomainNginxProvisioner

        # Laravel / frameworks with a nested public/
        if (repo / "artisan").is_file() and (repo / "public").is_dir():
            return (repo / "public").resolve()
        if (repo / "public" / "index.php").is_file():
            return (repo / "public").resolve()
        if (repo / "public_html" / "index.php").is_file() or (repo / "public_html" / "index.html").is_file():
            return (repo / "public_html").resolve()
        if (repo / "index.php").is_file() or (repo / "index.html").is_file():
            return repo.resolve()
        return DomainNginxProvisioner.resolve_web_root(repo)

    def _clone_url_for(self, env: CustomerEnvironment, real: Path) -> str | None:
        user = env.unix_username
        if not user:
            return None
        host = (
            getattr(self._settings, "customer_ssh_host", None)
            or getattr(self._settings, "customer_shared_ip", None)
            or "git.ifnotus.space"
        )
        port = int(getattr(self._settings, "customer_ssh_port", None) or 22)
        return f"ssh://{user}@{host}:{port}{real}"

    async def _inspect(self, env: CustomerEnvironment, real: Path, *, name: str | None = None) -> dict:
        display = self._display_path(env, real)
        payload = {
            "id": display,
            "name": name or real.name or "repository",
            "path": str(real),
            "path_display": display,
            "configured": (real / ".git").is_dir(),
            "branch": None,
            "commit": None,
            "commit_full": None,
            "author": None,
            "author_email": None,
            "committed_at": None,
            "message": None,
            "remote": None,
            "dirty": False,
            "clone_url": self._clone_url_for(env, real),
        }
        if not payload["configured"]:
            return payload
        _, branch, _ = await run_git(real, "rev-parse", "--abbrev-ref", "HEAD")
        _, commit, _ = await run_git(real, "rev-parse", "--short", "HEAD")
        _, commit_full, _ = await run_git(real, "rev-parse", "HEAD")
        _, remote, _ = await run_git(real, "config", "--get", "remote.origin.url")
        _, dirty_out, _ = await run_git(real, "status", "--porcelain")
        _, log, _ = await run_git(
            real,
            "log",
            "-1",
            "--format=%an%n%ae%n%cI%n%s",
        )
        author = email = committed = subject = None
        parts = (log or "").split("\n", 3)
        if len(parts) >= 4:
            author, email, committed, subject = (p.strip() or None for p in parts[:4])
        payload.update(
            {
                "branch": (branch or "").strip() or None,
                "commit": (commit or "").strip() or None,
                "commit_full": (commit_full or "").strip() or None,
                "author": author,
                "author_email": email,
                "committed_at": committed,
                "message": subject,
                "remote": (remote or "").strip() or None,
                "dirty": bool((dirty_out or "").strip()),
            }
        )
        return payload

    def _upsert_registry(self, env: CustomerEnvironment, real: Path, name: str) -> None:
        rows = self._load_registry(env)
        key = str(real)
        found = False
        for row in rows:
            if str(row.get("path")) == key:
                row["name"] = name
                found = True
                break
        if not found:
            rows.append({"name": name, "path": key})
        self._save_registry(env, rows)

    async def _discover(self, env: CustomerEnvironment) -> list[dict]:
        home = self._account_home(env)
        site = self._site_home(env)
        rows = self._load_registry(env)
        known = {str(Path(r["path"]).resolve()) for r in rows if r.get("path")}
        # Always include document root when it is a git repo.
        doc = self._root(env)
        if (doc / ".git").is_dir() and str(doc) not in known:
            rows.append({"name": doc.name or env.domain or "website", "path": str(doc)})
            known.add(str(doc))
        # Light scan: account home, site home, docroot, and immediate children.
        scan_roots = [home, site, doc]
        try:
            scan_roots.extend(list(home.iterdir())[:80])
        except OSError:
            pass
        try:
            scan_roots.extend(list(site.iterdir())[:40])
        except OSError:
            pass
        for child in scan_roots:
            try:
                if child.is_dir() and (child / ".git").is_dir() and str(child.resolve()) not in known:
                    rows.append({"name": child.name, "path": str(child.resolve())})
                    known.add(str(child.resolve()))
            except OSError:
                continue
        self._save_registry(env, rows)
        return rows

    async def list_repos(self, env: CustomerEnvironment) -> dict:
        cap = None
        try:
            cap = await self._plan_cap(env)
        except ValidationError as exc:
            return {
                "environment_id": str(env.id),
                "configured": False,
                "repositories": [],
                "home_display": self._home_display(env),
                "repos_limit": 0,
                "message": str(exc),
            }
        rows = await self._discover(env)
        repos = []
        for row in rows:
            real = Path(str(row.get("path") or "")).resolve()
            try:
                real.relative_to(self._account_home(env))
            except ValueError:
                continue
            if not real.exists():
                continue
            repos.append(await self._inspect(env, real, name=str(row.get("name") or real.name)))
        configured = any(r["configured"] for r in repos)
        primary = next((r for r in repos if r["path"] == str(self._root(env))), repos[0] if repos else None)
        return {
            "environment_id": str(env.id),
            "configured": configured,
            "path": str(self._root(env)),
            "home_display": self._home_display(env),
            "repos_limit": cap,
            "repositories": repos,
            "branch": (primary or {}).get("branch"),
            "commit": (primary or {}).get("commit"),
            "remote": (primary or {}).get("remote"),
            "dirty": (primary or {}).get("dirty"),
            "message": "Git is ready." if configured else "Create or clone a repository to get started.",
        }

    async def status(self, env: CustomerEnvironment) -> dict:
        return await self.list_repos(env)

    def _validate_clone_url(self, url: str) -> str:
        url = (url or "").strip()
        if not url or any(ch.isspace() for ch in url):
            raise ValidationError("Enter a valid clone URL.")
        if not _CLONE_URL_OK.match(url):
            raise ValidationError(
                "Clone URLs must begin with http://, https://, ssh://, git://, file://, or git@."
            )
        if url.startswith(("http://", "https://")):
            parsed = urlparse(url)
            if not parsed.netloc:
                raise ValidationError("Enter a valid clone URL.")
        return url

    async def create(
        self,
        env: CustomerEnvironment,
        *,
        name: str,
        repo_path: str | None = None,
        clone: bool = False,
        repo_url: str | None = None,
        branch: str | None = None,
        serve_as_website: bool = False,
    ) -> dict:
        cap = await self._plan_cap(env)
        listing = await self.list_repos(env)
        if cap is not None and len(listing.get("repositories") or []) >= cap:
            raise ValidationError(f"Your plan allows {cap} Git repository(ies). Remove one first.")
        display_name = (name or "").strip()
        if "<" in display_name or ">" in display_name:
            raise ValidationError("The repository name may not include < or >.")
        if not display_name:
            display_name = _slug_name(Path(repo_path or "repository").name)
        real, display = self.resolve_requested_path(env, repo_path)
        if (real / ".git").is_dir():
            raise ConflictError("That path already contains a Git repository.")
        if clone:
            url = self._validate_clone_url(repo_url or "")
            if real.exists() and any(real.iterdir()):
                raise ValidationError("That folder is not empty. Choose an empty path to clone into.")
            real.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone"]
            if branch and str(branch).strip():
                cmd += ["--branch", str(branch).strip()]
            cmd += [url, str(real)]
            code, out, err = await run_command(*cmd, timeout=180)
            if code != 0:
                shutil.rmtree(real, ignore_errors=True)
                raise AppException((err or out or "Git clone failed")[-400:])
        else:
            real.mkdir(parents=True, exist_ok=True)
            code, out, err = await run_git(real, "init", "-b", "main")
            if code != 0:
                # older git without -b
                code, out, err = await run_git(real, "init")
            if code != 0:
                raise AppException((err or out or "Git init failed")[-400:])
        fix_web_ownership(real, user=self._settings.web_run_user)
        if env.unix_username:
            from app.services.platform.fs_ownership import grant_tenant_traverse

            grant_tenant_traverse(
                self._settings.customer_environments_root,
                customer_id=env.customer_id,
                unix_username=env.unix_username,
            )
        self._upsert_registry(env, real, display_name)
        logger.info("env_git_created", environment_id=str(env.id), path=str(real), clone=clone)
        payload = await self.list_repos(env)
        payload["message"] = "Repository cloned." if clone else "Repository created."
        payload["created_path"] = display
        # Auto-serve when asked, or when cloning into a path that already looks like a site.
        should_serve = serve_as_website or (
            clone and bool((real / "index.php").is_file() or (real / "public" / "index.php").is_file())
        )
        if should_serve:
            try:
                served = await self.activate_as_website(env, repo_path=display)
                payload["message"] = (
                    f"{payload['message']} Website now serves {served.get('web_root_display') or display}."
                )
                payload["web_root"] = served.get("web_root")
                payload["web_root_display"] = served.get("web_root_display")
            except Exception as exc:  # noqa: BLE001
                logger.warning("env_git_auto_serve_failed", error=str(exc), path=str(real))
                payload["message"] = f"{payload['message']} (Could not activate website yet: {exc})"
        return payload

    async def activate_as_website(self, env: CustomerEnvironment, *, repo_path: str) -> dict:
        """Point the domain's nginx/PHP document root at a Git (or app) folder."""
        real, display = self.resolve_requested_path(env, repo_path)
        if not real.is_dir():
            raise ValidationError("That repository path does not exist.")
        web_root = self.detect_web_root(real)
        if not web_root.is_dir():
            raise ValidationError("Could not find a folder to serve for this repository.")

        from app.models.hosting import Domain
        from app.services.hosting.nginx_provisioner import DomainNginxProvisioner
        from app.services.platform.php_fpm import PhpFpmPoolService

        domain = None
        if env.hosting_domain_id:
            domain = await self._session.get(Domain, env.hosting_domain_id)
        if domain is None and env.domain:
            from sqlalchemy import select

            domain = (
                await self._session.execute(select(Domain).where(Domain.name == env.domain))
            ).scalar_one_or_none()

        # Keep env.document_root on the site tree; Domain.document_root is the nginx root.
        site = self._site_home(env)
        preferred = site / "public_html"
        if preferred.is_dir():
            env.document_root = str(preferred)
        elif str(env.document_root or "") != str(site):
            env.document_root = str(site)

        if domain:
            domain.document_root = str(web_root)
            domain.proxy_port = None

        hostname = (env.domain or (domain.name if domain else "") or "").strip()
        if not hostname:
            raise ValidationError("This environment has no domain to activate.")

        nginx = DomainNginxProvisioner(self._settings)
        await nginx.provision(
            hostname=hostname,
            document_root=str(web_root),
            proxy_port=None,
            force_https=bool(domain.force_https) if domain else False,
            ssl_certificate=domain.ssl_certificate_path if domain else None,
            enabled=True,
            create_docroot=False,
        )

        try:
            PhpFpmPoolService(self._settings).ensure_pool(
                hostname=hostname,
                document_root=str(web_root),
                ram_gb=float(env.ram_limit_gb or 0) or None,
                unix_user=env.unix_username or env.hosting_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("env_git_php_pool_failed", domain=hostname, error=str(exc))

        fix_web_ownership(web_root, user=self._settings.web_run_user)
        await self._session.flush()
        logger.info(
            "env_git_website_activated",
            environment_id=str(env.id),
            repo=str(real),
            web_root=str(web_root),
        )
        return {
            "environment_id": str(env.id),
            "path": str(real),
            "path_display": display,
            "web_root": str(web_root),
            "web_root_display": self._display_path(env, web_root),
            "message": f"Website now serves PHP/static files from {self._display_path(env, web_root)}.",
        }

    async def clone(self, env: CustomerEnvironment, *, repo_url: str, branch: str | None = None, repo_path: str | None = None, name: str | None = None) -> dict:
        if repo_path:
            return await self.create(
                env,
                name=name or Path(repo_path).name,
                repo_path=repo_path,
                clone=True,
                repo_url=repo_url,
                branch=branch,
            )
        # Legacy: clone into the site document root.
        await self._plan_cap(env)
        url = self._validate_clone_url(repo_url)
        root = self._root(env)
        if (root / ".git").is_dir():
            raise ConflictError("This site already has a Git repository. Pull instead of cloning.")
        entries = [p for p in root.iterdir() if p.name not in {".", ".."}]
        meaningful = [p for p in entries if p.name not in {"index.html", ".well-known", "favicon.ico"}]
        if meaningful:
            raise ValidationError(
                "Site folder is not empty. Clear files first, or clone into a new repository path."
            )
        tmp = root.parent / f".git-clone-{env.id.hex[:8]}"
        if tmp.exists():
            shutil.rmtree(tmp)
        cmd = ["git", "clone", "--depth", "1"]
        if branch and branch.strip():
            cmd += ["--branch", branch.strip()]
        cmd += [url, str(tmp)]
        code, out, err = await run_command(*cmd, timeout=180)
        if code != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise AppException((err or out or "Git clone failed")[-400:])
        for item in tmp.iterdir():
            dest = root / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
        shutil.rmtree(tmp, ignore_errors=True)
        fix_web_ownership(root, user=self._settings.web_run_user)
        self._upsert_registry(env, root, name or root.name or "website")
        logger.info("env_git_cloned", environment_id=str(env.id), url=url)
        payload = await self.list_repos(env)
        payload["message"] = "Repository cloned successfully."
        return payload

    async def pull(self, env: CustomerEnvironment, *, repo_path: str | None = None) -> dict:
        if repo_path:
            real, _ = self.resolve_requested_path(env, repo_path)
        else:
            real = self._root(env)
        if not (real / ".git").is_dir():
            raise ValidationError("No Git repository yet. Clone or create one first.")
        code, out, err = await run_git(real, "pull", "--ff-only", timeout=120)
        if code != 0:
            raise AppException((err or out or "Git pull failed")[-400:])
        fix_web_ownership(real, user=self._settings.web_run_user)
        payload = await self.list_repos(env)
        payload["message"] = "Pulled latest changes."
        payload["pulled_path"] = self._display_path(env, real)
        return payload

    async def history(self, env: CustomerEnvironment, *, repo_path: str, limit: int = 20) -> dict:
        real, display = self.resolve_requested_path(env, repo_path)
        if not (real / ".git").is_dir():
            raise NotFoundError("Repository not found.")
        n = max(1, min(int(limit or 20), 50))
        _, log, _ = await run_git(real, "log", f"-{n}", "--format=%h%x09%cI%x09%an%x09%s")
        commits = []
        for line in (log or "").splitlines():
            parts = line.split("\t", 3)
            if len(parts) < 4:
                continue
            commits.append(
                {
                    "commit": parts[0],
                    "committed_at": parts[1],
                    "author": parts[2],
                    "message": parts[3],
                }
            )
        return {"path_display": display, "commits": commits}

    async def remove(self, env: CustomerEnvironment, *, repo_path: str, delete_files: bool = False) -> dict:
        real, _ = self.resolve_requested_path(env, repo_path)
        home = self._site_home(env)
        doc = self._root(env)
        rows = [r for r in self._load_registry(env) if str(Path(str(r.get("path") or "")).resolve()) != str(real)]
        self._save_registry(env, rows)
        if delete_files and real != home and real != doc:
            shutil.rmtree(real, ignore_errors=True)
        elif (real / ".git").is_dir() and real != doc:
            shutil.rmtree(real / ".git", ignore_errors=True)
        payload = await self.list_repos(env)
        payload["message"] = "Repository removed from Git Version Control."
        return payload
