"""QQ 扫码会话。

QQ 那条与微信的差别都在这里，所以值得单独测：

- **二维码两分钟就过期**，用户收到第一条消息到掏出手机要花掉大半。所以会话
  会反复换码，而且**每次换都必须推给用户**——不推的话用户盯着的是一张已经
  失效的图，扫多少次都没用。
- 授权码要从浏览器深链接里捞，中途还要换票换营地账号。

测试用假的浏览器会话驱动真实的 `QQ扫码会话`，不碰网络也不需要 playwright。
"""

from __future__ import annotations

import asyncio

import pytest

from ainong.auth.qq_login import QQ扫码会话


class 假浏览器:
    """按脚本决定换页与取图的结果。

    `扫到第几次` 是"第几次换页时认为用户扫到了"——扫码要花时间，不会第一轮
    就中。设为 None 表示一直扫不到（测超时用）。
    """

    def __init__(self, 换页脚本: list = (), 扫到第几次: int | None = None) -> None:
        self.换页脚本 = list(换页脚本)
        self.扫到第几次 = 扫到第几次
        self.轮次 = 0
        self.取图次数 = 0
        self.已关 = False

    async def 换页重开(self, url: str) -> None:
        self.轮次 += 1
        if self.换页脚本:
            结果 = self.换页脚本.pop(0)
            if isinstance(结果, Exception):
                raise 结果

    async def 取二维码(self) -> str:
        self.取图次数 += 1
        return f"图片-{self.取图次数}"

    async def 打开(self, url: str) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.已关 = True

    @property
    def 已获授权码(self) -> str | None:
        if self.扫到第几次 is None:
            return None
        if self.轮次 >= self.扫到第几次:
            return "CODE-1"
        return None


def _会话(浏览器: 假浏览器, 刷新秒: int = 0, 超时秒: int = 5) -> QQ扫码会话:
    会话 = QQ扫码会话("http://侧车:3000", 超时秒, 刷新秒)
    会话._浏览器 = 浏览器
    return 会话


async def _等结束(会话: QQ扫码会话, 容忍异常: bool = False) -> None:
    task = 会话._待等
    assert task is not None, "还没开始等待"
    try:
        await task
    except BaseException:
        if not 容忍异常:
            raise
        会话._待等 = None


class Test换码通知:
    async def test_每次换码都推一张新图(self):
        """这是 QQ 那条最关键的行为。

        不推的话，用户手上永远是第一张图，而那张早就过期了。
        """
        推出去的 = []

        async def 换页(url: str) -> None:
            pass

        async def 换码通知(图片: str) -> None:
            推出去的.append(图片)

        async def 完成(凭据) -> None:
            return None

        # 扫到第 4 次才中：之前每次换完都要推一张新的
        浏览器 = 假浏览器(换页脚本=[None, None, None, None], 扫到第几次=4)
        会话 = _会话(浏览器, 刷新秒=0)
        会话.开始等待(完成, 换码通知)
        await _等结束(会话)

        assert len(推出去的) >= 2, f"应多次推新码，实际 {len(推出去的)} 次"
        assert len(set(推出去的)) == len(推出去的), "每次推的应是不同的码"

    async def test_出码之后不会立刻再推一张(self):
        """`出码()` 已经给过用户一张，后台要等这张到期再换。

        原来循环体一进来就无条件换页 + 取图 + 推送：用户一次绑定连着收到两张
        码，而且那次换页会让 `出码()` 那张当场作废——扫第一张必然失败。所以
        这里用真实的刷新间隔，断言"间隔没到就既不推、也不取图"。
        """
        推出去的 = []

        async def 换码通知(图片: str) -> None:
            推出去的.append(图片)

        async def 完成(凭据) -> None:
            return None

        浏览器 = 假浏览器(扫到第几次=None)
        会话 = _会话(浏览器, 刷新秒=1, 超时秒=5)
        会话.开始等待(完成, 换码通知)
        await asyncio.sleep(0.4)  # 远早于第一个刷新间隔

        assert 推出去的 == [], f"刷新间隔未到就不该推码，实际推了 {len(推出去的)} 张"
        assert 浏览器.取图次数 == 0, "更不该在用户还没看第一张时就去取第二张"
        await 会话.关闭()

    async def test_扫到就停不再换码(self):
        推出去的 = []

        async def 换页(url: str) -> None:
            pass

        async def 换码通知(图片: str) -> None:
            推出去的.append(图片)

        async def 完成(凭据) -> None:
            return None

        浏览器 = 假浏览器(扫到第几次=2)
        会话 = _会话(浏览器, 刷新秒=0)
        会话.开始等待(完成, 换码通知)
        await _等结束(会话)

        # 扫到就停，不再取图
        assert 浏览器.取图次数 <= 2, f"扫到后不该继续取图，实际 {浏览器.取图次数} 次"

    async def test_取图失败不放弃整轮(self):
        """单次取图失败只是这一轮不行，不能让整场扫码崩掉。"""
        推出去的 = []
        完成的 = []

        async def 换码通知(图片: str) -> None:
            推出去的.append(图片)

        async def 完成(凭据) -> None:
            完成的.append(凭据)

        # 第一次换页报错，第二次正常且扫到了
        浏览器 = 假浏览器(换页脚本=[RuntimeError("页面还没渲染完")], 扫到第几次=2)
        会话 = _会话(浏览器, 刷新秒=0)
        会话.开始等待(完成, 换码通知)
        await _等结束(会话)

        assert 完成的 == ["CODE-1"], "取图失败后应继续重试，而不是整体失败"


