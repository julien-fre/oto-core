"""Résolution de secrets 3-tier (`oto.config`) — le socle d'auth de tous les clients.

Ordre : env → provider (sops/file/scaleway) → fallback fichier → défaut. Ce
module n'avait AUCUN test alors qu'il décide QUELLE clé chaque connecteur reçoit
— un bug dans l'ordre = auth cassée en silence, ou pire, la mauvaise clé.

On isole tout ce qui touche l'environnement de la machine de test : caches vidés,
provider forcé via `_get_oto_config`, providers sops/scaleway stubbés. Aucun accès
au vrai `~/.otomata` ni à un store SOPS.
"""
from __future__ import annotations

import pytest

from oto import config


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Neutralise l'état machine : caches vidés, config vide (provider=sops par
    défaut), aucun secret de projet/user, DISABLE_SOPS non posé."""
    config._secrets_cache.clear()
    monkeypatch.setattr(config, "_oto_config_cache", None)
    monkeypatch.setattr(config, "_get_oto_config", lambda: {})
    monkeypatch.setattr(config, "_find_project_secrets", lambda: None)
    monkeypatch.setattr(config, "_file_provider_lookup", lambda name: config._MISSING)
    monkeypatch.delenv("OTO_CONFIG_DISABLE_SOPS", raising=False)
    monkeypatch.delenv("MY_SECRET", raising=False)


# --- tier 1 : env gagne toujours -------------------------------------------

def test_env_var_wins(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "from-env")
    assert config.get_secret("MY_SECRET") == "from-env"


def test_env_beats_provider(monkeypatch):
    """L'env prime sur le provider configuré (tier 1 > tier 2)."""
    monkeypatch.setenv("MY_SECRET", "from-env")
    monkeypatch.setattr(config, "_get_oto_config", lambda: {"secret_provider": "file"})
    monkeypatch.setattr(config, "_file_provider_lookup", lambda name: "from-file")
    assert config.get_secret("MY_SECRET") == "from-env"


def test_empty_env_var_does_not_win(monkeypatch):
    """Une var d'env VIDE n'est pas une valeur (`if env_val:`) → on continue la
    cascade jusqu'au défaut, au lieu de renvoyer ''."""
    monkeypatch.setenv("MY_SECRET", "")
    assert config.get_secret("MY_SECRET", default="fallback") == "fallback"


# --- server hardening : OTO_CONFIG_DISABLE_SOPS ----------------------------

def test_disable_sops_skips_filesystem(monkeypatch):
    """En mode serveur, un secret hors-env NE doit PAS être lu du filesystem —
    sinon une lecture silencieuse contournerait le store DB du serveur."""
    monkeypatch.setenv("OTO_CONFIG_DISABLE_SOPS", "1")
    monkeypatch.setattr(config, "_file_provider_lookup", lambda name: "from-file")
    assert config.get_secret("MY_SECRET", default="def") == "def"


def test_disable_sops_still_honours_env(monkeypatch):
    monkeypatch.setenv("OTO_CONFIG_DISABLE_SOPS", "1")
    monkeypatch.setenv("MY_SECRET", "from-env")
    assert config.get_secret("MY_SECRET") == "from-env"


# --- tier 2 : provider fichier ---------------------------------------------

def test_file_provider_lookup(monkeypatch):
    monkeypatch.setattr(config, "_get_oto_config", lambda: {"secret_provider": "file"})
    monkeypatch.setattr(config, "_file_provider_lookup", lambda name: "from-file")
    assert config.get_secret("MY_SECRET") == "from-file"


# --- tier 2 : provider sops (stubbé) ---------------------------------------

def _wire_sops(monkeypatch, *, secrets=None, ambiguous=None, missing_store=False):
    import oto.sops_secrets as sops

    def fetch(path=None, dir_path=None):
        if missing_store:
            raise FileNotFoundError("no SOPS repo")
        return secrets or {}

    monkeypatch.setattr(sops, "fetch_secrets", fetch)
    monkeypatch.setattr(sops, "ambiguous_keys", lambda: ambiguous or {})


