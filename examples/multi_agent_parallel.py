# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""多 Agent 并行协作示例 — 带文件系统权限和 JSON 持久化。

场景：
    三个 Agent 协作编写一个小型 Python 项目：
    1. planner（规划者）：分析需求，生成项目结构设计文档
    2. coder（编码者）：根据设计编写代码文件
    3. reviewer（审查者）：读取代码文件，输出审查报告

    工作流程：
        planner 先完成设计 → 将设计传给 coder → coder 完成后 reviewer 开始审查

目录结构：
    /tmp/ghrah_multi_agent_<timestamp>/
    ├── agentsworkspace/           # Agent 工作区
    │   ├── planner/               # planner 的工作区
    │   ├── coder/                 # coder 的工作区
    │   └── reviewer/              # reviewer 的工作区
    └── agentactionchain/          # JSON 持久化输出
        └── session_<id>/
            ├── planner/
            ├── coder/
            └── reviewer/

前置条件：
    1. 已配置 agentconf（运行 `agentconf --help` 查看配置方法）
    2. 至少配置了以下 Agent：
       - planner
       - coder
       - reviewer

用法：
    uv run python examples/multi_agent_parallel.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from ghrah.abilities.builtin import (
    ConversationAbility,
    EndTaskAbility,
    FSPermissionChecker,
    ListDirectoryAbility,
    ReadFileAbility,
    WriteFileAbility,
)
from ghrah.communication import SupervisorActor
from ghrah.core.config import AgentConfig, ContextConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# 工作区路径配置
# ============================================================================

