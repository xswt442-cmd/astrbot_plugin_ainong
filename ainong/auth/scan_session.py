"""一次扫码绑定的会话生命周期。

出码和等待分成两步，二维码才能立刻发出去；等待跑在后台 task 里。

这个类里踩过两个坑，都在注释里写着原因：

- **回调参数个数**。`等授权码` 拿到授权码后只传一个参数，而绑定侧需要
  （用户, 授权码）两个。把双参函数直接传进来就是 TypeError，异常发生在没人
  看的 task 里，用户看到微信提示"扫码已登上"却没绑定成功。所以这里只接受
  单参回调，用户标识由调用方在外面绑掉。
- **失败后不清理**。超时或二维码失效时异常从 task 抛走，会话条目留在调用方
  的字典里，用户再发绑定只会一直看到"扫码正在进行中"。所以失败一律交给
  出错回调，由它去清场并告知用户；取消不算失败。

放在这里而不是 main.py，是为了能脱离 astrbot 单测——main.py 顶层 import
了 astrbot，本地没有这个包。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ..日志 import 记
from .wechat_flow import 微信出码会话

__all__ = ["扫码会话"]


class 扫码会话:
    """一次扫码绑定会话。"""

    def __init__(self, 超时秒: int) -> None:
        self._超时 = 超时秒
        self._会话: Any = None
        self._待等: asyncio.Task | None = None

    async def 出码(self) -> str:
        """出二维码，立刻返回 base64 图片。"""
        self._会话 = 微信出码会话()
        return await self._会话.出码()

    def 开始等待(
        self,
        完成: Callable[[str], Any],
        出错: Callable[[BaseException], Any] | None = None,
    ) -> None:
        """后台等扫码完成，拿到授权码后回调。

        两个回调都是单参：完成收授权码，出错收异常。需要更多上下文就在
        调用方用闭包绑掉，不要改这里的签名——等授权码是按单参调用的。

        出错回调不是可选的装饰：等待跑在没人看的 task 里，异常不接住就只是
        让 task 静默崩掉，用户什么都看不到。
        """
        if self._会话 is None:
            raise RuntimeError("还没出码，不能开始等待")
        self._待等 = asyncio.create_task(self._等待(完成, 出错))

    async def _等待(
        self,
        完成: Callable[[str], Any],
        出错: Callable[[BaseException], Any] | None,
    ) -> None:
        try:
            await self._会话.等授权码(self._超时, 完成)
        except asyncio.CancelledError:
            # 主动关闭不算失败，不该触发"扫码没走完"
            raise
        except BaseException as exc:  # noqa: BLE001 - 任何失败都要能交出去
            if 出错 is None:
                记("warning", f"扫码等待失败：{type(exc).__name__}: {exc}")
                raise
            try:
                await 出错(exc)
            except asyncio.CancelledError:
                raise
            except BaseException as 内层:  # noqa: BLE001
                # 出错处理自己失败时不能连它一起消失，至少留日志
                记("error", f"处理扫码失败时又出错：{type(内层).__name__}: {内层}")

    async def 关闭(self) -> None:
        """取消等待并关掉 http 会话。可重复调用。"""
        # 先等 task 自己收尾再关 http：取消是异步的，立刻关会话可能让
        # 正在轮询的那一下抛连接错误。
        if self._待等 is not None:
            self._待等.cancel()
            try:
                await self._待等
            except BaseException:  # noqa: BLE001 - 取消与失败都在预期内
                pass
            self._待等 = None
        if self._会话 is not None:
            会话, self._会话 = self._会话, None
            await 会话.关闭()
