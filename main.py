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
import gdown
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

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
async def progress_bar(current, total, message_obj, start_time, status_text, task_info_text=""):
    now=time.time(); diff=now-start_time
    if round(diff % 4.00)==0 or current==total:
        p=current*100/total; s=current/diff; eta=round((total-p)/s)*1000 if s>0 else 0
        prog = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(''.join(["■" for i in range(math.floor(p/5))]), ''.join(["□" for i in range(20-math.floor(p/5))]), round(p,2))
        tmp = (f"{task_info_text}{prog}**📦 Done:** {humanbytes(current)}/{humanbytes(total)}\n**🚀 Speed:** {humanbytes(s)}/s\n**⏳ ETA:** {time_formatter(eta)}\n\n**{status_text}**")
        try: await message_obj.edit_text(text=tmp)
        except Exception: pass

async def animate_status(message, text, stop_event):
    animation_chars = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
    idx = 0
    while not stop_event.is_set():
        try:
            await message.edit_text(f"{text} {animation_chars[idx]}")
            idx = (idx + 1) % len(animation_chars)
            await asyncio.sleep(0.3)
        except Exception: break

# --- REDIS SETUP ---
db = None
try:
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        db = redis.from_url(redis_url, decode_responses=True)
        db.ping()
        logger.info("✅✅✅ Successfully connected to Redis database! ✅✅✅")
    else:
        logger.warning("❌ REDIS_URL environment variable not found. Intro feature will be disabled.")
except Exception as e: logger.error(f"❌❌❌ Failed to connect to Redis: {e}")

# --- COMMANDS ---
@bot.on_message(filters.command(["setvideo"]) & filters.user(sudo_users))
async def set_intro_link_db(bot: Client, m: Message):
    if not db: return await m.reply_text("❌ **Database Error:**\nBot Redis database se connect nahi hai.")
    if len(m.command) < 2: return await m.reply_text("**Usage:** `/setvideo <direct_download_link>`")
    link = m.command[1]
    db.set("intro_video_link", link)
    await m.reply_text(f"✅ **Success!** Intro video link set kar diya gaya hai.")

@bot.on_message(filters.command(["setphoto"]) & filters.user(sudo_users))
async def set_photo_link_db(bot: Client, m: Message):
    if not db: return await m.reply_text("❌ **Database Error:**\nBot Redis database se connect nahi hai.")
    if len(m.command) < 2: return await m.reply_text("**Usage:** `/setphoto <direct_image_link>`")
    link = m.command[1]
    db.set("intro_photo_link", link)
    await m.reply_text(f"✅ **Success!** Intro photo link set kar diya gaya hai.")

@bot.on_message(filters.command(["delintro"]) & filters.user(sudo_users))
async def del_intro(bot: Client, m: Message):
    if not db: return await m.reply_text("❌ **Database Error:**\nBot Redis database se connect nahi hai.")
    db.delete("intro_video_link")
    db.delete("intro_photo_link")
    await m.reply_text("✅ **Success!** Sabhi intro settings delete kar di gayi hain.")

@bot.on_message(filters.command(["checkintro"]) & filters.user(sudo_users))
async def check_intro(bot: Client, m: Message):
    if not db: return await m.reply_text("❌ **Database Error:**\nBot Redis database se connect nahi hai.")
    video_link = db.get("intro_video_link")
    photo_link = db.get("intro_photo_link")
    reply = "📝 **Current Intro Settings:**\n\n"
    reply += f"🎬 **Video Intro:**\n`{video_link}`\n\n" if video_link else "🎬 **Video Intro:** `Not Set`\n\n"
    reply += f"🖼️ **Photo Intro:**\n`{photo_link}`" if photo_link else "🖼️ **Photo Intro:** `Not Set`"
    await m.reply_text(reply)

