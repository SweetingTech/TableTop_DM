from __future__ import annotations

from redis import Redis


def fail_once(redis_url: str, key: str) -> int:
    """Importable RQ fixture proving an immediate retry can recover."""
    connection = Redis.from_url(redis_url)
    attempt = int(connection.incr(key))
    if attempt == 1:
        raise RuntimeError("intentional first-attempt failure")
    return attempt
