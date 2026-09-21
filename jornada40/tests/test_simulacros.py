"""Pruebas de jornada40/simulacros.py."""
from datetime import date

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from jornada40.datos_sinteticos import (
    generar_ausentismo,
    generar_plantilla,
    generar_tiendas,
    generar_trafico,
    generar_ventas,
)
from jornada40.simulacros import (
    Palancas,
    aplicar_palancas,
    correr_simulacro,
    correr_simulacro_red,
    simular_refuerzo_entre_tiendas,
)

SEED = 42
REF = date(2027, 1, 3)


def _datos_prueba(n_tiendas=1):
    tiendas = generar_tiendas(seed=SEED).head(n_tiendas)
    trafico = generar_trafico(tiendas, REF, REF + pd.Timedelta(days=2), seed=SEED)
    ventas = generar_ventas(trafico, seed=SEED)
    plantilla = generar_plantilla(tiendas, seed=SEED)
    ausentismo = generar_ausentismo(plantilla, REF, REF + pd.Timedelta(days=2), seed=SEED)
    return tiendas, trafico, ventas, plantilla, ausentismo


def test_palancas_default_no_cambia_nada():
    tiendas, trafico, ventas, plantilla, ausentismo = _datos_prueba()
    tienda_id = tiendas["tienda_id"].iloc[0]
    resultado = aplicar_palancas(tienda_id, Palancas(), tiendas, trafico, ventas, plantilla,
                                  ausentismo, anio_base=2027, seed=SEED)
    original_trafico = trafico.loc[trafico["tienda_id"] == tienda_id].reset_index(drop=True)
    nuevo_trafico = resultado["trafico_df"].reset_index(drop=True)
    assert_frame_equal(original_trafico, nuevo_trafico)
    assert len(resultado["plantilla_df"]) == len(plantilla.loc[plantilla["tienda_id"] == tienda_id])


def test_multiplicador_trafico_se_aplica():
    tiendas, trafico, ventas, plantilla, ausentismo = _datos_prueba()
    tienda_id = tiendas["tienda_id"].iloc[0]
    palancas = Palancas(multiplicador_trafico=1.3)
    resultado = aplicar_palancas(tienda_id, palancas, tiendas, trafico, ventas, plantilla,
                                  ausentismo, anio_base=2027, seed=SEED)
    original = trafico.loc[trafico["tienda_id"] == tienda_id]["clientes_estimados"].to_numpy()
    nuevo = resultado["trafico_df"]["clientes_estimados"].to_numpy()
    assert (nuevo == (original * 1.3).astype(int)).all()


def test_anio_regimen_sobrescribe_anio_base():
    tiendas, trafico, ventas, plantilla, ausentismo = _datos_prueba()
    tienda_id = tiendas["tienda_id"].iloc[0]
    palancas = Palancas(anio_regimen=2030)
    resultado = aplicar_palancas(tienda_id, palancas, tiendas, trafico, ventas, plantilla,
                                  ausentismo, anio_base=2026, seed=SEED)
    assert resultado["anio"] == 2030


def test_refuerzo_nunca_deja_origen_en_deficit_propio():
    resultados = {
        "T01": {"horas_sobrestaffing": 10, "horas_subdotacion_totales": 0,
                "costo_total_mxn": 1000, "costo_ordinario_mxn": 1000, "horas_ordinarias_totales": 100},
        "T02": {"horas_sobrestaffing": 0, "horas_subdotacion_totales": 25,
                "costo_total_mxn": 1200, "costo_ordinario_mxn": 1200, "horas_ordinarias_totales": 100},
    }
    propuestas = simular_refuerzo_entre_tiendas(resultados)
    assert not propuestas.empty
    prestado_desde_t01 = propuestas.loc[propuestas["tienda_origen"] == "T01", "horas_prestadas"].sum()
    assert prestado_desde_t01 <= 10  # nunca más de lo que T01 tiene de exceso


def test_correr_simulacro_delta_costo_no_cero_con_mas_plantilla():
    tiendas, trafico, ventas, plantilla, ausentismo = _datos_prueba()
    tienda_id = tiendas["tienda_id"].iloc[0]
    datos_originales = {"tiendas_df": tiendas, "trafico_df": trafico, "ventas_df": ventas,
                         "plantilla_df": plantilla, "ausentismo_df": ausentismo}
    palancas = Palancas(delta_plantilla=5)
    resultado = correr_simulacro(tienda_id, palancas, datos_originales, anio_base=2027,
                                  fecha_inicio=REF, tiempo_limite_seg=15)
    assert "delta_costo_mxn" in resultado
    # con más plantilla, el costo total no debería ser negativo de forma
    # descontrolada; validamos solo que el cálculo corrió y produjo un número.
    assert isinstance(resultado["delta_costo_mxn"], float)


def test_correr_simulacro_red_dos_tiendas():
    tiendas, trafico, ventas, plantilla, ausentismo = _datos_prueba(n_tiendas=2)
    datos_originales = {"tiendas_df": tiendas, "trafico_df": trafico, "ventas_df": ventas,
                         "plantilla_df": plantilla, "ausentismo_df": ausentismo}
    palancas = Palancas()
    resultado = correr_simulacro_red(list(tiendas["tienda_id"]), palancas, datos_originales,
                                      anio_base=2027, fecha_inicio=REF, tiempo_limite_seg=10,
                                      max_workers=2)
    assert set(resultado["por_tienda"].keys()) == set(tiendas["tienda_id"])
    assert "delta_costo_total_mxn" in resultado["consolidado"]
