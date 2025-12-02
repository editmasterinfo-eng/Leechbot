import os
import sys

# -------------------------------------------------------------------------
# PATCH FOR PYTHON 3.10+ (CRITICAL FOR MEGA LIBRARY)
# Is part ko mat hatana, warna "AttributeError: module 'collections' has no attribute 'Iterable'" aayega.
import collections.abc
if not hasattr(collections, 'Iterable'):
    collections.Iterable = collections.abc.Iterable
if not hasattr(collections, 'Mapping'):
    collections.Mapping = collections.abc.Mapping
if not hasattr(collections, 'MutableMapping'):
    collections.MutableMapping = collections.abc.MutableMapping
# -------------------------------------------------------------------------

import time
import math
import asyncio
import threading
import logging
import re
import gdown
import psutil
from mega import Mega  # Mega Library
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# --- Global Variables ---
CONCURRENCY_LIMIT = 3
semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
ACTIVE_TASKS = {}  # Store tasks for cancellation
ANIMATION_FRAMES = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
animation_index = 0

# --- Logging & Web Server (Keep Alive) ---
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
def home(): return "Bot is Alive & Running"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()

bot = Client("bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# --- Helper Functions ---
def humanbytes(size):
    if not size: return "0 B"
    power=1024; n=0; dic_powerN={0:'B', 1:'KiB', 2:'MiB', 3:'GiB', 4:'TiB'}
    while size>power: size/=power; n+=1
    return f"{round(size, 2)} {dic_powerN[n]}"

def time_formatter(milliseconds: int) -> str:
    s, ms = divmod(int(milliseconds), 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    return ((f"{d}d, " if d else "") + (f"{h}h, " if h else "") + (f"{m}m, " if m else "") + (f"{s}s, " if s else "")).strip(', ') or "0s"

def get_system_stats():
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    return f"**🖥️ CPU:** {cpu_usage}% | **🧠 RAM:** {ram_usage}%"

async def progress_bar(current, total, message_obj, start_time, status_text):
    global animation_index
    now=time.time()
    diff=now-start_time
    
    if round(diff % 4.00)==0 or current==total:
        p=current*100/total
        s=current/diff if diff > 0 else 0
        eta=round((total-current)/s)*1000 if s>0 else 0
        
        loader = ANIMATION_FRAMES[animation_index % len(ANIMATION_FRAMES)]
        animation_index += 1
        
        filled_blocks = math.floor(p/5)
        empty_blocks = 20 - filled_blocks
        prog = "[{0}{1}]".format('■' * filled_blocks, '□' * empty_blocks)
        
        tmp = (f"{prog} {round(p,2)}%\n"
               f"**📦 Done:** {humanbytes(current)}/{humanbytes(total)}\n"
               f"**🚀 Speed:** {humanbytes(s)}/s | **⏳ ETA:** {time_formatter(eta)}\n\n"
               f"{get_system_stats()}\n\n"
               f"**{status_text}** {loader}")
        try:
            await message_obj.edit_text(text=tmp)
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Progress bar error: {e}")

async def edit_status(message, text):
    try:
        await message.edit_text(f"{text}\n\n{get_system_stats()}")
    except MessageNotModified:
        pass

# --- UI & Control Handlers ---
@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    txt = (f"👋 **Hello {m.from_user.first_name}!**\n\n"
           "I can download files from:\n"
           "🔹 **Mega.nz** (Files & Folders)\n"
           "🔹 **Google Drive**\n"
           "🔹 **YouTube/Direct Links**\n\n"
           "Commands:\n"
           "📦 `/bulk <links>`\n"
           "❌ `/cancel`\n"
           "Just send me a link to start!")
    await m.reply_text(txt, quote=True)

@bot.on_message(filters.command(["help"]))
async def help_command(bot: Client, m: Message):
    await m.reply_text("Help: Send any link to download. Use /bulk for multiple links.", quote=True)

@bot.on_message(filters.command(["cancel"]))
async def cancel_tasks_command(bot: Client, m: Message):
    user_id = m.from_user.id
    if user_id in ACTIVE_TASKS and ACTIVE_TASKS[user_id]:
        count = 0
        for task in ACTIVE_TASKS[user_id].values():
            task.cancel()
            count += 1
        await m.reply_text(f"✅ Cancelled {count} active tasks.")
    else:
        await m.reply_text("🤷‍♂️ No active tasks found.")

# --- CORE DOWNLOAD LOGIC ---
async def process_link(client: Client, m: Message, url: str, status_msg: Message):
    downloaded_file = None
    try:
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        # --- GOOGLE DRIVE ---
        if "drive.google.com" in url:
            await edit_status(status_msg, "📥 Downloading from Google Drive...")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=True))
            if not downloaded_file: raise Exception("File not found or private.")

        # --- MEGA.NZ ---
        elif "mega.nz" in url:
            await edit_status(status_msg, "📥 Downloading from Mega.nz...")
            mega = Mega()
            m_mega = mega.login() # Anonymous login
            
            # Handling: https://mega.nz/folder/ID#Key/file/FileID
            if "/folder/" in url and "/file/" in url:
                try:
                    folder_url = url.split("/file/")[0]
                    target_file_id = url.split("/file/")[1]
                    
                    files = m_mega.get_public_url_info(folder_url)
                    target_node = None
                    
                    # Mega sometimes returns list, sometimes dict
                    node_list = files.values() if isinstance(files, dict) else files
                    
                    for node in node_list:
                        if isinstance(node, dict) and node.get('h') == target_file_id:
                            target_node = node
                            break
                    
                    if target_node:
                        downloaded_file = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: m_mega.download(target_node)
                        )
                    else:
                        raise Exception("Specific file not found in Mega folder.")
                except Exception as e:
                    raise Exception(f"Mega Folder Error: {e}")
            
            # Handling: Standard File Link or Folder Link
            else:
                try:
                    downloaded_file = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: m_mega.download_url(url)
                    )
                except Exception as e:
                    raise Exception(f"Mega Download Error: {e}")

        # --- YOUTUBE-DL / DIRECT LINKS ---
        else:
            await edit_status(status_msg, "🔎 Analyzing Link...")
            ydl_opts = {
                'outtmpl': '%(title)s @skillneast.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'logger': MyLogger()
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                downloaded_file = ydl.prepare_filename(info)

        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception("Download Failed. File not found on disk.")

        # --- RENAMING (If not already done by YTDLP) ---
        if "@skillneast" not in downloaded_file:
            name, ext = os.path.splitext(downloaded_file)
            new_name = f"{name} @skillneast{ext}"
            os.rename(downloaded_file, new_name)
            downloaded_file = new_name

        # --- UPLOADING ---
        base_name = os.path.basename(downloaded_file)
        await edit_status(status_msg, f"⬆️ Uploading: `{base_name}`")
        caption = f"📂 **{base_name}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"
        
        progress_args = (status_msg, time.time(), f"⬆️ Uploading...")
        
        if downloaded_file.lower().endswith(video_extensions):
            await m.reply_video(
                video=downloaded_file, 
                caption=caption, 
                supports_streaming=True, 
                progress=progress_bar, 
                progress_args=progress_args
            )
        else:
            await m.reply_document(
                document=downloaded_file, 
                caption=caption, 
                progress=progress_bar, 
                progress_args=progress_args
            )
        
        await status_msg.delete()

    except asyncio.CancelledError:
        await status_msg.edit_text("❌ **Task Cancelled by User**")
        raise
    except Exception as e:
        error_text = str(e).replace('ERROR:', '').strip()
        await status_msg.edit_text(f"❌ **Error:**\n`{error_text}`")
    finally:
        # Cleanup
        if downloaded_file and os.path.exists(downloaded_file):
            try: os.remove(downloaded_file)
            except: pass

async def run_task_with_cancellation(user_id, msg_id, awaitable_task):
    task = asyncio.create_task(awaitable_task)
    if user_id not in ACTIVE_TASKS: ACTIVE_TASKS[user_id] = {}
    ACTIVE_TASKS[user_id][msg_id] = task
    
    try:
        await task
    except asyncio.CancelledError:
        raise
    finally:
        if user_id in ACTIVE_TASKS and msg_id in ACTIVE_TASKS[user_id]:
            del ACTIVE_TASKS[user_id][msg_id]
            if not ACTIVE_TASKS[user_id]:
                del ACTIVE_TASKS[user_id]

async def run_process_wrapper(client, m, url):
    async with semaphore:
        status_msg = await m.reply_text(f"⏳ **Queued:** `{url}`")
        try:
            await run_task_with_cancellation(
                m.from_user.id,
                status_msg.id,
                process_link(client, m, url, status_msg)
            )
            return True
        except:
            return False

# --- Main Message Handlers ---

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    
    if len(m.command) > 1: raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text: raw_text = m.reply_to_message.text
    else: return await m.reply_text("**Usage:** `/bulk <link1> <link2> ...`")
        
    links = re.findall(r'https?://[^\s]+', raw_text)
    if not links: return await m.reply_text("❓ No valid links found.")
        
    total_links = len(links)
    completed = 0
    failed = 0
    
    bulk_msg = await m.reply_text(f"📦 **Bulk Queue Started!**\nLinks: {total_links}")
    
    tasks = [run_process_wrapper(bot, m, link) for link in links]
    
    for future in asyncio.as_completed(tasks):
        res = await future
        if res: completed += 1
        else: failed += 1
        try:
            await bulk_msg.edit_text(f"📦 **Bulk Progress:** {completed+failed}/{total_links}\n✅ {completed} | ❌ {failed}")
        except: pass
            
    await bulk_msg.edit_text(f"✅ **Bulk Finished!**\nTotal: {total_links} | Success: {completed} | Failed: {failed}")

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "cancel"]))
async def single_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        status_msg = await m.reply_text("🚀 **Initializing...**", quote=True)
        try:
            await run_task_with_cancellation(
                m.from_user.id,
                status_msg.id,
                process_link(bot, m, url, status_msg)
            )
        except:
            pass # Errors handled inside process_link

# --- EXECUTION ---
if __name__ == "__main__":
    print("Starting Web Server...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
