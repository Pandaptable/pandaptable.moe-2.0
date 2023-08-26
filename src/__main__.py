import logging

import discord
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
        context = {"x": fuckery.replace("+", " ")[1:]}
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


app.start(url="0.0.0.0", port=app.env["PORT"])
