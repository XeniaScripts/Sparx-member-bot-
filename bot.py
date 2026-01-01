import discord
from discord import app_commands
import asyncio
import requests
import sqlite3
from flask import Flask, request
import os
import threading

# === Config ===
CLIENT_ID = os.environ.get("CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "YOUR_CLIENT_SECRET")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://your-site.onrender.com/callback")

AUTH_URL = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={requests.utils.quote(REDIRECT_URI, safe='')}&response_type=code&scope=identify%20guilds.join"
TOKEN_URL = "https://discord.com/api/oauth2/token"
ADD_MEMBER_URL = "https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"

# === Database ===
conn = sqlite3.connect("authorized_users.db", check_same_thread=False)
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS users (
             user_id TEXT PRIMARY KEY,
             access_token TEXT,
             refresh_token TEXT
             )""")
conn.commit()

# === Flask App - MUST come BEFORE the routes ===
flask_app = Flask(__name__)

# === Beautiful Home Page ===
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
        </style>
    </head>
    <body>
        <div class="container">
            <h1>⚡ Sparx Free Members ⚡</h1>
            <p>Join any Discord server instantly — completely free!</p>
            <a href="%s" class="btn" target="_blank">🔑 Authorize Me Now</a>
            <div class="features">
                <div class="feature"><h3>🚀 Instant Join</h3><p>One click to join any server the bot is in.</p></div>
                <div class="feature"><h3>🛡️ Safe & Secure</h3><p>Only adds you when you authorize. Full control.</p></div>
                <div class="feature"><h3>💰 100%% Free</h3><p>No payments, no limits. Forever free.</p></div>
            </div>
            <h2>How It Works</h2>
            <p>1. Click the button above and authorize the bot<br>2. Server owners use <code>/join</code> command with their server ID<br>3. All authorized members (like you!) get added instantly<br>4. Enjoy being part of exclusive communities!</p>
            <footer>Made with ❤️ for the Discord community</footer>
        </div>
    </body>
    </html>
    """ % AUTH_URL

# === Callback Route ===
@flask_app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Error: No code provided", 400

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
    <head><title>Success! - Sparx Free Members</title>
    <style>
        body { font-family: Arial; background: #1a1d2e; color: #00ffea; text-align: center; padding: 100px; }
        h1 { font-size: 50px; }
        p { font-size: 24px; color: #b9bbbe; }
        .check { font-size: 100px; }
    </style>
    </head>
    <body>
        <div class="check">✅</div>
        <h1>Authorization Successful!</h1>
        <p>You've been added to the Sparx Free Members list.</p>
        <p>You can now be added to any server using the bot.</p>
        <p><strong>You can safely close this tab.</strong></p>
    </body>
    </html>
    """

# === Rest of Discord Bot Code (intents, client, commands, etc.) ===
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# [Paste the rest of your Discord bot code here: refresh_token function, /join command, on_ready, etc.]

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    client.run(BOT_TOKEN)
