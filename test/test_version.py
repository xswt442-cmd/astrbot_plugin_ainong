"""版本号在几处出现，必须一致。

版本号散在三个文件里，改一处漏一处不会立刻坏：metadata.yaml 是市场读的，
pyproject.toml 只有构建时才看，CHANGELOG 的小节标题则要人去找。所以在这里
卡住，别等发版时才发现。

`v` 前缀只有 metadata.yaml 有：市场按 `v0.1.3` 认，Python 包版本按 PEP 440
不能带 `v`。
"""

from __future__ import annotations

import re
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent

_元数据版本 = re.compile(r"^version:\s*(v[0-9.]+)\s*$", re.MULTILINE)
_打包版本 = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_日志小节 = re.compile(r"^## \[([0-9][^\]]*)\] - ", re.MULTILINE)


def _元数据() -> str:
    命中 = _元数据版本.search((仓库根 / "metadata.yaml").read_text(encoding="utf-8"))
    assert 命中, "metadata.yaml 里没有 version 字段"
    return 命中.group(1)


def _打包() -> str:
    命中 = _打包版本.search((仓库根 / "pyproject.toml").read_text(encoding="utf-8"))
    assert 命中, "pyproject.toml 里没有 version 字段"
    return 命中.group(1)


def _日志小节列表() -> list[str]:
    return _日志小节.findall((仓库根 / "docs" / "CHANGELOG.md").read_text(encoding="utf-8"))


def test_元数据带_v_前缀():
    """市场按带 v 的形式认这个字段。"""
    assert _元数据().startswith("v"), "metadata.yaml 的 version 必须带 v 前缀"


def test_打包版本与元数据一致():
    """pyproject.toml 的版本不带 v，比较时要去掉。"""
    元 = _元数据()
    assert _打包() == 元.removeprefix("v"), (
        f"pyproject.toml 是 {_打包()}，metadata.yaml 是 {元}，去掉 v 后应相同。"
        "打 wheel 的版本会按 pyproject 来，两者不一致时装出来的包会报错版本。"
    )


def test_日志里有当前版本的小节():
    裸 = _元数据().removeprefix("v")
    assert 裸 in _日志小节列表(), f"docs/CHANGELOG.md 里没有 [{裸}] 的小节"


def test_日志版本号不重复():
    """同一个版本出现两次，说明改版时复制小节忘了删旧的。"""
    小节 = _日志小节列表()
    重复 = {v for v in 小节 if 小节.count(v) > 1}
    assert not 重复, f"CHANGELOG 里这些版本有小节重复：{sorted(重复)}"


def test_日志版本号单调不降():
    """倒序排列的更新日志里，新版本必须在最前。"""
    小节 = _日志小节列表()

    def _键(v: str) -> tuple:
        return tuple(int(x) for x in re.findall(r"[0-9]+", v))

    键 = [_键(v) for v in 小节]
    assert 键 == sorted(键, reverse=True), f"更新日志的版本顺序不对：{小节}"
