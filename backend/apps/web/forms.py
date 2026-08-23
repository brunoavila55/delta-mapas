from __future__ import annotations

from django import forms

from apps.maps.models import IndexType
from apps.properties.exceptions import InvalidGeometry, InvalidShapefile
from apps.properties.importers import import_shapefile
from apps.properties.models import Property
from apps.properties.services import parse_and_validate_geometry


class LoginForm(forms.Form):
    username = forms.CharField(label="Usuário", max_length=150)
    password = forms.CharField(label="Senha", widget=forms.PasswordInput)


class PropertyForm(forms.Form):
    name = forms.CharField(label="Nome da propriedade", max_length=180)
    city = forms.CharField(label="Município", max_length=120, required=False)
    state = forms.CharField(label="Estado", max_length=120, required=False)
    country = forms.CharField(label="País", max_length=2, initial="BR")
    description = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    shapefile = forms.FileField(label="Shapefile compactado (.zip)", required=False)
    geometry = forms.CharField(
        label="Geometria GeoJSON",
        required=False,
        widget=forms.Textarea(attrs={"rows": 10, "spellcheck": "false"}),
    )

    def __init__(self, *args, instance: Property | None = None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        if instance and not self.is_bound:
            self.initial.update(
                {
                    "name": instance.name,
                    "city": instance.city,
                    "state": instance.state,
                    "country": instance.country,
                    "description": instance.description,
                    "geometry": instance.geometry.geojson,
                }
            )

    def clean_country(self):
        value = self.cleaned_data["country"].strip().upper()
        if len(value) != 2:
            raise forms.ValidationError("Use o código ISO de duas letras.")
        return value

    def clean(self):
        cleaned = super().clean()
        upload = cleaned.get("shapefile")
        raw_geometry = (cleaned.get("geometry") or "").strip()
        if upload and raw_geometry:
            self.add_error(
                "shapefile", "Escolha apenas uma origem: arquivo ZIP ou GeoJSON."
            )
            return cleaned
        if not upload and not raw_geometry:
            self.add_error("geometry", "Informe um shapefile ou uma geometria GeoJSON.")
            return cleaned
        try:
            if upload:
                if not upload.name.lower().endswith(".zip"):
                    raise forms.ValidationError("Envie um arquivo com extensão .zip.")
                cleaned["normalized_geometry"] = import_shapefile(upload)
            else:
                cleaned["normalized_geometry"] = parse_and_validate_geometry(raw_geometry)
        except InvalidShapefile as exc:
            self.add_error("shapefile", exc.messages)
        except InvalidGeometry as exc:
            self.add_error("geometry", exc.messages)
        except forms.ValidationError as exc:
            self.add_error("shapefile", exc)
        return cleaned


class MapJobForm(forms.Form):
    property = forms.ModelChoiceField(
        label="Propriedade", queryset=Property.objects.none(), empty_label="Selecione uma área"
    )
    index_type = forms.ChoiceField(
        label="Produto", choices=IndexType.choices, initial=IndexType.NDVI
    )
    date_from = forms.DateField(label="Data inicial", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="Data final", widget=forms.DateInput(attrs={"type": "date"}))
    max_cloud_cover = forms.DecimalField(
        label="Máximo de nuvens (%)", min_value=0, max_value=100, initial=20
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.order_by("name")

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            self.add_error("date_to", "A data final deve ser posterior à inicial.")
        return cleaned
