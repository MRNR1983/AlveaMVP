"""Respaldo de los datos vivos de la app en GitHub (rama ``datos-app``).

Streamlit Community Cloud borra el disco en cada reinicio. Para que el
historial, los avisos, los cambios de turno y el estado de las cuentas
sobrevivan, cada archivo de ``data/`` que la app escribe se copia a la rama
``datos-app`` del repo, y al arrancar se restaura desde ahí.

Configuración (Streamlit Cloud -> Settings -> Secrets)::

    github_token = "github_pat_..."   # fine-grained, solo Contents: Read and write en este repo
    github_repo = "MRNR1983/AlveaMVP"   # opcional, este es el valor por omisión
    github_rama_datos = "datos-app"      # opcional

Sin token la app funciona igual, solo que sin respaldo (como antes).
Todo es best-effort: un fallo de red nunca tumba la app.
"""
from __future__ import annotations

import base64
import os
import threading
import time
from pathlib import Path

import requests

ARCHIVOS = ("auditoria.csv", "notificaciones.csv", "notificaciones_leidas.csv",
            "ediciones.csv", "usuarios_estado.csv")
_API = "https://api.github.com"
_ESPERA_SEG = 4.0          # junta varias escrituras seguidas en una sola subida

_lock = threading.Lock()
_pendientes: dict[str, Path] = {}
_sha: dict[str, str] = {}
_hilo: threading.Thread | None = None


def _config() -> tuple[str, str, str] | None:
    token = os.environ.get("GITHUB_TOKEN_DATOS")
    repo, rama = "MRNR1983/AlveaMVP", "datos-app"
    try:
        import streamlit as st
        token = st.secrets.get("github_token", token)
        repo = st.secrets.get("github_repo", repo)
        rama = st.secrets.get("github_rama_datos", rama)
    except Exception:
        pass
    return (token, repo, rama) if token else None


def configurado() -> bool:
    return _config() is not None


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def restaurar(data_dir: Path) -> list[str]:
    """Baja de GitHub los archivos que no existan localmente. Regresa los restaurados."""
    cfg = _config()
    if not cfg:
        return []
    token, repo, rama = cfg
    data_dir.mkdir(parents=True, exist_ok=True)
    hechos = []
    for nombre in ARCHIVOS:
        try:
            r = requests.get(f"{_API}/repos/{repo}/contents/data/{nombre}", params={"ref": rama},
                             headers=_headers(token), timeout=10)
            if r.status_code != 200:
                continue
            j = r.json()
            _sha[nombre] = j["sha"]
            destino = data_dir / nombre
            if not destino.exists():
                contenido = base64.b64decode(j["content"]) if j.get("content") else _bajar_grande(j, token)
                destino.write_bytes(contenido)
                hechos.append(nombre)
        except Exception:
            continue
    return hechos


def _bajar_grande(j: dict, token: str) -> bytes:
    # La API no incluye 'content' para archivos > 1 MB: se baja el blob.
    r = requests.get(j["git_url"], headers=_headers(token), timeout=20)
    return base64.b64decode(r.json()["content"])


def subir(ruta: Path) -> None:
    """Marca el archivo para respaldo; lo sube un hilo en segundo plano."""
    global _hilo
    if ruta.name not in ARCHIVOS or not configurado():
        return
    with _lock:
        _pendientes[ruta.name] = ruta
        if _hilo is None or not _hilo.is_alive():
            _hilo = threading.Thread(target=_trabajador, daemon=True)
            _hilo.start()


def _trabajador() -> None:
    while True:
        time.sleep(_ESPERA_SEG)
        with _lock:
            lote = dict(_pendientes)
            _pendientes.clear()
        if not lote:
            return
        cfg = _config()
        if not cfg:
            return
        for nombre, ruta in lote.items():
            _subir_uno(nombre, ruta, *cfg)


def _subir_uno(nombre: str, ruta: Path, token: str, repo: str, rama: str) -> None:
    try:
        contenido = base64.b64encode(ruta.read_bytes()).decode()
    except Exception:
        return
    url = f"{_API}/repos/{repo}/contents/data/{nombre}"
    for _ in range(2):   # si el sha quedó viejo, se refresca y se reintenta una vez
        cuerpo = {"message": f"datos: {nombre}", "content": contenido, "branch": rama}
        if nombre in _sha:
            cuerpo["sha"] = _sha[nombre]
        try:
            r = requests.put(url, json=cuerpo, headers=_headers(token), timeout=15)
        except Exception:
            return
        if r.status_code in (200, 201):
            _sha[nombre] = r.json()["content"]["sha"]
            return
        if r.status_code in (409, 422):
            g = requests.get(url, params={"ref": rama}, headers=_headers(token), timeout=10)
            if g.status_code == 200:
                _sha[nombre] = g.json()["sha"]
            else:
                _sha.pop(nombre, None)
            continue
        return
