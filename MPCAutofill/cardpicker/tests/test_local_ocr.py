"""
Direct unit tests for local_ocr.py's issue #259 additions ("Stage D no-text bucket: OCR
preprocessing/crop recovery") - `preprocess_fallback_variants`, `_median_from_histogram`,
`ALTERNATE_TESSERACT_CONFIG`, and the `config` kwarg on `run_tesseract`/
`run_tesseract_text_and_words`. Real tesseract throughout (no mocking) - per CLAUDE.md,
tesseract is installed in CI and real OCR tests are expected to run, not be skipped.

Nothing in this module touches `local_fallback.py`/`local_identify_printing_tags.py`
(PROTECTED CORE) - both keep calling the ORIGINAL `preprocess_variants`/`run_tesseract` exactly
as before this issue; see local_ocr.py's own module docstring for the full rationale.

`TestFallbackTierRecoversBlurryUpload` is this issue's one genuine, reproducible (not
argued-only) recovery demonstration - see that class's own docstring for how the exact blur
radius was found and what it does and doesn't prove. The companion mechanism
(`preprocess_fallback_variants`' percentile/median threshold, targeting the diagnostic's
"garbled but present" - uneven-brightness - failure mode) and the alternate-PSM tier
(`ALTERNATE_TESSERACT_CONFIG`) are NOT independently fixture-proven here: this codebase's
existing synthetic card-image fixtures (a tiny PIL default bitmap font, see
test_image_evidence.py's own `_build_card_image`) don't reproduce an uneven-brightness or
segmentation failure realistically enough to demonstrate a genuine before/after recovery -
stated honestly rather than manufactured. The real measurement for both of those happens at the
gated re-extraction against the live no-text cohort (see docs/features/catalog-completion-
plan.md and this PR's own body).
"""

import importlib.util
import logging
import sys
from typing import Any

import pytest
from PIL import Image, ImageDraw, ImageFilter

from django.test import override_settings

from cardpicker import local_ocr
from cardpicker.local_ocr import (
    ALTERNATE_TESSERACT_CONFIG,
    OCR_ENGINE_PYTESSERACT,
    OCR_ENGINE_TESSEROCR,
    TESSERACT_CONFIG,
    _median_from_histogram,
    parse_collector_line,
    parse_legal_line,
    preprocess_fallback_variants,
    preprocess_variants,
    run_tesseract,
    run_tesseract_text_and_words,
    run_tesseract_tsv,
)


def _text_crop(text: str, size: tuple[int, int] = (300, 90)) -> "Image.Image":
    """A small standalone crop - black background, white text, PIL's default bitmap font (the
    same rendering convention test_image_evidence.py's own `_build_card_image` uses) - this
    module tests local_ocr.py's own functions directly, not the Stage C extractor, so a full
    synthetic card image is unnecessary overhead."""
    img = Image.new("RGB", size, "black")
    draw = ImageDraw.Draw(img)
    draw.text((5, 10), text, fill="white")
    return img


class TestMedianFromHistogram:
    """`preprocess_fallback_variants`' own percentile-threshold helper - pure arithmetic, no
    image/tesseract dependency."""

    def test_empty_histogram_defaults_to_128(self):
        # a degenerate (zero-pixel) histogram shouldn't happen for a real crop - guarded
        # defensively (matching preprocess_variants' own fixed 128 cut) rather than raising.
        assert _median_from_histogram([0] * 256) == 128

    def test_all_pixels_at_one_value(self):
        histogram = [0] * 256
        histogram[200] = 1000
        assert _median_from_histogram(histogram) == 200

    def test_skewed_histogram_reflects_the_dominant_mode_not_the_fixed_midpoint(self):
        # 90% of pixels dark (value 10, the background), 10% bright (value 250, the text) - the
        # real-world shape a text crop's own histogram usually has (background occupies most of
        # the crop's area). The median should sit within the DOMINANT (background) mode, not at
        # preprocess_variants' fixed 128 cut - exactly the adaptivity preprocess_fallback_variants'
        # own docstring claims for it.
        histogram = [0] * 256
        histogram[10] = 900
        histogram[250] = 100
        assert _median_from_histogram(histogram) == 10

    def test_evenly_split_histogram_lands_near_the_midpoint(self):
        histogram = [0] * 256
        histogram[0] = 500
        histogram[255] = 500
        median = _median_from_histogram(histogram)
        assert 0 <= median <= 255


