"""Unit tests for Python/Node project auto-detect helpers."""

from __future__ import annotations

from pathlib import Path

from app.services.platform.application_runtime import (
    ApplicationRuntimeService,
    classify_project_dir,
    detect_node_start_command,
    detect_python_entry,
)


def test_detect_fastapi_entry(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    assert detect_python_entry(tmp_path) == ("asgi", "app.main:app")


def test_detect_flask_entry(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )
    assert detect_python_entry(tmp_path) == ("wsgi", "app:app")


def test_detect_django_entry(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("print('x')\n", encoding="utf-8")
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "wsgi.py").write_text("application = None\n", encoding="utf-8")
    assert detect_python_entry(tmp_path) == ("wsgi", "config.wsgi:application")


def test_classify_and_node_start(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","main":"server.js","scripts":{"start":"node server.js"}}',
        encoding="utf-8",
    )
    (tmp_path / "server.js").write_text("console.log(1)\n", encoding="utf-8")
    assert classify_project_dir(tmp_path) == ("nodejs", "express") or classify_project_dir(
        tmp_path
    )[0] == "nodejs"
    assert detect_node_start_command(tmp_path) == "npm start"


def test_default_python_start_helper() -> None:
    assert ApplicationRuntimeService._is_default_python_start(
        "fastapi",
        "gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} app.main:app",
    )
    assert not ApplicationRuntimeService._is_default_python_start(
        "fastapi",
        "gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} myapi.main:app",
    )
