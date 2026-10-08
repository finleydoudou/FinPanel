"""Preserve each taxonomy/concept/unit observation, including duplicates."""

from datetime import date
from decimal import Decimal

from finpanel.models import FactObservation, ParseResult, RawResponse
from finpanel.sec.common import Reader, normalize_cik, pointer


def parse_companyfacts(response: RawResponse) -> ParseResult[FactObservation]:
    from finpanel._reuse import memo

    return memo(
        "companyfacts_parse",
        (response.url, response.sha256, response.retrieved_at),
        lambda: _parse_companyfacts(response),
    )


def _parse_companyfacts(response: RawResponse) -> ParseResult[FactObservation]:
    data = response.json()
    cik = normalize_cik(data.get("cik"))
    reader = Reader(response)
    name = reader.optional(data, "entityName", str, "")
    records = []

    def mapping(value, path):
        if not isinstance(value, dict):
            reader.issue(path, value, "Expected object", "invalid_container")
            return {}
        return value

    for taxonomy, concepts in sorted(mapping(data.get("facts"), "/facts").items()):
        tax_path = pointer("facts", taxonomy)
        for concept, details in sorted(mapping(concepts, tax_path).items()):
            path = pointer("facts", taxonomy, concept)
            details = mapping(details, path)
            label = reader.optional(details, "label", str, path)
            description = reader.optional(details, "description", str, path)
            for unit, observations in sorted(
                mapping(details.get("units"), path + "/units").items()
            ):
                unit_path = path + pointer("units", unit)
                if not isinstance(observations, list):
                    reader.issue(
                        unit_path, observations, "Expected observation array", "invalid_container"
                    )
                    continue
                for i, row in enumerate(observations):
                    obs_path = unit_path + f"/{i}"
                    if not isinstance(row, dict):
                        reader.issue(obs_path, row, "Expected observation object", "invalid_record")
                        continue
                    value = row.get("val")
                    if type(value) not in (int, Decimal) or (
                        isinstance(value, Decimal) and not value.is_finite()
                    ):
                        reader.issue(
                            obs_path, row, "val must be a finite JSON number", "invalid_record"
                        )
                        continue
                    start = reader.optional(row, "start", date, obs_path)
                    end = reader.optional(row, "end", date, obs_path)
                    if start is not None and end is not None and start > end:
                        reader.issue(obs_path, row, "Period start is after end", "ambiguous_period")
                    records.append(
                        FactObservation(
                            cik=cik,
                            entity_name=name,
                            taxonomy=taxonomy,
                            concept=concept,
                            label=label,
                            description=description,
                            unit=unit,
                            value=value,
                            accession_number=reader.optional(row, "accn", str, obs_path),
                            form=reader.optional(row, "form", str, obs_path),
                            filing_date=reader.optional(row, "filed", date, obs_path),
                            report_date=reader.optional(row, "reportDate", date, obs_path),
                            fiscal_year=reader.optional(row, "fy", int, obs_path),
                            fiscal_period=reader.optional(row, "fp", str, obs_path),
                            period_start=start,
                            period_end=end,
                            frame=reader.optional(row, "frame", str, obs_path),
                            provenance=response.provenance(obs_path),
                            raw=row,
                        )
                    )
    return ParseResult(tuple(records), tuple(reader.issues), response.provenance(""))
