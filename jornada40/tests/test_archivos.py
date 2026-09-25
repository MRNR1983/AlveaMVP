"""Los datos son archivos: subir uno lo cruza con lo que hay, por semana y por tienda."""
from datetime import date, timedelta
import shutil

import pandas as pd
import pytest

from jornada40 import archivos, persistencia


@pytest.fixture
def capas(tmp_path, monkeypatch):
    base = tmp_path / "arranque"
    base.mkdir()
    for rel in ["tiendas.csv", "plantilla.csv"] + [f"{t}/2027-03-14.csv.gz" for t in archivos.SEMANALES]:
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(archivos.ARRANQUE / rel, base / rel)
    monkeypatch.setattr(archivos, "ARRANQUE", base)
    monkeypatch.setattr(archivos, "SUBIDOS", tmp_path / "subidos")
    monkeypatch.setattr(persistencia, "configurado", lambda: False)
    return tmp_path


def test_detecta_cada_archivo_por_sus_columnas():
    for tipo, info in archivos.TIPOS.items():
        assert archivos.detectar_tipo(pd.DataFrame(columns=info["columnas"])) == tipo
    assert archivos.detectar_tipo(pd.DataFrame(columns=["x", "y"])) is None


def test_subir_semana_11_cruza_solo_esa_tienda_y_esos_dias(capas):
    dom = date(2027, 3, 14)                      # semana 11 de 2027 (14-20 mar)
    antes = archivos.leer_semana(dom)
    h1_antes, h2_antes = archivos.huella(antes, "T001"), archivos.huella(antes, "T002")
    nuevo = antes["trafico"][(antes["trafico"]["tienda_id"] == "T001")
                             & (antes["trafico"]["fecha"] <= dom + timedelta(days=1))].copy()
    nuevo["clientes_estimados"] = nuevo["clientes_estimados"] * 2
    r = archivos.cruzar("trafico", nuevo)
    assert r["semanas"] == [dom] and r["reemplazadas"] == len(nuevo)

    despues = archivos.leer_semana(dom)
    t = despues["trafico"]
    assert len(t) == len(antes["trafico"])                              # nada se duplicó
    dom_t001 = t[(t["tienda_id"] == "T001") & (t["fecha"] == dom)]["clientes_estimados"].sum()
    assert dom_t001 == 2 * antes["trafico"][(antes["trafico"]["tienda_id"] == "T001")
                                            & (antes["trafico"]["fecha"] == dom)]["clientes_estimados"].sum()
    assert archivos.huella(despues, "T001") != h1_antes                 # T001 se recalcula
    assert archivos.huella(despues, "T002") == h2_antes                 # T002 queda igual

    assert archivos.restaurar_originales() >= 1
    assert archivos.huella(archivos.leer_semana(dom), "T001") == h1_antes


def test_tienda_nueva_entra_al_catalogo(capas):
    t = archivos.leer("tiendas")
    nueva = t[t["tienda_id"] == "T001"].assign(tienda_id="T051")
    r = archivos.cruzar("tiendas", nueva)
    assert r["nuevas"] == 1 and "T051" in set(archivos.leer("tiendas")["tienda_id"])


def test_semana_sin_archivos_se_reporta(capas):
    assert not archivos.semana_completa(archivos.leer_semana(date(2031, 1, 5)))
