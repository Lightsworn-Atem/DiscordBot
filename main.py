import discord
from discord.ext import commands
import json
import os
from discord.ext import tasks
import random
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
from keep_alive import keep_alive
import copy
import asyncio
from datetime import datetime, timedelta


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


def is_owner():
    def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)


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
                "Moulinglacia the Elemental Lord": 90,
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
mirvu_bot_etoiles = 0  # Étoiles que Mathmech Circular possède
joueurs_adam_reserves = {}  
PHASE_INSCRIPTION = 1
PHASE_TOURNOI = 2 
PHASE_QUALIFIES = 3

# Variable pour tracker la phase actuelle
phase_actuelle = PHASE_INSCRIPTION

SEUIL_QUALIFICATION = 10

# --- FONCTIONS UTILITAIRES POUR LES PHASES ---

def get_phase_name(phase):
    """Retourne le nom lisible de la phase"""
    if phase == PHASE_INSCRIPTION:
        return "Inscription"
    elif phase == PHASE_TOURNOI:
        return "Tournoi"
    elif phase == PHASE_QUALIFIES:
        return "Qualifiés"
    return "Inconnue"

def compter_qualifies():
    """Compte le nombre de joueurs avec 10+ étoiles"""
    return len([uid for uid, stats in joueurs.items() if stats.get("etoiles", 0) >= SEUIL_QUALIFICATION and uid != 999999999999999999])

def verifier_phase_qualifies():
    """Vérifie si on doit passer en phase qualifiés"""
    global phase_actuelle
    if phase_actuelle == PHASE_TOURNOI and compter_qualifies() >= 4:
        phase_actuelle = PHASE_QUALIFIES
        return True
    return False

async def annoncer_changement_phase(channel, nouvelle_phase):
    """Annonce le changement de phase dans le salon"""
    if nouvelle_phase == PHASE_TOURNOI:
        # Disperser les joueurs quand la phase 2 commence
        disperser_joueurs_aleatoirement()
        
        # Créer un message avec la répartition
        repartition = {}
        for user_id, zone in positions.items():
            if user_id in joueurs and user_id != 999999999999999999:
                if zone not in repartition:
                    repartition[zone] = []
                try:
                    user = await bot.fetch_user(user_id)
                    repartition[zone].append(user.display_name)
                except:
                    repartition[zone].append(f"ID {user_id}")
        
        message = "**PHASE DE TOURNOI !**\nLes inscriptions sont fermées, que les duels commencent !\n\n"
        message += "🎲 **Dispersion aléatoire des joueurs :**\n"
        
        for zone, joueurs_liste in repartition.items():
            if joueurs_liste:  # Seulement afficher les zones avec des joueurs
                message += f"📍 **{zone}** : {', '.join(joueurs_liste)}\n"
        
        message += "\n⚠️ Vous devez disputer un duel dans votre zone actuelle avant de pouvoir vous déplacer !"
        
        await channel.send(message)
        
    elif nouvelle_phase == PHASE_QUALIFIES:
        await channel.send("🏆 **PHASE DES QUALIFIÉS ATTEINTE !**\n4 joueurs ont atteint 10 étoiles ! Place aux phases finales !")


