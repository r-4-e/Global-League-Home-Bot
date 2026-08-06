"""
verify_web.py — aiohttp routes for anti-alt verification.

Mounted onto the SAME aiohttp app main.py already runs for Render's
health check (`keep_alive`), so this needs no second Render service
and no second process. Because it lives in-process with the bot, role
grants go straight through discord.py instead of a REST round-trip.

Flow:
  1. cogs/verification.py's button mints a token -> /verify/{token}
  2. /verify/{token} validates the token, redirects to Discord's OAuth2
     authorize screen (scope=identify), passing the token as `state`.
  3. Discord redirects back to /callback?code=...&state=...
  4. We exchange the code, fetch the user's profile, confirm it's the
     same account that requested the token, hash their IP (salted
     SHA-256), check it against every previously verified account,
     check account age from the Discord snowflake, and — if clean —
     grant VERIFIED_ROLE_ID directly via the bot's own guild object.
"""

import time
import logging
import urllib.parse

import aiohttp
import discord
from aiohttp import web

import config
from database import db

log = logging.getLogger("elura.verify_web")

DISCORD_API = "https://discord.com/api/v10"
DISCORD_EPOCH_MS = 1420070400000


def snowflake_created_at(discord_id: str) -> float:
    """Discord snowflake IDs encode a creation timestamp — no extra API call needed."""
    ms = (int(discord_id) >> 22) + DISCORD_EPOCH_MS
    return ms / 1000


def get_client_ip(request: web.Request) -> str:
    """
    Render terminates TLS and proxies every request through its own edge,
    so X-Forwarded-For is trustworthy there by default (TRUST_PROXY_HEADERS
    defaults to true). Only keep that default if Render (or another proxy
    you control) is genuinely the sole path into this app — otherwise the
    header is spoofable and defeats the IP-dedup check entirely.
    """
    if config.TRUST_PROXY_HEADERS:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
    peername = request.transport.get_extra_info("peername") if request.transport else None
    return peername[0] if peername else (request.remote or "unknown")


async def log_to_staff(message: str) -> None:
    if not config.VERIFY_LOG_WEBHOOK_URL:
        return
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(
                config.VERIFY_LOG_WEBHOOK_URL,
                json={"content": message},
                timeout=aiohttp.ClientTimeout(total=10),
            )
        except aiohttp.ClientError as exc:
            log.warning("Staff webhook post failed: %s", exc)


