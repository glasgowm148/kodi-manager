"""Keep CI test hangs bounded and preserve output before the runner is cancelled."""
import os
import subprocess
import sys
from pathlib import Path


def run_bounded(command, log, timeout=180):
    with Path(log).open("wb") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
            output.write(b"\nCI test process exceeded its deadline and was terminated.\n")
            return 124


def main():
    log = Path("pytest.log")
    result = run_bounded([sys.executable, "-u", "-m", "pytest", "-vv", *sys.argv[1:]], log,
                         timeout=int(os.environ.get("CI_PYTEST_TIMEOUT", "180")))
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-80:] if result else lines[-5:]))
    return result


if __name__ == "__main__":
    sys.exit(main())