def require_phase(*phases_autorisees):
    """Décorateur pour limiter les commandes à certaines phases"""
    def decorator(func):
        async def wrapper(ctx, *args, **kwargs):
            if phase_actuelle not in phases_autorisees:
                phase_nom = get_phase_name(phase_actuelle)
                phases_noms = [get_phase_name(p) for p in phases_autorisees]
                await ctx.send(f"❌ Cette commande n'est disponible qu'en phase : {', '.join(phases_noms)}. Phase actuelle : {phase_nom}")
                return
            return await func(ctx, *args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper
    return decorator

@bot.command()
@is_owner()
async def phase(ctx, nouvelle_phase: int = None):
    """Affiche ou change la phase actuelle du tournoi (admin only)"""
    global phase_actuelle
    
    if nouvelle_phase is None:
        qualifies = compter_qualifies()
        embed = discord.Embed(title="📊 État du tournoi", color=discord.Color.blue())
        embed.add_field(name="Phase actuelle", value=f"{phase_actuelle} - {get_phase_name(phase_actuelle)}", inline=False)
        embed.add_field(name="Joueurs inscrits", value=len(joueurs), inline=True)
        embed.add_field(name="Joueurs éliminés", value=len(elimines), inline=True)
        embed.add_field(name="Joueurs qualifiés", value=f"{qualifies}/4", inline=True)
        await ctx.send(embed=embed)
        return
    
    if nouvelle_phase not in [PHASE_INSCRIPTION, PHASE_TOURNOI, PHASE_QUALIFIES]:
        await ctx.send("❌ Phase invalide. Utilisez 1 (Inscription), 2 (Tournoi), ou 3 (Qualifiés).")
        return
    
    ancienne_phase = phase_actuelle
    phase_actuelle = nouvelle_phase
    save_data()
    
    await ctx.send(f"✅ Phase changée de **{get_phase_name(ancienne_phase)}** vers **{get_phase_name(nouvelle_phase)}**")
    
    # Déclencher la dispersion si on passe en phase tournoi
    if nouvelle_phase == PHASE_TOURNOI:
        await annoncer_changement_phase(ctx.channel, PHASE_TOURNOI)
    elif nouvelle_phase == PHASE_QUALIFIES:
        await annoncer_changement_phase(ctx.channel, PHASE_QUALIFIES)

@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def qualifies(ctx):
    """Affiche la liste des joueurs qualifiés (10+ étoiles)"""
    joueurs_qualifies = []
    
    for uid, stats in joueurs.items():
        if stats.get("etoiles", 0) >= SEUIL_QUALIFICATION and uid != 999999999999999999:
            try:
                user = await bot.fetch_user(uid)
                joueurs_qualifies.append((user.display_name, stats["etoiles"]))
            except:
                joueurs_qualifies.append((f"ID {uid}", stats["etoiles"]))
    
    if not joueurs_qualifies:
        await ctx.send("🚫 Aucun joueur qualifié pour le moment (10+ étoiles requis).")
        return
    
    # Trier par nombre d'étoiles décroissant
    joueurs_qualifies.sort(key=lambda x: x[1], reverse=True)
    
    embed = discord.Embed(title="🏆 Joueurs qualifiés", color=discord.Color.gold())
    embed.description = f"Joueurs avec {SEUIL_QUALIFICATION}+ étoiles :"
    
    for i, (nom, etoiles) in enumerate(joueurs_qualifies[:10], 1):
        embed.add_field(name=f"{i}. {nom}", value=f"⭐ {etoiles} étoiles", inline=False)
    
    embed.set_footer(text=f"{len(joueurs_qualifies)}/4 qualifiés")
    await ctx.send(embed=embed)


@bot.command()
async def statut_tournoi(ctx):
    """Affiche l'état général du tournoi"""
    qualifies = compter_qualifies()
    
    embed = discord.Embed(title="📊 État du tournoi", color=discord.Color.blue())
    embed.add_field(name="Phase actuelle", value=get_phase_name(phase_actuelle), inline=False)
    embed.add_field(name="Joueurs inscrits", value=len(joueurs), inline=True)
    embed.add_field(name="Joueurs éliminés", value=len(elimines), inline=True)
    embed.add_field(name="Joueurs qualifiés", value=f"{qualifies}/4", inline=True)
    
    if phase_actuelle == PHASE_INSCRIPTION:
        embed.add_field(name="Action possible", value="Utilisez `!inscrire` pour rejoindre", inline=False)
    elif phase_actuelle == PHASE_TOURNOI:
        embed.add_field(name="Action possible", value="Les duels sont ouverts !", inline=False)
    elif phase_actuelle == PHASE_QUALIFIES:
        embed.add_field(name="Action possible", value="Phase finale en cours", inline=False)
    
    await ctx.send(embed=embed)

def disperser_joueurs_aleatoirement():
    """Disperse tous les joueurs dans des zones aléatoirement"""
    for user_id in joueurs.keys():
        if user_id != 999999999999999999:  # Exclure Mathmech Circular
            zone_aleatoire = random.choice(zones)
            positions[user_id] = zone_aleatoire
            # Marquer que le joueur doit faire un duel avant de pouvoir bouger
            derniers_deplacements[str(user_id)] = True
    save_data()


@tasks.loop(hours=24)
async def mirvu_daily_task():
    """Distribue une étoile de Mathmech Circular chaque jour à 6h"""
    global mirvu_bot_etoiles
    
    # Vérifier qu'il est 6h du matin
    now = datetime.now()
    if now.hour != 6:
        return
    
    if mirvu_bot_etoiles <= 0:
        mirvu_daily_task.stop()
        return
    
    # Trouver un joueur au hasard (excluant Mathmech Circular)
    joueurs_eligibles = [uid for uid in joueurs.keys() if uid != 999999999999999999]
    
    if not joueurs_eligibles:
        return
    
    import random
    lucky_player_id = random.choice(joueurs_eligibles)
    
    try:
        lucky_player = await bot.fetch_user(lucky_player_id)
        
        # Transférer une étoile
        joueurs[lucky_player_id]["etoiles"] += 1
        mirvu_bot_etoiles -= 1
        joueurs[999999999999999999]["etoiles"] = mirvu_bot_etoiles
        
        # Annoncer dans le salon principal
        channel = discord.utils.get(bot.get_all_channels(), name="conversation-tournois")
        if channel:
            await channel.send(f"🌟 **Distribution quotidienne !** {lucky_player.display_name} reçoit 1 étoile de Mathmech Circular ! (Reste : {mirvu_bot_etoiles})")
        
        save_data()
        
        # Arrêter si plus d'étoiles
        if mirvu_bot_etoiles <= 0:
            if channel:
                await channel.send("🍽️ Mathmech Circular a fini de manger toutes ses étoiles !")
            mirvu_daily_task.stop()
            
    except Exception as e:
        print(f"Erreur dans mirvu_daily_task: {e}")


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
        
        # Table des joueurs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS joueurs (
                user_id BIGINT PRIMARY KEY,
                or_amount INTEGER DEFAULT 30,
                etoiles INTEGER DEFAULT 2,
                statuts JSONB DEFAULT '[]'::jsonb,
                minerva_shield BOOLEAN DEFAULT FALSE,
                negociateur BOOLEAN DEFAULT FALSE,
                atem_protection BOOLEAN DEFAULT FALSE,
                skream_omnipresent BOOLEAN DEFAULT FALSE,
                tyrano_active BOOLEAN DEFAULT FALSE,
                yop_coin_advantage BOOLEAN DEFAULT FALSE
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


@bot.command()
@is_owner()
async def migrate_db(ctx):
    """Ajoute les nouvelles colonnes à la base de données"""
    conn = get_db_connection()
    if not conn:
        await ctx.send("❌ Impossible de se connecter à la DB")
        return
        
    try:
        cursor = conn.cursor()
        
        # Ajouter les nouvelles colonnes une par une
        nouvelles_colonnes = [
            ("atem_protection", "BOOLEAN DEFAULT FALSE"),
            ("skream_omnipresent", "BOOLEAN DEFAULT FALSE"), 
            ("tyrano_active", "BOOLEAN DEFAULT FALSE"),
            ("yop_coin_advantage", "BOOLEAN DEFAULT FALSE")
        ]
        
        colonnes_ajoutees = []
        colonnes_existantes = []
        
        for nom_colonne, definition in nouvelles_colonnes:
            try:
                cursor.execute(f"ALTER TABLE joueurs ADD COLUMN {nom_colonne} {definition}")
                colonnes_ajoutees.append(nom_colonne)
            except Exception as e:
                if "already exists" in str(e).lower():
                    colonnes_existantes.append(nom_colonne)
                else:
                    await ctx.send(f"❌ Erreur lors de l'ajout de {nom_colonne}: {e}")
                    conn.rollback()
                    conn.close()
                    return
        
        conn.commit()
        cursor.close()
        conn.close()
        
        message = "✅ Migration terminée !\n"
        if colonnes_ajoutees:
            message += f"Colonnes ajoutées: {', '.join(colonnes_ajoutees)}\n"
        if colonnes_existantes:
            message += f"Colonnes déjà existantes: {', '.join(colonnes_existantes)}"
            
        await ctx.send(message)
        
    except Exception as e:
        await ctx.send(f"❌ Erreur générale de migration: {e}")
        if conn:
            conn.rollback()
            conn.close()


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


exclusive_commands = ["fsz", "zaga", "fman", "capitaine", "fayth", "shaman", 
                     "atem", "skream", "tyrano", "retro", "voorhees", "yop"]

TOURNAMENT_WINNERS_JVC = [
    673606402782265344,
    536681221481037824,
    383073877820964864,
    699694209950548069,
    884822218566152222,
    496026713730318336,
    1038417018589822976
]

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
    """Sauvegarde tous les données en base - VERSION CORRIGÉE AVEC GESTION D'ERREUR"""
    conn = get_db_connection()
    if not conn:
        print("❌ Impossible de se connecter à la DB pour sauvegarder")
        return
        
    try:
        cursor = conn.cursor()
        
        # Vérifier d'abord si les nouvelles colonnes existent
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'joueurs' AND column_name IN ('atem_protection', 'skream_omnipresent', 'tyrano_active', 'yop_coin_advantage')
        """)
        colonnes_existantes = [row[0] for row in cursor.fetchall()]
        
        # Sauvegarder les joueurs selon les colonnes disponibles
        for user_id, data in joueurs.items():
            try:
                if len(colonnes_existantes) == 4:  # Toutes les nouvelles colonnes existent
                    cursor.execute("""
                        INSERT INTO joueurs (user_id, or_amount, etoiles, statuts, minerva_shield, negociateur,
                                           atem_protection, skream_omnipresent, tyrano_active, yop_coin_advantage)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET
                            or_amount = EXCLUDED.or_amount,
                            etoiles = EXCLUDED.etoiles,
                            statuts = EXCLUDED.statuts,
                            minerva_shield = EXCLUDED.minerva_shield,
                            negociateur = EXCLUDED.negociateur,
                            atem_protection = EXCLUDED.atem_protection,
                            skream_omnipresent = EXCLUDED.skream_omnipresent,
                            tyrano_active = EXCLUDED.tyrano_active,
                            yop_coin_advantage = EXCLUDED.yop_coin_advantage
                    """, (
                        int(user_id), 
                        data.get('or', 30), 
                        data.get('etoiles', 2),
                        json.dumps(data.get('statuts', [])),
                        data.get('minerva_shield', False),
                        data.get('negociateur', False),
                        data.get('atem_protection', False),
                        data.get('skream_omnipresent', False),
                        data.get('tyrano_active', False),
                        data.get('yop_coin_advantage', False)
                    ))
                else:  # Utiliser l'ancien format
                    cursor.execute("""
                        INSERT INTO joueurs (user_id, or_amount, etoiles, statuts, minerva_shield, negociateur)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET
                            or_amount = EXCLUDED.or_amount,
                            etoiles = EXCLUDED.etoiles,
                            statuts = EXCLUDED.statuts,
                            minerva_shield = EXCLUDED.minerva_shield,
                            negociateur = EXCLUDED.negociateur
                    """, (
                        int(user_id), 
                        data.get('or', 30), 
                        data.get('etoiles', 2),
                        json.dumps(data.get('statuts', [])),
                        data.get('minerva_shield', False),
                        data.get('negociateur', False)
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

            # Dans save_data(), après la sauvegarde des bans temporaires :

        # Sauvegarder les données Mirvu
        try:
            cursor.execute("""
                INSERT INTO commandes_globales (command_name, used, user_id)
                VALUES ('mirvu_bot_etoiles', %s, %s)
                ON CONFLICT (command_name) DO UPDATE SET 
                    used = EXCLUDED.used,
                    user_id = EXCLUDED.user_id
            """, (bool(mirvu_bot_etoiles > 0), mirvu_bot_etoiles))
        except Exception as e:
            print(f"Erreur sauvegarde données Mirvu: {e}")

        # Sauvegarder les réserves Adam
        try:
            cursor.execute("DELETE FROM commandes_globales WHERE command_name LIKE 'adam_reserve_%'")
            for user_id in joueurs_adam_reserves.keys():
                cursor.execute("""
                    INSERT INTO commandes_globales (command_name, used, user_id)
                    VALUES (%s, %s, %s)
                """, (f"adam_reserve_{user_id}", True, int(user_id)))
        except Exception as e:
            print(f"Erreur sauvegarde réserves Adam: {e}")

        cursor.execute("""
            INSERT INTO commandes_globales (command_name, used, user_id)
            VALUES ('phase_actuelle', %s, %s)
            ON CONFLICT (command_name) DO UPDATE SET 
                used = EXCLUDED.used,
                user_id = EXCLUDED.user_id
        """, (True, phase_actuelle))
        
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
        
        # Vérifier quelles colonnes existent
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'joueurs'
        """)
        colonnes_disponibles = [row['column_name'] for row in cursor.fetchall()]
        
        # Charger les joueurs
        cursor.execute("SELECT * FROM joueurs")
        joueurs.clear()
        for row in cursor.fetchall():
            joueurs[row['user_id']] = {
                'or': row['or_amount'],
                'etoiles': row['etoiles'],
                'statuts': row['statuts'] if row['statuts'] else [],
                'minerva_shield': row['minerva_shield'],
                'negociateur': row['negociateur'],
                'atem_protection': row.get('atem_protection', False) if 'atem_protection' in colonnes_disponibles else False,
                'skream_omnipresent': row.get('skream_omnipresent', False) if 'skream_omnipresent' in colonnes_disponibles else False,
                'tyrano_active': row.get('tyrano_active', False) if 'tyrano_active' in colonnes_disponibles else False,
                'yop_coin_advantage': row.get('yop_coin_advantage', False) if 'yop_coin_advantage' in colonnes_disponibles else False
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

        # Dans load_data(), après le chargement des commandes globales :
        # Charger les données Mirvu et Adam
        cursor.execute("SELECT * FROM commandes_globales WHERE command_name IN ('mirvu_bot_etoiles') OR command_name LIKE 'adam_reserve_%'")
        for row in cursor.fetchall():
            if row['command_name'] == 'mirvu_bot_etoiles':
                mirvu_bot_etoiles = row['user_id'] if row['user_id'] else 0
                if mirvu_bot_etoiles > 0 and not mirvu_daily_task.is_running():
                    mirvu_daily_task.start()
            elif row['command_name'].startswith('adam_reserve_'):
                user_id = int(row['command_name'].replace('adam_reserve_', ''))
                joueurs_adam_reserves[user_id] = True

        
        try:
            cursor.execute("SELECT user_id FROM commandes_globales WHERE command_name = 'phase_actuelle'")
            row = cursor.fetchone()
            if row:
                phase_actuelle = row['user_id']  # On stocke la phase dans user_id
            else:
                phase_actuelle = PHASE_INSCRIPTION  # Valeur par défaut
        except Exception as e:
            print(f"Erreur chargement phase: {e}")
            phase_actuelle = PHASE_INSCRIPTION
        
        cursor.close()
        conn.close()
        print("✅ Données chargées depuis PostgreSQL")
        
    except Exception as e:
        print(f"Erreur chargement: {e}")
        if conn:
            conn.close()


# --- UTILITAIRES ---
def est_inscrit(user_id):
    return user_id in joueurs and user_id not in elimines


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
@require_phase(PHASE_INSCRIPTION)
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

"""@bot.command()
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

    await ctx.send(msg)"""


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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def aller(ctx, *, zone: str):
    user = ctx.author
    user_id = str(user.id)

    if not est_inscrit(user.id):
        await ctx.send("❌ Tu dois d’abord t’inscrire avec `!inscrire`.")
        return
    if zone not in zones:
        await ctx.send("❌ Zone invalide ! Tape !zones_dispo pour voir les zones.")
        return

    # Vérifie si le joueur a déjà changé de zone sans duel
    if derniers_deplacements.get(user_id, False):
        await ctx.send("🚫 Tu ne peux pas changer de zone deux fois de suite sans avoir disputé de duel dans ta zone.")
        return

    # Change la zone
    positions[user.id] = zone
    derniers_deplacements[user_id] = True  # il doit jouer un duel avant de rebouger
    save_data()

    await ctx.send(f"🚶 {user.display_name} se rend à **{zone}**.")

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
        await ctx.send(f"❌ {membre.display_name} n’est pas inscrit.")
        return
    zone = positions[membre.id]
    await ctx.send(f"📍 {membre.display_name} est actuellement à **{zone}**.")


# --- DUEL ---
@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def duel(ctx, gagnant: discord.Member, perdant: discord.Member, etoiles: int, or_: int):
    """COMMANDE MODIFIÉE - Duel avec gestion des nouveaux effets"""
    if not est_inscrit(gagnant.id) or not est_inscrit(perdant.id):
        await ctx.send("❌ Les deux joueurs doivent être inscrits.")
        return

    if joueurs[perdant.id]["etoiles"] < etoiles:
        await ctx.send(f"❌ {perdant.display_name} n'a pas assez d'étoiles pour miser ({etoiles} demandées).")
        return

    if joueurs[perdant.id]["or"] < or_:
        await ctx.send(f"❌ {perdant.display_name} n'a pas assez d'or pour miser ({or_} demandés).")
        return

    # Vérification zone avec effet Skream
    gagnant_omnipresent = joueurs.get(gagnant.id, {}).get("skream_omnipresent", False)
    perdant_omnipresent = joueurs.get(perdant.id, {}).get("skream_omnipresent", False)
    
    if not gagnant_omnipresent and not perdant_omnipresent:
        if positions.get(gagnant.id) != positions.get(perdant.id):
            await ctx.send("❌ Les deux joueurs doivent être dans la même zone pour dueler.")
            return

    if gagnant.id == perdant.id:
        await ctx.send("❌ Tu ne peux pas te défier toi-même !")
        return

    # ----- Effet Minerva côté perdant : perd 1 ⭐ de moins, une seule fois -----
    perte_etoiles = etoiles
    if joueurs.get(perdant.id, {}).get("minerva_shield"):
        perte_etoiles = max(0, etoiles - 1)
        joueurs[perdant.id]["minerva_shield"] = False
        # Retire le statut visible
        statuts = joueurs[perdant.id].get("statuts", [])
        if "Protégé par Minerva" in statuts:
            statuts.remove("Protégé par Minerva")

    # ----- Consommation effet Skream après 1 duel -----
    skream_message = ""
    if gagnant_omnipresent:
        joueurs[gagnant.id]["skream_omnipresent"] = False
        statuts = joueurs[gagnant.id].get("statuts", [])
        if "Omniprésent" in statuts:
            statuts.remove("Omniprésent")
        skream_message = f"\n🌟 L'effet Skream de {gagnant.display_name} s'estompe après ce duel."
    
    if perdant_omnipresent:
        joueurs[perdant.id]["skream_omnipresent"] = False
        statuts = joueurs[perdant.id].get("statuts", [])
        if "Omniprésent" in statuts:
            statuts.remove("Omniprésent")
        skream_message += f"\n🌟 L'effet Skream de {perdant.display_name} s'estompe après ce duel."

    # Transfert des mises
    joueurs[perdant.id]["etoiles"] -= perte_etoiles
    joueurs[gagnant.id]["etoiles"] += perte_etoiles
    joueurs[gagnant.id]["or"] += or_
    joueurs[perdant.id]["or"] -= or_

    await ctx.send(
        f"⚔️ Duel terminé à **{positions.get(gagnant.id, 'Zone inconnue')}** !\n"
        f"🏆 {gagnant.display_name} gagne ⭐{perte_etoiles} étoile(s) et 💰{or_} or.\n"
        f"💀 {perdant.display_name} perd ⭐{perte_etoiles} étoile(s) et 💰{or_} or."
        f"{skream_message}"
    )

    # Vérification élimination avec protection Atem
    if joueurs[perdant.id]["etoiles"] <= 0:
        if joueurs.get(perdant.id, {}).get("atem_protection", False):
            # Protection Atem activée
            joueurs[perdant.id]["etoiles"] = 1
            joueurs[perdant.id]["atem_protection"] = False
            
            # Retirer le statut
            statuts = joueurs[perdant.id].get("statuts", [])
            if "Protégé par Atem" in statuts:
                statuts.remove("Protégé par Atem")
                
            await ctx.send(f"🛡️ **{perdant.display_name}** était protégé par Atem ! Il survit avec 1 étoile !")
        else:
            # Élimination normale
            await ctx.send(f":skull: **{perdant.display_name} est éliminé du tournoi !**")
            elimines.add(perdant.id)
            await activer_effet_adam(perdant.id, ctx.channel)
            joueurs.pop(perdant.id, None)
            positions.pop(perdant.id, None)
            inventaires.pop(perdant.id, None)

    derniers_deplacements[str(gagnant.id)] = False
    derniers_deplacements[str(perdant.id)] = False

    # Vérifier si on passe en phase qualifiés
    if verifier_phase_qualifies():
        await annoncer_changement_phase(ctx.channel, PHASE_QUALIFIES)

    save_data()


# --- GESTION D'ERREURS POUR LA COMMANDE DUEL ---
@duel.error
async def duel_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Utilisation : `!duel @Gagnant @Perdant [étoiles] [or]`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Arguments invalides. Assurez-vous que les étoiles et l'or sont des nombres.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Un des membres mentionnés est introuvable.")
    else:
        await ctx.send(f"❌ Erreur lors du duel : {str(error)}")
        print(f"Erreur duel non gérée: {error}")


# --- COMMANDE DEBUG POUR TESTER LA CONVERSION ---
@bot.command()
@is_owner()
async def test_membre(ctx, *, argument):
    """Teste la conversion d'un argument en Member (debug admin)"""
    try:
        converter = commands.MemberConverter()
        member = await converter.convert(ctx, argument)
        await ctx.send(f"✅ Conversion réussie : {member.display_name} (ID: {member.id})")
    except commands.MemberNotFound:
        await ctx.send(f"❌ Impossible de convertir '{argument}' en Member")
    except Exception as e:
        await ctx.send(f"❌ Erreur : {e}")




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
                "Moulinglacia the Elemental Lord": 90,
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def atem(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "atem")
    if not ok:
        await ctx.send(msg)
        return

    # Activer la protection Atem
    joueurs[user_id]["atem_protection"] = True
    
    joueurs[user_id].setdefault("statuts", [])
    if "Protégé par Atem" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Protégé par Atem")

    lock_exclusive(user_id, "atem")
    save_data()

    await ctx.send(f"{ctx.author.display_name} a corrompu l'orga ! La prochaine fois que tu devrais être éliminé, tu survis avec 1 étoile !")


@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def skream(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "skream")
    if not ok:
        await ctx.send(msg)
        return

    # Activer l'omniprésence
    joueurs[user_id]["skream_omnipresent"] = True
    
    joueurs[user_id].setdefault("statuts", [])
    if "Omniprésent" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Omniprésent")

    lock_exclusive(user_id, "skream")
    save_data()

    await ctx.send(f"{ctx.author.display_name} est maintenant présent dans chaque zone du tournoi ! Tu peux affronter n'importe qui !")


@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def tyrano(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "tyrano")
    if not ok:
        await ctx.send(msg)
        return

    # Activer l'effet Tyrano
    joueurs[user_id]["tyrano_active"] = True
    
    joueurs[user_id].setdefault("statuts", [])
    if "Tyrano actif" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Tyrano actif")

    lock_exclusive(user_id, "tyrano")
    save_data()

    await ctx.send(f"{ctx.author.display_name} active une météore ! À la fin de chaque BO3, tu gagnes 3 or par monstre détruit par un effet. Si 30 monstres sont détruits en 1 BO3, tu gagnes 1 étoile !")

@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def retro(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "retro")
    if not ok:
        await ctx.send(msg)
        return

    # Ajouter Dimensional Shifter à l'inventaire
    inventaires[user_id]["cartes"].append("Dimensional Shifter")

    lock_exclusive(user_id, "retro")
    save_data()

    await ctx.send(f"{ctx.author.display_name} change de dimension ! **Dimensional Shifter** a été ajoutée à ton inventaire !")


@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def voorhees(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "voorhees")
    if not ok:
        await ctx.send(msg)
        return

    # Vérifier si le joueur est un gagnant de tournoi JVC
    if user_id in TOURNAMENT_WINNERS_JVC:
        # Gagnant de tournoi : +1 étoile
        joueurs[user_id]["etoiles"] += 1
        lock_exclusive(user_id, "voorhees")
        save_data()
        await ctx.send(f"{ctx.author.display_name} a l'Âme d'un Vainqueur ! Tu gagnes **1 étoile** !")
    else:
        # Joueur normal : +30 or
        joueurs[user_id]["or"] += 30
        lock_exclusive(user_id, "voorhees")
        save_data()
        await ctx.send(f"{ctx.author.display_name} gagne **30 or** !")


@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def yop(ctx):
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "yop")
    if not ok:
        await ctx.send(msg)
        return

    # Activer l'avantage à pile ou face
    joueurs[user_id]["yop_coin_advantage"] = True
    
    joueurs[user_id].setdefault("statuts", [])
    if "Avantage Yop" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Avantage Yop")

    lock_exclusive(user_id, "yop")
    save_data()

    await ctx.send(f"{ctx.author.display_name} truque la pièce ! Tu gagnes la pièce à ton prochain BO3, si ton deck ne contient aucune de ces cartes : Arcana Force XXI - The World, Moulinglacia the Elemental Lord, Herald of Ultimateness !")


