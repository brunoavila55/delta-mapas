from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import get_public_schema_name, tenant_context

from apps.accounts.models import Membership
from apps.billing.models import CreditAccount, CreditTransaction, ProcessingPrice
from apps.tenants.models import Domain, Tenant


class Command(BaseCommand):
    help = "Create an idempotent local tenant, domain, superuser and initial credits."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default=os.getenv("DEV_TENANT_SCHEMA", "demo"))
        parser.add_argument(
            "--domain", default=os.getenv("DEV_TENANT_DOMAIN", "localhost")
        )
        parser.add_argument("--name", default="Delta Mapas Demo")
        parser.add_argument(
            "--username", default=os.getenv("DEV_SUPERUSER_USERNAME", "admin")
        )
        parser.add_argument(
            "--email", default=os.getenv("DEV_SUPERUSER_EMAIL", "admin@localhost")
        )
        parser.add_argument("--password", default=os.getenv("DEV_SUPERUSER_PASSWORD"))
        parser.add_argument(
            "--credits", type=int, default=int(os.getenv("DEV_INITIAL_CREDITS", "10"))
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["password"]:
            raise CommandError(
                "Set DEV_SUPERUSER_PASSWORD or provide --password; no default password is created."
            )
        if options["credits"] < 0:
            raise CommandError("Initial credits cannot be negative.")

        public_tenant, _ = Tenant.objects.get_or_create(
            schema_name=get_public_schema_name(), defaults={"name": "Delta Mapas"}
        )
        Domain.objects.get_or_create(
            domain="public.localhost",
            defaults={"tenant": public_tenant, "is_primary": True},
        )

        tenant, _ = Tenant.objects.get_or_create(
            schema_name=options["schema"], defaults={"name": options["name"]}
        )
        domain, domain_created = Domain.objects.get_or_create(
            domain=options["domain"],
            defaults={"tenant": tenant, "is_primary": True},
        )
        if not domain_created and domain.tenant_id != tenant.id:
            raise CommandError(
                f"Domain {domain.domain!r} already belongs to another tenant."
            )

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=options["username"], defaults={"email": options["email"]}
        )
        if not created and user.email != options["email"]:
            user.email = options["email"]
        user.is_staff = True
        user.is_superuser = True
        user.set_password(options["password"])
        user.save()

        Membership.objects.update_or_create(
            user=user,
            tenant=tenant,
            defaults={"role": Membership.Role.OWNER, "is_active": True},
        )

        with tenant_context(tenant), transaction.atomic():
            account, _ = CreditAccount.objects.get_or_create(singleton_key=True)
            ProcessingPrice.objects.update_or_create(
                index_type="NDVI",
                defaults={
                    "credit_cost": int(os.getenv("DEV_NDVI_CREDIT_COST", "1")),
                    "is_active": True,
                },
            )
            key = f"setup-dev:{tenant.id}:initial-credits"
            if (
                options["credits"]
                and not CreditTransaction.objects.filter(idempotency_key=key).exists()
            ):
                account.available_balance += options["credits"]
                account.save(update_fields=("available_balance", "updated_at"))
                CreditTransaction.objects.create(
                    account=account,
                    transaction_type=CreditTransaction.Type.BONUS,
                    amount=options["credits"],
                    idempotency_key=key,
                    available_balance_after=account.available_balance,
                    reserved_balance_after=account.reserved_balance,
                    created_by=user,
                    metadata={"source": "setup_dev"},
                )

        self.stdout.write(self.style.SUCCESS("Development environment is ready."))
        self.stdout.write(f"Tenant: {tenant.schema_name} ({domain.domain})")
        self.stdout.write(f"User: {user.username} / {user.email}")
