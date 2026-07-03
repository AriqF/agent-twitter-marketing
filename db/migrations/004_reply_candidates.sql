CREATE TABLE IF NOT EXISTS reply_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twitter_post_id TEXT NOT NULL UNIQUE,
    author_username TEXT,
    tweet_content TEXT,
    keyword_matched TEXT,
    react_reasoning TEXT,
    react_decision VARCHAR(50),
    reply_text TEXT,
    status VARCHAR(50),
    revision_note TEXT,
    approved_at TIMESTAMPTZ,
    replied_at TIMESTAMPTZ,
    scanned_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reply_candidates_status ON reply_candidates(status);
CREATE INDEX IF NOT EXISTS idx_reply_candidates_twitter_post_id ON reply_candidates(twitter_post_id);
