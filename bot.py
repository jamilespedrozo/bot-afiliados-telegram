"""
bot.py - Bot Telegram para Afiliados
======================================
Versões: python-telegram-bot>=22, google-genai>=1, yt-dlp>=2024

Funcionalidades:
  - Recebe links de TikTok, Instagram, Pinterest, YouTube e MP4
  - Baixa o vídeo sem marca d'água usando yt-dlp
  - Remove metadados com FFmpeg
  - Gera descrição e hashtags com Gemini AI
  - Sistema de acesso pago integrado com Kiwify + PostgreSQL
  - Webhook HTTP para ativação automática de assinaturas
  - Verificação diária de planos expirados
"""

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode, ChatAction

from downloader import download_video, cleanup_file, detect_platform
from cleaner import remove_metadata, get_file_size_mb, ffmpeg_available
from generator import generate_description, generate_hashtags, setup_gemini
import database as db
import webhook as wh
import admin as adm

load_dotenv()

# ──────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────
BOT_TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
ADMIN_ID         = int(os.getenv("ADMIN_ID", "0"))
MAX_FILE_SIZE_MB = 50

# Freemium
FREE_USAGE_LIMIT = int(os.getenv("FREE_USAGE_LIMIT", "3"))
LINK_COMPRA      = os.getenv("LINK_COMPRA", "https://charm-craft-sell.lovable.app")

# Limites diários por plano (0 = ilimitado)
LIMITES_PLANO = {
    "starter": 15, "iniciante": 15, "afiliado iniciante": 15,
    "pro": 0, "afiliado pro": 0,
    "black": 0, "premium": 0, "escala": 0, "escala de vendas": 0,
    "trimestral": 0, "anual": 0,
    "vitalício": 0, "vitalicio": 0, "lifetime": 0,
}

URL_PATTERN = re.compile(
    r"https?://[^\s]+"
    r"|www\.[^\s]+"
    r"|(?:tiktok|instagram|youtube|pinterest)\.com/[^\s]+",
    re.IGNORECASE,
)

# Armazenamento temporário para callbacks dos botões inline
_pending: dict[str, dict] = {}

# Referência global ao app (usada pelo webhook para enviar boas-vindas)
_bot_app: Application | None = None

