"""Development server entry point with bounded graceful shutdown."""

from __future__ import annotations

import argparse
import os
import signal

import uvicorn


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the YiBanPaiBan development API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--timeout-graceful-shutdown",
        type=float,
        default=15.0,
        help="Maximum seconds to wait for streaming requests during reload.",
    )
    parser.add_argument("--no-reload", action="store_true", help="Disable WatchFiles reload.")
    return parser


def _install_windows_reload_fallback(timeout: float) -> None:
    """Bound detached Windows reloads where CTRL_C_EVENT may not reach workers."""
    if os.name != "nt":
        return

    from uvicorn._subprocess import get_subprocess
    from uvicorn.supervisors.basereload import BaseReload

    def restart(self) -> None:
        # Uvicorn's Windows reloader uses CTRL_C_EVENT, which is not delivered
        # reliably when the launcher has no attached console (e.g. Desktop).
        self.is_restarting = True
        assert self.process.pid is not None
        try:
            os.kill(self.process.pid, signal.CTRL_C_EVENT)
        except (OSError, ValueError):
            pass
        self.process.join(timeout=timeout)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()
        self.process = get_subprocess(config=self.config, target=self.target, sockets=self.sockets)
        self.process.start()

    BaseReload.restart = restart


def main() -> None:
    args = _parser().parse_args()
    timeout = max(0.0, args.timeout_graceful_shutdown)
    _install_windows_reload_fallback(timeout)
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        timeout_graceful_shutdown=timeout,
        timeout_keep_alive=5,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
