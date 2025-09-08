#!/usr/bin/env python3
"""
RX Ultimate Video Downloader Bot - Fixed Professional Edition
Supports ALL major platforms with reliable downloads
Optimized for Android/Termux deployment
"""

import os
import logging
import asyncio
import hashlib
import base64
import re
import tempfile
import math
import subprocess
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    import yt_dlp
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import Command
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.utils.chat_action import ChatActionMiddleware
    from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
    import aiofiles
    import aiohttp
except ImportError as e:
    logging.error(f"Required packages not installed: {e}")
    # Try to auto-install missing packages
    try:
        subprocess.check_call(["pip", "install", "yt-dlp", "aiogram", "aiofiles", "aiohttp"])
        logging.info("Missing packages installed successfully")
    except:
        logging.error("Failed to auto-install packages. Please install manually: pip install yt-dlp aiogram aiofiles aiohttp")
    raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ])
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN") or "7801242693:AAHdcM9ZC22S-oXGWk5MYc1xXD9-7JT21AM"
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

# Channel information
CHANNEL_USERNAME = "@rxfreezone"
CHANNEL_URL = "https://t.me/rxfreezone"

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
CHUNK_SIZE = 45 * 1024 * 1024  # 45MB per chunk

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.message.middleware(ChatActionMiddleware())

# Platform Icons
PLATFORM_ICONS = {
    "youtube": "", "facebook": "", "instagram": "", "tiktok": "",
    "twitter": "", "snapchat": "", "linkedin": "", "pinterest": "",
    "reddit": "", "vimeo": "", "dailymotion": "", "twitch": "",
    "soundcloud": "", "terabox": "", "likee": "", "kwai": "",
    "bilibili": "", "telegram": "", "discord": "", "default": "",
    "pinterest": "", "rutube": "", "ok": "", "whatsapp": ""
}

# Supported platforms
SUPPORTED_PLATFORMS = {
    "youtube.com", "youtu.be", "m.youtube.com", "youtube-nocookie.com",
    "facebook.com", "fb.watch", "m.facebook.com", "web.facebook.com",
    "instagram.com", "www.instagram.com", "tiktok.com", "vm.tiktok.com",
    "twitter.com", "x.com", "reddit.com", "v.redd.it", "vimeo.com",
    "dailymotion.com", "twitch.tv", "soundcloud.com", "terabox.com",
    "likee.com", "kwai.com", "bilibili.com", "t.me", "discord.com",
    "pin.it", "pinterest.com", "rutube.ru", "ok.ru", "whatsapp.com"
}

# Global storage
url_cache: Dict[str, str] = {}

def clean_text(text: str) -> str:
    """Clean text for safe display"""
    if not text:
        return "Unknown"
    # Remove or replace problematic characters
    text = str(text).replace('&', 'and').replace('<', '').replace('>', '')
    text = re.sub(r'[^\w\s\-_.,!?()[\]]', '', text)
    return text[:100] + "..." if len(text) > 100 else text

def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB"]
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe use"""
    if not filename:
        return "video"
    # Remove problematic characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(filename))
    filename = re.sub(r'[^\w\s\-_\.]', '', filename)
    filename = filename.strip()
    
    # Limit length
    if len(filename) > 80:
        name, ext = os.path.splitext(filename)
        filename = name[:70] + "..." + ext
        
    return filename or "video"

def generate_url_id(url: str) -> str:
    """Generate short ID for URL"""
    try:
        hash_obj = hashlib.md5(url.encode('utf-8'))
        return base64.urlsafe_b64encode(hash_obj.digest())[:12].decode('utf-8')
    except:
        return "default"

def store_url(url: str) -> str:
    """Store URL and return ID"""
    url_id = generate_url_id(url)
    url_cache[url_id] = url
    return url_id

def get_url(url_id: str) -> Optional[str]:
    """Get URL by ID"""
    return url_cache.get(url_id)

def detect_platform(url: str) -> str:
    """Detect platform from URL"""
    url_lower = url.lower()
    
    if any(domain in url_lower for domain in ["youtube.com", "youtu.be"]):
        return "youtube"
    elif any(domain in url_lower for domain in ["facebook.com", "fb.watch"]):
        return "facebook"
    elif "instagram.com" in url_lower:
        return "instagram"
    elif any(domain in url_lower for domain in ["tiktok.com", "vm.tiktok.com"]):
        return "tiktok"
    elif any(domain in url_lower for domain in ["twitter.com", "x.com"]):
        return "twitter"
    elif "reddit.com" in url_lower or "v.redd.it" in url_lower:
        return "reddit"
    elif "vimeo.com" in url_lower:
        return "vimeo"
    elif "dailymotion.com" in url_lower:
        return "dailymotion"
    elif "twitch.tv" in url_lower:
        return "twitch"
    elif "soundcloud.com" in url_lower:
        return "soundcloud"
    elif "terabox.com" in url_lower:
        return "terabox"
    elif "likee.com" in url_lower:
        return "likee"
    elif "kwai.com" in url_lower:
        return "kwai"
    elif "bilibili.com" in url_lower:
        return "bilibili"
    elif "pinterest.com" in url_lower or "pin.it" in url_lower:
        return "pinterest"
    elif "rutube.ru" in url_lower:
        return "rutube"
    elif "ok.ru" in url_lower:
        return "ok"
    elif "whatsapp.com" in url_lower:
        return "whatsapp"
    
    return "default"

def is_valid_url(url: str) -> bool:
    """Validate URL"""
    try:
        if not url.startswith(('http://', 'https://')):
            return False
        
        domain_match = re.search(r'://(?:www\.)?([^/]+)', url.lower())
        if not domain_match:
            return False
        
        domain = domain_match.group(1)
        return any(platform in domain for platform in SUPPORTED_PLATFORMS)
    except:
        return False

def create_channel_keyboard() -> InlineKeyboardMarkup:
    """Create channel keyboard"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=" RX Free Zone   ", url=CHANNEL_URL))
    return builder.as_markup()

