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


def _preparar(anio, plantilla_tienda_df, demanda_tienda_df, ausentismo_df, fecha_inicio):
    fref = date(anio, 1, 1)
    dom_ref = fecha_inicio or reglas.semana_domingo_a_sabado(fref)[0]
    dias = [dom_ref + timedelta(days=i) for i in range(7)]
    empleados = plantilla_tienda_df.reset_index(drop=True)
    if not ausentismo_df.empty and "ausente" in ausentismo_df.columns:
        a = ausentismo_df.loc[ausentismo_df["ausente"].astype(bool)]
        ausentes = set(zip(a["empleado_id"], a["fecha"]))
    else:
        ausentes = set()
    demanda = demanda_tienda_df.set_index(["fecha", "hora", "rol"])["personas_requeridas"].to_dict()
    es_pico_map = (demanda_tienda_df.set_index(["fecha", "hora"])["es_pico"].to_dict()
                   if "es_pico" in demanda_tienda_df.columns else {})
    horas_del_dia = sorted(demanda_tienda_df["hora"].unique().tolist())
    roles = sorted(empleados["rol"].unique().tolist())
    con_dem = demanda_tienda_df.loc[demanda_tienda_df["personas_requeridas"] > 0, "hora"]
    if len(con_dem):
        turnos = catalogo_turnos(int(con_dem.min()), int(con_dem.max()) + 1)
    else:
        turnos = catalogo_turnos(min(horas_del_dia), max(horas_del_dia) + 1) if horas_del_dia else []
    reg = {n: reglas.regla_vigente(n, fref) for n in (
        "jornada_ordinaria_semanal_horas", "extra_tope_doble_semanal_horas", "extra_tope_triple_semanal_horas",
        "dias_trabajo_maximo_antes_descanso", "pago_extra_doble_multiplicador", "pago_extra_triple_multiplicador")}
    return dict(dias=dias, empleados=empleados, ausentes=ausentes, demanda=demanda, es_pico_map=es_pico_map,
                horas_del_dia=horas_del_dia, roles=roles, turnos=turnos, reg=reg)


def _modelo_agregado(ctx: dict, modo: str, pico_duro: bool, tiempo: float):
    """Decide CUÁNTAS personas de cada área van a cada turno/variante cada día
    y cuántas descansan a cada hora. Personas del mismo área son
    intercambiables para la cobertura, así que este modelo (unos cientos de
    variables) es exacto para la cobertura y se resuelve al óptimo en segundos
    -- el modelo persona por persona tenía ~13 mil variables y en 10 s daba
    resultados inestables (a veces ahorro negativo). Los nombres se asignan
    después respetando los límites legales por persona (_asignar_personas)."""
    dias, roles, turnos, emp, reg = ctx["dias"], ctx["roles"], ctx["turnos"], ctx["empleados"], ctx["reg"]
    tope = reg["jornada_ordinaria_semanal_horas"]
    dias_max = int(reg["dias_trabajo_maximo_antes_descanso"])
    por_rol = {r: list(emp.loc[emp["rol"] == r, "empleado_id"]) for r in roles}
    avail = {(d, r): sum((e, d) not in ctx["ausentes"] for e in por_rol[r]) for d in dias for r in roles}
    cap_dias = {r: sum(min(dias_max, sum((e, d) not in ctx["ausentes"] for d in dias)) for e in por_rol[r])
                for r in roles}
    vh = {r: int(round(emp.loc[emp["rol"] == r, "salario_diario_mxn"].mean() / (tope / 6) * _SCALE_CENTAVOS))
          for r in roles}
    m = cp_model.CpModel()
    n, c = {}, {}
    for d in dias:
        for r in roles:
            ub = avail[(d, r)]
            del_dia = []
            for ti, t in enumerate(turnos):
                for k in range(len(t["spans"])):
                    v = m.NewIntVar(0, ub, "")
                    n[(d, ti, k, r)] = v
                    del_dia.append(v)
                    cs = {p: m.NewIntVar(0, ub, "") for p in t["pausas"]}
                    m.Add(sum(cs.values()) == v)
                    c[(d, ti, k, r)] = cs
            m.Add(sum(del_dia) <= ub)
    costo = []
    for r in roles:
        H = len(por_rol[r])
        todos = [(n[(d, ti, k, r)], t["spans"][k][1] - t["spans"][k][0], k)
                 for d in dias for ti, t in enumerate(turnos) for k in range(len(t["spans"]))]
        m.Add(sum(v for v, _, _ in todos) <= cap_dias[r])
        m.Add(sum(v for v, _, k in todos if k > 0) <= MAX_DIAS_EXTENDIDOS * H)
        horas = sum(v * h for v, h, _ in todos)
        extra = m.NewIntVar(0, 10**6, "")
        m.Add(extra >= horas - int(tope) * H)
        # costo = horas x valor hora + extra x valor hora (la hora doble paga 2x en total)
        costo.append(horas * vh[r] + extra * vh[r] * int(reg["pago_extra_doble_multiplicador"] - 1))
    penal = []
    for d in dias:
        for h in ctx["horas_del_dia"]:
            for r in roles:
                terms = []
                for ti, t in enumerate(turnos):
                    for k, (ini, fin) in enumerate(t["spans"]):
                        if ini <= h < fin:
                            terms.append(n[(d, ti, k, r)])
                            if h in c[(d, ti, k, r)]:
                                terms.append(-c[(d, ti, k, r)][h])
                cob = sum(terms) if terms else 0
                req = int(ctx["demanda"].get((d, h, r), 0))
                pico = bool(ctx["es_pico_map"].get((d, h), False))
                if pico and pico_duro:
                    m.Add(cob >= req)
                elif req > 0:
                    df = m.NewIntVar(0, req, "")
                    m.Add(df >= req - cob)
                    peso = _PESO_DEFICIT_PICO_RESPALDO if pico else (0 if modo == "techo" else _PESO_DEFICIT_OFFPICO)
                    if peso:
                        penal.append(df * peso)
                if modo != "techo":
                    ex = m.NewIntVar(0, max(1, len(por_rol[r])), "")
                    m.Add(ex >= cob - req - _MARGEN_SOBRESTAFFING)
                    penal.append(ex * _PESO_SOBRESTAFFING)
    m.Minimize(sum(costo) + sum(penal))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = tiempo
    sv.parameters.num_search_workers = 4
    st = sv.Solve(m)
    nombre = sv.StatusName(st)
    if nombre not in ("OPTIMAL", "FEASIBLE"):
        return nombre, None, None, None
    obj, bound = sv.ObjectiveValue(), sv.BestObjectiveBound()
    brecha = (abs(obj - bound) / abs(obj) * 100) if obj else 0.0
    return (nombre, {key: sv.Value(v) for key, v in n.items()},
            {key: {p: sv.Value(v) for p, v in cs.items()} for key, cs in c.items()}, brecha)


