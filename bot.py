import discord
from discord import app_commands
import requests
import os
import threading
import urllib.parse
import asyncio
from flask import Flask, request
import psycopg2
from psycopg2.extras import RealDictCursor

# === Environment Variables (Set in Render Dashboard) ===
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
REDIRECT_URI = os.environ["REDIRECT_URI"]  # e.g. https://your-site.onrender.com/callback
DATABASE_URL = os.environ["DATABASE_URL"]  # Neon connection string

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

# === Database Connection ===
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# Initialize table safely
def init_database():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        access_token TEXT,
                        refresh_token TEXT
                    )
                """)
            conn.commit()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"DB init warning (table may already exist): {e}")

init_database()

# === Flask Website ===
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
            body { font-family: 'Whitney', 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #1a1d2e, #0f111a); color: #fff; text-align: center; margin: 0; padding: 60px 20px; min-height: 100vh; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { font-size: 52px; background: linear-gradient(90deg, #00ffea, #5865f2, #ff73fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 20px; }
            .spark { font-size: 70px; vertical-align: middle; }
            .btn { display: inline-block; padding: 20px 50px; background: #5865F2; color: white; font-size: 24px; font-weight: bold; text-decoration: none; border-radius: 12px; margin: 40px 0; box-shadow: 0 10px 30px rgba(88,101,242,0.5); transition: 0.3s; }
            .btn:hover { transform: translateY(-8px); background: #4752c4; }
            p { font-size: 20px; color: #b9bbbe; max-width: 700px; margin: 20px auto; line-height: 1.6; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1><span class="spark">⚡</span> Sparx Free Members <span class="spark">⚡</span></h1>
            <p>Join any Discord server instantly — <strong>100% free forever!</strong></p>
            <p>Authorize once and stay added permanently. Tokens are auto-refreshed daily.</p>
            <a href="%s" class="btn">🔑 Authorize Me Now</a>
            <p>Server owners use <code>/join &lt;server_id&gt;</code> to add everyone.</p>
        </div>
    </body>
    </html>
    """ % AUTH_URL

@flask_app.route("/callback")
@flask_app.route("/callback/")
def callback():
    code = request.args.get("code")
    if not code:
        return "<h1 style='color:red;padding:100px;text-align:center;'>Error: No authorization code</h1>", 400

    try:
        # Exchange code for tokens
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

        # Get user ID
        user_info = requests.get("https://discord.com/api/users/@me",
                                 headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
        user_id = str(user_info["id"])

        # Save to Neon DB
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (user_id, access_token, refresh_token)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        access_token = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token
                """, (user_id, tokens["access_token"], tokens["refresh_token"]))
            conn.commit()

        return """
        <!DOCTYPE html>
        <html>
        <head><title>Success ⚡</title></head>
        <body style="background:#1a1d2e;color:#00ffea;text-align:center;padding:100px;font-family:Arial;">
            <h1 style="font-size:60px;">✅ Authorization Successful! ⚡</h1>
            <p style="font-size:26px;">You're now permanently on the Sparx Free Members list!</p>
            <p>Your token will be auto-refreshed daily — you never need to authorize again.</p>
            <p><strong>Safe to close this tab.</strong></p>
        </body>
        </html>
        """
    except Exception as e:
        return f"<h1 style='color:red;padding:100px;text-align:center;'>Error: {str(e)}</h1>", 500

# === Discord Bot ===
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def get_authorized_users():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, access_token, refresh_token FROM users")
                return cur.fetchall()
    except Exception as e:
        print(f"DB read error: {e}")
        return []

def refresh_token(refresh):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }
    r = requests.post(TOKEN_URL, data=data)
    if r.ok:
        return r.json().get("access_token")
    return None

@tree.command(name="join", description="Add all authorized members to a server (bot must be in it)")
@app_commands.describe(server_id="The server (guild) ID")
async def join(interaction: discord.Interaction, server_id: str):
    await interaction.response.defer(ephemeral=True)

    try:
        guild_id = int(server_id)
    except ValueError:
        await interaction.followup.send("Invalid server ID.", ephemeral=True)
        return

    guild = client.get_guild(guild_id)
    if not guild:
        await interaction.followup.send("Bot is not in that server.", ephemeral=True)
        return
    if not guild.me.guild_permissions.create_instant_invite:
        await interaction.followup.send("Bot needs 'Create Instant Invite' permission.", ephemeral=True)
        return

    users = get_authorized_users()
    if not users:
        await interaction.followup.send("No authorized members yet.", ephemeral=True)
        return

    success = failed = 0
    for row in users:
        user_id = row["user_id"]
        token = row["access_token"]
        refresh = row["refresh_token"]

        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        data = {"access_token": token}
        url = ADD_MEMBER_URL.format(guild_id=guild_id, user_id=user_id)
        r = requests.put(url, headers=headers, json=data)

        if r.status_code not in (201, 204):
            new_token = refresh_token(refresh)
            if new_token:
                data["access_token"] = new_token
                r2 = requests.put(url, headers=headers, json=data)
                if r2.status_code in (201, 204):
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE users SET access_token = %s WHERE user_id = %s", (new_token, user_id))
                        conn.commit()
                    success += 1
                    continue
            failed += 1
        else:
            success += 1

        await asyncio.sleep(1)

    await interaction.followup.send(f"Completed! Added: {success} | Failed: {failed}", ephemeral=True)

# === Auto Daily Token Refresh ===
async def auto_refresh_tokens():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            print("Starting daily token refresh...")
            users = get_authorized_users()
            refreshed = 0
            for row in users:
                refresh = row["refresh_token"]
                user_id = row["user_id"]
                if not refresh:
                    continue
                new_token = refresh_token(refresh)
                if new_token:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE users SET access_token = %s WHERE user_id = %s", (new_token, user_id))
                        conn.commit()
                    refreshed += 1
            print(f"Daily refresh complete: {refreshed} tokens updated.")
        except Exception as e:
            print(f"Refresh task error: {e}")

        await asyncio.sleep(86400)  # 24 hours

@client.event
async def on_ready():
    await tree.sync()
    print(f"⚡ Sparx Free Members Bot is online as {client.user} ⚡")
    client.loop.create_task(auto_refresh_tokens())

# === Run Flask + Bot ===
def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    client.run(BOT_TOKEN)
