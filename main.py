"""Entry point: run the local Flask UI."""

from __future__ import annotations

import os

from ui.app import app


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Serving at http://{host}:{port}/ (Ctrl+C to stop)")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG", "1") == "1")


if __name__ == "__main__":
    main()
