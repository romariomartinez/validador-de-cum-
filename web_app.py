#!/usr/bin/env python3
"""Front sencillo para validar códigos CUM contra la base SQLite local."""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

DB_PATH = Path("medicamentos.db")
HOST = "127.0.0.1"
PORT = 8080

HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Validador CUM</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 2rem auto; max-width: 900px; padding: 0 1rem; }
    textarea { width: 100%; min-height: 160px; }
    button { margin-top: 1rem; padding: .7rem 1rem; cursor: pointer; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid #ddd; padding: .6rem; text-align: left; }
    th { background: #f4f4f4; }
    .ok { color: #0a7f2e; font-weight: bold; }
    .bad { color: #c21c1c; font-weight: bold; }
  </style>
</head>
<body>
  <h1>Validador de medicamentos CUM</h1>
  <p>Pega uno o varios códigos CUM (separados por coma, espacio o salto de línea).</p>
  <form id="form">
    <textarea id="cums" placeholder="Ejemplo:\n19939557\n20003780"></textarea><br/>
    <button type="submit">Validar</button>
  </form>
  <div id="resumen"></div>
  <table id="tabla" hidden>
    <thead>
      <tr><th>CUM</th><th>Existe</th><th>Nombre</th><th>Estado</th><th>Fecha actualización</th></tr>
    </thead>
    <tbody></tbody>
  </table>

<script>
const form = document.getElementById('form');
const tabla = document.getElementById('tabla');
const tbody = tabla.querySelector('tbody');
const resumen = document.getElementById('resumen');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const cums = document.getElementById('cums').value;
  const resp = await fetch('/validar', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({cums})
  });

  const data = await resp.json();
  tbody.innerHTML = '';

  data.resultados.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.cum}</td>
      <td class="${r.existe ? 'ok' : 'bad'}">${r.existe ? 'Sí' : 'No'}</td>
      <td>${r.nombre ?? '-'}</td>
      <td>${r.estado ?? '-'}</td>
      <td>${r.fecha_actualizacion ?? '-'}</td>`;
    tbody.appendChild(tr);
  });

  resumen.innerHTML = `<p><strong>Total consultados:</strong> ${data.total}. <strong>Encontrados:</strong> ${data.encontrados}.</p>`;
  tabla.hidden = false;
});
</script>
</body>
</html>
"""


def obtener_registros(cums: list[str]) -> list[dict[str, str | bool | None]]:
    """Consulta lote de CUM en SQLite y arma respuesta para el front."""
    if not cums:
        return []

    placeholders = ",".join("?" for _ in cums)
    query = (
        f"SELECT cum, nombre, estado, fecha_actualizacion FROM medicamentos "
        f"WHERE cum IN ({placeholders})"
    )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, cums).fetchall()
    finally:
        conn.close()

    encontrados = {row["cum"]: dict(row) for row in rows}
    salida = []
    for cum in cums:
        row = encontrados.get(cum)
        if row:
            salida.append({"cum": cum, "existe": True, **row})
        else:
            salida.append({"cum": cum, "existe": False, "nombre": None, "estado": None, "fecha_actualizacion": None})
    return salida


class Handler(BaseHTTPRequestHandler):
    """Servidor HTTP simple para formulario y validación."""

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send(HTTPStatus.OK, HTML)
            return
        self._send(HTTPStatus.NOT_FOUND, "No encontrado")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/validar":
            self._send(HTTPStatus.NOT_FOUND, "No encontrado")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        data = parse_qs(raw)
        entrada = data.get("cums", [""])[0]

        tokens = [x.strip() for x in entrada.replace(",", " ").split() if x.strip()]
        cums = list(dict.fromkeys(tokens))

        resultados = obtener_registros(cums)
        encontrados = sum(1 for r in resultados if r["existe"])
        payload = json.dumps({"total": len(cums), "encontrados": encontrados, "resultados": resultados}, ensure_ascii=False)
        self._send(HTTPStatus.OK, payload, "application/json; charset=utf-8")


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError("No existe medicamentos.db. Ejecuta primero sync_medicamentos.py")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Servidor iniciado en http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