@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
        joueurs[user_id]["or"] = joueurs[user_id].get("or", 0) + 60
        await ctx.send(f"{ctx.author.display_name} a activé Mathmech Circular : **+60 or** !")

    lock_exclusive(user_id, "fsz")
    save_data()


@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def zaga(ctx):
    """COMMANDE MODIFIÉE - ZagaNaga accorde le pouvoir de prohibition"""
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "zaga")
    if not ok:
        await ctx.send(msg)
        return

    # Activer le statut Prohibition
    joueurs[user_id].setdefault("statuts", [])
    if "Prohibition" not in joueurs[user_id]["statuts"]:
        joueurs[user_id]["statuts"].append("Prohibition")

    lock_exclusive(user_id, "zaga")
    save_data()

    await ctx.send(f"{ctx.author.display_name} active Prohibition !\n"
                   f"**Effet :** Lors de chacun de tes duels, tu peux déclarer une carte d'ARCHÉTYPE DE MAIN DECK (donc PAS DE STAPLES) que ton adversaire ne pourra pas utiliser durant le BO3.\n"
                   f"Tu dois simplement l'annoncer à ton adversaire avant le duel.")




@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def mirvu(ctx):
    """Commande Mirvu avec le scénario complet"""
    global mirvu_bot_etoiles
    
    user_id = ctx.author.id
    ok, msg = can_use_exclusive(user_id, "mirvu")
    if not ok:
        await ctx.send(msg)
        return
    
    if not est_inscrit(user_id):
        await ctx.send("⚠️ Tu dois être inscrit pour utiliser cette commande.")
        return
    
    participant = ctx.author.display_name
    etoiles_actuelles = joueurs[user_id]["etoiles"]
    etoiles_gagnees = 10 - etoiles_actuelles  # Calcul selon la nouvelle règle
    
    # Séquence de messages avec délais
    await ctx.send("Vous gagnez…")
    await asyncio.sleep(2)
    
    await ctx.send("Hmmmm")
    await asyncio.sleep(2)
    
    await ctx.send("Vous gagneeeeeeez…..")
    await asyncio.sleep(3)
    
    await ctx.send("J'ai plus grand chose à offrir…")
    await asyncio.sleep(2)
    
    await ctx.send("OH JE SAIS")
    await asyncio.sleep(2)
    
    await ctx.send("Vous gagnez…")
    await asyncio.sleep(3)
    
    await ctx.send("… le tournoi !")
    await asyncio.sleep(1)
    
    await ctx.send(f"🏆 **{participant}** gagne {etoiles_gagnees} étoiles !")
    await asyncio.sleep(1)
    
    await ctx.send(f"🎉 **FÉLICITATIONS À {participant.upper()} POUR SA VICTOIRE AU TOURNOI !** 🎉")
    
    # Attendre 30 secondes
    await asyncio.sleep(30)
    
    await ctx.send("Ah-")
    await asyncio.sleep(2)
    
    await ctx.send("On me dit que je peux pas faire ça")
    await asyncio.sleep(2)
    
    await ctx.send("Je vais donc reprendre ces étoiles")
    await asyncio.sleep(1)
    
    await ctx.send(f"📉 **{participant}** perd {etoiles_gagnees} étoiles")
    await asyncio.sleep(1)
    
    await ctx.send(f"❌ {participant} ne remporte plus le tournoi")
    await asyncio.sleep(2)
    
    await ctx.send("Mais que vais-je faire de ces étoiles…")
    await asyncio.sleep(3)
    
    await ctx.send("Je vais les manger !")
    await asyncio.sleep(2)
    
    # Mathmech Circular s'inscrit avec les étoiles
    mirvu_bot_etoiles = etoiles_gagnees
    mathmech_id = 999999999999999999  # ID fictif pour Mathmech Circular
    
    # L'ajouter comme "joueur" spécial
    joueurs[mathmech_id] = {"or": 0, "etoiles": mirvu_bot_etoiles}
    positions[mathmech_id] = "KaibaCorp"
    inventaires[mathmech_id] = {"or": 0, "cartes": []}
    
    await ctx.send(f"🤖 **@Mathmech Circular** s'inscrit au tournoi avec {mirvu_bot_etoiles} étoiles et 0 or")
    await ctx.send("⏰ *Le bot donnera une étoile à un joueur au hasard chaque jour à 6h du matin jusqu'à ce qu'il n'en ait plus*")
    
    # Démarrer la tâche quotidienne si pas déjà active
    if not mirvu_daily_task.is_running():
        mirvu_daily_task.start()
    
    lock_exclusive(user_id, "mirvu")
    save_data()

