import asyncio
import logging
import sqlite3
import time
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

# Updated /help guide command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🎲 **WELCOME TO THE DICE BETTING GAME** 🎲\n\n"
        "Here is a beginner-friendly guide on how the game works and how you can manage your digital wallet!\n\n"
        "📖 **HOW TO PLAY**\n"
        "1. Wait for the game administrator to open a betting round using `/setbet`.\n"
        "2. Once open, place your prediction on what the total sum of **two rolled dice** will be.\n"
        "3. The admin will run the `/roll` command to spin the dice live in the chat and calculate payouts!\n\n"
        "💰 **MULTIPLIERS & PAYOUTS**\n"
        "• 🟢 `/under <amount>` — Combined sum is **1 to 6**. (Pays **2x** total return)\n"
        "• 🔵 `/over <amount>` — Combined sum is **8 to 12**. (Pays **2x** total return)\n"
        "• 🟡 `/equal <amount>` — Combined sum is **exactly 7**. (🔥 Pays **4x** total return)\n"
        "• 🎯 `/exact <number> <amount>` — Guess the **exact target sum** from 2 to 12. (💎 **MEGA JACKPOT: Pays 7x!**)\n"
        "  _Example:_ `/exact 10 500` places a 500-coin bet on the dice total landing on exactly 10.\n\n"
        "💳 **PLAYER WALLET COMMANDS**\n"
        "• `/balance` (or `/bal`, `/wallet`) — Check your current coin count.\n"
        "• `/claim` — Collect **100 free coins** every 24 hours.\n"
        "• `/leaderboard` — View the top 10 richest players in the community.\n"
        "• `/donate <amount>` — Send coins to another player by **replying** to their message (An 11% processing tax applies).\n\n"
        "✨ _Tip: Type `/claim` right now to get your starting capital if you haven't already!_"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# /setbet command (Strictly Admin Only)
async def set_bet_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ **Access Denied:** Only the bot Administrator can open a betting round.")
        return

    if 'betting_open' not in context.chat_data:
        context.chat_data['betting_open'] = False

    if context.chat_data['betting_open']:
        await update.message.reply_text("⚠️ **A betting round is already open!** Players are currently placing bets. Type `/roll` to finish it.")
        return

    context.chat_data['betting_open'] = True
    context.chat_data['active_bets'] = {}

    await update.message.reply_text(
        "🎲 **A NEW ROUND OF DICE BETTING HAS BEGUN!** 🎲\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "The game is now open! Place your predictions using:\n"
        "🟢 `/under <amount>` (Sums 1-6)\n"
        "🟡 `/equal <amount>` (Sum exactly 7 — **Pays 4x!**)\n"
        "🔵 `/over <amount>` (Sums 8-12)\n"
        "🎯 `/exact <target_number> <amount>` (**Pays 7x!**)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 *Admin will roll the dice shortly! Get your stakes in!*",
        parse_mode="Markdown"
    )

