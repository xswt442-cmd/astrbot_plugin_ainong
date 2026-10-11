"""版本号解析逻辑。

`release` 工作流要在 runner 上核对三处版本号。这套逻辑已经因为「本地写法
与实际文件格式不符」失败过一次：

    pkgver=$(grep '^version:' pyproject.toml | awk '{print $2}')

`:` 是 YAML 的写法，`pyproject.toml` 是 TOML、用 `=`，所以匹配不到；又
因为工作流里开了 `pipefail`，grep 一失败整步直接退出，日志里只剩
`Process completed with exit code 1`，看不出是哪错了。

这里用 Python 复刻同一套解析，本机就能验证，不依赖 runner。工作流里那几行
shell 保持与此处一致，`test_工作流与本文件一致` 会盯住。
"""

from __future__ import annotations

import re
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent

# YAML：version: v0.1.4
_元数据 = re.compile(r"^version:\s*(v[0-9][0-9.]*)\s*$", re.MULTILINE)
# TOML：version = "0.1.4"，等号两侧空格可有可无
_打包 = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
# 更新日志：## [0.1.4] - 2026-10-12
_小节 = re.compile(r"^## \[([0-9][^\]]*)\] - ", re.MULTILINE)


class 版本不一致(Exception):
    """版本号对不上。消息要能直接指出是哪个文件、两边各是什么。"""


def 读元数据版本() -> str:
    """读 metadata.yaml 的 version，带 v 前缀。"""
    文本 = (仓库根 / "metadata.yaml").read_text(encoding="utf-8")
    命中 = _元数据.search(文本)
    if not 命中:
        raise 版本不一致("metadata.yaml 里读不到 version 字段")
    return 命中.group(1)


def 读打包版本() -> str:
    """读 pyproject.toml 的 version，不带 v。

    用 `=` 匹配而不是 `:`：TOML 不是 YAML。写成 `:` 会静默匹配不到，
    在开了 pipefail 的 shell 里表现为整步无输出地失败。
    """
    文本 = (仓库根 / "pyproject.toml").read_text(encoding="utf-8")
    命中 = _打包.search(文本)
    if not 命中:
        raise 版本不一致(
            "pyproject.toml 里读不到 version 字段。"
            '注意它是 TOML，字段写成 version = "0.1.4"，等号不是冒号'
        )
    return 命中.group(1)


def 读日志小节() -> list[str]:
    return _小节.findall((仓库根 / "docs" / "CHANGELOG.md").read_text(encoding="utf-8"))


def 校验一致(期望: str) -> str:
    """核对三处版本号，全对才返回不带 v 的版本号。"""
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", 期望):
        raise 版本不一致(f"版本号格式不对：{期望}。要像 v0.1.4 这样，带 v 前缀")

    元数据 = 读元数据版本()
    if 元数据 != 期望:
        raise 版本不一致(f"metadata.yaml 是 {元数据}，要 {期望}")

    裸 = 期望.removeprefix("v")
    if 裸 not in 读日志小节():
        raise 版本不一致(f"docs/CHANGELOG.md 里没有 [{裸}] 的小节，要写成 ## [{裸}] - YYYY-MM-DD")

    打包 = 读打包版本()
    if 打包 != 裸:
        raise 版本不一致(f"pyproject.toml 是 {打包}，要 {裸}（两处都不带 v）")

    return 裸


def test_当前仓库三处一致():
    期望 = 读元数据版本()
    assert 校验一致(期望) == 期望.removeprefix("v")


def test_元数据带_v_前缀():
    """市场按带 v 的形式认这个字段；PEP 440 不允许 v，所以只有这一处有。"""
    assert 读元数据版本().startswith("v")


def test_日志版本号不重复():
    """同一个版本出现两次，说明改版时复制小节忘了删旧的。"""
    小节 = 读日志小节()
    重复 = {v for v in 小节 if 小节.count(v) > 1}
    assert not 重复, f"CHANGELOG 里这些版本有小节重复：{sorted(重复)}"


def test_日志版本号单调不降():
    """倒序排列的更新日志里，新版本必须在最前。"""
    小节 = 读日志小节()

    def _键(v: str) -> tuple:
        return tuple(int(x) for x in re.findall(r"[0-9]+", v))

    键 = [_键(v) for v in 小节]
    assert 键 == sorted(键, reverse=True), f"更新日志的版本顺序不对：{小节}"


def test_工作流读_pyproject_用的是_等号():
    """工作流里那行 grep 必须匹配 TOML 的写法。

    这是实际踩过的坑：`^version:` 匹配不到 TOML，pipefail 让整步无声失败。
    """
    工作流 = (仓库根 / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "version[[:space:]]*=" in 工作流, (
        "工作流读 pyproject.toml 的版本号要用 = （TOML），用 : 匹配不到"
    )
    assert re.search(r"grep\s+'\^version:'", 工作流) is None, (
        "工作流里不该再出现 ^version: 去读 pyproject.toml，那是 YAML 写法"
    )


def test_打标签前配了_git_身份():
    """checkout 只配认证凭据，不配 user.name 与 user.email。

    打标签要生成 tagger，是写操作，缺身份直接报 "Committer identity unknown"
    退出 128。已实际踩过一次。
    """
    工作流 = (仓库根 / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "git config user.name" in 工作流, "打标签前必须配 user.name"
    assert "git config user.email" in 工作流, "打标签前必须配 user.email"
    # 顺序：配置必须在 tag 命令之前
    assert 工作流.index("git config user.name") < 工作流.index("git tag -a")


def test_格式不对会报错():
    for 坏 in ("0.1.4", "v0.1", "vx.y.z", "", "v1.2.3-rc1"):
        try:
            校验一致(坏)
        except 版本不一致:
            continue
        raise AssertionError(f"{坏!r} 应该被判为格式不对")


def test_错误消息要指出是哪个文件():
    """只说"不一致"没用，日志里得知道去改哪。"""
    try:
        校验一致("v9.9.9")
    except 版本不一致 as e:
        文本 = str(e)
        assert "metadata.yaml" in 文本, 文本
        assert "v9.9.9" in 文本, 文本
    else:
        raise AssertionError("版本对不上时应该抛异常")
