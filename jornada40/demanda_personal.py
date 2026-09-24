"""Conversión de tráfico y ventas en personas requeridas por franja horaria.

Convierte el tráfico de clientes y las ventas (jornada40/datos_sinteticos.py)
en personas requeridas por tienda, día, hora y rol:

  - Cajas: aproximación de Erlang C (cola M/M/c) sobre el tráfico de clientes,
    acotada por el número de cajas físicas de la tienda (tope físico).
  - Piso/reposición, perecederos y almacén: carga de trabajo (proxy sobre
    tickets) dividida entre productividad por persona, con mínimo de
    cobertura si el área está operando esa hora.

Todos los parámetros de calibración (tiempo de atención, espera máxima,
factores de carga y productividad por rol) viven en los dicts CONFIG al
inicio del archivo — son SUPUESTOS de negocio, no datos medidos, y deben
calibrarse con datos reales en Fase 1 (ver README del proyecto).

Dependencias: jornada40.reglas (ventana de slots), pandas, numpy.
"""
from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from jornada40 import reglas  # noqa: F401  convenciones compartidas del dominio

__all__ = [
    "CONFIG",
    "personas_requeridas_cajas",
    "personas_requeridas_area",
    "calcular_demanda_tienda",
    "calcular_demanda_red",
    "marcar_franjas_pico",
]

# ---------------------------------------------------------------------------
# SUPUESTOS DE CALIBRACIÓN — CALIBRAR CON DATOS REALES EN FASE 1
# ---------------------------------------------------------------------------
CONFIG: dict = {
    "cajas": {
        "tiempo_atencion_seg_default": 180.0,   # SUPUESTO: 3 min por cliente
        "espera_max_min_default": 4.0,          # SUPUESTO: SLA de espera
        "nivel_servicio_objetivo": 0.80,        # P(espera <= objetivo) >= 80 %
    },
    "areas": {
        # SUPUESTO: unidades de "carga" generadas por ticket, por rol.
        "factor_carga_por_ticket": {
            "piso_reposicion": 0.9,
            "perecederos": 0.5,
            "almacen": 0.6,
        },
        # SUPUESTO: unidades de carga que atiende una persona por hora.
        "productividad_por_persona_hora": {
            "piso_reposicion": 25.0,
            "perecederos": 18.0,
            "almacen": 30.0,
        },
        "minimo_si_area_abierta": 1,
    },
    # CALIBRACIÓN (24-sep-2026). Sin esto, la demanda que sale del tráfico
    # sintético era ~30-55 % de la capacidad de 80 FTE x 48 h, y el
    # "ahorro" salía en 50-70 % -- un número que ningún CFO cree, porque
    # implica que sobra más de la mitad de la gente. El tráfico solo
    # captura trabajo ligado a tickets; una tienda real además recibe
    # mercancía, limpia, hace inventario, cuida cadena de frío, etc.
    #
    # SUPUESTO EXPLÍCITO DEL PMV: la plantilla actual (80 FTE, reparto fijo
    # por rol) está dimensionada para operar al 60 % de su capacidad a 48 h
    # en una semana PROMEDIO de su formato. (Se probó 85 %: con turnos
    # fijos de 8 h y fines de semana +50 % la tienda se quedaba sin gente
    # en la apertura; 60 % deja la tienda cubierta todos los días y aun así
    # en 2030, a 40 h, la plantilla ya no alcanza sin horas extra.) Estos factores (calculados
    # sobre 13 semanas repartidas en 2026, 50 tiendas) escalan la demanda
    # por rol y formato para cumplir ese supuesto. Semanas pico (quincena,
    # Buen Fin, Navidad) quedan por arriba -- ahí aparece horas extra.
    # Recalibrar con datos reales en Fase 1.
    "utilizacion_objetivo": 0.60,
    "factor_calibracion": {
        "chico": {"cajas": 1.42, "piso_reposicion": 2.8, "perecederos": 1.72, "almacen": 1.59},
        "mediano": {"cajas": 1.07, "piso_reposicion": 1.84, "perecederos": 1.15, "almacen": 1.15},
        "grande": {"cajas": 0.92, "piso_reposicion": 1.3, "perecederos": 0.82, "almacen": 0.88},
    },
    "almacen_extendido": {
        "horas_extra_preapertura": 1,
        "horas_extra_postcierre": 1,
        "minimo_personas": 3,  # SUPUESTO: cuadrilla mínima de reposición/arqueo
    },
}

_SLOT_INICIO = int(getattr(reglas, "SLOT_HORA_INICIO", 6))
_SLOT_FIN = int(getattr(reglas, "SLOT_HORA_FIN", 23))

_ROLES_AREA = ("piso_reposicion", "perecederos", "almacen")


