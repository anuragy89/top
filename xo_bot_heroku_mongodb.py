"""
🎮 Advanced Telegram XO Bot - HEROKU + MONGODB VERSION
Features: AI, Multiplayer, Leaderboard, Broadcast, Stats, Analytics
"""

import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
import random
from typing import Optional, List, Dict
from datetime import datetime
import json

# MongoDB imports
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
import certifi

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN not found!")
    exit(1)

if not MONGODB_URI:
    logger.error("❌ MONGODB_URI not found!")
    exit(1)

# Game States
MENU, GAME_MODE, WAITING_PLAYER, PLAYING, BROADCAST_INPUT = range(5)

# Emoji Constants
EMPTY = "⬜"
PLAYER_X = "❌"
PLAYER_O = "⭕"
HUMAN = "👤"
AI = "🤖"
VERSUS = "⚔️"
THINKING = "🤔"
WIN = "🎉"
DRAW = "🤝"
MOVE = "👉"
LOADING = "⏳"
TROPHY = "🏆"
CHART = "📊"

# MongoDB Connection
class MongoDBManager:
    """MongoDB connection and operations manager"""
    
    def __init__(self, uri: str):
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000, tlsCAFile=certifi.where())
            self.db = self.client['xo_gaming_bot']
            self.users = self.db['users']
            self.groups = self.db['groups']
            self.games = self.db['games']
            self.broadcasts = self.db['broadcasts']
            
            # Test connection
            self.client.admin.command('ping')
            logger.info("✅ MongoDB connected successfully!")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            raise
    
    def update_user_stats(self, user_id: int, username: str, result: str):
        """Update user game statistics"""
        try:
            self.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "user_id": user_id,
                        "username": username,
                        "last_updated": datetime.now()
                    },
                    "$inc": {
                        f"stats.{result}": 1,
                        "stats.total_games": 1
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error updating user stats: {e}")
    
    def update_group_stats(self, group_id: int, group_name: str):
        """Update group statistics"""
        try:
            self.groups.update_one(
                {"group_id": group_id},
                {
                    "$set": {
                        "group_id": group_id,
                        "name": group_name,
                        "last_activity": datetime.now()
                    },
                    "$inc": {"games_played": 1}
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error updating group stats: {e}")
    
    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Get top players by wins"""
        try:
            pipeline = [
                {
                    "$project": {
                        "username": 1,
                        "wins": {"$getField": ["stats", "wins"]},
                        "losses": {"$getField": ["stats", "losses"]},
                        "draws": {"$getField": ["stats", "draws"]},
                        "total_games": {"$getField": ["stats", "total_games"]},
                        "winrate": {
                            "$cond": [
                                {"$eq": [{"$getField": ["stats", "total_games"]}, 0]},
                                0,
                                {
                                    "$multiply": [
                                        {
                                            "$divide": [
                                                {"$getField": ["stats", "wins"]},
                                                {"$getField": ["stats", "total_games"]}
                                            ]
                                        },
                                        100
                                    ]
                                }
                            ]
                        }
                    }
                },
                {"$sort": {"wins": -1}},
                {"$limit": limit}
            ]
            
            return list(self.users.aggregate(pipeline))
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []
    
    def get_user_stats(self, user_id: int) -> Optional[Dict]:
        """Get specific user statistics"""
        try:
            return self.users.find_one({"user_id": user_id})
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return None
    
    def get_all_users(self) -> List[Dict]:
        """Get all users for broadcast"""
        try:
            return list(self.users.find({}, {"user_id": 1}))
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def get_all_groups(self) -> List[Dict]:
        """Get all groups for broadcast"""
        try:
            return list(self.groups.find({}, {"group_id": 1}))
        except Exception as e:
            logger.error(f"Error getting groups: {e}")
            return []
    
    def get_statistics(self) -> Dict:
        """Get overall statistics"""
        try:
            total_users = self.users.count_documents({})
            total_groups = self.groups.count_documents({})
            total_games = self.games.count_documents({})
            
            return {
                "total_users": total_users,
                "total_groups": total_groups,
                "total_games": total_games
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}
    
    def log_game(self, user_id: int, opponent: str, result: str):
        """Log game to database"""
        try:
            self.games.insert_one({
                "user_id": user_id,
                "opponent": opponent,
                "result": result,
                "timestamp": datetime.now()
            })
        except Exception as e:
            logger.error(f"Error logging game: {e}")

# Initialize MongoDB
try:
    db_manager = MongoDBManager(MONGODB_URI)
except Exception as e:
    logger.error(f"Failed to initialize MongoDB: {e}")
    exit(1)

class XOGame:
    """Tic-Tac-Toe game logic"""
    
    def __init__(self, ai_opponent: bool = False, difficulty: str = "hard"):
        self.board = [0] * 9
        self.current_player = 1
        self.ai_opponent = ai_opponent
        self.difficulty = difficulty
        self.game_over = False
        self.winner = None
        self.move_count = 0
        self.moves_history = []
        
    def make_move(self, position: int, player: int) -> bool:
        """Make a move"""
        if position < 0 or position > 8 or self.board[position] != 0:
            return False
        self.board[position] = player
        self.move_count += 1
        self.moves_history.append(position)
        self.check_game_state()
        return True
    
    def check_game_state(self) -> None:
        """Check if game is won or drawn"""
        winning_combos = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],
            [0, 3, 6], [1, 4, 7], [2, 5, 8],
            [0, 4, 8], [2, 4, 6]
        ]
        
        for combo in winning_combos:
            if (self.board[combo[0]] != 0 and 
                self.board[combo[0]] == self.board[combo[1]] == self.board[combo[2]]):
                self.winner = self.board[combo[0]]
                self.game_over = True
                return
        
        if self.move_count == 9:
            self.game_over = True
            self.winner = 0
    
    def get_available_moves(self) -> List[int]:
        """Get available positions"""
        return [i for i in range(9) if self.board[i] == 0]
    
    def ai_move(self) -> Optional[int]:
        """Get best AI move"""
        available = self.get_available_moves()
        if not available:
            return None
        
        if self.difficulty == "easy":
            return random.choice(available)
        elif self.difficulty == "medium":
            if random.random() < 0.3:
                return random.choice(available)
        
        best_score = float('-inf')
        best_move = None
        
        for move in available:
            self.board[move] = 2
            score = self._minimax(0, False)
            self.board[move] = 0
            
            if score > best_score:
                best_score = score
                best_move = move
        
        return best_move
    
    def _minimax(self, depth: int, is_maximizing: bool) -> int:
        """Minimax algorithm"""
        winning_combos = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],
            [0, 3, 6], [1, 4, 7], [2, 5, 8],
            [0, 4, 8], [2, 4, 6]
        ]
        
        for combo in winning_combos:
            if (self.board[combo[0]] != 0 and 
                self.board[combo[0]] == self.board[combo[1]] == self.board[combo[2]]):
                winner = self.board[combo[0]]
                return 10 - depth if winner == 2 else depth - 10
        
        available = self.get_available_moves()
        if len(available) == 0:
            return 0
        
        if is_maximizing:
            best_score = float('-inf')
            for move in available:
                self.board[move] = 2
                score = self._minimax(depth + 1, False)
                self.board[move] = 0
                best_score = max(score, best_score)
            return best_score
        else:
            best_score = float('inf')
            for move in available:
                self.board[move] = 1
                score = self._minimax(depth + 1, True)
                self.board[move] = 0
                best_score = min(score, best_score)
            return best_score
    
    def get_board_display(self) -> str:
        """Get formatted board"""
        display = ""
        for i in range(9):
            if self.board[i] == 0:
                display += EMPTY
            elif self.board[i] == 1:
                display += PLAYER_X
            else:
                display += PLAYER_O
            
            if (i + 1) % 3 == 0:
                display += "\n"
            else:
                display += " "
        return display

def get_game_keyboard(game: XOGame, game_id: str = "ai") -> InlineKeyboardMarkup:
    """Generate game board keyboard"""
    buttons = []
    for i in range(9):
        if game.board[i] == 0:
            buttons.append(InlineKeyboardButton(MOVE, callback_data=f"move_{game_id}_{i}"))
        else:
            symbol = PLAYER_X if game.board[i] == 1 else PLAYER_O
            buttons.append(InlineKeyboardButton(symbol, callback_data=f"noop_{i}"))
    
    keyboard = [buttons[i:i+3] for i in range(0, 9, 3)]
    keyboard.append([
        InlineKeyboardButton("🔄 New Game", callback_data=f"newgame_{game_id}"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu")
    ])
    
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command"""
    user = update.effective_user
    chat = update.effective_chat
    
    # Update group stats if in group
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        db_manager.update_group_stats(chat.id, chat.title)
    
    welcome_text = f"""
╔════════════════════════════════════╗
║    🎮 XO GAMING BOT 🎮            ║
║   Ultimate Tic-Tac-Toe Gaming      ║
╚════════════════════════════════════╝

👋 Hello {user.first_name}!

🎯 <b>Features:</b>
  🤖 Play vs Unbeatable AI
  👥 Multiplayer Mode
  🏆 Leaderboard Rankings
  📊 Your Statistics
  ⚡ Instant Responses

<b>What would you like to do?</b>
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🤖 vs AI", callback_data="mode_ai"),
            InlineKeyboardButton("👥 vs Player", callback_data="mode_player")
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
        ],
        [
            InlineKeyboardButton("📜 Rules", callback_data="rules"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ]
    ]
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Main callback handler"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    
    data = query.data
    user_id = query.from_user.id
    
    try:
        if data == "menu":
            return await show_menu(query)
        elif data == "rules":
            return await show_rules(query)
        elif data == "help":
            return await show_help(query)
        elif data == "mode_ai":
            return await start_ai_game(query, context)
        elif data == "mode_player":
            return await show_multiplayer_message(query)
        elif data == "leaderboard":
            return await show_leaderboard(query)
        elif data == "my_stats":
            return await show_user_stats(query, user_id)
        elif data.startswith("move_"):
            return await handle_game_move(query, context, data)
        elif data.startswith("newgame_"):
            return await handle_new_game(query, context, data)
        
        return MENU
    except Exception as e:
        logger.error(f"Error in callback: {e}")
        return MENU

async def show_menu(query) -> int:
    """Show main menu"""
    text = """
╔════════════════════════════════════╗
║     🎮 MAIN MENU 🎮               ║
╚════════════════════════════════════╝

<b>Choose your game mode:</b>

🤖 <b>Play vs AI</b> - Unbeatable opponent
👥 <b>Multiplayer</b> - Challenge friends
🏆 <b>Leaderboard</b> - Top players
📊 <b>My Stats</b> - Your performance
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🤖 vs AI", callback_data="mode_ai"),
            InlineKeyboardButton("👥 vs Player", callback_data="mode_player")
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
        ],
        [
            InlineKeyboardButton("📜 Rules", callback_data="rules"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def show_leaderboard(query) -> int:
    """Show leaderboard"""
    leaderboard = db_manager.get_leaderboard(10)
    
    if not leaderboard:
        text = "🏆 <b>Leaderboard</b>\n\nNo games played yet! 🎮"
    else:
        text = "╔════════════════════════════════════╗\n"
        text += "║  🏆 TOP 10 PLAYERS 🏆             ║\n"
        text += "╚════════════════════════════════════╝\n\n"
        
        for i, player in enumerate(leaderboard, 1):
            wins = player.get('wins', 0) or 0
            losses = player.get('losses', 0) or 0
            draws = player.get('draws', 0) or 0
            total = wins + losses + draws
            winrate = (wins / total * 100) if total > 0 else 0
            
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}️⃣"
            text += f"{medal} <b>{player.get('username', 'Unknown')}</b>\n"
            text += f"   ✅ {wins} | ❌ {losses} | 🤝 {draws} | 📊 {winrate:.1f}%\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def show_user_stats(query, user_id: int) -> int:
    """Show user statistics"""
    user_data = db_manager.get_user_stats(user_id)
    
    if not user_data:
        text = "📊 <b>Your Statistics</b>\n\nNo games played yet! Play to see your stats. 🎮"
    else:
        stats = user_data.get('stats', {})
        wins = stats.get('wins', 0)
        losses = stats.get('losses', 0)
        draws = stats.get('draws', 0)
        total = wins + losses + draws
        winrate = (wins / total * 100) if total > 0 else 0
        
        text = "╔════════════════════════════════════╗\n"
        text += "║     📊 YOUR STATISTICS 📊         ║\n"
        text += "╚════════════════════════════════════╝\n\n"
        text += f"<b>Player:</b> @{user_data.get('username', 'Unknown')}\n"
        text += f"<b>Total Games:</b> {total} 🎮\n"
        text += f"<b>Wins:</b> {wins} ✅\n"
        text += f"<b>Losses:</b> {losses} ❌\n"
        text += f"<b>Draws:</b> {draws} 🤝\n"
        text += f"<b>Win Rate:</b> {winrate:.1f}% 📈\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def show_rules(query) -> int:
    """Show rules"""
    text = """
╔════════════════════════════════════╗
║    📜 GAME RULES 📜               ║
╚════════════════════════════════════╝

<b>🎯 Objective:</b>
Get 3 symbols in a row (horizontal, vertical, or diagonal)

<b>Symbols:</b>
  ❌ = Your Move
  ⭕ = Opponent
  ⬜ = Empty Cell

<b>How to Play:</b>
1. Tap ⬜ to choose a cell
2. Opponent makes their move
3. First to 3-in-a-row wins! 🎉

<b>💡 Pro Tips:</b>
• Center (4) controls the board
• Corners (0,2,6,8) are strong
• Block opponent's winning setup
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def show_help(query) -> int:
    """Show help"""
    text = """
╔════════════════════════════════════╗
║    ❓ HELP & FAQ ❓               ║
╚════════════════════════════════════╝

<b>Commands:</b>
/start - Start game
/stats - Your statistics
/leaderboard - Top players
/help - This message

<b>Bot Features:</b>
🤖 Smart AI opponent
👥 Multiplayer mode
🏆 Ranking system
📊 Game statistics
⚡ Instant responses

<b>Need Help?</b>
• Check your stats: /stats
• View leaderboard: /leaderboard
• Read rules: Use Rules button
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def show_multiplayer_message(query) -> int:
    """Show multiplayer info"""
    text = """
╔════════════════════════════════════╗
║    👥 MULTIPLAYER MODE 👥        ║
╚════════════════════════════════════╝

<b>Coming Soon! 🚀</b>

For now, challenge friends using:
🤖 AI mode - Practice & rank up
📊 Leaderboard - Track progress

Share your bot with friends! 🎮
"""
    
    keyboard = [
        [InlineKeyboardButton("🤖 Play vs AI", callback_data="mode_ai")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def start_ai_game(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start AI game"""
    user = query.from_user
    game = XOGame(ai_opponent=True, difficulty="hard")
    context.user_data['game'] = game
    context.user_data['game_mode'] = 'ai'
    context.user_data['player1_id'] = user.id
    context.user_data['player1_name'] = user.username or user.first_name
    
    text = f"""
╔════════════════════════════════════╗
║   🤖 vs AI - GAME STARTED! 🤖    ║
╚════════════════════════════════════╝

{HUMAN} <b>You:</b> {PLAYER_X}
{AI} <b>Bot:</b> {PLAYER_O}

{game.get_board_display()}

<b>🎯 Your move!</b>
"""
    
    await query.edit_message_text(
        text,
        reply_markup=get_game_keyboard(game, "ai"),
        parse_mode=ParseMode.HTML
    )
    return PLAYING

async def handle_game_move(query, context: ContextTypes.DEFAULT_TYPE, data: str) -> int:
    """Handle game move"""
    try:
        parts = data.split("_")
        game_id = parts[1]
        move_pos = int(parts[2])
        user = query.from_user
        
        game = context.user_data.get('game')
        if not game:
            await query.answer("❌ Game not found!", show_alert=True)
            return MENU
        
        if not game.make_move(move_pos, 1):
            await query.answer("❌ Invalid move!", show_alert=True)
            return PLAYING
        
        if game.game_over:
            return await end_game(query, context, game, 'human_win', user)
        
        if game.ai_opponent:
            ai_move = game.ai_move()
            if ai_move is None:
                return await end_game(query, context, game, 'draw', user)
            
            game.make_move(ai_move, 2)
            
            if game.game_over:
                result = 'ai_win' if game.winner == 2 else 'draw'
                return await end_game(query, context, game, result, user)
        
        text = f"""
╔════════════════════════════════════╗
║     🤖 vs AI - PLAYING 🤖        ║
╚════════════════════════════════════╝

{HUMAN} <b>You:</b> {PLAYER_X}
{AI} <b>Bot:</b> {PLAYER_O}

{game.get_board_display()}

<b>🎯 Your move!</b>
"""
        
        await query.edit_message_text(
            text,
            reply_markup=get_game_keyboard(game, game_id),
            parse_mode=ParseMode.HTML
        )
        return PLAYING
        
    except Exception as e:
        logger.error(f"Error in game move: {e}")
        return PLAYING

async def end_game(query, context: ContextTypes.DEFAULT_TYPE, game: XOGame, result: str, user) -> int:
    """End game and update stats"""
    board_display = game.get_board_display()
    
    # Update database
    username = user.username or user.first_name
    db_manager.update_user_stats(user.id, username, result)
    db_manager.log_game(user.id, "AI", result)
    
    if result == 'human_win':
        text = f"""
╔════════════════════════════════════╗
║   {WIN} VICTORY! YOU WON! {WIN}   ║
╚════════════════════════════════════╝

{board_display}

<b>🎉 Congratulations!</b>
You defeated the AI! 💪

Stats updated! Check /stats
"""
    elif result == 'ai_win':
        text = f"""
╔════════════════════════════════════╗
║     {THINKING} AI WINS! {THINKING}    ║
╚════════════════════════════════════╝

{board_display}

<b>🤖 Better luck next time!</b>
AI outplayed you this round 📚

Study the board and try again!
"""
    else:
        text = f"""
╔════════════════════════════════════╗
║    {DRAW} IT'S A DRAW! {DRAW}     ║
╚════════════════════════════════════╝

{board_display}

<b>🤝 Great Match!</b>
You both played equally well

Try again for victory! 🎯
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 Play Again", callback_data="mode_ai"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu")
        ]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return MENU

async def handle_new_game(query, context: ContextTypes.DEFAULT_TYPE, data: str) -> int:
    """Handle new game"""
    game_id = data.split("_")[1]
    context.user_data['game'] = XOGame(ai_opponent=(game_id == 'ai'))
    return await start_ai_game(query, context) if game_id == 'ai' else MENU

# OWNER COMMANDS

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics (owner only)"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    stats = db_manager.get_statistics()
    text = f"""
╔════════════════════════════════════╗
║     📊 BOT STATISTICS 📊          ║
╚════════════════════════════════════╝

<b>System Stats:</b>
👤 Total Users: {stats.get('total_users', 0)}
👥 Total Groups: {stats.get('total_groups', 0)}
🎮 Total Games: {stats.get('total_games', 0)}

<b>Database:</b>
✅ Connected to MongoDB
📍 Tracking all games

<b>Commands:</b>
/broadcast - Send message to all
/stats - View this message
"""
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start broadcast command (owner only)"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    text = """
╔════════════════════════════════════╗
║     📢 BROADCAST MESSAGE 📢       ║
╚════════════════════════════════════╝

Send the message you want to broadcast to all users and groups.

Type: /cancel to cancel
"""
    
    await update.message.reply_text(text)
    return BROADCAST_INPUT

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive broadcast message and send to all users/groups"""
    if update.effective_user.id != OWNER_ID:
        return BROADCAST_INPUT
    
    broadcast_text = update.message.text
    
    # Show confirmation
    text = f"""
📢 <b>Broadcast Preview:</b>

{broadcast_text}

<b>Send to:</b>
👤 All Users
👥 All Groups
📍 Both
❌ Cancel
"""
    
    keyboard = [
        [InlineKeyboardButton("👤 Users Only", callback_data="broadcast_users")],
        [InlineKeyboardButton("👥 Groups Only", callback_data="broadcast_groups")],
        [InlineKeyboardButton("📍 Both", callback_data="broadcast_both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")]
    ]
    
    context.user_data['broadcast_message'] = broadcast_text
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return BROADCAST_INPUT

async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "broadcast_cancel":
        await query.edit_message_text("❌ Broadcast cancelled!")
        return MENU
    
    broadcast_text = context.user_data.get('broadcast_message', '')
    sent_count = 0
    failed_count = 0
    
    await query.edit_message_text(f"⏳ Broadcasting message...\n\n{LOADING} Processing...")
    
    if query.data in ["broadcast_users", "broadcast_both"]:
        users = db_manager.get_all_users()
        for user_doc in users:
            try:
                user_id = user_doc.get('user_id')
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 <b>Message from Bot Owner:</b>\n\n{broadcast_text}",
                    parse_mode=ParseMode.HTML
                )
                sent_count += 1
            except TelegramError as e:
                logger.warning(f"Failed to send to user {user_id}: {e}")
                failed_count += 1
    
    if query.data in ["broadcast_groups", "broadcast_both"]:
        groups = db_manager.get_all_groups()
        for group_doc in groups:
            try:
                group_id = group_doc.get('group_id')
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"📢 <b>Message from Bot Owner:</b>\n\n{broadcast_text}",
                    parse_mode=ParseMode.HTML
                )
                sent_count += 1
            except TelegramError as e:
                logger.warning(f"Failed to send to group {group_id}: {e}")
                failed_count += 1
    
    result_text = f"""
✅ <b>Broadcast Complete!</b>

📤 Sent: {sent_count}
❌ Failed: {failed_count}

Message delivered successfully!
"""
    
    await query.edit_message_text(result_text, parse_mode=ParseMode.HTML)
    return MENU

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel broadcast"""
    await update.message.reply_text("❌ Broadcast cancelled!")
    return MENU

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Start the bot"""
    logger.info("🚀 Starting Telegram XO Gaming Bot (Heroku + MongoDB)...")
    
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("help", lambda u, c: show_help(u.callback_query)))
    
    # Broadcast handlers
    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message),
                CallbackQueryHandler(broadcast_callback),
                CommandHandler("cancel", cancel_broadcast)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_broadcast)]
    )
    application.add_handler(broadcast_handler)
    
    # Game handlers
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot initialized!")
    logger.info("📱 Starting polling...")
    
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
