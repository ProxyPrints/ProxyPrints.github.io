# Hand-written (not `manage.py makemigrations`-generated - same convention as migration 0104
# `cardquestionabstention.py`) to add the optional reason field to
# `cardpicker.models.CardQuestionAbstention` (WTC border question's "Can't tell from this
# scan." answer; the reason-carrying abstention stays the same model, just distinguishable).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0109_card_illustration_rejection"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardquestionabstention",
            name="reason",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
