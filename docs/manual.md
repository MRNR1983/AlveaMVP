# Manual de Alvea (PMV)

Alvea arma el horario semanal de cada tienda de Autoservicio MX (marca
ficticia, datos 100% sintéticos), cumple la jornada legal de cada año de
la reforma (48 h en 2026 → 40 h en 2030) y dice cuánto se ahorra frente al
rol fijo con el que se programa hoy.

App en línea: https://alveamvp.streamlit.app · Contraseña de todas las
cuentas: `3.14159265358`

## 1. Cómo se usa: un tutorial por rol

| Rol | Usuario | Páginas | Tutorial |
| --- | --- | --- | --- |
| Gerente de tienda | `Man001` … `Man050` | Horario · Avisos | [gerente.md](tutoriales/gerente.md) |
| Admin de zona | `ADMIN-Z1` … `ADMIN-Z5` | Resumen · Horario · Avisos · Usuarios | [admin.md](tutoriales/admin.md) |
| Super Admin (HQ) | `SADMIN` | Lo mismo para las 50 tiendas + Ver como · Reglas legales · Datos | [sadmin.md](tutoriales/sadmin.md) |

Cada página tiene un solo trabajo: **Horario** es la operación y el dinero de
una tienda (semana, día, mes, descargas y de dónde sale el ahorro);
**Resumen** es la zona o la red; **Avisos** es lo que requiere atención y el
historial; **Usuarios** es quién entra. Solo el gerente cambia turnos.

## 2. Cómo se calcula

- **Rol fijo de hoy (base)**: 80 personas en 3 turnos rotativos fijos;
  donde falta gente se alarga el turno con horas extra.
- **Alvea**: cada tienda tiene 4 turnos fijos de 8 h con arranques
  repartidos entre la apertura y el cierre; cualquier turno puede
  extenderse 2 h (tiempo extra legal, máx. 3 días por semana y persona).
  El cálculo va en dos pasos:
  1. **Cuántos**: un modelo por área (Cajas, Piso, Perecederos, Almacén)
     decide cuántas personas van a cada turno cada día y cuántas descansan
     a cada hora. Las horas pico se cubren siempre (restricción dura). Es
     exacto y se resuelve al óptimo en segundos.
  2. **Quiénes**: un segundo modelo exacto reparte los nombres sin tocar
     días de ausencia, con máx. 6 días trabajados y repartiendo las
     extensiones para no pagar extra de más.
  El costo se calcula sobre el horario final con nombres, pagando las horas
  en orden legal (ordinarias → dobles → triples).
- **Techo teórico**: el mismo modelo sin penalizar exceso ni déficit
  fuera de pico; sirve para decir qué parte del ahorro posible se captura.
- **Valor hora** = salario diario ÷ (jornada semanal ÷ 6). A menor jornada
  legal, mayor valor hora: el salario semanal no baja.

**Supuestos a calibrar con datos reales**
- La plantilla actual (80 FTE, reparto fijo por área) opera al **60% de su
  capacidad a 48 h en una semana promedio**. Sin este supuesto la demanda
  sintética era tan baja que el ahorro salía en 50–70% (irreal).
- Tiempo de atención en caja, productividad por área y temporadas
  (quincena, Buen Fin, Navidad, regreso a clases) — ver `CONFIG` en
  `demanda_personal.py` y `datos_sinteticos.py`.
- El tramo de horas extra al triple (art. 68) está pendiente de validación
  legal.

**Qué esperar de los números** (50 tiendas): en 2026 (48 h) la red ahorra
29% y todas las tiendas pasan el 8%, sin horas pico descubiertas; el ahorro
sale sobre todo de no tener gente de más (sobrestaffing) y de no pagar
horas extra. En 2030 (40 h) baja a 21.7%: menos horas ordinarias por persona
encarecen la semana, pero las 50 tiendas siguen arriba de 8% y con el pico
cubierto — el efecto de la reforma que el CFO necesita ver.

## 3. Límites conocidos

- Turnos nocturnos/mixtos (7 y 7.5 h) no se modelan; todos son de 8 h.
- Los archivos que HQ sube en **Datos** aplican a su sesión; los demás
  usuarios siguen viendo los datos de ejemplo.
- Sin el secreto `github_token` en Streamlit Cloud, historial, avisos y
  cambios de turno se pierden si la app se reinicia (ver README).
- Una semana no precalculada tarda ~25 s por tienda la primera vez.
- Si una semana no tiene forma de cubrir todo el pico con la plantilla,
  el optimizador entrega el mejor horario posible y lo reporta en **Hora
  pico** en lugar de fallar.
- El tramo de horas extra al triple (art. 68) está pendiente de
  validación legal.

## 4. Lo que se probó (navegador, clic por clic)

| Rol | Qué se probó | Resultado |
| --- | --- | --- |
| Gerente | Login; Semana (3 cifras, descargas, de dónde sale el ahorro); salto a 2030; Día; cambio de turno en 2 pasos con calificación "No recomendado" y Deshacer; gráfica de cobertura que se abre sola; Mes; Avisos; Mi correo con validación; Privacidad y términos; Cerrar sesión | OK |
| Gerente | Cambio ilegal (7.º día) bloqueado con el motivo; 5 contraseñas malas = bloqueo de 5 min | OK |
| Admin CDMX | Resumen de su zona; aviso del cambio del gerente con **Ver día** (ve el cambio guardado); historial; Usuarios | OK |
| Super Admin | Resumen de 50 tiendas 2026 y 2030 al instante (precalculadas); Ver como; Reglas legales; Datos con una tienda nueva (T051) y +40% de tráfico: se recalcula y T051 aparece con horario legal y pico cubierto | OK |
| Celular (390 px) | Sin scroll horizontal; cifras en 2 columnas | OK |
| Automáticas | 99 pruebas (`pytest jornada40/tests`), incluidas solver determinista, calificación por área y respaldo en GitHub simulado | Pasan |
