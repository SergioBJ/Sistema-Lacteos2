from django import forms
from django.utils import timezone

from catalogo.models import Material, Proveedor

from .models import Llegada


class LlegadaForm(forms.ModelForm):
    tipo = forms.ChoiceField(
        label="Tipo de material", choices=Material.Tipo.choices, widget=forms.RadioSelect,
        initial=Material.Tipo.MATERIA_PRIMA,
    )

    class Meta:
        model = Llegada
        fields = ["material", "cantidad", "proveedor", "lote_proveedor", "vencimiento",
                  "ficha_tecnica", "certificado", "remision", "observaciones"]
        labels = {"cantidad": "Cantidad que llegó"}
        widgets = {
            "vencimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observaciones": forms.Textarea(attrs={"rows": 3,
                                                   "placeholder": "Escribe aquí si algo llegó dañado o incompleto"}),
        }
        help_texts = {
            "material": "Solo aparecen materiales del tipo que elegiste.",
            "proveedor": "Solo aparecen los proveedores que suministran este material.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["tipo"] + list(self.Meta.fields))
        self.fields["material"].queryset = Material.objects.filter(activo=True).order_by("tipo", "nombre")
        self.fields["proveedor"].queryset = Proveedor.objects.filter(activo=True)
        self.fields["material"].empty_label = "Elige el material"
        self.fields["proveedor"].empty_label = "Elige el proveedor"

    def clean(self):
        datos = super().clean()
        material, proveedor = datos.get("material"), datos.get("proveedor")
        tipo = datos.get("tipo")
        if material and tipo and material.tipo != tipo:
            self.add_error("material", "Este material no es del tipo que elegiste.")
        if material and proveedor and not proveedor.materiales.filter(pk=material.pk).exists():
            self.add_error("proveedor", f"{proveedor} no suministra {material.nombre}.")
        vence = datos.get("vencimiento")
        if vence and vence <= timezone.localdate():
            self.add_error("vencimiento", "Este material ya está vencido. Debe devolverse al proveedor.")
        return datos
