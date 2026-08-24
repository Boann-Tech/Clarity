"""Configuration loading tests."""

import os


def test_load_backend_env_reads_explicit_env_file(tmp_path, monkeypatch):
    from app.config import load_backend_env

    env_file = tmp_path / ".env"
    env_file.write_text(
        "CLARITY_BIFROST_BASE_URL=https://gateway.example/v1\n"
        "CLARITY_BIFROST_MODEL=provider/deployed-model\n"
    )
    monkeypatch.delenv("CLARITY_BIFROST_BASE_URL", raising=False)
    monkeypatch.delenv("CLARITY_BIFROST_MODEL", raising=False)

    load_backend_env(env_file)

    assert os.environ["CLARITY_BIFROST_BASE_URL"] == "https://gateway.example/v1"
    assert os.environ["CLARITY_BIFROST_MODEL"] == "provider/deployed-model"
