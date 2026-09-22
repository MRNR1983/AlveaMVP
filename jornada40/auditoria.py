"""Histórico / auditoría: quién hizo qué, cuándo y en qué alcance.

Registro append-only en CSV (mismo patrón que usuarios_estado.csv en
app.py: sin infraestructura nueva, compartido por todo el proceso, no por
sesión de navegador). Cada fila es un evento ya ocurrido -- este módulo
no valida permisos ni decide si algo debe registrarse, eso lo decide
quien llama (app.py) en el punto exacto donde el evento ocurre.

Alcance (para filtrar quién puede VER cada evento, ver `visible_para`):
  - "tienda": un evento de una tienda específica (alcance_valor = tienda_id)
  - "zona":   un evento a nivel de una zona/admin regional (alcance_valor = zona_id)
  - "red":    un evento de toda la red (SADMIN, cálculo de red completa, etc.)

Dependencias: pandas.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

__all__ = [
    "TIPOS_EVENTO", "registrar_evento", "cargar_auditoria", "visible_para",
]

_COLUMNAS = ["timestamp", "usuario", "rol", "alcance_tipo", "alcance_valor", "tipo_evento", "detalle"]

# Catálogo de tipos de evento -- centraliza la etiqueta legible (usada en
# el filtro de la página Auditoría) para no repetir strings sueltos por
# toda la app y para que agregar un tipo nuevo sea de una sola línea.
TIPOS_EVENTO: dict[str, str] = {
    "sesion_iniciada": "Inicio de sesión",
    "sesion_cerrada": "Cierre de sesión",
    "cuenta_desactivada": "Cuenta desactivada",
    "cuenta_reactivada": "Cuenta reactivada",
    "correo_actualizado": "Correo de notificaciones actualizado",
    "datos_cargados": "Datos propios cargados",
    "datos_restablecidos": "Vuelta a datos de ejemplo",
    "red_calculada": "Cálculo de Vista Red",
    "turno_reasignado": "Turno reasignado (Calendario)",
    "turno_calificado": "Cambio de turno calificado",
    "pagina_visitada": "Navegación entre páginas",
}


def _ruta_csv(data_dir: Path) -> Path:
    return data_dir / "auditoria.csv"


def registrar_evento(
    data_dir: Path,
    usuario: str,
    rol: str,
    alcance_tipo: str,
    alcance_valor: str | None,
    tipo_evento: str,
    detalle: str = "",
) -> None:
    """Agrega una fila al histórico. Nunca lanza -- un fallo de auditoría
    no debe tumbar la acción de negocio que la originó (best-effort)."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        fila = pd.DataFrame([{
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "usuario": usuario, "rol": rol,
            "alcance_tipo": alcance_tipo, "alcance_valor": alcance_valor or "",
            "tipo_evento": tipo_evento, "detalle": detalle,
        }])
        ruta = _ruta_csv(data_dir)
        fila.to_csv(ruta, mode="a", header=not ruta.exists(), index=False)
    except Exception:
        pass


def cargar_auditoria(data_dir: Path) -> pd.DataFrame:
    ruta = _ruta_csv(data_dir)
    if not ruta.exists():
        return pd.DataFrame(columns=_COLUMNAS)
    try:
        df = pd.read_csv(ruta)
        return df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=_COLUMNAS)


def visible_para(df: pd.DataFrame, auth: dict) -> pd.DataFrame:
    """Recorta el histórico al alcance del rol: manager ve su tienda (+ lo
    que él mismo hizo), admin ve su zona (+ lo suyo), super_admin ve todo."""
    if df.empty:
        return df
    if auth["rol"] == "super_admin":
        return df
    if auth["rol"] == "admin":
        return df[
            ((df["alcance_tipo"] == "zona") & (df["alcance_valor"] == auth["zona_id"]))
            | (df["usuario"] == auth["usuario"])
            | (df["alcance_tipo"] == "red")
        ]
    return df[
        ((df["alcance_tipo"] == "tienda") & (df["alcance_valor"] == auth["tienda_id"]))
        | (df["usuario"] == auth["usuario"])
    ]