@bot.command()
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
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
@require_phase(PHASE_TOURNOI, PHASE_QUALIFIES)
async def adam(ctx):
    """Permet à un joueur encore en course de réserver l'effet Adam pour son élimination future"""
    user_id = ctx.author.id
    
    # Vérifier que le joueur est encore en course
    if not est_inscrit(user_id):
        await ctx.send("⚠️ Tu dois être inscrit pour utiliser cette commande.")
        return
    
    if user_id in elimines:
        await ctx.send("⚠️ Tu es déjà éliminé, tu ne peux plus utiliser cette commande.")
        return
    
    ok, msg = can_use_exclusive(user_id, "adam")
    if not ok:
        await ctx.send(msg)
        return
    
    # Réserver l'effet Adam pour ce joueur
    joueurs_adam_reserves[user_id] = True
    
    await ctx.send(f"🔮 **{ctx.author.display_name}**, Quand tu seras éliminé, tu rejoindras automatiquement un joueur encore en course.")
    
    lock_exclusive(user_id, "adam")
    save_data()

async def activer_effet_adam(user_id, channel):
    """Active l'effet Adam si le joueur éliminé l'avait réservé"""
    if user_id not in joueurs_adam_reserves:
        return False
    
    # Trouver un joueur au hasard encore en course
    joueurs_actifs = [uid for uid in joueurs.keys() if uid not in elimines and uid != 999999999999999999 and uid != user_id]
    
    if not joueurs_actifs:
        await channel.send("⚠️ Aucun joueur actif disponible pour l'effet Adam.")
        return False
    
    import random
    hote_id = random.choice(joueurs_actifs)
    
    try:
        user = await bot.fetch_user(user_id)
        hote_user = await bot.fetch_user(hote_id)
        participant = user.display_name
        hote_name = hote_user.display_name
        
        # Le nom devient "participant rejoint + hôte"
        nouveau_nom = f"{participant} rejoint {hote_name}"
        
        await channel.send(f"🔮 **Effet Adam activé !**")
        await channel.send(f"🤝 **{participant}** rejoint **{hote_name}** pour le reste du tournoi !")
        await channel.send(f"📝 L'équipe s'appelle maintenant : **{nouveau_nom}**")
        await channel.send(f"ℹ️ {hote_name} décide lequel des deux joueurs dispute les BO3.")
        
        # Retirer de la liste des réserves Adam
        del joueurs_adam_reserves[user_id]
        save_data()
        return True
        
    except Exception as e:
        await channel.send(f"⚠️ Erreur lors de l'activation de l'effet Adam : {e}")
        return False


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
async def admin_eliminer(ctx, membre: discord.Member):
    """Élimine un joueur du tournoi (admin only)"""
    if not est_inscrit(membre.id):
        await ctx.send(f"⚠️ {membre.display_name} n'est pas inscrit.")
        return
    
    if membre.id in elimines:
        await ctx.send(f"⚠️ {membre.display_name} est déjà éliminé.")
        return
    
    # Éliminer le joueur
    elimines.add(membre.id)
    joueurs.pop(membre.id, None)
    positions.pop(membre.id, None)
    inventaires.pop(membre.id, None)
    
    save_data()
    await ctx.send(f"☠️ **{membre.display_name}** a été éliminé du tournoi par l'administration.")

