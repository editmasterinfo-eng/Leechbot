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
from pyrogram.errors import ChatAdminRequired

# --- CONFIG SE NAYI CHEEZ IMPORT KAREIN ---
from config import api_id, api_hash, bot_token, auth_users, sudo_users, INTRO_CHANNEL_ID
from yt_dlp import YoutubeDL
import gdown

# ... (baaki sab kuch pehle jaisa hi) ...
# CRITICAL FIX, LOGGING, YT-DLP, FLASK, HELPERS sab pehle jaise rahenge

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
def humanbytes(size):
    if not size: return "0 B"
    power = 1024; n = 0; dic_powerN = {0: 'B', 1: 'KiB', 2: 'MiB', 3: 'GiB', 4: 'TiB'}
    while size > power: size /= power; n += 1
    return f"{round(size, 2)} {dic_powerN[n]}"
def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000); minutes, seconds = divmod(seconds, 60); hours, minutes = divmod(minutes, 60); days, hours = divmod(hours, 24)
    return ((f"{days}d, " if days else "") + (f"{hours}h, " if hours else "") + (f"{minutes}m, " if minutes else "") + (f"{seconds}s, " if seconds else "")).strip(', ') or "0s"
async def progress_bar(current, total, message_obj, start_time, status_text, task_info_text=""):
    now = time.time(); diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total; speed = current / diff; time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        progress_str = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(''.join(["■" for i in range(math.floor(percentage / 5))]), ''.join(["□" for i in range(20 - math.floor(percentage / 5))]), round(percentage, 2))
        tmp = (f"{task_info_text}{progress_str}**📦 Done:** {humanbytes(current)} / {humanbytes(total)}\n**🚀 Speed:** {humanbytes(speed)}/s\n**⏳ ETA:** {time_formatter(time_to_completion)}\n\n**{status_text}**")
        try: await message_obj.edit_text(text=tmp)
        except Exception: pass
async def download_progress_hook(d, message_obj, start_time, loop, task_info_text):
    if d['status'] == 'downloading':
        now = time.time()
        if not hasattr(download_progress_hook, 'last_update') or (now - download_progress_hook.last_update) > 3:
            download_progress_hook.last_update = now; total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total_bytes:
                downloaded_bytes = d.get('downloaded_bytes', 0); percentage = (downloaded_bytes / total_bytes) * 100; speed = d.get('speed'); eta = d.get('eta')
                progress_str = "[{0}{1}] \n**📊 Progress:** {2:.2f}%\n".format(''.join(["■" for i in range(math.floor(percentage / 5))]), ''.join(["□" for i in range(20 - math.floor(percentage / 5))]), percentage)
                tmp = (f"{task_info_text}{progress_str}**📦 Done:** {humanbytes(downloaded_bytes)} / {humanbytes(total_bytes)}\n**🚀 Speed:** {humanbytes(speed) if speed else 0}/s\n**⏳ ETA:** {time_formatter(eta * 1000) if eta else 'N/A'}\n\n**⬇️ Downloading...**")
                asyncio.run_coroutine_threadsafe(message_obj.edit_text(text=tmp), loop)
# -------------------

async def get_intro_video(client: Client) -> str | None:
    """Channel se intro video download karta hai."""
    intro_clip_path = "intro.mp4"
    if not INTRO_CHANNEL_ID:
        logger.warning("INTRO_CHANNEL_ID is not set in config. Skipping intro.")
        return None
    try:
        # Channel se last message fetch karein
        async for last_message in client.get_chat_history(chat_id=INTRO_CHANNEL_ID, limit=1):
            if last_message and last_message.video:
                logger.info("Found intro video in the channel. Downloading it...")
                # Agar purani file hai to delete karein
                if os.path.exists(intro_clip_path):
                    os.remove(intro_clip_path)
                # Nayi file download karein
                await last_message.download(file_name=intro_clip_path)
                return intro_clip_path
        logger.warning("No video message found in the intro channel.")
        return None
    except ChatAdminRequired:
        logger.error("Bot is not an admin in the INTRO_CHANNEL. Please make it an admin.")
        return None
    except Exception as e:
        logger.error(f"Failed to get intro video from channel: {e}", exc_info=True)
        return None


