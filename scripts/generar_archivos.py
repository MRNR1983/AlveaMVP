"""Escribe los archivos de arranque en archivos/ (tiendas, plantilla y, por semana,
tráfico, ventas y ausentismo) desde la semana DESDE hasta diciembre de 2030.

Uso: python scripts/generar_archivos.py [AAAA-MM-DD]   (domingo inicial; por omisión 2026-09-20)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jornada40 import archivos, datos_sinteticos  # noqa: E402

DESDE = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 9, 20)
HASTA = archivos.domingo_de(date(2030, 12, 31))


def main() -> None:
    raiz = archivos.ARRANQUE
    raiz.mkdir(parents=True, exist_ok=True)
    tiendas = datos_sinteticos.generar_tiendas(seed=42)
    plantilla = datos_sinteticos.generar_plantilla(tiendas, seed=42)
    tiendas[archivos.TIPOS["tiendas"]["columnas"]].to_csv(raiz / "tiendas.csv", index=False)
    plantilla[archivos.TIPOS["plantilla"]["columnas"]].to_csv(raiz / "plantilla.csv", index=False)
    dom, n = DESDE, 0
    while dom <= HASTA:
        sem = datos_sinteticos.generar_semana(tiendas, plantilla, dom, seed=42)
        sem["ausentismo"] = sem["ausentismo"][sem["ausentismo"]["ausente"]]   # solo quién falta
        for tipo in archivos.SEMANALES:
            p = raiz / tipo / f"{dom.isoformat()}.csv.gz"
            p.parent.mkdir(parents=True, exist_ok=True)
            sem[tipo][archivos.TIPOS[tipo]["columnas"]].to_csv(p, index=False, compression="gzip")
        dom += timedelta(days=7)
        n += 1
    print(f"{n} semanas escritas en {raiz}")


if __name__ == "__main__":
    main()
