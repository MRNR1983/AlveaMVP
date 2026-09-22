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
selector aparte). Usuario `ADMIN`, `SADMIN`, o `T001-U1` (tienda-cuenta,
para gerente) — contraseña **`3.14159265358`** para cualquiera (primeros
dígitos de π — público a propósito, ver README para el detalle completo).

## Empieza aquí

- [README — cómo correrlo, estructura, supuestos](https://github.com/MRNR1983/AlveaMVP/blob/main/README.md)
- [Guion de demo (45 min con el CEO/CFO)](guion_demo.html)
- [Registro de uso de herramientas agénticas](registro_agentic.html)

## Estado del PMV

- 62 pruebas unitarias, todas pasando.
- App Streamlit verificada extremo a extremo (sin excepciones en las 6 pantallas).
- **Pendiente antes de la demo real**: calibrar el ahorro (salió >60% en
  corridas chicas de prueba, hay que correr las 50 tiendas y revisar
  `demanda_personal.py` / `escenario_base.py`).
- **Pendiente de validación legal**: interpretación del tramo de tiempo
  extra al triple (arts. 66/68 LFT reformados).
- Docker incluido pero no verificado en la sandbox de desarrollo (sin
  demonio Docker disponible ahí) — verificar en local antes de la demo.

## Fuera de alcance del PMV

Traslado físico de personal entre tiendas como decisión legal, integración
con nómina/registro electrónico de jornada, pronóstico de demanda con ML,
horizonte de más de una semana. Detalle completo en el README.
