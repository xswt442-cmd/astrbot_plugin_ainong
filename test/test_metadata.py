"""metadata.yaml 里市场可见的字段。

这些字段错了不会让安装失败，只会在插件详情页上显示成 `[MISSING: ...]` 或
落到默认分类里，而那要等市场索引刷新才看得到，本地和 CI 里都没有任何提示。
所以在这里校验。

分类的合法取值来自市场自己那套（ AstrBot Cloud 的分类枚举），从已上架的
两千多个插件反推出来的。九个中文分类：其他、工具、娱乐、三方集成、生活、
长期记忆、知识库库、AI 增强、语音。
"""

from __future__ import annotations

from pathlib import Path

import yaml

仓库根 = Path(__file__).resolve().parent.parent
元数据路径 = 仓库根 / "metadata.yaml"

# 市场自己用的分类枚举。填错的话市场不报错，只是归到「其他」或者显示
# [MISSING]，所以必须在这里拦。
合法分类 = {
    "其他",
    "工具",
    "娱乐",
    "三方集成",
    "生活",
    "长期记忆",
    "知识库",
    "AI 增强",
    "语音",
}


def _元数据() -> dict:
    with 元数据路径.open(encoding="utf-8") as 文件:
        return yaml.safe_load(文件)


def test_元数据能解析():
    """YAML 写坏了这里就会炸，比等市场解析失败早。"""
    数据 = _元数据()
    assert isinstance(数据, dict), "metadata.yaml 解析结果不是字典"
    assert 数据, "metadata.yaml 是空的"


def test_分类填了且合法():
    """不填会被默认成「其他」，详情页显示成 [MISSING: ...其他]。"""
    分类 = _元数据().get("category")
    assert 分类, "metadata.yaml 缺 category，市场会归到「其他」并在详情页显示 [MISSING]"
    assert 分类 in 合法分类, f"category={分类!r} 不在市场分类里。可选：{sorted(合法分类)}"


def test_标签是列表():
    """tags 要写成 YAML 列表。写成逗号分隔的字符串，市场不会拆。"""
    标签 = _元数据().get("tags")
    assert 标签, "metadata.yaml 缺 tags，市场搜索里不好找"
    assert isinstance(标签, list), f"tags 要是列表，现在是 {type(标签).__name__}"
    assert all(isinstance(t, str) and t.strip() for t in 标签), f"标签得都是非空字符串：{标签}"


def test_标签含游戏():
    """游戏类插件的惯例是打「游戏」标签，搜索按标签过滤。"""
    assert "游戏" in (_元数据().get("tags") or []), "tags 里应有「游戏」"


def test_简介字段齐全():
    """界面上会显示这些，缺一个就少一块信息。"""
    数据 = _元数据()
    for 字段 in ("name", "display_name", "short_desc", "desc", "version", "author", "repo"):
        assert 数据.get(字段), f"metadata.yaml 缺 {字段}"


def test_简介长度适合界面():
    """short_desc 显示在紧凑位置，塞太长会溢出或被截。"""
    短 = _元数据().get("short_desc", "")
    assert len(短) <= 40, f"short_desc {len(短)} 字，太长了，建议控制在 40 字内"
