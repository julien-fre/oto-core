"""Microsoft Graph client — an organization's directory, used by a signed-in person
(delegated access, scope `scopes.DIRECTORY`): its users and their licences, its
subscriptions, its groups and their members, its SharePoint sites. It WRITES only three
things: a user's licences, whether an account is enabled, a group's members — never an
account created or deleted, never a password.

## Protocol facts that shape a caller

- ⚠️ **`scopes.DIRECTORY` needs a tenant administrator's consent** (`Directory.Read.All`,
  `AuditLog.Read.All`), and the person's own role still bounds what comes back:
  Graph never returns more than she may read in the admin centre.
- **A licence is a `skuId`** on the user (`assignedLicenses`); its name comes from the
  tenant's subscriptions (`list_subscriptions`: `skuPartNumber`, bought / used units).
  `SKU_NAMES` gives the commercial name of the usual ones.
- **The last sign-in** (`signInActivity`) needs an Entra ID P1 licence on the tenant and
  a reporting role: without them Graph answers 403 for the whole listing —
  `list_users(sign_in=True)` raises it, the caller retries without.
- **A group's kind** is read from three fields: Microsoft 365 group (`groupTypes`
  contains `Unified` — a team, a SharePoint team site, a shared mailbox), security group
  (`securityEnabled`, not mail-enabled), distribution list (`mailEnabled`, not security,
  not Unified), mail-enabled security group (both). A Microsoft 365 group backs a team
  when `resourceProvisioningOptions` contains `Team`.
- **Who can open a SharePoint site** is not all in Graph: a team site's members are its
  Microsoft 365 group's (`list_group_members`), but permissions granted inside
  SharePoint itself (SharePoint groups, sharing links) are not listed here.
- `list_sites` searches the sites the person can see (`search=*`), not every site of
  the tenant.
- **Writing needs a Microsoft role** on top of the consent: License Administrator (or
  User Administrator) for licences, User Administrator for enabling an account (a
  Privileged Authentication Administrator for an administrator's account), Groups
  Administrator or the group's owner for its members. Graph answers 403 otherwise.
- ⚠️ **A licence needs a usage location** on the user (`usageLocation`): without one,
  `assignLicense` answers 400 — it is set in the admin centre.
- ⚠️ **Distribution lists and mail-enabled security groups are Exchange's**: Graph
  refuses to change their members (400); only security and Microsoft 365 groups are
  changed here. A group membership is added by the member's object `id`, not an address.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..common import UpstreamHTTPError
from ._transport import BASE_URL, GraphBase, segment

#: Graph's `$top` ceiling on directory objects.
DIRECTORY_PAGE_SIZE = 999

_USER_FIELDS = ("id", "displayName", "givenName", "surname", "mail", "userPrincipalName",
                "accountEnabled", "userType", "jobTitle", "department", "officeLocation",
                "city", "companyName", "employeeId", "createdDateTime", "assignedLicenses",
                "usageLocation")
_GROUP_FIELDS = ("id", "displayName", "description", "mail", "mailEnabled",
                 "securityEnabled", "groupTypes", "visibility", "createdDateTime",
                 "resourceProvisioningOptions")
_MEMBER_FIELDS = ("id", "displayName", "mail", "userPrincipalName", "accountEnabled")

#: Commercial name of the usual subscriptions (`skuPartNumber` → name). A part number
#: absent from this table is shown as is.
SKU_NAMES: Dict[str, str] = {
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "SPB": "Microsoft 365 Business Premium",
    "O365_BUSINESS": "Microsoft 365 Apps for business",
    "SMB_APPS": "Microsoft 365 Apps for business",
    "OFFICESUBSCRIPTION": "Microsoft 365 Apps for enterprise",
    "STANDARDPACK": "Office 365 E1",
    "ENTERPRISEPACK": "Office 365 E3",
    "ENTERPRISEPREMIUM": "Office 365 E5",
    "SPE_E3": "Microsoft 365 E3",
    "SPE_E5": "Microsoft 365 E5",
    "SPE_F1": "Microsoft 365 F3",
    "DESKLESSPACK": "Office 365 F3",
    "EXCHANGESTANDARD": "Exchange Online (Plan 1)",
    "EXCHANGEENTERPRISE": "Exchange Online (Plan 2)",
    "EXCHANGEDESKLESS": "Exchange Online Kiosk",
    "AAD_PREMIUM": "Microsoft Entra ID P1",
    "AAD_PREMIUM_P2": "Microsoft Entra ID P2",
    "EMS": "Enterprise Mobility + Security E3",
    "INTUNE_A": "Microsoft Intune",
    "POWER_BI_STANDARD": "Power BI (free)",
    "POWER_BI_PRO": "Power BI Pro",
    "FLOW_FREE": "Power Automate (free)",
    "TEAMS_EXPLORATORY": "Microsoft Teams Exploratory",
    "Microsoft_Teams_Exploratory_Dept": "Microsoft Teams Exploratory",
    "VISIOCLIENT": "Visio Plan 2",
    "PROJECTPROFESSIONAL": "Project Plan 3",
}


def group_kind(group: Dict[str, Any]) -> str:
    """`microsoft365` | `security` | `distribution` | `mail_security` — see the
    protocol facts."""
    if "Unified" in (group.get("groupTypes") or []):
        return "microsoft365"
    mail, security = bool(group.get("mailEnabled")), bool(group.get("securityEnabled"))
    if mail and security:
        return "mail_security"
    return "distribution" if mail else "security"


class DirectoryClient(GraphBase):
    """An organization's directory, read on behalf of one person."""

    def _directory(self, path: str, fields, *, limit: int,
                   params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._paged(path, {**(params or {}), "$select": ",".join(fields)},
                           limit=limit, page_size=DIRECTORY_PAGE_SIZE)

    def list_users(self, *, sign_in: bool = False, limit: int = 5000
                   ) -> List[Dict[str, Any]]:
        """GET /users — every account of the directory (members and guests, enabled or
        not), with its `assignedLicenses`. `sign_in=True` adds `signInActivity`
        (`lastSignInDateTime`, `lastNonInteractiveSignInDateTime`) — see the protocol
        facts for its 403."""
        fields = _USER_FIELDS + (("signInActivity",) if sign_in else ())
        return self._directory("/users", fields, limit=limit)

    def get_user(self, user: str) -> Dict[str, Any]:
        """GET /users/{id | userPrincipalName} — one account, with its manager."""
        return self._json("GET", f"/users/{segment(user, 'user')}", params={
            "$select": ",".join(_USER_FIELDS),
            "$expand": "manager($select=id,displayName,mail)"})

    def list_user_groups(self, user: str, *, limit: int = 500) -> List[Dict[str, Any]]:
        """GET /users/{id}/memberOf — the groups the account is a DIRECT member of."""
        return self._directory(f"/users/{segment(user, 'user')}/memberOf/microsoft.graph.group",
                               _GROUP_FIELDS, limit=limit)

    def list_subscriptions(self) -> List[Dict[str, Any]]:
        """GET /subscribedSkus — the tenant's subscriptions: `skuId`, `skuPartNumber`,
        `prepaidUnits.enabled` (bought), `consumedUnits` (assigned), `capabilityStatus`."""
        return (self._json("GET", "/subscribedSkus") or {}).get("value") or []

    def list_groups(self, *, limit: int = 5000) -> List[Dict[str, Any]]:
        """GET /groups — every group of the directory (see `group_kind`)."""
        return self._directory("/groups", _GROUP_FIELDS, limit=limit)

    def get_group(self, group_id: str) -> Dict[str, Any]:
        """GET /groups/{id}."""
        return self._json("GET", f"/groups/{segment(group_id, 'group_id')}",
                          params={"$select": ",".join(_GROUP_FIELDS)})

    def list_group_members(self, group_id: str, *, owners: bool = False,
                           limit: int = 5000) -> List[Dict[str, Any]]:
        """GET /groups/{id}/members (or `/owners`) — DIRECT members (users, nested
        groups, devices: `@odata.type` says which)."""
        rel = "owners" if owners else "members"
        return self._directory(f"/groups/{segment(group_id, 'group_id')}/{rel}",
                               _MEMBER_FIELDS, limit=limit)

    def get_group_site(self, group_id: str) -> Optional[Dict[str, Any]]:
        """GET /groups/{id}/sites/root — the team site of a Microsoft 365 group (`id`,
        `displayName`, `webUrl`); `None` for a group without one (404)."""
        try:
            return self._json("GET", f"/groups/{segment(group_id, 'group_id')}/sites/root")
        except UpstreamHTTPError as e:
            if e.status_code == 404:
                return None
            raise

    def list_sites(self, *, query: str = "*", limit: int = 500) -> List[Dict[str, Any]]:
        """GET /sites?search= — the SharePoint sites the person can see (`*`: all of
        them), `id`, `displayName`, `webUrl`, `createdDateTime`."""
        return self._paged("/sites", {"search": query or "*"}, limit=limit,
                           page_size=None)

    # ── Writes ─────────────────────────────────────────────────────────────────────

    def assign_licenses(self, user: str, *, add: Sequence[str] = (),
                        remove: Sequence[str] = ()) -> Dict[str, Any]:
        """POST /users/{id}/assignLicense — adds the `add` subscriptions (`skuId`, every
        service plan enabled) and removes the `remove` ones, in one call. Returns the
        user as Graph answers it."""
        add, remove = list(add), list(remove)
        if not add and not remove:
            raise ValueError("assign_licenses needs at least one licence to add or remove")
        if set(add) & set(remove):
            raise ValueError("a licence cannot be both added and removed")
        return self._json("POST", f"/users/{segment(user, 'user')}/assignLicense", json={
            "addLicenses": [{"skuId": s, "disabledPlans": []} for s in add],
            "removeLicenses": remove})

    def set_account_enabled(self, user: str, enabled: bool) -> str:
        """PATCH /users/{id} `accountEnabled` — a disabled account can no longer sign in
        (its data, licences and groups stay). Returns the user given."""
        self._json("PATCH", f"/users/{segment(user, 'user')}",
                   json={"accountEnabled": bool(enabled)})
        return user

    def add_group_member(self, group_id: str, member_id: str) -> str:
        """POST /groups/{id}/members/$ref — `member_id` is the member's object id."""
        self._json("POST", f"/groups/{segment(group_id, 'group_id')}/members/$ref",
                   json={"@odata.id": f"{BASE_URL}/directoryObjects/"
                                      f"{segment(member_id, 'member_id')}"})
        return member_id

    def remove_group_member(self, group_id: str, member_id: str) -> str:
        """DELETE /groups/{id}/members/{member}/$ref — the object itself stays."""
        self._json("DELETE", f"/groups/{segment(group_id, 'group_id')}/members/"
                             f"{segment(member_id, 'member_id')}/$ref")
        return member_id
