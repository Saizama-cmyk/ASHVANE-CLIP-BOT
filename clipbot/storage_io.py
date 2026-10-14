"""Bound slow capture storage without consuming the dashboard's general workers."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial


class StorageIO:
    def __init__(self, limit: int):
        self.limit, self.active, self.waiting = limit, 0, 0
        self._slots = asyncio.Semaphore(limit)
        self._pool = ThreadPoolExecutor(max_workers=limit, thread_name_prefix="capture-storage")
        self._closed = False

    async def run(self, function, *args):
        if self._closed:
            raise RuntimeError("Capture storage workers are stopped")
        self.waiting += 1
        try:
            await self._slots.acquire()
        finally:
            self.waiting -= 1
        if self._closed:
            self._slots.release()
            raise RuntimeError("Capture storage workers are stopped")
        self.active += 1
        try:
            future = asyncio.get_running_loop().run_in_executor(self._pool, partial(function, *args))
        except BaseException:
            self.active -= 1
            self._slots.release()
            raise
        def finished(_):
            self.active -= 1
            self._slots.release()
        future.add_done_callback(finished)
        # Cancellation cannot free a worker while its filesystem call is still running.
        return await asyncio.shield(future)

    def snapshot(self):
        return {"active": self.active, "waiting": self.waiting, "limit": self.limit,
                "reason": "capture_storage_capacity" if self.waiting else ""}

    def close(self):
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
