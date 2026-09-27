"""Run repository checks and each test file in an isolated subprocess.

No desktop model or drawing is opened. --core excludes the geospatial suite
when its optional packages have not been installed.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', action='store_true')
    args = parser.parse_args()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', SITE_ANALYSIS_SKIP_BOOTSTRAP='1')
    # Upstream Rhino tests inspect files from its full C# repository. This
    # distribution contains only its Python bridge and contracts; validate it
    # through the separate documented runtime smoke check instead.
    tests = [path for path in (ROOT / 'plugins').rglob('test_*.py')
             if 'rhinomcp' not in path.relative_to(ROOT).parts]
    files = [ROOT / 'scripts/validate_repo.py'] + sorted(tests)
    failed = []
    skipped = []
    for path in files:
        rel = str(path.relative_to(ROOT))
        if args.core and 'site-analysis' in path.parts:
            skipped.append(rel)
            continue
        print(f'\n>>> {rel}', flush=True)
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(path)], cwd=ROOT, env=env, check=False)
        if result.returncode:
            failed.append(rel)
    print(f'\nChecks: {len(files) - len(skipped)} executed; {len(failed)} failed; {len(skipped)} skipped.')
    if failed:
        print('Failed:', ', '.join(failed))
    if skipped:
        print('Not validated:', ', '.join(skipped))
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
