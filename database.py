"""
database.py - Gerenciamento de usuários no PostgreSQL
Armazena assinaturas, planos e controla expiração automática.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def _get_conn():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL não configurada. Adicione o PostgreSQL no Railway.")
    # Railway às vezes usa postgres:// mas psycopg2 precisa de postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url)


def criar_tabelas():
    """Cria as tabelas necessárias se não existirem."""
    sql_usuarios = """
    CREATE TABLE IF NOT EXISTS usuarios (
        telegram_id     BIGINT PRIMARY KEY,
        nome            TEXT,
        email           TEXT,
        plano           TEXT,
        data_expiracao  TIMESTAMP WITH TIME ZONE,
        ativo           BOOLEAN DEFAULT TRUE,
        kiwify_order_id TEXT,
        data_cadastro   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """
    sql_uso_diario = """
    CREATE TABLE IF NOT EXISTS uso_diario (
        telegram_id    BIGINT,
        data_uso       DATE DEFAULT CURRENT_DATE,
        usos           INTEGER DEFAULT 0,
        PRIMARY KEY (telegram_id, data_uso)
    );
    """
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_usuarios)
            cur.execute(sql_uso_diario)
        conn.commit()
    logger.info("Tabelas do banco de dados verificadas (usuarios + uso_diario).")


def adicionar_usuario(
    telegram_id: int,
    nome: str,
    email: str,
    plano: str,
    dias: int,
    kiwify_order_id: str = "",
) -> bool:
    """
    Adiciona ou atualiza um usuário.
    dias=0 significa acesso vitalício (sem expiração).
    """
    expiry = None
    if dias > 0:
        expiry = datetime.now(timezone.utc) + timedelta(days=dias)

    sql = """
    INSERT INTO usuarios (telegram_id, nome, email, plano, data_expiracao, ativo, kiwify_order_id)
    VALUES (%s, %s, %s, %s, %s, TRUE, %s)
    ON CONFLICT (telegram_id) DO UPDATE SET
        nome            = EXCLUDED.nome,
        email           = EXCLUDED.email,
        plano           = EXCLUDED.plano,
        data_expiracao  = EXCLUDED.data_expiracao,
        ativo           = TRUE,
        kiwify_order_id = EXCLUDED.kiwify_order_id;
    """
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (telegram_id, nome, email, plano, expiry, kiwify_order_id))
        conn.commit()
    logger.info(f"Usuário {telegram_id} ({nome}) adicionado/atualizado. Plano: {plano} | Dias: {dias}")
    return True


def verificar_acesso(telegram_id: int) -> bool:
    """Verifica se o usuário tem acesso ativo e não expirado."""
    sql = "SELECT ativo, data_expiracao FROM usuarios WHERE telegram_id = %s;"
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (telegram_id,))
            row = cur.fetchone()

    if not row:
        return False
    ativo, expiry = row
    if not ativo:
        return False
    if expiry is None:
        return True  # vitalício
    return datetime.now(timezone.utc) < expiry


def buscar_usuario(telegram_id: int) -> Optional[dict]:
    """Retorna dados completos do usuário ou None."""
    sql = "SELECT * FROM usuarios WHERE telegram_id = %s;"
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (telegram_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def listar_usuarios_ativos() -> list:
    """Lista todos os usuários com acesso ativo."""
    sql = """
    SELECT telegram_id, nome, email, plano, data_expiracao, data_cadastro
    FROM usuarios
    WHERE ativo = TRUE
    ORDER BY data_cadastro DESC;
    """
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def remover_usuario(telegram_id: int) -> bool:
    """Desativa o acesso de um usuário."""
    sql = "UPDATE usuarios SET ativo = FALSE WHERE telegram_id = %s;"
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (telegram_id,))
            affected = cur.rowcount
        conn.commit()
    return affected > 0


def desativar_expirados() -> list:
    """
    Desativa usuários com plano vencido.
    Retorna lista de usuários desativados: [{telegram_id, nome}, ...]
    """
    sql = """
    UPDATE usuarios
    SET ativo = FALSE
    WHERE ativo = TRUE
      AND data_expiracao IS NOT NULL
      AND data_expiracao < NOW()
    RETURNING telegram_id, nome;
    """
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
        conn.commit()
    return rows


def estatisticas() -> dict:
    """Retorna estatísticas gerais dos usuários."""
    sql_usuarios = """
    SELECT
        COUNT(*) FILTER (WHERE ativo = TRUE)                            AS ativos,
        COUNT(*) FILTER (WHERE ativo = FALSE)                           AS inativos,
        COUNT(*) FILTER (WHERE ativo = TRUE AND data_expiracao IS NULL) AS vitalicios,
        COUNT(*) FILTER (WHERE ativo = TRUE AND data_expiracao > NOW()) AS com_plano_ativo
    FROM usuarios;
    """
    sql_uso = """
    SELECT
        COUNT(DISTINCT telegram_id) AS usuarios_gratis_hoje,
        COALESCE(SUM(usos), 0)     AS total_usos_hoje
    FROM uso_diario
    WHERE data_uso = CURRENT_DATE;
    """
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_usuarios)
            stats = dict(cur.fetchone())
            cur.execute(sql_uso)
            stats.update(dict(cur.fetchone()))
            return stats


# ──────────────────────────────────────────────
# Funções do sistema freemium
# ──────────────────────────────────────────────
def registrar_uso(telegram_id: int) -> int:
    """Incrementa e retorna o número de usos do dia."""
    sql = """
    INSERT INTO uso_diario (telegram_id, data_uso, usos)
    VALUES (%s, CURRENT_DATE, 1)
    ON CONFLICT (telegram_id, data_uso) DO UPDATE SET
        usos = uso_diario.usos + 1
    RETURNING usos;
    """
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (telegram_id,))
            result = cur.fetchone()[0]
        conn.commit()
    return result


def consultar_usos_hoje(telegram_id: int) -> int:
    """Retorna quantos vídeos o usuário processou hoje."""
    sql = "SELECT usos FROM uso_diario WHERE telegram_id = %s AND data_uso = CURRENT_DATE;"
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (telegram_id,))
            row = cur.fetchone()
    return row[0] if row else 0


def get_plano_usuario(telegram_id: int) -> Optional[str]:
    """Retorna o nome do plano do usuário ativo ou None."""
    sql = """
    SELECT plano FROM usuarios
    WHERE telegram_id = %s AND ativo = TRUE
      AND (data_expiracao IS NULL OR data_expiracao > NOW());
    """
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (telegram_id,))
            row = cur.fetchone()
    return row[0] if row else None
