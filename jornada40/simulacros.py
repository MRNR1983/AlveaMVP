"""Simulacros: palancas de escenario y préstamo de personal entre tiendas.

Permite correr escenarios alternativos (tráfico, plantilla, ausentismo,
horario, régimen legal) SIN pisar los datos originales, comparando siempre
el resultado del simulacro contra el resultado original lado a lado. El
préstamo de personal entre tiendas del mismo clúster es una palanca más,
implementada como una PROPUESTA (no modifica horarios automáticamente).

Dependencias: jornada40.datos_sinteticos, jornada40.demanda_personal,
jornada40.optimizador, jornada40.costos_ahorro (reutiliza _normalizar).
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from jornada40 import datos_sinteticos, demanda_personal, optimizador
from jornada40.costos_ahorro import _normalizar, _valor_hora_referencia

__all__ = [
    "Palancas",
    "aplicar_palancas",
    "simular_refuerzo_entre_tiendas",
    "correr_simulacro",
    "correr_simulacro_red",
]

_COSTO_TRASLADO_DEFAULT_MXN_HORA = 15.0


@dataclass
class Palancas:
    """Un simulacro es un conjunto de palancas sobre el escenario original.

    Todos los campos son opcionales; el default (todo en su valor neutro)
    significa "sin cambio respecto al escenario original".
    """
    multiplicador_trafico: float = 1.0
    delta_plantilla: int = 0
    delta_plantilla_por_rol: dict[str, int] | None = None
    tasa_ausentismo: float | None = None
    delta_horario_apertura_horas: float = 0
    anio_regimen: int | None = None
    refuerzos_activos: bool = False


def _ajustar_plantilla(plantilla_tienda: pd.DataFrame, palancas: Palancas, seed: int = 42) -> pd.DataFrame:
    """Aplica delta_plantilla / delta_plantilla_por_rol a la plantilla de una tienda."""
    if palancas.delta_plantilla == 0 and not palancas.delta_plantilla_por_rol:
        return plantilla_tienda.copy()

    rng = np.random.default_rng(seed)
    plantilla = plantilla_tienda.copy()
    tienda_id = plantilla["tienda_id"].iloc[0]

    if palancas.delta_plantilla_por_rol:
        deltas = dict(palancas.delta_plantilla_por_rol)
    else:
        # Reparte delta_plantilla proporcionalmente entre roles existentes.
        conteos = plantilla["rol"].value_counts()
        total = conteos.sum()
        deltas = {rol: round(palancas.delta_plantilla * n / total) for rol, n in conteos.items()}

    siguiente_id = int(plantilla["empleado_id"].str.extract(r"(\d+)$")[0].astype(int).max()) + 1
    filas_nuevas = []
    for rol, delta in deltas.items():
        if delta > 0:
            candidatos = plantilla.loc[plantilla["rol"] == rol]
            if candidatos.empty:
                continue
            for _ in range(delta):
                base = candidatos.sample(1, random_state=rng.integers(0, 1_000_000)).iloc[0]
                nueva = base.copy()
                nueva["empleado_id"] = f"S{siguiente_id:06d}"
                siguiente_id += 1
                filas_nuevas.append(nueva)
        elif delta < 0:
            candidatos = plantilla.loc[plantilla["rol"] == rol]
            a_quitar = candidatos["empleado_id"].tail(min(-delta, len(candidatos)))
            plantilla = plantilla.loc[~plantilla["empleado_id"].isin(a_quitar)]

    if filas_nuevas:
        plantilla = pd.concat([plantilla, pd.DataFrame(filas_nuevas)], ignore_index=True)
    plantilla["tienda_id"] = tienda_id
    return plantilla.reset_index(drop=True)


def aplicar_palancas(
    tienda_id: str,
    palancas: Palancas,
    tiendas_df: pd.DataFrame,
    trafico_df: pd.DataFrame,
    ventas_df: pd.DataFrame,
    plantilla_df: pd.DataFrame,
    ausentismo_df: pd.DataFrame,
    anio_base: int,
    seed: int = 42,
) -> dict:
    """Aplica las palancas a los datos de ENTRADA de una tienda.

    Regresa un dict con tiendas_df/trafico_df/ventas_df/plantilla_df/
    ausentismo_df/anio ya modificados, listos para pasar a
    demanda_personal + optimizador. No modifica los DataFrames originales.
    """
    tienda_row = tiendas_df.loc[tiendas_df["tienda_id"] == tienda_id].copy()
    trafico_tienda = trafico_df.loc[trafico_df["tienda_id"] == tienda_id].copy()
    plantilla_tienda = plantilla_df.loc[plantilla_df["tienda_id"] == tienda_id].copy()
    ausentismo_tienda = ausentismo_df.loc[
        ausentismo_df["empleado_id"].isin(plantilla_tienda["empleado_id"])
    ].copy() if not ausentismo_df.empty else ausentismo_df.copy()

    # 1) Tráfico.
    trafico_tienda["clientes_estimados"] = np.floor(
        trafico_tienda["clientes_estimados"] * palancas.multiplicador_trafico
    ).astype(int)
    ventas_tienda = datos_sinteticos.generar_ventas(trafico_tienda, seed=seed)

    # 2) Ventana horaria.
    if palancas.delta_horario_apertura_horas:
        tienda_row["hora_cierre"] = (
            tienda_row["hora_cierre"] + palancas.delta_horario_apertura_horas
        ).clip(upper=23).astype(int)

    # 3) Plantilla.
    plantilla_tienda = _ajustar_plantilla(plantilla_tienda, palancas, seed=seed)

    # 4) Ausentismo (si cambia la tasa, o si cambió la plantilla, se
    #    regenera para todos los empleados vigentes en el rango de fechas
    #    original).
    if not ausentismo_df.empty:
        fechas = sorted(ausentismo_tienda["fecha"].unique()) if not ausentismo_tienda.empty else []
        if fechas and (palancas.tasa_ausentismo is not None
                       or set(plantilla_tienda["empleado_id"]) != set(ausentismo_tienda["empleado_id"].unique())):
            tasa = palancas.tasa_ausentismo if palancas.tasa_ausentismo is not None else \
                datos_sinteticos.CONFIG["ausentismo"]["tasa_default"]
            ausentismo_tienda = datos_sinteticos.generar_ausentismo(
                plantilla_tienda, min(fechas), max(fechas), tasa=tasa, seed=seed,
            )

    anio = palancas.anio_regimen if palancas.anio_regimen is not None else anio_base

    return {
        "tiendas_df": tienda_row, "trafico_df": trafico_tienda, "ventas_df": ventas_tienda,
        "plantilla_df": plantilla_tienda, "ausentismo_df": ausentismo_tienda, "anio": anio,
    }


def simular_refuerzo_entre_tiendas(
    resultados_cluster: dict[str, dict],
    costo_traslado_por_hora_mxn: float = _COSTO_TRASLADO_DEFAULT_MXN_HORA,
) -> pd.DataFrame:
    """Propone préstamos de horas entre tiendas del MISMO clúster.

    Detecta tiendas con horas sobrantes (sobrestaffing) y tiendas con
    déficit (subdotación pico) dentro de ``resultados_cluster`` (dict
    {tienda_id: resultado de optimizador.resolver_tienda}), y arma
    propuestas ordenadas por ahorro neto (ahorro en horas extra evitadas
    en destino, menos el costo de traslado). Un préstamo NUNCA deja a la
    tienda origen con menos horas sobrantes de las que ella misma tiene de
    margen (no puede quedar en déficit propio: el tope de lo prestado es
    exactamente su exceso reportado, ``horas_sobrestaffing``).

    El traslado físico de personal entre centros de trabajo requiere
    acuerdo con la persona trabajadora (fuera del alcance legal de esta
    función: es responsabilidad operativa del cliente aprobar cada caso).
    """
    donantes = {tid: r for tid, r in resultados_cluster.items()
                if _normalizar(r).get("horas_sobrestaffing", 0) > 0}
    receptores = {tid: r for tid, r in resultados_cluster.items()
                  if _normalizar(r).get("horas_subdotacion", 0) > 0}

    propuestas = []
    excedentes = {tid: _normalizar(r)["horas_sobrestaffing"] for tid, r in donantes.items()}
    for tid_dest, r_dest in receptores.items():
        deficit = _normalizar(r_dest)["horas_subdotacion"]
        valor_hora_dest = _valor_hora_referencia(r_dest) or 0.0
        for tid_orig in list(excedentes.keys()):
            if tid_orig == tid_dest or deficit <= 0:
                continue
            disponible = excedentes[tid_orig]
            if disponible <= 0:
                continue
            horas = min(disponible, deficit)
            costo_traslado = horas * costo_traslado_por_hora_mxn
            ahorro_evitado = horas * valor_hora_dest * 2.0  # evita pagarlas al doble en destino
            ahorro_neto = ahorro_evitado - costo_traslado
            propuestas.append({
                "tienda_origen": tid_orig, "tienda_destino": tid_dest,
                "horas_prestadas": horas, "costo_traslado_mxn": round(costo_traslado, 2),
                "ahorro_neto_mxn": round(ahorro_neto, 2),
            })
            excedentes[tid_orig] -= horas  # nunca deja al origen en déficit propio
            deficit -= horas

    df = pd.DataFrame(propuestas)
    if df.empty:
        return pd.DataFrame(columns=["tienda_origen", "tienda_destino", "horas_prestadas",
                                      "costo_traslado_mxn", "ahorro_neto_mxn"])
    return df.sort_values("ahorro_neto_mxn", ascending=False).reset_index(drop=True)


def _resolver_pipeline(
    tienda_id: str, anio: int, plantilla_tienda: pd.DataFrame, trafico_tienda: pd.DataFrame,
    ventas_tienda: pd.DataFrame, tienda_row: pd.DataFrame, ausentismo_tienda: pd.DataFrame,
    fecha_inicio: date | None, tiempo_limite_seg: float,
) -> dict:
    demanda = demanda_personal.calcular_demanda_tienda(tienda_id, trafico_tienda, ventas_tienda, tienda_row)
    demanda = demanda_personal.marcar_franjas_pico(demanda)
    return optimizador.resolver_tienda(
        tienda_id, anio, plantilla_tienda, demanda, ausentismo_tienda,
        tiempo_limite_seg=tiempo_limite_seg, fecha_inicio=fecha_inicio,
    )


def correr_simulacro(
    tienda_id: str,
    palancas: Palancas,
    datos_originales: dict,
    anio_base: int,
    fecha_inicio: date | None = None,
    tiempo_limite_seg: float = 20.0,
) -> dict:
    """Corre un simulacro para UNA tienda y lo compara contra el original.

    ``datos_originales`` debe traer tiendas_df, trafico_df, ventas_df,
    plantilla_df, ausentismo_df (sin filtrar a una tienda) y, opcionalmente,
    resultado_original ya calculado (si no viene, se calcula aquí sobre
    los datos SIN palancas).
    """
    tiendas_df = datos_originales["tiendas_df"]
    trafico_df = datos_originales["trafico_df"]
    ventas_df = datos_originales["ventas_df"]
    plantilla_df = datos_originales["plantilla_df"]
    ausentismo_df = datos_originales["ausentismo_df"]

    if "resultado_original" in datos_originales:
        resultado_original = datos_originales["resultado_original"]
    else:
        tienda_row = tiendas_df.loc[tiendas_df["tienda_id"] == tienda_id]
        plantilla_tienda = plantilla_df.loc[plantilla_df["tienda_id"] == tienda_id]
        resultado_original = _resolver_pipeline(
            tienda_id, anio_base, plantilla_tienda, trafico_df, ventas_df, tienda_row,
            ausentismo_df, fecha_inicio, tiempo_limite_seg,
        )

    modificado = aplicar_palancas(
        tienda_id, palancas, tiendas_df, trafico_df, ventas_df, plantilla_df, ausentismo_df, anio_base,
    )
    resultado_simulacro = _resolver_pipeline(
        tienda_id, modificado["anio"], modificado["plantilla_df"], modificado["trafico_df"],
        modificado["ventas_df"], modificado["tiendas_df"], modificado["ausentismo_df"],
        fecha_inicio, tiempo_limite_seg,
    )

    no_normal = _normalizar(resultado_original)
    ns_normal = _normalizar(resultado_simulacro)
    return {
        "tienda_id": tienda_id,
        "resultado_original": resultado_original,
        "resultado_simulacro": resultado_simulacro,
        "delta_costo_mxn": round(ns_normal["costo_total_mxn"] - no_normal["costo_total_mxn"], 2),
        "delta_horas_extra": ((ns_normal["horas_extra_doble"] + ns_normal["horas_extra_triple"])
                               - (no_normal["horas_extra_doble"] + no_normal["horas_extra_triple"])),
    }


def _worker_simulacro(args: tuple) -> dict:
    tienda_id, palancas, datos_originales, anio_base, fecha_inicio, tiempo_limite_seg = args
    return correr_simulacro(tienda_id, palancas, datos_originales, anio_base,
                             fecha_inicio=fecha_inicio, tiempo_limite_seg=tiempo_limite_seg)


def correr_simulacro_red(
    tiendas_ids: list[str],
    palancas: Palancas,
    datos_originales: dict,
    anio_base: int,
    fecha_inicio: date | None = None,
    tiempo_limite_seg: float = 20.0,
    max_workers: int = 8,
) -> dict:
    """Corre el mismo simulacro sobre varias tiendas, en paralelo, y consolida.

    Regresa {"por_tienda": {tienda_id: resultado_correr_simulacro},
    "consolidado": {delta_costo_total_mxn, delta_horas_extra_total}}.
    """
    args = [(tid, palancas, datos_originales, anio_base, fecha_inicio, tiempo_limite_seg)
            for tid in tiendas_ids]
    if max_workers <= 1 or len(tiendas_ids) <= 1:
        resultados = [_worker_simulacro(a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            resultados = list(ex.map(_worker_simulacro, args))
    por_tienda = {r["tienda_id"]: r for r in resultados}
    consolidado = {
        "delta_costo_total_mxn": round(sum(r["delta_costo_mxn"] for r in resultados), 2),
        "delta_horas_extra_total": sum(r["delta_horas_extra"] for r in resultados),
    }
    return {"por_tienda": por_tienda, "consolidado": consolidado}
