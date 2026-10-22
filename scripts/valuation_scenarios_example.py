"""Export the hand-checkable SYNTHETIC worked example. Never fetches market/SEC data.

Fixture numbers and citations are deliberately fictitious. They cannot value MSFT/MU/JPM.
The same evidence packet schema is used for real observations with verified sources.
The fixture lives in `stockwatch.research_lab`, which the dashboard's Research view also shows.
"""
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stockwatch import valuation_scenarios as vs
from stockwatch.research_lab import synthetic_valuation


def example():
    return synthetic_valuation()


if __name__ == '__main__':
    config, report = example()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/valuation-synthetic')
    out.with_suffix('.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    out.with_suffix('.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    out.with_suffix('.md').write_text(vs.markdown([report]))
    print(json.dumps({'status': report['status'], 'values': {
        k: v['equity_per_share'] for k, v in report['scenarios'].items()}}))
