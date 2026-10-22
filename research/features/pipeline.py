"""Pipeline connecting Phase 08 Data Lake, Microstructure Feature Engine,
and Phase 09 Safeguards.
"""

from collections.abc import Sequence

import pyarrow as pa

from research.datasets.reader import DatasetReader
from research.features.engine import MicrostructureFeatureEngine
from research.features.types import FeatureEngineConfig
from research.leakage.detector import LookaheadDetector
from research.leakage.point_in_time import PointInTimeAligner
from research.leakage.types import LeakageAuditReport


class MicrostructureFeaturePipeline:
    """End-to-end microstructure feature extraction, audit, and causal alignment pipeline."""

    def __init__(self, instrument_id: int, config: FeatureEngineConfig | None = None) -> None:
        self.instrument_id = instrument_id
        self.config = config or FeatureEngineConfig()
        self.engine = MicrostructureFeatureEngine(instrument_id, self.config)

    def extract_from_table(self, table: pa.Table, event_type: str = "auto") -> pa.Table:
        """Extract microstructure features directly from an in-memory PyArrow table."""
        return self.engine.extract_from_table(table, event_type=event_type)

    def extract_from_dataset(
        self,
        reader: DatasetReader,
        event_type: str = "auto",
        filter_partitions: dict[str, str] | None = None,
    ) -> pa.Table:
        """Stream and extract microstructure features from a Phase 08 partitioned dataset."""
        table = reader.read_table(filter_partitions=filter_partitions)
        return self.extract_from_table(table, event_type=event_type)

    def extract_and_audit(
        self,
        table: pa.Table,
        event_type: str = "auto",
    ) -> tuple[pa.Table, LeakageAuditReport]:
        """Extract features and verify zero point-in-time leakage via Phase 09 LookaheadDetector."""
        feat_table = self.extract_from_table(table, event_type=event_type)
        if len(feat_table) == 0:
            return feat_table, LeakageAuditReport(
                is_valid=True,
                violation_count=0,
                violations=(),
                audited_sample_count=0,
                metadata={"audit_type": "point_in_time_availability"},
            )

        dec_ts = feat_table["decision_timestamp_ns"].to_pylist()
        ev_ts = feat_table["event_timestamp_ns"].to_pylist()

        # In the engine, feature availability timestamp is decision_timestamp_ns
        audit_report = LookaheadDetector.audit_point_in_time(
            decision_timestamps=dec_ts,
            available_timestamps=dec_ts,
            event_timestamps=ev_ts,
        )
        return feat_table, audit_report

    def align_features_to_decisions(
        self,
        features_table: pa.Table,
        decision_timestamps: Sequence[int],
        max_staleness_ns: int | None = None,
    ) -> pa.Table:
        """Perform causal as-of alignment matching decision timestamps to past available features.

        Guarantees:
        1. T_available <= T_decision for every joined record.
        2. T_event <= T_available (physical causality).
        3. Zero forward leakage.
        """
        aligner = PointInTimeAligner(max_staleness_ns=max_staleness_ns)
        return aligner.align_as_of(
            decision_timestamps=decision_timestamps,
            features_table=features_table,
            event_ts_col="event_timestamp_ns",
            available_ts_col="decision_timestamp_ns",
        )
