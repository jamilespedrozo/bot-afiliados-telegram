"""
webhook.py - Servidor HTTP para receber eventos do Kiwify
Processa compras aprovadas e cancela acessos automaticamente.
"""
import asyncio
import logging
import os
from typing import Callable, Awaitable, Optional

from aiohttp import web

import database as db

logger = logging.getLogger(__name__)

# Mapeamento de nomes de plano → dias de acesso
PLANOS_DIAS = {
    "mensal":      int(os.getenv("PLANO_MENSAL_DIAS",      "30")),
    "monthly":     int(os.getenv("PLANO_MENSAL_DIAS",      "30")),
    "trimestral":  int(os.getenv("PLANO_TRIMESTRAL_DIAS",  "90")),
    "quarterly":   int(os.getenv("PLANO_TRIMESTRAL_DIAS",  "90")),
    "anual":       int(os.getenv("PLANO_ANUAL_DIAS",       "365")),
    "annual":      int(os.getenv("PLANO_ANUAL_DIAS",       "365")),
    "vitalicio":   0,
    "vitalício":   0,
    "lifetime":    0,
}

# Callback chamado quando usuário é ativado (envia boas-vindas pelo bot)
_on_user_activated: Optional[Callable[[int, str, str], Awaitable[None]]] = None
_on_user_canceled:  Optional[Callable[[int], Awaitable[None]]] = None


def set_callbacks(on_activated=None, on_canceled=None):
    global _on_user_activated, _on_user_canceled
    _on_user_activated = on_activated
    _on_user_canceled  = on_canceled


# ──────────────────────────────────────────────
# Helpers para extrair dados do payload Kiwify
# ──────────────────────────────────────────────
def _extrair_telegram_id(data: dict) -> Optional[int]:
    """Procura o Telegram ID em múltiplos campos do payload."""
    # 1. Campo personalizado do checkout (mais confiável)
    for field in data.get("checkout_custom_fields", []):
        label = str(field.get("label", "")).lower()
        value = str(field.get("value", "")).strip().replace(" ", "")
        if "telegram" in label and value.isdigit() and len(value) >= 6:
            return int(value)

    # 2. Campos do cliente
    customer = data.get("customer", {})
    for key in ["telegram_id", "telegram", "id_telegram"]:
        val = str(customer.get(key, "")).strip()
        if val.isdigit() and len(val) >= 6:
            return int(val)

    # 3. Raiz do payload
    for key in ["telegram_id", "telegram"]:
        val = str(data.get(key, "")).strip()
        if val.isdigit() and len(val) >= 6:
            return int(val)

    return None


def _extrair_dias(data: dict) -> int:
    """Determina dias de acesso baseado no plano."""
    plano = data.get("plan", {})
    nome  = str(plano.get("name", "")).lower().strip()

    for chave, dias in PLANOS_DIAS.items():
        if chave in nome:
            return dias

    # Kiwify às vezes envia days_remaining direto
    days = plano.get("days_remaining", 0)
    if isinstance(days, int) and days > 0:
        return days

    # Padrão: mensal
    return int(os.getenv("PLANO_MENSAL_DIAS", "30"))


def _nome_plano(data: dict) -> str:
    plano = data.get("plan", {})
    nome  = str(plano.get("name", "")).strip()
    dias  = _extrair_dias(data)
    if not nome:
        nome = "Vitalício" if dias == 0 else f"{dias} dias"
    return nome


# ──────────────────────────────────────────────
# Handlers HTTP
# ──────────────────────────────────────────────
async def handle_kiwify(request: web.Request) -> web.Response:
    """Recebe e processa eventos do Kiwify."""
    secret = os.getenv("WEBHOOK_SECRET", "")

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    # Validação do token de segurança
    if secret:
        token = (
            body.get("token", "")
            or request.headers.get("X-Kiwify-Token", "")
            or request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if token != secret:
            logger.warning("Webhook com token inválido rejeitado.")
            return web.json_response({"error": "Unauthorized"}, status=401)

    event = body.get("event", "")
    data  = body.get("data", body)

    logger.info(f"Kiwify webhook: {event}")

    if event in ("purchase.approved", "order_approved", "purchase.complete"):
        await _ativar_usuario(data, body)

    elif event in ("subscription.canceled", "purchase.refunded", "purchase.chargeback"):
        await _cancelar_usuario(data)

    return web.json_response({"status": "ok"})


async def _ativar_usuario(data: dict, raw: dict):
    """Ativa o acesso após compra aprovada."""
    customer  = data.get("customer", {})
    nome      = customer.get("name", "Cliente")
    email     = customer.get("email", "")
    order_id  = data.get("id", raw.get("id", ""))
    dias      = _extrair_dias(data)
    plano_str = _nome_plano(data)

    # Tenta extrair no data primeiro, depois no raw completo
    telegram_id = _extrair_telegram_id(data) or _extrair_telegram_id(raw)

    if not telegram_id:
        logger.warning(f"Compra aprovada SEM Telegram ID: {email} | {order_id}")
        return

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, db.adicionar_usuario,
        telegram_id, nome, email, plano_str, dias, order_id
    )

    logger.info(f"✅ Acesso ativado: {telegram_id} ({nome}) | {plano_str}")

    if _on_user_activated:
        await _on_user_activated(telegram_id, nome, plano_str)


async def _cancelar_usuario(data: dict):
    """Desativa acesso em cancelamento/reembolso."""
    telegram_id = _extrair_telegram_id(data)
    email       = data.get("customer", {}).get("email", "")

    if telegram_id:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, db.remover_usuario, telegram_id)
        logger.info(f"❌ Acesso cancelado: {telegram_id}")
        if _on_user_canceled:
            await _on_user_canceled(telegram_id)
    else:
        logger.warning(f"Cancelamento sem Telegram ID: {email}")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "bot-afiliados"})


# ──────────────────────────────────────────────
# Inicialização do servidor
# ──────────────────────────────────────────────
async def iniciar_servidor():
    """Inicia o servidor aiohttp na porta definida pelo Railway ($PORT)."""
    port = int(os.getenv("PORT", "8080"))
    app  = web.Application()
    app.router.add_post("/kiwify", handle_kiwify)
    app.router.add_get("/health",  handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Servidor webhook ativo na porta {port} → /kiwify")
