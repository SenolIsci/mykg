from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from mykg.logging import get

log = get("mykg.uv_venv")


def _venv_bin(venv_dir: Path, name: str) -> Path:
    """Return the path to an executable inside a uv-created venv."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def _run(cmd: list[str], *, timeout: int, phase: str) -> None:
    """Run a uv subcommand. Raise RuntimeError with truncated stderr on failure."""
    log.info("uv_venv — %s: %s", phase, " ".join(cmd))
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"uv_venv — {phase} timed out after {timeout}s") from exc
    duration = time.monotonic() - t0

    if proc.returncode != 0:
        # Imported lazily so that importing this module (transitively via cli.py)
        # does not force config.py to load — that lets `mykg init` run in a
        # directory that has no mykg_config.yaml yet.
        from mykg.config import LOG_ERROR_OUTPUT_MAX_CHARS

        stderr = (proc.stderr or "").strip()[:LOG_ERROR_OUTPUT_MAX_CHARS]
        stdout = (proc.stdout or "").strip()[:LOG_ERROR_OUTPUT_MAX_CHARS]
        raise RuntimeError(
            f"uv_venv — {phase} failed with exit code {proc.returncode}\n"
            f"stderr: {stderr}\nstdout: {stdout}"
        )
    log.info("uv_venv — %s done in %.1fs", phase, duration)


@contextmanager
def ephemeral_venv(
    python_version: str,
    spec: str,
    uv_path: str,
    install_timeout: int,
    *,
    bin_name: str,
    prefix: str,
) -> Iterator[Path]:
    """Create a fresh Python venv with `spec` installed, yield a named binary.

    The venv lives in a TemporaryDirectory and is deleted when the context
    exits (success or exception). uv auto-downloads the requested Python
    interpreter if the host system lacks it. `bin_name` is the executable to
    yield from the venv's bin/ dir (e.g. "mineru", or "python" to run a script).
    """
    resolved_uv = shutil.which(uv_path)
    if resolved_uv is None:
        raise RuntimeError(
            f"uv not found at {uv_path!r}; uv is a core mykg dependency, "
            "reinstall mykg or set the uv_path key in mykg_config.yaml."
        )

    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        venv_dir = Path(tmp) / "venv"
        log.info("uv_venv — creating venv at %s (python=%s)", venv_dir, python_version)

        _run(
            [resolved_uv, "venv", "--python", python_version, str(venv_dir)],
            timeout=install_timeout,
            phase="uv venv",
        )
        # Split spec on whitespace so multi-package specs like
        # "mineru[all] pdftext<0.7.0" expand into separate arguments.
        spec_args = spec.split()
        _run(
            [
                resolved_uv,
                "pip",
                "install",
                "--python",
                str(_venv_bin(venv_dir, "python")),
                "-U",
                *spec_args,
            ],
            timeout=install_timeout,
            phase=f"uv pip install {spec}",
        )

        target_bin = _venv_bin(venv_dir, bin_name)
        if not target_bin.exists():
            raise RuntimeError(f"uv_venv — installed {spec} but {target_bin} not found")

        log.info("uv_venv — ready: %s", target_bin)
        try:
            yield target_bin
        finally:
            log.info("uv_venv — cleaning up %s", venv_dir)


@contextmanager
def ephemeral_mineru_venv(
    python_version: str,
    mineru_spec: str,
    uv_path: str,
    install_timeout: int,
) -> Iterator[Path]:
    """Thin wrapper over `ephemeral_venv` yielding the mineru binary (D48)."""
    with ephemeral_venv(
        python_version,
        mineru_spec,
        uv_path,
        install_timeout,
        bin_name="mineru",
        prefix="mykg-mineru-venv-",
    ) as mineru_bin:
        yield mineru_bin


__all__ = ["ephemeral_venv", "ephemeral_mineru_venv"]
