"""Outreach candidate scoring from product.yaml keywords config."""

from config import PRODUCT, X_ACCOUNT_USERNAME


def _keywords_config() -> dict:
    return PRODUCT.get("keywords") or {}


def _outreach_config() -> dict:
    return _keywords_config().get("outreach") or {}


def _filtering_config() -> dict:
    return _keywords_config().get("filtering") or {}


def _scoring_weights() -> dict:
    return _keywords_config().get("scoring") or {}


def _thresholds() -> dict:
    return _keywords_config().get("thresholds") or {}


def get_reply_threshold() -> int:
    return int(_thresholds().get("reply", 60))


def get_engagement_min() -> int:
    return int(_thresholds().get("engagement_min", 5))


def get_brand_accounts() -> set[str]:
    accounts = _outreach_config().get("brand_accounts") or []
    normalized = {a.lower().lstrip("@") for a in accounts if a}
    if X_ACCOUNT_USERNAME:
        normalized.add(X_ACCOUNT_USERNAME.lower().lstrip("@"))
    return normalized


def get_negative_keywords() -> list[str]:
    return _filtering_config().get("negative_keywords") or []


def get_conversation_query_keywords() -> list[str]:
    return _outreach_config().get("conversation_keywords") or []


def _text_contains(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def _any_match(text: str, keywords: list[str]) -> bool:
    return any(_text_contains(text, kw) for kw in keywords)


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if _text_contains(text, kw)]


def is_brand_account(username: str | None) -> bool:
    if not username:
        return False
    return username.lower().lstrip("@") in get_brand_accounts()


def has_negative_keyword(text: str) -> bool:
    return _any_match(text, get_negative_keywords())


def total_engagement(public_metrics: dict | None) -> int:
    if not public_metrics:
        return 0
    return (
        public_metrics.get("likes", 0)
        + public_metrics.get("retweets", 0)
        + public_metrics.get("replies", 0)
    )


def score_outreach_candidate(
    tweet_text: str,
    *,
    public_metrics: dict | None = None,
    is_duplicate_content: bool = False,
) -> tuple[int, list[str]]:
    """
    Score a tweet for outreach reply potential.
    Returns (score, list of matched signal labels).
    """
    weights = _scoring_weights()
    outreach = _outreach_config()
    text = tweet_text or ""
    signals: list[str] = []
    score = 0

    conv_kw = outreach.get("conversation_keywords") or []
    if _any_match(text, conv_kw):
        score += weights.get("contains_conversation_keyword", 0)
        signals.append("conversation_keyword")

    intent_kw = outreach.get("intent_keywords") or []
    matched_intent = _matched_keywords(text, intent_kw)
    if matched_intent:
        score += weights.get("contains_intent_keyword", 0)
        signals.append(f"intent:{','.join(matched_intent[:3])}")

    pain_kw = outreach.get("pain_point_keywords") or []
    matched_pain = _matched_keywords(text, pain_kw)
    if matched_pain:
        score += weights.get("contains_pain_point", 0)
        signals.append(f"pain_point:{','.join(matched_pain[:3])}")

    buying_kw = outreach.get("buying_signals") or []
    matched_buying = _matched_keywords(text, buying_kw)
    if matched_buying:
        score += weights.get("contains_buying_signal", 0)
        signals.append(f"buying_signal:{','.join(matched_buying[:3])}")

    question_patterns = outreach.get("question_patterns") or []
    if _any_match(text, question_patterns):
        score += weights.get("contains_question_pattern", 0)
        signals.append("question_pattern")

    if total_engagement(public_metrics) >= get_engagement_min():
        score += weights.get("engagement_above_threshold", 0)
        signals.append("engagement_above_threshold")

    score += weights.get("author_not_brand_account", 0)
    signals.append("author_not_brand_account")

    if has_negative_keyword(text):
        score += weights.get("contains_negative_keyword", 0)
        signals.append("negative_keyword")

    if is_duplicate_content:
        score += weights.get("duplicate_conversation", 0)
        signals.append("duplicate_conversation")

    return score, signals
