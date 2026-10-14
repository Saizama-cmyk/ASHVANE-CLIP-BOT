import asyncio

import httpx

from clipbot.hardware import _net_mbps


def test_speedtest_trickle_cannot_avoid_overall_deadline():
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.005)
                yield b"x"
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Trickle()))) as http:
            return await asyncio.wait_for(_net_mbps(http, .03), .3)
    assert asyncio.run(run()) is None
