"""Bounded proposals from the conversation reviewer; never staff decisions."""

from typing import Literal
from pydantic import Field
from eas_shared.skills import WireModel, LearningProposal


class ChatSignal(WireModel):
    kind: Literal["correction", "preference", "new_information", "problem", "ambiguous"]
    message_id: str = Field(min_length=1, max_length=160)
    quote: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=2000)
    target_episode_id: str | None = None
    invocation: str | None = Field(default=None, max_length=300)


class ChatReview(LearningProposal):
    signals: list[ChatSignal] = Field(default_factory=list, max_length=5)


def messages(episode):
    return [{"message_id": "request:" + episode["job"]["id"], "text": episode["job"]["task"]}] + [
        {"message_id": e["message_id"], "text": e["text"]}
        for e in episode["events"]
        if e["kind"] == "staff_message"
    ][-20:]


def validate_signals(signals, episode, related):
    sources = {m["message_id"]: m["text"] for m in messages(episode)}
    episodes = {e["job"]["id"]: e for e in [episode, *related]}
    result = []
    for raw in signals:
        signal = ChatSignal.model_validate(raw).model_dump()
        if signal["message_id"] not in sources or signal["quote"] not in sources[signal["message_id"]]:
            raise ValueError("Chat feedback must quote an actual new staff message")
        target = signal["target_episode_id"]
        if target and target not in episodes:
            raise ValueError("Chat feedback references unavailable work")
        if signal["invocation"]:
            if not target or signal["kind"] == "ambiguous":
                raise ValueError("Ambiguous feedback cannot assess a specific operation")
            kinds = {
                e["kind"] for e in episodes[target]["events"] if e.get("invocation") == signal["invocation"]
            }
            if not {"action_started", "action_result"}.issubset(kinds):
                raise ValueError("Chat feedback references an unfinished or unavailable operation")
        result.append(signal)
    return result
