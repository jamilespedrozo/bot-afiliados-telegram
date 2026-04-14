"""
generator.py - Gera descrições prontas para afiliados usando Google Gemini
Formatos: Post para grupos de afiliados + Instagram Story
SDK: google-genai (versão atual e suportada)
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Tenta importar o novo SDK do Gemini
try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("google-genai não instalado. Usando descrições padrão.")

_gemini_client = None


def setup_gemini(api_key: str) -> bool:
    """Configura o cliente Gemini com a chave da API."""
    global _gemini_client
    if GEMINI_AVAILABLE and api_key:
        try:
            _gemini_client = genai.Client(api_key=api_key)
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar Gemini: {e}")
    return False


async def generate_description(
    title: str,
    platform: str,
    original_description: str = "",
    duration: int = 0,
) -> dict:
    """
    Gera dois tipos de descrição para afiliados:
      1. Post para grupos de afiliados (WhatsApp/Telegram)
      2. Legenda para Instagram Story

    Retorna:
      - group_post (str) — texto para grupos
      - story_caption (str) — legenda para Story
      - used_ai (bool) — se usou IA ou template padrão
    """
    result = {
        "group_post": "",
        "story_caption": "",
        "used_ai": False,
    }

    api_key = os.getenv("GEMINI_API_KEY", "")

    # Tenta usar IA se disponível e configurada
    if GEMINI_AVAILABLE and _gemini_client:
        try:
            ai_result = await _generate_with_gemini(
                title, platform, original_description, duration
            )
            if ai_result:
                result.update(ai_result)
                result["used_ai"] = True
                return result
        except Exception as e:
            logger.warning(f"Gemini falhou, usando template padrão: {e}")

    # Fallback: template padrão inteligente
    result.update(_generate_template(title, platform, duration))
    return result


async def _generate_with_gemini(
    title: str,
    platform: str,
    original_description: str,
    duration: int,
) -> Optional[dict]:
    """Usa o Google Gemini para gerar descrições criativas e persuasivas."""

    duration_text = f"{duration}s" if duration > 0 else "curto"
    desc_context = (
        f"\nDescrição original: {original_description[:300]}"
        if original_description
        else ""
    )

    prompt = f"""Você é um especialista em marketing de afiliados no Brasil.

Recebi um vídeo da plataforma {platform} com o título: "{title}"{desc_context}
Duração: {duration_text}

Crie DOIS textos em português do Brasil, diretos, persuasivos e com emojis:

---
TEXTO 1 - POST PARA GRUPOS DE AFILIADOS (WhatsApp/Telegram)
Formato: curto, impactante, máximo 5 linhas
- Inclua uma chamada para ação clara
- Use emojis estratégicos
- Tom urgente e direto
- Inclua hashtags relevantes no final

TEXTO 2 - LEGENDA PARA INSTAGRAM STORY
Formato: bem curto (máximo 2-3 linhas), vibrante, moderno
- Ideal para aparecer sobre um vídeo/imagem
- Máximo 150 caracteres
- Use 2-3 emojis no máximo
- Call to action em 1 linha

Responda EXATAMENTE neste formato JSON (sem markdown):
{{
  "group_post": "texto aqui",
  "story_caption": "texto aqui"
}}"""

    def _call_gemini():
        response = _gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.8,
                max_output_tokens=500,
            ),
        )
        return response.text

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _call_gemini)

    # Remove possíveis blocos de código markdown
    raw = re.sub(r"```json\s*|\s*```", "", raw).strip()

    try:
        data = json.loads(raw)
        return {
            "group_post": data.get("group_post", ""),
            "story_caption": data.get("story_caption", ""),
        }
    except json.JSONDecodeError:
        logger.warning(f"Gemini retornou JSON inválido: {raw[:200]}")
        return None


def _generate_template(title: str, platform: str, duration: int) -> dict:
    """
    Gera descrições usando templates prontos quando a IA não está disponível.
    """
    clean_title = title[:60] if len(title) > 60 else title
    if clean_title.lower() in ("vídeo sem título", "video", ""):
        clean_title = "esse conteúdo incrível"

    platform_emoji = {
        "TikTok": "🎵",
        "Instagram": "📸",
        "YouTube": "▶️",
        "Pinterest": "📌",
        "MP4 Direto": "🎬",
        "Web": "🌐",
    }
    emoji = platform_emoji.get(platform, "🎬")

    group_post = (
        f"{emoji} *{clean_title}*\n\n"
        f"🔥 Conteúdo quente que está bombando no {platform}!\n"
        f"💰 Compartilhe e monetize agora\n"
        f"👇 Veja e repasse para seus grupos\n\n"
        f"#afiliados #marketingdigital #{platform.lower()} #conteudodigital #renda"
    )

    story_caption = (
        f"{emoji} Isso tá viral no {platform}!\n"
        f"🚀 Corre ver e compartilha!"
    )

    return {
        "group_post": group_post,
        "story_caption": story_caption,
    }
