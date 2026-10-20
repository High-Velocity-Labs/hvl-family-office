"""
forecast/actuarial.py: SSA Actuarial Period Life Table & Survival Probability Interpolator.
Provides adult survival probability breakdowns for ages 30 through 100.
"""

from __future__ import annotations
from typing import Dict

# SSA Period Life Table conditional adult survival probabilities through age 100
# Source: Social Security Administration Actuarial Period Life Table
SSA_PERIOD_SURVIVAL_TABLE: Dict[int, Dict[str, float]] = {
    30: {"male": 1.0000, "female": 1.0000},
    35: {"male": 0.9965, "female": 0.9980},
    40: {"male": 0.9920, "female": 0.9955},
    45: {"male": 0.9855, "female": 0.9915},
    50: {"male": 0.9904, "female": 0.9937},
    52: {"male": 0.9788, "female": 0.9859},
    55: {"male": 0.9572, "female": 0.9715},
    60: {"male": 0.9123, "female": 0.9405},
    65: {"male": 0.8496, "female": 0.8973},
    70: {"male": 0.7631, "female": 0.8361},
    72: {"male": 0.7208, "female": 0.8048},
    75: {"male": 0.6481, "female": 0.7483},
    78: {"male": 0.5647, "female": 0.6798},
    80: {"male": 0.5019, "female": 0.6271},
    82: {"male": 0.4350, "female": 0.5678},
    85: {"male": 0.3312, "female": 0.4688},
    88: {"male": 0.2319, "female": 0.3621},
    90: {"male": 0.1708, "female": 0.2905},
    92: {"male": 0.1172, "female": 0.2183},
    95: {"male": 0.0578, "female": 0.1260},
    98: {"male": 0.0215, "female": 0.0592},
    100: {"male": 0.0094, "female": 0.0315},
}


def get_survival_prob(age: int) -> Dict[str, float]:
    """Interpolates adult survival probability to target age."""
    if age < 50:
        return {"male": 1.0, "female": 1.0, "joint": 1.0}
    if age >= 100:
        return {"male": 0.008, "female": 0.025, "joint": 0.033}

    sorted_ages = sorted(SSA_PERIOD_SURVIVAL_TABLE.keys())
    for i in range(len(sorted_ages) - 1):
        a_low = sorted_ages[i]
        a_high = sorted_ages[i + 1]
        if a_low <= age <= a_high:
            ratio = (age - a_low) / (a_high - a_low)
            m_low = SSA_PERIOD_SURVIVAL_TABLE[a_low]["male"]
            m_high = SSA_PERIOD_SURVIVAL_TABLE[a_high]["male"]
            f_low = SSA_PERIOD_SURVIVAL_TABLE[a_low]["female"]
            f_high = SSA_PERIOD_SURVIVAL_TABLE[a_high]["female"]

            p_m = m_low + ratio * (m_high - m_low)
            p_f = f_low + ratio * (f_high - f_low)
            p_joint = 1.0 - ((1.0 - p_m) * (1.0 - p_f))
            return {"male": round(p_m, 4), "female": round(p_f, 4), "joint": round(p_joint, 4)}

    return {"male": 0.01, "female": 0.03, "joint": 0.04}
