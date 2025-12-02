import os
import sys
import time
import math
import asyncio
import threading
import logging
import re
import gdown
import psutil  # System monitoring library
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# --- Global Variables for Concurrency and Cancellation ---
CONCURRENCY_LIMIT = 3
semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
ACTIVE_TASKS = {}  # To store and manage active tasks {user_id: {msg_id: task}}
# Animated Loader Frames
ANIMATION_FRAMES = ["⠷", "⠯", "⠟", "⠻", "⠽", "⠾"]
animation_index = 0

# --- Boilerplate code (Logging, Flask, Helpers) ---
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
    power = 1024
    n = 0
    dic_powerN = {0: 'B', 1: 'KiB', 2: 'MiB', 3: 'GiB', 4: 'TiB'}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)} {dic_powerN[n]}"

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((f"{days}d, " if days else "") +
           (f"{hours}h, " if hours else "") +
           (f"{minutes}m, " if minutes else "") +
           (f"{seconds}s, " if seconds else "")).strip(', ')
    return tmp or "0s"

def get_system_stats():
    """Returns a formatted string of system stats."""
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    return f"🖥 **CPU:** {cpu}%  |  🧠 **RAM:** {ram}%"

# --- IMPROVED PROGRESS BAR UI ---
async def progress_bar(current, total, message_obj, start_time, status_text):
    global animation_index
    now = time.time()
    diff = now - start_time
    
    # Update every 4 seconds or when complete to avoid flood wait
    if round(diff % 4.00) == 0 or current == total:
        # Calculations
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = round((total - current) / speed) * 1000 if speed > 0 else 0
        
        # UI Design Logic
        # Bar Logic: 20 blocks total
        filled_blocks = int(percentage / 5) 
        empty_blocks = 20 - filled_blocks
        bar = "■" * filled_blocks + "□" * empty_blocks
        
        # Loader Animation
        loader = ANIMATION_FRAMES[animation_index % len(ANIMATION_FRAMES)]
        animation_index += 1

        # Final UI Template
        text = (
            f"**{status_text}** {loader}\n\n"
            f"**[{bar}]**\n"
            f"📊 **Progress:** `{round(percentage, 2)}%`\n\n"
            f"📦 **Done:** `{humanbytes(current)}` / `{humanbytes(total)}`\n"
            f"🚀 **Speed:** `{humanbytes(speed)}/s`  |  ⏳ **ETA:** `{time_formatter(eta)}`\n\n"
            f"{get_system_stats()}"
        )
        
        try:
            await message_obj.edit_text(text=text)
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Progress update error: {e}")

async def edit_status(message, text):
    """Edits a message with a live loader and stats."""
    global animation_index
    loader = ANIMATION_FRAMES[animation_index % len(ANIMATION_FRAMES)]
    animation_index += 1
    try:
        await message.edit_text(f"{loader} **{text}**\n\n{get_system_stats()}")
    except MessageNotModified:
        pass

# --- UI/UX & CONTROL COMMANDS ---
@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    welcome_text = f"""
👋 **Hello, {m.from_user.first_name}!**

Main ek advanced downloader bot hoon.
Mujhe koi bhi **Direct Link** ya **YouTube Link** bhejo, main usse download karke dunga.

**Features:**
🔹 Live Progress Bar & Stats
🔹 Google Drive & YouTube Support
🔹 Bulk Download Support (`/bulk`)
🔹 Cancel Support (`/cancel`)

Start karne ke liye link bhejein! 🚀
"""
    # Aap chahein to yahan apni photo laga sakte hain
    await m.reply_text(welcome_text, quote=True)

@bot.on_message(filters.command(["help"]))
async def help_command(bot: Client, m: Message):
    help_text = """
📚 **Help Menu**

🚀 **/start** - Bot ko restart karein.
📦 **/bulk** `link1 link2` - Multiple links ek sath download karein.
❌ **/cancel** - Active tasks ko rokne ke liye.
📎 **Links** - Direct link bhejein download ke liye.
"""
    await m.reply_text(help_text, quote=True)

@bot.on_message(filters.command(["cancel"]))
async def cancel_tasks_command(bot: Client, m: Message):
    user_id = m.from_user.id
    
    # Specific task cancellation (reply karke)
    if m.reply_to_message:
        msg_id_to_cancel = m.reply_to_message.id
        if user_id in ACTIVE_TASKS and msg_id_to_cancel in ACTIVE_TASKS[user_id]:
            task_to_cancel = ACTIVE_TASKS[user_id][msg_id_to_cancel]
            task_to_cancel.cancel()
            await m.reply_text(f"✅ Task `{msg_id_to_cancel}` cancel kar diya gaya hai.")
        else:
            await m.reply_text("❌ Ye task active nahi hai ya aapka nahi hai.")
        return

    # Cancel All
    if user_id in ACTIVE_TASKS and ACTIVE_TASKS[user_id]:
        count = 0
        for task in ACTIVE_TASKS[user_id].values():
            task.cancel()
            count += 1
        await m.reply_text(f"✅ Aapke sabhi `{count}` active tasks cancel kar diye gaye hain.")
    else:
        await m.reply_text("🤷‍♂️ Aapka koi active task nahi hai.")

