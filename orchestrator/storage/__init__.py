"""
orchestrator/storage
======================
Everything durable: sessions, chat messages, and downloadable reports. See
`orchestrator/DESIGN.md` §10 for the schema and why SQLite (via Python's
built-in `sqlite3` -- no ORM) was chosen over a JSON file or in-memory
store.

- `db.py` -- the SQLite connection + all session/message queries.
- `reports.py` -- writes/reads the small JSON report file each completed
  query produces.
"""
