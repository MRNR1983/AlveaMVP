from datetime import date

import pandas as pd

from jornada40 import archivos, cuentas


def test_registro_y_login(tmp_path):
    vacio = cuentas.cargar(tmp_path)
    assert cuentas.validar_registro("a@b.mx", "Ana", "Acme", "12345678", "12345678", vacio) is None
    assert cuentas.validar_registro("a@b", "Ana", "Acme", "12345678", "12345678", vacio)
    assert cuentas.validar_registro("a@b.mx", "Ana", "Acme", "123", "123", vacio)
    assert cuentas.validar_registro("a@b.mx", "Ana", "Acme", "12345678", "87654321", vacio)
    c = cuentas.crear(tmp_path, "Ana@B.mx ", "Ana López", "Acme", "12345678")
    assert c["ob"] == "1" and len(c["espacio"]) == 12
    df = cuentas.cargar(tmp_path)
    assert "12345678" not in df.to_csv()                       # nunca el texto de la contraseña
    assert cuentas.verificar(tmp_path, "ana@b.mx", "12345678")["nombre"] == "Ana López"
    assert cuentas.verificar(tmp_path, "ana@b.mx", "otra-cosa") is None
    assert cuentas.validar_registro("ANA@b.mx", "Ana", "Acme", "12345678", "12345678", df)   # repetido
    cuentas.fijar_paso(tmp_path, "ana@b.mx", 0)
    assert cuentas.buscar(tmp_path, "ana@b.mx")["ob"] == "0"


def test_espacio_propio_no_toca_la_demo_y_se_vacia(tmp_path, monkeypatch):
    monkeypatch.setattr(archivos, "SUBIDOS", tmp_path / "demo")
    dom = date(2026, 10, 4)
    antes_demo = len(archivos.leer("tiendas"))
    archivos.usar_espacio(tmp_path / "cuenta")
    try:
        assert len(archivos.leer("tiendas")) == antes_demo            # arranca con los de ejemplo
        archivos.cruzar("tiendas", archivos.leer("tiendas").head(1).assign(num_cajas_fisicas=99))
        assert (tmp_path / "cuenta" / "tiendas.csv").exists()
        assert archivos.vaciar() == 1
        assert archivos.vacio() and archivos.leer("tiendas").empty
        assert not archivos.semana_completa(archivos.leer_semana(dom))
        archivos.cruzar("tiendas", pd.DataFrame([{"tienda_id": "X1", "cluster_id": "Nuevo", "formato": "chico",
                                                   "hora_apertura": 8, "hora_cierre": 22, "num_cajas_fisicas": 5,
                                                   "fte_totales": 20}]))
        assert list(archivos.leer("tiendas")["tienda_id"]) == ["X1"]
        assert archivos.restaurar_originales() == 1 and not archivos.vacio()
        assert len(archivos.leer("tiendas")) == antes_demo
    finally:
        archivos.usar_espacio(None)
    assert not (tmp_path / "demo").exists()                           # la demo no se tocó
