"""授权页上的二维码元素查找。

QQ 授权页的二维码有多个历史版本，元素标识不一致，且可能出现在子框架中。
"""

from __future__ import annotations

from typing import Any

__all__ = ["找二维码图片元素"]

选择器候选 = (
    "#qrlogin_img",
    ".qrlogin_img",
    'img[src*="ptqrshow"]',
    'img[src*="qrcode"]',
    "canvas#qrlogin_canvas",
    ".qrlogin canvas",
)

_最小边长 = 40
_单次等待毫秒 = 400
_总等待秒 = 40


async def 找二维码图片元素(页面: Any):
    """在所有框架中查找二维码元素，找不到返回 None。"""
    import asyncio
    import time

    截止 = time.monotonic() + _总等待秒
    while time.monotonic() < 截止:
        for 框架 in 页面.frames:
            for 选择器 in 选择器候选:
                定位 = 框架.locator(选择器).first
                try:
                    盒 = await 定位.bounding_box(timeout=_单次等待毫秒)
                    if (
                        盒
                        and 盒["width"] > _最小边长
                        and 盒["height"] > _最小边长
                        and await 定位.is_visible()
                    ):
                        return 定位
                except Exception:
                    # 不同页面版本可能不含当前选择器，继续试下一个。
                    continue
        await asyncio.sleep(0.5)
    return None
