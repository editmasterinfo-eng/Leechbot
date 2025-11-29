import os
import time
import math
import asyncio
import threading
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# Bot Client
bot = Client(
    "bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
)

# ------------------- HELPER FUNCTIONS FOR UI -------------------

def humanbytes(size):
    """Bytes ko KB, MB, GB mein convert karta hai"""
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
    """Time ko Seconds/Minutes mein format karta hai"""
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
          ((str(hours) + "h, ") if hours else "") + \
          ((str(minutes) + "m, ") if minutes else "") + \
          ((str(seconds) + "s, ") if seconds else "") + \
          ((str(milliseconds) + "ms, ") if milliseconds else "")
    return tmp[:-2]

async def progress_bar(current, total, message_obj, start_time, status_text):
    """
    Ye function Uploading ke time UI update karega.
    """
    now = time.time()
    diff = now - start_time
    
    # Har 5 second mein update karega taaki FloodWait na aaye
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000
        estimated_total_time = elapsed_time + time_to_completion

        elapsed_time = time_formatter(milliseconds=elapsed_time)
        estimated_total_time = time_formatter(milliseconds=estimated_total_time)

        # Progress Bar Design
        progress = "[{0}{1}] \n**📊 Progress:** {2}%\n".format(
            ''.join(["■" for i in range(math.floor(percentage / 5))]),
            ''.join(["□" for i in range(20 - math.floor(percentage / 5))]),
            round(percentage, 2))

        # Full Stats UI
        tmp = progress + \
              f"**📦 Completed:** {humanbytes(current)} / {humanbytes(total)}\n" \
              f"**🚀 Speed:** {humanbytes(speed)}/s\n" \
              f"**⏳ ETA:** {estimated_total_time if estimated_total_time != '' else '0 s'}\n\n" \
              f"**{status_text}**"

        try:
            await message_obj.edit(
                text=tmp
            )
        except Exception:
            pass

# ------------------- CORE LOGIC -------------------

async def process_video(client, m, url, is_bulk=False):
    """
    Ye function actual download aur upload karega.
    ise Single aur Bulk dono use karenge.
    """
    
    # Agar Bulk nahi hai to naya message bhejo, nahi to reply wale ko edit karo
    status_msg = await m.reply_text(f"🔎 **Analyzing Link:** `{url}`", quote=True)

    try:
        # 1. Get Info
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
            'geo_bypass': True,
            'nocheckcertificate': True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            try:
                info_dict = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                original_title = info_dict.get('title', 'Video')
                # Title modification
                final_title = f"{original_title} @skillneast"
            except Exception as e:
                await status_msg.edit_text(f"❌ **Error getting link info:**\n`{str(e)}`")
                return

        # 2. Download Video
        await status_msg.edit_text(f"⬇️ **Downloading:** `{final_title}`\n\nPlease wait, getting data from server...")
        
        out_filename = f"{final_title}.mp4"
        
        # Download Options
        download_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': out_filename,
            'quiet': True,
            'noplaylist': True,
            'nocheckcertificate': True,
        }

        # Download ko thread mein chalana zaruri hai taki bot hang na ho
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: YoutubeDL(download_opts).download([url])
        )

        # File Rename Verification (Kabhi kabhi yt-dlp mkv bana deta hai)
        if not os.path.exists(out_filename):
            for file in os.listdir('.'):
                if file.startswith(final_title):
                    out_filename = file
                    break
            else:
                await status_msg.edit_text("❌ Download Failed. File not found on server.")
                return

        # 3. Upload Video
        await status_msg.edit_text(f"⬆️ **Preparing Upload...**")
        start_time = time.time()
        
        # Sending Video with Progress Bar
        await m.reply_video(
            video=out_filename,
            caption=f"🎥 **{final_title}**\n\n👤 **Downloaded by:** {m.from_user.mention}\n🤖 **Bot:** @skillneast",
            supports_streaming=True,
            progress=progress_bar,
            progress_args=(status_msg, start_time, "⬆️ Uploading to Telegram...")
        )

        # 4. Cleanup
        await status_msg.delete()
        if os.path.exists(out_filename):
            os.remove(out_filename)
        
        # Agar bulk hai to thoda wait karo taki flood na ho
        if is_bulk:
            await asyncio.sleep(2)

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error Occurred:** `{str(e)}`")
        if 'out_filename' in locals() and os.path.exists(out_filename):
            os.remove(out_filename)

# ------------------- COMMAND HANDLERS -------------------

@bot.on_message(filters.command(["start"]))
async def start_command(bot, m: Message):
    await m.reply_text(
        f"👋 **Hello {m.from_user.first_name}!**\n\n"
        "Main ek **Video Downloader Bot** hoon.\n"
        "Mujhe YouTube ya Google Drive ka link bhejo, main use @skillneast tag ke sath bhej dunga.\n\n"
        "📜 **Commands:**\n"
        "/bulk - Ek sath multiple links download karne ke liye.\n"
        "/commands - Sare commands dekhne ke liye."
    )

@bot.on_message(filters.command(["help", "commands"]))
async def help_command(bot, m: Message):
    text = (
        "🛠 **Available Commands:**\n\n"
        "1️⃣ **/start** - Check if bot is alive.\n"
        "2️⃣ **/bulk** - Bulk Download Mode.\n"
        "   *Usage:* `/bulk link1 link2` ya fir `/bulk` likh ke links reply karein.\n"
        "3️⃣ **/help** - Show this message.\n\n"
        "🔗 **Direct Download:** Bas koi bhi link paste karein."
    )
    await m.reply_text(text)

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot, m: Message):
    # Auth Check
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await m.reply("🚫 **Access Denied:** You are not authorized.", quote=True)
        return

    # Check agar command ke sath text hai (e.g., /bulk link1 link2)
    if len(m.command) > 1:
        raw_text = m.text.split(maxsplit=1)[1]
    # Agar user ne reply kiya hai message pe
    elif m.reply_to_message and m.reply_to_message.text:
        raw_text = m.reply_to_message.text
    else:
        await m.reply_text(
            "⚠️ **Bulk Usage:**\n"
            "1. `/bulk` likh kar un links par reply karein jo download karne hain.\n"
            "2. Ya `/bulk link1 link2` bhejein (space ya new line se alag karke)."
        )
        return

    # Links ko alag karna (New line ya space se)
    links = raw_text.replace(" ", "\n").split("\n")
    links = [link.strip() for link in links if link.strip().startswith(("http://", "https://"))]

    if not links:
        await m.reply_text("❌ Koi valid link nahi mila.")
        return

    await m.reply_text(f"📦 **Bulk Task Started!**\nTotal Links: {len(links)}")

    # Ek ek karke process karo
    for i, link in enumerate(links):
        try:
            await process_video(bot, m, link, is_bulk=True)
        except Exception as e:
            await m.reply_text(f"❌ Error in Link #{i+1}: {link}\nError: {e}")

    await m.reply_text("✅ **Bulk Task Completed!**")

@bot.on_message(filters.text)
async def single_download(bot, m: Message):
    # Auth Check
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await m.reply("🚫 **Access Denied:** You are not authorized.", quote=True)
        return

    url = m.text.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        # Agar ye command nahi hai aur link bhi nahi, ignore karein
        return

    # Single link process function call
    await process_video(bot, m, url, is_bulk=False)

print("Bot Started Successfully...")
bot.run()
