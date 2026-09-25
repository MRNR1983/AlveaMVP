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
HORAS_EXTENSION = 2          # extensión opcional de un turno = tiempo extra (máx. 3 h/día, art. 66)
MAX_DIAS_EXTENDIDOS = 3      # "ni más de tres veces en una semana" (art. 66)
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
         "pausas": ([i + dur // 2 - 1, i + dur // 2, i + dur // 2 + 1] if dur >= 6 else [i + dur // 2]),
         # Variantes de horario: normal, o extendido HORAS_EXTENSION h (tiempo extra
         # legal, art. 66). El turno de cierre se extiende hacia antes (la tienda
         # cierra a su hora); los demás, hacia después. Solo si cabe en la ventana.
         "spans": [(i, i + dur)] + (
             [(i - HORAS_EXTENSION, i + dur)] if (n == NOMBRES_TURNO[-1] and i - HORAS_EXTENSION >= hora_apertura)
             else [(i, i + dur + HORAS_EXTENSION)] if (n != NOMBRES_TURNO[-1] and i + dur + HORAS_EXTENSION <= hora_cierre)
             else [])}
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
    # (e, d, t, k) -> Bool: la persona e trabaja el día d el turno t en su
    # variante de horario k (0 = normal, 1 = extendido con tiempo extra).
    # El DESCANSO no se decide por persona dentro del modelo (eso triplicaba
    # las variables y el solver no alcanzaba buenas soluciones en 10 s): se
    # decide CUÁNTAS personas de cada rol descansan a cada hora permitida del
    # turno (enteros pequeños), y _extraer_turnos reparte los nombres.
    x: dict = {}
    for emp in empleados.itertuples(index=False):
        e = emp.empleado_id
        for d in dias:
            if (e, d) in ausentes:
                continue
            vars_dia = []
            for t in t_idx:
                for k in range(len(turnos[t]["spans"])):
                    x[(e, d, t, k)] = model.NewBoolVar(f"x_{e}_{d}_{t}_{k}")
                    vars_dia.append(x[(e, d, t, k)])
            model.AddAtMostOne(vars_dia)

    horas_ordinarias: dict = {}
    horas_extra_doble: dict = {}
    horas_extra_triple: dict = {}
    x_por_emp: dict = {}
    for (e, d, t, k), v in x.items():
        x_por_emp.setdefault(e, []).append((t, k, v))
    for emp in empleados.itertuples(index=False):
        e = emp.empleado_id
        vs = x_por_emp.get(e, [])
        model.Add(sum(v for _t, k, v in vs if k > 0) <= MAX_DIAS_EXTENDIDOS)
        model.Add(sum(v for _t, _k, v in vs) <= int(dias_trabajo_max))
        horas_semana = model.NewIntVar(0, jornada_semanal_cap, f"hs_{e}")
        model.Add(horas_semana == sum(
            (turnos[t]["spans"][k][1] - turnos[t]["spans"][k][0]) * v for t, k, v in vs))
        horas_ordinarias[e] = model.NewIntVar(0, int(tope_semanal), f"ho_{e}")
        horas_extra_doble[e] = model.NewIntVar(0, int(tope_extra_doble), f"hed_{e}")
        horas_extra_triple[e] = model.NewIntVar(0, int(tope_extra_triple), f"het_{e}")
        model.Add(horas_semana == horas_ordinarias[e] + horas_extra_doble[e] + horas_extra_triple[e])
        # Orden legal: primero ordinarias, luego dobles, luego triples (no se
        # puede "elegir" pagar triple teniendo cupo al doble).
        model.AddMinEquality(horas_ordinarias[e], [horas_semana, int(tope_semanal)])
        resto = model.NewIntVar(0, jornada_semanal_cap, f"rs_{e}")
        model.Add(resto == horas_semana - horas_ordinarias[e])
        model.AddMinEquality(horas_extra_doble[e], [resto, int(tope_extra_doble)])

    empleados_por_rol = {rol: list(empleados.loc[empleados["rol"] == rol, "empleado_id"]) for rol in roles}

    # Personas por (día, turno, variante, rol) y cuántas descansan a cada hora.
    n_grupo: dict = {}
    pausas_grupo: dict = {}
    for d in dias:
        for t in t_idx:
            for k in range(len(turnos[t]["spans"])):
                for rol in roles:
                    vs = [x[(e, d, t, k)] for e in empleados_por_rol[rol] if (e, d, t, k) in x]
                    ub = len(vs)
                    n = model.NewIntVar(0, ub, f"n_{d}_{t}_{k}_{rol}")
                    model.Add(n == (sum(vs) if vs else 0))
                    n_grupo[(d, t, k, rol)] = n
                    cs = {p: model.NewIntVar(0, ub, f"c_{d}_{t}_{k}_{rol}_{p}") for p in turnos[t]["pausas"]}
                    model.Add(sum(cs.values()) == n)
                    pausas_grupo[(d, t, k, rol)] = cs

    cobertura: dict = {}
    deficit_vars: list = []
    deficit_pico_vars: list = []
    exceso_vars: list = []
    for d in dias:
        for h in horas_del_dia:
            for rol in roles:
                terms = []
                for t in t_idx:
                    for k, (ini, fin) in enumerate(turnos[t]["spans"]):
                        if ini <= h < fin:
                            terms.append(n_grupo[(d, t, k, rol)])
                            if h in pausas_grupo[(d, t, k, rol)]:
                                terms.append(-pausas_grupo[(d, t, k, rol)][h])
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
        "x": x, "n_grupo": n_grupo, "pausas_grupo": pausas_grupo, "turnos": turnos, "dias": dias, "horas_del_dia": horas_del_dia,
        "roles": roles, "horas_ordinarias": horas_ordinarias,
        "horas_extra_doble": horas_extra_doble, "horas_extra_triple": horas_extra_triple,
        "cobertura": cobertura, "deficit_vars": deficit_vars, "exceso_vars": exceso_vars,
        "valor_hora_cent": valor_hora_cent, "costo_payroll_expr": costo_payroll,
        "empleados": empleados, "demanda": demanda, "es_pico_map": es_pico_map,
        "tope_semanal": tope_semanal,
    }
    return model, variables


