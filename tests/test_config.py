from pathlib import Path

from opentoonz_mcp.config import Settings, settings_from_env


def test_defaults():
    settings = Settings.from_env({})
    assert settings.data_home == Path("~/.local/share/opentoonz-mcp").expanduser()
    assert settings.workspaces_root == settings.data_home / "workspaces"
    assert settings.script_timeout == 90
    assert settings.render_timeout == 600
    assert settings.keep_scripts is True
    assert settings.stuff_root == settings.data_home / "stuff"
    assert settings.home == settings.data_home / "home"


def test_overrides():
    settings = settings_from_env(
        {
            "OPENTOONZ_MCP_HOME": "/tmp/ot-home",
            "OPENTOONZ_WORKSPACES": "/tmp/ot-ws",
            "OPENTOONZ_RUNTIME": "/opt/ot",
            "OPENTOONZ_STUFF": "/opt/ot-stuff",
            "OPENTOONZ_SCRIPT_TIMEOUT": "12",
            "OPENTOONZ_RENDER_TIMEOUT": "34",
            "OPENTOONZ_KEEP_SCRIPTS": "false",
            "OPENTOONZ_FFMPEG": "/usr/bin/ffmpeg",
        }
    )
    assert settings.data_home == Path("/tmp/ot-home")
    assert settings.workspaces_root == Path("/tmp/ot-ws")
    assert settings.runtime_dir == Path("/opt/ot")
    assert settings.stuff_root == Path("/opt/ot-stuff")
    assert settings.script_timeout == 12
    assert settings.render_timeout == 34
    assert settings.keep_scripts is False
    assert settings.ffmpeg == "/usr/bin/ffmpeg"


def test_bad_int_falls_back_to_default():
    assert settings_from_env({"OPENTOONZ_SCRIPT_TIMEOUT": "nope"}).script_timeout == 90


def test_empty_values_ignored():
    settings = settings_from_env({"OPENTOONZ_MCP_HOME": "   "})
    assert settings.data_home == Path("~/.local/share/opentoonz-mcp").expanduser()