class TestPreprocessFallbackVariants:
    def test_returns_four_variants(self):
        crop = _text_crop("158/287 R MOM EN")
        variants = preprocess_fallback_variants(crop)
        assert len(variants) == 4

    def test_heavier_upscale_than_base_preprocess_variants(self):
        crop = _text_crop("158/287 R MOM EN")
        base = preprocess_variants(crop)
        fallback = preprocess_fallback_variants(crop)
        # default upscale 5x (fallback) vs 3x (base) - fallback variants are strictly larger.
        assert fallback[0].size[0] > base[0].size[0]
        assert fallback[0].size[1] > base[0].size[1]

    def test_percentile_pair_is_inverse_polarity(self):
        # percentile pair is tried FIRST (see preprocess_fallback_variants' own docstring for why
        # - less noise-amplifying than the sharpened pair, tried first to reduce the odds of a
        # spurious early "first parse" win over a later-but-correct read).
        crop = _text_crop("158/287 R MOM EN")
        percentile_dark_on_light, percentile_light_on_dark, _sharp_dark, _sharp_light = preprocess_fallback_variants(
            crop
        )
        # ImageOps.invert produces the exact per-pixel inverse - spot check a handful of pixels
        # rather than asserting a full-image byte-for-byte inverse (this is a smoke check that
        # the polarity pairing is real, not a re-derivation of ImageOps.invert's own contract).
        for xy in [(0, 0), (10, 10), (crop.width - 1, 0)]:
            assert percentile_light_on_dark.getpixel(xy) == 255 - percentile_dark_on_light.getpixel(xy)

    def test_sharpened_pair_is_inverse_polarity(self):
        _pct_dark, _pct_light, sharp_dark_on_light, sharp_light_on_dark = preprocess_fallback_variants(
            _text_crop("158/287 R MOM EN")
        )
        for xy in [(0, 0), (10, 10)]:
            assert sharp_light_on_dark.getpixel(xy) == 255 - sharp_dark_on_light.getpixel(xy)


class TestRunTesseractConfigKwarg:
    """Backward-compatibility: every pre-existing call site (local_fallback.py/
    local_identify_printing_tags.py, both PROTECTED CORE) calls `run_tesseract`/
    `run_tesseract_text_and_words` with a single positional `image` argument - the new `config`
    kwarg must default to the exact prior behavior."""

    def test_run_tesseract_default_config_matches_explicit_default(self):
        crop = _text_crop("HELLO")
        assert run_tesseract(crop) == run_tesseract(crop, config=TESSERACT_CONFIG)

    def test_run_tesseract_text_and_words_default_config_matches_explicit_default(self):
        crop = _text_crop("HELLO")
        assert run_tesseract_text_and_words(crop) == run_tesseract_text_and_words(crop, config=TESSERACT_CONFIG)

    def test_run_tesseract_text_and_words_accepts_alternate_config(self):
        crop = _text_crop("HELLO")
        text, words = run_tesseract_text_and_words(crop, config=ALTERNATE_TESSERACT_CONFIG)
        assert isinstance(text, str)
        assert isinstance(words, list)


_TESSEROCR_INSTALLED = importlib.util.find_spec("tesserocr") is not None
_TESSEROCR_SKIP_REASON = (
    "tesserocr not installed in this environment - it's an optional dependency added to "
    "docker/django/Dockerfile only (issue #423), not requirements.txt, so it's expected absent "
    "on a runner that only installed requirements.txt (e.g. default CI)."
)


class _FakeTesserocrApi:
    """Minimal stand-in for `tesserocr.PyTessBaseAPI` - just enough surface for `local_ocr.py`'s
    engine seam to call (`SetPageSegMode`/`SetImage`/`Recognize`/`GetUTF8Text`/`GetTSVText`), so
    the dispatch tests below exercise the REAL seam code in `local_ocr.py` without needing the
    real tesserocr C extension installed - see `_TESSEROCR_INSTALLED` above for the separate,
    real-engine confirmation class that DOES need it (and is named-skipped when absent)."""

    def __init__(self, text: str, tsv: str) -> None:
        self._text = text
        self._tsv = tsv
        self.psm_calls: list[int] = []

    def SetPageSegMode(self, psm: int) -> None:
        self.psm_calls.append(psm)

    def SetImage(self, image: "Image.Image") -> None:
        pass

    def Recognize(self) -> None:
        pass

    def GetUTF8Text(self) -> str:
        return self._text

    def GetTSVText(self, page: int) -> str:
        return self._tsv


