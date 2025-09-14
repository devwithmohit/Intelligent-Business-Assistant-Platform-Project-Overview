from typing import Any, Dict, List, Optional, Union, Literal

from pydantic import BaseModel, Field


class BaseIntegration(BaseModel):
    name: Optional[str] = None
    enabled: bool = True
    # keep unknown provider-specific keys (useful for passthrough configs)
    model_config = {"extra": "allow"}


# Email providers -------------------------------------------------------------
class GmailConfig(BaseIntegration):
    type: Literal["gmail"] = "gmail"
    client_secrets_path: Optional[str] = None
    token_path: Optional[str] = None
    scopes: Optional[List[str]] = None


class OutlookEmailConfig(BaseIntegration):
    type: Literal["outlook"] = "outlook"
    email: str
    username: Optional[str] = None
    password: Optional[str] = None
    server: Optional[str] = None
    autodiscover: bool = True


# Calendar providers ----------------------------------------------------------
class GoogleCalendarConfig(BaseIntegration):
    type: Literal["google_calendar", "google"] = Field("google_calendar", alias="type")
    client_secrets_path: Optional[str] = None
    token_path: Optional[str] = None
    scopes: Optional[List[str]] = None
    calendar_id: Optional[str] = "primary"


class OutlookCalendarConfig(BaseIntegration):
    type: Literal["outlook_calendar", "outlook"] = Field("outlook_calendar", alias="type")
    email: str
    username: Optional[str] = None
    password: Optional[str] = None
    server: Optional[str] = None
    autodiscover: bool = True


# Storage providers -----------------------------------------------------------
class GoogleDriveConfig(BaseIntegration):
    type: Literal["google_drive", "gdrive"] = Field("google_drive", alias="type")
    client_secrets_path: Optional[str] = None
    token_path: Optional[str] = None
    scopes: Optional[List[str]] = None


class OneDriveConfig(BaseIntegration):
    type: Literal["onedrive", "microsoft"] = Field("onedrive", alias="type")
    access_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    drive_id: Optional[str] = None


# CRM providers ---------------------------------------------------------------
class SalesforceConfig(BaseIntegration):
    type: Literal["salesforce", "sf"] = Field("salesforce", alias="type")
    username: Optional[str] = None
    password: Optional[str] = None
    security_token: Optional[str] = None
    domain: Optional[str] = "login"
    session_id: Optional[str] = None
    instance_url: Optional[str] = None
    client_id: Optional[str] = None


class HubspotConfig(BaseIntegration):
    type: Literal["hubspot", "hs"] = Field("hubspot", alias="type")
    api_key: Optional[str] = None
    access_token: Optional[str] = None


# Messaging providers ---------------------------------------------------------
class SlackConfig(BaseIntegration):
    type: Literal["slack"] = "slack"
    token: str
    default_channel: Optional[str] = None


class TeamsConfig(BaseIntegration):
    type: Literal["teams", "msteams"] = Field("teams", alias="type")
    webhook_url: Optional[str] = None
    access_token: Optional[str] = None
    default_team_id: Optional[str] = None
    default_channel_id: Optional[str] = None


# Generic / fallback ----------------------------------------------------------
class GenericIntegration(BaseIntegration):
    type: str = "generic"
    config: Dict[str, Any] = Field(default_factory=dict)


# Union of supported integration schemas (useful for parsing)
IntegrationConfig = Union[
    GmailConfig,
    OutlookEmailConfig,
    GoogleCalendarConfig,
    OutlookCalendarConfig,
    GoogleDriveConfig,
    OneDriveConfig,
    SalesforceConfig,
    HubspotConfig,
    SlackConfig,
    TeamsConfig,
    GenericIntegration,
]


def parse_integration_config(payload: Dict[str, Any]) -> IntegrationConfig:
    """
    Parse a raw integration config dict into one of the typed models above.
    Falls back to GenericIntegration for unknown types.
    """
    t = (payload or {}).get("type", "").lower()
    try:
        if t == "gmail":
            return GmailConfig.model_validate(payload)
        if t in ("outlook", "exchange", "ews"):
            # could be email or calendar; disambiguate by presence of 'email' + mail-related keys
            if "calendar_id" in payload or payload.get("type") == "outlook_calendar":
                return OutlookCalendarConfig.model_validate(payload)
            return OutlookEmailConfig.model_validate(payload)
        if t in ("google", "google_calendar", "calendar"):
            return GoogleCalendarConfig.model_validate(payload)
        if t in ("google_drive", "gdrive"):
            return GoogleDriveConfig.model_validate(payload)
        if t in ("onedrive", "microsoft", "msgraph"):
            return OneDriveConfig.model_validate(payload)
        if t in ("salesforce", "sf"):
            return SalesforceConfig.model_validate(payload)
        if t in ("hubspot", "hs"):
            return HubspotConfig.model_validate(payload)
        if t == "slack":
            return SlackConfig.model_validate(payload)
        if t in ("teams", "msteams"):
            return TeamsConfig.model_validate(payload)
    except Exception:
        # allow fallback to generic if strict parsing fails
        return GenericIntegration.model_validate({"config": payload, "type": t or "generic"})
    return GenericIntegration.model_validate({"config": payload, "type": t or "generic"})
