"""Install the release wheel in a fresh venv and run the isolated local smoke check."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = re.search(r'^VERSION = "([^"]+)"$', (ROOT / "src/kodi_manager/version.py").read_text(), re.M).group(1)
    wheels = list((ROOT / "dist").glob("*-" + version + "-*.whl"))
    if len(wheels) != 1:
        raise ValueError("Build exactly one current-version wheel first")
    with tempfile.TemporaryDirectory() as directory:
        environment = Path(directory) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", str(wheels[0])], check=True)
        subprocess.run([str(python), "-I", str(ROOT / "scripts/smoke_install.py")], cwd=directory, check=True)


if __name__ == "__main__":
    main()
