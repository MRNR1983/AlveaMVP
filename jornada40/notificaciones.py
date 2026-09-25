"""Notificaciones in-app + correo (best-effort) sobre eventos del sistema.

Mismo patrón de persistencia que jornada40.auditoria: CSV en disco,
compartido por todo el proceso (no por sesión de navegador), sin
infraestructura nueva. Una notificación se crea con un ALCANCE (a quién le
aplica) y cada usuario que la ve puede marcarla como leída sin afectar a
los demás destinatarios del mismo alcance (tabla aparte de "leídas").

Correo: usa smtplib + st.secrets. Si no hay credenciales SMTP configuradas
(o el destinatario no tiene correo registrado), NO se intenta conectar --
se registra la notificación in-app igual y el envío de correo queda en
"no enviado", nunca truena la acción de negocio que la originó.

Para activar correo real en Streamlit Cloud: Settings -> Secrets, agregar
    SMTP_HOST = "smtp.tu-proveedor.com"
    SMTP_PORT = 587
    SMTP_USER = "alertas@tu-dominio.mx"
    SMTP_PASSWORD = "..."
    SMTP_FROM = "Alvea PMV <alertas@tu-dominio.mx>"

Dependencias: pandas, smtplib/email (stdlib).
"""
from __future__ import annotations

import smtplib
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

__all__ = [
    "SEVERIDADES", "crear_notificacion", "cargar_notificaciones",
    "cargar_leidas", "visible_para", "marcar_leidas", "no_leidas_para",
    "intentar_enviar_correo", "correo_configurado",
]

_COLS_NOTIF = ["id", "timestamp", "alcance_tipo", "alcance_valor", "tipo",
               "severidad", "mensaje", "correo_enviado", "tienda_id", "fecha"]
_COLS_LEIDAS = ["id", "usuario"]

SEVERIDADES: dict[str, dict] = {
    "info": {"etiqueta": "Info", "st_metodo": "info"},
    "advertencia": {"etiqueta": "Advertencia", "st_metodo": "warning"},
    "critico": {"etiqueta": "Crítico", "st_metodo": "error"},
}


def _ruta_notif(data_dir: Path) -> Path:
    return data_dir / "notificaciones.csv"


def _ruta_leidas(data_dir: Path) -> Path:
    return data_dir / "notificaciones_leidas.csv"


def crear_notificacion(
    data_dir: Path,
    alcance_tipo: str,
    alcance_valor: str | None,
    tipo: str,
    severidad: str,
    mensaje: str,
    email_destino: str | None = None,
    tienda_id: str | None = None,
    fecha: str | None = None,
) -> None:
    """Crea una notificación in-app y, si hay correo destino y SMTP
    configurado, intenta también enviarla por correo (best-effort).
    ``tienda_id``/``fecha`` (ISO) permiten abrir ese día desde el aviso."""
    correo_ok = False
    if email_destino:
        correo_ok = intentar_enviar_correo(
            email_destino, f"Alvea PMV — {SEVERIDADES.get(severidad, {}).get('etiqueta', severidad)}", mensaje,
        )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        fila = pd.DataFrame([{
            "id": uuid.uuid4().hex[:12],
            "timestamp": datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None).isoformat(timespec="seconds"),
            "alcance_tipo": alcance_tipo, "alcance_valor": alcance_valor or "",
            "tipo": tipo, "severidad": severidad, "mensaje": mensaje,
            "correo_enviado": correo_ok, "tienda_id": tienda_id or "", "fecha": fecha or "",
        }])
        ruta = _ruta_notif(data_dir)
        if ruta.exists():
            previas = pd.read_csv(ruta)
            if list(previas.columns) != _COLS_NOTIF:   # archivo de una versión anterior: se migra
                pd.concat([previas, fila], ignore_index=True).reindex(columns=_COLS_NOTIF).to_csv(ruta, index=False)
                return
        fila.to_csv(ruta, mode="a", header=not ruta.exists(), index=False)
    except Exception:
        pass


