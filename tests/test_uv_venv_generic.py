from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from mykg.uv_venv import ephemeral_mineru_venv, ephemeral_venv


def _fake_run_factory(bin_names):
    """Return a fake_run that fabricates a venv tree with the given binaries."""
    def fake_run(cmd, **kwargs):
        from unittest.mock import MagicMock
        if "venv" in cmd and "pip" not in cmd:
            venv_dir = Path(cmd[-1])
            bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in bin_names:
                (bin_dir / name).write_text("")
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc
    return fake_run


def test_ephemeral_venv_yields_named_binary(tmp_path: Path) -> None:
    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=_fake_run_factory(["python"])),
    ):
        with ephemeral_venv("3.12", "crawlee[beautifulsoup]", "uv", 60,
                            bin_name="python", prefix="mykg-crawl-venv-") as py:
            assert py.name in ("python", "python.exe")
            assert py.exists()


def test_ephemeral_mineru_venv_still_yields_mineru(tmp_path: Path) -> None:
    """Regression: the wrapper still yields the mineru binary unchanged."""
    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=_fake_run_factory(["python", "mineru"])),
    ):
        with ephemeral_mineru_venv("3.12", "mineru[all]", "uv", 60) as mineru_bin:
            assert mineru_bin.name in ("mineru", "mineru.exe")
            assert mineru_bin.exists()
