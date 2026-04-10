import discord
import requests
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord.ext import commands, tasks
from datetime import datetime, timezone

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

def create_card(list_id, name):
    res = requests.post(
        f"{BASE_URL}/cards",
        params={**AUTH, "idList": list_id, "name": name}
    )
    return res.json()

def get_board_members():
    res = requests.get(f"{BASE_URL}/boards/{BOARD_ID}/members", params=AUTH)
    if res.ok:
        return res.json()
    return []

def get_all_cards():
    res = requests.get(f"{BASE_URL}/boards/{BOARD_ID}/cards", params={**AUTH, "members": "true"})
    if res.ok:
        return res.json()
    return []

def find_card(card_name, cards=None):
    """Find a card by name across all lists."""
    if cards is None:
        cards = get_all_cards()
    for card in cards:
        if card["name"].lower() == card_name.lower():
            return card
    return None

def get_list_name_by_id(list_id):
    res = requests.get(f"{BASE_URL}/lists/{list_id}", params=AUTH)
    if res.ok:
        return res.json().get("name", "Unknown")
    return "Unknown"

def get_board_actions():
    """Get recent actions (card moves and card creates) from the board."""
    params = {**AUTH, "filter": "updateCard:idList,createCard", "limit": 20}
    res = requests.get(f"{BASE_URL}/boards/{BOARD_ID}/actions", params=params)
    if res.ok:
        return res.json()
    return []

# Track last checked time to avoid duplicate notifications
last_check_time = None

# === CHANNEL CHECK ===
async def check_channel(ctx):
    if TRELLO_CHANNEL_ID != 0 and ctx.channel.id != TRELLO_CHANNEL_ID:
        await ctx.message.delete()
        return False
    return True

# === DISCORD EVENTS ===

@tasks.loop(seconds=30)
async def check_trello_moves():
    """Poll Trello every 30 seconds for card movements and post in Discord."""
    global last_check_time
    if TRELLO_CHANNEL_ID == 0:
        return

    channel = bot.get_channel(TRELLO_CHANNEL_ID)
    if not channel:
        return

    try:
        actions = get_board_actions()
        now = datetime.now(timezone.utc)

        for action in actions:
            action_date = datetime.fromisoformat(action["date"].replace("Z", "+00:00"))

            if last_check_time and action_date <= last_check_time:
                continue

            action_type = action["type"]
            card_name = action["data"]["card"]["name"]
            member = action["memberCreator"]["fullName"]

            if action_type == "createCard":
                list_name = action["data"]["list"]["name"]
                await channel.send(
                    f"🆕 **{member}** created **'{card_name}'**\n"
                    f"📋 List: **{list_name}**"
                )
            elif action_type == "updateCard":
                list_before = action["data"]["listBefore"]["name"]
                list_after = action["data"]["listAfter"]["name"]
                await channel.send(
                    f"📦 **{member}** moved **'{card_name}'**\n"
                    f"➡️ **{list_before}** → **{list_after}**"
                )

        last_check_time = now
    except Exception as e:
        print(f"⚠️ Error checking Trello moves: {e}")

@check_trello_moves.before_loop
async def before_check():
    await bot.wait_until_ready()
    global last_check_time
    last_check_time = datetime.now(timezone.utc)

@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    if not check_trello_moves.is_running():
        check_trello_moves.start()
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
            move_card(card["id"], lists["Testing Done"])
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

@bot.command(name="add")
async def add_card(ctx, *, args: str):
    """!add <list name> | <card name> — Create a new card"""
    if not await check_channel(ctx):
        return

    if "|" not in args:
        await ctx.send("❌ Perdor: `!add <emri i listes> | <emri i kartes>`")
        return

    list_name, card_name = [x.strip() for x in args.split("|", 1)]
    lists = get_lists()

    # Find matching list (case insensitive)
    matched_list = None
    for name, lid in lists.items():
        if name.lower() == list_name.lower():
            matched_list = (name, lid)
            break

    if not matched_list:
        available = ", ".join(lists.keys())
        await ctx.send(f"❌ Lista **'{list_name}'** nuk u gjet.\n📋 Listat: {available}")
        return

    card = create_card(matched_list[1], card_name)
    await ctx.send(f"✅ Karta **'{card_name}'** u krijua te **{matched_list[0]}**!")

