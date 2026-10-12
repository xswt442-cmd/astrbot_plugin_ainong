"""战绩统计的测试。

统计要回答的问题很具体：这个玩家在打什么模式、什么位置、常用哪些英雄、
近期的表现如何。字段语义来自真实接口响应，不按字段名推测。
"""

import pytest

from ainong.stats import (
    占优项数,
    对比文本,
    对比要点,
    抽对局结果,
    映射英雄名,
    汇总文本,
    统计战绩,
)


def _场(
    *,
    胜: bool = True,
    模式: str = "排位赛",
    英雄: str = "镜",
    击杀: int = 3,
    死亡: int = 2,
    助攻: int = 5,
    MVP: int = 0,
    评分: float = 6.5,
    时长秒: int = 900,
) -> dict:
    return {
        "gameresult": 1 if 胜 else 2,
        "mapName": 模式,
        "heroName": 英雄,
        "killcnt": 击杀,
        "deadcnt": 死亡,
        "assistcnt": 助攻,
        "mvpcnt": MVP,
        "gradeGame": 评分,
        "usedTime": 时长秒,
    }


class Test映射英雄名:
    表 = {105: "廉颇", 168: "牛魔"}

    def test_按编号查出名字(self):
        assert 映射英雄名([{"heroId": 105}], self.表)[0]["heroName"] == "廉颇"

    def test_一次映射多场(self):
        结果 = 映射英雄名([{"heroId": 105}, {"heroId": 105}], self.表)
        assert all(场["heroName"] == "廉颇" for 场 in 结果)

    def test_保留原有字段(self):
        场 = 映射英雄名([{"heroId": 105, "killcnt": 3}], self.表)[0]
        assert 场["killcnt"] == 3

    def test_查不到时不加名字字段(self):
        assert "heroName" not in 映射英雄名([{"heroId": 999}], self.表)[0]

    def test_已有名字时不覆盖(self):
        assert 映射英雄名([{"heroName": "自定义"}], self.表)[0]["heroName"] == "自定义"

    def test_原列表不被修改(self):
        场次 = [{"heroId": 105}]
        映射英雄名(场次, self.表)
        assert "heroName" not in 场次[0]

    def test_空表时原样返回(self):
        assert 映射英雄名([{"heroId": 105}], {}) == [{"heroId": 105}]

    def test_空列表照常返回(self):
        assert 映射英雄名([], self.表) == []


class Test拉英雄表:
    def test_取到表后能用编号查名(self):
        import asyncio

        from ainong.stats import 拉英雄表

        表 = asyncio.run(拉英雄表())
        if 表:  # 网络不可用时跳过实质断言，只确认不抛异常
            assert all(isinstance(v, str) for v in 表.values())
            assert all(isinstance(k, int) for k in 表)

    def test_第二次直接用缓存(self):
        import asyncio

        from ainong.stats import 拉英雄表

        asyncio.run(拉英雄表())
        assert asyncio.run(拉英雄表()) is asyncio.run(拉英雄表())


