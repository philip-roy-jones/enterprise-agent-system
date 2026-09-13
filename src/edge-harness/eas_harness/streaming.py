"""Stream public coordinator text without changing checkpoint or approval semantics."""

import time
from langchain_core.messages import AIMessageChunk

PUBLIC_CHAT = "eas-public-chat"


def public_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        )
    return ""


def stream_agent(agent, value, config, store, job_id):
    result, pending, last_sent = {}, {}, {}
    interrupts = []

    def flush(message_id):
        text = pending[message_id]
        if text:
            store.event(job_id, "assistant_message_delta", {"message_id": message_id, "text": text})
            pending[message_id] = ""
            last_sent[message_id] = time.monotonic()

    try:
        for mode, data in agent.stream(
            value, config, stream_mode=["messages", "values", "updates"], durability="sync"
        ):
            if mode == "values":
                result = data
                continue
            if mode == "updates":
                interrupts.extend(data.get("__interrupt__", ()))
                continue
            chunk, metadata = data
            if (
                not isinstance(chunk, AIMessageChunk)
                or not chunk.id
                or PUBLIC_CHAT not in metadata.get("tags", [])
                or metadata.get("langgraph_node") != "model"
            ):
                continue
            # Reasoning blocks, tool arguments and untagged judgments are never
            # public text. Small transport batches avoid an HTTP call per token.
            text = public_text(chunk.content)
            if text:
                pending[chunk.id] = pending.get(chunk.id, "") + text
                if time.monotonic() - last_sent.get(chunk.id, 0) >= 0.05:
                    flush(chunk.id)
        return {**result, "__interrupt__": interrupts} if interrupts else result
    finally:
        # A completed assistant_message supersedes these provisional chunks.
        # If generation failed, the remaining partial reply is marked interrupted.
        for message_id in pending:
            try:
                flush(message_id)
                store.event(job_id, "assistant_stream_end", {"message_id": message_id})
            except Exception:
                # A revoked assignment/cancelled request must still stop even
                # when it can no longer upload the final display-only event.
                pass
