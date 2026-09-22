"""Autenticacion sencilla y roster de usuarios (PMV).

DECISION DE PRODUCTO (21-sep-2026, tercera vuelta -- reemplaza el esquema
de cuentas U1/U2/U3 por tienda, que se retiro por completo de la app: no
aportaban nada al negocio en esta etapa). Estructura final:

- 1 SADMIN: ve y puede simular cualquier perfil, sin restriccion.
- 5 ADMIN, uno por ZONA geografica (agrupando los 10 clusters ficticios del
  catalogo de tiendas en 5 zonas -- ver ZONAS abajo). Cada admin regional
  solo ve/opera las tiendas de su zona, no las 50.
- 1 MANAGER por tienda (usuario = el propio tienda_id, p.ej. "T001"): ya no
  hay cuentas de respaldo/flotantes -- una tienda, un usuario de gerente.

Todos comparten la misma contrasena (ver password_login): el rol y el
alcance (tienda o zona) los da el propio nombre de usuario, no un selector
en el login ni una contrasena distinta por rol.

SUPUESTO (documentar en la demo si se pregunta): el catalogo trae 10
clusters geograficos ficticios; se agruparon en 5 zonas de admin por
cercania (CDMX junta sus 3 sub-zonas; el resto en pares), no por conteo
exacto de tiendas -- con 50 tiendas repartidas ~parejo entre 10 clusters,
cada zona administra aprox. 10 tiendas (mas en CDMX, menos en Sureste). Si
el negocio prefiere otra agrupacion, es un cambio de una sola tabla (ZONAS).

SEGURIDAD (brecha conocida, aceptada para el PMV): la contrasena de demo
vive en este archivo como fallback visible en el repo publico -- son los
primeros digitos de pi (3.14159265358), elegidos justamente por ser un
valor publico y facil de compartir con el revisor, no un secreto real. En
Streamlit Cloud, si se configura st.secrets["password_login"] (ver
.streamlit/secrets.toml, NO versionado), esa pisa el fallback. Antes de
cualquier uso real: mover a secrets + contrasenas individuales + hash +
rate limit.
"""
from __future__ import annotations

import pandas as pd

__all__ = [
    "generar_usuarios", "password_login", "buscar_usuario",
    "tiendas_de_zona", "zona_de_cluster", "ZONAS",
]

# Fallback de demo -- visible a proposito (ver docstring). st.secrets pisa esto si existe.
_PASSWORD_DEMO = "3.14159265358"

# Agrupa los 10 clusters ficticios del catalogo (ver datos_sinteticos.CONFIG)
# en 5 zonas de administracion regional. Ver SUPUESTO en el docstring.
ZONAS: dict[str, dict] = {
    "Z1": {"nombre": "CDMX", "clusters": ["CDMX-Norte", "CDMX-Sur", "CDMX-Centro"]},
    "Z2": {"nombre": "Occidente", "clusters": ["GDL", "Leon"]},
    "Z3": {"nombre": "Noreste", "clusters": ["MTY", "Queretaro"]},
    "Z4": {"nombre": "Centro", "clusters": ["Puebla", "Toluca"]},
    "Z5": {"nombre": "Sureste", "clusters": ["Merida"]},
}


def password_login() -> str:
    """Contrasena unica compartida por todas las cuentas (el rol/alcance lo da el usuario)."""
    try:
        import streamlit as st
        return st.secrets.get("password_login", _PASSWORD_DEMO)
    except Exception:
        return _PASSWORD_DEMO


def zona_de_cluster(cluster_id: str) -> str:
    """Regresa el id de zona (Z1..Z5) al que pertenece un cluster geografico."""
    for zona_id, info in ZONAS.items():
        if cluster_id in info["clusters"]:
            return zona_id
    raise ValueError(f"Cluster sin zona asignada: {cluster_id!r} -- revisa ZONAS en usuarios.py")


def tiendas_de_zona(zona_id: str, tiendas_df: pd.DataFrame) -> pd.DataFrame:
    """Subconjunto de tiendas_df que pertenece a la zona dada."""
    clusters = ZONAS[zona_id]["clusters"]
    return tiendas_df[tiendas_df["cluster_id"].isin(clusters)]


def generar_usuarios(tiendas_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Roster completo: SADMIN, 5 ADMIN (uno por zona), 1 MANAGER por tienda.

    Columnas: usuario (login, único), rol (admin/super_admin/manager),
    tienda_id (solo manager), zona_id (admin y manager; None para sadmin),
    etiqueta, activo.
    """
    del seed  # sin aleatoriedad real: la lista es determinista por diseño
    filas = [{
        "usuario": "SADMIN", "rol": "super_admin", "tienda_id": None, "zona_id": None,
        "etiqueta": "Super Admin (ve todo, puede simular cualquier perfil)", "activo": True,
    }]
    for zona_id, info in ZONAS.items():
        filas.append({
            "usuario": f"ADMIN-{zona_id}", "rol": "admin", "tienda_id": None, "zona_id": zona_id,
            "etiqueta": f"Admin regional — zona {info['nombre']} ({zona_id})", "activo": True,
        })
    for _, tienda in tiendas_df.iterrows():
        zona_id = zona_de_cluster(tienda["cluster_id"])
        filas.append({
            "usuario": tienda["tienda_id"], "rol": "manager", "tienda_id": tienda["tienda_id"],
            "zona_id": zona_id, "etiqueta": f"Gerente de {tienda['tienda_id']}", "activo": True,
        })
    return pd.DataFrame(filas)


def buscar_usuario(usuario: str, usuarios_df: pd.DataFrame) -> dict | None:
    """Busca un usuario por nombre (sin distinguir mayúsculas/minúsculas).

    Regresa la fila como dict (usuario, rol, tienda_id, zona_id, etiqueta,
    activo) o None si no existe. No valida contraseña ni estado activo --
    eso lo decide quien llama (la pantalla de login).
    """
    if not usuario:
        return None
    coincidencia = usuarios_df[usuarios_df["usuario"].str.upper() == usuario.strip().upper()]
    if coincidencia.empty:
        return None
    fila = coincidencia.iloc[0].to_dict()
    # tienda_id/zona_id son None para algunas filas; pandas los vuelve NaN al
    # mezclarse con strings en la misma columna -- se regresan a None explícitamente.
    for campo in ("tienda_id", "zona_id"):
        if pd.isna(fila.get(campo)):
            fila[campo] = None
    return fila
