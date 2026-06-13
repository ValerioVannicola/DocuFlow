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
        try:
            import nest_asyncio  # type: ignore[import]

            nest_asyncio.apply(loop)
        except ImportError:
            raise RuntimeError(
                "Cannot call run_sync() from within a running event loop "
                "(e.g. Jupyter). Either install nest_asyncio "
                "(`pip install nest_asyncio`) or use the async API directly: "
                "`await extract_async(...)`."
            ) from None
        return loop.run_until_complete(coro)  # type: ignore[return-value]

    return asyncio.run(coro)  # type: ignore[return-value]
