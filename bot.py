import discord
from discord import app_commands
import requests
import os
import threading
import urllib.parse
from flask import Flask, request
import psycopg2
from psycopg2.extras import RealDictCursor

# === Environment Variables ===
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

# === Safe DB Connection ===
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# === Initialize Table Safely (won't crash app if fails) ===
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
        print("Database table ready.")
    except Exception as e:
        print(f"Warning: Could not initialize DB table: {e}")
        print("Bot will still run — table might already exist or connection issue.")

# Run init at import time (safe)
init_database()

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
        <title>Sparx Free Members ⚡</title>
        <style>
            body { font-family: 'Whitney', 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #1a1d2e, #0f111a); color: #fff; text-align: center; margin: 0; padding: 60px 20px; min-height: 100vh; }
            h1 { font-size: 52px; background: linear-gradient(90deg, #00ffea, #5865f2, #ff73fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
            .spark { font-size: 70px; }
            .btn { display: inline-block; padding: 20px 50px; background: #5865F2; color: white; font-size: 24px; font-weight: bold; text-decoration: none; border-radius: 12px; margin: 40px 0; box-shadow: 0 10px 30px rgba(88,101,242,0.5); transition: 0.3s; }
            .btn:hover { transform: translateY(-8px); background: #4752c4; }
            p { font-size: 20px; color: #b9bbbe; max-width: 700px; margin: 20px auto; }
        </style>
    </head>
    <body>
        <h1><span class="spark">⚡</span> Sparx Free Members <span class="spark">⚡</span></h1>
        <p>Join any Discord server instantly — 100% free forever!</p>
        <a href="%s" class="btn">🔑 Authorize Me Now</a>
        <p>One click to let the bot add you to servers with /join command.</p>
    </body>
    </html>
    """ % AUTH_URL

@flask_app.route("/callback")
@flask_app.route("/callback/")
def callback():
    code = request.args.get("code")
    if not code:
        return "<h1 style='color:red;text-align:center;padding:100px;'>Error: No code provided</h1>", 400

    try:
        # Token exchange
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

        # Get user info
        user_info = requests.get("https://discord.com/api/users/@me",
                                 headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
        user_id = str(user_info["id"])

        # Save to DB safely
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
            <p style="font-size:26px;">You're now on the Sparx Free Members list.</p>
            <p>You can be added to any server using the bot.</p>
            <p><strong>Safe to close this tab.</strong></p>
        </body>
        </html>
        """
    except Exception as e:
        return f"<h1 style='color:red;text-align:center;padding:100px;'>Error: {str(e)}</h1>", 500

# === Rest of bot code remains the same (join command, etc.) ===
# ... [keep your Discord bot code exactly as in previous version]

# === Run ===
def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    client.run(BOT_TOKEN)
