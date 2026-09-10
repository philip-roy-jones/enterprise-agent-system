# Library API verification

Verified against official documentation and installed packages on 2026-09-10. The exact resolved environment is recorded in `requirements.lock`.

| Library | Installed version | APIs exercised |
| --- | --- | --- |
| LangGraph | 1.2.11 | `StateGraph`, conditional edges, durable snapshots, `interrupt`, `Command(resume=...)` |
| LangGraph SQLite checkpointer | 3.1.1 | `SqliteSaver` with durable SQLite connections |
| Deep Agents | 0.7.13 | `create_deep_agent(model=..., tools=..., middleware=..., checkpointer=...)` |
| LangChain | 1.4.0 | `wrap_model_call`, `wrap_tool_call`, `ModelRequest.override`, configurable `init_chat_model` |
| Playwright | 1.62.0 | Chromium, `page.screenshot`, DOM locators, `fill`, `press`, `wait_for_function` |
| FastAPI | 0.141.1 | Auth dependencies, JSON endpoints, static files, SSE responses |

Official references:

- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Deep Agents human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
- [Deep Agents factory reference](https://reference.langchain.com/python/deepagents/graph/create_deep_agent)
- [Deep Agents customization](https://docs.langchain.com/oss/python/deepagents/customization)
- [Playwright Python Page API](https://playwright.dev/python/docs/api/class-page)

Deep Agents provides `interrupt_on` for tool approval. This prototype uses custom tool middleware with the same durable interrupt mechanism so that **all executable calls pass through the shared authority layer**, including argument corrections, screenshot binding, lease enforcement, cancellation, permissions, and evidence. Built-in filesystem, execution, planning, and delegation tools are not exposed to the model and are denied if requested.

No live provider/model ID is assumed. `EAS_MODEL_PROVIDER` and `EAS_MODEL_ID` must name a provider integration and model actually available to your account. Install that provider's supported LangChain package and credentials, then select `EAS_MODEL_MODE=live`. GPT-6 Astra is not hard-coded or claimed as a computer-use model. The prototype's computer interaction is implemented by Playwright tools, not a vendor-specific computer-use API.

The default simulated model subclasses LangChain's `BaseChatModel`, so tests execute the actual Deep Agents harness and its checkpoint/tool middleware without an API key. Those runs assess the harness and deterministic fixture policy, not real-model intelligence or reliability.
