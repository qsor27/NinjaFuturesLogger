import pytest
from pydantic import ValidationError

from models.mfe_mae import MfeMaeResult


def test_winner_result_valid():
    r = MfeMaeResult(
        mfe_dollars=450.0,
        mae_dollars=-120.0,
        mfe_time=1700000100,
        mae_time=1700000050,
        mfe_price=100.0,
        mae_price=100.0,
        coverage=1.0,
        capture_efficiency=0.67,
        risk_efficiency=None,
    )
    assert r.capture_efficiency == 0.67
    assert r.risk_efficiency is None


def test_loser_result_valid():
    r = MfeMaeResult(
        mfe_dollars=50.0,
        mae_dollars=-200.0,
        mfe_time=1700000010,
        mae_time=1700000080,
        mfe_price=100.0,
        mae_price=100.0,
        coverage=0.95,
        capture_efficiency=None,
        risk_efficiency=0.2,
    )
    assert r.risk_efficiency == 0.2


def test_scratch_result_valid():
    r = MfeMaeResult(
        mfe_dollars=10.0,
        mae_dollars=-10.0,
        mfe_time=1700000010,
        mae_time=1700000080,
        mfe_price=100.0,
        mae_price=100.0,
        coverage=1.0,
        capture_efficiency=None,
        risk_efficiency=None,
    )
    assert r.capture_efficiency is None and r.risk_efficiency is None


def test_both_efficiencies_set_rejected():
    with pytest.raises(ValidationError):
        MfeMaeResult(
            mfe_dollars=100.0,
            mae_dollars=-10.0,
            mfe_time=1,
            mae_time=2,
            mfe_price=100.0,
            mae_price=100.0,
            coverage=1.0,
            capture_efficiency=0.8,
            risk_efficiency=0.5,
        )


def test_coverage_out_of_range_rejected():
    with pytest.raises(ValidationError):
        MfeMaeResult(
            mfe_dollars=10.0,
            mae_dollars=-10.0,
            mfe_time=1,
            mae_time=2,
            mfe_price=100.0,
            mae_price=100.0,
            coverage=1.5,
            capture_efficiency=None,
            risk_efficiency=None,
        )


def test_efficiency_out_of_range_rejected():
    with pytest.raises(ValidationError):
        MfeMaeResult(
            mfe_dollars=10.0,
            mae_dollars=-10.0,
            mfe_time=1,
            mae_time=2,
            mfe_price=100.0,
            mae_price=100.0,
            coverage=1.0,
            capture_efficiency=1.2,
            risk_efficiency=None,
        )
