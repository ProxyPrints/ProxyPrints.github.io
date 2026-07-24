from django.apps import AppConfig


class CardpickerConfig(AppConfig):
    name = "cardpicker"

    def ready(self) -> None:
        # Stage E Phase 2 (docs/proposals/stage-e-streaming.md §3 decision (1)) - registers the
        # card-create/evidence-change post_save receivers (cardpicker/stage_e_signals.py).
        # Connecting a signal receiver is cheap and side-effect-free by itself; each receiver is
        # its own no-op while settings.STAGE_E_STREAMING_ENABLED is False (default), so importing
        # this module here has no observable effect until that flag flips - see that module's own
        # docstring.
        from cardpicker import stage_e_signals  # noqa: F401
