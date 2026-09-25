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
CARPETAS = ("archivos/",)   # todo lo que haya debajo también se respalda (archivos subidos)
RAIZ_DATOS = Path("data")
_API = "https://api.github.com"
_ESPERA_SEG = 4.0          # junta varias escrituras seguidas en una sola subida

_lock = threading.Lock()
_pendientes: dict[str, tuple[Path, str]] = {}   # rel -> (ruta, "subir" | "borrar")
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


def _relativa(ruta: Path) -> str | None:
    """Ruta dentro de data/ (p. ej. 'auditoria.csv' o 'archivos/trafico/2027-03-14.csv.gz'),
    o None si no se respalda."""
    try:
        rel = ruta.resolve().relative_to(RAIZ_DATOS.resolve()).as_posix()
    except ValueError:
        rel = ruta.name
    return rel if (rel in ARCHIVOS or rel.startswith(CARPETAS)) else None


def restaurar(data_dir: Path) -> list[str]:
    """Baja de GitHub lo que no exista localmente (datos vivos y archivos subidos)."""
    cfg = _config()
    if not cfg:
        return []
    token, repo, rama = cfg
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(f"{_API}/repos/{repo}/git/trees/{rama}", params={"recursive": "1"},
                         headers=_headers(token), timeout=15)
        arbol = r.json().get("tree", []) if r.status_code == 200 else []
    except Exception:
        return []
    hechos = []
    for nodo in arbol:
        ruta = nodo.get("path", "")
        if nodo.get("type") != "blob" or not ruta.startswith("data/"):
            continue
        rel = ruta[len("data/"):]
        if not (rel in ARCHIVOS or rel.startswith(CARPETAS)):
            continue
        _sha[rel] = nodo["sha"]
        destino = data_dir / rel
        if destino.exists():
            continue
        try:
            b = requests.get(nodo["url"], headers=_headers(token), timeout=20).json()
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(base64.b64decode(b["content"]))
            hechos.append(rel)
        except Exception:
            continue
    return hechos


def subir(ruta: Path) -> None:
    """Marca el archivo para respaldo; lo sube un hilo en segundo plano."""
    _encolar(ruta, "subir")


def borrar(ruta: Path) -> None:
    """Marca el archivo para quitarlo también del respaldo."""
    _encolar(ruta, "borrar")


def _encolar(ruta: Path, accion: str) -> None:
    global _hilo
    rel = _relativa(ruta)
    if rel is None or not configurado():
        return
    with _lock:
        _pendientes[rel] = (ruta, accion)
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
        for rel, (ruta, accion) in lote.items():
            if accion == "borrar":
                _borrar_uno(rel, *cfg)
            else:
                _subir_uno(rel, ruta, *cfg)


def _sha_remoto(url: str, rama: str, token: str) -> str | None:
    g = requests.get(url, params={"ref": rama}, headers=_headers(token), timeout=10)
    return g.json().get("sha") if g.status_code == 200 else None


def _borrar_uno(rel: str, token: str, repo: str, rama: str) -> None:
    url = f"{_API}/repos/{repo}/contents/data/{rel}"
    try:
        sha = _sha.get(rel) or _sha_remoto(url, rama, token)
        if sha:
            requests.delete(url, json={"message": f"datos: quitar {rel}", "sha": sha, "branch": rama},
                            headers=_headers(token), timeout=15)
        _sha.pop(rel, None)
    except Exception:
        return


def _subir_uno(rel: str, ruta: Path, token: str, repo: str, rama: str) -> None:
    try:
        contenido = base64.b64encode(ruta.read_bytes()).decode()
    except Exception:
        return
    url = f"{_API}/repos/{repo}/contents/data/{rel}"
    for _ in range(2):   # si el sha quedó viejo, se refresca y se reintenta una vez
        cuerpo = {"message": f"datos: {rel}", "content": contenido, "branch": rama}
        if rel in _sha:
            cuerpo["sha"] = _sha[rel]
        try:
            r = requests.put(url, json=cuerpo, headers=_headers(token), timeout=20)
        except Exception:
            return
        if r.status_code in (200, 201):
            _sha[rel] = r.json()["content"]["sha"]
            return
        if r.status_code in (409, 422):
            sha = _sha_remoto(url, rama, token)
            if sha:
                _sha[rel] = sha
            else:
                _sha.pop(rel, None)
            continue
        return
