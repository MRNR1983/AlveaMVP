# Alvea contra el PDF del reto

Fuente: "Reto técnico — Head de Producto y Tecnología — AIvena" (PDF adjunto
al correo del 21-sep-2026). Cifras de la semana 20–26 sep 2026 (jornada
48 h) y 22–28 sep 2030 (jornada 40 h), 50 tiendas. El solver es determinista:
estas cifras son las mismas en la app en línea y en cualquier reinicio.

| Lo que pide el PDF | Cómo lo cumple Alvea | Estado |
| --- | --- | --- |
| Herramienta funcional que, con datos operativos de una tienda (tráfico, ventas, plantilla, turnos), genere la programación semanal | Horario semanal por tienda: 4 turnos fijos, cada persona asignada día por día | Cumple |
| a. Tope de 40 horas por empleado | El tope sale de la fecha de la semana: 48 h en 2026 → 40 h en 2030 (reducción escalonada del Decreto DOF 01-05-2026). La semana de 2030 opera a 40 h | Cumple (con la gradualidad de la ley; para mostrar 40 h en la demo, tocar la etiqueta "Jornada 48 h · 2026" y elegir 2030) |
| b. Cuantificar en MXN el costo evitado frente a la programación actual | "Rol fijo de hoy" contra "Con Alvea" en Horario (semana, día y su desglose) y Resumen | Cumple |
| ~50 tiendas, ~80 FTE por tienda, domingo a domingo | 50 tiendas × 80 personas; semana domingo–sábado | Cumple |
| Demostrar al menos 8% de ahorro en costo laboral total (horas extra y sobrestaffing evitados) | 2026: **29.0% en la red ($1,889,625), 50 de 50 tiendas ≥ 8%** (mínimo 22.9%). 2030: **21.7% ($1,519,383), 50 de 50 ≥ 8%** (mínimo 14.9%). Horario → "De dónde sale el ahorro" desglosa horas extra evitadas y gente de más evitada | Cumple |
| Sin caer en subdotación en horas pico | Cobertura pico como restricción dura, contada por área. **0 horas pico sin cubrir en las 50 tiendas, en 2026 y en 2030** | Cumple |
| Datos definidos por el candidato (sintéticos o públicos) | Archivos en `archivos/` (tiendas, plantilla y, por semana, tráfico, ventas y ausentismo), marca ficticia, con temporadas (quincena, Buen Fin, Navidad, regreso a clases) | Cumple |
| Automatizada: cualquiera del equipo la corre con datos de una tienda nueva sin operación manual | Página Datos: se sueltan los CSV (tienda nueva en Tiendas + Plantilla, sus semanas en Tráfico/Ventas/Ausentismo); Alvea los reconoce, los cruza por semana y recalcula solo lo que cambió | Cumple (la página Datos es de HQ) |
| Stack y formato libres ("lo que llevarías a un cliente el lunes") | App web en línea (Streamlit), roles por usuario, descargas CSV/TXT | Cumple |
| Trazabilidad de restricciones | Página Reglas legales: tabla año por año y trazabilidad de cada regla contra el Decreto, con lo pendiente de validar | Cumple |
| Entregable 1 — herramienta funcionando, accesible, reproducible, de extremo a extremo sin el candidato | alveamvp.streamlit.app + credenciales en README + repo público | Cumple |
| Entregable 2 — evidencia del proceso: repo, documentación, capturas, supuestos, decisiones, nota de trazabilidad, registro de herramientas agénticas | README, docs/tutoriales/ (con capturas), docs/manual.md, docs/registro_agentic.md, Reglas legales | Cumple |
| Entregable 3 — demo de 45 min con CFO/COO | docs/guion_demo.md | Listo |

## Riesgos que conviene decir en la demo

- La jornada de 40 h es gradual por ley: en 2026 el tope es 48 h. La
  herramienta ya proyecta 2027–2030; la semana de 2030 es la que muestra el
  tope de 40 h.
- El ahorro depende del supuesto de calibración: la plantilla actual opera al
  60% de su capacidad en una semana promedio. Con datos reales se recalibra.
- El tramo de horas extra al triple (art. 68) sigue pendiente de validar con
  un abogado laboral.
- Docker incluido, pero no probado fuera del entorno de desarrollo.
