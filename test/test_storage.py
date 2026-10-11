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
