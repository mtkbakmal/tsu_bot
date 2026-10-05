import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe

from tsu_bot.__main__ import poll_forever


class FakeDP:
    def __init__(self, fails):
        self.fails, self.calls, self.kwargs = fails, 0, None

    async def start_polling(self, bot, **kw):
        self.calls += 1
        self.kwargs = kw
        if self.calls <= self.fails:
            raise TelegramNetworkError(method=GetMe(), message="timeout")


async def test_retries_with_backoff_instead_of_crashing():
    delays = []

    async def fake_sleep(d): delays.append(d)

    dp = FakeDP(fails=4)
    await poll_forever(dp, object(), first_delay=10, max_delay=30, sleep=fake_sleep)
    assert dp.calls == 5 and delays == [10, 20, 30, 30]
    assert dp.kwargs == {"close_bot_session": False}   # сессию закрываем сами один раз


async def test_other_errors_are_not_swallowed():
    class Boom(FakeDP):
        async def start_polling(self, bot, **kw): raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        await poll_forever(Boom(0), object(), sleep=lambda d: None)


@pytest.mark.parametrize("proxy", ["http://127.0.0.1:8080", "socks5://127.0.0.1:1080"])
async def test_proxy_session_is_constructible(proxy):
    s = AiohttpSession(proxy=proxy)
    await s.create_session()
    await s.close()
