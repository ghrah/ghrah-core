# Architecture Diagrams & Flowcharts

ghrah's architecture design revolves around three core concepts: ActorAgent (Agent container), Ability (capability composition), and ContextManager (context management), supporting both local and distributed runtime modes.

## System Architecture Overview

```mermaid
graph TB
    subgraph User Layer
        User[User Code]
    end
    
    subgraph Communication Layer
        Supervisor[SupervisorActor<br/>Central Orchestrator]
        Registry[AgentRegistry<br/>Registry]
        Router[MessageRouter<br/>Message Router]
    end
    
    subgraph Agent Layer
        Agent1[ActorAgent 1]
        Agent2[ActorAgent 2]
        AgentN[ActorAgent N]
    end
    
    subgraph Ability Layer
        Conv[ConversationAbility]
        End[EndTaskAbility]
        FS[File System Abilities]
        Custom[Custom Ability]
    end
    
    subgraph Context Layer
        CM[ContextManager]
        Chain[ActionChain<br/>Chain History]
        SM[StateManager<br/>Transactional State]
        MS[MessageStore<br/>Message Storage]
        WM[WindowManager<br/>Window Management]
    end
    
    subgraph Persistence Layer
        JB[JsonFileBackend]
        IB[InMemoryBackend]
        SB[SqliteBackend]
        RB[RemoteBackend]
    end
    
    subgraph LLM Layer
        LF[LLMFactory]
        CF[ChatFormat<br/>OpenAIFormat / AnthropicFormat]
        AC[agentconf]
    end
    
    subgraph Executor Layer
        LAE[LocalAbilityExecutor<br/>Local Execution]
        RAE[RemoteAbilityExecutor<br/>Remote Execution]
        CS[CommandSender<br/>Communication Client]
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

## Module Dependencies

```mermaid
graph LR
    Core[core<br/>Config/Message/Events/Exceptions] --> Abilities[abilities<br/>Ability Interface/Hooks/Executor]
    Core --> Agents[agents<br/>ActorAgent]
    Core --> Context[context<br/>Context Management]
    Core --> LLM[llm<br/>LLM Factory]
    Core --> Communication[communication<br/>Communication Layer]
    
    Abilities --> Agents
    Context --> Agents
    LLM --> Agents
    Communication --> Agents
    
    Chat[chat<br/>ChatMessage/ContentBlock/ChatFormat] --> LLM
    Chat --> Agents
```

## Module Descriptions

| Module | Path | Responsibility |
|--------|------|----------------|
| core | `src/ghrah/core/` | Core abstractions: config, messages, events, exceptions, HITL, CommandSender |
| chat | `src/ghrah/chat/` | LLM interaction layer: ChatMessage, ContentBlock, ChatFormat adapters |
| abilities | `src/ghrah/abilities/` | Ability interface, Hooks, executors (Local/Remote), built-in Abilities |
| agents | `src/ghrah/agents/` | ActorAgent base class, drive loop |
| context | `src/ghrah/context/` | Context management: chain history, state, messages, window, persistence |
| llm | `src/ghrah/llm/` | LLM factory: agentconf → ChatFormat |
| communication | `src/ghrah/communication/` | Communication: registry, routing, supervisor |
| tools | `src/ghrah/tools/` | Tool definition layer (skeleton) |

## Drive Loop Flow

```mermaid
flowchart TD
    Start([receive - Receive message]) --> HasAbilities{Has registered Ability?}
    HasAbilities -->|No| Error[Raise AgentError<br/>At least one Ability required]
    HasAbilities -->|Yes| InitLLM[_ensure_llm<br/>Lazy ChatFormat init]
    InitLLM --> AddMsg[Add user message to ContextManager]
    AddMsg --> SetIter[Set max_iterations<br/>reset_iteration]
    SetIter --> DriveLoop[_drive_loop]
    
    DriveLoop --> BeginIter[begin_iteration<br/>Start new iteration]
    BeginIter --> RunHooks1[BEFORE_ACTION hooks]
    RunHooks1 --> SelectAbility[Select Ability]
    
    SelectAbility --> RunHooks2[PRE_LLM_CALL hooks]
    RunHooks2 --> LLMCall[ChatFormat.generate<br/>LLM call]
    LLMCall --> RunHooks3[POST_LLM_CALL hooks]
    RunHooks3 --> HasToolCall{Has tool_call?}
    
    HasToolCall -->|Yes| RunHooks4[PRE_TOOL_EXECUTE hooks]
    RunHooks4 --> ToolExec[AbilityExecutor.execute_tool_calls]
    ToolExec --> RunHooks5[POST_TOOL_EXECUTE hooks]
    
    HasToolCall -->|No| ConvExec[ConversationAbility<br/>Pure text response]
    
    RunHooks5 --> RunHooks6[PRE_EXECUTE hooks]
    ConvExec --> RunHooks6
    RunHooks6 --> AbilityExec[Ability.execute]
    AbilityExec --> RunHooks7[POST_EXECUTE hooks]
    RunHooks7 --> RunHooks8[AFTER_ACTION hooks]
    
    RunHooks8 --> ShouldContinue{should_continue?}
    ShouldContinue -->|Yes| BeginIter
    ShouldContinue -->|No| Commit[commit_iteration]
    ShouldContinue -->|Max iterations| MaxIter[ON_MAX_ITERATIONS hooks]
    MaxIter --> Commit
    
    Commit --> BuildResp[_build_response<br/>Build final response]
    BuildResp --> Return([Return response Message])
    Fallback --> Return
    
    BeginIter -->|Exception| OnError[ON_ERROR hooks]
    OnError --> Rollback[rollback_iteration]
    Rollback --> BuildResp
