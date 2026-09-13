"""Approved screen sharing, with synthetic images and staff decisions."""

import base64
from types import SimpleNamespace
import pytest
from eas_shared.types import JobInput
from eas_shared.screenshots import Annotation, captured_screen
from eas_harness.execution import ExecutionLayer
from eas_harness.screenshots import screen_tool
from eas_harness.errors import Paused
from test_security_boundaries import secured, new_job  # noqa: F401


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jVv8AAAAASUVORK5CYII="
)


def test_full_screen_capture_and_share_need_approval_but_no_invoice_or_focus(store):
    job = store.create_job(JobInput(task="Show me the entire screen").model_dump(), ongoing=True)
    store.claim("fixture")
    store.transfer(job["id"], "assistant")
    captured = []

    class Adapter:
        def observe(self):
            pytest.fail("Screen capture must not require or focus a business application")

        def capture_screen(self):
            self.fence()
            captured.append(True)
            return dict(screenshot=base64.b64encode(PNG).decode(), width=1, height=1, surface="desktop")

    def artifact(png):
        assert png == PNG
        (store.root / "artifacts" / "screen.png").write_bytes(png)
        return "screen.png"

    store.artifact = artifact
    layer = ExecutionLayer(store, Adapter())

    def run(name, args):
        return layer.run(
            job["id"],
            job["id"] + ":" + name,
            name,
            args,
            lambda a: screen_tool(store, layer.adapter, job["id"], name, a),
            kind="tool",
        )

    with pytest.raises(Paused):
        run("capture_screen", {})
    assert not captured
    approval = store.approvals(job["id"])[-1]
    store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
    result = run("capture_screen", {})
    assert result["value"]["surface"] == "desktop"
    args = dict(
        screenshot="screen.png",
        caption="The visible test screen",
        annotations=[dict(kind="arrow", x=0.1, y=0.2, x2=0.7, y2=0.8, label="Look here")],
    )
    with pytest.raises(Paused):
        run("share_screenshot", args)
    approval = store.approvals(job["id"])[-1]
    store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
    shared = run("share_screenshot", args)["value"]["data"]
    assert shared["captured_at"] == result["value"]["captured_at"]
    assert len(shared["annotations"]) == 1 and len(captured) == 1
    assert run("capture_screen", {}) == result and len(captured) == 1
    assert store.conclude(job["id"])["result_kind"] == "conversation"
    assert store.get_job(job["id"])["record_id"] is None


def test_attachments_reject_foreign_captures_and_invalid_shapes(store):
    with pytest.raises(PermissionError):
        screen_tool(
            store,
            SimpleNamespace(),
            "missing",
            "share_screenshot",
            dict(screenshot="foreign.png", caption="Claimed capture"),
        )
    with pytest.raises(ValueError):
        Annotation(kind="arrow", x=0.1, y=0.2)
    with pytest.raises(ValueError):
        Annotation(kind="text", x=1.1, y=0.2, label="outside")
    with pytest.raises(PermissionError):
        captured_screen([], "../../secret")


def test_only_assigned_planner_can_retrieve_completed_screen_capture(secured):  # noqa: F811
    app, client, headers, rpc, _ = secured
    job = new_job(secured)
    rpc("exec-a", "claim", "fixture").raise_for_status()
    store = app.state.store
    artifact = client.post(
        "/api/worker-artifacts", headers={**headers("exec-a"), "X-EAS-Job": job["id"]}, content=PNG
    )
    artifact.raise_for_status()
    name = artifact.json()["id"]
    url = f"/api/worker-artifacts/{job['id']}/{name}"
    assert client.get(url, headers=headers("planner")).status_code in {400, 403}
    # The server-owned ledger is seeded only as an explicit fixture here.
    store.event(job["id"], "action_started", dict(invocation="capture", action={"name": "capture_screen"}))
    store.event(
        job["id"],
        "action_result",
        dict(
            invocation="capture",
            result={"value": dict(screenshot=name, width=1, height=1, captured_at=1, surface="desktop")},
        ),
    )
    assert client.get(url, headers=headers("planner")).content == PNG
    from eas_harness.remote import RemoteStore
    from eas_harness.screenshots import model_image

    remote = RemoteStore("http://testserver", "test-planner")
    remote.client.close()
    remote.client = client
    client.headers.update(headers("planner"))
    assert model_image(remote, job["id"], name).startswith("data:image/png;base64,")
    shared = screen_tool(
        remote,
        SimpleNamespace(),
        job["id"],
        "share_screenshot",
        dict(screenshot=name, caption="Remote capture"),
    )
    assert shared["data"]["surface"] == "desktop"
    assert client.get(url, headers=headers("exec-b")).status_code == 404
    assert client.get(url, headers=headers("bob")).status_code == 403


def test_agent_sees_capture_without_archiving_image_bytes(store, tmp_path, monkeypatch):
    from eas_harness.coordinator import Coordinator, SimulatedCoordinator
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class Adapter:
        def observe(self):
            pytest.fail("Screenshot-only request must not inspect application state")

        def capture_screen(self):
            return dict(screenshot=base64.b64encode(PNG).decode(), width=1, height=1, surface="desktop")

    def artifact(png):
        (store.root / "artifacts" / "screen.png").write_bytes(png)
        return "screen.png"

    store.artifact = artifact
    seen = []

    def generate(self, messages, **kwargs):
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if not results:
            message = AIMessage(
                content="",
                tool_calls=[
                    dict(
                        id="old-share",
                        name="share_screenshot",
                        args={"screenshot": "older-request.png", "caption": "Old context"},
                    )
                ],
            )
        elif results[-1].status == "error":
            assert "capture_required" in results[-1].content
            message = AIMessage(content="", tool_calls=[dict(id="capture", name="capture_screen", args={})])
        elif results[-1].name == "capture_screen":
            assert results[-1].content[1]["image_url"]["url"].startswith("data:image/png;base64,")
            seen.append("image")
            message = AIMessage(
                content="",
                tool_calls=[
                    dict(
                        id="share",
                        name="share_screenshot",
                        args={
                            "screenshot": "screen.png",
                            "caption": "Simulated annotated screen",
                            "annotations": [
                                dict(kind="circle", x=0.1, y=0.1, x2=0.9, y2=0.9, label="Visible area")
                            ],
                        },
                    )
                ],
            )
        else:
            message = AIMessage(content="The screenshot is in chat.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    monkeypatch.setattr(SimulatedCoordinator, "_generate", generate)
    job = store.create_job(JobInput(task="Show me the screen with a circle").model_dump(), ongoing=True)
    store.claim("fixture")
    c = Coordinator(
        SimpleNamespace(
            data_dir=tmp_path, model_mode="simulated", model_provider="", model_id="", max_model_calls=6
        ),
        store,
        ExecutionLayer(store, Adapter()),
        InMemorySaver(),
        InMemorySaver(),
    )
    for _ in range(6):
        c.tick(store.get_job(job["id"]))
        if store.get_job(job["id"])["status"] == "completed":
            break
        for a in store.approvals(job["id"]):
            if a["status"] == "pending":
                store.decide(a["id"], {"decision": "approve"}, actor="simulated-staff")
    assert seen and store.get_job(job["id"])["status"] == "completed"
    assert {a["name"] for a in store.approvals(job["id"])} == {"capture_screen", "share_screenshot"}
    with c.memory.db() as db:
        assert all("data:image/png;base64" not in r[0] for r in db.execute("SELECT data FROM history"))
