"""通过 Playwright 服务操作浏览器。

AstrBot 容器不装浏览器，扫码登录交给独立的浏览器服务。这里用 Playwright
自带的 WebSocket 协议连接它，浏览器生命周期由本进程控制，退出时全部释放。

playwright 只在 `qq-verify` 依赖组里，装了这条才可用。所以 import 放在
`浏览器会话.__aenter__` 里而不是模块顶层：没装 playwright 的环境下插件照常
加载，微信那条路也不受影响，只有 QQ 扫码会明确报「没装 playwright」。

两个实测得到的行为，不处理就会失败：

1. QQ 把 `auth://tauth.qq.com/` 回调改写成 `http://auth//tauth.qq.com/?code=...`，
   这个主机名不存在。必须拦截并中止，否则浏览器会去解析一个不存在的域名。
2. 深链接不触发普通 HTTP 请求，只轮询页面 URL 会漏掉授权码。要同时监听
   导航事件和网络请求。
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

__all__ = ["浏览器会话", "playwright_可用"]

_回调路由 = "http://auth//tauth.qq.com/**"
_导航超时毫秒 = 45000


def playwright_可用() -> bool:
    """playwright 装了没。没装只有 QQ 扫码不可用，其余功能正常。"""
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class 浏览器会话:
    """一个独占的浏览器上下文。退出时释放全部资源。"""

    服务地址: str
    手机UA: str
    二维码路径: str = ""
    _pw: Any = None
    _上下文: Any = None
    页面: Any = None
    _授权码: str | None = field(default=None, init=False)
    _找二维码: Any = None

    async def __aenter__(self) -> 浏览器会话:
        # 延迟到真正要用浏览器时才 import playwright。没装的环境下插件照常
        # 加载，微信那条路也不受影响。
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "QQ 扫码登录需要 playwright，但没装。"
                "装它：uv sync --group qq-verify，或在容器里 pip install playwright。"
                "只用微信绑定的话用不到这个功能。"
            ) from exc

        from .selectors import 找二维码图片元素

        self._找二维码 = 找二维码图片元素
        self._pw = await async_playwright().start()
        浏览器 = await self._pw.chromium.connect(self.服务地址)
        self._上下文 = await 浏览器.new_context(
            user_agent=self.手机UA,
            viewport={"width": 420, "height": 760},
            is_mobile=True,
        )
        self._上下文.on("request", lambda r: self._记录(r.url))

        async def _截获(route: Any) -> None:
            self._记录(route.request.url)
            await route.abort()

        await self._上下文.route(_回调路由, _截获)
        await self._新页面()
        return self

    async def _新页面(self) -> None:
        """开一个页面并挂上授权码捕获。

        每次换二维码都换新页面：授权页带自动刷新参数，旧页面上的元素随时
        会被替换掉，继续用它取图不可靠。
        """
        self.页面 = await self._上下文.new_page()

        cdp = await self._上下文.new_cdp_session(self.页面)
        await cdp.send("Page.enable")
        cdp.on(
            "Page.frameRequestedNavigation",
            lambda e: self._记录(e.get("url", "")),
        )
        cdp.on("Page.windowOpen", lambda e: self._记录(e.get("url", "")))
        self.页面.on("framenavigated", lambda f: self._记录(f.url))

    async def 换页重开(self, url: str) -> None:
        """丢掉旧页面，用新页面重新打开授权页。"""
        旧页面 = self.页面
        self._授权码 = None
        await self._新页面()
        if 旧页面 is not None:
            await 旧页面.close()
        响应 = await self.页面.goto(url, wait_until="domcontentloaded", timeout=_导航超时毫秒)
        if 响应 is not None and not 响应.ok:
            raise RuntimeError(f"授权页返回 HTTP {响应.status}")

    async def __aexit__(self, *exc: object) -> None:
        if self._上下文 is not None:
            await self._上下文.close()
        if self._pw is not None:
            await self._pw.stop()

    def 重置授权码(self) -> None:
        """清掉上一轮可能带回来的授权码。"""
        self._授权码 = None

    def _记录(self, url: str) -> None:
        if self._授权码 or not url or "code=" not in url:
            return
        值 = parse_qs(urlparse(url).query).get("code", [None])[0]
        if 值:
            self._授权码 = 值

    async def 打开(self, url: str) -> None:
        响应 = await self.页面.goto(url, wait_until="domcontentloaded", timeout=_导航超时毫秒)
        if 响应 is not None and not 响应.ok:
            raise RuntimeError(f"授权页返回 HTTP {响应.status}")

    @property
    def 已获授权码(self) -> str | None:
        return self._授权码

    async def 取二维码(self) -> str:
        """取当前授权页的二维码，同时存到约定路径。

        授权页带自动刷新参数，元素随时可能在截图前被替换掉。
        所以整个查找过程重试几轮，而不是遇到一次失败就放弃。
        """
        import asyncio

        if self._找二维码 is None:
            raise RuntimeError("浏览器会话还没启动")

        最后异常: Exception | None = None
        for _ in range(3):
            try:
                元素 = await self._找二维码(self.页面)
                if 元素 is None:
                    raise RuntimeError("授权页已打开，但二维码没有加载出来")
                数据 = await 元素.screenshot(type="png", timeout=5000)
            except Exception as exc:
                最后异常 = exc
                await asyncio.sleep(1)
                continue

            if self.二维码路径:
                with open(self.二维码路径, "wb") as f:
                    f.write(数据)
            return base64.b64encode(数据).decode("ascii")

        raise RuntimeError(f"取二维码失败：{最后异常}")


async def 等待授权码(会话: 浏览器会话, 超时秒: int, 间隔秒: int) -> str:
    import asyncio
    import time

    截止 = time.monotonic() + 超时秒
    while time.monotonic() < 截止:
        if 会话.已获授权码:
            return 会话.已获授权码
        await asyncio.sleep(间隔秒)
    raise TimeoutError(f"{超时秒} 秒内没有等到扫码完成")


def 保存二维码(图片: str, 目录: str | None = None) -> str:
    路径 = os.path.join(目录 or os.environ.get("TMP", "."), "ainong_qq_qr.png")
    with open(路径, "wb") as f:
        f.write(base64.b64decode(图片))
    return 路径
