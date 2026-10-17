"""战绩统计。

把营地接口的原始场次数据折成能直接交给模型的结论：打什么模式、什么段位、
常用哪些英雄、近期的表现。输出是紧凑文本而不是 JSON——模型读文本更省
token，也更容易从中得出有话说的评价。
"""

from __future__ import annotations

import json
import random
import re
from typing import Any

__all__ = [
    "拉英雄表",
    "映射英雄名",
    "统计战绩",
    "汇总文本",
    "走势文本",
    "对比要点",
    "对比文本",
    "占优项数",
    "抽对局结果",
]

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

    from .日志 import 记

    try:
        async with aiohttp.ClientSession() as 会话:
            async with 会话.get(_英雄表地址) as 响应:
                响应.raise_for_status()
                条目 = json.loads(await 响应.text())
    except Exception as exc:  # noqa: BLE001 - 拿不到就用编号，不影响查战绩
        # 以前这里是裸 `return {}`，失败完全静默。审核把「静默请求未声明的域名」
        # 视为隐藏网络访问，所以至少留一条 warning。
        记("warning", f"英雄名对照表拉取失败，退回显示编号：{type(exc).__name__}: {exc}")
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


def _可选数(场: dict[str, Any], *键名: str) -> float | None:
    """按候选键名依次取一个数，全都没有时返回 None。

    同一份数据在不同接口版本里键名不一致（`mvp` / `mvpcnt`、`gold` / `coin`），
    按候选列表试比写死一个稳。取不到就还 None——上层据此决定这一项显不显示，
    而不是拿 0 冒充「这项数据是 0」。
    """
    for 键 in 键名:
        值 = 场.get(键)
        if 值 is None or 值 == "":
            continue
        try:
            return float(值)
        except (TypeError, ValueError):
            continue
    return None


def _巅峰分(场次: list[dict[str, Any]]) -> float | None:
    """最新一个「有效」的巅峰分，没有巅峰赛场次时返回 None。

    列表接口每场都带 `newMasterMatchScore`，没打过巅峰赛的号全是 1200（巅峰赛
    初始分）。照着直接显示，等于告诉模型「这人巅峰 1200」，而事实是他没打过。
    """
    巅峰场 = [场 for 场 in 场次 if "巅峰" in str(场.get("mapName") or "")]
    if not 巅峰场:
        return None
    值 = _最新有值(巅峰场, "newMasterMatchScore", "masterMatchScore")
    if 值 is None or 值 == _巅峰赛初始分:
        return None
    return 值


def _走势(场次: list[dict[str, Any]], 场数: int = 10) -> list[bool]:
    """最近 N 场的胜负，最新在前。"""
    return [_胜(场) for 场 in 场次[:场数]]


def 走势文本(序列: list[bool]) -> str:
    """胜负序列折成一行字，如「胜胜负负胜」。"""
    return "".join("胜" if 胜 else "负" for 胜 in 序列)


def _最长连胜(场次: list[dict[str, Any]]) -> int:
    最长 = 当前 = 0
    for 场 in 场次:
        if _胜(场):
            当前 += 1
            最长 = max(最长, 当前)
        else:
            当前 = 0
    return 最长


def _最新有值(场次: list[dict[str, Any]], *键名: str) -> float | None:
    """取最新一场里这几个键的值（场次是最新在前）。"""
    for 场 in 场次:
        值 = _可选数(场, *键名)
        if 值 is not None:
            return 值
    return None


# 奖牌图标地址里就带着等级与职业，如 `…/evaluateV3/silver_archer.png`。
# 这是实测出来的：40 场里金牌 12、银牌 18，职业词是 warrior/mage/assassin/archer/tank。
_奖牌图 = re.compile(r"/(gold|silver|bronze)_([a-z]+)")

_奖牌等级 = {"gold": "金牌", "silver": "银牌", "bronze": "铜牌"}
_职业名 = {
    "warrior": "战士",
    "mage": "法师",
    "assassin": "刺客",
    "archer": "射手",
    "shooter": "射手",
    "tank": "坦克",
    "support": "辅助",
}


