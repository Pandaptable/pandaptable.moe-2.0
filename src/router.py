import json
import re
import traceback
import discord
import logging
import sys
import sentry_sdk

from loguru import logger
from aiohttp import ClientSession
from datetime import datetime
from supabase import create_client, Client
from discord_interactions import verify_key, InteractionType, InteractionResponseType
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from utils import Website


async def lifespan(_):
    await website.login()
    await website.notify_owner()
    await website.reload_links()
    logger.info("Website & API ready")
    yield
    await website.client.close()
    logger.info("Shut down website & API")


website = Website()

DISCORD_API_BASE = website.env["DISCORD_API_PROXY_URI"] or "https://discord.com"

if website.env["DISCORD_API_PROXY_URI"]:
    from discord.http import Route
    Route.BASE = f"{website.env['DISCORD_API_PROXY_URI']}/api/v10"

sentry_sdk.init(
    dsn=website.env["SENTRY_DSN"],
    integrations=[FastApiIntegration(), StarletteIntegration()],
    traces_sample_rate=1.0,
    profiles_sample_rate=0.5)

app = FastAPI(lifespan=lifespan)

supabase: Client = create_client(
    website.env["DATABASE_URL"], website.env["DATABASE_KEY"]
)
LOG_LEVEL = logging.getLevelName(website.env["LOG_LEVEL"])
JSON_LOGS = True if (website.env["JSON_LOGS"]) == "1" else False

app.mount("/static", StaticFiles(directory="../pandaptable.moe"), name="static")


@app.middleware("http")
async def log_request(req: Request, call_next):
    logger.info(
        "Received request: {} {}", req.method, f"https://pandaptable.moe{req.url.path}"
    )
    embed = discord.Embed(
        title="Request Details", colour=0xCBA6F7, timestamp=datetime.now()
    )
    embed.add_field(
        name="IP Address", value=f"{req.headers.get('cf-connecting-ip')}", inline=False
    )
    embed.add_field(
        name="User Agent", value=f"{req.headers.get('user-agent')}", inline=False
    )
    embed.add_field(name="Request Method", value=f"{req.method}", inline=False)
    embed.add_field(
        name="URL", value=f"https://pandaptable.moe{req.url.path}", inline=False
    )
    embed.set_thumbnail(url="https://pandaptable.moe/icon")
    await website.http_client.post(
        f"{DISCORD_API_BASE}/api/v10/channels/1232181813288505405/messages",
        json={"embeds": [embed.to_dict()]},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bot {website.env['TOKEN']}",
        },
    )
    response = await call_next(req)
    return response


@app.get("/")
async def root(request: Request):
    return website.jinja_template.TemplateResponse(
        name="site.html", context={"request": request}
    )


@app.get("/version")
async def version_handler():
    return f"Version: {website.version}\nUp since: {website.up_since} (JST)"


@app.get("/s/{code}")
async def redirector(code: str):
    if not website.links.get(code):
        await website.reload_links()
    if not website.links.get(code):
        return RedirectResponse("/")
    return RedirectResponse(website.links.get(code))


@app.get("/icon")
async def favicon():
    icon, image_type = await website.get_owner()
    return Response(content=icon, media_type=image_type)


@app.get("/fuck/{fuckery}")
async def fuck_everything(request: Request, fuckery: str):
    lmao = "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz0123456789/+"

    def check(word: str):
        return all(i in lmao for i in word)

    if check(fuckery):
        return website.jinja_template.TemplateResponse(
            name="true.html",
            context={"request": request, "x": fuckery.replace("+", " ")},
        )
    else:
        return website.jinja_template.TemplateResponse(
            name="error.html",
            context={
                "request": request,
                "title": "404",
                "message": "Invalid Characters.\nYou can use + for spaces.",
            },
        )


@app.get("/av/{user_id}")
async def user_avatar(user_id: str):
    if user_id == "@me":
        user_id = str(website.env["OWNER_ID"])
    if not user_id.isdigit():
        return RedirectResponse("/")
    try:
        user: discord.User = await website.client.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        return RedirectResponse("/")
    return RedirectResponse(user.display_avatar.with_size(4096).url)


