"""Private service-account configuration and retryable Smallcap Sheet delivery."""
from __future__ import annotations

import json
import os
import re


class SheetConfigError(ValueError):
    """Safe to print: never includes credentials, paths or the Sheet URL."""


def connect(env: str = "STOCKWATCH_SMALLCAP_SHEET_URL"):
    """Validate configuration before scanning; no credentials or URLs are stored in SQLite."""
    url = os.environ.get(env, "").strip()
    if not url:
        raise SheetConfigError(f"Missing {env}; no scan or Sheet write was made.")
    if not re.fullmatch(r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+(?:[/?#].*)?", url):
        raise SheetConfigError(f"{env} must be a Google Sheets link.")
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw and not path:
        raise SheetConfigError("Missing Google service-account key: set GOOGLE_APPLICATION_CREDENTIALS (file path) "
                               "or GOOGLE_SERVICE_ACCOUNT_JSON (key JSON).")
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        credentials = (Credentials.from_service_account_info(json.loads(raw), scopes=scopes) if raw else
                       Credentials.from_service_account_file(path, scopes=scopes))
    except ImportError:
        raise SheetConfigError("Google Sheets dependencies missing; install requirements.txt.") from None
    except Exception:
        raise SheetConfigError("Cannot read the Google service-account key; check the JSON or key file.") from None
    # Remote errors must be sanitized by the CLI (they can contain the private URL).
    client = gspread.authorize(credentials)
    client.set_timeout(60)
    return client.open_by_url(url)


def deliver(sheet, pending: dict, save_pending):
    """Replace Shortlist, then append events at a reserved row, safe to retry after an ambiguous timeout.

    Only this job should write Log. Persist the target row before writing; retries overwrite
    those same cells rather than append duplicates. Headers are written once, even with no events.
    """
    import gspread

    def tab(name, cols):
        try:
            return sheet.worksheet(name)
        except gspread.WorksheetNotFound:
            return sheet.add_worksheet(title=name, rows=1000, cols=cols)

    shortlist, log = tab("Shortlist", 18), tab("Log", 3)
    shortlist.clear()
    shortlist.update(range_name="A1", values=pending["shortlist"], value_input_option="RAW")
    if "log_start" not in pending:
        existing = log.get_all_values()
        pending["log_start"] = len(existing) + 1
        pending["log_write"] = pending["log"] if not existing else pending["log"][1:]
        save_pending(pending)
    rows = pending["log_write"]
    if rows:
        end = pending["log_start"] + len(rows) - 1
        if end > log.row_count:
            log.resize(rows=end)
        log.update(range_name=f"A{pending['log_start']}:C{end}", values=rows, value_input_option="RAW")
