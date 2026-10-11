"""Convierte un reporte (ver datos.py) en archivo Excel o PDF, con el logo y el estilo del sistema."""
from io import BytesIO

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify

SISTEMA = "Sistema de Control Estadístico y Trazabilidad en Procesos Lácteos"
AZUL = "16427A"
LOGO = settings.BASE_DIR / "static" / "img" / "logo.jpg"


def _nombre_archivo(rep, ext):
    return f"{slugify(rep['titulo'])}_{timezone.localdate():%Y-%m-%d}.{ext}"


def _pie(usuario):
    nombre = usuario.get_full_name() or usuario.username
    return f"Generado por {nombre} ({usuario.get_rol_display()}) el {timezone.localtime():%d/%m/%Y a las %H:%M} · Datos tomados del historial del sistema"


# =====================================================================
# Excel
# =====================================================================
def a_excel(rep, usuario):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    hoja = libro.active
    hoja.title = rep["titulo"][:31]
    hoja.sheet_view.showGridLines = False
    borde = Border(bottom=Side(style="thin", color="DCE4EE"))
    fila = 1

    try:
        from openpyxl.drawing.image import Image
        img = Image(str(LOGO))
        img.width, img.height = 64, 64
        hoja.add_image(img, "A1")
        hoja.row_dimensions[1].height = 26
        hoja.row_dimensions[2].height = 26
        col_texto = "B"
    except Exception:
        col_texto = "A"

    hoja[f"{col_texto}1"] = rep["titulo"]
    hoja[f"{col_texto}1"].font = Font(size=18, bold=True, color=AZUL)
    hoja[f"{col_texto}2"] = f"{rep['subtitulo']} · {SISTEMA}"
    hoja[f"{col_texto}2"].font = Font(size=10, color="3E5A7E")
    fila = 4
    hoja.cell(fila, 1, " · ".join(rep["filtros"])).font = Font(size=10, italic=True, color="3E5A7E")
    fila += 2

    for i, k in enumerate(rep.get("kpis", [])):
        c = hoja.cell(fila, 1 + i * 2, k["valor"])
        c.font = Font(size=16, bold=True, color="14233A")
        hoja.cell(fila + 1, 1 + i * 2, k["texto"]).font = Font(size=9, color="3E5A7E")
        if k.get("cambio"):
            color = {"bueno": "165C37", "malo": "951B10"}.get(k["cambio"]["tono"], "3E5A7E")
            hoja.cell(fila + 2, 1 + i * 2, k["cambio"]["texto"]).font = Font(size=8, bold=True, color=color)
    fila += 4

    anchos = {}
    for sec in rep["secciones"]:
        hoja.cell(fila, 1, sec["titulo"].upper()).font = Font(size=11, bold=True, color=AZUL)
        fila += 1
        for j, cab in enumerate(sec["cabeceras"], 1):
            c = hoja.cell(fila, j, cab)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=AZUL)
            c.alignment = Alignment(vertical="center", wrap_text=True)
            anchos[j] = max(anchos.get(j, 0), len(str(cab)))
        fila += 1
        if not sec["filas"]:
            hoja.cell(fila, 1, "Sin datos en el periodo.").font = Font(italic=True, color="5B6662")
            fila += 1
        for f in sec["filas"]:
            grupo = isinstance(f[0], str) and f[0].startswith("» ")
            for j, valor in enumerate(f, 1):
                c = hoja.cell(fila, j, valor)
                c.border = borde
                c.alignment = Alignment(vertical="top", wrap_text=True)
                if grupo:
                    c.font = Font(bold=True, color=AZUL)
                    c.fill = PatternFill("solid", fgColor="F7F9FC")
                anchos[j] = max(anchos.get(j, 0), min(len(str(valor)), 60))
            fila += 1
        if sec.get("nota"):
            hoja.cell(fila, 1, sec["nota"]).font = Font(size=9, italic=True, color="3E5A7E")
            fila += 1
        fila += 1

    if rep.get("nota_final"):
        hoja.cell(fila, 1, rep["nota_final"]).font = Font(bold=True, color="14233A")
        fila += 2
    hoja.cell(fila, 1, _pie(usuario)).font = Font(size=8, color="5B6662")

    for j, ancho in anchos.items():
        hoja.column_dimensions[get_column_letter(j)].width = max(10, ancho + 2)

    salida = BytesIO()
    libro.save(salida)
    respuesta = HttpResponse(salida.getvalue(),
                             content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre_archivo(rep, "xlsx")}"'
    return respuesta


