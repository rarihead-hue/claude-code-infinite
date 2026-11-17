# Customs PDFs → Qargo

Watches the customs team's mail, finds the **RXOE** order reference, and attaches every customs PDF
to that order's **Documents** tab in Qargo as **Customs Document**. Anything it can't match safely is
moved to a review folder for a person to handle; it never guesses.

```
eu_customsteam@rxo.com (DL) ──► customs-automation mailbox ──► this service ──► Qargo order (RXOE…) → Documents
                                                                   │
                                                                   └─► "Qargo - Needs Review" folder
```

## How a message is handled

1. Only **PDF** attachments are considered (inline signature images and logos are ignored).
2. The RXOE reference is read from the **email subject and body**: `RXOE123456`, `RXOE 123456`, and
   `rxoe-123456` all work.
   - Exactly one reference: every PDF goes to that order.
   - None or several: each PDF's **filename**, then its **text**, decides which reference it belongs to.
3. The order is looked up in Qargo. If it's found, the PDF is uploaded as `RXOE123456_<original name>.pdf`
   with document type `Customs Document`.
4. Fully uploaded emails move to **Qargo - Uploaded**. Anything else (no reference, ambiguous reference,
   order not found, API error, no PDF) moves to **Qargo - Needs Review**, tagged with a category, and the
   reason is written to `report.csv`.
5. Each upload is recorded in `state.sqlite3`, so re-running never uploads the same file twice.

## One-off setup (IT / M365 admin)

**1. A mailbox to read from.** A distribution list has no mailbox of its own, so nothing can read
"from" it directly. Do one of the following:
- Create a shared mailbox, e.g. `customs-automation@rxo.com`, and **add it as a member of
  `eu_customsteam@rxo.com`**. The team keeps receiving mail as normal and the bot gets its own copy.
  This is the recommended option.
- Or convert the DL to a shared mailbox, if the team is happy to work from a shared mailbox.

**2. Azure AD app registration** (Entra ID → App registrations → New):
- API permission: Microsoft Graph → **Application** → `Mail.ReadWrite`, then grant admin consent.
- Restrict it to the one mailbox with an Exchange **Application Access Policy**, so the app cannot read
  anyone else's mail:
  ```powershell
  New-DistributionGroup -Name "Qargo Customs Bot Scope" -Type Security -Members customs-automation@rxo.com
  New-ApplicationAccessPolicy -AppId <client-id> -PolicyScopeGroupId "Qargo Customs Bot Scope" `
      -AccessRight RestrictAccess -Description "Customs bot: one mailbox only"
  ```
- Create a client secret. Tenant ID, client ID, and secret go in `.env`.

**3. Qargo API credentials**, with permission to read orders and upload documents.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in the values
python -m pytest -q          # offline tests
python -m customs_ingest.main            # DRY RUN: reads mail, matches orders, writes report.csv; uploads/moves nothing
python -m customs_ingest.main --live     # real: uploads and files mail, polls every POLL_SECONDS
```

Leave it in dry-run mode until `report.csv` looks right on a few days of real mail. Then switch to `--live`.

## ⚠️ Before going live: confirm the Qargo calls

The Qargo API docs (api-docs.qargo.com) weren't reachable while this was built, so these parts of
`customs_ingest/qargo_client.py` are educated guesses, each marked `VERIFY`:
- the token endpoint and auth style
- how to search orders by RXOE reference (is it the order number or a customer reference field?)
- the document upload call, whether it links to the order in the same request, and the exact name or ID of the
  **Customs Document** type

Qargo also lists a `POST /v1/webhook/document-import` endpoint for "importing documents and attaching
them to existing orders". If that matches orders by reference on Qargo's side, the order lookup can be dropped.

## Hosting

Any always-on box with Python 3.11+ works. Good options are a small Azure VM, an Azure Container App, or an
Azure Function on a 1-minute timer that runs `--once --live`. Keep `state.sqlite3` and `report.csv` on
persistent storage, and keep the secrets in Key Vault or the platform's secret store, not in the repo.
