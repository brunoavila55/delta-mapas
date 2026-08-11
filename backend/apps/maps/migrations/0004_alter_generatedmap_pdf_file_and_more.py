from django.db import migrations, models

import apps.maps.models


class Migration(migrations.Migration):
    dependencies = [
        ("maps", "0003_alter_mapjob_credit_cost_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="generatedmap",
            name="pdf_file",
            field=models.FileField(
                max_length=255,
                upload_to=apps.maps.models.generated_map_upload_to,
            ),
        ),
        migrations.AlterField(
            model_name="generatedmap",
            name="png_file",
            field=models.FileField(
                max_length=255,
                upload_to=apps.maps.models.generated_map_upload_to,
            ),
        ),
    ]
