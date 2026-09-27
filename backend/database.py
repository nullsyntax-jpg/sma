"""
Database layer — SQLAlchemy models for the Multi-Database Entity Resolution platform.

Design notes (see ARCHITECTURE.md for the full write-up):
- raw_records keeps the untouched source row (as JSON) for full traceability.
- normalized_records holds the cleaned canonical fields used for matching.
- master_entities is the unified "golden record" table.
- master_entity_fields stores PER-FIELD provenance: for every value on a master
  entity we know exactly which source/record it came from. This is what lets
  the UI answer "why does this entity have this phone number?".
- match_log records every matching decision (what matched, on which field,
  what confidence) — this is the audit trail for the matching engine.
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, DateTime,
    ForeignKey, Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "entity_resolution.db"))
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

CANONICAL_FIELDS = ["email", "phone", "name", "username", "member_id", "address", "company"]


class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    source_type = Column(String, default="csv")  # csv | sql
    created_at = Column(DateTime, default=datetime.utcnow)

    batches = relationship("ImportBatch", back_populates="source")


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"))
    filename = Column(String)
    part_label = Column(String, nullable=True)   # e.g. "Part 1 of 3" for multi-part imports
    status = Column(String, default="uploaded")
    # uploaded -> mapping_suggested -> mapping_confirmed -> cleaning -> indexing
    # -> matching -> enriching -> completed / completed_with_errors
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    matched_rows = Column(Integer, default=0)
    new_entity_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    source = relationship("Source", back_populates="batches")


class FieldMapping(Base):
    __tablename__ = "field_mappings"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id"))
    source_column = Column(String)
    canonical_field = Column(String)   # one of CANONICAL_FIELDS, or "ignore"
    confidence = Column(Float, default=0.0)
    suggested_by = Column(String, default="ai")  # ai | heuristic | user
    confirmed = Column(Boolean, default=False)


class RawRecord(Base):
    __tablename__ = "raw_records"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id"))
    source_id = Column(Integer, ForeignKey("sources.id"))
    row_index = Column(Integer)
    data_json = Column(Text)   # untouched original row, as JSON
    created_at = Column(DateTime, default=datetime.utcnow)


class NormalizedRecord(Base):
    __tablename__ = "normalized_records"
    id = Column(Integer, primary_key=True)
    raw_record_id = Column(Integer, ForeignKey("raw_records.id"))
    batch_id = Column(Integer, ForeignKey("import_batches.id"))
    source_id = Column(Integer, ForeignKey("sources.id"))

    email = Column(String, index=True, nullable=True)
    phone = Column(String, index=True, nullable=True)
    username = Column(String, index=True, nullable=True)
    member_id = Column(String, index=True, nullable=True)
    name = Column(String, nullable=True)
    address = Column(String, nullable=True)
    company = Column(String, nullable=True)

    raw_json = Column(Text)          # original values for the mapped fields
    master_entity_id = Column(Integer, ForeignKey("master_entities.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MasterEntity(Base):
    __tablename__ = "master_entities"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True, nullable=True)
    email = Column(String, index=True, nullable=True)
    phone = Column(String, index=True, nullable=True)
    username = Column(String, index=True, nullable=True)
    member_id = Column(String, index=True, nullable=True)
    address = Column(String, nullable=True)
    company = Column(String, nullable=True)
    status = Column(String, default="active")  # active | newly_created | unresolved
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    fields = relationship("MasterEntityField", back_populates="entity")


class MasterEntityField(Base):
    """Per-field provenance: which source/record contributed each value."""
    __tablename__ = "master_entity_fields"
    id = Column(Integer, primary_key=True)
    master_entity_id = Column(Integer, ForeignKey("master_entities.id"))
    field_name = Column(String)
    value = Column(String)
    source_id = Column(Integer, ForeignKey("sources.id"))
    normalized_record_id = Column(Integer, ForeignKey("normalized_records.id"))
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    entity = relationship("MasterEntity", back_populates="fields")


class MatchLog(Base):
    """Audit trail: every matching / enrichment decision the engine made."""
    __tablename__ = "match_log"
    id = Column(Integer, primary_key=True)
    master_entity_id = Column(Integer, ForeignKey("master_entities.id"))
    normalized_record_id = Column(Integer, ForeignKey("normalized_records.id"))
    matched_on_field = Column(String)
    matched_value = Column(String)
    confidence = Column(Float)
    hop = Column(Integer, default=0)   # which enrichment hop discovered this
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()
