"""QQ 扫码绑定。

微信出码是纯 HTTP，不需要浏览器；QQ 不行——授权页要执行 JS、渲染二维码、
捕获深链接里的授权码，只能靠真的浏览器。所以这一路依赖独立的 Playwright
服务（AstrBot 容器里没有浏览器）。

流程与微信那条并行：

    出码 → 把二维码推给用户 → 后台换新码并等扫码 → 授权码 → 营地账号

二维码只有约两分钟寿命，而用户从收到消息到掏出手机要花掉大半，所以不等它
失效就主动换新。已发出的那张图会过期，**换码时要再推一张新的**，否则用户
盯着的是一张扫不了的图。这是 QQ 与微信最大的区别：微信那张码五分钟内都有效。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from ..auth.ysdk import YSDK_URL, build_auth_headers
from ..camp.transport import 营地传输
from .browser import 浏览器会话

__all__ = ["QQ扫码会话", "QQ_APP_ID", "QQ_LOGIN_URL", "QQ_USER_AGENT"]

QQ_APP_ID = "1105200115"
QQ_LOGIN_URL = (
    "https://openmobile.qq.com/oauth2.0/m_authorize"
    f"?client_id={QQ_APP_ID}&scope=all"
    f"&redirect_uri=auth%3A%2F%2Ftauth.qq.com%2F&style=qr&response_type=code"
)
# 授权页对 UA 有要求：桌面 UA 会拿到不同的页面结构，二维码元素找不到。
QQ_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; V2366GA Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/110.0.5481.154 Safari/537.36 tencent_game_emulator"
)

# 二维码寿命远短于直觉：扫完手机端还要经一次 txz.qq.com 跳转才回到授权页，
# 这段往返吃掉大半有效期。刷新间隔必须比真实寿命短。
默认刷新秒 = 25
轮询间隔秒 = 1


async def 换取平台凭据(code: str) -> dict[str, str]:
    """授权码换 YSDK 平台凭据。纯 HTTP，不走浏览器。"""
    timestamp = str(int(time.time()))
    body = json.dumps({"appID": QQ_APP_ID, "loginCode": code}, separators=(",", ":"))

    async with aiohttp.ClientSession() as 会话:
        async with 会话.post(
            YSDK_URL, headers=build_auth_headers(body, timestamp), data=body.encode("utf-8")
        ) as 响应:
            载荷 = json.loads(await 响应.text())

    数据 = 载荷.get("data") or {}
    if 载荷.get("code") != 0 or 数据.get("ret") != 0:
        raise RuntimeError(f"换票失败：{载荷.get('errmsg') or 数据.get('message') or '未知原因'}")

    return {
        "accessToken": 数据["accessToken"],
        "openId": 数据["openID"],
        "payToken": 数据.get("payToken", ""),
        "refreshToken": 数据.get("refreshToken", ""),
    }


async def 登录营地(平台凭据: dict[str, str]) -> dict[str, Any]:
    """平台凭据换营地账号。失败时关掉传输层，不留悬空的连接。"""
    async with 营地传输() as 传输:
        return await 传输.登录(平台凭据=平台凭据)


class QQ扫码会话:
    """一次 QQ 扫码绑定会话。

    与微信那条一样是两步：先出码立刻返回，后台等扫码。差别在于二维码要
    反复换，每换一次都要通过 `换码通知` 推给用户。
    """

    def __init__(
        self,
        服务地址: str,
        超时秒: int,
        刷新秒: int = 默认刷新秒,
        二维码路径: str = "",
    ) -> None:
        self._服务地址 = 服务地址
        self._超时 = 超时秒
        self._刷新秒 = 刷新秒
        self._二维码路径 = 二维码路径
        self._浏览器: 浏览器会话 | None = None
        self._待等: asyncio.Task | None = None

    async def 出码(self) -> str:
        """启动浏览器、打开授权页，返回第一张二维码的 base64。

        浏览器启动失败要在这里就报出来——用户看到的应该是「浏览器服务不可用」，
        而不是一张永远扫不出来的图。

        浏览器先放局部变量，全流程成功才挂到 `self._浏览器` 上。反过来写的话，
        `__aenter__` 自己失败时 `self._浏览器` 已经赋值，而它从没被关过——每个
        会话独占一个 Chromium 上下文，漏一个就漏一个。
        """
        浏览器 = 浏览器会话(self._服务地址, QQ_USER_AGENT, self._二维码路径)
        try:
            await 浏览器.__aenter__()
            await 浏览器.打开(QQ_LOGIN_URL)
            图片 = await 浏览器.取二维码()
        except BaseException:
            await 浏览器.__aexit__(None, None, None)
            raise

        self._浏览器 = 浏览器
        return 图片

    def 开始等待(
        self,
        完成: Callable[[str], Any],
        换码通知: Callable[[str], Any],
        出错: Callable[[BaseException], Any] | None = None,
    ) -> None:
        """后台等扫码。

        `换码通知` 收到新的 base64 二维码。因为码两分钟就过期，用户手上
        早先那张会失效，所以每次换码都要推一张新的给他。
        """
        self._待等 = asyncio.create_task(self._等待(完成, 换码通知, 出错))

    async def _等待(
        self,
        完成: Callable[[str], Any],
        换码通知: Callable[[str], Any],
        出错: Callable[[BaseException], Any] | None,
    ) -> None:
        try:
            code = await self._换码直到扫码(换码通知)
            await 完成(code)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - 任何失败都要能交出去
            if 出错 is None:
                raise
            try:
                await 出错(exc)
            except asyncio.CancelledError:
                raise
            except BaseException as 内层:  # noqa: BLE001
                import logging

                logging.getLogger("astrbot_plugin_ainong").error(
                    "[ainong] 处理 QQ 扫码失败时又出错：%s: %s",
                    type(内层).__name__,
                    内层,
                )

    async def _换码直到扫码(self, 换码通知: Callable[[str], Any]) -> str:
        """等扫码，二维码到期才换新的一张。

        这里踩过一个坑：原来循环体一进来就无条件 `换页重开` + `取二维码` +
        `换码通知`，于是用户一次绑定会连着收到**两张**码——`出码()` 刚给过一张，
        后台任务立刻又推一张。更糟的是那次换页会让 `出码()` 那张当场作废，
        用户扫第一张必然失败。

        所以要等第一张用满自己的寿命再去换：到期时间从进入本函数时起算，
        而不是从循环开始处。每换一次把到期时间往后推一个刷新间隔。
        """
        assert self._浏览器 is not None, "还没出码"
        截止 = time.monotonic() + self._超时
        下次换 = time.monotonic() + self._刷新秒
        while time.monotonic() < 截止:
            if self._浏览器.已获授权码:
                return self._浏览器.已获授权码

            if time.monotonic() >= 下次换:
                try:
                    await self._浏览器.换页重开(QQ_LOGIN_URL)
                    图片 = await self._浏览器.取二维码()
                except Exception:
                    # 单次取图失败不值得放弃整轮，等下一个周期再试。
                    await asyncio.sleep(轮询间隔秒)
                    下次换 = time.monotonic() + self._刷新秒
                    continue

                if self._浏览器.已获授权码:
                    return self._浏览器.已获授权码

                await 换码通知(图片)
                下次换 = time.monotonic() + self._刷新秒

            await asyncio.sleep(轮询间隔秒)

        raise TimeoutError(f"{self._超时} 秒内没有等到扫码完成")

    async def 关闭(self) -> None:
        """关掉浏览器与后台任务。可重复调用。"""
        if self._待等 is not None:
            self._待等.cancel()
            try:
                await self._待等
            except BaseException:  # noqa: BLE001 - 取消与失败都在预期内
                pass
            self._待等 = None
        if self._浏览器 is not None:
            浏览器, self._浏览器 = self._浏览器, None
            await 浏览器.__aexit__(None, None, None)
