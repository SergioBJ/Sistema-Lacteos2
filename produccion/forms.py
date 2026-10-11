from decimal import Decimal

from django import forms

from catalogo.models import Cliente, Producto, Tamano
from usuarios.models import Usuario

from .models import OrdenProduccion


class NuevaOrdenForm(forms.Form):
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.filter(activo=True).select_related("tipo"),
        empty_label="Elige el producto",
    )
    tamano = forms.ModelChoiceField(
        label="Tamaño", queryset=Tamano.objects.filter(activo=True), empty_label="Elige el tamaño",
        help_text="Solo aparecen los tamaños del producto que elegiste.",
    )
    cantidad = forms.IntegerField(label="Cantidad (unidades)", min_value=1)
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.filter(activo=True), required=False, empty_label="Sin cliente (para bodega)",
    )
    operador = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(rol=Usuario.Rol.OPERADOR, is_active=True), empty_label="Elige el operador",
    )

    def clean(self):
        datos = super().clean()
        producto, tamano = datos.get("producto"), datos.get("tamano")
        if producto and tamano and tamano.producto_id != producto.pk:
            self.add_error("tamano", "Ese tamaño no es de este producto.")
        return datos


class FilaFormulaForm(forms.Form):
    material = forms.ModelChoiceField(queryset=None, empty_label="Elige el material")
    cantidad = forms.DecimalField(min_value=Decimal("0.0001"), max_digits=12, decimal_places=4)

    def __init__(self, *args, tipo_material=None, **kwargs):
        super().__init__(*args, **kwargs)
        from catalogo.models import Material
        self.fields["material"].queryset = Material.objects.filter(activo=True, tipo=tipo_material)
