"""
generator.py - Gera descrições prontas para afiliados usando Google Gemini
Formatos: Post para grupos de afiliados + Hashtags
SDK: google-genai (versão atual e suportada)
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

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
    Gera dois tipos de conteúdo para afiliados:
      1. Legenda vendedora para grupos (WhatsApp/Telegram)
      2. Hashtags nichadas e relevantes

    Retorna:
      - group_post (str) — legenda vendedora
      - story_caption (str) — hashtags
      - used_ai (bool) — se usou IA ou template padrão
    """
    result = {
        "group_post": "",
        "story_caption": "",
        "used_ai": False,
    }

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

    result.update(_generate_template(title, platform, duration))
    return result


async def _generate_with_gemini(
    title: str,
    platform: str,
    original_description: str,
    duration: int,
) -> Optional[dict]:
    """Usa o Google Gemini para gerar legendas vendedoras e hashtags para afiliados."""

    duration_text = f"{duration}s" if duration > 0 else "curto"
    desc_context = (
        f"\nDescrição original do vídeo: {original_description[:400]}"
        if original_description
        else ""
    )

    prompt = f"""Você é um copywriter especialista em marketing de afiliados no Brasil, com foco em conversão e engajamento nas redes sociais.

Recebi um vídeo da plataforma {platform}.
Título do vídeo: "{title}"{desc_context}
Duração: {duration_text}

Sua missão é criar dois conteúdos prontos para um afiliado publicar:

━━━━━━━━━━━━━━━━━━
1. LEGENDA VENDEDORA (group_post)
━━━━━━━━━━━━━━━━━━
Escreva uma legenda curta e persuasiva para publicar junto com o vídeo em grupos de WhatsApp e Telegram.

Regras:
- Comece com um emoji de impacto + frase de gancho que prende atenção (ex: "Esse produto mudou minha rotina 🔥")
- Destaque o principal benefício ou resultado do produto em 1-2 linhas
- Crie senso de oportunidade ou urgência de forma natural (sem parecer spam)
- Finalize com uma chamada para ação curta e direta (ex: "Link na bio 👆", "Corre antes de acabar 🏃", "Comenta QUERO que te mando o link!")
- Tom: animado, humano, como se fosse uma amiga indicando algo que gostou
- Máx 6 linhas no total
- Use emojis estrategicamente (4 a 6 emojis)
- Sem hashtags na legenda

━━━━━━━━━━━━━━━━━━
2. HASHTAGS (story_caption)
━━━━━━━━━━━━━━━━━━
Gere exatamente 18 hashtags relevantes ao nicho do produto.

Regras:
- Misture: 6 populares (ex: #oferta #produtosvirais) + 6 de nicho (ex: #cafeteiraportatil) + 6 de afiliado (ex: #indicaçãoboa #compreonline)
- Todas em português
- Apenas as hashtags, sem texto extra

━━━━━━━━━━━━━━━━━━
Responda EXATAMENTE neste formato JSON (sem markdown, sem explicações):
{{
  "group_post": "legenda vendedora aqui",
  "story_caption": "#hashtag1 #hashtag2 #hashtag3 ..."
}}"""

    def _call_gemini():
        response = _gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.9,
                max_output_tokens=700,
            ),
        )
        return response.text

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _call_gemini)

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
    Template de fallback quando a IA não está disponível.
    Mais vendedor do que antes.
    """
    clean_title = title[:60] if len(title) > 60 else title
    if clean_title.lower() in ("vídeo sem título", "video", ""):
        clean_title = "esse produto incrível"

    platform_emoji = {
        "TikTok": "🎵",
        "Instagram": "📸",
        "YouTube": "▶️",
        "Pinterest": "📌",
        "MP4 Direto": "🎬",
        "Web": "🌐",
    }
    emoji = platform_emoji.get(platform, "🔥")

    group_post = (
        f"{emoji} *{clean_title}*\n\n"
        f"✅ Esse produto está bombando e eu precisava compartilhar com vocês!\n"
        f"🛒 Qualidade comprovada, preço que vale muito a pena\n"
        f"👇 Comenta QUERO que te mando o link direto!"
    )

    platform_tag = f"#{platform.lower().replace(' ', '')}"
    story_caption = (
        f"#oferta #produtosviral #compraonline #indicação #afiliados "
        f"#marketingdigital #rendaextra {platform_tag} "
        f"#promoção #acheibarato #valedapena #melhorpreço "
        f"#comprerecomendo #dicaboa #produtosincriveis #viral "
        f"#tendencia #novidade"
    )

    return {
        "group_post": group_post,
        "story_caption": story_caption,
    }


async def generate_hashtags(
    title: str,
    platform: str,
    original_description: str = "",
) -> str:
    """
    Gera um bloco de hashtags relevantes para afiliados.
    """
    if GEMINI_AVAILABLE and _gemini_client:
        try:
            prompt = f"""Você é especialista em marketing de afiliados no Brasil.

Vídeo da plataforma {platform}, título: "{title}"
{"Descrição: " + original_description[:200] if original_description else ""}

Gere exatamente 20 hashtags em português para afiliados publicarem junto com vídeos de produtos.
Misture: populares + nichadas ao produto + de compra/oferta.

Responda APENAS as hashtags em uma linha, separadas por espaço, começando com #.
Nada mais além das hashtags."""

            def _call():
                response = _gemini_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=200,
                    ),
                )
                return response.text.strip()

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _call)
            if result.startswith("#"):
                return result
        except Exception as e:
            logger.warning(f"Gemini hashtags falhou: {e}")

    platform_tag = f"#{platform.lower().replace(' ', '')}"
    return (
        f"#afiliados #marketingdigital #rendaextra #oferta #promoção "
        f"#compraonline #indicação #produtosviral #acheibarato {platform_tag} "
        f"#valedapena #melhorpreço #comprerecomendo #dicaboa #tendencia "
        f"#viral #novidade #trabalhoonline #negociodigital #empreendedorismo"
    )