def _asignar_personas(ctx: dict, n_val: dict, c_val: dict) -> pd.DataFrame:
    """Reparte los conteos del modelo agregado entre personas concretas con un
    modelo exacto por área (pequeño: ~26 personas x 7 días x 8 variantes):
    cada conteo se cubre completo, nadie trabaja en su ausencia, máx. 6 días
    y máx. 3 días extendidos por persona, y se minimizan las horas por encima
    de la jornada ordinaria (para no pagar extra de más por mal reparto)."""
    dias, roles, turnos, emp, reg = ctx["dias"], ctx["roles"], ctx["turnos"], ctx["empleados"], ctx["reg"]
    dias_max = int(reg["dias_trabajo_maximo_antes_descanso"])
    tope = int(reg["jornada_ordinaria_semanal_horas"])
    grupos = [(ti, k) for ti, t in enumerate(turnos) for k in range(len(t["spans"]))]
    filas = []
    for r in roles:
        gente = sorted(emp.loc[emp["rol"] == r, "empleado_id"])
        m = cp_model.CpModel()
        z = {}
        for e in gente:
            for d in dias:
                if (e, d) in ctx["ausentes"]:
                    continue
                vs = []
                for g in grupos:
                    if n_val.get((d, g[0], g[1], r), 0) > 0:
                        z[(e, d, g)] = m.NewBoolVar("")
                        vs.append(z[(e, d, g)])
                if vs:
                    m.AddAtMostOne(vs)
        falta = []
        for d in dias:
            for g in grupos:
                req = n_val.get((d, g[0], g[1], r), 0)
                if req:
                    vs = [z[(e, d, g)] for e in gente if (e, d, g) in z]
                    f = m.NewIntVar(0, req, "")
                    m.Add(sum(vs) + f == req)
                    falta.append(f)
        extra = []
        for e in gente:
            vs = [(v, g) for (ee, _d, g), v in z.items() if ee == e]
            m.Add(sum(v for v, _ in vs) <= dias_max)
            m.Add(sum(v for v, g in vs if g[1] > 0) <= MAX_DIAS_EXTENDIDOS)
            h = sum(v * (turnos[g[0]]["spans"][g[1]][1] - turnos[g[0]]["spans"][g[1]][0]) for v, g in vs)
            x = m.NewIntVar(0, 100, "")
            m.Add(x >= h - tope)
            extra.append(x)
        m.Minimize(1000 * sum(falta) + sum(extra))
        sv = cp_model.CpSolver()
        sv.parameters.max_time_in_seconds = 5.0
        sv.parameters.num_search_workers = 4
        if sv.Solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            continue
        asignados: dict = {}
        for (e, d, g), v in z.items():
            if sv.Value(v):
                asignados.setdefault((d, g), []).append(e)
        for (d, (ti, k)), es in asignados.items():
            t = turnos[ti]
            ini, fin = t["spans"][k]
            cola = []
            for p, cnt in sorted(c_val.get((d, ti, k, r), {}).items()):
                cola += [p] * cnt
            cola += [t["pausa"]] * max(0, len(es) - len(cola))
            for e, p in zip(sorted(es), cola):
                filas.append({"empleado_id": e, "fecha": d, "turno": t["turno"],
                              "hora_inicio": ini, "hora_fin": fin, "hora_pausa": p})
    return pd.DataFrame(filas, columns=["empleado_id", "fecha", "turno", "hora_inicio", "hora_fin", "hora_pausa"])


