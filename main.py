import os
import time
import asyncio
import math
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# --- Bot Initialization ---
bot = Client(
    "video_downloader_bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
)

# --- Helper Functions ---

def humanbytes(size):
    """Human readable file size"""
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

async def progress_for_pyrogram(current, total, ud_type, message, start_time):
    """Advanced progress bar function"""
    now = time.time()
    diff = now - start_time
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff)
        eta = round((total - current) / speed) if speed > 0 else 0
        
        # Progress bar visuals
        progress_bar = "[{0}{1}]".format(
            ''.join(["█" for i in range(math.floor(percentage / 10))]),
            ''.join(["░" for i in range(10 - math.floor(percentage / 10))])
        )

        # Text format
        progress_text = (
            f"**{ud_type}**\n"
            f"{progress_bar} {round(percentage, 2)}%\n"
            f"➢ **Size:** {humanbytes(current)} / {humanbytes(total)}\n"
            f"➢ **Speed:** {humanbytes(speed)}/s\n"
            f"➢ **ETA:** {time.strftime('%H:%M:%S', time.gmtime(eta))}"
        )
        
        try:
            await message.edit_text(text=progress_text)
        except Exception:
            pass

# --- Core Video Processing Function ---

async def process_link(bot: Client, m: Message, url: str):
    """
    This function handles the entire process for a single link:
    - Extracts info
    - Downloads video
    - Uploads video
    - Cleans up
    """
    msg = await m.reply_text("🔎 **Processing Link & Extracting Info...**", quote=True)

    try:
        # 1. Extract Info using yt-dlp
        ydl_opts = {'format': 'best', 'quiet': True, 'no_warnings': True}
        with YoutubeDL(ydl_opts) as ydl:
            try:
                info_dict = ydl.extract_info(url, download=False)
                original_title = info_dict.get('title', 'Video').strip()
                final_title = f"{original_title} @skillneast"
            except Exception as e:
                await msg.edit_text(f"❌ Error getting link info: `{e}`")
                return

        # 2. Download Video
        await msg.edit_text(f"⬇️ **Downloading:** `{final_title}`\n\nPlease wait...")
        
        out_filename = f"{final_title}.mp4"
        download_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': out_filename,
            'quiet': True,
            'noplaylist': True,
        }

        with YoutubeDL(download_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(out_filename):
            found = False
            for file in os.listdir('.'):
                if file.startswith(original_title):
                    out_filename = file
                    found = True
                    break
            if not found:
                await msg.edit_text("❌ Download Failed. File not found after download.")
                return

        # 3. Upload Video
        start_time = time.time()
        await m.reply_video(
            video=out_filename,
            caption=f"**{final_title}**\n\nDownloaded by: {m.from_user.mention}",
            supports_streaming=True,
            progress=progress_for_pyrogram,
            progress_args=("⬆️ Uploading...", msg, start_time)
        )

        # 4. Cleanup
        await msg.delete()
        if os.path.exists(out_filename):
            os.remove(out_filename)

    except Exception as e:
        await msg.edit_text(f"❌ **An unexpected error occurred:**\n`{str(e)}`")
        if 'out_filename' in locals() and os.path.exists(out_filename):
            os.remove(out_filename)

# --- Bot Command Handlers ---

@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    await m.reply_text(
        f"👋 Hello {m.from_user.first_name}!\n\n"
        "Mujhe koi bhi YouTube ya Google Drive (Public) video ka link bhejo.\n"
        "Main use download karke `@skillneast` tag ke sath bhej dunga.\n\n"
        "Ek se zyada link ek sath download karne ke liye `/bulk` command ka istemal karein."
    )

@bot.on_message(filters.command(["bulk"]))
async def bulk_download(bot: Client, m: Message):
    # Auth Check
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await m.reply("**You Are Not Authorised To Use This Bot**", quote=True)
        return

    try:
        links_text = m.text.split(None, 1)[1]
        links = [link.strip() for link in links_text.strip().split('\n') if link.strip()]
    except IndexError:
        await m.reply("`/bulk` command ke baad links bhejein. Har link ek nayi line mein hona chahiye.", quote=True)
        return

    if not links:
        await m.reply("Please provide links after the /bulk command.", quote=True)
        return

    total_links = len(links)
    await m.reply(f"✅ **Bulk process started for {total_links} links.**\n\nMain ek-ek karke sabhi videos bhej dunga.", quote=True)

    for i, link in enumerate(links):
        status_msg = await m.reply(f"**Processing Link {i+1}/{total_links}**\n`{link}`", quote=True)
        try:
            await process_link(bot, m, link)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(f"❌ **Failed to process link {i+1}/{total_links}:**\n`{link}`\n\n**Error:** `{e}`")
            continue
    
    await m.reply("🎉 **Bulk process finished!**", quote=True)

# THE FIX IS HERE 👇
@bot.on_message(filters.text & ~filters.command())
async def single_download(bot: Client, m: Message):
    # Auth Check
    user_id = m.from_user.id
    if auth_users and user_id not in auth_users and user_id not in sudo_users:
        await m.reply("**You Are Not Authorised To Use This Bot**", quote=True)
        return

    url = m.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await m.reply_text("Please send a valid Link starting with http or https.")
        return
    
    await process_link(bot, m, url)


# --- Start The Bot ---
async def main():
    print("Bot Starting...")
    await bot.start()
    print("Bot Started Successfully!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