def _extraer_turnos(solver: cp_model.CpSolver, variables: dict) -> pd.DataFrame:
    """Una fila por persona y día trabajado: qué turno fijo le tocó, su horario
    (normal o extendido) y a qué hora descansa. Los descansos se reparten entre
    las personas de cada grupo (día, turno, variante, rol) según los conteos
    que decidió el modelo."""
    turnos = variables["turnos"]
    rol_de = dict(zip(variables["empleados"]["empleado_id"], variables["empleados"]["rol"]))
    grupos: dict = {}
    for (e, d, t, k), var in variables["x"].items():
        if solver.Value(var):
            grupos.setdefault((d, t, k, rol_de[e]), []).append(e)
    filas = []
    for (d, t, k, rol), gente in grupos.items():
        tt = turnos[t]
        ini, fin = tt["spans"][k]
        cola = []
        for p, c in sorted(variables["pausas_grupo"][(d, t, k, rol)].items()):
            cola += [p] * int(solver.Value(c))
        cola += [tt["pausa"]] * max(0, len(gente) - len(cola))
        for e, p in zip(sorted(gente), cola):
            filas.append({"empleado_id": e, "fecha": d, "turno": tt["turno"],
                          "hora_inicio": ini, "hora_fin": fin, "hora_pausa": p})
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


