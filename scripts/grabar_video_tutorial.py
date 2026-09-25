"""Graba el video tutorial de Alvea (3 roles) con subtítulos y cursor visible."""
import glob
import re
import sys
import time
from playwright.sync_api import sync_playwright

URL = "http://localhost:8599"
PW = "3.14159265358"
OUT = "/tmp/claude-0/video/raw"
W, H = 1440, 810
REPO = "/home/claude/AlveaMVP/archivos_para_subir/semana27sep_2026_cdmx_mas40/"
CALENTAR = "--calentar" in sys.argv

OVERLAY_JS = """
(() => {
  if (document.getElementById('tut-cap')) return;
  const st = document.createElement('style');
  st.textContent = `
    #tut-cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:78%;z-index:2147483646;
      background:rgba(20,20,22,.88);color:#fff;font:600 21px/1.35 -apple-system,'Inter','Segoe UI',sans-serif;
      padding:14px 22px;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.25);text-align:center;transition:opacity .25s;pointer-events:none}
    #tut-cap small{display:block;font-weight:500;font-size:15px;opacity:.75;margin-top:4px}
    #tut-tag{position:fixed;left:18px;top:14px;z-index:2147483646;background:#eb6834;color:#fff;
      font:700 13px/1 -apple-system,'Inter',sans-serif;padding:7px 11px;border-radius:999px;letter-spacing:.3px;pointer-events:none}
    #tut-cur{position:fixed;width:22px;height:22px;border-radius:50%;background:rgba(235,104,52,.35);
      border:2px solid #eb6834;z-index:2147483647;pointer-events:none;left:-40px;top:-40px;
      transition:left .55s ease,top .55s ease,transform .15s}
    #tut-full{position:fixed;inset:0;z-index:2147483645;background:#111;color:#fff;display:flex;flex-direction:column;
      align-items:center;justify-content:center;font-family:-apple-system,'Inter',sans-serif;text-align:center}
    #tut-full h1{font-size:64px;margin:0 0 12px;font-weight:800;letter-spacing:-1px;color:#fff !important}
    #tut-full p{font-size:24px;opacity:.85;margin:6px;color:#fff !important}`;
  document.head.appendChild(st);
  const c = document.createElement('div'); c.id = 'tut-cap'; c.style.opacity = 0; document.body.appendChild(c);
  const t = document.createElement('div'); t.id = 'tut-tag'; t.style.display = 'none'; document.body.appendChild(t);
  const k = document.createElement('div'); k.id = 'tut-cur'; document.body.appendChild(k);
})()
"""


def prep(pg):
    pg.evaluate(OVERLAY_JS)


def cap(pg, texto, sub="", seg=3.2):
    prep(pg)
    pg.evaluate("""([t, s]) => { const c = document.getElementById('tut-cap');
        c.innerHTML = t + (s ? '<small>' + s + '</small>' : ''); c.style.opacity = t ? 1 : 0; }""", [texto, sub])
    pg.wait_for_timeout(int(seg * 1000))


def tag(pg, texto):
    prep(pg)
    pg.evaluate("t => { const e = document.getElementById('tut-tag'); e.textContent = t; e.style.display = t ? 'block' : 'none'; }", texto)


def pantalla(pg, titulo, sub, seg=3.5):
    prep(pg)
    pg.evaluate("""([t, s]) => { let f = document.getElementById('tut-full'); if (!f) { f = document.createElement('div');
        f.id = 'tut-full'; document.body.appendChild(f); } f.style.display = 'flex';
        f.innerHTML = '<h1>' + t + '</h1>' + s.map(x => '<p>' + x + '</p>').join(''); }""", [titulo, sub])
    pg.wait_for_timeout(int(seg * 1000))
    pg.evaluate("() => { const f = document.getElementById('tut-full'); if (f) f.style.display = 'none'; }")


def quieto(pg, limite=300):
    t0 = time.time(); s = 0
    while time.time() - t0 < limite:
        c = pg.locator("[data-testid=stStatusWidget]").count() > 0
        s = 0 if c else s + 1
        if s >= 3:
            break
        pg.wait_for_timeout(300)
    prep(pg)


def señalar(pg, loc):
    loc.scroll_into_view_if_needed()
    bb = loc.bounding_box()
    if bb:
        pg.evaluate("([x, y]) => { const k = document.getElementById('tut-cur'); k.style.left = (x - 11) + 'px'; k.style.top = (y - 11) + 'px'; }",
                    [bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2])
        pg.wait_for_timeout(650)


