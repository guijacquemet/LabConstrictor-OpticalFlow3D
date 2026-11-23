"""Offline smoke test of an installed OpticalFlow3D Profiler (Linux).

Usage, with the Python of the installed app (``<prefix>/bin/python``) and the app folder
(``<prefix>/OpticalFlow3D Profiler``)::

    unshare -rn <prefix>/bin/python tools/offline_smoke.py "<prefix>/OpticalFlow3D Profiler"

``unshare -rn`` runs it in a new network namespace without any network. The script checks
that the network is unreachable, starts JupyterLab and fetches the notebook through its
API, then executes every cell of the installed notebook. Add ``--allow-root`` when run as
root (containers).
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PORT = 8899


def loopback_up() -> None:
    """Bring up ``lo`` in a fresh network namespace (SIOCGIFFLAGS / SIOCSIFFLAGS)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    flags = struct.unpack("16sH", fcntl.ioctl(sock, 0x8913, struct.pack("16sH", b"lo", 0)))[1]
    fcntl.ioctl(sock, 0x8914, struct.pack("16sH", b"lo", flags | 0x1))


def check_offline() -> None:
    """Exit when the internet is reachable."""
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3)
    except OSError as error:
        print("offline confirmed:", error)
        return
    sys.exit("The network is reachable: this is not an offline test.")


def check_jupyterlab(root: Path, extra: list[str]) -> None:
    """Start JupyterLab and fetch the notebook through its contents API."""
    command = [
        str(Path(sys.executable).parent / "jupyter"),
        "lab",
        "--no-browser",
        f"--port={PORT}",
        "--IdentityProvider.token=smoke",
        f"--ServerApp.root_dir={root / 'notebooks'}",
        *extra,
    ]
    lab = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = (
        f"http://127.0.0.1:{PORT}/api/contents/OpticalFlow3D_Profiler/OpticalFlow3D_Profiler.ipynb"
    )
    try:
        for _ in range(60):
            try:
                notebook = json.load(urllib.request.urlopen(url + "?token=smoke", timeout=2))
            except OSError:
                time.sleep(1)
                continue
            print("JupyterLab serves", notebook["name"])
            return
        sys.exit("JupyterLab did not start.")
    finally:
        lab.terminate()
        lab.wait(timeout=30)


def run_notebook(root: Path) -> None:
    """Execute every cell of the installed notebook and fail on any error output."""
    import nbclient  # noqa: PLC0415 (installed with JupyterLab)
    import nbformat  # noqa: PLC0415

    path = root / "notebooks" / "OpticalFlow3D_Profiler" / "OpticalFlow3D_Profiler.ipynb"
    notebook = nbformat.read(path, as_version=4)
    nbclient.NotebookClient(notebook, timeout=120, kernel_name="python3").execute()
    errors = [
        o for c in notebook.cells for o in c.get("outputs", []) if o["output_type"] == "error"
    ]
    if errors:
        sys.exit(f"{len(errors)} cell(s) failed.")
    print("notebook executed offline without errors")


def main() -> None:
    """Run the three checks."""
    loopback_up()
    check_offline()
    os.environ["JUPYTER_DATA_DIR"] = tempfile.mkdtemp()  # only the app's own kernel
    # As launch_jupyter.py does: the app's kernel wins over a user-level "python3" kernelspec.
    os.environ["JUPYTER_PREFER_ENV_PATH"] = "1"
    root = Path(sys.argv[1])
    check_jupyterlab(root, sys.argv[2:])
    run_notebook(root)


if __name__ == "__main__":
    main()
