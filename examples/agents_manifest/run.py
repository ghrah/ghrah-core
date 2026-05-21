# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""基于 manifest 的多 Agent 并行协作示例。

使用 YAML manifest 声明式定义 Agent，替代原 Python 代码式配置。
场景与 multi_agent_parallel.py 完全一致：
    planner → coder → reviewer 三阶段协作。

目录结构：
    examples/agents_manifest/
    ├── agents/          # Agent manifest YAML
    │   ├── planner.yaml
    │   ├── coder.yaml
    │   └── reviewer.yaml
    ├── runner.py        # ManifestRunner：manifest → 运行时桥接（基于 ManifestResolver）
    └── run.py           # 本文件：主入口

用法：
    cd ghrah-core
    uv run python examples/agents_manifest/run.py

前置条件：
    已配置 agentconf（参见 multi_agent_parallel.py 的详细说明）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from runner import ManifestRunner

from ghrah.communication import SupervisorActor
from ghrah.core.config import AgentConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

EXAMPLES_DIR = Path(__file__).resolve().parent


def create_workspace() -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    temp_root = Path("./test") / f"ghrah_manifest_{ts}"
    temp_root.mkdir(parents=True, exist_ok=True)

    workspace = temp_root / "agentsworkspace"
    persistence_dir = temp_root / "agentactionchain"
    workspace.mkdir(parents=True, exist_ok=True)
    persistence_dir.mkdir(parents=True, exist_ok=True)
    for p in ["coder","planner","reviewer"]:
        agent_workspace = workspace / p
        agent_workspace.mkdir(parents=True, exist_ok=True)

    logger.info("工作区已创建: %s", temp_root)
    return temp_root


async def main() -> None:
    temp_root = create_workspace()
    workspace = temp_root / "agentsworkspace"
    persistence_dir = temp_root / "agentactionchain"

    session_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    session_id = f"session_{session_ts}"

    print("=" * 60)
    print("基于 Manifest 的多 Agent 并行协作示例")
    print(f"工作区: {temp_root}")
    print("=" * 60)

    runner = ManifestRunner(
        workspace=workspace,
        persistence_dir=persistence_dir,
        session_id=session_id,
    )

    agents_dir = EXAMPLES_DIR / "agents"
    manifests = runner.load_manifests_from_dir(agents_dir)
    print(f"\n已加载 {len(manifests)} 个 Agent manifest:")
    for m in manifests:
        print(f"  - {m.full_name} ({m.metadata.description})")

    supervisor = SupervisorActor()

    print("\n" + "=" * 60)
    print("注册 Agent...")
    resolved: list[tuple[str, AgentConfig]] = []
    for manifest in manifests:
        config, abilities = runner.resolve(manifest)
        registered_name = await supervisor.spawn_agent(config, abilities=abilities)
        print(f"  ✓ Agent 注册成功: {registered_name}")
        resolved.append((registered_name, manifest))

    print("\n" + "=" * 60)
    print("健康检查:")
    health = await supervisor.health_check()
    for name, is_healthy in health.items():
        status = "✓ 健康" if is_healthy else "✗ 不健康"
        print(f"  - {name}: {status}")

    # 阶段 1: planner
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

    # 阶段 2: coder
    print("=" * 60)
    print("阶段 2: Coder 根据设计编写代码...")
    print("-" * 60)

    # design_file = workspace / "planner" / "design.md"
    # if design_file.exists():
    #     with open(design_file) as f:
    #         design_content = f.read()
    #     print(f"  已读取设计文档 ({len(design_content)} 字符)")
    # else:
    #     design_content = planner_response
    #     print("  设计文档不存在，使用 planner 回复作为设计")

    coder_prompt = (
        f"请根据以下设计文档编写 Python 代码。\n\n"
        f"设计文档内容位于:{workspace / 'planner' } 下\n"
        f"首先阅读设计文档，然后开始实现 \n"
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

    # 阶段 3: reviewer
    print("=" * 60)
    print("阶段 3: Reviewer 审查代码...")
    print("-" * 60)

    coder_dir = workspace / "coder"
    code_files: list[str] = []
    if coder_dir.exists():
        code_files = sorted(f.name for f in coder_dir.iterdir() if f.suffix == ".py")
    print(f"  发现代码文件: {code_files}")

    code_contents: list[str] = []
    for fname in code_files:
        fpath = coder_dir / fname
        with open(fpath) as f:
            content = f.read()
        code_contents.append(f"### {fname}\n```python\n{content}\n```")

    all_code = "\n\n".join(code_contents)

    reviewer_prompt = (
        f"请审查以下 Python 代码，"
        f"并将审查报告写入 {workspace / 'reviewer' / 'review_report.md'}。\n\n"
        f"代码内容:\n{all_code}\n\n"
        f"审查要点：\n"
        f"1. 代码质量和可读性评分（1-10）\n"
        f"2. 潜在的 Bug 或安全问题\n"
        f"3. 问题以严重，中等，轻微进行分组\n"
        f"4. 针对以上问题的优化建议（如有）\n"
        f"请将报告保存到文件中。"
    )

    reviewer_response = await supervisor.send("reviewer", reviewer_prompt)
    print(f"  Reviewer 回复:\n{reviewer_response[:500]}...")

    fix_prompt = (
        "代码审查者对你的实现提出了一些改进意见,"
        f"使用读取文件的工具查看{workspace / 'reviewer' / 'review_report.md'} \n\n"
        f"修复其中被评定为中等或以上的问题"
    )
    coder_response_2 = await supervisor.send("coder", fix_prompt)
    print(f"  Coder 回复:\n{coder_response[:500]}...")
    print()

    print(f"  Coder 回复:\n{coder_response_2[:500]}...")
    # 结果汇总
    print("=" * 60)
    print("结果汇总")
    print("=" * 60)

    print("\n工作区文件:")
    for agent_name in ("planner", "coder", "reviewer"):
        agent_dir = workspace / agent_name
        if agent_dir.exists():
            files = sorted(f.name for f in agent_dir.iterdir() if f.is_file())
            print(f"  {agent_name}/:")
            for fname in files:
                fpath = agent_dir / fname
                size = fpath.stat().st_size
                print(f"    - {fname} ({size} bytes)")

    print(f"\n持久化输出目录: {persistence_dir}")
    session_dir = persistence_dir / session_id
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

    # 清理
    print("\n" + "=" * 60)
    print("清理资源...")
    agents = await supervisor.list_agents()
    for agent in agents:
        await supervisor.terminate_agent(agent["name"])
        print(f"  ✓ Agent 已终止: {agent['name']}")

    print("\n示例运行完成！")
    print(f"工作区位置: {temp_root}")
    print(f"持久化位置: {persistence_dir}")


if __name__ == "__main__":
    asyncio.run(main())