def _erlang_c_prob_espera(n_servidores: int, intensidad_erlangs: float) -> float:
    """Probabilidad de que un cliente tenga que esperar (fórmula de Erlang C).

    Implementación directa de la fórmula clásica de Erlang C, sin
    dependencias externas. ``intensidad_erlangs`` es A = lambda/mu
    (tráfico ofrecido, en Erlangs). Requiere n_servidores > intensidad
    para que el sistema sea estable; si no, regresa 1.0 (siempre hay cola).
    """
    a = intensidad_erlangs
    n = n_servidores
    if n <= 0:
        return 1.0
    if a <= 0:
        return 0.0
    if n <= a:
        return 1.0  # sistema inestable: la cola crece sin límite

    # Erlang B recursivo (numéricamente estable) y de ahí Erlang C.
    erlang_b = 1.0
    for k in range(1, n + 1):
        erlang_b = (a * erlang_b) / (k + a * erlang_b)
    erlang_c = (n * erlang_b) / (n - a * (1 - erlang_b))
    return min(max(erlang_c, 0.0), 1.0)


def personas_requeridas_cajas(
    trafico_hora: int,
    num_cajas_fisicas: int,
    tiempo_atencion_seg: float = CONFIG["cajas"]["tiempo_atencion_seg_default"],
    espera_max_min: float = CONFIG["cajas"]["espera_max_min_default"],
) -> int:
    """Cajeros necesarios en una hora, vía Erlang C, acotado por cajas físicas.

    Encuentra el menor número de cajas abiertas tal que la probabilidad de
    que un cliente espere más de ``espera_max_min`` no exceda el nivel de
    servicio objetivo (CONFIG["cajas"]["nivel_servicio_objetivo"]). Nunca
    excede ``num_cajas_fisicas`` (tope físico de la tienda) ni es negativo.
    """
    if trafico_hora <= 0:
        return 0
    if num_cajas_fisicas <= 0:
        return 0

    mu_por_hora = 3600.0 / tiempo_atencion_seg  # clientes/hora que atiende 1 caja
    intensidad = trafico_hora / mu_por_hora     # Erlangs ofrecidos
    objetivo = CONFIG["cajas"]["nivel_servicio_objetivo"]

    n = max(1, math.ceil(intensidad))  # arranca en el mínimo estable
    while n < num_cajas_fisicas:
        prob_espera = _erlang_c_prob_espera(n, intensidad)
        # Probabilidad de esperar MÁS que espera_max_min, vía decaimiento
        # exponencial del tiempo de espera condicional (aproximación estándar).
        mu_efectivo = n * mu_por_hora - trafico_hora
        if mu_efectivo <= 0:
            prob_espera_larga = 1.0
        else:
            prob_espera_larga = prob_espera * math.exp(
                -mu_efectivo * (espera_max_min / 60.0)
            )
        if prob_espera_larga <= (1 - objetivo):
            break
        n += 1
    return min(n, num_cajas_fisicas)


def personas_requeridas_area(
    carga_trabajo: float,
    productividad_persona: float,
    area_abierta: bool = True,
    minimo_si_area_abierta: int = CONFIG["areas"]["minimo_si_area_abierta"],
) -> int:
    """Personas requeridas en un área genérica (piso, perecederos, almacén).

    ``carga_trabajo`` / ``productividad_persona`` redondeado hacia arriba,
    con un mínimo de cobertura si el área está operando esa hora
    (``area_abierta=True``). Si el área está cerrada, regresa 0 siempre.
    """
    if not area_abierta:
        return 0
    if productividad_persona <= 0:
        raise ValueError("productividad_persona debe ser > 0")
    requeridas = math.ceil(carga_trabajo / productividad_persona)
    return max(requeridas, minimo_si_area_abierta)


def _ventana_apertura(tienda_row: pd.Series) -> tuple[int, int]:
    apertura = max(int(tienda_row["hora_apertura"]), _SLOT_INICIO)
    cierre = min(int(tienda_row["hora_cierre"]), _SLOT_FIN)
    return apertura, cierre