def _奖牌(场: dict[str, Any]) -> tuple[str, str] | None:
    """从奖牌图地址里解出 (等级, 职业)。没有奖牌返回 None。"""
    地址 = str(场.get("evaluateUrl") or 场.get("evaluateUrlV2") or "")
    命中 = _奖牌图.search(地址)
    if not 命中:
        return None
    等级 = _奖牌等级.get(命中.group(1))
    if not 等级:
        return None
    return 等级, _职业名.get(命中.group(2), 命中.group(2))


def _标记数(场次: list[dict[str, Any]], 键名: str) -> int:
    """数一数有多少场带这个 0/1 标记。"""
    return sum(1 for 场 in 场次 if int(场.get(键名, 0) or 0))


# 巅峰赛分数。列表接口每场都带 newMasterMatchScore，没打过巅峰赛的号全是 1200
# （巅峰赛初始分），直接显示会把「没打过」说成「1200 分」。
_巅峰赛初始分 = 1200.0


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
            "KDA": 0.0,
            "mvp次数": 0,
            "svp次数": 0,
            "平均评分": 0.0,
            "平均时长分钟": 0.0,
            "模式分布": [],
            "常用英雄": [],
            "当前连胜": 0,
            "当前连败": 0,
            "最长连胜": 0,
            "最近走势": [],
            "走势文本": "",
            "奖牌": {},
            "奖牌位置": [],
            "高光": {},
            "局内评价": [],
            "星数": None,
            "巅峰分": None,
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

    # 场均 KDA 与各项均值。死亡为 0 时按击杀+助攻计，不写成无穷大——
    # 文本里出现「inf」比数字不好看，语义上也是「没死过，KDA 拉满」。
    击杀 = _平均(场次, "killcnt")
    死亡 = _平均(场次, "deadcnt")
    助攻 = _平均(场次, "assistcnt")
    kda = (击杀 + 助攻) / 死亡 if 死亡 else 击杀 + 助攻

    平均时长分 = _平均(场次, "usedTime") / 60

    走势 = _走势(场次)
    mvp次数 = _标记数(场次, "mvpcnt")

    # 奖牌：等级计数 + 拿奖最多的职业。
    奖牌计数: dict[str, int] = {}
    职业计数: dict[str, int] = {}
    for 场 in 场次:
        结果 = _奖牌(场)
        if 结果 is None:
            continue
        奖牌计数[结果[0]] = 奖牌计数.get(结果[0], 0) + 1
        职业计数[结果[1]] = 职业计数.get(结果[1], 0) + 1

    return {
        "总场次": 总数,
        "胜场": 胜场数,
        "负场": 总数 - 胜场数,
        "胜率": _取整(胜场数 / 总数 * 100),
        "平均击杀": _取整(击杀),
        "平均死亡": _取整(死亡),
        "平均助攻": _取整(助攻),
        "KDA": _取整(kda),
        "mvp次数": mvp次数,
        # 败方 MVP 就是 SVP，字段是 losemvp。别按名字猜成 svp。
        "svp次数": _标记数(场次, "losemvp"),
        "平均评分": _取整(_平均(场次, "gradeGame")),
        "平均时长分钟": _取整(平均时长分),
        "模式分布": _分布(场次, lambda 场: 场.get("mapName", "")),
        "常用英雄": 英雄统计[:_常用英雄上限],
        "当前连胜": 连胜,
        "当前连败": 连败,
        "最长连胜": _最长连胜(场次),
        "最近走势": 走势,
        "走势文本": 走势文本(走势),
        "奖牌": 奖牌计数,
        "奖牌位置": sorted(职业计数.items(), key=lambda kv: -kv[1]),
        "高光": {
            "一血": _标记数(场次, "firstBlood"),
            "超神": _标记数(场次, "godLikeCnt"),
            "三杀": _标记数(场次, "hero1TripleKillCnt"),
            "四杀": _标记数(场次, "hero1UltraKillCnt"),
        },
        "局内评价": [(名, 数) for 名, 数 in _分布(场次, lambda 场: 场.get("desc") or "") if 名],
        # 段位星数只看最新一场（场次倒序），比拿全期平均更贴近「现在」。
        "星数": _最新有值(场次, "stars"),
        "巅峰分": _巅峰分(场次),
    }


