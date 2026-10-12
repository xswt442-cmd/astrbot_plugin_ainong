"""凭据与绑定的本地存储。

一个 Bot 用户绑一个营地账号，账号下有多个游戏角色，用户可以切换当前
用哪个。凭据属于营地账号，所以按 Bot 用户分文件存——Bot 用户之间互不
可见。

文件内容不进日志、不进异常消息。解绑时删文件，不保留。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

__all__ = ["凭据仓库"]

_凭据字段 = ("营地ID", "令牌", "对称密钥")
_文件名后缀 = ".json"


class 凭据仓库:
    def __init__(self, 目录: Path) -> None:
        self.目录 = 目录

    def 路径(self, 用户: str) -> Path:
        """用户标识不直接当文件名——QQ 号可能带@和斜杠。取摘要即可。"""
        摘要 = hashlib.sha256(用户.encode("utf-8")).hexdigest()[:32]
        return self.目录 / f"{摘要}{_文件名后缀}"

    def 读取(self, 用户: str) -> dict[str, Any] | None:
        路径 = self.路径(用户)
        try:
            载荷 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(载荷, dict):
            return None
        if not all(载荷.get(字段) for 字段 in _凭据字段):
            return None
        return 载荷

    def 写入(self, 用户: str, 账号: dict[str, Any]) -> None:
        self.目录.mkdir(parents=True, exist_ok=True)
        路径 = self.路径(用户)
        # 顺手把用户标识与昵称一起存下来。文件名是标识的哈希，反推不回去，
        # 而 PK 要按昵称找人、再拿标识去查战绩，两样都得在文件里。
        载荷 = {**账号, "用户": 用户}
        路径.write_text(json.dumps(载荷, ensure_ascii=False), encoding="utf-8")
        if os.name == "posix":
            路径.chmod(0o600)

    def 全部(self) -> list[dict[str, Any]]:
        """所有已绑定的记录。损坏或字段不全的文件直接跳过。"""
        try:
            文件们 = sorted(self.目录.glob(f"*{_文件名后缀}"))
        except OSError:
            return []

        结果 = []
        for 路径 in 文件们:
            try:
                载荷 = json.loads(路径.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(载荷, dict) and all(载荷.get(字段) for 字段 in _凭据字段):
                结果.append(载荷)
        return 结果

    def 按昵称找(self, 昵称: str) -> list[dict[str, Any]]:
        """按平台显示名找人。完全命中优先，其次是不区分大小写的子串。

        走这条路是因为 QQ 官方平台拿不到被 @ 的人的标识：适配器只把「@机器人」
        转成组件，@别人在事件里连痕迹都没有（实测组件与正文都为空）。所以群里
        PK 只能靠名字点人。
        """
        目标 = (昵称 or "").strip().lower()
        if not 目标:
            return []
        记录们 = self.全部()
        精确 = [记录 for 记录 in 记录们 if str(记录.get("昵称", "")).strip().lower() == 目标]
        if 精确:
            return 精确
        return [记录 for 记录 in 记录们 if 目标 in str(记录.get("昵称", "")).strip().lower()]

    def 删除(self, 用户: str) -> dict[str, Any] | None:
        记录 = self.读取(用户)
        if 记录 is None:
            return None
        try:
            self.路径(用户).unlink()
        except OSError:
            return None
        return 记录

    def 当前角色(self, 用户: str) -> str:
        记录 = self.读取(用户)
        return str(记录.get("角色ID", "")) if 记录 else ""

    def 选角色(self, 用户: str, 角色ID: str) -> bool:
        记录 = self.读取(用户)
        if 记录 is None:
            return False
        记录["角色ID"] = 角色ID
        self.写入(用户, 记录)
        return True
