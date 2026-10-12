"""PK 目标解析。

这块的坑全在「从哪拿到对手标识」上：群里 @ 一个人，多数平台给的是消息组件，
而 QQ 官方平台的适配器只把「@机器人」转成组件，@别人会原样留在正文里
（见 qqofficial_platform_adapter 的消息组装）。两条路都得走通。
"""

from __future__ import annotations

from ainong.pk import 找对手

群里甲 = "6D3ECFCFEE847D22127AFEB5D8ABA171"
群里乙 = "2A8FDBA44C38D5B4863B0F49D76E744E"


class 假At:
    def __init__(self, qq) -> None:
        self.qq = qq


class 假Plain:
    """正文组件没有 qq 属性，不该被误当成提及。"""

    text = "PK"


class Test从组件里找:
    def test_拿到_At_的_qq(self):
        assert 找对手([假At(群里甲)], "") == 群里甲

    def test_数字_qq_也接(self):
        assert 找对手([假At(123456789)], "") == "123456789"

    def test_没有_qq_属性的组件跳过(self):
        assert 找对手([假Plain(), 假At(群里甲)], "") == 群里甲

    def test_组件优先于正文(self):
        assert 找对手([假At(群里甲)], f"<@!{群里乙}>") == 群里甲


class Test从正文里找:
    def test_抠出_QQ_官方的提及原文(self):
        """@别人在 QQ 官方平台就是一段纯文本，只能从这儿抠。"""
        assert 找对手([], f"PK <@!{群里甲}>") == 群里甲

    def test_不带头叹号的写法也认(self):
        assert 找对手([], f"PK <@{群里甲}>") == 群里甲

    def test_太短的提及不当标识(self):
        assert 找对手([], "PK <@1>") is None

    def test_正文直接是标识(self):
        assert 找对手([], f" {群里甲} ") == 群里甲

    def test_正文是中文昵称时不乱认(self):
        assert 找对手([], "PK 小明") is None

    def test_空正文返回_None(self):
        assert 找对手([], "") is None
        assert 找对手([], None) is None


class Test要排掉的:
    def test_排掉机器人自己(self):
        """群里 @机器人 也会生成 At 组件，不排掉就会拿机器人当 PK 对象。"""
        机器人 = "BOTIDENTITY1234567890AAAA"
        对手 = 找对手([假At(机器人)], f"<@!{机器人}> PK <@!{群里甲}>", 机器人=机器人)
        assert 对手 == 群里甲

    def test_排掉发起者自己(self):
        assert 找对手([], f"<@!{群里甲}>", 自己=群里甲) is None

    def test_排掉_qq_official_这类占位(self):
        assert 找对手([假At("qq_official")], "") is None
        assert 找对手([假At("all")], "") is None
        assert 找对手([假At("unknown_selfid")], "") is None

    def test_排掉后还能找到后面那个(self):
        assert 找对手([假At("qq_official"), 假At(群里甲)], "") == 群里甲
