import asyncio
import logging
import sqlite3
import time
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Configuration
TOKEN = "8490224778:AAHBykM6v_R9cI4ctWPpfbr5RxHN_S4ZfnE"
ADMIN_ID = 7812499632
DB_FILE = "players.db"
STARTING_COINS = 1000
CLAIM_AMOUNT = 100
COOLDOWN_HOURS = 24

# Cloud Environmental Variables
PORT = int(os.environ.get("PORT", 8080))
# Dynamically extract application URL if provided by hosting provider envs
APP_URL = os.environ.get("APP_URL", "") 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# ==================== DATABASE FUNCTIONS ====================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 0,
            last_claim REAL DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_player_data(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT coins, last_claim FROM players WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute("INSERT INTO players (user_id, coins, last_claim) VALUES (?, ?, 0)", (user_id, STARTING_COINS))
        conn.commit()
        data = (STARTING_COINS, 0.0)
    else:
        data = (row[0], row[1])
        
    conn.close()
    return data

def get_balance(user_id: int) -> int:
    return get_player_data(user_id)[0]

def update_balance(user_id: int, amount_change: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (amount_change, user_id))
    conn.commit()
    conn.close()

def set_claim_timestamp(user_id: int, timestamp: float):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET last_claim = ? WHERE user_id = ?", (timestamp, user_id))
    conn.commit()
    conn.close()

def get_top_players():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, coins FROM players ORDER BY coins DESC LIMIT 10")
    top_users = cursor.fetchall()
    conn.close()
    return top_users

# ==================== NOTIFICATION JOB ====================

async def send_ready_notification(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.send_message(
            chat_id=job.chat_id,
            text=f"🔔 **Hey! Your daily reward is ready!**\nType `/claim` right now to collect your **{CLAIM_AMOUNT} coins**! 🎉",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Failed to send notification to user {job.chat_id}: {e}")

# ==================== BOT GAME LOGIC ====================

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
        "• `/claim` — Collect **100 free coins** every 24 hours.\n"
        "• `/leaderboard` — View the top 10 richest players.\n"
        "• `/donate <amount>` — Send coins to another player by **replying** to them."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def set_bet_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ **Access Denied:** Only the bot Administrator can open a betting round.")
        return

    if context.chat_data.get('betting_open', False):
        await update.message.reply_text("⚠️ **A betting round is already open!** Type `/roll` to finish it.")
        return

    context.chat_data['betting_open'] = True
    context.chat_data['active_bets'] = {}

    await update.message.reply_text(
        "🎲 **A NEW ROUND OF DICE BETTING HAS BEGUN!** 🎲\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 `/under <amount>` (Sums 1-6)\n"
        "🟡 `/equal <amount>` (Sum exactly 7 — **Pays 4x!**)\n"
        "🔵 `/over <amount>` (Sums 8-12)\n"
        "🎯 `/exact <target_number> <amount>` (**Pays 7x!**)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 *Admin will roll the dice shortly!*",
        parse_mode="Markdown"
    )

async def add_coins_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ **Access Denied.**")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: `/addcoins <amount>`")
        return

    try:
        amount_to_add = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number.")
        return

    target_id = update.message.reply_to_message.from_user.id if update.message.reply_to_message else user_id
    target_name = update.message.reply_to_message.from_user.first_name if update.message.reply_to_message else "yourself"

    get_balance(target_id)
    update_balance(target_id, amount_to_add)
    await update.message.reply_text(f"🛠️ Credited **+{amount_to_add} coins** to **{target_name}**.")

async def donate_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    sender_name = update.effective_user.first_name
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to the message of the person you want to donate to.")
        return

    recipient = update.message.reply_to_message.from_user
    if sender_id == recipient.id or recipient.is_bot:
        await update.message.reply_text("❌ Invalid recipient.")
        return

    try:
        amount = int(context.args[0])
        if amount <= 0: raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/donate <amount>`")
        return

    sender_balance = get_balance(sender_id)
    if amount > sender_balance:
        await update.message.reply_text("❌ Insufficient balance.")
        return

    tax_charge = max(1, round(amount * 0.11))
    received_amount = amount - tax_charge

    get_balance(recipient.id)
    update_balance(sender_id, -amount)             
    update_balance(recipient.id, received_amount)   

    await update.message.reply_text(
        f"🤝 **Donation Successful!**\n"
        f"📤 From: **{sender_name}** | 📥 To: **{recipient.first_name}**\n"
        f"💰 Sent: **{amount}** | ⚡ Tax (11%): **{tax_charge}** | 🎁 Received: **{received_amount}**",
        parse_mode="Markdown"
    )

async def claim_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    coins, last_claim = get_player_data(user_id)
    current_time = time.time()
    cooldown = COOLDOWN_HOURS * 3600
    
    if current_time - last_claim < cooldown:
        left = int(cooldown - (current_time - last_claim))
        await update.message.reply_text(f"⏳ Please wait **{left//3600}h {(left%3600)//60}m** to claim again.")
        return

    update_balance(user_id, CLAIM_AMOUNT)
    set_claim_timestamp(user_id, current_time)
    
    await update.message.reply_text(f"🎁 **Daily Reward Claimed!** (+{CLAIM_AMOUNT} coins)")
    
    for old_job in context.job_queue.get_jobs_by_name(f"notify_{user_id}"):
        old_job.schedule_removal()
    context.job_queue.run_once(send_ready_notification, when=cooldown, chat_id=chat_id, name=f"notify_{user_id}")

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💰 Balance: **{get_balance(update.effective_user.id)} coins**", parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_players = get_top_players()
    if not top_players:
        await update.message.reply_text("📋 Empty.")
        return

    text = "🏆 **TOP 10 PLAYERS** 🏆\n"
    for i, (u_id, coins) in enumerate(top_players, start=1):
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, u_id)
            name = m.user.first_name
        except Exception:
            name = f"User({u_id})"
        text += f"#{i} **{name}** — `{coins}` coins\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def place_bet(update: Update, context: ContextTypes.DEFAULT_TYPE, bet_type: str, target_num: int = None, amount: int = None):
    user_id = update.effective_user.id
    if not context.chat_data.get('betting_open', False):
        await update.message.reply_text("🔒 Betting is closed. Wait for `/setbet`.")
        return

    if amount > get_balance(user_id):
        await update.message.reply_text("❌ Insufficient funds.")
        return

    context.chat_data.setdefault('active_bets', {})[user_id] = {
        'name': update.effective_user.first_name,
        'bet_type': bet_type,
        'target_num': target_num,
        'amount': amount
    }
    await update.message.reply_text(f"🪙 Bet registered for **{update.effective_user.first_name}**!")

async def bet_under(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/under <amount>`")
        return
    await place_bet(update, context, "under", amount=amt)

async def bet_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/over <amount>`")
        return
    await place_bet(update, context, "over", amount=amt)

async def bet_equal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/equal <amount>`")
        return
    await place_bet(update, context, "equal", amount=amt)

async def bet_exact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(context.args[0])
        amt = int(context.args[1])
        if target < 2 or target > 12 or amt <= 0: raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/exact <2-12> <amount>`")
        return
    await place_bet(update, context, "exact", target_num=target, amount=amt)

async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    bets = context.chat_data.get('active_bets', {})
    if not bets:
        await update.message.reply_text("❌ No active bets.")
        return

    context.chat_data['betting_open'] = False
    await update.message.reply_text("🎲 **Rolling dice...**")

    d1 = await context.bot.send_dice(update.effective_chat.id)
    d2 = await context.bot.send_dice(update.effective_chat.id)
    await asyncio.sleep(3)

    total = d1.dice.value + d2.dice.value
    bracket = "under" if total <= 6 else ("equal" if total == 7 else "over")

    header = f"🎲 **Dice Total: {total}** ({bracket.upper()})\n\n"
    win, lose = [], []

    for u_id, info in bets.items():
        is_win = (info['bet_type'] == "exact" and info['target_num'] == total) or (info['bet_type'] == bracket and info['bet_type'] != "exact")
        profit = info['amount'] * 7 if info['bet_type'] == "exact" else (info['amount'] * 4 if info['bet_type'] == "equal" else info['amount'])
        
        if is_win:
            update_balance(u_id, profit)
            win.append(f"🟢 {info['name']}: +{profit}")
        else:
            update_balance(u_id, -info['amount'])
            lose.append(f"🔴 {info['name']}: -{info['amount']}")

    msg = header + "🏆 **Winners:**\n" + ("\n".join(win) if win else "None") + "\n\n💀 **Losers:**\n" + ("\n".join(lose) if lose else "None")
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
    context.chat_data['active_bets'].clear()

def main():
    init_db()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("setbet", set_bet_round))
    application.add_handler(CommandHandler("addcoins", add_coins_admin))
    application.add_handler(CommandHandler("roll", roll_dice))
    application.add_handler(CommandHandler("under", bet_under))
    application.add_handler(CommandHandler("over", bet_over))
    application.add_handler(CommandHandler("equal", bet_equal))
    application.add_handler(CommandHandler("exact", bet_exact))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("claim", claim_reward))
    application.add_handler(CommandHandler("donate", donate_coins))
    application.add_handler(CommandHandler("bal", check_balance))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("leaderboard", leaderboard))

    # Fallback initialization structure to prevent crashing if environment strings are absent
    if not APP_URL:
        print("Starting via Polling baseline...")
        application.run_polling()
    else:
        print(f"Starting Webhook pipeline on port {PORT} with target {APP_URL}...")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"{APP_URL}/{TOKEN}"
        )

if __name__ == '__main__':
    main()
