from flask import Flask
from threading import Thread
import requests
import os 
import sys
import time

app = Flask('')
KEEP_ALIVE_URL = "https://e452861f-0ced-458c-b285-a009c7261654-00-orp7av1otz2y.picard.replit.dev/"


@app.route('/')
def home():
    return "Bot actif !"

def run():
    # Lancer le serveur Flask
    app.run(host='0.0.0.0', port=8080)

def ping_self():
    url_env = os.getenv("KEEP_ALIVE_URL")  # URL publique Replit
    if not url_env:
        print("KEEP_ALIVE_URL not set.  Falling back to hardcoded URL.")
        url_env = "https://e452861f-0ced-458c-b285-a009c7261654-00-orp7av1otz2y.picard.replit.dev/" #Hardcoded URL as fallback
    while True:
        try:
            if url_env:
                url = url_env
                r = requests.get(url, timeout=10)
                print(f"Ping: {r.status_code}")
            else:
                print("KEEP_ALIVE_URL environment variable not set.")
        except Exception as e:
            print(f"Erreur de connexion : {e}")
        time.sleep(300)  # ping toutes les 5 minutes

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    monitor = Thread(target=ping_self)
    monitor.daemon = True
    monitor.start()