@app.get("/banner/{user_id}")
async def user_banner(user_id: str):
    if user_id == "@me":
        user_id = str(website.env["OWNER_ID"])
    if not user_id.isdigit():
        return RedirectResponse("/")
    try:
        user: discord.User = await website.client.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        return RedirectResponse("/")
    if not user.banner:
        return RedirectResponse("/")
    return RedirectResponse(user.banner.with_size(4096).url)


@app.get("/u/{user_id}")
async def embed_user(request: Request, user_id: str):
    if user_id == "@me":
        user_id = str(website.env["OWNER_ID"])
    if not user_id.isdigit():
        return RedirectResponse("/")
    try:
        user: discord.User = await website.client.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        return website.jinja_template.TemplateResponse(
            name="user.html",
            context={
                "request": request,
                "tag": "Not Found",
                "description": "User not found",
                "image": "https://cdn.discordapp.com/embed/avatars/0.png",
                "user": user_id,
            },
        )
    description = f"Created: {user.created_at.strftime('%m/%d/%Y, %H:%M:%S')}\n"
    if user.public_flags:
        description += f"Flags: {', '.join([str(flag.name).replace('_', ' ').title() for flag in user.public_flags.all()])}"
    return website.jinja_template.TemplateResponse(
        name="user.html",
        context={
            "request": request,
            "tag": f"{user} (Bot)" if user.bot else user,
            "description": description,
            "image": user.display_avatar.with_size(4096).url,
            "user": user_id,
        },
    )


@app.get("/g/{guild_id}")
async def embed_guild(request: Request, guild_id: str):
    if not guild_id.isdigit():
        return RedirectResponse("/")
    try:
        guild: discord.Widget = await website.client.fetch_widget(guild_id)
    except (discord.Forbidden, discord.HTTPException):
        return website.jinja_template.TemplateResponse(
            name="guild.html",
            context={
                "request": request,
                "name": "Not Found",
                "description": "Guild not found",
                "icon": "",
                "invite": f"https://{website.env['BASE_URL']}",
            },
        )
    invite = await guild.fetch_invite()
    if not invite:
        return website.jinja_template.TemplateResponse(
            name="guild.html",
            context={
                "request": request,
                "name": "Not Found",
                "description": "Guild not found",
                "icon": "",
                "invite": f"https://{website.env['BASE_URL']}",
            },
        )
    description = f"Created: {invite.guild.created_at.strftime('%m/%d/%Y, %H:%M:%S')}\n"
    description += f"🟢 {guild.presence_count}\n"
    description += f"{invite.guild.description}"
    return website.jinja_template.TemplateResponse(
        name="guild.html",
        context={
            "request": request,
            "name": invite.guild.name,
            "description": description,
            "icon": invite.guild.icon.with_size(4096).url,
            "invite": invite.url,
        },
    )


@app.get("/contact")
async def discord_contact(request: Request):
    return website.jinja_template.TemplateResponse(
        name="contact.html",
        context={
            "request": request,
            "title": "By clicking accept, you'll be redirected to a discord login.",
            "message": "This will give me the ability to add you to a group DM and see your connections.",
            "message2": "You can stop me from doing so by removing the connection in settings -> Authorized Apps -> Lain",
            "redirect": f"{website.env['OAUTH2_URL']}",
            "source": "https://github.com/Pandaptable/pandaptable.moe-2.0/blob/master/src/__main__.py",
        },
    )


