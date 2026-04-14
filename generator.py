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

    prompt = f"""Você é um especialista em conteúdo digital para afiliados no Brasil.

Recebi um vídeo da plataforma {platform}.
Título: "{title}"{desc_context}
Duração: {duration_text}

Gere uma DESCRIÇÃO SIMPLES E DIRETA do produto ou serviço mostrado no vídeo.

Regras para a descrição:
- Explique O QUE É o produto/serviço em 2 a 4 linhas
- Diga quais são os principais benefícios ou resultados
- Linguagem natural, sem fórmulas de vendas, sem urgência, sem “clica no link”
- Use emojis de forma discreta (máx 3)
- Sem hashtags na descrição

Regras para as hashtags:
- Gere exatamente 15 hashtags relevantes ao nicho do produto
- Misture populares e nichadas
- Apenas as hashtags, sem texto extra

Responda EXATAMENTE neste formato JSON (sem markdown):
{{
  "group_post": "descrição do produto aqui",
  "story_caption": "#hashtag1 #hashtag2 #hashtag3 ..."
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
        f"{emoji} {clean_title}\n\n"
        f"✅ Conteúdo de {platform} com dicas e informações úteis\n"
        f"📍 Assista e descubra mais sobre esse assunto"
    )

    # Hashtags padrão por plataforma
    platform_tag = f"#{platform.lower().replace(' ', '')}"
    story_caption = (
        f"#conteúdo #dicas #viral {platform_tag} "
        f"#digital #aprenda #trending #brasil "
        f"#descoberta #novidade #informação #top "
        f"#recomendo #assista #valeudemais"
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
    Retorna uma string com ~20 hashtags prontas para copiar.
    """
    if GEMINI_AVAILABLE and _gemini_client:
        try:
            prompt = f"""Você é especialista em marketing de afiliados no Brasil.

Vídeo da plataforma {platform}, título: "{title}"
{"Descrição: " + original_description[:200] if original_description else ""}

Gere exatamente 20 hashtags relevantes em português para uso em posts de afiliados.
Misture hashtags: populares (amplo alcance) + nichadas (engajamento) + de ação.

Responda APENAS as hashtags em uma linha, separadas por espaço, começando com #.
Exemplo: #afiliados #marketingdigital #rendaextra ...

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

    # Fallback: hashtags padrão para afiliados
    platform_tag = f"#{platform.lower().replace(' ', '')}"
    return (
        f"#afiliados #marketingdigital #rendaextra #trabalhoonline "
        f"#empreendedorismo #ganhedinheiro #negociodigital {platform_tag} "
        f"#conteudodigital #marketingdeafiliados #vendasonline #lucro "
        f"#liberdadefinanceira #dinheiro #sucesso #motivacao "
        f"#dicasdemarketing #tudodigital #brasilempreendedor #riqueza"
    )
