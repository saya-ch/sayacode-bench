#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
python - <<'PY'
from pathlib import Path

answer = Path('/app/answer.txt')
passed = answer.is_file() and answer.read_bytes() == b'42\n'
Path('/logs/verifier/reward.txt').write_text('1\n' if passed else '0\n', encoding='utf-8')
PY
