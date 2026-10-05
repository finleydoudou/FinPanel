"""Run with FINPANEL_SEC_USER_AGENT set to your actual identity and contact."""

import os

from finpanel.sec import parse_companyfacts
from finpanel.sec.client import SECClient

with SECClient(os.environ["FINPANEL_SEC_USER_AGENT"]) as client:
    response = client.companyfacts("0000320193")
result = parse_companyfacts(response)
print(f"{len(result.records)} observations; {len(result.issues)} issues")
print(f"Source SHA-256: {response.sha256}")
