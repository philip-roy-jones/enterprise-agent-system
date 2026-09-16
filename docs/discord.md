# Private Discord team channels

The optional server-side bridge makes a dedicated private Discord text channel a shared conversation with one digital employee. The Deep Agent, skills, and application credentials still run on that employee's computer. The web console provides supervision and the same room's history/debug events. Model internals and debug traces are never sent to Discord.

This integration has simulated transport tests. A real Discord bot has not been connected or live-tested in this checkout. Starting the bridge enables actual message delivery; the server never starts it automatically.

## Configure

1. Create a bot in the [Discord developer portal](https://discord.com/developers/applications). Enable **Server Members Intent** and **Message Content Intent**. Invite it to a test server with View Channel, Send Messages, Attach Files and Read Message History. Do not give it Administrator.
2. Create a dedicated text channel for the employee. Explicitly deny View Channel to `@everyone`; allow only the intended staff and this bot. Everyone who can view it—including administrators—must be linked to an authorized staff identity. Other bots with visibility cause delivery to stop. Keep channels dedicated: all human text messages are directed to the employee. DMs, threads, incoming attachments and edited-message commands are not supported in this first version.
3. Give those existing staff identities explicit scope-matching `request`, `read`, and `control` grants with `own_only: false` for team work, and the required capabilities. This is a deliberate shared-scope grant, not a permission inferred from Discord membership. Supervisors additionally need `supervise`. OS/application accounts are still provisioned separately.
4. Copy `docs/examples/discord-channels.json` to a protected location under ignored `runtime/security/`. Replace the placeholder IDs, employee and scope. Get Discord IDs using Developer Mode. The mapping is Discord user ID → existing server human principal ID. Do not put passwords or tokens in this JSON.
5. Set `EAS_DISCORD_CHANNELS_FILE` to that file's absolute path in the server environment. Set `EAS_DISCORD_BOT_TOKEN` privately in the bridge's environment; never commit it. Restart the server so room choices appear in the console. Install the optional transport in the server environment:

   ```bash
   python -m pip install -c requirements.lock 'src/server[discord]'
   EAS_ENV_FILE=/absolute/path/to/server.env enterprise-discord
   ```

Run one bridge alongside the backend, under the server's trusted account, with the same database and identity registry. It has authority to route authenticated messages locally; it is not an edge worker. The bot credential stays on the server.

## Behavior

An active employee executes scoped requests without per-action approval. Messages during work become attributed guidance. Bot/webhook messages are ignored to prevent loops. Unknown users, revoked identities, incorrect scope and public or unexpectedly visible channels fail closed. Inspect bridge logs when a room is held. New work remains subject to server authorization and employee lifecycle. Removing Discord access does not cancel already authorized work; use Stop or Pause in the console.

In shadowing, choose the Discord channel in the supervisor console and start a demonstration. Operate the **employee's computer** through its console or remote desktop. The observer's questions appear in the room; only that demonstration's mentor may answer as teaching evidence. Finish with an observed outcome in the console. Activation remains a separate supervisor decision.

Channel history is shared across its members. Direct web conversations remain private contexts. Changing a binding or its configured audience starts a new context; Discord's existing messages remain in Discord. The bridge cannot revoke copies of information already delivered, and Discord administrators and infrastructure remain part of that channel's trust boundary. Permissions are rechecked before each send; there is no atomic transaction spanning Discord permission changes and message delivery.

Only final public messages, staff questions, observation errors and explicitly shared screenshots leave the server. Responses appear after completion of each model message; the web UI retains token streaming. Screenshot annotations are delivered as accompanying text, with the original image. Raw observation samples are not posted. Output uses disabled mentions, size-bounded chunks and persisted delivery cursors. Inbound message IDs prevent duplicate execution. Stable output nonces reduce duplicates on recent delivery retries; a prolonged crash around a send can still duplicate a message. Gateway reconnects are handled by discord.py; messages missed while the bridge is fully offline are not backfilled into executable work. Resend the request after recovery.

Official references: [Discord Gateway and intents](https://docs.discord.com/developers/events/gateway), [message delivery and nonce semantics](https://docs.discord.com/developers/resources/message#create-message).