def test_sops_provider_returns_secret(monkeypatch):
    _wire_sops(monkeypatch, secrets={"MY_SECRET": "from-sops"})
    assert config.get_secret("MY_SECRET") == "from-sops"


def test_sops_ambiguous_key_raises(monkeypatch):
    """Une clé présente avec des valeurs DIFFÉRENTES selon les fichiers = refus
    (renvoyer l'une d'elles serait arbitraire)."""
    _wire_sops(monkeypatch, secrets={}, ambiguous={"MY_SECRET": ["a.yaml", "b.yaml"]})
    with pytest.raises(config.AmbiguousSecretError, match="DIFFERENT values"):
        config.get_secret("MY_SECRET")


def test_sops_store_missing_falls_back_to_file(monkeypatch):
    """sops par défaut mais aucun repo SOPS (install tierce) → fallback gracieux
    sur le fichier local, pas d'exception."""
    _wire_sops(monkeypatch, missing_store=True)
    monkeypatch.setattr(config, "_file_provider_lookup",
                        lambda name: "from-file" if name == "MY_SECRET" else config._MISSING)
    assert config.get_secret("MY_SECRET") == "from-file"


def test_sops_store_missing_no_file_returns_default(monkeypatch):
    _wire_sops(monkeypatch, missing_store=True)
    assert config.get_secret("MY_SECRET", default="def") == "def"


# --- tier 3 : défaut --------------------------------------------------------

def test_returns_default_when_unresolved(monkeypatch):
    _wire_sops(monkeypatch, secrets={})
    assert config.get_secret("MY_SECRET", default="def") == "def"
    assert config.get_secret("MY_SECRET") is None


# --- require_secret ---------------------------------------------------------

def test_require_secret_returns_value(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "v")
    assert config.require_secret("MY_SECRET") == "v"


def test_require_secret_raises_with_guidance(monkeypatch):
    _wire_sops(monkeypatch, secrets={})
    with pytest.raises(ValueError, match="not found"):
        config.require_secret("MY_SECRET")


def test_require_secret_server_mode_message(monkeypatch):
    """En mode serveur, le message d'erreur oriente vers l'env / le store DB,
    pas vers les fichiers locaux (désactivés)."""
    monkeypatch.setenv("OTO_CONFIG_DISABLE_SOPS", "1")
    with pytest.raises(ValueError, match="OTO_CONFIG_DISABLE_SOPS"):
        config.require_secret("MY_SECRET")


# --- get_json_secret --------------------------------------------------------

def test_json_secret_parses(monkeypatch):
    monkeypatch.setenv("MY_SECRET", '{"a": 1}')
    assert config.get_json_secret("MY_SECRET") == {"a": 1}


def test_json_secret_bad_json_returns_none(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "not-json")
    assert config.get_json_secret("MY_SECRET") is None


def test_json_secret_absent_returns_none(monkeypatch):
    _wire_sops(monkeypatch, secrets={})
    assert config.get_json_secret("MY_SECRET") is None


# --- _parse_env_file : quotes / comments / cache ---------------------------

def test_parse_env_file_handles_quotes_and_comments(tmp_path):
    f = tmp_path / "secrets.env"
    f.write_text(
        "# a comment\n"
        "\n"
        "PLAIN=value\n"
        "QUOTED='single quoted'\n"
        'DQUOTED="double quoted"\n'
        "WITH_EQUALS=a=b=c\n"
        "  SPACED  =  trimmed  \n"
    )
    config._secrets_cache.clear()
    parsed = config._parse_env_file(f)
    assert parsed["PLAIN"] == "value"
    assert parsed["QUOTED"] == "single quoted"
    assert parsed["DQUOTED"] == "double quoted"
    assert parsed["WITH_EQUALS"] == "a=b=c"  # split sur le 1er '=' seulement
    assert parsed["SPACED"] == "trimmed"
    assert "# a comment" not in parsed


def test_parse_env_file_missing_is_empty(tmp_path):
    config._secrets_cache.clear()
    assert config._parse_env_file(tmp_path / "nope.env") == {}