@bot.command()
@is_owner()
async def admin_restaurer(ctx, membre: discord.Member, etoiles: int = 2, or_amount: int = 30):
    """Restaure un joueur éliminé dans le tournoi (admin only)"""
    if est_inscrit(membre.id):
        await ctx.send(f"⚠️ {membre.display_name} est déjà inscrit.")
        return
    
    # Retirer de la liste des éliminés
    elimines.discard(membre.id)
    
    # Réinscrire le joueur
    joueurs[membre.id] = {"or": or_amount, "etoiles": etoiles}
    positions[membre.id] = "KaibaCorp"
    inventaires[membre.id] = {"or": or_amount, "cartes": []}
    
    save_data()
    await ctx.send(f"✅ **{membre.display_name}** a été restauré dans le tournoi avec ⭐{etoiles} étoiles et 💰{or_amount} or.")

@bot.command()
@is_owner()
async def admin_teleporter(ctx, membre: discord.Member, zone: str):
    """Téléporte un joueur dans une zone spécifique (admin only)"""
    if not est_inscrit(membre.id):
        await ctx.send(f"⚠️ {membre.display_name} n'est pas inscrit.")
        return
    
    if zone not in zones:
        await ctx.send(f"⚠️ Zone invalide. Zones disponibles : {', '.join(zones)}")
        return
    
    positions[membre.id] = zone
    save_data()
    await ctx.send(f"🚀 **{membre.display_name}** a été téléporté à **{zone}**.")

