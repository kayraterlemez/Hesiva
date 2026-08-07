from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a factory for sessions whose transactions are owned by the caller."""
    return sessionmaker(bind=engine)
