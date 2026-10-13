"""指令落空时的兜底。

`/爱农 <任意内容>` 时，如果没有子命令匹配上，`CommandGroupFilter.filter`
会返回 False，指令被跳过，**消息原样进模型**。于是模型把它当成一句提问，
自己编答案——爱完美实测过：用户发一个 Steam 主页链接，模型回「打不开Steam，
你发链接干嘛」，还自称「我又没权限爬Steam」，它并不在查数据，它在编。

用户没打错指令，是这条指令没接住。所以组里要挂一个兜底过滤器：匹配了组名
但没匹配任何子命令时，自己回一句提示，不让消息落到模型手上。

这些测试不 import `main.py`（它顶层 import astrbot，本地跑不了），只测本模块
里的纯函数。
"""

from __future__ import annotations

import pytest

from ainong.兜底 import (
    以组名开头,
    取落空参数,
    子命令名,
    是否落空,
    落空提示,
)


class Test取落空参数:
    def test_取出组名后面的内容(self):
        assert 取落空参数("/爱农 老王", "爱农") == "老王"

    def test_带开头的斜杠与空格(self):
        assert 取落空参数("/爱农    老王", "爱农") == "老王"

    def test_只有组名时是空(self):
        assert 取落空参数("/爱农", "爱农") == ""

    def test_没带斜杠也认(self):
        """有些平台的消息不会带 `/`。"""
        assert 取落空参数("爱农 战绩", "爱农") == "战绩"

    def test_组名出现两次时取第一个之后的(self):
        assert 取落空参数("/爱农 /爱农 战绩", "爱农") == "/爱农 战绩"


class Test子命令名:
    def test_认得各个子命令(self):
        for 名 in ("战绩", "锐评", "开一局", "PK", "昵称", "角色", "解绑", "状态", "帮助"):
            assert 名 in 子命令名

    def test_认得两条绑定(self):
        """绑定拆成微信与 QQ 两条，两条都得认。"""
        assert "绑定微信" in 子命令名
        assert "绑定QQ" in 子命令名

    def test_认得别名(self):
        """别名也要认，否则用户打 `/爱农 绑定` 或 `/爱农 开一局排位` 照样落空。"""
        for 别名 in ("绑定", "绑定qq", "开一局排位", "pk", "对战", "help", "菜单", "status"):
            assert 别名 in 子命令名

    def test_认得大小写差异(self):
        assert "PK" in 子命令名
        assert "pk" in 子命令名


class Test落空提示:
    def test_没参数时列出指令(self):
        提示 = 落空提示("")

        assert "战绩" in 提示
        assert "帮助" in 提示
        assert "绑定" in 提示

    def test_把参数原样带回去(self):
        """用户不用重新打字。"""
        assert "老王" in 落空提示("老王")

    def test_太长时截断(self):
        提示 = 落空提示("王" * 200)

        assert len(提示) <= 80

    def test_不长(self):
        """落空说明要短，太长就成了第二份帮助文本。"""
        assert len(落空提示("老王")) <= 120

    def test_空参数不抛(self):
        assert 落空提示("").strip()


class Test该拦不该拦:
    @pytest.mark.parametrize(
        ("消息", "期望落空"),
        [
            ("/爱农 战绩", False),
            ("/爱农 锐评", False),
            ("/爱农 开一局", False),
            ("/爱农 开一局排位", False),
            ("/爱农 PK 老王", False),
            ("/爱农 pk 老王", False),
            ("/爱农 昵称 老王", False),
            ("/爱农 角色", False),
            ("/爱农 绑定微信", False),
            ("/爱农 绑定", False),
            ("/爱农 绑定QQ", False),
            ("/爱农 绑定qq", False),
            ("/爱农 帮助", False),
            ("/爱农 help", False),
            # 这些才是真的落空
            ("/爱农 老王", True),
            ("/爱农 我的战绩怎么样", True),
        ],
    )
    def test_只有真落空才算落空(self, 消息, 期望落空):
        """正常子命令与别名都走各自指令，别被兜底吃掉。

        顺带验「该拦」本身——只断言前半段的话，把后半段改成永远 False
        测试也不红，等于没钉。
        """
        assert 是否落空(消息, "爱农") is 期望落空

    def test_不带斜杠也算本组(self):
        """有些平台的消息不带 `/`，只按带斜杠的形式判会漏掉。"""
        参数 = 取落空参数("爱农 老王", "爱农")

        assert 参数 == "老王"
        assert not any(参数.startswith(名) for 名 in 子命令名)

    def test_别的插件的指令不算本组(self):
        """`/爱瓦 绑定` 是另一个插件的，不能被这里抢走。

        注意：这个 filter **会**被调用。`CommandGroupFilter.filter` 的执行
        顺序是先跑 `custom_filter_ok()`、之后才检查组名是否匹配，所以挂在
        指令组上的过滤器对每一条消息都执行。原实现里 `取落空参数` 对非本组
        消息「原样返回」，于是别人的指令被判定成「爱农的子命令落空」，
        `stop_event()` 把整条掐死——爱瓦因此从能用变成完全没反应。
        所以非本组消息必须返回**空串**，让调用方一眼看出不归自己管。
        """
        assert 取落空参数("/爱瓦 绑定", "爱农") == ""
        assert not 是否落空("/爱瓦 绑定", "爱农")
        assert not 是否落空("爱完美 PK 老王", "爱农")

    @pytest.mark.parametrize(
        "消息",
        ["在吗", "", "今天天气不错", "爱瓦 绑定", "爱完美 战绩", "/help"],
    )
    def test_陌生消息一律放行(self, 消息):
        assert not 是否落空(消息, "爱农"), f"{消息!r} 被误判成爱农的落空"

    @pytest.mark.parametrize(
        "消息",
        ["/爱农 绑定微信", "爱农 绑定", "/爱农 战绩", "爱农 PK 老王", "/爱农 help"],
    )
    def test_本组正常指令放行(self, 消息):
        assert not 是否落空(消息, "爱农"), f"{消息!r} 是正常指令，不该判成落空"

    def test_以组名开头(self):
        assert 以组名开头("爱农 绑定", "爱农")
        assert 以组名开头("/爱农 绑定", "爱农")
        assert not 以组名开头("爱瓦 绑定", "爱农")
        assert not 以组名开头("在吗", "爱农")
        assert not 以组名开头("", "爱农")
