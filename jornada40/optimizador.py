"""Optimizador de horario semanal por tienda con OR-Tools CP-SAT.

Arma el horario de UNA tienda (domingo a sábado) minimizando el costo
laboral, con las reglas legales de jornada40.reglas como restricciones
DURAS del modelo, y la cobertura de la demanda (jornada40.demanda_personal)
como restricción dura en franjas pico y suave (penalizada) fuera de pico.

SIMPLIFICACIONES DEL PMV (documentadas a propósito, no son bugs):
  - La jornada diaria por tipo (diurna/nocturna/mixta, art. 61) se colapsa
    a un único tope diario ORDINARIO genérico (se usa el valor "diurna" de
    reglas.MAPA_JORNADA_DIARIA), más el tope diario TOTAL duro de 12h
    (ordinaria + extra, art. 68). Distinguir night/mixed shifts por
    empleado queda como TODO de Fase 2 — reglas.py sí expone las tres
    reglas por separado (MAPA_JORNADA_DIARIA), este módulo solo usa la
    diurna como aproximación del PMV.
  - La clasificación ordinaria/extra-doble/extra-triple se hace a nivel
    SEMANAL por empleado (no día por día), acotada por
    extra_tope_doble_semanal_horas + extra_tope_triple_semanal_horas.
  - El descanso intrajornada de 30 min (art. 63) se modela como UN slot
    de 1 hora completo sin cobertura por día trabajado (aproximación:
    los slots son de 1h, no hay resolución de media hora), pagado
    (cuenta como horas trabajadas, solo resta de la cobertura).
  - El máximo de 6 días trabajados antes de un descanso (art. 69) se
    aproxima como "máximo 6 días trabajados en la semana" (horizonte de
    una semana, sin encadenar con la semana anterior/siguiente).

Costos: se escalan a centavos (enteros) porque CP-SAT requiere
coeficientes enteros en la función objetivo.

Dependencias: jornada40.reglas, ortools (cp_model), pandas.
"""
from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta

import pandas as pd
from ortools.sat.python import cp_model

from jornada40 import reglas

__all__ = [
    "construir_modelo",
    "resolver_tienda",
    "resolver_techo_teorico",
    "resolver_red",
]

_SCALE_CENTAVOS = 100
_PESO_DEFICIT_OFFPICO = 5000   # centavos "virtuales" por hora de déficit fuera de pico
_PESO_SOBRESTAFFING = 500      # centavos "virtuales" por hora de exceso sobre el margen
_MARGEN_SOBRESTAFFING = 1      # personas de más toleradas sin penalizar


def _slots_dia(hora_apertura: int, hora_cierre: int) -> list[int]:
    return list(range(hora_apertura, hora_cierre))


