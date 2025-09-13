from sqlalchemy import (create_engine, Column, Integer, Float, String, Text,
                        DateTime, UniqueConstraint)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

engine = create_engine("sqlite:///trend.db", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Tool(Base):
    __tablename__ = "tools"
    slug = Column(String, primary_key=True)   # "fastapi"
    name = Column(String, nullable=False)     # "FastAPI"
    aliases = Column(Text, default="")        # "fast api|ファストapi"

class Article(Base):
    __tablename__ = "articles"
    id = Column(String, primary_key=True)     # qiita: URL or id
    source = Column(String, nullable=False)   # "qiita" / "zenn"
    tool_slug = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    likes = Column(Integer, default=0)
    published_at = Column(DateTime, index=True)

    __table_args__ = (
        UniqueConstraint("source", "url", name="u_source_url"),
    )

class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_slug = Column(String, index=True)
    days = Column(Integer, default=90)
    articles = Column(Integer, default=0)
    likes_sum = Column(Integer, default=0)
    score = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)

def init_db():
    Base.metadata.create_all(engine)