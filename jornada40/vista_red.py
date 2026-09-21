"""Vista Red: consolida las 50 tiendas como un solo ente para reporting.

El cálculo sigue siendo por tienda (50 problemas independientes resueltos
en paralelo por jornada40.optimizador); este módulo solo agrega, filtra y
orquesta acciones masivas sobre ese resultado ya calculado.

Contrato de entrada esperado en ``resultados_por_tienda``: un dict
{tienda_id: {"ahorro_semanal": <de costos_ahorro.calcular_ahorro_semanal>,
"brecha_vs_techo": <de costos_ahorro.calcular_brecha_vs_techo>,
"status": <status del optimizador, ej. "OPTIMAL">}} — típicamente
construido en app.py combinando costos_ahorro.generar_reporte_cfo() con
el status del resultado de optimizador.resolver_tienda().

Dependencias: jornada40.simulacros (acciones masivas), jornada40.costos_ahorro
(_normalizar, multiplicadores legales), pandas.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from jornada40 import reglas, simulacros
from jornada40.costos_ahorro import _normalizar

__all__ = [
    "consolidar_resultados",
    "filtrar_por",
    "aplicar_accion_masiva",
    "calcular_techo_red_pool",
    "resumen_para_demo",
]

_COSTO_TRASLADO_INTERCLUSTER_MXN_HORA = 40.0  # SUPUESTO: mayor al intra-clúster (15)


def consolidar_resultados(resultados_por_tienda: dict[str, dict], tiendas_df: pd.DataFrame) -> dict:
    """Agrega el resultado de todas las tiendas en un consolidado de red."""
    filas = []
    for tid, r in resultados_por_tienda.items():
        ahorro = r["ahorro_semanal"]
        brecha = r["brecha_vs_techo"]
        meta = tiendas_df.loc[tiendas_df["tienda_id"] == tid]
        cluster_id = meta["cluster_id"].iloc[0] if not meta.empty else None
        formato = meta["formato"].iloc[0] if not meta.empty else None
        filas.append({
            "tienda_id": tid, "cluster_id": cluster_id, "formato": formato,
            "ahorro_mxn": ahorro["ahorro_total_mxn"], "ahorro_pct": ahorro["ahorro_pct"],
            "pct_del_techo_capturado": brecha["pct_del_techo_capturado"],
            "status_solver": r.get("status", "DESCONOCIDO"),
            "cumple_minimo_8pct": ahorro["cumple_minimo_8pct"],
        })
    ranking = pd.DataFrame(filas).sort_values("ahorro_pct", ascending=False).reset_index(drop=True)

    costo_base_red = sum(r["ahorro_semanal"]["costo_base_mxn"] for r in resultados_por_tienda.values())
    costo_propuesta_red = sum(r["ahorro_semanal"]["costo_propuesta_mxn"] for r in resultados_por_tienda.values())
    ahorro_total_red = sum(r["ahorro_semanal"]["ahorro_total_mxn"] for r in resultados_por_tienda.values())
    horas_extra_evitadas_red = sum(
        r["ahorro_semanal"]["horas_extra_doble_evitadas"] + r["ahorro_semanal"]["horas_extra_triple_evitadas"]
        for r in resultados_por_tienda.values()
    )

    return {
        "ahorro_total_red_mxn": round(ahorro_total_red, 2),
        "ahorro_pct_red": (ahorro_total_red / costo_base_red) if costo_base_red > 0 else 0.0,
        "costo_base_red_mxn": round(costo_base_red, 2),
        "costo_propuesta_red_mxn": round(costo_propuesta_red, 2),
        "horas_extra_evitadas_red": horas_extra_evitadas_red,
        "ranking_tiendas": ranking,
        "tiendas_bajo_minimo_8pct": ranking.loc[~ranking["cumple_minimo_8pct"], "tienda_id"].tolist(),
        "tiendas_infeasible": ranking.loc[ranking["status_solver"] == "INFEASIBLE", "tienda_id"].tolist(),
    }


def filtrar_por(
    ranking_df: pd.DataFrame,
    cluster_id: str | None = None,
    formato: str | None = None,
    ahorro_pct_max: float | None = None,
) -> pd.DataFrame:
    """Filtro simple sobre el ranking consolidado (vista Red de la app)."""
    df = ranking_df
    if cluster_id is not None:
        df = df.loc[df["cluster_id"] == cluster_id]
    if formato is not None:
        df = df.loc[df["formato"] == formato]
    if ahorro_pct_max is not None:
        df = df.loc[df["ahorro_pct"] < ahorro_pct_max]
    return df.reset_index(drop=True)


def aplicar_accion_masiva(
    tiendas_ids: list[str],
    palancas: "simulacros.Palancas",
    datos_originales: dict,
    anio_base: int,
    fecha_inicio: date | None = None,
    tiempo_limite_seg: float = 20.0,
    max_workers: int = 8,
) -> dict:
    """Aplica las mismas palancas a un conjunto de tiendas de un solo golpe.

    Envuelve simulacros.correr_simulacro_red; regresa su mismo resultado
    ({"por_tienda": ..., "consolidado": {delta_costo_total_mxn,
    delta_horas_extra_total}}) — la consolidación completa vía
    consolidar_resultados() requiere el formato "reporte_cfo" (ahorro
    contra el base legal), mientras que una acción masiva compara contra
    el escenario ORIGINAL, no contra el base; por eso se reportan por
    separado (simplificación documentada del PMV).
    """
    return simulacros.correr_simulacro_red(
        tiendas_ids, palancas, datos_originales, anio_base,
        fecha_inicio=fecha_inicio, tiempo_limite_seg=tiempo_limite_seg, max_workers=max_workers,
    )


def calcular_techo_red_pool(
    tiendas_ids: list[str],
    resultados_techo_por_tienda: dict,
    resultados_propuesta_por_tienda: dict,
    anio: int,
) -> dict:
    """Cota superior TEÓRICA: qué pasaría si las 4000 personas fueran un pool.

    NO es una propuesta operativa (nadie mueve personal entre CDMX y
    Monterrey); sirve solo para poner un límite superior a cuánto pueden
    valer los refuerzos entre tiendas. Estima cuánta de la subdotación de
    unas tiendas podría cubrirse con el sobrestaffing de otras, descontando
    un costo de traslado promedio ENTRE clústeres (más caro que el
    intra-clúster de simulacros.py, por ser cruces de ciudad/región).
    """
    fref = date(anio, 1, 1)
    mult_doble = reglas.regla_vigente("pago_extra_doble_multiplicador", fref)

    techos = {t: _normalizar(resultados_techo_por_tienda[t]) for t in tiendas_ids
              if t in resultados_techo_por_tienda}
    propuestas = {t: _normalizar(resultados_propuesta_por_tienda[t]) for t in tiendas_ids
                  if t in resultados_propuesta_por_tienda}

    techo_suma_tiendas_mxn = sum(v["costo_total_mxn"] for v in techos.values())

    total_deficit = sum(v["horas_subdotacion"] for v in propuestas.values())
    total_exceso = sum(v["horas_sobrestaffing"] for v in propuestas.values())
    horas_movibles = min(total_deficit, total_exceso)

    horas_totales = sum(v["horas_ordinarias"] + v["horas_extra_doble"] + v["horas_extra_triple"]
                         for v in propuestas.values())
    costo_total = sum(v["costo_total_mxn"] for v in propuestas.values())
    valor_hora_prom = (costo_total / horas_totales) if horas_totales > 0 else 0.0

    ahorro_bruto = horas_movibles * valor_hora_prom * mult_doble
    costo_traslado_estimado = horas_movibles * _COSTO_TRASLADO_INTERCLUSTER_MXN_HORA
    ahorro_neto_pool = max(0.0, ahorro_bruto - costo_traslado_estimado)

    techo_red_pool_mxn = techo_suma_tiendas_mxn - ahorro_neto_pool
    return {
        "techo_suma_tiendas_mxn": round(techo_suma_tiendas_mxn, 2),
        "techo_red_pool_mxn": round(techo_red_pool_mxn, 2),
        "valor_maximo_de_refuerzos_mxn": round(ahorro_neto_pool, 2),
    }


def resumen_para_demo(consolidado: dict) -> str:
    """Texto corto (5-8 líneas) para leer en voz alta en la demo con el CFO."""
    ranking = consolidado["ranking_tiendas"]
    n_total = len(ranking)
    n_bajo_minimo = len(consolidado["tiendas_bajo_minimo_8pct"])
    n_infeasible = len(consolidado["tiendas_infeasible"])
    pct_techo_prom = ranking["pct_del_techo_capturado"].mean() if not ranking.empty else 0.0

    return (
        f"Ahorro total de la red: ${consolidado['ahorro_total_red_mxn']:,.0f} MXN, "
        f"{consolidado['ahorro_pct_red']:.1%} del costo laboral base.\n"
        f"De {n_total} tiendas, {n_total - n_bajo_minimo} superan el mínimo de 8% de ahorro "
        f"y {n_bajo_minimo} quedan por debajo.\n"
        f"En promedio, la propuesta captura {pct_techo_prom:.0%} del ahorro máximo posible (techo) "
        f"por tienda.\n"
        f"{n_infeasible} tiendas no encontraron horario factible dentro del tiempo límite "
        f"y requieren revisión manual.\n"
        f"Horas extra evitadas en la red: {consolidado['horas_extra_evitadas_red']:.0f} horas/semana."
    )