class Test统计战绩:
    def test_空列表不崩(self):
        结果 = 统计战绩([])
        assert 结果["总场次"] == 0
        assert 结果["胜场"] == 0
        assert 结果["胜率"] == 0.0

    def test_统计总场次与胜负(self):
        场次 = [_场(胜=True), _场(胜=True), _场(胜=False)]
        结果 = 统计战绩(场次)
        assert 结果["总场次"] == 3
        assert 结果["胜场"] == 2
        assert 结果["负场"] == 1

    def test_胜率按百分比(self):
        场次 = [_场(胜=True)] * 7 + [_场(胜=False)] * 3
        结果 = 统计战绩(场次)
        assert 结果["胜率"] == pytest.approx(70.0)

    def test_胜率四舍五入到一位(self):
        场次 = [_场(胜=True)] * 2 + [_场(胜=False)]
        assert 统计战绩(场次)["胜率"] == pytest.approx(66.7)

    def test_统计平均KDA(self):
        场次 = [_场(击杀=3, 死亡=2, 助攻=5), _场(击杀=7, 死亡=4, 助攻=1)]
        结果 = 统计战绩(场次)
        assert 结果["平均击杀"] == pytest.approx(5.0)
        assert 结果["平均死亡"] == pytest.approx(3.0)
        assert 结果["平均助攻"] == pytest.approx(3.0)

    def test_统计MVP次数(self):
        结果 = 统计战绩([_场(MVP=1), _场(MVP=0), _场(MVP=1)])
        assert 结果["mvp次数"] == 2

    def test_统计平均评分(self):
        结果 = 统计战绩([_场(评分=6.0), _场(评分=7.0)])
        assert 结果["平均评分"] == pytest.approx(6.5)

    def test_统计平均时长分钟(self):
        结果 = 统计战绩([_场(时长秒=600), _场(时长秒=1200)])
        assert 结果["平均时长分钟"] == pytest.approx(15.0)

    def test_模式分布按场次降序(self):
        场次 = [_场(模式="排位赛")] * 5 + [_场(模式="巅峰赛")] * 2
        结果 = 统计战绩(场次)
        assert [名 for 名, _ in 结果["模式分布"]] == ["排位赛", "巅峰赛"]
        assert 结果["模式分布"][0][1] == 5

    def test_常用英雄按场次降序(self):
        场次 = [_场(英雄="镜")] * 4 + [_场(英雄="赵云")] * 2 + [_场(英雄="李白")]
        结果 = 统计战绩(场次)
        assert [名 for 名, _, _ in 结果["常用英雄"]] == ["镜", "赵云", "李白"]

    def test_英雄统计带各自胜率(self):
        场次 = [_场(英雄="镜", 胜=True), _场(英雄="镜", 胜=False)]
        结果 = 统计战绩(场次)
        名, 场数, 胜率 = 结果["常用英雄"][0]
        assert (名, 场数) == ("镜", 2)
        assert 胜率 == pytest.approx(50.0)

    def test_英雄列表有长度上限(self):
        场次 = [_场(英雄=f"英雄{i}") for i in range(20)]
        结果 = 统计战绩(场次)
        assert len(结果["常用英雄"]) == 5

    def test_英雄缺名字时用英雄ID占位(self):
        场 = _场()
        del 场["heroName"]
        场["heroId"] = 105
        结果 = 统计战绩([场])
        assert 结果["常用英雄"][0][0] == "105"

    def test_连胜连败按最新场次算(self):
        # 场次按时间倒序，最新在最前
        场次 = [_场(胜=False)] * 2 + [_场(胜=True)] * 3
        结果 = 统计战绩(场次)
        assert 结果["当前连胜"] == 0
        assert 结果["当前连败"] == 2

    def test_最新是胜利时数连胜(self):
        场次 = [_场(胜=True)] * 3 + [_场(胜=False)] * 2
        结果 = 统计战绩(场次)
        assert 结果["当前连胜"] == 3
        assert 结果["当前连败"] == 0

    def test_全部获胜时当前连败为零(self):
        结果 = 统计战绩([_场(胜=True)] * 4)
        assert 结果["当前连胜"] == 4
        assert 结果["当前连败"] == 0

    def test_零击杀场次参与平均(self):
        结果 = 统计战绩([_场(击杀=0), _场(击杀=0)])
        assert 结果["平均击杀"] == pytest.approx(0.0)


class Test汇总文本:
    def test_包含段位与场次(self):
        文本 = 汇总文本(统计战绩([_场()]), 段位="至尊星耀V", 巅峰分="2100")
        assert "至尊星耀V" in 文本
        assert "1" in 文本

    def test_是给模型看的紧凑文本(self):
        文本 = 汇总文本(统计战绩([_场()] * 4), 段位="至尊星耀V")
        assert len(文本) < 400

    def test_空战绩时给出说明(self):
        文本 = 汇总文本(统计战绩([]), 段位="未定级")
        assert "没有" in 文本 or "暂无" in 文本

    def test_包含常用英雄(self):
        文本 = 汇总文本(统计战绩([_场(英雄="镜")] * 3))
        assert "镜" in 文本

    def test_不需要星级或表情符号(self):
        文本 = 汇总文本(统计战绩([_场()]))
        assert "*" not in 文本


