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
ACTIVE_TASKS = {}  # To store and manage active tasks for cancellation {user_id: {msg_id: task}}
ANIMATION_FRAMES = ["â¢¿", "â£»", "â£½", "â£¾", "â£·", "â£¯", "â£Ÿ", "â¡¿"]
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
    """Returns a formatted string of system stats."""
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    stats = f"**ðŸ–¥ï¸ CPU:** {cpu_usage}% | **ðŸ§  RAM:** {ram_usage}%"
    try:
        # Note: Temperature may not be available on all systems/platforms (like Render/Heroku)
        temps = psutil.sensors_temperatures()
        if temps and 'coretemp' in temps:
            core_temps = [temp.current for temp in temps['coretemp']]
            avg_temp = sum(core_temps) / len(core_temps)
            stats += f" | **ðŸŒ¡ï¸ Temp:** {avg_temp:.1f}Â°C"
    except (AttributeError, KeyError):
        pass # Silently ignore if temp sensors are not found
    return stats

async def progress_bar(current, total, message_obj, start_time, status_text):
    global animation_index
    now=time.time(); diff=now-start_time
    if round(diff % 4.00)==0 or current==total:
        p=current*100/total; s=current/diff if diff > 0 else 0; eta=round((total-current)/s)*1000 if s>0 else 0
        
        loader = ANIMATION_FRAMES[animation_index % len(ANIMATION_FRAMES)]
        animation_index += 1

        prog = "[{0}{1}] \n**ðŸ“Š Progress:** {2}%\n".format(''.join(["â– " for i in range(math.floor(p/5))]), ''.join(["â–¡" for i in range(20-math.floor(p/5))]), round(p,2))
        tmp = (f"{prog}**ðŸ“¦ Done:** {humanbytes(current)}/{humanbytes(total)}\n"
               f"**ðŸš€ Speed:** {humanbytes(s)}/s\n"
               f"**â³ ETA:** {time_formatter(eta)}\n\n"
               f"{get_system_stats()}\n\n"
               f"**{status_text}** {loader}")
        try:
            await message_obj.edit_text(text=tmp)
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Progress bar update error: {e}")

async def edit_status(message, text):
    """Edits a message with a live loader and stats."""
    global animation_index
    loader = ANIMATION_FRAMES[animation_index % len(ANIMATION_FRAMES)]
    animation_index += 1
    try:
        await message.edit_text(f"{text} {loader}\n\n{get_system_stats()}")
    except MessageNotModified:
        pass

# --- UI/UX & CONTROL COMMANDS ---
@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    welcome_text = f"""
ðŸ‘‹ **Hello, {m.from_user.first_name}!**

Mein ek file downloader bot hoon. Aap mujhe direct download links (jaise Google Drive) ya YouTube video links de sakte hain, aur main unhe download karke aapko bhej dunga.

**Khaas Features:**
ðŸ”¹ **Google Drive & YouTube-DL Support.**
ðŸ”¹ **Bulk Downloader:** `/bulk` se ek saath kai links download karein.
ðŸ”¹ **Live Status:** Har download me live speed, progress aur system usage dekhein.
ðŸ”¹ **Cancellation:** `/cancel` command se kisi bhi download ko rokein.

Shuru karne ke liye, mujhe koi link bhejein ya `/help` command ka istemal karein.
"""
    welcome_image = "https://i.imgur.com/v1L4y2g.jpeg"
    await m.reply_photo(photo=welcome_image, caption=welcome_text, quote=True)

@bot.on_message(filters.command(["help"]))
async def help_command(bot: Client, m: Message):
    help_text = """
ðŸ“œ **Bot Help Section**

Yahan bot ke sabhi commands ki jaankari hai:

ðŸš€ **/start**
- Bot ko start karein aur welcome message dekhein.

ðŸ¤ **/help**
- Is help message ko dekhein.

ðŸ“¦ **/bulk** ` <link1> <link2> ...`
- Ek saath kai links download karein.

âŒ **/cancel**
- Aapke shuru kiye gaye sabhi downloads ko cancel kar dega.
- Agar aap kisi download status message ko reply karke is command ko bhejenge, to sirf wahi download cancel hoga.

ðŸ”— **Direct Link Download**
- Bot ko koi bhi link bhejein, aur woh use download kar dega.
"""
    await m.reply_text(help_text, quote=True)

@bot.on_message(filters.command(["cancel"]))
async def cancel_tasks_command(bot: Client, m: Message):
    user_id = m.from_user.id
    
    # Specific task cancellation
    if m.reply_to_message:
        msg_id_to_cancel = m.reply_to_message.id
        if user_id in ACTIVE_TASKS and msg_id_to_cancel in ACTIVE_TASKS[user_id]:
            task_to_cancel = ACTIVE_TASKS[user_id][msg_id_to_cancel]
            task_to_cancel.cancel()
            await m.reply_text(f"âœ… Task `{msg_id_to_cancel}` ko cancel karne ka request bhej diya gaya hai.")
        else:
            await m.reply_text("âŒ Is message se juda koi active task nahi mila.")
        return

    # Global cancellation for the user
    if user_id in ACTIVE_TASKS and ACTIVE_TASKS[user_id]:
        count = 0
        for task in ACTIVE_TASKS[user_id].values():
            task.cancel()
            count += 1
        await m.reply_text(f"âœ… Aapke sabhi `{count}` active tasks ko cancel karne ka request bhej diya gaya hai.")
    else:
        await m.reply_text("ðŸ¤·â€â™‚ï¸ Aapka koi bhi task active nahi hai.")

