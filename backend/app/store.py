from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Project, TestCase, utc_now


class Store:
    def __init__(self, path: str = "data/atlas.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS test_cases (
                project_id TEXT NOT NULL, case_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (project_id, case_id)
            )""")

    def save_project(self, project: Project) -> Project:
        project.updated_at = utc_now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO projects(id,payload,created_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (project.id, project.model_dump_json(), project.created_at, project.updated_at),
            )
        return project

    def get_project(self, project_id: str) -> Project | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
        return Project.model_validate_json(row["payload"]) if row else None

    def save_cases(self, project_id: str, cases: list[TestCase]) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM test_cases WHERE project_id=?", (project_id,))
            db.executemany(
                "INSERT INTO test_cases(project_id,case_id,payload) VALUES(?,?,?)",
                [(project_id, case.id, case.model_dump_json()) for case in cases],
            )

    def get_cases(self, project_id: str) -> list[TestCase]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM test_cases WHERE project_id=? ORDER BY case_id", (project_id,)).fetchall()
        return [TestCase.model_validate_json(row["payload"]) for row in rows]

    def update_case(self, project_id: str, case_id: str, payload: dict) -> TestCase | None:
        cases = self.get_cases(project_id)
        current = next((case for case in cases if case.id == case_id), None)
        if not current:
            return None
        updated = TestCase.model_validate({**current.model_dump(), **payload})
        with self._connect() as db:
            db.execute(
                "UPDATE test_cases SET payload=? WHERE project_id=? AND case_id=?",
                (updated.model_dump_json(), project_id, case_id),
            )
        return updated
