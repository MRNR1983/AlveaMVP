"""Optimizador de horario semanal por tienda con OR-Tools CP-SAT.

Arma el horario de UNA tienda (domingo a sábado) asignando a cada persona,
cada día, UNO de 4 turnos fijos (ver catalogo_turnos) o descanso,
minimizando el costo laboral, con las reglas legales de jornada40.reglas como restricciones
DURAS del modelo, y la cobertura de la demanda (jornada40.demanda_personal)
como restricción dura en franjas pico y suave (penalizada) fuera de pico.

SIMPLIFICACIONES DEL PMV (documentadas a propósito, no son bugs):
  - Todos los turnos del catálogo son de 8 h (= tope diario diurno, art.
    61), así que el tope diario se cumple por construcción. Turnos
    nocturnos/mixtos (7 / 7.5 h) quedan como TODO de Fase 2.
  - La clasificación ordinaria/extra-doble/extra-triple se hace a nivel
    SEMANAL por empleado (no día por día), acotada por
    extra_tope_doble_semanal_horas + extra_tope_triple_semanal_horas.
  - El descanso intrajornada de 30 min (art. 63) se modela como UN slot
    de 1 hora completo, FIJO a la mitad de cada turno y escalonado entre
    turnos (nunca coinciden), sin cobertura por día trabajado (aproximación:
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
    "DURACION_TURNO_H",
    "NOMBRES_TURNO",
    "catalogo_turnos",
    "turnos_a_horario",
    "construir_modelo",
    "resolver_tienda",
    "resolver_techo_teorico",
    "resolver_red",
]

_SCALE_CENTAVOS = 100
_PESO_DEFICIT_OFFPICO = 20000  # centavos "virtuales" (200 MXN) por hora de déficit fuera de pico:
                               # más caro que pagar a alguien, para que la tienda nunca abra vacía
_PESO_SOBRESTAFFING = 500      # centavos "virtuales" por hora de exceso sobre el margen
_MARGEN_SOBRESTAFFING = 1      # personas de más toleradas sin penalizar
_PESO_DEFICIT_PICO_RESPALDO = 200000  # solo cuando la cobertura pico dura es infactible


def _slots_dia(hora_apertura: int, hora_cierre: int) -> list[int]:
    return list(range(hora_apertura, hora_cierre))


# ---------------------------------------------------------------------------
# Catálogo fijo de turnos
# ---------------------------------------------------------------------------
# DECISIÓN DE PRODUCTO (24-sep-2026): el modelo YA NO decide hora por hora
# quién trabaja (eso producía decenas de "micro-turnos" y turnos partidos
# ilegibles para un gerente). Ahora cada tienda tiene un catálogo FIJO de
# 4 turnos de 8 h (horario y hora de descanso fijos, nadie los mueve) y lo
# único que decide el CP-SAT, día por día, es QUÉ PERSONA entra en QUÉ
# turno (o si descansa). Así un día se lee como "Apertura: 18 personas,
# Intermedio: 12, ..." -- exactamente como lo arma un gerente a mano.
#
# Los descansos (1 slot de 1 h, pagado, art. 63) están ESCALONADOS: cada
# turno descansa a la mitad de su jornada y como los 4 turnos arrancan a
# horas distintas, sus descansos nunca coinciden. (Bug real del primer
# intento: dos plantillas descansaban a la misma hora y esa hora quedaba
# sin nadie que la pudiera cubrir -> INFEASIBLE sin importar la plantilla.)

DURACION_TURNO_H = 8
NOMBRES_TURNO = ("Apertura", "Intermedio", "Refuerzo pico", "Cierre")


def catalogo_turnos(hora_apertura: int, hora_cierre: int) -> list[dict]:
    """Catálogo fijo de turnos de una tienda según su horario de atención.

    4 turnos de 8 h con arranques repartidos de forma pareja entre la
    apertura y (cierre - 8 h): el primero abre la tienda y el último la
    cierra. Descanso a la mitad de cada turno (inicio + 4 h). Si la tienda
    abre 8 h o menos, un solo turno cubre todo el día.

    Cada turno: {"turno", "inicio", "fin", "pausa", "pausas"} (horas enteras,
    fin exclusivo). "pausas" son las horas en que cada PERSONA puede tomar su
    descanso (4.ª, 5.ª o 6.ª hora del turno); el optimizador reparte a la
    gente entre ellas para que el turno nunca se vacíe de golpe en una hora
    pico. "pausa" es la opción central (la que se usa al mover a alguien a
    mano).
    """
    hora_apertura, hora_cierre = int(hora_apertura), int(hora_cierre)
    dur = min(DURACION_TURNO_H, hora_cierre - hora_apertura)
    if dur <= 0:
        return []
    holgura = hora_cierre - hora_apertura - dur
    if holgura <= 0:
        inicios = [hora_apertura]
    else:
        inicios = sorted({hora_apertura + round(k * holgura / 3) for k in range(4)})
    nombres = list(NOMBRES_TURNO) if len(inicios) == 4 else [
        NOMBRES_TURNO[0], *NOMBRES_TURNO[1:len(inicios) - 1], NOMBRES_TURNO[-1]
    ][:len(inicios)]
    return [
        {"turno": n, "inicio": i, "fin": i + dur, "pausa": i + dur // 2,
         "pausas": ([i + dur // 2 - 1, i + dur // 2, i + dur // 2 + 1] if dur >= 6 else [i + dur // 2])}
        for n, i in zip(nombres, inicios)
    ]


def construir_modelo(
    tienda_id: str,
    anio: int,
    plantilla_tienda_df: pd.DataFrame,
    demanda_tienda_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    modo: str = "operativo",
    fecha_inicio: date | None = None,
    pico_duro: bool = True,
) -> tuple[cp_model.CpModel, dict]:
    """Construye el modelo CP-SAT: asignación persona -> turno fijo, por día.

    ``modo="operativo"``: sobrestaffing y déficit fuera de pico penalizados.
    ``modo="techo"``: esos dos pesos a 0 (relajación teórica), mismas
    restricciones legales duras -- su óptimo nunca cuesta más que el
    operativo. ``pico_duro=False`` convierte la cobertura en pico en una
    penalización muy alta (se usa solo como respaldo si la versión dura
    es infactible, para no dejar al gerente sin horario).
    """
    fref = date(anio, 1, 1)
    dom_ref = fecha_inicio or reglas.semana_domingo_a_sabado(fref)[0]
    dias = [dom_ref + timedelta(days=i) for i in range(7)]

    tope_semanal = reglas.regla_vigente("jornada_ordinaria_semanal_horas", fref)
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
    # Ventana del catálogo = horas en que la tienda necesita a alguien
    # (incluye la ventana extendida de almacén antes de abrir/después de
    # cerrar). Fuera de ella la demanda es 0 y no tiene sentido poner turnos.
    _con_demanda = demanda_tienda_df.loc[demanda_tienda_df["personas_requeridas"] > 0, "hora"]
    if len(_con_demanda):
        turnos = catalogo_turnos(int(_con_demanda.min()), int(_con_demanda.max()) + 1)
    else:
        turnos = catalogo_turnos(min(horas_del_dia), max(horas_del_dia) + 1) if horas_del_dia else []
    t_idx = range(len(turnos))

    model = cp_model.CpModel()
    # (e, d, t, p) -> Bool: la persona e trabaja el turno t el día d y toma
    # su descanso a la hora p (una de turnos[t]["pausas"]).
    x: dict = {}
    for emp in empleados.itertuples(index=False):
        e = emp.empleado_id
        for d in dias:
            if (e, d) in ausentes:
                continue
            vars_dia = []
            for t in t_idx:
                for p in turnos[t]["pausas"]:
                    x[(e, d, t, p)] = model.NewBoolVar(f"x_{e}_{d}_{t}_{p}")
                    vars_dia.append(x[(e, d, t, p)])
            model.AddAtMostOne(vars_dia)

    horas_ordinarias: dict = {}
    horas_extra_doble: dict = {}
    horas_extra_triple: dict = {}
    for emp in empleados.itertuples(index=False):
        e = emp.empleado_id
        dias_trab = [v for (ee, _d, _t, _p), v in x.items() if ee == e]
        model.Add(sum(dias_trab) <= int(dias_trabajo_max))
        horas_semana = model.NewIntVar(0, jornada_semanal_cap, f"hs_{e}")
        model.Add(horas_semana == sum(
            (turnos[t]["fin"] - turnos[t]["inicio"]) * v
            for (ee, _d, t, _p), v in x.items() if ee == e
        ))
        horas_ordinarias[e] = model.NewIntVar(0, int(tope_semanal), f"ho_{e}")
        horas_extra_doble[e] = model.NewIntVar(0, int(tope_extra_doble), f"hed_{e}")
        horas_extra_triple[e] = model.NewIntVar(0, int(tope_extra_triple), f"het_{e}")
        model.Add(horas_semana == horas_ordinarias[e] + horas_extra_doble[e] + horas_extra_triple[e])

    # Qué turnos cubren (trabajando, no en pausa) cada hora.
    turnos_que_cubren = {
        h: [(t, p) for t in t_idx for p in turnos[t]["pausas"]
            if turnos[t]["inicio"] <= h < turnos[t]["fin"] and p != h]
        for h in horas_del_dia
    }
    empleados_por_rol = {rol: list(empleados.loc[empleados["rol"] == rol, "empleado_id"]) for rol in roles}

    cobertura: dict = {}
    deficit_vars: list = []
    deficit_pico_vars: list = []
    exceso_vars: list = []
    for d in dias:
        for h in horas_del_dia:
            for rol in roles:
                terms = [x[(e, d, t, p)] for e in empleados_por_rol[rol]
                         for (t, p) in turnos_que_cubren[h] if (e, d, t, p) in x]
                n_max = max(1, len(empleados_por_rol[rol]))
                cob_var = model.NewIntVar(0, n_max, f"cob_{d}_{h}_{rol}")
                model.Add(cob_var == (sum(terms) if terms else 0))
                cobertura[(d, h, rol)] = cob_var
                requerido = int(demanda.get((d, h, rol), 0))
                es_pico = bool(es_pico_map.get((d, h), False))
                if es_pico and pico_duro:
                    model.Add(cob_var >= requerido)
                else:
                    deficit = model.NewIntVar(0, max(requerido, 0), f"def_{d}_{h}_{rol}")
                    model.Add(deficit >= requerido - cob_var)
                    (deficit_pico_vars if es_pico else deficit_vars).append(deficit)
                exceso = model.NewIntVar(0, n_max, f"exc_{d}_{h}_{rol}")
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
    objetivo = (costo_payroll + peso_deficit * sum(deficit_vars)
                + _PESO_DEFICIT_PICO_RESPALDO * sum(deficit_pico_vars)
                + peso_exceso * sum(exceso_vars))
    model.Minimize(objetivo)

    variables = {
        "x": x, "turnos": turnos, "dias": dias, "horas_del_dia": horas_del_dia,
        "roles": roles, "horas_ordinarias": horas_ordinarias,
        "horas_extra_doble": horas_extra_doble, "horas_extra_triple": horas_extra_triple,
        "cobertura": cobertura, "deficit_vars": deficit_vars, "exceso_vars": exceso_vars,
        "valor_hora_cent": valor_hora_cent, "costo_payroll_expr": costo_payroll,
        "empleados": empleados, "demanda": demanda, "es_pico_map": es_pico_map,
        "tope_semanal": tope_semanal,
    }
    return model, variables


def _extraer_turnos(solver: cp_model.CpSolver, variables: dict) -> pd.DataFrame:
    """Una fila por persona y día trabajado: qué turno fijo le tocó."""
    turnos = variables["turnos"]
    filas = []
    for (e, d, t, p), var in variables["x"].items():
        if solver.Value(var):
            tt = turnos[t]
            filas.append({"empleado_id": e, "fecha": d, "turno": tt["turno"],
                          "hora_inicio": tt["inicio"], "hora_fin": tt["fin"], "hora_pausa": p})
    cols = ["empleado_id", "fecha", "turno", "hora_inicio", "hora_fin", "hora_pausa"]
    return pd.DataFrame(filas, columns=cols)


def turnos_a_horario(turnos_df: pd.DataFrame) -> pd.DataFrame:
    """Expande turnos (1 fila por persona-día) al formato hora por hora que
    usa el resto del pipeline (costos, calificación de ediciones, CSV):
    empleado_id, fecha, hora, trabajando, en_pausa, turno."""
    filas = []
    for r in turnos_df.itertuples(index=False):
        for h in range(int(r.hora_inicio), int(r.hora_fin)):
            filas.append({"empleado_id": r.empleado_id, "fecha": r.fecha, "hora": h,
                          "trabajando": True, "en_pausa": h == int(r.hora_pausa), "turno": r.turno})
    return pd.DataFrame(filas, columns=["empleado_id", "fecha", "hora", "trabajando", "en_pausa", "turno"])


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
    """Resuelve la asignación óptima (o factible) persona -> turno de UNA tienda.

    Primero intenta con la cobertura en hora pico como restricción DURA. Si
    eso es infactible (p. ej. mucho ausentismo esa semana), reintenta con
    la cobertura pico como penalización muy alta: así el gerente siempre
    recibe un horario, y ``horas_subdotacion_pico`` le dice cuántas horas
    pico quedaron cortas (``pico_relajado=True``).

    El límite de tiempo es un trade-off explícito calidad/velocidad; la
    brecha de optimalidad se reporta (0 % si terminó como OPTIMAL).
    """
    pico_relajado = False
    for pico_duro in (True, False):
        model, variables = construir_modelo(
            tienda_id, anio, plantilla_tienda_df, demanda_tienda_df, ausentismo_df,
            modo=modo, fecha_inicio=fecha_inicio, pico_duro=pico_duro,
        )
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = tiempo_limite_seg
        solver.parameters.num_search_workers = 4
        status = solver.Solve(model)
        status_nombre = solver.StatusName(status)
        if status_nombre in ("OPTIMAL", "FEASIBLE"):
            pico_relajado = not pico_duro
            break

    if status_nombre not in ("OPTIMAL", "FEASIBLE"):
        return {
            "tienda_id": tienda_id, "status": "INFEASIBLE",
            "mensaje": ("No se encontró horario factible con las reglas legales de jornada y "
                        "descansos, ni siquiera relajando la cobertura en pico."),
            "horario_df": pd.DataFrame(), "turnos_df": pd.DataFrame(),
            "catalogo_turnos": variables["turnos"], "costo_total_mxn": None,
            "brecha_optimalidad_pct": None, "horas_ordinarias": None,
            "horas_extra_doble": None, "horas_extra_triple": None,
            "horas_subdotacion_pico": None, "horas_sobrestaffing": None, "pico_relajado": None,
        }

    turnos_df = _extraer_turnos(solver, variables)
    horario_df = turnos_a_horario(turnos_df)
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
        "horario_df": horario_df, "turnos_df": turnos_df,
        "catalogo_turnos": variables["turnos"],
        "costo_total_mxn": round(costo_payroll_cent / _SCALE_CENTAVOS, 2),
        "brecha_optimalidad_pct": round(brecha, 3),
        "horas_ordinarias": horas_ord, "horas_extra_doble": horas_ed,
        "horas_extra_triple": horas_et,
        "horas_subdotacion_pico": horas_subdotacion_pico,
        "horas_sobrestaffing": horas_sobrestaffing,
        "pico_relajado": pico_relajado,
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