```

## Ability Selection Flow

```mermaid
flowchart TD
    LLMResponse[LLMResponse] --> HasToolCalls{Has tool_calls?}
    HasToolCalls -->|Yes| ExtractTool[Extract tool_call name]
    ExtractTool --> FindAbility{Find Ability}
    FindAbility --> Found[Found corresponding Ability]
    FindAbility --> NotFound[AbilityNotFoundError]
    
    HasToolCalls -->|No| UseConv[Use ConversationAbility]
    
    Found --> ParseArgs[Parse tool_call args<br/>→ tool_args]
    ParseArgs --> CreateContext[Create AbilityExecutionContext]
    CreateContext --> Execute[Ability.execute]
    
    UseConv --> CreateContext2[Create AbilityExecutionContext<br/>accumulated_data.llm_response]
    CreateContext2 --> Execute2[ConversationAbility.execute]
```

## Message Routing Flow

```mermaid
sequenceDiagram
    participant User as User
    participant Sup as SupervisorActor
    participant Reg as AgentRegistry
    participant Router as MessageRouter
    participant Agent as ActorAgent

    User->>Sup: send(agent_name, content)
    Sup->>Reg: get(agent_name)
    Reg-->>Sup: AgentInfo
    
    Sup->>Sup: Create Message
    Sup->>Router: route(message)
    Router->>Agent: receive(message)
    Agent-->>Router: response Message
    Router-->>Sup: response
    Sup-->>User: response
```

## Context Management Flow

```mermaid
sequenceDiagram
    participant Agent as ActorAgent
    participant CM as ContextManager
    participant Chain as ActionChain
    participant SM as StateManager
    participant MS as MessageStore
    participant Persist as PersistenceBackend

    Note over Agent,Persist: Iteration start
    Agent->>CM: begin_iteration()
    CM->>Chain: Create new node
    CM->>SM: begin_transaction()
    
    Agent->>CM: add_messages([ChatMessage])
    CM->>MS: Store messages
    
    Agent->>CM: apply_state_changes({"key": "value"})
    CM->>SM: apply_changes(changes)
    
    Note over Agent,Persist: Iteration end
    alt Success
        Agent->>CM: commit_iteration()
        CM->>SM: commit()
        CM->>Chain: Commit node
        CM->>Persist: persist() (if auto_persist)
    else Failure
        Agent->>CM: rollback_iteration()
        CM->>SM: rollback()
        CM->>Chain: Discard node
    end
