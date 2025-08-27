import discord
from discord.ext import commands
import json
import os
from keep_alive import keep_alive
from discord.ext import tasks
import random
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
from keep_alive import keep_alive
import copy


# --- CONFIG ---
TOKEN = os.getenv("DISCORD_TOKEN")  # Mets ton token Discord ici
PREFIX = "!"  # Commandes commencent par !
DATABASE_URL = os.getenv("DATABASE_URL")


# --- INITIALISATION ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# --- STATUTS CYCLIQUES DU BOT ---
STATUSES = [
    "Envoyer Mathmech Sigma au cimetière",
    "Traumatiser FszOpen",
    "Ne pas se prendre Ash blossom"
]

@tasks.loop(seconds=3600)  # ajuste l'intervalle si tu veux
async def cycle_status():
    if not hasattr(cycle_status, "_idx"):
        cycle_status._idx = 0
    game = discord.Game(STATUSES[cycle_status._idx])
    await bot.change_presence(activity=game)
    cycle_status._idx = (cycle_status._idx + 1) % len(STATUSES)

print("🚀 main.py a bien été relancé")
TOURNAMENT_STARTED = False

"""@bot.check
async def check_tournament(ctx):
    # Autoriser la commande help ou le créateur
    if ctx.command.name == 'help' or ctx.author.id == OWNER_ID:
        return True

    # Vérifier si le tournoi a commencé
    if not TOURNAMENT_STARTED:
        await ctx.send("Le tournoi n'a pas encore commencé, le bot ne sera activé qu'à ce moment là.")
        return False

    return True"""



# --- DONNÉES ---
zones = ["Parc", "Docks", "KaibaCorp", "Quartier", "Ruines"]

BOUTIQUE_INITIALE = {
    "packs": {
        "Super Polymérisation": {
            "prix": 150,
            "cartes": ["Super Polymerisation (x3)", "Mudragon of the Swamp", "Saint Azamina",
                       "Garura, Wings of Resonant Life", "Earth Golem @Ignister"]
        },
        "Light Fiend": {
            "prix": 150,
            "cartes": ["Fiendsmith Engraver", "Weiss, Lightsworn Archfiend (x2)", "Evilswarm Exciton Knight",
                       "Moon of the Closed Heaven", "Fiendsmith Tract"]
        },
        "Loi de la Normale": {
            "prix": 150,
            "cartes": ["Primite Dragon Ether Beryl (x2)", "Primite Roar (x2)", "Primite Drillbeam",
                       "Unexpected Dai (x2)"]
        },
        "Dix Siècles": {
            "prix": 150,
            "cartes": ["Sengenjin Awakes from a Millennium (x2)", "Sengenjin (x3)", "Zombie Vampire",
                       "Snake-Eyes Doomed Dragon"]
        },
        "Chaos": {
            "prix": 150,
            "cartes": ["Chaos Dragon Levianeer", "Chaos Space", "Chaos Angel", "Chaos Archfiend"]
        },
        "Monstres Ardents": {
            "prix": 150,
            "cartes": ["Snake-Eye Ash", "Snake-Eyes Poplar", "Snake-Eyes Flamberge Dragon"]
        }
    },
    "shops": {
        "Staples": {
            "cartes": {
                "Triple Tactics Talents": 10,
                "Triple Tactics Thrust": 80,
                "Harpie's Feather Duster": 70,
                "Heavy Storm": 70,
                "Evenly Matched": 100,
                "Ghost Ogre & Snow Rabbit": 80,
                "Ghost Belle & Haunted Mansion": 80,
                "Nibiru, the Primal Being": 80,
                "S:P Little Knight": 100
            }
        },
        "JVC": {
            "cartes": {
                "Fairy Tail Snow": 70,
                "Curious, the Lightsworn Dominion": 70,
                "Mathmech Circular": 70,
                "Sillva, Warlord of Dark World": 70,
                "Superheavy Samurai Wakaushi": 70,
                "Amorphactor Pain": 70,
                "Masked HERO Dark Law": 70,
                "Isolde, Two Tales of the Noble Knights": 70,
                "Trishula, Dragon of the Ice Barrier": 70
            },
            "limite_par_joueur": 1
        },
        "Bannis": {
            "cartes": {
                "Pot of Greed": 200,
                "Graceful Charity": 200,
                "Painful Choice": 200
            },
            "limite_par_joueur": 1
        }
    }
}

positions = {}     # {user_id: zone}
joueurs = {}       # {user_id: {"or": int, "etoiles": int}}
elimines = set()   # user_id éliminés
inventaires = {}   # {user_id: {"or": int, "cartes": []}}
achats_uniques = {}  # {user_id: {item: True}}
commandes_utilisees = {}  # {user_id: {"fsz": True, "fman": True, ...}}
commandes_uniques_globales = {}
derniers_deplacements = {}
GAGNANTS_JVC_IDS = set()  # Tu pourras ajouter les IDs via une commande admin