def construir_modelo(
    tienda_id: str,
    anio: int,
    plantilla_tienda_df: pd.DataFrame,
    demanda_tienda_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    modo: str = "operativo",
    fecha_inicio: date | None = None,
) -> tuple[cp_model.CpModel, dict]:
    """Construye el modelo CP-SAT del horario semanal de una tienda.

    ``modo="operativo"``: sobrestaffing y déficit fuera de pico penalizados
    (restricciones suaves reales). ``modo="techo"``: esos dos pesos se
    ponen a 0 (relajación teórica: el costo reportado queda libre de
    penalización por acomodo poco realista), manteniendo intactas TODAS
    las restricciones legales duras y la cobertura dura en pico — por
    construcción, el óptimo de "techo" nunca puede costar más que el de
    "operativo" (ver docstring de resolver_techo_teorico).
    """
    fref = date(anio, 1, 1)
    dom_ref = fecha_inicio or reglas.semana_domingo_a_sabado(fref)[0]
    dias = [dom_ref + timedelta(days=i) for i in range(7)]

    tope_semanal = reglas.regla_vigente("jornada_ordinaria_semanal_horas", fref)
    tope_diario_ordinario = reglas.regla_vigente(reglas.MAPA_JORNADA_DIARIA["diurna"], fref)
    tope_diario_total = reglas.regla_vigente("jornada_diaria_total_max_horas", fref)
    tope_extra_doble = reglas.regla_vigente("extra_tope_doble_semanal_horas", fref)
    tope_extra_triple = reglas.regla_vigente("extra_tope_triple_semanal_horas", fref)
    dias_trabajo_max = reglas.regla_vigente("dias_trabajo_maximo_antes_descanso", fref)
    mult_doble = reglas.regla_vigente("pago_extra_doble_multiplicador", fref)
    mult_triple = reglas.regla_vigente("pago_extra_triple_multiplicador", fref)
    jornada_semanal_cap = int(math.floor(tope_semanal + tope_extra_doble + tope_extra_triple))

    empleados = plantilla_tienda_df.reset_index(drop=True)
    if not ausentismo_df.empty and "ausente" in ausentismo_df.columns:
        ausentes_df = ausentismo_df.loc[ausentismo_df["ausente"]]
        ausentes = set(zip(ausentes_df["empleado_id"], ausentes_df["fecha"]))
    else:
        ausentes = set()

    demanda = demanda_tienda_df.set_index(["fecha", "hora", "rol"])["personas_requeridas"].to_dict()
    es_pico_map = (demanda_tienda_df.set_index(["fecha", "hora"])["es_pico"].to_dict()
                   if "es_pico" in demanda_tienda_df.columns else {})

    horas_del_dia = sorted(demanda_tienda_df["hora"].unique().tolist())
    roles = sorted(plantilla_tienda_df["rol"].unique().tolist())

    model = cp_model.CpModel()
    work: dict = {}
    pausa: dict = {}
    for emp in empleados.itertuples(index=False):
        for d in dias:
            if (emp.empleado_id, d) in ausentes:
                for h in horas_del_dia:
                    work[(emp.empleado_id, d, h)] = model.NewConstant(0)
                    pausa[(emp.empleado_id, d, h)] = model.NewConstant(0)
                continue
            for h in horas_del_dia:
                work[(emp.empleado_id, d, h)] = model.NewBoolVar(f"w_{emp.empleado_id}_{d}_{h}")
                pausa[(emp.empleado_id, d, h)] = model.NewBoolVar(f"p_{emp.empleado_id}_{d}_{h}")
                model.Add(pausa[(emp.empleado_id, d, h)] <= work[(emp.empleado_id, d, h)])

    trabaja_dia: dict = {}
    horas_dia: dict = {}
    horas_ordinarias: dict = {}
    horas_extra_doble: dict = {}
    horas_extra_triple: dict = {}

    for emp in empleados.itertuples(index=False):
        e = emp.empleado_id
        for d in dias:
            horas_dia[(e, d)] = model.NewIntVar(0, len(horas_del_dia), f"hd_{e}_{d}")
            model.Add(horas_dia[(e, d)] == sum(work[(e, d, h)] for h in horas_del_dia))
            trabaja_dia[(e, d)] = model.NewBoolVar(f"td_{e}_{d}")
            model.Add(horas_dia[(e, d)] >= 1).OnlyEnforceIf(trabaja_dia[(e, d)])
            model.Add(horas_dia[(e, d)] == 0).OnlyEnforceIf(trabaja_dia[(e, d)].Not())
            model.Add(horas_dia[(e, d)] <= int(tope_diario_total))
            # descanso intrajornada: exactamente 1 slot de pausa si trabaja ese día.
            model.Add(sum(pausa[(e, d, h)] for h in horas_del_dia) == trabaja_dia[(e, d)])

        model.Add(sum(trabaja_dia[(e, d)] for d in dias) <= int(dias_trabajo_max))

        horas_semana = model.NewIntVar(0, jornada_semanal_cap, f"hs_{e}")
        model.Add(horas_semana == sum(horas_dia[(e, d)] for d in dias))

        horas_ordinarias[e] = model.NewIntVar(0, int(tope_semanal), f"ho_{e}")
        horas_extra_doble[e] = model.NewIntVar(0, int(tope_extra_doble), f"hed_{e}")
        horas_extra_triple[e] = model.NewIntVar(0, int(tope_extra_triple), f"het_{e}")
        model.Add(horas_semana == horas_ordinarias[e] + horas_extra_doble[e] + horas_extra_triple[e])
        # Prioriza llenar ordinaria antes de extra-doble, y extra-doble antes
        # de extra-triple (evita que el solver "invente" extra innecesaria):
        model.Add(horas_ordinarias[e] == int(tope_semanal)).OnlyEnforceIf(
            _hs_mayor_igual(model, horas_semana, int(tope_semanal)))

    cobertura: dict = {}
    deficit_vars: list = []
    exceso_vars: list = []
    for d in dias:
        for h in horas_del_dia:
            for rol in roles:
                empleados_rol = [e for e in empleados.loc[empleados["rol"] == rol, "empleado_id"]]
                cobertura_expr = sum(
                    work[(e, d, h)] - pausa[(e, d, h)] for e in empleados_rol
                ) if empleados_rol else 0
                requerido = int(demanda.get((d, h, rol), 0))
                es_pico = bool(es_pico_map.get((d, h), False))

                cob_var = model.NewIntVar(0, max(1, len(empleados_rol)), f"cob_{d}_{h}_{rol}")
                model.Add(cob_var == cobertura_expr)
                cobertura[(d, h, rol)] = cob_var

                if es_pico:
                    model.Add(cob_var >= requerido)
                else:
                    deficit = model.NewIntVar(0, requerido, f"def_{d}_{h}_{rol}")
                    model.Add(deficit >= requerido - cob_var)
                    deficit_vars.append(deficit)

                exceso = model.NewIntVar(0, max(1, len(empleados_rol)), f"exc_{d}_{h}_{rol}")
                model.Add(exceso >= cob_var - requerido - _MARGEN_SOBRESTAFFING)
                exceso_vars.append(exceso)

    valor_hora_cent = {
        emp.empleado_id: int(round((emp.salario_diario_mxn / (tope_semanal / 6)) * _SCALE_CENTAVOS))
        for emp in empleados.itertuples(index=False)
    }
    costo_payroll = sum(
        horas_ordinarias[e] * valor_hora_cent[e]
        + horas_extra_doble[e] * valor_hora_cent[e] * int(mult_doble)
        + horas_extra_triple[e] * valor_hora_cent[e] * int(mult_triple)
        for e in valor_hora_cent
    )

    peso_deficit = 0 if modo == "techo" else _PESO_DEFICIT_OFFPICO
    peso_exceso = 0 if modo == "techo" else _PESO_SOBRESTAFFING
    objetivo = costo_payroll + peso_deficit * sum(deficit_vars) + peso_exceso * sum(exceso_vars)
    model.Minimize(objetivo)

    variables = {
        "work": work, "pausa": pausa, "dias": dias, "horas_del_dia": horas_del_dia,
        "roles": roles, "horas_ordinarias": horas_ordinarias,
        "horas_extra_doble": horas_extra_doble, "horas_extra_triple": horas_extra_triple,
        "cobertura": cobertura, "deficit_vars": deficit_vars, "exceso_vars": exceso_vars,
        "valor_hora_cent": valor_hora_cent, "costo_payroll_expr": costo_payroll,
        "empleados": empleados, "demanda": demanda, "es_pico_map": es_pico_map,
        "tope_semanal": tope_semanal,
    }
    return model, variables


