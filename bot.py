import discord
from discord import app_commands
import asyncio
import requests
import os
import threading
import urllib.parse
from flask import Flask, request
import asyncpg  # New: for Neon Postgres

# === Secrets from Environment Only ===
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
REDIRECT_URI = os.environ["REDIRECT_URI"]
DATABASE_URL = os.environ["DATABASE_URL"]

# Fixed AUTH_URL
AUTH_URL = (
    f"https://discord.com/oauth2/authorize?"
    f"client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&response_type=code"
    f"&scope=identify%20guilds.join"
)

TOKEN_URL = "https://discord.com/api/oauth2/token"
ADD_MEMBER_URL = "https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"

# === Neon Postgres Connection Pool ===
pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                access_token TEXT,
                refresh_token TEXT
            )
        """)

# === Flask ===
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return """
    [Your beautiful HTML from before — same as last version]
    """ % AUTH_URL

@flask_app.route("/callback")
@flask_app.route("/callback/")
async def callback():  # Now async because we use DB
    code = request.args.get("code")
    if not code:
        return "<h1>Error: No code</h1>", 400

    # Exchange code
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    r = requests.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if not r.ok:
        return f"<h1>Failed: {r.text}</h1>", 500
    tokens = r.json()

    # Get user ID
    user_info = requests.get("https://discord.com/api/users/@me",
                             headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    user_id = str(user_info["id"])

    # Save to Neon DB
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, access_token, refresh_token)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token
        """, user_id, tokens["access_token"], tokens["refresh_token"])

    return """
    [Your success HTML — same as before]
    """

# === Discord Bot ===
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

async def get_users():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, access_token, refresh_token FROM users")
        return [(row["user_id"], row["access_token"], row["refresh_token"]) for row in rows]

def refresh_access_token(refresh_token):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    r = requests.post(TOKEN_URL, data=data)
    if r.ok:
        return r.json()["access_token"]
    return None

@tree.command(name="join", description="Add all authorized users to this server")
@app_commands.describe(server_id="Server ID")
async def join_command(interaction: discord.Interaction, server_id: str):
    await interaction.response.defer(ephemeral=True)

    try:
        guild_id = int(server_id)
    except:
        await interaction.followup.send("Invalid server ID.", ephemeral=True)
        return

    guild = client.get_guild(guild_id)
    if not guild or not guild.me.guild_permissions.create_instant_invite:
        await interaction.followup.send("Bot not in server or missing perms.", ephemeral=True)
        return

    users = await get_users()
    if not users:
        await interaction.followup.send("No authorized users.", ephemeral=True)
        return

    success = failed = 0
    for user_id, access_token, refresh_token in users:
        # ... same add logic as before ...
        # Use requests.put with access_token
        # If fails, try refresh once
        # Update DB if refreshed
        await asyncio.sleep(0.8)

    await interaction.followup.send(f"Done! Success: {success} | Failed: {failed}", ephemeral=True)

@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot online: {client.user}")

# === Run ===
if __name__ == "__main__":
    # Start Flask in thread
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000))), daemon=True).start()
    
    # Init DB and run bot
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    loop.run_until_complete(client.start(BOT_TOKEN))
