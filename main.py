import os
import sys
import time
import math
import asyncio
import threading
import logging
import re
import subprocess
from functools import partial
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL
import gdown

# ... (Baaki sab kuch pehle jaisa hi) ...

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

# ------------------- HELPER FUNCTIONS (pehle jaise hi) -------------------
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

async def progress_bar(current, total, message_obj, start_time, status_text, task_info_text=""):
    now = time.time()
    diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        progress_str = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(
            ''.join(["■" for _ in range(math.floor(percentage / 5))]),
            ''.join(["□" for _ in range(20 - math.floor(percentage / 5))]),
            round(percentage, 2))
        tmp = (f"{task_info_text}"
               f"{progress_str}"
               f"**📦 Done:** {humanbytes(current)} / {humanbytes(total)}\n"
               f"**🚀 Speed:** {humanbytes(speed)}/s\n"
               f"**⏳ ETA:** {time_formatter(time_to_completion)}\n\n"
               f"**{status_text}**")
        try:
            await message_obj.edit_text(text=tmp)
        except Exception: pass

async def download_progress_hook(d, message_obj, start_time, loop, task_info_text):
    if d['status'] == 'downloading':
        now = time.time()
        if not hasattr(download_progress_hook, 'last_update') or (now - download_progress_hook.last_update) > 3:
            download_progress_hook.last_update = now
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
                tmp = (f"{task_info_text}"
                       f"{progress_str}"
                       f"**📦 Done:** {humanbytes(downloaded_bytes)} / {humanbytes(total_bytes)}\n"
                       f"**🚀 Speed:** {humanbytes(speed) if speed else 0}/s\n"
                       f"**⏳ ETA:** {time_formatter(eta * 1000) if eta else 'N/A'}\n\n"
                       f"**⬇️ Downloading...**")
                asyncio.run_coroutine_threadsafe(message_obj.edit_text(text=tmp), loop)

