# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""InitProjectAbility：项目脚手架初始化能力。

根据 project_type 参数调用 CLI 工具创建项目骨架：
- backend: 使用 uv init 创建空 Python 项目
- frontend: 使用 pnpm create vite --template vue-ts 创建 Vue 3 + TypeScript 项目
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ghrah.abilities.base import Ability, ActionOutcome, ActionResult
from ghrah.abilities.builtin.fs_permissions import FSPermissionChecker

if TYPE_CHECKING:
    from ghrah.abilities.context import AbilityExecutionContext
    from ghrah.abilities.hooks import Hook

logger = logging.getLogger(__name__)

__all__ = ["InitProjectAbility"]


class InitProjectInput(BaseModel):
    project_type: str
    target_dir: str


class InitProjectAbility(Ability):
    """项目脚手架初始化能力。

    根据 project_type 调用 CLI 工具创建项目骨架：
    - backend: uv init <target_dir>
    - frontend: pnpm create vite <target_dir> --template vue-ts && pnpm install
    """

    def __init__(
        self,
        workspace_root: str | None = None,
        hooks: list[Hook] | None = None,
        permission_checker: FSPermissionChecker | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._hooks = hooks or []
        self._checker = permission_checker

    @property
    def name(self) -> str:
        return "init_project"

    def bind_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "init_project",
                "description": (
                    "Initialize a project scaffolding using CLI tools. "
                    "Creates either a Python project (uv init) or a Vue 3 + TypeScript "
                    "frontend project (pnpm create vite --template vue-ts). "
                    "Returns the created directory path and tool output."
                ),
                "parameters": InitProjectInput.model_json_schema(),
            },
        }

    def to_prompt_description(self) -> str:
        return (
            "init_project(project_type: str, target_dir: str) -> dict: "
            "Initialize project scaffolding via CLI tools. "
            "project_type='backend' calls uv init, "
            "project_type='frontend' calls pnpm create vite --template vue-ts."
        )

    def get_hooks(self) -> list[Hook]:
        return list(self._hooks)

    async def execute(self, context: AbilityExecutionContext) -> ActionResult:
        tool_args = context.tool_args or context.accumulated_data.get("tool_args", {})
        project_type = tool_args.get("project_type", "")
        target_dir = tool_args.get("target_dir", "")

        if not project_type:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "project_type is required"},
            )
        if not target_dir:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": "target_dir is required"},
            )
        if project_type not in ("backend", "frontend"):
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"project_type must be 'backend' or 'frontend', got '{project_type}'"},
            )

        if self._checker is not None:
            allowed, reason = self._checker.check_write_path(target_dir)
            if not allowed:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    data={"error": reason},
                )

        target_path = os.path.abspath(target_dir)

        if os.path.exists(target_path) and os.listdir(target_path):
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"Target directory '{target_path}' already exists and is not empty"},
            )

        try:
            if project_type == "frontend":
                return await self._init_frontend(target_path)
            else:
                return await self._init_backend(target_path)
        except FileNotFoundError as exc:
            cli_name = "pnpm" if project_type == "frontend" else "uv"
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={"error": f"{cli_name} CLI not found. Please install {cli_name} first.", "detail": str(exc)},
            )

    async def _init_frontend(self, target_path: str) -> ActionResult:
        result = subprocess.run(
            ["pnpm", "create", "vue@latest", target_path, "--ts", "--router" ,"--pinia","--force"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={
                    "error": f"pnpm create vite failed: {result.stderr}",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )

        install_result = subprocess.run(
            ["pnpm", "install"],
            cwd=target_path,
            capture_output=True,
            text=True,
        )
        if install_result.returncode != 0:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={
                    "error": f"pnpm install failed: {install_result.stderr}",
                    "stdout": install_result.stdout,
                    "stderr": install_result.stderr,
                },
            )

        logger.info("InitProjectAbility: created frontend project at %s", target_path)

        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={
                "project_type": "frontend",
                "target_dir": target_path,
                "tool": "pnpm create vite --template vue-ts",
                "stdout": result.stdout,
            },
        )

    async def _init_backend(self, target_path: str) -> ActionResult:
        result = subprocess.run(
            ["uv", "init", target_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                data={
                    "error": f"uv init failed: {result.stderr}",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )

        logger.info("InitProjectAbility: created backend project at %s", target_path)

        return ActionResult(
            outcome=ActionOutcome.SUCCESS,
            data={
                "project_type": "backend",
                "target_dir": target_path,
                "tool": "uv init",
                "stdout": result.stdout,
            },
        )