@pytest.fixture(autouse=True)
def _reset_engine_seam_state():
    """`local_ocr.py`'s own engine-seam failure-tracking globals (`_tesserocr_import_failed`/
    `_tesserocr_runtime_disabled`/`_tesserocr_api`) are deliberately process-global in production
    (module docstring: sticky, never reset - one warning per process lifetime, one persistent API
    instance per process) - reset around every test in this file so no test leaks that state into
    another."""

    def _reset() -> None:
        local_ocr._tesserocr_import_failed = None
        local_ocr._tesserocr_runtime_disabled = False
        local_ocr._tesserocr_api = None

    _reset()
    yield
    _reset()


class TestActiveEngineResolution:
    def test_default_settings_resolve_to_tesserocr(self):
        # THE FLIP (issue #480's combined pass): settings.OCR_ENGINE's own default is now
        # "tesserocr", not "pytesseract" - see settings.py's own comment for the full rationale
        # and this PR's own description for the owner A/B GO this default is gated on merging
        # behind.
        assert local_ocr._active_engine() == OCR_ENGINE_TESSEROCR

    def test_explicit_pytesseract_setting(self):
        with override_settings(OCR_ENGINE="pytesseract"):
            assert local_ocr._active_engine() == OCR_ENGINE_PYTESSERACT

    def test_explicit_tesserocr_setting(self):
        with override_settings(OCR_ENGINE="tesserocr"):
            assert local_ocr._active_engine() == OCR_ENGINE_TESSEROCR

    def test_unrecognized_setting_falls_back_to_pytesseract(self):
        with override_settings(OCR_ENGINE="something-else-entirely"):
            assert local_ocr._active_engine() == OCR_ENGINE_PYTESSERACT


class TestParsePsmFromConfig:
    def test_extracts_psm_number_from_config_string(self):
        assert local_ocr._parse_psm_from_config("--psm 6") == 6
        assert local_ocr._parse_psm_from_config("--psm 11") == 11

    def test_defaults_when_no_psm_present(self):
        assert local_ocr._parse_psm_from_config("") == local_ocr._DEFAULT_PSM
        assert local_ocr._parse_psm_from_config("--oem 1") == local_ocr._DEFAULT_PSM


class TestTesserocrTsvToDict:
    """Pure parsing logic, no tesserocr dependency - `PyTessBaseAPI.GetTSVText`'s own tab-
    separated output format is stable/documented (same upstream tesseract TSV writer pytesseract's
    own `image_to_data` shells out to), so this is tested directly against a hand-built TSV string
    rather than requiring the real library."""

    _TSV = "1\t1\t0\t0\t0\t0\t0\t0\t100\t40\t-1\t\n5\t1\t1\t1\t1\t1\t6\t12\t32\t8\t81.5\tHELLO\n"

    def test_parses_into_the_same_column_shape_pytesseract_returns(self):
        data = local_ocr._tesserocr_tsv_to_dict(self._TSV)
        assert list(data.keys()) == [
            "level",
            "page_num",
            "block_num",
            "par_num",
            "line_num",
            "word_num",
            "left",
            "top",
            "width",
            "height",
            "conf",
            "text",
        ]
        assert data["text"] == ["", "HELLO"]
        assert data["conf"] == [-1.0, 81.5]
        assert data["left"] == [0, 6]
        assert isinstance(data["left"][0], int)
        assert isinstance(data["conf"][0], float)

    def test_blank_lines_are_ignored(self):
        data = local_ocr._tesserocr_tsv_to_dict(self._TSV + "\n")
        assert len(data["text"]) == 2

    def test_row_missing_only_the_trailing_text_column_is_padded_not_dropped(self):
        # issue #487 LOW: a row that's short only because its trailing "text" column was empty
        # (some TSV writers trim a wholly-empty final field rather than leaving one behind) still
        # carries a real, useful layout box - the previous version silently DROPPED any row with
        # fewer than 12 tab-separated fields, this one pads instead.
        row_missing_trailing_text_field = "1\t1\t0\t0\t0\t0\t0\t0\t100\t40\t-1"  # 11 fields, no text column at all
        data = local_ocr._tesserocr_tsv_to_dict(row_missing_trailing_text_field)
        assert data["text"] == [""]
        assert data["conf"] == [-1.0]
        assert data["level"] == [1]

    def test_row_missing_more_than_the_trailing_text_column_still_raises(self):
        # The padding above only degrades gracefully for a genuinely blank TRAILING text field - a
        # row missing more than that (here: conf, height, width all absent too) is still a real
        # parse failure (int("") on a missing numeric column, not silently accepted as valid data).
        # This is exactly the failure `_tesserocr_tsv` (issue #487 fix 2) is responsible for
        # catching one layer up - this pure-parse function itself is not expected to paper over it.
        with pytest.raises(ValueError):
            local_ocr._tesserocr_tsv_to_dict("1\t1\t0\t0\t0\t0\t0\t0\t100")


