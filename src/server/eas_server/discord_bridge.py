"""Optional server-side Discord transport. Starting this command enables delivery."""

import asyncio
import hashlib
import logging
import os
from contextlib import suppress

from fastapi import HTTPException
from eas_shared.types import Stale
from eas_server.channels import Channels
from eas_server.config import Settings
from eas_server.security import Security
from eas_server.store import Store

log = logging.getLogger(__name__)


def make_client(channels):
    import discord
    from discord.http import Route, handle_message_parameters

    intents = discord.Intents.none()
    intents.guilds = intents.members = intents.guild_messages = intents.message_content = True

    class Bridge(discord.Client):
        async def setup_hook(self):
            self.serial = asyncio.Lock()
            self.delivery = asyncio.create_task(self.deliver_forever())

        async def close(self):
            if hasattr(self, "delivery"):
                self.delivery.cancel()
                with suppress(asyncio.CancelledError):
                    await self.delivery
            await super().close()

        async def destination(self, binding):
            # Fresh permissions and complete member enumeration, not a partial cache.
            guild = await self.fetch_guild(int(binding.guild_id))
            channel = await guild.fetch_channel(int(binding.channel_id))
            if not isinstance(channel, discord.TextChannel):
                raise PermissionError("Only dedicated guild text channels are supported")
            visible = []
            async for member in guild.fetch_members(limit=None):
                if member.id != self.user.id and channel.permissions_for(member).view_channel:
                    if member.bot:
                        raise PermissionError("Another bot can read this channel")
                    visible.append(str(member.id))
            private = channel.overwrites_for(guild.default_role).view_channel is False
            channels.audience(binding, visible, private=private)
            return channel, visible

        async def send_public(self, channel, identity, text, artifact=None):
            nonce = hashlib.sha256(identity.encode()).hexdigest()[:24]
            file = discord.File(artifact, filename="desktop.png") if artifact else discord.utils.MISSING
            with handle_message_parameters(
                content=text, nonce=nonce, file=file, allowed_mentions=discord.AllowedMentions.none()
            ) as params:
                if params.payload is not None:
                    params.payload["enforce_nonce"] = True
                else:
                    import json

                    payload = next(p for p in params.multipart if p["name"] == "payload_json")
                    value = json.loads(payload["value"])
                    value["enforce_nonce"] = True
                    payload["value"] = json.dumps(value)
                # discord.py handles rate limits; Discord handles recent nonce retries.
                return await self.http.request(
                    Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id),
                    json=params.payload,
                    form=params.multipart,
                    files=params.files,
                )

        async def on_message(self, message):
            if message.author.bot or message.webhook_id or not message.guild:
                return
            try:
                binding = channels.get(message.channel.id)
            except PermissionError:
                return
            if str(message.guild.id) != binding.guild_id:
                return
            async with self.serial:
                try:
                    channel, viewers = await self.destination(binding)
                    if str(message.author.id) not in viewers:
                        raise PermissionError("Sender cannot view the bound channel")
                    channels.member(binding, message.author.id)
                    if message.attachments or not message.content.strip():
                        raise ValueError("This prototype accepts text messages; attached files are not read")
                    channels.receive(
                        binding, author_id=message.author.id, message_id=message.id, text=message.content
                    )
                except (Stale, ValueError) as error:
                    # Destination and identity were checked before this public status.
                    if "channel" in locals():
                        await self.send_public(channel, f"status:{message.id}", str(error)[:1800])
                except (PermissionError, HTTPException, discord.DiscordException) as error:
                    log.warning(
                        "Discord inbound blocked for channel %s (%s)",
                        binding.channel_id,
                        type(error).__name__,
                    )

        async def deliver_once(self):
            for binding in channels.bindings():
                for item in channels.pending(binding):
                    try:
                        channel, viewers = await self.destination(binding)
                        for viewer in viewers:
                            channels.security.authorize(channels.member(binding, viewer), "read", item["job"])
                        result = await self.send_public(
                            channel, item["identity"], item["text"], item.get("artifact")
                        )
                        channels.delivered(item["identity"], result["id"])
                    except (PermissionError, HTTPException, discord.DiscordException) as error:
                        log.warning(
                            "Discord delivery held for channel %s (%s)",
                            binding.channel_id,
                            type(error).__name__,
                        )
                        break

        async def deliver_forever(self):
            await self.wait_until_ready()
            while not self.is_closed():
                try:
                    async with self.serial:
                        await self.deliver_once()
                except (OSError, ValueError):
                    log.warning("Discord delivery paused: check channel configuration")
                await asyncio.sleep(2)

    return Bridge(intents=intents, allowed_mentions=discord.AllowedMentions.none())


def main():
    settings = Settings()
    token = os.getenv("EAS_DISCORD_BOT_TOKEN")
    if not token or not settings.discord_channels_file:
        raise SystemExit("Set EAS_DISCORD_BOT_TOKEN and EAS_DISCORD_CHANNELS_FILE in the server environment")
    security = Security(settings, Store(settings.data_dir))
    channels = Channels(security)
    channels.bindings()  # Validate before opening any network connection.
    logging.basicConfig(level=logging.INFO)
    make_client(channels).run(token, log_handler=None)


if __name__ == "__main__":
    main()
