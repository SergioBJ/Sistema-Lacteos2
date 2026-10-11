from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Cliente, Material, Producto, Proveedor, Tamano, TipoProducto

PREFIJOS = {
    Material.Tipo.MATERIA_PRIMA: "MP",
    Material.Tipo.EMPAQUE: "EMP",
    Material.Tipo.DESINFECTANTE: "DES",
}


def siguiente_codigo(modelo, prefijo):
    """MP-001, MP-002... Busca el primer número libre con ese prefijo."""
    n = modelo.objects.filter(codigo__startswith=prefijo + "-").count() + 1
    while modelo.objects.filter(codigo=f"{prefijo}-{n:03d}").exists():
        n += 1
    return f"{prefijo}-{n:03d}"


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ["nombre", "tipo", "unidad", "stock_minimo"]
        labels = {"tipo": "Tipo de material", "unidad": "Unidad de medida"}
        help_texts = {
            "stock_minimo": "Cuando el inventario baja de aquí, sale una alerta.",
        }

    def save(self, commit=True):
        material = super().save(commit=False)
        if not material.codigo:
            material.codigo = siguiente_codigo(Material, PREFIJOS[material.tipo])
        if commit:
            material.save()
        return material


class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = ["nit", "nombre", "telefono", "correo", "direccion", "materiales"]
        widgets = {"materiales": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["materiales"].queryset = Material.objects.filter(activo=True)


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nit", "nombre", "ciudad", "telefono", "correo"]


class ProductoForm(forms.ModelForm):
    tipo_nombre = forms.CharField(
        label="Nombre del producto", max_length=120,
        help_text="Ejemplo: Leche en polvo entera. Si el tipo ya existe, elígelo de la lista.",
        widget=forms.TextInput(attrs={"list": "tipos-existentes"}),
    )

    class Meta:
        model = Producto
        fields = ["marca", "vida_util_meses"]
        help_texts = {"vida_util_meses": "Con esto se calcula el vencimiento de cada lote."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["tipo_nombre", "marca", "vida_util_meses"])
        if self.instance.pk:
            self.fields["tipo_nombre"].initial = self.instance.tipo.nombre

    def clean(self):
        datos = super().clean()
        nombre = (datos.get("tipo_nombre") or "").strip()
        marca = (datos.get("marca") or "").strip()
        if nombre and marca:
            repetido = Producto.objects.filter(tipo__nombre__iexact=nombre, marca__iexact=marca)
            if self.instance.pk:
                repetido = repetido.exclude(pk=self.instance.pk)
            if repetido.exists():
                raise forms.ValidationError("Ya existe ese producto con esa marca.")
        return datos

    def save(self, commit=True):
        producto = super().save(commit=False)
        nombre = self.cleaned_data["tipo_nombre"].strip()
        tipo = TipoProducto.objects.filter(nombre__iexact=nombre).first()
        if tipo is None:
            tipo = TipoProducto.objects.create(nombre=nombre)
        producto.tipo = tipo
        if commit:
            producto.save()
        return producto


class TamanoFormSetBase(BaseInlineFormSet):
    def clean(self):
        super().clean()
        vistos = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            clave = (form.cleaned_data.get("cantidad"), form.cleaned_data.get("unidad"))
            if clave in vistos:
                raise forms.ValidationError("Hay dos tamaños iguales. Deja solo uno.")
            vistos.add(clave)

    def save_new(self, form, commit=True):
        tamano = super().save_new(form, commit=False)
        tamano.codigo = siguiente_codigo(Tamano, "LAC")
        if commit:
            tamano.save()
        return tamano


def tamanos_formset(extra):
    return inlineformset_factory(
        Producto, Tamano, formset=TamanoFormSetBase,
        fields=["cantidad", "unidad", "empaque", "stock_minimo", "activo"],
        labels={"cantidad": "Tamaño", "stock_minimo": "Stock mínimo", "activo": "Activo"},
        extra=extra, min_num=1, validate_min=True, can_delete=False,
        widgets={
            "cantidad": forms.NumberInput(attrs={"step": "any", "min": "0", "placeholder": "Ej. 25"}),
            "empaque": forms.TextInput(attrs={"list": "empaques", "placeholder": "Bolsa, Saco…"}),
            "stock_minimo": forms.NumberInput(attrs={"min": "0"}),
        },
    )
