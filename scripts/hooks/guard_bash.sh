#!/usr/bin/env bash
# PreToolUse(Bash) hook entry point. Delegates to guard_bash.py; without python3 it allows everything.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 "$here/guard_bash.py"
