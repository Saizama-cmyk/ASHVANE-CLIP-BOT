import asyncio
import threading

import pytest

from clipbot.storage_io import StorageIO


def test_slow_capture_work_never_consumes_general_workers_or_exceeds_budget():
    async def run():
        storage = StorageIO(2)
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        def blocked(index):
            entered[index].set()
            assert release.wait(5)
        jobs = [asyncio.create_task(storage.run(blocked, index % 2)) for index in range(40)]
        try:
            for event in entered:
                assert await asyncio.wait_for(asyncio.to_thread(event.wait, 2), 3)
            assert await asyncio.wait_for(asyncio.to_thread(lambda: 'dashboard metadata'), 1) == 'dashboard metadata'
            assert storage.snapshot() == {'active': 2, 'waiting': 38, 'limit': 2, 'reason': 'capture_storage_capacity'}
            for task in jobs: task.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            assert storage.active == 2 and storage.waiting == 0  # running I/O still owns its slots
            release.set()
            assert await asyncio.wait_for(storage.run(lambda: 'recovered'), 2) == 'recovered'
        finally:
            release.set()
            await asyncio.gather(*jobs, return_exceptions=True)
            storage.close()
    asyncio.run(run())


def test_worker_exception_releases_slot_and_stopped_pool_refuses_new_work():
    async def run():
        storage = StorageIO(1)
        def broken(): raise OSError('fixture failure')
        try:
            with pytest.raises(OSError, match='fixture failure'):
                await storage.run(broken)
            assert storage.active == 0
            assert await storage.run(lambda: 1) == 1
        finally: storage.close()
        with pytest.raises(RuntimeError, match='stopped'):
            await storage.run(lambda: 1)
    asyncio.run(run())
