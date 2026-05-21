# 架构图与流程图

ghrah 的架构设计围绕三大核心概念：ActorAgent（Agent 容器）、Ability（能力组合）和 ContextManager（上下文管理），支持本地和分布式两种运行模式。

## 系统架构总览

```mermaid
graph TB
    subgraph 用户层
        User[用户代码]
    end
    
    subgraph 通信层
        Supervisor[SupervisorActor<br/>中心编排者]
        Registry[AgentRegistry<br/>注册中心]
        Router[MessageRouter<br/>消息路由]
    end
    
    subgraph Agent层
        Agent1[ActorAgent 1]
        Agent2[ActorAgent 2]
        AgentN[ActorAgent N]
    end
    
    subgraph Ability层
        Conv[ConversationAbility]
        End[EndTaskAbility]
        FS[文件系统 Abilities]
        Custom[自定义 Ability]
    end
    
    subgraph 上下文层
        CM[ContextManager]
        Chain[ActionChain<br/>链式历史]
        SM[StateManager<br/>事务性状态]
        MS[MessageStore<br/>消息存储]
        WM[WindowManager<br/>窗口管理]
    end
    
    subgraph 持久化层
        JB[JsonFileBackend]
        IB[InMemoryBackend]
        SB[SqliteBackend]
        RB[RemoteBackend]
    end
    
    subgraph LLM层
        LF[LLMFactory]
        CF[ChatFormat<br/>OpenAIFormat / AnthropicFormat]
        AC[agentconf]
    end
    
    subgraph 执行器层
        LAE[LocalAbilityExecutor<br/>本地执行]
        RAE[RemoteAbilityExecutor<br/>远程执行]
        CS[CommandSender<br/>通信客户端]
        EP[EventPublisher<br/>NullEventPublisher / ServerEventPublisher]
    end
    
    User --> Supervisor
    Supervisor --> Registry
    Supervisor --> Router
    Router --> Agent1
    Router --> Agent2
    Router --> AgentN
    
    Agent1 --> CM
    Agent1 --> Conv
    Agent1 --> End
    Agent1 --> FS
    Agent1 --> Custom
    
    CM --> Chain
    CM --> SM
    CM --> MS
    CM --> WM
    
    CM --> JB
    CM --> IB
    CM --> SB
    CM --> RB
    
    Agent1 --> LF
    LF --> AC
    LF --> CF
    
    Agent1 --> LAE
    Agent1 --> RAE
    RAE --> CS
    Agent1 --> EP
```

## 模块依赖关系

```mermaid
graph LR
    Core[core<br/>配置/消息/事件/异常] --> Abilities[abilities<br/>能力接口/Hook/执行器]
    Core --> Agents[agents<br/>ActorAgent]
    Core --> Context[context<br/>上下文管理]
    Core --> LLM[llm<br/>LLM工厂]
    Core --> Communication[communication<br/>通信层]
    
    Abilities --> Agents
    Context --> Agents
    LLM --> Agents
    Communication --> Agents
    
    Chat[chat<br/>ChatMessage/ContentBlock/ChatFormat] --> LLM
    Chat --> Agents
```

## 模块说明

| 模块 | 路径 | 职责 |
|------|------|------|
| core | `src/ghrah/core/` | 核心抽象：配置、消息、事件、异常、HITL、CommandSender |
| chat | `src/ghrah/chat/` | LLM 交互层：ChatMessage、ContentBlock、ChatFormat 适配器 |
| abilities | `src/ghrah/abilities/` | Ability 接口、Hook、执行器（Local/Remote）、内置 Ability |
| agents | `src/ghrah/agents/` | ActorAgent 基类、驱动循环 |
| context | `src/ghrah/context/` | 上下文管理：链式历史、状态、消息、窗口、持久化 |
| llm | `src/ghrah/llm/` | LLM 工厂：agentconf → ChatFormat |
| communication | `src/ghrah/communication/` | 通信层：注册、路由、Supervisor |
| tools | `src/ghrah/tools/` | 工具定义层（骨架） |

## 驱动循环流程

