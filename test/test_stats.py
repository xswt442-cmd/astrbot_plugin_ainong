"""战绩统计的测试。

统计要回答的问题很具体：这个玩家在打什么模式、什么位置、常用哪些英雄、
近期的表现如何。字段语义来自真实接口响应，不按字段名推测。
"""

import pytest

from ainong.stats import 汇总文本, 统计战绩


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
