"""Precalcula semanas de demo (50 tiendas) y las deja en precalculado/<version>/.

Uso:  python scripts/precalcular.py [AAAA-MM-DD ...]   (domingos; sin argumentos, las de la demo)
Es reanudable: salta las tiendas-semana que ya existen.
"""
from __future__ import annotations

import sys
import time
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jornada40 import datos_sinteticos, optimizador, precalculado, semana  # noqa: E402

TIEMPO_LIMITE_SEG = 10.0   # igual que app.TIEMPO_LIMITE_SEG
VERSION = optimizador.VERSION_MODELO
DEMO = ["2026-09-20", "2026-09-27", "2026-10-04",            # semanas actuales (48 h)
        "2027-09-19", "2028-09-24", "2029-09-23",            # a donde lleva el salto de año desde hoy
        "2030-09-22", "2030-09-29", "2030-10-06"]            # 40 h

_datos: dict = {}


def _datos_semana(domingo: date) -> dict:
    if domingo not in _datos:
        tiendas = datos_sinteticos.generar_tiendas(seed=42)
        plantilla = datos_sinteticos.generar_plantilla(tiendas, seed=42)
        d = datos_sinteticos.generar_semana(tiendas, plantilla, domingo, seed=42)
        norm = {}
        for n in ("trafico", "ventas", "ausentismo"):
            df = d[n].copy()
            df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
            norm[n] = df
        _datos[domingo] = {"tiendas": tiendas, "plantilla": plantilla, **norm}
    return _datos[domingo]


def _uno(args: tuple[str, date]) -> str:
    tid, dom = args
    t = time.time()
    _, prop, techo = semana.calcular(tid, dom, _datos_semana(dom), TIEMPO_LIMITE_SEG, VERSION,
                                     usar_precalculado=False)
    precalculado.guardar(VERSION, tid, dom, prop, techo)
    return f"{dom} {tid} {prop['status']} {time.time() - t:.0f}s"


def main() -> None:
    domingos = [date.fromisoformat(x) for x in (sys.argv[1:] or DEMO)]
    tiendas = datos_sinteticos.generar_tiendas(seed=42)["tienda_id"].tolist()
    tareas = [(t, d) for d in domingos for t in tiendas
              if not (precalculado.CARPETA / VERSION / f"{d.isoformat()}_{t}.pkl.gz").exists()]
    print(f"{len(tareas)} tienda-semanas por calcular (versión {VERSION})", flush=True)
    with Pool(2) as pool:
        for i, msg in enumerate(pool.imap_unordered(_uno, tareas), 1):
            print(f"[{i}/{len(tareas)}] {msg}", flush=True)


if __name__ == "__main__":
    main()
