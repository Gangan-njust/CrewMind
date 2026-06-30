"""工作方案数据库模型"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.storage.database import Base


class User(Base):
  __tablename__ = "users"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
  password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TopicRecord(Base):
  __tablename__ = "topics"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  user_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=False
  )
  scenario: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
  title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  topic_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
  user_input: Mapped[str] = mapped_column(Text, nullable=False)
  best_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WorkflowRecord(Base):
  __tablename__ = "workflow_records"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  crew_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
  user_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=True
  )
  topic_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("topics.id"), index=True, nullable=True
  )
  version_number: Mapped[int] = mapped_column(nullable=False, default=1)
  scenario: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
  title: Mapped[str] = mapped_column(String(256), index=True, nullable=False, default="")
  user_input: Mapped[str] = mapped_column(Text, nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
  metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
  tasks_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class WorkflowTemplateRecord(Base):
  __tablename__ = "workflow_templates"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  user_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=False
  )
  name: Mapped[str] = mapped_column(String(128), nullable=False)
  description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
  scenario: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
  user_input: Mapped[str] = mapped_column(Text, nullable=False)
  selected_agents_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CustomAgentRecord(Base):
  __tablename__ = "custom_agents"

  id: Mapped[str] = mapped_column(String(64), primary_key=True)
  user_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=True
  )
  name: Mapped[str] = mapped_column(String(128), nullable=False)
  title: Mapped[str] = mapped_column(String(256), nullable=False)
  background: Mapped[str] = mapped_column(Text, nullable=False)
  goal: Mapped[str] = mapped_column(Text, nullable=False)
  tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  use_reasoning: Mapped[bool] = mapped_column(nullable=False, default=False)


class WorkspaceRecord(Base):
  __tablename__ = "workspaces"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  name: Mapped[str] = mapped_column(String(256), nullable=False)
  description: Mapped[str] = mapped_column(Text, nullable=False, default="")
  user_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=False
  )
  current_selected_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LiteratureRecord(Base):
  __tablename__ = "literatures"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  workspace_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("workspaces.id"), index=True, nullable=False
  )
  title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
  authors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  journal: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  year: Mapped[int | None] = mapped_column(Integer, nullable=True)
  doi: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
  pdf_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
  full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
  uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="pending")


class LiteratureAnalysisRecord(Base):
  __tablename__ = "literature_analysis"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  literature_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("literatures.id"), index=True, nullable=False, unique=True
  )
  tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  contribution_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
  relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
  recommendation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
  key_findings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  limitations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  citation_templates_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  formulas_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  research_background: Mapped[str] = mapped_column(Text, nullable=False, default="")
  research_goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
  methods_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
  conclusion: Mapped[str] = mapped_column(Text, nullable=False, default="")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WorkspaceSelectionRecord(Base):
  __tablename__ = "workspace_selections"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  workspace_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("workspaces.id"), index=True, nullable=False
  )
  selected_literature_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  selection_name: Mapped[str] = mapped_column(String(256), nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WritingProjectRecord(Base):
  __tablename__ = "writing_projects"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  user_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=False
  )
  title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
  paper_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="journal")
  target_journal: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  source_workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
  workspace_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("workspaces.id"), index=True, nullable=True
  )
  outline_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  citation_format: Mapped[str] = mapped_column(String(32), nullable=False, default="gb7714")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WritingSectionRecord(Base):
  __tablename__ = "writing_sections"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  project_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("writing_projects.id"), index=True, nullable=False
  )
  section_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
  title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  is_custom: Mapped[bool] = mapped_column(nullable=False, default=False)
  content: Mapped[str] = mapped_column(Text, nullable=False, default="")
  word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WritingSectionVersionRecord(Base):
  __tablename__ = "writing_section_versions"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  section_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("writing_sections.id"), index=True, nullable=False
  )
  content: Mapped[str] = mapped_column(Text, nullable=False, default="")
  word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
  note: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WritingReferenceRecord(Base):
  __tablename__ = "writing_references"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  section_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("writing_sections.id"), index=True, nullable=False
  )
  literature_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("literatures.id"), index=True, nullable=False
  )
  citation_context: Mapped[str] = mapped_column(Text, nullable=False, default="")
  position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ExperimentRecord(Base):
  __tablename__ = "experiments"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  user_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("users.id"), index=True, nullable=False
  )
  title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  description: Mapped[str] = mapped_column(Text, nullable=False, default="")
  source_workflow_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
  expected_metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="active")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ExperimentEntryRecord(Base):
  __tablename__ = "experiment_entries"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  experiment_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("experiments.id"), index=True, nullable=False
  )
  title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  step_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
  instrument_params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
  raw_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
  entry_type: Mapped[str] = mapped_column(String(32), nullable=False, default="observation")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ExperimentAttachmentRecord(Base):
  __tablename__ = "experiment_attachments"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  entry_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("experiment_entries.id"), index=True, nullable=False
  )
  filename: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  file_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
  mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
  file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  attachment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="photo")
  uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ExperimentDatasetRecord(Base):
  __tablename__ = "experiment_datasets"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  experiment_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("experiments.id"), index=True, nullable=False
  )
  entry_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("experiment_entries.id"), index=True, nullable=True
  )
  filename: Mapped[str] = mapped_column(String(256), nullable=False, default="")
  file_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
  file_type: Mapped[str] = mapped_column(String(16), nullable=False, default="csv")
  columns_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  preview_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ExperimentAnalysisRecord(Base):
  __tablename__ = "experiment_analyses"

  id: Mapped[str] = mapped_column(String(36), primary_key=True)
  dataset_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("experiment_datasets.id"), index=True, nullable=False
  )
  config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
  summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
  charts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  stats_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
  created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
