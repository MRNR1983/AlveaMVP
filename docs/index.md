---
title: Alvea PMV
---

# Alvea PMV

PMV para el reto técnico de **ALVENA/AIvena** (Head of Product and Technology):
programación semanal de personal para 50 tiendas, cumpliendo la reforma de
40 horas (DOF 01-05-2026), con ahorro cuantificado en MXN frente al escenario
actual.

**App funcional (en vivo):** [alveamvp.streamlit.app](https://alveamvp.streamlit.app/)
**Repo (código completo):** [github.com/MRNR1983/AlveaMVP](https://github.com/MRNR1983/AlveaMVP)

**Login:** usuario + contraseña (el usuario ya dice el rol, no hay
selector aparte). Usuario `SADMIN`, `ADMIN-Z1`..`ADMIN-Z5` (por zona), o
`Man001`..`Man050` (un gerente por tienda) — contraseña **`3.14159265358`**
para cualquiera (primeros dígitos de π — público a propósito, ver README
para el detalle completo).

## Empieza aquí

- [Comparación contra el PDF del reto](comparacion_pdf.html)
- [Manual de uso (toda la app) + checklist de verificación](manual.html)
- [README — cómo correrlo, estructura, supuestos](https://github.com/MRNR1983/AlveaMVP/blob/main/README.md)
- [Guion de demo (45 min con el CEO/CFO)](guion_demo.html)
- [Registro de uso de herramientas agénticas](registro_agentic.html)

## Estado del PMV

- 96 pruebas unitarias, todas pasando; cada página verificada sin errores
  para Gerente, Admin de zona y Super Admin.
- Horario desde hoy hasta diciembre de 2030; la jornada legal de cada
  semana sale sola de su fecha (48 → 40 h).
- Optimizador con 4 turnos fijos por tienda; cambios manuales persona →
  turno, con bloqueo legal y calificación.
- Ahorro con las 50 tiendas: 29% en 2026 (50/50 ≥ 8%, pico 100% cubierto) y ~20% en 2030 (supuesto
  explícito: la plantilla actual opera al 60% de su capacidad en una semana
  promedio).
- **Pendiente de validación legal**: tramo de tiempo extra al triple
  (arts. 66/68 LFT reformados).
- Docker incluido pero no verificado en la sandbox de desarrollo.

## Fuera de alcance del PMV

Turnos nocturnos/mixtos, integración con nómina/registro electrónico de
jornada, pronóstico de demanda con ML, simulacros y préstamo de personal
entre tiendas (código conservado, sin interfaz). Detalle en el README.
