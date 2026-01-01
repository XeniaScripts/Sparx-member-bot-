import discord
from discord import app_commands
import asyncio
import requests
import sqlite3
from flask import Flask, request
import os
import threading
import urllib.parse  # For proper URL encoding

# === Environment Variables (Set these in Render dashboard) ===
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIRECT_URI = os.environ.get("REDIRECT_URI")  # e.g. https://your-site.onrender.com/callback

if not all([CLIENT_ID, CLIENT_SECRET, BOT_TOKEN, REDIRECT_URI]):
    raise ValueError("Missing required environment variables!")

# === Fixed AUTH_URL with proper encoding ===
AUTH_URL = (
    f"https://discord.com/oauth2/authorize?"
    f"client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&response_type=code"
    f"&scope=identify%20guilds.join"
)

TOKEN_URL = "https://discord.com/api/oauth2/token"
ADD_MEMBER_URL = "https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"

# === Database Setup ===
conn = sqlite3.connect("authorized_users.db", check_same_thread=False)
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS users (
             user_id TEXT PRIMARY KEY,
             access_token TEXT,
             refresh_token TEXT
             )""")
conn.commit()

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
        <title>Sparx Free Members - Join Any Server Instantly</title>
        <style>
            body { font-family: 'Whitney', 'Helvetica Neue', Helvetica, Arial, sans-serif; background: linear-gradient(135deg, #1a1d2e, #0f111a); color: #fff; text-align: center; margin: 0; padding: 0; min-height: 100vh; display: flex; flex-direction: column; justify-content: center; }
            .container { max-width: 800px; margin: 0 auto; padding: 40px; }
            h1 { font-size: 48px; background: linear-gradient(90deg, #00ffea, #5865f2, #ff73fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 20px; }
            p { font-size: 20px; line-height: 1.6; margin: 20px 0; color: #b9bbbe; }
            .btn { display: inline-block; padding: 18px 40px; background: #5865F2; color: white; font-size: 22px; font-weight: bold; text-decoration: none; border-radius: 12px; margin: 30px 0; box-shadow: 0 8px 20px rgba(88, 101, 242, 0.4); transition: all 0.3s; }
            .btn:hover { transform: translateY(-5px); box-shadow: 0 15px 30px rgba(88, 101, 242, 0.6); background: #4752c4; }
            .features { display: flex; justify-content: center; gap: 30px; margin: 50px 0; flex-wrap: wrap; }
            .feature { background: rgba(255, 255, 255, 0.05); padding: 25px; border-radius: 16px; width: 250px; backdrop-filter: blur(10px); }
            .feature h3 { color: #00ffea; margin-bottom: 10px; }
            footer { margin-top: 80px; color: #72767d; font-size: 14px; }
            .lightning { font-size: 60px; margin: 0 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1><span class="lightning">⚡</span> Sparx Free Members <span class="lightning">⚡</span></h1>
            <p>Join any Discord server instantly — completely free!</p>
            <a href="%s" class="btn" target="_blank">🔑 Authorize Me Now</a>
            <div class="features">
                <div class="feature"><h3>🚀 Instant Join</h3><p>One click to join any server the bot is in.</p></div>
                <div class="feature"><h3>🛡️ Safe & Secure</h3><p>Only adds you with your permission.</p></div>
                <div class="feature"><h3>💰 100%% Free</h3><p>No payments. Forever free.</p></div>
            </div>
            <h2>How It Works</h2>
            <p>1. Click Authorize → login to Discord<br>2. Server owners use <code>/join &lt;server_id&gt;</code><br>3. All authorized members get added instantly!</p>
            <footer>Made with ❤️ for the Discord community</footer>
        </div>
    </body>
    </html>
    """ % AUTH_URL

@flask_app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Error: No authorization code provided.", 400

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(TOKEN_URL, data=data, headers=headers)
    if not r.ok:
        return f"Token exchange failed: {r.text}", 500
    tokens = r.json()

    user_info = requests.get("https://discord.com/api/users/@me",
                             headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    user_id = user_info["id"]

    c.execute("INSERT OR REPLACE INTO users (user_id, access_token, refresh_token) VALUES (?, ?, ?)",
              (user_id, tokens["access_token"], tokens["refresh_token"]))
    conn.commit()

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Success! ⚡ Sparx Free Members</title>
        <style>
            body { font-family: Arial, sans-serif; background: #1a1d2e; color: #00ffea; text-align: center; padding: 100px; }
            h1 { font-size: 50px; }
            p { font-size: 24px; color: #b9bbbe; }
            .check { font-size: 100px; }
            .spark { color: #ff73fa; }
        </style>
    </head>
    <body>
        <div class="check">✅</div>
        <h1>Authorization Successful! <span class="spark">⚡</span></h1>
        <p>You've joined the Sparx Free Members list.</p>
        <p>You can now be added to any server using the bot.</p>
        <p><strong>Safe to close this tab.</strong></p>
    </body>
    </html>
    """

# === Discord Bot ===
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

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

@tree.command(name="join", description="Add all authorized users to a server (bot must be in it)")
@app_commands.describe(server_id="The server ID to add users to")
async def join_command(interaction: discord.Interaction, server_id: str):
    await interaction.response.defer(ephemeral=True)

    try:
        guild_id_int = int(server_id)
    except ValueError:
        await interaction.followup.send("Invalid server ID format.", ephemeral=True)
        return

    guild = client.get_guild(guild_id_int)
    if not guild:
        await interaction.followup.send("Bot is not in that server.", ephemeral=True)
        return

    if not guild.me.guild_permissions.create_instant_invite:
        await interaction.followup.send("Bot needs 'Create Instant Invite' permission.", ephemeral=True)
        return

    c.execute("SELECT user_id, access_token, refresh_token FROM users")
    users = c.fetchall()
    if not users:
        await interaction.followup.send("No authorized users yet.", ephemeral=True)
        return

    success = 0
    failed = 0

    for user_id, access_token, refresh_token in users:
        token = access_token
        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        data = {"access_token": token}
        url = ADD_MEMBER_URL.format(guild_id=guild_id_int, user_id=user_id)
        r = requests.put(url, headers=headers, json=data)

        if r.status_code not in (201, 204):
            new_token = refresh_access_token(refresh_token)
            if new_token:
                data = {"access_token": new_token}
                r2 = requests.put(url, headers=headers, json=data)
                if r2.status_code in (201, 204):
                    success += 1
                    c.execute("UPDATE users SET access_token=? WHERE user_id=?", (new_token, user_id))
                    conn.commit()
                    continue
            failed += 1
        else:
            success += 1

        await asyncio.sleep(1.1)

    await interaction.followup.send(f"Done! Added: {success} | Failed: {failed}", ephemeral=True)

@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot logged in as {client.user} | Website: {REDIRECT_URI.replace('/callback', '')}")

# === Run Flask + Bot ===
def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    client.run(BOT_TOKEN)
