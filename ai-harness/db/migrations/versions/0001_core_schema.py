"""Ядро схемы: 34 таблицы по СТ FNR-13 §4.1.1 (с одобренными отклонениями:
task_run для режима «параллельно», is_published на flow_version, версии task_artifact).

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Проекты (ФТ-ah-46, ФТ-ah-47) ---
    op.create_table(
        "project",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("mnemonic", sa.String(10), nullable=False, unique=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("base_branch", sa.String(128), nullable=False, server_default="main"),
        sa.Column("description", sa.Text()),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("next_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 64", name="ck_project_name_len"),
        sa.CheckConstraint("mnemonic ~ '^[A-Z0-9]{2,10}$'", name="ck_project_mnemonic_format"),
    )

    # Мнемоники удалённых проектов не переиспользуются (ФТ-ah-47)
    op.create_table("dead_mnemonic", sa.Column("mnemonic", sa.String(10), primary_key=True))

    # --- Пользователи: человек или ИИ-агент (ФТ-ah-72); ролей нет (решение 3.1-5) ---
    op.create_table(
        "user",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("user_type", sa.String(8), nullable=False),
        sa.Column("is_chat_bot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_service", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("password_hash", sa.Text()),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("user_type IN ('human','agent')", name="ck_user_type"),
        sa.CheckConstraint("user_type <> 'human' OR password_hash IS NOT NULL", name="ck_user_human_password"),
    )

    op.create_table(
        "task_type",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("key", sa.String(24), nullable=False, unique=True),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # --- Alias-колонки доски; статус живёт ровно в одной колонке (ФТ-ah-58, ФТ-ah-67) ---
    op.create_table(
        "alias_column",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#888888"),
        sa.Column("position", sa.Integer(), nullable=False),
    )

    # --- Версии flow (ФТ-ah-56); is_published=false — рабочая копия (решение владельца 25.10.2026) ---
    op.create_table(
        "flow_version",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_type_id", pg.UUID(), sa.ForeignKey("task_type.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("task_type_id", "version", name="uq_flow_version"),
    )
    op.create_index(
        "uq_flow_current_draft", "flow_version", ["task_type_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "flow_status",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("flow_version_id", pg.UUID(), sa.ForeignKey("flow_version.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status_key", sa.String(32), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("stage_desc", sa.String(2000)),
        sa.Column("checklist_gate", sa.String(16)),
        sa.Column("is_entry", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("alias_column_id", pg.UUID(), sa.ForeignKey("alias_column.id")),
        sa.UniqueConstraint("flow_version_id", "status_key", name="uq_flow_status_key"),
        sa.CheckConstraint(
            "checklist_gate IS NULL OR checklist_gate IN ('developer','reviewer','tester')",
            name="ck_flow_status_gate",
        ),
        sa.CheckConstraint("status_key ~ '^[a-z0-9_]+$'", name="ck_flow_status_key_format"),
    )

    op.create_table(
        "flow_transition",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("flow_version_id", pg.UUID(), sa.ForeignKey("flow_version.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=False),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("runner", sa.String(16), nullable=False),
        sa.Column("display", sa.String(64), nullable=False),  # формулировки постановки длиннее 32 символов
        sa.Column("cond_checklist", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cond_links", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cond_artifact", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rule_code", sa.String(16)),
        sa.UniqueConstraint("flow_version_id", "from_status", "to_status", name="uq_flow_transition"),
        sa.CheckConstraint("runner IN ('human','agent','auto','auto_or_agent')", name="ck_flow_transition_runner"),
    )

    # --- Задача: единая сущность с типом (ФТ-ah-1); резерв демона уникален (НФТ-ah-6);
    #     исполнители — только в task_assignee (ФТ-ah-10) ---
    op.create_table(
        "task",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("project_id", pg.UUID(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("task_type_id", pg.UUID(), sa.ForeignKey("task_type.id"), nullable=False),
        sa.Column("title", sa.String(64), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=False),
        sa.Column("status_key", sa.String(32), nullable=False),
        sa.Column("flow_version_id", pg.UUID(), sa.ForeignKey("flow_version.id"), nullable=False),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("story_id", pg.UUID(), sa.ForeignKey("task.id")),
        sa.Column("author_id", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reserved_by", pg.UUID(), sa.ForeignKey("user.id")),
        sa.Column("reserved_at", pg.TIMESTAMP(timezone=True)),
        sa.Column("heartbeat_at", pg.TIMESTAMP(timezone=True)),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("rework_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("m4_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("blocked_reason", sa.Text()),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 64", name="ck_task_title_len"),
        sa.CheckConstraint("char_length(description_md) <= 20000", name="ck_task_desc_len"),
        sa.CheckConstraint("priority IN ('low','medium','high','critical')", name="ck_task_priority"),
        sa.CheckConstraint("id <> story_id", name="ck_task_not_self_story"),
    )
    op.create_index("idx_task_status", "task", ["project_id", "status_key"])
    op.create_index("idx_task_story", "task", ["story_id"])

    op.create_table(
        "checklist",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("task_id", "kind", name="uq_checklist_task_kind"),
        sa.CheckConstraint("kind IN ('developer','reviewer','tester','psi')", name="ck_checklist_kind"),
    )

    op.create_table(
        "checklist_item",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("checklist_id", pg.UUID(), sa.ForeignKey("checklist.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False, server_default="item"),
        sa.Column("level", sa.SmallInteger()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="todo"),
        sa.Column("psi_expected", sa.Text()),
        sa.Column("psi_actual", sa.Text()),
        sa.Column("bug_task_id", pg.UUID(), sa.ForeignKey("task.id")),
        sa.CheckConstraint("kind IN ('heading','item')", name="ck_checklist_item_kind"),
        sa.CheckConstraint("level IS NULL OR level BETWEEN 1 AND 5", name="ck_checklist_item_level"),
        sa.CheckConstraint(
            "kind = 'heading' OR status IN ('todo','in_progress','closed','done','failed')",
            name="ck_checklist_item_status",
        ),
    )

    # Связи задач (ФТ-ah-7): каноническое направление, одна запись на связь
    op.create_table(
        "task_relation",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("from_task", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_task", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("from_task <> to_task", name="ck_relation_not_self"),
        sa.UniqueConstraint("from_task", "to_task", "kind", name="uq_task_relation"),
        sa.CheckConstraint("kind IN ('do_after','blocked_by')", name="ck_relation_kind"),
    )

    # --- Хроники: лёгкая запись всегда, тяжёлое — отдельно (ФТ-ah-43, ФТ-ah-44) ---
    op.create_table(
        "chronicle_payload",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("expires_at", pg.TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_table(
        "chronicle",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("author_id", pg.UUID(), sa.ForeignKey("user.id")),
        sa.Column("author_kind", sa.String(8), nullable=False),
        sa.Column("rule_code", sa.String(16)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_id", pg.UUID(), sa.ForeignKey("chronicle_payload.id")),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "event_type IN ('field','transition','force','agent','denied','psi','bug')",
            name="ck_chronicle_event_type",
        ),
        sa.CheckConstraint("author_kind IN ('human','agent','eve','auto')", name="ck_chronicle_author_kind"),
        sa.CheckConstraint("author_kind <> 'auto' OR rule_code IS NOT NULL", name="ck_chronicle_auto_rule"),
    )
    op.create_index("idx_chronicle_task", "chronicle", ["task_id", "created_at"])

    # --- ПСИ (ФТ-ah-39…42): документ с версиями, прогоны, снапшот пунктов ---
    op.create_table(
        "psi_document",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("story_id", pg.UUID(), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("author_id", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("story_id", "version", name="uq_psi_document"),
    )

    op.create_table(
        "psi_run",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("psi_doc_id", pg.UUID(), sa.ForeignKey("psi_document.id"), nullable=False),
        sa.Column("run_by", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("passed", sa.SmallInteger(), nullable=False),
        sa.Column("failed", sa.SmallInteger(), nullable=False),
        sa.Column("ran_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Снапшот пунктов прогона: протокол самодостаточен и не зависит от сброса чеклиста (ФТ-ah-41)
    op.create_table(
        "psi_run_item",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("psi_run_id", pg.UUID(), sa.ForeignKey("psi_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", pg.UUID(), sa.ForeignKey("checklist_item.id")),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_text", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("actual", sa.Text()),
        sa.CheckConstraint("status IN ('todo','done','failed')", name="ck_psi_run_item_status"),
    )

    op.create_table(
        "notification",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("recipient_id", pg.UUID(), sa.ForeignKey("user.id")),
        sa.Column("event_key", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("tech_detail", sa.Text()),
        sa.Column("resolved_at", pg.TIMESTAMP(timezone=True)),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_notification_open", "notification", ["code", "event_key"],
        unique=True, postgresql_where=sa.text("resolved_at IS NULL"),
    )

    # Журнал настроек: полный диф, секреты масками (ФТ-ah-64)
    op.create_table(
        "settings_journal",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("who_id", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("diff", pg.JSONB(), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # --- Теги (ФТ-ah-6): 1–5 на задачу, один — авторский; осиротевшие удаляются ---
    op.create_table(
        "tag",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, unique=True),
        sa.Column("is_author", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "task_tag",
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", pg.UUID(), sa.ForeignKey("tag.id"), primary_key=True),
    )

    # Несколько исполнителей задачи (ФТ-ah-10, ФТ-ah-63) — единственный источник правды
    op.create_table(
        "task_assignee",
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("user.id"), primary_key=True),
    )

    op.create_table(
        "task_comment",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Артефакты этапов (ФТ-ah-38): повторный цикл доработки = новая версия
    op.create_table(
        "task_artifact",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("created_by", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("task_id", "kind", "version", name="uq_task_artifact"),
        sa.CheckConstraint("kind IN ('dev_report','review_report','qa_report')", name="ck_task_artifact_kind"),
    )

    # Ветки задач (ФТ-ah-37): task/<task-code>, worktree, слияние перед done
    op.create_table(
        "task_branch",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id"), nullable=False, unique=True),
        sa.Column("branch_name", sa.String(64), nullable=False),
        sa.Column("worktree_path", sa.Text(), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("merged_at", pg.TIMESTAMP(timezone=True)),
    )

    # Прогоны агентов (решение владельца 25.10.2026 — режим «параллельно», AC-4.4.3.1):
    # heartbeat/исход привязаны к прогону, а не к задаче; reserved_by остаётся
    # денормализацией «текущего писателя» для UI и правила одного писателя в git.
    op.create_table(
        "task_run",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_id", pg.UUID(), sa.ForeignKey("task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("status_key", sa.String(32), nullable=False),
        sa.Column("attempt_no", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("started_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("heartbeat_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", pg.TIMESTAMP(timezone=True)),
        sa.Column("outcome", sa.String(16)),
        sa.Column("detail", sa.Text()),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('success','failed','blocked','interrupted')",
            name="ck_task_run_outcome",
        ),
    )
    op.create_index(
        "uq_task_run_active", "task_run", ["task_id", "agent_id"],
        unique=True, postgresql_where=sa.text("finished_at IS NULL"),
    )
    op.create_index("idx_task_run_task", "task_run", ["task_id"])

    # --- Подключения провайдеров (ФТ-ah-59…61, решение 3.1-12): AES-256-GCM, ровно одно активное ---
    op.create_table(
        "connection",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("token_encrypted", pg.BYTEA(), nullable=False),
        sa.Column("token_tail", sa.String(8), nullable=False),
        sa.Column("check_status", sa.String(12), nullable=False, server_default="unchecked"),
        sa.Column("check_error", sa.Text()),
        sa.Column("checked_at", pg.TIMESTAMP(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("protocol IN ('openai','anthropic')", name="ck_connection_protocol"),
        sa.CheckConstraint(
            "check_status IN ('active','checked','unchecked','error')", name="ck_connection_check_status"
        ),
    )
    op.create_index(
        "uq_connection_active", "connection", ["is_active"],
        unique=True, postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "agent_profile",
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(200), nullable=False),
        sa.Column("skill_md", sa.Text(), nullable=False),
        sa.Column("connection_id", pg.UUID(), sa.ForeignKey("connection.id")),
        sa.Column("is_preset", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("preset_source", pg.JSONB()),
    )

    # Матрица назначений (ФТ-ah-63): тип → статус → исполнители + режим
    op.create_table(
        "assignment",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("task_type_id", pg.UUID(), sa.ForeignKey("task_type.id"), nullable=False),
        sa.Column("status_key", sa.String(32), nullable=False),
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False, server_default="replacement"),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("task_type_id", "status_key", "user_id", name="uq_assignment"),
        sa.CheckConstraint("mode IN ('parallel','replacement')", name="ck_assignment_mode"),
    )

    op.create_table(
        "provider_preset",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("protocol IN ('openai','anthropic')", name="ck_provider_preset_protocol"),
    )

    # Пресеты flow (ФТ-ah-57): библиотека, импорт/экспорт YAML
    op.create_table(
        "flow_preset",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("updated_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("updated_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # История диалогов Eve (ФТ-ah-50)
    op.create_table(
        "chat_message",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("task_code", sa.String(16)),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_chat_message_role"),
    )

    # Сессии входа (ФТ-ah-73): httpOnly-cookie, хранится только хэш токена
    op.create_table(
        "session",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("user_id", pg.UUID(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", pg.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    for table in (
        "session", "chat_message", "app_setting", "flow_preset", "provider_preset",
        "assignment", "agent_profile", "connection", "task_run", "task_branch",
        "task_artifact", "task_comment", "task_assignee", "task_tag", "tag",
        "settings_journal", "notification", "psi_run_item", "psi_run", "psi_document",
        "chronicle", "chronicle_payload", "task_relation", "checklist_item",
        "checklist", "task", "flow_transition", "flow_status", "flow_version",
        "alias_column", "task_type", "user", "dead_mnemonic", "project",
    ):
        op.drop_table(table)
    op.execute("DROP INDEX IF EXISTS uq_flow_current_draft")
