"""Costos, ahorro y trazabilidad: compara el escenario base contra la propuesta.

Junta los resultados de jornada40.escenario_base (baseline) y
jornada40.optimizador (propuesta y techo teórico) en los reportes que se
muestran al CFO/COO: ahorro semanal y diario, brecha contra el techo, y la
tabla de trazabilidad legal (regla -> artículo -> restricción -> estado).

Los resultados de escenario_base y optimizador tienen nombres de llave
ligeramente distintos (p. ej. "horas_ordinarias_totales" vs
"horas_ordinarias"); ``_normalizar`` los homogeniza para que este módulo
pueda comparar cualquier combinación de los dos sin acoplarse a un origen
específico.

Regla de negocio explícita (candado anti-trampa): si la propuesta deja
subdotación en franjas donde el base SÍ cubría la demanda, esas horas NO
cuentan como ahorro — se penalizan y se restan del ahorro reportado.

Dependencias: jornada40.reglas, pandas.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from jornada40 import reglas

__all__ = [
    "calcular_ahorro_semanal",
    "desglosar_por_dia",
    "calcular_brecha_vs_techo",
    "armar_tabla_trazabilidad",
    "generar_reporte_cfo",
]

# Multiplicador con el que se penaliza la subdotación NUEVA que la
# propuesta introduce y el base no tenía (candado anti-trampa). No es una
# cifra legal, es una convención de negocio del PMV: castiga el ahorro
# "de papel" que en realidad es servicio perdido, no ahorro real.
_PESO_PENALIZACION_SUBDOTACION_NUEVA = 3.0


def _normalizar(resultado: dict) -> dict:
    """Homogeniza los resultados de escenario_base.py y optimizador.py."""
    return {
        "horas_ordinarias": resultado.get("horas_ordinarias_totales", resultado.get("horas_ordinarias", 0.0)) or 0.0,
        "horas_extra_doble": resultado.get("horas_extra_doble_totales", resultado.get("horas_extra_doble", 0.0)) or 0.0,
        "horas_extra_triple": resultado.get("horas_extra_triple_totales", resultado.get("horas_extra_triple", 0.0)) or 0.0,
        "horas_subdotacion": resultado.get("horas_subdotacion_totales", resultado.get("horas_subdotacion_pico", 0.0)) or 0.0,
        "horas_sobrestaffing": resultado.get("horas_sobrestaffing", 0.0) or 0.0,
        "costo_total_mxn": resultado.get("costo_total_mxn", 0.0) or 0.0,
    }


def _valor_hora_referencia(resultado_base: dict) -> float:
    """Valor hora de referencia para desglosar $ por concepto (informativo).

    Usa costo_ordinario_mxn / horas_ordinarias_totales del BASE cuando
    están disponibles (más preciso); si no, aproxima con
    costo_total / horas_ordinarias.
    """
    n = _normalizar(resultado_base)
    costo_ordinario = resultado_base.get("costo_ordinario_mxn", n["costo_total_mxn"])
    horas_ord = n["horas_ordinarias"]
    return float(costo_ordinario) / horas_ord if horas_ord > 0 else 0.0


def calcular_ahorro_semanal(
    resultado_base: dict,
    resultado_propuesta: dict,
    anio: int,
    valor_hora_mxn: float | None = None,
) -> dict:
    """Compara base vs propuesta y calcula el ahorro semanal en pesos.

    ``ahorro_total_mxn`` es SIEMPRE ``costo_total_base - costo_total_propuesta``
    menos la penalización por subdotación nueva (candado anti-trampa): si
    la propuesta deja franjas sin cubrir que el base sí cubría, esas horas
    NO cuentan como ahorro, se restan explícitamente.
    """
    fref = date(anio, 1, 1)
    b = _normalizar(resultado_base)
    p = _normalizar(resultado_propuesta)
    vh = valor_hora_mxn if valor_hora_mxn is not None else _valor_hora_referencia(resultado_base)
    mult_doble = reglas.regla_vigente("pago_extra_doble_multiplicador", fref)
    mult_triple = reglas.regla_vigente("pago_extra_triple_multiplicador", fref)

    horas_extra_doble_evitadas = b["horas_extra_doble"] - p["horas_extra_doble"]
    horas_extra_triple_evitadas = b["horas_extra_triple"] - p["horas_extra_triple"]
    costo_extra_evitado_mxn = (horas_extra_doble_evitadas * vh * mult_doble
                                + horas_extra_triple_evitadas * vh * mult_triple)

    horas_sobrestaffing_evitadas = b["horas_sobrestaffing"] - p["horas_sobrestaffing"]
    costo_sobrestaffing_evitado_mxn = horas_sobrestaffing_evitadas * vh

    subdotacion_nueva = max(0.0, p["horas_subdotacion"] - b["horas_subdotacion"])
    penalizacion_subdotacion_no_cubierta_mxn = subdotacion_nueva * vh * _PESO_PENALIZACION_SUBDOTACION_NUEVA

    costo_base = b["costo_total_mxn"]
    costo_propuesta = p["costo_total_mxn"]
    ahorro_total_mxn = (costo_base - costo_propuesta) - penalizacion_subdotacion_no_cubierta_mxn
    ahorro_pct = (ahorro_total_mxn / costo_base) if costo_base > 0 else 0.0

    return {
        "costo_base_mxn": round(costo_base, 2),
        "costo_propuesta_mxn": round(costo_propuesta, 2),
        "horas_extra_doble_evitadas": horas_extra_doble_evitadas,
        "horas_extra_triple_evitadas": horas_extra_triple_evitadas,
        "costo_extra_evitado_mxn": round(costo_extra_evitado_mxn, 2),
        "horas_sobrestaffing_evitadas": horas_sobrestaffing_evitadas,
        "costo_sobrestaffing_evitado_mxn": round(costo_sobrestaffing_evitado_mxn, 2),
        "penalizacion_subdotacion_no_cubierta_mxn": round(penalizacion_subdotacion_no_cubierta_mxn, 2),
        "ahorro_total_mxn": round(ahorro_total_mxn, 2),
        "ahorro_pct": ahorro_pct,
        "cumple_minimo_8pct": ahorro_pct >= 0.08,
    }


def desglosar_por_dia(
    resultados_diarios_base: dict[date, dict],
    resultados_diarios_propuesta: dict[date, dict],
    anio: int,
    valor_hora_mxn: float | None = None,
) -> pd.DataFrame:
    """Ahorro día por día (domingo a sábado) + fila de totales.

    ``resultados_diarios_base``/``_propuesta`` son dicts {fecha: resultado},
    con el mismo formato de resultado que calcular_ahorro_semanal recibe
    (uno por cada uno de los 7 días — típicamente producidos corriendo
    escenario_base/optimizador con la demanda de un solo día a la vez).

    La suma de las 7 filas diarias debe cuadrar EXACTO con el resultado de
    calcular_ahorro_semanal sobre los totales agregados de la semana; si no
    cuadra, lanza AssertionError (es el "reporte auditable").
    """
    fechas = sorted(resultados_diarios_base.keys())
    filas = []
    for fecha in fechas:
        ahorro_dia = calcular_ahorro_semanal(
            resultados_diarios_base[fecha], resultados_diarios_propuesta[fecha],
            anio, valor_hora_mxn=valor_hora_mxn,
        )
        ahorro_dia["fecha"] = fecha
        filas.append(ahorro_dia)
    df = pd.DataFrame(filas)

    columnas_suma = ["costo_extra_evitado_mxn", "costo_sobrestaffing_evitado_mxn",
                      "penalizacion_subdotacion_no_cubierta_mxn", "ahorro_total_mxn"]
    totales = {c: df[c].sum() for c in columnas_suma}
    totales["fecha"] = "TOTAL"

    # Agregado semanal real (suma de horas/costos de los 7 días) para el
    # cuadre exacto contra calcular_ahorro_semanal.
    base_agg = _agregar_resultados(list(resultados_diarios_base.values()))
    prop_agg = _agregar_resultados(list(resultados_diarios_propuesta.values()))
    ahorro_semanal = calcular_ahorro_semanal(base_agg, prop_agg, anio, valor_hora_mxn=valor_hora_mxn)

    for c in columnas_suma:
        assert abs(totales[c] - ahorro_semanal[c]) < 0.01, (
            f"Desglose diario no cuadra con el semanal en '{c}': "
            f"{totales[c]} != {ahorro_semanal[c]}"
        )

    return pd.concat([df, pd.DataFrame([totales])], ignore_index=True)


def _agregar_resultados(resultados: list[dict]) -> dict:
    """Suma un conjunto de resultados diarios (mismo esquema) en uno solo."""
    normalizados = [_normalizar(r) for r in resultados]
    agregado = {
        "horas_ordinarias_totales": sum(n["horas_ordinarias"] for n in normalizados),
        "horas_extra_doble_totales": sum(n["horas_extra_doble"] for n in normalizados),
        "horas_extra_triple_totales": sum(n["horas_extra_triple"] for n in normalizados),
        "horas_subdotacion_totales": sum(n["horas_subdotacion"] for n in normalizados),
        "horas_sobrestaffing": sum(n["horas_sobrestaffing"] for n in normalizados),
        "costo_total_mxn": sum(n["costo_total_mxn"] for n in normalizados),
        "costo_ordinario_mxn": sum(r.get("costo_ordinario_mxn", 0.0) for r in resultados),
    }
    return agregado


def calcular_brecha_vs_techo(resultado_base: dict, resultado_propuesta: dict, resultado_techo: dict) -> dict:
    """Qué tanto del ahorro máximo posible (techo) capturó la propuesta.

    ``pct_del_techo_capturado`` = ahorro_logrado / ahorro_techo. Si el
    ahorro_techo es 0 (no había nada que ahorrar), se reporta 100% cuando
    la propuesta tampoco ahorró de más, o 0% si de algún modo costó más
    que el base (no debería pasar con un optimizador correcto).
    """
    costo_base = _normalizar(resultado_base)["costo_total_mxn"]
    costo_propuesta = _normalizar(resultado_propuesta)["costo_total_mxn"]
    costo_techo = _normalizar(resultado_techo)["costo_total_mxn"]

    ahorro_logrado_mxn = costo_base - costo_propuesta
    ahorro_techo_mxn = costo_base - costo_techo
    brecha_mxn = ahorro_techo_mxn - ahorro_logrado_mxn

    if ahorro_techo_mxn > 0:
        pct_del_techo_capturado = ahorro_logrado_mxn / ahorro_techo_mxn
    else:
        pct_del_techo_capturado = 1.0 if ahorro_logrado_mxn <= 0 else 0.0

    factores_limitantes = [
        "Cobertura mínima por área abierta",
        "Colchón por incertidumbre del pronóstico de demanda",
        "Estabilidad de horarios (no relajada en este cálculo)",
    ]
    return {
        "ahorro_logrado_mxn": round(ahorro_logrado_mxn, 2),
        "ahorro_techo_mxn": round(ahorro_techo_mxn, 2),
        "pct_del_techo_capturado": round(pct_del_techo_capturado, 4),
        "brecha_mxn": round(brecha_mxn, 2),
        "factores_limitantes": factores_limitantes,
    }


_TABLA_TRAZABILIDAD = [
    {"regla": "Jornada ordinaria máxima semanal según año", "articulo_fuente": "Art. 59 + Transitorio 2", "tipo": "dura", "estado": "verificado"},
    {"regla": "Jornada diaria 8h diurna/7h nocturna/7.5h mixta", "articulo_fuente": "Art. 61", "tipo": "dura", "estado": "verificado"},
    {"regla": "Distribución de jornada de común acuerdo", "articulo_fuente": "Art. 58 párr. 2", "tipo": "habilitador", "estado": "verificado"},
    {"regla": "Un día de descanso por cada 6 trabajados", "articulo_fuente": "Art. 69", "tipo": "dura", "estado": "verificado"},
    {"regla": "Prima dominical 25% mínimo", "articulo_fuente": "Art. 71", "tipo": "costo", "estado": "verificado"},
    {"regla": "Extra al doble, tope semanal según año, máx 4h/día y 4 días/semana", "articulo_fuente": "Art. 66 + Transitorio 4", "tipo": "dura", "estado": "verificado"},
    {"regla": "Extra que excede el tope: máx 4h/semana adicionales, al triple", "articulo_fuente": "Art. 68", "tipo": "dura", "estado": "pendiente_validacion_legal"},
    {"regla": "Ordinaria + extra máximo 12h/día", "articulo_fuente": "Art. 68", "tipo": "dura", "estado": "verificado"},
    {"regla": "Registro electrónico de jornada (desde 2027)", "articulo_fuente": "Art. 132 fr. XXXIV + Transitorio 5", "tipo": "funcional", "estado": "verificado"},
    {"regla": "La reforma no puede bajar sueldos ni prestaciones", "articulo_fuente": "Transitorio 7", "tipo": "parametro_costo", "estado": "verificado"},
    {"regla": "Descanso de 30 min en jornada continua", "articulo_fuente": "Art. 63", "tipo": "dura", "estado": "verificado"},
    {"regla": "Trabajar en día de descanso: salario doble adicional", "articulo_fuente": "Art. 73", "tipo": "costo", "estado": "verificado"},
    {"regla": "Días de descanso obligatorio (calendario)", "articulo_fuente": "Art. 74", "tipo": "dato", "estado": "verificado"},
    {"regla": "Trabajar día festivo: salario doble adicional (además del día)", "articulo_fuente": "Art. 75", "tipo": "costo", "estado": "verificado"},
]


def armar_tabla_trazabilidad() -> pd.DataFrame:
    """Tabla estática regla -> artículo -> tipo -> estado (14 filas fijas)."""
    return pd.DataFrame(_TABLA_TRAZABILIDAD)


def generar_reporte_cfo(
    tienda_id: str,
    resultado_base: dict,
    resultado_propuesta: dict,
    resultado_techo: dict,
    anio: int,
) -> dict:
    """Junta ahorro semanal, brecha vs techo y trazabilidad en un solo dict."""
    ahorro = calcular_ahorro_semanal(resultado_base, resultado_propuesta, anio)
    brecha = calcular_brecha_vs_techo(resultado_base, resultado_propuesta, resultado_techo)
    tabla = armar_tabla_trazabilidad()

    resumen = (
        f"Tienda {tienda_id}: ahorro semanal de ${ahorro['ahorro_total_mxn']:,.0f} MXN "
        f"({ahorro['ahorro_pct']:.1%} del costo base), "
        f"{'cumple' if ahorro['cumple_minimo_8pct'] else 'NO cumple'} el mínimo de 8%. "
        f"Captura {brecha['pct_del_techo_capturado']:.0%} del ahorro máximo posible (techo)."
    )
    return {
        "tienda_id": tienda_id,
        "resumen_ejecutivo": resumen,
        "ahorro_semanal": ahorro,
        "brecha_vs_techo": brecha,
        "tabla_trazabilidad": tabla,
    }
