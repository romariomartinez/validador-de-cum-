# Validador de CUM (Colombia)

Proyecto en Python para:

1. **Sincronizar** medicamentos CUM desde datos.gov.co (Socrata) a SQLite.
2. Exponer un **frontend web simple** para validar códigos CUM.

## 1) Requisitos

- Python 3.10+

## 2) Sincronizar base local

```bash
export SOCRATA_APP_TOKEN="TU_APP_TOKEN"
python3 sync_medicamentos.py
```

Esto crea/actualiza `medicamentos.db`.

## 3) Levantar el frontend local

```bash
python3 web_app.py
```

Abrir en navegador: `http://127.0.0.1:8080`

---

## Publicar en GitHub

### A) Crear repositorio y subir

```bash
git init
git add .
git commit -m "Proyecto inicial validador CUM"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

### B) Despliegue recomendado (Render) usando GitHub

> GitHub Pages no sirve para este caso porque aquí hay backend Python.

1. Entra a [https://render.com](https://render.com)
2. Conecta tu cuenta de GitHub.
3. Crea un **Web Service** desde este repo.
4. Configura:
   - **Build Command**: `python -m py_compile sync_medicamentos.py web_app.py`
   - **Start Command**: `python web_app.py`
5. Variables de entorno:
   - `SOCRATA_APP_TOKEN=TU_APP_TOKEN`
6. Deploy.

### C) Tarea de actualización automática

En Render crea un **Cron Job** con:

- Comando: `python sync_medicamentos.py`
- Frecuencia: cada hora o diaria (según necesidad)

Así tu base quedará actualizada automáticamente.

---

## Seguridad

- **No subas tokens o secretos al repositorio.**
- Usa siempre variables de entorno.
- Si ya compartiste un token públicamente, **rótalo**.

