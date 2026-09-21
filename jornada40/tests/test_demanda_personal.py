"""Pruebas de jornada40/demanda_personal.py."""
from datetime import date

import pandas as pd
import pytest

from jornada40.datos_sinteticos import generar_tiendas, generar_trafico, generar_ventas
from jornada40.demanda_personal import (
    calcular_demanda_red,
    calcular_demanda_tienda,
    marcar_franjas_pico,
    personas_requeridas_area,
    personas_requeridas_cajas,
)

SEED = 42


def test_personas_requeridas_cajas_no_excede_fisicas():
    for trafico in (0, 10, 100, 500, 5000):
        req = personas_requeridas_cajas(trafico, num_cajas_fisicas=8)
        assert 0 <= req <= 8


def test_personas_requeridas_cajas_trafico_cero():
    assert personas_requeridas_cajas(0, num_cajas_fisicas=8) == 0


def test_personas_requeridas_area_cerrada_es_cero():
    assert personas_requeridas_area(100.0, 10.0, area_abierta=False) == 0


def test_personas_requeridas_area_carga_cero_respeta_minimo():
    assert personas_requeridas_area(0.0, 10.0, area_abierta=True,
                                     minimo_si_area_abierta=1) == 1


def _tiendas_prueba():
    tiendas = generar_tiendas(seed=SEED)
    tiendas.loc[tiendas.index[0], "hora_apertura"] = 7
    tiendas.loc[tiendas.index[0], "hora_cierre"] = 22
    return tiendas


def test_calcular_demanda_tienda_fuera_de_ventana_cajas_es_cero():
    tiendas = _tiendas_prueba()
    tienda_id = tiendas["tienda_id"].iloc[0]
    trafico = generar_trafico(tiendas, date(2027, 1, 3), date(2027, 1, 3), seed=SEED)
    ventas = generar_ventas(trafico, seed=SEED)
    demanda = calcular_demanda_tienda(tienda_id, trafico, ventas, tiendas)
    fuera = demanda[(demanda["hora"] == 3) & (demanda["rol"] == "cajas")]
    assert (fuera["personas_requeridas"] == 0).all()


def test_marcar_franjas_pico_aprox_20_por_ciento():
    tiendas = _tiendas_prueba()
    tienda_id = tiendas["tienda_id"].iloc[0]
    trafico = generar_trafico(tiendas, date(2027, 1, 3), date(2027, 1, 9), seed=SEED)
    ventas = generar_ventas(trafico, seed=SEED)
    demanda = calcular_demanda_tienda(tienda_id, trafico, ventas, tiendas)
    marcada = marcar_franjas_pico(demanda, percentil=0.8)
    franjas = marcada.drop_duplicates(["tienda_id", "fecha", "hora"])
    pct_pico = franjas["es_pico"].mean()
    assert 0.10 <= pct_pico <= 0.30


def test_calcular_demanda_red_dos_tiendas_no_vacia():
    tiendas = generar_tiendas(seed=SEED).head(2)
    trafico = generar_trafico(tiendas, date(2027, 1, 3), date(2027, 1, 4), seed=SEED)
    ventas = generar_ventas(trafico, seed=SEED)
    demanda = calcular_demanda_red(trafico, ventas, tiendas, max_workers=2)
    assert not demanda.empty
    assert set(demanda["tienda_id"].unique()) == set(tiendas["tienda_id"])
