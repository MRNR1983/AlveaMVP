"""Pruebas unitarias de jornada40/datos_sinteticos.py (dataset sintético)."""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from jornada40.datos_sinteticos import (
    CONFIG,
    generar_ausentismo,
    generar_dataset_completo,
    generar_plantilla,
    generar_tiendas,
    generar_trafico,
    generar_ventas,
)

SEED = 42
SEMANA_INI = date(2027, 1, 3)   # domingo
SEMANA_FIN = date(2027, 1, 9)   # sábado


def test_generar_tiendas_50_filas_ids_unicos():
    df = generar_tiendas(seed=SEED)
    assert len(df) == 50
    assert df["tienda_id"].is_unique
    assert df["tienda_id"].iloc[0] == "T001"
    assert df["tienda_id"].iloc[-1] == "T050"
    assert set(df["formato"].unique()) <= {"chico", "mediano", "grande"}
    assert (df["fte_totales"] == 80).all()
    assert (df["hora_cierre"] > df["hora_apertura"]).all()


def test_generar_plantilla_suma_80_por_tienda():
    tiendas = generar_tiendas(seed=SEED)
    plantilla = generar_plantilla(tiendas, seed=SEED)
    assert len(plantilla) == 50 * 80  # 4000 filas
    assert plantilla["empleado_id"].is_unique
    conteos = plantilla.groupby(["tienda_id", "rol"]).size().unstack(fill_value=0)
    esperado = pd.Series(CONFIG["plantilla"]["roles"])
    for _, fila in conteos.iterrows():
        assert fila.sum() == 80, "la suma de FTE por rol debe ser 80"
        for rol, n in esperado.items():
            assert fila[rol] == n, f"rol {rol} con conteo inesperado"


def test_generar_trafico_reproducible_con_misma_semilla():
    tiendas = generar_tiendas(seed=SEED)
    a = generar_trafico(tiendas, SEMANA_INI, SEMANA_FIN, seed=SEED)
    b = generar_trafico(tiendas, SEMANA_INI, SEMANA_FIN, seed=SEED)
    assert_frame_equal(a, b)


def _tercer_viernes_nov(anio: int) -> date:
    viernes = [d for d in range(1, 31) if date(anio, 11, d).weekday() == 4]
    return date(anio, 11, viernes[2])


def test_trafico_buen_fin_supera_a_domingo_normal_misma_tienda():
    tiendas = generar_tiendas(seed=SEED)
    anio = 2027
    bf_domingo = _tercer_viernes_nov(anio) + timedelta(days=2)
    domingo_normal = bf_domingo - timedelta(days=14)  # domingo sin temporada
    trafico = generar_trafico(tiendas, date(anio, 11, 1), date(anio, 11, 27), seed=SEED)
    tienda = "T001"

    def total(d: date) -> int:
        return int(trafico.loc[(trafico["tienda_id"] == tienda)
                               & (trafico["fecha"] == d), "clientes_estimados"].sum())

    assert total(bf_domingo) > total(domingo_normal), \
        "el multiplicador de temporada de Buen Fin no se aplicó"


def test_sin_negativos_ni_nan_en_columnas_numericas():
    tiendas = generar_tiendas(seed=SEED)
    trafico = generar_trafico(tiendas, SEMANA_INI, SEMANA_FIN, seed=SEED)
    ventas = generar_ventas(trafico, seed=SEED)
    plantilla = generar_plantilla(tiendas, seed=SEED)
    ausentismo = generar_ausentismo(plantilla, SEMANA_INI, SEMANA_FIN, seed=SEED)
    for nombre, df in {"tiendas": tiendas, "trafico": trafico, "ventas": ventas,
                       "plantilla": plantilla, "ausentismo": ausentismo}.items():
        assert not df.isna().any().any(), f"{nombre} contiene NaN"
        for col in df.select_dtypes(include=[np.number]).columns:
            assert (df[col] >= 0).all(), f"{nombre}.{col} contiene negativos"


def test_generar_ventas_deriva_de_trafico():
    tiendas = generar_tiendas(seed=SEED)
    trafico = generar_trafico(tiendas, SEMANA_INI, SEMANA_FIN, seed=SEED)
    ventas = generar_ventas(trafico, seed=SEED)
    assert len(ventas) == len(trafico)
    assert (ventas["tickets"] <= trafico["clientes_estimados"]).all()
    assert (ventas["monto_mxn"] >= 0).all()


def test_generar_dataset_completo_una_semana_escribe_5_csv(tmp_path):
    tablas = generar_dataset_completo(SEMANA_INI, SEMANA_FIN, seed=SEED, out_dir=tmp_path)
    assert set(tablas) == {"tiendas", "trafico", "ventas", "plantilla", "ausentismo"}
    for nombre in tablas:
        ruta = Path(tmp_path) / f"{nombre}.csv"
        assert ruta.exists(), f"falta {ruta}"
        assert len(pd.read_csv(ruta)) == len(tablas[nombre])
