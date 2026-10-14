"""日志出口。

插件规范要求 logger **只能从 `astrbot.api` 取**，不许用内置 `logging`；而
`ainong/auth/` 与 `ainong/camp/` 刻意不 import astrbot——本地单测要能直接跑它们。
两边靠一个钩子接起来，这里钉住钩子的行为，也钉住「真出问题时确实会写一条」。

上线被驳回就是因为这两个模块用了内置 `logging`，所以这些用例不只是行为测试。
"""

from __future__ import annotations

import pytest

from ainong.auth.scan_session import 扫码会话
from ainong.日志 import 挂日志, 记


class _假出码会话:
    def __init__(self, 行为) -> None:
        self.行为 = 行为

    async def 等授权码(self, 超时秒: int, 完成) -> None:
        await self.行为(超时秒, 完成)

    async def 关闭(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _用完摘钩子():
    """钩子是模块级全局，用例之间不能互相污染。"""
    yield
    挂日志(None)


class Test记:
    def test_没挂钩子时静默(self):
        """本地单测就是这种情况：没有 astrbot，也没有钩子。"""
        记("warning", "没人听")

    def test_挂钩子后收到级别与内容(self):
        收到 = []
        挂日志(lambda 级别, 一句: 收到.append((级别, 一句)))

        记("error", "出事了")

        assert 收到 == [("error", "出事了")]

    def test_可以摘掉钩子(self):
        收到 = []
        挂日志(lambda 级别, 一句: 收到.append(一句))
        挂日志(None)

        记("warning", "没人听")

        assert 收到 == []


class Test真出问题时留得下日志:
    """这几条是钩子存在的理由：出错处理自己炸了的时候，只有日志能留线索。"""

    async def test_出错回调失败时写一条_error(self):
        收到 = []
        挂日志(lambda 级别, 一句: 收到.append((级别, 一句)))

        async def 行为(超时秒, 完成):
            raise RuntimeError("二维码已失效")

        async def 出错(exc):
            raise ValueError("通知又失败了")

        会话 = 扫码会话(5)
        会话._会话 = _假出码会话(行为)
        会话.开始等待(_忽略, 出错)
        await 会话._待等

        assert [级别 for 级别, _ in 收到] == ["error"]
        assert "通知又失败了" in 收到[0][1]

    async def test_没有出错回调时写一条_warning(self):
        收到 = []
        挂日志(lambda 级别, 一句: 收到.append((级别, 一句)))

        async def 行为(超时秒, 完成):
            raise TimeoutError("扫码超时")

        会话 = 扫码会话(5)
        会话._会话 = _假出码会话(行为)
        会话.开始等待(_忽略, None)
        with pytest.raises(TimeoutError):
            await 会话._待等

        assert [级别 for 级别, _ in 收到] == ["warning"]
        assert "扫码超时" in 收到[0][1]


async def _忽略(*_args) -> None:
    """空回调。必须是协程——`等授权码` 会 await 它。"""
