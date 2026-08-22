# PHASE 25 — Application runtime manager

Customer environments can run **multiple managed applications** under one site.
IFNOTUS owns the process supervisor — customers do not get raw `systemctl`, `supervisorctl`, or PM2 daemon access.

## Architecture

```text
Hosting Panel → ApplicationRuntimeService → supervisor (or pid fallback)
                      ↓
              apps/{slug}/ under document root
                      ↓
              nginx location /apps/{slug}/ → proxy port
```

## Supported frameworks (package-gated)

Static HTML, PHP, WordPress, Laravel, Python, Flask, FastAPI, Django, Node.js, Express, React, Vue.

Catalog: `GET /customers/environments/{id}/applications/catalog`

## API

| Method | Path | Action |
|--------|------|--------|
| GET | `.../applications/catalog` | List frameworks + entitlement |
| GET | `.../applications` | List apps |
| POST | `.../applications` | Create (name, framework, git_url, build/start, env_vars) |
| POST | `.../applications/{id}/deploy` | Build + start via supervisor |
| POST | `.../applications/{id}/restart` | Restart process |
| DELETE | `.../applications/{id}` | Stop + remove |

`PlatformJob` backup/restore types remain separate; app deploy is synchronous for now.

## Data model

`application_instances`: `runtime`, `framework`, `status`, `allocated_port`, `config_json` (name, slug, git_url, commands, env_vars, supervisor_program).

## Hosting Panel

**Apps** tab → Applications list + create form (replaces one-click stack for that tab; Stack remains under portal site subnav).

## Ops notes

- Supervisor configs: `/etc/supervisor/conf.d/ifnotus_{env}_{app}.conf`
- Nginx snippets: `/etc/nginx/ifnotus-apps/{env_id}-{slug}.conf`
- Without supervisor socket, deploy still marks static/PHP apps running; proxy apps need supervisor or manual ops.
