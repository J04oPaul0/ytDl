from __future__ import annotations
import os
import json
import shutil
import subprocess
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from collections import deque
from uuid import uuid4
from yt_dlp import YoutubeDL
import io
import re
from typing import TYPE_CHECKING
from config import Config
import asyncio
from functools import partial, wraps

from typesp.video import Video

app_config = Config()

if TYPE_CHECKING:
    from collections.abc import Callable

def aiowrap(func: Callable) -> Callable:
    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, pfunc)

    return run
# Token do bot

YOUTUBE_REGEX = re.compile(
    r"(?m)http(?:s?):\/\/(?:www\.)?(?:music\.)?youtu(?:be\.com\/(watch\?v=|shorts/)|\.be\/|)([\w\-\_]*)(&(amp;)?[\w\?=]*)?"
)
MAX_FILESIZE = 200000000

@aiowrap
def extract_info(url: str, download=True, isSearch=False):
    command = [
        "yt-dlp", "--no-playlist", "--dump-json", "--username","oauth2" "--password", "''",
        url]
    
    if isSearch:
        command = [
        "yt-dlp","--username","oauth2" "--password", "''","--default-search", url ,
        "--no-playlist", "--dump-json", 
        url]

    print(command)
    result = subprocess.run(command, capture_output=True, text=True)
    video_info = json.loads(result.stdout)

    return video_info

TIME_REGEX = re.compile(r"[?&]t=([0-9]+)")
# Fila de downloads
download_queue = deque()

# Função para baixar o vídeo ou áudio
def download_media(idv, format, output_extension, tipo):
    unique_id = uuid4().hex
    url = f"https://www.youtube.com/watch?v={idv}"
    download_dir = f'downloads/{unique_id}'
    os.makedirs(download_dir, exist_ok=True)
    output_template = f'{download_dir}/%(title)s.{output_extension}'

    if tipo == "video":
        ydl_command = [
            'yt-dlp',
            "--username","oauth2" "--password", "''",
            '--no-playlist',
            '--cookies', 'cookies.txt',
            '-f', "b[filesize<50M] / w",
            '--max-filesize', '50M',
            '-o', output_template,
            
            url
        ]
    else:
        ydl_command = [
            'yt-dlp',
            "--username","oauth2" "--password", "''",
            '--no-playlist',
            '--cookies', 'cookies.txt',
            '-f', 'bestaudio[ext=m4a]',
            '--max-filesize', '50M',
            '--audio-format', 'mp3',
            '-o', output_template,
            url
        ]
    # Remove None values from the command
    ydl_command = [arg for arg in ydl_command if arg]

    try:
        result = subprocess.run(ydl_command, check=True, capture_output=True, text=True)
        output = result.stdout.strip()

        for line in output.splitlines():
            if "Destination:" in line:
                downloaded_file = line.split("Destination: ")[1]
                return downloaded_file, None
        return None, "Arquivo não encontrado."
    except subprocess.CalledProcessError as e:
        if "File is larger than max-filesize" in e.stderr:
            return None, "O conteúdo excede 50MB."
        return None, "Erro ao baixar o conteúdo."
    except Exception as e:
        return None, f"Erro inesperado: {str(e)}"

async def get_info(url: str )-> Video:
    ydl = YoutubeDL({"noplaylist": True, 'cookiefile':"cookies.txt"})
    info = Video()
    yt = await extract_info(ydl, url, download=False)
    info.thumb = yt["thumbnail"]
    info.title = yt["title"]
    info.performer = yt.get("creator") or yt.get("uploader")
    return info
    
# Processa a fila de downloads
async def process_queue(context: ContextTypes.DEFAULT_TYPE):
    while download_queue:
        update, url_or_query, format_type, output_extension = download_queue.popleft()
        chat_id = update.message.chat_id

        # Enviar uma mensagem inicial e obter o ID para edição
        sent_message = await context.bot.send_message(chat_id=chat_id, text="Iniciando o download...")

        filename, error = download_media(url_or_query, format_type, output_extension, format_type)

        if error:
            # Editar a mensagem em vez de enviar uma nova
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=error)
            shutil.rmtree(os.path.dirname(filename), ignore_errors=True)
        else:
            # Editar a mensagem para mostrar progresso
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="Download concluído! Enviando arquivo...")

            if format_type == 'video':
                try:
                    await context.bot.send_video(
                        chat_id=chat_id, 
                        video=open(filename, 'rb'),
                        supports_streaming=True
                    )
                    # Apagar a mensagem de status após o envio
                    await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
                except FileNotFoundError:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="Erro ao tentar baixar!")
            else:
                info = await get_info(url_or_query)
                try:
                    thumb = io.BytesIO(httpx.get(info.thumb).content)
                    thumb.name = "thumbnail.png"

                    await context.bot.send_audio(
                        chat_id=chat_id, 
                        audio=open(filename, 'rb'),
                        title=info.title,
                        performer=info.performer,
                        thumbnail=thumb
                    )
                    # Apagar a mensagem de status após o envio
                    await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
                except FileNotFoundError:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="Erro ao tentar baixar!")

            shutil.rmtree(os.path.dirname(filename))
            
# Função para iniciar o download e adicionar à fila
async def start_ytdl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Por favor, envie uma URL do YouTube ou uma consulta de texto após o comando /ytdl.")
        return
    
    url_or_query = " ".join(context.args)
    match = YOUTUBE_REGEX.match(url_or_query)

    t = TIME_REGEX.search(url_or_query)
    
    afsize = 0
    vfsize = 0

    if match:
        yt = await extract_info(match.group(), download=False)
    else:
        yt = await extract_info(f"ytsearch:{url_or_query}", download=False,isSearch=True)
    
    for f in yt["formats"]:
        if f["format_id"] == "140" and f.get("filesize") is not None:
            afsize = f["filesize"] or 0
        
        if f["ext"] == "mp4" and f.get("filesize") is not None:
            vfsize = f["filesize"] or 0
        
    keyboard = [
        [InlineKeyboardButton("Vídeo (MP4) 📹", callback_data=f"video|{yt["id"]}|mp4|{vfsize}")],
        [InlineKeyboardButton("Áudio (MP3) 🎵", callback_data=f"audio|{yt["id"]}|mp3|{afsize}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Escolha o formato para {yt['title']}:", reply_markup=reply_markup)

# Callback para manipular a escolha do usuário
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    format_type, url_or_query, output_extension, size = query.data.split('|')
    size = int(size)
    if size >= MAX_FILESIZE:
        await query.edit_message_text("Não consigo baixar esse arquivo.")
        return    
    # Adiciona à fila
    download_queue.append((query, url_or_query, format_type, output_extension))
    await query.edit_message_text(text="Download adicionado à fila. Por favor, aguarde...")

    # Inicia o processamento da fila se não estiver em execução
    if len(download_queue) == 1:
        await process_queue(context)

# Mensagem de start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(app_config.TEXT_START)

# Mensagem de ajuda
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(app_config.TEXT_HELP)

def main():
    application = ApplicationBuilder().token(app_config.TOKEN_BOT).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ytdl", start_ytdl))
    application.add_handler(CallbackQueryHandler(button))

    # Método para iniciar o bot
    application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
