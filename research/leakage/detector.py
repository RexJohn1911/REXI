"""Lookahead bias and temporal leakage verification engine."""

from collections.abc import Sequence
from typing import Any

from research.leakage.types import (
    LabelInformationInterval,
    LeakageAuditReport,
    PurgeEmbargoConfig,
    SplitDefinition,
    TimeInterval,
)


class LookaheadDetector:
    """Verifiable causal leakage and boundary compliance auditor."""

    @classmethod
    def audit_point_in_time(
        cls,
        decision_timestamps: Sequence[int],
        available_timestamps: Sequence[int | None],
        event_timestamps: Sequence[int | None] | None = None,
    ) -> LeakageAuditReport:
        """Audit point-in-time causality constraints for a decision stream.

        Verifies:
        1. T_available <= T_decision (Lookahead prevention)
        2. T_event <= T_available (Physical causality, if event_timestamps provided)
        """
        violations: list[str] = []
        n = len(decision_timestamps)

        for i in range(n):
            t_dec = decision_timestamps[i]
            t_av = available_timestamps[i]

            if t_av is not None:
                # 1. Availability check
                if t_av > t_dec:
                    violations.append(
                        f"Sample {i}: Lookahead violation: "
                        f"available_ts ({t_av}) > decision_ts ({t_dec})"
                    )

                # 2. Event consistency check
                if event_timestamps is not None:
                    t_ev = event_timestamps[i]
                    if t_ev is not None and t_ev > t_av:
                        violations.append(
                            f"Sample {i}: Causal order violation: "
                            f"event_ts ({t_ev}) > available_ts ({t_av})"
                        )

        return LeakageAuditReport(
            is_valid=len(violations) == 0,
            violation_count=len(violations),
            violations=tuple(violations),
            audited_sample_count=n,
            metadata={"audit_type": "point_in_time_availability"},
        )

    @classmethod
    def audit_split_compliance(
        cls,
        split_def: SplitDefinition,
        timestamps: Sequence[int],
        label_intervals: Sequence[LabelInformationInterval],
        purge_config: PurgeEmbargoConfig,
    ) -> LeakageAuditReport:
        """Audit an evaluation split for boundary, purging, and embargo compliance.

        Verifies:
        1. Train and Test index sets are strictly disjoint.
        2. No retained training sample has a label horizon touching the test partition.
        3. No post-test training sample falls within the embargo buffer.
        """
        violations: list[str] = []
        train_part = split_def.train_partition
        test_part = split_def.test_partition

        train_indices = set(train_part.record_indices or ())
        test_indices = set(test_part.record_indices or ())

        # 1. Disjoint index check
        overlap_indices = train_indices.intersection(test_indices)
        if overlap_indices:
            violations.append(
                f"Split {split_def.split_index}: {len(overlap_indices)} samples present in "
                f"both Train and Test partitions (e.g. index {next(iter(overlap_indices))})"
            )

        # Duplicate index checks
        raw_train_indices = train_part.record_indices or ()
        if len(raw_train_indices) != len(train_indices):
            violations.append(
                f"Split {split_def.split_index}: Train partition contains duplicate record indices."
            )

        raw_test_indices = test_part.record_indices or ()
        if len(raw_test_indices) != len(test_indices):
            violations.append(
                f"Split {split_def.split_index}: Test partition contains duplicate record indices."
            )

        # Discrete test intervals (supports CPCV with non-contiguous test blocks)
        if "test_intervals" in split_def.metadata:
            test_intervals = [
                TimeInterval.from_dict(d) for d in split_def.metadata["test_intervals"]
            ]
        else:
            test_intervals = [test_part.time_boundary]

        # 2. Purging check: verify training labels do not touch ANY test interval
        for idx in train_indices:
            lbl = label_intervals[idx]
            t_obs = timestamps[idx]

            for t_interval in test_intervals:
                if lbl.touches_partition(t_interval):
                    violations.append(
                        f"Split {split_def.split_index}: Training sample {idx} "
                        f"(obs={lbl.observation_timestamp_ns}, "
                        f"label_end={lbl.label_end_timestamp_ns}) "
                        f"touches test partition {t_interval.to_dict()} without being purged."
                    )

                # 3. Embargo check: applies to samples post-test relative to this test interval
                if purge_config.embargo_ns > 0 and t_obs >= t_interval.end_timestamp_ns:
                    embargo_end_ns = t_interval.end_timestamp_ns + purge_config.embargo_ns
                    if t_obs < embargo_end_ns:
                        violations.append(
                            f"Split {split_def.split_index}: Post-test sample {idx} (ts={t_obs}) "
                            f"falls inside embargo window [{t_interval.end_timestamp_ns}, "
                            f"{embargo_end_ns}) without being embargoed."
                        )

        # 4. Validation partition check if present
        if split_def.val_partition is not None:
            val_part = split_def.val_partition
            val_indices = set(val_part.record_indices or ())

            train_val_overlap = train_indices.intersection(val_indices)
            if train_val_overlap:
                violations.append(
                    f"Split {split_def.split_index}: {len(train_val_overlap)} "
                    "samples present in both Train and Val."
                )

            val_test_overlap = val_indices.intersection(test_indices)
            if val_test_overlap:
                violations.append(
                    f"Split {split_def.split_index}: {len(val_test_overlap)} "
                    "samples present in both Val and Test."
                )

            val_interval = val_part.time_boundary
            for idx in train_indices:
                lbl = label_intervals[idx]
                if lbl.touches_partition(val_interval):
                    violations.append(
                        f"Split {split_def.split_index}: Training sample {idx} touches "
                        f"validation partition {val_interval.to_dict()} without being purged."
                    )

        return LeakageAuditReport(
            is_valid=len(violations) == 0,
            violation_count=len(violations),
            violations=tuple(violations),
            audited_sample_count=len(train_indices) + len(test_indices),
            metadata={"split_index": split_def.split_index},
        )

    @staticmethod
    def compute_feature_target_correlation_heuristic(
        features: Sequence[float],
        future_targets: Sequence[float],
    ) -> dict[str, Any]:
        """Compute exploratory diagnostic correlation between a feature and future target.

        NOTE: This is strictly an exploratory heuristic, NEVER proof of leakage.
        Predictive features naturally exhibit non-zero correlation with future returns.
        """
        n = min(len(features), len(future_targets))
        if n < 2:
            return {"correlation": 0.0, "is_diagnostic_flag": False, "note": "Insufficient samples"}

        mean_f = sum(features[:n]) / n
        mean_t = sum(future_targets[:n]) / n

        num = sum((features[i] - mean_f) * (future_targets[i] - mean_t) for i in range(n))
        den_f = sum((features[i] - mean_f) ** 2 for i in range(n))
        den_t = sum((future_targets[i] - mean_t) ** 2 for i in range(n))

        if den_f == 0.0 or den_t == 0.0:
            corr = 0.0
        else:
            corr = num / ((den_f * den_t) ** 0.5)

        # Flag if correlation is near-perfect, suggesting possible label target copied into feature
        is_suspicious = abs(corr) > 0.999

        return {
            "correlation": corr,
            "is_suspicious_near_identity": is_suspicious,
            "note": (
                "Exploratory heuristic only; correlation does not constitute proof of leakage."
            ),
        }
