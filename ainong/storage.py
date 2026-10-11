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

    def 写入(self, 用户: str, 账号: dict[str, str]) -> None:
        self.目录.mkdir(parents=True, exist_ok=True)
        路径 = self.路径(用户)
        路径.write_text(json.dumps(账号, ensure_ascii=False), encoding="utf-8")
        if os.name == "posix":
            路径.chmod(0o600)

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
