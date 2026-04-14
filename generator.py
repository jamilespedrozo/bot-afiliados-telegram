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

    prompt = f"""Você é um copywriter expert em vendas de afiliados no Brasil.

Preciso de textos persuasivos para vender um produto/serviço ao cliente final.
O vídeo que tenho é da plataforma {platform}, título: "{title}"{desc_context}
Duração: {duration_text}

IMPORTANTE: os textos devem falar DIRETAMENTE COM O CLIENTE FINAL (comprador),
NÃO com outros afiliados. Use linguagem de vendas, gatilhos mentais e benefícios.

---
TEXTO 1 - POST PARA GRUPOS (WhatsApp/Telegram) — fala COM o cliente
Regras:
- Abra com uma dor, desejo ou situação que o cliente vive
- Mostre o benefício principal do produto/serviço
- Use gatilhos: escassez, prova social, curiosidade ou urgência
- Termine com uma chamada para ação clara (ex: "Clica no link", "Comenta SIM", "Manda mensagem agora")
- Máximo 6 linhas, com emojis estratégicos
- NÃO mencione afiliado, comissão ou "compartilhe"

TEXTO 2 - LEGENDA PARA INSTAGRAM STORY — fala COM o cliente
Regras:
- Máximo 2 linhas, impacto imediato
- Fale de uma transformação ou resultado que o cliente quer
- Termine com CTA curto ("Link na bio", "Arrasta pra cima", "Me chama no direct")
- Máximo 120 caracteres
- 2 emojis no máximo
- NÃO mencione afiliado ou repassar

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
        f"{emoji} Você já tentou resolver isso e não conseguiu?\n\n"
        f"👉 {clean_title}\n"
        f"✅ Isso está mudando a vida de muita gente — e pode mudar a sua também\n"
        f"⏳ As vagas/condições são limitadas, não deixa pra depois\n\n"
        f"👇 Clica no link e descobre como"
    )

    story_caption = (
        f"{emoji} Isso pode mudar tudo pra você!\n"
        f"🔗 Link na bio — corre antes que esgote!"
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
