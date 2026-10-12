"""main.py 里几处顺序与接线约束。

这些规则本地跑不了——main.py 顶层 import astrbot，而开发环境没这个包，
装上又会把整个插件的依赖拖进测试环境。所以按源码检查。

**`_通知` 必须在 `_清理会话` 之前。** 通知依赖 `_事件` 与 `_会话标识`，
清理会把两者丢掉，顺序一反通知就发不出去。这个坑已经踩过一次：
`_扫码失败` 里先清理再通知，事件已被 pop，只能靠日志才发现。

`main.py` 的导入与指令注册也一并检查，避免同类问题再次溜过去。
"""

from __future__ import annotations

import ast
from pathlib import Path

入口 = Path(__file__).resolve().parent.parent / "main.py"
源码 = 入口.read_text(encoding="utf-8")
树 = ast.parse(源码)


def _方法节点(类名: str, 方法名: str):
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ClassDef) and 节点.name == 类名:
            for 项 in 节点.body:
                if isinstance(项, (ast.FunctionDef, ast.AsyncFunctionDef)) and 项.name == 方法名:
                    return 项
    raise AssertionError(f"main.py 里找不到 {类名}.{方法名}")


def _方法体(类名: str, 方法名: str) -> list[ast.stmt]:
    return _方法节点(类名, 方法名).body


def _方法源码(类名: str, 方法名: str) -> str:
    """整个方法的源码，含装饰器。

    只取 body[0] 会落到 docstring 上；嵌套函数的实现也在方法体内，所以要
    连函数定义一起取。
    """
    节点 = _方法节点(类名, 方法名)
    return ast.get_source_segment(源码, 节点) or ""


def _调用的方法(方法名: str) -> list[ast.Call]:
    """在某个方法体里找到对指定方法的调用，按顺序返回行号。"""
    行号 = []
    for 节点 in _方法体("Main", 方法名):
        for 子 in ast.walk(节点):
            if isinstance(子, ast.Call) and isinstance(子.func, ast.Attribute):
                if 子.func.attr == 方法名:
                    行号.append(子.lineno)
    return 行号


def test_入口能解析():
    assert 源码, "main.py 读出来是空的"


def test_通知在清理之前调用():
    """_通知 依赖 _事件 与 _会话标识，清理会 pop 掉它们。"""
    片段 = _方法源码("Main", "_收到授权码")
    最后一次通知 = 片段.rfind("_通知(")
    清理位置 = 片段.rfind("_清理会话(")
    assert 最后一次通知 != -1, "_收到授权码 里没有 _通知 调用"
    assert 清理位置 != -1, "_收到授权码 里没有 _清理会话 调用"
    assert 最后一次通知 < 清理位置, (
        "_收到授权码 里 _清理会话 出现在 _通知 之前，通知会被清掉的事件与标识"
    )


def test_扫码失败里也是先通知再清理():
    """_扫码失败 里的顺序同样关键，这里最容易写反。"""
    片段 = _方法源码("Main", "_扫码失败")
    通知 = 片段.rfind("_通知(")
    清理 = 片段.rfind("_清理会话(")
    assert 通知 != -1, "_扫码失败 里没有 _通知 调用"
    assert 清理 != -1, "_扫码失败 里没有 _清理会话 调用"
    assert 通知 < 清理, "_扫码失败 里先清理再通知，事件已被 pop，通知发不出去"


def test_清理会话清掉三样东西():
    """事件、会话标识、会话，三样都归它管。漏一样就会漏通知或泄漏对象。"""
    for 行 in _方法体("Main", "_清理会话"):
        if isinstance(行, ast.Expr) and isinstance(行.value, ast.Await):
            行 = 行.value.value
        if isinstance(行, ast.Call) and isinstance(行.func, ast.Attribute):
            if 行.func.attr == "pop" and isinstance(行.func.value, ast.Attribute):
                assert 行.func.value.attr in {"_事件", "_会话标识"}, (
                    f"_清理会话 里 pop 了 {行.func.value.attr}，只该清 _事件 与 _会话标识"
                )


def test_回调是单参协程():
    """等授权码 按单参调用回调，传双参进去就是 TypeError。"""
    片段 = _方法源码("Main", "_绑定")
    assert "def _完成(" in 片段, "绑定 里的回调应是只收一个参数的协程"
    assert "self._收到授权码(用户," in 片段, "回调里要把用户标识传下去"
    # 不能直接把双参方法当回调传出去
    assert "开始等待(self._收到授权码" not in 片段, (
        "别把 _收到授权码 直接当回调传，等授权码 只传一个参数"
    )


def test_有状态指令():
    """扫码过程用户看不到结果，需要能自己查。"""
    指令 = _指令集()
    assert {"绑定微信", "绑定QQ", "解绑", "战绩", "状态", "帮助"} <= 指令, (
        f"指令不全：{sorted(指令)}"
    )


def _指令集() -> set[str]:
    指令: set[str] = set()
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute):
            if 节点.func.attr == "command" and 节点.args:
                第一个 = 节点.args[0]
                if isinstance(第一个, ast.Constant) and isinstance(第一个.value, str):
                    指令.add(第一个.value)
    return 指令


def test_绑定有微信与_qq_两条():
    """两条授权路径是分开的：微信纯 HTTP，QQ 要浏览器侧车。

    别合成一个「绑定」再靠参数选——QQ 那条在侧车不可用时要给明确错误，
    合成一条就只能说「绑定失败」。
    """
    指令 = _指令集()
    assert "绑定微信" in 指令
    assert "绑定QQ" in 指令
    assert "绑定" not in 指令, "绑定应该拆成两条，别用一个入口混着选"


def test_绑定_保留旧指令_作别名():
    """老用户发 /爱农 绑定 不该突然失效——它是 绑定微信 的别名。"""
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.AsyncFunctionDef):
            continue
        if 节点.name not in ("绑定微信", "绑定QQ"):
            continue
        别名: set[str] = set()
        for 装饰器 in 节点.decorator_list:
            if isinstance(装饰器, ast.Call) and isinstance(装饰器.func, ast.Attribute):
                if 装饰器.func.attr != "command":
                    continue
                for 关键字 in 装饰器.keywords:
                    if 关键字.arg == "alias" and isinstance(关键字.value, ast.Set):
                        别名 = {
                            e.value
                            for e in 关键字.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        }
        assert "绑定" in 别名 or "绑定qq" in 别名, (
            f"{节点.name} 没有保留旧指令名作别名，会让老用户的 /爱农 绑定 失效"
        )


def test_侧车地址来自配置():
    """QQ 要连侧车，地址不能硬编码——部署时容器名可能不同。"""
    片段 = _方法源码("Main", "_侧车地址")
    assert "self.config.get" in 片段, "侧车地址应从配置读，不要写死"
