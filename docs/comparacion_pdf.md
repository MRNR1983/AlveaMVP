# Alvea contra el PDF del reto

Fuente: "Reto técnico — Head de Producto y Tecnología — AIvena" (PDF adjunto
al correo del 21-sep-2026). Cifras de la semana 20–26 sep 2026 (jornada
48 h) y de una semana de junio 2030 (jornada 40 h), corriendo las 50 tiendas
con el optimizador actual.

| Lo que pide el PDF | Cómo lo cumple Alvea | Estado |
| --- | --- | --- |
| Herramienta funcional que, con datos operativos de una tienda (tráfico, ventas, plantilla, turnos), genere la programación semanal | Horario semanal por tienda: 4 turnos fijos, cada persona asignada día por día | Cumple |
| a. Tope de 40 horas por empleado | El tope sale de la fecha de la semana: 48 h en 2026 → 40 h en 2030 (reducción escalonada del Decreto DOF 01-05-2026). La semana de 2030 opera a 40 h | Cumple (con la gradualidad de la ley; para mostrar 40 h en la demo, avanzar a una semana de 2030) |
| b. Cuantificar en MXN el costo evitado frente a la programación actual | "Rol fijo de hoy" contra "Con Alvea" en Horario (semana y día), Mi tienda y Resumen | Cumple |
| ~50 tiendas, ~80 FTE por tienda, domingo a domingo | 50 tiendas × 80 personas; semana domingo–sábado | Cumple |
| Demostrar al menos 8% de ahorro en costo laboral total (horas extra y sobrestaffing evitados) | 2026: **29% en la red, 50 de 50 tiendas ≥ 8%** (mínimo 22.9%). 2030: **~20% en la red, todas ≥ 8%**. Mi tienda desglosa horas extra evitadas y sobrestaffing evitado | Cumple |
| Sin caer en subdotación en horas pico | Cobertura pico como restricción dura. 2026: **0 horas pico sin cubrir en las 50 tiendas**. 2030: 5 tiendas con faltantes chicos (22 h en total) donde el rol fijo tiene 968 h: la plantilla actual ya no alcanza a 40 h y la app lo muestra | Cumple en 2026; en 2030 lo reporta como hallazgo de la reforma |
| Datos definidos por el candidato (sintéticos o públicos) | Datos sintéticos con marca ficticia, calibrados (quincena, Buen Fin, Navidad, regreso a clases) | Cumple |
| Automatizada: cualquiera del equipo la corre con datos de una tienda nueva sin operación manual | Página Datos: descargar formato → subir CSV → la app recalcula sola | Cumple (hoy la página Datos es solo para HQ) |
| Stack y formato libres ("lo que llevarías a un cliente el lunes") | App web en línea (Streamlit), roles por usuario, descargas CSV/TXT | Cumple |
| Trazabilidad de restricciones | Página Reglas legales: tabla año por año y trazabilidad de cada regla contra el Decreto, con lo pendiente de validar | Cumple |
| Entregable 1 — herramienta funcionando, accesible, reproducible, de extremo a extremo sin el candidato | alveamvp.streamlit.app + credenciales en README + repo público | Cumple |
| Entregable 2 — evidencia del proceso: repo, documentación, capturas, supuestos, decisiones, nota de trazabilidad, registro de herramientas agénticas | README, docs/manual.md, docs/capturas/, docs/registro_agentic.md, Reglas legales | Cumple |
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
