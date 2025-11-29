import os
import time
import asyncio
import re # Import regex for URL extraction
import requests # For generic file downloads (like PDFs)
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
        # Avoid division by zero if diff is too small
        if diff < 1:
            diff = 1
        
        percentage = current * 100 / total
        
        # Calculate speed
        speed = current / diff
        speed_string = f"{humanbytes(speed)}/s"
        
        # Calculate ETA
        try:
            eta = int((total - current) / speed)
            eta_string = f"{str(datetime.timedelta(seconds=eta))} left"
        except ZeroDivisionError:
            eta_string = "Calculating..."
        
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

# yt-dlp's progress hook function (for download)
async def download_progress_hook(d, message, start_time, ud_type="Downloading"):
    if d['status'] == 'downloading':
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
        downloaded_bytes = d.get('downloaded_bytes', 0)
        
        if total_bytes:
            await progress_for_pyrogram(downloaded_bytes, total_bytes, ud_type, message, start_time)
    elif d['status'] == 'finished':
        await message.edit_text(f"✅ **Download Complete!**\n\n**Ab Upload Ho Raha Hai...**")

# Regex to find URLs in text
URL_REGEX = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"

# --- Main Download Logic (Refactored for better reusability) ---
async def process_single_link(bot_client: Client, original_message: Message, url: str):
    user_id = original_message.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await original_message.reply("**You Are Not Subscribed To This Bot**", quote=True)
        return

    # Reply to the user to show that processing for this specific link has started
    msg = await original_message.reply_text(f"🔎 **Link Process Ho Raha Hai:** `{url}`\n**Jankari Nikali Jaa Rahi Hai...**", quote=True)

    out_filename = None # Initialize to None for cleanup

    try:
        # Check if it's a direct file download (like PDF from Drive)
        if "drive.google.com" in url and ("file/d/" in url or "uc?id=" in url):
            # Try to get file extension if possible from the URL
            file_extension = ".dat" # Default
            match = re.search(r'\.([a-zA-Z0-9]+)(?:[\?\/]|$)', url)
            if match:
                file_extension = f".{match.group(1)}"
            
            # For Google Drive files, yt-dlp might fail for non-video.
            # We can try a direct download using requests for such cases.
            # Simplified approach: If yt-dlp fails, we can assume it's not a video it can handle
            # and potentially try generic download. But for now, let's keep it within yt-dlp's scope
            # and let it fail if it's not a video/audio.
            pass # Continue to yt-dlp logic
            
        # 2. Extract Info using yt-dlp
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True, # Only extract info first
        }

        with YoutubeDL(ydl_opts) as ydl:
            try:
                info_dict = ydl.extract_info(url, download=False)
                original_title = info_dict.get('title', 'Video')
                # Title modification logic
                final_title = f"{original_title} @skillneast"
                
                # Get preferred extension
                ext = info_dict.get('ext', 'mp4')
                if not ext: ext = 'mp4' # Fallback
                
            except Exception as e:
                await msg.edit_text(f"❌ **Link Ki Jankari Nikalne Mein Erro Ho Gaya Ya Ye Video Nahi Hai:** {e}")
                return

        # 3. Download Video
        await msg.edit_text(f"⬇️ **Download Ho Raha Hai:** `{final_title}.{ext}`\n\n**Kripya Intezaar Kare...**")
        
        # Output filename template
        temp_filename_base = f"download_{original_message.from_user.id}_{int(time.time())}"
        
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
        
        # Check file size for upload type
        file_size = os.path.getsize(out_filename)
        if file_size > 2000 * 1024 * 1024: # 2 GB limit approx
            await msg.edit_text(f"❌ **File size {humanbytes(file_size)} bada hai. Telegram ki {humanbytes(2000 * 1024 * 1024)} limit se zyada.**")
            return

        # Determine if it's a video or document based on extension
        if final_file_extension.lower() in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
            await original_message.reply_video(
                video=out_filename,
                caption=f"**{final_title}**\n\nDownloaded by: {original_message.from_user.mention}",
                supports_streaming=True,
                progress=progress_for_pyrogram,
                progress_args=("Uploading", msg, upload_start_time)
            )
        else:
            await original_message.reply_document(
                document=out_filename,
                caption=f"**{final_title}**\n\nDownloaded by: {original_message.from_user.mention}",
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

# Store active bulk handlers to prevent multiple concurrent bulk processes per user
active_bulk_handlers = {}

@bot.on_message(filters.command(["bulk"]))
async def bulk_download_command(bot: Client, m: Message):
    user_id = m.from_user.id
    if user_id not in auth_users and user_id not in sudo_users:
        await m.reply("**You Are Not Subscribed To This Bot**", quote=True)
        return

    if user_id in active_bulk_handlers:
        await m.reply_text("Ek bulk download pehle se chal raha hai. Kripya uske khatam hone ka intezaar kare ya /cancelbulk use kare (agar banaya ho).")
        return
    
    bulk_prompt_msg = await m.reply_text(
        "**Bulk Download Mode Shuru Hua:**\n"
        "Ab mujhe ek message mein multiple YouTube/Google Drive links bhejo.\n"
        "Har link ek naye line mein hona chahiye.\n\n"
        "Example:\n"
        "`https://www.youtube.com/watch?v=video1`\n"
        "`https://drive.google.com/file/d/video2/view`"
    )

    # Use a temporary handler to capture the next message with links
    @bot.on_message(filters.text & filters.user(m.from_user.id))
    async def process_bulk_links(client: Client, message: Message):
        # Ensure this handler only runs once for the prompt
        if message.id <= bulk_prompt_msg.id:
            return

        # Remove this handler immediately after capturing the links to prevent further triggers
        client.remove_handler(process_bulk_links)
        del active_bulk_handlers[user_id] # Mark bulk process as finished for this user
        
        raw_lines = message.text.split('\n')
        links_to_process = []

        for line in raw_lines:
            # Extract URL using regex, ignoring any leading numbers or text
            match = re.search(URL_REGEX, line)
            if match:
                extracted_url = match.group(0).strip()
                if extracted_url.startswith("http://") or extracted_url.startswith("https://"):
                    links_to_process.append(extracted_url)
            
        if not links_to_process:
            await message.reply_text("Koi valid link nahi mila. Kripya sahi format mein links bheje.", quote=True)
            return

        await message.reply_text(f"**Bulk download shuru ho raha hai for {len(links_to_process)} links.**", quote=True)
        
        for i, link in enumerate(links_to_process):
            await message.reply_text(f"**Link {i+1}/{len(links_to_process)} Process Ho Raha Hai:**", quote=True)
            await process_single_link(bot, message, link) # Pass original message for replying
            await asyncio.sleep(2) # Small delay between downloads to prevent flooding

        await message.reply_text("**Bulk download complete!**", quote=True)

    # Store the handler to manage it later (e.g., removal)
    active_bulk_handlers[user_id] = process_bulk_links
    bot.add_handler(process_bulk_links)


@bot.on_message(filters.text & ~filters.command(["start", "commands", "help", "bulk"]))
async def handle_single_link(bot: Client, m: Message):
    url = m.text.strip()
    # Apply URL regex to ensure it's a clean URL
    match = re.search(URL_REGEX, url)
    if not match:
        await m.reply_text("Please send a valid Link starting with http or https.", quote=True)
        return
    
    clean_url = match.group(0).strip()
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        await m.reply_text("Please send a valid Link starting with http or https.", quote=True)
        return
        
    await process_single_link(bot, m, clean_url)


print("Bot Started...")
bot.run()