# ──────────────────────────────────────────────
# Logs
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
    "✅ Baixo sem marca d'água\n"
    "✅ Removo metadados\n"
    "✅ Gero descrição e hashtags com IA\n\n"
    "*Comandos:* /ajuda /status /meuacesso"
)

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def md_escape(text: str) -> str:
    """Escapa caracteres especiais para MarkdownV2."""
    chars = r"_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def build_keyboard(desc_id: str) -> InlineKeyboardMarkup:
    """Constrói o teclado inline com os botões de ação."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Descrição",     callback_data=f"group_{desc_id}"),
            InlineKeyboardButton("#️⃣ Hashtags",     callback_data=f"story_{desc_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Nova variação", callback_data=f"regen_{desc_id}"),
        ],
    ])


def _get_limite_diario(plano: str | None) -> int:
    """Retorna o limite diário de vídeos baseado no plano. 0 = ilimitado."""
    if not plano:
        return FREE_USAGE_LIMIT
    plano_lower = plano.lower().strip()
    for chave, limite in LIMITES_PLANO.items():
        if chave in plano_lower:
            return limite
    return 0  # plano pago desconhecido → ilimitado


# ──────────────────────────────────────────────
# Verificação freemium
# ──────────────────────────────────────────────
async def verificar_freemium(user_id: int) -> dict:
    """
    Retorna o status do usuário no modelo freemium.
    {
        'pode_usar': bool,
        'is_admin': bool,
        'is_pago': bool,
        'plano': str | None,
        'usos_hoje': int,
        'limite_diario': int,  # 0 = ilimitado
    }
    """
    if user_id == ADMIN_ID:
        return {'pode_usar': True, 'is_admin': True, 'is_pago': True,
                'plano': 'Admin', 'usos_hoje': 0, 'limite_diario': 0}

    loop = asyncio.get_event_loop()
    plano = await loop.run_in_executor(None, db.get_plano_usuario, user_id)
    usos_hoje = await loop.run_in_executor(None, db.consultar_usos_hoje, user_id)

    is_pago = plano is not None
    limite = _get_limite_diario(plano)

    if limite == 0:  # ilimitado
        pode_usar = True
    else:
        pode_usar = usos_hoje < limite

    return {
        'pode_usar': pode_usar,
        'is_admin': False,
        'is_pago': is_pago,
        'plano': plano,
        'usos_hoje': usos_hoje,
        'limite_diario': limite,
    }

# ──────────────────────────────────────────────
# Callback de boas-vindas (chamado pelo webhook)
# ──────────────────────────────────────────────
async def enviar_boas_vindas(telegram_id: int, nome: str, plano: str):
    """Envia mensagem de boas-vindas quando usuário é ativado via Kiwify."""
    if not _bot_app:
        return
    expiry = "Vitalício ♾️" if plano.lower() in ("vitalício", "vitalicio", "lifetime") else f"Plano: {plano}"
    msg = (
        f"🎉 *Bem\\-vindo, {md_escape(nome)}\\!*\n\n"
        f"Seu acesso ao *Bot de Afiliados* foi ativado\\!\n"
        f"✅ {md_escape(expiry)}\n\n"
        f"Envie um link de vídeo e eu cuido do resto\\.\n"
        f"Use /meuacesso para ver os detalhes do seu plano\\."
    )
    try:
        await _bot_app.bot.send_message(
            chat_id=telegram_id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logger.info(f"Boas-vindas enviadas para {telegram_id}")
    except Exception as e:
        logger.warning(f"Não foi possível enviar boas-vindas para {telegram_id}: {e}")


async def enviar_cancelamento(telegram_id: int):
    """Notifica usuário que o acesso foi cancelado."""
    if not _bot_app:
        return
    try:
        await _bot_app.bot.send_message(
            chat_id=telegram_id,
            text=(
                "⚠️ *Seu acesso foi cancelado*\n\n"
                "Se isso foi um erro, entre em contato com o suporte\\.\n"
                "Para renovar, adquira um novo plano\\."
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        logger.warning(f"Não foi possível notificar cancelamento para {telegram_id}: {e}")

# ──────────────────────────────────────────────
# Job diário: desativa planos expirados
# ──────────────────────────────────────────────
async def verificar_expirados():
    """Desativa usuários com plano vencido e os notifica."""
    logger.info("Verificando planos expirados...")
    loop = asyncio.get_event_loop()
    expirados = await loop.run_in_executor(None, db.desativar_expirados)
    for u in expirados:
        logger.info(f"Plano expirado: {u['telegram_id']} ({u.get('nome', '?')})")
        await enviar_cancelamento(u["telegram_id"])
    if expirados:
        logger.info(f"{len(expirados)} plano(s) expirado(s) desativado(s).")

# ──────────────────────────────────────────────
# Handlers de comandos
# ──────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    info  = await verificar_freemium(user.id)

    id_block = (
        f"🆔 *Seu ID do Telegram:* `{user.id}`\n"
        f"_Guarde este número para usar no checkout ao comprar o plano\\._\n\n"
    )

    if info['is_pago']:
        plano_str = md_escape(info['plano'] or '')
        limite_str = "♾️ Ilimitado" if info['limite_diario'] == 0 else f"{info['limite_diario']} vídeos/dia"
        extra = f"\n📦 *Plano:* {plano_str} \\| {limite_str}"
    else:
        restantes = max(0, FREE_USAGE_LIMIT - info['usos_hoje'])
        extra = (
            f"\n🆓 *Plano Grátis:* {restantes}/{FREE_USAGE_LIMIT} vídeos restantes hoje\n"
            f"_Faça upgrade para processar mais vídeos\\!_"
        )

    await update.message.reply_text(
        id_block + MSG_WELCOME + extra,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💡 *Dicas de Uso*\n\n"
        "*Plataformas suportadas:*\n"
        "• TikTok, Instagram Reels, YouTube, Pinterest, MP4\n\n"
        "🆓 *Plano Grátis:* 3 vídeos/dia\n"
        "🟢 *Starter:* 15 vídeos/dia — R$37/mês\n"
        "🟡 *Pro:* Ilimitado — R$67/mês\n"
        "🔵 *Black:* Ilimitado + prioridade — R$97/mês\n\n"
        "⚠️ *Avisos:*\n"
        "• Vídeos privados não funcionam\n"
        "• Limite de 50MB por vídeo\n"
        "• Use /meuacesso para ver seu plano"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_meuacesso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    info = await verificar_freemium(user.id)

    if info['is_admin']:
        await update.message.reply_text(
            "👑 Você é o *administrador* — acesso ilimitado\\.\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if info['is_pago']:
        loop  = asyncio.get_event_loop()
        dados = await loop.run_in_executor(None, db.buscar_usuario, user.id)
        expiry = dados.get("data_expiracao") if dados else None

        if expiry is None:
            exp_str = "♾️ Vitalício"
        else:
            now       = datetime.now(timezone.utc)
            dias_rest = (expiry - now).days
            data_fmt  = expiry.strftime("%d/%m/%Y")
            exp_str   = f"📅 {data_fmt} \\({dias_rest} dias restantes\\)"

        limite_str = "♾️ Ilimitado" if info['limite_diario'] == 0 else f"{info['limite_diario']} vídeos/dia"
        usos_str   = str(info['usos_hoje'])

        await update.message.reply_text(
            f"✅ *Seu Plano*\n\n"
            f"👤 Nome: {md_escape(dados.get('nome', '') if dados else '')}\n"
            f"📦 Plano: {md_escape(info['plano'] or '')}\n"
            f"📊 Limite diário: {limite_str}\n"
            f"🎬 Usos hoje: {usos_str}\n"
            f"⏰ Validade: {exp_str}\n",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        restantes = max(0, FREE_USAGE_LIMIT - info['usos_hoje'])
        await update.message.reply_text(
            f"🆓 *Plano Grátis*\n\n"
            f"🆔 Seu ID: `{user.id}`\n"
            f"🎬 Vídeos hoje: {info['usos_hoje']}/{FREE_USAGE_LIMIT}\n"
            f"📊 Restantes: {restantes}\n\n"
            f"_O limite reseta todo dia à meia\\-noite\\._\n\n"
            f"⬆️ *Faça upgrade* para processar mais vídeos\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Ver Planos", url=LINK_COMPRA)]
            ]),
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    ffmpeg_ok = ffmpeg_available()
    gemini_ok = bool(GEMINI_API_KEY and GEMINI_API_KEY != "SUA_CHAVE_GEMINI_AQUI")
    db_ok     = True
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, db.estatisticas)
    except Exception:
        db_ok = False

    all_ok = ffmpeg_ok and gemini_ok and db_ok

    lines = [
        "🔍 *Status do Bot*\n",
        f"{'✅' if True      else '❌'} yt\\-dlp \\(download de vídeos\\)",
        f"{'✅' if ffmpeg_ok else '⚠️'} FFmpeg \\(remoção de metadados\\)" + ("" if ffmpeg_ok else " — *não instalado*"),
        f"{'✅' if gemini_ok else '⚠️'} Gemini AI \\(gerador de descrições\\)" + ("" if gemini_ok else " — *chave não configurada*"),
        f"{'✅' if db_ok     else '❌'} PostgreSQL \\(banco de dados\\)" + ("" if db_ok else " — *erro de conexão*"),
        "",
        "🟢 Tudo operacional\\!" if all_ok else "🟡 Funcionando com recursos limitados",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ──────────────────────────────────────────────
# Handler principal: processa links
# ──────────────────────────────────────────────
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # ── Verificação freemium antes de processar ──
    info = await verificar_freemium(user.id)

    if not info['pode_usar']:
        limite = info['limite_diario']
        usos   = info['usos_hoje']

        if info['is_pago']:
            # Plano Starter atingiu o limite diário
            await update.message.reply_text(
                f"⚠️ *Limite diário atingido*\n\n"
                f"📊 Você usou *{usos}/{limite}* vídeos do seu plano hoje\\.\n"
                f"O limite reseta à meia\\-noite\\.\n\n"
                f"⬆️ Faça upgrade para *ilimitado*\\!",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Fazer Upgrade", url=LINK_COMPRA)]
                ]),
            )
        else:
            # Usuário grátis atingiu o limite
            await update.message.reply_text(
                f"⛔ *Limite grátis atingido\\!*\n\n"
                f"Você já usou seus *{FREE_USAGE_LIMIT} vídeos grátis* de hoje\\.\n"
                f"O limite reseta todo dia à meia\\-noite\\.\n\n"
                f"🆔 Seu ID: `{user.id}`\n"
                f"_Informe este ID no checkout ao comprar\\._\n\n"
                f"🟢 *Starter* — 15 vídeos/dia — R\\$37/mês\n"
                f"🟡 *Pro* — Ilimitado — R\\$67/mês\n"
                f"🔵 *Black* — Ilimitado \\+ extras — R\\$97/mês",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Assinar Agora", url=LINK_COMPRA)]
                ]),
            )
        return

    # ── Processar vídeo ──
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

    status_msg = await update.message.reply_text(
        f"⏳ Baixando vídeo do {platform}... aguarde! 🔄"
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)

    logger.info(f"[{user.id}] Download: {url}")
    dl = await download_video(url)

    if not dl["success"]:
        await status_msg.edit_text(
            f"❌ Falha no download\n\n{dl['error']}\n\n"
            "💡 Verifique se o link é público e está correto."
        )
        return

    video_path    = dl["file_path"]
    video_title   = dl["title"]
    video_dur     = dl["duration"]
    original_desc = dl.get("description", "")

    await status_msg.edit_text("🧹 Removendo metadados e rastreadores...")
    clean      = await remove_metadata(video_path)
    final_path = clean.get("output_path", video_path)
    has_ffmpeg = clean.get("error") != "ffmpeg_missing"

    await status_msg.edit_text("✍️ Gerando descrição e hashtags com IA...")
    desc = await generate_description(
        title=video_title,
        platform=platform,
        original_description=original_desc,
        duration=video_dur,
    )

    file_size = get_file_size_mb(final_path)
    logger.info(f"[{user.id}] Pronto: {file_size} MB")

    await status_msg.edit_text(f"📤 Enviando vídeo ({file_size} MB)...")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)

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

    if send_ok:
        # ── Registrar uso após sucesso ──
        loop = asyncio.get_event_loop()
        usos = await loop.run_in_executor(None, db.registrar_uso, user.id)

        ai_label = "🤖 IA" if desc.get("used_ai") else "📝 Template"

        desc_id = str(uuid.uuid4())[:8]
        _pending[desc_id] = {
            "group_post":    desc["group_post"],
            "story_caption": desc["story_caption"],
            "title":         video_title,
            "platform":      platform,
            "description":   original_desc,
        }

        # Mensagem com contador de uso (só para quem tem limite)
        limite = info['limite_diario']
        if limite > 0 and not info['is_admin']:
            restantes = limite - usos
            uso_info = f"\n\n📊 Usos: {usos}/{limite} | Restam: {restantes}"
            if restantes <= 1 and not info['is_pago']:
                uso_info += "\n⚡ _Quase no limite! Faça upgrade para continuar._"
        else:
            uso_info = ""

        await update.message.reply_text(
            f"✅ *Descrições prontas* — {ai_label}\n\nEscolha o que deseja:{uso_info}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_keyboard(desc_id),
        )

    await status_msg.delete()
    cleanup_file(video_path)
    if final_path != video_path:
        cleanup_file(final_path)

    logger.info(f"[{user.id}] Concluído com sucesso!")


# ──────────────────────────────────────────────
# Handler dos botões inline
# ──────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data.startswith("group_"):
        desc_id = data[6:]
        entry   = _pending.get(desc_id)
        if not entry:
            await query.message.reply_text("⏳ Sessão expirada. Processe o vídeo novamente.")
            return
        await query.answer("📝 Descrição enviada!", show_alert=False)
        await query.message.reply_text(
            f"📝 *Descrição do produto:*\n\n{entry['group_post']}",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("story_"):
        desc_id = data[6:]
        entry   = _pending.get(desc_id)
        if not entry:
            await query.message.reply_text("⏳ Sessão expirada. Processe o vídeo novamente.")
            return
        await query.answer("#️⃣ Hashtags enviadas!", show_alert=False)
        await query.message.reply_text(
            f"#️⃣ *Hashtags:*\n\n{entry['story_caption']}",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("regen_"):
        desc_id = data[6:]
        entry   = _pending.get(desc_id)
        if not entry:
            await query.message.reply_text("⏳ Sessão expirada. Processe o vídeo novamente.")
            return
        msg = await query.message.reply_text("🔄 Gerando nova variação com IA...")
        new_desc = await generate_description(
            title=entry["title"],
            platform=entry["platform"],
            original_description=entry["description"],
        )
        entry["group_post"]    = new_desc["group_post"]
        entry["story_caption"] = new_desc["story_caption"]
        _pending[desc_id]      = entry

        ai_label = "🤖 IA" if new_desc.get("used_ai") else "📝 Template"
        await msg.edit_text(
            f"✅ *Nova variação gerada* — {ai_label}\n\nEscolha o que deseja:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_keyboard(desc_id),
        )

    elif data.startswith("tags_"):
        desc_id = data[5:]
        entry   = _pending.get(desc_id)
        if not entry:
            await query.message.reply_text("⏳ Sessão expirada. Processe o vídeo novamente.")
            return
        msg = await query.message.reply_text("#️⃣ Gerando hashtags com IA...")
        hashtags = await generate_hashtags(
            title=entry["title"],
            platform=entry["platform"],
            original_description=entry["description"],
        )
        await msg.edit_text(
            f"#️⃣ *Hashtags para {entry['platform']}:*\n\n{hashtags}",
            parse_mode=ParseMode.MARKDOWN,
        )


# ──────────────────────────────────────────────
# Mensagens desconhecidas
# ──────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# Inicialização — post_init roda antes do polling
# ──────────────────────────────────────────────
async def post_init(app: Application):
    """Inicializa o banco, webhook e scheduler antes do bot começar."""
    global _bot_app
    _bot_app = app

    # 1. Banco de dados
    logger.info("Inicializando banco de dados...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, db.criar_tabelas)

    # 2. Webhook Kiwify
    wh.set_callbacks(
        on_activated=enviar_boas_vindas,
        on_canceled=enviar_cancelamento,
    )
    await wh.iniciar_servidor()

    # 3. Scheduler: verifica expirados a cada 24h
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(verificar_expirados, "interval", hours=24, id="verificar_expirados")
    scheduler.start()
    logger.info("Scheduler de expiração iniciado (intervalo: 24h).")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    if not BOT_TOKEN or BOT_TOKEN == "SEU_TOKEN_AQUI":
        print("❌ ERRO: Configure o TELEGRAM_BOT_TOKEN no arquivo .env")
        return

    has_gemini = bool(GEMINI_API_KEY and GEMINI_API_KEY != "SUA_CHAVE_GEMINI_AQUI")
    if has_gemini:
        setup_gemini(GEMINI_API_KEY)
        logger.info("Gemini AI configurado.")
    else:
        logger.warning("GEMINI_API_KEY não configurada. Usando templates padrão.")

    if not ffmpeg_available():
        logger.warning("FFmpeg não encontrado. Metadados NÃO serão removidos.")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Comandos públicos
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("ajuda",     cmd_ajuda))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("meuacesso", cmd_meuacesso))

    # Comandos admin
    app.add_handler(CommandHandler("adduser",    adm.cmd_adduser))
    app.add_handler(CommandHandler("removeuser", adm.cmd_removeuser))
    app.add_handler(CommandHandler("usuarios",   adm.cmd_usuarios))
    app.add_handler(CommandHandler("stats",      adm.cmd_stats))

    # Mensagens
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(URL_PATTERN),
        handle_link,
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_unknown,
    ))

    # Botões inline
    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_error_handler(error_handler)

    print("=" * 52)
    print("   BOT DE AFILIADOS — MODO PRODUÇÃO")
    print("=" * 52)
    print(f"   FFmpeg    : {'OK' if ffmpeg_available() else 'NÃO INSTALADO'}")
    print(f"   Gemini AI : {'Configurado' if has_gemini else 'NÃO CONFIGURADO'}")
    print(f"   Admin ID  : {ADMIN_ID or 'NÃO CONFIGURADO'}")
    print("=" * 52)
    print("   Aguardando mensagens... (Ctrl+C para parar)\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
