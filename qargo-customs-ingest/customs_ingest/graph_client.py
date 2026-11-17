"""Minimal Microsoft Graph client: read mail + attachments from one mailbox and file the processed messages."""
import base64
from dataclasses import dataclass

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class Attachment:
    id: str
    name: str
    content_type: str | None
    data: bytes


@dataclass
class Message:
    id: str
    subject: str
    body_text: str
    sender: str
    received: str
    attachments: list[Attachment]


class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, mailbox: str):
        self.mailbox = mailbox
        token = httpx.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=30,
        )
        token.raise_for_status()
        self.http = httpx.Client(
            base_url=f"{GRAPH}/users/{mailbox}",
            headers={"Authorization": f"Bearer {token.json()['access_token']}", "Prefer": 'outlook.body-content-type="text"'},
            timeout=60,
        )
        self._folder_ids: dict[str, str] = {}

    def folder_id(self, name: str) -> str:
        """Well-known names (Inbox) work directly; custom folders are looked up and created if missing."""
        if name.lower() == "inbox":
            return "inbox"
        if name not in self._folder_ids:
            r = self.http.get("/mailFolders", params={"$filter": f"displayName eq '{name}'"})
            r.raise_for_status()
            found = r.json()["value"]
            if found:
                self._folder_ids[name] = found[0]["id"]
            else:
                r = self.http.post("/mailFolders", json={"displayName": name})
                r.raise_for_status()
                self._folder_ids[name] = r.json()["id"]
        return self._folder_ids[name]

    def messages_with_attachments(self, folder: str, limit: int = 25) -> list[Message]:
        r = self.http.get(
            f"/mailFolders/{self.folder_id(folder)}/messages",
            params={
                "$filter": "hasAttachments eq true",
                "$select": "id,subject,body,from,receivedDateTime",
                "$orderby": "receivedDateTime asc",
                "$top": str(limit),
            },
        )
        r.raise_for_status()
        out = []
        for m in r.json()["value"]:
            out.append(
                Message(
                    id=m["id"],
                    subject=m.get("subject") or "",
                    body_text=(m.get("body") or {}).get("content") or "",
                    sender=((m.get("from") or {}).get("emailAddress") or {}).get("address", ""),
                    received=m.get("receivedDateTime", ""),
                    attachments=self._attachments(m["id"]),
                )
            )
        return out

    def _attachments(self, message_id: str) -> list[Attachment]:
        r = self.http.get(f"/messages/{message_id}/attachments")
        r.raise_for_status()
        atts = []
        for a in r.json()["value"]:
            if a.get("@odata.type") != "#microsoft.graph.fileAttachment" or a.get("isInline"):
                continue  # skip embedded signatures/logos and attached emails
            atts.append(Attachment(a["id"], a.get("name") or "attachment", a.get("contentType"), base64.b64decode(a["contentBytes"])))
        return atts

    def move(self, message_id: str, folder: str) -> None:
        r = self.http.post(f"/messages/{message_id}/move", json={"destinationId": self.folder_id(folder)})
        r.raise_for_status()

    def add_category(self, message_id: str, category: str) -> None:
        r = self.http.patch(f"/messages/{message_id}", json={"categories": [category]})
        r.raise_for_status()
