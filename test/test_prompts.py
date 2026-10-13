"""提示词的措辞。

这些不是「文案好不好」的审美测试，而是**格式与反端水约束**：

- 称号那一行要以「你最近是个」开头，四段小标题不能并成一段；
- PK 必须给出胜者、必须要求分差、必须列出不许说的端水词。

模型很爱把这些约束自由发挥掉（实测 PK 出过 83 对 87 这种看不出输赢的分），
改了提示就靠这几条兜住。
"""

from __future__ import annotations

from ainong.prompts import PK提示, 开一局提示, 推演声明, 称号前缀, 端水词, 锐评提示

数据 = "段位 至尊星耀V 3星 ｜ 近40场 27胜13负 ｜ 胜率 67.5%"

_对比 = "胜率：asd占优（asd 67.5% / 老王 52.1%）\nKDA：asd占优（asd 3.0 / 老王 2.1）"
_占优 = "asd 2 项、老王 0 项"


class Test锐评提示:
    提示 = 锐评提示(数据)

    def test_带上数据(self):
        assert 数据 in self.提示

    def test_称号行有硬前缀(self):
        assert 称号前缀 in self.提示, "称号必须固定以「你最近是个」开头"
        assert 称号前缀 == "你最近是个"

    def test_四个小标题都在(self):
        for 段 in ("打得好：", "问题：", "建议："):
            assert 段 in self.提示, f"缺小标题 {段}"

    def test_要求不要前言(self):
        assert "不要前言" in self.提示

    def test_要求出现具体数字(self):
        assert "至少出现 3 个具体数字" in self.提示

    def test_问题那段要落到数据上(self):
        assert "多注意意识" in self.提示, "要点名不许写这种没落到数据上的空话"

    def test_禁掉了端水词(self):
        for 词 in 端水词:
            assert 词 in self.提示, f"端水词「{词}」应该写进禁令里"

    def test_不许编数据里没有的东西(self):
        assert "只说数据支撑得住的话" in self.提示
        assert "宁可少说一句，也不要编一句" in self.提示

    def test_有字数区间(self):
        assert "180 到 260 字" in self.提示


class TestPK提示:
    提示 = PK提示("asd", "老王", _对比, _占优, 数据, "段位 永恒钻石I ｜ 近40场 20胜20负")

    def test_两个人的名字与数据都在(self):
        assert "asd" in self.提示
        assert "老王" in self.提示
        assert "永恒钻石I" in self.提示

    def test_带上算好的对比(self):
        assert "asd 67.5%" in self.提示, "逐项对比要原样带进提示"
        assert "KDA" in self.提示

    def test_带上占优项数(self):
        assert "asd 2 项、老王 0 项" in self.提示

    def test_要模型别推翻对比(self):
        assert "不要重算" in self.提示
        assert "不要推翻对比结论" in self.提示

    def test_分数有量纲且分差要合理(self):
        """分差要跟实际差距相符。

        写「要敢于给大的分数差距」时，两个数据接近的人也会被硬拉开三十分，
        看起来像在制造对立而不是在打分。
        """
        assert "0-100 的整数" in self.提示, "分数要有量纲"
        assert "分差要跟两人的实际差距相符" in self.提示
        assert "敢于给大的分数差距" not in self.提示

    def test_胜者要与分数一致(self):
        """分数与胜者由模型各写各的，不钉住就会出现 88 分输给 70 分。"""
        assert "胜者那一行写分数更高的那个人" in self.提示

    def test_不强制占优多的一方赢(self):
        """项数是机械数出来的，哪几项占优才决定强弱，判断留给模型。"""
        assert "占优项更多的一方不一定分数更高" in self.提示
        assert "一切从实际出发" in self.提示
        assert "必须分数更高" not in self.提示, "别把项数变成硬结论"

    def test_要求给出胜者(self):
        assert "胜者：" in self.提示

    def test_要求逐项带数字(self):
        assert "逐项：" in self.提示

    def test_互损点名难看的那一项(self):
        assert "必须点名双方最难看的那一项" in self.提示
        assert "对于输的一方点名更狠一点" in self.提示

    def test_不许编数据里没有的东西(self):
        assert "只说数据支撑得住的话" in self.提示
        assert "宁可少说一句，也不要编一句" in self.提示

    def test_禁掉了端水词(self):
        for 词 in 端水词:
            assert 词 in self.提示, f"端水词「{词}」应该写进禁令里"

    def test_不许两边都给好评(self):
        assert "不要两边都给好评" in self.提示

    def test_互损有字数下限(self):
        assert "至少 90 字" in self.提示

    def test_数据按人分开标注(self):
        assert "【asd】" in self.提示
        assert "【老王】" in self.提示


class Test开一局提示:
    提示 = 开一局提示(数据, "失败")

    def test_带上数据(self):
        assert 数据 in self.提示

    def test_六个结构标签都在(self):
        for 段 in ("选人：", "经过：", "亮点：", "问题：", "复盘：", "结算："):
            assert 段 in self.提示, f"缺结构 {段}"

    def test_这是推演不是战绩(self):
        """用户看到一串 K/D/A 看不出真假，第一行那句话是唯一的提示。"""
        assert self.提示.count(推演声明) >= 2, "推演声明要在骨架与硬要求里各出现一次"
        assert f"第一行必须是「{推演声明}」" in self.提示
        assert "不要复述数据原文" in self.提示

    def test_结果写进去且不许改(self):
        assert "胜负已经定了：失败" in self.提示
        assert "必须原样写「失败」" in self.提示

    def test_胜利的情况也带进去(self):
        assert "胜负已经定了：胜利" in 开一局提示(数据, "胜利")

    def test_选人限定在常用英雄里(self):
        assert "常用英雄" in self.提示

    def test_不许编数据里没有的东西(self):
        assert "只说数据支撑得住的话" in self.提示

    def test_有字数上限(self):
        assert "240 字" in self.提示
