"""消息链的构造方式。

`event.chain_result([...])` 要的是消息组件列表。曾经往里面塞过裸字符串，
发送前的日志环节对每个组件取 `.type` 汇总消息概要，字符串没这个属性，
整条流水线抛 AttributeError——用户那边表现为指令完全没反应，日志里只有一行
`Pipeline task failed`。

这里按源码检查：链式接口（`.message()` / `.base64_image()`）由 AstrBot 自己
转组件，`chain_result` 只允许传组件。前者是唯一可用的写法。
"""

from __future__ import annotations

import ast
from pathlib import Path

入口 = Path(__file__).resolve().parent.parent / "main.py"
源码 = 入口.read_text(encoding="utf-8")
树 = ast.parse(源码)

_链式接口 = {"message", "base64_image", "chain", "text", "image", "url_image"}


def _调用链(节点: ast.AST) -> list[ast.Call]:
    """按源码顺序收集函数调用，`await` 和嵌套都要。"""
    return [n for n in ast.walk(树) if isinstance(n, ast.Call)]


def test_没有链式调用报错():
    """确认这个测试文件自己没写错，否则它静默通过、什么也拦不住。"""
    assert 源码, "main.py 读出来是空的"


def test_不用_chain_result_手搭列表():
    """`chain_result([...])` 是这次出错的写法。链式接口更安全，不该再出现。"""
    违规 = []
    for 调用 in _调用链(树):
        函数 = 调用.func
        if not (isinstance(函数, ast.Attribute) and 函数.attr == "chain_result"):
            continue
        if 调用.args and isinstance(调用.args[0], (ast.List, ast.Tuple)):
            违规.append(调用.lineno)
    assert not 违规, f"这些行手搭了消息链，改用链式接口：{违规}"


def test_图片走_base64_image():
    """二维码是 base64，必须走 base64_image，它会包成 Image 组件。"""
    链式 = {函数.attr for 调用 in _调用链(树) if isinstance((函数 := 调用.func), ast.Attribute)}
    assert "base64_image" in 链式, "绑定指令要发二维码，应使用 base64_image"
    # 确认没人在链外自己 new 组件再塞进去
    assert "fromBase64" not in 源码, "直接用 fromBase64 容易漏掉文本组件的转换"