```mermaid
flowchart TD
    Start([receive - 接收消息]) --> HasAbilities{有注册 Ability?}
    HasAbilities -->|否| Error[抛出 AgentError<br/>需要注册至少一个 Ability]
    HasAbilities -->|是| InitLLM[_ensure_llm<br/>惰性初始化 ChatFormat]
    InitLLM --> AddMsg[添加用户消息到 ContextManager]
    AddMsg --> SetIter[设置 max_iterations<br/>reset_iteration]
    SetIter --> DriveLoop[_drive_loop]
    
    DriveLoop --> BeginIter[begin_iteration<br/>开始新迭代]
    BeginIter --> RunHooks1[BEFORE_ACTION hooks]
    RunHooks1 --> SelectAbility[选择 Ability]
    
    SelectAbility --> RunHooks2[PRE_LLM_CALL hooks]
    RunHooks2 --> LLMCall[ChatFormat.generate<br/>LLM 调用]
    LLMCall --> RunHooks3[POST_LLM_CALL hooks]
    RunHooks3 --> HasToolCall{有 tool_call?}
    
    HasToolCall -->|是| RunHooks4[PRE_TOOL_EXECUTE hooks]
    RunHooks4 --> ToolExec[AbilityExecutor.execute_tool_calls]
    ToolExec --> RunHooks5[POST_TOOL_EXECUTE hooks]
    
    HasToolCall -->|否| ConvExec[ConversationAbility<br/>纯文本响应]
    
    RunHooks5 --> RunHooks6[PRE_EXECUTE hooks]
    ConvExec --> RunHooks6
    RunHooks6 --> AbilityExec[Ability.execute]
    AbilityExec --> RunHooks7[POST_EXECUTE hooks]
    RunHooks7 --> RunHooks8[AFTER_ACTION hooks]
    
    RunHooks8 --> ShouldContinue{should_continue?}
    ShouldContinue -->|是| BeginIter
    ShouldContinue -->|否| Commit[commit_iteration]
    ShouldContinue -->|最大迭代| MaxIter[ON_MAX_ITERATIONS hooks]
    MaxIter --> Commit
    
    Commit --> BuildResp[_build_response<br/>构建最终回复]
    BuildResp --> Return([返回响应 Message])
    Fallback --> Return
    
    BeginIter -->|异常| OnError[ON_ERROR hooks]
    OnError --> Rollback[rollback_iteration]
    Rollback --> BuildResp
```

## Ability 选择流程

```mermaid
flowchart TD
    LLMResponse[LLMResponse] --> HasToolCalls{有 tool_calls?}
    HasToolCalls -->|是| ExtractTool[提取 tool_call 名称]
    ExtractTool --> FindAbility{查找 Ability}
    FindAbility --> Found[找到对应 Ability]
    FindAbility --> NotFound[AbilityNotFoundError]
    
    HasToolCalls -->|否| UseConv[使用 ConversationAbility]
    
    Found --> ParseArgs[解析 tool_call 参数<br/>→ tool_args]
    ParseArgs --> CreateContext[创建 AbilityExecutionContext]
    CreateContext --> Execute[Ability.execute]
    
    UseConv --> CreateContext2[创建 AbilityExecutionContext<br/>accumulated_data.llm_response]
    CreateContext2 --> Execute2[ConversationAbility.execute]
```

## 消息路由流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant Sup as SupervisorActor
    participant Reg as AgentRegistry
    participant Router as MessageRouter
    participant Agent as ActorAgent

    User->>Sup: send(agent_name, content)
    Sup->>Reg: get(agent_name)
    Reg-->>Sup: AgentInfo
    
    Sup->>Sup: 创建 Message
    Sup->>Router: route(message)
    Router->>Agent: receive(message)
    Agent-->>Router: response Message
    Router-->>Sup: response
    Sup-->>User: response
```

## 上下文管理流程

```mermaid
sequenceDiagram
    participant Agent as ActorAgent
    participant CM as ContextManager
    participant Chain as ActionChain
    participant SM as StateManager
    participant MS as MessageStore
    participant Persist as PersistenceBackend

    Note over Agent,Persist: 迭代开始
    Agent->>CM: begin_iteration()
    CM->>Chain: 创建新节点
    CM->>SM: begin_transaction()
    
    Agent->>CM: add_messages([ChatMessage])
    CM->>MS: 存储消息
    
    Agent->>CM: apply_state_changes({"key": "value"})
    CM->>SM: apply_changes(changes)
    
    Note over Agent,Persist: 迭代结束
    alt 成功
        Agent->>CM: commit_iteration()
        CM->>SM: commit()
        CM->>Chain: 提交节点
        CM->>Persist: persist()（如果 auto_persist）
    else 失败
        Agent->>CM: rollback_iteration()
        CM->>SM: rollback()
        CM->>Chain: 丢弃节点
    end
