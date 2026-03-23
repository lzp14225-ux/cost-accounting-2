"""
Progress stage constants shared by workers and websocket updates.
"""


class ProgressStage:
    """Progress stage names."""

    INITIALIZING = "initializing"

    CAD_SPLIT_STARTED = "cad_split_started"
    CAD_SPLIT_COMPLETED = "cad_split_completed"
    CAD_SPLIT_FAILED = "cad_split_failed"

    FEATURE_RECOGNITION_STARTED = "feature_recognition_started"
    FEATURE_RECOGNITION_COMPLETED = "feature_recognition_completed"
    FEATURE_RECOGNITION_FAILED = "feature_recognition_failed"

    WAITING_FOR_CONFIRMATION = "awaiting_confirm"

    NC_CALCULATION_STARTED = "nc_calculation_started"
    NC_CALCULATION_COMPLETED = "nc_calculation_completed"
    NC_CALCULATION_FAILED = "nc_calculation_failed"
    DECISION_FAILED = "decision_failed"

    PRICING_STARTED = "pricing_started"
    PRICING_COMPLETED = "pricing_completed"
    PRICING_FAILED = "pricing_failed"

    COMPLETED = "completed"
    FAILED = "failed"


class ProgressPercent:
    """Progress percentage milestones."""

    INITIALIZING = 0

    CAD_SPLIT_STARTED = 5
    CAD_SPLIT_COMPLETED = 20

    FEATURE_RECOGNITION_STARTED = 25
    FEATURE_RECOGNITION_COMPLETED = 50

    NC_CALCULATION_STARTED = 55
    NC_CALCULATION_COMPLETED = 70

    PRICING_STARTED = 75
    PRICING_COMPLETED = 90

    COMPLETED = 100
