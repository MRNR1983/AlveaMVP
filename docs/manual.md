# Manual de Alvea (PMV)

Alvea arma el horario semanal de cada tienda de Autoservicio MX (marca
ficticia, datos 100% sintéticos), cumple la jornada legal de cada año de
la reforma (48 h en 2026 → 40 h en 2030) y dice cuánto se ahorra frente al
rol fijo con el que se programa hoy.

App en línea: https://alveamvp.streamlit.app · Contraseña de todas las
cuentas: `3.14159265358`

---

## 1. Entrar

| Usuario | Quién es | Qué ve |
| --- | --- | --- |
| `Man001` … `Man050` | Gerente de una tienda | Horario, Mi tienda, Avisos |
| `ADMIN-Z1` … `ADMIN-Z5` | Admin de zona (CDMX, Occidente, Noreste, Centro, Sureste) | Resumen, Horario, Tienda, Avisos, Historial, Usuarios — solo de su zona |
| `SADMIN` | HQ | Todo lo anterior para las 50 tiendas + Reglas legales, Datos y "Ver como" |

Escribe usuario y contraseña → **Entrar**. Si la cuenta fue desactivada,
el login lo dice y no deja pasar (en cualquier sesión, al instante).

## 2. El menú lateral

- **Arriba**: la navegación de tu rol. La página activa queda resaltada.
  "Avisos · 3" indica avisos sin leer.
- **Abajo**: tu nombre y alcance, **Mi correo** (el correo al que te
  llegan avisos urgentes; se guarda para todas tus sesiones) y **Cerrar
  sesión**.
- **Ver como** (solo SADMIN, arriba del menú): muestra la app como la
  vería una zona o una tienda. Solo cambia lo que ves; tus permisos siguen
  siendo de HQ.

## 3. Una sola semana activa

Todas las páginas comparten la misma semana. Arranca en **la semana de
hoy** y se mueve con la barra de fechas:

`Hoy` · `‹` · `›` · título de la fecha · etiqueta **Jornada 48 h · 2026**

- **Hoy** regresa a la fecha actual desde cualquier vista.
- `‹` `›` avanzan un mes, una semana o un día según la vista.
- No se puede ir antes de la semana de hoy ni después de diciembre de 2030.
- La etiqueta azul dice qué jornada legal aplica a esa semana. Cambia
  sola: 48 h (2026), 46 (2027), 44 (2028), 42 (2029), 40 (2030). Si la
  semana cruza de año, aplica el tope del año nuevo (el más estricto).

## 4. Horario

Tres vistas, con el selector **Mes / Semana / Día** a la derecha. Admin y
SADMIN eligen la tienda en el selector de arriba a la derecha.

### Mes
Cuadrícula del mes. El día de hoy tiene borde azul; los días pasados se
ven en gris y no se pueden abrir. Un punto verde marca las semanas que ya
abriste (quedan en memoria y se abren al instante). **Toca un día** para ir
directo a su vista Día.

### Semana
Al abrirla se calcula (unos segundos la primera vez). Arriba, cinco cifras:

| Cifra | Qué significa |
| --- | --- |
| **Ahorro de la semana** | Pesos y % que se ahorran frente al rol fijo de hoy |
| Costo con este horario | Nómina de la semana con el horario de Alvea (y la de antes) |
| Personas con turno | Cuántas de las 80 trabajan al menos un día |
| Horas extra | Dobles + triples que el horario necesita (aparecen en años de jornada corta) |
| Horas pico sin cubrir | Horas-persona que faltan en las horas más cargadas. 0 = cobertura completa |

Debajo, los 7 días. Cada día muestra sus 4 turnos con su horario y cuántas
personas tiene cada uno. **Toca el nombre del día** para abrirlo.

### Día
- Cuatro cifras: personas trabajando, horas programadas (incluye 1 h de
  descanso pagado por persona), quién descansa y faltas previstas.
- **Cuatro columnas, una por turno**: color, nombre, horario, hora de
  descanso y cuántas personas; debajo, la lista de nombres con su área
  (Cajas, Piso, Perecederos, Almacén).
- **Cambiar a alguien de turno**: elige a la persona (se puede buscar
  escribiendo su nombre; al lado ves su turno actual) → elige el nuevo
  turno o **Descanso** → **Cambiar**.
  - Si el cambio rompe la ley (7 días seguidos o más horas que el máximo
    legal con extras), no se aplica y te dice por qué.
  - Si es legal, se aplica, la persona queda marcada en amarillo y arriba
    aparece la calificación: **Neutral** (no cambia costo ni cobertura),
    **Aceptable/Caro** (sube el costo), **Costoso** (manda a alguien a
    horas triples) o **No recomendado** (deja una hora pico sin cubrir).
  - **Deshacer** revierte el último cambio.
  - Si la calificación es Caro, Costoso o No recomendado, el admin de la
    zona recibe un aviso.
- **Cobertura por hora**: barras = personas trabajando (sin contar a
  quien está en su descanso); línea punteada = personas necesarias. Pasa
  el cursor para ver los números.

## 5. Mi tienda (Tienda para admin/HQ)

Para la semana activa: las mismas cinco cifras, un mensaje de si **cumple
la meta de 8%** y cuánto del ahorro máximo teórico se captura, y la tabla
**De dónde sale el ahorro** (horas ordinarias, extras dobles y triples, y
costo, antes vs. con Alvea).

Descargas: **Horario (CSV)** — una fila por persona y día con turno,
horario y descanso, ya con los cambios manuales — y **Reporte (TXT)** para
el CFO. **Cómo se calcula** explica el método y los supuestos.

## 6. Resumen (admin y HQ)

Ahorro de la semana activa en tu zona (admin) o en la red (HQ).

