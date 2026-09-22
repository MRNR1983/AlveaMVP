"""Autenticacion sencilla y roster de usuarios por tienda (PMV).

DECISION DE PRODUCTO (21-sep-2026, corregida): el login NO pregunta "que
rol eres" -- el rol lo determina el NOMBRE DE USUARIO con el que se entra
(como cualquier login real). Todos comparten una sola contrasena (ver
password_login), pero el usuario ya trae codificado a que tienda y a que
cuenta pertenece, asi no hace falta un selector de tienda aparte en el
login: "ADMIN" y "SADMIN" son cuentas unicas; cada tienda tiene sus 3
cuentas de gerente como "<tienda_id>-U1", "<tienda_id>-U2", "<tienda_id>-U3"
(p.ej. "T001-U1"), asi el usuario mismo dice en que tienda esta.

Las 3 cuentas -Un por tienda NO son "backups de gerente" -- son cuentas
GENERICAS/flotantes que el gerente puede usar SI LAS NECESITA: cuando
alguien nuevo ya esta trabajando pero todavia no tiene su alta/cuenta
individual capturada en el sistema, sus horas se siguen registrando bajo
una de estas cuentas genericas en vez de perderse. HQ las activa/desactiva
desde "Gestion de usuarios"; el admin decide cuando reasignar esas horas
al empleado real una vez completada su alta.

SEGURIDAD (brecha conocida, aceptada para el PMV): la contrasena de demo
vive en este archivo como fallback visible en el repo publico -- son los
primeros digitos de pi (3.14159265358), elegidos justamente por ser un
valor publico y facil de compartir con el revisor, no un secreto real. En
Streamlit Cloud, si se configura st.secrets["password_login"] (ver
.streamlit/secrets.toml, NO versionado), esa pisa el fallback. Sin secrets
configurados, la app sigue funcionando con la de demo de abajo -- por eso
esta documentada y no oculta: ocultarla a medias hubiera dado falsa
sensacion de seguridad. Antes de cualquier uso real: mover a secrets +
contrasenas individuales + hash + rate limit.
"""
from __future__ import annotations

import pandas as pd

__all__ = ["generar_usuarios", "password_login", "buscar_usuario", "ETIQUETA_CUENTA_GENERICA"]

# Fallback de demo -- visible a proposito (ver docstring). st.secrets pisa esto si existe.
_PASSWORD_DEMO = "3.14159265358"

ETIQUETA_CUENTA_GENERICA = "Cuenta genérica/flotante (para altas de personal pendientes)"

_SLOTS_GERENTE = ["U1", "U2", "U3"]


def password_login() -> str:
    """Contrasena unica compartida por todas las cuentas (el rol lo da el usuario, no la contrasena)."""
    try:
        import streamlit as st
        return st.secrets.get("password_login", _PASSWORD_DEMO)
    except Exception:
        return _PASSWORD_DEMO


def generar_usuarios(tiendas_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Roster completo de cuentas: ADMIN, SADMIN, y 3 cuentas de gerente por tienda.

    Columnas: usuario (login, único), rol (admin/super_admin/manager),
    tienda_id (None para admin/sadmin), usuario_id (ADMIN/SADMIN/U1/U2/U3),
    etiqueta, activo.

    El nombre de usuario ya codifica el rol y, para gerentes, la tienda
    ("T001-U1"), así el login no necesita preguntar "¿qué rol eres?" ni
    tener un selector de tienda separado -- se lee del propio usuario.
    """
    del seed  # sin aleatoriedad real: la lista es determinista por diseño
    filas = [
        {"usuario": "ADMIN", "rol": "admin", "tienda_id": None, "usuario_id": "ADMIN",
         "etiqueta": "Admin / HQ (ve las 50 tiendas)", "activo": True},
        {"usuario": "SADMIN", "rol": "super_admin", "tienda_id": None, "usuario_id": "SADMIN",
         "etiqueta": "Super Admin (ve todo, puede simular cualquier perfil)", "activo": True},
    ]
    for tienda in tiendas_df["tienda_id"]:
        for slot in _SLOTS_GERENTE:
            filas.append({
                "usuario": f"{tienda}-{slot}",
                "rol": "manager",
                "tienda_id": tienda,
                "usuario_id": slot,
                "etiqueta": ETIQUETA_CUENTA_GENERICA,
                "activo": True,
            })
    return pd.DataFrame(filas)


def buscar_usuario(usuario: str, usuarios_df: pd.DataFrame) -> dict | None:
    """Busca un usuario por nombre (sin distinguir mayúsculas/minúsculas).

    Regresa la fila como dict (usuario, rol, tienda_id, usuario_id, etiqueta,
    activo) o None si no existe. No valida contraseña ni estado activo --
    eso lo decide quien llama (la pantalla de login).
    """
    if not usuario:
        return None
    coincidencia = usuarios_df[usuarios_df["usuario"].str.upper() == usuario.strip().upper()]
    if coincidencia.empty:
        return None
    fila = coincidencia.iloc[0].to_dict()
    # tienda_id es None para ADMIN/SADMIN; pandas lo vuelve NaN al mezclarse
    # con strings en la misma columna -- se regresa a None explícitamente.
    if pd.isna(fila.get("tienda_id")):
        fila["tienda_id"] = None
    return fila
