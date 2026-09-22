"""Autenticacion sencilla y roster de cuentas genericas por tienda (PMV).

DECISION DE PRODUCTO (21-sep-2026, corregida): "autenticador sencillo"
pedido explicitamente por el negocio -- NO es un sistema de auth de
produccion (sin hash, sin sesiones de servidor, sin rotacion). Separa la
navegacion de Gerente de tienda / Admin-HQ / Super Admin en la demo.

Las 3 cuentas por tienda (U1/U2/U3) NO son "backups de gerente" -- son
cuentas GENERICAS reutilizables para que, cuando alguien nuevo ya esta
trabajando pero todavia no tiene su alta/cuenta individual en el sistema,
sus horas se sigan capturando bajo una cuenta generica en vez de perderse.
HQ las activa/desactiva; el admin decide cuando reasignar esas horas al
empleado real una vez completada su alta.

SEGURIDAD (brecha conocida, aceptada para el PMV): las contrasenas de demo
viven en este archivo como fallback visible en el repo publico. En
Streamlit Cloud, si se configuran st.secrets (ver .streamlit/secrets.toml,
NO versionado), esas pisan el fallback. Sin secrets configurados, la app
sigue funcionando con las de demo de abajo -- por eso estan documentadas y
no ocultas: ocultarlas a medias hubiera dado falsa sensacion de seguridad.
Antes de cualquier uso real: mover a secrets + agregar hash/rate limit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

def _secret_o_fallback(clave: str, fallback: str) -> str:
    """Lee de st.secrets si existe y tiene la clave; si no (sin secrets.toml,
    fuera de contexto Streamlit, o clave ausente), regresa el fallback de
    demo. st.secrets truena en vez de comportarse como dict si no hay NINGUN
    secrets.toml -- por eso todo esto va en try/except, no basta un .get().
    """
    try:
        import streamlit as st
        return st.secrets.get(clave, fallback)
    except Exception:
        return fallback

__all__ = [
    "generar_usuarios",
    "password_manager", "password_admin", "password_super_admin",
    "ETIQUETA_CUENTA_GENERICA",
]

# Fallback de demo -- visibles a proposito (ver docstring). st.secrets pisa esto si existe.
_PASSWORD_MANAGER_DEMO = "jornada40"
_PASSWORD_ADMIN_DEMO = "hq2026"
_PASSWORD_SUPER_ADMIN_DEMO = "superhq2026"

ETIQUETA_CUENTA_GENERICA = "Cuenta genérica (para altas de personal pendientes)"


def password_manager() -> str:
    return _secret_o_fallback("password_manager", _PASSWORD_MANAGER_DEMO)


def password_admin() -> str:
    return _secret_o_fallback("password_admin", _PASSWORD_ADMIN_DEMO)


def password_super_admin() -> str:
    return _secret_o_fallback("password_super_admin", _PASSWORD_SUPER_ADMIN_DEMO)


def generar_usuarios(tiendas_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """3 cuentas genericas (U1/U2/U3) por tienda, todas activas por default.

    Columnas: tienda_id, usuario_id (U1/U2/U3), etiqueta, activo.
    No llevan nombre de persona real -- son cuentas genericas reutilizables,
    no personas fijas asignadas (ver docstring del modulo).
    """
    del seed  # sin aleatoriedad real: la lista es determinista por diseño (mismo trio siempre)
    filas = []
    for tienda in tiendas_df["tienda_id"]:
        for usuario_id in ["U1", "U2", "U3"]:
            filas.append({
                "tienda_id": tienda,
                "usuario_id": usuario_id,
                "etiqueta": ETIQUETA_CUENTA_GENERICA,
                "activo": True,
            })
    return pd.DataFrame(filas)