def create_workspace() -> Path:
    """创建临时工作区目录结构。

    Returns:
        临时目录根路径
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    # temp_root = Path(tempfile.gettempdir()) / f"ghrah_multi_agent_{ts}"
    temp_root = Path("./test") / f"ghrah_multi_agent_{ts}"
    temp_root.mkdir(parents=True, exist_ok=True)

    # 创建 Agent 工作区子目录
    workspace = temp_root / "agentsworkspace"
    for agent_name in ("planner", "coder", "reviewer"):
        (workspace / agent_name).mkdir(parents=True, exist_ok=True)

    # 创建持久化输出目录
    (temp_root / "agentactionchain").mkdir(parents=True, exist_ok=True)

    logger.info(f"工作区已创建: {temp_root}")
    return temp_root


# ============================================================================
# 权限检查器工厂
# ============================================================================

def make_checker(workspace: Path, agent_name: str) -> FSPermissionChecker:
    """为指定 Agent 创建文件系统权限检查器。

    每个 Agent 只能读写自己的工作区子目录。
    特殊情况：
        coder 可以读取planner的设计文档
        reviewer 还可以读取 coder 的工作区

    Args:
        workspace: agentsworkspace 根目录路径
        agent_name: Agent 名称

    Returns:
        配置好的 FSPermissionChecker
    """
    allowed_paths: list[str] = [str(workspace / agent_name)]
    # 允许coder 读取设计文档
    if agent_name == "coder":
        allowed_paths.append(str(workspace / "planner"))
    # reviewer 需要读取 coder 的工作区代码
    if agent_name == "reviewer":
        allowed_paths.append(str(workspace / "coder"))

    return FSPermissionChecker(
        allowed_paths=allowed_paths,
        require_approval=False,  # 自动批准，无需人工确认
    )


# ============================================================================
# Agent Ability 组合
# ============================================================================

def make_planner_abilities(checker: FSPermissionChecker) -> list:
    """创建 planner 的 Ability 组合：对话 + 结束 + 写文件 + 列目录。"""
    return [
        ConversationAbility(),
        EndTaskAbility(),
        WriteFileAbility(permission_checker=checker),
        ListDirectoryAbility(permission_checker=checker),
    ]


def make_coder_abilities(checker: FSPermissionChecker) -> list:
    """创建 coder 的 Ability 组合：对话 + 结束 + 读写文件 + 列目录。"""
    return [
        ConversationAbility(),
        EndTaskAbility(),
        ReadFileAbility(permission_checker=checker),
        WriteFileAbility(permission_checker=checker),
        ListDirectoryAbility(permission_checker=checker),
    ]


def make_reviewer_abilities(read_checker: FSPermissionChecker, write_checker: FSPermissionChecker) -> list:
    """创建 reviewer 的 Ability 组合：对话 + 结束 + 读文件（多路径） + 写文件 + 列目录。"""
    return [
        ConversationAbility(),
        EndTaskAbility(),
        ReadFileAbility(permission_checker=read_checker),
        WriteFileAbility(permission_checker=write_checker),
        ListDirectoryAbility(permission_checker=read_checker),
    ]


# ============================================================================
# 主流程
# ============================================================================

async def main() -> None:
    """运行多 Agent 并行协作示例。"""

    # 1. 创建工作区
    temp_root = create_workspace()
    workspace = temp_root / "agentsworkspace"
    persistence_dir = temp_root / "agentactionchain"

    print("=" * 60)
    print("多 Agent 并行协作示例")
    print(f"工作区: {temp_root}")
    print("=" * 60)

    # 2. 创建 Supervisor
    supervisor = SupervisorActor()

    # 3. 创建共享的持久化 session_id（确保所有 Agent 使用同一个 session）
    session_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    shared_session_id = f"session_{session_ts}"

    # 4. 定义 Agent 配置
    agents_config = [
        AgentConfig(
            name="planner",
            description="任务规划专家，负责分解复杂任务并输出设计文档",
            system_prompt=(
                "你是一个任务规划专家。请将复杂任务分解为清晰的步骤，"
                "并以 Markdown 格式输出设计文档。"
                "你可以使用 write_file 工具将设计文档写入文件系统。"
                "请确保你的输出简洁而完整。"
                "完成设计后请使用 end_task 结束。"
            ),
            max_iterations=5,
            context=ContextConfig(
                auto_persist=True,
                persistence_type="json_file",
                persistence_root_dir=str(persistence_dir),
                persistence_compress=False,
                persistence_run_id=shared_session_id,
            ),
        ),
        AgentConfig(
            name="coder",
            description="代码编写专家，根据设计文档实现代码",
            system_prompt=(
                "你是一个代码编写专家。请根据提供的设计文档编写高质量的 Python 代码。"
                "你可以使用 read_file 读取设计文档，使用 write_file 写入代码文件。"
                "每个文件作为独立模块编写，保持代码简洁清晰。"
                "完成编码后请使用 end_task 结束。"
            ),
            max_iterations=8,
            context=ContextConfig(
                auto_persist=True,
                persistence_type="json_file",
                persistence_root_dir=str(persistence_dir),
                persistence_compress=False,
                persistence_run_id=shared_session_id,
            ),
        ),
        AgentConfig(
            name="reviewer",
            description="代码审查专家，审查代码并提供改进建议",
            system_prompt=(
                "你是一个代码审查专家。请审查提供的代码，从以下角度进行评估：\n"
                "1. 代码质量和可读性\n"
                "2. 潜在的 Bug 或安全问题\n"
                "3. 性能优化建议\n"
                "4. 改进建议\n"
                "请将审查报告以 Markdown 格式使用 write_file 写入文件。"
                "完成审查后请使用 end_task 结束。"
            ),
            max_iterations=5,
            context=ContextConfig(
                auto_persist=True,
                persistence_type="json_file",
                persistence_root_dir=str(persistence_dir),
                persistence_compress=False,
                persistence_run_id=shared_session_id,
            ),
        ),
    ]

    # 5. 注册所有 Agent（带文件系统 Ability）
    print("\n" + "=" * 60)
    print("注册 Agent...")
    for config in agents_config:
        name = config.name
        checker = make_checker(workspace, name)

        if name == "planner":
            abilities = make_planner_abilities(checker)
        elif name == "coder":
            abilities = make_coder_abilities(checker)
        elif name == "reviewer":
            # reviewer 需要两个 checker：读取（coder + reviewer）和写入（reviewer）
            read_checker = FSPermissionChecker(
                allowed_paths=[str(workspace / "coder"), str(workspace / "reviewer")],
                require_approval=False,
            )
            write_checker = FSPermissionChecker(
                allowed_paths=[str(workspace / "reviewer")],
                require_approval=False,
            )
            abilities = make_reviewer_abilities(read_checker, write_checker)
        else:
            abilities = [ConversationAbility(), EndTaskAbility()]

        registered_name = await supervisor.spawn_agent(config, abilities=abilities)
        print(f"  ✓ Agent 注册成功: {registered_name}")

    # 6. 健康检查
    print("\n" + "=" * 60)
    print("健康检查:")
    health = await supervisor.health_check()
    for name, is_healthy in health.items():
        status = "✓ 健康" if is_healthy else "✗ 不健康"
        print(f"  - {name}: {status}")

    # ====================================================================
    # 阶段 1：planner 独立完成设计
    # ====================================================================
    print("\n" + "=" * 60)
    print("阶段 1: Planner 设计项目结构...")
    print("-" * 60)

    planner_prompt = (
        f"请设计一个简单的 Python 命令行计算器程序。要求：\n"
        f"1. 支持加减乘除四则运算\n"
        f"2. 使用模块化设计\n"
        f"3. 输出设计文档到 {workspace / 'planner'}\n\n"
        f"设计文档应包含：\n"
        f"- 模块划分（以文件为单位）\n"
        f"- 每个模块的职责说明\n"
        f"- 模块间的依赖关系\n\n"
        f"请保持设计简洁，不超过 3 个文件。"
    )

    planner_response = await supervisor.send("planner", planner_prompt)
    print(f"  Planner 回复:\n{planner_response[:500]}...")
    print()

    # ====================================================================
    # 阶段 2：coder 根据设计编写代码
    # ====================================================================
    print("=" * 60)
    print("阶段 2: Coder 根据设计编写代码...")
    print("-" * 60)

    # 读取 planner 生成的设计文档
    design_file = workspace / "planner" / "design.md"
    if design_file.exists():
        with open(design_file) as f:
            design_content = f.read()
        print(f"  已读取设计文档 ({len(design_content)} 字符)")
    else:
        design_content = planner_response
        print("  设计文档不存在，使用 planner 回复作为设计")

    coder_prompt = (
        f"请根据以下设计文档编写 Python 代码。\n\n"
        f"设计文档内容:\n{design_content}\n\n"
        f"要求：\n"
        f"1. 将每个模块写入独立文件，放在 {workspace / 'coder'}/ 目录下\n"
        f"2. 文件名使用小写下划线命名法\n"
        f"3. 包含必要的注释和类型注解\n"
        f"4. 确保代码可以直接运行\n\n"
        f"请开始编写代码。"
    )

    coder_response = await supervisor.send("coder", coder_prompt)
    print(f"  Coder 回复:\n{coder_response[:500]}...")
    print()

    # ====================================================================
    # 阶段 3：reviewer 审查代码
    # ====================================================================
    print("=" * 60)
    print("阶段 3: Reviewer 审查代码...")
    print("-" * 60)

    # 列出 coder 工作区的文件
    coder_dir = workspace / "coder"
    code_files = []
    if coder_dir.exists():
        code_files = sorted(
            f.name for f in coder_dir.iterdir() if f.suffix == ".py"
        )
    print(f"  发现代码文件: {code_files}")

    # 读取所有代码文件内容
    code_contents = []
    for fname in code_files:
        fpath = coder_dir / fname
        with open(fpath) as f:
            content = f.read()
        code_contents.append(f"### {fname}\n```python\n{content}\n```")

    all_code = "\n\n".join(code_contents)

    reviewer_prompt = (
        f"请审查以下 Python 代码，并将审查报告写入 {workspace / 'reviewer' / 'review_report.md'}。\n\n"
        f"代码内容:\n{all_code}\n\n"
        f"审查要点：\n"
        f"1. 代码质量和可读性评分（1-10）\n"
        f"2. 潜在的 Bug 或安全问题\n"
        f"3. 性能优化建议\n"
        f"4. 具体的改进建议（如有）\n\n"
        f"请将报告保存到文件中。"
    )

    reviewer_response = await supervisor.send("reviewer", reviewer_prompt)
    print(f"  Reviewer 回复:\n{reviewer_response[:500]}...")
    print()

    # ====================================================================
    # 结果汇总
    # ====================================================================
    print("=" * 60)
    print("结果汇总")
    print("=" * 60)

    # 检查生成的文件
    print("\n📄 工作区文件:")
    for agent_name in ("planner", "coder", "reviewer"):
        agent_dir = workspace / agent_name
        if agent_dir.exists():
            files = sorted(f.name for f in agent_dir.iterdir() if f.is_file())
            print(f"  {agent_name}/:")
            for fname in files:
                fpath = agent_dir / fname
                size = fpath.stat().st_size
                print(f"    - {fname} ({size} bytes)")

    # 检查持久化输出
    print(f"\n💾 持久化输出目录: {persistence_dir}")
    session_dir = persistence_dir / shared_session_id
    if session_dir.exists():
        for agent_dir in sorted(session_dir.iterdir()):
            if agent_dir.is_dir():
                files = sorted(f.name for f in agent_dir.iterdir() if f.is_file())
                print(f"  {agent_dir.name}/:")
                for fname in files:
                    fpath = agent_dir / fname
                    size = fpath.stat().st_size
                    print(f"    - {fname} ({size} bytes)")
    else:
        print("  (未找到持久化数据)")

    # ====================================================================
    # 清理
    # ====================================================================
    print("\n" + "=" * 60)
    print("清理资源...")
    agents = await supervisor.list_agents()
    for agent in agents:
        await supervisor.terminate_agent(agent["name"])
        print(f"  ✓ Agent 已终止: {agent['name']}")

    print("\n✅ 示例运行完成！")
    print(f"工作区位置: {temp_root}")
    print(f"持久化位置: {persistence_dir}")


if __name__ == "__main__":
    asyncio.run(main())
