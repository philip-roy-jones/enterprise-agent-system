"""Methods exposed by the authenticated worker RPC endpoint."""

WORKER_METHODS = {
    "get_job",
    "update_job",
    "event",
    "lease",
    "claim",
    "check",
    "transfer",
    "boundary",
    "proposal",
    "approvals",
    "stale_approval",
    "begin_action",
    "begin_window_recovery",
    "finish_action",
    "result",
    "relevant_episodes",
    "search_knowledge",
    "conversation",
    "ask_staff",
}