1. Si faltan tiendas por calcular, **Calcular N tiendas** las calcula con
   barra de progreso (cada tienda tarda unos segundos; las 50 toman varios
   minutos). Lo calculado queda en memoria.
2. Cifras: ahorro total, tiendas en meta (≥ 8%) y tiendas sin horario legal.
3. **Ahorro por tienda**: barras azules = en meta, naranjas = debajo de
   8%; la línea punteada es la meta. **Ver tabla** muestra el detalle.

## 7. Avisos

Se generan solos. Un aviso nuevo se ve en **negritas**; **Leído** lo
marca, y **Marcar N como leídos** los marca todos. Qué genera avisos:

| Evento | Quién lo recibe | Severidad |
| --- | --- | --- |
| Cambio manual calificado Caro/Costoso | Admin de la zona | Advertencia |
| Cambio manual No recomendado | Admin de la zona | Crítico |
| Cuenta desactivada / reactivada | El gerente de esa cuenta (y por correo si tiene) | Crítico / Info |

Los críticos también se mandan por correo cuando la cuenta tiene correo y
el servidor SMTP está configurado (Secrets de Streamlit Cloud).

## 8. Historial (admin y HQ)

Quién hizo qué y cuándo, dentro de tu alcance: inicios y cierres de
sesión, cambios de turno y su calificación, cálculos del Resumen, cuentas
activadas o desactivadas, correo actualizado y datos cargados. Filtra por
**Qué** y **Quién**; **Descargar (CSV)** exporta lo filtrado.

## 9. Usuarios (admin y HQ)

Una fila por tienda: usuario, tienda, **Activo** y **Correo**. Edita en la
tabla y pulsa **Guardar N cambio(s)**. Desactivar una cuenta la saca en
ese momento de cualquier sesión abierta y le avisa. Abajo se listan las
tiendas que quedaron sin acceso. Un admin solo ve las tiendas de su zona.

## 10. Reglas legales (HQ)

Tabla año por año (desde el año actual hasta 2030): jornada semanal, topes
de horas extra dobles y triples, y días máximos seguidos. Abajo, cuántas
reglas faltan de validar con un abogado laboral y la trazabilidad completa
contra el Decreto DOF 01-05-2026.

## 11. Datos (HQ)

1. **Descarga el formato** de cada archivo (tiendas, plantilla, tráfico
   por hora, ventas por hora, ausentismo).
2. **Sube tus archivos** en el mismo formato → **Usar mis archivos**.
   Lo que no subas se sigue tomando del ejemplo. **Volver al ejemplo**
   descarta lo subido.

---

## Cómo se calcula

- **Rol fijo de hoy (base)**: 80 personas en 3 turnos rotativos fijos;
  donde falta gente se alarga el turno con horas extra.
- **Alvea**: cada tienda tiene 4 turnos fijos de 8 h con arranques
  repartidos entre la apertura y el cierre, y descanso a mitad de turno
  escalonado (dos turnos nunca descansan a la misma hora). Cada día, cada
  persona entra a uno de esos turnos o descansa. El optimizador (OR-Tools
  CP-SAT) elige la combinación más barata que cumple:
  jornada semanal del año, 1 día de descanso por cada 6, topes de extras
  dobles y triples, ausencias previstas, y cobertura de las horas pico.
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

**Qué esperar de los números**: 2026 (48 h) ahorra ~11–21% por tienda, sobre
todo por evitar horas extra del rol fijo. En 2030 (40 h) el ahorro cae a
~6–8% porque la misma plantilla ya no alcanza sin horas extra — que es
justo el efecto de la reforma que el CFO necesita ver.

## Límites conocidos (honestos)

- Turnos nocturnos/mixtos (7 y 7.5 h) no se modelan; todos son de 8 h.
- Los cambios manuales viven en la sesión del navegador (no se guardan
  para otras personas); el historial sí queda registrado.
- Si una semana no tiene forma de cubrir todo el pico con la plantilla,
  el optimizador entrega el mejor horario posible y lo reporta en **Horas
  pico sin cubrir** en lugar de fallar.
- Simulacros y préstamo de personal entre tiendas se quitaron de la
  interfaz para mantenerla enfocada; el código y sus pruebas siguen en
  `simulacros.py`.

---

## Checklist de verificación (lo que se probó)

| # | Qué | Cómo se verificó | Resultado |
| --- | --- | --- | --- |
| 1 | 95 pruebas unitarias | `pytest jornada40/tests` | Pasan |
| 2 | Cada página carga sin errores para Gerente, Admin y SADMIN | AppTest de Streamlit, clic en cada entrada del menú | Sin excepciones |
| 3 | Login, menú por rol, usuario abajo, Cerrar sesión | Navegador | OK |
| 4 | Hoy / ‹ / › en Mes, Semana y Día | Navegador | OK |
| 5 | Semana calcula al abrir y muestra 4 turnos por día | Navegador | OK |
| 6 | Día: columnas por turno, gráfica de cobertura | Navegador | OK |
| 7 | Cambio de turno → calificación, marca amarilla, Deshacer | Navegador | OK |
| 8 | Cambio ilegal bloqueado (7.º día) | Prueba de lógica `validar_legal` | OK |
| 9 | Resumen de zona: calcular tiendas, gráfica, tabla | Navegador (zona Sureste) | OK |
| 10 | Mi tienda: cifras, meta 8%, tabla, descargas | Navegador | OK |
| 11 | Régimen cambia solo por año (48 → 40 h) | Semanas de 2026, 2027 y 2030 | OK |
| 12 | Nadie ausente queda con turno; ≤ 6 días por persona; 1 descanso por turno | Pruebas `test_turnos_fijos.py` | OK |