def create_quality_keyboard(url_id: str, platform: str) -> InlineKeyboardMarkup:
    """Create quality selection keyboard"""
    builder = InlineKeyboardBuilder()
    
    # High Quality
    builder.row(InlineKeyboardButton(
        text=" High Quality (1080p)",
        callback_data=f"dl:high:{url_id}"
    ))
    
    # Standard Quality
    builder.row(InlineKeyboardButton(
        text=" Standard Quality (720p)",
        callback_data=f"dl:standard:{url_id}"
    ))
    
    # Audio Only
    builder.row(InlineKeyboardButton(
        text=" Audio Only (MP3)",
        callback_data=f"dl:audio:{url_id}"
    ))
    
    # Channel button
    builder.row(InlineKeyboardButton(text=" RX Free Zone", url=CHANNEL_URL))
    
    return builder.as_markup()

# Welcome message
def get_welcome_message() -> str:
    return f""" RX ULTIMATE DOWNLOADER BOT 

              !

  :
 YouTube (  , Shorts)
 Facebook (, , Watch)
 Instagram (, , )
 TikTok ( )
 Twitter/X (, GIF)
 Reddit (, v.redd.it)
 Vimeo (HD )
 Dailymotion
 Twitch (, VOD)
 SoundCloud (MP3)
 Terabox ( )
 Likee, Kwai, Bilibili
 Pinterest, Rutube, OK.ru
 WhatsApp status
   !

 :
  High Speed Downloads
  1080p  
  320kbps MP3 
  Smart File Splitting
  Fast Processing

 :    !

   : {CHANNEL_USERNAME}"""

# Bot Commands
@dp.message(Command("start"))
async def start_command(message: types.Message) -> None:
    """Welcome message"""
    logger.info(f"Start command from user {message.from_user.id}")
    
    await message.answer(
        text=get_welcome_message(),
        reply_markup=create_channel_keyboard(),
        disable_web_page_preview=True
    )

@dp.message(Command("help"))
async def help_command(message: types.Message) -> None:
    """Help command"""
    help_text = f""" RX ULTIMATE DOWNLOADER 

  :
1.     
2.   
3.  !

 :
 1080p  
 320kbps MP3 
 50MB+   
   

  :
 URL      
    
     

 :
 /start -   
 /help -  

 : {CHANNEL_USERNAME}"""

    await message.answer(
        text=help_text,
        reply_markup=create_channel_keyboard(),
        disable_web_page_preview=True
    )

# URL Processing
@dp.message(F.text & ~F.text.startswith('/'))
async def process_url(message: types.Message) -> None:
    """Process video URLs"""
    try:
        url = message.text.strip()
        
        # Validate URL
        if not is_valid_url(url):
            await message.answer(
                " Invalid URL!\n\n"
                "       \n"
                "   /help   "
            )
            return

        # Detect platform
        platform = detect_platform(url)
        platform_icon = PLATFORM_ICONS.get(platform, "")
        
        # Store URL
        url_id = store_url(url)
        
        # Analysis message
        analysis_msg = await message.answer(" URL   ...")
        
        try:
            # Get basic info
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 30,
                'noplaylist': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                
            if info:
                title = clean_text(info.get('title', 'Unknown Title'))
                duration = info.get('duration', 0)
                uploader = clean_text(info.get('uploader', 'Unknown'))
                
                # Format duration
                if duration:
                    minutes, seconds = divmod(duration, 60)
                    hours, minutes = divmod(minutes, 60)
                    if hours:
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration_str = f"{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = "Unknown"
                
                success_text = f"""   !

{platform_icon} Platform: {platform.title()}
 Title: {title}
 Uploader: {uploader}
 Duration: {duration_str}

     :"""

                await analysis_msg.edit_text(
                    text=success_text,
                    reply_markup=create_quality_keyboard(url_id, platform)
                )
            else:
                # Fallback
                fallback_text = f""" URL !

{platform_icon} Platform: {platform.title()}
 Status: Ready for processing

     :"""

                await analysis_msg.edit_text(
                    text=fallback_text,
                    reply_markup=create_quality_keyboard(url_id, platform)
                )
                
        except Exception as e:
            logger.error(f"Error extracting video info: {e}")
            # Always show download options
            fallback_text = f""" URL !

{platform_icon} Platform: {platform.title()}
 Status: Ready for download

     :"""

            await analysis_msg.edit_text(
                text=fallback_text,
                reply_markup=create_quality_keyboard(url_id, platform)
            )
            
    except Exception as e:
        logger.error(f"Error processing URL: {e}")
        await message.answer(" URL   !   ")

