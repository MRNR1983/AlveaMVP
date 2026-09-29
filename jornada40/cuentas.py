"""Cuentas propias: cualquiera se registra y obtiene un espacio privado.

Cada cuenta tiene su carpeta ``data/espacios/<id>/``: sus archivos subidos,
su historial, avisos y cambios de turno. Arranca con los archivos de la demo
(para ver resultados desde el primer segundo) y puede subir los suyos o
vaciarlo y empezar desde cero. Nada de lo que haga toca la demo ni a otras cuentas.

Contraseñas: PBKDF2-SHA256 con sal por cuenta; nunca se guarda el texto.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from jornada40 import persistencia

COLUMNAS = ["correo", "nombre", "empresa", "sal", "hash", "espacio", "creada", "ob"]
ITERACIONES = 200_000
MAX_CUENTAS = 500
PASOS_OB = 4          # ob: 1..4 = paso del asistente; 0 = terminado
_CORREO = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def _ruta(data_dir: Path) -> Path:
    return data_dir / "cuentas.csv"


def cargar(data_dir: Path) -> pd.DataFrame:
    p = _ruta(data_dir)
    if not p.exists():
        return pd.DataFrame(columns=COLUMNAS)
    try:
        df = pd.read_csv(p, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=COLUMNAS)
    for c in COLUMNAS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNAS]


def _guardar(data_dir: Path, df: pd.DataFrame) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(_ruta(data_dir), index=False)
    persistencia.subir(_ruta(data_dir))


def _hash(password: str, sal: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(sal), ITERACIONES).hex()


def normalizar(correo: str) -> str:
    return correo.strip().lower()


def es_correo(texto: str) -> bool:
    return bool(_CORREO.fullmatch(texto.strip()))


def validar_registro(correo: str, nombre: str, empresa: str, password: str, password2: str,
                     existentes: pd.DataFrame) -> str | None:
    """Regresa el primer problema, en palabras para el usuario, o None si todo está bien."""
    if not nombre.strip():
        return "Escribe tu nombre."
    if not empresa.strip():
        return "Escribe tu empresa."
    if not es_correo(correo):
        return "Revisa el correo: falta @ o el dominio."
    if normalizar(correo) in set(existentes["correo"]):
        return "Ya hay una cuenta con ese correo. Entra con él."
    if len(password) < 8:
        return "La contraseña necesita al menos 8 caracteres."
    if password != password2:
        return "Las contraseñas no coinciden."
    if len(existentes) >= MAX_CUENTAS:
        return "Ya no hay lugar para cuentas nuevas en esta prueba."
    return None


def crear(data_dir: Path, correo: str, nombre: str, empresa: str, password: str) -> dict:
    df = cargar(data_dir)
    sal = secrets.token_hex(16)
    fila = {"correo": normalizar(correo), "nombre": nombre.strip(), "empresa": empresa.strip(),
            "sal": sal, "hash": _hash(password, sal), "espacio": secrets.token_hex(6),
            "creada": datetime.now(ZoneInfo("America/Mexico_City")).isoformat(timespec="seconds"),
            "ob": "1"}
    _guardar(data_dir, pd.concat([df, pd.DataFrame([fila])], ignore_index=True))
    return fila


def verificar(data_dir: Path, correo: str, password: str) -> dict | None:
    df = cargar(data_dir)
    m = df[df["correo"] == normalizar(correo)]
    if m.empty:
        return None
    fila = m.iloc[0].to_dict()
    return fila if hmac.compare_digest(_hash(password, fila["sal"]), fila["hash"]) else None


def buscar(data_dir: Path, correo: str) -> dict | None:
    df = cargar(data_dir)
    m = df[df["correo"] == normalizar(correo)]
    return None if m.empty else m.iloc[0].to_dict()


def fijar_paso(data_dir: Path, correo: str, paso: int) -> None:
    df = cargar(data_dir)
    df.loc[df["correo"] == normalizar(correo), "ob"] = str(paso)
    _guardar(data_dir, df)


def carpeta_espacio(data_dir: Path, espacio: str) -> Path:
    return data_dir / "espacios" / espacio