@bot.command(name="move")
async def move_card_cmd(ctx, *, args: str):
    """!move <card name> | <target list> — Move card to any list"""
    if not await check_channel(ctx):
        return

    if "|" not in args:
        await ctx.send("❌ Perdor: `!move <emri i kartes> | <emri i listes>`")
        return

    card_name, target_list = [x.strip() for x in args.split("|", 1)]
    lists = get_lists()

    # Find target list
    matched_list = None
    for name, lid in lists.items():
        if name.lower() == target_list.lower():
            matched_list = (name, lid)
            break

    if not matched_list:
        available = ", ".join(lists.keys())
        await ctx.send(f"❌ Lista **'{target_list}'** nuk u gjet.\n📋 Listat: {available}")
        return

    # Find card
    card = find_card(card_name)
    if not card:
        await ctx.send(f"❌ Karta **'{card_name}'** nuk u gjet.")
        return

    move_card(card["id"], matched_list[1])
    add_comment(card["id"], f"Moved to {matched_list[0]}")
    await ctx.send(f"📦 **'{card_name}'** u zhvendos te **{matched_list[0]}**!")

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

@bot.command(name="members")
async def show_members(ctx):
    """!members — Show who is assigned to which cards"""
    if not await check_channel(ctx):
        return

    cards = get_all_cards()
    members = get_board_members()
    member_map = {m["id"]: m["fullName"] for m in members}
    lists = get_lists()
    list_id_to_name = {v: k for k, v in lists.items()}

    message = "👥 **Kartat dhe anetaret:**\n\n"
    has_assignments = False

    for card in cards:
        if card.get("idMembers"):
            has_assignments = True
            assigned = ", ".join(member_map.get(mid, "Unknown") for mid in card["idMembers"])
            list_name = list_id_to_name.get(card["idList"], "Unknown")
            message += f"• **{card['name']}** ({list_name}) — {assigned}\n"

    if not has_assignments:
        message += "Asnje karte nuk ka anetar te caktuar."

    await ctx.send(message)

@bot.command(name="mytickets")
async def my_tickets(ctx):
    """!mytickets — Show your assigned cards"""
    if not await check_channel(ctx):
        return

    cards = get_all_cards()
    members = get_board_members()
    lists = get_lists()
    list_id_to_name = {v: k for k, v in lists.items()}

    # Match Discord username to Trello member
    discord_name = ctx.author.display_name.lower()
    trello_member_id = None
    for m in members:
        if m["fullName"].lower() == discord_name or m["username"].lower() == discord_name:
            trello_member_id = m["id"]
            break

    if not trello_member_id:
        await ctx.send(f"❌ Nuk gjeta llogarine tende ne Trello. (Discord name: {ctx.author.display_name})\nSignohu qe emri ne Discord dhe Trello te jete i njejte.")
        return

    my_cards = [c for c in cards if trello_member_id in c.get("idMembers", [])]

    if not my_cards:
        await ctx.send("📭 Nuk ke asnje karte te caktuar.")
        return

    message = f"🎯 **Kartat e tua ({ctx.author.display_name}):**\n\n"
    for card in my_cards:
        list_name = list_id_to_name.get(card["idList"], "Unknown")
        message += f"• **{card['name']}** — {list_name}\n"

    await ctx.send(message)

@bot.command(name="summary")
async def show_summary(ctx):
    """!summary — Show a quick summary of the board"""
    if not await check_channel(ctx):
        return

    lists = get_lists()
    message = "📊 **Board Summary:**\n\n"
    total = 0

    for list_name, list_id in lists.items():
        cards = get_cards_in_list(list_id)
        count = len(cards)
        total += count
        bar = "█" * count + "░" * (10 - min(count, 10))
        message += f"**{list_name}**: {count} {bar}\n"

    message += f"\n**Total: {total} karta**"
    await ctx.send(message)

@bot.command(name="help_trello")
async def help_trello(ctx):
    """!help_trello — Shfaq te gjitha komandat"""
    if not await check_channel(ctx):
        return

    await ctx.send("""
📖 **Komandat e disponueshme:**

**Menaxhimi i kartave:**
`!add <lista> | <emri>` — Krijo karte te re
`!move <emri i kartes> | <lista>` — Zhvendos karte ne cfardo liste
`!ready <emri i kartes>` — Zhvendos nga **In Progress** → **Testing**
`!tested <emri i kartes>` — Zhvendos nga **Testing** → **Testing Done**
`!return <emri i kartes> | <arsyeja>` — Kthe nga **Testing** → **In Progress**

**Informatat:**
`!board` — Shfaq te gjitha kartat
`!summary` — Permbledhje e boardit
`!members` — Shfaq kush eshte assign ne karta
`!mytickets` — Shfaq kartat e tua
`!help_trello` — Shfaq komandat

🔔 Boti poston automatikisht kur krijohet ose levizet nje karte ne Trello.
    """)

# === RUN ===
bot.run(DISCORD_BOT_TOKEN)