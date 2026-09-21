"""Escenario base (baseline): plantilla rotativa fija + horas extra realista.

Genera el horario "como lo haría hoy un gerente razonable": cuadrillas
rotativas de turno fijo (apertura/intermedio/cierre) que cubren los picos
extendiendo turnos con horas extra hasta el tope legal vigente del año,
en vez de una cobertura deliberadamente mala. Es la "regla anti hombre de
paja": el base compite de forma justa contra la propuesta del optimizador
(jornada40/optimizador.py).

Funciona para cualquier año calendario: consulta jornada40.reglas para el
tope de jornada ordinaria, el tope de horas extra al doble/triple y el
máximo de días trabajados antes de un descanso, todos vigentes según el
año dado (reglas.regla_vigente).

SIMPLIFICACIÓN DOCUMENTADA: la asignación de horas extra a empleados
específicos no garantiza contigüidad horaria estricta con su turno
(el supervisor "prolonga" el turno del empleado disponible con menor
acumulado semanal de extra, sin forzar que sea exactamente antes/después
de su turno original). El optimizador de jornada40/optimizador.py sí
modela la contigüidad real vía CP-SAT; este módulo es la línea base con
la que se compara, deliberadamente más simple.

Dependencias: jornada40.reglas, pandas, numpy.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from jornada40 import reglas

__all__ = [
    "dotacion_por_tipo_dia",
    "armar_cuadrillas_rotativas",
    "aplicar_ausentismo_y_demanda_real",
    "calcular_horario_base_tienda",
]

_TURNOS = ("apertura", "intermedio", "cierre")
_HORA_BASE_APERTURA = 7   # SUPUESTO: ventana genérica del baseline (07:00-22:00)
_HORA_BASE_CIERRE = 22


def _tipo_dia(fecha: date) -> str:
    """Clasifica una fecha en entre_semana / sabado / domingo."""
    if reglas.es_domingo(fecha):
        return "domingo"
    return "sabado" if fecha.weekday() == 5 else "entre_semana"


def dotacion_por_tipo_dia(demanda_tienda_df: pd.DataFrame) -> pd.DataFrame:
    """Dotación planeada hoy: promedio de personas_requeridas por tipo de día.

    Agrupa por (tipo_dia, rol) el PROMEDIO de personas_requeridas (no por
    hora — a propósito, simula la planeación de hoy sin ver detalle por
    hora) y redondea hacia arriba. Columnas: tienda_id, tipo_dia, rol,
    personas_dotadas.
    """
    df = demanda_tienda_df.copy()
    df["tipo_dia"] = df["fecha"].map(_tipo_dia)
    agg = (df.groupby(["tienda_id", "tipo_dia", "rol"])["personas_requeridas"]
           .mean().reset_index())
    agg["personas_dotadas"] = agg["personas_requeridas"].apply(math.ceil)
    return agg[["tienda_id", "tipo_dia", "rol", "personas_dotadas"]]


def armar_cuadrillas_rotativas(
    plantilla_tienda_df: pd.DataFrame,
    anio: int,
    fecha_inicio: date | None = None,
) -> pd.DataFrame:
    """Arma turnos fijos rotativos para una semana (domingo a sábado).

    Cada empleado trabaja ``dias_trabajados = min(6, ceil(jornada/8))`` días
    con turno fijo (apertura/intermedio/cierre, por índice del empleado) y
    descansa el resto de la semana (``7 - dias_trabajados`` días, cumpliendo
    el art. 69: máximo 6 días trabajados antes de un descanso). Las horas
    del día se reparten lo más parejo posible entre los días trabajados
    (jornada_semanal / dias_trabajados), sin exceder individualmente la
    jornada diaria total máxima vigente.

    Si ``fecha_inicio`` es None, usa el domingo de la semana que contiene
    el 1 de enero del año dado (semana de referencia del baseline).

    Columnas: empleado_id, tienda_id, rol, fecha, turno
    ("apertura"/"intermedio"/"cierre"/"descanso"), hora_inicio, hora_fin
    (NaN en días de descanso).
    """
    ref = fecha_inicio or reglas.semana_domingo_a_sabado(date(anio, 1, 1))[0]
    dias_semana = [ref + timedelta(days=i) for i in range(7)]

    jornada_semanal = reglas.regla_vigente("jornada_ordinaria_semanal_horas", date(anio, 1, 1))
    dias_trabajados = min(6, math.ceil(jornada_semanal / 8))
    dias_descanso = 7 - dias_trabajados
    horas_por_dia = jornada_semanal / dias_trabajados

    filas: list[dict] = []
    empleados = plantilla_tienda_df.reset_index(drop=True)
    n = len(empleados)
    for idx, emp in enumerate(empleados.itertuples(index=False)):
        # Rotación del/de los día(s) de descanso: reparte empleados a lo
        # largo de la semana según su índice, para no descansar todos el
        # mismo día (labor continua, arts. 69/70).
        offset = idx % 7
        dias_descanso_idx = {(offset + k) % 7 for k in range(dias_descanso)}
        turno = _TURNOS[idx % 3]
        if turno == "apertura":
            hi, hf = _HORA_BASE_APERTURA, _HORA_BASE_APERTURA + horas_por_dia
        elif turno == "intermedio":
            hi, hf = _HORA_BASE_APERTURA + 4, _HORA_BASE_APERTURA + 4 + horas_por_dia
        else:  # cierre
            hi, hf = _HORA_BASE_CIERRE - horas_por_dia, _HORA_BASE_CIERRE

        for d_idx, fecha in enumerate(dias_semana):
            if d_idx in dias_descanso_idx:
                filas.append({"empleado_id": emp.empleado_id, "tienda_id": emp.tienda_id,
                               "rol": emp.rol, "fecha": fecha, "turno": "descanso",
                               "hora_inicio": np.nan, "hora_fin": np.nan})
            else:
                filas.append({"empleado_id": emp.empleado_id, "tienda_id": emp.tienda_id,
                               "rol": emp.rol, "fecha": fecha, "turno": turno,
                               "hora_inicio": hi, "hora_fin": hf})
    return pd.DataFrame(filas)


def aplicar_ausentismo_y_demanda_real(
    horario_base_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    demanda_tienda_df: pd.DataFrame,
    anio: int,
) -> pd.DataFrame:
    """Cruza el horario planeado con ausentismo real y demanda real.

    Donde la gente presente < demanda requerida, extiende turnos de
    empleados disponibles ese día (presentes, sin llegar a su tope diario
    de 12h) con horas extra: primero al doble hasta el tope semanal
    vigente, luego al triple hasta el tope adicional; si aun así no
    alcanza, registra el faltante como subdotación (no fuerza cobertura
    imposible).

    Columnas: tienda_id, fecha, hora, rol, personas_presentes,
    personas_requeridas, horas_extra_doble, horas_extra_triple,
    horas_subdotacion.
    """
    fref = date(anio, 1, 1)
    tope_doble = reglas.regla_vigente("extra_tope_doble_semanal_horas", fref)
    tope_triple = reglas.regla_vigente("extra_tope_triple_semanal_horas", fref)
    tope_dia = reglas.regla_vigente("jornada_diaria_total_max_horas", fref)

    ausentes = set(zip(ausentismo_df.loc[ausentismo_df["ausente"], "empleado_id"],
                        ausentismo_df.loc[ausentismo_df["ausente"], "fecha"]))

    trabaja = horario_base_df[horario_base_df["turno"] != "descanso"].copy()

    # Presencia original por hora (antes de horas extra).
    presencia: dict[tuple, set[str]] = {}
    horas_dia_acum: dict[tuple, float] = {}
    extra_doble_acum: dict[str, float] = {}
    extra_triple_acum: dict[str, float] = {}
    presentes_ese_dia: dict[tuple, list[str]] = {}  # (tienda_id, rol, fecha) -> [empleado_id]

    for row in trabaja.itertuples(index=False):
        presente = (row.empleado_id, row.fecha) not in ausentes
        horas_dia_acum[(row.empleado_id, row.fecha)] = float(row.hora_fin - row.hora_inicio) if presente else 0.0
        if presente:
            presentes_ese_dia.setdefault((row.tienda_id, row.rol, row.fecha), []).append(row.empleado_id)
            for h in range(int(row.hora_inicio), math.ceil(row.hora_fin)):
                presencia.setdefault((row.tienda_id, row.rol, row.fecha, h), set()).add(row.empleado_id)
        extra_doble_acum.setdefault(row.empleado_id, 0.0)
        extra_triple_acum.setdefault(row.empleado_id, 0.0)

    demanda = demanda_tienda_df.sort_values(["fecha", "hora"]).copy()
    resultado: list[dict] = []
    ot_por_franja: dict[tuple, dict[str, int]] = {}

    for row in demanda.itertuples(index=False):
        clave = (row.tienda_id, row.rol, row.fecha, int(row.hora))
        presentes_originales = presencia.get(clave, set())
        n_presentes = len(presentes_originales)
        deficit = max(0, int(row.personas_requeridas) - n_presentes)
        n_doble = n_triple = 0

        candidatos = [e for e in presentes_ese_dia.get((row.tienda_id, row.rol, row.fecha), [])
                      if e not in presentes_originales]
        candidatos.sort(key=lambda e: (extra_triple_acum[e], extra_doble_acum[e]))

        while deficit > 0 and candidatos:
            emp = candidatos.pop(0)
            if horas_dia_acum.get((emp, row.fecha), 0.0) >= tope_dia:
                continue
            if extra_doble_acum[emp] < tope_doble:
                extra_doble_acum[emp] += 1
                n_doble += 1
            elif extra_triple_acum[emp] < tope_triple:
                extra_triple_acum[emp] += 1
                n_triple += 1
            else:
                continue  # este empleado ya agotó ambos topes semanales
            horas_dia_acum[(emp, row.fecha)] = horas_dia_acum.get((emp, row.fecha), 0.0) + 1
            deficit -= 1

        resultado.append({
            "tienda_id": row.tienda_id, "fecha": row.fecha, "hora": int(row.hora),
            "rol": row.rol,
            "personas_presentes": n_presentes + n_doble + n_triple,
            "personas_requeridas": int(row.personas_requeridas),
            "horas_extra_doble": n_doble, "horas_extra_triple": n_triple,
            "horas_subdotacion": deficit,
        })
    return pd.DataFrame(resultado)


def calcular_horario_base_tienda(
    tienda_id: str,
    anio: int,
    plantilla_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    demanda_tienda_df: pd.DataFrame,
    fecha_inicio: date | None = None,
) -> dict:
    """Orquesta el cálculo del horario base de UNA tienda para un año.

    Regresa un dict con las tablas intermedias (dotacion_planeada,
    cuadrillas, resultado_horas) y un resumen de costos:
    {horas_ordinarias_totales, horas_extra_doble_totales,
    horas_extra_triple_totales, horas_subdotacion_totales,
    costo_ordinario_mxn, costo_extra_mxn, costo_total_mxn}.

    El valor hora por empleado se calcula como
    salario_diario / (jornada_horas_semana_vigente / 6) — a menor jornada,
    mayor valor hora, para no bajar el salario semanal (Transitorio 7).
    Se agrega por rol usando el salario diario promedio de ese rol en la
    tienda (simplificación: no se rastrea el costo por empleado individual
    en el resumen agregado).
    """
    plantilla_tienda = plantilla_df.loc[plantilla_df["tienda_id"] == tienda_id]
    dotacion = dotacion_por_tipo_dia(demanda_tienda_df.loc[demanda_tienda_df["tienda_id"] == tienda_id])
    cuadrillas = armar_cuadrillas_rotativas(plantilla_tienda, anio, fecha_inicio=fecha_inicio)
    resultado_horas = aplicar_ausentismo_y_demanda_real(
        cuadrillas, ausentismo_df, demanda_tienda_df.loc[demanda_tienda_df["tienda_id"] == tienda_id], anio,
    )

    jornada_semanal = reglas.regla_vigente("jornada_ordinaria_semanal_horas", date(anio, 1, 1))
    valor_hora_por_rol = (plantilla_tienda.groupby("rol")["salario_diario_mxn"].mean()
                           / (jornada_semanal / 6))

    trabaja = cuadrillas[cuadrillas["turno"] != "descanso"].copy()
    trabaja["horas"] = trabaja["hora_fin"] - trabaja["hora_inicio"]
    horas_ordinarias_por_rol = trabaja.groupby("rol")["horas"].sum()

    horas_extra_doble_por_rol = resultado_horas.groupby("rol")["horas_extra_doble"].sum()
    horas_extra_triple_por_rol = resultado_horas.groupby("rol")["horas_extra_triple"].sum()

    costo_ordinario = sum(
        float(horas_ordinarias_por_rol.get(r, 0.0)) * float(valor_hora_por_rol.get(r, 0.0))
        for r in valor_hora_por_rol.index
    )
    mult_doble = reglas.regla_vigente("pago_extra_doble_multiplicador", date(anio, 1, 1))
    mult_triple = reglas.regla_vigente("pago_extra_triple_multiplicador", date(anio, 1, 1))
    costo_extra = sum(
        float(horas_extra_doble_por_rol.get(r, 0.0)) * float(valor_hora_por_rol.get(r, 0.0)) * mult_doble
        + float(horas_extra_triple_por_rol.get(r, 0.0)) * float(valor_hora_por_rol.get(r, 0.0)) * mult_triple
        for r in valor_hora_por_rol.index
    )

    return {
        "tienda_id": tienda_id,
        "dotacion_planeada": dotacion,
        "cuadrillas": cuadrillas,
        "resultado_horas": resultado_horas,
        "horas_ordinarias_totales": float(horas_ordinarias_por_rol.sum()),
        "horas_extra_doble_totales": float(resultado_horas["horas_extra_doble"].sum()),
        "horas_extra_triple_totales": float(resultado_horas["horas_extra_triple"].sum()),
        "horas_subdotacion_totales": float(resultado_horas["horas_subdotacion"].sum()),
        "costo_ordinario_mxn": round(costo_ordinario, 2),
        "costo_extra_mxn": round(costo_extra, 2),
        "costo_total_mxn": round(costo_ordinario + costo_extra, 2),
    }
