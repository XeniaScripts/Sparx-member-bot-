import os
import threading
import urllib.parse
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request
import discord
from discord import app_commands
import asyncio

# === Environment Variables ===
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
REDIRECT_URI = os.environ["REDIRECT_URI"]
DATABASE_URL = os.environ["DATABASE_URL"]

# === OAuth2 URLs ===
AUTH_URL = (
    f"https://discord.com/oauth2/authorize?"
    f"client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&response_type=code"
    f"&scope=identify%20guilds.join"
)

TOKEN_URL = "https://discord.com/api/oauth2/token"
ADD_MEMBER_URL = "https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"

# === Database ===
def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except Exception as e:
        print(f"DB connection failed: {e}")
        return None

def init_database():
    conn = get_db_connection()
    if not conn:
        print("Skipping DB init — connection failed")
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        access_token TEXT,
                        refresh_token TEXT
                    )
                """)
        print("Database ready.")
    except Exception as e:
        print(f"DB init error (probably already exists): {e}")
    finally:
        conn.close()

init_database()

# === Flask App ===
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sparx Free Members ⚡</title>
        <style>
            body { font-family: Arial, sans-serif; background: #1a1d2e; color: #fff; text-align: center; padding: 60px; }
            h1 { font-size: 50px; background: linear-gradient(90deg, #00ffea, #5865f2, #ff73fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
            .spark { font-size: 70px; }
            .btn { padding: 20px 50px; background: #5865F2; color: white; font-size: 24px; border-radius: 12px; text-decoration: none; box-shadow: 0 10px 30px rgba(88,101,242,0.5); }
            .btn:hover { background: #4752c4; }
        </style>
    </head>
    <body>
        <h1><span class="spark">⚡</span> Sparx Free Members <span class="spark">⚡</span></h1>
        <p>Free instant server joins — forever.</p>
        <a href="%s" class="btn">🔑 Authorize Now</a>
    </body>
    </html>
    """ % AUTH_URL

@flask_app.route("/callback")
@flask_app.route("/callback/")
def callback():
    code = request.args.get("code")
    if not code:
        return "No code", 400

    try:
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }
        r = requests.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        tokens = r.json()

        user_info = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
        user_id = str(user_info["id"])

        conn = get_db_connection()
        if conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (user_id, access_token, refresh_token) VALUES (%s, %s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET access_token = EXCLUDED.access_token, refresh_token = EXCLUDED.refresh_token
                    """, (user_id, tokens["access_token"], tokens["refresh_token"]))
            print(f"User {user_id} authorized and saved.")
            conn.close()

        return """
        <h1 style="color:#00ffea;padding:100px;text-align:center;">✅ SUCCESS ⚡</h1>
        <p>You are now permanently authorized. Close this tab.</p>
        """
    except Exception as e:
        return f"<h1>Error: {str(e)}</h1>", 500

# === Discord Bot in Background Thread ===
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def get_users():
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, access_token, refresh_token FROM users")
                return cur.fetchall()
    except:
        return []

def refresh_single_token(refresh):
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "refresh_token", "refresh_token": refresh}
    r = requests.post(TOKEN_URL, data=data)
    if r.ok:
        return r.json().get("access_token")
    return None

@tree.command(name="join", description="Add all authorized users")
@app_commands.describe(server_id="Server ID")
async def join(interaction: discord.Interaction, server_id: str):
    await interaction.response.defer(ephemeral=True)
    try:
        guild_id = int(server_id)
    except:
        await interaction.followup.send("Bad server ID.", ephemeral=True)
        return

    guild = client.get_guild(guild_id)
    if not guild or not guild.me.guild_permissions.create_instant_invite:
        await interaction.followup.send("Bot not in server or missing perms.", ephemeral=True)
        return

    users = get_users()
    success = failed = 0
    for row in users:
        user_id = row["user_id"]
        token = row["access_token"]
        refresh = row["refresh_token"]
        r = requests.put(ADD_MEMBER_URL.format(guild_id=guild_id, user_id=user_id),
                         headers={"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"},
                         json={"access_token": token})
        if r.status_code not in (201, 204):
            new_token = refresh_single_token(refresh)
            if new_token:
                r2 = requests.put(ADD_MEMBER_URL.format(guild_id=guild_id, user_id=user_id),
                                  headers={"Authorization": f"Bot {BOT_TOKEN}"}, json={"access_token": new_token})
                if r2.status_code in (201, 204):
                    conn = get_db_connection()
                    if conn:
                        with conn:
                            with conn.cursor() as cur:
                                cur.execute("UPDATE users SET access_token = %s WHERE user_id = %s", (new_token, user_id))
                        conn.close()
                    success += 1
                    continue
            failed += 1
        else:
            success += 1
        await asyncio.sleep(1)

    await interaction.followup.send(f"Done! Added: {success} | Failed: {failed}", ephemeral=True)

@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot online: {client.user}")

async def auto_refresh():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            users = get_users()
            for row in users:
                refresh = row["refresh_token"]
                user_id = row["user_id"]
                if refresh:
                    new_token = refresh_single_token(refresh)
                    if new_token:
                        conn = get_db_connection()
                        if conn:
                            with conn:
                                with conn.cursor() as cur:
                                    cur.execute("UPDATE users SET access_token = %s WHERE user_id = %s", (new_token, user_id))
                            conn.close()
            print("Daily token refresh done.")
        except Exception as e:
            print(f"Refresh error: {e}")
        await asyncio.sleep(86400)

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(client.start(BOT_TOKEN))

# === Start Bot in Background ===
threading.Thread(target=run_bot, daemon=True).start()

# === Run Flask in Main Thread (Required for Render) ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)