def _hs_mayor_igual(model: cp_model.CpModel, var: cp_model.IntVar, umbral: int) -> cp_model.IntVar:
    """Bool auxiliar: True si ``var >= umbral`` (para forzar ordinaria=tope)."""
    b = model.NewBoolVar(f"ge_{var.Name()}_{umbral}")
    model.Add(var >= umbral).OnlyEnforceIf(b)
    model.Add(var < umbral).OnlyEnforceIf(b.Not())
    return b


def _extraer_horario(solver: cp_model.CpSolver, variables: dict) -> pd.DataFrame:
    filas = []
    for (e, d, h), var in variables["work"].items():
        trabaja = bool(solver.Value(var))
        if trabaja:
            en_pausa = bool(solver.Value(variables["pausa"][(e, d, h)]))
            filas.append({"empleado_id": e, "fecha": d, "hora": h,
                          "trabajando": True, "en_pausa": en_pausa})
    return pd.DataFrame(filas)


def resolver_tienda(
    tienda_id: str,
    anio: int,
    plantilla_tienda_df: pd.DataFrame,
    demanda_tienda_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    modo: str = "operativo",
    tiempo_limite_seg: float = 60.0,
    fecha_inicio: date | None = None,
) -> dict:
    """Resuelve el horario óptimo (o factible) de UNA tienda.

    El límite de tiempo (``tiempo_limite_seg``) es un trade-off explícito
    entre calidad de solución y viabilidad de correr 50 tiendas en
    paralelo: con más tiempo, ``brecha_optimalidad`` baja. Si preguntan en
    la demo "¿es óptimo de verdad?", la respuesta honesta es: es la mejor
    solución encontrada dentro del tiempo límite, con una brecha reportada
    explícitamente (0 % si terminó como OPTIMAL antes del límite).
    """
    model, variables = construir_modelo(
        tienda_id, anio, plantilla_tienda_df, demanda_tienda_df, ausentismo_df,
        modo=modo, fecha_inicio=fecha_inicio,
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_limite_seg
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    status_nombre = solver.StatusName(status)
    if status_nombre not in ("OPTIMAL", "FEASIBLE"):
        return {
            "tienda_id": tienda_id, "status": "INFEASIBLE",
            "mensaje": ("No se encontró horario factible: probablemente la demanda "
                        "pico excede la capacidad de la plantilla dada las restricciones "
                        "legales de jornada y descansos."),
            "horario_df": pd.DataFrame(), "costo_total_mxn": None,
            "brecha_optimalidad_pct": None, "horas_ordinarias": None,
            "horas_extra_doble": None, "horas_extra_triple": None,
            "horas_subdotacion_pico": None, "horas_sobrestaffing": None,
        }

    horario_df = _extraer_horario(solver, variables)
    horas_ord = sum(solver.Value(v) for v in variables["horas_ordinarias"].values())
    horas_ed = sum(solver.Value(v) for v in variables["horas_extra_doble"].values())
    horas_et = sum(solver.Value(v) for v in variables["horas_extra_triple"].values())
    costo_payroll_cent = solver.Value(variables["costo_payroll_expr"])

    horas_subdotacion_pico = 0
    for (d, h, rol), cob_var in variables["cobertura"].items():
        if variables["es_pico_map"].get((d, h), False):
            req = int(variables["demanda"].get((d, h, rol), 0))
            horas_subdotacion_pico += max(0, req - solver.Value(cob_var))
    horas_sobrestaffing = sum(solver.Value(v) for v in variables["exceso_vars"])

    best_bound = solver.BestObjectiveBound()
    obj_val = solver.ObjectiveValue()
    brecha = (abs(obj_val - best_bound) / abs(obj_val) * 100) if obj_val else 0.0

    return {
        "tienda_id": tienda_id, "status": status_nombre,
        "horario_df": horario_df,
        "costo_total_mxn": round(costo_payroll_cent / _SCALE_CENTAVOS, 2),
        "brecha_optimalidad_pct": round(brecha, 3),
        "horas_ordinarias": horas_ord, "horas_extra_doble": horas_ed,
        "horas_extra_triple": horas_et,
        "horas_subdotacion_pico": horas_subdotacion_pico,
        "horas_sobrestaffing": horas_sobrestaffing,
    }


def resolver_techo_teorico(
    tienda_id: str,
    anio: int,
    plantilla_tienda_df: pd.DataFrame,
    demanda_tienda_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    tiempo_limite_seg: float = 60.0,
    fecha_inicio: date | None = None,
) -> dict:
    """Costo mínimo teórico: solo restricciones legales duras + pico duro.

    Es una relajación de resolver_tienda (mismas restricciones duras,
    penalizaciones de sobrestaffing y déficit fuera de pico puestas a 0),
    así que su costo_total_mxn nunca puede ser mayor al de
    resolver_tienda con el mismo modo="operativo" (ver docstring de
    construir_modelo para la demostración).
    """
    return resolver_tienda(
        tienda_id, anio, plantilla_tienda_df, demanda_tienda_df, ausentismo_df,
        modo="techo", tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=fecha_inicio,
    )


def _worker_resolver(args: tuple) -> dict:
    (tienda_id, anio, plantilla_df, demanda_df, ausentismo_df, modo,
     tiempo_limite_seg, fecha_inicio) = args
    plantilla_tienda = plantilla_df.loc[plantilla_df["tienda_id"] == tienda_id]
    demanda_tienda = demanda_df.loc[demanda_df["tienda_id"] == tienda_id]
    return resolver_tienda(tienda_id, anio, plantilla_tienda, demanda_tienda, ausentismo_df,
                            modo=modo, tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=fecha_inicio)


def resolver_red(
    tiendas_ids: list[str],
    anio: int,
    plantilla_df: pd.DataFrame,
    demanda_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    modo: str = "operativo",
    tiempo_limite_seg: float = 60.0,
    fecha_inicio: date | None = None,
    max_workers: int = 8,
) -> dict[str, dict]:
    """Resuelve varias tiendas EN PARALELO (cada una es un problema aparte).

    Usa ProcessPoolExecutor (no hilos: CP-SAT no libera bien el GIL).
    Regresa {tienda_id: resultado}; revisa cuántas terminaron OPTIMAL vs
    FEASIBLE vs INFEASIBLE contando el campo "status" del resultado.
    """
    args = [(tid, anio, plantilla_df, demanda_df, ausentismo_df, modo,
             tiempo_limite_seg, fecha_inicio) for tid in tiendas_ids]
    if max_workers <= 1 or len(tiendas_ids) <= 1:
        resultados = [_worker_resolver(a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            resultados = list(ex.map(_worker_resolver, args))
    return {r["tienda_id"]: r for r in resultados}
