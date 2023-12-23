import logging
import json
import requests

import discord
from requests_oauthlib import OAuth2Session
from robyn import Request, Response
from datetime import datetime

from utils import Website

app = Website(__file__)

app.add_directory(
    route="/",
    directory_path="pandaptable.moe",
    index_file="index.html",
)


@app.startup_handler
async def startup() -> None:
    await app.login()
    await app.notify_owner()
    await app.reload_links()
    logging.info("Website & API ready")


@app.shutdown_handler
async def shutdown_handler() -> None:
    await app.client.close()
    logging.info("Shut down website & API")


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
            "message": "Invalid Characters.\n You can use + for spaces.",
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
    OAUTH_DATA = {"user": user, "connections": connections}
    return OAUTH_DATA

async def discord_contact_callback(OAUTH_DATA):
    connectionsList = OAUTH_DATA['connections']
    hashMap = {}
    i = 0
    while i < len(connectionsList):
        connection = connectionsList[i]
        connectionType = connection['type']
        
        if connectionType not in hashMap.keys():
            hashMap[connectionType] = []
        hashMap[connectionType].append(connection)
        i = i + 1
    print(json.dumps(hashMap))
    embed = discord.Embed(title=f"@{OAUTH_DATA['user']['username']} / {OAUTH_DATA['user']['global_name']}",
                      url=f"https://pandaptable.moe/u/{OAUTH_DATA['user']['id']}",
                      colour=0xcba6f7,
                      timestamp=datetime.now())

    embed.set_author(name="Contact Request", icon_url="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9IiNjYmE2ZjciIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIyIiBkPSJtNCA2bDYuMTA4IDQuNjEybC4wMDIuMDAyYy42NzguNDk3IDEuMDE3Ljc0NiAxLjM4OS44NDJhMiAyIDAgMCAwIDEuMDAyIDBjLjM3Mi0uMDk2LjcxMi0uMzQ1IDEuMzkyLS44NDRjMCAwIDMuOTE3LTMuMDA2IDYuMTA3LTQuNjEyTTMgMTUuOFY4LjJjMC0xLjEyIDAtMS42OC4yMTgtMi4xMDhjLjE5Mi0uMzc3LjQ5Ny0uNjgyLjg3NC0uODc0QzQuNTIgNSA1LjA4IDUgNi4yIDVoMTEuNmMxLjEyIDAgMS42OCAwIDIuMTA3LjIxOGMuMzc3LjE5Mi42ODMuNDk3Ljg3NS44NzRjLjIxOC40MjcuMjE4Ljk4Ny4yMTggMi4xMDV2Ny42MDdjMCAxLjExOCAwIDEuNjc2LS4yMTggMi4xMDRhMi4wMDIgMi4wMDIgMCAwIDEtLjg3NS44NzRjLS40MjcuMjE4LS45ODYuMjE4LTIuMTA0LjIxOEg2LjE5N2MtMS4xMTggMC0xLjY3OCAwLTIuMTA1LS4yMThhMiAyIDAgMCAxLS44NzQtLjg3NEMzIDE3LjQ4IDMgMTYuOTIgMyAxNS44Ii8+PC9zdmc+")
    
    embed.add_field(name="<:domain:1187827140381638827>Domains", value=f"{hashMap['domain'][0]['name']}", inline=True)
    embed.add_field(name="<:steam:1187827145314160752>Steam", value=f"{hashMap['steam'][0]['name']}", inline=True)
    embed.add_field(name="<:github:1187827143716118699>Github", value=f"{hashMap['github'][0]['name']}", inline=True)
    embed.add_field(name="<:epicgames:1187827142654963813>Epic", value=f"{hashMap['epicgames'][0]['name']}", inline=True)
    embed.add_field(name="<:youtube:1187827150208893048>Youtube", value=f"{hashMap['youtube'][0]['name']}", inline=True)
    embed.add_field(name="<:twitter:1187827148363419688>Twitter", value=f"{hashMap['twitter'][0]['name']}", inline=True)
    
    embed.set_image(url=f"https://cdn.discordapp.com/avatars/{OAUTH_DATA['user']['id']}/{OAUTH_DATA['user']['banner']}.png?size=4096")
    embed.set_thumbnail(url=f"https://cdn.discordapp.com/avatars/{OAUTH_DATA['user']['id']}/{OAUTH_DATA['user']['avatar']}.png?size=4096")
    
    embed.set_footer(text="pandaptable.moe", icon_url="https://dp.nea.moe/avatar/97153209843335168.png")
    await app.http_client.post(
        "https://discord.com/api/v10/channels/1145120233447768265/messages",
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
                            "custom_id": f"accept-{OAUTH_DATA['user']['id']}",
                        },
                        {
                            "type": 2,
                            "label": "Deny",
                            "style": 2,
                            "custom_id": f"deny-{OAUTH_DATA['user']['id']}",
                        },
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
        "message": "A contact request has been sent. A group DM will be created if I want to talk.",
    }
    return app.jinja_template.render_template(template_name="error.html", **context)

app.start(url="0.0.0.0", port=app.env["PORT"])
