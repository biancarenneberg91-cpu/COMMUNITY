# ═══════════════════════════════════════════════════════════════
#  NEXUS — Discord Bot
#  Arbeitet zusammen mit api.py (Dashboard) über data.json /
#  brain.json / announce_queue.json
# ═══════════════════════════════════════════════════════════════
import discord
from discord.ext import commands, tasks
import json, os, random, datetime, asyncio

# ── Konfiguration ────────────────────────────────────────────────
TOKEN      = os.environ.get("DISCORD_TOKEN", "")
PREFIX     = os.environ.get("BOT_PREFIX", "!")
DATA_FILE  = "data.json"
BRAIN_FILE = "brain.json"
QUEUE_FILE = "announce_queue.json"

# ── Intents ──────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ═══════════════════════════════════════════════════════════════
#  HELPERS — JSON I/O
# ═══════════════════════════════════════════════════════════════
def lade(pfad, default=None):
    if default is None:
        default = {}
    if not os.path.exists(pfad):
        return default
    with open(pfad, "r", encoding="utf-8") as f:
        return json.load(f)

def speichere(pfad, data):
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def xp_fuer_level(level):
    return 100 * (level ** 2) + 100 * level

def get_level(xp):
    level = 0
    while xp >= xp_fuer_level(level + 1):
        level += 1
    return level

# ═══════════════════════════════════════════════════════════════
#  EVENTS
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    print(f"🤖 NEXUS ist online als {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Slash-Commands synchronisiert")
    except Exception as e:
        print(f"⚠️  Slash-Command-Sync fehlgeschlagen: {e}")

    # Boot-Zähler erhöhen
    daten = lade(DATA_FILE)
    daten["boot_count"] = daten.get("boot_count", 0) + 1
    speichere(DATA_FILE, daten)

    # Hintergrundaufgaben starten
    check_announce_queue.start()
    check_giveaways.start()

@bot.event
async def on_member_join(member):
    daten = lade(DATA_FILE)
    if daten.get("maintenance"):
        return

    kanal_id = daten.get("welcome_channel")
    if not kanal_id:
        return

    kanal = bot.get_channel(int(kanal_id))
    if not kanal:
        return

    # Benutzerdefinierte Willkommensnachricht oder Standard
    nachricht = daten.get("welcome_message", "")
    if not nachricht:
        nachricht = f"Willkommen auf dem Server, {member.mention}! 🎉"
    else:
        nachricht = nachricht.replace("{user}", member.mention).replace("{name}", member.display_name)

    if daten.get("show_member_count", True):
        nachricht += f"\nIhr seid jetzt **{member.guild.member_count}** Mitglieder!"

    await kanal.send(nachricht)

    # Auto-Rollen vergeben
    for role_id in daten.get("auto_roles", []):
        role = member.guild.get_role(int(role_id))
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    daten = lade(DATA_FILE)
    if daten.get("maintenance"):
        await bot.process_commands(message)
        return

    # ── XP-System ────────────────────────────────────────────────
    uid = str(message.author.id)
    xp_cooldowns = daten.setdefault("xp_cooldowns", {})
    jetzt = datetime.datetime.utcnow().timestamp()
    cooldown = daten.get("xp_cooldown_secs", 60)

    if jetzt - xp_cooldowns.get(uid, 0) >= cooldown:
        xp_min = daten.get("xp_min", 10)
        xp_max = daten.get("xp_max", 25)
        gewinn = random.randint(xp_min, xp_max)

        daten.setdefault("xp", {}).setdefault(uid, 0)
        alter_level = get_level(daten["xp"][uid])
        daten["xp"][uid] += gewinn
        neuer_level = get_level(daten["xp"][uid])
        daten.setdefault("levels", {})[uid] = neuer_level
        xp_cooldowns[uid] = jetzt

        # Level-Up-Nachricht
        if neuer_level > alter_level:
            level_kanal_id = daten.get("level_channel")
            ziel = bot.get_channel(int(level_kanal_id)) if level_kanal_id else message.channel
            if ziel:
                await ziel.send(
                    f"🎉 {message.author.mention} hat **Level {neuer_level}** erreicht!"
                )

            # Level-Rollen vergeben
            level_rollen = daten.get("level_rollen", {})
            for lvl_str, role_id in level_rollen.items():
                if neuer_level >= int(lvl_str):
                    role = message.guild.get_role(int(role_id))
                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role)
                        except discord.Forbidden:
                            pass

        speichere(DATA_FILE, daten)

    await bot.process_commands(message)