def calcular_demanda_tienda(
    tienda_id: str,
    trafico_df: pd.DataFrame,
    ventas_df: pd.DataFrame,
    tiendas_df: pd.DataFrame,
) -> pd.DataFrame:
    """Demanda de personal (personas_requeridas) por fecha/hora/rol, 1 tienda.

    Dentro de la ventana real de apertura de la tienda: calcula cajas vía
    Erlang C sobre el tráfico, y piso/perecederos/almacén vía carga de
    trabajo (tickets * factor_por_rol) / productividad. Fuera de la
    ventana, demanda = 0, EXCEPTO almacén, que tiene una ventana extendida
    (pre-apertura/post-cierre) para reposición y arqueo, con una cuadrilla
    mínima fija (CONFIG["almacen_extendido"]).
    """
    tienda_row = tiendas_df.loc[tiendas_df["tienda_id"] == tienda_id].iloc[0]
    apertura, cierre = _ventana_apertura(tienda_row)
    pre = CONFIG["almacen_extendido"]["horas_extra_preapertura"]
    post = CONFIG["almacen_extendido"]["horas_extra_postcierre"]
    hora_ini_almacen = max(apertura - pre, _SLOT_INICIO)
    hora_fin_almacen = min(cierre + post, _SLOT_FIN)

    trafico = trafico_df.loc[trafico_df["tienda_id"] == tienda_id].copy()
    ventas = ventas_df.loc[ventas_df["tienda_id"] == tienda_id].copy()
    datos = trafico.merge(ventas[["tienda_id", "fecha", "hora", "tickets"]],
                           on=["tienda_id", "fecha", "hora"], how="left")
    datos["tickets"] = datos["tickets"].fillna(0)

    factores = CONFIG["areas"]["factor_carga_por_ticket"]
    productividad = CONFIG["areas"]["productividad_por_persona_hora"]
    minimo_area = CONFIG["areas"]["minimo_si_area_abierta"]
    minimo_almacen_extra = CONFIG["almacen_extendido"]["minimo_personas"]

    filas: list[dict] = []
    for row in datos.itertuples(index=False):
        hora = int(row.hora)
        en_ventana_normal = apertura <= hora < cierre
        en_ventana_almacen = hora_ini_almacen <= hora < hora_fin_almacen

        # Cajas: solo dentro de la ventana normal.
        req_cajas = (
            personas_requeridas_cajas(int(row.clientes_estimados),
                                       int(tienda_row["num_cajas_fisicas"]))
            if en_ventana_normal else 0
        )
        filas.append({"tienda_id": tienda_id, "fecha": row.fecha, "hora": hora,
                       "rol": "cajas", "personas_requeridas": req_cajas})

        for rol in ("piso_reposicion", "perecederos"):
            carga = float(row.tickets) * factores[rol]
            req = personas_requeridas_area(
                carga, productividad[rol], area_abierta=en_ventana_normal,
                minimo_si_area_abierta=minimo_area,
            )
            filas.append({"tienda_id": tienda_id, "fecha": row.fecha, "hora": hora,
                           "rol": rol, "personas_requeridas": req})

        # Almacén: ventana extendida (pre-apertura/post-cierre incluidos).
        carga_almacen = float(row.tickets) * factores["almacen"]
        if en_ventana_normal:
            req_almacen = personas_requeridas_area(
                carga_almacen, productividad["almacen"], area_abierta=True,
                minimo_si_area_abierta=minimo_area,
            )
        elif en_ventana_almacen:
            req_almacen = minimo_almacen_extra
        else:
            req_almacen = 0
        filas.append({"tienda_id": tienda_id, "fecha": row.fecha, "hora": hora,
                       "rol": "almacen", "personas_requeridas": req_almacen})

    demanda = pd.DataFrame(filas)
    factores_cal = CONFIG["factor_calibracion"].get(str(tienda_row.get("formato", "")), {})
    if factores_cal and not demanda.empty:
        f = demanda["rol"].map(factores_cal).fillna(1.0)
        demanda["personas_requeridas"] = [
            int(math.ceil(v * k - 1e-9)) if v > 0 else 0
            for v, k in zip(demanda["personas_requeridas"], f)
        ]
    return demanda


def _worker_demanda_tienda(args: tuple) -> pd.DataFrame:
    tienda_id, trafico_df, ventas_df, tiendas_df = args
    return calcular_demanda_tienda(tienda_id, trafico_df, ventas_df, tiendas_df)


def calcular_demanda_red(
    trafico_df: pd.DataFrame,
    ventas_df: pd.DataFrame,
    tiendas_df: pd.DataFrame,
    max_workers: int = 8,
) -> pd.DataFrame:
    """Demanda de personal para TODAS las tiendas, resuelta en paralelo.

    Cada tienda es un cálculo independiente (no comparte estado), así que
    se reparte entre procesos con ProcessPoolExecutor. Concatena el
    resultado de calcular_demanda_tienda de las 50 tiendas.
    """
    tiendas_ids = list(tiendas_df["tienda_id"])
    args = [(tid, trafico_df, ventas_df, tiendas_df) for tid in tiendas_ids]
    resultados: list[pd.DataFrame] = []
    if max_workers <= 1 or len(tiendas_ids) <= 1:
        resultados = [_worker_demanda_tienda(a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            resultados = list(ex.map(_worker_demanda_tienda, args))
    return pd.concat(resultados, ignore_index=True)


def marcar_franjas_pico(demanda_df: pd.DataFrame, percentil: float = 0.8) -> pd.DataFrame:
    """Agrega la columna booleana ``es_pico`` (top (1-percentil) por tienda).

    Suma personas_requeridas de todos los roles por (tienda, fecha, hora) y
    marca es_pico=True para el ``1 - percentil`` de franjas con mayor
    demanda total de CADA tienda (candado anti-subdotación del optimizador).
    """
    totales = (demanda_df.groupby(["tienda_id", "fecha", "hora"])["personas_requeridas"]
               .sum().rename("total_tienda_franja").reset_index())
    umbral = (totales.groupby("tienda_id")["total_tienda_franja"]
              .transform(lambda s: s.quantile(percentil)))
    totales["es_pico"] = totales["total_tienda_franja"] >= umbral
    return demanda_df.merge(
        totales[["tienda_id", "fecha", "hora", "es_pico"]],
        on=["tienda_id", "fecha", "hora"], how="left",
    )
