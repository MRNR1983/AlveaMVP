"""Barrido de TODOS los botones por tipo de usuario (Playwright). Uso: correr la app en :8599 y python scripts/barrido_botones.py"""
import re
import time
from playwright.sync_api import sync_playwright

URL = "http://localhost:8599"
PW = "3.14159265358"
R = []


def quieto(pg, limite=400):
    t0 = time.time(); s = 0
    while time.time() - t0 < limite:
        c = pg.locator("[data-testid=stStatusWidget]").count() > 0
        s = 0 if c else s + 1
        if s >= 4:
            return
        pg.wait_for_timeout(400)


def tit(pg):
    loc = pg.locator(".nav-titulo")
    return loc.first.inner_text() if loc.count() else ""


def err(pg):
    n = pg.locator("[data-testid=stException]").count()
    return f" · EXCEPCIÓN x{n}: " + pg.locator("[data-testid=stException]").first.inner_text()[:200] if n else ""


def paso(nombre, pg, cond, detalle=""):
    e = err(pg)
    ok = bool(cond) and not e
    R.append((ok, nombre, (detalle + e)[:240]))
    print(("OK   " if ok else "FALLA"), nombre, "|", (detalle + e)[:240], flush=True)


def btn_key(pg, frag):
    return pg.locator(f"[class*='st-key-{frag}'] button").first


def lateral(pg, txt):
    pg.locator("section[data-testid=stSidebar] button").filter(has_text=txt).first.click()
    pg.wait_for_timeout(700); quieto(pg)


def vista(pg, txt):
    pg.locator("[data-testid=stButtonGroup] button").filter(has_text=re.compile(rf"^{txt}$")).first.click()
    pg.wait_for_timeout(700); quieto(pg)


def entrar(b, u):
    pg = b.new_context(viewport={"width": 1491, "height": 812}, accept_downloads=True).new_page()
    pg.goto(URL); pg.wait_for_timeout(3500)
    pg.get_by_label("Usuario").fill(u); pg.get_by_label("Contraseña").fill(PW)
    pg.get_by_role("button", name="Entrar").click(); pg.wait_for_timeout(1500); quieto(pg)
    return pg


def navegacion(pg, rol, clave_sem="sem"):
    """Hoy, flechas, vistas y año en Horario."""
    lateral(pg, "Horario")
    t0 = tit(pg); paso(f"{rol} · Horario abre", pg, "sep 2026" in t0, t0)
    btn_key(pg, f"navf_next_{clave_sem}").click(); pg.wait_for_timeout(700); quieto(pg)
    t1 = tit(pg); paso(f"{rol} · › semana", pg, t1 != t0 and "oct" in t1, t1)
    btn_key(pg, f"navf_prev_{clave_sem}").click(); pg.wait_for_timeout(700); quieto(pg)
    t2 = tit(pg); paso(f"{rol} · ‹ semana", pg, t2 == t0, t2)
    vista(pg, "Día"); td = tit(pg); paso(f"{rol} · Día", pg, "septiembre" in td, td)
    btn_key(pg, "navf_next_dia").click(); pg.wait_for_timeout(700); quieto(pg)
    td2 = tit(pg); paso(f"{rol} · › día", pg, td2 != td, td2)
    btn_key(pg, "navf_prev_dia").click(); pg.wait_for_timeout(700); quieto(pg)
    paso(f"{rol} · ‹ día", pg, tit(pg) == td, tit(pg))
    vista(pg, "Mes"); tm = tit(pg); paso(f"{rol} · Mes", pg, "Septiembre 2026" in tm, tm)
    btn_key(pg, "navf_next_mes").click(); pg.wait_for_timeout(700); quieto(pg)
    btn_key(pg, "navf_next_mes").click(); pg.wait_for_timeout(700); quieto(pg)
    tm2 = tit(pg); paso(f"{rol} · › mes ×2", pg, "Noviembre 2026" in tm2, tm2)
    vista(pg, "Semana"); ts = tit(pg); paso(f"{rol} · Semana sigue al mes", pg, "nov" in ts, ts)
    vista(pg, "Mes")
    btn_key(pg, "navf_hoy_mes").click(); pg.wait_for_timeout(700); quieto(pg)
    th = tit(pg); paso(f"{rol} · Hoy en Mes", pg, "Septiembre 2026" in th, th)
    pg.locator("[class*='st-key-mes_2026-09-28'] button").first.click(); pg.wait_for_timeout(700); quieto(pg)
    tc = tit(pg); paso(f"{rol} · clic en un día del mes abre Día", pg, "28 de septiembre" in tc, tc)
    vista(pg, "Semana")
    btn_key(pg, "navf_hoy_sem").click(); pg.wait_for_timeout(700); quieto(pg)
    paso(f"{rol} · Hoy en Semana", pg, "20–26 sep 2026" in tit(pg), tit(pg))
    pg.get_by_role("button", name="Jornada 48 h · 2026").click(); pg.wait_for_timeout(800)
    pg.get_by_role("button", name="2030 · 40 h").click(); pg.wait_for_timeout(800); quieto(pg)
    t30 = tit(pg); paso(f"{rol} · salto a 2030", pg, "2030" in t30 and pg.get_by_role("button", name="Jornada 40 h · 2030").count(), t30)
    btn_key(pg, "navf_hoy_sem").click(); pg.wait_for_timeout(700); quieto(pg)
    paso(f"{rol} · Hoy regresa desde 2030", pg, "20–26 sep 2026" in tit(pg), tit(pg))
    # botón de día en la cabecera de la semana
    pg.locator("[class*='st-key-sem_2026-09-22'] button").first.click(); pg.wait_for_timeout(700); quieto(pg)
    paso(f"{rol} · clic en 'Mar 22' abre ese día", pg, "22 de septiembre" in tit(pg), tit(pg))
    vista(pg, "Semana")
    # descargas y plegables
    with pg.expect_download() as d1:
        pg.get_by_role("button", name="Horario (CSV)").click()
    paso(f"{rol} · descarga Horario (CSV)", pg, d1.value.suggested_filename.endswith(".csv"), d1.value.suggested_filename)
    with pg.expect_download() as d2:
        pg.get_by_role("button", name="Reporte (TXT)").click()
    paso(f"{rol} · descarga Reporte (TXT)", pg, d2.value.suggested_filename.endswith(".txt"), d2.value.suggested_filename)
    pg.get_by_text("De dónde sale el ahorro").click(); pg.wait_for_timeout(800)
    paso(f"{rol} · De dónde sale el ahorro", pg, pg.get_by_text("Horas ordinarias").count() > 0)
    vista(pg, "Día")
    pg.get_by_text(re.compile(r"^Descansan \(")).first.click(); pg.wait_for_timeout(600)
    paso(f"{rol} · plegable Descansan/Ausencias", pg, True)
    pg.get_by_text(re.compile(r"^Cobertura por hora")).first.click(); pg.wait_for_timeout(1000)
    paso(f"{rol} · plegable Cobertura por hora", pg, pg.locator("[data-testid=stVegaLiteChart], [data-testid=stArrowVegaLiteChart]").count() > 0)
    vista(pg, "Semana")


