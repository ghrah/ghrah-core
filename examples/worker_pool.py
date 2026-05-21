# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""Worker 池示例 — 演示 agent_config_name 实现多 Agent 共享 LLM 配置。

场景：
    多个 solve_worker 并行处理不同的任务，它们共享同一份 agentconf 配置。
    通过 agent_config_name 字段，运行时名称（solve_worker_0, solve_worker_1, ...）
    可以与 agentconf 中的配置名称（solve_worker）分离。

    这解决了以下问题：
    - 动态创建的 worker（如 solve_worker_3）在 agentconf 中不存在
    - 避免在 agentconf 中为每个 worker 创建重复配置
    - 支持运行时名称与 LLM 配置名称的灵活映射

前置条件：
    1. 已配置 agentconf（运行 `agentconf --help` 查看配置方法）
    2. 至少配置了以下 Agent：
       - planner
       - solve_worker
    注意：只需要创建一个 solve_worker 配置，所有 worker 实例共享此配置。

用法：
    uv run python examples/worker_pool.py
"""

from __future__ import annotations

import asyncio
import logging

from ghrah.communication import SupervisorActor
from ghrah.core.config import AgentConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """运行 Worker 池示例。"""

    # Worker 池大小
    NUM_WORKERS = 3

    print("=" * 60)
    print("Worker 池示例 — agent_config_name 演示")
    print("=" * 60)

    # 1. 创建 Supervisor
    supervisor = SupervisorActor()

    # 2. 创建 planner Agent（name 与 agentconf 配置名称一致，无需 agent_config_name）
    planner_config = AgentConfig(
        name="planner",
        description="任务规划专家，负责分解问题并分配给 worker",
        system_prompt=(
            "你是一个任务规划专家。请将复杂问题分解为多个独立的子任务，"
            "每个子任务应该可以由一个 worker 独立完成。"
            "请以编号列表的形式输出子任务。"
            "完成规划后请使用 end_task 结束。"
        ),
        max_iterations=5,
    )

    # 3. 创建 worker 池（关键：agent_config_name 指向 agentconf 中的模板配置）
    #    - name: 运行时唯一标识（solve_worker_0, solve_worker_1, ...）
    #    - agent_config_name: agentconf 中的配置名称（solve_worker）
    #
    #    这样所有 worker 共享同一份 LLM 配置，无需在 agentconf 中
    #    为每个 worker 创建单独的配置。
    worker_configs = [
        AgentConfig(
            name=f"solve_worker_{i}",
            agent_config_name="solve_worker",  # 指向 agentconf 中的模板配置
            description=f"解题 Worker #{i}",
            system_prompt=(
                f"你是解题 Worker #{i}。请独立完成分配给你的子任务。"
                "给出清晰的解答步骤和最终答案。"
                "完成解题后请使用 end_task 结束。"
            ),
            max_iterations=8,
        )
        for i in range(NUM_WORKERS)
    ]

    # 4. 注册所有 Agent
    print("\n注册 Agent...")
    registered_name = await supervisor.spawn_agent(planner_config)
    print(f"  ✓ Agent 注册成功: {registered_name}")

    for config in worker_configs:
        registered_name = await supervisor.spawn_agent(config)
        print(
            f"  ✓ Agent 注册成功: {registered_name} "
            f"(agent_config_name={config.effective_agent_config_name})"
        )

    # 5. 健康检查
    print("\n" + "=" * 60)
    print("健康检查:")
    health = await supervisor.health_check()
    for name, is_healthy in health.items():
        status = "✓ 健康" if is_healthy else "✗ 不健康"
        print(f"  - {name}: {status}")

    # 6. 演示：planner 分解任务，worker 并行处理
    print("\n" + "=" * 60)
    print("阶段 1: Planner 分解任务...")
    print("-" * 60)

    planner_prompt = (
        "请将以下问题分解为 3 个独立的子任务，每个子任务由一个 worker 独立完成：\n"
        "问题：设计一个小型 Python 项目，包含数据处理、算法实现和测试三个模块。\n\n"
        "请为每个子任务给出明确的输入和预期输出。"
    )

    planner_response = await supervisor.send("planner", planner_prompt)
    print(f"  Planner 回复:\n{planner_response[:500]}...")

    # 7. 并行分配任务给 worker
    print("\n" + "=" * 60)
    print("阶段 2: Worker 并行处理子任务...")
    print("-" * 60)

    # 简单的任务分配示例
    tasks = [
        "请设计一个数据处理模块，支持 CSV 和 JSON 格式的数据读取和清洗。",
        "请实现一个排序算法模块，包含快速排序和归并排序两种实现。",
        "请编写一个测试框架，使用 pytest 对上述两个模块进行单元测试。",
    ]

    async def dispatch_task(worker_name: str, task: str) -> str:
        """分配任务给指定 worker。"""
        response = await supervisor.send(worker_name, task)
        return response

    # 并行执行所有 worker 任务
    worker_names = [f"solve_worker_{i}" for i in range(NUM_WORKERS)]
    results = await asyncio.gather(
        *[
            dispatch_task(name, task)
            for name, task in zip(worker_names, tasks)
        ]
    )

    for name, result in zip(worker_names, results):
        print(f"\n  {name} 回复:")
        print(f"  {result[:300]}...")

    # 8. 结果汇总
    print("\n" + "=" * 60)
    print("结果汇总")
    print("=" * 60)
    print("  Planner 规划完成")
    for name, result in zip(worker_names, results):
        print(f"  {name}: 完成 ({len(result)} 字符)")

    # 9. 清理
    print("\n" + "=" * 60)
    print("清理资源...")
    agents = await supervisor.list_agents()
    for agent in agents:
        await supervisor.terminate_agent(agent["name"])
        print(f"  ✓ Agent 已终止: {agent['name']}")

    print("\n✅ 示例运行完成！")


if __name__ == "__main__":
    asyncio.run(main())
