# Manual y criterios de aceptación — Vista de Calendario (Mes / Semana / Día)

**Módulo:** `app.py` — sección Calendario
**Último cambio:** commit `29ca882` (24-sep-2026)
**Commits relacionados:** `b0ed6b4` (fix layout de tarjetas), `29ca882` (rediseño + navegación)

---

## 1. Qué hace esta vista

El gerente de tienda (rol `manager`) entra a **Calendario** y navega en tres niveles:

`Mes → Semana → Día`

- **Mes**: cuadrícula del mes, cada día con punto azul si ya tiene cálculo de horario. Es navegación libre (no dispara cálculo).
- **Semana**: dispara el cálculo real de horario/ahorro para esa semana (botón "Calcular esta semana" si aún no existe). Muestra costo base, costo propuesto y % de ahorro.
- **Día**: muestra los turnos del día como tarjetas arrastrables (drag-and-drop) para reasignar empleados.

---

## 2. Criterios de aceptación

Estado: ✅ verificado en vivo · ⚠️ implementado pero no probado en vivo esta sesión · ❌ no implementado

### 2.1 Navegación entre fechas

| # | Criterio | Estado |
|---|----------|--------|
| 1 | En Semana, el botón ▶ avanza a la semana siguiente y recalcula el rango de fechas mostrado | ✅ |
| 2 | En Semana, el botón ◀ retrocede una semana | ⚠️ (mismo código que ▶, no probado el sentido inverso en vivo) |
| 3 | En Semana, el breadcrumb "‹ {Mes} {Año}" es clicable y regresa a la vista Mes | ⚠️ (implementado; solo probé el breadcrumb de Día→Semana) |
| 4 | En Día, el botón ▶ avanza al día siguiente, recalcula turnos y colores | ✅ |
| 5 | En Día, el botón ◀ retrocede un día | ⚠️ (mismo código que ▶, no probado el sentido inverso en vivo) |
| 6 | En Día, el breadcrumb "‹ Semana del ..." es clicable y regresa a la vista Semana | ✅ |
| 7 | Si el ◀/▶ de Día cruza un límite de semana (ej. sábado→domingo), la semana seleccionada internamente (`cal_semana_sel`) se recalcula para que el breadcrumb muestre la semana correcta | ⚠️ (lógica con `calendario.semana_de()`, no until se probó cruzando el límite) |

### 2.2 Diseño de tarjetas de turno (vista Día)

| # | Criterio | Estado |
|---|----------|--------|
| 8 | Cada turno se ve como una tarjeta con el horario en una banda superior de color y el nombre del empleado dentro de una casilla gris debajo | ✅ |
| 9 | Turnos normales (sin hueco) tienen banda **azul** | ✅ |
| 10 | Turnos partidos (con hueco) tienen banda **naranja** | ✅ |
| 11 | La casilla "Plantilla" (empleados sin turno hoy) tiene banda **gris**, ocupa todo el ancho y su cuerpo tiene borde punteado para distinguirla de un turno real | ✅ |
| 12 | Existe una leyenda de colores debajo del contador de turnos ("● turno normal · ● turno partido · ● Plantilla") | ✅ |
| 13 | Varias tarjetas caben por fila (no una por renglón completo) | ✅ (era el bug original, corregido en `b0ed6b4` y confirmado de nuevo aquí) |

### 2.3 Funcionalidad de arrastrar y soltar

| # | Criterio | Estado |
|---|----------|--------|
| 14 | Arrastrar un nombre desde "Plantilla" hacia una tarjeta de turno lo asigna a ese turno | ❌ no probado en vivo esta sesión |
| 15 | Si el turno ya tenía a alguien, el nuevo nombre queda asignado y el anterior se libera | ❌ no probado en vivo esta sesión |
| 16 | El buscador "Buscar empleado (nombre o ID)" resalta o localiza en qué turno está un empleado | ❌ no probado en vivo esta sesión (se vio en pantalla, no se usó) |

### 2.4 Cálculo semanal

| # | Criterio | Estado |
|---|----------|--------|
| 17 | "Calcular esta semana" corre el optimizador y muestra costo base, costo propuesto, % ahorro | ✅ |
| 18 | El cálculo persiste en `cache_calendario` mientras dure la sesión (no se recalcula al solo mirar el día) | ⚠️ (comportamiento esperado por diseño, no forzado un refresh de página para confirmarlo) |

### 2.5 Alcance no cubierto por esta sesión de pruebas

- Roles ADMIN / SADMIN (solo se probó como `manager`, tienda T001).
- Vista Mes con el nuevo esquema (no se tocó su CSS, pero tampoco se re-confirmó visualmente).
- Responsivo / móvil.
- Concurrencia (dos gerentes editando el mismo día a la vez).

---

## 3. Datos de acceso (entorno de demo)

- **Usuario:** `Man001`..`Man050` (uno por tienda), `ADMIN-Z1`..`ADMIN-Z5` (por zona), `SADMIN` (todo).
- **Contraseña:** `3.14159265358` (compartida por todas las cuentas — primeros dígitos de π, visible a propósito en `jornada40/usuarios.py` como fallback de demo). Si se configura `st.secrets["password_login"]` en Streamlit Cloud, esa pisa el fallback.

⚠️ **Nota de seguridad ya documentada en el propio código:** esta contraseña compartida es aceptada como brecha conocida para el PMV. Antes de cualquier uso con datos reales: mover a `st.secrets`, contraseñas individuales, hash y rate limit.

---

## 4. Siguiente paso recomendado

Antes de dar por "100% funcional" el rediseño completo, faltaría una pasada en vivo específicamente sobre:
1. Arrastrar y soltar un turno real (asignar y reasignar).
2. El buscador de empleado.
3. Los botones ◀ (retroceder) en Semana y Día — solo se probó ▶ en esta sesión.
4. Una cuenta ADMIN o SADMIN para confirmar que el rediseño no rompe nada en esas vistas.
