"""工具注册表：名称 → 实现 + 声明（参数 schema、只读/写、描述）.

写工具必须显式声明 side_effect=True，护栏据此拦截未授权写操作。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

ToolFn = Callable[..., dict[str, Any]]


@dataclass
class ToolDecl:
    name: str
    description: str
    params: dict[str, str]              # 参数名 → 类型/说明
    required: list[str] = field(default_factory=list)
    side_effect: bool = False           # True = 写操作，默认需审批


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDecl, ToolFn]] = {}

    def register(self, decl: ToolDecl, fn: ToolFn) -> None:
        if decl.name in self._tools:
            raise ValueError(f"tool duplicated: {decl.name}")
        # 声明的参数必须与函数签名一致（防声明与实现漂移）；下划线开头为内部参数
        sig = {p for p in inspect.signature(fn).parameters if not p.startswith("_")}
        if set(decl.params) != sig:
            raise ValueError(
                f"tool {decl.name}: declared params {sorted(decl.params)} != signature {sorted(sig)}"
            )
        for req in decl.required:
            if req not in decl.params:
                raise ValueError(f"tool {decl.name}: required '{req}' not in params")
        self._tools[decl.name] = (decl, fn)

    def get(self, name: str) -> tuple[ToolDecl, ToolFn] | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def decls(self) -> list[ToolDecl]:
        return [self._tools[n][0] for n in self.names()]

    def write_tools(self) -> list[str]:
        return [n for n in self.names() if self._tools[n][0].side_effect]
