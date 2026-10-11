import os, json, hmac, hashlib, urllib.parse, sqlite3, random, asyncio, time
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
DB_PATH = os.getenv("DB_PATH", "giftgram.sqlite3")
PORT = int(os.getenv("PORT", "8000"))
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

if not BOT_TOKEN:
    raise RuntimeError("Укажи BOT_TOKEN в переменных окружения.")
if not WEBAPP_URL.startswith("https://"):
    raise RuntimeError("Укажи WEBAPP_URL с HTTPS-адресом опубликованной Mini App.")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

def connect():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            stars INTEGER NOT NULL DEFAULT 100, last_daily TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS nfts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT NOT NULL, rarity TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")

def upsert_user(user):
    uid = int(user["id"])
    username = user.get("username") or ""
    first_name = user.get("first_name") or "Игрок"
    with connect() as con:
        con.execute("""INSERT OR IGNORE INTO users(user_id, username, first_name, stars)
                       VALUES(?,?,?,100)""", (uid, username, first_name))
        con.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                    (username, first_name, uid))

def get_user(uid):
    with connect() as con:
        return con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def validate_init_data(init_data: str):
    if DEV_MODE and not init_data:
        # Local preview only. Never enable DEV_MODE on a public deployment.
        return {"id": 999999999, "first_name": "Тестовый игрок", "username": "giftgram_demo"}
    if not init_data:
        raise HTTPException(401, "Открой GiftGram через Telegram.")
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            raise ValueError("missing hash")
        auth_date = int(parsed.get("auth_date", "0"))
        if time.time() - auth_date > 86400:
            raise HTTPException(401, "Сессия устарела. Закрой и снова открой Mini App.")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            raise ValueError("bad hash")
        user = json.loads(parsed["user"])
        if not user.get("id"):
            raise ValueError("missing user id")
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Не удалось подтвердить Telegram-сессию.")

def current_user(authorization: str | None):
    init_data = ""
    if authorization and authorization.startswith("tma "):
        init_data = authorization[4:]
    user = validate_init_data(init_data)
    upsert_user(user)
    return user

@dp.message(CommandStart())
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 Открыть GiftGram", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await message.answer(
        "🎁 <b>GiftGram</b>\n\n"
        "Собирай игровые ⭐, открывай кейсы и прокачивай коллекцию NFT.\n"
        "Нажми кнопку ниже, чтобы открыть приложение.",
        reply_markup=keyboard
    )

@dp.message()
async def help_message(message: Message):
    await message.answer("Нажми /start, чтобы открыть GiftGram.")

app = FastAPI(title="GiftGram Mini App")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "Web", "web")

app = FastAPI(title="GiftGram Mini App")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WEB_DIR = None
INDEX_FILE = None

for root, dirs, files in os.walk(BASE_DIR):
    index_name = next(
        (f for f in files if f.lower() == "index.html"), None
    )
    style_name = next(
        (f for f in files if f.lower() == "style.css"), None
    )

    if index_name and style_name:
        WEB_DIR = root
        INDEX_FILE = os.path.join(root, index_name)
        break

if WEB_DIR is None:
    raise RuntimeError(
        "Не найдены index.html и style.css в одной папке."
    )

@app.get("/")
async def index():
    return FileResponse(INDEX_FILE)

app.mount(
    "/static",
    StaticFiles(directory=WEB_DIR),
    name="static"
)






@app.get("/api/me")
async def me(authorization: str | None = Header(default=None)):
    tg = current_user(authorization)
    uid = int(tg["id"])
    user = get_user(uid)
    with connect() as con:
        nfts = con.execute("SELECT * FROM nfts WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    return {
        "user": {"id": uid, "first_name": user["first_name"], "username": user["username"]},
        "stars": user["stars"],
        "last_daily": user["last_daily"],
        "nfts": [dict(n) for n in nfts]
    }

@app.post("/api/daily")
async def daily(authorization: str | None = Header(default=None)):
    tg = current_user(authorization)
    uid = int(tg["id"])
    today = datetime.now(timezone.utc).date().isoformat()
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if user["last_daily"] == today:
            raise HTTPException(409, "Ежедневная награда уже получена. Возвращайся завтра!")
        reward = 100
        con.execute("UPDATE users SET stars=stars+?, last_daily=? WHERE user_id=?", (reward, today, uid))
        balance = con.execute("SELECT stars FROM users WHERE user_id=?", (uid,)).fetchone()["stars"]
    return {"ok": True, "reward": reward, "stars": balance}

PRIZES = [
    {"name": "Пиксельный кот", "rarity": "Обычный", "weight": 45, "emoji": "🐈"},
    {"name": "Кристальный череп", "rarity": "Редкий", "weight": 30, "emoji": "💎"},
    {"name": "Неоновая маска", "rarity": "Эпический", "weight": 17, "emoji": "🎭"},
    {"name": "Золотой дракон", "rarity": "Легендарный", "weight": 7, "emoji": "🐉"},
    {"name": "Космический призрак", "rarity": "Мифический", "weight": 1, "emoji": "👻"},
]
CASE_COST = 50

@app.post("/api/case")
async def open_case(authorization: str | None = Header(default=None)):
    tg = current_user(authorization)
    uid = int(tg["id"])
    with connect() as con:
        user = con.execute("SELECT stars FROM users WHERE user_id=?", (uid,)).fetchone()
        if user["stars"] < CASE_COST:
            raise HTTPException(400, "Не хватает звёзд. Забери ежедневную награду!")
        prize = random.choices(PRIZES, weights=[p["weight"] for p in PRIZES], k=1)[0]
        con.execute("UPDATE users SET stars=stars-? WHERE user_id=?", (CASE_COST, uid))
        cur = con.execute(
            "INSERT INTO nfts(user_id,name,rarity,level,created_at) VALUES(?,?,?,1,?)",
            (uid, prize["name"], prize["rarity"], datetime.now(timezone.utc).isoformat())
        )
        balance = con.execute("SELECT stars FROM users WHERE user_id=?", (uid,)).fetchone()["stars"]
        nft_id = cur.lastrowid
    return {"ok": True, "stars": balance, "nft": {"id": nft_id, "name": prize["name"],
            "rarity": prize["rarity"], "level": 1, "emoji": prize["emoji"]}}

@app.post("/api/upgrade/{nft_id}")
async def upgrade(nft_id: int, authorization: str | None = Header(default=None)):
    tg = current_user(authorization)
    uid = int(tg["id"])
    with connect() as con:
        nft = con.execute("SELECT * FROM nfts WHERE id=? AND user_id=?", (nft_id, uid)).fetchone()
        if not nft:
            raise HTTPException(404, "NFT не найден.")
        cost = int(nft["level"]) * 40
        user = con.execute("SELECT stars FROM users WHERE user_id=?", (uid,)).fetchone()
        if user["stars"] < cost:
            raise HTTPException(400, f"Для улучшения нужно {cost} ⭐.")
        con.execute("UPDATE users SET stars=stars-? WHERE user_id=?", (cost, uid))
        con.execute("UPDATE nfts SET level=level+1 WHERE id=?", (nft_id,))
        balance = con.execute("SELECT stars FROM users WHERE user_id=?", (uid,)).fetchone()["stars"]
        new_level = int(nft["level"]) + 1
    return {"ok": True, "stars": balance, "level": new_level, "cost": cost}

@app.get("/api/health")
async def health():
    return {"ok": True, "app": "GiftGram"}

async def run():
    init_db()
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(dp.start_polling(bot), server.serve())

if __name__ == "__main__":
    asyncio.run(run())

