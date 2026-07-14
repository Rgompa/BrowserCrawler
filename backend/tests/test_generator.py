import csv
import io
import zipfile

from app.generator import cases_csv, pytest_zip
from app.models import AutomationStep, Project, TestCase as QATestCase, TestStep as QATestStep


def sample_case(status="Ready"):
    return QATestCase(
        id="AUTH-001", title="Valid login", flow="Authentication", type="Positive",
        priority="P0", status=status, preconditions=["Signed out"], evidence=["/login"],
        steps=[
            QATestStep(action="Open login", expected="Form is visible", automation=AutomationStep(kind="navigate", value="/login")),
            QATestStep(action="Submit", expected="Dashboard opens", automation=AutomationStep(kind="click", role="button", name="Sign in")),
        ],
    )


def test_csv_keeps_detailed_steps_in_single_row():
    rows = list(csv.reader(io.StringIO(cases_csv([sample_case()]))))
    assert len(rows) == 2
    assert "1. Open login" in rows[1][7]
    assert "2. Dashboard opens" in rows[1][8]


def test_pytest_zip_only_emits_approved_cases():
    project = Project(name="Portal", base_url="https://example.test")
    content = pytest_zip(project, [sample_case(), sample_case("Needs review")])
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        generated = archive.read("tests/test_authentication.py").decode()
        assert generated.count("def test_") == 1
        assert "get_by_role('button', name='Sign in').click()" in generated
        assert "test-cases.json" in archive.namelist()
