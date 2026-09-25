"""Cálculo completo de 1 tienda x 1 semana (base, propuesta, techo, reporte).

Vive fuera de app.py para que la app y ``scripts/precalcular.py`` usen
exactamente el mismo camino.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from jornada40 import costos_ahorro, demanda_personal, escenario_base, optimizador, precalculado


def anio_regimen(domingo: date) -> int:
    """Año cuyas reglas aplican: el del sábado (si la semana cruza de año, ya aplica el tope nuevo)."""
    return (domingo + timedelta(days=6)).year


def calcular(tienda_id: str, domingo: date, datos: dict[str, pd.DataFrame], tiempo_limite_seg: float,
             version_modelo: str, usar_precalculado: bool = True) -> tuple[dict, dict, dict]:
    """Regresa (reporte, propuesta, techo)."""
    anio = anio_regimen(domingo)
    tiendas_t = datos["tiendas"].loc[datos["tiendas"]["tienda_id"] == tienda_id]
    plantilla_t = datos["plantilla"].loc[datos["plantilla"]["tienda_id"] == tienda_id]
    trafico_t = datos["trafico"].loc[datos["trafico"]["tienda_id"] == tienda_id]
    ventas_t = datos["ventas"].loc[datos["ventas"]["tienda_id"] == tienda_id]
    ausentismo_t = datos["ausentismo"].loc[
        datos["ausentismo"]["empleado_id"].isin(set(plantilla_t["empleado_id"]))]

    demanda = demanda_personal.marcar_franjas_pico(
        demanda_personal.calcular_demanda_tienda(tienda_id, trafico_t, ventas_t, tiendas_t))
    base = escenario_base.calcular_horario_base_tienda(
        tienda_id, anio, plantilla_t, ausentismo_t, demanda, fecha_inicio=domingo)
    guardado = precalculado.cargar(version_modelo, tienda_id, domingo) if usar_precalculado else None
    if guardado:
        propuesta, techo = guardado
    else:
        propuesta = optimizador.resolver_tienda(
            tienda_id, anio, plantilla_t, demanda, ausentismo_t,
            tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=domingo)
        techo = optimizador.resolver_techo_teorico(
            tienda_id, anio, plantilla_t, demanda, ausentismo_t,
            tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=domingo)
    reporte = costos_ahorro.generar_reporte_cfo(tienda_id, base, propuesta, techo, anio)
    reporte.update({"status": propuesta["status"], "propuesta": propuesta, "base": base,
                    "demanda": demanda, "fecha_inicio": domingo, "anio": anio,
                    "plantilla": plantilla_t, "ausentismo": ausentismo_t,
                    "precalculado": bool(guardado)})
    return reporte, propuesta, techo
