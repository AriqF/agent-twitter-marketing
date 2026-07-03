CREATE TABLE IF NOT EXISTS content_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES content_batches(id) ON DELETE CASCADE,
    tweet_copy TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    revision_note TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_drafts_batch_id ON content_drafts(batch_id);
CREATE INDEX IF NOT EXISTS idx_content_drafts_status ON content_drafts(status);
