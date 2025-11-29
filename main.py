import os
import sys
import time
import math
import asyncio
import threading
import logging
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# ------------------- CRITICAL FIX FOR 'NoneType' object has no attribute 'write' -------------------
# Ye code ka sabse important hissa hai. Ye fake output create karta hai taaki bot crash na ho.
class DummyWriter:
    def write(self, *args, **kwargs):
        pass
    def flush(self, *args, **kwargs):
        pass

# Agar system ka output None hai, to hum apna DummyWriter laga denge
if sys.stdout is None:
    sys.stdout = DummyWriter()
if sys.stderr is None:
    sys.stderr = DummyWriter()

# ------------------- LOGGING SETUP -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)] # Use patched stdout
)
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
    # Important: use_reloader=False threads ke sath conflicts rokta hai
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()

# ------------------- BOT SETUP -------------------

bot = Client(
    "bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
)

# ------------------- HELPER FUNCTIONS -------------------

def humanbytes(size):
    if not size: return ""
    power = 2**10
    n = 0
    dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + dic_powerN[n] + 'B'

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return ((str(days) + "d, ") if days else "") + \
           ((str(hours) + "h, ") if hours else "") + \
           ((str(minutes) + "m, ") if minutes else "") + \
           ((str(seconds) + "s, ") if seconds else "") + \
           ((str(milliseconds) + "ms, ") if milliseconds else "")

async def progress_bar(current, total, message_obj, start_time, status_text):
    now = time.time()
    diff = now - start_time
    
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        
        progress_str = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(
            ''.join(["■" for i in range(math.floor(percentage / 5))]),
            ''.join(["□" for i in range(20 - math.floor(percentage / 5))]),
            round(percentage, 2))

        tmp = progress_str + \
              f"**📦 Done:** {humanbytes(current)} / {humanbytes(total)}\n" \
              f"**🚀 Speed:** {humanbytes(speed)}/s\n" \
              f"**⏳ ETA:** {time_formatter(time_to_completion)}\n\n" \
              f"**{status_text}**"
        try:
            await message_obj.edit(text=tmp)
        except Exception:
            pass

# ------------------- DOWNLOAD LOGIC -------------------

async def process_video(client, m, url, is_bulk=False):
    status_msg = await m.reply_text(f"🔎 **Analyzing Link...**", quote=True)
    
    try:
        # --- 1. Info Extraction ---
        ydl_opts_info = {
            'logger': MyLogger(), # Silent logger
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'allow_unplayable_formats': True,
        }

        with YoutubeDL(ydl_opts_info) as ydl:
            try:
                info_dict = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                original_title = info_dict.get('title', 'Unknown_File')
                ext = info_dict.get('ext', 'mp4')
                
                # Sanitize filename to prevent errors
                safe_title = "".join([c for c in original_title if c.isalnum() or c in (' ', '-', '_')]).strip()
                if not safe_title: safe_title = f"file_{int(time.time())}"
                
                final_filename = f"{safe_title} @skillneast.{ext}"
                
            except Exception as e:
                await status_msg.edit_text(f"❌ **Link Error:**\n`{str(e)}`")
                return

        # --- 2. Download ---
        await status_msg.edit_text(f"⬇️ **Downloading:** `{safe_title}`")
        
        ydl_opts_down = {
            'outtmpl': final_filename,
            'logger': MyLogger(), # IMPORTANT: Prevent console writing
            'noprogress': True,     # IMPORTANT: No progress bar in console
            'quiet': True,
            'nocheckcertificate': True,
            'allow_unplayable_formats': True,
            'concurrent_fragment_downloads': 5, # Speed boost
            'buffersize': 1024,
        }

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: YoutubeDL(ydl_opts_down).download([url])
        )

        # Check if file exists (Handling ext mismatch)
        if not os.path.exists(final_filename):
            found = False
            for file in os.listdir('.'):
                if file.startswith(safe_title):
                    final_filename = file
                    found = True
                    break
            if not found:
                await status_msg.edit_text("❌ Download Failed. File not found.")
                return

        # --- 3. Upload ---
        await status_msg.edit_text(f"⬆️ **Uploading...**")
        upload_start = time.time()
        
        caption_text = f"📂 **{final_filename}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"

        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')
        
        if final_filename.lower().endswith(video_extensions):
            await m.reply_video(
                video=final_filename,
                caption=caption_text,
                supports_streaming=True,
                progress=progress_bar,
                progress_args=(status_msg, upload_start, "⬆️ Uploading Video...")
            )
        else:
            await m.reply_document(
                document=final_filename,
                caption=caption_text,
                progress=progress_bar,
                progress_args=(status_msg, upload_start, "⬆️ Uploading File...")
            )

        # --- 4. Cleanup ---
        await status_msg.delete()
        if os.path.exists(final_filename):
            os.remove(final_filename)
        
        if is_bulk:
            await asyncio.sleep(2)

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
        if 'final_filename' in locals() and os.path.exists(final_filename):
            os.remove(final_filename)

# ------------------- COMMANDS -------------------

@bot.on_message(filters.command(["start"]))
async def start_command(bot, m: Message):
    await m.reply_text(f"👋 **Hi {m.from_user.first_name}!**\nSend any link.")

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot, m: Message):
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        return
    
    if len(m.command) > 1:
        raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text:
        raw_text = m.reply_to_message.text
    else:
        await m.reply_text("Usage: `/bulk link1 link2`")
        return

    links = [link.strip() for link in raw_text.replace(" ", "\n").split("\n") if link.strip().startswith("http")]
    await m.reply_text(f"📦 **Queue:** {len(links)} Links")

    for link in links:
        await process_video(bot, m, link, is_bulk=True)
    await m.reply_text("✅ Done!")

@bot.on_message(filters.text)
async def single_download(bot, m: Message):
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        return
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        await process_video(bot, m, url, is_bulk=False)

# ------------------- MAIN EXECUTION -------------------

if __name__ == "__main__":
    print("Starting Flask Server (Dummy Writer Active)...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
