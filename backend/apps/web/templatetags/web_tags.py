from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    encoded = query.urlencode()
    return f"?{encoded}" if encoded else ""


@register.filter
def status_tone(value):
    return {
        "COMPLETED": "success",
        "FAILED": "danger",
        "CANCELLED": "neutral",
        "PENDING": "warning",
    }.get(value, "info")


@register.filter
def get_item(value, key):
    if isinstance(value, dict):
        return value.get(key)
    return None