def cargar_notificaciones(data_dir: Path) -> pd.DataFrame:
    ruta = _ruta_notif(data_dir)
    if not ruta.exists():
        return pd.DataFrame(columns=_COLS_NOTIF)
    try:
        df = pd.read_csv(ruta)
        return df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=_COLS_NOTIF)


def cargar_leidas(data_dir: Path) -> pd.DataFrame:
    ruta = _ruta_leidas(data_dir)
    if not ruta.exists():
        return pd.DataFrame(columns=_COLS_LEIDAS)
    try:
        return pd.read_csv(ruta)
    except Exception:
        return pd.DataFrame(columns=_COLS_LEIDAS)


def visible_para(df: pd.DataFrame, auth: dict) -> pd.DataFrame:
    """Igual criterio de alcance que auditoria.visible_para, pero aquí
    'red' siempre es visible para todos (avisos de toda la compañía)."""
    if df.empty:
        return df
    if auth["rol"] == "super_admin":
        return df
    if auth["rol"] == "admin":
        return df[
            (df["alcance_tipo"] == "red")
            | ((df["alcance_tipo"] == "zona") & (df["alcance_valor"] == auth["zona_id"]))
            | ((df["alcance_tipo"] == "usuario") & (df["alcance_valor"] == auth["usuario"]))
        ]
    return df[
        (df["alcance_tipo"] == "red")
        | ((df["alcance_tipo"] == "tienda") & (df["alcance_valor"] == auth["tienda_id"]))
        | ((df["alcance_tipo"] == "usuario") & (df["alcance_valor"] == auth["usuario"]))
    ]


def marcar_leidas(data_dir: Path, ids: list[str], usuario: str) -> None:
    if not ids:
        return
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        filas = pd.DataFrame([{"id": i, "usuario": usuario} for i in ids])
        ruta = _ruta_leidas(data_dir)
        filas.to_csv(ruta, mode="a", header=not ruta.exists(), index=False)
    except Exception:
        pass


def no_leidas_para(data_dir: Path, auth: dict) -> pd.DataFrame:
    """Notificaciones visibles para este usuario que él mismo no ha marcado leídas."""
    notif = visible_para(cargar_notificaciones(data_dir), auth)
    if notif.empty:
        return notif
    leidas = cargar_leidas(data_dir)
    ids_leidas_propias = set(leidas.loc[leidas["usuario"] == auth["usuario"], "id"]) if not leidas.empty else set()
    return notif[~notif["id"].isin(ids_leidas_propias)]


def correo_configurado() -> bool:
    try:
        import streamlit as st
        return bool(st.secrets.get("SMTP_HOST")) and bool(st.secrets.get("SMTP_USER"))
    except Exception:
        return False


def intentar_enviar_correo(destino: str, asunto: str, cuerpo: str) -> bool:
    """Envía un correo por SMTP si hay credenciales en st.secrets.

    Nunca lanza: si falla la conexión, las credenciales están incompletas,
    o no hay destino, regresa False sin interrumpir a quien llama (el
    envío de correo es una mejora, no una condición para que la
    notificación in-app exista).
    """
    if not destino:
        return False
    try:
        import streamlit as st
        host = st.secrets.get("SMTP_HOST")
        user = st.secrets.get("SMTP_USER")
        password = st.secrets.get("SMTP_PASSWORD")
        puerto = int(st.secrets.get("SMTP_PORT", 587))
        remitente = st.secrets.get("SMTP_FROM", user)
        if not (host and user and password):
            return False
        msg = MIMEText(cuerpo)
        msg["Subject"] = asunto
        msg["From"] = remitente
        msg["To"] = destino
        with smtplib.SMTP(host, puerto, timeout=8) as servidor:
            servidor.starttls()
            servidor.login(user, password)
            servidor.sendmail(remitente, [destino], msg.as_string())
        return True
    except Exception:
        return False
