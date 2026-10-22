#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
if [ -f /tmp/sayacode-smoke-answer.txt ] && [ "$(cat /tmp/sayacode-smoke-answer.txt)" = "42" ]; then
    printf '1\n' > /logs/verifier/reward.txt
else
    printf '0\n' > /logs/verifier/reward.txt
fi
