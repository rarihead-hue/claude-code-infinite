"""Qargo API client.

!!! VERIFY AGAINST https://api-docs.qargo.com BEFORE GOING LIVE !!!
The endpoint paths, query parameters and field names below are best guesses: the Qargo docs could not
be reached while this was written. Everything Qargo-specific lives in this file, so once you have the
docs and credentials only this file should need changing. Run with DRY_RUN=true until it is verified.

Endpoints referenced in Qargo's public docs index (details unconfirmed):
  POST /v1/documents/document/upload_content      upload a file
  POST /v1/webhook/document-import                import documents and attach them to existing orders
  GET  /v1/orders/order/{order_id}/documents      list an order's documents
"""
import httpx


class QargoError(RuntimeError):
    pass


class QargoClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        # VERIFY: token endpoint and auth style (assumed OAuth2 client-credentials with HTTP basic auth).
        r = httpx.post(f"{self.base_url}/v1/auth/token", auth=(client_id, client_secret),
                       data={"grant_type": "client_credentials"}, timeout=30)
        if r.status_code >= 400:
            raise QargoError(f"Qargo auth failed ({r.status_code}): {r.text[:300]}")
        self.http = httpx.Client(base_url=self.base_url, timeout=60,
                                 headers={"Authorization": f"Bearer {r.json()['access_token']}"})

    def find_order_id(self, reference: str) -> str | None:
        """Return the Qargo order id whose reference is `reference` (e.g. RXOE123456), or None.

        VERIFY: path, the filter parameter, and which order field holds the RXOE number
        (order number vs customer reference).
        """
        r = self.http.get("/v1/orders/order", params={"reference": reference})
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise QargoError(f"Order lookup failed ({r.status_code}): {r.text[:300]}")
        body = r.json()
        items = body.get("items", body) if isinstance(body, dict) else body
        matches = [o for o in items if reference.upper() in {str(v).upper() for v in o.values() if isinstance(v, str)}]
        if len(matches) > 1:
            raise QargoError(f"{reference} matches {len(matches)} orders")
        return str(matches[0]["id"]) if matches else None

    def upload_document(self, order_id: str, filename: str, data: bytes, document_type: str) -> None:
        """Attach a PDF to the order's Documents tab with the given document type.

        VERIFY: whether this is one call or two (upload_content, then link to the order),
        and the exact name/ID of the 'Customs Document' type.
        """
        r = self.http.post(
            "/v1/documents/document/upload_content",
            files={"file": (filename, data, "application/pdf")},
            data={"order_id": order_id, "document_type": document_type, "name": filename},
        )
        if r.status_code >= 400:
            raise QargoError(f"Upload failed ({r.status_code}): {r.text[:300]}")