class Test失败处理:
    async def test_超时交给出错回调(self):
        记下 = []

        async def 换页(url: str) -> None:
            pass

        async def 换码通知(图片: str) -> None:
            pass

        浏览器 = 假浏览器()
        会话 = _会话(浏览器, 刷新秒=0, 超时秒=0)
        会话.开始等待(
            lambda 码: None,
            换码通知,
            lambda exc: 记下.append(exc),
        )
        await _等结束(会话)
        assert len(记下) == 1
        assert isinstance(记下[0], TimeoutError)

    async def test_出错回调抛异常不会让任务消失(self):
        async def 换页(url: str) -> None:
            pass

        async def 换码通知(图片: str) -> None:
            pass

        async def 出错(exc) -> None:
            raise ValueError("通知又失败了")

        浏览器 = 假浏览器()
        会话 = _会话(浏览器, 刷新秒=0, 超时秒=0)
        会话.开始等待(lambda 码: None, 换码通知, 出错)
        await _等结束(会话)  # 不该抛

    async def test_取消不当成失败(self):
        """关闭会话时主动取消，不该触发"扫码没走完"。"""
        触发 = []

        async def 换页(url: str) -> None:
            pass

        async def 换码通知(图片: str) -> None:
            pass

        async def 行为(超时秒, 完成):
            await asyncio.sleep(10)

        浏览器 = 假浏览器()
        会话 = _会话(浏览器, 刷新秒=1)

        # 造一个永远换不完的循环
        async def 换页卡住(url: str) -> None:
            await asyncio.sleep(10)

        浏览器.换页重开 = 换页卡住
        会话.开始等待(lambda 码: None, 换码通知, lambda exc: 触发.append(exc))
        await asyncio.sleep(0)
        await 会话.关闭()
        assert 触发 == [], "主动取消不该走失败分支"


class Test关闭:
    async def test_关闭会关掉浏览器并清空(self):
        浏览器 = 假浏览器()
        会话 = _会话(浏览器)
        await 会话.关闭()
        assert 浏览器.已关
        assert 会话._浏览器 is None

    async def test_重复关闭不报错(self):
        会话 = _会话(假浏览器())
        await 会话.关闭()
        await 会话.关闭()

    async def test_没出码也能关闭(self):
        await QQ扫码会话("http://侧车:3000", 5).关闭()

    async def test_关闭时会话仍在轮询也不报错(self):
        """取消是异步的，立刻关浏览器可能让正在取图的那一下抛连接错误。"""

        async def 换页卡住(url: str) -> None:
            await asyncio.sleep(10)

        浏览器 = 假浏览器()
        浏览器.换页重开 = 换页卡住
        会话 = _会话(浏览器, 刷新秒=1)

        async def 换码通知(图片: str) -> None:
            pass

        会话.开始等待(lambda 码: None, 换码通知, lambda exc: None)
        await asyncio.sleep(0)
        await 会话.关闭()  # 不该抛


class Test出码:
    async def test_取图失败会把浏览器关掉(self, monkeypatch):
        """浏览器起来了但授权页没加载出来，不能把它留在后台跑着。

        每个会话独占一个浏览器上下文，漏关就等于漏一个 Chromium 页面。
        """
        已关 = []

        class 会失败的浏览器:
            async def __aenter__(self):
                return self

            async def 打开(self, url: str) -> None:
                pass

            async def 取二维码(self) -> str:
                raise RuntimeError("授权页没加载出来")

            async def __aexit__(self, *exc: object) -> None:
                已关.append(True)

        monkeypatch.setattr("ainong.auth.qq_login.浏览器会话", lambda *a, **kw: 会失败的浏览器())

        会话 = QQ扫码会话("http://侧车:3000", 5)
        with pytest.raises(RuntimeError, match="授权页没加载出来"):
            await 会话.出码()

        assert 已关, "取图失败时必须把浏览器关掉"
        assert 会话._浏览器 is None

    async def test_浏览器启动失败也不留下会话(self, monkeypatch):
        """`__aenter__` 自己失败时不能把半启动的浏览器挂在会话上。

        每个会话独占一个 Chromium 上下文，挂在 `self._浏览器` 上却从没关过，
        就是漏一个。每发一次 `/爱农 绑定QQ` 漏一个。
        """

        class 起不来的浏览器:
            async def __aenter__(self):
                raise RuntimeError("连不上浏览器侧车")

            async def __aexit__(self, *exc: object) -> None:
                pass

        monkeypatch.setattr("ainong.auth.qq_login.浏览器会话", lambda *a, **kw: 起不来的浏览器())

        会话 = QQ扫码会话("http://不存在的侧车:9999", 5)
        with pytest.raises(RuntimeError, match="连不上浏览器侧车"):
            await 会话.出码()
        assert 会话._浏览器 is None

    async def test_没装_playwright_时错误要说清楚(self):
        """playwright 在可选依赖组里。没装时要报「没装」，不是 ModuleNotFoundError。

        ModuleNotFoundError 直接透给用户的话，他看到的是英文的模块名，
        不知道该做什么。
        """
        会话 = QQ扫码会话("http://侧车:3000", 5)
        with pytest.raises(Exception) as 捕获:
            await 会话.出码()
        文本 = str(捕获.value)
        assert "playwright" in 文本, f"错误消息要说清缺什么：{文本}"