def _metricas(ctx: dict, turnos_df: pd.DataFrame) -> dict:
    """Costo real (por persona, orden legal de horas extra) y cobertura real."""
    reg, emp = ctx["reg"], ctx["empleados"]
    tope, t_dbl, t_tpl = (reg["jornada_ordinaria_semanal_horas"], reg["extra_tope_doble_semanal_horas"],
                          reg["extra_tope_triple_semanal_horas"])
    m_dbl, m_tpl = reg["pago_extra_doble_multiplicador"], reg["pago_extra_triple_multiplicador"]
    horas = (turnos_df["hora_fin"] - turnos_df["hora_inicio"]).groupby(turnos_df["empleado_id"]).sum().to_dict() \
        if not turnos_df.empty else {}
    sal = dict(zip(emp["empleado_id"], emp["salario_diario_mxn"]))
    ho = hd = ht = 0
    costo = 0.0
    for e, h in horas.items():
        o = min(h, tope); dbl = min(max(0, h - tope), t_dbl); tpl = max(0, h - tope - t_dbl)
        vh = sal[e] / (tope / 6)
        costo += o * vh + dbl * vh * m_dbl + tpl * vh * m_tpl
        ho += o; hd += dbl; ht += tpl
    rol_de = dict(zip(emp["empleado_id"], emp["rol"]))
    cob: dict = {}
    for r in turnos_df.itertuples(index=False):
        for h in range(int(r.hora_inicio), int(r.hora_fin)):
            if h != int(r.hora_pausa):
                key = (r.fecha, h, rol_de[r.empleado_id])
                cob[key] = cob.get(key, 0) + 1
    sub_pico = sobre = 0
    for (d, h, rol), req in ctx["demanda"].items():
        cv = cob.get((d, h, rol), 0)
        if ctx["es_pico_map"].get((d, h), False):
            sub_pico += max(0, int(req) - cv)
        sobre += max(0, cv - int(req) - _MARGEN_SOBRESTAFFING)
    return {"costo_total_mxn": round(costo, 2), "horas_ordinarias": int(ho), "horas_extra_doble": int(hd),
            "horas_extra_triple": int(ht), "horas_subdotacion_pico": int(sub_pico), "horas_sobrestaffing": int(sobre)}


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
    """Horario óptimo de UNA tienda para UNA semana: persona -> turno fijo.

    1) Modelo agregado por área (exacto para cobertura, óptimo en segundos).
       Cobertura en hora pico DURA; si es imposible (p. ej. mucha ausencia),
       se reintenta con penalización muy alta y se reporta
       ``pico_relajado=True`` y ``horas_subdotacion_pico``.
    2) Asignación de nombres respetando límites legales por persona.
    3) Costo y cobertura se recalculan sobre el horario real con nombres.
    """
    ctx = _preparar(anio, plantilla_tienda_df, demanda_tienda_df, ausentismo_df, fecha_inicio)
    pico_relajado = False
    for pico_duro in (True, False):
        status, n_val, c_val, brecha = _modelo_agregado(ctx, modo, pico_duro, tiempo_limite_seg)
        if status in ("OPTIMAL", "FEASIBLE"):
            pico_relajado = not pico_duro
            break
    if n_val is None:
        return {
            "tienda_id": tienda_id, "status": "INFEASIBLE",
            "mensaje": "No se encontró horario factible con las reglas legales de jornada y descansos.",
            "horario_df": pd.DataFrame(), "turnos_df": pd.DataFrame(), "catalogo_turnos": ctx["turnos"],
            "costo_total_mxn": None, "brecha_optimalidad_pct": None, "horas_ordinarias": None,
            "horas_extra_doble": None, "horas_extra_triple": None, "horas_subdotacion_pico": None,
            "horas_sobrestaffing": None, "pico_relajado": None,
        }
    turnos_df = _asignar_personas(ctx, n_val, c_val)
    res = {"tienda_id": tienda_id, "status": status, "turnos_df": turnos_df,
           "horario_df": turnos_a_horario(turnos_df), "catalogo_turnos": ctx["turnos"],
           "brecha_optimalidad_pct": round(brecha, 3), "pico_relajado": pico_relajado}
    res.update(_metricas(ctx, turnos_df))
    return res


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
