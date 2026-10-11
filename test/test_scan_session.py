"""扫码会话的后台等待。

这个环节出过两个用户可见的问题，都在下面钉住：

1. **回调参数个数对不上。** `等授权码` 拿到授权码后 `await 完成(授权码)`，
   只传一个参数；而绑定时直接把 `_收到授权码(用户, 授权码)` 传了进去，
   它要两个。调用即 TypeError，异常发生在没人看的 task 里，用户看到微信提示
   "扫码已登上"但绑定没成功，日志里只有一行 Traceback。
2. **失败后会话不清理。** 超时或二维码失效时异常从 task 里抛走，
   调用方的会话字典里条目还在，用户再发绑定只会一直看到"扫码已经在进行中"，
   而他其实什么都没在扫。

测试用假的出码会话驱动真实的 `扫码会话`，不碰网络也不需要 astrbot。
pyproject 里 pytest-asyncio 是 auto 模式，async 测试直接写。
"""

from __future__ import annotations

import asyncio

import pytest

from ainong.auth.scan_session import 扫码会话


class 假出码会话:
    """替身：按脚本决定等授权码时发生什么。"""

    def __init__(self, 行为) -> None:
        self.行为 = 行为
        self.已关 = False

    async def 等授权码(self, 超时秒: int, 完成) -> None:
        await self.行为(超时秒, 完成)

    async def 关闭(self) -> None:
        self.已关 = True


async def _记下(exc: BaseException, 收集: list) -> None:
    收集.append(exc)


async def _忽略(*_args) -> None:
    """空回调。必须是协程——`等授权码` 会 await 它，返回 None 的同步回调会
    直接 TypeError。"""


def _会话(行为, 超时秒: int = 180) -> 扫码会话:
    会话 = 扫码会话(超时秒)
    会话._会话 = 假出码会话(行为)
    return 会话


async def _等结束(会话: 扫码会话, 容忍异常: bool = False) -> None:
    task = 会话._待等
    assert task is not None, "还没开始等待"
    try:
        await task
    except BaseException:
        if not 容忍异常:
            raise
        会话._待等 = None


class Test回调参数:
    async def test_单参异步回调能正常收到授权码(self):
        """回调必须是协程：`等授权码` 会 `await 完成(...)`，返回 None 的同步
        回调会直接 TypeError。原先签名标的 `Callable[[str], Any]` 太松。"""
        收到 = []

        async def 行为(超时秒, 完成):
            await 完成("授权码-XYZ")

        async def 完成(授权码: str) -> None:
            收到.append(授权码)

        会话 = _会话(行为)
        会话.开始等待(完成)
        await _等结束(会话)
        assert 收到 == ["授权码-XYZ"]

    async def test_同步回调的报错不会静默(self):
        """传了同步回调会 TypeError。要能被出错回调接住，而不是无声蒸发。"""
        记下 = []

        async def 行为(超时秒, 完成):
            await 完成("授权码-XYZ")

        会话 = _会话(行为)
        会话.开始等待(lambda 码: 记下.append(码), lambda exc: _记下(exc, 记下))
        await _等结束(会话)
        assert any(isinstance(x, TypeError) for x in 记下), (
            f"同步回调的 TypeError 应该被出错回调接住，实际收到：{记下}"
        )

    async def test_完整绑定流程能走通(self):
        """按 main.py 里的接法跑一遍：闭包把用户绑掉，只留单参回调。

        原先是直接传双参的 `_收到授权码`，而 `等授权码` 只传一个。
        """
        调用 = []

        async def 收到授权码(用户: str, 授权码: str) -> None:
            调用.append((用户, 授权码))

        def 完成(授权码: str):
            return 收到授权码("用户-1", 授权码)

        async def 行为(超时秒, 回调):
            await 回调("授权码-OK")

        会话 = _会话(行为)
        会话.开始等待(完成, _忽略)
        await _等结束(会话)
        assert 调用 == [("用户-1", "授权码-OK")]

    async def test_没出码不能开始等待(self):
        """顺序错了要当场报错，别等到后台 task 里才发现。"""
        会话 = 扫码会话(180)
        with pytest.raises(RuntimeError, match="还没出码"):
            会话.开始等待(_忽略)


class Test失败处理:
    async def test_异常会交给出错回调(self):
        记下 = []

        async def 行为(超时秒, 完成):
            raise TimeoutError("扫码超时")

        会话 = _会话(行为, 1)
        会话.开始等待(_忽略, lambda exc: _记下(exc, 记下))
        await _等结束(会话)
        assert len(记下) == 1
        assert isinstance(记下[0], TimeoutError)

    @pytest.mark.parametrize("异常", [TimeoutError("超时"), RuntimeError("二维码已失效")])
    async def test_两种失败都交给出错回调(self, 异常: BaseException):
        async def 行为(超时秒, 完成):
            raise 异常

        记下 = []
        会话 = _会话(行为, 1)
        会话.开始等待(_忽略, lambda exc: _记下(exc, 记下))
        await _等结束(会话)
        assert 记下 == [异常]

    async def test_出错回调抛异常不会让任务消失(self):
        """出错处理自己失败时不能连它一起蒸发，至少要留下异常。"""

        async def 行为(超时秒, 完成):
            raise RuntimeError("二维码已失效")

        async def 出错(exc):
            raise ValueError("通知又失败了")

        会话 = _会话(行为, 1)
        会话.开始等待(_忽略, 出错)
        # 不该有异常逃出来
        await _等结束(会话)

    async def test_出错回调可以是异步的(self):
        """清场和通知都要发网络请求，回调本身是协程。"""
        记下 = []

        async def 行为(超时秒, 完成):
            raise RuntimeError("二维码已失效")

        async def 出错(exc):
            await asyncio.sleep(0)
            记下.append(exc)

        会话 = _会话(行为, 1)
        会话.开始等待(_忽略, 出错)
        await _等结束(会话)
        assert len(记下) == 1


class Test取消与关闭:
    async def test_取消不当成失败处理(self):
        """主动关闭不该触发"扫码没走完"的通知。"""
        触发 = []

        async def 行为(超时秒, 完成):
            await asyncio.sleep(10)

        会话 = _会话(行为)

        async def 出错(exc):
            触发.append(exc)

        会话.开始等待(_忽略, 出错)
        await asyncio.sleep(0)
        await 会话.关闭()
        assert 触发 == [], "主动取消不该走失败分支"

    async def test_关闭会等_task_收尾并关掉会话(self):
        内部 = 假出码会话(lambda 秒, 完成: None)

        async def 行为(超时秒, 完成):
            await asyncio.sleep(10)

        会话 = _会话(行为)
        会话._会话 = 内部
        会话.开始等待(_忽略, _忽略)
        await asyncio.sleep(0)

        await 会话.关闭()
        assert 内部.已关, "http 会话应该被关掉"
        assert 会话._会话 is None
        assert 会话._待等 is None

    async def test_重复关闭不报错(self):
        会话 = _会话(lambda 秒, 完成: None)
        会话.开始等待(_忽略, _忽略)
        await 会话.关闭()
        await 会话.关闭()

    async def test_没出码也能关闭(self):
        await 扫码会话(180).关闭()

    async def test_关闭时会话仍在轮询也不报错(self):
        """取消是异步的，立刻关 http 可能让正在轮询的那一下抛连接错误。"""

        async def 行为(超时秒, 完成):
            await asyncio.sleep(10)

        会话 = _会话(行为)
        会话.开始等待(_忽略, _忽略)
        await asyncio.sleep(0)
        await 会话.关闭()  # 不该抛
