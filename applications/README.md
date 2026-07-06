# IFNOTUS Application Registry

Place one YAML file per application in this directory.
Files with `.example` suffix are ignored.

## Example

See `app.example.yaml.example` for the full schema.

## Quick start

```bash
cp app.example.yaml.example my-api.yaml
# Edit paths, runtime bindings, and type
```

Supported types: `laravel`, `fastapi`, `django`, `nodejs`, `static_site`
