from __future__ import annotations

import os

from kernel.api.app import app

if __name__ == "__main__":
    app.run(
        host=os.environ.get("TTDM_HOST", "127.0.0.1"),
        port=int(os.environ.get("TTDM_PORT", "8000")),
        debug=False,
    )
