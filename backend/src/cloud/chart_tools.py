"""A pure formatting tool for the phone's bounded native chart contract."""
import json
import math
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator


class ChartSeries(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    values: list[float] = Field(min_length=1, max_length=24)

    @field_validator('values', mode='before')
    @classmethod
    def numeric_values(cls, values):
        if not isinstance(values, list) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                not math.isfinite(v) or abs(v) > 1e12 for v in values):
            raise ValueError('Chart values must be finite numeric values with magnitude at most 1e12.')
        return values


def chart_tools():
    @tool
    def render_chart(chart_type: Literal['bar', 'line', 'pie'], title: str,
                     labels: list[str], series: list[ChartSeries], unit: str = '') -> str:
        """Validate and format a native bar, line or pie chart from verified tool/user data.
        Use AFTER retrieving the relevant source. Copy the returned markdown into the final
        reply exactly. This tool does not fetch records or make up missing values. Convert
        app-usage milliseconds to seconds/minutes exactly, not rounded text. Use one numeric
        value per label in every series. Max 24 labels/3 series; pie requires 1 series and
        at most 12 nonnegative categories with a positive total. Aggregate remaining actual
        categories if needed; preserve their total. Cite/describe the data source outside
        the chart, and distinguish unknown data from zero. No HTML or executable code.
        """
        error = None
        if not title.strip() or len(title) > 120 or len(unit) > 32:
            error = 'Use a nonempty title up to 120 characters and a unit up to 32 characters.'
        elif not 1 <= len(labels) <= 24 or any(not label.strip() or len(label) > 80 for label in labels):
            error = 'Choose 1 to 24 nonempty labels, each at most 80 characters.'
        elif not 1 <= len(series) <= 3 or any(len(row.values) != len(labels) for row in series):
            error = 'Choose 1 to 3 series with exactly one value per label.'
        elif chart_type == 'pie' and (len(series) != 1 or len(labels) > 12 or
                any(value < 0 for value in series[0].values) or sum(series[0].values) <= 0):
            error = 'A pie needs one nonnegative series, at most 12 labels and a positive total.'
        if error:
            return json.dumps({'status': 'invalid_arguments', 'message': error})
        chart = {'type': chart_type, 'title': title.strip(), 'unit': unit,
                 'labels': labels, 'series': [row.model_dump() for row in series]}
        return json.dumps({'status': 'ok', 'chart': chart,
            'markdown': '```chart\n' + json.dumps(chart, ensure_ascii=False) + '\n```'}, ensure_ascii=False)

    return [render_chart]