async def process_link(client: Client, m: Message, url: str, status_msg: Message, task_info_text: str = ""):
    downloaded_file = None
    final_output_file = None
    intro_clip_path = None # Isko None se start karein
    
    try:
        await status_msg.edit_text(f"{task_info_text}🔎 **Analyzing Link...**\n`{url}`")
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        if "drive.google.com" in url:
            await status_msg.edit_text(f"{task_info_text}📥 **Downloading from Google Drive...**")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=False))
            if downloaded_file is None: raise Exception("File not found or permission denied on Google Drive.")

            is_video = downloaded_file.lower().endswith(video_extensions)
            if is_video:
                # --- YAHAN BADLAAV KIYA GAYA HAI ---
                intro_clip_path = await get_intro_video(client)
            
            if is_video and intro_clip_path:
                await status_msg.edit_text(f"{task_info_text}🖇️ **Adding intro clip...**\n_This might take some time._")
                name, ext = os.path.splitext(downloaded_file)
                final_output_file = f"{name} @skillneast{ext}"
                with open("concat_list.txt", "w", encoding="utf-8") as f:
                    f.write(f"file '{os.path.abspath(intro_clip_path)}'\n")
                    f.write(f"file '{os.path.abspath(downloaded_file)}'\n")

                ffmpeg_command = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', 'concat_list.txt', '-c', 'copy', final_output_file]
                process = await asyncio.create_subprocess_exec(*ffmpeg_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, stderr = await process.communicate()

                if process.returncode != 0:
                    raise Exception(f"Failed to add intro clip. FFmpeg Error: {stderr.decode().splitlines()[-1]}")
                
                os.remove(downloaded_file)
                downloaded_file = final_output_file
            else:
                name, ext = os.path.splitext(downloaded_file)
                final_filename = f"{name} @skillneast{ext}"
                os.rename(downloaded_file, final_filename)
                downloaded_file = final_filename
        else:
            # YouTube-DL logic pehle jaisa hi
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info_dict = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                original_title = info_dict.get('title', 'Unknown_File'); ext = info_dict.get('ext', 'mp4')
                safe_title = "".join([c for c in original_title if c.isalnum() or c in (' ', '-', '_')]).strip() or f"file_{int(time.time())}"
                downloaded_file = f"{safe_title} @skillneast.{ext}"
            await status_msg.edit_text(f"{task_info_text}⬇️ **Downloading:** `{safe_title}`")
            download_start = time.time(); main_loop = asyncio.get_event_loop()
            hook = partial(download_progress_hook, message_obj=status_msg, start_time=download_start, loop=main_loop, task_info_text=task_info_text)
            ydl_opts_down = {'outtmpl': downloaded_file, 'logger': MyLogger(), 'nocheckcertificate': True, 'progress_hooks': [hook]}
            await asyncio.get_event_loop().run_in_executor(None, lambda: YoutubeDL(ydl_opts_down).download([url]))
            if not os.path.exists(downloaded_file): raise Exception("Download Failed.")

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
        logger.error(f"Error processing {url}: {e}", exc_info=True)
        await status_msg.edit_text(error_message)
        raise e
    finally:
        # Saari temporary files saaf karein
        if downloaded_file and os.path.exists(downloaded_file): os.remove(downloaded_file)
        if final_output_file and os.path.exists(final_output_file): os.remove(final_output_file)
        if intro_clip_path and os.path.exists(intro_clip_path): os.remove(intro_clip_path) # Intro ko bhi delete karein
        if os.path.exists("concat_list.txt"): os.remove("concat_list.txt")

# ------------------- COMMANDS -------------------
@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    await m.reply_text(f"👋 **Hi {m.from_user.first_name}! Main ek URL Downloader Bot hoon.**\n\nCommands ke baare mein jaanne ke liye /help type karein.", quote=True)

@bot.on_message(filters.command(["help"]))
async def help_command(bot: Client, m: Message):
    help_text = ("**📜 Bot Help Section**\n\n"
                 "**Commands:**\n"
                 "🔹 `/start` - Bot ko start karne ke liye.\n"
                 "🔹 `/help` - Yeh help message dekhne ke liye.\n"
                 "🔹 `/bulk <link1> ...` - Ek saath multiple links download karne ke liye.\n\n"
                 "**Intro Video Note:**\n"
                 "Google Drive videos mein intro add karne ke liye, admin ne ek private channel set kiya hai. Bot hamesha uss channel mein मौजूद sabse nayi video ko intro ke taur par istemaal karega.")
    await m.reply_text(help_text, quote=True)

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users:
        return await m.reply_text("🚫 You are not authorized.")
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
            failed += 1; await asyncio.sleep(4)
    await bulk_status_msg.edit_text(f"✅ **Bulk Download Complete!**\n\n**Total:** {total_links}\n**✅ Successful:** {completed}\n**❌ Failed:** {failed}")

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk"]))
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
