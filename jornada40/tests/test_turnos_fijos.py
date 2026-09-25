"""Pruebas del rediseño 24-sep-2026: catálogo fijo de turnos, datos por semana y calibración."""
from datetime import date

import pandas as pd
import pytest

from jornada40 import datos_sinteticos as ds
from jornada40 import demanda_personal as dp
from jornada40 import optimizador as op


@pytest.mark.parametrize("apertura,cierre", [(6, 23), (7, 23), (8, 22), (7, 16)])
def test_catalogo_cubre_la_ventana_y_descansos_no_coinciden(apertura, cierre):
    cat = op.catalogo_turnos(apertura, cierre)
    assert cat[0]["inicio"] == apertura
    assert cat[-1]["fin"] == cierre
    assert all(t["fin"] - t["inicio"] == 8 for t in cat)
    pausas = [t["pausa"] for t in cat]
    assert len(set(pausas)) == len(pausas), "dos turnos descansan a la misma hora"
    # Cada hora abierta la cubre al menos un turno que NO está en su descanso.
    for h in range(apertura, cierre):
        assert any(t["inicio"] <= h < t["fin"] and t["pausa"] != h for t in cat), h


def test_catalogo_tienda_corta_un_solo_turno():
    cat = op.catalogo_turnos(9, 15)
    assert len(cat) == 1 and cat[0]["inicio"] == 9 and cat[0]["fin"] == 15


@pytest.fixture(scope="module")
def semana_real():
    tiendas = ds.generar_tiendas(seed=42)
    plantilla = ds.generar_plantilla(tiendas, seed=42)
    dom = date(2026, 9, 20)
    sem = ds.generar_semana(tiendas, plantilla, dom)
    tid = "T001"
    tt = tiendas[tiendas.tienda_id == tid]
    pt = plantilla[plantilla.tienda_id == tid]
    nf = lambda df: df.assign(fecha=pd.to_datetime(df.fecha).dt.date)  # noqa: E731
    tr = nf(sem["trafico"]).query("tienda_id == @tid")
    ve = nf(sem["ventas"]).query("tienda_id == @tid")
    au = nf(sem["ausentismo"])
    au = au[au.empleado_id.isin(pt.empleado_id)]
    dem = dp.marcar_franjas_pico(dp.calcular_demanda_tienda(tid, tr, ve, tt))
    r = op.resolver_tienda(tid, 2026, pt, dem, au, tiempo_limite_seg=15, fecha_inicio=dom)
    return {"r": r, "au": au, "dem": dem, "pt": pt}


def test_propuesta_una_asignacion_por_persona_y_dia(semana_real):
    t = semana_real["r"]["turnos_df"]
    assert semana_real["r"]["status"] in ("OPTIMAL", "FEASIBLE")
    assert not t.duplicated(["empleado_id", "fecha"]).any()
    assert set(t["turno"]) <= set(op.NOMBRES_TURNO)


def test_propuesta_respeta_descanso_semanal_y_ausencias(semana_real):
    t = semana_real["r"]["turnos_df"]
    assert (t.groupby("empleado_id").size() <= 6).all()
    ausentes = semana_real["au"][semana_real["au"]["ausente"]]
    cruce = t.merge(ausentes, on=["empleado_id", "fecha"])
    assert cruce.empty, "alguien ausente quedó con turno"


def test_horario_por_hora_cuadra_con_turnos(semana_real):
    r = semana_real["r"]
    h = r["horario_df"]
    assert len(h) == int((r["turnos_df"]["hora_fin"] - r["turnos_df"]["hora_inicio"]).sum())
    # exactamente una hora de descanso por persona-día
    assert (h.groupby(["empleado_id", "fecha"])["en_pausa"].sum() == 1).all()


def test_tienda_nunca_abre_vacia(semana_real):
    """Con la calibración vigente, en toda hora con demanda hay al menos 1 persona."""
    r, dem = semana_real["r"], semana_real["dem"]
    h = r["horario_df"]
    cob = h[~h["en_pausa"]].groupby(["fecha", "hora"]).size()
    req = dem.groupby(["fecha", "hora"])["personas_requeridas"].sum()
    for (f, hr), v in req.items():
        if v > 0:
            assert cob.get((f, hr), 0) > 0, (f, hr)


def test_generar_semana_es_reproducible_y_de_7_dias():
    tiendas = ds.generar_tiendas(seed=42)
    plantilla = ds.generar_plantilla(tiendas, seed=42)
    a = ds.generar_semana(tiendas, plantilla, date(2028, 3, 5))
    b = ds.generar_semana(tiendas, plantilla, date(2028, 3, 5))
    pd.testing.assert_frame_equal(a["trafico"], b["trafico"])
    fechas = sorted(pd.to_datetime(a["trafico"]["fecha"]).dt.date.unique())
    assert fechas[0] == date(2028, 3, 5) and len(fechas) == 7


def test_calibracion_por_formato_definida_para_los_tres_formatos():
    cal = dp.CONFIG["factor_calibracion"]
    assert set(cal) == {"chico", "mediano", "grande"}
    for f in cal.values():
        assert set(f) == {"cajas", "piso_reposicion", "perecederos", "almacen"}
        assert all(v > 0 for v in f.values())


def test_descansos_personales_dentro_de_la_ventana_del_turno(semana_real):
    """Cada persona descansa en una de las horas permitidas de SU turno, y en
    un turno con varias personas los descansos se reparten (no todos a la vez)."""
    r = semana_real["r"]
    cat = {t["turno"]: t for t in r["catalogo_turnos"]}
    t = r["turnos_df"]
    assert all(row.hora_pausa in cat[row.turno]["pausas"] for row in t.itertuples())
    grupos = t.groupby(["fecha", "turno"])
    grandes = [g for _, g in grupos if len(g) >= 10]
    assert grandes and any(g["hora_pausa"].nunique() > 1 for g in grandes)


def test_calificacion_cuenta_pico_por_area():
    """Quitar al único de almacén en pico es 'No recomendado' aunque en total
    sobre gente de cajas: la calificación cuenta igual que la tarjeta (por área)."""
    from jornada40 import costos_ahorro
    f = date(2026, 9, 24)
    plantilla = pd.DataFrame({"empleado_id": ["A", "C1", "C2"], "rol": ["almacen", "cajas", "cajas"],
                              "salario_diario_mxn": [400.0] * 3})
    demanda = pd.DataFrame({"fecha": [f, f], "hora": [18, 18], "rol": ["almacen", "cajas"],
                            "personas_requeridas": [1, 1], "es_pico": [True, True]})
    h = lambda emps: pd.DataFrame({"empleado_id": emps, "fecha": f, "hora": 18,  # noqa: E731
                                   "trabajando": True, "en_pausa": False})
    res = costos_ahorro.calificar_edicion_manual(h(["A", "C1", "C2"]), h(["C1", "C2"]), plantilla, demanda, 2026)
    assert res["calificacion"] == "No recomendado"