def register_verify_routes(app: web.Application, bot: discord.Client) -> None:
    async def start_verify(request: web.Request) -> web.Response:
        token = request.match_info["token"]
        row = await db.get_verify_token(token)
        if row is None or row["used"] or db.is_expired(row["expires_at"]):
            return web.Response(
                text="<h1>This verification link is invalid or has expired.</h1>"
                "<p>Go back to Discord and click Verify again.</p>",
                content_type="text/html",
                status=400,
            )

        if not config.DISCORD_CLIENT_ID or not config.OAUTH_REDIRECT_URI.startswith("http"):
            return web.Response(
                text="<h1>Verification isn't configured yet.</h1><p>Contact staff.</p>",
                content_type="text/html",
                status=500,
            )

        params = {
            "client_id": config.DISCORD_CLIENT_ID,
            "redirect_uri": config.OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "identify",
            "state": token,
            "prompt": "consent",
        }
        raise web.HTTPFound(f"https://discord.com/oauth2/authorize?{urllib.parse.urlencode(params)}")

    async def oauth_callback(request: web.Request) -> web.Response:
        code = request.query.get("code")
        state = request.query.get("state")
        if not code or not state:
            return web.Response(text="<h1>Missing code or state.</h1>", content_type="text/html", status=400)

        row = await db.get_verify_token(state)
        if row is None or row["used"] or db.is_expired(row["expires_at"]):
            return web.Response(
                text="<h1>This verification link is invalid or has expired.</h1>",
                content_type="text/html",
                status=400,
            )
        expected_discord_id = str(row["discord_id"])

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DISCORD_API}/oauth2/token",
                data={
                    "client_id": config.DISCORD_CLIENT_ID,
                    "client_secret": config.DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.OAUTH_REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as token_resp:
                if token_resp.status != 200:
                    return web.Response(
                        text="<h1>Discord authorization failed. Please try again.</h1>",
                        content_type="text/html",
                        status=400,
                    )
                token_data = await token_resp.json()

            async with session.get(
                f"{DISCORD_API}/users/@me",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            ) as user_resp:
                if user_resp.status != 200:
                    return web.Response(
                        text="<h1>Could not fetch your Discord profile.</h1>",
                        content_type="text/html",
                        status=400,
                    )
                user = await user_resp.json()

        discord_id = str(user["id"])
        username = user.get("username", "unknown")

        # The account completing OAuth must match the account that requested the
        # token, so someone can't hand their own link off to an alt to verify it.
        if discord_id != expected_discord_id:
            await log_to_staff(
                f":warning: Verification mismatch — link issued to <@{expected_discord_id}> "
                f"but completed as <@{discord_id}> (`{username}`)."
            )
            return web.Response(
                text="<h1>Account mismatch.</h1><p>Restart verification from Discord using your own account.</p>",
                content_type="text/html",
                status=400,
            )

        await db.mark_verify_token_used(state)

        ip_hash = db.hash_ip(get_client_ip(request))

        existing = await db.find_verified_ip(ip_hash)
        if existing and str(existing["discord_id"]) != discord_id:
            await log_to_staff(
                f":rotating_light: **Verification flagged — duplicate IP**\n"
                f"New attempt: <@{discord_id}> (`{discord_id}`, {username})\n"
                f"Already tied to: <@{existing['discord_id']}> (`{existing['discord_id']}`)"
            )
            return web.Response(
                text="<h1>Verification failed.</h1>"
                "<p>This network is already associated with another verified account. "
                "Contact server staff if you believe this is a mistake.</p>",
                content_type="text/html",
                status=403,
            )

        age_days = (time.time() - snowflake_created_at(discord_id)) / 86400
        if age_days < config.MIN_ACCOUNT_AGE_DAYS:
            await log_to_staff(
                f":rotating_light: **Verification flagged — young account**\n"
                f"<@{discord_id}> (`{discord_id}`, {username}) — account is {age_days:.1f} days old "
                f"(minimum {config.MIN_ACCOUNT_AGE_DAYS})"
            )
            return web.Response(
                text=f"<h1>Verification failed.</h1>"
                f"<p>Your account must be at least {config.MIN_ACCOUNT_AGE_DAYS} days old to verify. "
                "Contact server staff if you think this is wrong.</p>",
                content_type="text/html",
                status=403,
            )

        # Clean — record the IP hash and grant the role directly through the bot,
        # since this web server runs in the same process.
        await db.store_verified_ip(ip_hash, discord_id)

        guild = bot.get_guild(config.GUILD_ID)
        granted = False
        if guild is not None:
            role = guild.get_role(config.VERIFIED_ROLE_ID)
            member = guild.get_member(int(discord_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(discord_id))
                except discord.NotFound:
                    member = None
                except discord.HTTPException as exc:
                    log.error("fetch_member failed for %s: %s", discord_id, exc)
                    member = None
            if member is not None and role is not None:
                try:
                    await member.add_roles(role, reason="Passed anti-alt verification")
                    granted = True
                except discord.Forbidden:
                    granted = False

        if not granted:
            await log_to_staff(
                f":x: <@{discord_id}> (`{discord_id}`) passed all checks but role grant FAILED — "
                "check the bot's permissions and role position in the server's role list."
            )
            return web.Response(
                text="<h1>You're verified, but role assignment failed.</h1>"
                "<p>Contact staff to get your role manually.</p>",
                content_type="text/html",
                status=500,
            )

        await log_to_staff(f":white_check_mark: <@{discord_id}> (`{username}`) verified successfully.")
        return web.Response(
            text="<h1>You're verified!</h1><p>You can close this tab and head back to Discord.</p>",
            content_type="text/html",
        )

    app.router.add_get("/verify/{token}", start_verify)
    app.router.add_get("/callback", oauth_callback)
    log.info("Verification routes registered: /verify/{token}, /callback")
