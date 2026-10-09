"""add h3 to alpn enum

Revision ID: 305943d779c4
Revises: 31f92220c0d0
Create Date: 2024-07-03 19:27:15.282711

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '305943d779c4'
down_revision = '31f92220c0d0'
branch_labels = None
depends_on = None


# The original PostgreSQL enum type created in migration c106bb40c861 is named
# "proxyhostalpn" (not "alpn"). This migration renames it to "alpn" while
# simultaneously adding h3 values.
old_type_name = "proxyhostalpn"   # actual type name in DB from c106bb40c861
new_type_name = "alpn"            # new type name after this migration
temp_enum_name = f"temp_{new_type_name}"  # "temp_alpn"

old_values = ("none", "h2", "http/1.1", "h2,http/1.1")
new_values = ("h3", "h3,h2", "h3,h2,http/1.1", *old_values)
# on downgrade
downgrade_from = ("h3", "h3,h2", "h3,h2,http/1.1", "")
downgrade_to = "none"

old_type = sa.Enum(*old_values, name=old_type_name)
new_type = sa.Enum(*new_values, name=new_type_name)
temp_type = sa.Enum(*new_values, name=temp_enum_name)

# Describing of table
table_name = "hosts"
column_name = "alpn"
temp_table = sa.sql.table(
    table_name,
    sa.Column(
        column_name,
        new_type,
        nullable=False
    )
)


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Create temp type (temp_alpn) to bridge old→new
    temp_type.create(bind, checkfirst=False)

    # PostgreSQL: DROP DEFAULT before ALTER COLUMN TYPE.
    # The column has server_default='none' which PostgreSQL cannot auto-cast
    # to the new enum type during ALTER COLUMN.
    if dialect == 'postgresql':
        op.execute(f'ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP DEFAULT')

    # Step 1: change column from proxyhostalpn → temp_alpn
    # SQLite will create a temp table for this
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=old_type,
            type_=temp_type,
            existing_nullable=False,
            postgresql_using=f"{column_name}::text::{temp_enum_name}"
        )

    # PostgreSQL: restore DEFAULT using the temp enum type
    if dialect == 'postgresql':
        op.execute(
            f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
            f"SET DEFAULT 'none'::{temp_enum_name}"
        )

    # Drop old type (proxyhostalpn), create new type (alpn)
    old_type.drop(bind, checkfirst=False)
    new_type.create(bind, checkfirst=False)

    # PostgreSQL: DROP DEFAULT again before the second ALTER COLUMN TYPE
    if dialect == 'postgresql':
        op.execute(f'ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP DEFAULT')

    # Step 2: change column from temp_alpn → alpn (final)
    # SQLite will create a temp table for this
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=temp_type,
            type_=new_type,
            existing_nullable=False,
            postgresql_using=f"{column_name}::text::{new_type_name}"
        )

    # PostgreSQL: restore DEFAULT using the final new enum type
    if dialect == 'postgresql':
        op.execute(
            f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
            f"SET DEFAULT 'none'::{new_type_name}"
        )

    # Drop temp type
    temp_type.drop(bind, checkfirst=False)


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Before downgrading, replace any h3-only values with the old default
    update_query = (
        temp_table
        .update()
        .where(temp_table.c.alpn.in_(downgrade_from))
        .values(alpn=downgrade_to)
    )
    op.execute(update_query)

    # Create temp type to bridge new→old
    temp_type.create(bind, checkfirst=False)

    # PostgreSQL: DROP DEFAULT before ALTER COLUMN TYPE
    if dialect == 'postgresql':
        op.execute(f'ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP DEFAULT')

    # Step 1: change column from alpn → temp_alpn
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=new_type,
            type_=temp_type,
            existing_nullable=False,
            postgresql_using=f"{column_name}::text::{temp_enum_name}"
        )

    # PostgreSQL: restore DEFAULT with temp enum type
    if dialect == 'postgresql':
        op.execute(
            f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
            f"SET DEFAULT 'none'::{temp_enum_name}"
        )

    # Drop new type (alpn), recreate old type (proxyhostalpn)
    new_type.drop(bind, checkfirst=False)
    old_type.create(bind, checkfirst=False)

    # PostgreSQL: DROP DEFAULT before final ALTER COLUMN TYPE
    if dialect == 'postgresql':
        op.execute(f'ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP DEFAULT')

    # Step 2: change column from temp_alpn → proxyhostalpn (original)
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=temp_type,
            type_=old_type,
            existing_nullable=False,
            postgresql_using=f"{column_name}::text::{old_type_name}"
        )

    # PostgreSQL: restore DEFAULT with old enum type (proxyhostalpn)
    if dialect == 'postgresql':
        op.execute(
            f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
            f"SET DEFAULT 'none'::{old_type_name}"
        )

    # Drop temp type
    temp_type.drop(bind, checkfirst=False)
