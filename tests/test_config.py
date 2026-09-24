import pytest

from doomlab.config import DEFAULT_MODEL, ConfigError, load_settings, normalize_base_url


@pytest.mark.parametrize(
    "raw",
    [
        "https://genai.rcac.purdue.edu",
        "https://genai.rcac.purdue.edu/",
        "https://genai.rcac.purdue.edu/api",
        "https://genai.rcac.purdue.edu/api/",
    ],
)
def test_base_url_is_normalized(raw):
    assert normalize_base_url(raw) == "https://genai.rcac.purdue.edu"


def test_settings_build_api_urls(monkeypatch, tmp_path):
    monkeypatch.setenv("RCAC_BASE_URL", "https://genai.rcac.purdue.edu/api")
    monkeypatch.setenv("RCAC_API_KEY", "test-key")
    monkeypatch.delenv("RCAC_MODEL", raising=False)
    settings = load_settings(env_file=tmp_path / "missing.env")
    assert settings.model_id == DEFAULT_MODEL == "qwen3.8:27b"
    assert settings.chat_url == "https://genai.rcac.purdue.edu/api/chat/completions"
    assert settings.models_url == "https://genai.rcac.purdue.edu/api/models"


@pytest.mark.parametrize("key", ["", "REPLACE_LOCALLY"])
def test_missing_or_placeholder_key_fails_fast(monkeypatch, tmp_path, key):
    monkeypatch.setenv("RCAC_API_KEY", key)
    with pytest.raises(ConfigError):
        load_settings(env_file=tmp_path / "missing.env")


def test_settings_repr_hides_key(monkeypatch, tmp_path):
    monkeypatch.setenv("RCAC_API_KEY", "super-secret")
    assert "super-secret" not in repr(load_settings(env_file=tmp_path / "missing.env"))
