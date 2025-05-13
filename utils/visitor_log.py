# utils/visitor_log.py
import sqlite3, uuid
from datetime import datetime
from flask import g, request

DB_PATH        = "visitors.sqlite"
VISITOR_COOKIE = "vuid"           # rename if you wish


def init_visitor_logging(app):
    """Call from create_app(); sets up SQLite + request hooks."""

    # ── helper: 1 connection per request ──────────────────────────────────
    def get_db():
        if "vlog_db" not in g:
            g.vlog_db = sqlite3.connect(DB_PATH,
                                        detect_types=sqlite3.PARSE_DECLTYPES)
            g.vlog_db.row_factory = sqlite3.Row
        return g.vlog_db

    @app.teardown_appcontext
    def close_db(exc):
        db = g.pop("vlog_db", None)
        if db:
            db.close()

    # ── create / migrate the table once ───────────────────────────────────
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS page_hits (
                id          INTEGER PRIMARY KEY,
                ts          TIMESTAMP,
                ip          TEXT,
                method      TEXT,
                path        TEXT,
                query       TEXT,
                referrer    TEXT,
                user_agent  TEXT,
                headers     TEXT,
                visitor     TEXT                 -- new column
            )
        """)
        # lightweight migration if the file pre-dated “visitor”
        cols = {row[1] for row in db.execute("PRAGMA table_info(page_hits)")}
        if "visitor" not in cols:
            db.execute("ALTER TABLE page_hits ADD COLUMN visitor TEXT;")

    # ── cookie helper ─────────────────────────────────────────────────────
    def _get_or_set_vuid(resp=None):
        vuid = request.cookies.get(VISITOR_COOKIE)
        if not vuid:                       # first visit from that browser
            vuid = uuid.uuid4().hex
            if resp is not None:           # add cookie to outgoing response
                resp.set_cookie(
                    VISITOR_COOKIE, vuid,
                    max_age=60*60*24*365,  # 1 year
                    samesite="Lax", secure=True, httponly=True
                )
        return vuid

    # ── write a row for every request ─────────────────────────────────────
    @app.before_request
    def log_visitor():
        db   = get_db()
        vuid = _get_or_set_vuid()          # read / create cookie
        db.execute(
            """INSERT INTO page_hits
               (visitor, ts, ip, method, path, query, referrer, user_agent, headers)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                vuid,
                datetime.utcnow(),
                request.remote_addr,
                request.method,
                request.path,
                request.query_string.decode(),
                request.referrer,
                request.headers.get("User-Agent", ""),
                str(dict(request.headers)),
            ),
        )
        db.commit()

    # ── make sure the cookie is actually delivered ───────────────────────
    @app.after_request
    def ensure_cookie(resp):
        _get_or_set_vuid(resp)
        return resp
