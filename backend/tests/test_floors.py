"""The retrieval Floors: checking a harness report against them, and recording them."""

import json

import pytest

from edgar_eval.floors import DEFAULT_FLOORS, check, main, record


def report(hit=0.88, recall=0.82, mrr=0.73, *, cases=17, version=1, chunk_tokens=600):
    return {
        "split": "dev",
        "golden_set_version": version,
        "chunk_tokens": chunk_tokens,
        "context_budget": 32000,
        "arms": {
            "dense": {"name": "dense", "shipped": False, "overall": {}},
            "fts5": {
                "name": "fts5",
                "shipped": True,
                "overall": {
                    "cases": cases,
                    "hit": {"5": 0.5, "10": hit, "20": 1.0},
                    "recall": {"5": 0.5, "10": recall, "20": 1.0},
                    "mrr": mrr,
                },
            },
        },
    }


FLOORS = record(report(hit=0.8823529, recall=0.8235294, mrr=0.7345938))


def test_floors_are_the_shipped_arms_scores_rounded_down():
    assert FLOORS["arm"] == "fts5"
    assert FLOORS["floors"] == {"hit@10": 0.88, "recall@10": 0.82, "mrr": 0.73}


def test_a_report_at_its_floors_passes():
    assert check(report(), FLOORS) == []


def test_a_metric_below_its_floor_fails_and_is_named():
    failures = check(report(hit=0.8235), FLOORS)
    assert len(failures) == 1
    assert failures[0].startswith("hit@10 0.824 is below its Floor 0.88")


@pytest.mark.parametrize(
    ("changed", "key"),
    [
        (report(version=2), "golden_set_version"),
        (report(cases=18), "cases"),
        (report(chunk_tokens=450), "chunk_tokens"),
    ],
)
def test_a_report_at_other_settings_is_stale_whatever_its_scores(changed, key):
    failures = check(changed, FLOORS)
    assert failures[0].startswith("Floors stale")
    assert any(failure.startswith(f"{key}:") for failure in failures[1:])


def test_the_cli_exits_nonzero_on_a_failure(tmp_path, capsys):
    floors = tmp_path / "floors.json"
    floors.write_text(json.dumps(FLOORS))
    passing, failing = tmp_path / "pass.json", tmp_path / "fail.json"
    passing.write_text(json.dumps(report()))
    failing.write_text(json.dumps(report(mrr=0.5)))
    assert main(["check", str(passing), "--floors", str(floors)]) == 0
    assert main(["check", str(failing), "--floors", str(floors)]) == 1
    assert "FAIL mrr 0.500 is below its Floor 0.73" in capsys.readouterr().out


def test_the_cli_records_floors(tmp_path):
    source, floors = tmp_path / "report.json", tmp_path / "floors.json"
    source.write_text(json.dumps(report()))
    assert main(["record", str(source), "--floors", str(floors)]) == 0
    assert json.loads(floors.read_text()) == record(report())


def test_the_committed_floors_record_every_setting():
    committed = json.loads(DEFAULT_FLOORS.read_text())
    assert set(committed) == set(FLOORS)
    assert set(committed["floors"]) == set(FLOORS["floors"])
