"""
bot.py - Bot Telegram para Afiliados
======================================
Versões: python-telegram-bot>=22, google-genai>=1, yt-dlp>=2024

Funcionalidades:
  - Recebe links de TikTok, Instagram, Pinterest, YouTube e MP4
  - Baixa o vídeo sem marca d'água usando yt-dlp
  - Remove metadados com FFmpeg
  - Gera descrições prontas para grupos e Stories com Gemini AI
  - Devolve tudo no Telegram

Uso:
  python bot.py
"""

import logging
import os
import re

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode, ChatAction

from downloader import download_video, cleanup_file, detect_platform
from cleaner import remove_metadata, get_file_size_mb, ffmpeg_available
from generator import generate_description, setup_gemini

# ──────────────────────────────────────────────
# Configuração de logs
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ──────────────────────────────────────────────
# Carrega variáveis de ambiente
# ──────────────────────────────────────────────
load_dotenv()

BOT_TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "")

ALLOWED_USERS: set[int] = set()
if ALLOWED_USERS_RAW.strip():
    for uid in ALLOWED_USERS_RAW.split(","):
        uid = uid.strip()
        if uid.isdigit():
            ALLOWED_USERS.add(int(uid))

MAX_FILE_SIZE_MB = 50

URL_PATTERN = re.compile(
    r"https?://[^\s]+"
    r"|www\.[^\s]+"
    r"|(?:tiktok|instagram|youtube|pinterest)\.com/[^\s]+",
    re.IGNORECASE,
)

# ──────────────────────────────────────────────
# Mensagens
# ──────────────────────────────────────────────
MSG_WELCOME = (
    "🤖 *Bot de Afiliados* está pronto\\!\n\n"
    "📲 *Como usar:*\n"
    "Envie um link de vídeo de qualquer plataforma:\n\n"
    "• 🎵 TikTok\n"
    "• 📸 Instagram \\(Reels/Posts\\)\n"
    "• 📌 Pinterest\n"
    "• ▶️ YouTube\n"
    "• 🎬 Link MP4 direto\n\n"
    "O que faço:\n"
    "✅ Baixo o vídeo *sem marca d'água*\n"
    "✅ Removo todos os metadados/rastreio\n"
    "✅ Gero descrição pronta para grupos e Stories\n"
    "✅ Te devolvo tudo aqui\n\n"
    "*Comandos:* /ajuda /status"
)

MSG_AJUDA = (
    "💡 *Dicas de Uso*\n\n"
    "*Plataformas suportadas:*\n"
    "• TikTok: link do vídeo ou perfil\n"
    "• Instagram: link de Reels ou Post público\n"
    "• YouTube: link normal, shorts ou youtu\\.be\n"
    "• Pinterest: link de pin com vídeo\n"
    "• MP4: qualquer URL terminando em \\.mp4\n\n"
    "⚠️ *Avisos:*\n"
    "• Vídeos privados não funcionam\n"
    "• Limite de 50MB para envio\n"
    "• Se falhar, atualize: `pip install \\-U yt\\-dlp`"
)

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

def md_escape(text: str) -> str:
    """Escapa caracteres especiais para MarkdownV2."""
    chars = r"_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text

