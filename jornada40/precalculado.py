"""Semanas ya resueltas por el optimizador, guardadas en el repo.

El optimizador tarda ~25 s por tienda y semana. Para la demo (semanas de
2026 y de 2030) los resultados se precalculan con ``scripts/precalcular.py``
y viajan en ``precalculado/<version_modelo>/``: la app los abre al instante y,
como el solver es determinista, dan exactamente lo mismo que calcularlos.
Solo aplican con los datos de ejemplo (si HQ sube sus archivos, se recalcula).
"""
from __future__ import annotations

import gzip
import pickle
from datetime import date
from pathlib import Path

from jornada40 import optimizador

CARPETA = Path(__file__).resolve().parent.parent / "precalculado"


def _ruta(version: str, tienda_id: str, domingo: date) -> Path:
    return CARPETA / version / f"{domingo.isoformat()}_{tienda_id}.pkl.gz"


def _compactar(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "horario_df"}   # se reconstruye de turnos_df


def _expandir(res: dict) -> dict:
    res = dict(res)
    res["horario_df"] = optimizador.turnos_a_horario(res["turnos_df"])
    return res


def guardar(version: str, tienda_id: str, domingo: date, propuesta: dict, techo: dict) -> None:
    ruta = _ruta(version, tienda_id, domingo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(ruta, "wb") as f:
        pickle.dump({"propuesta": _compactar(propuesta), "techo": _compactar(techo)}, f)


def cargar_existe(version: str, tienda_id: str, domingo: date) -> bool:
    return _ruta(version, tienda_id, domingo).exists()


def cargar(version: str, tienda_id: str, domingo: date) -> tuple[dict, dict] | None:
    ruta = _ruta(version, tienda_id, domingo)
    if not ruta.exists():
        return None
    try:
        with gzip.open(ruta, "rb") as f:
            d = pickle.load(f)
        return _expandir(d["propuesta"]), _expandir(d["techo"])
    except Exception:
        return None
