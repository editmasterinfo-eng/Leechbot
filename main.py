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

# ... (baaki sab kuch pehle jaisa hi) ...

# ------------------- CRITICAL FIX & LOGGING -------------------
class DummyWriter:
    def write(self, *args, **kwargs): pass
    def flush(self, *args, **kwargs): pass

if sys.stdout is None: sys.stdout = DummyWriter()
if sys.stderr is None: sys.stderr = DummyWriter()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# ------------------- YT-DLP & FLASK (pehle jaisa hi) -------------------
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

# ------------------- BOT SETUP -------------------
bot = Client("bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# ------------------- HELPER FUNCTIONS (pehle jaisa hi) -------------------
def humanbytes(size):
    if not size: return "0 B"
    power = 1024; n = 0
    dic_powerN = {0: 'B', 1: 'KiB', 2: 'MiB', 3: 'GiB', 4: 'TiB'}
    while size > power: size /= power; n += 1
    return f"{round(size, 2)} {dic_powerN[n]}"

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return ((f"{days}d, " if days else "") + (f"{hours}h, " if hours else "") + (f"{minutes}m, " if minutes else "") + (f"{seconds}s, " if seconds else "")).strip(', ') or "0s"

async def progress_bar(current, total, message_obj, start_time, status_text, task_info_text=""):
    now = time.time(); diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total; speed = current / diff
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        progress_str = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(''.join(["■" for i in range(math.floor(percentage / 5))]), ''.join(["□" for i in range(20 - math.floor(percentage / 5))]), round(percentage, 2))
        tmp = (f"{task_info_text}{progress_str}**📦 Done:** {humanbytes(current)} / {humanbytes(total)}\n**🚀 Speed:** {humanbytes(speed)}/s\n**⏳ ETA:** {time_formatter(time_to_completion)}\n\n**{status_text}**")
        try: await message_obj.edit_text(text=tmp)
        except Exception: pass

async def download_progress_hook(d, message_obj, start_time, loop, task_info_text):
    if d['status'] == 'downloading':
        now = time.time()
        if not hasattr(download_progress_hook, 'last_update') or (now - download_progress_hook.last_update) > 3:
            download_progress_hook.last_update = now
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total_bytes:
                downloaded_bytes = d.get('downloaded_bytes', 0); percentage = (downloaded_bytes / total_bytes) * 100
                speed = d.get('speed'); eta = d.get('eta')
                progress_str = "[{0}{1}] \n**📊 Progress:** {2:.2f}%\n".format(''.join(["■" for i in range(math.floor(percentage / 5))]), ''.join(["□" for i in range(20 - math.floor(percentage / 5))]), percentage)
                tmp = (f"{task_info_text}{progress_str}**📦 Done:** {humanbytes(downloaded_bytes)} / {humanbytes(total_bytes)}\n**🚀 Speed:** {humanbytes(speed) if speed else 0}/s\n**⏳ ETA:** {time_formatter(eta * 1000) if eta else 'N/A'}\n\n**⬇️ Downloading...**")
                asyncio.run_coroutine_threadsafe(message_obj.edit_text(text=tmp), loop)

# ------------------- DOWNLOAD LOGIC (Updated with LOGGING) -------------------
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

            # --- DEBUGGING LOGS ADDED HERE ---
            logger.info(f"Downloaded G-Drive file: {downloaded_file}")
            is_video = downloaded_file.lower().endswith(video_extensions)
            intro_exists = os.path.exists(intro_clip_path)
            logger.info(f"Is it a video? -> {is_video}")
            logger.info(f"Does '{intro_clip_path}' exist? -> {intro_exists} (Full path check: {os.path.abspath(intro_clip_path)})")
            # --- END OF LOGS ---

            if is_video and intro_exists:
                await status_msg.edit_text(f"{task_info_text}🖇️ **Adding intro clip...**\n_This might take some time._")
                name, ext = os.path.splitext(downloaded_file)
                final_output_file = f"{name} @skillneast{ext}"
                
                with open("concat_list.txt", "w", encoding="utf-8") as f:
                    f.write(f"file '{os.path.abspath(intro_clip_path)}'\n")
                    f.write(f"file '{os.path.abspath(downloaded_file)}'\n")

                ffmpeg_command = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', 'concat_list.txt', '-c', 'copy', final_output_file]
                process = await asyncio.create_subprocess_exec(*ffmpeg_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_log = stderr.decode()
                    logger.error(f"FFmpeg Error: {error_log}")
                    # Agar FFmpeg fail ho, to original video upload karein
                    raise Exception(f"Failed to add intro clip. Uploading original. Error: {error_log.splitlines()[-1]}")
                
                os.remove(downloaded_file) # Purani file delete karein
                downloaded_file = final_output_file # Final file ko upload ke liye set karein
            else:
                logger.warning("Skipping intro merge. Either not a video or intro.mp4 not found.")
                name, ext = os.path.splitext(downloaded_file)
                final_filename = f"{name} @skillneast{ext}"
                os.rename(downloaded_file, final_filename)
                downloaded_file = final_filename
        else:
            # ... (YouTube-DL logic remains the same)
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info_dict = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                original_title = info_dict.get('title', 'Unknown_File'); ext = info_dict.get('ext', 'mp4')
                safe_title = "".join([c for c in original_title if c.isalnum() or c in (' ', '-', '_')]).strip() or f"file_{int(time.time())}"
                downloaded_file = f"{safe_title} @skillneast.{ext}"
            await status_msg.edit_text(f"{task_info_text}⬇️ **Downloading:** `{safe_title}`")
            download_start = time.time(); main_loop = asyncio.get_event_loop()
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
    # (Same as before)
    await m.reply_text(f"👋 **Hi {m.from_user.first_name}! Main ek URL Downloader Bot hoon.**\n\nCommands ke baare mein jaanne ke liye /help type karein.", quote=True)

@bot.on_message(filters.command(["help"]))
async def help_command(bot: Client, m: Message):
    # (Updated to include /checkintro)
    help_text = ("**📜 Bot Help Section**\n\n"
                 "**Commands:**\n"
                 "🔹 `/start` - Bot ko start karne ke liye.\n"
                 "🔹 `/help` - Yeh help message dekhne ke liye.\n"
                 "🔹 `/bulk <link1> ...` - Ek saath multiple links download karne ke liye.\n")
    if m.from_user.id in sudo_users:
        help_text += ("\n**Admin Commands:**\n"
                      "🔹 `/setvideo` - Kisi video ko reply karke yeh command dein, taaki woh Google Drive videos ke liye intro ban jaye.\n"
                      "🔹 `/checkintro` - Check karein ki intro video server par maujood hai ya nahi.")
    await m.reply_text(help_text, quote=True)

@bot.on_message(filters.command(["setvideo"]) & filters.user(sudo_users))
async def set_intro_video(bot: Client, m: Message):
    # (Same as before)
    if not m.reply_to_message or not m.reply_to_message.video:
        return await m.reply_text("Intro set karne ke liye, कृपया ek video message ko reply karte hue `/setvideo` command dein.")
    status_msg = await m.reply_text("📥 **Downloading and setting new intro video...**", quote=True)
    try:
        if os.path.exists("intro.mp4"): os.remove("intro.mp4")
        await m.reply_to_message.download(file_name="intro.mp4")
        await status_msg.edit_text("✅ **Success!** Nayi intro video set ho gayi hai.")
    except Exception as e:
        logger.error(f"Failed to set intro video: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Error:** Video set nahi ho payi. Logs check karein.\n`{e}`")

# --- NAYA COMMAND ADD KIYA GAYA HAI ---
@bot.on_message(filters.command(["checkintro"]) & filters.user(sudo_users))
async def check_intro_video(bot: Client, m: Message):
    intro_path = "intro.mp4"
    if os.path.exists(intro_path):
        await m.reply_text(f"✅ **File Found!**\n`intro.mp4` server par maujood hai aur istemaal ke liye taiyaar hai.", quote=True)
    else:
        await m.reply_text(f"❌ **File Not Found!**\n`intro.mp4` server par nahi mili. Kripya ise `/setvideo` command ka istemaal karke set karein.", quote=True)

# ... (baaki sabhi commands jaise /bulk aur single_download pehle jaise hi rahenge) ...

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users:
        return await m.reply_text("🚫 You are not authorized to use this command.")
    if len(m.command) > 1: raw_text = m.text.split(maxsplit=1)[1]
    elif m.reply_to_message and m.reply_to_message.text: raw_text = m.reply_to_message.text
    else: return await m.reply_text("**Usage:** `/bulk <link1> <link2> ...`")
    links = re.findall(r'https?://[^\s]+', raw_text)
    if not links: return await m.reply_text("❓ No valid links found.")
    total_links = len(links)
    bulk_status_msg = await m.reply_text(f"📦 **Bulk Queue Started:** Found {total_links} links.")
    completed, failed = 0, 0
    for i, link in enumerate(links, 1):
        task_info = (f"**📊 Task Status**\n**Total:** {total_links} | **✅ Completed:** {completed} | **❌ Failed:** {failed}\n\n**▶️ Processing Link {i}/{total_links}:**\n")
        try:
            await process_link(bot, m, link, bulk_status_msg, task_info_text=task_info)
            completed += 1
        except Exception:
            failed += 1
            await asyncio.sleep(4)
    await bulk_status_msg.edit_text(f"✅ **Bulk Download Complete!**\n\n**Total Links:** {total_links}\n**✅ Successful:** {completed}\n**❌ Failed:** {failed}")

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "setvideo", "checkintro"]))
async def single_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    url = m.text.strip()
    if url.startswith(("http://", "https://")):
        status_msg = await m.reply_text("🚀 **Preparing to download...**", quote=True)
        try: await process_link(bot, m, url, status_msg)
        except Exception: pass

# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("Starting Flask Server for Keep-Alive...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
