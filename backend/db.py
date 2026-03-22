import os
import aiosqlite

DB_PATH = os.getenv("SQLITE_PATH", "./data/swarm.db")


async def get_db():
    return await aiosqlite.connect(DB_PATH)


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                text        TEXT NOT NULL,
                token_budget INTEGER NOT NULL,
                tokens_used  INTEGER DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'PENDING',
                claims      TEXT,
                trace       TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
