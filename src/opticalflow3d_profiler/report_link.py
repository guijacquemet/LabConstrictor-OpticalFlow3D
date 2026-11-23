"""Open an HTML report in a new browser tab from the notebook (I/O).

A small web server on ``127.0.0.1`` serves the report's folder (read-only, the standard
library's ``http.server``), and the notebook shows a link to it that opens in a new tab:

- **local Jupyter / the installed app:** the link points to ``http://127.0.0.1:<port>/``;
  the browser runs on the same computer;
- **Google Colab:** the kernel runs remotely, so Colab's own proxy opens the port in a new
  window (``google.colab.output.serve_kernel_port_as_window``).

A self-contained page also works when opened directly from the file browser; the path is
printed with the link.
"""

from __future__ import annotations

import functools
import html
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SERVERS: dict[Path, int] = {}


class _QuietHandler(SimpleHTTPRequestHandler):
    """Serve the report's files only: no directory listing, no request log in the notebook."""

    def list_directory(self, path: str) -> None:
        """Refuse directory listings (only named files are served)."""
        del path
        self.send_error(404, "No directory listing")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (stdlib name)
        """Do not log."""


def serve(folder: Path) -> int:
    """Serve ``folder`` on a free local port (once per folder) and return the port."""
    folder = Path(folder).resolve()
    if folder not in _SERVERS:
        handler = functools.partial(_QuietHandler, directory=str(folder))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _SERVERS[folder] = server.server_address[1]
    return _SERVERS[folder]


def show_link(report: Path, text: str = "Open the report in a new tab") -> None:
    """Display a link that opens ``report`` (an HTML file) in a new browser tab."""
    from IPython.display import HTML, display

    report = Path(report).resolve()
    port = serve(report.parent)
    if "google.colab" in sys.modules:
        from google.colab import output

        output.serve_kernel_port_as_window(port, path=f"/{report.name}", anchor_text=text)
    else:
        url = f"http://127.0.0.1:{port}/{report.name}"
        display(
            HTML(
                f'<p><a href="{html.escape(url)}" target="_blank" rel="noopener" '
                f'style="font-size:1.1em;font-weight:600">{html.escape(text)} ↗</a></p>'
            )
        )
    print(f"Report file: {report}")
