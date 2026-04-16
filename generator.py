"""
generator.py - Gera descrições prontas para afiliados usando Groq AI
Formatos: Legenda vendedora para grupos + Hashtags nichadas
SDK: groq (pip install groq)
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    logger.warning("groq não instalado. Rode: pip install groq")

_groq_client = None


def setup_gemini(api_key: str) -> bool:
    """
    Mantido por compatibilidade com bot.py.
    Inicializa o cliente Groq usando GROQ_API_KEY do ambiente.
    """
    return setup_groq()


def setup_groq() -> bool:
    """Configura o cliente Groq com a chave da API."""
    global _groq_client
    if not GROQ_AVAILABLE:
        return False
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("GROQ_API_KEY não configurada.")
        return False
    try:
        _groq_client = Groq(api_key=api_key)
        logger.info("Groq AI configurado com sucesso.")
        return True
    except Exception as e:
        logger.error(f"Erro ao configurar Groq: {e}")
        return False


async def generate_description(
    title: str,
    platform: str,
    original_description: str = "",
    duration: int = 0,
) -> dict:
    """
    Gera legenda vendedora e hashtags para afiliados.

    Retorna:
      - group_post (str)    — legenda vendedora para grupos
      - story_caption (str) — hashtags nichadas
      - used_ai (bool)      — True se usou Groq, False se usou template
    """
    result = {
        "group_post": "",
        "story_caption": "",
        "used_ai": False,
    }

    if GROQ_AVAILABLE and _groq_client:
        try:
            ai_result = await _generate_with_groq(
                title, platform, original_description, duration
            )
            if ai_result:
                result.update(ai_result)
                result["used_ai"] = True
                return result
        except Exception as e:
            logger.warning(f"Groq falhou, usando template padrão: {e}")

    result.update(_generate_template(title, platform, duration))
    return result


async def _generate_with_groq(
    title: str,
    platform: str,
    original_description: str,
    duration: int,
) -> Optional[dict]:
    """Chama a API do Groq para gerar legenda vendedora e hashtags."""

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

Crie dois conteúdos prontos para um afiliado publicar:

━━━━━━━━━━━━━━━━━━
1. LEGENDA VENDEDORA (group_post)
━━━━━━━━━━━━━━━━━━
Escreva uma legenda curta e persuasiva para publicar junto com o vídeo em grupos de WhatsApp e Telegram.

Regras:
- Comece com emoji de impacto + frase de gancho que prende atenção
- Destaque o principal benefício ou resultado do produto em 1-2 linhas
- Crie senso de oportunidade ou urgência de forma natural (sem parecer spam)
- Finalize com uma chamada para ação curta e direta (ex: "Comenta QUERO que te mando o link!", "Corre antes de acabar 🏃", "Link na bio 👆")
- Tom: animado, humano, como se fosse uma amiga indicando algo que adorou
- Máximo 6 linhas no total
- Use de 4 a 6 emojis estrategicamente
- Sem hashtags na legenda

━━━━━━━━━━━━━━━━━━
2. HASHTAGS (story_caption)
━━━━━━━━━━━━━━━━━━
Gere exatamente 18 hashtags relevantes ao nicho do produto.

Regras:
- 6 populares (ex: #oferta #produtosviral)
- 6 de nicho do produto (ex: #cafeteiraportatil #cozinhaorganizada)
- 6 de afiliado/compra (ex: #compreonline #indicaçãoboa)
- Todas em português
- Apenas as hashtags, sem texto extra

━━━━━━━━━━━━━━━━━━
Responda EXATAMENTE neste formato JSON (sem markdown, sem explicações):
{{
  "group_post": "legenda vendedora aqui",
  "story_caption": "#hashtag1 #hashtag2 #hashtag3 ..."
}}"""

    def _call_groq():
        response = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Você é um copywriter especialista em marketing de afiliados no Brasil. Sempre responda apenas com JSON válido, sem markdown e sem texto extra."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.9,
            max_tokens=700,
        )
        return response.choices[0].message.content

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _call_groq)

    raw = re.sub(r"```json\s*|\s*```", "", raw).strip()

    try:
        data = json.loads(raw)
        return {
            "group_post": data.get("group_post", ""),
            "story_caption": data.get("story_caption", ""),
        }
    except json.JSONDecodeError:
        logger.warning(f"Groq retornou JSON inválido: {raw[:200]}")
        return None


def _generate_template(title: str, platform: str, duration: int) -> dict:
    """Template de fallback quando a IA não está disponível."""
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
    """Gera um bloco de hashtags relevantes para afiliados."""
    if GROQ_AVAILABLE and _groq_client:
        try:
            prompt = f"""Você é especialista em marketing de afiliados no Brasil.

Vídeo da plataforma {platform}, título: "{title}"
{"Descrição: " + original_description[:200] if original_description else ""}

Gere exatamente 20 hashtags em português para afiliados publicarem junto com vídeos de produtos.
Misture: populares + nichadas ao produto + de compra/oferta.

Responda APENAS as hashtags em uma linha, separadas por espaço, começando com #.
Nada mais além das hashtags."""

            def _call():
                response = _groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "Responda apenas com hashtags, sem texto extra."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=200,
                )
                return response.choices[0].message.content.strip()

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _call)
            if result.startswith("#"):
                return result
        except Exception as e:
            logger.warning(f"Groq hashtags falhou: {e}")

    platform_tag = f"#{platform.lower().replace(' ', '')}"
    return (
        f"#afiliados #marketingdigital #rendaextra #oferta #promoção "
        f"#compraonline #indicação #produtosviral #acheibarato {platform_tag} "
        f"#valedapena #melhorpreço #comprerecomendo #dicaboa #tendencia "
        f"#viral #novidade #trabalhoonline #negociodigital #empreendedorismo"
    )