class Test更细的维度:
    """升级后新增的统计项。

    营地接口各版本字段不一致，取不到的项**不能拿 0 充数**——0 是个合法的
    数据，「这一项没有」不是。所以下面一半的测试在盯「缺字段时不出现」。
    """

    def test_有死亡时算KDA(self):
        场次 = [_场(击杀=3, 死亡=3, 助攻=6), _场(击杀=3, 死亡=3, 助攻=6)]
        assert 统计战绩(场次)["KDA"] == pytest.approx(3.0)

    def test_零死亡时KDA不算成无穷(self):
        """一场没死过，KDA 记作击杀+助攻，别让文本里冒出 inf。"""
        结果 = 统计战绩([_场(击杀=4, 死亡=0, 助攻=3)])
        assert 结果["KDA"] == pytest.approx(7.0)

    def test_走势是最新在前(self):
        场次 = [_场(胜=True), _场(胜=True), _场(胜=False), _场(胜=True)]
        结果 = 统计战绩(场次)
        assert 结果["最近走势"] == [True, True, False, True]
        assert 结果["走势文本"] == "胜胜负胜"

    def test_走势最多取十场(self):
        结果 = 统计战绩([_场()] * 25)
        assert len(结果["最近走势"]) == 10

    def test_最长连胜跨过失败继续数(self):
        场次 = [_场(胜=True)] * 2 + [_场(胜=False)] + [_场(胜=True)] * 5
        结果 = 统计战绩(场次)
        assert 结果["最长连胜"] == 5
        assert 结果["当前连胜"] == 2

    def test_星数取最新一场(self):
        场次 = [{**_场(), "stars": 3}, {**_场(), "stars": 1}]
        assert 统计战绩(场次)["星数"] == pytest.approx(3.0)

    def test_巅峰分取最新一场(self):
        场次 = [
            {**_场(), "mapName": "巅峰赛", "newMasterMatchScore": 1652},
            {**_场(), "mapName": "巅峰赛", "newMasterMatchScore": 1600},
        ]
        assert 统计战绩(场次)["巅峰分"] == pytest.approx(1652.0)

    def test_没打过巅峰赛时不报巅峰分(self):
        """列表接口每场都带 newMasterMatchScore，没打过的号全是 1200 初始分。

        照直显示等于告诉模型「这人巅峰 1200」，而事实是他根本没打过。
        """
        场次 = [{**_场(), "newMasterMatchScore": 1200, "mapName": "排位赛 五排"}]
        assert 统计战绩(场次)["巅峰分"] is None

    def test_有巅峰赛场次时才报巅峰分(self):
        场次 = [
            {**_场(), "mapName": "巅峰赛", "newMasterMatchScore": 1652},
            {**_场(), "mapName": "排位赛 五排", "newMasterMatchScore": 1200},
        ]
        assert 统计战绩(场次)["巅峰分"] == pytest.approx(1652.0)

    def test_奖牌从图地址里解出等级和职业(self):
        """奖牌图地址形如 `.../evaluateV3/silver_archer.png`，等级与职业都写在里面。"""
        场次 = [
            {**_场(), "evaluateUrl": "http://x/evaluate-v2/gold_warrior_1.png"},
            {**_场(), "evaluateUrl": "http://x/evaluate-v2/silver_archer_1.png"},
            {**_场(), "evaluateUrl": "http://x/evaluate-v2/gold_warrior_1.png"},
        ]
        结果 = 统计战绩(场次)
        assert 结果["奖牌"] == {"金牌": 2, "银牌": 1}
        assert 结果["奖牌位置"][0] == ("战士", 2)

    def test_没有奖牌图时不编(self):
        结果 = 统计战绩([_场()])
        assert 结果["奖牌"] == {}
        assert 结果["奖牌位置"] == []

    def test_高光数各类标记(self):
        场次 = [
            {**_场(), "firstBlood": 1, "hero1TripleKillCnt": 1},
            {**_场(), "godLikeCnt": 1, "hero1UltraKillCnt": 1},
            _场(),
        ]
        assert 统计战绩(场次)["高光"] == {"一血": 1, "超神": 1, "三杀": 1, "四杀": 1}

    def test_局内评价按场次降序且不留空名(self):
        场次 = [_场(), _场(), _场(), {**_场(), "desc": "实力局"}, {**_场(), "desc": "实力局"}]
        评价 = 统计战绩(场次)["局内评价"]
        assert 评价[0] == ("实力局", 2)
        assert all(名 for 名, _ in 评价), "评价为空的行不该进列表"

    def test_缺字段时这些项是_None_而不是_0(self):
        结果 = 统计战绩([_场()])
        assert 结果["星数"] is None
        assert 结果["巅峰分"] is None

    def test_空列表也带着这些键(self):
        结果 = 统计战绩([])
        for 键 in ("KDA", "最长连胜", "最近走势", "奖牌", "高光", "局内评价", "星数", "巅峰分"):
            assert 键 in 结果

    def test_统计败方MVP当作SVP(self):
        """接口里没有 svp 字段，败方 MVP 叫 losemvp（实测与 mvpUrlV2 里的 svp 图一致）。"""
        场次 = [{**_场(), "losemvp": 1}, _场(), {**_场(), "losemvp": 1}]
        assert 统计战绩(场次)["svp次数"] == 2


