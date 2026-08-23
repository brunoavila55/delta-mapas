from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import get_public_schema_name, tenant_context

from apps.accounts.models import Membership
from apps.billing.models import ProcessingPrice
from apps.billing.services import grant_credits
from apps.tenants.models import Domain, Tenant


def configure_tenant_owner(user) -> None:
    user.is_staff = False
    user.is_superuser = False


class Command(BaseCommand):
    help = "Provision the first production tenant, owner, price and initial credits."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default=os.getenv("TENANT_SCHEMA", "principal"))
        parser.add_argument("--domain", default=os.getenv("TENANT_DOMAIN"))
        parser.add_argument("--name", default=os.getenv("TENANT_NAME", "Delta Mapas"))
        parser.add_argument(
            "--username", default=os.getenv("SUPERUSER_USERNAME", "admin")
        )
        parser.add_argument("--email", default=os.getenv("SUPERUSER_EMAIL"))
        parser.add_argument(
            "--password-env", default="SUPERUSER_PASSWORD", metavar="VARIABLE"
        )
        parser.add_argument(
            "--credits", type=int, default=int(os.getenv("INITIAL_CREDITS", "10"))
        )
        parser.add_argument(
            "--ndvi-credit-cost",
            type=int,
            default=int(os.getenv("NDVI_CREDIT_COST", "1")),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        schema = options["schema"].strip().lower()
        domain = (options["domain"] or "").strip().lower().rstrip(".")
        email = (options["email"] or "").strip().lower()
        password = os.getenv(options["password_env"], "")

        if not domain or "://" in domain or any(char in domain for char in "/:"):
            raise CommandError(
                "TENANT_DOMAIN must be a hostname without scheme or port."
            )
        if schema == get_public_schema_name():
            raise CommandError("TENANT_SCHEMA cannot use the public schema name.")
        if not email:
            raise CommandError("Set SUPERUSER_EMAIL or provide --email.")
        if options["credits"] < 0:
            raise CommandError("Initial credits cannot be negative.")
        if options["ndvi_credit_cost"] <= 0:
            raise CommandError("NDVI credit cost must be positive.")

        public_tenant, _ = Tenant.objects.get_or_create(
            schema_name=get_public_schema_name(), defaults={"name": "Delta Mapas"}
        )
        Domain.objects.get_or_create(
            domain=f"public.{domain}",
            defaults={"tenant": public_tenant, "is_primary": True},
        )

        tenant, tenant_created = Tenant.objects.get_or_create(
            schema_name=schema, defaults={"name": options["name"]}
        )
        domain_record, domain_created = Domain.objects.get_or_create(
            domain=domain,
            defaults={"tenant": tenant, "is_primary": True},
        )
        if not domain_created and domain_record.tenant_id != tenant.id:
            raise CommandError(f"Domain {domain!r} already belongs to another tenant.")

        User = get_user_model()
        conflicting_email = User.objects.filter(email=email).exclude(
            username=options["username"]
        )
        if conflicting_email.exists():
            raise CommandError("SUPERUSER_EMAIL already belongs to another user.")

        user, user_created = User.objects.get_or_create(
            username=options["username"], defaults={"email": email}
        )
        if user_created and not password:
            raise CommandError(
                f"Set {options['password_env']} before creating the first tenant owner."
            )
        if user.email != email:
            user.email = email
        # A tenant owner is an application role, not a platform administrator.
        # Clear legacy privilege escalation from earlier provisioning runs too.
        configure_tenant_owner(user)
        if user_created:
            user.set_password(password)
        user.save()

        Membership.objects.update_or_create(
            user=user,
            tenant=tenant,
            defaults={"role": Membership.Role.OWNER, "is_active": True},
        )

        with tenant_context(tenant), transaction.atomic():
            ProcessingPrice.objects.update_or_create(
                index_type="NDVI",
                defaults={
                    "credit_cost": options["ndvi_credit_cost"],
                    "is_active": True,
                },
            )
            if options["credits"]:
                grant_credits(
                    amount=options["credits"],
                    idempotency_key=f"provision:{tenant.id}:initial-credits",
                    created_by=user,
                    metadata={"source": "provision_tenant"},
                )

        status = "created" if tenant_created else "already existed"
        self.stdout.write(self.style.SUCCESS(f"Production tenant {status}."))
        self.stdout.write(f"Tenant: {tenant.schema_name} ({domain_record.domain})")
        self.stdout.write(f"Owner: {user.username} / {user.email}")
