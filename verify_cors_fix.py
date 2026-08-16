import os
import sys
from unittest.mock import patch, MagicMock

# Mock all dependencies to avoid import issues
sys.modules['flask'] = MagicMock()
sys.modules['flask_socketio'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['werkzeug.utils'] = MagicMock()
sys.modules['markdown'] = MagicMock()
sys.modules['pypdf'] = MagicMock()
sys.modules['openai'] = MagicMock()

def test_cors_logic():
    # Since we've mocked flask_socketio, we can check what was passed to its constructor
    import flask_socketio

    scenarios = [
        (None, None),
        ("http://localhost:8000", ["http://localhost:8000"]),
        ("http://localhost:8000, https://example.com ", ["http://localhost:8000", "https://example.com"]),
    ]

    for env_val, expected in scenarios:
        # Reset mocks and sys.modules for re-import
        flask_socketio.SocketIO.reset_mock()
        if 'app' in sys.modules:
            del sys.modules['app']

        env = {"DATABASE_URL": "mock://"}
        if env_val is not None:
            env["CORS_ALLOWED_ORIGINS"] = env_val

        with patch.dict(os.environ, env):
            import app

            # Check the second argument to SocketIO constructor (cors_allowed_origins)
            # socketio = SocketIO(app, cors_allowed_origins=_cors_origins, ...)
            args, kwargs = flask_socketio.SocketIO.call_args
            actual = kwargs.get('cors_allowed_origins')

            assert actual == expected, f"Expected {expected}, got {actual} for env={env_val}"
            print(f"PASSED: CORS_ALLOWED_ORIGINS='{env_val}' -> {actual}")

if __name__ == "__main__":
    try:
        test_cors_logic()
        print("\nAll CORS verification tests passed successfully!")
    except Exception as e:
        print(f"\nVerification FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