@app.get("/contact/callback")
async def discord_contact_callback_parse(request: Request):
    query_data = request.query_params
    if "code" not in query_data:
        return website.jinja_template.TemplateResponse(
            name="error.html",
            context={
                "request": request,
                "title": "404",
                "message": "You've canceled the oauth.\n(No parameters provided)",
            },
        )
    else:
        code = query_data["code"]
        data = {
        "client_id": website.env["OAUTH2_CLIENT_ID"],
        "client_secret": website.env["OAUTH2_CLIENT_SECRET"],
        "grant_type": 'authorization_code',
        "code": code,
        "redirect_uri": website.env["OAUTH2_REDIRECT_URI"]
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        token = website.http_client.post(f"{DISCORD_API_BASE}/api/v10/oauth2/token", data=data, headers=headers)
        return await discord_contact_callback_data(token)


async def discord_contact_callback_data(token):
    headers = {
        'Authorization': f"{token['token_type']} {token['access_token']}"
    }
    user = website.http_client.get(f"{DISCORD_API_BASE}/api/v10/users/@me", headers=headers).json()
    connections = website.http_client.get(f"{DISCORD_API_BASE}/api/v10/users/@me/connections", headers=headers).json()
    OAUTH_DATA = {
        "id": user["id"],
        "username": user["username"],
        "avatar": user["avatar"],
        "discriminator": user["discriminator"],
        "public_flags": user["public_flags"],
        "premium_type": user["premium_type"],
        "flags": user["flags"],
        "banner": user["banner"],
        "accent_color": user["accent_color"],
        "global_name": user["global_name"],
        "banner_color": user["banner_color"],
        "mfa_enabled": user["mfa_enabled"],
        "locale": user["locale"],
        "connections": connections,
        "token_type": token["token_type"],
        "access_token": token["access_token"],
        "token_expires_in": token["expires_in"],
        "token_scopes": token["scope"],
        "refresh_token": token["refresh_token"],
    }
    supabase.table("OAUTH_DATA").upsert(OAUTH_DATA).execute()
    banned_status, _ = (
        supabase.table("OAUTH_DATA").select("*").eq("id", OAUTH_DATA["id"]).execute()
    )
    _, banned_status = banned_status
    if not banned_status[0]["banned"]:
        return await discord_contact_callback(OAUTH_DATA)
    else:
        return RedirectResponse(url="/contact/banned")


def num_to_roman(n: int) -> str:
    return chr(0x215F + n)


def getValue(n: int, fmt: str, collection: dict):
    s = fmt.replace("<n>", num_to_roman(n))
    replaced = [collection[m] for m in re.findall(r"<(.*?)>", s)]
    other = re.split(r"<.*?>", s)
    return "".join([x for xs in zip(other, replaced) for x in xs]) + other[-1]


async def discord_contact_callback(OAUTH_DATA):
    connectionsList, _ = (
        supabase.table("OAUTH_DATA").select("*").eq("id", OAUTH_DATA["id"]).execute()
    )
    _, connectionsList = connectionsList
    hashMap = {}
    for connection in connectionsList[0]["connections"]:
        connectionType = connection["type"]
        hashMap.setdefault(connectionType, [])
        hashMap[connectionType].append(connection)

    embed = discord.Embed(
        title=f"@{OAUTH_DATA['username']} / {OAUTH_DATA['global_name']}",
        url=f"https://pandaptable.moe/u/{OAUTH_DATA['id']}",
        colour=0xCBA6F7,
        timestamp=datetime.now(),
    )

    embed.set_author(
        name="Contact Request", icon_url="https://files.catbox.moe/axcja3.png"
    )

    # embed.add_field(name=":domain:Domains", value=f"{hashMap['domain'][0]['name']}", inline=True)
    # ...
    fieldData = {
        "domain": dict(
            num=1187827140381638827, prettyName="Domains", fmt="[<n>](https://<id>)"
        ),
        "steam": dict(
            num=1187827145314160752,
            prettyName="Steam",
            fmt="[<n>](https://steamcommunity.com/profiles/<id>)",
        ),
        "github": dict(
            num=1187827143716118699,
            prettyName="Github",
            fmt="[<n>](https://github.com/<name>)",
        ),
        "epicgames": dict(num=1187827142654963813, prettyName="Epic", fmt="<name>"),
        "youtube": dict(
            num=1187827150208893048,
            prettyName="Youtube",
            fmt="[<n>](https://youtube.com/channel/<id>)",
        ),
        "twitter": dict(
            num=1187827148363419688,
            prettyName="Twitter",
            fmt="[<n>](https://twitter.com/<id>)",
        ),
    }
    for conType in fieldData:
        val = "None"
        conData = fieldData[conType]
        if conType in hashMap:
            val = " | ".join(
                [
                    getValue(i + 1, conData["fmt"], con)
                    for i, con in enumerate(hashMap[conType])
                ]
            )
        embed.add_field(
            name=f"<:{conType}:{conData['num']}> {conData['prettyName']}",
            value=val,
            inline=True,
        )

    embed.set_image(
        url=f"https://cdn.discordapp.com/banners/{OAUTH_DATA['id']}/{OAUTH_DATA['banner']}.png?size=4096"
    )
    embed.set_thumbnail(
        url=f"https://cdn.discordapp.com/avatars/{OAUTH_DATA['id']}/{OAUTH_DATA['avatar']}.png?size=4096"
    )

    embed.set_footer(
        text="pandaptable.moe",
        icon_url="https://dp.nea.moe/avatar/97153209843335168.png",
    )
    await website.http_client.post(
        f"{DISCORD_API_BASE}/api/v10/channels/1145120233447768265/messages",
        json={
            "embeds": [embed.to_dict()],
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "label": "Accept",
                            "style": 3,
                            "custom_id": f"accept-{OAUTH_DATA['id']}",
                        },
                        {
                            "type": 2,
                            "label": "Deny",
                            "style": 2,
                            "custom_id": f"deny-{OAUTH_DATA['id']}",
                        },
                        {
                            "type": 2,
                            "label": "Ban",
                            "style": 4,
                            "custom_id": f"ban-{OAUTH_DATA['id']}",
                        },
                    ],
                }
            ],
        },
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bot {website.env['TOKEN']}",
        },
    )
    return RedirectResponse(url="/contact/success")


