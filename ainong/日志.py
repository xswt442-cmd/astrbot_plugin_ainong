"""给不 import astrbot 的模块用的日志出口。

插件规范要求 logger **只能从 `astrbot.api` 取**，不许用 Python 内置 `logging`。
而 `ainong/auth/` 刻意不 import astrbot——本地 pytest 要能直接跑它们，没有这个包。
两边都要满足，所以由 `main.py` 在启动时把框架 logger 挂进来，这里只留一个出口。

爱瓦的 `aiva/transport.py` 是同一套做法，理由写在那边：模块保持 astrbot 无关，
日志又能进插件日志。**别拆**——拆掉之后「扫完了却绑不上」这类问题就没有线索了。

没挂钩子时静默丢弃，本地单测就是这种情况。
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["挂日志", "记"]

# 钩子签名：(级别, 一句)。级别用 logger 自己的方法名，warning / error 两种够用。
_钩子: Callable[[str, str], None] | None = None


def 挂日志(钩子: Callable[[str, str], None] | None) -> None:
    """挂一个日志函数进来。`main.py` 启动时调一次。"""
    global _钩子
    _钩子 = 钩子


def 记(级别: str, 一句: str) -> None:
    """写一条日志。没挂钩子时什么也不做。"""
    if _钩子 is not None:
        _钩子(级别, 一句)
