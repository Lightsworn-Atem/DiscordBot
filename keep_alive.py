from flask import Flask
from threading import Thread
import requests
import os 
import sys
import time

app = Flask('')

@app.route('/')
def home():
    return "Bot actif !"

@app.route('/health')
def health():
    return {"status": "online", "service": "discord_bot"}, 200

def run():
    # Utilise le port fourni par Render ou 8080 par défaut
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def ping_self():
    # URL de votre service Render (remplacez par votre vraie URL)
    render_url = os.getenv("RENDER_URL", "https://discordbot-s7ie.onrender.com")
    
    # Attendre 30 secondes avant le premier ping (laisser le temps au serveur de démarrer)
    time.sleep(30)
    
    while True:
        try:
            if render_url:
                r = requests.get(render_url, timeout=10)
                if r.status_code == 200:
                    print(f"✅ Ping self successful: {r.status_code}")
                else:
                    print(f"⚠️ Ping self warning: {r.status_code}")
            else:
                print("❌ RENDER_URL environment variable not set")
        except requests.exceptions.RequestException as e:
            print(f"🔄 Ping self error (will retry): {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
        
        time.sleep(300)  # ping toutes les 5 minutes

def keep_alive():
    print("🚀 Starting Flask server...")
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    print("🔄 Starting self-ping monitor...")
    monitor = Thread(target=ping_self)
    monitor.daemon = True
    monitor.start()
    
    print("✅ Keep alive service started")