import os
import time
import logging
import sqlite3
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =====================================================================
# CONFIGURATION & CONSTANTS
# =====================================================================
TOKEN = "8490224778:AAHBykM6v_R9cI4ctWPpfbr5RxHN_S4ZfnE"
ADMIN_ID = 7812499632
DB_FILE = "players.db"
STARTING_COINS = 1000
CLAIM_AMOUNT = 500       
COOLDOWN_HOURS = 24

# Setup system logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# =====================================================================
# FLASK WEB SERVER ENGINE (RENDER COMPATIBILITY BIND)
# =====================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Dice Engine Active and Running Live", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


# =====================================================================
# DATABASE ENGINE CORE FUNCTIONS
# =====================================================================
def init_db():
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 0,
            last_claim REAL DEFAULT 0
        )
    ''')
    connection.commit()
    connection.close()

def get_player_data(user_id: int):
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute("SELECT coins, last_claim FROM players WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute(
            "INSERT INTO players (user_id, coins, last_claim) VALUES (?, ?, 0)", 
            (user_id, STARTING_COINS)
        )
        connection.commit()
        player_coins = STARTING_COINS
        player_last_claim = 0.0
    else:
        player_coins = row[0]
        player_last_claim = row[1]
        
    connection.close()
    return player_coins, player_last_claim

def get_balance(user_id: int) -> int:
    coins, _ = get_player_data(user_id)
    return coins

def update_balance(user_id: int, amount_change: int):
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE players SET coins = coins + ? WHERE user_id = ?", 
        (amount_change, user_id)
    )
    connection.commit()
    connection.close()

def set_claim_timestamp(user_id: int, timestamp: float):
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE players SET last_claim = ? WHERE user_id = ?", 
        (timestamp, user_id)
    )
    connection.commit()
    connection.close()

def get_top_players():
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute("SELECT user_id, coins FROM players ORDER BY coins DESC LIMIT 10")
    top_users = cursor.fetchall()
    connection.close()
    return top_users


# =====================================================================
# PLAYER WALLET COMMAND HANDLERS
# =====================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🎲 **WELCOME TO THE DICE BETTING GAME** 🎲\n\n"
        "📖 **HOW TO PLAY**\n"
        "1. Wait for the game administrator to open a betting round using `/setbet`.\n"
        "2. Place your prediction on what the total sum of **two rolled dice** will be.\n"
        "3. The admin will run the `/roll` command to spin the dice live!\n\n"
        "💰 **MULTIPLIERS & PAYOUTS**\n"
        "• 🟢 `/under <amount>` — Sum is **1 to 6**. (Pays **2x**)\n"
        "• 🔵 `/over <amount>` — Sum is **8 to 12**. (Pays **2x**)\n"
        "• 🟡 `/equal <amount>` — Sum is **exactly 7**. (🔥 Pays **4x**)\n"
        "• 🎯 `/exact <number> <amount>` — Guess the **exact target sum** from 2 to 12. (💎 **Pays 7x!**)\n\n"
        "💳 **PLAYER WALLET COMMANDS**\n"
        "• `/balance` — Check your current coin count.\n"
        f"• `/claim` — Collect **{CLAIM_AMOUNT} free coins** every 24 hours.\n"
        "• `/leaderboard` — View the top 10 richest players.\n"
        "• `/donate <amount>` — Send coins to another player by **replying** to them."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins = get_balance(user_id)
    await update.message.reply_text(
        f"💰 Wallet Balance: **{coins} coins**", 
        parse_mode="Markdown"
    )

async def claim_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins, last_claim = get_player_data(user_id)
    
    current_time = time.time()
    cooldown_seconds = COOLDOWN_HOURS * 3600
    
    if current_time - last_claim < cooldown_seconds:
        time_left = int(cooldown_seconds - (current_time - last_claim))
        hours = time_left // 3600
        minutes = (time_left % 3600) // 60
        await update.message.reply_text(
            f"⏳ Cooldown Active! Please wait **{hours}h {minutes}m** to claim your next reward."
        )
        return

    update_balance(user_id, CLAIM_AMOUNT)
    set_claim_timestamp(user_id, current_time)
    await update.message.reply_text(
        f"🎁 **Daily Reward Claimed Successfully!**\nAdded `+{CLAIM_AMOUNT}` coins to your wallet."
    )

async def donate_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Error: You must reply to the user message of the person you want to donate to.")
        return

    recipient_user = update.message.reply_to_message.from_user
    if sender_id == recipient_user.id or recipient_user.is_bot:
        await update.message.reply_text("❌ Error: You cannot transfer coins to yourself or to a bot system.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage Format: `/donate <amount>`")
        return

    try:
        amount = int(context.args[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Error: Please enter a valid positive number for the donation.")
        return

    sender_coins = get_balance(sender_id)
    if amount > sender_coins:
        await update.message.reply_text("❌ Transaction Declined: Insufficient wallet balance.")
        return

    tax_charge = round(amount * 0.11)
    if tax_charge < 1:
        tax_charge = 1
    received_amount = amount - tax_charge

    get_player_data(recipient_user.id) 
    update_balance(sender_id, -amount)
    update_balance(recipient_user.id, received_amount)

    await update.message.reply_text(
        f"🤝 **Donation Successful!**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 Sender: **{update.effective_user.first_name}**\n"
        f"📥 Recipient: **{recipient_user.first_name}**\n"
        f"💰 Gross Amount: **{amount} coins**\n"
        f"⚡ Platform Tax (11%): **{tax_charge} coins**\n"
        f"🎁 Net Delivered: **{received_amount} coins**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = get_top_players()

    if not top_users:
        await update.message.reply_text("📋 The ranking leaderboard is currently empty.")
        return

    leaderboard_text = "🏆 **TOP 10 RICHEST PLAYERS** 🏆\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for position, (u_id, coins) in enumerate(top_users, start=1):
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, u_id)
            display_name = member.user.first_name
        except Exception:
            display_name = f"User_ID({u_id})"
        leaderboard_text += f"#{position} **{display_name}** — `{coins}` coins\n"
        
    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")


# =====================================================================
# INDEPENDENT GAME COMMAND HANDLERS (EXPANDED TO FULL LENGTH)
# =====================================================================
async def set_bet_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Access Denied: Only the system administrator can perform this command.")
        return

    if context.chat_data.get('betting_open', False):
        await update.message.reply_text("⚠️ System Status: A betting window is already open. Close it via `/roll` first.")
        return

    context.chat_data['betting_open'] = True
    context.chat_data['active_bets'] = {}

    await update.message.reply_text(
        "🎲 **A NEW ROUND OF DICE BETTING HAS BEGUN!** 🎲\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 `/under <amount>` (Sums 1 to 6 — Pays **2x**)\n"
        "🟡 `/equal <amount>` (Sum exactly 7 — 🔥 Pays **4x!**)\n"
        "🔵 `/over <amount>` (Sums 8 to 12 — Pays **2x**)\n"
        "🎯 `/exact <target> <amount>` (Guess exact sum — 💎 **Pays 7x!**)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 *Place your predictions now! Admin will spin the dice shortly!*",
        parse_mode="Markdown"
    )

async def bet_under(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.chat_data.get('betting_open', False):
        await update.message.reply_text("🔒 Request Denied: The betting window is currently closed.")
        return

    if not context.args:
        await update.message.reply_text("❌ Correct Usage: `/under <amount>`")
        return

    try:
        amount = int(context.args[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Error: Bet amount must be a valid positive integer.")
        return

    player_coins = get_balance(user_id)
    if amount > player_coins:
        await update.message.reply_text("❌ Bet Rejected: You don't have enough coins in your balance.")
        return

    if 'active_bets' not in context.chat_data:
        context.chat_data['active_bets'] = {}

    context.chat_data['active_bets'][user_id] = {
        'name': update.effective_user.first_name,
        'bet_type': "under",
        'target_num': None,
        'amount': amount
    }
    await update.message.reply_text(f"🪙 UNDER bet successfully recorded for **{update.effective_user.first_name}**!")

async def bet_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.chat_data.get('betting_open', False):
        await update.message.reply_text("🔒 Request Denied: The betting window is currently closed.")
        return

    if not context.args:
        await update.message.reply_text("❌ Correct Usage: `/over <amount>`")
        return

    try:
        amount = int(context.args[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Error: Bet amount must be a valid positive integer.")
        return

    player_coins = get_balance(user_id)
    if amount > player_coins:
        await update.message.reply_text("❌ Bet Rejected: You don't have enough coins in your balance.")
        return

    if 'active_bets' not in context.chat_data:
        context.chat_data['active_bets'] = {}

    context.chat_data['active_bets'][user_id] = {
        'name': update.effective_user.first_name,
        'bet_type': "over",
        'target_num': None,
        'amount': amount
    }
    await update.message.reply_text(f"🪙 OVER bet successfully recorded for **{update.effective_user.first_name}**!")

async def bet_equal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.chat_data.get('betting_open', False):
        await update.message.reply_text("🔒 Request Denied: The betting window is currently closed.")
        return

    if not context.args:
        await update.message.reply_text("❌ Correct Usage: `/equal <amount>`")
        return

    try:
        amount = int(context.args[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Error: Bet amount must be a valid positive integer.")
        return

    player_coins = get_balance(user_id)
    if amount > player_coins:
        await update.message.reply_text("❌ Bet Rejected: You don't have enough coins in your balance.")
        return

    if 'active_bets' not in context.chat_data:
        context.chat_data['active_bets'] = {}

    context.chat_data['active_bets'][user_id] = {
        'name': update.effective_user.first_name,
        'bet_type': "equal",
        'target_num': None,
        'amount': amount
    }
    await update.message.reply_text(f"🪙 EQUAL bet successfully recorded for **{update.effective_user.first_name}**!")

async def bet_exact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.chat_data.get('betting_open', False):
        await update.message.reply_text("🔒 Request Denied: The betting window is currently closed.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Correct Usage: `/exact <2-12> <amount>`")
        return

    try:
        target_number = int(context.args[0])
        amount = int(context.args[1])
        if target_number < 2 or target_number > 12 or amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Error: Target number must be 2-12 and amount must be positive.")
        return

    player_coins = get_balance(user_id)
    if amount > player_coins:
        await update.message.reply_text("❌ Bet Rejected: You don't have enough coins in your balance.")
        return

    if 'active_bets' not in context.chat_data:
        context.chat_data['active_bets'] = {}

    context.chat_data['active_bets'][user_id] = {
        'name': update.effective_user.first_name,
        'bet_type': "exact",
        'target_num': target_number,
        'amount': amount
    }
    await update.message.reply_text(f"🎯 EXACT target bet ({target_number}) successfully recorded for **{update.effective_user.first_name}**!")


# =====================================================================
# SYSTEM CORE ROLL ENGINE & SETTLEMENT LOGIC
# =====================================================================
async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    active_bets = context.chat_data.get('active_bets', {})
    if not active_bets:
        await update.message.reply_text("❌ Cannot Roll: There are no active bets registered in this round.")
        return

    context.chat_data['betting_open'] = False
    await update.message.reply_text("🎲 **The dice are rolling live... Best of luck!**")

    dice_1 = await context.bot.send_dice(update.effective_chat.id)
    dice_2 = await context.bot.send_dice(update.effective_chat.id)
    
    await asyncio.sleep(3)

    total_sum = dice_1.dice.value + dice_2.dice.value

    if total_sum <= 6:
        result_bracket = "under"
        bracket_title = "UNDER (1-6)"
    elif total_sum == 7:
        result_bracket = "equal"
        bracket_title = "EQUAL (7)"
    else:
        result_bracket = "over"
        bracket_title = "OVER (8-12)"

    results_header = (
        f"🎲 **DICE ROLL COMPLETE** 🎲\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎲 Dice One: `{dice_1.dice.value}`\n"
        f"🎲 Dice Two: `{dice_2.dice.value}`\n"
        f"🎯 Combined Total: **{total_sum}**\n"
        f"📊 Winning Category: **{bracket_title}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    winners_list = []
    losers_list = []

    for user_id, bet_info in active_bets.items():
        is_winner = False
        payout_multiplier = 1

        if bet_info['bet_type'] == "exact":
            if bet_info['target_num'] == total_sum:
                is_winner = True
                payout_multiplier = 7
        else:
            if bet_info['bet_type'] == result_bracket:
                is_winner = True
                if bet_info['bet_type'] == "equal":
                    payout_multiplier = 4
                else:
                    payout_multiplier = 1

        if is_winner == True:
            net_profit = bet_info['amount'] * payout_multiplier
            update_balance(user_id, net_profit)
            winners_list.append(f"🟢 **{bet_info['name']}**: +{net_profit} coins")
        else:
            update_balance(user_id, -bet_info['amount'])
            losers_list.append(f"🔴 **{bet_info['name']}**: -{bet_info['amount']} coins")

    final_message = results_header + "🏆 **WINNERS:**\n"
    if winners_list:
        final_message += "\n".join(winners_list)
    else:
        final_message += "None"

    final_message += "\n\n💀 **LOSERS:**\n"
    if losers_list:
        final_message += "\n".join(losers_list)
    else:
        final_message += "None"

    await context.bot.send_message(update.effective_chat.id, final_message, parse_mode="Markdown")
    context.chat_data['active_bets'].clear()


# =====================================================================
# ADMINISTRATIVE COIN MANAGEMENT COMMAND HANDLERS
# =====================================================================
async def add_coins_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Access Denied: Only the system administrator can perform this command.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: `/addcoins <amount>` (as a reply to a user)")
        return

    try:
        amount_to_add = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number.")
        return

    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        target_name = update.message.reply_to_message.from_user.first_name
    else:
        target_id = user_id
        target_name = "yourself"

    get_player_data(target_id)
    update_balance(target_id, amount_to_add)
    await update.message.reply_text(f"🛠️ Admin Action: Credited **+{amount_to_add} coins** to **{target_name}**.")


# =====================================================================
# SYSTEM SETUP RUNTIME INITIALIZER
# =====================================================================
async def run_bot_app():
    init_db()
    
    # Run the web port listener pipeline to stop Render from failing builds
    threading.Thread(target=run_flask_server, daemon=True).start()
    
    # Initialize the engine
    application = Application.builder().token(TOKEN).build()
    
    # Command registration bindings
    application.add_handler(CommandHandler("setbet", set_bet_round))
    application.add_handler(CommandHandler("roll", roll_dice))
    application.add_handler(CommandHandler("addcoins", add_coins_admin))
    application.add_handler(CommandHandler("under", bet_under))
    application.add_handler(CommandHandler("over", bet_over))
    application.add_handler(CommandHandler("equal", bet_equal))
    application.add_handler(CommandHandler("exact", bet_exact))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("claim", claim_reward))
    application.add_handler(CommandHandler("donate", donate_coins))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("bal", check_balance))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    
    async with application:
        await application.initialize()
        await application.start()
        logging.info("Polling routine connected successfully.")
        await application.updater.start_polling()
        
        while True:
            await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(run_bot_app())
