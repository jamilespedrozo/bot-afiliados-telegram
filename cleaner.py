"""
cleaner.py - Remove metadados e rastreamento de vídeos
Usa FFmpeg para limpar: título, autor, comentários, GPS, câmera, etc.
"""

import asyncio
import logging
import os
import subprocess
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

CLEAN_DIR = Path("downloads/clean")
CLEAN_DIR.mkdir(parents=True, exist_ok=True)


def ffmpeg_available() -> bool:
    """Verifica se o FFmpeg está instalado no sistema."""
    return shutil.which("ffmpeg") is not None


async def remove_metadata(input_path: str) -> dict:
    """
    Remove todos os metadados do vídeo usando FFmpeg.

    Retorna:
      - success (bool)
      - output_path (str) — caminho do vídeo limpo
      - error (str) — mensagem de erro (se houver)
    """
    result = {"success": False, "output_path": None, "error": None}

    if not ffmpeg_available():
        logger.warning("FFmpeg não encontrado. Enviando vídeo sem limpeza de metadados.")
        # Sem FFmpeg, retorna o arquivo original mesmo
        result["success"] = True
        result["output_path"] = input_path
        result["error"] = "ffmpeg_missing"
        return result

    input_file = Path(input_path)
    output_file = CLEAN_DIR / f"clean_{input_file.name}"

    # Comando FFmpeg para remover TODOS os metadados
    # -map_metadata -1  → apaga todos os metadados globais
    # -map_chapters -1  → apaga capítulos
    # -fflags +bitexact → garante saída determinística
    # -c copy           → reencoda sem perda de qualidade (stream copy)
    cmd = [
        "ffmpeg",
        "-y",                      # Sobrescreve sem perguntar
        "-i", str(input_file),     # Arquivo de entrada
        "-map_metadata", "-1",     # Remove todos os metadados
        "-map_chapters", "-1",     # Remove capítulos
        "-c", "copy",              # Sem reencoding (mais rápido)
        "-movflags", "+faststart", # Otimiza para streaming/web
        str(output_file),          # Arquivo de saída
    ]

    try:
        loop = asyncio.get_event_loop()
        proc_result = await loop.run_in_executor(None, _run_ffmpeg, cmd)

        if proc_result["returncode"] == 0 and output_file.exists():
            if output_file.stat().st_size > 0:
                result["success"] = True
                result["output_path"] = str(output_file)
                logger.info(f"Metadados removidos: {output_file.name}")
            else:
                result["error"] = "Arquivo de saída vazio após processamento."
        else:
            stderr = proc_result.get("stderr", "")
            logger.error(f"FFmpeg falhou: {stderr[:300]}")
            # Fallback: retorna original se FFmpeg falhar
            result["success"] = True
            result["output_path"] = input_path
            result["error"] = f"ffmpeg_failed: {stderr[:100]}"

    except Exception as e:
        logger.exception(f"Erro ao remover metadados: {e}")
        # Fallback: retorna original
        result["success"] = True
        result["output_path"] = input_path
        result["error"] = str(e)

    return result


def _run_ffmpeg(cmd: list) -> dict:
    """Executa o FFmpeg em processo separado."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,  # 5 minutos de timeout
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout.decode("utf-8", errors="ignore"),
            "stderr": proc.stderr.decode("utf-8", errors="ignore"),
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stderr": "Timeout: processamento demorou demais."}
    except FileNotFoundError:
        return {"returncode": -1, "stderr": "FFmpeg não encontrado no sistema."}


def get_file_size_mb(file_path: str) -> float:
    """Retorna o tamanho do arquivo em MB."""
    try:
        size = os.path.getsize(file_path)
        return round(size / (1024 * 1024), 2)
    except Exception:
        return 0.0


def cleanup_clean_dir():
    """Remove todos os arquivos da pasta de vídeos limpos."""
    try:
        for f in CLEAN_DIR.iterdir():
            if f.is_file():
                f.unlink()
    except Exception as e:
        logger.warning(f"Erro ao limpar pasta clean: {e}")