# --- CONNEXION BASE DE DONNÉES ---
def get_db_connection():
    """Crée une connexion à la base PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"Erreur connexion DB: {e}")
        return None

def init_database():
    """Initialise les tables de la base de données"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cursor = conn.cursor()
        
        # Table des joueurs (mise à jour avec nouveaux champs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS joueurs (
                user_id BIGINT PRIMARY KEY,
                or_amount INTEGER DEFAULT 30,
                etoiles INTEGER DEFAULT 2,
                statuts JSONB DEFAULT '[]'::jsonb,
                minerva_shield BOOLEAN DEFAULT FALSE,
                negociateur BOOLEAN DEFAULT FALSE,
                atem_shield BOOLEAN DEFAULT FALSE,
                skream_omnipresent BOOLEAN DEFAULT FALSE,
                tyrano_active BOOLEAN DEFAULT FALSE,
                yop_coin_guaranteed BOOLEAN DEFAULT FALSE
            )
        """)

        # Nouvelle table pour les gagnants JVC
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gagnants_jvc (
                user_id BIGINT PRIMARY KEY
            )
        """)
        
        # Table des positions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                user_id BIGINT PRIMARY KEY,
                zone VARCHAR(50) DEFAULT 'KaibaCorp'
            )
        """)
        
        # Table des éliminés
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS elimines (
                user_id BIGINT PRIMARY KEY
            )
        """)
        
        # Table des inventaires
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventaires (
                user_id BIGINT PRIMARY KEY,
                or_amount INTEGER DEFAULT 30,
                cartes JSONB DEFAULT '[]'::jsonb
            )
        """)
        
        # Table des achats uniques
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS achats_uniques (
                user_id BIGINT,
                shop_name VARCHAR(100),
                PRIMARY KEY (user_id, shop_name)
            )
        """)
        
        # Table des commandes globales
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commandes_globales (
                command_name VARCHAR(100) PRIMARY KEY,
                used BOOLEAN DEFAULT FALSE,
                user_id BIGINT DEFAULT NULL
            )
        """)
        
        # Table des derniers déplacements
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS derniers_deplacements (
                user_id BIGINT PRIMARY KEY,
                needs_duel BOOLEAN DEFAULT FALSE
            )
        """)
        
        # Table de la boutique
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS boutique_data (
                id INTEGER PRIMARY KEY DEFAULT 1,
                data JSONB
            )
        """)
        
        # Table des bans temporaires
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bans_temp (
                joueur VARCHAR(100) PRIMARY KEY,
                deck VARCHAR(200)
            )
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Base de données initialisée")
        return True
        
    except Exception as e:
        print(f"Erreur init DB: {e}")
        if conn:
            conn.close()
        return False


def peut_utiliser_commande_unique(nom: str) -> bool:
    """
    Vérifie si la commande 'nom' a déjà été utilisée globalement (par n'importe qui).
    Retourne True si c'est la première fois, sinon False.
    """
    global commandes_uniques_globales
    if commandes_uniques_globales.get(nom):
        return False
    commandes_uniques_globales[nom] = True
    save_data()
    return True


exclusive_commands = ["fsz", "zaga", "fman", "capitaine", "fayth", "shaman", "atem", "skream", "tyrano", "retro", "voorhees", "yop"]

def can_use_exclusive(user_id: int, cmd_name: str):
    global commandes_uniques_globales

    if "exclusives_globales" not in commandes_uniques_globales:
        commandes_uniques_globales["exclusives_globales"] = {}
    if "exclusives_joueurs" not in commandes_uniques_globales:
        commandes_uniques_globales["exclusives_joueurs"] = {}

    # Déjà utilisée par quelqu'un
    if commandes_uniques_globales["exclusives_globales"].get(cmd_name, False):
        return False, "Cette commande a déjà été utilisée."

    # Ce joueur a déjà utilisé une exclusive
    if commandes_uniques_globales["exclusives_joueurs"].get(str(user_id), False):
        return False, "Tu as déjà utilisé une commande spéciale, tu ne peux pas en reprendre une autre."

    return True, None


def lock_exclusive(user_id: int, cmd_name: str):
    global commandes_uniques_globales

    commandes_uniques_globales["exclusives_globales"][cmd_name] = True
    commandes_uniques_globales["exclusives_joueurs"][str(user_id)] = True
    save_data()


def save_data():
    """Sauvegarde tous les données en base - VERSION CORRIGÉE"""
    conn = get_db_connection()
    if not conn:
        print("❌ Impossible de se connecter à la DB pour sauvegarder")
        return
        
    try:
        cursor = conn.cursor()
        
        # Sauvegarder les joueurs (avec nouveaux champs)
        for user_id, data in joueurs.items():
            try:
                cursor.execute("""
                    INSERT INTO joueurs (user_id, or_amount, etoiles, statuts, minerva_shield, negociateur, 
                               atem_shield, skream_omnipresent, tyrano_active, yop_coin_guaranteed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        or_amount = EXCLUDED.or_amount,
                        etoiles = EXCLUDED.etoiles,
                        statuts = EXCLUDED.statuts,
                        minerva_shield = EXCLUDED.minerva_shield,
                        negociateur = EXCLUDED.negociateur,
                        atem_shield = EXCLUDED.atem_shield,
                        skream_omnipresent = EXCLUDED.skream_omnipresent,
                        tyrano_active = EXCLUDED.tyrano_active,
                        yop_coin_guaranteed = EXCLUDED.yop_coin_guaranteed
                """, (
                    int(user_id), 
                    data.get('or', 30), 
                    data.get('etoiles', 2),
                    json.dumps(data.get('statuts', [])),
                    data.get('minerva_shield', False),
                    data.get('negociateur', False),
                    data.get('atem_shield', False),
                    data.get('skream_omnipresent', False),
                    data.get('tyrano_active', False),
                    data.get('yop_coin_guaranteed', False)
                ))
            except Exception as e:
                print(f"Erreur sauvegarde joueur {user_id}: {e}")
                continue
        
        # Sauvegarder les positions
        for user_id, zone in positions.items():
            try:
                cursor.execute("""
                    INSERT INTO positions (user_id, zone) VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET zone = EXCLUDED.zone
                """, (int(user_id), str(zone)))
            except Exception as e:
                print(f"Erreur sauvegarde position {user_id}: {e}")
                continue
        
        # Sauvegarder les éliminés
        try:
            cursor.execute("DELETE FROM elimines")
            for user_id in elimines:
                cursor.execute("INSERT INTO elimines (user_id) VALUES (%s)", (int(user_id),))
        except Exception as e:
            print(f"Erreur sauvegarde éliminés: {e}")
        
        # Sauvegarder les inventaires
        for user_id, data in inventaires.items():
            try:
                cursor.execute("""
                    INSERT INTO inventaires (user_id, or_amount, cartes)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        or_amount = EXCLUDED.or_amount,
                        cartes = EXCLUDED.cartes
                """, (int(user_id), data.get('or', 30), json.dumps(data.get('cartes', []))))
            except Exception as e:
                print(f"Erreur sauvegarde inventaire {user_id}: {e}")
                continue
        
        # Sauvegarder les achats uniques
        try:
            cursor.execute("DELETE FROM achats_uniques")
            for user_id, shops in achats_uniques.items():
                for shop_name in shops.keys():
                    cursor.execute("""
                        INSERT INTO achats_uniques (user_id, shop_name) VALUES (%s, %s)
                    """, (int(user_id), str(shop_name)))
        except Exception as e:
            print(f"Erreur sauvegarde achats uniques: {e}")
        
        # Sauvegarder les commandes globales
        try:
            # D'abord, sauvegarder les commandes exclusives globales
            for cmd_name, used in commandes_uniques_globales.get('exclusives_globales', {}).items():
                cursor.execute("""
                    INSERT INTO commandes_globales (command_name, used)
                    VALUES (%s, %s)
                    ON CONFLICT (command_name) DO UPDATE SET used = EXCLUDED.used
                """, (str(cmd_name), bool(used)))
            
            # Sauvegarder aussi les commandes anciennes au niveau racine (compatibilité)
            for cmd_name, used in commandes_uniques_globales.items():
                if cmd_name not in ['exclusives_globales', 'exclusives_joueurs'] and isinstance(used, bool):
                    cursor.execute("""
                        INSERT INTO commandes_globales (command_name, used)
                        VALUES (%s, %s)
                        ON CONFLICT (command_name) DO UPDATE SET used = EXCLUDED.used
                    """, (str(cmd_name), bool(used)))
        except Exception as e:
            print(f"Erreur sauvegarde commandes globales: {e}")
        
        # Sauvegarder les derniers déplacements
        try:
            for user_id, needs_duel in derniers_deplacements.items():
                cursor.execute("""
                    INSERT INTO derniers_deplacements (user_id, needs_duel)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET needs_duel = EXCLUDED.needs_duel
                """, (int(user_id), bool(needs_duel)))
        except Exception as e:
            print(f"Erreur sauvegarde derniers déplacements: {e}")
        
        # Sauvegarder la boutique
        try:
            cursor.execute("""
                INSERT INTO boutique_data (id, data) VALUES (1, %s)
                ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
            """, (json.dumps(boutique),))
        except Exception as e:
            print(f"Erreur sauvegarde boutique: {e}")
        
        # Sauvegarder les bans temporaires
        try:
            cursor.execute("DELETE FROM bans_temp")
            for joueur, deck in bans_temp.items():
                cursor.execute("""
                    INSERT INTO bans_temp (joueur, deck) VALUES (%s, %s)
                """, (str(joueur), str(deck)))
        except Exception as e:
            print(f"Erreur sauvegarde bans temporaires: {e}")

        # Sauvegarder les gagnants JVC
        try:
            cursor.execute("DELETE FROM gagnants_jvc")
            for user_id in GAGNANTS_JVC_IDS:
                cursor.execute("INSERT INTO gagnants_jvc (user_id) VALUES (%s)", (int(user_id),))
        except Exception as e:
            print(f"Erreur sauvegarde gagnants JVC: {e}")
        
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Sauvegarde réussie")
        
    except Exception as e:
        print(f"Erreur générale sauvegarde: {e}")
        if conn:
            conn.rollback()
            conn.close()

def load_data():
    """Charge toutes les données depuis la base - VERSION CORRIGÉE"""
    global joueurs, positions, elimines, inventaires, achats_uniques
    global commandes_uniques_globales, derniers_deplacements, boutique, bans_temp
    
    conn = get_db_connection()
    if not conn:
        print("❌ Impossible de se connecter à la DB pour charger")
        return
        
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Charger les joueurs (avec nouveaux champs)
        cursor.execute("SELECT * FROM joueurs")
        joueurs.clear()
        for row in cursor.fetchall():
            joueurs[row['user_id']] = {
                'or': row['or_amount'],
                'etoiles': row['etoiles'],
                'statuts': row['statuts'] if row['statuts'] else [],
                'minerva_shield': row['minerva_shield'],
                'negociateur': row['negociateur'],
                'atem_shield': row.get('atem_shield', False),
                'skream_omnipresent': row.get('skream_omnipresent', False),
                'tyrano_active': row.get('tyrano_active', False),
                'yop_coin_guaranteed': row.get('yop_coin_guaranteed', False)
            }
        
        # Charger les positions
        cursor.execute("SELECT * FROM positions")
        positions.clear()
        for row in cursor.fetchall():
            positions[row['user_id']] = row['zone']
        
        # Charger les éliminés
        cursor.execute("SELECT user_id FROM elimines")
        elimines.clear()
        elimines.update(row['user_id'] for row in cursor.fetchall())
        
        # Charger les inventaires
        cursor.execute("SELECT * FROM inventaires")
        inventaires.clear()
        for row in cursor.fetchall():
            inventaires[row['user_id']] = {
                'or': row['or_amount'],
                'cartes': row['cartes'] if row['cartes'] else []
            }
        
        # Charger les achats uniques
        cursor.execute("SELECT * FROM achats_uniques")
        achats_uniques.clear()
        for row in cursor.fetchall():
            if row['user_id'] not in achats_uniques:
                achats_uniques[row['user_id']] = {}
            achats_uniques[row['user_id']][row['shop_name']] = True
        
        # Charger les commandes globales
        cursor.execute("SELECT * FROM commandes_globales")
        commandes_uniques_globales = {
            'exclusives_globales': {},
            'exclusives_joueurs': {}
        }
        for row in cursor.fetchall():
            commandes_uniques_globales['exclusives_globales'][row['command_name']] = row['used']
        
        # Charger les derniers déplacements
        cursor.execute("SELECT * FROM derniers_deplacements")
        derniers_deplacements.clear()
        for row in cursor.fetchall():
            derniers_deplacements[str(row['user_id'])] = row['needs_duel']
        
        # Charger la boutique
        cursor.execute("SELECT data FROM boutique_data WHERE id = 1")
        row = cursor.fetchone()
        boutique.clear()
        if row and row['data']:
            boutique.update(row['data'])
        else:
            boutique.update(BOUTIQUE_INITIALE)
        
        # Charger les bans temporaires
        cursor.execute("SELECT * FROM bans_temp")
        bans_temp.clear()
        for row in cursor.fetchall():
            bans_temp[row['joueur']] = row['deck']

        cursor.execute("SELECT user_id FROM gagnants_jvc")
        GAGNANTS_JVC_IDS.clear()
        GAGNANTS_JVC_IDS.update(row['user_id'] for row in cursor.fetchall())
        
        cursor.close()
        conn.close()
        print("✅ Données chargées depuis PostgreSQL")
        
    except Exception as e:
        print(f"Erreur chargement: {e}")
        if conn:
            conn.close()

# --- UTILITAIRES ---
def est_inscrit(user_id):
    return user_id in joueurs


@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Commandes disponibles", color=discord.Color.blue())
    embed.add_field(name="!inscrire", value="Inscris-toi au tournoi", inline=False)
    embed.add_field(name="!aller", value="Va dans une zone du tournoi", inline=False)
    embed.add_field(name="!zones_dispo", value="Affiche la liste des zones", inline=False)
    embed.add_field(name="!ou", value="Affiche la zone où tu es", inline=False)
    embed.add_field(name="!boutique_cmd", value="Affiche la boutique", inline=False)
    embed.add_field(name="!inventaire", value="Affiche ton inventaire", inline=False)
    embed.add_field(name="!profil", value="Affiche ton profil", inline=False)
    embed.add_field(name="!duel @Gagnant @Perdant (Étoiles) (Or)", value="Démarre un duel", inline=False)
    # Pas de commandes spéciales ni secrètes ici
    await ctx.send(embed=embed)



# --- INITIALISATION DU BOT ---
@bot.event
async def on_ready():
    # Initialiser la DB
    if init_database():
        load_data()
    
    # Démarrer les tâches périodiques
    if not cycle_status.is_running():
        cycle_status.start()
    
    await bot.change_presence(activity=discord.Game("Bot initialisé"))
    print(f"✅ Connecté en tant que {bot.user}")


# --- INSCRIPTION ---
@bot.command()
async def inscrire(ctx):
    user = ctx.author
    if est_inscrit(user.id):
        await ctx.send(f"❌ {user.display_name} est déjà inscrit.")
        return
    if user.id in elimines:
        await ctx.send(f"❌ {user.display_name} a été éliminé et ne peut plus se réinscrire.")
        return

    joueurs[user.id] = {"or": 30, "etoiles": 2}
    positions[user.id] = "KaibaCorp"
    inventaires[user.id] = {"or": 30, "cartes": []}
    save_data()
    await ctx.send(f"✅ {user.display_name} rejoint le tournoi avec 💰30 or et ⭐2 étoiles !")

@bot.command()
async def joueurs_liste(ctx):
    if not joueurs:
        await ctx.send("❌ Aucun joueur inscrit.")
        return

    msg = "📜 **Liste des joueurs inscrits :**\n"
    for uid, stats in joueurs.items():
        try:
            user = await bot.fetch_user(uid)
            pseudo = user.display_name
        except:
            pseudo = f"ID {uid}"
        zone = positions.get(uid, "❓ Inconnue")
        statuts = stats.get("statuts", [])
        badge = f" [{' ,'.join(statuts)}]" if statuts else ""
        msg += f"- {pseudo}{badge} → ⭐{stats['etoiles']} | 💰{stats['or']} | 📍 {zone}\n"

    await ctx.send(msg)


# --- PROFIL ---
@bot.command()
async def profil(ctx, membre: discord.Member = None):
    if membre is None:
        membre = ctx.author
    if not est_inscrit(membre.id):
        await ctx.send(f"❌ {membre.display_name} n’est pas inscrit.")
        return
    stats = joueurs[membre.id]
    statuts = stats.get("statuts", [])
    badge = f" [{' ,'.join(statuts)}]" if statuts else ""
    await ctx.send(f"👤 {membre.display_name}{badge} → ⭐{stats['etoiles']} | 💰{stats['or']} or")


# --- DEPLACEMENT ---
@bot.command()
async def zones_dispo(ctx):
    await ctx.send("🌍 Zones disponibles : " + ", ".join(zones))

@bot.command()
async def aller(ctx, *, zone: str):
    user = ctx.author
    user_id = str(user.id)

    if not est_inscrit(user.id):
        await ctx.send("❌ Tu dois d'abord t'inscrire avec `!inscrire`.")
        return
    if zone not in zones:
        await ctx.send("❌ Zone invalide ! Tape !zones_dispo pour voir les zones.")
        return

    # Vérifier si le joueur a le pouvoir Skream (omnipresent)
    if not joueurs.get(user.id, {}).get("skream_omnipresent", False):
        # Vérifie si le joueur a déjà changé de zone sans duel
        if derniers_deplacements.get(user_id, False):
            await ctx.send("🚫 Tu ne peux pas changer de zone deux fois de suite sans avoir disputé de duel dans ta zone.")
            return

    # Change la zone
    positions[user.id] = zone
    if not joueurs.get(user.id, {}).get("skream_omnipresent", False):
        derniers_deplacements[user_id] = True  # il doit jouer un duel avant de rebouger
    save_data()

    skream_msg = " (Skream : omnipresent)" if joueurs.get(user.id, {}).get("skream_omnipresent", False) else ""
    await ctx.send(f"🚶 {user.display_name} se rend à **{zone}**{skream_msg}.")

    # Vérifier si un autre joueur est déjà dans la même zone
    joueurs_dans_zone = [uid for uid, z in positions.items() if z == zone]
    if len(joueurs_dans_zone) > 1:
        adversaires = []
        for uid in joueurs_dans_zone:
            try:
                u = await bot.fetch_user(uid)
                adversaires.append(u.display_name)
            except:
                adversaires.append(f"ID {uid}")
        await ctx.send(f"⚔️ Duel déclenché à **{zone}** entre : {', '.join(adversaires)} !")


@bot.command()
async def ou(ctx, membre: discord.Member = None):
    if membre is None:
        membre = ctx.author
    if membre.id not in positions:
        await ctx.send(f"❌ {membre.display_name} n'est pas inscrit.")
        return
    zone = positions[membre.id]
    
    # Vérifier si le joueur a le pouvoir Skream
    skream_msg = ""
    if joueurs.get(membre.id, {}).get("skream_omnipresent", False):
        skream_msg = " (Skream : présent partout)"
        
    await ctx.send(f"📍 {membre.display_name} est actuellement à **{zone}**{skream_msg}.")


# --- DUEL ---
@bot.command()
async def duel(ctx, gagnant: discord.Member, perdant: discord.Member, etoiles: int, or_: int):
    if not est_inscrit(gagnant.id) or not est_inscrit(perdant.id):
        await ctx.send("❌ Les deux joueurs doivent être inscrits.")
        return

    if joueurs[perdant.id]["etoiles"] < etoiles:
        await ctx.send(f"❌ {perdant.display_name} n'a pas assez d'étoiles pour miser ({etoiles} demandées).")
        return

    if joueurs[perdant.id]["or"] < or_:
        await ctx.send(f"❌ {perdant.display_name} n'a pas assez d'or pour miser ({or_} demandés).")
        return

    # Vérifier la position sauf si l'un des joueurs a Skream
    gagnant_skream = joueurs.get(gagnant.id, {}).get("skream_omnipresent", False)
    perdant_skream = joueurs.get(perdant.id, {}).get("skream_omnipresent", False)
    
    if not gagnant_skream and not perdant_skream:
        if positions.get(gagnant.id) != positions.get(perdant.id):
            await ctx.send("❌ Les deux joueurs doivent être dans la même zone pour dueler.")
            return

    if gagnant.id == perdant.id:
        await ctx.send("❌ Tu ne peux pas te défier toi-même !")
        return

    # Effet YOP (coin garanti pour le prochain duel)
    yop_bonus = ""
    if joueurs.get(gagnant.id, {}).get("yop_coin_guaranteed", False):
        joueurs[gagnant.id]["or"] += 10
        joueurs[gagnant.id]["yop_coin_guaranteed"] = False
        # Retirer le statut visible
        statuts_gagnant = joueurs[gagnant.id].get("statuts", [])
        if "YOP Coin Winner" in statuts_gagnant:
            statuts_gagnant.remove("YOP Coin Winner")
        yop_bonus = " (+10 or bonus YOP !)"

    # ----- Effet Minerva côté perdant : perd 1 ⭐ de moins, une seule fois -----
    perte_etoiles = etoiles
    if joueurs.get(perdant.id, {}).get("minerva_shield"):
        perte_etoiles = max(0, etoiles - 1)
        joueurs[perdant.id]["minerva_shield"] = False
        # Retire le statut visible
        statuts = joueurs[perdant.id].get("statuts", [])
        if "Protégé par Minerva" in statuts:
            statuts.remove("Protégé par Minerva")

    # Transfert des mises (on transfère ce que le perdant perd réellement)
    joueurs[perdant.id]["etoiles"] -= perte_etoiles
    joueurs[gagnant.id]["etoiles"] += perte_etoiles
    joueurs[gagnant.id]["or"] += or_
    joueurs[perdant.id]["or"] -= or_

    # Effet Tyrano : +3 or par monstre détruit (simulation basique pour l'exemple)
    tyrano_bonus = ""
    if joueurs.get(gagnant.id, {}).get("tyrano_active", False):
        monstres_detruits = random.randint(5, 15)  # Simulation
        bonus_or = monstres_detruits * 3
        joueurs[gagnant.id]["or"] += bonus_or
        tyrano_bonus = f" (Tyrano: +{bonus_or} or pour {monstres_detruits} monstres détruits)"
        
        # Si 30+ monstres détruits, +1 étoile (rare)
        if monstres_detruits >= 30:
            joueurs[gagnant.id]["etoiles"] += 1
            tyrano_bonus += " +1⭐ bonus!"

    await ctx.send(
        f"⚔️ Duel terminé à **{positions[gagnant.id]}** !\n"
        f"🏆 {gagnant.display_name} gagne ⭐{perte_etoiles} étoile(s) et 💰{or_} or{yop_bonus}{tyrano_bonus}.\n"
        f"💀 {perdant.display_name} perd ⭐{perte_etoiles} étoile(s) et 💰{or_} or."
    )

    # Vérification élimination vs bouclier Atem
    if joueurs[perdant.id]["etoiles"] <= 0:
        if joueurs.get(perdant.id, {}).get("atem_shield", False):
            # Sauver le joueur avec 1 étoile
            joueurs[perdant.id]["etoiles"] = 1
            joueurs[perdant.id]["atem_shield"] = False
            # Retirer le statut visible
            statuts = joueurs[perdant.id].get("statuts", [])
            if "Protégé par Atem" in statuts:
                statuts.remove("Protégé par Atem")
            await ctx.send(f"💫 **{perdant.display_name}** survit grâce au pouvoir d'Atem avec 1 étoile !")
        else:
            await ctx.send(f":skull: **{perdant.display_name} est éliminé du tournoi !**")
            elimines.add(perdant.id)
            joueurs.pop(perdant.id, None)
            positions.pop(perdant.id, None)
            inventaires.pop(perdant.id, None)

    derniers_deplacements[str(gagnant.id)] = False
    derniers_deplacements[str(perdant.id)] = False

    save_data()



# --- Boutique ---
boutique = {
    "packs": {
        "Super Polymérisation": {
            "prix": 150,
            "cartes": ["Super Polymerisation (x3)", "Mudragon of the Swamp", "Saint Azamina",
                       "Garura, Wings of Resonant Life", "Earth Golem @Ignister"]
        },
        "Light Fiend": {
            "prix": 150,
            "cartes": ["Fiendsmith Engraver", "Weiss, Lightsworn Archfiend (x2)", "Evilswarm Exciton Knight",
                       "Moon of the Closed Heaven", "Fiendsmith Tract"]
        },
        "Loi de la Normale": {
            "prix": 150,
            "cartes": ["Primite Dragon Ether Beryl (x2)", "Primite Roar (x2)", "Primite Drillbeam",
                       "Unexpected Dai (x2)"]
        },
        "Dix Siècles": {
            "prix": 150,
            "cartes": ["Sengenjin Awakes from a Millennium (x2)", "Sengenjin (x3)", "Zombie Vampire",
                       "Snake-Eyes Doomed Dragon"]
        },
        "Chaos": {
            "prix": 150,
            "cartes": ["Chaos Dragon Levianeer", "Chaos Space", "Chaos Angel", "Chaos Archfiend"]
        },
        "Monstres Ardents": {
            "prix": 150,
            "cartes": ["Snake-Eye Ash", "Snake-Eyes Poplar", "Snake-Eyes Flamberge Dragon"]
        }
    },
    "shops": {
        "Staples": {
            "cartes": {
                "Triple Tactics Talents": 90,
                "Triple Tactics Thrust": 80,
                "Harpie's Feather Duster": 70,
                "Heavy Storm": 70,
                "Evenly Matched": 100,
                "Ghost Ogre & Snow Rabbit": 80,
                "Ghost Belle & Haunted Mansion": 80,
                "Nibiru, the Primal Being": 80,
                "S:P Little Knight": 100
            }
        },
        "JVC": {
            "cartes": {
                "Fairy Tail Snow": 70,
                "Curious, the Lightsworn Dominion": 70,
                "Mathmech Circular": 70,
                "Sillva, Warlord of Dark World": 70,
                "Superheavy Samurai Wakaushi": 70,
                "Amorphactor Pain": 70,
                "Masked HERO Dark Law": 70,
                "Isolde, Two Tales of the Noble Knights": 70,
                "Trishula, Dragon of the Ice Barrier": 70
            },
            "limite_par_joueur": 1
        },
        "Bannis": {
            "cartes": {
                "Pot of Greed": 200,
                "Graceful Charity": 200,
                "Painful Choice": 200
            },
            "limite_par_joueur": 1
        }
    }
}

# --- BOUTIQUE COMMANDES ---
@bot.command()
async def boutique_cmd(ctx, *, nom: str = None):
    """Affiche la boutique ou le détail d’un pack/shop"""
    if nom is None:
        msg = "🏬 **Boutique disponible :**\n\n📦 **Packs** :\n"
        for pack, data in boutique["packs"].items():
            msg += f"- {pack} ({data['prix']} or)\n"
        msg += "\n🛒 **Shops** :\n"
        for shop in boutique["shops"].keys():
            msg += f"- {shop}\n"
        await ctx.send(msg)
    else:
        nom = nom.strip()
        if nom in boutique["packs"]:
            pack = boutique["packs"][nom]
            msg = f"📦 **{nom}** ({pack['prix']} or)\nCartes incluses :\n"
            for c in pack["cartes"]:
                msg += f"- {c}\n"
            await ctx.send(msg)
        elif nom in boutique["shops"]:
            shop = boutique["shops"][nom]
            msg = f"🛒 **{nom}**\n"
            for c, prix in shop["cartes"].items():
                msg += f"- {c} ({prix} or)\n"
            if "limite_par_joueur" in shop:
                msg += f"\n⚠️ Limite : {shop['limite_par_joueur']} carte par joueur"
            await ctx.send(msg)
        else:
            await ctx.send("❌ Pack ou shop introuvable.")

@bot.command()
async def acheter(ctx, *, nom: str):
    """Permet d'acheter un pack complet ou une carte d'un shop"""
    user = ctx.author
    if not est_inscrit(user.id):
        await ctx.send("❌ Tu dois être inscrit pour acheter.")
        return

    # Vérifier si c'est un pack
    if nom in boutique["packs"]:
        pack = boutique["packs"][nom]
        prix = pack["prix"]

        if joueurs[user.id]["or"] < prix:
            await ctx.send(f"❌ Pas assez d'or ! ({prix} requis)")
            return

        joueurs[user.id]["or"] -= prix
        inventaires[user.id]["cartes"].extend(pack["cartes"])

        # Supprimer le pack de la boutique
        del boutique["packs"][nom]

        save_data()
        await ctx.send(f"✅ {user.display_name} a acheté le pack **{nom}** !")
        return

    # Vérifier si c'est une carte dans un shop
    for shop_nom, shop in boutique["shops"].items():
        if nom in shop["cartes"]:
            prix = shop["cartes"][nom]

            # Réduction "Négociateur" (UNE SEULE carte, puis disparaît)
            reduction = 30 if joueurs.get(user.id, {}).get("negociateur") else 0
            prix_effectif = max(0, prix - reduction)

            if joueurs[user.id]["or"] < prix_effectif:
                await ctx.send(f"❌ Pas assez d'or ! ({prix_effectif} requis)")
                return

            # Limite par joueur
            if "limite_par_joueur" in shop:
                if achats_uniques.get(user.id, {}).get(shop_nom, False):
                    await ctx.send(f"❌ Tu as déjà acheté une carte du shop {shop_nom}.")
                    return
                achats_uniques.setdefault(user.id, {})[shop_nom] = True

            # Débiter le prix effectif (avec réduction éventuelle)
            joueurs[user.id]["or"] -= prix_effectif
            inventaires[user.id]["cartes"].append(nom)
            
            # Si la réduction a été appliquée, on consomme le statut et on l'enlève de l'affichage
            if reduction > 0:
                joueurs[user.id]["negociateur"] = False
                statuts = joueurs[user.id].get("statuts", [])
                if "Négociateur" in statuts:
                    statuts.remove("Négociateur")

            # Supprimer la carte du shop si c'est un shop à stock limité
            if "limite_par_joueur" in shop or shop_nom in ["Staples", "JVC", "Bannis"]:
                del shop["cartes"][nom]

            save_data()
            msg = f"✅ {user.display_name} a acheté **{nom}** dans le shop {shop_nom}"
            if reduction > 0:
                msg += f" (réduction Négociateur appliquée : -{reduction} or)"
            msg += " !"
            await ctx.send(msg)
            return

    await ctx.send("❌ Aucun pack ou carte trouvé avec ce nom.")



@bot.command()
async def inventaire(ctx, membre: discord.Member = None):
    """Affiche l’inventaire de soi-même ou d’un autre joueur"""
    if membre is None:
        membre = ctx.author

    if not est_inscrit(membre.id):
        await ctx.send(f"❌ {membre.display_name} n’est pas inscrit.")
        return

    cartes = inventaires[membre.id].get("cartes", [])
    or_joueur = joueurs[membre.id]["or"]

    if not cartes:
        await ctx.send(f"🎒 **Inventaire de {membre.display_name}**\n💰 Or : {or_joueur}\n📦 Cartes : *(vide)*")
    else:
        msg = f"🎒 **Inventaire de {membre.display_name}**\n💰 Or : {or_joueur}\n📦 Cartes :\n"
        for c in cartes:
            msg += f"- {c}\n"
        await ctx.send(msg)


# --- COMMANDES SECRÈTES --- 

@bot.command()
async def fsz(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "fsz")
    if not ok:
        await ctx.send(msg)
        return

    if str(user_id) == "306059710908596224":
        joueurs[user_id]["or"] = joueurs[user_id].get("or", 0) - 10
        await ctx.send("Je te hais. -10 or")
    else:
        joueurs[user_id]["or"] = joueurs[user_id].get("or", 0) + 10
        await ctx.send(f"{ctx.author.display_name} a activé Mathmech Circular : **+10 or** !")

    lock_exclusive(user_id, "fsz")
    save_data()


@bot.command()
async def fman(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "fman")
    if not ok:
        await ctx.send(msg)
        return

    inventaires[user_id]["cartes"].append("Dimensional Fissure")
    lock_exclusive(user_id, "fman")

    await ctx.send("Le fait que tu aies trouvé cette commande montre que tes decks sont bien pensés et réfléchis...\n"
                   "Tu gagnes : 1 **Dimensional Fissure** !")
    save_data()


@bot.command()
async def minerva(ctx):
    user = ctx.author
    if not est_inscrit(user.id):
        await ctx.send("❌ Tu dois d’abord t’inscrire avec `!inscrire`.")
        return

    if not peut_utiliser_commande_unique("minerva"):
        await ctx.send("Cette commande a déjà été utilisée")
        return

    joueurs[user.id].setdefault("statuts", [])
    if "Protégé par Minerva" not in joueurs[user.id]["statuts"]:
        joueurs[user.id]["statuts"].append("Protégé par Minerva")
    joueurs[user.id]["minerva_shield"] = True

    await ctx.send(f"{user.mention} est désormais **Protégé par Minerva** ! (perdra 1 ⭐ de moins au prochain duel perdu)")
    save_data()



@bot.command()
async def fayth(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "fayth")
    if not ok:
        await ctx.send(msg)
        return

    # Initialiser le flag negociateur
    joueurs[user_id]["negociateur"] = True
    
    joueurs[user_id].setdefault("statuts", [])
    if "Négociateur" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Négociateur")

    lock_exclusive(user_id, "fayth")
    save_data()

    await ctx.send("Grâce à la négociation de Fayth, la prochaine carte que tu achèteras dans un shop coûtera 30 or de moins !")


@bot.command()
async def capitaine(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "capitaine")
    if not ok:
        await ctx.send(msg)
        return

    joueurs[user_id].setdefault("statuts", [])
    if "Roux" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Roux")

    lock_exclusive(user_id, "capitaine")

    await ctx.send(f"{ctx.author.display_name} est traité comme roux pour le reste du tournoi !")

@bot.command()
async def roux(ctx):
    """Commande secrète : uniquement pour les joueurs roux."""
    user = ctx.author
    uid = str(user.id)

    # Vérif inscription
    if not est_inscrit(user.id):
        await ctx.send("❌ Tu dois d’abord t’inscrire avec `!inscrire`.")
        return

    # Vérif statut "roux"
    if "statuts" not in joueurs[user.id] or "Roux" not in joueurs[user.id]["statuts"]:
        await ctx.send("❌ Tu n’es pas roux, tu ne peux pas utiliser cette commande.")
        return

    # Vérif si la commande est déjà prise globalement
    if commandes_uniques_globales["exclusives_globales"].get("roux", False):
        await ctx.send("❌ Cette commande a déjà été utilisée par un autre joueur.")
        return

    # Effet : +1 étoile
    joueurs[user.id]["etoiles"] = joueurs[user.id].get("etoiles", 0) + 1

    # Marquer la commande comme utilisée globalement
    commandes_uniques_globales["exclusives_globales"]["roux"] = True
    save_data()

    await ctx.send(f"{user.display_name} gagne **1 étoile** !")



@bot.command()
async def shaman(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "shaman")
    if not ok:
        await ctx.send(msg)
        return

    lock_exclusive(user_id, "shaman")

    try:
        await ctx.author.send("https://media.discordapp.net/attachments/1256671184745922610/1408048409587220653/image.png?ex=68a852c5&is=68a70145&hm=8e6c9d33f25f8bf0c2bd13e2e0467be636f6441298636db5eeee9a14d413a379&=&format=webp&quality=lossless&width=1318&height=758")
        await ctx.send("Un vent étrange souffle...")
    except:
        await ctx.send("Impossible de t’envoyer un MP. Veuillez contacter ATEM.")


@bot.command()
async def atem(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "atem")
    if not ok:
        await ctx.send(msg)
        return

    joueurs[user_id]["atem_shield"] = True
    joueurs[user_id].setdefault("statuts", [])
    if "Protégé par Atem" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Protégé par Atem")

    lock_exclusive(user_id, "atem")
    save_data()

    await ctx.send("Vous avez corrompu l'orga : La prochaine fois que vous devriez être éliminé, vous survivez avec 1 étoile !")

@bot.command()
async def skream(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "skream")
    if not ok:
        await ctx.send(msg)
        return

    joueurs[user_id]["skream_omnipresent"] = True
    joueurs[user_id].setdefault("statuts", [])
    if "Skream Omnipresent" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Skream Omnipresent")

    lock_exclusive(user_id, "skream")
    save_data()

    await ctx.send("Vous êtes présent dans chaque zone du tournoi. Vous pouvez affronter n'importe qui (dure jusqu'à la fin du prochain bo3).")

@bot.command()
async def tyrano(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "tyrano")
    if not ok:
        await ctx.send(msg)
        return

    joueurs[user_id]["tyrano_active"] = True
    joueurs[user_id].setdefault("statuts", [])
    if "Tyrano Hunter" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Tyrano Hunter")

    lock_exclusive(user_id, "tyrano")
    save_data()

    await ctx.send("À la fin de chaque bo3 du tournoi, vous gagnez 3 or pour chaque monstre détruit par un effet de carte pendant le bo3. Si 30 monstres sont détruits par un effet pendant un bo3, vous gagnez 1 étoile !")

@bot.command()
async def retro(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "retro")
    if not ok:
        await ctx.send(msg)
        return

    inventaires[user_id]["cartes"].append("Dimensional Shifter")
    lock_exclusive(user_id, "retro")
    save_data()

    await ctx.send("La carte **Dimensional Shifter** a été ajoutée à votre inventaire !")

@bot.command()
async def voorhees(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "voorhees")
    if not ok:
        await ctx.send(msg)
        return

    if user_id in GAGNANTS_JVC_IDS:
        joueurs[user_id]["etoiles"] += 1
        lock_exclusive(user_id, "voorhees")
        save_data()
        await ctx.send("Vous avez remporté au moins un tournoi sur JVC ! Vous gagnez **1 étoile** !")
    else:
        joueurs[user_id]["or"] += 30
        lock_exclusive(user_id, "voorhees")
        save_data()
        await ctx.send("Vous gagnez **30 or** !")

@bot.command()
async def yop(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "yop")
    if not ok:
        await ctx.send(msg)
        return

    joueurs[user_id]["yop_coin_guaranteed"] = True
    joueurs[user_id].setdefault("statuts", [])
    if "YOP Coin Winner" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("YOP Coin Winner")

    lock_exclusive(user_id, "yop")
    save_data()

    await ctx.send("Vous gagnez la pièce à votre prochain bo3, si et seulement si votre deck ne contient aucune des cartes suivantes : Arcana Force XXI - The World, Amorphactor Pain, Herald of Ultimateness ! (+10 or au prochain duel gagné)")

# Modification de la commande zaga existante
@bot.command()
async def zaga(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "zaga")
    if not ok:
        await ctx.send(msg)
        return

    # ZagaNaga se venge avec un nouvel effet
    cartes_zaga = [
        "Archétype Tenpai",
        "Archétype Gimmick Puppet", 
        "Naturia Beast"
    ]
    
    inventaires[user_id]["cartes"].extend(cartes_zaga)
    lock_exclusive(user_id, "zaga")
    save_data()

    await ctx.send(f"ZagaNaga se venge des tournois précédents... Les cartes suivantes ont été ajoutées à votre inventaire :\n- " + "\n- ".join(cartes_zaga))


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    uid = message.author.id
    contenu = message.content

    # 4.a) Pénalité spéciale pour l'ID donné quand il mentionne "Circular" ou "Mathmech"
    if uid == 306059710908596224 and ("Circular" in contenu or "Mathmech" in contenu):
        # Compte uniquement les lettres (pas espaces/punct)
        perte = sum(1 for ch in contenu if ch.isalpha())
        if est_inscrit(uid):
            joueurs[uid]["or"] -= perte
            save_data()
        await message.channel.send(f" {message.author.mention} Vu que t'aimes tant parler de moi, chaque **lettre** te coûte 1 or… Tu perds **{perte}** or !")

    # 4.b) !help : la 1ʳᵉ fois → message + -5 or (on laisse le help normal s’afficher derrière)
    if contenu.strip().lower().startswith(f"{PREFIX}help"):
        if est_inscrit(uid):
            achats_uniques.setdefault(uid, {})
            cle = "cmd_help_penalite"
            if not achats_uniques[uid].get(cle):
                achats_uniques[uid][cle] = True
                joueurs[uid]["or"] -= 5
                save_data()
                await message.channel.send("Ne sais-tu donc PAS LIRE le salon spécifiquement DÉDIÉ à mon fonctionnement ??? Pour la peine... - 5 or !")

    # Très important pour ne pas bloquer les commandes
    await bot.process_commands(message)




# --- ADMIN ---
OWNER_ID = 673606402782265344  # <<< Ton ID Discord

def is_owner():
    def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)

@bot.command()
@is_owner()
async def admin_or(ctx, membre: discord.Member, montant: int):
    """Ajoute de l'or à un joueur (admin only)"""
    if not est_inscrit(membre.id):
        await ctx.send(f"❌ {membre.display_name} n’est pas inscrit.")
        return
    joueurs[membre.id]["or"] += montant
    save_data()
    await ctx.send(f"✅ {membre.display_name} reçoit 💰{montant} or (total = {joueurs[membre.id]['or']}).")

@bot.command()
@is_owner()
async def admin_etoiles(ctx, membre: discord.Member, montant: int):
    """Ajoute des étoiles à un joueur (admin only)"""
    if not est_inscrit(membre.id):
        await ctx.send(f"❌ {membre.display_name} n’est pas inscrit.")
        return
    joueurs[membre.id]["etoiles"] += montant
    save_data()
    await ctx.send(f"✅ {membre.display_name} reçoit ⭐{montant} étoiles (total = {joueurs[membre.id]['etoiles']}).")

@bot.command()
@is_owner()
async def admin_reset_or(ctx, membre: discord.Member):
    """Réinitialise l'or d'un joueur à 0 (admin only)"""
    if not est_inscrit(membre.id):
        await ctx.send(f"❌ {membre.display_name} n’est pas inscrit.")
        return
    joueurs[membre.id]["or"] = 0
    save_data()
    await ctx.send(f"⚠️ L’or de {membre.display_name} a été réinitialisé à 0.")

@bot.command()
@is_owner()
async def admin_jvc(ctx, action: str, membre: discord.Member = None):
    """Gère la liste des gagnants JVC"""
    global GAGNANTS_JVC_IDS
    
    if action == "add" and membre:
        GAGNANTS_JVC_IDS.add(membre.id)
        save_data()
        await ctx.send(f"✅ {membre.display_name} ajouté à la liste des gagnants JVC.")
    elif action == "remove" and membre:
        GAGNANTS_JVC_IDS.discard(membre.id)
        save_data()
        await ctx.send(f"✅ {membre.display_name} retiré de la liste des gagnants JVC.")
    elif action == "list":
        if not GAGNANTS_JVC_IDS:
            await ctx.send("Aucun gagnant JVC enregistré.")
        else:
            msg = "🏆 **Gagnants JVC enregistrés :**\n"
            for uid in GAGNANTS_JVC_IDS:
                try:
                    user = await bot.fetch_user(uid)
                    msg += f"- {user.display_name}\n"
                except:
                    msg += f"- ID {uid}\n"
            await ctx.send(msg)
    else:
        await ctx.send("Usage: `!admin_jvc add/remove/list [@membre]`")

@bot.command()
@is_owner()
async def database(ctx, action: str = None, *, params: str = None):
    """Commande principale pour vérifier différents éléments de la database"""
    if action is None:
        embed = discord.Embed(title="Commandes Database disponibles", color=discord.Color.blue())
        embed.add_field(name="!database stats", value="Statistiques générales de la DB", inline=False)
        embed.add_field(name="!database joueurs", value="Liste tous les joueurs", inline=False)
        embed.add_field(name="!database joueur [pseudo]", value="Détails d'un joueur spécifique", inline=False)
        embed.add_field(name="!database elimines", value="Liste des joueurs éliminés", inline=False)
        embed.add_field(name="!database positions", value="Positions de tous les joueurs", inline=False)
        embed.add_field(name="!database inventaires", value="Résumé des inventaires", inline=False)
        embed.add_field(name="!database boutique", value="État actuel de la boutique", inline=False)
        embed.add_field(name="!database commandes", value="État des commandes exclusives", inline=False)
        embed.add_field(name="!database sync", value="Synchronise les données en mémoire avec la DB", inline=False)
        embed.add_field(name="!database backup", value="Affiche un backup JSON complet", inline=False)
        await ctx.send(embed=embed)
        return

    if action == "stats":
        conn = get_db_connection()
        if not conn:
            await ctx.send("❌ Impossible de se connecter à la DB")
            return
        
        try:
            cursor = conn.cursor()
            
            # Compter les entrées dans chaque table
            tables = ["joueurs", "positions", "elimines", "inventaires", "achats_uniques", 
                     "commandes_globales", "derniers_deplacements", "boutique_data", "bans_temp"]
            
            stats = {}
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            
            embed = discord.Embed(title="📊 Statistiques Database", color=discord.Color.green())
            for table, count in stats.items():
                embed.add_field(name=f"Table {table}", value=f"{count} entrées", inline=True)
            
            cursor.close()
            conn.close()
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Erreur lors du check stats: {e}")
            if conn:
                conn.close()

    elif action == "joueurs":
        if not joueurs:
            await ctx.send("Aucun joueur en mémoire")
            return
        
        msg = "👥 **Joueurs en mémoire:**\n"
        for uid, data in list(joueurs.items())[:20]:  # Limiter à 20 pour éviter les messages trop longs
            try:
                user = await bot.fetch_user(uid)
                pseudo = user.display_name
            except:
                pseudo = f"ID {uid}"
            
            statuts = data.get('statuts', [])
            flags = []
            if data.get('minerva_shield'): flags.append("Minerva")
            if data.get('negociateur'): flags.append("Négociateur")
            
            status_str = f"[{','.join(statuts + flags)}]" if statuts or flags else ""
            msg += f"- {pseudo} {status_str}: ⭐{data['etoiles']} | 💰{data['or']}\n"
        
        if len(joueurs) > 20:
            msg += f"\n... et {len(joueurs) - 20} autres joueurs"
        
        await ctx.send(msg)

    elif action == "joueur" and params:
        # Chercher un joueur par pseudo
        target_user = None
        for uid in joueurs.keys():
            try:
                user = await bot.fetch_user(uid)
                if params.lower() in user.display_name.lower():
                    target_user = user
                    break
            except:
                continue
        
        if not target_user:
            await ctx.send(f"❌ Joueur '{params}' introuvable")
            return
        
        uid = target_user.id
        data = joueurs[uid]
        
        embed = discord.Embed(title=f"👤 Profil de {target_user.display_name}", color=discord.Color.blue())
        embed.add_field(name="ID", value=str(uid), inline=True)
        embed.add_field(name="Étoiles", value=data['etoiles'], inline=True)
        embed.add_field(name="Or", value=data['or'], inline=True)
        embed.add_field(name="Zone", value=positions.get(uid, "Inconnue"), inline=True)
        embed.add_field(name="Statuts", value=", ".join(data.get('statuts', [])) or "Aucun", inline=True)
        
        flags = []
        if data.get('minerva_shield'): flags.append("Bouclier Minerva")
        if data.get('negociateur'): flags.append("Négociateur actif")
        embed.add_field(name="Flags spéciaux", value=", ".join(flags) or "Aucun", inline=True)
        
        # Inventaire
        inv = inventaires.get(uid, {})
        cartes = inv.get('cartes', [])
        if cartes:
            cartes_str = ", ".join(cartes[:10])  # Limiter à 10 cartes
            if len(cartes) > 10:
                cartes_str += f" ... (+{len(cartes)-10} autres)"
        else:
            cartes_str = "Vide"
        embed.add_field(name="Inventaire", value=cartes_str, inline=False)
        
        await ctx.send(embed=embed)

    elif action == "elimines":
        if not elimines:
            await ctx.send("Aucun joueur éliminé")
            return
        
        msg = "💀 **Joueurs éliminés:**\n"
        for uid in list(elimines)[:20]:
            try:
                user = await bot.fetch_user(uid)
                msg += f"- {user.display_name} (ID: {uid})\n"
            except:
                msg += f"- ID {uid}\n"
        
        if len(elimines) > 20:
            msg += f"\n... et {len(elimines) - 20} autres"
            
        await ctx.send(msg)

    elif action == "positions":
        if not positions:
            await ctx.send("Aucune position enregistrée")
            return
        
        zones_count = {}
        for zone in positions.values():
            zones_count[zone] = zones_count.get(zone, 0) + 1
        
        embed = discord.Embed(title="📍 Répartition par zones", color=discord.Color.orange())
        for zone, count in zones_count.items():
            embed.add_field(name=zone, value=f"{count} joueurs", inline=True)
        
        await ctx.send(embed=embed)

    elif action == "inventaires":
        if not inventaires:
            await ctx.send("Aucun inventaire enregistré")
            return
        
        total_cartes = sum(len(inv.get('cartes', [])) for inv in inventaires.values())
        total_or_inventaires = sum(inv.get('or', 0) for inv in inventaires.values())
        
        embed = discord.Embed(title="🎒 Résumé des inventaires", color=discord.Color.purple())
        embed.add_field(name="Nombre d'inventaires", value=len(inventaires), inline=True)
        embed.add_field(name="Total cartes stockées", value=total_cartes, inline=True)
        embed.add_field(name="Or total en inventaires", value=total_or_inventaires, inline=True)
        
        await ctx.send(embed=embed)

    elif action == "boutique":
        packs_dispo = len(boutique.get("packs", {}))
        
        msg = f"🏪 **État de la boutique:**\n"
        msg += f"📦 Packs disponibles: {packs_dispo}\n\n"
        
        for shop_name, shop_data in boutique.get("shops", {}).items():
            cartes_dispo = len(shop_data.get("cartes", {}))
            msg += f"🛒 {shop_name}: {cartes_dispo} cartes\n"
        
        await ctx.send(msg)

    elif action == "commandes":
        global commandes_uniques_globales
        
        embed = discord.Embed(title="⚡ État des commandes exclusives", color=discord.Color.red())
        
        exclusives_globales = commandes_uniques_globales.get("exclusives_globales", {})
        exclusives_joueurs = commandes_uniques_globales.get("exclusives_joueurs", {})
        
        # Commandes utilisées
        utilisees = [cmd for cmd, used in exclusives_globales.items() if used]
        embed.add_field(name="Commandes utilisées", value=", ".join(utilisees) or "Aucune", inline=False)
        
        # Joueurs ayant utilisé une exclusive
        nb_joueurs_exclusives = len(exclusives_joueurs)
        embed.add_field(name="Joueurs avec exclusive utilisée", value=str(nb_joueurs_exclusives), inline=True)
        
        await ctx.send(embed=embed)

    elif action == "sync":
        load_data()
        await ctx.send("🔄 Données synchronisées depuis la base de données")

    elif action == "backup":
        # Créer un backup complet en JSON
        backup_data = {
            "joueurs": joueurs,
            "positions": {str(k): v for k, v in positions.items()},
            "elimines": list(elimines),
            "inventaires": {str(k): v for k, v in inventaires.items()},
            "achats_uniques": {str(k): v for k, v in achats_uniques.items()},
            "commandes_uniques_globales": commandes_uniques_globales,
            "derniers_deplacements": derniers_deplacements,
            "boutique": boutique,
            "bans_temp": bans_temp
        }
        
        import json
        backup_json = json.dumps(backup_data, indent=2, ensure_ascii=False)
        
        if len(backup_json) > 1900:  # Limite Discord
            # Sauver dans un fichier temporaire et l'envoyer
            with open("backup.json", "w", encoding="utf-8") as f:
                f.write(backup_json)
            
            await ctx.send("📁 Backup trop volumineux, envoyé en fichier:", file=discord.File("backup.json"))
            
            import os
            os.remove("backup.json")
        else:
            await ctx.send(f"```json\n{backup_json}\n```")

    else:
        await ctx.send("❌ Action non reconnue. Utilise `!database` sans paramètre pour voir les options.")


# --- RESET ---

@bot.command()
@is_owner()
async def reset(ctx):
    """Réinitialise complètement le tournoi (OWNER uniquement)."""

    global joueurs, positions, elimines, inventaires, achats_uniques, boutique
    global commandes_uniques_globales, derniers_deplacements, bans_temp
    global proteges_minerva, negociateurs

    # Reset complet en mémoire
    joueurs = {}
    positions = {}
    elimines = set()
    inventaires = {}
    achats_uniques = {}
    commandes_uniques_globales = {"exclusives_globales": {}, "exclusives_joueurs": {}}
    derniers_deplacements = {}
    bans_temp = {}
    
    # CORRECTION : faire une copie profonde de BOUTIQUE_INITIALE
    import copy
    boutique = copy.deepcopy(BOUTIQUE_INITIALE)

    # Si tu as des statuts spéciaux comme Minerva, Boutique_CM, etc.
    proteges_minerva = {}
    negociateurs = {}

    # NOUVEAU: Nettoyer explicitement la base de données
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Vider toutes les tables
            tables_to_clear = [
                "joueurs", "positions", "elimines", "inventaires", 
                "achats_uniques", "commandes_globales", "derniers_deplacements", 
                "bans_temp"
            ]
            
            for table in tables_to_clear:
                cursor.execute(f"DELETE FROM {table}")
            
            # Réinitialiser la boutique à l'état initial
            cursor.execute("""
                INSERT INTO boutique_data (id, data) VALUES (1, %s)
                ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
            """, (json.dumps(boutique),))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            await ctx.send("🔥 Toutes les données du tournoi ont été complètement réinitialisées (mémoire + base de données) !")
            
        except Exception as e:
            await ctx.send(f"⚠️ Erreur lors du nettoyage de la base : {e}")
            if conn:
                conn.rollback()
                conn.close()
            return
    else:
        await ctx.send("⚠️ Impossible de se connecter à la base de données pour le nettoyage")
        return

    # Sauvegarder les données vides (par sécurité)
    save_data()

@reset.error
async def reset_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande.")

@bot.command()
async def reset_exclusives(ctx):
    """Réinitialise toutes les commandes spéciales (OWNER uniquement)."""
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Seul l'OWNER du bot peut utiliser cette commande.")
        return

    global commandes_uniques_globales

    # Reset des exclusives globales
    for cmd in ["fsz", "zaga", "fman", "capitaine", "boutique_cm", "shaman"]:
        commandes_uniques_globales["exclusives_globales"][cmd] = False

    # Reset des exclusives par joueur
    commandes_uniques_globales["exclusives_joueurs"] = {}

    save_data()
    await ctx.send("✅ Toutes les commandes spéciales ont été réinitialisées !")

@bot.command(name="reset_secrets")
@is_owner()
async def reset_secrets(ctx):
    """Réinitialise toutes les commandes secrètes/exclusives (globales et par joueur)."""
    global commandes_uniques_globales

    # S'assurer de la structure
    if "exclusives_globales" not in commandes_uniques_globales or not isinstance(commandes_uniques_globales["exclusives_globales"], dict):
        commandes_uniques_globales["exclusives_globales"] = {}
    if "exclusives_joueurs" not in commandes_uniques_globales or not isinstance(commandes_uniques_globales["exclusives_joueurs"], dict):
        commandes_uniques_globales["exclusives_joueurs"] = {}

    # Liste canonique des exclusives connues
    canon = {"fsz","zaga","fman","capitaine","fayth","shaman","roux","minerva"}

    # 1) Réinitialiser les flags legacy au niveau racine (ex: 'minerva')
    for k, v in list(commandes_uniques_globales.items()):
        if k in ("exclusives_globales", "exclusives_joueurs"):
            continue
        if isinstance(v, bool):
            commandes_uniques_globales[k] = False

    # 2) Réinitialiser les exclusives globales et ajouter les clés manquantes
    for k in set(list(commandes_uniques_globales["exclusives_globales"].keys()) + list(canon)):
        commandes_uniques_globales["exclusives_globales"][k] = False

    # 3) Vider les verrous par joueur
    commandes_uniques_globales["exclusives_joueurs"] = {}

    save_data()
    await ctx.send("✅ Réinitialisation terminée.")


# --- TOURNOI TYRANO ---
# Stockage temporaire : {adversaire: {auteur: deck}}
# Stockage temporaire : {joueur: deck}
bans_temp = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Seulement en DM
    if message.guild is None:
        deck = message.content.strip()
        if not deck:
            await message.channel.send("❌ Merci d’indiquer le nom d’un deck.")
            return

        joueur = message.author.display_name
        bans_temp[joueur] = deck
        await message.channel.send(f"✅ Ton choix a bien été enregistré : bannir **{deck}**.")

        # Vérifier si 2 joueurs ont répondu
        if len(bans_temp) >= 2:
            joueurs = list(bans_temp.keys())
            channel = discord.utils.get(bot.get_all_channels(), name="conversation-tournois")

            if channel and isinstance(channel, discord.TextChannel):
                txt = "📢 Résultats des bans :\n"
                for j in joueurs:
                    txt += f"🔸 **{j}** bannit **{bans_temp[j]}**\n"
                await channel.send(txt)
            else:
                print("⚠️ Erreur : le salon 'conversation-tournois' est introuvable.")

            # Reset après annonce
            bans_temp.clear()

    await bot.process_commands(message)

@bot.command()
async def dispo(ctx):
    """Affiche l'état des bans enregistrés en MP."""
    if not bans_temp:
        await ctx.send("Aucun joueur n'a encore envoyé de ban en MP.")
    else:
        txt = "Bans déjà reçus :\n"
        for joueur in bans_temp:
            txt += f"- {joueur}\n"
        await ctx.send(txt)


@bot.command()
async def clear(ctx):

    bans_temp.clear()
    await ctx.send("🗑️ Les bans temporaires ont été réinitialisés.")


print("Commandes enregistrées :", list(bot.all_commands.keys()))


# --- LANCEMENT ---
keep_alive()
bot.run(TOKEN)
@bot.command()
async def ping(ctx):
    await ctx.send("Pong 🏓")
URL = "https://e452861f-0ced-458c-b285-a009c7261654-00-orp7av1otz2y.picard.replit.dev/"
# Vérification automatique toutes les 5 minutes
@tasks.loop(minutes=5)
async def check_server():
    try:
        r = requests.get(URL, timeout=5)
        if r.status_code == 200:
            print("✅ Le serveur Flask répond bien.")
        else:
            print(f"⚠️ Problème : code {r.status_code} reçu de Flask")
    except Exception as e:
        print(f"❌ Impossible de joindre le serveur Flask : {e}")
bot.run(TOKEN)