# /addcoins command (Strictly Admin Only)
async def add_coins_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ **Access Denied:** Only the bot Administrator can mint new coins.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: `/addcoins <amount>` (Optionally reply to someone's message)", parse_mode="Markdown")
        return

    try:
        amount_to_add = int(context.args[0])
        if amount_to_add <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0.")
            return
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid whole number for the amount.")
        return

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_id = target_user.id
        target_name = target_user.first_name
    else:
        target_id = user_id
        target_name = "yourself"

    get_balance(target_id)
    update_balance(target_id, amount_to_add)
    new_target_balance = get_balance(target_id)

    await update.message.reply_text(
        f"🛠️ **Admin Action Authorized**\n"
        f"⚡ Generated: **+{amount_to_add} coins**\n"
        f"👤 Credited To: **{target_name}**\n"
        f"💰 New Wallet Balance: **{new_target_balance} coins**",
        parse_mode="Markdown"
    )

# /donate command with 11% tax deduction
async def donate_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    sender_name = update.effective_user.first_name
    
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ **Donation Failed!**\nYou must use this command by **replying** to the message of the person you want to donate to.\n\n"
            "Example: Reply to someone with `/donate 500`",
            parse_mode="Markdown"
        )
        return

    recipient = update.message.reply_to_message.from_user
    recipient_id = recipient.id
    recipient_name = recipient.first_name

    if sender_id == recipient_id:
        await update.message.reply_text("❌ You cannot donate coins to yourself!")
        return

    if recipient.is_bot:
        await update.message.reply_text("❌ You cannot donate coins to bots!")
        return

    if not context.args:
        await update.message.reply_text("❌ Please specify an amount. Example: `/donate 100`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
        if amount <= 0:
            await update.message.reply_text("❌ Donation amount must be greater than 0.")
            return
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid whole number for the donation amount.")
        return

    sender_balance = get_balance(sender_id)
    if amount > sender_balance:
        await update.message.reply_text(f"❌ Transfer denied. You only have **{sender_balance} coins**.", parse_mode="Markdown")
        return

    tax_charge = round(amount * 0.11)
    if tax_charge < 1 and amount >= 1: 
        tax_charge = 1 
        
    received_amount = amount - tax_charge

    get_balance(recipient_id)

    update_balance(sender_id, -amount)             
    update_balance(recipient_id, received_amount)   

    await update.message.reply_text(
        f"🤝 **Donation Successful!**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📤 From: **{sender_name}**\n"
        f"📥 To: **{recipient_name}**\n\n"
        f"💰 Total Sent: **{amount} coins**\n"
        f"⚡ Tax Fee (11%): **{tax_charge} coins**\n"
        f"🎁 Received: **{received_amount} coins**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👛 Your remaining balance: **{sender_balance - amount} coins**",
        parse_mode="Markdown"
    )

async def claim_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name
    
    coins, last_claim = get_player_data(user_id)
    current_time = time.time()
    
    cooldown_seconds = COOLDOWN_HOURS * 3600
    time_passed = current_time - last_claim
    
    if time_passed < cooldown_seconds:
        seconds_left = int(cooldown_seconds - time_passed)
        hours = seconds_left // 3600
        minutes = (seconds_left % 3600) // 60
        seconds = seconds_left % 60
        
        await update.message.reply_text(
            f"⏳ **Too Early, {user_name}!**\n"
            f"You must wait **{hours}h {minutes}m {seconds}s** before claiming your next reward.",
            parse_mode="Markdown"
        )
        return

    update_balance(user_id, CLAIM_AMOUNT)
    set_claim_timestamp(user_id, current_time)
    new_balance = coins + CLAIM_AMOUNT
    
    await update.message.reply_text(
        f"🎁 **Daily Reward Claimed!**\n"
        f"💰 Added: **+{CLAIM_AMOUNT} coins**\n"
        f"👛 Total Balance: **{new_balance} coins**\n\n"
        f"🔔 *I will notify you in exactly 24 hours when it's ready again!*",
        parse_mode="Markdown"
    )
    
    current_jobs = context.job_queue.get_jobs_by_name(f"notify_{user_id}")
    for old_job in current_jobs:
        old_job.schedule_removal()
        
    context.job_queue.run_once(
        send_ready_notification,
        when=cooldown_seconds,
        chat_id=chat_id,
        name=f"notify_{user_id}"
    )

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = get_balance(user_id)
    await update.message.reply_text(f"💰 Your current balance is: **{balance} coins**", parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_players = get_top_players()
    
    if not top_players:
        await update.message.reply_text("📋 The leaderboard is currently empty.")
        return

    leaderboard_text = "🏆 **TOP 10 PLAYERS RANKING** 🏆\n"
    leaderboard_text += "━━━━━━━━━━━━━━━━━━━\n"
    
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for index, (u_id, coins) in enumerate(top_players, start=1):
        rank_badge = medals.get(index, f"`#{index:02d}`")
        
        try:
            chat_member = await context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=u_id)
            player_name = chat_member.user.first_name
        except Exception:
            player_name = f"User({u_id})"
            
        leaderboard_text += f"{rank_badge} **{player_name}** — `{coins}` coins\n"

    leaderboard_text += "━━━━━━━━━━━━━━━━━━━\n"
    leaderboard_text += "Keep rolling the dice to climb the ladder! 🎲"

    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")

# Core Bet Placement Base Logic
async def place_bet(update: Update, context: ContextTypes.DEFAULT_TYPE, bet_type: str, target_num: int = None, amount: int = None):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if not context.chat_data.get('betting_open', False):
        await update.message.reply_text("🔒 **Betting is currently closed.** Please wait for the Admin to start a new round using `/setbet`!", parse_mode="Markdown")
        return

    current_balance = get_balance(user_id)
    if amount > current_balance:
        await update.message.reply_text(f"❌ {user_name}, you only have **{current_balance} coins**.", parse_mode="Markdown")
        return

    if 'active_bets' not in context.chat_data:
        context.chat_data['active_bets'] = {}

    context.chat_data['active_bets'][user_id] = {
        'name': user_name,
        'bet_type': bet_type,
        'target_num': target_num,
        'amount': amount
    }

    prediction_display = f"EXACT NUMBER ({target_num})" if bet_type == "exact" else bet_type.upper()

    await update.message.reply_text(
        f"🪙 **Bet Registered!**\n"
        f"👤 Player: **{user_name}**\n"
        f"🔮 Prediction: **{prediction_display}**\n"
        f"💸 Stake: **{amount} coins**\n\n"
        f"Waiting for more players or type `/roll` to spin!",
        parse_mode="Markdown"
    )

async def bet_under(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/under <amount>`", parse_mode="Markdown")
        return
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number greater than 0.")
        return
    await place_bet(update, context, "under", amount=amt)

async def bet_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/over <amount>`", parse_mode="Markdown")
        return
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number greater than 0.")
        return
    await place_bet(update, context, "over", amount=amt)

async def bet_equal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/equal <amount>`", parse_mode="Markdown")
        return
    try:
        amt = int(context.args[0])
        if amt <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number greater than 0.")
        return
    await place_bet(update, context, "equal", amount=amt)

# New Custom /exact command handler
async def bet_exact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ **Usage Error!**\nFormat must be: `/exact <number> <amount>`\n\nExample: `/exact 10 500`", parse_mode="Markdown")
        return

    try:
        target_num = int(context.args[0])
        amount = int(context.args[1])
        
        if target_num < 2 or target_num > 12:
            await update.message.reply_text("❌ **Invalid Target!** Two standard dice can only result in a sum between **2 and 12**.")
            return
            
        if amount <= 0:
            await update.message.reply_text("❌ Bet amount must be greater than 0.")
            return
    except ValueError:
        await update.message.reply_text("❌ Please provide valid whole numbers.\nFormat: `/exact <number> <amount>`")
        return

    await place_bet(update, context, "exact", target_num=target_num, amount=amount)

# Adjusted /roll command evaluating the new jackpot structures
async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ **Access Denied:** Only the bot Administrator can execute the `/roll` processing command.")
        return

    if 'active_bets' not in context.chat_data or not context.chat_data['active_bets']:
        await update.message.reply_text("❌ No active bets pool detected! Use `/setbet` to start a round and gather player stakes.")
        return

    bets_pool = context.chat_data['active_bets']
    context.chat_data['betting_open'] = False
    
    await update.message.reply_text("🎲 **Rolling two dice for all active players! Hold on...**", parse_mode="Markdown")

    dice1_msg = await context.bot.send_dice(chat_id=chat_id)
    dice2_msg = await context.bot.send_dice(chat_id=chat_id)

    await asyncio.sleep(3)

    val1 = dice1_msg.dice.value
    val2 = dice2_msg.dice.value
    total_sum = val1 + val2

    if total_sum <= 6:
        result_bracket = "under"
        bracket_text = "UNDER (1-6)"
    elif total_sum == 7:
        result_bracket = "equal"
        bracket_text = "EQUAL (7)"
    else:
        result_bracket = "over"
        bracket_text = "OVER (8-12)"

    header_msg = (
        f"🎲 **ROUND RESULTS** 🎲\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎲 Dice 1: **{val1}**\n"
        f"🎲 Dice 2: **{val2}**\n"
        f"🧮 Total Sum: **{total_sum}** — ✨ **{bracket_text}** ✨\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )

    winners_list = []
    losers_list = []

    for u_id, bet_info in bets_pool.items():
        p_name = bet_info['name']
        p_choice = bet_info['bet_type']
        p_target = bet_info['target_num']
        p_stake = bet_info['amount']
        
        c_bal = get_balance(u_id)
        if p_stake > c_bal:
            continue 

        # Evaluate if the player won
        is_winner = False
        profit = 0

        if p_choice == "exact" and p_target == total_sum:
            is_winner = True
            profit = p_stake * 7  # 7x Payout for hitting the precise number!
        elif p_choice == result_bracket and p_choice != "exact":
            is_winner = True
            profit = p_stake if p_choice != "equal" else p_stake * 4

        if is_winner:
            update_balance(u_id, profit)
            bet_display = f"EXACT ({p_target})" if p_choice == "exact" else p_choice.upper()
            winners_list.append(f"🟢 **{p_name}**\n   ↳ Bet: {bet_display} | Stake: {p_stake} | **Payout: +{profit} coins**")
        else:
            update_balance(u_id, -p_stake)
            bet_display = f"EXACT ({p_target})" if p_choice == "exact" else p_choice.upper()
            losers_list.append(f"🔴 **{p_name}**\n   ↳ Bet: {bet_display} | Stake: {p_stake} | **Payout: -{p_stake} coins**")

    body_msg = "🏆 **WINNERS:**\n"
    if winners_list:
        body_msg += "\n".join(winners_list)
    else:
        body_msg += "_None_"

    body_msg += "\n\n💀 **LOSERS:**\n"
    if losers_list:
        body_msg += "\n".join(losers_list)
    else:
        body_msg += "_None_"

    await context.bot.send_message(chat_id=chat_id, text=header_msg + body_msg, parse_mode="Markdown")
    context.chat_data['active_bets'].clear()

def main():
    init_db()

    application = Application.builder().token(TOKEN).build()

    # Admin Control Handlers
    application.add_handler(CommandHandler("setbet", set_bet_round))
    application.add_handler(CommandHandler("addcoins", add_coins_admin))
    application.add_handler(CommandHandler("roll", roll_dice))
    
    # Player Bet Placement Handlers
    application.add_handler(CommandHandler("under", bet_under))
    application.add_handler(CommandHandler("over", bet_over))
    application.add_handler(CommandHandler("equal", bet_equal))
    application.add_handler(CommandHandler("exact", bet_exact))
    
    # General Commands
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("claim", claim_reward))
    application.add_handler(CommandHandler("donate", donate_coins))
    application.add_handler(CommandHandler("bal", check_balance))
    application.add_handler(CommandHandler("wallet", check_balance))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("leaderboard", leaderboard))

    print("Dice Game Engine with /exact jackpot systems running...")
    application.run_polling()

if __name__ == '__main__':
    main()
