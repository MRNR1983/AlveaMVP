"""Cuánto se paga a cada persona en una semana, según su contrato.

DECISIÓN DE PRODUCTO (30-sep-2026). Antes, la propuesta de Alvea pagaba solo
las horas que programaba, mientras que el rol fijo pagaba las horas completas
de todos. Eso contaba como "ahorro" horas de gente de tiempo completo que no
se programaban, aunque su sueldo semanal se paga igual (no se puede bajar;
Transitorio 7 del Decreto DOF 01-05-2026). Con esta regla:

- Tiempo completo (cualquier ``tipo_contrato`` que no sea por hora): cobra
  su jornada semanal completa aunque se le programen menos horas. Las horas
  pagadas que no se programan son **capacidad liberada**, no ahorro.
- Por hora (``tipo_contrato`` en ``CONTRATOS_POR_HORA``): cobra lo trabajado.
- Horas extra: igual para todos, en orden legal (doble y luego triple).

Se aplica DESPUÉS de optimizar (no cambia qué horario se elige), para que los
resultados precalculados sigan sirviendo.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from jornada40 import reglas

CONTRATOS_POR_HORA = {"por_hora", "por hora", "hora", "horas", "eventual_por_hora"}


def paga_semana_completa(tipo_contrato) -> bool:
    return str(tipo_contrato or "completo").strip().lower() not in CONTRATOS_POR_HORA


def costo_por_empleado(horas: dict[str, float], plantilla: pd.DataFrame, anio: int) -> dict[str, dict]:
    """Pago semanal de CADA persona de la plantilla (aunque no tenga turnos).

    ``horas``: horas trabajadas en la semana por empleado_id.
    Regresa {empleado_id: {costo_mxn, horas, ordinaria_trabajada, ordinaria_pagada, doble, triple}}.
    """
    fref = date(anio, 1, 1)
    tope = float(reglas.regla_vigente("jornada_ordinaria_semanal_horas", fref))
    t_dbl = float(reglas.regla_vigente("extra_tope_doble_semanal_horas", fref))
    m_dbl = float(reglas.regla_vigente("pago_extra_doble_multiplicador", fref))
    m_tpl = float(reglas.regla_vigente("pago_extra_triple_multiplicador", fref))
    contrato = (dict(zip(plantilla["empleado_id"], plantilla["tipo_contrato"]))
                if "tipo_contrato" in plantilla.columns else {})
    out: dict[str, dict] = {}
    for e, sal in zip(plantilla["empleado_id"], plantilla["salario_diario_mxn"]):
        h = float(horas.get(e, 0.0))
        vh = float(sal) / (tope / 6)
        o = min(h, tope)
        dbl = min(max(0.0, h - tope), t_dbl)
        tpl = max(0.0, h - tope - t_dbl)
        o_pag = tope if paga_semana_completa(contrato.get(e)) else o
        out[e] = {"costo_mxn": o_pag * vh + dbl * vh * m_dbl + tpl * vh * m_tpl, "horas": h,
                  "ordinaria_trabajada": o, "ordinaria_pagada": o_pag, "doble": dbl, "triple": tpl}
    return out


def horas_de_turnos(turnos_df: pd.DataFrame) -> dict[str, float]:
    if turnos_df is None or turnos_df.empty:
        return {}
    return (turnos_df["hora_fin"] - turnos_df["hora_inicio"]).groupby(turnos_df["empleado_id"]).sum().to_dict()


def aplicar_piso(resultado: dict, plantilla: pd.DataFrame, anio: int) -> dict:
    """Copia de un resultado del optimizador con el costo recalculado según contrato."""
    if not resultado or resultado.get("costo_total_mxn") is None or "turnos_df" not in resultado:
        return resultado
    pagos = costo_por_empleado(horas_de_turnos(resultado["turnos_df"]), plantilla, anio)
    res = dict(resultado)
    res["costo_sin_piso_mxn"] = resultado["costo_total_mxn"]
    res["costo_total_mxn"] = round(sum(p["costo_mxn"] for p in pagos.values()), 2)
    res["horas_ordinarias_pagadas"] = round(sum(p["ordinaria_pagada"] for p in pagos.values()), 2)
    res["horas_capacidad_liberada"] = round(
        sum(p["ordinaria_pagada"] - p["ordinaria_trabajada"] for p in pagos.values()), 2)
    return res