# ------------------- DOWNLOAD LOGIC (pehle jaisa hi) -------------------
async def process_link(client: Client, m: Message, url: str, status_msg: Message, task_info_text: str = ""):
    downloaded_file = None
    final_output_file = None
    
    try:
        await status_msg.edit_text(f"{task_info_text}🔎 **Analyzing Link...**\n`{url}`")
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')
        intro_clip_path = "intro.mp4"

        if "drive.google.com" in url:
            await status_msg.edit_text(f"{task_info_text}📥 **Downloading from Google Drive...**")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=False))
            if downloaded_file is None: raise Exception("File not found or permission denied on Google Drive.")

            if downloaded_file.lower().endswith(video_extensions) and os.path.exists(intro_clip_path):
                await status_msg.edit_text(f"{task_info_text}🖇️ **Adding intro clip...**\n_This might take some time._")
                name, ext = os.path.splitext(downloaded_file)
                final_output_file = f"{name} @skillneast{ext}"
                with open("concat_list.txt", "w") as f:
                    f.write(f"file '{os.path.abspath(intro_clip_path)}'\n")
                    f.write(f"file '{os.path.abspath(downloaded_file)}'\n")

                ffmpeg_command = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', 'concat_list.txt', '-c', 'copy', final_output_file]
                process = await asyncio.create_subprocess_exec(*ffmpeg_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    logger.error(f"FFmpeg Error: {stderr.decode()}")
                    raise Exception("Failed to add intro clip. Uploading original video.")
                os.remove(downloaded_file)
                downloaded_file = final_output_file
            else:
                name, ext = os.path.splitext(downloaded_file)
                final_filename = f"{name} @skillneast{ext}"
                os.rename(downloaded_file, final_filename)
                downloaded_file = final_filename
        else:
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info_dict = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                original_title = info_dict.get('title', 'Unknown_File')
                ext = info_dict.get('ext', 'mp4')
                safe_title = "".join([c for c in original_title if c.isalnum() or c in (' ', '-', '_')]).strip()
                if not safe_title: safe_title = f"file_{int(time.time())}"
                downloaded_file = f"{safe_title} @skillneast.{ext}"
            await status_msg.edit_text(f"{task_info_text}⬇️ **Downloading:** `{safe_title}`")
            download_start = time.time()
            main_loop = asyncio.get_event_loop()
            hook = partial(download_progress_hook, message_obj=status_msg, start_time=download_start, loop=main_loop, task_info_text=task_info_text)
            ydl_opts_down = {'outtmpl': downloaded_file, 'logger': MyLogger(), 'nocheckcertificate': True, 'progress_hooks': [hook], 'concurrent_fragment_downloads': 5, 'buffersize': 1024*256}
            await asyncio.get_event_loop().run_in_executor(None, lambda: YoutubeDL(ydl_opts_down).download([url]))
            if not os.path.exists(downloaded_file): raise Exception("Download Failed. File not found on disk.")

        base_name = os.path.basename(downloaded_file)
        await status_msg.edit_text(f"{task_info_text}⬆️ **Uploading:** `{base_name}`")
        upload_start = time.time()
        caption_text = f"📂 **{base_name}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"
        progress_args_tuple = (status_msg, upload_start, "⬆️ Uploading...", task_info_text)
        
        if downloaded_file.lower().endswith(video_extensions):
            await m.reply_video(video=downloaded_file, caption=caption_text, supports_streaming=True, progress=progress_bar, progress_args=progress_args_tuple)
        else:
            await m.reply_document(document=downloaded_file, caption=caption_text, progress=progress_bar, progress_args=progress_args_tuple)
        
        if not task_info_text: await status_msg.delete()
    except Exception as e:
        error_message = f"{task_info_text}❌ **An Error Occurred:**\n`{str(e)}`"
        logger.error(f"Error in process_link for URL {url}: {e}", exc_info=True)
        await status_msg.edit_text(error_message)
        raise e
    finally:
        if downloaded_file and os.path.exists(downloaded_file): os.remove(downloaded_file)
        if final_output_file and os.path.exists(final_output_file): os.remove(final_output_file)
        if os.path.exists("concat_list.txt"): os.remove("concat_list.txt")

# ------------------- COMMANDS -------------------
@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    await m.reply_text(
        f"👋 **Hi {m.from_user.first_name}! Main ek URL Downloader Bot hoon.**\n\n"
        "Aap mujhe koi bhi direct link (YouTube, Instagram, Google Drive, etc.) bhej sakte hain aur main use download karke aapko bhej dunga.\n\n"
        "Commands ke baare mein jaanne ke liye /help type karein.", quote=True
    )

@bot.on_message(filters.command(["help"]))
async def help_command(bot: Client, m: Message):
    help_text = (
        "**📜 Bot Help Section**\n\n"
        "**Kaise Use Karein:**\n"
        "1.  **Single Link**: Bas mujhe koi bhi download link chat mein bhejein.\n"
        "2.  **Multiple Links**: Ek saath kai links download karne ke liye `/bulk` command ka istemaal karein.\n\n"
        "**Commands:**\n"
        "🔹 `/start` - Bot ko start karne ke liye.\n"
        "🔹 `/help` - Yeh help message dekhne ke liye.\n"
        "🔹 `/bulk <link1> ...` - Ek saath multiple links download karne ke liye.\n"
    )
    if m.from_user.id in sudo_users:
        help_text += "\n**Admin Commands:**\n" \
                     "🔹 `/setvideo` - Kisi video ko reply karke yeh command dein, taaki woh Google Drive videos ke liye intro ban jaye."
    await m.reply_text(help_text, quote=True)

# Naya command yahan add kiya gaya hai
@bot.on_message(filters.command(["setvideo"]) & filters.user(sudo_users))
async def set_intro_video(bot: Client, m: Message):
    if not m.reply_to_message or not m.reply_to_message.video:
        await m.reply_text(
            "**Kaise Use Karein:**\n"
            "Intro set karne ke liye, कृपया ek video message ko reply karte hue `/setvideo` command dein."
        )
        return

    status_msg = await m.reply_text("📥 **Downloading and setting new intro video...** Please wait.", quote=True)
    try:
        # Purani intro file agar hai to delete kar dein
        if os.path.exists("intro.mp4"):
            os.remove("intro.mp4")
            
        # Nayi video ko intro.mp4 ke naam se download karein
        await m.reply_to_message.download(file_name="intro.mp4")
        
        await status_msg.edit_text("✅ **Success!** Nayi intro video set ho gayi hai.")
    except Exception as e:
        logger.error(f"Failed to set intro video: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Error:** Video set nahi ho payi. Logs check karein.\n`{e}`")


@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    # (Yeh function pehle jaisa hi rahega)
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users:
        return await m.reply_text("🚫 You are not authorized to use this command.")
    
    if len(m.command) > 1: raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text: raw_text = m.reply_to_message.text
    else: return await m.reply_text("**Usage:** `/bulk <link1> <link2> ...`")

    links = re.findall(r'https?://[^\s]+', raw_text)
    if not links: return await m.reply_text("❓ No valid links found.")
        
    total_links = len(links)
    bulk_status_msg = await m.reply_text(f"📦 **Bulk Queue Started:** Found {total_links} links.")
    
    completed = 0
    failed = 0
    for i, link in enumerate(links, 1):
        task_info = (f"**📊 Task Status**\n"
                     f"**Total:** {total_links} | **✅ Completed:** {completed} | **❌ Failed:** {failed}\n\n"
                     f"**▶️ Processing Link {i}/{total_links}:**\n")
        try:
            await process_link(bot, m, link, bulk_status_msg, task_info_text=task_info)
            completed += 1
        except Exception:
            failed += 1
            await asyncio.sleep(4)
    
    await bulk_status_msg.edit_text(f"✅ **Bulk Download Complete!**\n\n**Total Links:** {total_links}\n**✅ Successful:** {completed}\n**❌ Failed:** {failed}")


@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "setvideo"]))
async def single_download(bot: Client, m: Message):
    # (Yeh function pehle jaisa hi rahega)
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        status_msg = await m.reply_text("🚀 **Preparing to download...**", quote=True)
        try:
            await process_link(bot, m, url, status_msg)
        except Exception: pass

# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("Starting Flask Server for Keep-Alive...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