@bot.command()
@is_owner()
async def admin_statut(ctx, membre: discord.Member, *, statut: str):
    """Ajoute un statut visible à un joueur (admin only)"""
    if not est_inscrit(membre.id):
        await ctx.send(f"⚠️ {membre.display_name} n'est pas inscrit.")
        return
    
    joueurs[membre.id].setdefault("statuts", [])
    if statut not in joueurs[membre.id]["statuts"]:
        joueurs[membre.id]["statuts"].append(statut)
        save_data()
        await ctx.send(f"✅ Statut **{statut}** ajouté à {membre.display_name}.")
    else:
        await ctx.send(f"⚠️ {membre.display_name} a déjà le statut **{statut}**.")

@bot.command()
@is_owner()
async def admin_retirer_statut(ctx, membre: discord.Member, *, statut: str):
    """Retire un statut d'un joueur (admin only)"""
    if not est_inscrit(membre.id):
        await ctx.send(f"⚠️ {membre.display_name} n'est pas inscrit.")
        return
    
    statuts = joueurs[membre.id].get("statuts", [])
    if statut in statuts:
        statuts.remove(statut)
        save_data()
        await ctx.send(f"✅ Statut **{statut}** retiré de {membre.display_name}.")
    else:
        await ctx.send(f"⚠️ {membre.display_name} n'a pas le statut **{statut}**.")

