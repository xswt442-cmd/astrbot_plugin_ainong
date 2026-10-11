"""营地请求的频率控制。

营地对账号维度限流，参考实现记录的实测数值：最小请求间隔 1200ms、
超时 10 秒、普通网络错误重试 2 次并指数退避、命中频控后冷却 12 小时。

这些是经验值不是腾讯公布的限额，但冷却时长这个量级说明一件事：不能靠
重试碰运气。冷却期间再发请求会把冷却重新计时，所以冷却中的账号要直接
跳过，换下一个可用账号。

账号维度隔离：一个号被频控不影响其他号。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

__all__ = ["冷却已过", "频控闸", "账号频控闸"]

_最小间隔秒 = 1.2
_冷却秒 = 12 * 3600


def 冷却已过(起算时刻: float, 冷却秒: float) -> float:
    """从起算时刻算出的冷却到期时刻。"""
    return 起算时刻 + 冷却秒


@dataclass
class 账号频控闸:
    """单个营地账号的请求闸。"""

    最小间隔秒: float = _最小间隔秒
    冷却秒: float = _冷却秒
    _上次发出: float | None = field(default=None, init=False)
    _冷却到: float = field(default=0.0, init=False)

    def 可以发(self) -> bool:
        if self.冷却中():
            return False
        return not self._需等待()

    def 记录发出(self) -> None:
        """记一次请求。

        已经发出过、还在间隔里的请求不再重置计时：那会把间隔一直往后推，
        让密集调用方永远过不去。冷却期间同样不记。
        """
        if self.冷却中() or self._需等待():
            return
        self._上次发出 = time.monotonic()

    def 记频控(self) -> None:
        self._冷却到 = time.monotonic() + self.冷却秒

    def 冷却中(self) -> bool:
        return time.monotonic() < self._冷却到

    def 冷却剩余(self) -> float:
        return max(0.0, self._冷却到 - time.monotonic())

    def 还需等待(self) -> float:
        """距下次可发请求还需多少秒。"""
        if self._上次发出 is None:
            return 0.0
        return max(0.0, self._上次发出 + self.最小间隔秒 - time.monotonic())

    def _需等待(self) -> bool:
        return self.还需等待() > 0

    def 可读提示(self) -> str:
        """给用户看的说明。不含账号标识——那是凭据的一部分。"""
        if self.冷却中():
            小时 = self.冷却剩余() / 3600
            return f"这个营地账号正在限流冷却中，约{小时:.1f} 小时后再试"
        if self._需等待():
            return f"请求太频繁，{self.还需等待():.1f} 秒后再试"
        return "可以请求"


class 频控闸:
    """按账号维度管理的请求闸集合。"""

    def __init__(
        self,
        最小间隔秒: float = _最小间隔秒,
        冷却秒: float = _冷却秒,
    ) -> None:
        self._最小间隔秒 = 最小间隔秒
        self._冷却秒 = 冷却秒
        self._各账号: dict[str, 账号频控闸] = {}

    def 取账号闸(self, 账号标识: str) -> 账号频控闸:
        闸 = self._各账号.get(账号标识)
        if 闸 is None:
            闸 = 账号频控闸(最小间隔秒=self._最小间隔秒, 冷却秒=self._冷却秒)
            self._各账号[账号标识] = 闸
        return 闸

    def 可用账号(self, 账号标识s: list[str]) -> str | None:
        """返回第一个不在冷却的账号。全在冷却时返回 None。"""
        for 标识 in 账号标识s:
            if self.取账号闸(标识).可以发():
                return 标识
        return None
