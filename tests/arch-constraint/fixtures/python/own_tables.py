"""Fixture: SQL к СВОИМ таблицам — НЕ нарушение (#28).

`tickets`/`ticket_history`/`ticket_messages` принадлежат kb-support, поэтому
прямые запросы к ним легитимны и НЕ должны триггерить AT-001 (в т.ч. lowercase).
"""

from sqlalchemy import text


def queries(session):
    session.execute(text("select * from tickets where status = 'OPEN'"))
    session.execute(text("SELECT * FROM ticket_history WHERE ticket_id = :id"))
    session.execute(text("update ticket_messages set is_internal = false where id = :id"))
