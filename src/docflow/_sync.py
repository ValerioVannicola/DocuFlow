from __future__ import annotations

import asyncio
from typing import TypeVar

T = TypeVar("T")


def run_sync(coro: object) -> T:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        raise RuntimeError(
            "Cannot call run_sync() from within a running event loop. "
            "Use the async API directly instead."
        )
    return asyncio.run(coro)