# --- MAIN LOGIC ---
async def process_link(client: Client, m: Message, url: str, status_msg: Message):
    downloaded_file = None
    try:
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        if "drive.google.com" in url:
            await edit_status(status_msg, "ðŸ“¥ Downloading from Google Drive...")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=True))
            if downloaded_file is None: raise Exception("File not found or permission denied.")
            
            name, ext = os.path.splitext(downloaded_file)
            final_filename = f"{name} @skillneast{ext}"
            os.rename(downloaded_file, final_filename)
            downloaded_file = final_filename

        else: # YouTube-DL links
            await edit_status(status_msg, "ðŸ”Ž Analyzing Link...")
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                safe_title = "".join(c for c in info.get('title', 'file') if c.isalnum() or c in ' -_').strip() or f"file_{int(time.time())}"
                downloaded_file = f"{safe_title} @skillneast.{info.get('ext', 'mp4')}"
            
            await edit_status(status_msg, f"â¬‡ï¸ Downloading: `{safe_title}`")
            ydl_opts_down = {'outtmpl': downloaded_file, 'logger': MyLogger(), 'progress_hooks': [lambda d: None]}
            await asyncio.get_event_loop().run_in_executor(None, lambda: YoutubeDL(ydl_opts_down).download([url]))
            if not os.path.exists(downloaded_file): raise Exception("Download Failed.")

        base_name = os.path.basename(downloaded_file)
        await edit_status(status_msg, f"â¬†ï¸ Uploading: `{base_name}`")
        caption = f"ðŸ“‚ **{base_name}**\n\nðŸ‘¤ **User:** {m.from_user.mention}\nðŸ¤– **Bot:** @skillneast"
        progress_args = (status_msg, time.time(), f"â¬†ï¸ Uploading...")
        
        if downloaded_file.lower().endswith(video_extensions):
            await m.reply_video(video=downloaded_file, caption=caption, supports_streaming=True, progress=progress_bar, progress_args=progress_args)
        else:
            await m.reply_document(document=downloaded_file, caption=caption, progress=progress_bar, progress_args=progress_args)
        
        await status_msg.delete()
            
    except asyncio.CancelledError:
        await status_msg.edit_text("âŒ **Task Cancelled by User**")
        raise # Re-throw to be caught by the handler
    except Exception as e:
        error_text = str(e).replace('ERROR:', '').strip()
        await status_msg.edit_text(f"âŒ **Error:**\n`{error_text}`")
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
        # The error is already handled in process_link, just re-raise for bulk handler
        raise
    finally:
        if user_id in ACTIVE_TASKS and msg_id in ACTIVE_TASKS[user_id]:
            del ACTIVE_TASKS[user_id][msg_id]
            if not ACTIVE_TASKS[user_id]:
                del ACTIVE_TASKS[user_id]

# Wrapper for bulk processing
async def run_process_wrapper(client, m, url):
    async with semaphore:
        status_msg = await m.reply_text(f"â³ **Queued:** `{url}`")
        try:
            await run_task_with_cancellation(
                m.from_user.id,
                status_msg.id,
                process_link(client, m, url, status_msg)
            )
            return True # Success
        except (Exception, asyncio.CancelledError):
            return False # Failure or Cancelled

# --- HANDLERS ---
@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    
    if len(m.command) > 1: raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text: raw_text = m.reply_to_message.text
    else: return await m.reply_text("**Usage:** `/bulk <link1> <link2> ...`")
        
    links = re.findall(r'https?://[^\s]+', raw_text)
    if not links: return await m.reply_text("â“ Diye gaye text me koi valid link nahi mila.")
        
    total_links = len(links)
    completed = 0
    failed = 0
    
    bulk_status_msg = await m.reply_text(f"ðŸ“¦ **Bulk Queue Started!**\n\nTotal Links: {total_links} | Concurrency: {CONCURRENCY_LIMIT}")
    
    tasks = [run_process_wrapper(bot, m, link) for link in links]
    
    for future in asyncio.as_completed(tasks):
        result = await future
        if result: completed += 1
        else: failed += 1
            
        try:
            await bulk_status_msg.edit_text(
                f"ðŸ“¦ **Bulk Progress...**\n\n"
                f"**ðŸ“Š Status:** {completed + failed} / {total_links}\n"
                f"**âœ… Completed:** {completed}\n"
                f"**âŒ Failed/Cancelled:** {failed}"
            )
        except MessageNotModified: pass
            
    await bulk_status_msg.edit_text(
        f"âœ… **Bulk Complete!**\n\n"
        f"**Total:** {total_links} | **Successful:** {completed} | **Failed/Cancelled:** {failed}"
    )

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "cancel"]))
async def single_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        status_msg = await m.reply_text("ðŸš€ Preparing to download...", quote=True)
        try:
            await run_task_with_cancellation(
                m.from_user.id,
                status_msg.id,
                process_link(bot, m, url, status_msg)
            )
        except (Exception, asyncio.CancelledError):
            # Errors are already logged and message edited within the process.
            pass

# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("Starting Flask Server for Keep-Alive...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