```

## Hook 执行时序

```mermaid
sequenceDiagram
    participant Loop as Drive Loop
    participant H1 as BEFORE_ACTION
    participant H2 as PRE_LLM_CALL
    participant CF as ChatFormat
    participant H3 as POST_LLM_CALL
    participant H4 as PRE_TOOL_EXECUTE
    participant AE as AbilityExecutor
    participant H5 as POST_TOOL_EXECUTE
    participant H6 as PRE_EXECUTE
    participant H7 as POST_EXECUTE
    participant H8 as AFTER_ACTION

    Loop->>H1: 触发 BEFORE_ACTION hooks
    H1-->>Loop: HookResult
    
    Loop->>H2: 触发 PRE_LLM_CALL hooks
    H2-->>Loop: HookResult
    
    Loop->>CF: generate(messages)
    CF-->>Loop: LLMResponse
    
    Loop->>H3: 触发 POST_LLM_CALL hooks
    H3-->>Loop: HookResult
    
    alt 有 tool_call
        Loop->>H4: 触发 PRE_TOOL_EXECUTE hooks
        H4-->>Loop: HookResult
        Loop->>AE: execute_tool_calls(tool_calls)
        AE-->>Loop: ActionResults
        Loop->>H5: 触发 POST_TOOL_EXECUTE hooks
        H5-->>Loop: HookResult
    end
    
    Loop->>H6: 触发 PRE_EXECUTE hooks
    H6-->>Loop: HookResult
    Loop->>AE: execute_ability(ability, context)
    AE-->>Loop: ActionResult
    Loop->>H7: 触发 POST_EXECUTE hooks
    H7-->>Loop: HookResult
    
    Loop->>H8: 触发 AFTER_ACTION hooks
    H8-->>Loop: HookResult
```

## 持久化架构

```mermaid
graph TB
    CM[ContextManager] --> PB[PersistenceBackend]
    
    PB --> JFB[JsonFileBackend]
    PB --> IMB[InMemoryBackend]
    PB --> SDB[SqliteBackend]
    PB --> RMB[RemoteBackend]
    
    JFB --> FS1[文件系统<br/>root_dir/agent_name/<br/>├── chain_meta.json.gz<br/>├── messages.json.gz<br/>└── nodes/<br/>    └── node_id.json.gz]
    IMB --> MEM[内存字典]
    SDB --> DB1[SQLite 数据库<br/>WAL 模式<br/>sessions / agents / nodes / chain_meta 表]
    RMB --> CS1[CommandSender<br/>→ Subject<br/>SubjectPersistenceService]
    
    subgraph 序列化
        SN[serialize_node]
        SAR[serialize_action_result]
        SM[serialize_messages]
    end
    
    CM --> SN
    CM --> SAR
    CM --> SM
```

## 双模式架构

```mermaid
graph TB
    subgraph 本地模式
        LA[ActorAgent] --> LAE[LocalAbilityExecutor]
        LA --> NEP[NullEventPublisher]
        LA --> LCM[ContextManager<br/>InMemoryBackend / JsonFileBackend / SqliteBackend]
        LAE --> LHITL[HITLFutureStore<br/>本地 Future 审批]
    end
    
    subgraph 分布式模式
        RA[ActorAgent] --> RAE[RemoteAbilityExecutor]
        RA --> SEP[ServerEventPublisher]
        RA --> RCM[ContextManager<br/>RemoteBackend]
        RAE --> CS[CommandSender]
        SEP --> CS
        RCM --> CS
        CS -->|网络通信| SUB[Subject<br/>Ability 执行 + HITL + 持久化]
    end
```

## 数据流总览

```mermaid
graph LR
    subgraph 输入
        MSG[Message<br/>用户消息]
        CFG[AgentConfig<br/>配置]
        AC[agentconf<br/>LLM 配置]
    end
    
    subgraph 处理
        AG[ActorAgent<br/>驱动循环]
        AB[Ability<br/>能力执行]
        HK[Hook<br/>控制流]
        CM[ContextManager<br/>上下文管理]
        CF[ChatFormat<br/>LLM 交互]
    end
    
    subgraph 输出
        RESP[Message<br/>响应消息]
        STATE[StateManager<br/>状态更新]
        PERSIST[PersistenceBackend<br/>持久化]
    end
    
    MSG --> AG
    CFG --> AG
    AC --> CF
    
    AG --> CF
    AG --> AB
    AG --> HK
    AG --> CM
    
    AB --> STATE
    CM --> PERSIST
    
    AG --> RESP
```

## 下一步

- [核心概念](core-concepts.md) — 深入理解架构设计
- [Chat 交互层](chat-module.md) — 了解 ChatMessage 和 ContentBlock
- [Ability 系统](ability-system.md) — 了解 Ability 组合模式
- [上下文管理](context-management.md) — 理解 ContextManager 的设计
- [多 Agent 通信](multi-agent.md) — 了解 SupervisorActor 和消息路由
- [双模式架构](distributed-mode.md) — 了解本地与分布式模式的详细对比