# =====================================================================
# PDF
# =====================================================================
def a_pdf(rep, usuario):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ancho_max = max(len(s["cabeceras"]) for s in rep["secciones"])
    pagina = landscape(letter) if ancho_max > 5 else letter
    margen = 14 * mm
    util = pagina[0] - 2 * margen

    azul = colors.HexColor("#" + AZUL)
    gris = colors.HexColor("#3E5A7E")
    est = {
        "titulo": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18, textColor=azul, alignment=TA_RIGHT, leading=22),
        "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, textColor=gris, alignment=TA_RIGHT, leading=11),
        "sis": ParagraphStyle("sis", fontName="Helvetica-Bold", fontSize=8.5, textColor=azul, leading=11),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10, textColor=azul, spaceBefore=8, spaceAfter=4),
        "celda": ParagraphStyle("c", fontName="Helvetica", fontSize=7.5, leading=9.5),
        "cab": ParagraphStyle("cab", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=colors.HexColor("#14233A")),
        "nota": ParagraphStyle("n", fontName="Helvetica", fontSize=8, textColor=gris, leading=10.5),
        "kv": ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#14233A")),
        "kv2": ParagraphStyle("kv2", fontName="Helvetica-Bold", fontSize=10, leading=12, textColor=colors.HexColor("#14233A")),
        "kt": ParagraphStyle("kt", fontName="Helvetica", fontSize=7.5, leading=9, textColor=gris),
    }

    def p(texto, estilo="celda"):
        texto = str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(texto, est[estilo])

    historia = []
    # Encabezado: logo + sistema | título
    try:
        logo = Image(str(LOGO), width=16 * mm, height=16 * mm)
    except Exception:
        logo = Spacer(1, 1)
    izq = Table([[logo, Paragraph(f"{SISTEMA}<br/><font color='#3E5A7E' size='8'>Inventario de lácteos</font>", est["sis"])]],
                colWidths=[18 * mm, 70 * mm])
    izq.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    der = [Paragraph(rep["titulo"], est["titulo"]), Paragraph(f"{rep['subtitulo']}<br/>Generado el {timezone.localtime():%d/%m/%Y a las %H:%M}", est["sub"])]
    cab = Table([[izq, der]], colWidths=[util * 0.5, util * 0.5])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, 0), 1.5, azul),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    historia += [cab, Spacer(1, 6), p(" · ".join(rep["filtros"]), "nota"), Spacer(1, 8)]

    # Números clave
    if rep.get("kpis"):
        celdas = []
        for k in rep["kpis"]:
            partes = [p(k["valor"], "kv2" if k.get("pequeno") else "kv"), p(k["texto"], "kt")]
            if k.get("cambio"):
                color = {"bueno": "#165C37", "malo": "#951B10"}.get(k["cambio"]["tono"], "#3E5A7E")
                partes.append(Paragraph(f"<font color='{color}'><b>{k['cambio']['texto']}</b></font>", est["kt"]))
            celdas.append(partes)
        ancho_k = util / len(celdas)
        t = Table([celdas], colWidths=[ancho_k] * len(celdas))
        t.setStyle(TableStyle([("BOX", (i, 0), (i, 0), 0.6, colors.HexColor("#DCE4EE")) for i in range(len(celdas))]
                              + [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        historia += [t, Spacer(1, 6)]

    # Secciones
    for sec in rep["secciones"]:
        historia.append(p(sec["titulo"].upper(), "h2"))
        datos = [[p(c, "cab") for c in sec["cabeceras"]]]
        grupos = []
        for i, fila in enumerate(sec["filas"], 1):
            if isinstance(fila[0], str) and fila[0].startswith("» "):
                grupos.append(i)
            datos.append([p(v, "cab") if i in grupos else p(v) for v in fila])
        if not sec["filas"]:
            datos.append([p("Sin datos en el periodo.")] + [p("")] * (len(sec["cabeceras"]) - 1))
        if sec.get("ancho"):
            total = sum(sec["ancho"])
            anchos = [util * a / total for a in sec["ancho"]]
        else:
            anchos = [util / len(sec["cabeceras"])] * len(sec["cabeceras"])
        t = Table(datos, colWidths=anchos, repeatRows=1)
        estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F8")),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#C9D5E4")),
                  ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#E9EEF4")),
                  ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for g in grupos:
            estilo.append(("BACKGROUND", (0, g), (-1, g), colors.HexColor("#F7F9FC")))
        t.setStyle(TableStyle(estilo))
        historia.append(t)
        if sec.get("nota"):
            historia += [Spacer(1, 3), p(sec["nota"], "nota")]
    if rep.get("nota_final"):
        historia += [Spacer(1, 10), Paragraph(f"<b>{rep['nota_final']}</b>", est["nota"])]

    pie = _pie(usuario)

    def dibujar_pie(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#DCE4EE"))
        canvas.line(margen, 11 * mm, pagina[0] - margen, 11 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(gris)
        canvas.drawString(margen, 7.5 * mm, pie)
        canvas.drawRightString(pagina[0] - margen, 7.5 * mm, f"Página {doc.page}")
        canvas.restoreState()

    salida = BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=pagina, leftMargin=margen, rightMargin=margen,
                            topMargin=12 * mm, bottomMargin=16 * mm, title=rep["titulo"], author=SISTEMA)
    doc.build(historia, onFirstPage=dibujar_pie, onLaterPages=dibujar_pie)
    respuesta = HttpResponse(salida.getvalue(), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre_archivo(rep, "pdf")}"'
    return respuesta
