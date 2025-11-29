import os
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from config import api_id, api_hash, bot_token, auth_users, sudo_users
from yt_dlp import YoutubeDL

# Initialize the bot client
bot = Client(
    "video_downloader_bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
)

# --- Helper Functions for Progress Bar ---
async def progress_for_pyrogram(current, total, ud_type, message, start_time):
    """
    Shows progress for Pyrogram upload/download.
    """
    now = time.time()
    diff = now - start_time
    if round(diff % 10.00) == 0 or current == total:
        # if round(diff % 10.00) == 0 or current == total:  # Update every 10 seconds or when finished
        percentage = current * 100 / total
        
        # Calculate speed
        speed = current / diff
        speed_string = f"{humanbytes(speed)}/s"
        
        # Calculate ETA
        eta = int((total - current) / speed)
        eta_string = f"{str(datetime.timedelta(seconds=eta))} left"
        
        # ASCII progress bar
        bar_length = 10
        filled_length = int(bar_length * current // total)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Construct the progress text
        progress_text = (
            f"**{ud_type}**\n"
            f"**Progress:** `{bar}` {percentage:.2f}%\n"
            f"**Size:** {humanbytes(current)} / {humanbytes(total)}\n"
            f"**Speed:** {speed_string}\n"
            f"**ETA:** {eta_string}"
        )
        
        try:
            await message.edit_text(progress_text)
        except Exception:
            pass

def humanbytes(size):
    """
    Converts bytes to human-readable format.
    """
    if not size:
        return ""
    power = 2**10
    n = 0
    dic_powerN = {0: ' ', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + dic_powerN[n] + 'B'

import datetime # Import datetime for ETA

# --- Command Handlers ---

@bot.on_message(filters.command(["start"]))
async def start_command(bot: Client, m: Message):
    await m.reply_text(
        f"**👋 Hello [{m.from_user.first_name}](tg://user?id={m.from_user.id})!**\n\n"
        "Mujhe koi bhi **YouTube** ya **Google Drive** (Public) video ka link bhejo.\n"
        "Main use download karke **@skillneast** tag ke sath bhej dunga.\n\n"
        "Type /commands for a list of available commands.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Developer 👨‍💻", url="https://t.me/skillneast")]]
        )
    )

@bot.on_message(filters.command(["commands", "help"]))
async def commands_command(bot: Client, m: Message):
    commands_list = (
        "**Available Commands:**\n\n"
        "**/start** - Bot ko start kare aur welcome message dekhe.\n"
        "**/commands** (or **/help**) - Sabhi commands ki list dekhe.\n"
        "**/bulk** - Multiple YouTube/Drive links download kare. Har link ko naye line mein bheje."
        "\n\n_Video download karne ke liye, bas link bhej dein._"
    )
    await m.reply_text(commands_list)

@bot.on_message(filters.command(["bulk"]))
async def bulk_download_command(bot: Client, m: Message):
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await m.reply("**You Are Not Subscribed To This Bot**", quote=True)
        return

    await m.reply_text(
        "**Bulk Download Mode:**\n"
        "Ab mujhe ek message mein multiple YouTube/Google Drive links bhejo.\n"
        "Har link ek naye line mein hona chahiye.\n\n"
        "Example:\n"
        "`https://www.youtube.com/watch?v=video1`\n"
        "`https://drive.google.com/file/d/video2/view`"
    )

    # Use a temporary handler to capture the next message with links
    @bot.on_message(filters.text & filters.reply & filters.user(m.from_user.id))
    async def process_bulk_links(client: Client, message: Message):
        if not message.reply_to_message or message.reply_to_message.id != m.id:
            return # Ignore if not a reply to the /bulk command itself

        links = [link.strip() for link in message.text.split('\n') if link.strip()]
        if not links:
            await message.reply_text("Koi link nahi mila. Kripya sahi format mein links bheje.")
            return

        await message.reply_text(f"**Bulk download shuru ho raha hai for {len(links)} links.**")
        
        for i, link in enumerate(links):
            # Process each link sequentially
            await message.reply_text(f"**Processing Link {i+1}/{len(links)}:** `{link}`")
            # Call the main download function logic
            # Create a dummy message object for download_video to use
            temp_msg = type('obj', (object,), {'text': link, 'from_user': message.from_user, 'reply_text': message.reply_text, 'reply_video': message.reply_video, 'edit_text': message.edit_text, 'delete': message.delete})()
            
            # Since download_video expects a Message object, we need to mock some attributes
            # Or refactor download_video to take link and user info separately.
            # For simplicity, let's create a temporary message with essential attributes
            class TempMessage:
                def __init__(self, original_msg, text_content):
                    self.id = original_msg.id # Use original message ID if needed for reply_to
                    self.from_user = original_msg.from_user
                    self.text = text_content
                    self.chat = original_msg.chat # Essential for reply functions

                async def reply_text(self, text, quote=True):
                    return await original_msg.reply_text(text, quote=quote)
                
                async def reply_video(self, video, caption, supports_streaming, progress, progress_args):
                    return await original_msg.reply_video(video, caption=caption, supports_streaming=supports_streaming, progress=progress, progress_args=progress_args)

                async def edit_text(self, text):
                    # This is tricky as we need to edit a specific message.
                    # For bulk, we'll send new messages, so this will act as a new reply.
                    return await original_msg.reply_text(text)

                async def delete(self):
                    # For bulk, we might not want to delete the main bulk message,
                    # but rather the individual progress messages.
                    pass # Do nothing for now, or handle specifically if needed.

            await download_video(bot, TempMessage(message, link))
            await asyncio.sleep(2) # Small delay between downloads

        await message.reply_text("**Bulk download complete!**")
        # Remove the temporary handler after processing
        bot.remove_handler(process_bulk_links)


