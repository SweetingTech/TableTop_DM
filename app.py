"""TableTop DM Flask entrypoint.

The route implementation lives in ``services.api.application`` so this file
stays as the small composition root expected by launchers and tests.
"""

import os

from services.api.application import app, socketio


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    debug = os.environ.get("TTDM_DEBUG", "0").lower() in {"1", "true", "yes", "on"}
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=debug,
        allow_unsafe_werkzeug=True,
    )
