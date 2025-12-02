import os
import sys

# --- PATCH FOR OLD LIBRARIES (MEGA.PY FIX) ---
# Ye code mega.py ke purane errors ko fix karega
import collections.abc
if not hasattr(collections, 'Iterable'):
    collections.Iterable = collections.abc.Iterable
if not hasattr(collections, 'Mapping'):
    collections.Mapping = collections.abc.Mapping
if not hasattr(collections, 'MutableMapping'):
    collections.MutableMapping = collections.abc.MutableMapping
# ---------------------------------------------

import time
import math
import asyncio
import threading
import logging
import re
import gdown
import psutil
from mega import Mega  # Ab ye bina error ke import hoga
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# --- Global Variables ---
CONCURRENCY_LIMIT = 3
semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
ACTIVE_TASKS = {}
ANIMATION_FRAMES = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
animation_index = 0

# --- Boilerplate ---
class DummyWriter:
    def write(self, *args, **kwargs): pass
    def flush(self, *args, **kwargs): pass
if sys.stdout is None: sys.stdout = DummyWriter()
if sys.stderr is None: sys.stderr = DummyWriter()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
class MyLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): print(f"YT-DLP Error: {msg}")
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Alive"
def run_web_server():
    port = int(os.environ.get("PORT", 8080)); app.run(host='0.0.0.0', port=port, use_reloader=False)
def keep_alive():
    t = threading.Thread(target=run_web_server); t.daemon = True; t.start()
bot = Client("bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

def humanbytes(size):
    if not size: return "0 B"
    power=1024; n=0; dic_powerN={0:'B', 1:'KiB', 2:'MiB', 3:'GiB', 4:'TiB'}
    while size>power: size/=power; n+=1
    return f"{round(size, 2)} {dic_powerN[n]}"

def time_formatter(milliseconds: int) -> str:
    s, ms = divmod(int(milliseconds), 1000); m, s = divmod(s, 60); h, m = divmod(m, 60); d, h = divmod(h, 24)
    return ((f"{d}d, " if d else "") + (f"{h}h, " if h else "") + (f"{m}m, " if m else "") + (f"{s}s, " if s else "")).strip(', ') or "0s"

def get_system_stats():
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    return f"**🖥️ CPU:** {cpu_usage}% | **🧠 RAM:** {ram_usage}%"

async def progress_bar(current, total, message_obj, start_time, status_text):
    global animation_index
    now=time.time(); diff=now-start_time
    if round(diff % 4.00)==0 or current==total:
        p=current*100/total; s=current/diff if diff > 0 else 0; eta=round((total-current)/s)*1000 if s>0 else 0
        loader = ANIMATION_FRAMES[animation_index % len(ANIMATION_FRAMES)]
        animation_index += 1
        prog = "[{0}{1}]".format(''.join(["■" for i in range(math.floor(p/5))]), ''.join(["□" for i in range(20-math.floor(p/5))]))
        tmp = (f"{prog} {round(p,2)}%\n**Done:** {humanbytes(current)}/{humanbytes(total)}\n"
               f"**Speed:** {humanbytes(s)}/s | **ETA:** {time_formatter(eta)}\n"
               f"{get_system_stats()}\n**{status_text}** {loader}")
        try: await message_obj.edit_text(text=tmp)
        except MessageNotModified: pass
        except Exception as e: logger.error(f"Progress error: {e}")

async def edit_status(message, text):
    try: await message.edit_text(f"{text}\n\n{get_system_stats()}")
    except MessageNotModified: pass

# --- HANDLERS ---
@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    await m.reply_text("👋 Hello! Send me a Mega, Drive, or YouTube link.", quote=True)

@bot.on_message(filters.command(["cancel"]))
async def cancel_tasks_command(bot: Client, m: Message):
    user_id = m.from_user.id
    if user_id in ACTIVE_TASKS and ACTIVE_TASKS[user_id]:
        for task in ACTIVE_TASKS[user_id].values(): task.cancel()
        await m.reply_text("✅ Tasks Cancelled.")
    else: await m.reply_text("🤷‍♂️ No active tasks.")

# --- PROCESS LOGIC ---
async def process_link(client: Client, m: Message, url: str, status_msg: Message):
    downloaded_file = None
    try:
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        if "drive.google.com" in url:
            await edit_status(status_msg, "📥 Downloading from Drive...")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=True))
            if not downloaded_file: raise Exception("Drive Link Failed.")
            
        elif "mega.nz" in url:
            await edit_status(status_msg, "📥 Downloading from Mega...")
            mega = Mega()
            m_mega = mega.login()
            
            # --- MEGA LOGIC FIX (Folder/File) ---
            if "/folder/" in url and "/file/" in url:
                try:
                    folder_url = url.split("/file/")[0]
                    target_file_id = url.split("/file/")[1]
                    files = m_mega.get_public_url_info(folder_url)
                    target_node = None
                    node_list = files.values() if isinstance(files, dict) else files
                    for node in node_list:
                        if isinstance(node, dict) and node.get('h') == target_file_id:
                            target_node = node
                            break
                    if target_node:
                        downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: m_mega.download(target_node))
                    else: raise Exception("File not found in folder.")
                except Exception as e: raise Exception(f"Mega Logic Error: {e}")
            else:
                try:
                    downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: m_mega.download_url(url))
                except Exception as e: raise Exception(f"Mega Download Error: {e}")

        else: # YT-DLP
            await edit_status(status_msg, "🔎 Analyzing...")
            ydl_opts = {'outtmpl': '%(title)s @skillneast.%(ext)s', 'quiet': True}
            with YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                downloaded_file = ydl.prepare_filename(info)

        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception("Download Failed (File not found).")

        # --- RENAME & UPLOAD ---
        if "@skillneast" not in downloaded_file:
            name, ext = os.path.splitext(downloaded_file)
            new_name = f"{name} @skillneast{ext}"
            os.rename(downloaded_file, new_name)
            downloaded_file = new_name

        base_name = os.path.basename(downloaded_file)
        await edit_status(status_msg, f"⬆️ Uploading: `{base_name}`")
        caption = f"📂 **{base_name}**\n\n🤖 **Bot:** @skillneast"
        
        progress_args = (status_msg, time.time(), f"⬆️ Uploading...")
        if downloaded_file.lower().endswith(video_extensions):
            await m.reply_video(video=downloaded_file, caption=caption, supports_streaming=True, progress=progress_bar, progress_args=progress_args)
        else:
            await m.reply_document(document=downloaded_file, caption=caption, progress=progress_bar, progress_args=progress_args)
        
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            os.remove(downloaded_file)

async def run_process_wrapper(client, m, url):
    async with semaphore:
        status_msg = await m.reply_text(f"⏳ **Queued:** `{url}`")
        await process_link(client, m, url, status_msg)

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    links = re.findall(r'https?://[^\s]+', m.text or "")
    if not links: return await m.reply_text("No links found.")
    await m.reply_text(f"📦 Bulk started for {len(links)} links.")
    for link in links: asyncio.create_task(run_process_wrapper(bot, m, link))

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "cancel"]))
async def single_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    if m.text.startswith("http"):
        status_msg = await m.reply_text("🚀 Starting...", quote=True)
        await process_link(bot, m, m.text.strip(), status_msg)

if __name__ == "__main__":
    keep_alive()
    bot.run()
