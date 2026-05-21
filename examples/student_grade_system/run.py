# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

"""学生成绩管理系统 — 端到端自动化软件生产示例。

使用 4 个 Manifest 声明式 Agent 协作构建一个前后端分离的学生成绩管理系统：
  1. Architect — 设计系统架构（数据模型、API 端点、前后端交互协议）
  2. Backend Coder — 实现 FastAPI + SQLite 后端（含 init_project 自动初始化项目骨架）
  3. Frontend Coder — 实现 Vue 3 + Vite 前端（含 init_project 自动初始化项目骨架）
  4. Code Reviewer — 审查前后端代码，提出改进意见

工作流：
  Architect 设计 → Backend Coder 实现 → Frontend Coder 实现
  → Git Commit #1 → Code Reviewer 审查 → Backend/Frontend 改进 → Git Commit #2

前置条件：
  1. 已配置 agentconf，至少有以下 agent：
     - architect (temperature 0.5)
     - coder (temperature 0.3)
     - reviewer (temperature 0.2)
  2. 所有 agent 指向有效的 LLM 模型

用法：
  cd ghrah-core
  uv run python examples/student_grade_system/run.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from runner import StudentGradeRunner

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
    temp_root = Path("./student_grade_test") / f"student_grade_{ts}"
    temp_root.mkdir(parents=True, exist_ok=True)

    workspace = temp_root / "workspace"
    persistence_dir = temp_root / "persistence"
    workspace.mkdir(parents=True, exist_ok=True)
    persistence_dir.mkdir(parents=True, exist_ok=True)

    for name in ("architect", "backend", "frontend", "reviewer"):
        (workspace / name).mkdir(parents=True, exist_ok=True)

    logger.info("Workspace created: %s", temp_root)
    return temp_root


def read_directory_files(directory: Path, suffixes: tuple[str, ...] = (".py", ".js", ".vue", ".html", ".json", ".yaml", ".yml", ".md")) -> str:
    parts: list[str] = []
    if not directory.exists():
        return f"(Directory not found: {directory})"
    for fpath in sorted(directory.rglob("*")):
        if fpath.is_file() and fpath.suffix in suffixes:
            try:
                content = fpath.read_text(encoding="utf-8")
                rel = fpath.relative_to(directory)
                parts.append(f"### {rel}\n```\n{content}\n```")
            except Exception:
                continue
    return "\n\n".join(parts) if parts else "(No files found)"


async def main() -> None:
    temp_root = create_workspace()
    workspace = temp_root / "workspace"
    persistence_dir = temp_root / "persistence"

    session_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    session_id = f"session_{session_ts}"

    print("=" * 60)
    print("学生成绩管理系统 — 端到端自动化软件生产示例")
    print(f"Workspace: {temp_root}")
    print("=" * 60)

    runner = StudentGradeRunner(
        workspace=workspace,
        persistence_dir=persistence_dir,
        session_id=session_id,
    )

    ability_yaml = EXAMPLES_DIR / "abilities" / "student_grade.init_project.yaml"
    runner.register_ability_manifest(ability_yaml)
    print(f"\nRegistered custom ability: {ability_yaml.name}")

    ability_list_dir_yaml = EXAMPLES_DIR / "abilities" / "student_grade.list_directory.yaml"
    runner.register_ability_manifest(ability_list_dir_yaml)
    print(f"Registered custom ability: {ability_list_dir_yaml.name}")

    agents_dir = EXAMPLES_DIR / "agents"
    manifests = runner.load_manifests_from_dir(agents_dir)
    print(f"\nLoaded {len(manifests)} Agent manifests:")
    for m in manifests:
        print(f"  - {m.full_name} ({m.metadata.description})")

    print("\nInitializing Git repositories for backend and frontend...")
    StudentGradeRunner.git_init(workspace / "backend")
    StudentGradeRunner.git_init(workspace / "frontend")
    print("  ✓ backend/ initialized")
    print("  ✓ frontend/ initialized")

    supervisor = SupervisorActor()

    print("\n" + "=" * 60)
    print("Registering Agents...")
    agent_registry: dict[str, AgentConfig] = {}
    for manifest in manifests:
        config, abilities = runner.resolve(manifest)
        registered_name = await supervisor.spawn_agent(config, abilities=abilities)
        agent_registry[manifest.metadata.name] = config
        print(f"  ✓ Agent registered: {registered_name}")

    print("\n" + "=" * 60)
    print("Health check")
    health = await supervisor.health_check()
    for name, is_healthy in health.items():
        status = "✓ healthy" if is_healthy else "✗ unhealthy"
        print(f"  - {name}: {status}")

    try:
        # ====================================================================
        # Phase 1: Architect designs the system
        # ====================================================================
        print("\n" + "=" * 60)
        print("Phase 1: Architect designs the system")
        print("-" * 60)

        architect_prompt = (
            "请设计一个学生成绩管理系统的整体架构，需求如下：\n"
            "1. 学生信息管理（增删改查）：学号、姓名、班级\n"
            "2. 成绩管理：科目、分数、学期\n"
            "3. 成绩查询：按学生、按科目、按学期\n"
            "\n"
            "请输出以下设计文档到你的工作目录：\n"
            "1. 前后端交互的数据模型契约\n"
            "2. 后端数据模型与CRUD设计包括：\n"
            "- 使用以下技术栈，Python+Sqlite+FastAPI,使用uv管理\n"
            "- 数据模型的实现（字段、类型、关系）\n"
            "- RESTful API 端点设计（路径、方法、请求体、响应体）\n"
            "3. 前端系统的规划设计，包括：\n"
            "- 基于Vue3+TypeScript+Pinia+Router\n"
            "- 前端页面和组件规划\n"
            "- 前后端交互协议（数据格式、错误码）\n"
            "额外要求：\n"
            "合理的按用途，前后端，对应模块，组织多份文档文件\n"
            "使用markdown语法, 文档保持简洁，高信息密度\n"
            f"\n所有设计文档请写入: {workspace / 'architect'}，"
            f"这是你的专属工作区，如果你需要检查文件情况，"
            f"list directory，必须是{workspace / 'architect'}"
        )

        architect_response = await supervisor.send("architect", architect_prompt)
        print(f"  Architect response (first 500 chars):\n{architect_response[:500]}...")
        print()

        # ====================================================================
        # Phase 2: Backend Coder implements the backend
        # ====================================================================
        print("=" * 60)
        print("Phase 2: Backend Coder implements the backend")
        print("-" * 60)

        backend_prompt = (
            "请阅读架构师的设计文档，然后实现学生成绩管理系统的后端。\n"
            f"设计文档位于: {workspace / 'architect'}\n"
            f"你需要完成计划中的后端系统的实现\n"
            "\n"
            "步骤：\n"
            "1. 首先使用 init_project 工具初始化后端项目骨架（project_type='backend', "
            f"target_dir='{workspace / 'backend'}'）,该命令会创建一个空的uv python项目\n"
            "2. 在生成的骨架基础上实现完整功能\n"
            "3. 确保实现所有 CRUD 端点、数据验证和错误处理\n"
            f"\n代码请写入: {workspace / 'backend'}"
            f"这是你的专属工作区，如果你需要检查文件情况，"
            f"list directory，必须是{workspace / 'architect'}"
        )

        backend_response = await supervisor.send("backend_coder", backend_prompt)
        print(f"  Backend Coder response (first 500 chars):\n{backend_response[:500]}...")
        print()

        # ====================================================================
        # Phase 3: Frontend Coder implements the frontend
        # ====================================================================
        print("=" * 60)
        print("Phase 3: Frontend Coder implements the frontend")
        print("-" * 60)

        frontend_prompt = (
            "请阅读架构师的设计文档和后端代码，然后实现学生成绩管理系统的前端。\n"
            f"设计文档位于: {workspace / 'architect'}\n"
            f"后端代码位于: {workspace / 'backend'}\n"
            "\n"
            "步骤：\n"
            "1. 你的工作区应该是空的或仅包含一个.gitkeep文件\n"
            "首先使用 init_project 工具初始化前端项目骨架（project_type='frontend', "
            f"target_dir='{workspace / 'frontend'}'），该命令会创建一个vue3+TS+Pinia+Router的框架\n"
            "2. 在生成的框架基础上实现完整功能\n"
            "3. 实现学生信息增删改查、成绩录入和查询的界面\n"
            "4. 通过 fetch 调用后端 API\n"
            f"\n代码请写入: {workspace / 'frontend'}"
            f"这是你的专属工作区，如果你需要检查文件情况，"
            f"list directory，必须是{workspace / 'architect'}"
        )

        frontend_response = await supervisor.send("frontend_coder", frontend_prompt)
        print(f"  Frontend Coder response (first 500 chars):\n{frontend_response[:500]}...")
        print()

        # ====================================================================
        # Git Commit #1: Initial implementation
        # ====================================================================
        print("=" * 60)
        print("Git Commit #1: Initial implementation")
        print("-" * 60)

        backend_hash = StudentGradeRunner.git_commit(
            workspace / "backend", "feat: initial backend implementation"
        )
        frontend_hash = StudentGradeRunner.git_commit(
            workspace / "frontend", "feat: initial frontend implementation"
        )
        print(f"  ✓ backend commit: {backend_hash[:8]}")
        print(f"  ✓ frontend commit: {frontend_hash[:8]}")

        # ====================================================================
        # Phase 4: Code Reviewer reviews the code
        # ====================================================================
        print("\n" + "=" * 60)
        print("Phase 4: Code Reviewer reviews the code")
        print("-" * 60)

        # backend_code = read_directory_files(workspace / "backend")
        # frontend_code = read_directory_files(workspace / "frontend")

        reviewer_prompt = (
            "请审查以下学生成绩管理系统的前后端代码，"
            f"=== 后端代码 ===\n{workspace / 'backend'}\n\n"
            f"=== 前端代码 ===\n{workspace / 'frontend'}\n\n"
            f"并将审查报告分别写入 {workspace / 'reviewer' / 'review_backend_report.md'}。\n"
            f"{workspace / 'reviewer' / 'review_frontend_report.md'}\n"
            "审查要点：\n"
            "1. 代码质量和可读性\n"
            "2. 安全性问题（SQL注入、XSS等）\n"
            "3. API 设计规范性\n"
            "4. 错误处理完整性\n"
            "5. 前后端接口一致性\n"
            "6. 性能优化建议\n\n"
            "请按严重程度分级：严重 / 中等 / 轻微"
        )

        reviewer_response = await supervisor.send("code_reviewer", reviewer_prompt)
        print(f"  Reviewer response (first 500 chars):\n{reviewer_response[:500]}...")
        print()

        # ====================================================================
        # Phase 5: Backend Coder improves based on review
        # ====================================================================
        print("=" * 60)
        print("Phase 5: Backend Coder improves based on review")
        print("-" * 60)

        review_file_backend = workspace / "reviewer" / "review_backend_report.md"
        improvement_backend_prompt = (
            f"请阅读代码审查报告 ({review_file_backend})，针对其中评定的「严重」和「中等」问题，"
            f"改进后端代码。\n"
            f"后端代码位于: {workspace / 'backend'}\n"
            f"审查报告位于: {review_file_backend}"
            f"你只需要修复属于后端范围内的问题\n"
        )

        backend_improve_response = await supervisor.send("backend_coder", improvement_backend_prompt)
        print(f"  Backend improve response (first 500 chars):\n{backend_improve_response[:500]}...")
        print()

        # ====================================================================
        # Phase 6: Frontend Coder improves based on review
        # ====================================================================
        print("=" * 60)
        print("Phase 6: Frontend Coder improves based on review")
        print("-" * 60)
        review_file_frontend = workspace / "reviewer" / "review_frontend_report.md"
        improvement_frontend_prompt = (
            f"请阅读代码审查报告 ({review_file_frontend})，针对其中评定的「严重」和「中等」问题，"
            f"改进前端代码。\n"
            f"前端代码位于: {workspace / 'frontend'}\n"
            f"审查报告位于: {review_file_frontend}"
            f"你只需要修复属于前端范围内的问题\n"
        )

        frontend_improve_response = await supervisor.send("frontend_coder", improvement_frontend_prompt)
        print(f"  Frontend improve response (first 500 chars):\n{frontend_improve_response[:500]}...")
        print()

        # ====================================================================
        # Git Commit #2: Improvements
        # ====================================================================
        print("=" * 60)
        print("Git Commit #2: Improvements based on code review")
        print("-" * 60)

        backend_hash_2 = StudentGradeRunner.git_commit(
            workspace / "backend", "fix: improve backend based on code review"
        )
        frontend_hash_2 = StudentGradeRunner.git_commit(
            workspace / "frontend", "fix: improve frontend based on code review"
        )
        print(f"  ✓ backend commit: {backend_hash_2[:8]}")
        print(f"  ✓ frontend commit: {frontend_hash_2[:8]}")

    finally:
        # ====================================================================
        # Summary
        # ====================================================================
        print("\n" + "=" * 60)
        print("Result Summary")
        print("=" * 60)

        print("\nWorkspace files:")
        for agent_name in ("architect", "backend", "frontend", "reviewer"):
            agent_dir = workspace / agent_name
            if agent_dir.exists():
                files = sorted(
                    f.name for f in agent_dir.iterdir() if f.is_file() and f.name != ".gitkeep"
                )
                print(f"  {agent_name}/:")
                for fname in files:
                    fpath = agent_dir / fname
                    size = fpath.stat().st_size
                    print(f"    - {fname} ({size} bytes)")

        print(f"\nPersistence directory: {persistence_dir}")

        # Git logs
        print("\n=== Backend Git Log ===")
        for entry in StudentGradeRunner.git_log(workspace / "backend"):
            print(f"  {entry.commit_hash[:8]} {entry.message}")

        print("\n=== Frontend Git Log ===")
        for entry in StudentGradeRunner.git_log(workspace / "frontend"):
            print(f"  {entry.commit_hash[:8]} {entry.message}")

        # Cleanup
        print("\n" + "=" * 60)
        print("Cleaning up agents...")
        agents = await supervisor.list_agents()
        for agent in agents:
            await supervisor.terminate_agent(agent["name"])
            print(f"  ✓ Agent terminated: {agent['name']}")

        print("\nExample run completed!")
        print(f"Workspace: {temp_root}")
        print(f"Persistence: {persistence_dir}")


if __name__ == "__main__":
    asyncio.run(main())
