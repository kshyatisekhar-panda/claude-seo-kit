#!/usr/bin/env python3
"""Entry point for Claude SEO Kit tools.

    python run.py setup     create the private environment (once)
    python run.py doctor    check the environment without changing anything
    python run.py <command> anything else, see `python run.py -h`

Dependencies live in their own virtual environment (SEOKIT_HOME, default
~/.claude-seo-kit), never in the system Python. Uses only the standard
library until that environment exists.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("SEOKIT_HOME") or Path.home() / ".claude-seo-kit")
VENV = HOME / "venv"
MIN = (3, 10)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def setup() -> int:
    if sys.version_info < MIN:
        print(f"Python {MIN[0]}.{MIN[1]}+ is required, this is {sys.version.split()[0]}.", file=sys.stderr)
        return 2
    HOME.mkdir(parents=True, exist_ok=True)
    if not venv_python().exists():
        print(f"creating environment in {VENV}")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    print("installing dependencies")
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                           "-r", str(ROOT / "requirements.txt")])
    print("ready. Optional: pip install weasyprint into this environment for PDF reports.")
    return 0


def doctor() -> int:
    ok = True
    print(f"python   {sys.version.split()[0]} {'ok' if sys.version_info >= MIN else 'too old'}")
    ok &= sys.version_info >= MIN
    exists = venv_python().exists()
    print(f"env      {VENV} {'ok' if exists else 'missing: run setup'}")
    ok &= exists
    if exists:
        probe = subprocess.run([str(venv_python()), "-c", "import requests, bs4, defusedxml, urllib3; "
                                "assert int(urllib3.__version__.split('.')[0]) >= 2"],
                               capture_output=True, text=True)
        print(f"packages {'ok' if probe.returncode == 0 else 'incomplete: run setup'}")
        ok &= probe.returncode == 0
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["setup"]:
        return setup()
    if args[:1] == ["doctor"]:
        return doctor()
    target = venv_python()
    inside = Path(sys.prefix).resolve() == VENV.resolve()
    if target.exists() and not inside:
        return subprocess.call([str(target), str(Path(__file__).resolve()), *args])
    sys.path.insert(0, str(ROOT))
    try:
        from seokit.cli import main as cli_main
    except ImportError as exc:
        print(f"missing dependency ({exc.name}). Run: python run.py setup", file=sys.stderr)
        return 3
    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
