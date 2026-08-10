from django.core.exceptions import ValidationError


class InvalidGeometry(ValidationError):
    pass


class InvalidShapefile(ValidationError):
    pass
