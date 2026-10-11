"""微信扫码的完整流程。

营地出 SDK 票据 → 微信官方换二维码 → 轮询等授权码 → 营地换登录态。
全程 HTTP，不需要浏览器。

出码与等待分成两步：二维码要立刻发给用户，扫码在后台等。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from .wechat import (
    WECHAT_POLL_URL,
    WECHAT_QR_URL,
    build_poll_query,
    build_qr_query,
    解析出码响应,
    解析扫码状态,
)

__all__ = ["微信出码会话"]

营地网关 = "https://ssl.kohsocialapp.qq.com:10001"
SDK票据接口 = f"{营地网关}/a/getwxsdkticket"

_轮询间隔秒 = 2
_单次请求秒 = 35


class 微信出码会话:
    """一次微信扫码会话。出码后可以等扫码完成。"""

    def __init__(self) -> None:
        self._http: Any = None
        self._uuid = ""

    async def 出码(self) -> str:
        """出二维码，返回 base64 图片内容。"""
        import aiohttp

        from ..camp.transport import _公共头

        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=_单次请求秒))

        票据 = await self._取票据(_公共头)
        async with self._http.get(WECHAT_QR_URL, params=build_qr_query(票据)) as 响应:
            结果 = 解析出码响应(json.loads(await 响应.text()))

        self._uuid = 结果["uuid"]
        return 结果["二维码"]

    async def _取票据(self, 公用头: dict[str, str]) -> str:
        import uuid

        头 = dict(公用头)
        头["x-log-uid"] = str(uuid.uuid4()).upper()

        async with self._http.post(SDK票据接口, headers=头) as 响应:
            载荷 = json.loads(await 响应.text())

        if 载荷.get("returnCode") != 0:
            raise RuntimeError(f"营地出票失败：{载荷.get('returnMsg') or '未知原因'}")

        票据 = str((载荷.get("data") or {}).get("sdkTicket") or "")
        if not 票据:
            raise RuntimeError("营地返回的票据为空")
        return 票据

    async def 等授权码(self, 超时秒: int, 完成: Callable[[str], Any]) -> None:
        """轮询等用户扫码，拿到授权码后交给回调处理。"""
        截止 = time.monotonic() + 超时秒
        while time.monotonic() < 截止:
            async with self._http.get(WECHAT_POLL_URL, params=build_poll_query(self._uuid)) as 响应:
                状态 = 解析扫码状态(json.loads(await 响应.text()))

            if 状态["授权码"]:
                await 完成(状态["授权码"])
                return
            if 状态["终态"]:
                raise RuntimeError(
                    "二维码已失效，请重新发 /绑定"
                    if 状态["状态"] == "过期"
                    else "扫码被取消，请重新发 /绑定"
                )
            await asyncio.sleep(_轮询间隔秒)

        raise TimeoutError("扫码超时，请重新发 /绑定")

    async def 关闭(self) -> None:
        if self._http is not None and not self._http.closed:
            await self._http.close()
