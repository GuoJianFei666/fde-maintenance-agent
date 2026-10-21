import pytest

from react_agent.evaluation import metrics


def test_nested_entities_and_top_level_projection_have_exact_denominators():
    cases = [{"expected": [
        {"start": 0, "end": 2, "type": "PhysicalObject/Example"},
        {"start": 1, "end": 2, "type": "PhysicalObject/Example"},
        {"start": 2, "end": 3, "type": "State/Failed"},
    ], "predicted": [
        {"start": 1, "end": 2, "type": "PhysicalObject"},
        {"start": 2, "end": 3, "type": "Process"},
    ]}]
    result = metrics(cases)
    assert result["micro"]["tp"] == 1
    assert result["micro"]["fp"] == 1
    assert result["micro"]["fn"] == 2
    assert result["micro"]["f1"] == pytest.approx(0.4)
    assert result["exact_record_count"] == 0


def test_failed_predictions_remain_in_the_recall_denominator():
    result = metrics([{"expected": [{"start": 0, "end": 1, "type": "PhysicalObject"}], "predicted": []}])
    assert result["micro"]["fn"] == 1 and result["micro"]["f1"] == 0