# Download handlers
@dp.callback_query(F.data.startswith("dl:"))
async def handle_download(callback: types.CallbackQuery) -> None:
    """Handle download requests"""
    await callback.answer()
    
    try:
        parts = callback.data.split(":")
        quality = parts[1]
        url_id = parts[2]
        
        url = get_url(url_id)
        if not url:
            await callback.message.answer(" URL  !   ")
            return
        
        platform = detect_platform(url)
        platform_icon = PLATFORM_ICONS.get(platform, "")
        
        # Start download
        download_msg = await callback.message.answer(
            f"   ...\n\n"
            f"{platform_icon} Platform: {platform.title()}\n"
            f" Quality: {quality.title()}\n"
            f" Status: Processing..."
        )
        
        # Configure download options
        if quality == "high":
            format_selector = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        elif quality == "standard":
            format_selector = "bestvideo[height<=720]+bestaudio/best[height<=720]"
        elif quality == "audio":
            format_selector = "bestaudio"
        else:
            format_selector = "best"
        
        ydl_opts = {
            'format': format_selector,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 120,
            'retries': 5,
            'noplaylist': True,
            'noprogress': True,
        }
        
        # Platform optimizations
        if platform == "facebook":
            ydl_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        elif platform in ["tiktok", "instagram"]:
            ydl_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15'
            }
        
        # Audio processing
        if quality == "audio":
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
            ydl_opts['outtmpl'] = '%(title)s.%(ext)s'
        else:
            ydl_opts['merge_output_format'] = 'mp4'
            ydl_opts['outtmpl'] = '%(title)s.%(ext)s'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
            
            try:
                # Try download with fallback
                success = False
                formats_to_try = [format_selector, "best", "worst"]
                
                for fmt in formats_to_try:
                    try:
                        opts = ydl_opts.copy()
                        opts['format'] = fmt
                        
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            await asyncio.to_thread(ydl.download, [url])
                        
                        success = True
                        break
                    except Exception as e:
                        logger.warning(f"Format {fmt} failed: {e}")
                        continue
                
                if not success:
                    await download_msg.edit_text(
                        "  !\n\n"
                        " :\n"
                        " URL      \n"
                        "    \n"
                        "     "
                    )
                    return
                
                # Find downloaded file
                downloaded_files = [f for f in os.listdir(temp_dir) if not f.startswith('.')]
                if not downloaded_files:
                    await download_msg.edit_text("    !")
                    return
                
                file_path = os.path.join(temp_dir, downloaded_files[0])
                file_size = os.path.getsize(file_path)
                filename = sanitize_filename(downloaded_files[0])
                
                await download_msg.edit_text("   ...")
                
                # Create caption
                caption = f"""  !

{platform_icon} Platform: {platform.title()}
 Size: {format_file_size(file_size)}
 Quality: {quality.title()}

   : {CHANNEL_USERNAME}"""
                
                # Send file
                if file_size <= MAX_FILE_SIZE:
                    # Send as single file
                    async with aiofiles.open(file_path, 'rb') as f:
                        file_data = await f.read()
                    
                    if quality == "audio":
                        await callback.message.answer_audio(
                            audio=BufferedInputFile(file_data, filename=filename),
                            caption=caption,
                            reply_markup=create_channel_keyboard()
                        )
                    else:
                        await callback.message.answer_video(
                            video=BufferedInputFile(file_data, filename=filename),
                            caption=caption,
                            reply_markup=create_channel_keyboard()
                        )
                else:
                    # Large file - split and send
                    await callback.message.answer(
                        f"   \n\n"
                        f"Size: {format_file_size(file_size)}\n"
                        f"Telegram limit: 50MB\n\n"
                        f"      "
                    )
                    
                    # Split and send
                    with open(file_path, 'rb') as f:
                        chunk_num = 0
                        while True:
                            chunk_data = f.read(CHUNK_SIZE)
                            if not chunk_data:
                                break
                            
                            chunk_filename = f"{filename}.part{chunk_num:03d}"
                            await callback.message.answer_document(
                                document=BufferedInputFile(chunk_data, filename=chunk_filename),
                                caption=f" Part {chunk_num + 1} - {chunk_filename}"
                            )
                            chunk_num += 1
                            await asyncio.sleep(1)
                
                await download_msg.delete()
                logger.info(f"Download completed: {filename}")
                
            except Exception as e:
                logger.error(f"Download error: {e}")
                await download_msg.edit_text("  !    ")
                
    except Exception as e:
        logger.error(f"Error in handle_download: {e}")
        await callback.message.answer("    !")

# Error handler
@dp.errors()
async def error_handler(event, exception):
    """Global error handler"""
    logger.error(f"Unhandled error: {exception}")
    return True

async def main():
    """Start the bot"""
    logger.info("Starting RX Ultimate Downloader Bot...")
    
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())