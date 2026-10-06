"""Verify the installed wheel from a synthetic directory, never source fallback."""

import importlib.metadata
import subprocess
import sys
import tempfile
from pathlib import Path

import tracecascade


def main():
    origin = Path(tracecascade.__file__).resolve()
    version = importlib.metadata.version('tracecascade')
    if 'site-packages' not in origin.parts or version != '1.0.3' or tracecascade.__version__ != version:
        raise SystemExit('Expected installed TraceCascade 1.0.3, not a source import')
    tests = Path(__file__).resolve().parents[1] / 'tests' / 'test_bounded_paths.py'
    with tempfile.TemporaryDirectory(prefix='tracecascade-installed-') as temporary:
        subprocess.run([sys.executable, '-I', str(tests), '-v'], cwd=temporary, check=True)
        subprocess.run([sys.executable, '-I', '-m', 'tracecascade', '--help'], cwd=temporary, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, '-I', '-m', 'pip', 'check'], cwd=temporary, check=True)
    print(f'Installed {version}: bounded-path oracle/CLI checks passed from site-packages')


if __name__ == '__main__':
    main()