@bot.command()
@is_owner()
async def admin_boutique_reset(ctx):
    """Remet la boutique à son état initial (admin only)"""
    global boutique
    import copy
    boutique = copy.deepcopy(BOUTIQUE_INITIALE)
    save_data()
    await ctx.send("🔄 La boutique a été remise à son état initial.")

@bot.command()
@is_owner()
async def admin_forcer_duel(ctx, gagnant: discord.Member, perdant: discord.Member, etoiles: int, or_amount: int):
    """Force un duel sans vérifications de zone (admin only)"""
    if not est_inscrit(gagnant.id) or not est_inscrit(perdant.id):
        await ctx.send("⚠️ Les deux joueurs doivent être inscrits.")
        return
    
    # Transférer directement sans vérifications
    if joueurs[perdant.id]["etoiles"] < etoiles:
        etoiles = joueurs[perdant.id]["etoiles"]  # Prendre le max possible
    
    if joueurs[perdant.id]["or"] < or_amount:
        or_amount = joueurs[perdant.id]["or"]  # Prendre le max possible
    
    joueurs[perdant.id]["etoiles"] -= etoiles
    joueurs[gagnant.id]["etoiles"] += etoiles
    joueurs[gagnant.id]["or"] += or_amount
    joueurs[perdant.id]["or"] -= or_amount
    
    await ctx.send(
        f"⚔️ **Duel forcé par l'administration !**\n"
        f"🏆 {gagnant.display_name} gagne ⭐{etoiles} étoile(s) et 💰{or_amount} or.\n"
        f"💀 {perdant.display_name} perd ⭐{etoiles} étoile(s) et 💰{or_amount} or."
    )
    
    # Vérification élimination
    if joueurs[perdant.id]["etoiles"] <= 0:
        await ctx.send(f"☠️ **{perdant.display_name} est éliminé du tournoi !**")
        elimines.add(perdant.id)
        joueurs.pop(perdant.id, None)
        positions.pop(perdant.id, None)
        inventaires.pop(perdant.id, None)
    
    save_data()

