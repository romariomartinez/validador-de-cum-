#!/usr/bin/env python3
"""Sincronizador incremental de medicamentos (CUM) usando API Socrata/datos.gov.co."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATASET_URL = "https://www.datos.gov.co/resource/i7cb-raxc.json"
DB_PATH = "medicamentos.db"
TABLE_NAME = "medicamentos"
PAGE_SIZE = 50_000
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


@dataclass
class Config:
    """Configuración del sincronizador."""

    dataset_url: str = DATASET_URL
    db_path: str = DB_PATH
    page_size: int = PAGE_SIZE
    app_token: str | None = None


def configurar_logging() -> None:
    """Inicializa formato de logs para trazabilidad."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def obtener_conexion(db_path: str) -> sqlite3.Connection:
    """Crea conexión SQLite y aplica ajustes de rendimiento."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_bd(conn: sqlite3.Connection) -> None:
    """Crea la tabla e índices necesarios si no existen."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS medicamentos (
            cum TEXT PRIMARY KEY,
            nombre TEXT,
            estado TEXT,
            fecha_actualizacion TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_medicamentos_fecha ON medicamentos (fecha_actualizacion)"
    )
    conn.commit()


def obtener_ultima_fecha(conn: sqlite3.Connection) -> str | None:
    """Retorna la fecha más reciente en base local para sincronización incremental."""
    row = conn.execute("SELECT MAX(fecha_actualizacion) AS ultima FROM medicamentos").fetchone()
    return row["ultima"] if row and row["ultima"] else None


def request_con_reintentos(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    max_retries: int = MAX_RETRIES,
) -> list[dict[str, Any]]:
    """Ejecuta GET con reintentos exponenciales básicos."""
    intento = 0
    while True:
        try:
            query = urlencode(params)
            final_url = f"{url}?{query}" if query else url
            req = Request(final_url, headers=headers, method="GET")
            with urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            intento += 1
            if intento > max_retries:
                logging.error("Fallo API tras %s intentos. Error: %s", max_retries, exc)
                raise
            espera = RETRY_BACKOFF_SECONDS * intento
            logging.warning(
                "Error en API (intento %s/%s). Reintentando en %ss...",
                intento,
                max_retries,
                espera,
            )
            time.sleep(espera)


def detectar_campo_fecha(config: Config, headers: dict[str, str]) -> bool:
    """Verifica si el dataset expone el campo `fecha_actualizacion`."""
    params = {"$select": "fecha_actualizacion", "$limit": 1}
    try:
        datos = request_con_reintentos(config.dataset_url, params, headers)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return False

    if not datos:
        return True
    return "fecha_actualizacion" in datos[0]


def limpiar_tabla(conn: sqlite3.Connection) -> None:
    """Vacía tabla para sincronización completa."""
    conn.execute(f"DELETE FROM {TABLE_NAME}")
    conn.commit()


def normalizar_registro(item: dict[str, Any]) -> tuple[str, str | None, str | None, str | None] | None:
    """Extrae campos relevantes de un registro remoto."""
    cum = item.get("cum")
    if not cum:
        return None
    nombre = item.get("descripcion_comercial") or item.get("nombre")
    estado = item.get("estado_registro") or item.get("estado")
    fecha_actualizacion = item.get("fecha_actualizacion")
    return str(cum), nombre, estado, fecha_actualizacion


def upsert_lote(conn: sqlite3.Connection, registros: Iterable[tuple[str, str | None, str | None, str | None]]) -> int:
    """Inserta/actualiza lotes evitando duplicados por CUM."""
    lote = list(registros)
    if not lote:
        return 0

    conn.executemany(
        """
        INSERT INTO medicamentos (cum, nombre, estado, fecha_actualizacion)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cum) DO UPDATE SET
            nombre=excluded.nombre,
            estado=excluded.estado,
            fecha_actualizacion=excluded.fecha_actualizacion
        """,
        lote,
    )
    conn.commit()
    return len(lote)


def sincronizar(
    conn: sqlite3.Connection,
    config: Config,
    headers: dict[str, str],
    incremental: bool,
) -> int:
    """Sincroniza por páginas, incremental o completa según bandera."""
    total_procesados = 0
    offset = 0

    ultima_fecha = obtener_ultima_fecha(conn) if incremental else None
    if incremental and ultima_fecha:
        logging.info("Sincronización incremental desde fecha: %s", ultima_fecha)
    elif incremental:
        logging.info("Sin fecha previa local; se hará carga completa inicial.")

    while True:
        params: dict[str, Any] = {
            "$limit": config.page_size,
            "$offset": offset,
        }
        if incremental and ultima_fecha:
            params["$where"] = f"fecha_actualizacion > '{ultima_fecha}'"
            params["$order"] = "fecha_actualizacion ASC"

        data = request_con_reintentos(config.dataset_url, params, headers)
        if not data:
            break

        lote = [r for item in data if (r := normalizar_registro(item)) is not None]
        procesados = upsert_lote(conn, lote)
        total_procesados += procesados
        offset += config.page_size

        logging.info(
            "Página procesada. offset=%s, recibidos=%s, upserts=%s, acumulado=%s",
            offset,
            len(data),
            procesados,
            total_procesados,
        )

        if len(data) < config.page_size:
            break

    return total_procesados


def actualizar_medicamentos(config: Config | None = None) -> int:
    """Función principal invocable por cron/tarea programada."""
    config = config or Config(app_token=os.getenv("SOCRATA_APP_TOKEN"))
    headers = {"X-App-Token": config.app_token} if config.app_token else {}

    conn = obtener_conexion(config.db_path)
    try:
        inicializar_bd(conn)
        tiene_fecha = detectar_campo_fecha(config, headers)

        if tiene_fecha:
            total = sincronizar(conn, config, headers, incremental=True)
        else:
            logging.warning(
                "El dataset no tiene campo fecha_actualizacion o no fue posible validarlo. "
                "Se ejecuta sincronización completa."
            )
            limpiar_tabla(conn)
            total = sincronizar(conn, config, headers, incremental=False)

        logging.info("Sincronización finalizada. Registros procesados: %s", total)
        return total
    finally:
        conn.close()


def main() -> int:
    configurar_logging()
    try:
        actualizar_medicamentos()
        return 0
    except Exception as exc:  # noqa: BLE001
        logging.exception("Error fatal en actualización: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
