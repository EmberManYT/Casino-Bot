"""Start the blackjack assistant with a model matching the current project."""
import subprocess
import sys
from pathlib import Path


def main() -> None:
    project = Path(__file__).resolve().parents[2]
    model = 'blackjack-happy-path'
    for args in (
        ['train', '--fixed-model-name', model],
        ['shell', '--model', f'models/{model}.tar.gz', '--endpoints', 'endpoints.yml'],
    ):
        result = subprocess.run([sys.executable, '-m', 'rasa', *args], cwd=project)
        if result.returncode:
            raise SystemExit(result.returncode)
