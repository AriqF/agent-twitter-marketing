"""
Database migration runner
Run with: python -m db.migrations.run
"""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DATABASE_URL



async def run_migrations():
    """Run all SQL migration files in order."""
    migrations_dir = Path(__file__).parent

    dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) UNIQUE NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        applied = await conn.fetch("SELECT filename FROM _migrations")
        applied_files = {row['filename'] for row in applied}
        
        migration_files = sorted([
            f for f in migrations_dir.glob("*.sql")
            if f.name not in applied_files
        ])
        
        if not migration_files:
            print("No new migrations to apply.")
            return
        
        for migration_file in migration_files:
            print(f"Applying migration: {migration_file.name}")
            
            sql = migration_file.read_text()
            
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)",
                    migration_file.name
                )
            
            print(f"  ✓ Applied {migration_file.name}")
        
        print(f"\nSuccessfully applied {len(migration_files)} migration(s).")
        
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
