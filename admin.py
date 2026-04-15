"""
admin.py - Comandos administrativos do Bot de Afiliados
Apenas o ADMIN_ID configurado nas variáveis de ambiente pode usar estes comandos.
"""
import asyncio
import logging
import os
from datetime import timezone, datetime

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import database as db

logger = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


# ──────────────────────────────────────────────
# /adduser <telegram_id> <dias>
# ──────────────────────────────────────────────
async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Uso correto:\n`/adduser <telegram_id> <dias>`\n\n"
            "Exemplo: `/adduser 123456789 30`\n"
            "Para vitalício: `/adduser 123456789 0`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        telegram_id = int(args[0])
        dias        = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ ID e dias devem ser números.")
        return

    nome  = " ".join(args[2:]) if len(args) > 2 else "Manual"
    plano = "Vitalício" if dias == 0 else f"{dias} dias"

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, db.adicionar_usuario,
        telegram_id, nome, "manual@admin.com", plano, dias, "manual"
    )

    expiry = "Vitalício ♾️" if dias == 0 else f"{dias} dias"
    await update.message.reply_text(
        f"✅ *Usuário adicionado!*\n\n"
        f"🆔 ID: `{telegram_id}`\n"
        f"👤 Nome: {nome}\n"
        f"📦 Plano: {expiry}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ──────────────────────────────────────────────
# /removeuser <telegram_id>
# ──────────────────────────────────────────────
async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "❌ Uso: `/removeuser <telegram_id>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        telegram_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ID deve ser um número.")
        return

    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, db.remover_usuario, telegram_id)

    if ok:
        await update.message.reply_text(f"✅ Acesso do `{telegram_id}` removido.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"⚠️ ID `{telegram_id}` não encontrado.", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /usuarios — lista todos os ativos
# ──────────────────────────────────────────────
async def cmd_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    loop  = asyncio.get_event_loop()
    lista = await loop.run_in_executor(None, db.listar_usuarios_ativos)

    if not lista:
        await update.message.reply_text("📭 Nenhum usuário ativo.")
        return

    linhas = [f"👥 *Usuários Ativos ({len(lista)})*\n"]
    now = datetime.now(timezone.utc)

    for u in lista:
        expiry = u.get("data_expiracao")
        if expiry is None:
            exp_str = "♾️ Vitalício"
        else:
            dias_rest = (expiry - now).days
            exp_str = f"📅 {dias_rest}d restantes"

        linhas.append(
            f"• `{u['telegram_id']}` — {u.get('nome', '?')} | {u.get('plano', '?')} | {exp_str}"
        )

    # Telegram tem limite de 4096 chars por mensagem
    texto = "\n".join(linhas)
    for i in range(0, len(texto), 4000):
        await update.message.reply_text(texto[i:i+4000], parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────
# /stats — estatísticas gerais
# ──────────────────────────────────────────────
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    loop   = asyncio.get_event_loop()
    stats  = await loop.run_in_executor(None, db.estatisticas)

    await update.message.reply_text(
        f"📊 *Estatísticas do Bot*\n\n"
        f"*Usuários Pagos:*\n"
        f"✅ Ativos:          `{stats.get('ativos', 0)}`\n"
        f"♾️ Vitalícios:     `{stats.get('vitalicios', 0)}`\n"
        f"📅 Com plano ativo: `{stats.get('com_plano_ativo', 0)}`\n"
        f"❌ Inativos:        `{stats.get('inativos', 0)}`\n\n"
        f"*Uso Hoje:*\n"
        f"👥 Usuários ativos hoje: `{stats.get('usuarios_gratis_hoje', 0)}`\n"
        f"🎬 Total de vídeos hoje: `{stats.get('total_usos_hoje', 0)}`\n",
        parse_mode=ParseMode.MARKDOWN,
    )