# ═══════════════════════════════════════════════════════════════
#  SLASH-COMMANDS
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="rang", description="Zeigt deinen aktuellen Rang und XP an")
async def rang(interaction: discord.Interaction):
    daten = lade(DATA_FILE)
    uid   = str(interaction.user.id)
    xp    = daten.get("xp", {}).get(uid, 0)
    level = get_level(xp)
    aktuell = xp - xp_fuer_level(level)
    needed  = xp_fuer_level(level + 1) - xp_fuer_level(level)
    prozent = round(aktuell / needed * 100) if needed > 0 else 0

    embed = discord.Embed(
        title=f"📊 Rang von {interaction.user.display_name}",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Level", value=str(level), inline=True)
    embed.add_field(name="XP", value=f"{xp:,}", inline=True)
    embed.add_field(name="Fortschritt", value=f"{prozent}%", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rangliste", description="Zeigt die Top-10 der XP-Rangliste")
async def rangliste(interaction: discord.Interaction):
    daten = lade(DATA_FILE)
    xp_data = daten.get("xp", {})
    sortiert = sorted(xp_data.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(title="🏆 XP-Rangliste", color=discord.Color.gold())
    for i, (uid, xp) in enumerate(sortiert, 1):
        level = get_level(xp)
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        embed.add_field(
            name=f"{i}. {name}",
            value=f"Level {level} • {xp:,} XP",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="Zeigt die Bot-Latenz an")
async def ping(interaction: discord.Interaction):
    latenz = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Latenz: **{latenz}ms**")

@bot.tree.command(name="info", description="Informationen über NEXUS")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 NEXUS Bot",
        description="Community-Bot mit XP-System, Giveaways, Moderation und Dashboard.",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Prefix", value=PREFIX, inline=True)
    embed.add_field(name="Server", value=str(interaction.guild.member_count) + " Mitglieder", inline=True)
    embed.set_footer(text="NEXUS Community Bot")
    await interaction.response.send_message(embed=embed)

# ── Moderation ───────────────────────────────────────────────────
@bot.tree.command(name="warn", description="Verwarnt ein Mitglied")
@discord.app_commands.describe(mitglied="Das zu verwarnende Mitglied", grund="Grund der Verwarnung")
@discord.app_commands.default_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, mitglied: discord.Member, grund: str = "Kein Grund angegeben"):
    daten = lade(DATA_FILE)
    uid   = str(mitglied.id)
    daten.setdefault("warnings", {}).setdefault(uid, [])
    daten["warnings"][uid].append({
        "grund": grund,
        "datum": str(datetime.datetime.utcnow()),
        "mod": str(interaction.user)
    })
    speichere(DATA_FILE, daten)
    anzahl = len(daten["warnings"][uid])
    await interaction.response.send_message(
        f"⚠️ {mitglied.mention} wurde verwarnt. Grund: **{grund}** (Verwarnung #{anzahl})"
    )

@bot.tree.command(name="verwarnungen", description="Zeigt die Verwarnungen eines Mitglieds")
@discord.app_commands.describe(mitglied="Das Mitglied")
@discord.app_commands.default_permissions(moderate_members=True)
async def verwarnungen(interaction: discord.Interaction, mitglied: discord.Member):
    daten = lade(DATA_FILE)
    warns = daten.get("warnings", {}).get(str(mitglied.id), [])
    if not warns:
        await interaction.response.send_message(f"✅ {mitglied.mention} hat keine Verwarnungen.")
        return
    embed = discord.Embed(title=f"⚠️ Verwarnungen: {mitglied.display_name}", color=discord.Color.orange())
    for i, w in enumerate(warns[-5:], 1):
        embed.add_field(name=f"#{i} — {w.get('datum','')[:10]}", value=w.get("grund", "?"), inline=False)
    embed.set_footer(text=f"Gesamt: {len(warns)} Verwarnung(en)")
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════════
#  HINTERGRUNDAUFGABEN
# ═══════════════════════════════════════════════════════════════
@tasks.loop(seconds=10)
async def check_announce_queue():
    """Liest announce_queue.json und sendet ausstehende Nachrichten."""
    queue = lade(QUEUE_FILE, {"messages": []})
    if not queue["messages"]:
        return

    daten = lade(DATA_FILE)
    kanal_id = daten.get("welcome_channel") or daten.get("announce_channel")
    if not kanal_id:
        return

    kanal = bot.get_channel(int(kanal_id))
    if not kanal:
        return

    farben = {"info": discord.Color.blurple(), "warn": discord.Color.orange(), "error": discord.Color.red()}
    for msg in queue["messages"]:
        embed = discord.Embed(
            description=msg.get("nachricht", ""),
            color=farben.get(msg.get("typ", "info"), discord.Color.blurple()),
            timestamp=datetime.datetime.utcnow()
        )
        try:
            await kanal.send(embed=embed)
        except discord.Forbidden:
            pass

    queue["messages"] = []
    speichere(QUEUE_FILE, queue)

@tasks.loop(minutes=1)
async def check_giveaways():
    """Beendet abgelaufene Giveaways und zieht Gewinner."""
    daten = lade(DATA_FILE)
    giveaways = daten.get("giveaways", {})
    jetzt = datetime.datetime.utcnow()
    geaendert = False

    for msg_id, gw in giveaways.items():
        if not gw.get("aktiv"):
            continue
        try:
            ende = datetime.datetime.fromisoformat(gw["ende"])
        except (KeyError, ValueError):
            continue

        if jetzt >= ende:
            gw["aktiv"] = False
            geaendert = True
            kanal_id = gw.get("kanal_id")
            if kanal_id:
                kanal = bot.get_channel(int(kanal_id))
                if kanal:
                    try:
                        await kanal.send(
                            f"🎉 Das Giveaway für **{gw.get('preis', '?')}** ist beendet!"
                        )
                    except discord.Forbidden:
                        pass

    if geaendert:
        speichere(DATA_FILE, daten)

# ═══════════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN ist nicht gesetzt! Bot kann nicht starten.")
        raise SystemExit(1)
    print("🤖 NEXUS Bot startet...")
    bot.run(TOKEN)
