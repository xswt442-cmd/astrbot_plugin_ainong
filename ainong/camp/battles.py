"""读战绩。

营地的战绩接口与角色列表不是一套：走JSON 请求体，需要一组固定参数，
响应加密后是游标翻页的结构。字段名以真实响应为准。

输出交给`ainong.stats` 折成模型可读的文本，这里只负责取数与翻页。
"""

from __future__ import annotations

from typing import Any

from ..stats import 汇总文本, 统计战绩

__all__ = ["读战绩", "读战绩摘要"]

营地主站 = "https://kohcamp.qq.com"

_每页场次 = 30
_最大页数 = 3
_翻页间隔秒 = 0.4


async def _请求场次(传输, 营地ID: str, 角色ID: str, 游标: int) -> dict[str, Any]:
    """取一页场次。

    这个接口用 JSON 请求体，与走表单的角色列表不是一套。实测不带
    `encodeParam` 签名也能通，所以这里不签。
    """
    请求头 = 传输._鉴权头(营地ID)
    请求头["Content-Type"] = "application/json; charset=UTF-8"

    载荷 = {
        "option": 0,
        "isMultiGame": 1,
        "apiVersion": 5,
        "lastTime": 游标,
        "recommendPrivacy": 0,
        "friendUserId": 营地ID,
    }
    if 角色ID:
        载荷["roleId"] = 角色ID

    import json

    async with 传输._http.post(
        f"{营地主站}/game/morebattlelist",
        headers=请求头,
        json=载荷,
    ) as 响应:
        文本 = await 响应.text()
        解密后 = 传输._解密响应(文本, 响应.headers)

    try:
        结果 = json.loads(解密后)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"战绩响应不是 JSON：{解密后[:200]}") from exc

    传输._检查业务码(结果)
    return 结果


async def 读战绩(传输, 角色ID: str = "", 页数: int = 1) -> list[dict[str, Any]]:
    """取近期场次。页数越多翻得越深，受接口游标限制。"""
    if 传输._账号 is None:
        raise RuntimeError("尚未登录营地账号")
    营地ID = 传输._账号["营地ID"]

    全部: list[dict[str, Any]] = []
    游标 = 0
    for 页 in range(min(页数, _最大页数)):
        载荷 = await _请求场次(传输, 营地ID, 角色ID, 游标)
        数据 = 载荷.get("data") or {}
        全部.extend(数据.get("list") or [])
        if not 数据.get("hasMore"):
            break
        新游标 = 数据.get("lastTime")
        if not 新游标 or 新游标 == 游标:
            break
        游标 = 新游标
        if 页 < 页数 - 1:
            import asyncio

            await asyncio.sleep(_翻页间隔秒)
    return 全部


async def 读战绩摘要(传输, 角色ID: str = "") -> str:
    """取近期战绩并折成模型可读的文本。"""
    场次 = await 读战绩(传输, 角色ID, 页数=2)
    统计 = 统计战绩(场次)

    段位 = ""
    巅峰分 = ""
    for 场 in 场次:
        if 场.get("roleJobName"):
            段位 = str(场["roleJobName"])
            break

    return 汇总文本(统计, 段位=段位, 巅峰分=巅峰分)
