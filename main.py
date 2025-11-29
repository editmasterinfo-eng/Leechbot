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
from pyrogram.errors import ChatAdminRequired, UserNotParticipant

# --- CONFIG SE NAYI CHEEZ IMPORT KAREIN ---
from config import api_id, api_hash, bot_token, auth_users, sudo_users, INTRO_CHANNEL_ID
from yt_dlp import YoutubeDL
import gdown

# --- CRITICAL FIX, LOGGING, YT-DLP, FLASK, HELPERS (sab pehle jaise rahenge) ---
# ... (yahan poora boilerplate code paste karein jo pehle tha, main use chhota kar raha hoon)
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
# ------------------------------------------------------------------------------------------

async def get_intro_video(client: Client) -> str | None:
    # Yeh function pehle jaisa hi rahega, channel se video download karega
    intro_clip_path = "intro.mp4"
    if not INTRO_CHANNEL_ID: return None
    try:
        async for last_message in client.get_chat_history(chat_id=INTRO_CHANNEL_ID, limit=1):
            if last_message and last_message.video:
                if os.path.exists(intro_clip_path): os.remove(intro_clip_path)
                await last_message.download(file_name=intro_clip_path)
                return intro_clip_path
        return None
    except Exception as e:
        logger.error(f"Failed to get intro video from channel: {e}", exc_info=True)
        return None

async def process_link(client: Client, m: Message, url: str, status_msg: Message, task_info_text: str = ""):
    # Yeh function bhi lagbhag pehle jaisa hi rahega
    downloaded_file = None; final_output_file = None; intro_clip_path = None
    try:
        await status_msg.edit_text(f"{task_info_text}🔎 **Analyzing Link...**")
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')
        if "drive.google.com" in url:
            await status_msg.edit_text(f"{task_info_text}📥 **Downloading from Google Drive...**")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=False))
            if downloaded_file is None: raise Exception("File not found or permission denied.")
            is_video = downloaded_file.lower().endswith(video_extensions)
            if is_video: intro_clip_path = await get_intro_video(client)
            if is_video and intro_clip_path:
                await status_msg.edit_text(f"{task_info_text}🖇️ **Adding intro clip...**")
                name, ext = os.path.splitext(downloaded_file)
                final_output_file = f"{name} @skillneast{ext}"
                with open("concat_list.txt", "w", encoding="utf-8") as f:
                    f.write(f"file '{os.path.abspath(intro_clip_path)}'\n"); f.write(f"file '{os.path.abspath(downloaded_file)}'\n")
                ffmpeg_command = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', 'concat_list.txt', '-c', 'copy', final_output_file]
                process = await asyncio.create_subprocess_exec(*ffmpeg_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, stderr = await process.communicate()
                if process.returncode != 0: raise Exception(f"FFmpeg Error: {stderr.decode().splitlines()[-1]}")
                os.remove(downloaded_file); downloaded_file = final_output_file
            else:
                name, ext = os.path.splitext(downloaded_file); final_filename = f"{name} @skillneast{ext}"
                os.rename(downloaded_file, final_filename); downloaded_file = final_filename
        else:
            ydl_opts_info = {'logger': MyLogger(), 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts_info) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                safe_title = "".join(c for c in info.get('title', 'file') if c.isalnum() or c in ' -_').strip() or f"file_{int(time.time())}"
                downloaded_file = f"{safe_title} @skillneast.{info.get('ext', 'mp4')}"
            await status_msg.edit_text(f"{task_info_text}⬇️ **Downloading:** `{safe_title}`")
            hook = partial(download_progress_hook, message_obj=status_msg, start_time=time.time(), loop=asyncio.get_event_loop(), task_info_text=task_info_text)
            ydl_opts_down = {'outtmpl': downloaded_file, 'logger': MyLogger(), 'progress_hooks': [hook]}
            await asyncio.get_event_loop().run_in_executor(None, lambda: YoutubeDL(ydl_opts_down).download([url]))
            if not os.path.exists(downloaded_file): raise Exception("Download Failed.")
        base_name = os.path.basename(downloaded_file)
        await status_msg.edit_text(f"{task_info_text}⬆️ **Uploading:** `{base_name}`")
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
        if intro_clip_path and os.path.exists(intro_clip_path): os.remove(intro_clip_path)
        if os.path.exists("concat_list.txt"): os.remove("concat_list.txt")

# ------------------- COMMANDS -------------------
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
                      "🔹 `/checkintro` - Check the currently set intro video in the channel.")
    await m.reply_text(help_text, quote=True)

