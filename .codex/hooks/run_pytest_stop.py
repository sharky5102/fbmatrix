import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def emit(payload):
    print(json.dumps(payload))


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        event = {}

    if sys.platform == 'win32':
        python = ROOT / '.venv' / 'Scripts' / 'python.exe'
    else:
        python = ROOT / '.venv' / 'bin' / 'python'
    if not python.is_file():
        python = Path(sys.executable)

    result = subprocess.run(
        [str(python), '-m', 'pytest', '-q'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        errors='replace',
        check=False,
    )
    output = '\n'.join(part.strip() for part in (result.stdout, result.stderr) if part.strip())

    if result.returncode == 0:
        emit({'continue': True, 'systemMessage': 'Full pytest suite passed.'})
        return

    excerpt = output[-12000:] if output else '(pytest produced no output)'
    reason = (
        'The full pytest suite failed with exit code %d. Review the output and '
        'fix the failures before finishing.\n\n%s'
    ) % (result.returncode, excerpt)
    if event.get('stop_hook_active'):
        emit({'continue': True, 'systemMessage': reason})
    else:
        emit({'decision': 'block', 'reason': reason})


if __name__ == '__main__':
    main()
