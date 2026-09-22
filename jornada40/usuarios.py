"""Autenticacion sencilla y roster de cuentas genericas por tienda (PMV).

DECISION DE PRODUCTO (21-sep-2026, simplificada por el negocio): un solo
autenticador con UNA contrasena compartida para los 3 roles (Admin,
Manager, SAdmin) -- "super sencillo, cuadrito en medio de la pantalla tipo
GitHub". No es un sistema de auth de produccion (sin hash, sin sesiones de
servidor, sin rotacion, sin usuarios individuales) -- el rol se elige en la
misma pantalla y la contrasena solo separa "sabe entrar" de "no sabe
entrar"; la navegacion despues del login sigue igual de segmentada por rol.

Las 3 cuentas por tienda (U1/U2/U3) NO son "backups de gerente" -- son
cuentas GENERICAS reutilizables para que, cuando alguien nuevo ya esta
trabajando pero todavia no tiene su alta/cuenta individual en el sistema,
sus horas se sigan capturando bajo una cuenta generica en vez de perderse.
HQ las activa/desactiva; el admin decide cuando reasignar esas horas al
empleado real una vez completada su alta.

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

__all__ = ["generar_usuarios", "password_login", "ETIQUETA_CUENTA_GENERICA"]

# Fallback de demo -- visible a proposito (ver docstring). st.secrets pisa esto si existe.
_PASSWORD_DEMO = "3.14159265358"

ETIQUETA_CUENTA_GENERICA = "Cuenta genérica (para altas de personal pendientes)"


def password_login() -> str:
    """Contrasena unica compartida por los 3 roles (Admin, Manager, SAdmin).

    Lee de st.secrets si existe y tiene la clave; si no (sin secrets.toml,
    fuera de contexto Streamlit, o clave ausente), regresa el fallback de
    demo. st.secrets truena en vez de comportarse como dict si no hay NINGUN
    secrets.toml -- por eso va en try/except, no basta un .get().
    """
    try:
        import streamlit as st
        return st.secrets.get("password_login", _PASSWORD_DEMO)
    except Exception:
        return _PASSWORD_DEMO


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
