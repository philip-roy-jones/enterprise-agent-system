"""Synthetic runtime-owned checks, launched without credentials."""

import json
import sys
from eas_harness.candidate_checks import check_candidate

if __name__ == "__main__":
    print(json.dumps(check_candidate(json.loads(sys.stdin.read(50001)))))