def 汇总文本(统计: dict[str, Any], *, 段位: str = "", 巅峰分: str = "") -> str:
    """把统计折成给模型读的紧凑文本。

    带不出值的维度直接不出现——营地接口各版本字段不一致，缺字段时宁可不写，
    也不要拿 0 充数让模型以为「这项是 0」。
    """
    if not 统计["总场次"]:
        return "这个角色还没有可查的近期战绩。"

    行 = []

    段 = 段位 or "未定级"
    if 统计.get("星数"):
        段 += f" {int(统计['星数'])}星"
    头部 = [f"段位 {段}"]
    分 = 巅峰分 or (f"{int(统计['巅峰分'])}" if 统计.get("巅峰分") else "")
    if 分:
        头部.append(f"巅峰分 {分}")
    头部.append(f"近{统计['总场次']}场 {统计['胜场']}胜{统计['负场']}负")
    头部.append(f"胜率 {统计['胜率']}%")
    行.append(" ｜ ".join(头部))

    模式项 = [f"{名}{数}场" for 名, 数 in 统计["模式分布"][:3]]
    其余 = sum(数 for _, 数 in 统计["模式分布"][3:])
    if 其余:
        模式项.append(f"其他{其余}场")
    if 模式项:
        行.append(f"模式：{'、'.join(模式项)}")

    英雄 = "、".join(f"{名} {数}场 {胜率}%" for 名, 数, 胜率 in 统计["常用英雄"])
    if 英雄:
        行.append(f"常用英雄：{英雄}")

    行.append(
        f"场均 {统计['平均击杀']}/{统计['平均死亡']}/{统计['平均助攻']}"
        f"（击杀/死亡/助攻），KDA {统计['KDA']}，平均评分 {统计['平均评分']}，"
        f"平均时长 {统计['平均时长分钟']}分钟"
    )

    if 统计["mvp次数"] or 统计.get("svp次数"):
        荣誉 = []
        # 场次够多时带上占比，一两次 MVP 在长样本里和短样本里含义完全不同。
        if 统计["mvp次数"]:
            占比 = f"（{_取整(统计['mvp次数'] / 统计['总场次'] * 100)}%）"
            荣誉.append(f"MVP {统计['mvp次数']} 次{占比 if 统计['总场次'] >= 10 else ''}")
        if 统计.get("svp次数"):
            荣誉.append(f"SVP {统计['svp次数']} 次")
        行.append("、".join(荣誉))

    if 统计.get("走势文本"):
        行.append(f"最近 {min(统计['总场次'], 10)} 场：{统计['走势文本']}")

    # 最长连胜与当前连胜一样时就别重复报一遍，只在这种「以前也连胜过」的
    # 情况下才有单独说的价值。
    当前连续 = max(统计["当前连胜"], 统计["当前连败"])
    if 统计.get("最长连胜", 0) >= 3 and 统计["最长连胜"] > 当前连续:
        行.append(f"最长连胜 {统计['最长连胜']} 场")

    if 统计["当前连胜"] >= 2:
        行.append(f"当前连胜 {统计['当前连胜']} 场")
    elif 统计["当前连败"] >= 2:
        行.append(f"当前连败 {统计['当前连败']} 场")

    奖牌 = 统计.get("奖牌") or {}
    if 奖牌:
        块 = [f"{等级} {奖牌[等级]} 次" for 等级 in ("金牌", "银牌", "铜牌") if 奖牌.get(等级)]
        位置 = 统计.get("奖牌位置") or []
        if 位置:
            块.append(f"多在{位置[0][0]}位")
        if 块:
            行.append("奖牌：" + "、".join(块))

    高光 = [f"{名} {数} 次" for 名, 数 in (统计.get("高光") or {}).items() if 数]
    if 高光:
        行.append("高光：" + "、".join(高光))

    评价 = [f"{名} {数} 场" for 名, 数 in (统计.get("局内评价") or [])[:4]]
    if 评价:
        行.append("局内评价：" + "、".join(评价))

    return "\n".join(行)


