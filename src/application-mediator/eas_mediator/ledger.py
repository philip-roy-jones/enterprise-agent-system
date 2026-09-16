"""Durable input reservation. An uncertain native write is never replayed."""

import json
import sqlite3


class InputLedger:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS inputs(id TEXT PRIMARY KEY, result TEXT)")
        self.db.commit()

    def run(self, key, action):
        row = self.db.execute("SELECT result FROM inputs WHERE id=?", (key,)).fetchone()
        if row:
            if row[0] is None:
                raise PermissionError(
                    "Previous desktop input has an uncertain outcome; reconcile before retrying"
                )
            return json.loads(row[0])
        self.db.execute("INSERT INTO inputs VALUES(?,NULL)", (key,))
        self.db.commit()
        result = action()
        self.db.execute("UPDATE inputs SET result=? WHERE id=?", (json.dumps(result), key))
        self.db.commit()
        return result
