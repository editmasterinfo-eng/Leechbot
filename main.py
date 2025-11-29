import os
import sys
import time
import math
import asyncio
import threading
import logging
import re
from functools import partial
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL
import gdown

# ------------------- CRITICAL FIX FOR 'NoneType' object has no attribute 'write' -------------------
class DummyWriter:
    def write(self, *args, **kwargs): pass
    def flush(self, *args, **kwargs): pass

if sys.stdout is None: sys.stdout = DummyWriter()
if sys.stderr is None: sys.stderr = DummyWriter()

# ------------------- LOGGING SETUP -------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# ------------------- YT-DLP SILENT LOGGER -------------------
class MyLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): print(f"YT-DLP Error: {msg}")

# ------------------- RENDER KEEP ALIVE (FLASK) -------------------
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is Alive & Running"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()

# ------------------- BOT SETUP -------------------
bot = Client("bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Global dictionary to prevent spamming message edits
progress_last_update = {}

# ------------------- HELPER FUNCTIONS -------------------
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
    return ((f"{days}d, " if days else "") +
            (f"{hours}h, " if hours else "") +
            (f"{minutes}m, " if minutes else "") +
            (f"{seconds}s, " if seconds else "")).strip(', ') or "0s"

async def progress_bar(current, total, message_obj, start_time, status_text):
    now = time.time()
    diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        
        progress_str = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(
            ''.join(["■" for _ in range(math.floor(percentage / 5))]),
            ''.join(["□" for _ in range(20 - math.floor(percentage / 5))]),
            round(percentage, 2))

        tmp = (progress_str +
               f"**📦 Done:** {humanbytes(current)} / {humanbytes(total)}\n"
               f"**🚀 Speed:** {humanbytes(speed)}/s\n"
               f"**⏳ ETA:** {time_formatter(time_to_completion)}\n\n"
               f"**{status_text}**")
        try:
            await message_obj.edit_text(text=tmp)
        except Exception:
            pass

# ------------------- DOWNLOAD LOGIC -------------------

async def download_progress_hook(d, message_obj, start_time, loop):
    if d['status'] == 'downloading':
        message_id = message_obj.id
        now = time.time()
        
        if message_id not in progress_last_update or (now - progress_last_update.get(message_id, 0)) > 3:
            progress_last_update[message_id] = now
            
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total_bytes:
                downloaded_bytes = d.get('downloaded_bytes', 0)
                percentage = (downloaded_bytes / total_bytes) * 100
                speed = d.get('speed')
                eta = d.get('eta')

                progress_str = "[{0}{1}] \n**📊 Progress:** {2:.2f}%\n".format(
                    ''.join(["■" for _ in range(math.floor(percentage / 5))]),
                    ''.join(["□" for _ in range(20 - math.floor(percentage / 5))]),
                    percentage)

                tmp = (progress_str +
                       f"**📦 Done:** {humanbytes(downloaded_bytes)} / {humanbytes(total_bytes)}\n"
                       f"**🚀 Speed:** {humanbytes(speed) if speed else 0}/s\n"
                       f"**⏳ ETA:** {time_formatter(eta * 1000) if eta else 'N/A'}\n\n"
                       f"**⬇️ Downloading...**")
                
                async def edit_message():
                    try:
                        await message_obj.edit_text(text=tmp)
                    except Exception:
                        pass
                
                asyncio.run_coroutine_threadsafe(edit_message(), loop)

async def process_link(client, m, url, is_bulk=False):
    status_msg = await m.reply_text("🔎 **Analyzing Link...**", quote=True)
    final_filename = None
    
    try:
        if "drive.google.com" in url:
            await status_msg.edit_text("📥 **Downloading from Google Drive...**\n_(Progress bar not available for G-Drive)_")
            final_filename = await asyncio.get_event_loop().run_in_executor(
                None, lambda: gdown.download(url, fuzzy=True, quiet=False)
            )
            if final_filename is None:
                raise Exception("File not found or permission denied on Google Drive.")
        else:
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info_dict = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                original_title = info_dict.get('title', 'Unknown_File')
                ext = info_dict.get('ext', 'mp4')
                safe_title = "".join([c for c in original_title if c.isalnum() or c in (' ', '-', '_')]).strip()
                if not safe_title: safe_title = f"file_{int(time.time())}"
                final_filename = f"{safe_title} @skillneast.{ext}"

            await status_msg.edit_text(f"⬇️ **Downloading:** `{safe_title}`")
            download_start = time.time()
            main_loop = asyncio.get_event_loop()
            hook = partial(download_progress_hook, message_obj=status_msg, start_time=download_start, loop=main_loop)
            
            ydl_opts_down = {
                'outtmpl': final_filename, 'logger': MyLogger(),
                'nocheckcertificate': True, 'progress_hooks': [hook],
                'concurrent_fragment_downloads': 5, 'buffersize': 1024*256,
            }
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: YoutubeDL(ydl_opts_down).download([url])
            )

            if not os.path.exists(final_filename):
                found = False
                for file in os.listdir('.'):
                    if file.startswith(safe_title):
                        final_filename, found = file, True
                        break
                if not found:
                    await status_msg.edit_text("❌ Download Failed. File not found.")
                    return

        await status_msg.edit_text(f"⬆️ **Uploading:** `{os.path.basename(final_filename)}`")
        upload_start = time.time()
        caption_text = f"📂 **{os.path.basename(final_filename)}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        if final_filename.lower().endswith(video_extensions):
            await m.reply_video(
                video=final_filename, caption=caption_text, supports_streaming=True,
                progress=progress_bar, progress_args=(status_msg, upload_start, "⬆️ Uploading Video...")
            )
        else:
            await m.reply_document(
                document=final_filename, caption=caption_text,
                progress=progress_bar, progress_args=(status_msg, upload_start, "⬆️ Uploading File...")
            )

        await status_msg.delete()
        if final_filename and os.path.exists(final_filename): os.remove(final_filename)
        if is_bulk: await asyncio.sleep(3)

    except Exception as e:
        logger.error(f"Error in process_link: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **An Error Occurred:**\n`{str(e)}`")
        if final_filename and os.path.exists(final_filename): os.remove(final_filename)

