DO $$ BEGIN
    CREATE TYPE wikicategory AS ENUM (
        'approved_pattern',
        'rejection_pattern',
        'revision_pattern',
        'product'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS agent_wiki (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category wikicategory NOT NULL,
    key TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    source_ids UUID[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_wiki_category ON agent_wiki(category);
CREATE INDEX IF NOT EXISTS idx_agent_wiki_key ON agent_wiki(key);
