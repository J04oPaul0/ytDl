from __future__ import annotations
import os
import shutil
import subprocess
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from collections import deque
from uuid import uuid4
from yt_dlp import YoutubeDL
import io
import re
from typing import TYPE_CHECKING

import asyncio
from functools import partial, wraps

TOKEN_BOT = os.environ["YT_TOKEN_BOT"]

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
def extract_info(instance: YoutubeDL, url: str, download=True):
    return instance.extract_info(url, download)

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
            '-f', "b[filesize<50M] / w",
            '--max-filesize', '50M',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',

            '-o', output_template,
            
            url
        ]
    else:
        ydl_command = [
            'yt-dlp',
            '-f', 'bestaudio[ext=m4a]',
            '--max-filesize', '50M',
            '--audio-format', 'mp3',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',

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

# Processa a fila de downloads
async def process_queue(context: ContextTypes.DEFAULT_TYPE):
    while download_queue:
        update, url_or_query, format_type, output_extension = download_queue.popleft()
        chat_id = update.message.chat_id

        await context.bot.send_message(chat_id=chat_id, text="Iniciando o download...")

        filename, error = download_media(url_or_query, format_type, output_extension, format_type)

        if error:
            await context.bot.send_message(chat_id=chat_id, text=error)
            shutil.rmtree(os.path.dirname(filename), ignore_errors=True)
        else:
            await context.bot.send_message(chat_id=chat_id, text="Download concluído! Enviando arquivo...")
            if format_type == 'video':
                try :
                    await context.bot.send_video(chat_id=chat_id, video=open(filename, 'rb'))
                except FileNotFoundError:
                    await context.bot.send_message(chat_id=chat_id, text="Erro ao tentar baixar!")

            else:
                try:
                    await context.bot.send_audio(chat_id=chat_id, audio=open(filename, 'rb'))
                except FileNotFoundError:
                    await context.bot.send_message(chat_id=chat_id, text="Erro ao tentar baixar!")

            shutil.rmtree(os.path.dirname(filename))
            
# Função para iniciar o download e adicionar à fila
async def start_ytdl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Por favor, envie uma URL do YouTube ou uma consulta de texto após o comando /ytdl.")
        return
    
    url_or_query = " ".join(context.args)
    ydl = YoutubeDL({"noplaylist": True})

    match = YOUTUBE_REGEX.match(url_or_query)

    t = TIME_REGEX.search(url_or_query)
    
    afsize = 0
    vfsize = 0

    if match:
        yt = await extract_info(ydl, match.group(), download=False)
    else:
        yt = await extract_info(ydl, f"ytsearch:{url_or_query}", download=False)
        yt = yt["entries"][0]
    
    for f in yt["formats"]:
        if f["format_id"] == "140" and f.get("filesize") is not None:
            afsize = f["filesize"] or 0
        print(f["format_id"], f["ext"], f.get("filesize"))
        if f["ext"] == "mp4" and f.get("filesize") is not None:
            vfsize = f["filesize"] or 0
    

    
    keyboard = [
        [InlineKeyboardButton("Vídeo (MP4) 📹", callback_data=f"video|{yt["id"]}|mp4|{vfsize}")],
        [InlineKeyboardButton("Áudio (MP3) 🎵", callback_data=f"audio|{yt["id"]}|mp3|{afsize}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Escolha o formato para download:", reply_markup=reply_markup)

# Callback para manipular a escolha do usuário
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    format_type, url_or_query, output_extension, size = query.data.split('|')
    size = int(size)
    if size>=MAX_FILESIZE:
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
    await update.message.reply_text(
        "🤖 Olá! Eu sou o bot de download de YouTube! \n\n"
        "Use o comando /ytdl seguido de uma URL do YouTube ou texto para pesquisar e baixar o vídeo ou áudio desejado. "
        "Eu vou te guiar pelo processo! 📥\n\n"
        "Digite /help para mais informações."
    )

# Mensagem de ajuda
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ **Comandos disponíveis:**\n\n"
        "🔹 /start - Inicia o bot e mostra esta mensagem.\n"
        "🔹 /ytdl <URL ou Texto> - Baixa o vídeo ou áudio do YouTube de acordo com sua escolha.\n\n"
        "Depois de escolher o formato, o download será adicionado à fila. Você será notificado quando o arquivo estiver pronto!"
    )

def main():
    application = ApplicationBuilder().token(TOKEN_BOT).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ytdl", start_ytdl))
    application.add_handler(CallbackQueryHandler(button))

    # Método para iniciar o bot
    application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
