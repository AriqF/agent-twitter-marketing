CREATE TABLE IF NOT EXISTS content_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_brief JSONB NOT NULL,
    content_plan JSONB NOT NULL,
    status TEXT DEFAULT 'pending',
    scheduled_from TIMESTAMPTZ,
    scheduled_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