@bot.command()
@is_owner()
async def admin_mirvu_stop(ctx):
    """Arrête la distribution quotidienne de Mathmech Circular (admin only)"""
    global mirvu_bot_etoiles
    
    if mirvu_daily_task.is_running():
        mirvu_daily_task.stop()
        await ctx.send("⏹️ Distribution quotidienne de Mathmech Circular arrêtée.")
    else:
        await ctx.send("⚠️ La distribution quotidienne n'était pas active.")
    
    # Optionnel : retirer Mathmech Circular du tournoi
    mathmech_id = 999999999999999999
    if mathmech_id in joueurs:
        mirvu_bot_etoiles = 0
        joueurs.pop(mathmech_id, None)
        positions.pop(mathmech_id, None)
        inventaires.pop(mathmech_id, None)
        await ctx.send("🤖 Mathmech Circular a été retiré du tournoi.")
        save_data()

@bot.command()
@is_owner()
async def admin_adam_list(ctx):
    """Affiche la liste des joueurs ayant réservé l'effet Adam (admin only)"""
    if not joueurs_adam_reserves:
        await ctx.send("Aucun joueur n'a réservé l'effet Adam.")
        return
    
    msg = "🔮 **Joueurs ayant réservé l'effet Adam :**\n"
    for user_id in joueurs_adam_reserves.keys():
        try:
            user = await bot.fetch_user(user_id)
            msg += f"- {user.display_name}\n"
        except:
            msg += f"- ID {user_id}\n"
    
    await ctx.send(msg)

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

    # Dans la fonction reset(), ajoutez :
    global mirvu_bot_etoiles, joueurs_adam_reserves

    mirvu_bot_etoiles = 0
    joueurs_adam_reserves = {}

    # Arrêter la tâche Mirvu si elle tourne
    if mirvu_daily_task.is_running():
        mirvu_daily_task.stop()

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

@bot.command()
@is_owner()
async def debug_elimination(ctx, membre: discord.Member):
    """Debug pour vérifier l'état d'un joueur (admin only)"""
    uid = membre.id
    
    embed = discord.Embed(title=f"🔍 Debug - État de {membre.display_name}", color=discord.Color.yellow())
    
    # Vérifier chaque dictionnaire
    embed.add_field(name="Dans joueurs", value=str(uid in joueurs), inline=True)
    embed.add_field(name="Dans positions", value=str(uid in positions), inline=True)
    embed.add_field(name="Dans inventaires", value=str(uid in inventaires), inline=True)
    embed.add_field(name="Dans elimines", value=str(uid in elimines), inline=True)
    embed.add_field(name="est_inscrit()", value=str(est_inscrit(uid)), inline=True)
    
    # Données si elles existent
    if uid in joueurs:
        stats = joueurs[uid]
        embed.add_field(name="Données joueur", 
                       value=f"Or: {stats.get('or', 'N/A')}, Étoiles: {stats.get('etoiles', 'N/A')}", 
                       inline=False)
    
    if uid in positions:
        embed.add_field(name="Position", value=positions[uid], inline=True)
    
    await ctx.send(embed=embed)


@bot.command()
@is_owner()
async def nettoyer_elimines(ctx):
    """Nettoie complètement tous les joueurs éliminés de toutes les structures de données"""
    nettoyés = 0
    
    # Parcourir tous les éliminés et les nettoyer
    for uid in list(elimines):
        # Supprimer de joueurs (si encore présent)
        if uid in joueurs:
            del joueurs[uid]
            nettoyés += 1
        
        # Supprimer de positions
        if uid in positions:
            del positions[uid]
        
        # Supprimer de inventaires
        if uid in inventaires:
            del inventaires[uid]
        
        # Supprimer des achats uniques
        if uid in achats_uniques:
            del achats_uniques[uid]
        
        # Supprimer des déplacements
        if str(uid) in derniers_deplacements:
            del derniers_deplacements[str(uid)]
        
        # Supprimer des réserves Adam
        if uid in joueurs_adam_reserves:
            del joueurs_adam_reserves[uid]
        
        # Supprimer des commandes exclusives
        if str(uid) in commandes_uniques_globales.get("exclusives_joueurs", {}):
            del commandes_uniques_globales["exclusives_joueurs"][str(uid)]
    
    save_data()
    await ctx.send(f"🧹 Nettoyage terminé ! {nettoyés} joueurs éliminés supprimés de toutes les structures.")


@bot.command()
async def joueurs_liste(ctx):
    """Version corrigée de la liste des joueurs qui filtre les éliminés"""
    if not joueurs:
        await ctx.send("❌ Aucun joueur inscrit.")
        return

    msg = "📜 **Liste des joueurs inscrits :**\n"
    for uid, stats in joueurs.items():
        # Vérifier explicitement que le joueur n'est pas éliminé
        if uid in elimines:
            continue  # Ignorer les joueurs éliminés
            
        try:
            user = await bot.fetch_user(uid)
            pseudo = user.display_name
        except:
            pseudo = f"ID {uid}"
            
        zone = positions.get(uid, "❓ Inconnue")
        statuts = stats.get("statuts", [])
        badge = f" [{' ,'.join(statuts)}]" if statuts else ""
        msg += f"- {pseudo}{badge} → ⭐{stats['etoiles']} | 💰{stats['or']} | 📍 {zone}\n"

    if len([uid for uid in joueurs.keys() if uid not in elimines]) == 0:
        await ctx.send("❌ Aucun joueur actif (tous éliminés).")
    else:
        await ctx.send(msg)


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


@bot.command()
async def ping(ctx):
    await ctx.send("Vous perdez 30 or")

# --- CONFIGURATION DE LA VÉRIFICATION AUTOMATIQUE ---
URL = "https://discordbot-s7ie.onrender.com"

import time
time.sleep(10)
keep_alive()
bot.run(TOKEN)