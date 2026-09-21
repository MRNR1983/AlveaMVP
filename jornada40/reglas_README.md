# Motor de reglas laborales (`reglas.py`) — Guía para abogados laborales

## ¿Qué es esto?

Es la tabla viva de las reglas de jornada que usa el sistema de programación
de personal. En lugar de escribir las reglas "a mano" dentro del programa,
todas viven en una sola tabla con fecha de entrada en vigor, de modo que el
sistema aplica automáticamente la regla correcta según el año que se esté
programando. Si el Congreso publica una nueva reforma, solo se agrega una
línea a la tabla; no se toca el programa.

## Reglas vigentes (Decreto DOF 01-05-2026, reforma a la LFT)

| Regla | 2026 | 2027 | 2028 | 2029 | 2030 en adelante |
|---|---|---|---|---|---|
| Jornada ordinaria semanal (horas) | 48 | 46 | 44 | 42 | 40 |
| Tope semanal de tiempo extra al doble (horas) | 9 | 9 | 10 | 11 | 12 |

Reglas que no cambian por año (vigentes desde 2026):

- **Jornada diaria máxima (art. 61):** 8 h diurna, 7 h nocturna, 7.5 h mixta.
- **Días con tiempo extra por semana (art. 66):** máximo 4 días a la semana.
- **Jornada diaria total máxima (art. 68):** 12 horas (ordinaria + extra).
- **Descanso semanal (art. 69):** por cada 6 días trabajados, 1 de descanso
  con salario íntegro.
- **Prima dominical (art. 71):** 25 % del salario diario.
- **Pagos:** tiempo extra al doble (art. 66), al triple (art. 68), día de
  descanso trabajado al doble además del salario (art. 73) y día festivo
  trabajado al doble además del salario (art. 75).
- **Descanso intrajornada (art. 63):** media hora cuando la jornada es continua.

## Interpretación adoptada del art. 66/68 (tiempo extra) — PENDIENTE DE VALIDACIÓN LEGAL

**Esto es una convención de trabajo del proyecto, no una conclusión legal.**

El sistema modela el tiempo extra en dos tramos semanales:

1. **Tramo al doble:** las primeras horas extra de la semana se pagan al
   doble, con un tope que crece según la tabla anterior (9 → 12 horas).
2. **Tramo al triple:** por encima del tope al doble, se admite un tramo de
   **hasta 4 horas semanales** adicionales pagadas al triple.

El art. 68 LFT vigente limita el tiempo extraordinario por día y por semana
y prevé el pago al triple para las horas que exceden el tope semanal; el
Decreto de 2026 reforma esos topes de forma escalonada (Transitorio Cuarto).
La cifra concreta de "4 horas adicionales al triple" que usa el sistema es
**una convención adoptada por el equipo del PMV** para poder programar y
costear: no proviene de una frase literal del artículo y **debe ser validada
por asesoría legal** contra el texto publicado en el Diario Oficial de la
Federación, incluyendo el alcance exacto del segundo párrafo del art. 68
reformado y su interacción con el tope diario de 12 horas.

## Qué falta validar legalmente

- **PENDIENTE DE VALIDACIÓN LEGAL:** tramo al triple de 4 h/semana
  (interpretación descrita arriba).
- **PENDIENTE DE VALIDACIÓN LEGAL:** topes finales del art. 68 reformado
  (texto exacto del DOF 01-05-2026 y sus transitorios).
- **Alcance fuera del sistema:** el día de jornada electoral (art. 74, fr.
  IX) no se modela: depende del calendario electoral y quedó fuera del
  alcance del PMV de forma deliberada.
