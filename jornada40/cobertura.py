"""Horas de demanda sin cubrir, en pico y fuera de pico, medidas igual para los dos horarios.

DECISIÓN DE PRODUCTO (1-oct-2026). Antes solo se contaba el déficit en hora pico de la
propuesta y se comparaba contra el déficit de TODAS las horas del rol fijo (alcances
distintos). Eso dejaba fuera las horas sin cubrir fuera de pico: la propuesta podía
"ahorrar" horas extra simplemente no cubriendo esa demanda. Aquí se miden ambos horarios
por día, hora y área, y el candado de costos_ahorro.py compara total contra total.
"""
from __future__ import annotations

import pandas as pd


def _vacio() -> dict:
    return {"pico": 0, "fuera_pico": 0, "total": 0, "por_dia": {}}


def _acumular(out: dict, fecha, es_pico: bool, falta: int) -> None:
    if falta <= 0:
        return
    out["pico" if es_pico else "fuera_pico"] += falta
    out["total"] += falta
    out["por_dia"][fecha] = out["por_dia"].get(fecha, 0) + falta


def deficit_propuesta(turnos_df: pd.DataFrame, demanda: pd.DataFrame, plantilla: pd.DataFrame) -> dict:
    """Déficit de un horario por turnos. Quien está en su hora de descanso no cubre esa hora."""
    out = _vacio()
    if demanda is None or demanda.empty:
        return out
    rol_de = dict(zip(plantilla["empleado_id"], plantilla["rol"]))
    cob: dict = {}
    if turnos_df is not None and not turnos_df.empty:
        for r in turnos_df.itertuples(index=False):
            for h in range(int(r.hora_inicio), int(r.hora_fin)):
                if h != int(r.hora_pausa):
                    k = (r.fecha, h, rol_de.get(r.empleado_id))
                    cob[k] = cob.get(k, 0) + 1
    for r in demanda.itertuples(index=False):
        _acumular(out, r.fecha, bool(r.es_pico),
                  int(r.personas_requeridas) - cob.get((r.fecha, int(r.hora), r.rol), 0))
    return out


def deficit_base(resultado_base: dict, demanda: pd.DataFrame) -> dict:
    """Déficit del rol fijo después de alargar turnos con horas extra (escenario_base.py)."""
    out = _vacio()
    rh = resultado_base.get("resultado_horas")
    if rh is None or rh.empty:
        return out
    pico = {(r.fecha, int(r.hora), r.rol): bool(r.es_pico) for r in demanda.itertuples(index=False)} \
        if demanda is not None and "es_pico" in demanda.columns else {}
    for r in rh.itertuples(index=False):
        _acumular(out, r.fecha, pico.get((r.fecha, int(r.hora), r.rol), False), int(r.horas_subdotacion))
    return out


def anotar(resultado: dict, deficit: dict) -> dict:
    """Copia del resultado con el déficit medido (sin tocar el costo)."""
    if not resultado:
        return resultado
    res = dict(resultado)
    res["horas_subdotacion_pico"] = int(deficit["pico"])
    res["horas_subdotacion_fuera_pico"] = int(deficit["fuera_pico"])
    res["horas_subdotacion_total"] = int(deficit["total"])
    res["subdotacion_por_dia"] = dict(deficit["por_dia"])
    return res
