# Library API verification

Verified against official documentation and installed packages on 2026-09-10. The exact resolved environment is recorded in `requirements.lock`.

| Library | Installed version | APIs exercised |
| --- | --- | --- |
| LangGraph | 1.2.11 | `StateGraph`, conditional edges, durable snapshots, `interrupt`, `Command(resume=...)` |
| LangGraph SQLite checkpointer | 3.1.1 | `SqliteSaver` with durable SQLite connections |
| Deep Agents | 0.7.13 | `create_deep_agent(model=..., tools=..., middleware=..., checkpointer=...)` |
| LangChain | 1.4.0 | `wrap_model_call`, `wrap_tool_call`, `ModelRequest.override`, configurable `init_chat_model` |
| LangChain OpenRouter | 0.2.8 | `ChatOpenRouter`, `OPENROUTER_API_KEY`, tool calls, image inputs, token usage; request timeout is in milliseconds |
| Playwright | 1.62.0 | Chromium, `page.screenshot`, DOM locators, `fill`, `press`, `wait_for_function` |
| FastAPI | 0.141.1 | Auth dependencies, JSON endpoints, static files, SSE responses |

Official references:

- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Deep Agents human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
- [Deep Agents factory reference](https://reference.langchain.com/python/deepagents/graph/create_deep_agent)
- [Deep Agents customization](https://docs.langchain.com/oss/python/deepagents/customization)
- [Playwright Python Page API](https://playwright.dev/python/docs/api/class-page)
- [LangChain OpenRouter integration](https://docs.langchain.com/oss/python/integrations/chat/openrouter)
- [Windows UI Automation control patterns](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/ui-automation-control-patterns-overview)
- [Windows SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

Deep Agents provides `interrupt_on` for tool approval. This prototype uses custom tool middleware with the same durable interrupt mechanism so that **all executable calls pass through the shared authority layer**, including argument corrections, screenshot binding, lease enforcement, cancellation, permissions, and evidence. Built-in filesystem, execution, planning, and delegation tools are not exposed to the model and are denied if requested.

The OpenRouter public model catalog and an authenticated request verified `openai/gpt-5.6-luna`. The installed integration uses a 20,000-millisecond timeout, no automatic retries, and 2,048 output tokens per request. Live model binding requests one tool call at a time; the shared execution layer serializes desktop access even if a model produces a batch. Desktop interaction uses scoped application, accessibility, and input adapters rather than a vendor-specific computer-use API.

The default simulated model subclasses LangChain's `BaseChatModel`, so tests execute the actual Deep Agents harness and its checkpoint/tool middleware without an API key. Those runs assess the harness and deterministic fixture policy, not real-model intelligence or reliability.

Native Windows build references (verified 2026-09-10):

- [.NET 10 SDK downloads](https://dotnet.microsoft.com/en-us/download/dotnet/10.0), SDK 10.0.401 used for the build.
- [Building Windows targets on Linux with EnableWindowsTargeting](https://learn.microsoft.com/en-us/dotnet/core/tools/sdk-errors/netsdk1100).
- [Windows Forms overview](https://learn.microsoft.com/en-us/dotnet/desktop/winforms/overview/).

DemoBooks targets `net10.0-windows` and publishes a self-contained Windows x64 executable. Its accounting model has a separate cross-platform smoke-test project.
