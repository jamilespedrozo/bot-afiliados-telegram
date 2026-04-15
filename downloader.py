"""
downloader.py - Módulo de download de vídeos
Suporta: TikTok, Instagram, Pinterest, YouTube, MP4 direto
"""

import os
import re
import asyncio
import uuid
import logging
from pathlib import Path
from typing import Optional

import yt_dlp

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)


def detect_platform(url: str) -> str:
    """Detecta a plataforma a partir da URL."""
    url_lower = url.lower()
    if "tiktok.com" in url_lower or "vm.tiktok" in url_lower:
        return "TikTok"
    elif "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "Instagram"
    elif "pinterest.com" in url_lower or "pin.it" in url_lower:
        return "Pinterest"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"
    elif url_lower.endswith(".mp4") or "mp4" in url_lower:
        return "MP4 Direto"
    else:
        return "Web"


def get_ydl_opts(output_path: str, platform: str) -> dict:
    """Retorna opções personalizadas por plataforma para yt-dlp."""
    base_opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "postprocessors": [
            {
                "key": "FFmpegMetadata",
                "add_metadata": False,
            }
        ],
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    }

    if platform == "TikTok":
        base_opts.update(
            {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "extractor_args": {
                    "tiktok": {
                        "api_hostname": ["api22-normal-c-useast2a.tiktokv.com"],
                        "app_version": ["35.1.3"],
                    }
                },
                "http_headers": {
                    "User-Agent": "TikTok/35.1.3 (iPhone; iOS 17.0; Scale/3.00)",
                    "Accept": "application/json",
                },
            }
        )

    elif platform == "Instagram":
        base_opts.update(
            {
                "format": "best[ext=mp4]/best",
            }
        )

    elif platform in ("YouTube",):
        base_opts.update(
            {
                "format": (
                    "bestvideo[height<=1080][ext=mp4]+"
                    "bestaudio[ext=m4a]/best[height<=1080]/best"
                ),
            }
        )

    return base_opts


async def download_video(url: str) -> dict:
    """
    Faz o download do vídeo a partir de qualquer URL suportada.

    Retorna um dicionário com:
      - success (bool)
      - file_path (str) — caminho do arquivo baixado
      - title (str) — título do vídeo
      - platform (str) — plataforma detectada
      - duration (int) — duração em segundos
      - error (str) — mensagem de erro (se houver)
    """
    platform = detect_platform(url)
    unique_id = uuid.uuid4().hex[:8]
    output_template = str(DOWNLOADS_DIR / f"video_{unique_id}.%(ext)s")
    final_path = str(DOWNLOADS_DIR / f"video_{unique_id}.mp4")

    result = {
        "success": False,
        "file_path": None,
        "title": "Vídeo sem título",
        "platform": platform,
        "duration": 0,
        "description": "",
        "error": None,
    }

    def _run_download():
        ydl_opts = get_ydl_opts(output_template, platform)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _run_download)

        if info:
            result["title"] = info.get("title", "Vídeo sem título")
            result["duration"] = info.get("duration", 0)
            result["description"] = info.get("description", "")

        downloaded = _find_downloaded_file(unique_id)
        if downloaded:
            result["file_path"] = downloaded
            result["success"] = True
        else:
            result["error"] = "Arquivo não encontrado após download."

    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e)
        logger.error(f"Erro de download [{platform}]: {err_msg}")
        result["error"] = _friendly_error(err_msg, platform)

    except Exception as e:
        logger.exception(f"Erro inesperado no download: {e}")
        result["error"] = f"Erro inesperado: {str(e)}"

    return result


def _find_downloaded_file(unique_id: str) -> Optional[str]:
    """Procura o arquivo baixado na pasta downloads."""
    for ext in ["mp4", "mkv", "webm", "mov", "avi", "flv"]:
        path = DOWNLOADS_DIR / f"video_{unique_id}.{ext}"
        if path.exists() and path.stat().st_size > 0:
            return str(path)
    for f in DOWNLOADS_DIR.iterdir():
        if unique_id in f.name and f.stat().st_size > 0:
            return str(f)
    return None


def _friendly_error(error_msg: str, platform: str) -> str:
    """Converte mensagens de erro técnicas para textos amigáveis."""
    msg = error_msg.lower()
    if "private" in msg or "login" in msg or "authentication" in msg:
        return (
            f"❌ Vídeo privado ou requer login.\n"
            f"O vídeo do {platform} é privado ou restrito. "
            f"Tente com um vídeo público."
        )
    elif "not found" in msg or "404" in msg:
        return f"❌ Vídeo não encontrado. Verifique se o link está correto."
    elif "unsupported" in msg:
        return (
            f"❌ Este tipo de link do {platform} não é suportado ainda. "
            f"Tente outro formato de URL."
        )
    elif "geo" in msg or "blocked" in msg or "available" in msg:
        return f"❌ Este vídeo está bloqueado por região ou indisponível."
    elif "copyright" in msg:
        return f"❌ Vídeo bloqueado por direitos autorais."
    else:
        return f"❌ Não foi possível baixar o vídeo. Tente novamente ou use outro link.\nDetalhe: {error_msg[:200]}"


def cleanup_file(file_path: str):
    """Remove um arquivo de vídeo após o envio."""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Arquivo removido: {file_path}")
    except Exception as e:
        logger.warning(f"Não foi possível remover {file_path}: {e}")
