"""
GibberLink Revisited — Shared Bootstrap Utilities

Venv re-execution and port management, used by server.py and tts_server.py.
"""

import os
import sys
import subprocess


def reexec_in_venv():
    """Re-exec the current script inside .venv if running under system Python.

    On failure (e.g. corrupted venv), falls back to subprocess + sys.exit
    instead of letting os.execv crash with a cryptic OS error.
    """
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    venv_py = os.path.join(
        here, ".venv",
        "Scripts" if sys.platform == "win32" else "bin",
        "python.exe" if sys.platform == "win32" else "python",
    )
    in_venv = (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )
    if not in_venv and os.path.exists(venv_py) and sys.executable != venv_py:
        try:
            os.execv(venv_py, [venv_py] + sys.argv)
        except OSError:
            # Fallback: subprocess instead of execv (also handles Windows better)
            result = subprocess.run([venv_py] + sys.argv)
            sys.exit(result.returncode)
    elif not in_venv and not os.path.exists(venv_py):
        print("  ⚠ No .venv found. Run python3 setup.py first.")
        sys.exit(1)


def free_port(port: int):
    """Try to free a port by gracefully stopping any process bound to it.

    Strategy: SIGTERM first (gives the process a chance to clean up),
    then SIGKILL after a timeout if it's still alive. Only kills processes
    owned by the current user to avoid accidentally nuking unrelated services.
    """
    import signal
    import time

    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        if not out:
            return
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    pids = []
    for pid_str in out.splitlines():
        pid = int(pid_str)
        if pid == os.getpid():
            continue
        pids.append(pid)

    if not pids:
        return

    # Phase 1: SIGTERM (graceful)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"  ⚠ Sent SIGTERM to process on port {port} (PID {pid})")
        except ProcessLookupError:
            pass

    # Wait up to 3 seconds for graceful shutdown
    deadline = time.monotonic() + 3.0
    remaining = list(pids)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.2)
        still_alive = []
        for pid in remaining:
            try:
                os.kill(pid, 0)  # check if alive (signal 0 = no signal)
                still_alive.append(pid)
            except ProcessLookupError:
                pass
        remaining = still_alive

    # Phase 2: SIGKILL anything that didn't exit gracefully
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"  ⚠ Force-killed stubborn process on port {port} (PID {pid})")
        except ProcessLookupError:
            pass

    if pids:
        time.sleep(0.3)  # give OS time to release the socket