# ──────────────────────────────────────────────
# Handlers de comandos
# ──────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Você não tem permissão para usar este bot.")
        return
    await update.message.reply_text(MSG_WELCOME, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(MSG_AJUDA, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    ffmpeg_ok = ffmpeg_available()
    gemini_ok = bool(GEMINI_API_KEY and GEMINI_API_KEY != "SUA_CHAVE_GEMINI_AQUI")
    all_ok    = ffmpeg_ok and gemini_ok

    lines = [
        "🔍 *Status do Bot*\n",
        f"{'✅' if True    else '❌'} yt\\-dlp \\(download de vídeos\\)",
        f"{'✅' if ffmpeg_ok else '⚠️'} FFmpeg \\(remoção de metadados\\)" + (
            "" if ffmpeg_ok else " — *não instalado*"
        ),
        f"{'✅' if gemini_ok else '⚠️'} Gemini AI \\(gerador de descrições\\)" + (
            "" if gemini_ok else " — *chave não configurada*"
        ),
        "",
        "🟢 Tudo operacional\\!" if all_ok else "🟡 Funcionando com recursos limitados",
    ]

    if not ffmpeg_ok:
        lines.append("\n💡 Instalar FFmpeg: https://ffmpeg\\.org/download\\.html")
    if not gemini_ok:
        lines.append("💡 Configure GEMINI\\_API\\_KEY no \\.env")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ──────────────────────────────────────────────
# Handler principal: recebe links
# ──────────────────────────────────────────────
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("⛔ Acesso não autorizado.")
        return

    message_text = update.message.text or ""
    urls = URL_PATTERN.findall(message_text)

    if not urls:
        await update.message.reply_text(
            "🔗 Nenhum link válido encontrado.\n"
            "Envie um link de TikTok, Instagram, YouTube, Pinterest ou MP4."
        )
        return

    url      = urls[0].strip()
    platform = detect_platform(url)

    # ── Etapa 1: Avisa que está processando
    status_msg = await update.message.reply_text(
        f"⏳ Baixando vídeo do {platform}... aguarde! 🔄"
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)

    # ── Etapa 2: Download
    logger.info(f"[{user.id}] Download: {url}")
    dl = await download_video(url)

    if not dl["success"]:
        await status_msg.edit_text(
            f"❌ Falha no download\n\n{dl['error']}\n\n"
            "💡 Verifique se o link é público e está correto."
        )
        return

    video_path   = dl["file_path"]
    video_title  = dl["title"]
    video_dur    = dl["duration"]
    original_desc = dl.get("description", "")

    # ── Etapa 3: Remove metadados
    await status_msg.edit_text("🧹 Removendo metadados e rastreadores...")

    clean       = await remove_metadata(video_path)
    final_path  = clean.get("output_path", video_path)
    has_ffmpeg  = clean.get("error") != "ffmpeg_missing"

    # ── Etapa 4: Gera descrições
    await status_msg.edit_text("✍️ Gerando descrições para afiliados com IA...")

    desc = await generate_description(
        title=video_title,
        platform=platform,
        original_description=original_desc,
        duration=video_dur,
    )

    # ── Etapa 5: Verifica tamanho
    file_size = get_file_size_mb(final_path)
    logger.info(f"[{user.id}] Pronto: {file_size} MB")

    await status_msg.edit_text(f"📤 Enviando vídeo ({file_size} MB)...")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)

    # ── Etapa 6: Envia vídeo
    send_ok = False
    try:
        if file_size > MAX_FILE_SIZE_MB:
            await update.message.reply_text(
                f"⚠️ Vídeo muito grande ({file_size} MB).\n"
                f"Limite do Telegram: {MAX_FILE_SIZE_MB} MB.\n"
                "Tente um vídeo menor."
            )
        else:
            caption = f"🎬 {video_title[:100]}\n📲 {platform} | {file_size} MB"
            if not has_ffmpeg:
                caption += "\n⚠️ FFmpeg não instalado — metadados mantidos"

            with open(final_path, "rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=30,
                )
            send_ok = True

    except Exception as e:
        logger.error(f"Erro ao enviar vídeo: {e}")
        try:
            with open(final_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    caption=f"📁 {video_title[:100]} ({file_size} MB)",
                    read_timeout=120,
                    write_timeout=120,
                )
            send_ok = True
        except Exception as e2:
            logger.error(f"Erro ao enviar documento: {e2}")
            await update.message.reply_text(f"❌ Não foi possível enviar o arquivo:\n{e}")

    # ── Etapa 7: Envia descrições
    if send_ok:
        ai_label = "🤖 Gerado com IA" if desc.get("used_ai") else "📝 Template padrão"

        desc_text = (
            f"📋 DESCRIÇÕES PRONTAS — {ai_label}\n"
            f"{'─' * 34}\n\n"
            f"👥 Post para Grupos (WhatsApp/Telegram):\n\n"
            f"{desc['group_post']}\n\n"
            f"{'─' * 34}\n\n"
            f"📱 Legenda para Instagram Story:\n\n"
            f"{desc['story_caption']}"
        )
        await update.message.reply_text(desc_text)

    # ── Etapa 8: Limpeza
    await status_msg.delete()
    cleanup_file(video_path)
    if final_path != video_path:
        cleanup_file(final_path)

    logger.info(f"[{user.id}] Concluído com sucesso!")


# ──────────────────────────────────────────────
# Mensagens desconhecidas
# ──────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "🤔 Me envie um link de vídeo para começar!\n"
        "Use /ajuda para ver as instruções."
    )


# ──────────────────────────────────────────────
# Handler global de erros
# ──────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Erro: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Ocorreu um erro inesperado. Tente novamente."
        )


# ──────────────────────────────────────────────
# Inicialização
# ──────────────────────────────────────────────
def main():
    if not BOT_TOKEN or BOT_TOKEN == "SEU_TOKEN_AQUI":
        print("❌ ERRO: Configure o TELEGRAM_BOT_TOKEN no arquivo .env")
        print("   Copie .env.example para .env e preencha seu token.")
        return

    has_gemini = bool(GEMINI_API_KEY and GEMINI_API_KEY != "SUA_CHAVE_GEMINI_AQUI")
    if has_gemini:
        setup_gemini(GEMINI_API_KEY)
        logger.info("Gemini AI configurado.")
    else:
        logger.warning("GEMINI_API_KEY nao configurada. Usando templates padrao.")

    if not ffmpeg_available():
        logger.warning("FFmpeg nao encontrado. Metadados NAO serao removidos.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("ajuda",  cmd_ajuda))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(URL_PATTERN),
        handle_link,
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_unknown,
    ))

    app.add_error_handler(error_handler)

    print("=" * 52)
    print("   BOT DE AFILIADOS INICIADO")
    print("=" * 52)
    print(f"   Python-telegram-bot : v22")
    print(f"   FFmpeg              : {'OK' if ffmpeg_available() else 'NAO INSTALADO'}")
    print(f"   Gemini AI           : {'Configurado' if has_gemini else 'NAO CONFIGURADO'}")
    print(f"   Usuarios permitidos : {'Todos' if not ALLOWED_USERS else str(ALLOWED_USERS)}")
    print("=" * 52)
    print("   Aguardando mensagens... (Ctrl+C para parar)\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
