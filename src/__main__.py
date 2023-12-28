import json
import requests
import re
import robyn
import discord
import logging
import sys

from requests_oauthlib import OAuth2Session
from robyn import Request, Response, logger
from loguru import logger
from datetime import datetime
from supabase import create_client, Client
from discord_interactions import InteractionType, InteractionResponseType


from utils import Website

app = Website(__file__)
robyn.logger = logger

supabase: Client = create_client(app.env["DATABASE_URL"], app.env["DATABASE_KEY"])

app.add_directory(
    route="/static",
    directory_path="pandaptable.moe",
    index_file="index.html",
)


@app.before_request()
async def log_request(req: Request):
    logger.info("Received request: {}", req.method, req.body)


@app.after_request()
async def log_response(res: Response):
    logger.info("Sending response: {}", res.status_code, res.body)


@app.startup_handler
async def startup() -> None:
    await app.login()
    await app.notify_owner()
    await app.reload_links()
    logger.info("Website & API ready")


@app.shutdown_handler
async def shutdown_handler() -> None:
    await app.client.close()
    logger.info("Shut down website & API")


@app.get("/version", const=True)
async def version_handler():
    return f"Version: {app.version}\nUp since: {app.up_since} (JST)"


@app.get("/s/:code")
async def redirector(req: Request):
    code: str = req.path_params["code"]
    if not app.links.get(code):
        await app.reload_links()
    if not app.links.get(code):
        return app.redirect("/")
    return app.redirect(app.links.get(code))


@app.get("/icon")
async def favicon():
    icon, image_type = await app.get_owner()
    return Response(
        status_code=200,
        headers={"Content-Type": image_type},
        body=icon,
    )

@app.get("/fuck/:fuckery")
async def fuck_everything(req: Request):
    fuckery = req.path_params["fuckery"]
    lmao = "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz0123456789/+"

    def check(word: str):
        return all(i in lmao for i in word)

    if check(fuckery):
        context = {"x": fuckery.replace("+", " ")}
        return app.jinja_template.render_template(template_name="true.html", **context)
    else:
        context = {
            "title": "404",
            "message": "Invalid Characters.\nYou can use + for spaces.",
        }
        return app.jinja_template.render_template(template_name="error.html", **context)


@app.get("/av/:user_id")
async def user_avatar(req: Request):
    user_id: str = req.path_params["user_id"]
    if user_id == "@me":
        user_id = str(app.env["OWNER_ID"])
    if not user_id.isdigit():
        return app.redirect("/")
    try:
        user: discord.User = await app.client.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        return app.redirect("/")
    return app.redirect(user.display_avatar.with_size(4096).url)


@app.get("/banner/:user_id")
async def user_banner(req: Request):
    user_id: str = req.path_params["user_id"]
    if user_id == "@me":
        user_id = str(app.env["OWNER_ID"])
    if not user_id.isdigit():
        return app.redirect("/")
    try:
        user: discord.User = await app.client.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        return app.redirect("/")
    if not user.banner:
        return app.redirect("/")
    return app.redirect(user.banner.with_size(4096).url)


@app.get("/u/:user_id")
async def embed_user(req: Request):
    user_id: str = req.path_params["user_id"]
    context = None
    if user_id == "@me":
        user_id = str(app.env["OWNER_ID"])
    if not user_id.isdigit():
        return app.redirect("/")
    try:
        user: discord.User = await app.client.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        context = {
            "tag": "Not Found",
            "description": "User not found",
            "image": "https://cdn.discordapp.com/embed/avatars/0.png",
            "user": user_id,
        }
        return app.jinja_template.render_template(template_name="user.html", **context)
    description = f"Created: {user.created_at.strftime('%m/%d/%Y, %H:%M:%S')}\n"
    if user.public_flags:
        description += f"Flags: {', '.join([str(flag.name).replace('_', ' ').title() for flag in user.public_flags.all()])}"
    context = {
        "tag": f"{user} (Bot)" if user.bot else user,
        "description": description,
        "image": user.display_avatar.with_size(4096).url,
        "user": user_id,
    }
    return app.jinja_template.render_template(template_name="user.html", **context)


@app.get("/g/:guild_id")
async def embed_guild(req: Request):
    guild_id: str = req.path_params["guild_id"]
    context = None
    if not guild_id.isdigit():
        return app.redirect("/")
    try:
        guild: discord.Widget = await app.client.fetch_widget(guild_id)
    except (discord.Forbidden, discord.HTTPException):
        context = {
            "name": "Not Found",
            "description": "Guild not found",
            "icon": "",
            "invite": f"https://{app.env['BASE_URL']}",
        }
        return app.jinja_template.render_template(template_name="guild.html", **context)
    invite = await guild.fetch_invite()
    if not invite:
        context = {
            "name": "Not Found",
            "description": "Guild not found",
            "icon": "",
            "invite": f"https://{app.env['BASE_URL']}",
        }
        return app.jinja_template.render_template(template_name="guild.html", **context)
    description = f"Created: {invite.guild.created_at.strftime('%m/%d/%Y, %H:%M:%S')}\n"
    description += f"🟢 {guild.presence_count}\n"
    description += f"{invite.guild.description}"
    context = {
        "name": invite.guild.name,
        "description": description,
        "icon": invite.guild.icon.with_size(4096).url,
        "invite": invite.url,
    }
    return app.jinja_template.render_template(template_name="guild.html", **context)

