"""Menú lateral de cada rol, igual al bosquejo.

Cada opción apunta al nombre de una ruta (url name). Si esa pantalla todavía
no existe, la opción sale en gris con la palabra "pronto".
"""

ROLES = {
    "GERENTE": {
        "nombre": "Gerente",
        "color": "#2E4A78",
        "pie": "No registra movimientos: los consulta. Sí crea los datos base: usuarios, "
               "proveedores, clientes y materiales.",
        "items": [
            ("Resumen", "gerente_resumen"),
            ("Gráficas", "gerente_graficas"),
            ("Trazabilidad", "gerente_trazabilidad"),
            ("Historial y reportes", "gerente_historial"),
            ("§Administración", None),
            ("Usuarios", "gerente_usuarios"),
            ("Proveedores", "gerente_proveedores"),
            ("Clientes", "gerente_clientes"),
            ("Materiales y productos", "gerente_materiales"),
        ],
    },
    "ALMACENISTA": {
        "nombre": "Almacenista",
        "color": "#1D6656",
        "pie": "Solo ves las tareas de bodega. Las pantallas de los otros roles no aparecen aquí.",
        "items": [
            ("Mis tareas", "almacen_tareas"),
            ("Recepción de materia prima", "almacen_recepcion"),
            ("Entregar a producción", "almacen_entrega"),
            ("Bodega y despacho", "almacen_despacho"),
        ],
    },
    "CALIDAD": {
        "nombre": "Supervisor de Calidad",
        "color": "#5A3D8A",
        "pie": "Solo ves las tareas de calidad. Las pantallas de los otros roles no aparecen aquí.",
        "items": [
            ("Mis tareas", "calidad_tareas"),
            ("Revisar material", "calidad_revision"),
            ("Liberar lote", "calidad_liberacion"),
            ("Parámetros de calidad", "calidad_parametros"),
        ],
    },
    "JEFE": {
        "nombre": "Jefe de Producción",
        "color": "#8A4A10",
        "pie": "Solo ves las tareas de producción. Las pantallas de los otros roles no aparecen aquí.",
        "items": [
            ("Mis órdenes", "jefe_ordenes"),
            ("Nueva orden", "jefe_nueva"),
            ("Revisar producción", "jefe_revisar"),
            ("Fórmulas de productos", "jefe_formulas"),
        ],
    },
    "OPERADOR": {
        "nombre": "Operador",
        "color": "#1D5A9E",
        "pie": "Solo ves la orden que te asignaron.",
        "items": [
            ("Mi orden de hoy", "operador_orden"),
            ("Registrar producción", "operador_registro"),
        ],
    },
}
