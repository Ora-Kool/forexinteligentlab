#!/usr/bin/env python3
"""Diagnose the macOS Wine MT5 bridge end to end.

Reports each hop separately -- Wine terminal, rpyc bridge, MT5 IPC, trade
account -- because a failure in the terminal's own login surfaces from the
Python API only as a generic ``(-6, 'Terminal: Authorization failed')``.

Windows (MT5_MODE=official) and agent setups are not touched by this script.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

WINE_PREFIX = Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5"
INSTALL_DIR = WINE_PREFIX / "drive_c/Program Files/MetaTrader 5"
WINDOWS_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

OK, WARN, BAD, INFO = "  ok  ", " warn ", " FAIL ", " info "


@dataclass
class Report:
    lines: list[tuple[str, str]] = field(default_factory=list)
    verdict: list[str] = field(default_factory=list)

    def add(self, level: str, message: str) -> None:
        self.lines.append((level, message))

    def fix(self, message: str) -> None:
        self.verdict.append(message)

    def render(self) -> int:
        print("\nMT5 mac bridge diagnostics")
        print("=" * 72)
        for level, message in self.lines:
            print(f"[{level}] {message}")
        print("=" * 72)
        if self.verdict:
            print("\nWhat to fix, in order:\n")
            for i, message in enumerate(self.verdict, 1):
                print(f"  {i}. {message}")
            print()
            return 1
        print("\nAll hops healthy: the bridge can read live FBS data.\n")
        return 0


def read_env(root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    path = root / ".env"
    if not path.exists():
        return env
    for raw in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_]+)\s*=\s*(.*)$", raw.strip())
        if match:
            env[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return env


def terminal_running() -> bool:
    try:
        out = subprocess.run(["ps", "ax"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    return "terminal64.exe" in out


def port_open(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(2.0)
        return sock.connect_ex((host, port)) == 0


def known_servers() -> list[str]:
    bases = INSTALL_DIR / "Bases"
    if not bases.is_dir():
        return []
    skip = {"Custom", "Default", "signals"}
    return sorted(
        p.name for p in bases.iterdir() if p.is_dir() and p.name not in skip
    )


def terminal_log_events() -> tuple[str | None, list[str]]:
    """Return (newest build line, recent network/login lines) from the MT5 log."""
    logs = INSTALL_DIR / "logs"
    if not logs.is_dir():
        return None, []
    files = sorted(logs.glob("2*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None, []
    try:
        text = files[0].read_text(encoding="utf-16", errors="replace")
    except Exception:
        text = files[0].read_text(encoding="utf-8", errors="replace")

    build: str | None = None
    events: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split("\t")[2:]).strip()
        if not line:
            continue
        if "started for" in line:
            build = line
        if re.search(r"authoriz|invalid account|login|no connection|connected to",
                     line, re.IGNORECASE):
            events.append(line)
    return build, events[-8:]


def probe_ipc(host: str, port: int, env: dict[str, str], report: Report) -> bool:
    try:
        import rpyc
    except ImportError:
        report.add(WARN, "rpyc not installed in .venv, skipping the IPC probe")
        report.fix("Install the client: ./scripts/mt5_mac_bridge.sh install-client")
        return False

    try:
        conn = rpyc.connect(
            host,
            port,
            config={"allow_all_attrs": True, "allow_public_attrs": True,
                    "sync_request_timeout": 120},
        )
        mt5 = conn.root.getmodule("MetaTrader5")
    except Exception as exc:
        report.add(BAD, f"cannot use MetaTrader5 through the bridge: {exc}")
        report.fix("Re-provision the Wine python: ./scripts/mt5_mac_bridge.sh provision")
        return False

    report.add(OK, "MetaTrader5 module imported inside Wine")

    path = env.get("MT5_TERMINAL_PATH") or WINDOWS_TERMINAL_PATH
    login = env.get("MT5_LOGIN", "")
    password = env.get("MT5_PASSWORD", "")
    server = env.get("MT5_SERVER", "")

    attempts: list[tuple[str, dict[str, object]]] = [
        ("path only", {"path": path}),
        ("portable=True", {"path": path, "portable": True}),
    ]
    if login and password and server:
        attempts.append(
            ("with credentials",
             {"path": path, "login": int(login), "password": password, "server": server}),
        )

    for label, kwargs in attempts:
        try:
            ok = bool(mt5.initialize(**kwargs))
            err = tuple(mt5.last_error())
        except Exception as exc:
            report.add(WARN, f"initialize({label}) raised: {exc}")
            continue
        if ok:
            account = mt5.account_info()
            report.add(OK, f"initialize({label}) succeeded")
            if account is None:
                report.add(BAD, "IPC is up but no trade account is authorized")
                report.fix(
                    "Log into your broker account in the MetaTrader 5 window "
                    "(File > Login to Trade Account)."
                )
                mt5.shutdown()
                return False
            report.add(OK, f"account {account.login} on {account.server} ({account.company})")
            bars = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M5, 0, 3)
            report.add(
                OK if bars is not None else WARN,
                f"EURUSD M5 sample: {0 if bars is None else len(bars)} bars",
            )
            mt5.shutdown()
            return True

        report.add(WARN if label != attempts[-1][0] else BAD,
                   f"initialize({label}) failed: {err}")
        if err and err[0] == -6:
            report.add(INFO, "-6 means the terminal has no authorized trade account")
        try:
            mt5.shutdown()
        except Exception:
            pass
    return False


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    env = read_env(root)
    host = env.get("MT5_BRIDGE_HOST") or "127.0.0.1"
    port = int(env.get("MT5_BRIDGE_PORT") or 18813)
    want_server = env.get("MT5_SERVER", "")
    report = Report()

    mode = env.get("MT5_MODE", "(unset)")
    report.add(INFO if mode == "bridge" else WARN, f"MT5_MODE={mode}")
    if mode != "bridge":
        report.fix("Set MT5_MODE=bridge in .env so the backend uses this bridge.")

    if INSTALL_DIR.is_dir():
        report.add(OK, f"MT5.app Wine prefix found: {INSTALL_DIR}")
    else:
        report.add(BAD, f"no MT5.app Wine prefix at {INSTALL_DIR}")
        report.fix("Install MetaTrader 5 for macOS and launch it once.")
        return report.render()

    if (INSTALL_DIR / "config").is_dir():
        report.add(INFO, "terminal runs in portable mode (data folder = install folder)")

    if terminal_running():
        report.add(OK, "terminal64.exe is running under Wine")
    else:
        report.add(BAD, "terminal64.exe is not running")
        report.fix("Open /Applications/MetaTrader 5.app and wait for it to finish loading.")

    build, events = terminal_log_events()
    if build:
        report.add(INFO, f"terminal log: {build}")

    servers = known_servers()
    if servers:
        report.add(INFO, f"trade servers this terminal has connected to: {', '.join(servers)}")
    else:
        report.add(WARN, "this terminal has never connected to a trade server")

    if want_server and want_server not in servers:
        report.add(BAD, f"MT5_SERVER={want_server} is not among the connected servers")
        report.fix(
            f"In the MetaTrader 5 window choose File > Open an Account, search for the "
            f"broker behind '{want_server}', pick the '{want_server}' server, then use "
            f"'Connect with an existing trade account' with login "
            f"{env.get('MT5_LOGIN', '<login>')}. Confirm the status bar bottom-right "
            f"shows a live ping instead of 'No connection'."
        )
    elif want_server:
        report.add(OK, f"MT5_SERVER={want_server} is known to the terminal")

    for line in events:
        bad = re.search(r"failed|invalid|no connection", line, re.IGNORECASE)
        report.add(BAD if bad else INFO, f"terminal log: {line}")

    if port_open(host, port):
        report.add(OK, f"rpyc bridge is listening on {host}:{port}")
        probe_ipc(host, port, env, report)
    else:
        report.add(BAD, f"nothing is listening on {host}:{port}")
        report.fix("Start the bridge in a second terminal: ./scripts/mt5_mac_bridge.sh serve")

    return report.render()


if __name__ == "__main__":
    raise SystemExit(main())
