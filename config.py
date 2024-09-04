import os

class Config:
    def __init__(self) -> None:
        self.TOKEN_BOT = os.environ["YT_TOKEN_BOT"]
        self.TEXT_HELP = ("ℹ️ **Comandos disponíveis:**\n\n"
        "🔹 /start - Inicia o bot e mostra esta mensagem.\n"
        "🔹 /ytdl <URL ou Texto> - Baixa o vídeo ou áudio do YouTube de acordo com sua escolha.\n\n"
        "Depois de escolher o formato, o download será adicionado à fila. Você será notificado quando o arquivo estiver pronto!")
        self.TEXT_START =   ("🤖 Olá! Eu sou o bot de download de YouTube! \n\n"
        "Use o comando /ytdl seguido de uma URL do YouTube ou texto para pesquisar e baixar o vídeo ou áudio desejado. "
        "Eu vou te guiar pelo processo! 📥\n\n"
        "Digite /help para mais informações.")