@app.get("/contact/success")
async def discord_contact_success(request: Request):
    return website.jinja_template.TemplateResponse(
        name="error.html",
        context={
            "request": request,
            "title": "Contact Success",
            "message": "A contact request has been sent.\nA group DM will be created if I want to talk.",
        },
    )


@app.get("/contact/banned")
async def discord_contact_banned(request: Request):
    return website.jinja_template.TemplateResponse(
        name="error.html",
        context={
            "request": request,
            "title": "L + ratio",
            "message": "I do not want to contact you and banned you from doing so :smileu:",
        },
    )


@app.post("/contact/interactions")
async def discord_contact_interactions(request: Request):
    signature = request.headers.get("x-signature-ed25519")
    timestamp = request.headers.get("x-signature-timestamp")
    body = await request.body()
    if (
        signature is None
        or timestamp is None
        or not verify_key(body, signature, timestamp, website.env["PUBLIC_KEY"])
    ):
        return "Bad request signature", 401

    if json.loads(body) and json.loads(body).get("type") == InteractionType.PING:
        return jsonable_encoder({"type": InteractionResponseType.PONG})

    message = json.loads(body)
    command = message["data"]["custom_id"].split("-")[0]
    user_id = message["data"]["custom_id"].split("-")[1]
    if len(message["data"]["custom_id"].split("-")) == 3:
        param = message["data"]["custom_id"].split("-")[2]
    else:
        param = None

    if command == "deny":
        supabase.table("OAUTH_DATA").delete().eq("id", user_id).execute()
        return Response(
            content=json.dumps(
                {
                    "type": 7,
                    "data": {
                        "embeds": message["message"]["embeds"],
                        "components": [
                            {
                                "type": 1,
                                "components": [
                                    {
                                        "type": 2,
                                        "label": "Request Denied",
                                        "style": 4,
                                        "custom-id": "",
                                        "disabled": 0,
                                    }
                                ],
                            }
                        ],
                    },
                }
            ),
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Authorization": f"Bot {website.env['TOKEN']}",
            },
        )

    if command == "ban":
        supabase.table("OAUTH_DATA").update({"banned": True}).eq(
            "id", user_id
        ).execute()
        return Response(
            content=json.dumps(
                {
                    "type": 7,
                    "data": {
                        "embeds": message["message"]["embeds"],
                        "components": [
                            {
                                "type": 1,
                                "components": [
                                    {
                                        "type": 2,
                                        "label": "User banned",
                                        "style": 4,
                                        "custom-id": "",
                                        "disabled": 0,
                                    }
                                ],
                            }
                        ],
                    },
                }
            ),
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Authorization": f"Bot {website.env['TOKEN']}",
            },
        )
    if command == "close":
        await website.http_client.delete(
            f"{DISCORD_API_BASE}/api/v10/channels/{param}/recipients/{user_id}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {website.env['TOKEN']}",
            },
        )
        await website.http_client.delete(
            f"{DISCORD_API_BASE}/api/v10/channels/{param}/recipients/{website.env['OWNER_ID']}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {website.env['TOKEN']}",
            },
        )
        return Response(
            content=json.dumps(
                {
                    "type": 7,
                    "data": {
                        "embeds": message["message"]["embeds"],
                        "components": [
                            {
                                "type": 1,
                                "components": [
                                    {
                                        "type": 2,
                                        "label": "DM Closed",
                                        "style": 4,
                                        "custom_id": "",
                                        "disabled": 0,
                                    }
                                ],
                            }
                        ],
                    },
                }
            ),
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Authorization": f"Bot {website.env['TOKEN']}",
            },
        )

    if command == "accept":
        user, _ = supabase.table("OAUTH_DATA").select("*").eq("id", user_id).execute()
        _, user = user
        owner, _ = (
            supabase.table("OAUTH_DATA")
            .select("*")
            .eq("id", website.env["OWNER_ID"])
            .execute()
        )
        _, owner = owner
        r = await website.http_client.post(
            f"{DISCORD_API_BASE}/api/v10/oauth2/token",
            data={
                "client_id": website.env["OAUTH2_CLIENT_ID"],
                "client_secret": website.env["OAUTH2_CLIENT_SECRET"],
                "grant_type": "refresh_token",
                "refresh_token": owner[0]["refresh_token"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        owner = r.json()
        refreshed_token = {
            "id": website.env["OWNER_ID"],
            "token_type": owner["token_type"],
            "access_token": owner["access_token"],
            "token_expires_in": owner["expires_in"],
            "token_scopes": owner["scope"],
            "refresh_token": owner["refresh_token"],
        }
        supabase.table("OAUTH_DATA").upsert(refreshed_token).execute()

        r = await website.http_client.post(
            f"{DISCORD_API_BASE}/api/v10/users/@me/channels",
            json={"access_tokens": [owner["access_token"], user[0]["access_token"]]},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {website.env['TOKEN']}",
            },
        )
        channel = r.json()
        return Response(
            content=json.dumps(
                {
                    "type": 7,
                    "data": {
                        "embeds": message["message"]["embeds"],
                        "components": [
                            {
                                "type": 1,
                                "components": [
                                    {
                                        "type": 2,
                                        "label": "See DM",
                                        "style": 5,
                                        "url": f"https://discord.com/channels/@me/{channel['id']}",
                                    },
                                    {
                                        "type": 2,
                                        "label": "Close DM",
                                        "style": 2,
                                        "custom_id": f"close-{user_id}-{channel['id']}",
                                    },
                                    {
                                        "type": 2,
                                        "label": "Ban",
                                        "style": 4,
                                        "custom_id": f"ban-{user_id}",
                                    },
                                ],
                            }
                        ],
                    },
                }
            ),
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "Authorization": f"Bot {website.env['TOKEN']}",
            },
        )


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # find caller from where originated the logged message
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging():
    # intercept everything at the root logger
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(LOG_LEVEL)

    # remove every other logger's handlers
    # and propagate to root logger
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # configure loguru
    logger.configure(handlers=[{"sink": sys.stdout, "serialize": JSON_LOGS}])

    setup_logging()
