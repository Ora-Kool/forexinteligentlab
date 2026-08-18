#!/usr/bin/env python3
"""Start a long-running command in its own session.

``nohup`` only ignores SIGHUP, so a service started from a shell still dies when
the whole process group is signalled (closing the terminal, an IDE task ending).
Calling ``setsid`` makes the child a session leader, fully detaching it. The
child's pid is also its process group id, so callers can stop the whole tree
with ``kill -- -<pid>``.

usage: spawn_detached.py <logfile> <pidfile> <cmd> [args...]
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2

    logfile, pidfile, *command = sys.argv[1:]

    pid = os.fork()
    if pid > 0:
        with open(pidfile, "w", encoding="utf-8") as handle:
            handle.write(str(pid))
        return 0

    # Child: become a session leader so no upstream process group kill reaches us.
    os.setsid()
    try:
        out = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, 0)
        os.dup2(out, 1)
        os.dup2(out, 2)
        os.execvp(command[0], command)
    except Exception as exc:  # pragma: no cover - exec failure path
        try:
            with open(logfile, "a", encoding="utf-8") as handle:
                handle.write(f"spawn_detached failed for {command!r}: {exc}\n")
        except Exception:
            pass
        os._exit(127)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