def clic(pg, loc, espera=900):
    loc = loc.first
    señalar(pg, loc)
    pg.evaluate("() => { const k = document.getElementById('tut-cur'); k.style.transform = 'scale(.7)'; setTimeout(() => k.style.transform = '', 180); }")
    loc.click()
    pg.wait_for_timeout(espera); quieto(pg)


def lateral(pg, txt):
    clic(pg, pg.locator("section[data-testid=stSidebar] button").filter(has_text=txt))


def vista(pg, txt):
    clic(pg, pg.locator("[data-testid=stButtonGroup] button").filter(has_text=re.compile(rf"^{txt}$")))


def key(pg, frag):
    return pg.locator(f"[class*='st-key-{frag}'] button")


def escribir(pg, loc, texto):
    clic(pg, loc, 300)
    pg.keyboard.type(texto, delay=70); pg.wait_for_timeout(500)


def login(pg, usuario, subt):
    pg.goto(URL); pg.wait_for_timeout(3000); prep(pg)
    cap(pg, f"Entra con tu usuario: {usuario}", subt, 1.5)
    escribir(pg, pg.get_by_label("Usuario"), usuario)
    escribir(pg, pg.get_by_label("Contraseña"), PW)
    clic(pg, pg.get_by_role("button", name="Entrar"), 1500)


def ctx(b, nombre):
    if CALENTAR:
        return b.new_context(viewport={"width": W, "height": H})
    return b.new_context(viewport={"width": W, "height": H},
                         record_video_dir=f"{OUT}/{nombre}", record_video_size={"width": W, "height": H})


