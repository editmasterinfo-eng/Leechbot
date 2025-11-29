import os
import time
import math
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# ------------------- RENDER DEPLOYMENT FIX (FLASK SERVER) -------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running"

def run_web_server():
    # Render PORT env variable use karega, default 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()

# ------------------- BOT CONFIGURATION -------------------

bot = Client(
    "bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
)

# ------------------- HELPER FUNCTIONS FOR UI -------------------

def humanbytes(size):
    """Bytes ko readable format mein convert karta hai"""
    if not size:
        return ""
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
    hours, minutes = divmod(hours, 60)
    days, hours = divmod(hours, 24)
    return ((str(days) + "d, ") if days else "") + \
           ((str(hours) + "h, ") if hours else "") + \
           ((str(minutes) + "m, ") if minutes else "") + \
           ((str(seconds) + "s, ") if seconds else "") + \
           ((str(milliseconds) + "ms, ") if milliseconds else "")

async def progress_bar(current, total, message_obj, start_time, status_text):
    """Upload/Download Progress Bar"""
    now = time.time()
    diff = now - start_time
    
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        estimated_total_time = elapsed_time + time_to_completion

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

# ------------------- DOWNLOAD HOOK FOR YT-DLP -------------------
# Ye trick use ki hai taaki yt-dlp ka progress Telegram pe show ho

class DownloadStatus:
    def __init__(self):
        self.message = None
        self.start_time = time.time()
        self.last_update = 0

def my_hook(d):
    if d['status'] == 'downloading':
        try:
            # Global variable ya context use karna mushkil hai hook me, 
            # isliye hum sirf print/log kar rahe hain yahan.
            # Real-time telegram update thread-blocking issue kar sakta hai.
            pass 
        except Exception:
            pass

# ------------------- CORE LOGIC -------------------

async def process_video(client, m, url, is_bulk=False):
    status_msg = await m.reply_text(f"🔎 **Analyzing Link:** `{url}`", quote=True)
    start_time = time.time()

    try:
        # 1. Get Info & Prepare Filename
        # GDrive aur generic files ke liye generic extractor allow kiya
        ydl_opts_info = {
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'allow_unplayable_formats': True, # PDF/ZIP ke liye important
        }

        with YoutubeDL(ydl_opts_info) as ydl:
            try:
                info_dict = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                original_title = info_dict.get('title', 'Unknown_File')
                ext = info_dict.get('ext', 'mp4') # Default ext detection
                final_title = f"{original_title} @skillneast.{ext}"
            except Exception as e:
                await status_msg.edit_text(f"❌ **Link Error:**\n`{str(e)}`")
                return

        # 2. Download Content
        await status_msg.edit_text(f"⬇️ **Downloading:** `{original_title}`\n⚡ Speed Boost Active...")
        
        # High Speed Settings
        ydl_opts_down = {
            'outtmpl': final_title,
            'quiet': True,
            'nocheckcertificate': True,
            'allow_unplayable_formats': True,
            # Speed Optimization Flags
            'concurrent_fragment_downloads': 5, # Parallel parts download
            'buffersize': 1024,
            'http_chunk_size': 10485760, 
        }

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: YoutubeDL(ydl_opts_down).download([url])
        )

        # File Verification
        if not os.path.exists(final_title):
            # Fallback check agar yt-dlp ne extension change kar di
            found = False
            for file in os.listdir('.'):
                if file.startswith(original_title):
                    final_title = file
                    found = True
                    break
            if not found:
                await status_msg.edit_text("❌ Download Failed. File not found.")
                return

        # 3. Upload File (Document or Video based on extension)
        await status_msg.edit_text(f"⬆️ **Uploading...**")
        upload_start = time.time()
        
        caption_text = f"📂 **{final_title}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"

        # Check file type for upload method
        if final_title.lower().endswith(('.mp4', '.mkv', '.webm', '.avi')):
            await m.reply_video(
                video=final_title,
                caption=caption_text,
                supports_streaming=True,
                progress=progress_bar,
                progress_args=(status_msg, upload_start, "⬆️ Uploading Video...")
            )
        else:
            # PDF, ZIP, etc ke liye document
            await m.reply_document(
                document=final_title,
                caption=caption_text,
                progress=progress_bar,
                progress_args=(status_msg, upload_start, "⬆️ Uploading File...")
            )

        # 4. Cleanup
        await status_msg.delete()
        if os.path.exists(final_title):
            os.remove(final_title)
        
        if is_bulk:
            await asyncio.sleep(2)

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
        if 'final_title' in locals() and os.path.exists(final_title):
            os.remove(final_title)

# ------------------- COMMAND HANDLERS -------------------

@bot.on_message(filters.command(["start"]))
async def start_command(bot, m: Message):
    await m.reply_text(
        f"👋 **Hi {m.from_user.first_name}!**\n\n"
        "Send any link (YouTube, Drive, PDF, ZIP).\n"
        "Render Port Error Fixed! ✅"
    )

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
    
    await m.reply_text("✅ All Tasks Done!")

@bot.on_message(filters.text)
async def single_download(bot, m: Message):
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        return

    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        await process_video(bot, m, url, is_bulk=False)

# ------------------- START BOT -------------------

print("Starting Web Server for Render...")
keep_alive()  # <--- Ye function Render ko khush rakhega

print("Bot Started Successfully...")
bot.run()