# --- YAHAN COMMANDS KO UPDATE KIYA GAYA HAI ---
@bot.on_message(filters.command(["setvideo"]) & filters.user(sudo_users))
async def set_intro_video(bot: Client, m: Message):
    if not INTRO_CHANNEL_ID:
        return await m.reply_text("`INTRO_CHANNEL_ID` config mein set nahi hai.")
    
    if len(m.command) < 2:
        return await m.reply_text("**Usage:** `/setvideo <direct_download_link>`")

    url = m.command[1]
    status_msg = await m.reply_text("📥 **Downloading video from link...**", quote=True)
    temp_intro_path = f"temp_intro_{m.id}.mp4"
    
    try:
        # yt-dlp se link download karein
        ydl_opts = {'outtmpl': temp_intro_path, 'logger': MyLogger()}
        with YoutubeDL(ydl_opts) as ydl:
            await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.download([url]))
        
        if not os.path.exists(temp_intro_path):
            raise Exception("Link se video download nahi ho payi.")
            
        await status_msg.edit_text("⬆️ **Uploading to intro channel...**")

        # Channel se purani video delete karein
        async for last_message in bot.get_chat_history(chat_id=INTRO_CHANNEL_ID, limit=1):
            if last_message and last_message.video:
                await last_message.delete()
                
        # Nayi video channel mein upload karein
        await bot.send_video(
            chat_id=INTRO_CHANNEL_ID,
            video=temp_intro_path,
            caption=f"New intro video set by {m.from_user.mention}."
        )
        
        await status_msg.edit_text("✅ **Success!** Nayi intro video set ho gayi hai.")
        
    except Exception as e:
        logger.error(f"Failed to set intro video from link: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Error:**\n`{e}`")
    finally:
        # Temporary file ko delete karein
        if os.path.exists(temp_intro_path):
            os.remove(temp_intro_path)


@bot.on_message(filters.command(["checkintro"]) & filters.user(sudo_users))
async def check_intro_video(bot: Client, m: Message):
    if not INTRO_CHANNEL_ID:
        return await m.reply_text("`INTRO_CHANNEL_ID` config mein set nahi hai.")
        
    status_msg = await m.reply_text("🔎 **Checking intro channel...**", quote=True)
    try:
        async for last_message in bot.get_chat_history(chat_id=INTRO_CHANNEL_ID, limit=1):
            if last_message and last_message.video:
                await status_msg.delete()
                await m.reply_video(
                    video=last_message.video.file_id,
                    caption="✅ **This is the current intro video.**"
                )
                return
        
        await status_msg.edit_text("❌ **No intro video found in the channel.**\nUse `/setvideo <link>` to set one.")
        
    except (UserNotParticipant, ChatAdminRequired):
        await status_msg.edit_text("❌ **Error:** Bot is not a member or admin in the intro channel.")
    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:**\n`{e}`")


# --- Baaki commands pehle jaise hi ---
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
        status_msg = await m.reply_text("🚀 **Preparing to download...**", quote=True)
        try: await process_link(bot, m, url, status_msg)
        except Exception: pass

# ------------------- MAIN EXECUTION -------------------
if __name__ == "__main__":
    print("Starting Flask Server for Keep-Alive...")
    keep_alive()
    print("Starting Bot...")
    bot.run()