def comunes(pg, rol):
    pg.get_by_role("button", name="Mi correo").click(); pg.wait_for_timeout(600)
    pg.get_by_placeholder("nombre@empresa.mx").fill("malo"); pg.keyboard.press("Tab"); pg.wait_for_timeout(1200)
    paso(f"{rol} · Mi correo valida", pg, pg.get_by_text("Revisa el correo").count() > 0)
    pg.get_by_placeholder("nombre@empresa.mx").fill("prueba@alvea.mx"); pg.keyboard.press("Tab"); pg.wait_for_timeout(1200)
    pg.locator("[class*='st-key-sb_correo'] button").click(); pg.wait_for_timeout(1500); quieto(pg)
    paso(f"{rol} · Mi correo guarda", pg, True)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    pg.get_by_role("button", name="Privacidad y términos").click(); pg.wait_for_timeout(1000)
    paso(f"{rol} · Privacidad y términos", pg, pg.get_by_text("Qué guardamos").count() > 0)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(600)
    lateral(pg, "Avisos"); paso(f"{rol} · Avisos abre", pg, pg.get_by_text("Avisos").count() > 0)


with sync_playwright() as p:
    b = p.chromium.launch()
    # ---------- Gerente ----------
    g = entrar(b, "Man001")
    paso("Gerente · login", g, g.locator("section[data-testid=stSidebar]").count() > 0)
    navegacion(g, "Gerente")
    vista(g, "Día")
    g.locator("[data-testid=stMain] [data-testid=stSelectbox]").nth(0).click(); g.keyboard.type("Alejandra Rom"); g.keyboard.press("Enter")
    g.wait_for_timeout(800); quieto(g)
    g.locator("[data-testid=stMain] [data-testid=stSelectbox]").nth(1).click(); g.get_by_role("option", name="Descanso").click()
    g.wait_for_timeout(800); quieto(g)
    paso("Gerente · cambio de turno + calificación", g, g.get_by_role("button", name="Deshacer").count() > 0,
         g.locator(".aviso").first.inner_text()[:80] if g.locator(".aviso").count() else "")
    g.get_by_role("button", name="Deshacer").click(); g.wait_for_timeout(800); quieto(g)
    paso("Gerente · Deshacer", g, g.get_by_role("button", name="Deshacer").count() == 0)
    comunes(g, "Gerente")
    # ---------- Admin ----------
    a = entrar(b, "ADMIN-Z1")
    paso("Admin · Resumen abre", a, a.get_by_text("Tiendas en meta").count() > 0)
    t0 = tit(a); btn_key(a, "navf_next_res").click(); a.wait_for_timeout(700); quieto(a)
    paso("Admin · › en Resumen", a, tit(a) != t0, tit(a))
    btn_key(a, "navf_hoy_res").click(); a.wait_for_timeout(700); quieto(a)
    paso("Admin · Hoy en Resumen", a, tit(a) == t0, tit(a))
    a.get_by_text("Ver tabla").click(); a.wait_for_timeout(800)
    paso("Admin · Ver tabla", a, a.locator("[data-testid=stDataFrame]").count() > 0)
    navegacion(a, "Admin")
    a.locator("[data-testid=stMain] [data-testid=stSelectbox]").first.click(); a.keyboard.type("T009"); a.keyboard.press("Enter")
    a.wait_for_timeout(800); quieto(a)
    paso("Admin · cambiar de tienda", a, "T009" in a.locator("[data-testid=stMain] [data-testid=stSelectbox] input").first.input_value())
    btn_key(a, "navf_next_sem").click(); a.wait_for_timeout(700); quieto(a)
    paso("Admin · › tras cambiar de tienda", a, "oct" in tit(a), tit(a))
    btn_key(a, "navf_hoy_sem").click(); a.wait_for_timeout(700); quieto(a)
    lateral(a, "Avisos")
    ver = a.get_by_role("button", name="Ver día")
    if ver.count():
        ver.first.click(); a.wait_for_timeout(800); quieto(a)
        paso("Admin · Ver día desde aviso", a, "septiembre" in tit(a), tit(a))
        lateral(a, "Avisos")
    a.get_by_text("Historial: quién hizo qué y cuándo").click(); a.wait_for_timeout(1000)
    paso("Admin · Historial", a, a.get_by_text("Qué pasó").count() > 0)
    a.locator("[data-testid=stExpander] [data-testid=stSelectbox]").nth(1).click(); a.keyboard.type("Man001"); a.keyboard.press("Enter")
    a.wait_for_timeout(800); quieto(a)
    paso("Admin · filtro Quién no cierra el historial", a, a.get_by_role("button", name="Descargar (CSV)").is_visible())
    with a.expect_download() as d:
        a.get_by_role("button", name="Descargar (CSV)").click()
    paso("Admin · descarga historial", a, d.value.suggested_filename.endswith(".csv"))
    lateral(a, "Usuarios")
    paso("Admin · Usuarios", a, a.locator("[data-testid=stDataFrame]").count() > 0)
    comunes(a, "Admin")
    # ---------- SADMIN ----------
    s = entrar(b, "SADMIN")
    paso("SADMIN · Resumen red", s, s.get_by_text("50 de 50").count() > 0)
    navegacion(s, "SADMIN")
    for como, esperado in [("Zona Occidente", "Resumen"), ("Tienda T005", "Horario")]:
        s.locator("section[data-testid=stSidebar] [data-testid=stSelectbox]").first.click()
        s.keyboard.type(como); s.keyboard.press("Enter"); s.wait_for_timeout(800); quieto(s)
        lateral(s, esperado)
        paso(f"SADMIN · Ver como {como}", s, True, tit(s))
        if esperado == "Horario":
            navegacion(s, f"SADMIN como {como}")
    s.locator("section[data-testid=stSidebar] [data-testid=stSelectbox]").first.click()
    s.keyboard.type("Toda la red"); s.keyboard.press("Enter"); s.wait_for_timeout(800); quieto(s)
    lateral(s, "Reglas legales")
    s.get_by_text("Trazabilidad completa").click(); s.wait_for_timeout(800)
    paso("SADMIN · Reglas + trazabilidad", s, s.get_by_text("2030").count() > 0)
    lateral(s, "Datos")
    for n in ["Tiendas", "Plantilla"]:
        with s.expect_download() as d:
            s.get_by_role("button", name=n).click()
        paso(f"SADMIN · descarga {n}", s, d.value.suggested_filename.endswith(".csv"))
    with s.expect_download() as d:
        s.get_by_role("button", name=re.compile("Tráfico por hora")).click()
    paso("SADMIN · descarga Tráfico de la semana", s, d.value.suggested_filename.startswith("trafico_"))
    s.locator("input[type=file]").first.set_input_files(["archivos_para_subir/semana11_2027_cdmx_mas40/trafico_semana11_2027.csv"])
    s.wait_for_timeout(2500); quieto(s)
    paso("SADMIN · vista previa del archivo", s, s.get_by_text("Tráfico por hora · 7 días").count() > 0)
    s.get_by_role("button", name=re.compile("Aplicar 1 archivo")).click(); s.wait_for_timeout(1500); quieto(s)
    paso("SADMIN · aplicar archivo", s, s.get_by_text("Listo.").count() > 0)
    s.get_by_role("button", name=re.compile("Volver a los archivos originales")).click(); s.wait_for_timeout(1000)
    s.get_by_role("button", name="Sí, quitar lo subido").click(); s.wait_for_timeout(1500); quieto(s)
    paso("SADMIN · volver a originales", s, s.get_by_text("1 semana subida").count() == 0)
    comunes(s, "SADMIN")
    s.locator("section[data-testid=stSidebar]").get_by_role("button", name="Cerrar sesión").click(); s.wait_for_timeout(2000)
    paso("SADMIN · Cerrar sesión", s, s.get_by_role("button", name="Entrar").count() > 0)
    b.close()

fallas = [r for r in R if not r[0]]
print(f"\n{len(R) - len(fallas)} OK · {len(fallas)} FALLAS")
for _, n, d in fallas:
    print("  ✗", n, "|", d)
