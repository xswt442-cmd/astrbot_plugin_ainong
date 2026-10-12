"""凭据存储的测试。

凭据属于营地账号，不属于 Bot 用户也不属于游戏角色，所以按 Bot 用户
分文件存：一个用户一个文件，里面记他绑定的营地账号和当前选中的角色。

解绑要真的删掉文件：凭据等同账号凭证，留着没有用途还多一份泄露面。
"""

import json
from pathlib import Path

import pytest

from ainong.storage import 凭据仓库

_营地 = {
    "营地ID": "1234567890",
    "令牌": "t" * 104,
    "对称密钥": "k" * 16,
}


@pytest.fixture
def 仓库(tmp_path: Path) -> 凭据仓库:
    return 凭据仓库(tmp_path)


class Test存储:
    def test_存后可读回(self, 仓库):
        仓库.写入("用户A", _营地)
        assert 仓库.读取("用户A")["营地ID"] == "1234567890"

    def test_未绑定时读到None(self, 仓库):
        assert 仓库.读取("用户B") is None

    def test_文件按用户分开(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.写入("用户B", {**_营地, "营地ID": "999"})
        assert 仓库.读取("用户A")["营地ID"] == "1234567890"
        assert 仓库.读取("用户B")["营地ID"] == "999"

    def test_写入会建目录(self, tmp_path: Path):
        目标 = tmp_path / "深层" / "目录"
        仓库 = 凭据仓库(目标)
        仓库.写入("用户A", _营地)
        assert 仓库.读取("用户A") is not None

    def test_覆盖同一用户的旧绑定(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.写入("用户A", {**_营地, "营地ID": "888"})
        assert 仓库.读取("用户A")["营地ID"] == "888"

    def test_文件名不含用户标识的原文(self, 仓库):
        # QQ 号可能带特殊字符，不能直接当文件名
        仓库.写入("12/34:56@qq.com", _营地)
        assert 仓库.读取("12/34:56@qq.com") is not None
        for 文件 in 仓库.目录.iterdir():
            assert "/" not in 文件.name


class Test角色选择:
    def test_默认没有选中角色(self, 仓库):
        仓库.写入("用户A", _营地)
        assert 仓库.当前角色("用户A") == ""

    def test_可选中角色(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.选角色("用户A", "432879689")
        assert 仓库.当前角色("用户A") == "432879689"

    def test_选角色随绑定一起存(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.选角色("用户A", "432879689")
        assert 仓库.读取("用户A")["角色ID"] == "432879689"

    def test_未绑定时选角色无效(self, 仓库):
        仓库.选角色("用户B", "123")
        assert 仓库.当前角色("用户B") == ""


class Test解绑:
    def test_删除后读到None(self, 仓库):
        仓库.写入("用户A", _营地)
        assert 仓库.删除("用户A") is not None
        assert 仓库.读取("用户A") is None

    def test_删除返回原记录(self, 仓库):
        仓库.写入("用户A", _营地)
        assert 仓库.删除("用户A")["营地ID"] == "1234567890"

    def test_删除不存在的用户返回None(self, 仓库):
        assert 仓库.删除("用户C") is None

    def test_删除不影响其他用户(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.写入("用户B", _营地)
        仓库.删除("用户A")
        assert 仓库.读取("用户B") is not None


class Test损坏文件:
    def test_内容不是JSON时视为未绑定(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.路径("用户A").write_text("这不是 JSON", encoding="utf-8")
        assert 仓库.读取("用户A") is None

    def test_缺关键字段时视为未绑定(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.路径("用户A").write_text(json.dumps({"别的": 1}), encoding="utf-8")
        assert 仓库.读取("用户A") is None


class Test文件权限:
    def test_凭据文件权限收紧(self, 仓库):
        import os

        仓库.写入("用户A", _营地)
        if os.name == "posix":
            模式 = 仓库.路径("用户A").stat().st_mode & 0o777
            assert 模式 == 0o600


class Test按昵称找人:
    """PK 用这条路，因为 QQ 官方平台拿不到被 @ 的人的标识。

    适配器只把「@机器人」转成组件，@别人在事件里连痕迹都没有（实测组件是
    `['qq_official', None]`、正文是 `'爱农 PK'`）。所以群里 PK 只能按名字点人。
    """

    def test_写入时记下用户标识(self, 仓库):
        """文件名是标识的哈希，反推不回去，所以要显式存一份。"""
        仓库.写入("用户A", _营地)
        assert 仓库.读取("用户A")["用户"] == "用户A"

    def test_全部列出所有绑定(self, 仓库):
        仓库.写入("用户A", _营地)
        仓库.写入("用户B", {**_营地, "营地ID": "999"})
        assert len(仓库.全部()) == 2

    def test_空目录返回空表(self, 仓库):
        assert 仓库.全部() == []

    def test_损坏文件被跳过(self, 仓库):
        仓库.写入("用户A", _营地)
        (仓库.目录 / "坏文件.json").write_text("不是 JSON", encoding="utf-8")
        assert len(仓库.全部()) == 1

    def test_按昵称精确命中(self, 仓库):
        仓库.写入("用户A", {**_营地, "昵称": "蕾蜜"})
        命中 = 仓库.按昵称找("蕾蜜")
        assert len(命中) == 1
        assert 命中[0]["用户"] == "用户A"

    def test_大小写不敏感(self, 仓库):
        仓库.写入("用户A", {**_营地, "昵称": "ZnNe"})
        assert len(仓库.按昵称找("znne")) == 1

    def test_精确优先于子串(self, 仓库):
        仓库.写入("用户A", {**_营地, "昵称": "蕾"})
        仓库.写入("用户B", {**_营地, "营地ID": "999", "昵称": "蕾蜜"})
        命中 = 仓库.按昵称找("蕾")
        assert [记录["用户"] for 记录 in 命中] == ["用户A"]

    def test_没有精确命中时给子串(self, 仓库):
        仓库.写入("用户A", {**_营地, "昵称": "蕾蜜酱"})
        命中 = 仓库.按昵称找("蕾蜜")
        assert [记录["用户"] for 记录 in 命中] == ["用户A"]

    def test_能返回多个让上层去问(self, 仓库):
        # 没有精确命中时才走子串，这里两个都只是包含「小明」。
        仓库.写入("用户A", {**_营地, "昵称": "小明A"})
        仓库.写入("用户B", {**_营地, "营地ID": "999", "昵称": "小明B"})
        assert len(仓库.按昵称找("小明")) == 2

    def test_有精确命中就不再给子串(self, 仓库):
        仓库.写入("用户A", {**_营地, "昵称": "小明"})
        仓库.写入("用户B", {**_营地, "营地ID": "999", "昵称": "小明明"})
        assert [记录["用户"] for 记录 in 仓库.按昵称找("小明")] == ["用户A"]

    def test_找不到返回空表(self, 仓库):
        仓库.写入("用户A", {**_营地, "昵称": "蕾蜜"})
        assert 仓库.按昵称找("张三") == []

    def test_空名字返回空表(self, 仓库):
        仓库.写入("用户A", {**_营地, "昵称": "蕾蜜"})
        assert 仓库.按昵称找("") == []
        assert 仓库.按昵称找("   ") == []

    def test_老记录没存昵称时不匹配(self, 仓库):
        仓库.写入("用户A", _营地)
        assert 仓库.按昵称找("蕾蜜") == []
