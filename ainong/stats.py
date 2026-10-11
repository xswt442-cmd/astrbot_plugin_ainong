"""战绩统计。

把营地接口的原始场次数据折成能直接交给模型的结论：打什么模式、什么段位、
常用哪些英雄、近期的表现。输出是紧凑文本而不是 JSON——模型读文本更省
token，也更容易从中得出有话说的评价。
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["拉英雄表", "映射英雄名", "统计战绩", "汇总文本"]

_英雄表地址 = "https://pvp.qq.com/web201605/js/herolist.json"

_常用英雄上限 = 5
_保留一位小数 = 1

_英雄表缓存: dict[int, str] | None = None


async def 拉英雄表() -> dict[int, str]:
    """取官方英雄编号到中文名的对照表。

    战绩接口只给英雄编号不给名字，模型看到数字没法判断，所以要映射。
    这张表是公开静态资源，取一次缓存在进程内。
    """
    global _英雄表缓存
    if _英雄表缓存 is not None:
        return _英雄表缓存

    import aiohttp

    try:
        async with aiohttp.ClientSession() as 会话:
            async with 会话.get(_英雄表地址) as 响应:
                响应.raise_for_status()
                条目 = json.loads(await 响应.text())
    except Exception:
        return {}

    _英雄表缓存 = {int(项["ename"]): str(项["cname"]) for 项 in 条目 if "ename" in 项}
    return _英雄表缓存


def 映射英雄名(场次: list[dict[str, Any]], 表: dict[int, str] | None = None) -> list[dict]:
    """给场次补上英雄名。查不到时保持原样，编号仍然可用。"""
    表 = 表 or {}
    结果 = []
    for 场 in 场次:
        新场 = dict(场)
        if not 新场.get("heroName"):
            名 = 表.get(int(新场["heroId"])) if 新场.get("heroId") else None
            if 名:
                新场["heroName"] = 名
        结果.append(新场)
    return 结果


def _胜(场: dict[str, Any]) -> bool:
    """接口里 gameresult 为1 是胜、2 是负。

    这个取值由真实响应统计确认：星耀段位 20 胜 10 负的账号，两者交叉后
    gameresult 稳定分成 20 与 10 两组，与段位相符。
    """
    return str(场.get("gameresult", "")) == "1"


def _英雄名(场: dict[str, Any]) -> str:
    """接口不返回英雄名，只有编号。这里用编号占位。"""
    名 = 场.get("heroName")
    if 名:
        return str(名)
    编号 = 场.get("heroId")
    return str(编号) if 编号 else "未知"


def _平均(场次: list[dict[str, Any]], 键: str) -> float:
    if not 场次:
        return 0.0
    return sum(float(场.get(键, 0) or 0) for 场 in 场次) / len(场次)


def _取整(值: float) -> float:
    return round(值, _保留一位小数)


def _分布(场次: list[dict[str, Any]], 取键) -> list[tuple[str, int]]:
    """按取键统计场次，降序返回 (名字, 场次数)。"""
    计数: dict[str, int] = {}
    for 场 in 场次:
        键 = str(取键(场))
        计数[键] = 计数.get(键, 0) + 1
    return sorted(计数.items(), key=lambda kv: -kv[1])


def 统计战绩(场次: list[dict[str, Any]]) -> dict[str, Any]:
    """把一场次列表折成统计结论。"""
    总数 = len(场次)
    if 总数 == 0:
        return {
            "总场次": 0,
            "胜场": 0,
            "负场": 0,
            "胜率": 0.0,
            "平均击杀": 0.0,
            "平均死亡": 0.0,
            "平均助攻": 0.0,
            "mvp次数": 0,
            "平均评分": 0.0,
            "平均时长分钟": 0.0,
            "模式分布": [],
            "常用英雄": [],
            "当前连胜": 0,
            "当前连败": 0,
        }

    胜场数 = sum(1 for 场 in 场次 if _胜(场))

    # 场次按时间倒序（最新在前），所以当前连胜要从头数连续同结果的场。
    连胜 = 0
    for 场 in 场次:
        if _胜(场):
            连胜 += 1
        else:
            break
    连败 = 0
    for 场 in 场次:
        if not _胜(场):
            连败 += 1
        else:
            break

    英雄分组: dict[str, list[dict[str, Any]]] = {}
    for 场 in 场次:
        英雄分组.setdefault(_英雄名(场), []).append(场)

    英雄统计 = sorted(
        (
            (
                名,
                len(组),
                _取整(sum(1 for 场 in 组 if _胜(场)) / len(组) * 100),
            )
            for 名, 组 in 英雄分组.items()
        ),
        key=lambda x: -x[1],
    )

    return {
        "总场次": 总数,
        "胜场": 胜场数,
        "负场": 总数 - 胜场数,
        "胜率": _取整(胜场数 / 总数 * 100),
        "平均击杀": _取整(_平均(场次, "killcnt")),
        "平均死亡": _取整(_平均(场次, "deadcnt")),
        "平均助攻": _取整(_平均(场次, "assistcnt")),
        "mvp次数": sum(int(场.get("mvpcnt", 0) or 0) for 场 in 场次),
        "平均评分": _取整(_平均(场次, "gradeGame")),
        "平均时长分钟": _取整(_平均(场次, "usedTime") / 60),
        "模式分布": _分布(场次, lambda 场: 场.get("mapName", "")),
        "常用英雄": 英雄统计[:_常用英雄上限],
        "当前连胜": 连胜,
        "当前连败": 连败,
    }


def 汇总文本(统计: dict[str, Any], *, 段位: str = "", 巅峰分: str = "") -> str:
    """把统计折成给模型读的紧凑文本。"""
    if not 统计["总场次"]:
        return "这个角色还没有可查的近期战绩。"

    行 = []
    头部 = [f"段位 {段位 or '未定级'}"]
    if 巅峰分:
        头部.append(f"巅峰分 {巅峰分}")
    头部.append(f"近{统计['总场次']}场 {统计['胜场']}胜{统计['负场']}负")
    头部.append(f"胜率 {统计['胜率']}%")
    行.append(" ｜ ".join(头部))

    模式 = "、".join(f"{名}{数}场" for 名, 数 in 统计["模式分布"][:3])
    if 模式:
        行.append(f"模式：{模式}")

    英雄 = "、".join(f"{名} {数}场 {胜率}%" for 名, 数, 胜率 in 统计["常用英雄"])
    if 英雄:
        行.append(f"常用英雄：{英雄}")

    数据 = (
        f"场均 {统计['平均击杀']}/{统计['平均死亡']}/{统计['平均助攻']}"
        f"（击杀/死亡/助攻），平均评分 {统计['平均评分']}，"
        f"平均时长 {统计['平均时长分钟']}分钟"
    )
    if 统计["mvp次数"]:
        数据 += f"，{统计['mvp次数']} 次 MVP"
    行.append(数据)

    if 统计["当前连胜"] >= 2:
        行.append(f"当前连胜 {统计['当前连胜']} 场")
    elif 统计["当前连败"] >= 2:
        行.append(f"当前连败 {统计['当前连败']} 场")

    return "\n".join(行)