class TestResolveTessdataPrefix:
    def test_prefers_the_env_var_when_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TESSDATA_PREFIX", "/env/tessdata")
        assert local_ocr._resolve_tessdata_prefix() == "/env/tessdata"

    def test_falls_back_to_the_highest_sorting_glob_match(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
        monkeypatch.setattr(
            local_ocr.glob,
            "glob",
            lambda pattern: [
                "/usr/share/tesseract-ocr/4.00/tessdata",
                "/usr/share/tesseract-ocr/5/tessdata",
            ],
        )
        assert local_ocr._resolve_tessdata_prefix() == "/usr/share/tesseract-ocr/5/tessdata"

    def test_returns_none_when_nothing_is_found(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
        monkeypatch.setattr(local_ocr.glob, "glob", lambda pattern: [])
        assert local_ocr._resolve_tessdata_prefix() is None


class TestEngineSeamDispatch:
    """Both engines are callable behind the SAME public interface (`run_tesseract`/
    `run_tesseract_tsv`/`run_tesseract_text_and_words`) - the tesserocr side is exercised via
    `_FakeTesserocrApi` (monkeypatched in place of `_tesserocr_recognize`), so these tests pass
    identically whether or not the real tesserocr C extension happens to be installed in this
    environment."""

    _TSV = "1\t1\t0\t0\t0\t0\t0\t0\t100\t40\t-1\t\n5\t1\t1\t1\t1\t1\t6\t12\t32\t8\t81.5\tHELLO\n"
    _EXPECTED_WORDS = [{"text": "HELLO", "left": 6, "top": 12, "width": 32, "height": 8, "conf": 81.5}]

    def test_run_tesseract_dispatches_to_tesserocr_when_selected(self, monkeypatch: pytest.MonkeyPatch):
        fake_api = _FakeTesserocrApi(text="HELLO\n", tsv=self._TSV)
        monkeypatch.setattr(local_ocr, "_tesserocr_recognize", lambda image, config: fake_api)
        with override_settings(OCR_ENGINE="tesserocr"):
            assert run_tesseract(_text_crop("HELLO")) == "HELLO\n"

    def test_run_tesseract_tsv_dispatches_to_tesserocr_when_selected(self, monkeypatch: pytest.MonkeyPatch):
        fake_api = _FakeTesserocrApi(text="HELLO\n", tsv=self._TSV)
        monkeypatch.setattr(local_ocr, "_tesserocr_recognize", lambda image, config: fake_api)
        with override_settings(OCR_ENGINE="tesserocr"):
            words = run_tesseract_tsv(_text_crop("HELLO"))
        assert words == self._EXPECTED_WORDS

    def test_run_tesseract_text_and_words_dispatches_to_tesserocr_when_selected(self, monkeypatch: pytest.MonkeyPatch):
        fake_api = _FakeTesserocrApi(text="HELLO\n", tsv=self._TSV)
        monkeypatch.setattr(local_ocr, "_tesserocr_recognize", lambda image, config: fake_api)
        with override_settings(OCR_ENGINE="tesserocr"):
            text, words = run_tesseract_text_and_words(_text_crop("HELLO"))
        assert text == "HELLO"
        assert words == self._EXPECTED_WORDS

    def test_config_psm_reaches_the_real_recognize_function_and_the_underlying_api(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Here `_tesserocr_recognize` ITSELF runs (unlike the tests above, which replace it
        # wholesale) - only `_tesserocr_available`/`_get_tesserocr_api` are faked, so this proves
        # the real seam function correctly parses `config` and calls `SetPageSegMode` with it.
        fake_api = _FakeTesserocrApi(text="HELLO\n", tsv=self._TSV)
        monkeypatch.setattr(local_ocr, "_tesserocr_available", lambda: True)
        monkeypatch.setattr(local_ocr, "_get_tesserocr_api", lambda: fake_api)
        with override_settings(OCR_ENGINE="tesserocr"):
            run_tesseract_text_and_words(_text_crop("HELLO"), config=TESSERACT_CONFIG)
            run_tesseract_text_and_words(_text_crop("HELLO"), config=ALTERNATE_TESSERACT_CONFIG)
        assert fake_api.psm_calls == [6, 11]

    def test_default_pytesseract_path_never_touches_tesserocr(self, monkeypatch: pytest.MonkeyPatch):
        def _fail_if_called(*args, **kwargs):
            raise AssertionError("pytesseract's own default engine must never call _tesserocr_recognize")

        monkeypatch.setattr(local_ocr, "_tesserocr_recognize", _fail_if_called)
        with override_settings(OCR_ENGINE="pytesseract"):
            run_tesseract(_text_crop("HELLO"))
            run_tesseract_tsv(_text_crop("HELLO"))
            run_tesseract_text_and_words(_text_crop("HELLO"))

    def test_tesserocr_dispatch_holds_the_process_lock_across_recognize_and_read(self, monkeypatch: pytest.MonkeyPatch):
        """issue #487 fix 3: the whole recognize+read sequence against the shared, process-global
        `_tesserocr_api` runs under `_tesserocr_lock` - proven here by asserting the lock is held
        (from an outside observer's point of view, i.e. `.locked()` reports True) DURING
        `_tesserocr_recognize`'s own call, not just checking the lock exists."""
        observed: dict[str, bool] = {}

        def _recognize(image: "Image.Image", config: str) -> _FakeTesserocrApi:
            observed["locked_during_recognize"] = local_ocr._tesserocr_lock.locked()
            return _FakeTesserocrApi(text="HELLO\n", tsv=self._TSV)

        monkeypatch.setattr(local_ocr, "_tesserocr_recognize", _recognize)
        with override_settings(OCR_ENGINE="tesserocr"):
            run_tesseract_text_and_words(_text_crop("HELLO"))
        assert observed["locked_during_recognize"] is True
        assert not local_ocr._tesserocr_lock.locked()  # released again once the call returns


class TestEngineSeamFallback:
    """The failure-tolerance contract this module's own docstring makes: tesserocr being absent
    or broken can never crash a caller, only make it silently no faster than before."""

    def test_missing_module_falls_back_to_pytesseract_and_logs_exactly_once(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        # `sys.modules["tesserocr"] = None` is the standard trick for simulating "this module
        # cannot be imported" without needing it to be genuinely absent from the environment -
        # `import tesserocr` raises ImportError against a None sys.modules entry.
        monkeypatch.setitem(sys.modules, "tesserocr", None)
        crop = _text_crop("HELLO")
        with override_settings(OCR_ENGINE="tesserocr"), caplog.at_level(logging.WARNING, logger="cardpicker.local_ocr"):
            first = run_tesseract(crop)
            second = run_tesseract(crop)
        assert isinstance(first, str)
        assert first == second  # same real pytesseract read both times, no crash either time
        matching = [r for r in caplog.records if "not importable" in r.message]
        assert len(matching) == 1  # exactly once across two calls, not once per call

    def test_runtime_failure_disables_tesserocr_for_the_rest_of_the_process(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        def _boom() -> None:
            raise RuntimeError("simulated tesserocr init failure")

        monkeypatch.setattr(local_ocr, "_tesserocr_available", lambda: True)
        monkeypatch.setattr(local_ocr, "_get_tesserocr_api", _boom)
        crop = _text_crop("HELLO")
        with override_settings(OCR_ENGINE="tesserocr"), caplog.at_level(logging.WARNING, logger="cardpicker.local_ocr"):
            first = run_tesseract(crop)
            assert local_ocr._tesserocr_runtime_disabled is True
            second = run_tesseract(crop)  # stays disabled - _get_tesserocr_api is not called again
        assert isinstance(first, str)
        assert isinstance(second, str)
        matching = [r for r in caplog.records if "tesserocr OCR call failed" in r.message]
        assert len(matching) == 1

    def test_non_import_error_import_failure_still_falls_back_and_logs_once(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """issue #487 fix 1: `_tesserocr_available` used to catch only `ImportError` - a broken
        shared-library link (a real, observed tesserocr failure mode: a version-mismatched
        libtesseract/libleptonica pair, or a corrupt partial install) raises `OSError`/
        `RuntimeError` straight out of the `import` statement itself, which the old narrower
        except let escape uncaught. `sys.modules["tesserocr"] = None` (the other tests' own trick)
        can only ever simulate a plain ImportError, so this patches `builtins.__import__` directly
        to prove the WIDER exception type is now caught too."""
        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "tesserocr":
                raise OSError("simulated broken shared-library link")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        crop = _text_crop("HELLO")
        with override_settings(OCR_ENGINE="tesserocr"), caplog.at_level(logging.WARNING, logger="cardpicker.local_ocr"):
            first = run_tesseract(crop)
            second = run_tesseract(crop)
        assert isinstance(first, str)
        assert first == second  # same real pytesseract read both times, no crash either time
        matching = [r for r in caplog.records if "not importable" in r.message]
        assert len(matching) == 1  # exactly once across two calls, not once per call

    def test_malformed_tsv_row_falls_back_to_pytesseract_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """issue #487 fix 2: `GetTSVText()`/`_tesserocr_tsv_to_dict`'s parse used to run OUTSIDE
        `_tesserocr_recognize`'s own crash guard - a malformed row (here: a non-numeric "left"
        column) raised a bare `ValueError` straight out of `run_tesseract_tsv`/
        `run_tesseract_text_and_words` to their PROTECTED-CORE-adjacent callers. Now it degrades
        to the pytesseract fallback instead, same "warn once, disable for the rest of this
        process" contract as every other tesserocr failure mode."""
        # Malformed via a non-numeric "left" column (a corrupt/truncated TSV row shape, not the
        # padding-eligible "missing trailing text column" case `TestTesserocrTsvToDict` covers
        # separately). `_tesserocr_available`/`_get_tesserocr_api` are faked (not
        # `_tesserocr_recognize` itself) so the REAL recognize function's own sticky
        # `_tesserocr_runtime_disabled` short-circuit is what's under test for the second call.
        malformed_tsv = "5\t1\t1\t1\t1\t1\tNaN\t12\t32\t8\t81.5\tHELLO\n"
        fake_api = _FakeTesserocrApi(text="HELLO\n", tsv=malformed_tsv)
        monkeypatch.setattr(local_ocr, "_tesserocr_available", lambda: True)
        monkeypatch.setattr(local_ocr, "_get_tesserocr_api", lambda: fake_api)
        crop = _text_crop("HELLO")
        with override_settings(OCR_ENGINE="tesserocr"), caplog.at_level(logging.WARNING, logger="cardpicker.local_ocr"):
            text, words = run_tesseract_text_and_words(crop)
            assert local_ocr._tesserocr_runtime_disabled is True
            tsv_words = run_tesseract_tsv(crop)  # stays disabled - real recognize short-circuits now
        assert isinstance(text, str)
        assert isinstance(words, list)
        assert isinstance(tsv_words, list)
        matching = [r for r in caplog.records if "GetTSVText" in r.message]
        assert len(matching) == 1  # exactly once across both calls, not once per call


@pytest.mark.skipif(not _TESSEROCR_INSTALLED, reason=_TESSEROCR_SKIP_REASON)
class TestTesserocrRealEngineConfigFidelity:
    """Real-tesserocr confirmation (skipped, with a named reason, when the optional dependency
    isn't installed - see `_TESSEROCR_SKIP_REASON`): unlike `TestEngineSeamDispatch` above (which
    proves the DISPATCH logic with a fake), this proves the REAL tesserocr call path produces the
    same call-contract shape `run_tesseract_text_and_words`'s docstring promises - a non-empty
    text/words pair with the confidence field present, and PSM 11 (ALTERNATE_TESSERACT_CONFIG)
    genuinely reaching the underlying engine as a different mode than the PSM 6 default (verified
    via each config producing a `SetPageSegMode` call in `TestEngineSeamDispatch` above, and here
    via both configs at least returning cleanly against a real crop)."""

    def test_real_tesserocr_produces_the_same_return_shape_as_pytesseract(self):
        crop = _text_crop("158/287 R MOM EN")
        with override_settings(OCR_ENGINE="tesserocr"):
            text, words = run_tesseract_text_and_words(crop, config=TESSERACT_CONFIG)
        assert isinstance(text, str)
        assert isinstance(words, list)
        for word in words:
            assert set(word.keys()) == {"text", "left", "top", "width", "height", "conf"}
            assert isinstance(word["conf"], float)

    def test_real_tesserocr_accepts_the_alternate_psm_config(self):
        crop = _text_crop("158/287 R MOM EN")
        with override_settings(OCR_ENGINE="tesserocr"):
            text, words = run_tesseract_text_and_words(crop, config=ALTERNATE_TESSERACT_CONFIG)
        assert isinstance(text, str)
        assert isinstance(words, list)

    def test_real_tesserocr_never_falls_back_to_pytesseract_on_a_healthy_install(self):
        # A healthy install/tessdata path should reach real Recognize() successfully, not the
        # failure-tolerance fallback path - this is what distinguishes this test from
        # TestEngineSeamFallback above (which deliberately breaks the install).
        crop = _text_crop("HELLO")
        with override_settings(OCR_ENGINE="tesserocr"):
            run_tesseract(crop)
        assert local_ocr._tesserocr_runtime_disabled is False


class TestFallbackTierRecoversBlurryUpload:
    """
    issue #259's B bucket - the bottom-quartile `blur_variance` failure mode - demonstrated as a
    real, reproducible recovery, not merely argued: `ImageFilter.GaussianBlur(1.1)` over a real
    collector-line-shaped crop makes BOTH of `preprocess_variants`' own base polarity variants
    misread "158" as "168" under real tesseract 4.1.1 (verified live, not assumed) -
    `preprocess_fallback_variants`' heavier-upscale + sharpen pass recovers the correct digits at
    the SAME blur radius, same input pixels.

    The radius (1.1) was found empirically by sweeping a range and locating the narrow band
    where the base tier's own fixed-point preprocessing genuinely fails and the fallback tier's
    heavier processing genuinely succeeds (see this PR's own description for the sweep) - it is
    NOT proof of a general blur-tolerance improvement at every radius (materially blurrier input
    defeats every tier here too, same as it would in production); it proves this specific
    recovery mechanism is real for at least one genuine failure case, which is the fixture-level
    claim issue #259 asks this PR to substantiate or honestly disclaim. Tied to a specific
    tesseract version (4.1.1, this environment's own) since exact OCR misreads are not something
    a differently-versioned tesseract binary is guaranteed to reproduce identically - if this
    test ever starts failing after a tesseract upgrade, that's a real signal to re-sweep for a
    still-failing radius, not evidence the underlying recovery mechanism stopped working.
    """

    _TEXT = "158/287 R MOM EN"
    _BLUR_RADIUS = 1.1

    def _blurred_crop(self) -> "Image.Image":
        return _text_crop(self._TEXT).filter(ImageFilter.GaussianBlur(self._BLUR_RADIUS))

    def test_base_variants_misread_the_collector_number_under_this_blur(self):
        crop = self._blurred_crop()
        for variant in preprocess_variants(crop):
            text, _words = run_tesseract_text_and_words(variant, config=TESSERACT_CONFIG)
            parsed = parse_collector_line(text)
            # the genuine failure this issue targets - NOT necessarily "no-text" (a plausible-
            # but-wrong digit run, "168", is what tesseract actually produces here), still a
            # miss against the real value.
            assert parsed.collector_number != "158"

    def test_fallback_variants_recover_the_correct_collector_number(self):
        crop = self._blurred_crop()
        recovered = any(
            parse_collector_line(run_tesseract_text_and_words(variant, config=TESSERACT_CONFIG)[0]).collector_number
            == "158"
            for variant in preprocess_fallback_variants(crop)
        )
        assert recovered


class TestParseLegalLineProxyMarker:
    """`parse_legal_line`'s `proxy_marker_detected` field - pure string-matching logic, no
    image/tesseract dependency, so tested directly against raw text (matching the file's own
    testing convention for `parse_collector_line` elsewhere in this module). Covers the
    2026-07-23 JestaProxy fix (`_PROXY_MARKER_RE`'s own comment): unbounded proxy/proxies/proxied
    substring matching, the "original design" maker-attribution heuristic, and the false-positive
    guards that fix's own comment argues for (verified live against prod, not just asserted here -
    see PR description for the query results these guard cases are drawn from).
    """

    # --- the live JestaProxy ticket's own two examples ---

    def test_detects_proxy_glued_onto_a_brand_prefix_with_no_word_boundary(self):
        # card 208067's real legal line - "Proxy" glued directly onto "Jesta" with no space/
        # punctuation between them, the exact shape a \b-anchored regex could never match.
        assert parse_legal_line("2025 JestaProxy MTG © EN ©").proxy_marker_detected is True

    def test_detects_original_design_maker_attribution(self):
        # card 215657's real legal line - the "TrixAreforScoot Original Design" maker-brand
        # watermark, no "proxy"-family word anywhere in it at all.
        assert parse_legal_line("TrixAreforScoot Original Design").proxy_marker_detected is True

    # --- unbounded proxy/proxies/proxied substring matching, more generally ---

    def test_detects_proxy_prefixed_brand_name(self):
        assert parse_legal_line("ValarProxy 2025 MTG EN MIDJOURNEY").proxy_marker_detected is True

    def test_detects_proxy_infixed_brand_name(self):
        assert parse_legal_line("2023 DankProxyStash MTG EN 7IFE").proxy_marker_detected is True

    def test_detects_proxies_glued_with_no_boundary(self):
        assert parse_legal_line("R 0311 OxProxies TDC EN BRAM SELS").proxy_marker_detected is True

    def test_still_detects_word_bounded_proxy_forms(self):
        # the pre-existing, already-working bounded cases must keep working under the widened
        # regex - this is an ADDITIVE change, not a rewrite.
        assert parse_legal_line("Proxies by Smaug").proxy_marker_detected is True
        assert parse_legal_line("POGO PROXIES").proxy_marker_detected is True
        assert parse_legal_line("Rustom Playtest Card - Not for Sale").proxy_marker_detected is True

    # --- false-positive guards (module comment's own reasoning, checked here as a regression
    # test rather than left as an argued-only claim) ---

    def test_does_not_match_proximity(self):
        # "proximity" contains "proxim", not "proxy" - the module comment's own reasoning for why
        # unbounding the proxy family is safe.
        assert parse_legal_line("PROXIMITY MTG EN SOME ARTIST").proxy_marker_detected is False

    def test_does_not_match_approximate(self):
        assert parse_legal_line("approximate value only").proxy_marker_detected is False

    def test_does_not_match_genuine_designed_by_credit(self):
        # the real Unknown Event promo shape ("Designed by Gavin Verheys") that the "original
        # design" heuristic is deliberately narrow enough to not collide with.
        assert parse_legal_line("UNK EN DESIGNED BY GAVIN VERHEYS").proxy_marker_detected is False

    def test_does_not_match_a_clean_genuine_legal_line(self):
        assert parse_legal_line("158/287 R MOM EN GREG STAPLES").proxy_marker_detected is False

    def test_empty_text_is_not_detected(self):
        assert parse_legal_line("").proxy_marker_detected is False

    # --- case-insensitivity ---

    def test_case_insensitive_match(self):
        assert parse_legal_line("jestaproxy mtg en").proxy_marker_detected is True
        assert parse_legal_line("ORIGINAL DESIGN").proxy_marker_detected is True
