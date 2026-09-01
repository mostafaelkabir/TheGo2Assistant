# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""PII detection, redaction, and the egress guard.

Precision is the property under test. A redactor that fires on ordinary content
gets switched off, and a switched-off control protects nothing — so the
negative cases here carry as much weight as the positive ones. Several are
verbatim from a real corpus where an earlier version produced only false
positives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from go2.config import get_settings
from go2.security.guard import PiiBlockedError, screen
from go2.security.pii import PiiKind, detect, redact, summarise

if TYPE_CHECKING:
    from collections.abc import Iterator

# A Luhn-valid test number reserved by the card networks for exactly this.
TEST_CARD = "4111 1111 1111 1111"
EXPECTED_TWO = 2


@pytest.fixture
def _policy() -> Iterator[None]:
    """Isolate the settings cache so policy changes do not leak between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestValidatedDetection:
    """Checksums are what separate a detection from a guess."""

    def test_a_luhn_valid_card_is_found(self) -> None:
        assert summarise(detect(f"Card {TEST_CARD} on file")) == {"credit_card": 1}

    def test_a_luhn_invalid_number_is_not(self) -> None:
        # Sixteen digits alone is not a card. In a corpus of run ids and
        # hashes, matching on shape would flag constantly.
        assert detect("Run id 4111111111111112 in the log") == []

    def test_a_valid_iban_is_found(self) -> None:
        assert summarise(detect("IBAN GB82 WEST 1234 5698 7654 32")) == {"iban": 1}

    def test_an_iban_failing_mod97_is_not(self) -> None:
        assert detect("Ref GB99 WEST 1234 5698 7654 31 here") == []


class TestPrecisionOnRealContent:
    """Verbatim lines from an ML corpus that must stay clean."""

    @pytest.mark.parametrize(
        "line",
        [
            "11% of detections \u00d7 70% \u00d7 +0.027 IoU \u2248 +0.002 mean IoU",
            "uniform +0.005\u20130.008 mAP50, no ranking change",
            "woman-recall +0.0005 = one more woman out of the set",
            "best `0.45/0.49/0.49` at conf 0.45",
            "475,207 images \u2192 1,579,649 detections, 100% verified",
            "best.ckpt.df4690DF and last.ckpt.5dBA0217",
            "2026-08-28 v1.28.2 shard1of3 on port 5433",
        ],
    )
    def test_ordinary_technical_content_is_clean(self, line: str) -> None:
        # Every one of these produced a false positive in an earlier version.
        assert detect(line) == [], f"false positive on: {line}"


class TestPhones:
    """A phone must be announced and long enough to be one."""

    @pytest.mark.parametrize(
        "line",
        ["Call +44 20 7946 0958 today", "Reach 020-7946-0958", "Call (020) 7946 0958"],
    )
    def test_real_phone_shapes_are_found(self, line: str) -> None:
        assert summarise(detect(line)) == {"phone": 1}

    def test_a_signed_decimal_is_not_a_phone(self) -> None:
        # The exact failure that made every phone hit in the first real scan a
        # false positive: "+0.027" read as country code plus subscriber number.
        assert detect("delta of +0.027 IoU") == []

    def test_too_few_digits_is_not_a_phone(self) -> None:
        assert detect("+1 22 333") == []


class TestRedaction:
    """Masking keeps the sentence, loses the value."""

    def test_the_value_is_replaced_by_its_category(self) -> None:
        masked, findings = redact(f"Pay with {TEST_CARD} now")
        assert masked == "Pay with [CREDIT_CARD] now"
        assert TEST_CARD not in masked
        assert len(findings) == 1

    def test_surrounding_text_survives(self) -> None:
        # The redacted text is still embedded, so it has to keep its meaning.
        masked, _ = redact("Email priya@example.com about the renewal fee")
        assert "about the renewal fee" in masked

    def test_clean_text_is_returned_unchanged(self) -> None:
        text = "The annual renewal fee is 4,500 EUR"
        assert redact(text) == (text, [])

    def test_several_values_in_one_string(self) -> None:
        masked, findings = redact(f"card {TEST_CARD} and mail a@b.com")
        assert len(findings) == EXPECTED_TWO
        assert "[CREDIT_CARD]" in masked
        assert "[EMAIL]" in masked

    def test_a_restricted_scan_ignores_other_kinds(self) -> None:
        found = detect("mail a@b.com", kinds=frozenset({PiiKind.CREDIT_CARD}))
        assert found == []


@pytest.mark.usefixtures("_policy")
class TestEgressGuard:
    """Nothing reaches a third party without passing through here."""

    def test_redact_is_the_default_and_masks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GO2_PII_POLICY", "redact")
        get_settings.cache_clear()
        result = screen([f"pay {TEST_CARD}"])
        assert TEST_CARD not in result.texts[0]
        assert result.counts == {"credit_card": 1}

    def test_block_refuses_rather_than_masking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GO2_PII_POLICY", "block")
        get_settings.cache_clear()
        with pytest.raises(PiiBlockedError, match="credit_card"):
            screen([f"pay {TEST_CARD}"])

    def test_block_names_both_ways_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GO2_PII_POLICY", "block")
        get_settings.cache_clear()
        with pytest.raises(PiiBlockedError, match="GO2_EMBEDDING_PROVIDER=local"):
            screen([f"pay {TEST_CARD}"])

    def test_allow_is_an_explicit_opt_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GO2_PII_POLICY", "allow")
        get_settings.cache_clear()
        assert screen([f"pay {TEST_CARD}"]).texts == [f"pay {TEST_CARD}"]

    def test_clean_text_passes_through_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GO2_PII_POLICY", "redact")
        get_settings.cache_clear()
        result = screen(["the renewal fee is 4,500 EUR"])
        assert result.texts == ["the renewal fee is 4,500 EUR"]
        assert not result.redacted_any