# ------------------- COMMANDS -------------------
@bot.on_message(filters.command(["start"]))
async def start_command(bot, m: Message):
    await m.reply_text(
        f"👋 **Hi {m.from_user.first_name}! Main ek URL Downloader Bot hoon.**\n\n"
        "Aap mujhe koi bhi direct link (YouTube, Instagram, Google Drive, etc.) bhej sakte hain aur main use download karke aapko bhej dunga.\n\n"
        "Commands ke baare mein jaanne ke liye /help type karein.", quote=True
    )

@bot.on_message(filters.command(["help"]))
async def help_command(bot, m: Message):
    await m.reply_text(
        "**📜 Bot Help Section**\n\n"
        "**Kaise Use Karein:**\n"
        "1.  **Single Link**: Bas mujhe koi bhi download link chat mein bhejein.\n"
        "2.  **Multiple Links**: Ek saath kai links download karne ke liye `/bulk` command ka istemaal karein.\n\n"
        "**Commands:**\n"
        "🔹 `/start` - Bot ko start karne ke liye.\n"
        "🔹 `/help` - Yeh help message dekhne ke liye.\n"
        "🔹 `/bulk <link1> <link2> ...` - Ek saath multiple links download karne ke liye. Aap links ko space ya agli line mein daal kar bhej sakte hain.", quote=True
    )

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users:
        return await m.reply_text("🚫 You are not authorized to use this command.")
    
    if len(m.command) > 1: raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text: raw_text = m.reply_to_message.text
    else: return await m.reply_text("**Usage:** `/bulk <link1> <link2> ...`\nAap command ke baad links de sakte hain ya kisi message ko reply karke jisme links ho.")

    links = re.findall(r'https?://[^\s]+', raw_text)
    if not links: return await m.reply_text("❓ No valid links found in the message.")
        
    await m.reply_text(f"📦 **Bulk Queue Started:** Found {len(links)} links. Processing one by one...")
    for i, link in enumerate(links, 1):
        await m.reply_text(f"**Processing Link {i}/{len(links)}:**\n`{link}`")
        await process_link(bot, m, link, is_bulk=True)
    await m.reply_text("✅ **Bulk Download Complete!** All links have been processed.")

# THIS IS THE FIXED LINE
@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk"]))
async def single_download(bot, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users:
        return
        
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        await process_link(bot, m, url, is_bulk=False)

# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("Starting Flask Server for Keep-Alive...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
