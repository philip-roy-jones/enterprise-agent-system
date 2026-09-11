from typing import TypedDict


class GraphState(TypedDict, total=False):
    job_id: str
    paused: bool
    turn: int
    next_node: str
    resume_node: str
    reason: str
    recovery_kind: str
    result: dict
