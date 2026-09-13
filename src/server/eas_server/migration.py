"""Associate legacy artifacts with their original requests, without changing owners."""

import re


def bind_legacy_artifacts(store):
    with store.db() as db:
        owners = {}
        for row in db.execute(
            "SELECT events.job_id,j.atom FROM events,json_tree(events.data) j WHERE j.key='screenshot' AND j.type='text'"
        ):
            name = row[1].rsplit("/", 1)[-1]
            if re.fullmatch(r"[a-f0-9]{32}\.png", name):
                owners.setdefault(name, set()).add(row[0])
        count = 0
        for name, jobs in owners.items():
            if len(jobs) == 1:
                count += db.execute(
                    "INSERT OR IGNORE INTO artifact_owners VALUES(?,?,?)",
                    (name, next(iter(jobs)), "legacy-worker-report"),
                ).rowcount
        return count
