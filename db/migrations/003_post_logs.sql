CREATE TABLE IF NOT EXISTS post_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES content_drafts(id),
    twitter_post_id TEXT NOT NULL,
    posted_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'success'
);

CREATE INDEX IF NOT EXISTS idx_post_logs_draft_id ON post_logs(draft_id);