# --- MAIN LOGIC ---
async def process_link(client: Client, m: Message, url: str, status_msg: Message):
    downloaded_file = None
    try:
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        if "drive.google.com" in url:
            await edit_status(status_msg, "Downloading from Google Drive...")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=True))
            if downloaded_file is None: raise Exception("File not found or permission denied.")
            
            # Rename for credit
            name, ext = os.path.splitext(downloaded_file)
            final_filename = f"{name} @skillneast{ext}"
            os.rename(downloaded_file, final_filename)
            downloaded_file = final_filename

        else: # YouTube-DL links
            await edit_status(status_msg, "Analyzing Link...")
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                safe_title = "".join(c for c in info.get('title', 'file') if c.isalnum() or c in ' -_').strip() or f"file_{int(time.time())}"
                downloaded_file = f"{safe_title} @skillneast.{info.get('ext', 'mp4')}"
            
            await edit_status(status_msg, f"Downloading: `{safe_title}`")
            ydl_opts_down = {'outtmpl': downloaded_file, 'logger': MyLogger(), 'progress_hooks': [lambda d: None]}
            await asyncio.get_event_loop().run_in_executor(None, lambda: YoutubeDL(ydl_opts_down).download([url]))
            if not os.path.exists(downloaded_file): raise Exception("Download Failed.")

        # Uploading Phase
        base_name = os.path.basename(downloaded_file)
        await edit_status(status_msg, f"Uploading: `{base_name}`")
        
        caption = f"📁 **{base_name}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"
        
        # Pass Start Time explicitly for progress bar
        start_time = time.time()
        progress_args = (status_msg, start_time, "⬆️ Uploading...")
        
        if downloaded_file.lower().endswith(video_extensions):
            await m.reply_video(video=downloaded_file, caption=caption, supports_streaming=True, progress=progress_bar, progress_args=progress_args)
        else:
            await m.reply_document(document=downloaded_file, caption=caption, progress=progress_bar, progress_args=progress_args)
        
        await status_msg.delete()
            
    except asyncio.CancelledError:
        await status_msg.edit_text("❌ **Task Cancelled by User**")
        raise 
    except Exception as e:
        error_text = str(e).replace('ERROR:', '').strip()
        await status_msg.edit_text(f"❌ **Error:**\n`{error_text}`")
        raise e
        
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            os.remove(downloaded_file)

async def run_task_with_cancellation(user_id, msg_id, awaitable_task):
    """Adds a task to the tracker and cleans up after completion/cancellation."""
    task = asyncio.create_task(awaitable_task)
    if user_id not in ACTIVE_TASKS:
        ACTIVE_TASKS[user_id] = {}
    ACTIVE_TASKS[user_id][msg_id] = task
    
    try:
        result = await task
        return result
    except asyncio.CancelledError:
        raise
    finally:
        if user_id in ACTIVE_TASKS and msg_id in ACTIVE_TASKS[user_id]:
            del ACTIVE_TASKS[user_id][msg_id]
            if not ACTIVE_TASKS[user_id]:
                del ACTIVE_TASKS[user_id]

# Wrapper for bulk processing
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
        except (Exception, asyncio.CancelledError):
            return False 

# --- HANDLERS ---
@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    
    if len(m.command) > 1: raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text: raw_text = m.reply_to_message.text
    else: return await m.reply_text("ℹ️ **Usage:** `/bulk <link1> <link2>`")
        
    links = re.findall(r'https?://[^\s]+', raw_text)
    if not links: return await m.reply_text("❓ Koi valid link nahi mila.")
        
    total_links = len(links)
    completed = 0
    failed = 0
    
    bulk_status_msg = await m.reply_text(f"📦 **Bulk Queue Started!**\nLinks: {total_links} | Threads: {CONCURRENCY_LIMIT}")
    
    tasks = [run_process_wrapper(bot, m, link) for link in links]
    
    for future in asyncio.as_completed(tasks):
        result = await future
        if result: completed += 1
        else: failed += 1
            
        try:
            await bulk_status_msg.edit_text(
                f"📦 **Bulk Progress**\n"
                f"📊 Status: `{completed + failed}/{total_links}`\n"
                f"✅ Done: `{completed}` | ❌ Failed: `{failed}`"
            )
        except MessageNotModified: pass
            
    await bulk_status_msg.edit_text(
        f"✅ **Bulk Finished!**\n"
        f"Total: {total_links} | Success: {completed} | Failed: {failed}"
    )

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "cancel"]))
async def single_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        status_msg = await m.reply_text("🔎 Checking Link...", quote=True)
        try:
            await run_task_with_cancellation(
                m.from_user.id,
                status_msg.id,
                process_link(bot, m, url, status_msg)
            )
        except (Exception, asyncio.CancelledError):
            pass

# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("Starting Flask Server...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
