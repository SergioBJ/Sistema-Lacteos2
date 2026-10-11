from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_date

from inventario.historial import registrar
from usuarios.permisos import rol_requerido

from .datos import REPORTES, Filtros
from .exportar import a_excel, a_pdf


@rol_requerido("GERENTE")
def descargar(request, nombre, formato):
    if nombre not in REPORTES or formato not in ("excel", "pdf"):
        raise Http404
    hoy = timezone.localdate()
    filtros = Filtros(
        desde=parse_date(request.GET.get("desde", "") or "") or hoy.replace(day=1),
        hasta=parse_date(request.GET.get("hasta", "") or "") or hoy,
        rol=request.GET.get("rol", ""),
        solo_no=request.GET.get("solo") == "no",
        q=request.GET.get("q", "").strip(),
    )
    titulo, funcion = REPORTES[nombre]
    rep = funcion(filtros)
    registrar(request.user, "ADMINISTRACION", f"descargó el reporte {titulo} en {formato.upper()}", True, "REPORTE")
    return a_excel(rep, request.user) if formato == "excel" else a_pdf(rep, request.user)
