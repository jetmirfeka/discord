import discord
import requests
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord.ext import commands

# === CONFIG ===
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_ID = os.getenv("BOARD_ID")
TRELLO_CHANNEL_ID = int(os.getenv("TRELLO_CHANNEL_ID", "0"))

BASE_URL = "https://api.trello.com/1"
AUTH = {"key": TRELLO_API_KEY, "token": TRELLO_TOKEN}

# === STATIC WEB SERVER (për Railway) ===
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Trello Bot is running!")
    def log_message(self, format, *args):
        pass  # Fsheh logs e serverit

def run_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

# Starto serverin në background
threading.Thread(target=run_server, daemon=True).start()

# === BOT SETUP ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# === TRELLO HELPERS ===

def get_lists():
    res = requests.get(f"{BASE_URL}/boards/{BOARD_ID}/lists", params=AUTH)
    return {lst["name"]: lst["id"] for lst in res.json()}

def get_cards_in_list(list_id):
    res = requests.get(f"{BASE_URL}/lists/{list_id}/cards", params=AUTH)
    return res.json()

def move_card(card_id, target_list_id):
    res = requests.put(
        f"{BASE_URL}/cards/{card_id}",
        params={**AUTH, "idList": target_list_id}
    )
    return res.json()

def add_comment(card_id, comment):
    requests.post(
        f"{BASE_URL}/cards/{card_id}/actions/comments",
        params={**AUTH, "text": comment}
    )

# === CHANNEL CHECK ===
async def check_channel(ctx):
    if TRELLO_CHANNEL_ID != 0 and ctx.channel.id != TRELLO_CHANNEL_ID:
        await ctx.message.delete()
        return False
    return True

# === DISCORD EVENTS ===

@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    if TRELLO_CHANNEL_ID != 0:
        try:
            channel = bot.get_channel(TRELLO_CHANNEL_ID)
            if channel:
                await channel.send("🤖 **Trello Bot është online dhe gati!**")
            else:
                print(f"⚠️ Channel {TRELLO_CHANNEL_ID} not found")
        except Exception as e:
            print(f"⚠️ Could not send startup message: {e}")

# === DISCORD COMMANDS ===

@bot.command(name="ready")
async def ready_to_test(ctx, *, card_name: str):
    """!ready <card name> — Move card to Testing"""
    if not await check_channel(ctx):
        return

    lists = get_lists()
    cards = get_cards_in_list(lists["In Progress"])

    for card in cards:
        if card["name"].lower() == card_name.lower():
            move_card(card["id"], lists["Testing"])
            add_comment(card["id"], "✅ Ready for testing.")
            await ctx.send(f"🧪 **'{card_name}'** u zhvendos te **Testing**!")
            return

    await ctx.send(f"❌ Karta **'{card_name}'** nuk u gjet te 'In Progress'.")

@bot.command(name="tested")
async def mark_tested(ctx, *, card_name: str):
    """!tested <card name> — Move card to Done"""
    if not await check_channel(ctx):
        return

    lists = get_lists()
    cards = get_cards_in_list(lists["Testing"])

    for card in cards:
        if card["name"].lower() == card_name.lower():
            move_card(card["id"], lists["Done"])
            add_comment(card["id"], "🎉 Testing passed.")
            await ctx.send(f"✅ **'{card_name}'** u zhvendos te **Done**!")
            return

    await ctx.send(f"❌ Karta **'{card_name}'** nuk u gjet te 'Testing'.")

@bot.command(name="return")
async def return_to_dev(ctx, *, args: str):
    """!return <card name> | <reason> — Move card back to In Progress"""
    if not await check_channel(ctx):
        return

    if "|" in args:
        card_name, reason = [x.strip() for x in args.split("|", 1)]
    else:
        card_name, reason = args.strip(), "No reason given"

    lists = get_lists()
    cards = get_cards_in_list(lists["Testing"])

    for card in cards:
        if card["name"].lower() == card_name.lower():
            move_card(card["id"], lists["In Progress"])
            add_comment(card["id"], f"🔁 Returned to dev. Reason: {reason}")
            await ctx.send(f"🔁 **'{card_name}'** u kthye te **In Progress**.\n📝 Arsyeja: {reason}")
            return

    await ctx.send(f"❌ Karta **'{card_name}'** nuk u gjet te 'Testing'.")

@bot.command(name="board")
async def show_board(ctx):
    """!board — Show all cards per list"""
    if not await check_channel(ctx):
        return

    lists = get_lists()
    message = "📋 **Trello Board Status**\n\n"

    for list_name, list_id in lists.items():
        cards = get_cards_in_list(list_id)
        card_names = [f"  • {c['name']}" for c in cards] or ["  • *(empty)*"]
        message += f"**{list_name}**\n" + "\n".join(card_names) + "\n\n"

    await ctx.send(message)

@bot.command(name="help_trello")
async def help_trello(ctx):
    """!help_trello — Shfaq të gjitha komandat"""
    if not await check_channel(ctx):
        return

    await ctx.send("""
📖 **Komandat e disponueshme:**

`!ready <emri i kartës>` — Zhvendos nga **In Progress** → **Testing**
`!tested <emri i kartës>` — Zhvendos nga **Testing** → **Done**
`!return <emri i kartës> | <arsyeja>` — Kthe nga **Testing** → **In Progress**
`!board` — Shfaq të gjitha kartat
`!help_trello` — Shfaq komandat
    """)

# === RUN ===
bot.run(DISCORD_BOT_TOKEN)