@app.get("/contact")
def discord_contact(req: Request):
    return app.redirect(app.env["OAUTH2_URL"])


@app.get("/contact/callback")
async def discord_contact_callback_parse(req: Request):
    discord = OAuth2Session(app.env["OAUTH2_CLIENT_ID"], redirect_uri=app.env["OAUTH2_REDIRECT_URI"], scope=['identify', 'gdm.join', 'connections'])
    query_data = req.queries
    code = query_data['code']
    token = discord.fetch_token(
        "https://discord.com/api/oauth2/token",
        client_secret=(app.env["OAUTH2_CLIENT_SECRET"]),
        authorization_response=f"{req.url.scheme}://{req.url.host}{req.url.path}",
        code=code
        )
    data = discord_contact_callback_data(token)
    return await discord_contact_callback(data)

def discord_contact_callback_data(token):
    discord = OAuth2Session(app.env["OAUTH2_CLIENT_ID"], token=token)
    user = discord.get('https://discord.com/api/users/@me').json()
    connections = discord.get('https://discord.com/api/users/@me/connections').json()
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
                    "banned": "false",
                    "refresh_token": token
                    }
    supabase_data = supabase.table('OAUTH_DATA').upsert(OAUTH_DATA).execute()
    return OAUTH_DATA

def num_to_roman(n: int) -> str:
    return chr(0x215F + n)

def getValue(n: int, fmt: str, collection: dict):
    s = fmt.replace("<n>", num_to_roman(n))
    replaced = [collection[m] for m in re.findall(r"<(.*?)>", s)]
    other = re.split(r"<.*?>", s)
    return ''.join([x for xs in zip(other, replaced) for x in xs]) + other[-1]

async def discord_contact_callback(OAUTH_DATA):
    connectionsList, _ = supabase.table('OAUTH_DATA').select('*').eq('id', OAUTH_DATA['id']).execute()
    _, connectionsList = connectionsList
    hashMap = {}
    for connection in connectionsList[0]['connections']:
        connectionType = connection['type']
        hashMap.setdefault(connectionType, [])
        hashMap[connectionType].append(connection)

    embed = discord.Embed(title=f"@{OAUTH_DATA['username']} / {OAUTH_DATA['global_name']}",
                      url=f"https://pandaptable.moe/u/{OAUTH_DATA['id']}",
                      colour=0xcba6f7,
                      timestamp=datetime.now())

    embed.set_author(name="Contact Request", icon_url="https://files.catbox.moe/axcja3.png")

    # embed.add_field(name=":domain:Domains", value=f"{hashMap['domain'][0]['name']}", inline=True)
    # ...
    fieldData = {
        'domain':    dict(num=1187827140381638827, prettyName='Domains', fmt='[<n>](https://<id>)'),
        'steam':     dict(num=1187827145314160752, prettyName='Steam', fmt='[<n>](https://steamcommunity.com/profiles/<id>)'),
        'github':    dict(num=1187827143716118699, prettyName='Github', fmt='[<n>](https://github.com/<name>)'),
        'epicgames': dict(num=1187827142654963813, prettyName='Epic', fmt='<name>'),
        'youtube':   dict(num=1187827150208893048, prettyName='Youtube', fmt='[<n>](https://youtube.com/channel/<id>)'),
        'twitter':   dict(num=1187827148363419688, prettyName='Twitter', fmt='[<n>](https://twitter.com/<id>)'),
    }
    for conType in fieldData:
        val = 'None'
        conData = fieldData[conType]
        if conType in hashMap:
            val = ' | '.join([getValue(i+1, conData['fmt'], con) for i,con in enumerate(hashMap[conType])])
        embed.add_field(name=f"<:{conType}:{conData['num']}> {conData['prettyName']}", value=val, inline=True)

    embed.set_image(url=f"https://cdn.discordapp.com/banners/{OAUTH_DATA['id']}/{OAUTH_DATA['banner']}.png?size=4096")
    embed.set_thumbnail(url=f"https://cdn.discordapp.com/avatars/{OAUTH_DATA['id']}/{OAUTH_DATA['avatar']}.png?size=4096")

    embed.set_footer(text="pandaptable.moe", icon_url="https://dp.nea.moe/avatar/97153209843335168.png")
    await app.http_client.post(
        "https://discord.com/api/channels/1145120233447768265/messages",
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
                            "custom_id": f"ban-{OAUTH_DATA['id']}"
                        }
                    ],
                }
            ],
        },
        headers={"Content-Type": "application/json", "Authorization": f"Bot {app.env['TOKEN']}"},
    )
    return app.redirect("/contact/success")

@app.get("/contact/success")
async def discord_contact_success(req: Request):
    context = {
        "title": "Contact Success",
        "message": "A contact request has been sent.\nA group DM will be created if I want to talk.",
    }
    return app.jinja_template.render_template(template_name="error.html", **context)

@app.post("/contact/interactions")
def discord_contact_interactions(req: Request):
    signature = req.headers.get('x-signature-ed25519')
    timestamp = req.headers.get('x-signature-timestamp')
    if not verify_key(req.data, signature, timestamp, app.env["PUBLIC_KEY"]):
        return Response(status_code=401)
    else:
        if req['type'] == 1:
            return {
                "status_code": 200,
                "headers": {"Content-Type": "application/json;charset=UTF-8"},
                "type": 1
            }

app.start(url="0.0.0.0", port=app.env["PORT"])
