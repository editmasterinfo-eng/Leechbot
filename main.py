import os
import sys
import time
import math
import asyncio
import threading
import logging
import re
import subprocess
import redis # Redis library import
from functools import partial
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message

from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL
import gdown

# --- Boilerplate code (Logging, Flask, Helpers) ---
# ... (Yahan saara boilerplate code hai jo pehle tha, use chhod raha hoon) ...
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
async def progress_bar(current, total, message_obj, start_time, status_text, task_info_text=""):
    now=time.time(); diff=now-start_time
    if round(diff % 4.00)==0 or current==total:
        p=current*100/total; s=current/diff; eta=round((total-p)/s)*1000 if s>0 else 0
        prog = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(''.join(["■" for i in range(math.floor(p/5))]), ''.join(["□" for i in range(20-math.floor(p/5))]), round(p,2))
        tmp = (f"{task_info_text}{prog}**📦 Done:** {humanbytes(current)}/{humanbytes(total)}\n**🚀 Speed:** {humanbytes(s)}/s\n**⏳ ETA:** {time_formatter(eta)}\n\n**{status_text}**")
        try: await message_obj.edit_text(text=tmp)
        except Exception: pass
# ------------------------------------------------------------------------------------------

# --- REDIS SETUP (Updated with better checks) ---
db = None
try:
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        db = redis.from_url(redis_url, decode_responses=True)
        # Ping the server to check the connection
        db.ping()
        logger.info("✅✅✅ Successfully connected to Redis database! ✅✅✅")
    else:
        logger.warning("❌ REDIS_URL environment variable not found. Intro feature will be disabled.")
except redis.exceptions.ConnectionError as e:
    logger.error(f"❌❌❌ Failed to connect to Redis: {e} ❌❌❌")
    logger.error("Please check your REDIS_URL in Render.com environment variables.")
except Exception as e:
    logger.error(f"An unexpected error occurred with Redis: {e}")

# --- COMMANDS ---

@bot.on_message(filters.command(["setvideo"]) & filters.user(sudo_users))
async def set_intro_link_db(bot: Client, m: Message):
    if not db:
        return await m.reply_text("❌ **Database Error:**\nBot Redis database se connect nahi hai. Kripya logs check karein.")
    if len(m.command) < 2:
        return await m.reply_text("**Usage:** `/setvideo <direct_download_link>`")
    
    link = m.command[1]
    if not link.startswith(("http://", "https://")):
        return await m.reply_text("❌ Please provide a valid URL.")
        
    try:
        db.set("intro_video_link", link)
        await m.reply_text(f"✅ **Success!** Intro link has been set to:\n`{link}`")
    except Exception as e:
        logger.error(f"Error saving to database: {e}")
        await m.reply_text(f"❌ **Database Error:**\nLink save nahi ho paya. ` {e} `")

@bot.on_message(filters.command(["checkintro"]) & filters.user(sudo_users))
async def check_intro_link_db(bot: Client, m: Message):
    if not db:
        return await m.reply_text("❌ **Database Error:**\nBot Redis database se connect nahi hai.")
    
    link = db.get("intro_video_link")
    if link:
        await m.reply_text(f"✅ **Current intro link is:**\n`{link}`")
    else:
        await m.reply_text("❌ **No intro link found in the database.**\nUse `/setvideo <link>` to set one.")