def _pistas_agregadas(model: cp_model.CpModel, v: dict, tope_semanal: float, dias_max: int,
                      tiempo: float, pico_duro: bool) -> None:
    """Resuelve una versión AGREGADA por rol (cuántas personas de cada rol en
    cada turno/día, sin nombres) y la pasa como pista (AddHint) al modelo por
    persona. El agregado es chico y se resuelve en segundos; sin pista, el
    solver pierde tiempo entre millones de soluciones equivalentes (personas
    del mismo rol son intercambiables) y en 10 s entregaba horarios con horas
    extra triples innecesarias."""
    turnos, dias, roles, horas = v["turnos"], v["dias"], v["roles"], v["horas_del_dia"]
    emp = v["empleados"]
    x = v["x"]
    rol_de = dict(zip(emp["empleado_id"], emp["rol"]))
    disp = {}
    for (e, d, t, k) in x:
        disp.setdefault((d, rol_de[e]), set()).add(e)
    plantilla = emp.groupby("rol").size().to_dict()
    sal = emp.groupby("rol")["salario_diario_mxn"].mean().to_dict()
    m = cp_model.CpModel()
    n, c = {}, {}
    for d in dias:
        for rol in roles:
            ub = len(disp.get((d, rol), ()))
            dia_vars = []
            for ti, t in enumerate(turnos):
                for k in range(len(t["spans"])):
                    n[(d, ti, k, rol)] = m.NewIntVar(0, ub, "")
                    dia_vars.append(n[(d, ti, k, rol)])
                    cs = {p: m.NewIntVar(0, ub, "") for p in t["pausas"]}
                    m.Add(sum(cs.values()) == n[(d, ti, k, rol)])
                    c[(d, ti, k, rol)] = cs
            m.Add(sum(dia_vars) <= ub)
    obj = []
    for rol in roles:
        H = plantilla.get(rol, 0)
        allv = [(n[(d, ti, k, rol)], t["spans"][k][1] - t["spans"][k][0], k)
                for d in dias for ti, t in enumerate(turnos) for k in range(len(t["spans"]))]
        m.Add(sum(a for a, _, _ in allv) <= dias_max * H)
        m.Add(sum(a for a, _, k in allv if k > 0) <= MAX_DIAS_EXTENDIDOS * H)
        horas_rol = sum(a * h for a, h, _ in allv)
        extra = m.NewIntVar(0, 10**6, "")
        m.Add(extra >= horas_rol - int(tope_semanal) * H)
        vh = int(round(sal.get(rol, 300) / (tope_semanal / 6) * _SCALE_CENTAVOS))
        obj.append(horas_rol * vh + extra * vh)
    for d in dias:
        for h in horas:
            for rol in roles:
                terms = []
                for ti, t in enumerate(turnos):
                    for k, (ini, fin) in enumerate(t["spans"]):
                        if ini <= h < fin:
                            terms.append(n[(d, ti, k, rol)])
                            if h in c[(d, ti, k, rol)]:
                                terms.append(-c[(d, ti, k, rol)][h])
                cob = sum(terms) if terms else 0
                req = int(v["demanda"].get((d, h, rol), 0))
                pico = bool(v["es_pico_map"].get((d, h), False))
                if pico and pico_duro:
                    m.Add(cob >= req)
                else:
                    df = m.NewIntVar(0, max(req, 0), "")
                    m.Add(df >= req - cob)
                    obj.append(df * (_PESO_DEFICIT_PICO_RESPALDO if pico else _PESO_DEFICIT_OFFPICO))
    m.Minimize(sum(obj))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = tiempo
    s.parameters.num_search_workers = 4
    if s.Solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return
    # Pistas para conteos y pausas
    for key, var in v["n_grupo"].items():
        model.AddHint(var, s.Value(n[key]))
    for key, cs in v["pausas_grupo"].items():
        for p, var in cs.items():
            model.AddHint(var, s.Value(c[key][p]))
    # Pista por persona: reparte cada conteo entre quienes tienen menos días asignados.
    dias_de = {e: 0 for e in emp["empleado_id"]}
    ext_de = {e: 0 for e in emp["empleado_id"]}
    asignado = set()
    for d in dias:
        for rol in roles:
            libres = sorted(disp.get((d, rol), ()), key=lambda e: (dias_de[e], e))
            for ti, t in enumerate(turnos):
                for k in range(len(t["spans"])):
                    for _ in range(s.Value(n[(d, ti, k, rol)])):
                        cand = [e for e in libres if dias_de[e] < dias_max and (k == 0 or ext_de[e] < MAX_DIAS_EXTENDIDOS)]
                        if not cand:
                            break
                        e = cand[0]
                        libres.remove(e)
                        dias_de[e] += 1
                        ext_de[e] += (k > 0)
                        asignado.add((e, d, ti, k))
    for key, var in x.items():
        model.AddHint(var, 1 if key in asignado else 0)


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
        solver.parameters.linearization_level = 2
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