class Test汇总文本的新维度:
    def test_带上走势(self):
        文本 = 汇总文本(统计战绩([_场(胜=True), _场(胜=False)]))
        assert "最近 2 场：胜负" in 文本

    def test_段位带星数(self):
        文本 = 汇总文本(统计战绩([{**_场(), "stars": 3}]), 段位="至尊星耀V")
        assert "至尊星耀V 3星" in 文本

    def test_有巅峰分时显示(self):
        场次 = [{**_场(), "mapName": "巅峰赛", "newMasterMatchScore": 1652}]
        assert "1652" in 汇总文本(统计战绩(场次))

    def test_巅峰分是初始分时不显示(self):
        文本 = 汇总文本(统计战绩([{**_场(), "newMasterMatchScore": 1200}]))
        assert "巅峰分" not in 文本

    def test_奖牌与高光各占一行(self):
        场次 = [
            {**_场(), "evaluateUrl": "http://x/gold_warrior_1.png", "firstBlood": 1},
            {**_场(), "evaluateUrl": "http://x/silver_mage_1.png", "godLikeCnt": 1},
        ]
        文本 = 汇总文本(统计战绩(场次))
        assert "奖牌：金牌 1 次、银牌 1 次" in 文本
        assert "高光：一血 1 次、超神 1 次" in 文本

    def test_局内评价进文本(self):
        场次 = [{**_场(), "desc": "实力局"}] * 3 + [{**_场(), "desc": "翻车局"}]
        文本 = 汇总文本(统计战绩(场次))
        assert "局内评价：实力局 3 场、翻车局 1 场" in 文本

    def test_缺字段时不出现这些字样(self):
        文本 = 汇总文本(统计战绩([_场()]))
        for 字样 in ("参团", "分均", "奖牌", "高光", "局内评价", "巅峰分", "星"):
            assert 字样 not in 文本, f"没有这项数据，不该出现「{字样}」"

    def test_模式超过三个时合并成其他(self):
        # 模式按场次降序，前三是 巅峰赛5 / 五排4 / 双排3，剩下的三排2 归入「其他」。
        场次 = (
            [_场(模式="排位赛 五排")] * 4
            + [_场(模式="排位赛 双排")] * 3
            + [_场(模式="排位赛 三排")] * 2
            + [_场(模式="巅峰赛")] * 5
        )
        文本 = 汇总文本(统计战绩(场次))
        assert "其他2场" in 文本
        assert "三排" not in 文本.split("模式：")[1].split("\n")[0]

    def test_最长连胜和当前连胜相同时不重复说(self):
        文本 = 汇总文本(统计战绩([_场(胜=True)] * 6))
        assert "当前连胜 6 场" in 文本
        assert "最长连胜" not in 文本

    def test_最长连胜更大时才单独说(self):
        场次 = [_场(胜=True)] * 2 + [_场(胜=False)] * 2 + [_场(胜=True)] * 5
        文本 = 汇总文本(统计战绩(场次))
        assert "最长连胜 5 场" in 文本
        assert "当前连胜 2 场" in 文本

    def test_MVP_带占比(self):
        文本 = 汇总文本(统计战绩([{**_场(MVP=1)}] * 10))
        assert "MVP 10 次（100.0%）" in 文本

    def test_短样本不写MVP占比(self):
        """三场里两次 MVP 不代表 66% 的 MVP 率，别误导模型。"""
        文本 = 汇总文本(统计战绩([{**_场(MVP=1)}, {**_场(MVP=1)}, _场()]))
        assert "MVP 2 次" in 文本
        assert "（" not in 文本.split("MVP")[1].split("\n")[0]