```

## Hook Execution Sequence

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

    Loop->>H1: Trigger BEFORE_ACTION hooks
    H1-->>Loop: HookResult
    
    Loop->>H2: Trigger PRE_LLM_CALL hooks
    H2-->>Loop: HookResult
    
    Loop->>CF: generate(messages)
    CF-->>Loop: LLMResponse
    
    Loop->>H3: Trigger POST_LLM_CALL hooks
    H3-->>Loop: HookResult
    
    alt Has tool_call
        Loop->>H4: Trigger PRE_TOOL_EXECUTE hooks
        H4-->>Loop: HookResult
        Loop->>AE: execute_tool_calls(tool_calls)
        AE-->>Loop: ActionResults
        Loop->>H5: Trigger POST_TOOL_EXECUTE hooks
        H5-->>Loop: HookResult
    end
    
    Loop->>H6: Trigger PRE_EXECUTE hooks
    H6-->>Loop: HookResult
    Loop->>AE: execute_ability(ability, context)
    AE-->>Loop: ActionResult
    Loop->>H7: Trigger POST_EXECUTE hooks
    H7-->>Loop: HookResult
    
    Loop->>H8: Trigger AFTER_ACTION hooks
    H8-->>Loop: HookResult
```

## Persistence Architecture

```mermaid
graph TB
    CM[ContextManager] --> PB[PersistenceBackend]
    
    PB --> JFB[JsonFileBackend]
    PB --> IMB[InMemoryBackend]
    PB --> SDB[SqliteBackend]
    PB --> RMB[RemoteBackend]
    
    JFB --> FS1[File System<br/>root_dir/agent_name/<br/>├── chain_meta.json.gz<br/>├── messages.json.gz<br/>└── nodes/<br/>    └── node_id.json.gz]
    IMB --> MEM[In-Memory Dict]
    SDB --> DB1[SQLite Database<br/>WAL Mode<br/>sessions / agents / nodes / chain_meta tables]
    RMB --> CS1[CommandSender<br/>→ Subject<br/>SubjectPersistenceService]
    
    subgraph Serialization
        SN[serialize_node]
        SAR[serialize_action_result]
        SM[serialize_messages]
    end
    
    CM --> SN
    CM --> SAR
    CM --> SM
```

## Dual-Mode Architecture

```mermaid
graph TB
    subgraph Local Mode
        LA[ActorAgent] --> LAE[LocalAbilityExecutor]
        LA --> NEP[NullEventPublisher]
        LA --> LCM[ContextManager<br/>InMemoryBackend / JsonFileBackend / SqliteBackend]
        LAE --> LHITL[HITLFutureStore<br/>Local Future Approval]
    end
    
    subgraph Distributed Mode
        RA[ActorAgent] --> RAE[RemoteAbilityExecutor]
        RA --> SEP[ServerEventPublisher]
        RA --> RCM[ContextManager<br/>RemoteBackend]
        RAE --> CS[CommandSender]
        SEP --> CS
        RCM --> CS
        CS -->|Network| SUB[Subject<br/>Ability Execution + HITL + Persistence]
    end
```

## Data Flow Overview

```mermaid
graph LR
    subgraph Input
        MSG[Message<br/>User Message]
        CFG[AgentConfig<br/>Configuration]
        AC[agentconf<br/>LLM Config]
    end
    
    subgraph Processing
        AG[ActorAgent<br/>Drive Loop]
        AB[Ability<br/>Capability Execution]
        HK[Hook<br/>Control Flow]
        CM[ContextManager<br/>Context Management]
        CF[ChatFormat<br/>LLM Interaction]
    end
    
    subgraph Output
        RESP[Message<br/>Response Message]
        STATE[StateManager<br/>State Update]
        PERSIST[PersistenceBackend<br/>Persistence]
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

## Next Steps

- [Core Concepts](core-concepts_en.md) — Deep dive into architecture design
- [Chat Module](chat-module_en.md) — Learn about ChatMessage and ContentBlock
- [Ability System](ability-system_en.md) — Understand the Ability composition pattern
- [Context Management](context-management_en.md) — Understand ContextManager design
- [Multi-Agent Communication](multi-agent_en.md) — Learn about SupervisorActor and message routing
- [Dual-Mode Architecture](distributed-mode_en.md) — Detailed comparison of local and distributed modes
