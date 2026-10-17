"""给不 import astrbot 的模块用的日志出口。

插件规范要求 logger **只能从 `astrbot.api` 取**，不许用 Python 内置 `logging`。
而 `ainong/auth/`、`ainong/camp/` 刻意不 import astrbot——本地 pytest 要能直接跑
它们，那个环境里没有这个包。所以这里分两层：

1. 运行期：`记()` 直接交给 `astrbot.api.logger`，框架按包名前缀路由到本插件
   自己的 logger（`astrbot.plugin.astrbot_plugin_ainong`）；
2. 本地单测（import 不到 astrbot）：退到 `挂日志()` 装的钩子，没钩子就丢弃。

**别改成内置 `logging`。** v0.1.14 就是因为 `auth/scan_session.py`、
`auth/qq_login.py` 里用了 `logging.getLogger` 被市场驳回的，规则只允许
`from astrbot.api import logger`。
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["挂日志", "记"]

try:  # 运行期走这条；本地单测 import 不到 astrbot，落到下面的钩子
    from astrbot.api import logger as _框架日志
except ImportError:  # pragma: no cover - 只在脱离 AstrBot 的测试环境
    _框架日志 = None

# 钩子签名：(级别, 一句)。级别用 logger 自己的方法名，warning / error 两种够用。
_钩子: Callable[[str, str], None] | None = None


def 挂日志(钩子: Callable[[str, str], None] | None) -> None:
    """挂一个日志函数进来。只有拿不到框架 logger 时才用它（本地单测）。"""
    global _钩子
    _钩子 = 钩子


def 记(级别: str, 一句: str) -> None:
    """写一条日志。既没有框架 logger 也没有钩子时丢弃。"""
    if _框架日志 is not None:
        getattr(_框架日志, 级别)(f"[ainong] {一句}")
        return
    if _钩子 is not None:
        _钩子(级别, 一句)
