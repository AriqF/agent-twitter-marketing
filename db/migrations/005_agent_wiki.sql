CREATE TABLE IF NOT EXISTS agent_wiki (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category VARCHAR(50) NOT NULL,
    key TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    source_ids UUID[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_wiki_category ON agent_wiki(category);
CREATE INDEX IF NOT EXISTS idx_agent_wiki_key ON agent_wiki(key);
