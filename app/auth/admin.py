"""users 表的管理端读写：列表、详情、改角色与启停。"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..db import get_pg
from .store import ROLE_ADMIN, ROLES, user_store

UNAVAILABLE = (psycopg.Error, RuntimeError)

_CONNECT_TIMEOUT = 2.0

ACTION_USER_UPDATE = "user_update"


class UserNotFound(Exception):
    """没有这个 id。"""


class Conflict(Exception):
    """照做会没有可用的管理员。"""


class Rejected(Exception):
    """管理员不能对自己做这件事。"""


_ITEM_COLUMNS = """
    u.id, u.username, u.role, u.is_active, u.created_at,
    coalesce(sum(h.search_count), 0)::bigint AS search_count,
    max(h.last_seen_at) AS last_seen_at
"""

_FROM = """
FROM users u
LEFT JOIN search_history h ON h.user_id = u.id
"""

_FILTER = """
WHERE (%(q)s::text IS NULL OR u.username ILIKE %(q)s)
  AND (%(role)s::text IS NULL OR u.role = %(role)s)
  AND (%(active)s::boolean IS NULL OR u.is_active = %(active)s)
"""

_LIST = f"""
SELECT {_ITEM_COLUMNS}
{_FROM}
{_FILTER}
GROUP BY u.id
ORDER BY u.id
LIMIT %(limit)s OFFSET %(offset)s
"""

_COUNT = f"SELECT count(*) AS n FROM users u {_FILTER}"

_DETAIL = f"""
SELECT {_ITEM_COLUMNS}
{_FROM}
WHERE u.id = %(user_id)s
GROUP BY u.id
"""

# 先锁全部启用中的管理员，再锁目标行。两条并发改管理员时按同一顺序排队。
_LOCK_ADMINS = """
SELECT id FROM users
 WHERE role = %(role)s AND is_active
 ORDER BY id
   FOR UPDATE
"""

_LOCK_USER = "SELECT id, role, is_active FROM users WHERE id = %(user_id)s FOR UPDATE"

_UPDATE = """
UPDATE users
   SET role = %(role)s, is_active = %(active)s, updated_at = now()
 WHERE id = %(user_id)s
"""

_RECORD = """
INSERT INTO admin_actions (actor_id, action, target_id, detail)
VALUES (%(actor_id)s, %(action)s, %(target_id)s, %(detail)s)
"""

_ACTION_FILTER = """
WHERE (%(action)s::text IS NULL OR a.action = %(action)s)
  AND (%(actor_id)s::bigint IS NULL OR a.actor_id = %(actor_id)s)
  AND (%(target_id)s::bigint IS NULL OR a.target_id = %(target_id)s)
"""

_LIST_ACTIONS = f"""
SELECT a.id, a.actor_id, actor.username AS actor_username,
       a.action, a.target_id, target.username AS target_username,
       a.detail, a.created_at
FROM admin_actions a
LEFT JOIN users actor  ON actor.id  = a.actor_id
LEFT JOIN users target ON target.id = a.target_id
{_ACTION_FILTER}
ORDER BY a.id DESC
LIMIT %(limit)s OFFSET %(offset)s
"""

_COUNT_ACTIONS = f"SELECT count(*) AS n FROM admin_actions a {_ACTION_FILTER}"


def _like(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    escaped = (cleaned.replace("\\", "\\\\")
                      .replace("%", "\\%")
                      .replace("_", "\\_"))
    return f"%{escaped}%"


def list_users(*, q: str | None = None, role: str | None = None,
               active: bool | None = None,
               limit: int = 20, offset: int = 0) -> dict[str, Any]:
    params = {
        "q": _like(q),
        "role": role,
        "active": active,
        "limit": limit,
        "offset": offset,
    }
    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_COUNT, params)
            total = int(cur.fetchone()["n"])
            cur.execute(_LIST, params)
            items = cur.fetchall()
    return {"total": total, "items": items}


def get_user(user_id: int) -> dict[str, Any] | None:
    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_DETAIL, {"user_id": user_id})
            return cur.fetchone()


def update_user(actor_id: int, user_id: int, *,
                role: str | None = None,
                active: bool | None = None) -> dict[str, Any]:
    """改角色或启停，返回改完的那一行。锁、校验、写在同一事务里。"""
    if role is not None and role not in ROLES:
        raise ValueError(f"unknown role: {role}")

    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_LOCK_ADMINS, {"role": ROLE_ADMIN})
            admins = {row["id"] for row in cur.fetchall()}

            cur.execute(_LOCK_USER, {"user_id": user_id})
            target = cur.fetchone()
            if target is None:
                raise UserNotFound(user_id)

            new_role = target["role"] if role is None else role
            new_active = target["is_active"] if active is None else active

            if user_id == actor_id:
                if not new_active:
                    raise Rejected("cannot deactivate yourself")
                if new_role != ROLE_ADMIN:
                    raise Rejected("cannot demote yourself")

            was_admin = target["role"] == ROLE_ADMIN and target["is_active"]
            will_admin = new_role == ROLE_ADMIN and new_active
            if was_admin and not will_admin and not admins - {user_id}:
                raise Conflict("at least one active admin is required")

            changes = {}
            if new_role != target["role"]:
                changes["role"] = [target["role"], new_role]
            if new_active != target["is_active"]:
                changes["is_active"] = [target["is_active"], new_active]

            if changes:
                cur.execute(_UPDATE, {
                    "role": new_role,
                    "active": new_active,
                    "user_id": user_id,
                })
                cur.execute(_RECORD, {
                    "actor_id": actor_id,
                    "action": ACTION_USER_UPDATE,
                    "target_id": user_id,
                    "detail": Jsonb({"changes": changes}),
                })

            cur.execute(_DETAIL, {"user_id": user_id})
            row = cur.fetchone()

    user_store.cache_clear()
    return row


def list_actions(*, action: str | None = None,
                 actor_id: int | None = None,
                 target_id: int | None = None,
                 limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """操作记录，新的在前。actor 或 target 已被删时用户名为 null。"""
    params = {
        "action": action,
        "actor_id": actor_id,
        "target_id": target_id,
        "limit": limit,
        "offset": offset,
    }
    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_COUNT_ACTIONS, params)
            total = int(cur.fetchone()["n"])
            cur.execute(_LIST_ACTIONS, params)
            items = cur.fetchall()
    return {"total": total, "items": items}