def 对比要点(甲名: str, 甲: dict[str, Any], 乙名: str, 乙: dict[str, Any]) -> list[dict[str, str]]:
    """逐项比出高低。

    返回 `[{"项": ..., "甲": ..., "乙": ..., "优": "甲" | "乙" | "持平"}]`。

    对比**由代码算死，不交给模型**：让模型自己比，它最省事的答案就是「各有千秋」
    这类端水话——实测 PK 出来就是 83 对 87 这种看不出输赢的分数。每项都算清
    谁占优、双方数字多少，模型的活只剩解说，端水就没地方藏。
    """
    要点: list[dict[str, str]] = []

    # 有一方没场次就不比。空统计里各项都是 0，逐项比下来会得到一串「持平」，
    # 看着像「两人打得一样好」，其实是「没数据」。
    if not 甲.get("总场次") or not 乙.get("总场次"):
        return 要点

    def 一项(
        标题: str,
        甲值: float | None,
        乙值: float | None,
        *,
        越小越好: bool = False,
        单位: str = "",
        位数: int = 1,
    ) -> None:
        if 甲值 is None or 乙值 is None:
            return
        模板 = f"{{:.{位数}f}}"
        甲文 = 模板.format(甲值) + 单位
        乙文 = 模板.format(乙值) + 单位
        if 甲值 == 乙值:
            优 = "持平"
        else:
            甲赢 = 甲值 < 乙值 if 越小越好 else 甲值 > 乙值
            优 = "甲" if 甲赢 else "乙"
        要点.append({"项": 标题, "甲": 甲文, "乙": 乙文, "优": 优})

    一项("胜率", 甲.get("胜率"), 乙.get("胜率"), 单位="%")
    一项("KDA", 甲.get("KDA"), 乙.get("KDA"))
    一项("平均评分", 甲.get("平均评分"), 乙.get("平均评分"))
    一项("MVP 次数", 甲.get("mvp次数"), 乙.get("mvp次数"), 单位=" 次", 位数=0)
    一项("场均击杀", 甲.get("平均击杀"), 乙.get("平均击杀"))
    一项("场均死亡", 甲.get("平均死亡"), 乙.get("平均死亡"), 越小越好=True)
    一项(
        "最近 10 场胜场",
        float(sum(甲.get("最近走势") or [])),
        float(sum(乙.get("最近走势") or [])),
        单位=" 胜",
        位数=0,
    )
    return 要点


def 对比文本(要点: list[dict[str, str]], 甲名: str, 乙名: str) -> str:
    """把对比要点折成给模型读的文本。每一行都直接说明谁占优。"""
    行 = []
    for 条 in 要点:
        if 条["优"] == "持平":
            行.append(f"{条['项']}：持平（{甲名} {条['甲']} / {乙名} {条['乙']}）")
        else:
            优名 = 甲名 if 条["优"] == "甲" else 乙名
            行.append(f"{条['项']}：{优名}占优（{甲名} {条['甲']} / {乙名} {条['乙']}）")
    return "\n".join(行)


def 占优项数(要点: list[dict[str, str]], 甲名: str, 乙名: str) -> str:
    """「asd 5 项、老王 2 项」这样的汇总，写进提示里当参考。

    刻意**不**把它写成「占优多的一方必须赢」：项数是机械数出来的，而实际谁更强
    要看是哪几项——输赢判断留给模型，这里只提供事实。
    """
    甲 = sum(1 for 条 in 要点 if 条["优"] == "甲")
    乙 = sum(1 for 条 in 要点 if 条["优"] == "乙")
    return f"{甲名} {甲} 项、{乙名} {乙} 项"


def 抽对局结果(统计: dict[str, Any], rng: Any = None) -> str:
    """按真实胜率抽这一局的胜负，返回「胜利」或「失败」。

    胜负不交给模型定：模型没有随机性，连开十局会给十次「超神带飞」，而一个
    45% 胜率的号不该这样。按他自己的胜率抽，既对得上水平又有变化。

    没有场次时按五成算；概率收到 0.1~0.9，免得出现「必赢」或「必输」。
    """
    随机 = rng or random
    胜率 = float(统计.get("胜率") or 0) if 统计.get("总场次") else 50.0
    概率 = min(max(胜率 / 100, 0.1), 0.9)
    return "胜利" if 随机.random() < 概率 else "失败"
