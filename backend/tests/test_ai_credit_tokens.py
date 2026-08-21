"""Token → credit conversion for SNR Dev metering."""

from app.services.platform.credits import credits_from_usage, tokens_from_credits


def test_short_chat_costs_one_credit():
    # Typical short tool turn (~4k prompt + 400 completion) → 1 credit
    assert credits_from_usage(4000, 400) == 1


def test_heavy_tool_loop_is_capped():
    # Even large dumps cannot exceed MAX_CREDITS_PER_CHAT (2)
    assert credits_from_usage(80_000, 8_000) == 2


def test_empty_usage_still_minimum_one():
    assert credits_from_usage(0, 0) == 1


def test_tokens_display():
    assert tokens_from_credits(12) == 12 * 12_000
