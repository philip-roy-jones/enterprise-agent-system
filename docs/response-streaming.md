# Response streaming

> Current execution policy: [digital employees](plans/digital-employees.md) use shadowing / active / paused. Active work uses server authorization without per-operation staff approval. Historical Strict-policy descriptions below remain as background where noted.

The edge consumes LangGraph's public coordinator message chunks while retaining synchronous checkpoints and the same stateful approval interrupts. The model still finishes proposing a tool call before it can reach the execution layer. Streaming text does not approve or execute an action.

Only text from the tagged foreground model node is forwarded. Tool argument fragments, reasoning blocks, and separate judgments are excluded. The first text chunk is sent immediately; subsequent chunks use small transport batches, normally around 50 milliseconds. This is actual model output, without a simulated typing animation. The implementation uses the existing [LangGraph messages and state streaming API](https://docs.langchain.com/oss/python/langgraph/streaming).

The assigned planner sends bounded `assistant_message_delta` records through the authenticated worker protocol. The server's existing staff event stream checks request access, supports `Last-Event-ID` on reconnect, and disables proxy buffering. The frontend applies these events directly without waiting for its periodic metadata refresh. Server sequences prevent duplicate replay and preserve chunks arriving during a concurrent fetch.

Each response has a stable message ID. Its completed `assistant_message` replaces the provisional text in one chat bubble and remains the source for context and learning. A failed or unfinished stream retains its partial text with an interruption label. Reloading reconstructs the same state from the event log. Unchanged historical bubbles, including enlarged screenshots, retain their DOM elements while new text arrives.

## Validation

Focused simulated-model/staff checks cover text delivery before model completion, exclusion of internal output, fragmented tool arguments and approval rejection, checkpoint resume, interrupted generation, audience/worker isolation, bounded payloads, browser reconnect and reload, HTML escaping, and existing Finance/Marketing workflows. The browser streaming test disables polling to verify that SSE itself updates the text.

An actual OpenRouter `openai/gpt-5.6-luna` run on the Ubuntu Marketing edge delivered 13 public text batches and 12 distinct visible partial updates. The first batch preceded the completed response by 1.618 seconds. The final text matched the concatenated chunks, with one bubble after reload and no browser JavaScript errors. This used a synthetic staff educational question and required no business approvals. Results are recorded in [the live evidence](evidence/response-streaming.json).

Both deployed edge planners match the updated source. Provider speed, model thinking time, and network buffering still affect when text becomes visible; this run does not establish a latency guarantee.