@bot.on_message(filters.text & ~filters.command(["start", "commands", "help", "bulk"]))
async def download_video(bot: Client, m: Message):
    
    # 1. Auth Check (Optional - hata sakte ho agar public banana hai)
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await m.reply("**You Are Not Subscribed To This Bot**", quote=True)
        return

    url = m.text.strip()

    # Check valid URL
    if not (url.startswith("http://") or url.startswith("https://")):
        await m.reply_text("Please send a valid Link starting with http or https.", quote=True)
        return

    msg = await m.reply_text("🔎 **Link Process Ho Raha Hai Aur Jankari Nikali Jaa Rahi Hai...**", quote=True)

    out_filename = None # Initialize to None for cleanup

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
                await msg.edit_text(f"❌ **Link Ki Jankari Nikalne Mein Erro Ho Gaya:** {e}")
                return

        # 3. Download Video
        await msg.edit_text(f"⬇️ **Download Ho Raha Hai:** `{final_title}`\n\n**Kripya Intezaar Kare...**")
        
        # Output filename template
        # Use a temporary unique name to avoid conflicts, then rename
        temp_filename_base = f"download_{m.from_user.id}_{int(time.time())}"
        
        download_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', # Prioritize mp4, then best
            'outtmpl': f"{temp_filename_base}.%(ext)s", # Save with temporary base name and original extension
            'quiet': True,
            'noplaylist': True,
            'progress_hooks': [lambda d: asyncio.ensure_future(
                download_progress_hook(d, msg, start_time=time.time(), ud_type="Downloading")
            )],
        }

        download_start_time = time.time()
        with YoutubeDL(download_opts) as ydl:
            ydl.download([url])

        # Find the actual downloaded file
        found = False
        for file in os.listdir('.'):
            if file.startswith(temp_filename_base):
                out_filename = file
                found = True
                break
        
        if not found:
            await msg.edit_text("❌ **Download Ho Nahi Paaya. File Nahi Mili.**")
            return
        
        # Rename the file to the final title + @skillneast
        final_file_extension = os.path.splitext(out_filename)[1]
        new_final_filename = f"{final_title}{final_file_extension}"
        os.rename(out_filename, new_final_filename)
        out_filename = new_final_filename # Update out_filename to the new name

        # 4. Upload Video
        await msg.edit_text("⬆️ **Telegram Par Upload Ho Raha Hai...**")
        
        upload_start_time = time.time()
        await m.reply_video(
            video=out_filename,
            caption=f"**{final_title}**\n\nDownloaded by: {m.from_user.mention}",
            supports_streaming=True,
            progress=progress_for_pyrogram,
            progress_args=("Uploading", msg, upload_start_time)
        )

        # 5. Cleanup
        await msg.delete() # Delete the progress message
        if os.path.exists(out_filename):
            os.remove(out_filename)
            print(f"Cleaned up {out_filename}")

    except Exception as e:
        await msg.edit_text(f"❌ **Error Ho Gaya:** {str(e)}")
        # Cleanup if error occurs
        if out_filename and os.path.exists(out_filename):
            os.remove(out_filename)
            print(f"Cleaned up {out_filename} due to error.")

# yt-dlp's progress hook function (for download)
async def download_progress_hook(d, message, start_time, ud_type="Downloading"):
    if d['status'] == 'downloading':
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
        downloaded_bytes = d.get('downloaded_bytes', 0)
        
        if total_bytes:
            await progress_for_pyrogram(downloaded_bytes, total_bytes, ud_type, message, start_time)
    elif d['status'] == 'finished':
        await message.edit_text(f"✅ **Download Complete!**\n\n**Ab Upload Ho Raha Hai...**")


print("Bot Started...")
bot.run()