class Test逐项对比:
    """PK 的对比由代码算死，不交给模型。

    线上实测：把两份数据丢给模型让它自己比，它给的分数是 83 对 87 —— 看不出
    输赢，点评也是「各有千秋」那一路。所以对比必须在这里算清楚。
    """

    def _甲(self):
        return 统计战绩(
            [
                {
                    "gameresult": 1,
                    "heroName": "牛魔",
                    "killcnt": 2,
                    "deadcnt": 4,
                    "assistcnt": 11,
                    "gradeGame": 7.6,
                    "usedTime": 900,
                    "mvpcnt": 1,
                }
            ]
            * 10
        )

    def _乙(self):
        return 统计战绩(
            [
                {
                    "gameresult": 2,
                    "heroName": "铠",
                    "killcnt": 6,
                    "deadcnt": 2,
                    "assistcnt": 3,
                    "gradeGame": 9.0,
                    "usedTime": 900,
                    "mvpcnt": 0,
                }
            ]
            * 10
        )

    def test_每项都指明谁占优(self):
        要点 = 对比要点("甲", self._甲(), "乙", self._乙())
        assert 要点, "应该比出若干项"
        for 条 in 要点:
            assert 条["优"] in ("甲", "乙", "持平"), 条
            assert 条["项"] and 条["甲"] and 条["乙"]

    def test_胜率高的一方算占优(self):
        要点 = {条["项"]: 条 for 条 in 对比要点("甲", self._甲(), "乙", self._乙())}
        assert 要点["胜率"]["优"] == "甲"

    def test_死亡少的一方算占优(self):
        """场均死亡越小越好，方向和胜率相反。"""
        要点 = {条["项"]: 条 for 条 in 对比要点("甲", self._甲(), "乙", self._乙())}
        assert 要点["场均死亡"]["优"] == "乙"

    def test_文本里写明谁占优(self):
        文本 = 对比文本(对比要点("甲", self._甲(), "乙", self._乙()), "甲", "乙")
        assert "甲占优" in 文本 or "乙占优" in 文本
        assert "胜率" in 文本

    def test_持平时标出来(self):
        同 = self._甲()
        文本 = 对比文本(对比要点("甲", 同, "乙", 同), "甲", "乙")
        assert "持平" in 文本

    def test_占优项数不对称(self):
        要点 = 对比要点("甲", self._甲(), "乙", self._乙())
        汇总 = 占优项数(要点, "甲", "乙")
        assert "甲" in 汇总 and "乙" in 汇总
        assert " 0 项" not in 汇总.split("、")[0], "这场明显该有一方占优多项"

    def test_空统计时不崩(self):
        空 = 统计战绩([])
        assert 对比要点("甲", 空, "乙", 空) == []


class Test抽对局结果:
    """胜负按真实胜率抽，不交给模型。

    模型没有随机性：让它定结果，连开十局就是十次「超神带飞」，而一个 45%
    胜率的号不该这样。
    """

    class 固定随机:
        def __init__(self, 值: float) -> None:
            self.值 = 值

        def random(self) -> float:
            return self.值

    def test_高胜率多数赢(self):
        统计 = {"总场次": 40, "胜率": 80.0}
        assert 抽对局结果(统计, self.固定随机(0.5)) == "胜利"
        assert 抽对局结果(统计, self.固定随机(0.9)) == "失败"

    def test_低胜率多数输(self):
        统计 = {"总场次": 40, "胜率": 30.0}
        assert 抽对局结果(统计, self.固定随机(0.5)) == "失败"
        assert 抽对局结果(统计, self.固定随机(0.2)) == "胜利"

    def test_没有场次时按五成(self):
        空 = {"总场次": 0, "胜率": 0.0}
        assert 抽对局结果(空, self.固定随机(0.4)) == "胜利"
        assert 抽对局结果(空, self.固定随机(0.6)) == "失败"

    def test_满胜率也不是必赢(self):
        """概率收到 0.9 上限——100% 胜率的号照样会输，不然没意思。"""
        assert 抽对局结果({"总场次": 10, "胜率": 100.0}, self.固定随机(0.95)) == "失败"

    def test_零胜率也不是必输(self):
        assert 抽对局结果({"总场次": 10, "胜率": 0.0}, self.固定随机(0.05)) == "胜利"

    def test_只返回两个值(self):
        统计 = {"总场次": 5, "胜率": 50.0}
        for 值 in (0.0, 0.3, 0.7, 0.99):
            assert 抽对局结果(统计, self.固定随机(值)) in ("胜利", "失败")
