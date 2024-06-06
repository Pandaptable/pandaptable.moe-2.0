import datetime
import os
from typing import Tuple

import discord
import httpx
import toml
from aiocache import SimpleMemoryCache, cached
from dotenv import load_dotenv
from lru import LRU

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates



class Website(FastAPI):
    def __init__(self) -> None:
        load_dotenv()
        self.client: discord.Client = discord.Client(intents=discord.Intents.none())
        self.jinja_template = Jinja2Templates("templates")
        self.up_since: str = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%m/%d/%Y, %H:%M:%S"
        )
        self.links: dict = LRU(30)
        self.http_client: httpx.AyncClient = httpx.AsyncClient()
        self.env: dict = {
            "BASE_URL": os.getenv("BASE_URL"),
            "CHANNEL_ID": os.getenv("CHANNEL_ID"),
            "MESSAGE_ID": os.getenv("MESSAGE_ID"),
            "OWNER_ID": int(os.getenv("OWNER_ID")),
            "DATABASE_URL": os.getenv("DATABASE_URL"),
            "DATABASE_KEY": os.getenv("DATABASE_KEY"),
            "PUBLIC_KEY": os.getenv("PUBLIC_KEY"),
            "OAUTH2_CLIENT_ID": os.getenv("OAUTH2_CLIENT_ID"),
            "OAUTH2_REDIRECT_URI": os.getenv("OAUTH2_REDIRECT_URI"),
            "OAUTH2_CLIENT_SECRET": os.getenv("OAUTH2_CLIENT_SECRET"),
            "OAUTH2_URL": os.getenv("OAUTH2_URL"),
            "PORT": os.getenv("PORT", 49999),
            "TOKEN": os.getenv("TOKEN"),
            "SENTRY_DSN": os.getenv("SENTRY_DSN"),
            "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
            "JSON_LOGS": os.getenv("JSON_LOGS", "0"),
        }

    async def login(self) -> None:
        """Logs in the client."""
        await self.client.login(self.env["TOKEN"])

    @property
    def version(self) -> str:
        """Returns the version of the website."""
        with open("pyproject.toml") as f:
            return toml.load(f)["tool"]["poetry"]["version"]

    def redirect(self, url: str) -> dict:
        """Redirects to a URL."""
        return {
            "status_code": 307,
            "body": "",
            "type": "text",
            "headers": {"Location": url},
        }

    async def reload_links(self) -> None:
        """Reloads the shortened links."""
        message = await self.client.http.get_message(
            self.env["CHANNEL_ID"], self.env["MESSAGE_ID"]
        )
        for link in message["content"].split("\n"):
            self.links[link.split(" ")[0]] = link.split(" ")[1]

    async def notify_owner(self) -> None:
        """Notifies owner that the website is online."""
        owner = await self.client.fetch_user(self.env["OWNER_ID"])
        await owner.send(
            f"**[{discord.utils.format_dt(discord.utils.utcnow(), 'f')}]**\n> Website is now online!"
        )

    @cached(ttl=30, cache=SimpleMemoryCache)
    async def get_owner(self) -> Tuple[bytes, str]:
        """Returns owner's avatar and image type."""
        owner = await self.client.fetch_user(self.env["OWNER_ID"])
        icon = await owner.display_avatar.read()
        image_type = "image/gif" if owner.display_avatar.is_animated() else "image/png"
        return icon, image_type
