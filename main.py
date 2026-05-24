import os
import time
import logging
import sqlite3
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Credentials & Configurations
TOKEN = "8490224778:AAHBykM6v_R9cI4ctWPpfbr5RxHN_S4ZfnE"
ADMIN_ID = 7812499632
DB_FILE = "players.db"
STARTING_COINS = 1000
CLAIM_AMOUNT = 100
COOLDOWN_HOURS = 24

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==================== FLASK APP WEB SERVER ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "Dice Engine Active", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# ==================== DATABASE CONFIGURATIONS ====================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                coins INTEGER DEFAULT 0,
                last_claim REAL DEFAULT 0
            )
        ''')

def get_player_data(user_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT coins, last_claim FROM players WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            conn.execute("INSERT INTO players (user_id, coins, last_claim) VALUES (?, ?, 0)", (user_id, STARTING_COINS))
            return STARTING_COINS, 0.0
        return row[0], row[1]

def update_balance(user_id: int, amount_change: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (amount_change, user_id))

def set_claim_timestamp(user_id: int, timestamp: float):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE players SET last_claim = ? WHERE user_id = ?", (timestamp, user_id))

# ==================== GAME LOGIC COMMANDS ====================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎲 **WELCOME TO THE DICE BETTING GAME** 🎲\n\n"
        "🟢 `/under <amount>` — Sum is 1-6 (Pays 2x)\n"
        "🔵 `/over <amount>` — Sum is 8-12 (Pays 2x)\n"
        "🟡 `/equal <amount>` — Sum is exactly 7 (Pays 4x)\n"
        "🎯 `/exact <num> <amount>` — Guess exact sum (Pays 7x!)\n\n"
        "💰 Wallet: `/balance` | `/claim` | `/leaderboard` | `/donate <amount>`", 
        parse_mode="Markdown"
    )

async def set_bet_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if context.chat_data.get('betting_open', False):
        await update.message.reply_text("⚠️ Betting is already open!")
        return
    context.chat_data['betting_open'] = True
    context.chat_data['active_bets'] = {}
    await update.message.reply_text("🎲 **NEW BETTING ROUND OPEN!**\nUse `/under`, `/over`, `/equal`, or `/exact`!", parse_mode="Markdown")

async def place_bet(update: Update, context: ContextTypes.DEFAULT_TYPE, bet_type: str, target_num: int = None, amount: int = None):
    user_id = update.effective_user.id
    if not context.chat_data.get('betting_open', False):
        await update.message.reply_text("🔒 Betting is closed!")
        return
    coins, _ = get_player_data(user_id)
    if amount > coins:
        await update.message.reply_text("❌ Insufficient funds.")
        return
    context.chat_data.setdefault('active_bets', {})[user_id] = {
        'name': update.effective_user.first_name, 'bet_type': bet_type, 'target_num': target_num, 'amount': amount
    }
    await update.message.reply_text(f"🪙 Bet accepted for {update.effective_user.first_name}!")

async def bet_under(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
        await place_bet(update, context, "under", amount=amt)
    except: await update.message.reply_text("❌ Usage: `/under <amount>`")

async def bet_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
        await place_bet(update, context, "over", amount=amt)
    except: await update.message.reply_text("❌ Usage: `/over <amount>`")

async def bet_equal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
        await place_bet(update, context, "equal", amount=amt)
    except: await update.message.reply_text("❌ Usage: `/equal <amount>`")

async def bet_exact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(context.args[0])
        amt = int(context.args[1])
        if target < 2 or target > 12 or amt <= 0: raise ValueError
        await place_bet(update, context, "exact", target_num=target, amount=amt)
    except: await update.message.reply_text("❌ Usage: `/exact <2-12> <amount>`")

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
    msg = f"🎲 **Dice Total: {total}** ({bracket.upper()})\n\n🏆 **Results:**\n"
    
    for u_id, info in bets.items():
        is_win = (info['bet_type'] == "exact" and info['target_num'] == total) or (info['bet_type'] == bracket and info['bet_type'] != "exact")
        mult = 7 if info['bet_type'] == "exact" else (4 if info['bet_type'] == "equal" else 1)
        if is_win:
            update_balance(u_id, info['amount'] * mult)
            msg += f"🟢 {info['name']}: +{info['amount'] * mult}\n"
        else:
            update_balance(u_id, -info['amount'])
            msg += f"🔴 {info['name']}: -{info['amount']}\n"
            
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
    context.chat_data['active_bets'].clear()

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins, _ = get_player_data(update.effective_user.id)
    await update.message.reply_text(f"💰 Balance: **{coins} coins**", parse_mode="Markdown")

async def claim_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins, last_claim = get_player_data(user_id)
    if time.time() - last_claim < (COOLDOWN_HOURS * 3600):
        left = int((COOLDOWN_HOURS * 3600) - (time.time() - last_claim))
        await update.message.reply_text(f"⏳ Wait **{left//3600}h {(left%3600)//60}m**.")
        return
    update_balance(user_id, CLAIM_AMOUNT)
    set_claim_timestamp(user_id, time.time())
    await update.message.reply_text(f"🎁 **Daily Reward Claimed!** (+{CLAIM_AMOUNT} coins)")

async def donate_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to the message of the person you want to donate to.")
        return
    try:
        amt = int(context.args[0])
        if amt <= 0 or get_player_data(update.effective_user.id)[0] < amt: raise ValueError
        rec_id = update.message.reply_to_message.from_user.id
        get_player_data(rec_id)
        update_balance(update.effective_user.id, -amt)
        update_balance(rec_id, round(amt * 0.89)) # 11% Tax
        await update.message.reply_text(f"🤝 Donated {amt} coins (Received: {round(amt * 0.89)})")
    except: await update.message.reply_text("❌ Invalid donation amount.")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect(DB_FILE) as conn:
        users = conn.execute("SELECT user_id, coins FROM players ORDER BY coins DESC LIMIT 10").fetchall()
    text = "🏆 **LEADERBOARD** 🏆\n"
    for i, (u_id, coins) in enumerate(users, 1):
        text += f"#{i} User({u_id}) — `{coins}` coins\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== MAIN INITIALIZER ====================
async def main():
    init_db()
    
    # Start Flask Webserver in a separate background thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Initialize the telegram app structure cleanly
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("setbet", set_bet_round))
    application.add_handler(CommandHandler("roll", roll_dice))
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
    
    # Clean modern polling loop logic
    async with application:
        await application.initialize()
        await application.start()
        print("Bot is polling successfully on Render engine...")
        await application.updater.start_polling()
        
        # Keep loop running infinitely
        while True:
            await asyncio.sleep(3600)

if __name__ == '__main__':
    # Use standard run method to prevent modern runtime lifecycle thread errors
    asyncio.run(main())