with sync_playwright() as p:
    b = p.chromium.launch()

    # ============ 1. GERENTE ============
    c1 = ctx(b, "1_gerente"); g = c1.new_page()
    g.goto(URL); g.wait_for_timeout(2500); prep(g)
    pantalla(g, "Alvea", ["Tutorial en 3 partes: Gerente de tienda · Admin de zona · Super Admin (HQ)",
                          "Horarios que cumplen la jornada legal de cada año (48 h en 2026 → 40 h en 2030)"], 5)
    tag(g, "1 · GERENTE DE TIENDA")
    login(g, "Man001", "Cada gerente ve solo su tienda (Man001 = tienda T001)")
    g.get_by_text("Hora pico").first.wait_for(timeout=200000); quieto(g)
    cap(g, "Horario → Semana: la semana de tu tienda", "Tienes dos páginas: Horario y Avisos", 3.5)
    señalar(g, g.locator(".tiles .tile").first)
    cap(g, "Ahorro de la semana contra el rol fijo de hoy", "Aquí se ven las dos bases: lo que cuesta hoy → lo que cuesta con Alvea", 4.5)
    señalar(g, g.locator(".tiles .tile").nth(1))
    cap(g, "Hora pico: cubierta en todas las áreas", "Si faltara gente en caja, piso, perecederos o almacén, aquí lo dice", 3.5)
    señalar(g, g.locator(".tiles .tile").nth(2))
    cap(g, "Horas extra con Alvea (0) contra las del rol fijo (170)", "", 3.2)
    señalar(g, g.locator("[class*='st-key-sem_2026-09-22']"))
    cap(g, "Cada día: cuántas personas van en cada uno de los 4 turnos y cuánto se ahorra", "", 3.8)
    clic(g, key(g, "navf_next_sem")); cap(g, "‹ › cambian de semana", "", 2.2)
    clic(g, key(g, "navf_hoy_sem")); cap(g, "Hoy te regresa a la semana actual", "", 2.2)
    clic(g, g.get_by_role("button", name="Jornada 48 h · 2026"), 700)
    cap(g, "La pastilla de jornada también salta de año", "48 h en 2026 → 40 h en 2030", 2.8)
    clic(g, g.get_by_role("button", name="2030 · 40 h"), 1200)
    g.get_by_role("button", name="Jornada 40 h · 2030").wait_for(timeout=200000); quieto(g)
    cap(g, "La misma tienda en 2030, con tope de 40 h", "Sigue sin dejar la hora pico sin gente", 4)
    clic(g, key(g, "navf_hoy_sem"))
    vista(g, "Día")
    cap(g, "Día: quién trabaja en cada turno, su hora de descanso y quién hace +2 h", "El color del punto es el área", 4.5)
    escribir(g, g.locator("[data-testid=stMain] [data-testid=stSelectbox]").nth(0), "Alejandra Rom")
    g.keyboard.press("Enter"); g.wait_for_timeout(900); quieto(g)
    cap(g, "Busca a una persona: Alvea dice dónde está hoy y la marca en la lista", "", 3.8)
    clic(g, g.locator("[data-testid=stMain] [data-testid=stSelectbox]").nth(1), 700)
    cap(g, "En «Mover a» solo aparecen los turnos donde no está, o Descanso", "", 3)
    clic(g, g.get_by_role("option", name="Descanso"), 1500)
    cap(g, "El cambio se aplica al elegirlo, y Alvea lo califica al instante", "«No recomendado»: deja 1 h de pico sin gente — tu admin de zona recibe un aviso", 5)
    exp = g.get_by_text(re.compile(r"^Cobertura por hora")).first
    señalar(g, exp); exp.scroll_into_view_if_needed(); g.wait_for_timeout(800)
    cap(g, "La gráfica de cobertura se abre sola y marca en naranja la hora que falta", "", 4.2)
    g.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); g.wait_for_timeout(900)
    clic(g, g.get_by_role("button", name="Deshacer"), 1200)
    cap(g, "Deshacer lo regresa como estaba", "", 2.6)
    vista(g, "Mes")
    cap(g, "Mes: cada día con personas y ahorro", "Franja verde = bien · naranja = falta gente en pico · amarillo = más caro que el rol fijo", 4.5)
    clic(g, key(g, "mes_2026-09-29"), 1000)
    cap(g, "Tocar un día abre ese día", "", 2.4)
    vista(g, "Semana")
    d = g.get_by_role("button", name="Horario (CSV)")
    señalar(g, d)
    cap(g, "Abajo: el horario en CSV para nómina y el reporte en TXT", "", 3.2)
    clic(g, g.get_by_text("De dónde sale el ahorro"), 1000)
    g.mouse.wheel(0, 380); g.wait_for_timeout(700)
    cap(g, "De dónde sale el ahorro: horas extra evitadas y gente de más evitada, en pesos", "", 4.5)
    g.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); g.wait_for_timeout(800)
    señalar(g, g.get_by_role("button", name="Mi correo"))
    cap(g, "Mi correo: a dónde te llegan los avisos · Privacidad y términos · Cerrar sesión", "", 3.5)
    c1.close()

    # ============ 2. ADMIN DE ZONA ============
    c2 = ctx(b, "2_admin"); a = c2.new_page()
    a.goto(URL); a.wait_for_timeout(2000); prep(a)
    pantalla(a, "Admin de zona", ["Vigila que las tiendas de su zona ahorren sin dejar el pico sin gente", "Páginas: Resumen · Horario · Avisos · Usuarios"], 4)
    tag(a, "2 · ADMIN DE ZONA")
    login(a, "ADMIN-Z1", "Una cuenta por zona (Z1 = CDMX, 12 tiendas)")
    a.get_by_text("Tiendas en meta").wait_for(timeout=200000); quieto(a)
    cap(a, "Resumen: ahorro de toda la zona y cuántas tiendas llegan a la meta de 8%", "", 4.2)
    a.mouse.wheel(0, 300); a.wait_for_timeout(600)
    cap(a, "Cada barra es una tienda; la línea punteada es la meta", "Las que no llegan saldrían en naranja", 3.8)
    a.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); a.wait_for_timeout(700)
    lateral(a, "Avisos")
    cap(a, "Avisos: aquí llegó el cambio «No recomendado» que hizo el gerente", "", 4)
    clic(a, a.get_by_role("button", name="Ver día"), 1500)
    a.get_by_text("Hora pico").first.wait_for(timeout=200000); quieto(a)
    cap(a, "«Ver día» abre ese día de esa tienda", "El admin ve el horario en lectura: los cambios los hace el gerente", 4.2)
    lateral(a, "Avisos")
    clic(a, a.get_by_text("Historial: quién hizo qué y cuándo"), 1000)
    cap(a, "Historial: quién hizo qué y cuándo en tus tiendas", "Se filtra por Qué y Quién, y se descarga en CSV", 4)
    lateral(a, "Horario")
    escribir(a, a.locator("[data-testid=stMain] [data-testid=stSelectbox]").first, "T009")
    a.keyboard.press("Enter"); a.wait_for_timeout(900); quieto(a)
    cap(a, "Horario de cualquier tienda de la zona: elígela arriba a la derecha", "", 3.8)
    lateral(a, "Usuarios")
    cap(a, "Usuarios: quita «Activo» para bloquear el acceso de una tienda, o cambia su correo", "", 4)
    c2.close()

    # ============ 3. SUPER ADMIN ============
    c3 = ctx(b, "3_sadmin"); s = c3.new_page()
    s.goto(URL); s.wait_for_timeout(2000); prep(s)
    pantalla(s, "Super Admin (HQ)", ["Las 50 tiendas, Ver como, Reglas legales y Datos"], 3.5)
    tag(s, "3 · SUPER ADMIN")
    login(s, "SADMIN", "")
    s.get_by_text("Tiendas en meta").wait_for(timeout=200000); quieto(s)
    cap(s, "Resumen de la red: 50 tiendas, $1,889,625 de ahorro esta semana (29%)", "50 de 50 tiendas arriba de la meta de 8%", 4.5)
    clic(s, s.get_by_role("button", name="Jornada 48 h · 2026"), 700)
    clic(s, s.get_by_role("button", name="2030 · 40 h"), 1500)
    s.get_by_role("button", name="Jornada 40 h · 2030").wait_for(timeout=200000); quieto(s)
    s.get_by_text("21.7%").wait_for(timeout=200000); quieto(s)
    cap(s, "En 2030, ya con 40 h: $1,519,383 (21.7%) y las 50 siguen en meta", "Las semanas de la demo abren al instante", 4.8)
    clic(s, key(s, "navf_hoy_res"))
    clic(s, s.locator("section[data-testid=stSidebar] [data-testid=stSelectbox]"), 900)
    cap(s, "Ver como: mira la app como una zona o una tienda, sin volver a entrar", "", 3.5)
    s.keyboard.press("Escape"); s.wait_for_timeout(500)
    lateral(s, "Reglas legales")
    cap(s, "Reglas legales: cómo baja la jornada año con año y la trazabilidad contra el Decreto", "", 4)
    lateral(s, "Horario")
    clic(s, key(s, "navf_next_sem")); s.get_by_text("Hora pico").first.wait_for(timeout=200000); quieto(s)
    cap(s, "Antes de subir archivos: T001, semana del 27 sep → $37,115 de ahorro", "", 4)
    lateral(s, "Datos")
    cap(s, "Datos: los 5 archivos con los que Alvea arma los horarios", "Tiendas, Plantilla y, por semana, Tráfico, Ventas y Ausentismo", 4.2)
    s.locator("input[type=file]").first.set_input_files(sorted(glob.glob(REPO + "*.csv")))
    s.wait_for_timeout(2500); quieto(s)
    s.mouse.wheel(0, 300); s.wait_for_timeout(600)
    cap(s, "Sueltas los CSV: Alvea reconoce cuál es por sus columnas y la semana por sus fechas", "Aquí: tráfico y ventas +40% para las 12 tiendas CDMX, semana del 27 sep", 5)
    clic(s, s.get_by_role("button", name=re.compile("Aplicar 2 archivos")), 1500)
    cap(s, "Aplicar: cada fila reemplaza solo lo mismo (misma tienda y día); lo demás se queda", "", 4)
    lateral(s, "Horario")
    s.get_by_text("Hora pico").first.wait_for(timeout=300000); quieto(s)
    cap(s, "T001 se recalcula con los archivos nuevos: $28,887 (21.4%) y el pico sigue cubierto", "Las tiendas que no venían en los archivos no cambian y abren al instante", 5.5)
    lateral(s, "Datos")
    clic(s, s.get_by_role("button", name=re.compile("Volver a los archivos originales")), 1000)
    cap(s, "«Volver a los archivos originales» quita todo lo subido", "", 3)
    clic(s, s.get_by_role("button", name="Sí, quitar lo subido"), 1500)
    s.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); s.wait_for_timeout(800)
    tag(s, "")
    cap(s, "", "", 0.3)
    pantalla(s, "Alvea", ["alveamvp.streamlit.app", "Contraseña de demo: 3.14159265358 · Man001…Man050 · ADMIN-Z1…Z5 · SADMIN"], 5)
    c3.close()
    b.close()
print("listo")
