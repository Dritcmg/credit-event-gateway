from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def session_factory(url: str):
    parsed = make_url(url)
    if parsed.drivername == "postgresql+psycopg":
        existing = parsed.query.get("options", "")
        parsed = parsed.update_query_dict(
            {"options": existing + " -cstatement_timeout=10000 -clock_timeout=5000"}
        )
        engine = create_engine(parsed, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        return engine, sessionmaker(engine, expire_on_commit=False)
    options = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, **options)
    return engine, sessionmaker(engine, expire_on_commit=False)
