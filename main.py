import os
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from config import api_id, api_hash, bot_token
from yt_dlp import YoutubeDL

# Agar aapko auth users rakhna hai to rakhein, warn sabke liye open ke liye ise hata dein
from config import auth_users, sudo_users 

bot = Client(
    "bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
)

# Progress Bar Function (Simple version included here to avoid helper dependency)
async def progress(current, total, message):
    try:
        if total > 0:
            percentage = current * 100 / total
            if percentage % 10 == 0:  # Update every 10%
                await message.edit_text(f"Uploading... {round(percentage, 2)}%")
    except Exception:
        pass

@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    await m.reply_text(
        f"**👋 Hello [{m.from_user.first_name}](tg://user?id={m.from_user.id})!**\n\n"
        "Mujhe koi bhi **YouTube** ya **Google Drive** (Public) video ka link bhejo.\n"
        "Main use download karke **@skillneast** tag ke sath bhej dunga."
    )

@bot.on_message(filters.text)
async def download_video(bot: Client, m: Message):
    
    # 1. Auth Check (Optional - hata sakte ho agar public banana hai)
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await m.reply("**You Are Not Subscribed To This Bot**", quote=True)
        return

    url = m.text.strip()

    # Check valid URL
    if not (url.startswith("http://") or url.startswith("https://")):
        await m.reply_text("Please send a valid Link starting with http or https.")
        return

    msg = await m.reply_text("🔎 **Processing Link & Extracting Info...**")

    try:
        # 2. Extract Info using yt-dlp
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            try:
                info_dict = ydl.extract_info(url, download=False)
                original_title = info_dict.get('title', 'Video')
                # Title modification logic
                final_title = f"{original_title} @skillneast"
            except Exception as e:
                await msg.edit_text(f"❌ Error getting link info: {e}")
                return

        # 3. Download Video
        await msg.edit_text(f"⬇️ **Downloading:** `{final_title}`\n\nPlease wait...")
        
        # Output filename template
        out_filename = f"{final_title}.mp4"
        
        download_opts = {
            'format': 'bestvideo+bestaudio/best', # Best quality
            'outtmpl': out_filename, # Save with modified name
            'quiet': True,
            'noplaylist': True,
        }

        with YoutubeDL(download_opts) as ydl:
            ydl.download([url])

        # Verify file exists
        if not os.path.exists(out_filename):
            # Sometimes yt-dlp changes extension (like .mkv), find it
            found = False
            for file in os.listdir('.'):
                if file.startswith(final_title):
                    out_filename = file
                    found = True
                    break
            if not found:
                await msg.edit_text("❌ Download Failed. File not found.")
                return

        # 4. Upload Video
        await msg.edit_text("⬆️ **Uploading to Telegram...**")
        
        start_time = time.time()
        await m.reply_video(
            video=out_filename,
            caption=f"**{final_title}**\n\nDownloaded by: {m.from_user.mention}",
            supports_streaming=True,
            progress=progress,
            progress_args=(msg,)
        )

        # 5. Cleanup
        await msg.delete()
        if os.path.exists(out_filename):
            os.remove(out_filename)

    except Exception as e:
        await msg.edit_text(f"❌ **Error:** {str(e)}")
        # Cleanup if error occurs
        if 'out_filename' in locals() and os.path.exists(out_filename):
            os.remove(out_filename)

print("Bot Started...")
bot.run()