# --- MAIN LOGIC ---
async def process_link(client: Client, m: Message, url: str, status_msg: Message, task_info_text: str = ""):
    downloaded_file = None
    final_output_file = None
    temp_intro_path = f"temp_intro_{m.id}.mp4"

    try:
        await status_msg.edit_text(f"{task_info_text}🔎 Analyzing Link...")
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        if "drive.google.com" in url:
            await status_msg.edit_text(f"{task_info_text}📥 Downloading main video...")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=False))
            if downloaded_file is None: raise Exception("File not found or permission denied.")

            is_video = downloaded_file.lower().endswith(video_extensions)
            intro_link = db.get("intro_video_link") if db and is_video else None

            if is_video and intro_link:
                await status_msg.edit_text(f"{task_info_text}📥 Downloading intro video...")
                ydl_opts = {'outtmpl': temp_intro_path, 'logger': MyLogger()}
                with YoutubeDL(ydl_opts) as ydl:
                    await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.download([intro_link]))
                
                if not os.path.exists(temp_intro_path):
                    raise Exception("Intro video link se download nahi ho payi.")
                
                await status_msg.edit_text(f"{task_info_text}🖇️ Merging videos...")
                name, ext = os.path.splitext(downloaded_file)
                final_output_file = f"{name} @skillneast{ext}"
                with open("concat_list.txt", "w", encoding="utf-8") as f:
                    f.write(f"file '{os.path.abspath(temp_intro_path)}'\n")
                    f.write(f"file '{os.path.abspath(downloaded_file)}'\n")
                
                ffmpeg_command = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', 'concat_list.txt', '-c', 'copy', final_output_file]
                process = await asyncio.create_subprocess_exec(*ffmpeg_command, stderr=asyncio.subprocess.PIPE)
                _, stderr = await process.communicate()
                if process.returncode != 0: raise Exception(f"FFmpeg Error: {stderr.decode().strip()}")
                os.remove(downloaded_file); downloaded_file = final_output_file
            else:
                name, ext = os.path.splitext(downloaded_file); final_filename = f"{name} @skillneast{ext}"
                os.rename(downloaded_file, final_filename); downloaded_file = final_filename
        else:
            # ... (baaki links ka logic pehle jaisa hi)
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                safe_title = "".join(c for c in info.get('title', 'file') if c.isalnum() or c in ' -_').strip() or f"file_{int(time.time())}"
                downloaded_file = f"{safe_title} @skillneast.{info.get('ext', 'mp4')}"
            await status_msg.edit_text(f"{task_info_text}⬇️ Downloading: `{safe_title}`")
            ydl_opts_down = {'outtmpl': downloaded_file, 'logger': MyLogger()}
            await asyncio.get_event_loop().run_in_executor(None, lambda: YoutubeDL(ydl_opts_down).download([url]))
            if not os.path.exists(downloaded_file): raise Exception("Download Failed.")

        base_name = os.path.basename(downloaded_file)
        await status_msg.edit_text(f"{task_info_text}⬆️ Uploading: `{base_name}`")
        caption = f"📂 **{base_name}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"
        progress_args = (status_msg, time.time(), "⬆️ Uploading...", task_info_text)
        if downloaded_file.lower().endswith(video_extensions):
            await m.reply_video(video=downloaded_file, caption=caption, supports_streaming=True, progress=progress_bar, progress_args=progress_args)
        else:
            await m.reply_document(document=downloaded_file, caption=caption, progress=progress_bar, progress_args=progress_args)
        if not task_info_text: await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"{task_info_text}❌ **Error:**\n`{str(e)}`"); raise e
    finally:
        if downloaded_file and os.path.exists(downloaded_file): os.remove(downloaded_file)
        if final_output_file and os.path.exists(final_output_file): os.remove(final_output_file)
        if os.path.exists(temp_intro_path): os.remove(temp_intro_path)
        if os.path.exists("concat_list.txt"): os.remove("concat_list.txt")

# --- Baaki saare handlers (/start, /help, /bulk, single_download) pehle jaise hi rahenge ---
# ... (unka code yahan paste karein) ...
@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    await m.reply_text(f"👋 **Hi {m.from_user.first_name}!**\n/help for more info.", quote=True)

@bot.on_message(filters.command(["help"]))
async def help_command(bot: Client, m: Message):
    help_text = ("**📜 Bot Help Section**\n\n"
                 "🔹 `/start` - Start the bot.\n"
                 "🔹 `/help` - Show this message.\n"
                 "🔹 `/bulk <links>` - Download multiple links.\n")
    if m.from_user.id in sudo_users:
        help_text += ("\n**Admin Commands:**\n"
                      "🔹 `/setvideo <url>` - Set intro video from a direct link.\n"
                      "🔹 `/checkintro` - Check the currently set intro video in the database.")
    await m.reply_text(help_text, quote=True)

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    if len(m.command) > 1: raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text: raw_text = m.reply_to_message.text
    else: return await m.reply_text("**Usage:** `/bulk <link1> <link2> ...`")
    links = re.findall(r'https?://[^\s]+', raw_text)
    if not links: return await m.reply_text("❓ No valid links found.")
    total_links, completed, failed = len(links), 0, 0
    bulk_status_msg = await m.reply_text(f"📦 **Bulk Queue Started:** Found {total_links} links.")
    for i, link in enumerate(links, 1):
        task_info = f"**📊 Task:** {i}/{total_links} | **✅ OK:** {completed} | **❌ Fail:** {failed}\n\n"
        try:
            await process_link(bot, m, link, bulk_status_msg, task_info_text=task_info)
            completed += 1
        except Exception:
            failed += 1; await asyncio.sleep(4)
    await bulk_status_msg.edit_text(f"✅ **Bulk Complete!**\n\n**Total:** {total_links}, **Successful:** {completed}, **Failed:** {failed}")

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "setvideo", "checkintro"]))
async def single_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        status_msg = await m.reply_text("🚀 Preparing to download...", quote=True)
        try: await process_link(bot, m, url, status_msg)
        except Exception: pass
        
# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("Starting Flask Server for Keep-Alive...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
