from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context

from apps.billing.exceptions import BillingError
from apps.billing.services import adjust_available_credits
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Apply an audited, idempotent credit adjustment to one tenant."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True)
        parser.add_argument("--delta", required=True, type=int)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--idempotency-key", required=True)
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        if options["delta"] == 0:
            raise CommandError("--delta cannot be zero.")
        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(schema_name=options["schema"])
                user = get_user_model().objects.get(username=options["username"])
            except (Tenant.DoesNotExist, get_user_model().DoesNotExist) as exc:
                raise CommandError("Tenant or user not found.") from exc

        try:
            with tenant_context(tenant):
                result = adjust_available_credits(
                    delta=options["delta"],
                    idempotency_key=options["idempotency_key"],
                    reason=options["reason"],
                    created_by=user,
                )
        except BillingError as exc:
            raise CommandError(str(exc)) from exc

        replayed = " (replayed)" if result.replayed else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Balance: {result.account.available_balance} available{replayed}"
            )
        )
