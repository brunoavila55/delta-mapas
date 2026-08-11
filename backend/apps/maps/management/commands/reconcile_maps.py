from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context

from apps.maps.services.reconciliation import (
    expire_stalled_jobs,
    reconcile_generated_map_storage,
)
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Expire stalled map jobs and audit generated-map objects for one tenant."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True)
        parser.add_argument(
            "--stale-minutes",
            type=int,
            default=settings.MAP_JOB_STALE_MINUTES,
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            dest="apply_changes",
            help="Expire stale jobs. Without this flag the command is read-only.",
        )
        parser.add_argument(
            "--delete-orphans",
            action="store_true",
            help="Delete unreferenced objects. Requires --apply.",
        )

    def handle(self, *args, **options):
        if options["stale_minutes"] <= 0:
            raise CommandError("--stale-minutes deve ser maior que zero.")
        if options["delete_orphans"] and not options["apply_changes"]:
            raise CommandError("--delete-orphans exige --apply.")

        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(schema_name=options["schema"])
            except Tenant.DoesNotExist as exc:
                raise CommandError("Tenant não encontrado.") from exc

        from django.utils import timezone

        stale_before = timezone.now() - timedelta(minutes=options["stale_minutes"])
        with tenant_context(tenant):
            stalled = expire_stalled_jobs(
                stale_before=stale_before,
                apply_changes=options["apply_changes"],
            )
            storage = reconcile_generated_map_storage(
                delete_orphans=options["delete_orphans"],
            )

        mode = "APLICADO" if options["apply_changes"] else "SIMULAÇÃO"
        self.stdout.write(f"Modo: {mode} | tenant: {tenant.schema_name}")
        self.stdout.write(
            f"Jobs travados: {len(stalled.candidates)} encontrados, "
            f"{len(stalled.expired)} expirados."
        )
        self.stdout.write(
            f"Storage: {storage.expected_objects} objetos esperados, "
            f"{len(storage.missing_files)} arquivos ausentes, "
            f"{len(storage.orphan_objects)} órfãos, "
            f"{len(storage.deleted_objects)} excluídos."
        )
        for missing in storage.missing_files:
            object_name = missing.object_name or "<campo vazio>"
            self.stdout.write(
                self.style.WARNING(
                    f"AUSENTE {missing.generated_map_id} "
                    f"{missing.field_name}: {object_name}"
                )
            )
        for object_name in storage.orphan_objects:
            label = "EXCLUÍDO" if object_name in storage.deleted_objects else "ÓRFÃO"
            self.stdout.write(self.style.WARNING(f"{label} {object_name}"))