# --- MAIN LOGIC ---
async def process_link(client: Client, m: Message, url: str, status_msg: Message, task_info_text: str = ""):
    downloaded_file = None
    final_output_file = None
    temp_intro_path = f"temp_intro_{m.id}"

    try:
        await status_msg.edit_text(f"{task_info_text}🔎 Analyzing Link...")
        video_extensions = ('.mp4', '.mkv', '.webm', '.avi', '.mov')

        if "drive.google.com" in url:
            await status_msg.edit_text(f"{task_info_text}📥 Downloading main video...")
            downloaded_file = await asyncio.get_event_loop().run_in_executor(None, lambda: gdown.download(url, fuzzy=True, quiet=False))
            if downloaded_file is None: raise Exception("File not found or permission denied.")

            is_video = downloaded_file.lower().endswith(video_extensions)
            
            # Decide which intro to use
            intro_to_use = None
            if db and is_video:
                if db.exists("intro_video_link"): intro_to_use = "video"
                elif db.exists("intro_photo_link"): intro_to_use = "photo"

            if intro_to_use == "video":
                # Video intro logic (pehle jaisa)
                intro_link = db.get("intro_video_link")
                await status_msg.edit_text(f"{task_info_text}📥 Downloading intro video...")
                gdown.download(intro_link, f"{temp_intro_path}.mp4", quiet=True)
                if not os.path.exists(f"{temp_intro_path}.mp4"): raise Exception("Intro video download nahi ho payi.")
                
                name, ext = os.path.splitext(downloaded_file)
                final_output_file = f"{name} @skillneast{ext}"

                stop_event = asyncio.Event()
                animation_task = asyncio.create_task(animate_status(status_msg, f"{task_info_text}🖇️ Merging videos...", stop_event))

                ffmpeg_command = ['ffmpeg', '-y', '-i', f"{temp_intro_path}.mp4", '-i', downloaded_file, '-filter_complex', '[0:v][1:v]scale2ref[v0][v1];[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[v][a]', '-map', '[v]', '-map', '[a]', '-preset', 'ultrafast', '-c:v', 'libx264', '-c:a', 'aac', final_output_file]
                
                process = await asyncio.create_subprocess_exec(*ffmpeg_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, stderr = await process.communicate()
                
                stop_event.set(); await animation_task
                if process.returncode != 0: raise Exception(f"FFmpeg Error:\n`{stderr.decode().strip()[-500:]}`")
                
                os.remove(downloaded_file); os.remove(f"{temp_intro_path}.mp4")
                downloaded_file = final_output_file

            elif intro_to_use == "photo":
                # Naya photo intro logic
                intro_link = db.get("intro_photo_link")
                await status_msg.edit_text(f"{task_info_text}📥 Downloading intro photo...")
                gdown.download(intro_link, f"{temp_intro_path}.jpg", quiet=True)
                if not os.path.exists(f"{temp_intro_path}.jpg"): raise Exception("Intro photo download nahi ho payi.")
                
                name, ext = os.path.splitext(downloaded_file)
                final_output_file = f"{name} @skillneast{ext}"

                stop_event = asyncio.Event()
                animation_task = asyncio.create_task(animate_status(status_msg, f"{task_info_text}🖇️ Attaching photo...", stop_event))

                # [FIXED COMMAND] 
                # Step 1: Image se 5-sec ka intro video banata hai (standard resolution/format me).
                # Step 2: Main video ko bhi same standard resolution/format me laata hai.
                # Step 3: Dono standard videos ko jodta hai (concat) aur main video ki audio copy karta hai.
                ffmpeg_command = [
                    'ffmpeg', '-y',
                    '-loop', '1', '-t', '5', '-i', f"{temp_intro_path}.jpg",  # Input 1: Image
                    '-i', downloaded_file,  # Input 2: Main Video
                    '-filter_complex',
                    # Process image: scale, pad to 1920x1080, set format, set aspect ratio -> [v_intro]
                    "[0:v]scale=w=1920:h=1080:force_original_aspect_ratio=decrease,pad=w=1920:h=1080:x=(ow-iw)/2:y=(oh-ih)/2,format=yuv420p,setsar=1[v_intro];" +
                    # Process main video: scale to 1920x1080, set format, set aspect ratio -> [v_main]
                    "[1:v]scale=w=1920:h=1080,format=yuv420p,setsar=1[v_main];" +
                    # Concat intro video and main video, but take audio only from main video
                    "[v_intro][v_main]concat=n=2:v=1:a=0[v_out]",
                    '-map', '[v_out]',     # Map the concatenated video stream
                    '-map', '1:a?',         # Map the audio from the second input (main video), '?' makes it optional
                    '-c:v', 'libx264',      # Video codec
                    '-c:a', 'copy',         # Copy audio without re-encoding
                    '-preset', 'ultrafast', # For faster processing
                    '-shortest',            # Finish encoding when the shortest stream ends (the audio)
                    final_output_file
                ]

                process = await asyncio.create_subprocess_exec(*ffmpeg_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, stderr = await process.communicate()
                
                stop_event.set(); await animation_task
                if process.returncode != 0: raise Exception(f"FFmpeg Error:\n`{stderr.decode().strip()[-500:]}`")
                
                os.remove(downloaded_file); os.remove(f"{temp_intro_path}.jpg")
                downloaded_file = final_output_file

            else:
                # Koi intro nahi, sirf rename karo
                name, ext = os.path.splitext(downloaded_file)
                final_filename = f"{name} @skillneast{ext}"
                os.rename(downloaded_file, final_filename)
                downloaded_file = final_filename

        else:
            # YouTube-DL links (pehle jaisa)
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
        await status_msg.edit_text(f"{task_info_text}✅ Done! Now Uploading: `{base_name}`")
        caption = f"📂 **{base_name}**\n\n👤 **User:** {m.from_user.mention}\n🤖 **Bot:** @skillneast"
        progress_args = (status_msg, time.time(), "⬆️ Uploading...", task_info_text)
        
        if downloaded_file.lower().endswith(video_extensions):
            await m.reply_video(video=downloaded_file, caption=caption, supports_streaming=True, progress=progress_bar, progress_args=progress_args)
        else:
            await m.reply_document(document=downloaded_file, caption=caption, progress=progress_bar, progress_args=progress_args)
        
        if not task_info_text: await status_msg.delete()
            
    except Exception as e:
        await status_msg.edit_text(f"{task_info_text}❌ **Error:**\n`{str(e)}`")
        raise e
        
    finally:
        if downloaded_file and os.path.exists(downloaded_file): os.remove(downloaded_file)
        if final_output_file and os.path.exists(final_output_file): os.remove(final_output_file)
        for f in [f"{temp_intro_path}.mp4", f"{temp_intro_path}.jpg"]:
            if os.path.exists(f): os.remove(f)


# --- HELP & OTHER HANDLERS ---
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
                      "🔹 `/setvideo <url>` - Video ko intro banaye.\n"
                      "🔹 `/setphoto <url>` - Image ko 5s ka intro banaye.\n"
                      "🔹 `/checkintro` - Check karein ki kaunsa intro set hai.\n"
                      "🔹 `/delintro` - Sabhi intro settings delete karein.")
    await m.reply_text(help_text, quote=True)

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    if m.from_user.id not in auth_users and m.from_user.id not in sudo_users: return
    # ... (bulk logic pehle jaisa hi hai)
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

@bot.on_message(filters.text & ~filters.command(["start", "help", "bulk", "setvideo", "setphoto", "checkintro", "delintro"]))
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
