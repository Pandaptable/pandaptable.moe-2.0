import logging
import json
import requests

import discord
from requests_oauthlib import OAuth2Session
from robyn import Request, Response

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
        with open("templates/false.html", "r") as f:
            html = f.read()
        return Response(
            status_code=200,
            headers={"Content-Type": "text/html"},
            body=html.encode(),
        )


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
def discord_contact_callback_parse(req: Request):
    print(str(req.url))
    discord = OAuth2Session(app.env["OAUTH2_CLIENT_ID"], redirect_uri=app.env["OAUTH2_REDIRECT_URI"], scope=['identify', 'gdm.join', 'connections'])
    query_data = req.queries
    code = query_data['code']
    token = discord.fetch_token(
        "https://discord.com/api/oauth2/token",
        client_secret=(app.env["OAUTH2_CLIENT_SECRET"]),
        authorization_response=str(req.url),
        )
    data = discord_contact_callback_data(token)
    discord_contact_callback(data)


def discord_contact_callback_data(token):
    discord = OAuth2Session(app.env["OAUTH2_CLIENT_ID"], token=token)
    user = discord.get('https://discord.com/api/users/@me').json()
    connections = discord.get('https://discord.com/api/users/@me/connections').json()
    OAUTH_DATA = json.dumps(user, connections)
    return OAUTH_DATA

async def discord_contact_callback(req: Request, OAUTH_DATA):
    discord.Embed.set_thumbnail(
        url=f"https://cdn.discordapp.com/avatars/{OAUTH_DATA['user']['id']}/{OAUTH_DATA['user']['avatar']}.png?size=4096"
    )
    await app.http_client.post(
        "https://discord.com/api/v10/channels/1145120233447768265/messages",
        json={
            "embeds": [discord.Embed.to_dict()],
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
                            "type": 3,
                            "label": "Deny",
                            "style": 3,
                            "custom_id": f"deny-{OAUTH_DATA['user']['id']}",
                        },
                    ],
                }
            ],
        },
        headers={"Content-Type": "application/json", "Authorization": f"Bot {app.env['token']}"},
    )
    return app.redirect("/contact/success")

@app.get("/contact/success")
async def discord_contact_success(req: Request):
    context = {
        "title": "Contact Success",
        "message": "A contact request has been sent.",
    }
    return app.jinja_template.render_template(template_name="error.html", **context)

app.start(url="0.0.0.0", port=app.env["PORT"])
